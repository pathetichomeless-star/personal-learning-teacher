"""R-1f rev-9 deterministic client-half tests (groups T-Z).

Runs on the macOS py-xiaozhi interpreter (numpy required):

    RTL_CLIENT_TELEMETRY=1 RTL_CLIENT_TELEMETRY_FILE=/tmp/r1f_client_tel.jsonl \
      py-xiaozhi/.venv/bin/python3 rtl-lab/tests/r1f_client_tests.py

Covers: T FIFO 200/480, U CL-2/CL-3/CL-4, V T2-A, W T2-B, X T2-B+T4 race,
Y cross-instance, Z __del__ active/closed windows.
"""

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENT_ROOT = os.environ.get("R1F_CLIENT_ROOT",
                             os.path.join(os.path.dirname(ROOT), "py-xiaozhi"))
if CLIENT_ROOT not in sys.path:
    sys.path.insert(0, CLIENT_ROOT)

os.environ.setdefault("RTL_CLIENT_TELEMETRY", "1")
os.environ.setdefault("RTL_CLIENT_TELEMETRY_FILE",
                      "/tmp/r1f_client_tests_%d.jsonl" % os.getpid())

import numpy as np                                        # noqa: E402
from src.audio_codecs.audio_buffer import PcmFifo        # noqa: E402
from src.audio_codecs import rtl_client_telemetry as T   # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        (" - " + str(detail)) if detail else ""))
    return bool(cond)


def mktracker(pipe=None):
    return T.PlayoutWindowTracker(pipe or (lambda: {}))


def open_window(tr, fifo, prefill=0):
    tr.on_tts_start()
    if prefill:
        fifo.push(np.ones(prefill, dtype=np.float32))
    tr.on_push(fifo)
    return tr


def test_T_fifo_200_480():
    f = PcmFifo(100000)
    f.push(np.ones(200, dtype=np.float32))
    out = f.pull(480)
    check("T1 CL-1 returned block length == 480", len(out) == 480, len(out))
    check("T2 CL-1 partial_underfill_events == +1",
          f.pcm_fifo_partial_underfill_events == 1)
    check("T3 CL-1 partial_zero_pad_samples == +280",
          f.pcm_fifo_partial_zero_pad_samples == 280)
    check("T4 CL-1 drained_to_empty_events == +1 (exactly once)",
          f.pcm_fifo_drained_to_empty_events == 1)
    return True


def test_U_fifo_edges():
    # CL-2: empty pull -> None, no counter moves (incl. no drained edge)
    g = PcmFifo(100000)
    r = g.pull(480)
    check("U1 CL-2 empty pull returns None", r is None)
    check("U2 CL-2 no counters move",
          g.pcm_fifo_partial_underfill_events == 0
          and g.pcm_fifo_partial_zero_pad_samples == 0
          and g.pcm_fifo_drained_to_empty_events == 0)
    # CL-3: starvation inside a session with zero Q1/Q2 drops
    before_q1 = dict(T.Q1)
    tr = mktracker()
    f = PcmFifo(100000)
    open_window(tr, f, prefill=200)
    f.pull(480)
    res = tr.on_tts_stop(f)          # stop processed after the drained edge
    w = tr.closed_windows[-1]
    check("U3 CL-3 stop after edge -> T2_EMPTY_AT_STOP",
          res["status"] == "T2_EMPTY_AT_STOP", res)
    check("U4 CL-3 drop gates are 0 while starvation is 280",
          (w["deltas"]["incoming_queue_dropped_packets"] == 0
           and w["deltas"]["dropped"] == 0
           and w["tts_playout_partial_zero_pad_samples"] == 280),
          w["deltas"])
    T.Q1.update(before_q1)
    # CL-4: partial-with-leftover pull
    h = PcmFifo(100000)
    h.push(np.ones(700, dtype=np.float32))
    h.pull(480)
    check("U5 CL-4 first pull: no edge, no partial counters",
          h.pcm_fifo_drained_to_empty_events == 0
          and h.pcm_fifo_partial_underfill_events == 0)
    h.pull(480)
    check("U6 CL-4 second pull: +1/+260 and exactly one edge",
          (h.pcm_fifo_partial_underfill_events,
           h.pcm_fifo_partial_zero_pad_samples,
           h.pcm_fifo_drained_to_empty_events) == (1, 260, 1),
          (h.pcm_fifo_partial_underfill_events,
           h.pcm_fifo_partial_zero_pad_samples,
           h.pcm_fifo_drained_to_empty_events))
    return True


def test_V_t2a_empty_at_stop():
    tr = mktracker()
    f = PcmFifo(100000)
    open_window(tr, f, prefill=0)
    f.push(np.ones(100, dtype=np.float32))
    f.pull(480)                       # drains to empty before the stop
    res = tr.on_tts_stop(f)
    w = tr.closed_windows[-1]
    check("V1 T2-A closes immediately as T2_EMPTY_AT_STOP",
          res["status"] == "T2_EMPTY_AT_STOP", res)
    check("V2 T2-A window valid + instance ids match",
          w["valid"] and w["start_fifo_instance_id"] == w["end_fifo_instance_id"])
    check("V3 T2-A records the stop evidence (size 0, no T2-B baseline)",
          w["t2_stop_drained_edge_baseline"] is None
          and w["t2_stop_fifo_size_at_stop"] == 0
          and w["t2_stop_fifo_instance_id"] == w["end_fifo_instance_id"], w)
    # later session push/pull must not alter the already-closed window
    frozen = dict(w)
    tr.on_tts_start()
    f.push(np.ones(300, dtype=np.float32))
    f.pull(480)
    same = next((x for x in tr.closed_windows
                 if x.get("terminal_event") == "T2_EMPTY_AT_STOP"), None)
    check("V4 closed window untouched by later sessions",
          same is not None and same == frozen
          and len([x for x in tr.closed_windows
                   if x.get("terminal_event") == "T2_EMPTY_AT_STOP"]) == 1,
          (same == frozen, len(tr.closed_windows)))
    return True


def test_W_t2b_drain_after_stop():
    tr = mktracker()
    f = PcmFifo(100000)
    open_window(tr, f, prefill=200)
    res = tr.on_tts_stop(f)           # stop precedes the drained edge
    check("W1 T2-B stays open", res["status"] == "T2_DRAIN_AFTER_STOP_pending",
          res)
    f.pull(480)
    still_open = tr.poll_tick()
    w = tr.closed_windows[-1]
    check("W2 T2-B closes on the same-instance drained edge",
          still_open is False
          and w["terminal_event"] == "T2_DRAIN_AFTER_STOP", w["terminal_event"])
    check("W3 end snapshot includes the draining pull's +280 (I3 after I2)",
          w["deltas"]["partial_zero_pad_samples"] == 280
          and w["deltas"]["partial_underfill_events"] == 1
          and w["deltas"]["drained_to_empty_events"] == 1, w["deltas"])
    check("W4 end instance == stop instance", w["valid"]
          and w["end_fifo_instance_id"] == w["t2_stop_fifo_instance_id"])
    return True


def test_X_t2b_t4_race():
    # X1: old session drained (cleared) before the new start -> clean T4 close
    tr = mktracker()
    f = PcmFifo(100000)
    open_window(tr, f, prefill=200)
    tr.on_tts_stop(f)                 # T2-B pending
    f.clear()                         # out-of-band drain/clear, no edge
    tr.on_tts_start()
    w = tr.closed_windows[-1]
    check("X1 drained old window -> clean T4 close",
          w["terminal_event"] == "T4" and not tr.invalid, w["terminal_event"])
    # X2: queued audio remains -> INVALID
    tr2 = mktracker()
    g = PcmFifo(100000)
    open_window(tr2, g, prefill=500)
    tr2.on_tts_stop(g)
    tr2.on_tts_start()
    check("X2 queued audio remains -> CLIENT_TELEMETRY_INVALID",
          tr2.invalid and tr2.invalid_reason == "T4_overlap_queued_audio",
          (tr2.invalid, tr2.invalid_reason))
    # X3: later session's drain edge must not close the old T2-B window
    tr3 = mktracker()
    h = PcmFifo(100000)
    open_window(tr3, h, prefill=200)
    tr3.on_tts_stop(h)                # T2-B pending on instance h
    h2 = PcmFifo(100000)
    h2.push(np.ones(200, dtype=np.float32))
    h2.pull(480)
    tr3.poll_tick()                   # window still on h; h2 edge ignored
    check("X3 later-session edge does not close the old window",
          tr3.window is not None
          and tr3.window.get("state") == "t2b", tr3.window)
    h.pull(480)
    tr3.poll_tick()
    check("X4 old window closes only on its own instance edge",
          tr3.closed_windows[-1]["terminal_event"] == "T2_DRAIN_AFTER_STOP")
    return True


def test_Y_cross_instance():
    # Y1: T3 rebuild with snapshot-old -> end-window (proper terminal)
    tr = mktracker()
    f = PcmFifo(100000)
    open_window(tr, f, prefill=100)
    tr.on_rebuild(f)
    w = tr.closed_windows[-1]
    check("Y1 T3 terminal closes with the OLD instance id",
          w["terminal_event"] == "T3"
          and w["end_fifo_instance_id"] == f.instance_id
          and w["valid"], w)
    # Y2: unrecorded instance change while T2-B pending -> INVALID
    tr2 = mktracker()
    g = PcmFifo(100000)
    open_window(tr2, g, prefill=200)
    tr2.on_tts_stop(g)
    g2 = PcmFifo(100000)
    tr2.window["fifo"] = g2
    tr2.poll_tick()
    check("Y2 cross-instance change during T2-B -> CLIENT_TELEMETRY_INVALID",
          tr2.invalid and tr2.invalid_reason == "t2b_fifo_instance_changed",
          (tr2.invalid, tr2.invalid_reason))
    # Y3: negative scoped delta impossible (per-instance monotone)
    check("Y3 per-instance counters are monotone (no negative deltas)",
          all(v >= 0 for v in [g.pcm_fifo_partial_zero_pad_samples,
                               g.pcm_fifo_drained_to_empty_events,
                               g.pcm_fifo_partial_underfill_events]))
    # Y4: T1 clear closes with pre-clear snapshot
    tr3 = mktracker()
    h = PcmFifo(100000)
    open_window(tr3, h, prefill=150)
    tr3.on_clear(h, samples=h.size)
    h.clear()
    w3 = tr3.closed_windows[-1]
    check("Y4 T1 label + clear sample count recorded",
          w3["terminal_event"] == "T1"
          and w3["end"].get("clear_audio_queue_samples_at_stop") == 150, w3)
    return True


def test_Z_del_windows():
    # Z1: __del__ while a window is active -> INVALID
    tr = mktracker()
    f = PcmFifo(100000)
    open_window(tr, f, prefill=100)
    tr.on_del()
    check("Z1 __del__ during active window -> CLIENT_TELEMETRY_INVALID",
          tr.invalid and tr.invalid_reason == "del_during_active_window",
          (tr.invalid, tr.invalid_reason))
    check("Z1b invalid record carries client_telemetry_invalid = 1",
          tr.closed_windows[-1].get("client_telemetry_invalid") == 1)
    check("Z1c in-memory del flag is readable by the collector",
          T.del_invalidated()["invalidated"] is True)
    # Z2: __del__ after the window closed -> no effect on the completed window
    tr2 = mktracker()
    g = PcmFifo(100000)
    open_window(tr2, g, prefill=200)
    g.pull(480)
    tr2.on_tts_stop(g)
    before = list(tr2.closed_windows)
    tr2.on_del()
    check("Z2 __del__ after close: prior result unchanged",
          tr2.closed_windows == before and not tr2.invalid,
          (len(before), len(tr2.closed_windows), tr2.invalid))
    # Z3: no destructor-time I/O — no new record appended by __del__
    check("Z3 no new record appended by __del__ after close",
          len(tr2.closed_windows) == len(before))
    # Z4: the emergency marker reaches the telemetry FILE on the next
    #     event-loop-side write (mi-5 observability without I/O in __del__)
    f2 = PcmFifo(100000)
    open_window(tr, f2, prefill=50)
    tr.on_clear(f2, samples=50)
    lines = []
    try:
        with open(T.TELEMETRY_FILE, encoding="utf-8") as fh:
            lines = [json.loads(x) for x in fh if x.strip()]
    except Exception as e:  # noqa: BLE001
        check("Z4 telemetry file readable", False, repr(e))
    marks = [r for r in lines
             if r.get("reason") == "del_during_active_window"
             and r.get("del_marker_flushed_later")]
    check("Z4 __del__ marker exported later (no destructor I/O)", bool(marks),
          marks[-1] if marks else None)
    return True


def _bare_codec(out_factory):
    """AudioCodec instance without __init__/audio devices (callback unit test)."""
    from src.audio_codecs.audio_codec import AudioCodec

    class _Conv:
        def __init__(self):
            self.out = out_factory()

        def convert_output(self, audio, frames):
            return self.out

        def drain_output_buffer(self, frames):
            return None

    c = AudioCodec.__new__(AudioCodec)
    c._rtl = {
        "whole_block_zero_fill_count": 0, "callback_error_count": 0,
        "portaudio_output_underflow_count": 0, "portaudio_output_overflow_count": 0,
        "decode_errors": 0, "toc_null_count": 0, "decoded_short_frame_count": 0,
        "clear_audio_queue_samples_at_stop": 0,
    }
    c._cb_last_t = None
    c._cb_min = None
    c._cb_max = None
    c._cb_intervals = []
    c._last_output_status_log = 0.0
    c._aec = None
    c._loop = None
    c._mix_chunk = 480
    c.converter = _Conv()
    return c


def test_Z4_zero_fill_semantics():
    frames = 480
    outdata = np.zeros((frames, 2), dtype=np.float32)
    # (a) all-empty path -> counts
    c = _bare_codec(lambda: None)
    c._pull_mixed = lambda n: None
    c._output_callback(outdata, frames, None, None)
    check("Z5 all-empty callback counts whole_block_zero_fill_count",
          c._rtl["whole_block_zero_fill_count"] == 1)
    # (b) resampler-residue short return -> must NOT count
    c2 = _bare_codec(lambda: np.zeros((100, 2), dtype=np.float32))
    c2._pull_mixed = lambda n: np.zeros(n, dtype=np.float32)
    c2._output_callback(outdata, frames, None, None)
    check("Z6 resampler short-return feeds no counter (A.12)",
          c2._rtl["whole_block_zero_fill_count"] == 0,
          c2._rtl["whole_block_zero_fill_count"])
    # (c) full block -> no counter, no error
    c3 = _bare_codec(lambda: np.zeros((frames, 2), dtype=np.float32))
    c3._pull_mixed = lambda n: np.zeros(n, dtype=np.float32)
    c3._output_callback(outdata, frames, None, None)
    check("Z7 full block: no zero-fill, no callback error",
          c3._rtl["whole_block_zero_fill_count"] == 0
          and c3._rtl["callback_error_count"] == 0)
    # (d) PortAudio status classified, not throttled away
    c4 = _bare_codec(lambda: None)
    c4._pull_mixed = lambda n: None
    c4._output_callback(outdata, frames, None, "output underflow")
    check("Z8 underflow status counted",
          c4._rtl["portaudio_output_underflow_count"] == 1)
    return True


def test_Z9_record_naming():
    tr = mktracker()
    f = PcmFifo(100000)
    open_window(tr, f, prefill=150)
    tr.on_clear(f, samples=150)
    w = tr.closed_windows[-1]
    check("Z9a normative client telemetry names present",
          w.get("pcm_fifo_instance_id") == f.instance_id
          and w.get("playout_window.terminal_event") == "T1"
          and w.get("tts_playout_partial_zero_pad_samples") == 0)
    check("Z9b clear sample count is raw evidence, not a delta key",
          w["end"].get("clear_audio_queue_samples_at_stop") == 150
          and "clear_audio_queue_samples_at_stop" not in w["deltas"])
    return True


TESTS = [
    ("T", test_T_fifo_200_480),
    ("U", test_U_fifo_edges),
    ("V", test_V_t2a_empty_at_stop),
    ("W", test_W_t2b_drain_after_stop),
    ("X", test_X_t2b_t4_race),
    ("Y", test_Y_cross_instance),
    ("Z", test_Z_del_windows),
    ("Z", test_Z4_zero_fill_semantics),
    ("Z", test_Z9_record_naming),
]


def main(argv):
    if not T.ENABLED:
        print("FATAL: RTL_CLIENT_TELEMETRY must be 1 for the client suite")
        return 2
    wanted = set(argv[1:])
    t0 = time.time()
    for group, fn in TESTS:
        if wanted and group not in wanted:
            continue
        print("---- %s %s ----" % (group, fn.__name__))
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            check("%s %s EXCEPTION" % (group, fn.__name__), False, repr(e))
    fails = [r for r in RESULTS if not r[1]]
    print("=" * 70)
    print("R1F_CLIENT_TESTS: %d checks, %d PASS, %d FAIL, %.1fs"
          % (len(RESULTS), len(RESULTS) - len(fails), len(fails), time.time() - t0))
    for name, _, detail in fails:
        print("  - %s %s" % (name, detail))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))