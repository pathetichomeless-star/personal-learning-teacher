"""R-1c temporary diagnostic instrumentation for the realtime lab bridge.

REMOVABLE SURFACE
-----------------
This module plus the ``diag.*`` call sites in ``app/turns.py`` and the ``/diag``
route in ``app/http.py`` are the *entire* R-1c diagnostic footprint. With
``RTL_DIAG`` unset every public helper returns immediately and the bridge
behaves exactly as it did before R-1c (no metadata is attached to queue items,
no extra HTTP route changes existing responses).

Env
---
  RTL_DIAG=1                  enable instrumentation (default: off)
  RTL_DIAG_DIR                journal/capture directory (default /tmp/rtl-diag)
  RTL_DIAG_CAPTURE=1          also capture raw audio (Phase 8)
  RTL_DIAG_CAPTURE_MAX        per-file byte cap for capture (default 4 MiB)

Assertions are **log-only**: they never alter control flow or timing decisions.
"""

import base64
import itertools
import json
import logging
import os
import struct
import time
from collections import deque

log = logging.getLogger("rtl.diag")

ENABLED = os.environ.get("RTL_DIAG", "0") == "1"
CAPTURE = ENABLED and os.environ.get("RTL_DIAG_CAPTURE", "0") == "1"
DIAG_DIR = os.environ.get("RTL_DIAG_DIR", "/tmp/rtl-diag")
CAPTURE_MAX = int(os.environ.get("RTL_DIAG_CAPTURE_MAX", str(4 * 1024 * 1024)))

JOURNAL_MAX = 20000
JOURNAL_TAIL = 400
TRANSCRIPT_MAX = 4000            # bounded per-kind transcript store
INTERVAL_VIOLATION_MS = 15.0     # 0.75 x FRAME_MS(20) -> "substantially faster"
FRAME_MS = 20.0

# ---- process-global state --------------------------------------------------

_gen_seq = itertools.count(1)
_pacer_seq = itertools.count(1)
_tx_seq = itertools.count(1)
_journal = deque(maxlen=JOURNAL_MAX)
_sends = deque(maxlen=8000)
_send_intents = deque(maxlen=8000)   # R-1d: frames about to be transmitted
_segments = deque(maxlen=4000)       # R-1f: raw steady-segment records (A.5)
_assertions = {}
_generations = {}
_transcripts = {"input": deque(maxlen=TRANSCRIPT_MAX),
                "output": deque(maxlen=TRANSCRIPT_MAX)}
_capture_state = {"qwen_pcm24_bytes": 0, "sent_opus_frames": 0,
                  "stopped": False, "dir": DIAG_DIR}
_started_at = time.monotonic()
_connections = {}


def now():
    return time.monotonic()


def _bump(name):
    _assertions[name] = _assertions.get(name, 0) + 1


def _entry(_k, **fields):
    """Append a journal entry. First parameter is deliberately named `_k` so it
    can never collide with a caller-supplied `kind`/`journal_kind` field."""
    fields["journal_kind"] = _k
    fields["j_ts"] = round(time.monotonic(), 6)
    _journal.append(fields)
    return fields


def violation(name, level=logging.WARNING, **fields):
    """Record a log-only assertion hit. Never raises, never alters flow."""
    if not ENABLED:
        return
    _bump(name)
    e = _entry(name, **fields)
    if name == "STALE_FRAME_VIOLATION":
        level = logging.ERROR
    log.log(level, "DIAG_ASSERT %s %s", name, json.dumps(e, default=str))


def gen_stats(gen):
    if gen is None:
        return None
    return _generations.setdefault(gen, {
        "gen": gen, "resp_ids": [], "status": None,
        "delta_events": 0, "delta_bytes": 0,
        "frames_encoded": 0, "frames_queued": 0, "frames_dropped": 0,
        "frames_sent": 0, "peak_queue_depth": 0,
        "created_ts": None, "end_ts": None, "sentinel_enqueued": 0,
        "sentinel_dequeued": 0, "sentinel_skipped": 0,
        "tts_starts": 0, "tts_stops": 0, "invalidated": None,
        "flush_discarded": 0,
        # rev-9 per-generation evidence fields
        "sealed": False, "terminal_tier": None, "terminal_reason": None,
        "sent_confirmed": 0, "flushed_by_reason": {},
        "source_bytes": 0, "admitted_bytes": 0,
        "guard_dropped_bytes": 0, "safety_truncated_bytes": 0,
        "residue_bytes_total": 0, "encode_failed": 0,
        "synthetic_tail_frames": 0, "synthetic_tail_encode_failures": 0,
        "cap_transitions": 0, "end_markers": 0, "tts_stop_emissions": 0,
        "cancel_attempts": 0, "post_terminal_sends": 0,
    })


# ---- per-frame metadata (owner: app/turns.py) ------------------------------
# The R-1f store holds raw encoded packets (A.3 direct representation); this
# module only consumes metadata objects supplied by the connection. No diag
# object ever holds an encoded packet, so the single-store sentinel walk is
# unaffected by diagnostics.


class Diag:
    """Per-connection diagnostic context. All methods are no-ops when disabled."""

    def __init__(self, frame_ms=FRAME_MS):
        self.sid = None
        self.frame_ms = frame_ms
        self.active_gen = 0
        self.active_resp_id = None
        self.tts_gen = None
        self.tts_resp_id = None
        self.tts_pacer_id = None
        self.frame_seq = 0
        self.invalidated = set()
        self.live_pacers = set()
        self.pacer_gen = {}
        self.last_send_ts = {}
        self.last_sent_seq = None
        self.intervals = deque(maxlen=4000)
        self.closes = 0

    # ---- lifecycle -------------------------------------------------------

    def bind(self, sid):
        if not ENABLED:
            return
        self.sid = sid
        _connections[sid] = self
        _entry("conn_open", sid=sid)

    def conn_close(self):
        if not ENABLED:
            return
        self.closes += 1
        _entry("conn_close", sid=self.sid)
        # release the per-connection registry entry (no unbounded growth)
        if self.sid is not None:
            _connections.pop(self.sid, None)

    # ---- Phase 2: Qwen event instrumentation -----------------------------

    def on_event(self, etype, rid=None, extra=None):
        if not ENABLED:
            return
        _entry("qwen_event", sid=self.sid, etype=etype, resp_id=rid,
               gen=self.gen_for(rid), active_gen=self.active_gen,
               active_resp_id=self.active_resp_id,
               current_resp_id=self.active_resp_id,
               extra=extra)

    def on_response_created(self, rid, gen_id=None):
        if not ENABLED:
            return None
        self.active_gen = next(_gen_seq) if gen_id is None else gen_id
        self.active_resp_id = rid
        self.frame_seq = 0
        st = gen_stats(self.active_gen)
        st["resp_ids"].append(rid)
        st["created_ts"] = round(now(), 6)
        _entry("generation_created", sid=self.sid, gen=self.active_gen,
               resp_id=rid)
        return self.active_gen

    def gen_for(self, rid):
        if not ENABLED or rid is None:
            return None
        for gen, st in _generations.items():
            if rid in st["resp_ids"]:
                return gen
        return None

    def on_delta(self, rid, nbytes, nframes):
        if not ENABLED:
            return
        st = gen_stats(self.gen_for(rid))
        if st:
            st["delta_events"] += 1
            st["delta_bytes"] += nbytes
            st["frames_encoded"] += nframes

    def on_response_end(self, etype, rid, status):
        if not ENABLED:
            return
        st = gen_stats(self.gen_for(rid))
        if st:
            st["end_ts"] = round(now(), 6)
            if etype == "response.done":
                st["status"] = status
        _entry("response_end", sid=self.sid, etype=etype, resp_id=rid,
               gen=self.gen_for(rid), status=status)

    def on_transcript(self, kind, text_delta, resp_id=None, full_text=None,
                      is_final=False, item_id=None):
        """Bounded, gated capture of input/output transcripts (ITEM 3a).

        `kind` selects the per-kind store ("input"/"output"; unknown kinds get
        their own bounded deque). Store is exposed as
        ``snapshot()["transcripts"]``.

        `resp_id` is a genuine response id only (output events); input events
        pass their own `item_id` — kept as a separate key so deltas can be
        joined to the matching completed event without mislabelling either.
        """
        if not ENABLED:
            return
        store = _transcripts.get(kind)
        if store is None:
            store = _transcripts.setdefault(kind, deque(maxlen=TRANSCRIPT_MAX))
        text = full_text if full_text is not None else text_delta
        store.append({
            "kind": kind,
            "resp_id": resp_id,
            "item_id": item_id,
            "gen": self.gen_for(resp_id),
            "text": text,
            "ts": round(now(), 6),
            "seq": next(_tx_seq),
            "is_final": bool(is_final),
        })

    def on_cancel_sent(self):
        if ENABLED:
            _entry("response_cancel_sent", sid=self.sid,
                   active_gen=self.active_gen, active_resp_id=self.active_resp_id)

    def on_cancel_skipped(self, reason):
        if ENABLED:
            _entry("response_cancel_skipped", sid=self.sid, reason=reason,
                   active_gen=self.active_gen, active_resp_id=self.active_resp_id)

    # ---- Phase 3 (rev-9): single store ----------------------------------

    def on_store_admit(self, meta, store_frames, backlog_frames, store_bytes):
        """A frame was admitted into future_audio_store (A.3/A.2)."""
        if not ENABLED:
            return
        st = gen_stats(meta.gen)
        if st:
            st["frames_queued"] += 1
            st["peak_queue_depth"] = max(st["peak_queue_depth"], backlog_frames)
        _entry("enqueue", sid=self.sid, resp_id=meta.resp_id, gen=meta.gen,
               frame_seq=meta.seq, kind=meta.kind,
               store_frames=store_frames, backlog_frames=backlog_frames,
               store_bytes=store_bytes, t_enq=round(meta.t_enq, 6)
               if meta.t_enq else None)

    def on_store_flush(self, active_gen, reason, frames, markers,
                       residue_bytes, detail=None):
        """Reason-scoped store/head flush (A.4.B); frames = dispositioned count."""
        if not ENABLED:
            return
        st = gen_stats(active_gen)
        if st:
            st["flush_discarded"] += frames
        _entry("flush", sid=self.sid, active_gen=active_gen, reason=reason,
               frames=frames, markers=markers, residue_bytes=residue_bytes,
               detail=detail)

    def on_store_pop(self, meta, store_frames, backlog_frames):
        if not ENABLED:
            return
        _entry("store_pop", sid=self.sid, resp_id=meta.resp_id, gen=meta.gen,
               frame_seq=meta.seq, store_frames=store_frames,
               backlog_frames=backlog_frames)

    def on_store_marker(self, phase, gen_id, resp_id, reason=None):
        if not ENABLED:
            return
        _entry("store_marker_" + phase, sid=self.sid, gen=gen_id,
               resp_id=resp_id, reason=reason)

    # ---- Phase 4b (rev-9): epochs / segments / guard / quiescence --------

    def on_epoch(self, kind, ordinal, pacer_task_id, anchor_ms, reason=None,
                 frame_index=0, sent_in_epoch=0):
        if not ENABLED:
            return
        _entry("media_epoch", sid=self.sid, kind=kind, epoch_ordinal=ordinal,
               pacer_task_id=pacer_task_id, anchor_ms=round(anchor_ms, 6),
               reason=reason, frame_index=frame_index,
               sent_in_epoch=sent_in_epoch)

    def on_r1f_send(self, meta, pid, ordinal, frame_index, sent_in_epoch,
                    deadline_ms, lateness_ms, wire_excess, t_ms,
                    guard_ms, floor_ms):
        if not ENABLED:
            return
        _entry("r1f_send", sid=self.sid, pacer_task_id=pid,
               resp_id=meta.resp_id if meta else None,
               gen=meta.gen if meta else None,
               frame_seq=meta.seq if meta else None,
               epoch_ordinal=ordinal, frame_index=frame_index,
               sent_in_epoch=sent_in_epoch,
               deadline_ms=round(deadline_ms, 6) if deadline_ms is not None else None,
               lateness_ms=round(lateness_ms, 6) if lateness_ms is not None else None,
               wire_excess=wire_excess,
               t_ms=round(t_ms, 6) if t_ms is not None else None,
               guard_ms=round(guard_ms, 6) if guard_ms is not None else None,
               floor_ms=round(floor_ms, 6) if floor_ms is not None else None)

    def on_segment(self, record):
        """Normative raw steady-segment record (A.5)."""
        if not ENABLED:
            return
        _segments.append(record)
        _entry("steady_segment", sid=self.sid, **record)

    def on_guard_arm(self, deadline_ms):
        if not ENABLED:
            return
        _entry("slow_guard_armed", sid=self.sid,
               deadline_ms=round(deadline_ms, 6))

    def on_guard_check(self, start_ms, deadline_ms, violation):
        if not ENABLED:
            return
        _entry("slow_guard_check", sid=self.sid, start_ms=round(start_ms, 6),
               deadline_ms=round(deadline_ms, 6), violation=violation)

    def on_generation_seal(self, gen_id, resp_id, branch, residue_bytes,
                           store_frames, backlog_frames, tail_bytes=None):
        if not ENABLED:
            return
        _entry("generation_seal", sid=self.sid, gen=gen_id, resp_id=resp_id,
               branch=branch, residue_bytes=residue_bytes,
               store_frames=store_frames, backlog_frames=backlog_frames,
               tail_bytes=tail_bytes)

    def on_generation_terminal(self, gen_id, resp_id, tier, reason):
        if not ENABLED:
            return
        _entry("generation_terminal", sid=self.sid, gen=gen_id, resp_id=resp_id,
               tier=tier, reason=reason)

    def on_cap_transition(self, gen_id, route, residue_bytes, backlog_frames):
        if not ENABLED:
            return
        _entry("store_cap_transition", sid=self.sid, gen=gen_id, route=route,
               residue_bytes=residue_bytes, backlog_frames=backlog_frames)

    def on_byte_cap(self, gen_id, step, **fields):
        if not ENABLED:
            return
        _entry("byte_cap", sid=self.sid, gen=gen_id, step=step, **fields)

    def on_late_event(self, etype, rid, classified, gen_id=None):
        """Tombstone absorption of a late upstream event (A.4.A/A.9)."""
        if not ENABLED:
            return
        _entry("late_event", sid=self.sid, etype=etype, resp_id=rid,
               classified=classified, gen=gen_id)

    def on_barge_bits(self, bits, results):
        if not ENABLED:
            return
        _entry("barge_bits", sid=self.sid, bits=bits, results=results)

    def on_gen_fields(self, gen_id, **fields):
        """Merge per-generation evidence fields (rev-9)."""
        if not ENABLED:
            return
        st = gen_stats(gen_id)
        if st:
            st.update(fields)

    def on_quiescence(self, gen_id, snap):
        if not ENABLED:
            return
        _entry("quiescence", sid=self.sid, gen=gen_id, **snap)

    def mark_invalidated(self, gen, reason, also_resp_id=None):
        if not ENABLED or gen is None:
            return
        self.invalidated.add(gen)
        st = gen_stats(gen)
        if st:
            st["invalidated"] = reason
        # R-1d: record which response id the invalidation was attributed to,
        # and raise a log-only GEN_SELECTION_MISMATCH when that response id
        # maps to a different generation than the one being invalidated.
        attr_gen = self.gen_for(also_resp_id)
        _entry("generation_invalidated", sid=self.sid, gen=gen, reason=reason,
               active_gen=self.active_gen, also_resp_id=also_resp_id,
               also_resp_id_gen=attr_gen)
        if also_resp_id is not None and attr_gen is not None and attr_gen != gen:
            violation("GEN_SELECTION_MISMATCH", invalidated_gen=gen,
                      resp_id=also_resp_id, resp_id_gen=attr_gen,
                      reason=reason, active_gen=self.active_gen, sid=self.sid)

    # ---- Phase 4: pacer --------------------------------------------------

    def pacer_open(self, pid=None):
        if not ENABLED:
            return None
        pid = next(_pacer_seq) if pid is None else pid
        self.live_pacers.add(pid)
        _entry("pacer_create", sid=self.sid, pacer_task_id=pid,
               active_gen=self.active_gen, active_resp_id=self.active_resp_id)
        _entry("pacer_start", sid=self.sid, pacer_task_id=pid)
        if len(self.live_pacers) > 1:
            violation("MULTIPLE_PACER_VIOLATION",
                      live=sorted(self.live_pacers), sid=self.sid,
                      new_pacer=pid,
                      generations={str(k): v for k, v in self.pacer_gen.items()})
        self.pacer_gen[pid] = self.active_gen
        return pid

    def pacer_close(self, pid, how, reason=None, assigned_gen=None):
        if not ENABLED:
            return
        self.live_pacers.discard(pid)
        self.pacer_gen.pop(pid, None)
        _entry("pacer_" + how, sid=self.sid, pacer_task_id=pid,
               assigned_gen=assigned_gen, active_gen=self.active_gen,
               reason=reason)

    def on_send_intent(self, meta, pid):
        """R-1d: record that a frame is ABOUT to begin transmission.

        Called immediately before ``ws.send_bytes``. ``on_send`` marks the
        same record resolved once the write returns. An intent that is never
        resolved means a frame BEGAN transmission and its fate is unknown
        (e.g. the pacer was cancelled at the send await). Log-only.
        """
        if not ENABLED or meta is None:
            return None
        e = {"frame_seq": meta.seq, "gen": meta.gen, "resp_id": meta.resp_id,
             "pacer_task_id": pid, "kind": meta.kind,
             "t_intent": round(now(), 6), "resolved": False, "t_send": None}
        _send_intents.append(e)
        meta.intent = e
        return e

    def on_send(self, meta, pid, ts):
        if not ENABLED:
            return
        prev = self.last_send_ts.get(pid)
        ival = None
        if prev is not None:
            ival = round((ts - prev) * 1000.0, 3)
            self.intervals.append(ival)
            if ival < INTERVAL_VIOLATION_MS:
                violation("PACING_INTERVAL_VIOLATION", pacer_task_id=pid,
                          interval_ms=ival, frame_seq=meta.seq if meta else None,
                          gen=meta.gen if meta else None, sid=self.sid)
        self.last_send_ts[pid] = ts
        if meta is not None:
            meta.pacer_id = pid
            meta.t_send = ts
            self.last_sent_seq = meta.seq
            # R-1d: the transmission we announced in on_send_intent completed.
            it = meta.intent
            if it is not None and not it.get("resolved"):
                it["resolved"] = True
                it["t_send"] = round(ts, 6)
            _sends.append({
                "frame_seq": meta.seq, "gen": meta.gen, "resp_id": meta.resp_id,
                "pacer_task_id": pid, "t_send": round(ts, 6),
                "interval_ms": ival,
                "queue_latency_ms": (round((ts - meta.t_enq) * 1000.0, 3)
                                     if meta.t_enq else None),
                "invalidated": meta.gen in self.invalidated,
            })
            st = gen_stats(meta.gen)
            if st:
                st["frames_sent"] += 1
            if meta.gen in self.invalidated:
                violation("STALE_FRAME_VIOLATION",
                          old_gen=meta.gen, new_gen=self.active_gen,
                          resp_id=meta.resp_id, frame_seq=meta.seq,
                          pacer_task_id=pid,
                          send_ts=round(ts, 6), sid=self.sid)
        _entry("send", sid=self.sid, pacer_task_id=pid,
               resp_id=meta.resp_id if meta else None,
               gen=meta.gen if meta else None,
               frame_seq=meta.seq if meta else None,
               interval_ms=ival,
               t_enq=round(meta.t_enq, 6) if meta and meta.t_enq else None,
               t_send=round(ts, 6),
               queue_latency_ms=(round((ts - meta.t_enq) * 1000.0, 3)
                                 if meta and meta.t_enq else None),
               e2e_ms=(round((ts - meta.t_qwen) * 1000.0, 3)
                       if meta and meta.t_qwen else None))

    # ---- Phase 5: TTS boundary ------------------------------------------

    def on_tts_start(self, resp_id, gen, pacer_id):
        if not ENABLED:
            return
        self.tts_gen = gen
        self.tts_resp_id = resp_id
        self.tts_pacer_id = pacer_id
        st = gen_stats(gen)
        if st:
            st["tts_starts"] += 1
        _entry("tts_start", sid=self.sid, resp_id=resp_id, gen=gen,
               active_gen=self.active_gen, pacer_task_id=pacer_id)

    def on_tts_stop(self, resp_id, gen, active_gen, pacer_id, caller):
        if not ENABLED:
            return
        st = gen_stats(gen)
        if st:
            st["tts_stops"] += 1
        _entry("tts_stop", sid=self.sid, resp_id=resp_id, gen=gen,
               active_gen=active_gen, pacer_task_id=pacer_id, caller=caller)
        if gen is not None and active_gen is not None and gen < active_gen:
            violation("STALE_TTS_STOP_VIOLATION", stop_gen=gen,
                      active_gen=active_gen, resp_id=resp_id,
                      pacer_task_id=pacer_id, caller=caller, sid=self.sid)
        self.tts_gen = None
        self.tts_resp_id = None
        self.tts_pacer_id = None

    def on_tts_start_skipped(self, reason):
        if ENABLED:
            _entry("tts_start_skipped", sid=self.sid, reason=reason,
                   tts_gen=self.tts_gen, active_gen=self.active_gen)

    # ---- Phase 6: barge-in ----------------------------------------------

    def barge_snapshot(self, partial):
        if not ENABLED:
            return
        snap = {
            "sid": self.sid,
            "active_gen": self.active_gen,
            "active_resp_id": self.active_resp_id,
            "tts_gen": self.tts_gen,
            "tts_resp_id": self.tts_resp_id,
            "invalidated_gens": sorted(self.invalidated),
        }
        snap.update(partial)          # caller keys win; never duplicate kwargs
        _entry("barge_snapshot", **snap)

    def step(self, name, **fields):
        if not ENABLED:
            return
        d = {"step": name, "ts": round(now(), 6), "active_gen": self.active_gen}
        d.update(fields)
        _entry("barge_step", **d)

    # ---- snapshot --------------------------------------------------------

    def snapshot(self):
        if not ENABLED:
            return {"enabled": False}
        iv = list(self.intervals)
        pct = None
        if iv:
            s = sorted(iv)
            pct = {"p50": s[len(s) // 2], "p95": s[int(len(s) * 0.95)],
                   "min": s[0], "max": s[-1], "n": len(s)}
        # R-1d: send-intent accounting. Chosen (log-only) semantics for
        # SEND_INTENT_UNRESOLVED: fires when, at snapshot time, one or more
        # frames BEGAN transmission (on_send_intent) and were never observed
        # to complete (no matching on_send) -> their fate is unknown.
        _unres = [e for e in _send_intents if not e.get("resolved")]
        _unres_inv = [e for e in _unres if e.get("gen") in self.invalidated]
        if _unres:
            violation("SEND_INTENT_UNRESOLVED", unresolved=len(_unres),
                      unresolved_invalidated_gen=len(_unres_inv), sid=self.sid,
                      sample=[{k: e.get(k) for k in
                               ("frame_seq", "gen", "resp_id", "pacer_task_id",
                                "t_intent")} for e in _unres[:5]])
        return {
            "enabled": True,
            "uptime_s": round(now() - _started_at, 3),
            "journal_entries": len(_journal),
            "assertions": dict(_assertions),
            "assertions_total": sum(_assertions.values()),
            "generations": {str(k): v for k, v in sorted(_generations.items())},
            "generation_count": len(_generations),
            "per_conn": {
                "sid": self.sid, "active_gen": self.active_gen,
                "active_resp_id": self.active_resp_id,
                "live_pacers": sorted(self.live_pacers),
                "invalidated_gens": sorted(self.invalidated),
                "tts_gen": self.tts_gen, "conns_closed": self.closes,
            },
            "connections": {sid: c.snapshot_conn()
                            for sid, c in _connections.items()},
            "send_intervals_ms": pct,
            "steady_segments": list(_segments),
            "send_intents": list(_send_intents)[-200:],
            "send_intent_unresolved": len(_unres),
            "send_intent_unresolved_invalidated_gen": len(_unres_inv),
            "send_timeline": list(_sends),
            "transcripts": {k: list(v) for k, v in _transcripts.items()},
            "capture": dict(_capture_state),
            "journal_tail": list(_journal)[-JOURNAL_TAIL:],
        }

    def snapshot_conn(self):
        return {
            "sid": self.sid,
            "active_gen": self.active_gen,
            "active_resp_id": self.active_resp_id,
            "live_pacers": sorted(self.live_pacers),
            "invalidated_gens": sorted(self.invalidated),
            "tts_gen": self.tts_gen,
            "conns_closed": self.closes,
        }

    def journal_tail(self, n=JOURNAL_TAIL):
        return list(_journal)[-n:]

    def reset(self):
        if not ENABLED:
            return
        _journal.clear()
        _assertions.clear()


# ---- fail-safe wrapping ----------------------------------------------------
# Guarantee: a fault inside a diagnostic hook can NEVER alter bridge control
# flow. Every hook called from a control path is wrapped so any exception is
# downgraded to a counter + log line.

def _safe(fn):
    def wrapper(self, *a, **kw):
        if not ENABLED:
            return None
        try:
            return fn(self, *a, **kw)
        except Exception as e:  # noqa: BLE001
            _bump("DIAG_INTERNAL_ERROR")
            log.warning("diag internal error in %s: %r", fn.__name__, e)
            return None
    wrapper.__name__ = fn.__name__
    return wrapper


for _name in ("bind", "conn_close", "on_event", "on_response_created",
              "on_delta", "on_response_end", "on_cancel_sent",
              "on_cancel_skipped", "on_store_admit", "on_store_flush",
              "on_store_pop", "on_store_marker", "on_epoch", "on_r1f_send",
              "on_segment", "on_guard_arm", "on_guard_check",
              "on_generation_seal", "on_generation_terminal",
              "on_cap_transition", "on_byte_cap", "on_late_event",
              "on_barge_bits", "on_gen_fields", "on_quiescence", "mark_invalidated",
              "pacer_open", "pacer_close", "on_send", "on_send_intent",
              "on_tts_start", "on_tts_stop", "on_tts_start_skipped",
              "barge_snapshot", "step", "on_transcript"):
    setattr(Diag, _name, _safe(getattr(Diag, _name)))


# ---- Phase 8: raw audio capture -------------------------------------------

def _cap_path(name):
    return os.path.join(CAPTURE_DIR, name)


CAPTURE_DIR = DIAG_DIR


def _ensure_dir():
    if not CAPTURE:
        return False
    try:
        os.makedirs(CAPTURE_DIR, exist_ok=True)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("diag capture dir failed: %s", e)
        return False


def cap_qwen_pcm(chunk):
    """A. Raw Qwen PCM24 s16le mono, exactly as reassembled pre-encode."""
    if not CAPTURE or _capture_state["stopped"]:
        return
    if _capture_state["qwen_pcm24_bytes"] >= CAPTURE_MAX:
        _capture_state["stopped"] = True
        return
    try:
        if not _ensure_dir():
            return
        with open(_cap_path("qwen_pcm24.raw"), "ab") as f:
            f.write(chunk)
        _capture_state["qwen_pcm24_bytes"] += len(chunk)
    except Exception:  # noqa: BLE001
        pass


def cap_sent_opus(pkt, meta):
    """B. Exact Opus packet handed to the XiaoZhi wire, length-prefixed."""
    if not CAPTURE or _capture_state["stopped"]:
        return
    try:
        if not _ensure_dir():
            return
        with open(_cap_path("sent_opus.bin"), "ab") as f:
            f.write(struct.pack(">I", len(pkt)))
            f.write(pkt)
        with open(_cap_path("sent_opus.jsonl"), "a") as f:
            f.write(json.dumps({
                "idx": _capture_state["sent_opus_frames"],
                "resp_id": meta.resp_id if meta else None,
                "gen": meta.gen if meta else None,
                "frame_seq": meta.seq if meta else None,
                "pacer_task_id": meta.pacer_id if meta else None,
                "t_send": meta.t_send if meta else None,
                "bytes": len(pkt),
            }) + "\n")
        _capture_state["sent_opus_frames"] += 1
    except Exception:  # noqa: BLE001
        pass


def capture_info():
    out = {"enabled": CAPTURE, "dir": CAPTURE_DIR}
    for name in ("qwen_pcm24.raw", "sent_opus.bin", "sent_opus.jsonl"):
        p = _cap_path(name)
        try:
            out[name] = os.path.getsize(p) if os.path.exists(p) else 0
        except Exception:  # noqa: BLE001
            out[name] = -1
    out.update(_capture_state)
    return out


def b64decode_delta(s):
    return base64.b64decode(s, validate=True)


# ---- HTTP providers (wired in app/http.py) --------------------------------

def _global_snapshot():
    """Snapshot for the /diag route: globals + the most recent connection."""
    if not ENABLED:
        return {"enabled": False}
    last = None
    for c in _connections.values():
        last = c
    return (last or Diag()).snapshot()


def _global_reset():
    """Clear journal + assertion tallies + generation aggregates."""
    if not ENABLED:
        return
    _journal.clear()
    _assertions.clear()
    _generations.clear()
    _sends.clear()
    _send_intents.clear()
    _segments.clear()
    for _v in _transcripts.values():
        _v.clear()


SNAPSHOT_PROVIDER = _global_snapshot
RESET_PROVIDER = _global_reset
