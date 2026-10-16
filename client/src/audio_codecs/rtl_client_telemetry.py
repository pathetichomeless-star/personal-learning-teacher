"""R-1f 客户端 TTS 播测窗口遥测（A.12；默认关闭）.

规范要点（rev-9）：
- 窗口 = 一次客户端 TTS 会话（server `tts` start/stop 对），不是 Qwen 生成。
- 窗口起点：该会话 `tts start` 之后的第一次 TTS FIFO push。
- 窗口终点（FIRST-of）：T1 clear / T2-A 停止时 FIFO 已空 / T2-B 停止后首次
  同实例排空边沿 / T3 FIFO 重建 / T4 被新会话取代。
- T2 停止快照与 T2-B 终点快照为 lock-held 原子读（PcmFifo.snapshot_locked）。
- 计数器按 FIFO 实例单调；跨实例的 delta 一律拒绝（CLIENT_TELEMETRY_INVALID）。
- `AudioCodec.__del__` 是紧急销毁路径：窗口仍活跃 => CLIENT_TELEMETRY_INVALID = 1，
  且析构期不做任何 I/O（仅置内存标志）。
- 回调线程内不做任何 I/O：本模块的导出只发生在事件循环侧。
"""

import asyncio
import json
import os
import threading
import time

ENABLED = os.environ.get("RTL_CLIENT_TELEMETRY", "0") == "1"
TELEMETRY_FILE = os.environ.get(
    "RTL_CLIENT_TELEMETRY_FILE", "/tmp/rtl-client-telemetry.jsonl")

# ---- Q1 (inbound Opus queue) process-global counters ----------------------
# Updated by ProtocolTransport; cheap integer writes only (no I/O).
Q1 = {"current": 0, "peak": 0, "dropped": 0}


def q1_note_enqueue(depth_after):
    Q1["current"] = depth_after
    if depth_after > Q1["peak"]:
        Q1["peak"] = depth_after


def q1_note_dequeue(depth_after):
    Q1["current"] = depth_after


def q1_note_drop():
    Q1["dropped"] += 1


# delta-able monotone counters (window scoped)
_DELTA_KEYS = (
    "partial_underfill_events", "partial_zero_pad_samples",
    "drained_to_empty_events", "dropped", "peak_samples",
    "whole_block_zero_fill_count", "callback_error_count",
    "portaudio_output_underflow_count", "portaudio_output_overflow_count",
    "decode_errors", "toc_null_count", "decoded_short_frame_count",
    "incoming_queue_dropped_packets", "incoming_queue_peak",
)
_RAW_KEYS = (
    "output_callback_interval_min", "output_callback_interval_max",
    "output_callback_interval_p95", "incoming_queue_current", "size",
    "clear_audio_queue_samples_at_stop",
)

# ---- emergency destruction (rev-9 mi-5) -----------------------------------
# __del__ must not perform I/O, so it only sets an in-memory flag; the flag is
# flushed into the telemetry file by the next event-loop-side write (or read
# by the run collector via `summary()`).
_DEL_STATE = {"invalidated": False, "reason": None, "session": None}


def del_invalidated():
    return dict(_DEL_STATE)


def _deltas(start, end):
    out = {}
    for k in _DELTA_KEYS:
        a = (start or {}).get(k)
        b = (end or {}).get(k)
        if isinstance(a, int) and isinstance(b, int):
            out[k] = b - a
    return out


class PlayoutWindowTracker:
    """One instance per AudioCodec; export accumulates in the JSONL file."""

    def __init__(self, pipeline_snapshot=None):
        self._pipeline_snapshot = pipeline_snapshot or (lambda: {})
        self._tlock = threading.Lock()
        self._session_seq = 0
        self._pending_start = False
        self.window = None
        self.invalid = False
        self.invalid_reason = None
        self.closed_windows = []
        self._poll_task = None

    # ---- snapshot helpers -------------------------------------------------

    def _fifo_snap(self, fifo, locked):
        if fifo is None:
            return {}
        snap = fifo.snapshot_locked() if locked else fifo.snapshot()
        return snap

    def _combined(self, fifo, locked=False, extra=None):
        snap = self._fifo_snap(fifo, locked)
        snap.update({
            "whole_block_zero_fill_count": None,
        })
        snap.update(self._pipeline_snapshot() or {})
        snap["incoming_queue_dropped_packets"] = Q1["dropped"]
        snap["incoming_queue_peak"] = Q1["peak"]
        snap["incoming_queue_current"] = Q1["current"]
        if extra:
            snap.update(extra)
        return snap

    # ---- window lifecycle -------------------------------------------------

    def on_tts_start(self):
        """T4 check runs FIRST: a new session may supersede an open window."""
        if not ENABLED:
            return
        with self._tlock:
            self._session_seq += 1
            w = self.window
            if w is not None:
                fifo = w.get("fifo")
                drained = (fifo is None or fifo.size == 0
                           or w.get("cleared"))
                if drained:
                    self._close_locked("T4",
                                       self._combined(fifo, locked=False))
                else:
                    self._invalidate_locked("T4_overlap_queued_audio")
            self._pending_start = True

    def on_push(self, fifo):
        """First TTS-FIFO push at/after the tts start opens the window."""
        if not ENABLED:
            return
        with self._tlock:
            if self._pending_start and self.window is None:
                self.window = {
                    "fifo": fifo,
                    "session": self._session_seq,
                    "start_fifo_instance_id": fifo.instance_id,
                    "start": self._combined(fifo, locked=False),
                    "state": "open",
                    "cleared": False,
                    "t2_stop": None,
                }
                self._pending_start = False

    def on_tts_stop(self, fifo):
        """Rev-9 two-branch T2 rule with a lock-held stop snapshot."""
        if not ENABLED:
            return {"status": "disabled"}
        with self._tlock:
            w = self.window
            if w is None:
                return {"status": "no_window"}
            if fifo is None or fifo is not w.get("fifo"):
                self._invalidate_locked("stop_fifo_mismatch")
                return {"status": "invalid"}
            snap = fifo.snapshot_locked()
            if snap["size"] == 0:
                # T2-A: record the stop evidence (discriminator) and close now.
                w["t2_stop"] = {
                    "instance_id": snap["instance_id"],
                    "size_at_stop": snap["size"],
                    "drained_edge_baseline": None,
                }
                end = dict(snap)
                end.update(self._pipeline_snapshot() or {})
                end["incoming_queue_dropped_packets"] = Q1["dropped"]
                end["incoming_queue_peak"] = Q1["peak"]
                end["incoming_queue_current"] = Q1["current"]
                self._close_locked("T2_EMPTY_AT_STOP", end)
                return {"status": "T2_EMPTY_AT_STOP"}
            w["state"] = "t2b"
            w["t2_stop"] = {
                "instance_id": snap["instance_id"],
                "size_at_stop": snap["size"],
                "drained_edge_baseline": snap["drained_to_empty_events"],
            }
            self._ensure_poll()
            return {"status": "T2_DRAIN_AFTER_STOP_pending"}

    def poll_tick(self):
        """Event-loop-side check for the T2-B terminal edge."""
        if not ENABLED:
            return False
        with self._tlock:
            w = self.window
            if w is None or w.get("state") != "t2b":
                return False
            fifo = w.get("fifo")
            stop = w.get("t2_stop") or {}
            if fifo is None:
                self._invalidate_locked("t2b_fifo_gone")
                return False
            if fifo.instance_id != stop.get("instance_id"):
                self._invalidate_locked("t2b_fifo_instance_changed")
                return False
            snap = fifo.snapshot_locked()
            if (snap["size"] == 0
                    and snap["drained_to_empty_events"]
                    > stop.get("drained_edge_baseline", 0)):
                end = dict(snap)
                end.update(self._pipeline_snapshot() or {})
                end["incoming_queue_dropped_packets"] = Q1["dropped"]
                end["incoming_queue_peak"] = Q1["peak"]
                end["incoming_queue_current"] = Q1["current"]
                self._close_locked("T2_DRAIN_AFTER_STOP", end)
                return False
            return True

    def on_clear(self, fifo=None, samples=0):
        """T1: MUST be called BEFORE the FIFO clear takes effect."""
        if not ENABLED:
            return
        with self._tlock:
            w = self.window
            if w is None:
                return
            if fifo is not None and w.get("fifo") is not fifo:
                return
            w["cleared"] = True
            end = self._combined(w.get("fifo"), locked=False,
                                 extra={"clear_audio_queue_samples_at_stop":
                                        samples})
            self._close_locked("T1", end)

    def on_rebuild(self, old_fifo=None):
        """T3: snapshot OLD counters -> end window -> then rebuild."""
        if not ENABLED:
            return
        with self._tlock:
            w = self.window
            if w is None:
                return
            if old_fifo is not None and w.get("fifo") is not old_fifo:
                return
            self._close_locked("T3",
                               self._combined(w.get("fifo"), locked=False))

    def on_del(self):
        """Emergency destruction: active window -> INVALID (no I/O here)."""
        if not ENABLED:
            return
        with self._tlock:
            if self.window is not None:
                self.invalid = True
                self.invalid_reason = "del_during_active_window"
                rec = {
                    "event": "client_telemetry_invalid",
                    "reason": "del_during_active_window",
                    "session_ordinal": self.window.get("session"),
                    "ts": time.time(),
                    "client_telemetry_invalid": 1,
                }
                self.closed_windows.append(rec)
                _DEL_STATE["invalidated"] = True
                _DEL_STATE["reason"] = "del_during_active_window"
                _DEL_STATE["session"] = self.window.get("session")
                self.window = None
                self._stop_poll()

    # ---- internals --------------------------------------------------------

    def _close_locked(self, label, end):
        w = self.window
        self.window = None
        self._stop_poll()
        if w is None:
            return
        stop = w.get("t2_stop") or {}
        rec = {
            "event": "playout_window_closed",
            "terminal_event": label,
            "session_ordinal": w.get("session"),
            "start_fifo_instance_id": w.get("start_fifo_instance_id"),
            "end_fifo_instance_id": (end or {}).get("instance_id"),
            "t2_stop_fifo_instance_id": stop.get("instance_id"),
            "t2_stop_fifo_size_at_stop": stop.get("size_at_stop"),
            "t2_stop_drained_edge_baseline": stop.get("drained_edge_baseline"),
            "start": w.get("start"),
            "end": end,
            "deltas": _deltas(w.get("start"), end),
            "ts": time.time(),
        }
        ok = (rec["start_fifo_instance_id"] is not None
              and rec["start_fifo_instance_id"] == rec["end_fifo_instance_id"])
        if label.startswith("T2") and stop:
            ok = ok and stop.get("instance_id") == rec["end_fifo_instance_id"]
        rec["valid"] = bool(ok)
        if not ok:
            self.invalid = True
            self.invalid_reason = "cross_instance_delta"
            rec["client_telemetry_invalid"] = 1
        rec["tts_playout_whole_block_zero_fill_count"] = rec["deltas"].get(
            "whole_block_zero_fill_count")
        rec["tts_playout_partial_zero_pad_samples"] = rec["deltas"].get(
            "partial_zero_pad_samples")
        # normative A.14 client-telemetry names (raw + scoped)
        rec["pcm_fifo_instance_id"] = rec["end_fifo_instance_id"]
        rec["playout_window.start_fifo_instance_id"] = rec["start_fifo_instance_id"]
        rec["playout_window.end_fifo_instance_id"] = rec["end_fifo_instance_id"]
        rec["playout_window.terminal_event"] = label
        rec["pcm_fifo_partial_underfill_events"] = rec["deltas"].get(
            "partial_underfill_events")
        rec["pcm_fifo_partial_zero_pad_samples"] = rec["deltas"].get(
            "partial_zero_pad_samples")
        rec["pcm_fifo_drained_to_empty_events"] = rec["deltas"].get(
            "drained_to_empty_events")
        rec["pcm_fifo_dropped_samples"] = rec["deltas"].get("dropped")
        rec["pcm_fifo_peak_samples"] = rec["deltas"].get("peak_samples")
        rec["incoming_queue_dropped_packets"] = rec["deltas"].get(
            "incoming_queue_dropped_packets")
        self.closed_windows.append(rec)
        self._export(rec)

    def _invalidate_locked(self, reason):
        self.invalid = True
        self.invalid_reason = reason
        w = self.window
        self.window = None
        self._stop_poll()
        rec = {
            "event": "client_telemetry_invalid",
            "reason": reason,
            "session_ordinal": w.get("session") if w else None,
            "ts": time.time(),
            "client_telemetry_invalid": 1,
        }
        self.closed_windows.append(rec)
        self._export(rec)

    def _export(self, rec):
        """Event-loop-side file write (never called from the audio callback
        and never from __del__)."""
        try:
            with open(TELEMETRY_FILE, "a", encoding="utf-8") as f:
                # flush a pending emergency-destruction marker first (mi-5)
                if _DEL_STATE["invalidated"]:
                    f.write(json.dumps({
                        "event": "client_telemetry_invalid",
                        "reason": _DEL_STATE["reason"],
                        "session_ordinal": _DEL_STATE["session"],
                        "del_marker_flushed_later": True,
                        "client_telemetry_invalid": 1,
                        "ts": time.time(),
                    }, ensure_ascii=False) + "\n")
                    _DEL_STATE["invalidated"] = False
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _ensure_poll(self):
        if self._poll_task is not None and not self._poll_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        try:
            self._poll_task = loop.create_task(self._poll_loop())
        except Exception:
            self._poll_task = None

    async def _poll_loop(self):
        try:
            while True:
                await asyncio.sleep(0.02)
                if not self.poll_tick():
                    return
        except asyncio.CancelledError:
            raise

    def _stop_poll(self):
        task = self._poll_task
        self._poll_task = None
        if task is not None and not task.done():
            task.cancel()

    # ---- summary ----------------------------------------------------------

    def summary(self):
        return {
            "enabled": ENABLED,
            "client_telemetry_invalid": 1 if self.invalid else 0,
            "invalid_reason": self.invalid_reason,
            "del_invalidated": del_invalidated(),
            "windows": list(self.closed_windows),
            "q1": dict(Q1),
        }