"""Per-connection turn engine: XiaoZhi client <-> Qwen realtime session.

R-1f rev-9 implementation of `rtl-lab/r1f-design-review.md` Part A.

Uplink   : client Opus (16 kHz) -> decode -> Qwen `input_audio_buffer.append`.
Downlink : Qwen PCM24k deltas -> 20 ms framing -> Opus -> single deque store
           -> deadline-driven pacer -> websocket `send_bytes`.

Locked constants (A.5): MEDIA_FRAME_MS=20.0, MIN_SEND_START_INTERVAL_MS=15.0,
PACING_SLACK_MS=5.0. The absolute media deadline is authoritative; the 15 ms
floor is only an anti-burst guard.
"""

import asyncio
import base64
import itertools
import json
import logging
import math
import time
from collections import deque
from enum import Enum

from . import audio, diag, protocol
from .behavior import BehaviorLink
from .counters import counters
from .qwen import QwenClient

log = logging.getLogger("rtl.turns")

UPLINK_QUEUE_MAX = 512

# ---- A.5 / A.6 / A.11 LOCKED constants ------------------------------------
MEDIA_FRAME_MS = 20.0
MIN_SEND_START_INTERVAL_MS = 15.0
PACING_SLACK_MS = 5.0
SLOW_SEND_THRESHOLD_MS = 5.0
MAX_REBASE_LATENESS_MS = 250.0
LATE_REBASE_THRESHOLD_MS = 40.0
SPACING_EPSILON_MS = 0.001
MAX_FUTURE_FRAMES = 1500
MAX_FUTURE_AUDIO_BYTES = 524288

_REASON_KEY = {
    "BARGEIN": "bargein", "ABORT": "abort", "CLOSE": "close",
    "LISTEN_START": "listen_start", "UPSTREAM_CLOSED": "upstream_closed",
    "PACER_STALL": "pacer_stall", "BYTE_CAP_FAILURE": "byte_cap_failure",
    "SEND_ERROR": "send_error",
}

_CONN_SEQ = itertools.count(1)
_PACER_SEQ = itertools.count(1)
_GEN_SEQ = itertools.count(1)      # generation ids: unique process-wide


def _now_ms():
    return time.monotonic() * 1000.0


class State(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    SPEAKING = "SPEAKING"


def _resp_id(obj):
    """Unified response id: top-level `response_id` or `response.id`."""
    rid = obj.get("response_id")
    if rid is None:
        resp = obj.get("response")
        if isinstance(resp, dict):
            rid = resp.get("id")
    return rid


def _transcript_args(obj):
    """Map the four transcript events to `diag.on_transcript()` args (R-1c).

    Purely additive: it never alters turn control flow.
    """
    t = obj.get("type")
    if t == "conversation.item.input_audio_transcription.delta":
        delta_text = obj.get("delta")
        if delta_text is None:
            # ASR-UI-01: text + stash = the COMPLETE current preview (cumulative
            # confirmed prefix + revisable suffix).  The UI forwarder emits it
            # with replace semantics; this mapping only extracts the preview.
            delta_text = (obj.get("text") or "") + (obj.get("stash") or "")
        return ("input", delta_text, None, None, False)
    if t == "conversation.item.input_audio_transcription.completed":
        return ("input", None, None, obj.get("transcript"), True)
    if t == "response.audio_transcript.delta":
        return ("output", obj.get("delta"), _resp_id(obj), None, False)
    if t == "response.audio_transcript.done":
        return ("output", None, _resp_id(obj), obj.get("transcript"), True)
    return None


class GenerationEnd:
    """Non-audio marker in the single store (A.9). Never counted as a frame."""

    __slots__ = ("gen_id", "reason")

    def __init__(self, gen_id, reason):
        self.gen_id = gen_id
        self.reason = reason


class FrameMeta:
    """Per-frame bookkeeping for a packet in the store.

    Deliberately holds NO encoded packet: the single-store invariant (A.3) is
    that only `future_audio_store` directly holds encoded frames.
    """

    __slots__ = ("gen", "gen_obj", "resp_id", "seq", "kind", "t_qwen", "t_enc",
                 "t_enq", "t_send", "pacer_id", "intent")

    def __init__(self, gen, gen_obj, resp_id, seq, t_qwen):
        self.gen = gen                 # int generation id (diag domain)
        self.gen_obj = gen_obj         # Generation object (ownership)
        self.resp_id = resp_id
        self.seq = seq
        self.kind = "audio"
        self.t_qwen = t_qwen
        self.t_enc = diag.now()
        self.t_enq = None
        self.t_send = None
        self.pacer_id = None
        self.intent = None


class Generation:
    """One upstream Qwen response (A.7)."""

    __slots__ = (
        "gen_id", "resp_id", "sealed", "send_forbidden", "forbid_reason",
        "terminal_tier", "terminal_reason", "upstream_terminal",
        "cancel_requested", "cancel_attempts", "cancel_reason",
        "cap_fired", "cap_transitions", "end_markers", "tts_stop_emissions",
        "tts_started", "marker_enqueued", "marker_consumed", "quiescent",
        "sent", "flushed_total", "residue_total", "source_bytes",
        "admitted_bytes", "guard_dropped_bytes", "safety_truncated_bytes",
        "encode_failed", "synthetic_tail_frames",
        "synthetic_tail_encode_failures", "post_terminal_sends",
    )

    def __init__(self, gen_id, resp_id):
        self.gen_id = gen_id
        self.resp_id = resp_id
        self.sealed = False              # entered SEALED_DRAINING (A.4.A)
        self.send_forbidden = False      # entered SEND_FORBIDDEN (A.4.A)
        self.forbid_reason = None
        self.terminal_tier = None
        self.terminal_reason = None
        self.upstream_terminal = False
        self.cancel_requested = False
        self.cancel_attempts = 0
        self.cancel_reason = None
        self.cap_fired = False
        self.cap_transitions = 0
        self.end_markers = 0
        self.tts_stop_emissions = 0
        self.tts_started = False
        self.marker_enqueued = False
        self.marker_consumed = False
        self.quiescent = False
        self.sent = 0
        self.flushed_total = 0
        self.residue_total = 0
        self.source_bytes = 0
        self.admitted_bytes = 0
        self.guard_dropped_bytes = 0
        self.safety_truncated_bytes = 0
        self.encode_failed = 0
        self.synthetic_tail_frames = 0
        self.synthetic_tail_encode_failures = 0
        self.post_terminal_sends = 0

    @property
    def locally_terminal(self):
        return self.sealed or self.send_forbidden


class Connection:
    def __init__(self, ws, config):
        self.ws = ws
        self.config = config
        self.conn_ordinal = next(_CONN_SEQ)
        self.state = State.DISCONNECTED
        self.session_id = None
        self._ui_turn = 0          # CLIENT-UI-1 transcript turn key
        # ASR-UI-01: stable per-utterance identity for USER transcripts.  Each
        # upstream input item gets a dedicated monotonic turn id, independent of
        # the assistant `_ui_turn`, so `response.created` can never re-key an
        # unfinished user transcript.  Registry is bounded (newest 64 kept).
        self._ui_user_seq = 0
        self._ui_user_turns = {}
        self._ui_user_last_key = None
        self._ui_user_preview_key = None
        self._ui_tasks = set()     # CLIENT-UI-1 fire-and-forget sends
        self.enc24 = audio.OpusEnc24()
        self.dec16 = audio.OpusDec16()
        self.tts_active = False
        self.tts_resp_id = None
        self._tts_lock = asyncio.Lock()
        self._tts_owner_gen = None

        # ---- A.3 single downlink store (the ONLY encoded-frame holder) -----
        self.future_audio_store = deque()
        self._store_meta = deque()          # parallel metadata (no packets)
        self._store_event = asyncio.Event()  # wake-up only; never holds audio
        self._store_bytes = 0
        self._queued_frames = 0

        self.dl_buf = bytearray()           # raw PCM residue (exempt, A.3)
        self.in_flight_frames = 0
        self._head_gen = None
        self._head_meta = None
        self._head_state = None             # RESERVED_WAIT | SEND_AWAIT | None

        # ---- A.5 pacer / epoch state --------------------------------------
        self.pacer_task = None
        self._pacer_pid = None
        self._pacer_owned = {}
        self._active_pacer_tasks = 0
        self.previous_audio_send_start_at = None
        self.send_guard_until = None
        self._pending_guards = deque()      # slow-guard deadlines (deque of ms)
        self.media_epoch_ms = None
        self.epoch_ordinal = 0
        self.sent_in_epoch = 0
        self.frame_index = 0
        self.pacer_starts = 0
        self._last_send_start_ms = None
        # clean steady segment (A.5)
        self._seg = None
        self._seg_ordinal_in_epoch = 0
        # wake-overshoot diagnostics (per pacer task)
        self._ov_last_start = None
        self._ov_sum = 0.0
        self._ov_n = 0
        self._ov_frames = 0
        self._ov_break = False
        # alias aggregation (PO M2 compatibility aliases)
        self._qual_rates = []
        self._qual_means = []

        # ---- A.7 generations ----------------------------------------------
        self._gen_seq = 0
        self.generations = {}               # ever-created map (connection lifetime)
        self.current_resp_id = None
        self._current_gen = None
        self._recent_gen = None
        self._cancel_reason = None
        self._invalid_reasons = []

        self._warned_missing_id = False
        self._first_delta_seen = False
        self._speech_stop_t = None
        self.uplink_q = asyncio.Queue(maxsize=UPLINK_QUEUE_MAX)
        self.uplink_worker_task = None
        # diagnostics (no-ops unless RTL_DIAG=1)
        self.diag = diag.Diag(frame_ms=MEDIA_FRAME_MS)
        self.qwen = QwenClient(self.config.qwen, self._on_qwen_event,
                               on_close=self._on_qwen_closed)
        # BEHAVIOR-1: text-plane routing link (instructions/memory/workbench).
        # Purely additive: it never touches the Opus/pacer data plane.
        self.behavior = BehaviorLink(self, self.qwen, config=self.config)

    # ---- BEHAVIOR-1 safe boundary ------------------------------------------

    def is_safe_boundary(self):
        """True when no generation / TTS / pacer output is active (IDLE/LISTENING)."""
        return (self._current_gen is None and not self.tts_active
                and self.pacer_task is None)

    # ---- backlog / store helpers ------------------------------------------

    def _backlog(self):
        return self._queued_frames + self.in_flight_frames

    def _sync_gauges(self):
        counters.set_gauge("audio_store_current_frames", self._queued_frames)
        counters.set_gauge("audio_store_current_bytes", self._store_bytes)
        counters.set_gauge("unsent_backlog_current_frames", self._backlog())
        counters.set_gauge("in_flight_frames", self.in_flight_frames)
        counters.set_gauge("still_buffered_pcm_bytes", len(self.dl_buf))

    def _store_push(self, pkt, meta, gen):
        self.future_audio_store.append(pkt)
        self._store_meta.append(meta)
        self._queued_frames += 1
        self._store_bytes += len(pkt)
        counters.observe_max("audio_store_peak_frames", self._queued_frames)
        counters.observe_max("unsent_backlog_peak_frames", self._backlog())
        counters.observe_max("audio_store_peak_bytes", self._store_bytes)
        self._sync_gauges()
        self._store_event.set()
        self._ensure_pacer()

    def _store_push_marker(self, marker):
        self.future_audio_store.append(marker)
        self._store_meta.append(None)
        self._sync_gauges()
        self._store_event.set()
        self._ensure_pacer()

    def _store_pop(self):
        item = self.future_audio_store.popleft()
        meta = self._store_meta.popleft()
        if not isinstance(item, GenerationEnd):
            self._queued_frames -= 1
            self._store_bytes -= len(item)
        return item, meta

    def _gen_note(self, gen, **fields):
        if gen is not None:
            self.diag.on_gen_fields(gen.gen_id, **fields)

    def _gen_sync(self, gen):
        """Push the per-generation scalar evidence fields to /diag."""
        if gen is None:
            return
        self.diag.on_gen_fields(
            gen.gen_id,
            sent_confirmed=gen.sent,
            source_bytes=gen.source_bytes,
            admitted_bytes=gen.admitted_bytes,
            guard_dropped_bytes=gen.guard_dropped_bytes,
            safety_truncated_bytes=gen.safety_truncated_bytes,
            residue_bytes_total=gen.residue_total,
            flushed_total=gen.flushed_total,
        )

    def _mark_run_invalid(self, reason):
        self._invalid_reasons.append(reason)
        log.warning("run invalid: %s", reason)
        self.diag.step("run_invalid", reason=reason)

    def _pick_terminal_gen(self):
        """The generation a flush-type terminal transition owns."""
        if self._current_gen is not None:
            return self._current_gen
        if self._tts_owner_gen is not None:
            return self._tts_owner_gen
        for meta in reversed(self._store_meta):
            if meta is not None and meta.gen_obj is not None:
                return meta.gen_obj
        if self._head_gen is not None:
            return self._head_gen
        return self._recent_gen

    # ---- lifecycle --------------------------------------------------------

    def _ui_owns_generation(self, gen):
        """CLIENT-UI-1 ownership guard (R-F-1 / R-F-5).

        True iff `gen` still owns the live/current response generation.  The UI
        turn key advances only on `response.created`, so only the response
        created most recently on this connection may stamp/forward UI transcript
        events or emit the interrupted notice.  A superseded/stale response must
        never mutate the current UI turn.
        """
        return gen is not None and gen is self._recent_gen

    def _ui_user_turn(self, obj):
        """ASR-UI-01 fix B: stable per-utterance identity for USER transcripts.

        Binds each upstream input item (``item_id``) to a dedicated, monotonic
        int turn id that is stable across its ``delta``/``completed``/``failed``
        events and independent of the assistant ``_ui_turn`` — so a later
        ``response.created`` can never re-key an unfinished user transcript, and
        late events of an older item keep their old id (the client drops
        older-than-newest user turns).  Events without an id join the most
        recent utterance.  Never raises (falls back to None → caller default).
        """
        try:
            item_id = obj.get("item_id")
            key = item_id or self._ui_user_last_key
            if key is None:
                key = "__anon__"
            self._ui_user_last_key = key
            turn = self._ui_user_turns.get(key)
            if turn is None:
                self._ui_user_seq += 1
                turn = self._ui_user_seq
                self._ui_user_turns[key] = turn
                if len(self._ui_user_turns) > 64:
                    for old in sorted(self._ui_user_turns,
                                      key=lambda k: self._ui_user_turns[k])[:-64]:
                        self._ui_user_turns.pop(old, None)
            return turn
        except Exception:  # noqa: BLE001  (never disturb the turn engine)
            return None

    def _ui_notify_interrupted(self, turn=None):
        """Schedule the CLIENT-UI-1 interrupted notice (sync-safe; never raises).

        `turn` freezes the owning response's UI turn key at decision time so the
        fire-and-forget send can never drift onto a newer `response.created`
        (R-F-5: a stale response must not mutate the current UI turn).
        """
        try:
            task = asyncio.ensure_future(
                self._send_transcript("assistant", final=True, interrupted=True,
                                      turn=turn))
            self._ui_tasks.add(task)
            task.add_done_callback(self._ui_tasks.discard)
        except Exception:
            pass

    async def _send_transcript(self, role, *, delta=None, text=None, final=False,
                               interrupted=False, turn=None):
        """CLIENT-UI-1: forward transcript text to the client.

        Purely additive and never fatal: bounded send, all failures swallowed.  It is NOT
        gated on RTL_DIAG (the client needs the text regardless of diagnostics).
        """
        try:
            msg = protocol.build_transcript(role, delta=delta, text=text, final=final,
                                            interrupted=interrupted,
                                            turn=turn if turn is not None else self._ui_turn)
            if not isinstance(msg, str):        # defensive: never send a dict to send_str
                msg = json.dumps(msg, ensure_ascii=False)
            await asyncio.wait_for(self.ws.send_str(msg), 2.0)
        except Exception:
            pass

    async def on_connect(self):
        self.session_id = protocol.new_session_id()
        counters.ws_connections += 1
        self.diag.bind(self.session_id)
        log.info("WS connected sid=%s conns=%d", self.session_id,
                 counters.ws_connections)

    async def close(self):
        self.diag.step("close_begin")
        try:
            gen = self._pick_terminal_gen()
            try:
                if gen is not None:
                    self._invalidate_generation(gen, "CLOSE")
                try:
                    await asyncio.wait_for(self._cancel_pacer("CLOSE"), 3.0)
                except BaseException as e:  # noqa: BLE001
                    log.warning("close: pacer cancel error: %r", e)
                self._flush_store_reason("CLOSE")
                self._discard_residue("CLOSE")
                try:
                    await asyncio.wait_for(self._stop_tts("close"), 3.0)
                except BaseException as e:  # noqa: BLE001
                    log.warning("close: tts stop error: %r", e)
                self.current_resp_id = None
                self._current_gen = None
                self._sync_gauges()
                task = self.uplink_worker_task
                self.uplink_worker_task = None
                if task is not None and not task.done():
                    task.cancel()
                    try:
                        await asyncio.gather(task, return_exceptions=True)
                    except BaseException:  # noqa: BLE001
                        pass
                while True:
                    try:
                        self.uplink_q.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                if self.behavior is not None:
                    try:
                        await asyncio.wait_for(self.behavior.close(), 3.0)
                    except BaseException as e:  # noqa: BLE001
                        log.warning("close: behavior close error: %r", e)
                if self.qwen is not None:
                    try:
                        await asyncio.wait_for(self.qwen.close(), 6.0)
                    except BaseException as e:  # noqa: BLE001
                        log.warning("close: qwen close error: %r", e)
            except BaseException as e:  # noqa: BLE001
                log.warning("close: cleanup error: %r", e)
        finally:
            self.enc24 = None
            self.dec16 = None
            self.state = State.DISCONNECTED
            counters.ws_connections -= 1
            self.diag.conn_close()
            log.info("WS disconnected sid=%s conns=%d", self.session_id,
                     counters.ws_connections)

    # ---- inbound dispatch -------------------------------------------------

    async def handle_text(self, raw):
        try:
            msg = protocol.parse_json(raw)
        except Exception as e:  # noqa: BLE001
            log.warning("malformed JSON ignored: %s", e)
            return
        mtype = msg.get("type")
        if mtype == "hello":
            await self._on_hello(msg)
        elif mtype == "listen":
            await self._on_listen(msg)
        elif mtype == "abort":
            await self._on_abort(msg)
        else:
            log.info("unknown message type ignored: %r", mtype)

    def handle_binary(self, data):
        counters.audio_in_opus_frames += 1
        dec = self.dec16
        if dec is None:
            return
        try:
            pcm = dec.decode(data, audio.DEC_FRAME_SAMPLES)
        except Exception as e:  # noqa: BLE001
            log.warning("opus decode failed; frame skipped: %s", e)
            return
        counters.audio_in_pcm_bytes += len(pcm)
        if self.qwen.connected:
            self._enqueue_uplink(pcm)
        else:
            self.qwen.request_connect()

    def _enqueue_uplink(self, pcm):
        q = self.uplink_q
        if q.full():
            try:
                q.get_nowait()
                counters.uplink_dropped += 1
            except asyncio.QueueEmpty:
                pass
        try:
            q.put_nowait(pcm)
        except asyncio.QueueFull:
            counters.uplink_dropped += 1
        if self.uplink_worker_task is None or self.uplink_worker_task.done():
            self.uplink_worker_task = asyncio.create_task(self._uplink_worker())

    async def _uplink_worker(self):
        try:
            while True:
                pcm = await self.uplink_q.get()
                try:
                    await self.qwen.send_append(pcm)
                except Exception as e:  # noqa: BLE001
                    log.warning("qwen append failed: %s", e)
        except asyncio.CancelledError:
            raise

    # ---- handlers ---------------------------------------------------------

    async def _on_hello(self, msg):
        self.state = State.IDLE
        await self.ws.send_str(protocol.build_hello(self.session_id))
        log.info("hello handshake sid=%s client_version=%s",
                 self.session_id, msg.get("version"))

    async def _on_listen(self, msg):
        state = msg.get("state")
        mode = msg.get("mode", "manual")
        if state == "start":
            await self._on_listen_start(mode)
        elif state == "stop":
            log.info("listen stop (VAD drives turns; no commit/response.create)")
        elif state == "detect":
            log.info("listen detect ignored text_len=%d",
                     len(msg.get("text") or ""))
        else:
            log.info("listen unknown state ignored: %r", state)

    async def _on_listen_start(self, mode):
        prev = self.state
        gen = self._current_gen
        if gen is not None:
            self._invalidate_generation(gen, "LISTEN_START")
        await self._cancel_pacer("LISTEN_START")
        if self.tts_active:
            await self._stop_tts("listen_start")
        self._flush_store_reason("LISTEN_START")
        self._discard_residue("LISTEN_START")
        self.current_resp_id = None
        self._current_gen = None
        self.state = State.LISTENING
        log.info("listen start mode=%s prev=%s -> LISTENING", mode, prev.value)
        await self.qwen.ensure_connected()
        # BEHAVIOR-1: explicit listening start is a safe boundary.
        self.behavior.schedule_apply()

    async def _on_abort(self, msg):
        t0 = time.monotonic()
        self.diag.step("abort_begin", reason=msg.get("reason"))
        gen = self._pick_terminal_gen()
        if gen is not None:
            self._invalidate_generation(gen, "ABORT")
        await self._cancel_pacer("ABORT")
        self._flush_store_reason("ABORT")
        self._discard_residue("ABORT")
        await self._stop_tts("abort")
        counters.last_abort_stop_ms = round((time.monotonic() - t0) * 1000.0, 3)
        counters.aborts += 1
        if gen is not None:
            await self._cancel_upstream_once(gen, "ABORT")
        else:
            self.diag.on_cancel_skipped("no_live_generation")
        self.current_resp_id = None
        self._current_gen = None
        self.state = State.LISTENING
        log.info("abort reason=%r -> tts stop in %.1f ms aborts=%d",
                 msg.get("reason"), counters.last_abort_stop_ms, counters.aborts)

    # ---- Qwen event dispatch ----------------------------------------------

    async def _on_qwen_event(self, obj):
        etype = obj.get("type")
        _extra = None
        if etype == "response.done":
            resp = obj.get("response")
            _extra = {"status": (resp or {}).get("status") if isinstance(resp, dict)
                      else None}
        elif etype == "response.audio.delta":
            _extra = {"delta_b64_len": len(obj.get("delta") or "")}
        elif etype == "error":
            _extra = {"code": (obj.get("error") or {}).get("code")}
        self.diag.on_event(etype, _resp_id(obj), _extra)
        if diag.ENABLED:
            _tx_args = _transcript_args(obj)
            if _tx_args is not None:
                _tx_kw = {}
                if _tx_args[0] == "input":
                    _tx_kw["item_id"] = obj.get("item_id")
                self.diag.on_transcript(*_tx_args, **_tx_kw)
        # CLIENT-UI-1 forwarding (independent of RTL_DIAG; never blocks the receive loop)
        _ui_tx = _transcript_args(obj)
        if _ui_tx is not None:
            _kind, _delta, _rid, _full, _final = _ui_tx
            _ui_gen = self.generations.get(_rid) if _rid is not None else None
            if (_kind == "output" and _rid is not None
                    and not self._ui_owns_generation(_ui_gen)):
                # R-F-1 / R-F-5: a late/superseded/cancelled response's transcript
                # must not be re-attributed to the current UI turn.
                log.info("ui transcript dropped (stale rid=%r)", _rid)
            elif _kind == "input":
                # ASR-UI-01 fix A: Qwen input transcription is a CUMULATIVE,
                # revisable preview (text = confirmed prefix, stash = revisable
                # suffix).  Forward the complete preview with REPLACE semantics
                # (text=…) — never append-style delta — so the client replaces
                # its user bubble text; the final `completed` still replaces and
                # finalizes.  Turn id = ASR-UI-01 fix B (stable per utterance,
                # independent of `response.created`).
                _preview = _delta if _delta is not None else _full
                _user_turn = self._ui_user_turn(obj)
                if _preview:
                    self._ui_user_preview_key = (obj.get("item_id")
                                                 or self._ui_user_last_key)
                if _preview or _final:
                    await self._send_transcript("user", text=(_preview or None),
                                                final=bool(_final),
                                                turn=_user_turn)
            else:
                await self._send_transcript("assistant",
                                            delta=_delta, text=_full, final=bool(_final))
        elif etype == "conversation.item.input_audio_transcription.failed":
            # ASR-UI-01 fix B: close an open user preview bubble honestly — only
            # when this utterance actually showed a preview (avoid empty bubbles).
            try:
                _fail_key = obj.get("item_id") or self._ui_user_last_key
                _fail_turn = self._ui_user_turn(obj)
                if _fail_key is not None and _fail_key == self._ui_user_preview_key:
                    await self._send_transcript("user", final=True, turn=_fail_turn)
            except Exception:  # noqa: BLE001
                pass
        # BEHAVIOR-1 routing (text plane only; exceptions are contained inside)
        await self.behavior.on_qwen_event(obj)
        # A.4 counter integrity: every branch is locally exception-contained.
        try:
            if etype == "input_audio_buffer.speech_started":
                await self._on_speech_started()
            elif etype == "input_audio_buffer.speech_stopped":
                self._speech_stop_t = time.monotonic()
                self._first_delta_seen = False
                log.info("qwen speech_stopped")
            elif etype == "response.created":
                self._on_response_created(obj)
            elif etype == "response.audio.delta":
                await self._on_audio_delta(obj)
            elif etype in ("response.audio.done", "response.done"):
                await self._on_response_end(obj)
            elif etype == "input_audio_buffer.committed":
                log.info("qwen input_audio_buffer.committed")
            elif etype in ("session.created", "session.updated"):
                log.info("qwen %s", etype)
            else:
                log.info("qwen event ignored: %r", etype)
        except Exception as e:  # noqa: BLE001
            counters.inc_dispatch_error(etype)
            log.warning("qwen dispatch error (%s): %r", etype, e)

    def _on_response_created(self, obj):
        rid = _resp_id(obj)
        gen_id = next(_GEN_SEQ)      # globally unique (diag evidence namespace)
        self._gen_seq = gen_id
        gen = Generation(gen_id, rid)
        self._ui_turn += 1          # CLIENT-UI-1: new assistant turn key
        self.generations[rid] = gen
        self._recent_gen = gen
        self.current_resp_id = rid
        self._current_gen = gen
        self._first_delta_seen = False
        self.diag.on_response_created(rid, gen.gen_id)
        log.info("qwen response.created id=%s gen=%s", rid, gen.gen_id)

    # ---- barge-in (A.10) ---------------------------------------------------

    async def _on_speech_started(self):
        log.info("qwen speech_started")
        # BEHAVIOR-1: warm the workbench cache while the user is still speaking
        # (text plane only; never affects the barge-in path below).
        self.behavior.on_speech_started()
        barge = (self.tts_active or self.pacer_task is not None
                 or self.current_resp_id is not None)
        self.diag.barge_snapshot({
            "tts_active": self.tts_active,
            "tts_resp_id": self.tts_resp_id,
            "pacer_task": self.pacer_task is not None,
            "pacer_task_id": self._pacer_pid,
            "store_frames": self._queued_frames,
            "store_bytes": self._store_bytes,
            "backlog_frames": self._backlog(),
            "dl_buf_len": len(self.dl_buf),
            "last_queued_frame_seq": self.diag.frame_seq,
            "last_sent_frame_seq": self.diag.last_sent_seq,
            "current_resp_id": self.current_resp_id,
            "barge_candidate": barge,
        })
        if not barge:
            return
        counters.inc("barge_in_sequences_total")
        gen = self._pick_terminal_gen()
        results = {}
        any_failed = False

        # BIT 0 — local invalidation (synchronous, before any await)
        try:
            if gen is not None:
                self._invalidate_generation(gen, "BARGEIN")
            results["bit0"] = "SUCCEEDED" if gen is not None else "NOT_APPLICABLE"
        except Exception as e:  # noqa: BLE001
            results["bit0"] = "FAILED"
            counters.inc("barge_in_invalidate_failures")
            any_failed = True
            log.warning("barge-in BIT0 failed: %r", e)
        self.diag.step("invalidate_generation")

        # BIT 1 — pacer cancel / not applicable
        try:
            cancelled = await self._cancel_pacer("BARGEIN")
            results["bit1"] = "SUCCEEDED" if cancelled else "NOT_APPLICABLE"
        except Exception as e:  # noqa: BLE001
            results["bit1"] = "FAILED"
            counters.inc("barge_in_pacer_cancel_failures")
            any_failed = True
            log.warning("barge-in BIT1 failed: %r", e)
        self.diag.step("pacer_cancel_done")

        # BIT 2 — store flush / empty
        try:
            frames, markers = self._flush_store_reason("BARGEIN")
            results["bit2"] = "SUCCEEDED"
            self.diag.step("store_flushed", frames=frames, markers=markers)
        except Exception as e:  # noqa: BLE001
            results["bit2"] = "FAILED"
            counters.inc("barge_in_store_flush_failures")
            any_failed = True
            log.warning("barge-in BIT2 failed: %r", e)

        # BIT 3 — TTS stop / not active
        try:
            if self.tts_active:
                await self._stop_tts("barge_in")
                results["bit3"] = "SUCCEEDED"
            else:
                results["bit3"] = "NOT_APPLICABLE"
        except Exception as e:  # noqa: BLE001
            results["bit3"] = "FAILED"
            counters.inc("barge_in_tts_stop_failures")
            any_failed = True
            log.warning("barge-in BIT3 failed: %r", e)
        self.diag.step("tts_stopped")

        if any_failed:
            counters.inc("barge_in_sequence_incomplete")
        self.diag.on_barge_bits(0b1111 if not any_failed else 0, results)

        # Upstream cancel is governed separately (A.8), not part of the mask.
        if gen is not None:
            await self._cancel_upstream_once(gen, "BARGEIN")
        else:
            self.diag.on_cancel_skipped("no_live_generation")
        counters.barge_ins += 1
        log.info("barge-in (Path B): playback cancelled barge_ins=%d",
                 counters.barge_ins)

    # ---- downlink ingest (A.4.A / A.2 / A.4.B) ----------------------------

    def _classify_rid(self, rid):
        """Attribution resolution BEFORE decoding (A.4.A)."""
        if rid is not None:
            gen = self.generations.get(rid)
            if gen is None:
                return None, "UNKNOWN_RID"
            if gen is self._current_gen and not gen.locally_terminal:
                return gen, "LIVE"
            return gen, "STALE"
        gen = self._current_gen
        if gen is not None and not gen.locally_terminal:
            return gen, "LIVE"
        return None, "UNMAPPED"

    async def _on_audio_delta(self, obj):
        rid = _resp_id(obj)
        gen, cls = self._classify_rid(rid)
        b64 = obj.get("delta", "")
        try:
            raw = base64.b64decode(b64, validate=True)
        except Exception:  # noqa: BLE001
            if cls == "LIVE":
                counters.inc("bad_base64_live_events")
                self._mark_run_invalid("bad_base64_live")
            else:
                counters.inc("bad_base64_stale_or_unmapped_events")
            log.warning("qwen audio.delta bad base64 ignored (target=%s)", cls)
            return
        # LEGACY diagnostic: documented post-decode / pre-guard update point.
        counters.inc("qwen_audio_delta_bytes", len(raw))
        if cls == "LIVE":
            if rid is None and gen is not None:
                counters.inc("idless_delta_mapped_bytes", len(raw))
            if not self._first_delta_seen:
                self._first_delta_seen = True
                if self._speech_stop_t is not None:
                    counters.last_speech_stop_to_first_audio_ms = round(
                        (time.monotonic() - self._speech_stop_t) * 1000.0, 3)
            counters.inc("source_pcm_bytes", len(raw))
            if gen is not None:
                gen.source_bytes += len(raw)
            await self._admit_live_delta(gen, raw, rid)
        elif cls == "STALE":
            counters.inc("source_pcm_bytes", len(raw))
            counters.inc("guard_dropped_pcm_bytes", len(raw))
            counters.inc("post_terminal_delta_events")
            if gen is not None:
                gen.guard_dropped_bytes += len(raw)
            self.diag.step("stale_delta", bytes=len(raw),
                           resp_id=rid, gen=gen.gen_id if gen else None)
        else:  # UNMAPPED / UNKNOWN_RID
            counters.inc("orphan_pcm_bytes", len(raw))
            self._mark_run_invalid("orphan_delta_%s" % cls.lower())
            self.diag.step("orphan_delta", bytes=len(raw), resp_id=rid,
                           classified=cls)

    async def _admit_live_delta(self, gen, raw, rid):
        if gen is None:
            counters.inc("orphan_pcm_bytes", len(raw))
            self._mark_run_invalid("live_without_generation")
            return
        # A.2 route R1 — delta-triggered store cap, BEFORE admitting any bytes.
        if gen.cap_fired:
            counters.inc("safety_truncated_pcm_bytes", len(raw))
            gen.safety_truncated_bytes += len(raw)
            return
        if (self._backlog() == MAX_FUTURE_FRAMES
                and (len(self.dl_buf) + len(raw)) >= audio.FRAME_BYTES):
            self._store_cap_transition_r1(gen, truncated=len(raw))
            return
        counters.inc("admitted_pcm_bytes", len(raw))
        gen.admitted_bytes += len(raw)
        self.dl_buf.extend(raw)
        self._sync_gauges()

        t_qwen = diag.now()
        n_frames = 0
        started = False
        # Single pass: form ONE frame, then admit it immediately, so the
        # backlog gauge used by the admission guard always includes this
        # delta's earlier frames (A.2 admission rule).
        while len(self.dl_buf) >= audio.FRAME_BYTES:
            if self._backlog() + 1 > MAX_FUTURE_FRAMES:
                # Mid-delta cap boundary: the frame that would have completed
                # is never formed; remaining unformed admitted bytes are
                # disposed exactly once through the STORE_CAP residue term and
                # the generation is closed to all further source bytes.
                self._store_cap_transition_mid_delta(gen)
                return
            chunk = bytes(self.dl_buf[:audio.FRAME_BYTES])
            del self.dl_buf[:audio.FRAME_BYTES]
            diag.cap_qwen_pcm(chunk)
            try:
                pkt = self.enc24.encode(chunk, audio.FRAME_SAMPLES)
            except Exception as e:  # noqa: BLE001
                counters.inc("encode_failed_frames")
                gen.encode_failed += 1
                log.warning("opus encode failed: %s", e)
                continue
            counters.inc("encoded_full_frames")
            n_frames += 1
            self._sync_gauges()
            if self._store_bytes + len(pkt) > MAX_FUTURE_AUDIO_BYTES:
                # A.11 byte-cap: the trigger packet is never stored.
                await self._byte_cap_failure(gen, pkt, extra=())
                return
            if not started and not self.tts_active:
                await self._tts_start(gen)
            started = True
            meta = self._make_meta(pkt, gen, rid, t_qwen)
            self._store_push(pkt, meta, gen)
            self.diag.on_store_admit(meta, self._queued_frames,
                                     self._backlog(), self._store_bytes)
        self.diag.on_delta(rid, len(raw), n_frames)

    def _make_meta(self, pkt, gen, rid, t_qwen):
        self.diag.frame_seq += 1
        return FrameMeta(gen.gen_id, gen, rid, self.diag.frame_seq, t_qwen)

    def _store_cap_transition_mid_delta(self, gen):
        """A.2 STORE_CAP at a mid-delta admission boundary.

        A multi-frame delta can reach the frame cap part-way through: the
        frame that would have completed is NEVER formed, and every remaining
        unformed byte in `dl_buf` was already admitted, so it is disposed
        exactly once through `residue_discarded_store_cap_bytes` (the A.4.B
        STORE_CAP residue term) — never reclassified as safety truncation
        (R1.3 post-condition analogue: `len(dl_buf) == 0` for the remainder,
        and all later deltas are safety-truncated by `gen.cap_fired`).
        """
        residue = len(self.dl_buf)
        if gen.cap_fired:
            # Already capped via the per-delta route: no second transition.
            if residue:
                counters.inc("residue_discarded_store_cap_bytes", residue)
                gen.residue_total += residue
            self.dl_buf.clear()
            self._sync_gauges()
            return
        gen.cap_fired = True
        gen.cap_transitions += 1
        counters.inc("cap_transitions_total")
        counters.observe_max("cap_transitions_max_per_generation",
                             gen.cap_transitions)
        if residue:
            counters.inc("residue_discarded_store_cap_bytes", residue)
            gen.residue_total += residue
        self.dl_buf.clear()
        self._sync_gauges()
        self.diag.on_cap_transition(gen.gen_id, "R1_mid_delta", residue,
                                    self._backlog())
        self._gen_note(gen, cap_transitions=gen.cap_transitions,
                       residue_bytes_total=gen.residue_total,
                       safety_truncated_bytes=gen.safety_truncated_bytes,
                       admitted_bytes=gen.admitted_bytes)
        log.warning("AUDIO_STORE_CAP_REACHED (mid-delta) gen=%s residue=%d "
                    "backlog=%d", gen.gen_id, residue, self._backlog())

    def _store_cap_transition_r1(self, gen, truncated):
        """A.2 route R1: discard admitted dl_buf residue, truncate the delta."""
        gen.cap_fired = True
        gen.cap_transitions += 1
        counters.inc("cap_transitions_total")
        counters.observe_max("cap_transitions_max_per_generation",
                             gen.cap_transitions)
        residue = len(self.dl_buf)
        if residue:
            counters.inc("residue_discarded_store_cap_bytes", residue)
            gen.residue_total += residue
            self.dl_buf.clear()
        if truncated:
            counters.inc("safety_truncated_pcm_bytes", truncated)
            gen.safety_truncated_bytes += truncated
        self._sync_gauges()
        self.diag.on_cap_transition(gen.gen_id, "R1", residue, self._backlog())
        self._gen_note(gen, cap_transitions=gen.cap_transitions,
                       residue_bytes_total=gen.residue_total,
                       safety_truncated_bytes=gen.safety_truncated_bytes,
                       admitted_bytes=gen.admitted_bytes)
        log.warning("AUDIO_STORE_CAP_REACHED (R1) gen=%s residue=%d truncated=%d",
                    gen.gen_id, residue, truncated)

    # ---- response end / seal (A.9) ----------------------------------------

    async def _on_response_end(self, obj):
        etype = obj.get("type")
        rid = _resp_id(obj)
        _status = None
        if isinstance(obj.get("response"), dict):
            _status = obj["response"].get("status")
        self.diag.on_response_end(etype, rid, _status)
        if rid is None:
            if self._current_gen is None:
                log.debug("id-less %s ignored (no current response)", etype)
                return
            if not self._warned_missing_id:
                self._warned_missing_id = True
                log.warning("response end without id; applying to current response")
            rid = self._current_gen.resp_id
        gen = self.generations.get(rid)
        if gen is None:
            self.diag.on_late_event(etype, rid, "unknown_rid")
            if etype == "response.done":
                self._count_response_done(_status)
            return
        gen.upstream_terminal = True
        if gen.locally_terminal:
            # Tombstone absorption: no marker / no stop / no tail (A.9).
            self.diag.on_late_event(etype, rid, "tombstone", gen.gen_id)
            self._duplicate_end_residue_check(gen)
            if etype == "response.done":
                self._count_response_done(_status, ui_gen=gen)
            return
        if gen is not self._current_gen:
            # Defensive: superseded generation (Qwen serialises responses).
            self.diag.on_late_event(etype, rid, "superseded", gen.gen_id)
            self._invalidate_generation(gen, "UPSTREAM_CLOSED")
            if etype == "response.done":
                self._count_response_done(_status, ui_gen=gen)
            return
        await self._seal_generation(gen, rid, etype, _status)

    def _count_response_done(self, status, ui_gen=None):
        if status == "cancelled":
            counters.responses_cancelled += 1
            # CLIENT-UI-1: mark the assistant turn as interrupted (text is NOT
            # fabricated) ONLY when the cancelled response still owns the
            # live/current generation (R-F-1 / R-F-5: a late cancelled done for a
            # superseded response must not mutate the current UI turn).  The
            # owning turn key is frozen NOW — by the ownership condition it is
            # exactly the cancelled response's own turn.
            # Fire-and-forget: this helper stays synchronous (no control-flow change).
            if self._ui_owns_generation(ui_gen):
                self._ui_notify_interrupted(turn=self._ui_turn)
        else:
            counters.responses_completed += 1

    def _duplicate_end_residue_check(self, gen):
        n = len(self.dl_buf)
        if n == 0:
            return
        # First end left accounting open: named accounting path, never a blind
        # clear (A.4.B duplicate-end rule).
        counters.inc("accounting_fault_events")
        reason = gen.forbid_reason or "UPSTREAM_CLOSED"
        key = _REASON_KEY.get(reason, "upstream_closed")
        counters.inc("residue_discarded_%s_bytes" % key, n)
        gen.residue_total += n
        self.dl_buf.clear()
        self._sync_gauges()
        self.diag.step("duplicate_end_residue", gen=gen.gen_id, bytes=n,
                       reason=key)

    async def _seal_generation(self, gen, rid, etype, status):
        N = len(self.dl_buf)
        backlog_now = self._backlog()
        branch = "no_tail"
        tail_bytes = None
        if backlog_now >= MAX_FUTURE_FRAMES:
            if N == 0:
                branch = "seal_no_tail_full_backlog"
            else:
                # A.2 route R2 — seal-time store-cap disposal (no tail frame).
                if gen.cap_fired:
                    # Unreachable by construction (R1.3); defensive tripwire.
                    counters.inc("accounting_fault_events")
                    self.diag.step("r2_after_r1_tripwire", gen=gen.gen_id)
                gen.cap_fired = True
                gen.cap_transitions += 1
                counters.inc("cap_transitions_total")
                counters.observe_max("cap_transitions_max_per_generation",
                                     gen.cap_transitions)
                counters.inc("residue_discarded_store_cap_bytes", N)
                gen.residue_total += N
                self.dl_buf.clear()
                self._sync_gauges()
                branch = "R2"
                self.diag.on_cap_transition(gen.gen_id, "R2", N, backlog_now)
        elif N > 0:
            # Synthetic tail (A.4.B): one padded frame, including N == 1.
            pad = audio.FRAME_BYTES - N
            chunk = bytes(self.dl_buf) + b"\x00" * pad
            self.dl_buf.clear()
            self._sync_gauges()
            try:
                pkt = self.enc24.encode(chunk, audio.FRAME_SAMPLES)
            except Exception as e:  # noqa: BLE001
                counters.inc("synthetic_tail_encode_failures")
                counters.inc("synthetic_tail_encode_failed_source_bytes", N)
                counters.inc("synthetic_tail_encode_failed_zero_pad_bytes", pad)
                gen.synthetic_tail_encode_failures += 1
                branch = "tail_encode_failed"
                log.warning("opus encode (tail) failed: %s", e)
            else:
                if self._store_bytes + len(pkt) > MAX_FUTURE_AUDIO_BYTES:
                    # Byte-cap on the seal-time tail encode (A.11): no tail
                    # frame; the N admitted bytes go to the byte-cap residue.
                    await self._byte_cap_failure(gen, pkt, extra=(),
                                                 pre_residue_bytes=N)
                    branch = "tail_byte_cap"
                    tail_bytes = N
                    self.diag.on_generation_seal(
                        gen.gen_id, gen.resp_id, branch, N,
                        self._queued_frames, self._backlog(), tail_bytes)
                    self._finalize_seal(gen, rid, etype, status, branch)
                    return
                counters.inc("synthetic_tail_frames")
                counters.inc("synthetic_tail_source_bytes", N)
                counters.inc("synthetic_tail_zero_pad_bytes", pad)
                gen.synthetic_tail_frames += 1
                meta = self._make_meta(pkt, gen, rid, diag.now())
                self._store_push(pkt, meta, gen)
                self.diag.on_store_admit(meta, self._queued_frames,
                                         self._backlog(), self._store_bytes)
                branch = "tail"
                tail_bytes = N
        gen.sealed = True
        gen.terminal_tier = "SEALED_DRAINING"
        gen.terminal_reason = "SEAL"
        # exactly one GenerationEnd after its final playable frame (both R2 and
        # normal branches); marker is excluded from all frame counters.
        gen.end_markers += 1
        gen.marker_enqueued = True
        counters.observe_max("end_markers_max_per_generation", gen.end_markers)
        self._store_push_marker(GenerationEnd(gen.gen_id, "seal"))
        self._finalize_seal(gen, rid, etype, status, branch)
        self.diag.on_generation_seal(gen.gen_id, gen.resp_id, branch, N,
                                self._queued_frames, self._backlog(), tail_bytes)
        self._gen_note(gen, sealed=True, terminal_tier=gen.terminal_tier,
                       terminal_reason=gen.terminal_reason,
                       end_markers=gen.end_markers,
                       cap_transitions=gen.cap_transitions,
                       synthetic_tail_frames=gen.synthetic_tail_frames,
                       synthetic_tail_encode_failures=gen.synthetic_tail_encode_failures,
                       residue_bytes_total=gen.residue_total)
        self._gen_sync(gen)
        self._ensure_pacer()

    def _finalize_seal(self, gen, rid, etype, status, branch):
        if self.current_resp_id == rid:
            self.current_resp_id = None
        if self._current_gen is gen:
            self._current_gen = None
        if etype == "response.done":
            self._count_response_done(status, ui_gen=gen)
            log.info("qwen response.done status=%s resp=%s", status, rid)
        else:
            log.info("qwen response.audio.done resp=%s", rid)

    # ---- TTS ---------------------------------------------------------------

    async def _emit_tts(self, state):
        try:
            await asyncio.wait_for(
                self.ws.send_str(protocol.build_tts(state, self.session_id)), 2.0)
        except Exception as e:  # noqa: BLE001
            log.warning("tts %s send failed: %s", state, e)

    async def _tts_start(self, gen=None):
        async with self._tts_lock:
            if self.tts_active:
                self.diag.on_tts_start_skipped("already_active")
                return
            self.tts_active = True
            self.tts_resp_id = gen.resp_id if gen is not None else self.current_resp_id
            self._tts_owner_gen = gen
            if gen is not None:
                gen.tts_started = True
            self.state = State.SPEAKING
            counters.set_state("tts_owner_generation_id",
                               gen.gen_id if gen is not None else None)
            self.diag.on_tts_start(self.tts_resp_id,
                                   gen.gen_id if gen is not None else None,
                                   self._pacer_pid)
            await asyncio.shield(self._emit_tts("start"))
        log.info("tts start resp=%s", self.tts_resp_id)

    async def _stop_tts(self, caller="unknown"):
        async with self._tts_lock:
            if not self.tts_active:
                return
            owner = self._tts_owner_gen
            _rid = self.tts_resp_id
            _gen = owner.gen_id if owner is not None else None
            self.tts_active = False
            self.tts_resp_id = None
            self._tts_owner_gen = None
            if owner is not None:
                owner.tts_stop_emissions += 1
                counters.observe_max("tts_stop_emissions_max_per_generation",
                                     owner.tts_stop_emissions)
                self._gen_note(owner,
                               tts_stop_emissions=owner.tts_stop_emissions)
            counters.set_state("tts_owner_generation_id", None)
            self.diag.on_tts_stop(_rid, _gen,
                                  self._current_gen.gen_id
                                  if self._current_gen is not None else None,
                                  self._pacer_pid, caller)
            await asyncio.shield(self._emit_tts("stop"))
            # BEHAVIOR-1: playback ended — a possible safe boundary.
            self.behavior.schedule_apply()

    # ---- invalidation / flush / residue (A.4.A-C) --------------------------

    def _invalidate_generation(self, gen, reason):
        """Flush-type terminal transition (synchronous, before any await)."""
        if gen is None:
            return
        gen.send_forbidden = True
        if gen.forbid_reason is None:
            gen.forbid_reason = reason
        gen.terminal_tier = "SEND_FORBIDDEN"
        gen.terminal_reason = reason
        if self.current_resp_id == gen.resp_id:
            self.current_resp_id = None
        if self._current_gen is gen:
            self._current_gen = None
        self.diag.mark_invalidated(gen.gen_id, reason, also_resp_id=gen.resp_id)
        self.diag.on_generation_terminal(gen.gen_id, gen.resp_id,
                                         "SEND_FORBIDDEN", reason)
        self._gen_note(gen, terminal_tier=gen.terminal_tier,
                       terminal_reason=gen.terminal_reason)
        self._gen_sync(gen)

    def _flush_store_reason(self, reason):
        """Dispose all QUEUED frames + un-consumed markers into the reason bucket."""
        if reason not in _REASON_KEY:
            raise KeyError("unknown flush reason: %r" % reason)
        key = _REASON_KEY[reason]
        frames = 0
        markers = 0
        by_gen = {}
        while self.future_audio_store:
            item, meta = self._store_pop()
            if isinstance(item, GenerationEnd):
                markers += 1
                continue
            counters.inc("flushed_%s_frames" % key)
            frames += 1
            if meta is not None and meta.gen_obj is not None:
                g = meta.gen_obj
                g.flushed_total += 1
                entry = by_gen.get(g.gen_id)
                if entry is None:
                    by_gen[g.gen_id] = [g, 1]
                else:
                    entry[1] += 1
        self._sync_gauges()
        residue = len(self.dl_buf)
        # Per-owning-generation attribution (normative /diag evidence) and tier
        # ownership: a flush-type transition tiers every generation whose
        # frames it disposes (A.4.A synchronous set).
        for gen_id, (g, n) in by_gen.items():
            if not g.send_forbidden:
                g.send_forbidden = True
                if g.forbid_reason is None:
                    g.forbid_reason = reason
                g.terminal_tier = "SEND_FORBIDDEN"
                g.terminal_reason = reason
                self.diag.on_generation_terminal(g.gen_id, g.resp_id,
                                                 "SEND_FORBIDDEN", reason)
            self.diag.on_store_flush(gen_id, reason, n, 0, residue)
        if markers:
            self.diag.on_store_flush(None, reason, 0, markers, residue)
        return frames, markers

    def _discard_residue(self, reason):
        if reason not in _REASON_KEY:
            raise KeyError("unknown residue reason: %r" % reason)
        n = len(self.dl_buf)
        if n:
            counters.inc("residue_discarded_%s_bytes" % _REASON_KEY[reason], n)
            self.dl_buf.clear()
            self._sync_gauges()
        return n

    def _resolve_known_unsent(self, gen, meta):
        """A.4.C: RESERVED_WAIT head is known-unsent -> owning reason bucket."""
        reason = gen.forbid_reason if gen is not None else None
        if reason is None:
            reason = self._cancel_reason
        if reason is None or reason not in _REASON_KEY:
            counters.inc("accounting_fault_events")
            reason = "CLOSE"
        if gen is not None and not gen.send_forbidden:
            # The owning transition sets SEND_FORBIDDEN synchronously; a
            # bystander generation whose head is flushed by this transition is
            # tiered here (A.4.A: the transition owns the flush disposition).
            gen.send_forbidden = True
            if gen.forbid_reason is None:
                gen.forbid_reason = reason
            gen.terminal_tier = "SEND_FORBIDDEN"
            gen.terminal_reason = reason
            self.diag.on_generation_terminal(gen.gen_id, gen.resp_id,
                                             "SEND_FORBIDDEN", reason)
        counters.inc("flushed_%s_frames" % _REASON_KEY[reason])
        if gen is not None:
            gen.flushed_total += 1
        # per-generation /diag evidence for the head disposition
        self.diag.on_store_flush(gen.gen_id if gen is not None else None,
                                 reason, 1, 0, len(self.dl_buf))
        self._release_head()

    def _release_head(self):
        self.in_flight_frames = max(0, self.in_flight_frames - 1)
        self._head_gen = None
        self._head_meta = None
        self._head_state = None
        self._sync_gauges()

    # ---- one-shot upstream cancel (A.8) ------------------------------------

    async def _cancel_upstream_once(self, gen, reason):
        if gen is None:
            self.diag.on_cancel_skipped("no_generation")
            return "NO_GENERATION"
        # synchronous latch, before any await
        if gen.cancel_requested:
            self.diag.on_cancel_skipped("already_requested")
            return "ALREADY_REQUESTED"
        if gen.upstream_terminal:
            self.diag.on_cancel_skipped("upstream_already_done")
            return "ALREADY_TERMINAL"
        gen.cancel_requested = True
        gen.cancel_attempts += 1
        gen.cancel_reason = reason
        counters.inc("cancel_attempts")
        counters.observe_max("cancel_max_per_generation", gen.cancel_attempts)
        self.diag.on_cancel_sent()
        self._gen_note(gen, cancel_attempts=gen.cancel_attempts)
        try:
            await self.qwen.send_cancel()
        except Exception as e:  # noqa: BLE001
            counters.inc("cancel_send_errors")
            log.warning("qwen cancel failed: %s", e)
        return "SENT"

    # ---- fatal stall / send error / byte cap -------------------------------

    async def _pacer_fatal_stall(self, gen, reason, head_resolution):
        """A.6 Case B exit list (single authoritative wording)."""
        counters.inc("pacer_fatal_stalls")
        self._segment_mark_dirty()
        if gen is not None:
            self._invalidate_generation(gen, "PACER_STALL")
        if head_resolution == "known_unsent":
            if gen is not None:
                counters.inc("flushed_pacer_stall_frames")
                gen.flushed_total += 1
            self._release_head()
        elif head_resolution == "outcome_unknown":
            counters.inc("send_outcome_unknown_frames")
            self._release_head()
        self._discard_residue("PACER_STALL")
        self._flush_store_reason("PACER_STALL")
        await self._cancel_upstream_once(gen, "PACER_STALL")
        await self._stop_tts("pacer_stall")
        if gen is not None:
            self._gen_note(gen, terminal_tier=gen.terminal_tier,
                           terminal_reason=gen.terminal_reason)

    async def _send_error_termination(self, gen, exc):
        self._segment_mark_dirty()
        if gen is not None:
            self._invalidate_generation(gen, "SEND_ERROR")
        self._discard_residue("SEND_ERROR")
        self._flush_store_reason("SEND_ERROR")
        await self._cancel_upstream_once(gen, "SEND_ERROR")
        await self._stop_tts("send_error")
        log.warning("pacer send failed; generation terminated: %r", exc)

    async def _byte_cap_failure(self, gen, trigger_pkt, extra=(),
                                pre_residue_bytes=None):
        """A.11 AUDIO_STORE_BYTE_CAP_REACHED (12-step, ordering normative)."""
        counters.inc("byte_cap_failures")
        # step 1 — SEND_FORBIDDEN synchronously before the first await.
        self._invalidate_generation(gen, "BYTE_CAP_FAILURE")
        self.diag.on_byte_cap(gen.gen_id, "fired", packet_bytes=len(trigger_pkt),
                         extra_packets=len(extra))
        # step 2 — cancel the pacer with reason BYTE_CAP_FAILURE.
        await self._cancel_pacer("BYTE_CAP_FAILURE")
        # steps 3-5 — head resolution (inside pacer cancel) + QUEUED flush.
        frames, markers = self._flush_store_reason("BYTE_CAP_FAILURE")
        # step 6 — triggering packet (+ not-yet-stored accepted packets of the
        # same delta) disposed exactly once, never stored.  Seal-time tail
        # case: no frame was formed, so the frame-formation rule does not
        # apply (A.11 final paragraph) and only the residue term is used.
        if pre_residue_bytes is None:
            counters.inc("flushed_byte_cap_failure_frames", 1 + len(extra))
            gen.flushed_total += 1 + len(extra)
        # step 7 — residue (tail-encode case supplies its own N bytes).
        if pre_residue_bytes:
            counters.inc("residue_discarded_byte_cap_failure_bytes",
                         pre_residue_bytes)
            gen.residue_total += pre_residue_bytes
        self._discard_residue("BYTE_CAP_FAILURE")
        # step 8 — upstream cancel once.
        await self._cancel_upstream_once(gen, "BYTE_CAP_FAILURE")
        # step 9 — exactly one TTS stop.
        await self._stop_tts("byte_cap_failure")
        # step 10 — byte_cap_failures already incremented.
        # step 12 — quiescence.
        self._sync_gauges()
        counters.set_gauge("still_stored_frames", self._queued_frames)
        self.diag.on_byte_cap(
            gen.gen_id, "quiescence", queued=self._queued_frames,
            in_flight=self.in_flight_frames,
            still_buffered=len(self.dl_buf),
            flushed_frames=frames, markers=markers)
        self._gen_note(gen, flushed_by_reason=dict(
            {"BYTE_CAP_FAILURE": gen.flushed_total}))
        log.warning("AUDIO_STORE_BYTE_CAP_REACHED gen=%s (RESOURCE_SAFETY_FAILURE)",
                    gen.gen_id)

    # ---- pacer (A.5 / A.6) -------------------------------------------------

    def _ensure_pacer(self):
        """Atomic single-pacer reservation (synchronous; no await)."""
        if self.pacer_task is None or self.pacer_task.done():
            pid = next(_PACER_SEQ)
            self._pacer_pid = pid
            self.diag.pacer_open(pid)
            task = asyncio.create_task(self._pacer(pid))
            self.pacer_task = task
            self._pacer_owned[task] = True
            self._active_pacer_tasks += 1
            counters.set_gauge("active_pacer_tasks", self._active_pacer_tasks)
            counters.observe_max("active_pacer_tasks_max",
                                 self._active_pacer_tasks)

    def _pacer_release(self, task):
        if self._pacer_owned.pop(task, None):
            self._active_pacer_tasks = max(0, self._active_pacer_tasks - 1)
            counters.set_gauge("active_pacer_tasks", self._active_pacer_tasks)

    def _epoch_create(self, kind, reason=None, anchor_ms=None):
        """E1/E2/E3/E4 media-clock epoch creation (A.5)."""
        self.epoch_ordinal += 1
        self.media_epoch_ms = (_now_ms() if anchor_ms is None else anchor_ms)
        self.frame_index = 0
        self.sent_in_epoch = 0
        self._seg_ordinal_in_epoch = 0
        self.diag.on_epoch(kind, self.epoch_ordinal, self._pacer_pid,
                           self.media_epoch_ms, reason=reason)
        self._ov_break = True
        return self.media_epoch_ms

    def _segment_mark_dirty(self):
        if self._seg is not None:
            self._seg["clean"] = False

    def _segment_add(self, send_start_ms):
        if self._seg is None:
            self._seg_ordinal_in_epoch += 1
            self._seg = {
                "epoch": self.epoch_ordinal,
                "ordinal": self._seg_ordinal_in_epoch,
                "pid": self._pacer_pid,
                "first": send_start_ms,
                "last": send_start_ms,
                "frames": 1,
                "clean": True,
            }
        else:
            self._seg["last"] = send_start_ms
            self._seg["frames"] += 1

    def _segment_terminate(self, reason, clean=True):
        seg = self._seg
        if seg is None:
            return
        self._seg = None
        if not seg["clean"] or not clean:
            self.diag.step("segment_closed_dirty", reason=reason,
                           frames=seg["frames"])
            return
        n = seg["frames"]
        if n < 250:
            return
        span = seg["last"] - seg["first"]
        rate = (n - 1) * 1000.0 / span if span > 0 else None
        mean = span / (n - 1) if n > 1 else None
        if rate is None or mean is None:
            return
        record = {
            "segment_id": "c%d-p%s-e%s-s%d" % (self.conn_ordinal, seg["pid"],
                                               seg["epoch"], seg["ordinal"]),
            "steady_segment_first_send_start": round(seg["first"], 6),
            "steady_segment_last_send_start": round(seg["last"], 6),
            "steady_segment_frames": n,
            "segment_rate_fps": round(rate, 6),
            "segment_mean_inter_send_ms": round(mean, 6),
            "epoch_ordinal": seg["epoch"],
            "qualifying": True,
        }
        counters.inc("steady_pacer_segments_qualifying_total")
        counters.observe_min("steady_segment_rate_fps_min", rate)
        counters.observe_max("steady_segment_rate_fps_max", rate)
        counters.observe_min("steady_segment_mean_inter_send_ms_min", mean)
        counters.observe_max("steady_segment_mean_inter_send_ms_max", mean)
        counters.observe_max("steady_segment_frames_max", n)
        self._qual_rates.append(rate)
        self._qual_means.append(mean)
        counters.set_gauge("steady_pacer_rate_fps",
                           sum(self._qual_rates) / len(self._qual_rates))
        counters.set_gauge("pacer_mean_inter_send_ms_observed",
                           sum(self._qual_means) / len(self._qual_means))
        self.diag.on_segment(record)

    def _overshoot_reset(self):
        self._ov_last_start = None
        self._ov_sum = 0.0
        self._ov_n = 0
        self._ov_frames = 0
        self._ov_break = False

    def _overshoot_track(self, send_start_ms, t_ms):
        self._ov_frames += 1
        if self._ov_last_start is not None and not self._ov_break:
            gap = send_start_ms - self._ov_last_start
            if gap < 200.0:
                self._ov_sum += gap - MEDIA_FRAME_MS - t_ms
                self._ov_n += 1
        self._ov_last_start = send_start_ms
        self._ov_break = False

    def _overshoot_close(self):
        if self._ov_frames >= 1000 and self._ov_n > 0:
            counters.observe_max("pacer_wake_overshoot_mean_ms_observed",
                                 self._ov_sum / self._ov_n)

    async def _pacer(self, pid=None):
        finished = False
        how = "normal_finish"
        reason = None
        gen_at_open = self.diag.active_gen
        # E1/E4 epoch creation at task start (synchronous; same rule, A.5).
        kind = "E1" if self.pacer_starts == 0 else "E4"
        self.pacer_starts += 1
        counters.inc("pacer_starts")
        self._epoch_create(kind, reason="pacer_start")
        self._segment_terminate("epoch_start", clean=True)
        self._overshoot_reset()
        try:
            while True:
                while True:
                    self._store_event.clear()
                    if self.future_audio_store:
                        break
                    await self._store_event.wait()
                item, meta = self._store_pop()
                if isinstance(item, GenerationEnd):
                    gen = self._gen_by_id(item.gen_id)
                    if gen is not None:
                        gen.marker_consumed = True
                    self.diag.on_store_marker("consume", item.gen_id,
                                              gen.resp_id if gen else None,
                                              item.reason)
                    if gen is not None and not gen.quiescent:
                        gen.quiescent = True
                        self._gen_sync(gen)
                        counters.set_gauge("still_stored_frames",
                                           self._queued_frames)
                        self.diag.on_quiescence(gen.gen_id, {
                            "queued": self._queued_frames,
                            "in_flight": self.in_flight_frames,
                            "residue": len(self.dl_buf),
                        })
                    await self._stop_tts("pacer_marker")
                    if not self.future_audio_store:
                        finished = True
                        break
                    continue
                pkt = item
                gen = meta.gen_obj if meta is not None else None
                self._head_gen = gen
                self._head_meta = meta
                self._head_state = "RESERVED_WAIT"
                self.in_flight_frames += 1
                self._sync_gauges()
                self.diag.on_store_pop(meta, self._queued_frames,
                                       self._backlog())
                # A.4.C pre-send protection: the owning generation's
                # SEND_FORBIDDEN flag is checked in the synchronous stretch.
                if gen is not None and gen.send_forbidden:
                    self._resolve_known_unsent(gen, meta)
                    continue
                deadline = self.media_epoch_ms + self.frame_index * MEDIA_FRAME_MS
                normal_floor = None
                if self.previous_audio_send_start_at is not None:
                    normal_floor = (self.previous_audio_send_start_at
                                    + MIN_SEND_START_INTERVAL_MS)
                guard = self.send_guard_until
                not_before = deadline
                if normal_floor is not None and normal_floor > not_before:
                    not_before = normal_floor
                if guard is not None and guard > not_before:
                    not_before = guard
                if (normal_floor is not None
                        and normal_floor >= deadline
                        and (guard is None or normal_floor >= guard)):
                    counters.inc("pacer_floor_bind_count")
                while True:
                    now = _now_ms()
                    if now >= not_before:
                        break
                    await asyncio.sleep(min(0.05, (not_before - now) / 1000.0))
                # A.6 lateness is evaluated at the pre-send wait decision point
                # (i.e. after the wait completes) so an event-loop stall that
                # elapses during the wait is still detected as a fatal stall.
                now = _now_ms()
                lateness = max(0.0, now - deadline)
                if lateness > MAX_REBASE_LATENESS_MS:
                    # A.6 Case B (pre-send): fatal stall.
                    how = "fatal_stall_pre_send"
                    await self._pacer_fatal_stall(gen, "lateness",
                                                  "known_unsent")
                    break
                if lateness > LATE_REBASE_THRESHOLD_MS:
                    # A.6 Case A: wall-clock phase reset (E2).
                    counters.inc("pacer_rebases")
                    counters.observe_max("pacer_rebase_max_lateness_ms", lateness)
                    self._segment_terminate("rebase_case_a", clean=False)
                    deadline = self._epoch_create("E2", reason="lateness_rebase")
                # Re-check after the wait: the flag may have been set meanwhile.
                if gen is not None and gen.send_forbidden:
                    self._resolve_known_unsent(gen, meta)
                    continue
                send_start = _now_ms()
                # rev-8 slow-send guard: each armed guard is checked against
                # exactly one next confirmed audio send start (in order).
                while self._pending_guards:
                    gdl = self._pending_guards.popleft()
                    violation = send_start < gdl - SPACING_EPSILON_MS
                    if violation:
                        counters.inc("slow_send_guard_violations")
                    self.diag.on_guard_check(send_start, gdl, violation)
                    break
                # post-terminal send invariant (owning generation only)
                if gen is not None and gen.send_forbidden:
                    counters.inc("post_terminal_sends_total")
                    gen.post_terminal_sends += 1
                self._head_state = "SEND_AWAIT"
                self.diag.on_send_intent(meta, pid)
                try:
                    await self.ws.send_bytes(pkt)
                except asyncio.CancelledError:
                    # cancellation inside the transport await: outcome unknown
                    counters.inc("send_outcome_unknown_frames")
                    # A.5 §2: a cancellation after transport entry arms the
                    # conservative guard (observation_time + 15 ms).
                    self.send_guard_until = (_now_ms()
                                             + MIN_SEND_START_INTERVAL_MS)
                    counters.set_state("send_guard_until",
                                       self.send_guard_until)
                    self._release_head()
                    raise
                except Exception as e:  # noqa: BLE001
                    counters.inc("send_failed_frames")
                    # A.5 §2: a failed send arms the conservative guard.
                    self.send_guard_until = (_now_ms()
                                             + MIN_SEND_START_INTERVAL_MS)
                    counters.set_state("send_guard_until",
                                       self.send_guard_until)
                    self._release_head()
                    how = "send_error"
                    reason = repr(e)
                    await self._send_error_termination(gen, e)
                    break
                completion = _now_ms()
                t_ms = completion - send_start
                counters.inc("sent_confirmed_frames")
                counters.audio_out_opus_frames += 1
                self._release_head()
                self.previous_audio_send_start_at = send_start
                counters.set_state("previous_audio_send_start_at", send_start)
                self.diag.on_send(meta, pid, diag.now())
                diag.cap_sent_opus(pkt, meta)
                if gen is not None:
                    gen.sent += 1
                    self._gen_note(gen, sent_confirmed=gen.sent)
                # media-clock epoch bookkeeping (A.5 wire-rate definition)
                self.sent_in_epoch += 1
                permitted = max(
                    0.0, 1.0 + math.floor(
                        (send_start - self.media_epoch_ms) / MEDIA_FRAME_MS))
                excess = self.sent_in_epoch - permitted
                counters.observe_max("wire_rate_excess_frames_max", excess)
                lead = max(0.0, (deadline - send_start) / MEDIA_FRAME_MS)
                counters.observe_max("pacer_lead_frames_max", lead)
                self.diag.on_r1f_send(meta, pid, self.epoch_ordinal,
                                      self.frame_index, self.sent_in_epoch,
                                      deadline, lateness, excess, t_ms,
                                      guard, normal_floor)
                self.frame_index += 1
                # connection-wide anti-burst minimum (across generations,
                # restarts and rebases — A.5).
                if self._last_send_start_ms is not None:
                    ival = send_start - self._last_send_start_ms
                    counters.observe_min("pacer_min_inter_send_ms_observed", ival)
                    if ival < MIN_SEND_START_INTERVAL_MS - SPACING_EPSILON_MS:
                        counters.inc("pacer_short_interval_count")
                self._last_send_start_ms = send_start
                self._overshoot_track(send_start, t_ms)
                self._segment_add(send_start)
                if t_ms > MAX_REBASE_LATENESS_MS:
                    # §2 very slow successful send: SENT, then fatal stall.
                    how = "fatal_stall_post_send"
                    await self._pacer_fatal_stall(gen, "slow_send", None)
                    break
                if t_ms > SLOW_SEND_THRESHOLD_MS:
                    counters.inc("slow_send_events")
                    self.send_guard_until = (completion
                                             + MIN_SEND_START_INTERVAL_MS)
                    counters.set_state("send_guard_until", self.send_guard_until)
                    self._pending_guards.append(self.send_guard_until)
                    self.diag.on_guard_arm(self.send_guard_until)
                    counters.observe_max("pacer_rebase_max_lateness_ms", t_ms)
                    self._segment_terminate("rebase_slow_send", clean=False)
                    counters.inc("pacer_rebases")
                    self._epoch_create("E3", reason="slow_send_rebase",
                                       anchor_ms=completion + MEDIA_FRAME_MS)
        except asyncio.CancelledError:
            how = "cancel_completed"
            if self._head_state == "SEND_AWAIT":
                counters.inc("send_outcome_unknown_frames")
                self._segment_mark_dirty()
                self._release_head()
            elif self._head_state == "RESERVED_WAIT":
                # known-unsent -> the owning transition's reason bucket
                self._resolve_known_unsent(self._head_gen, self._head_meta)
            raise
        except Exception as e:  # noqa: BLE001
            how = "exception"
            reason = repr(e)
            log.warning("pacer error: %s", e)
        finally:
            task = asyncio.current_task()
            if task is self.pacer_task:
                self.pacer_task = None
            self._pacer_release(task)
            self._segment_terminate("pacer_exit", clean=True)
            self._overshoot_close()
            if finished:
                await self._stop_tts("pacer_finally")
                self.state = State.LISTENING
                log.info("pacer drained -> LISTENING")
            self.diag.pacer_close(pid, how, reason, gen_at_open)
            if self._pacer_pid == pid:
                self._pacer_pid = None

    def _gen_by_id(self, gen_id):
        for gen in self.generations.values():
            if gen.gen_id == gen_id:
                return gen
        return None

    async def _cancel_pacer(self, reason=None):
        task = self.pacer_task
        if task is None or task.done():
            self.pacer_task = None
            self.diag.step("pacer_cancel_skipped", reason="no_live_pacer")
            return False
        self._cancel_reason = reason
        self.diag.step("pacer_cancel_requested", pacer_task_id=self._pacer_pid,
                       active_gen=self.diag.active_gen,
                       store_frames=self._queued_frames)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001
            log.warning("pacer cancel raised: %s", e)
        # clear only AFTER the await so a delta during cancel cannot adopt the
        # dying task's slot and leave a stranded idle pacer.
        if self.pacer_task is task:
            self.pacer_task = None
        self._pacer_release(task)
        return True

    # ---- upstream failure -------------------------------------------------

    async def _on_qwen_closed(self):
        gen = self._pick_terminal_gen()
        if gen is not None:
            self._invalidate_generation(gen, "UPSTREAM_CLOSED")
        await self._cancel_pacer("UPSTREAM_CLOSED")
        self._flush_store_reason("UPSTREAM_CLOSED")
        self._discard_residue("UPSTREAM_CLOSED")
        try:
            await self._stop_tts("upstream_closed")
        except Exception:  # noqa: BLE001
            pass
        self.current_resp_id = None
        self._current_gen = None
        self.state = State.LISTENING
        counters.upstream_errors += 1
        log.warning("qwen upstream closed; connection state cleaned up")