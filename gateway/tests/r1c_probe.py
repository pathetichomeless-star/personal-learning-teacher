#!/usr/bin/env python3
"""R-1c instrumented reproduction probe (runs inside the bridge container).

Zero-cost, deterministic: a controllable fake Qwen Realtime upstream plus an
instrumented XiaoZhi client that mirrors py-xiaozhi's real audio semantics
(`tts start` does NOT clear the TTS FIFO; `tts stop` clears it only when
`keep_listening` is true).

Usage:
  python /app/tests/r1c_probe.py --test all
  python /app/tests/r1c_probe.py --test barge --scenario barge_cancel_first
  python /app/tests/r1c_probe.py --test barge --client-stall-ms 1500

Tests:
  t1  long normal response, no barge-in   -> can the downlink queue overflow?
  t2  active voice barge-in (real order)  -> stale-frame / stale-tts / multi-pacer
  t3  rapid response boundary             -> pacer-finally / tts ordering races

Prints a single JSON blob between R1C_RESULT_BEGIN/END markers.
"""

import argparse
import asyncio
import base64
import json
import math
import os
import struct
import sys
import time
import traceback

sys.path.insert(0, "/app")

import aiohttp
from aiohttp import WSMsgType, web
import opuslib

FAKE_PORT = 9988
BRIDGE_WS = "ws://127.0.0.1:8110/xiaozhi/v1/"
BRIDGE_HTTP = "http://127.0.0.1:8111"
FRAME_BYTES = 960          # 480 samples s16le = 20 ms @ 24 kHz
ENCODE_CHUNKS = 60         # chunks per turn for the default scenario
SAMPLE_RATE_OUT = 24000
OUT_FRAME_SAMPLES = 480
TTS_FIFO_MAX_S = 10.0      # mirrors py-xiaozhi _TTS_FIFO_MAX_S

# ---- R-1e ITEM 2: capture reset discipline --------------------------------
# R-1d established a real trap: the three capture files AND the bridge's
# `_capture_state` accumulate PER PROCESS for the lifetime of that process, and
# `POST /diag/reset` does NOT clear them (app/diag.py `_global_reset` only
# clears journal/assertions/generations/sends/intents/transcripts). A capture
# taken after any earlier traffic in the same process therefore contains
# PREDECESSOR data, and the analyzer's `n_src` silently covers more than the
# intended run.
#
# PRIMARY recommendation: the FRESH-SIDE-PROCESS approach -- start a brand-new
# side instance so `_capture_state` starts at zero (the count and the files are
# then in agreement by construction). That is a runner responsibility and needs
# no help from the probe.
#
# BELT-AND-BRACES (what this flag does): explicitly TRUNCATE the three capture
# files in RTL_DIAG_DIR before any traffic starts, and record path + sizes
# before/after + timestamp so the truncation is auditable after the fact.
# NOTE the honest limitation: truncation alone makes the FILES match the
# intended run, but it CANNOT lower the bridge's in-process
# `_capture_state["qwen_pcm24_bytes"]` counter, so after a truncate-without-
# restart `capture.qwen_pcm24_bytes` stays high while the file on disk is
# small. That divergence is exactly why the fresh side process is primary; the
# probe reports BOTH numbers so the mismatch can never be hidden.
CAPTURE_DIR = os.environ.get("RTL_DIAG_DIR", "/tmp/rtl-diag")
CAPTURE_FILES = ("qwen_pcm24.raw", "sent_opus.bin", "sent_opus.jsonl")
CAPTURE_RESET = []         # append-only audit log of every truncation performed

HELLO = {
    "type": "hello", "version": 1, "transport": "websocket",
    "audio_params": {"format": "opus", "sample_rate": 16000,
                     "channels": 1, "frame_duration": 20},
}
LISTEN_START = {"session_id": "", "type": "listen",
                "state": "start", "mode": "realtime"}

BENIGN_CANCEL_ERROR = {
    "type": "error",
    "error": {"type": "invalid_request_error",
              "code": "response_cancel_not_active",
              "message": "no active response to cancel", "param": None},
}


WAVE = "pattern"           # "pattern" | "sine" | "file"
WAVE_GAP = 0.0             # seconds between upstream deltas (0 = as fast as possible)
FILE_CHUNKS = []           # 960-byte 24 kHz chunks loaded from --wave-file
U1_PKTS = []               # pre-encoded Opus 16 kHz uplink packets
U2_PKTS = []
UP2_AT = 1e9               # seconds after uplink start when utterance 2 begins
INTERRUPT_AFTER_PLAYBACK_MS = 0   # 0 = disabled (time-based --up2-at only)
ATTEMPTS = 1               # --attempts: repeat the full cycle N times
INTERRUPT_DELAYS = []      # parsed per-attempt playback delays (ms); [] = none
LOAD_FAILURES = []         # fixture-encode failures (never silently dropped)

# ---- R-1d ITEM 1/2: LIVE auto-cancel barge variant -------------------------
# The real-Qwen order when the user speaks over a response that is STILL
# GENERATING is: response.done{status="cancelled"} for the active response,
# THEN input_audio_buffer.speech_started. The response was live at the cancel.
# These knobs script that shape deterministically.
LATE_DELTA_CHUNKS = 20            # --late-delta-chunks (old-response deltas
                                  # that arrive AFTER the cancel)
LIVE_PRE_DELTA_CHUNKS = 100       # deltas streamed BEFORE the mid-stream
                                  # cancel (100 x 960 B = 2 s of audio)
EXTREME_LATE_DELTA_CHUNKS = 150   # auto_cancel_late_delta floor
# ~15 ms/chunk (realtime-ish). Deliberately a touch AHEAD of the bridge's
# 20 ms pacer so a live downlink backlog exists at the cancel instant; with a
# 20 ms-equal cadence the queue sits empty, the pacer drains the sentinel
# before the 1 ms-later speech_started and Path B is never entered (which is
# NOT the variant under test).
LIVE_DELTA_GAP_S = 0.015
LATE_DELTA_GAP_S = 0.015

# ---- R-1e ITEM 1: bursty overflow scenario --------------------------------
# Models the MEASURED real Qwen burst structure from the previous real run's
# journal -- NOT an instantaneous dump. Observed upstream: micro-bursts of
# ~12-16 frames delivered within ~0.14-0.19 ms, spaced ~40 ms apart, with
# individual `response.audio.delta` events carrying delta_b64_len = 20480
# (~21.3 frames) at 39-45 ms spacing -> an effective arrival rate of ~154
# frames/s against a measured ~47.4 fps pacer drain. Overflow therefore needs a
# response that STREAMS TO COMPLETION, not one cancelled after ~1 s.
BURST_CHUNKS = 16           # --burst-chunks   (chunks per micro-burst)
BURST_GAP_MS = 40.0         # --burst-gap-ms   (gap between micro-bursts)
OVERFLOW_CHUNKS = 900       # --overflow-chunks(total chunks ~= 18 s of audio)

# Scenario name registry (argparse choices + dispatch).
SCENARIOS = ("long_pressure", "barge_cancel_first", "barge_repeat_content",
             "auto_cancel_first", "rapid_boundary",
             "auto_cancel_live", "auto_cancel_late_delta",
             "overflow_bursty")


def _exc_record(stage, exc, extra=None):
    """Full, reportable record of a caught exception. NEVER swallow silently.

    Captures type, message, repr and a complete traceback (works both inside
    and outside an `except` block, and for exceptions returned by
    `asyncio.gather(..., return_exceptions=True)`).
    """
    try:
        tb = "".join(traceback.format_exception(
            type(exc), exc, getattr(exc, "__traceback__", None)))
    except Exception:  # noqa: BLE001
        tb = "<traceback unavailable>"
    rec = {
        "stage": stage,
        "type": type(exc).__name__,
        "message": str(exc),
        "repr": repr(exc),
        "traceback": tb,
    }
    if extra:
        rec.update(extra)
    return rec


def load_wave_file(path):
    global FILE_CHUNKS
    raw = open(path, "rb").read()
    if len(raw) % 2:
        raw = raw[:-1]
    FILE_CHUNKS = [raw[i:i + FRAME_BYTES]
                   for i in range(0, len(raw) - FRAME_BYTES + 1, FRAME_BYTES)]
    return len(FILE_CHUNKS)


def load_uplink(path, enc):
    """Encode raw 16 kHz s16le PCM into 20 ms Opus packets.

    Returns (packets, failures). Any per-packet encode failure is RECORDED
    (offset + index + traceback) and returned to the caller — the packet is
    NOT silently dropped without a report (that used to change the intended
    frame count invisibly).
    """
    raw = open(path, "rb").read()
    out = []
    failures = []
    idx = 0
    for i in range(0, len(raw) - 639, 640):        # 320 samples @16 kHz = 20 ms
        try:
            out.append(enc.encode(raw[i:i + 640], 320))
        except Exception as e:  # noqa: BLE001
            failures.append(_exc_record("load_uplink", e, {
                "path": path, "byte_offset": i, "packet_index": idx,
                "raw_len": len(raw),
            }))
        idx += 1
    return out, failures


def reset_capture(directory=None):
    """R-1e ITEM 2: truncate the three capture files, with an audit record.

    Must be called BEFORE any traffic is generated. Each file's existence, size
    before and size after are recorded, so the truncation is auditable after the
    fact and a zero-length "before" cannot be mistaken for "nothing was there".

    Honest limitation (see CAPTURE_DIR docs): this cannot lower the bridge's
    in-process `_capture_state` counters, so a truncate-without-restart leaves
    `capture.qwen_pcm24_bytes` disagreeing with the file on disk. The probe
    reports both so the divergence is visible rather than hidden.
    """
    d = directory or CAPTURE_DIR
    rec = {"dir": d, "ts": round(time.time(), 6),
           "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
           "files": [], "errors": []}
    try:
        os.makedirs(d, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        rec["errors"].append(_exc_record("reset_capture.makedirs", e,
                                         {"dir": d}))
        CAPTURE_RESET.append(rec)
        return rec
    for name in CAPTURE_FILES:
        p = os.path.join(d, name)
        ent = {"path": p, "existed_before": os.path.exists(p),
               "size_before": None, "size_after": None, "truncated": False}
        try:
            ent["size_before"] = os.path.getsize(p) if ent["existed_before"] else 0
            with open(p, "wb"):
                pass                      # create-or-truncate to zero length
            ent["size_after"] = os.path.getsize(p)
            ent["truncated"] = True
        except Exception as e:  # noqa: BLE001
            rec["errors"].append(_exc_record("reset_capture.truncate", e,
                                             {"path": p}))
        rec["files"].append(ent)
    CAPTURE_RESET.append(rec)
    print("R1C_STATE CAPTURE_RESET " + json.dumps(rec, default=str),
          file=sys.stderr)
    return rec


def parse_delay_list(s):
    """Parse `--interrupt-after-playback-ms`.
    comma-separated per-attempt list (e.g. "50,400,900"). An empty/invalid
    value fails LOUDLY (never silently coerced to 0).
    """
    vals = []
    for part in str(s).split(","):
        part = part.strip()
        if part == "":
            continue
        try:
            vals.append(int(part))
        except ValueError as e:  # noqa: BLE001
            raise SystemExit("--interrupt-after-playback-ms: not an integer "
                             "component: %r (%s)" % (part, e))
    return vals or [0]


def verify_capture_scope(diag, directory=None):
    """R-1e ITEM 2 proof helper: does the capture correspond to ONE run?

    Cross-checks, read back from the bridge (never assumed):
      * `capture.qwen_pcm24_bytes`  -- the bridge's own in-process counter
      * on-disk size of qwen_pcm24.raw
      * `sum(generations[*].delta_bytes)` -- bytes the bridge accepted upstream
      * `sum(generations[*].frames_encoded)` vs source frames implied by the file
    Equality of the last pair is the strong check: it can only hold if the file
    contains exactly the frames this run's generations produced and nothing
    from a predecessor run.
    """
    directory = directory or CAPTURE_DIR
    gens = diag.get("generations") or {}
    delta_bytes = sum(int((st or {}).get("delta_bytes") or 0)
                      for st in gens.values())
    frames_encoded = sum(int((st or {}).get("frames_encoded") or 0)
                         for st in gens.values())
    cap = diag.get("capture") or {}
    on_disk = {}
    for name in CAPTURE_FILES:
        p = os.path.join(directory, name)
        try:
            on_disk[name] = os.path.getsize(p) if os.path.exists(p) else 0
        except Exception:  # noqa: BLE001
            on_disk[name] = -1
    src_frames_from_disk = on_disk.get("qwen_pcm24.raw", 0) // FRAME_BYTES
    # Count PACKETS by walking the 4-byte length prefixes -- sent_opus.bin is a
    # byte size, so comparing it directly to a frame count would be meaningless.
    pkts_from_disk = None
    try:
        blob = open(os.path.join(directory, "sent_opus.bin"), "rb").read()
        cnt, off = 0, 0
        while off + 4 <= len(blob):
            ln = struct.unpack(">I", blob[off:off + 4])[0]
            off += 4 + ln
            cnt += 1
        pkts_from_disk = cnt
    except Exception:  # noqa: BLE001
        pkts_from_disk = None
    rows_from_disk = 0
    try:
        with open(os.path.join(directory, "sent_opus.jsonl")) as f:
            rows_from_disk = sum(1 for l in f if l.strip())
    except Exception:  # noqa: BLE001
        pass
    return {
        "diag_dir": directory,
        "bridge_capture_state": cap,
        "on_disk_bytes": on_disk,
        "sum_generation_delta_bytes": delta_bytes,
        "sum_generation_frames_encoded": frames_encoded,
        "source_frames_from_disk": src_frames_from_disk,
        "packets_from_disk": pkts_from_disk,
        "jsonl_rows_from_disk": rows_from_disk,
        "delta_bytes_equals_disk_pcm": delta_bytes == on_disk.get("qwen_pcm24.raw"),
        "capture_state_equals_disk_pcm": (
            cap.get("qwen_pcm24_bytes") == on_disk.get("qwen_pcm24.raw")),
        "capture_state_sent_frames_equals_disk_packets": (
            cap.get("sent_opus_frames") == pkts_from_disk),
        "bin_packets_equal_jsonl_rows": (pkts_from_disk == rows_from_disk),
        # THE scoping check: the captured source stream contains exactly the
        # frames this run's generations produced -- no predecessor leftovers.
        "scoped_to_this_run": (frames_encoded == src_frames_from_disk
                               and delta_bytes == on_disk.get("qwen_pcm24.raw")),
    }


def pcm(total_bytes, tag=0):
    """Downlink PCM s16le. `sine` gives a smooth, speech-like waveform whose
    natural frame boundaries are continuous — required for a valid
    discontinuity measurement (Phase 8)."""
    n = total_bytes // 2
    if WAVE == "sine":
        out = bytearray()
        for i in range(n):
            t = i / 24000.0
            env = 0.55 + 0.45 * math.sin(2 * math.pi * 1.7 * t)
            v = (0.6 * math.sin(2 * math.pi * 220 * t + tag * 0.31)
                 + 0.3 * math.sin(2 * math.pi * 440 * t + tag)
                 + 0.1 * math.sin(2 * math.pi * 880 * t)) * env
            s = int(max(-1.0, min(1.0, v)) * 20000)
            out += struct.pack("<h", s)
        return bytes(out)
    return bytes((i * 7 + 11 + tag * 13) & 0xFF for i in range(total_bytes))


def b64(d):
    return base64.b64encode(d).decode("ascii")


async def send(ws, obj):
    await ws.send_str(json.dumps(obj))


class FakeQwen:
    """Scriptable fake upstream. One ws connection per bridge QwenClient."""

    def __init__(self, scenario):
        self.scenario = scenario
        self.seq = 0
        self.active = None
        self.events = []          # upstream-side event log (ts, kind, detail)
        self.errors = []          # RECORDED upstream exceptions (never silent)
        self.cancel_count = 0
        self.cancel_seen = asyncio.Event()
        self.turn_started = asyncio.Event()
        self.seq_log = None       # ITEM 2: exact emitted order (auto_cancel_*)
        self.shape = None         # ITEM 2: the three shape verdicts
        self.burst_stats = None   # R-1e ITEM 1: overflow_bursty delivery stats

    def rid(self):
        self.seq += 1
        return "resp_%d" % self.seq

    def log(self, kind, **kw):
        self.events.append(dict(ts=round(time.monotonic(), 6), kind=kind, **kw))

    async def handler(self, request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        scen = self.scenario
        task = None
        try:
            await send(ws, {"type": "session.created",
                            "session": {"id": "fake_sess"}})
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    obj = json.loads(msg.data)
                except Exception as e:  # noqa: BLE001
                    self.errors.append(_exc_record("fakeqwen.json_parse", e,
                                                   {"raw": msg.data[:200]}))
                    continue
                et = obj.get("type")
                if et == "session.update":
                    await send(ws, {"type": "session.updated",
                                    "session": {"id": "fake_sess"}})
                    task = asyncio.create_task(self.run(ws, scen))
                elif et == "response.cancel":
                    self.cancel_count += 1
                    self.cancel_seen.set()
                    self.log("cancel_received", active=self.active)
                    await send(ws, BENIGN_CANCEL_ERROR)
                    if self.active is not None and not scen.startswith("auto"):
                        await send(ws, {"type": "response.done", "response": {
                            "id": self.active, "status": "cancelled"}})
                        self.active = None
                elif et == "session.finish":
                    break
        except Exception as e:  # noqa: BLE001
            self.errors.append(_exc_record("fakeqwen.handler", e))
        finally:
            if task and not task.done():
                task.cancel()
            try:
                await ws.close()
            except Exception as e:  # noqa: BLE001
                self.errors.append(_exc_record("fakeqwen.ws_close", e))
        return ws

    async def delta_stream(self, ws, rid, n_chunks, gap, tag=0):
        if WAVE == "file" and FILE_CHUNKS:
            chunks = FILE_CHUNKS[:n_chunks]
        else:
            total = pcm(n_chunks * FRAME_BYTES, tag)
            chunks = [total[i * FRAME_BYTES:(i + 1) * FRAME_BYTES]
                      for i in range(n_chunks)]
        for chunk in chunks:
            await send(ws, {"type": "response.audio.delta", "response_id": rid,
                            "item_id": "item", "delta": b64(chunk)})
            if gap:
                await asyncio.sleep(gap)

    # -- R-1e ITEM 1: measured-structure bursty delivery -------------------

    async def delta_stream_bursty(self, ws, rid, n_chunks, burst, gap_s, tag=0):
        """Deliver `n_chunks` as micro-bursts of `burst` chunks, gap `gap_s`.

        Within a burst the sends are back-to-back with NO sleep, so they land
        sub-millisecond apart exactly as measured in the real run. The gap
        between bursts replaces any per-chunk pacing. This reproduces an
        arrival rate far above the drain rate WITHOUT ever dumping thousands of
        frames instantaneously -- the overflow, if any, arises from the
        upstream delivery pattern alone (the bridge is untouched).
        """
        chunks = self._chunks(n_chunks, tag)
        i = 0
        n_bursts = 0
        t0 = time.monotonic()
        while i < len(chunks):
            for k in range(min(burst, len(chunks) - i)):
                await send(ws, {"type": "response.audio.delta",
                                "response_id": rid, "item_id": "item",
                                "delta": b64(chunks[i + k])})
            i += burst
            n_bursts += 1
            if i < len(chunks) and gap_s:
                await asyncio.sleep(gap_s)
        self.log("bursty_stream_done", resp_id=rid, chunks=len(chunks),
                 bursts=n_bursts, burst=burst, gap_ms=round(gap_s * 1000.0, 3),
                 elapsed_s=round(time.monotonic() - t0, 4),
                 arrival_frames_per_s=round(
                     len(chunks) / max(1e-9, time.monotonic() - t0), 2))
        return {"chunks": len(chunks), "bursts": n_bursts,
                "burst_chunks": burst, "gap_ms": round(gap_s * 1000.0, 3),
                "elapsed_s": round(time.monotonic() - t0, 4),
                "arrival_frames_per_s": round(
                    len(chunks) / max(1e-9, time.monotonic() - t0), 2)}

    async def run(self, ws, scen):
        try:
            await asyncio.sleep(0.2)
            if scen in ("barge_cancel_first", "barge_repeat_content",
                        "auto_cancel_first"):
                await self.sc_barge(ws, scen)
            elif scen in ("auto_cancel_live", "auto_cancel_late_delta"):
                await self.sc_auto_cancel(ws, scen)
            elif scen == "rapid_boundary":
                await self.sc_rapid(ws)
            elif scen == "overflow_bursty":
                await self.sc_overflow(ws)
            elif scen == "long_pressure":
                await self.sc_long(ws)
            else:
                await self.sc_long(ws)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            self.log("scenario_error", err=repr(e))
            self.errors.append(_exc_record("fakeqwen.scenario", e,
                                           {"scenario": scen}))

    # -- turn helpers ----------------------------------------------------

    async def open_turn(self, ws, rid, tag=0):
        self.active = rid
        self.log("response_created", resp_id=rid)
        await send(ws, {"type": "response.created",
                        "response": {"id": rid, "status": "in_progress"}})

    async def close_turn(self, ws, rid, status="completed", tag=0,
                         with_audio_done=True):
        if with_audio_done:
            await send(ws, {"type": "response.audio.done", "response_id": rid})
        await send(ws, {"type": "response.done",
                        "response": {"id": rid, "status": status}})
        self.log("response_done", resp_id=rid, status=status)
        if self.active == rid:
            self.active = None
        self.turn_started.set()

    async def sc_long(self, ws):
        """One long turn; deltas run ahead of realtime to load the downlink."""
        self.log("speech_started", phase="turn1")
        await send(ws, {"type": "input_audio_buffer.speech_started",
                        "audio_start_ms": 0, "item_id": "item_1"})
        await asyncio.sleep(0.03)
        await send(ws, {"type": "input_audio_buffer.speech_stopped",
                        "audio_end_ms": 200, "item_id": "item_1"})
        await asyncio.sleep(0.02)
        r1 = self.rid()
        await self.open_turn(ws, r1, 0)
        n = len(FILE_CHUNKS) if (WAVE == "file" and FILE_CHUNKS) else 900
        await self.delta_stream(ws, r1, n, WAVE_GAP, 0)
        await self.close_turn(ws, r1, "completed")

    async def sc_overflow(self, ws):
        """R-1e ITEM 1: overflow driven ONLY by the upstream delivery pattern.

        Identical turn shape to `sc_long` (speech_started -> speech_stopped ->
        response.created -> deltas -> audio.done -> done{completed}) and the
        response STREAMS TO COMPLETION -- which is precisely what the last real
        session never did (every response was cancelled ~1 s in, so only
        96-160 frames arrived and the queue peaked at 131/256 with zero drops).

        The ONLY difference from `sc_long` is the delivery cadence: bursts of
        BURST_CHUNKS frames back-to-back, separated by BURST_GAP_MS. The bridge
        is completely untouched, so any overflow is attributable purely to the
        upstream pattern. `sine` is used for the waveform so a later analyzer
        run gets a physically meaningful discontinuity measurement.
        """
        self.log("speech_started", phase="turn1")
        await send(ws, {"type": "input_audio_buffer.speech_started",
                        "audio_start_ms": 0, "item_id": "item_1"})
        await asyncio.sleep(0.03)
        await send(ws, {"type": "input_audio_buffer.speech_stopped",
                        "audio_end_ms": 200, "item_id": "item_1"})
        await asyncio.sleep(0.02)
        r1 = self.rid()
        await self.open_turn(ws, r1, 0)
        n = (len(FILE_CHUNKS) if (WAVE == "file" and FILE_CHUNKS)
             else OVERFLOW_CHUNKS)
        st = await self.delta_stream_bursty(
            ws, r1, n, BURST_CHUNKS, BURST_GAP_MS / 1000.0, 0)
        self.burst_stats = st
        # stream to COMPLETION -- no cancel, so the queue is never flushed
        await self.close_turn(ws, r1, "completed")

    async def sc_barge(self, ws, scen):
        """Emulates the OBSERVED REAL ORDER:
        response.done{cancelled} for N  ->  input_audio_buffer.speech_started
        -> late deltas for N -> resp N+1."""
        r1 = self.rid()
        await send(ws, {"type": "input_audio_buffer.speech_started",
                        "audio_start_ms": 0, "item_id": "item_1"})
        self.log("speech_started", phase="turn1")
        await asyncio.sleep(0.03)
        await send(ws, {"type": "input_audio_buffer.speech_stopped",
                        "audio_end_ms": 200, "item_id": "item_1"})
        await asyncio.sleep(0.02)
        await self.open_turn(ws, r1, 0)
        # 60 chunks @5 ms -> 0.3 s to deliver 1.2 s of audio (queue builds)
        await self.delta_stream(ws, r1, 60, 0.005, 0)
        await asyncio.sleep(0.4)

        # ---- the observed real-Qwen order ----
        await send(ws, {"type": "response.done",
                        "response": {"id": r1, "status": "cancelled"}})
        self.log("response_done", resp_id=r1, status="cancelled",
                 phase="auto_cancel")
        if self.active == r1:
            self.active = None
        await asyncio.sleep(0.001)
        await send(ws, {"type": "input_audio_buffer.speech_started",
                        "audio_start_ms": 0, "item_id": "item_2"})
        self.log("speech_started", phase="barge")

        # late deltas for the CANCELLED response (must be rejected by the bridge)
        await self.delta_stream(ws, r1, 8, 0.002, 0)
        self.log("late_delta_sent", resp_id=r1, n=8)

        await asyncio.sleep(0.3)
        await send(ws, {"type": "input_audio_buffer.speech_stopped",
                        "audio_end_ms": 200, "item_id": "item_2"})
        r2 = self.rid()
        await self.open_turn(ws, r2, 1)
        tag = 0 if scen == "barge_repeat_content" else 1
        await self.delta_stream(ws, r2, 40, 0.005, tag)
        await self.close_turn(ws, r2, "completed")

    # -- R-1d LIVE auto-cancel variant (ITEM 1/2) ------------------------

    def _chunks(self, n, tag=0):
        """n x 960-byte PCM24 chunks for the auto_cancel_* scenarios."""
        if WAVE == "file" and FILE_CHUNKS:
            base = list(FILE_CHUNKS)
            while len(base) < n:
                base = base + base
            return base[:n]
        total = pcm(n * FRAME_BYTES, tag)
        return [total[i * FRAME_BYTES:(i + 1) * FRAME_BYTES]
                for i in range(n)]

    def _shape_proof(self, seq, rid, pre_n, late_n, t_cancel):
        """ITEM 2: decide the three verdicts FROM the emitted sequence."""
        deltas = [e for e in seq if e["type"] == "response.audio.delta"
                  and e["resp_id"] == rid]
        before = [e for e in deltas if e["ts"] <= t_cancel]
        after = [e for e in deltas if e["ts"] > t_cancel]

        def terminal(e):
            if e["type"] == "response.audio.done":
                return True
            return e["type"] == "response.done" and e.get("status") == "completed"

        term_before = [e for e in seq if e["resp_id"] == rid
                       and e["ts"] < t_cancel and terminal(e)]
        created = any(e["type"] == "response.created" and e["resp_id"] == rid
                      for e in seq)
        cancelled = any(e["type"] == "response.done" and e["resp_id"] == rid
                        and e.get("status") == "cancelled" for e in seq)
        return {
            "response_id": rid,
            "pre_delta_chunks": pre_n,
            "late_delta_chunks": late_n,
            "deltas_before_cancel": len(before),
            "deltas_after_cancel": len(after),
            "response_created_before_cancel": bool(created),
            "cancelled_event_present": bool(cancelled),
            "terminal_events_before_cancel": [e["type"] for e in term_before],
            "audio_done_before_cancel": any(
                e["type"] == "response.audio.done" for e in term_before),
            "done_completed_before_cancel": any(
                e["type"] == "response.done" and e.get("status") == "completed"
                for e in term_before),
            # ---- the three required verdicts ----
            "CURRENT_RESPONSE_ACTIVE": bool(created and not term_before),
            "RESPONSE_AUDIO_DELTA_STILL_FLOWING": bool(
                len(before) == pre_n and len(after) == late_n
                and len(before) > 0 and len(after) > 0),
            "RESPONSE_DONE_COMPLETED_NOT_SEEN": not term_before,
        }

    async def sc_auto_cancel(self, ws, scen):
        """R-1d ITEM 1: the LIVE auto-cancel barge variant.

        Exact emit order (documented real-Qwen live barge-in):
          1 speech_started(turn1)
          2 speech_stopped(turn1)
          3 response.created(r1)
          4 response.audio.delta(r1) x LIVE_PRE_DELTA_CHUNKS, still flowing
          5 WHILE deltas still arrive: response.done{cancelled}(r1)
          6 ~1 ms later: speech_started(turn2)  [the interruption]
          7 LATE response.audio.delta(r1) x late_n  (after the cancel)
          8 speech_stopped(turn2), response.created(r2), deltas, done(r2)
        The stream is never drained before the cancel and keeps arriving after
        it -> this is the RIGHT variant, not a completed-response tail.
        """
        extreme = scen == "auto_cancel_late_delta"
        late_n = (max(LATE_DELTA_CHUNKS, EXTREME_LATE_DELTA_CHUNKS)
                  if extreme else LATE_DELTA_CHUNKS)
        pre_n = LIVE_PRE_DELTA_CHUNKS
        r1 = self.rid()
        seq = []

        async def emit(obj, rid, status=None):
            await send(ws, obj)
            seq.append(dict(ts=round(time.monotonic(), 6),
                            type=obj.get("type"), resp_id=rid, status=status))

        chunks = self._chunks(pre_n + late_n, 0)
        # 1/2: turn-1 speech
        await emit({"type": "input_audio_buffer.speech_started",
                    "audio_start_ms": 0, "item_id": "item_1"}, None)
        self.log("speech_started", phase="turn1")
        await asyncio.sleep(0.03)
        await emit({"type": "input_audio_buffer.speech_stopped",
                    "audio_end_ms": 200, "item_id": "item_1"}, None)
        await asyncio.sleep(0.02)
        # 3: response.created
        await emit({"type": "response.created",
                    "response": {"id": r1, "status": "in_progress"}}, r1,
                   status="in_progress")
        self.active = r1
        self.log("response_created", resp_id=r1)
        # 4: stream deltas for r1 realtime-ish; do NOT drain the stream here
        for i in range(pre_n):
            await emit({"type": "response.audio.delta", "response_id": r1,
                        "item_id": "item", "delta": b64(chunks[i])}, r1)
            await asyncio.sleep(LIVE_DELTA_GAP_S)
        # 5: cancel MID-STREAM (late_n deltas are still to be sent)
        t_cancel = time.monotonic()
        await emit({"type": "response.done",
                    "response": {"id": r1, "status": "cancelled"}}, r1,
                   status="cancelled")
        self.log("response_done", resp_id=r1, status="cancelled",
                 phase="auto_cancel_midstream", deltas_sent_before=pre_n,
                 deltas_remaining=late_n)
        if self.active == r1:
            self.active = None
        # 6: the user interruption ~1 ms later
        await asyncio.sleep(0.001)
        await emit({"type": "input_audio_buffer.speech_started",
                    "audio_start_ms": 0, "item_id": "item_2"}, None)
        self.log("speech_started", phase="barge",
                 since_cancel_ms=round((time.monotonic() - t_cancel) * 1000.0, 3))
        # 7: the genuinely LATE old-response deltas (after the cancel)
        for i in range(pre_n, pre_n + late_n):
            await emit({"type": "response.audio.delta", "response_id": r1,
                        "item_id": "item", "delta": b64(chunks[i])}, r1)
            await asyncio.sleep(LATE_DELTA_GAP_S)
        self.log("late_delta_sent", resp_id=r1, n=late_n, after_cancel=True)
        # 8: turn 2 -> r2
        await asyncio.sleep(0.05)
        await emit({"type": "input_audio_buffer.speech_stopped",
                    "audio_end_ms": 200, "item_id": "item_2"}, None)
        r2 = self.rid()
        await emit({"type": "response.created",
                    "response": {"id": r2, "status": "in_progress"}}, r2,
                   status="in_progress")
        self.active = r2
        self.log("response_created", resp_id=r2)
        await self.delta_stream(ws, r2, 40, 0.005, 1)
        await emit({"type": "response.audio.done", "response_id": r2}, r2)
        await emit({"type": "response.done",
                    "response": {"id": r2, "status": "completed"}}, r2,
                   status="completed")
        self.log("response_done", resp_id=r2, status="completed")
        if self.active == r2:
            self.active = None
        self.turn_started.set()

        # ITEM 2: record + assert the shape (fails LOUDLY if wrong).
        self.seq_log = seq
        self.shape = self._shape_proof(seq, r1, pre_n, late_n, t_cancel)
        ok = all(self.shape[k] for k in (
            "CURRENT_RESPONSE_ACTIVE",
            "RESPONSE_AUDIO_DELTA_STILL_FLOWING",
            "RESPONSE_DONE_COMPLETED_NOT_SEEN"))
        print("R1C_STATE BARGE_SHAPE " + json.dumps(self.shape),
              file=sys.stderr)
        if not ok:
            raise AssertionError("WRONG_BARGE_IN_VARIANT: %r" % (self.shape,))

    async def sc_rapid(self, ws):
        """Response N completes, N+1 starts immediately (boundary race)."""
        for i in range(4):
            rid = self.rid()
            await send(ws, {"type": "input_audio_buffer.speech_started",
                            "audio_start_ms": 0, "item_id": "item_%d" % i})
            await send(ws, {"type": "input_audio_buffer.speech_stopped",
                            "audio_end_ms": 200, "item_id": "item_%d" % i})
            await self.open_turn(ws, rid, i)
            await self.delta_stream(ws, rid, 30, 0.004, i)
            await self.close_turn(ws, rid, "completed")
            await asyncio.sleep(0.0)     # back-to-back boundary


class ProbeClient:
    """Instrumented XiaoZhi client mirroring py-xiaozhi audio semantics."""

    def __init__(self, name, keep_listening=True, stall_ms=0, drain=True):
        self.name = name
        self.keep_listening = keep_listening
        self.stall_ms = stall_ms
        self.dec = opuslib.Decoder(SAMPLE_RATE_OUT, 1)
        self.fifo = 0                       # samples @ 24 kHz
        self.fifo_max = 0
        self.fifo_max_s = 0.0
        self.fifo_dropped = 0
        self.consumed = 0
        self.rx_seq = 0
        self.rx = []                        # per-frame record
        self.txt = []                       # text frames
        self.tts_state = None
        self.clears = []                    # (ts, samples_discarded)
        self.decode_errors = 0
        self.drain_enabled = drain
        self._drain_task = None
        self._stall_until = 0.0

        # --- explicit transmit/close instrumentation (no silent exits) ---
        self.intended_frames = 0       # 20 ms frames the schedule asked for
        self.sent_frames = 0           # frames actually handed to send_bytes()
        self.uplink_fail_index = None  # frame index where a send failed (or None)
        self.uplink_elapsed_s = None
        self.uplink_stop_reason = None
        self.uplink_stopped_early = None
        self.ws_close_code = None
        self.ws_close_reason = None
        self.close_events = []         # explicit WS/session close reasons
        self.failures = []             # recorded exceptions -> probe failure
        self.failed = False            # explicit failure flag
        self.speak_s = None
        self.after_s = None

        # --- ITEM 1: per-utterance send accounting (separate i1/i2) ---
        self.u1_sent_frames = 0        # frames actually sent from U1_PKTS
        self.u2_sent_frames = 0        # frames actually sent from U2_PKTS
        self.silence_frames_sent = 0   # frames sent by the `silent` fallback
        self.u2_switch_events = []     # explicit timestamped state transitions
        self.u2_first_pkt_is_index0 = None   # proof the switch restarted at 0
        self.u2_gated_out = False      # True = utterance 2 deliberately NOT sent
        self.u2_gate_reason = None

        # --- ITEM 2: playback-triggered interruption ---
        self.interrupt_trigger_mode = None   # "time" | "playback"
        self.playback_proven = False   # a binary (Opus) downlink frame arrived
        self.t_first_binary_rx = None
        self.playback_first_frame_bytes = None
        self.interrupt_triggered = None      # dict recorded once at the switch

        # --- R-1d ITEM MULTI-ATTEMPT: repeat the full cycle N times ---
        self.attempts = []                   # one record per full cycle
        self.cur_attempt_index = None        # attempt currently being driven
        self.cur_delay_ms = 0                # this attempt's configured delay
        self.u1_exhaustion_events = []       # explicit U1 index-exhaustion log
        self.u2_exhaustion_events = []       # explicit U2 index-exhaustion log

    def _fail(self, stage, exc, extra=None):
        """Record an exception AND raise the probe failure flag."""
        self.failures.append(_exc_record(stage, exc, extra))
        self.failed = True

    # -- FIFO model ------------------------------------------------------

    async def _drain_loop(self):
        """Realtime playback consumption at 24 kHz (480 samples / 20 ms)."""
        try:
            while True:
                await asyncio.sleep(0.02)
                if self.drain_enabled:
                    self.fifo = max(0, self.fifo - OUT_FRAME_SAMPLES)
                    self.consumed += OUT_FRAME_SAMPLES
        except asyncio.CancelledError:
            raise

    def push(self, n):
        cap = int(SAMPLE_RATE_OUT * TTS_FIFO_MAX_S)
        self.fifo += n
        if self.fifo > cap:
            self.fifo_dropped += self.fifo - cap
            self.fifo = cap
        self.fifo_max = max(self.fifo_max, self.fifo)
        self.fifo_max_s = round(self.fifo_max / SAMPLE_RATE_OUT, 4)

    def clear(self, why):
        n = self.fifo
        self.fifo = 0
        self.clears.append({"ts": round(time.monotonic(), 6), "samples": n,
                            "seconds": round(n / SAMPLE_RATE_OUT, 4),
                            "why": why})
        return n

    def tts(self, state):
        self.tts_state = state
        if state == "stop":
            if self.keep_listening:
                self.clear("tts_stop")
            # else: py-xiaozhi returns early -> NO clear
        # NOTE: py-xiaozhi does NOT clear on tts start (realtime mode)

    # -- main loop -------------------------------------------------------

    async def run(self, session, speak_s=6.0, after_s=3.0):
        ws = await session.ws_connect(BRIDGE_WS, max_msg_size=0)
        await ws.send_json(HELLO)
        await ws.receive(timeout=5)
        await ws.send_json(LISTEN_START)
        self._drain_task = asyncio.create_task(self._drain_loop())

        enc = opuslib.Encoder(16000, 1, opuslib.APPLICATION_VOIP)
        up = enc.encode(b"\x09\x00" * 160, 320)
        silent = enc.encode(b"\x00" * 640, 320)

        # INTENDED transmit frame count for the requested schedule. Reported
        # explicitly so a mismatch with SENT is never invisible again.
        self.intended_frames = int(round(speak_s / 0.02))
        self.speak_s = speak_s
        self.after_s = after_s

        def _delay_for_attempt(idx):
            """Per-attempt configured playback delay (ms).

            A single value applies to every attempt; a comma-separated list is
            consumed in order and the LAST value is reused once the list runs
            out (0 = the playback gate is disabled for that attempt).
            """
            if not INTERRUPT_DELAYS:
                return 0
            if idx < len(INTERRUPT_DELAYS):
                return INTERRUPT_DELAYS[idx]
            return INTERRUPT_DELAYS[-1]

        def _switch_decision(el, t0, delay_ms, gate):
            """Return (should_switch, mode) for the current uplink instant.

            mode is "time" (--up2-at elapsed) or "playback"
            (--interrupt-after-playback-ms elapsed since the first binary
            downlink frame). Whichever *fires first* wins; with the playback
            gate active, utterance 2 is withheld until the playback proof
            exists (no binary frame -> utterance 2 is never sent).
            """
            if not U2_PKTS:
                return False, None
            now = time.monotonic()
            cands = []
            if now - t0 >= UP2_AT:
                cands.append((t0 + UP2_AT, "time"))
            if gate:
                if not self.playback_proven:
                    return False, None        # hard gate: no playback proof
                play_fire = (self.t_first_binary_rx + delay_ms / 1000.0)
                if now >= play_fire:
                    cands.append((play_fire, "playback"))
            if not cands:
                return False, None
            return True, min(cands, key=lambda c: c[0])[1]

        def _record_switch(el, mode, delay_ms):
            now = time.monotonic()
            ev = {
                "ts": round(now, 6),
                "elapsed_s": round(el, 4),
                "mode": mode,
                "frames_sent_so_far": self.sent_frames,
                "u1_sent": self.u1_sent_frames,
                "u2_pkts": len(U2_PKTS),
                "downlink_frames_rx": self.rx_seq,
                "playback_proven": self.playback_proven,
            }
            if mode == "playback":
                ev["elapsed_since_playback_ms"] = round(
                    (now - self.t_first_binary_rx) * 1000.0, 3)
                ev["configured_playback_ms"] = delay_ms
            else:
                ev["up2_at_s"] = UP2_AT
            self.u2_switch_events.append(ev)
            self.interrupt_trigger_mode = mode
            self.interrupt_triggered = dict(ev)
            print("R1C_STATE INTERRUPT_TRIGGERED " + json.dumps(ev),
                  file=sys.stderr)
            return ev

        def _finalize_attempt(att, i1, i2, j_switched):
            """Close one attempt record. Called on EVERY exit path (normal end
            and send-exception) so an attempt can never vanish silently."""
            att["u1_sent"] = i1
            att["u2_sent"] = i2
            att["switched"] = bool(j_switched)
            att["t_first_binary_rx"] = (
                round(self.t_first_binary_rx, 6)
                if self.t_first_binary_rx is not None else None)
            att["playback_proven"] = bool(self.playback_proven)
            att["t_end"] = round(time.monotonic(), 6)
            self.attempts.append(att)

        async def uplink():
            # ---- R-1d ITEM MULTI: repeat the full cycle --attempts N times --
            # A XiaoZhi client connection owns exactly ONE upstream (paid)
            # Qwen session, so the hedge lives INSIDE this single connection:
            # every attempt re-sends utterance 1 from index 0, waits for a
            # FRESH playback proof, then sends utterance 2 from index 0.
            for attempt_index in range(ATTEMPTS):
                self.cur_attempt_index = attempt_index
                self.cur_delay_ms = _delay_for_attempt(attempt_index)
                gate = self.cur_delay_ms > 0
                t0 = time.monotonic()
                end = t0 + speak_s
                # per-attempt playback-proof reset (a no-op on attempt 0 when
                # it is already False -> attempts==1 is left untouched)
                self.playback_proven = False
                self.t_first_binary_rx = None
                self.playback_first_frame_bytes = None
                att = {
                    "attempt_index": attempt_index,
                    "t_start": round(t0, 6),
                    "t_end": None,
                    "t_first_binary_rx": None,
                    "playback_proven": False,
                    "configured_delay_ms": self.cur_delay_ms,
                    "delay_used_ms": None,
                    "interrupt_triggered_ts": None,
                    "downlink_frames_rx_at_trigger": None,
                    "u1_intended": len(U1_PKTS),
                    "u1_sent": 0,
                    "u2_intended": len(U2_PKTS),
                    "u2_sent": 0,
                    "trigger_path": "none",
                    "u1_exhausted": False,
                    "u2_exhausted": False,
                    "u2_gated_out": False,
                    "u2_gate_reason": None,
                    "produced_new_generation": None,
                }
                i1 = 0                   # U1_PKTS index (per-utterance)
                i2 = 0                   # U2_PKTS index (per-utterance)
                switched = False
                sil_before = self.silence_frames_sent
                while time.monotonic() < end:
                    if U1_PKTS:
                        el = time.monotonic() - t0
                        if not switched:
                            do_switch, mode = _switch_decision(
                                el, t0, self.cur_delay_ms, gate)
                            if do_switch:
                                switched = True
                                ev = _record_switch(el, mode,
                                                    self.cur_delay_ms)
                                att["trigger_path"] = (
                                    "playback" if mode == "playback"
                                    else "time_fallback")
                                att["interrupt_triggered_ts"] = ev.get("ts")
                                att["downlink_frames_rx_at_trigger"] = ev.get(
                                    "downlink_frames_rx")
                                att["delay_used_ms"] = ev.get(
                                    "elapsed_since_playback_ms")
                        if switched:
                            if i2 < len(U2_PKTS):
                                pkt = U2_PKTS[i2]
                                kind = "u2"
                                if i2 == 0:
                                    self.u2_first_pkt_is_index0 = True
                                i2 += 1
                            else:
                                pkt = silent
                                kind = "silent"
                        elif i1 < len(U1_PKTS):
                            pkt = U1_PKTS[i1]
                            kind = "u1"
                            i1 += 1
                        else:
                            pkt = silent
                            kind = "silent"
                    else:
                        pkt = up
                        kind = "raw"
                    try:
                        await ws.send_bytes(pkt)
                    except asyncio.CancelledError:
                        self.uplink_stop_reason = "cancelled"
                        raise
                    except Exception as e:  # noqa: BLE001
                        # A send error must NEVER be a silent `return`.
                        if kind == "u1":
                            self.uplink_fail_index = i1 - 1 if i1 > 0 else 0
                        elif kind == "u2":
                            self.uplink_fail_index = i2 - 1 if i2 > 0 else 0
                        else:
                            self.uplink_fail_index = None
                        self._fail("uplink.send_bytes", e, {
                            "frame_index": self.uplink_fail_index,
                            "frame_kind": kind,
                            "attempt_index": attempt_index,
                            "sent_before_failure": self.sent_frames,
                            "intended_frames": self.intended_frames,
                            "elapsed_s": round(time.monotonic() - t0, 4),
                            "ws_closed": getattr(ws, "closed", None),
                        })
                        self.uplink_stop_reason = "send_exception"
                        self.uplink_stopped_early = True
                        self.uplink_elapsed_s = round(time.monotonic() - t0, 4)
                        _finalize_attempt(att, i1, i2, j_switched=switched)
                        return
                    self.sent_frames += 1
                    if kind == "u1":
                        self.u1_sent_frames += 1
                    elif kind == "u2":
                        self.u2_sent_frames += 1
                    elif kind == "silent":
                        self.silence_frames_sent += 1
                    await asyncio.sleep(0.02)

                # ---- explicit per-utterance exhaustion transitions ----
                # (constraint: reaching the end of an utterance's packet list
                # must be a logged transition, never a silent fall-through)
                if U1_PKTS and i1 >= len(U1_PKTS):
                    att["u1_exhausted"] = True
                    ev = {"attempt_index": attempt_index, "utterance": 1,
                          "i1": i1, "u1_pkts": len(U1_PKTS),
                          "switched": switched,
                          "ts": round(time.monotonic(), 6)}
                    self.u1_exhaustion_events.append(ev)
                    print("R1C_STATE U1_PKTS_EXHAUSTED " + json.dumps(ev),
                          file=sys.stderr)
                if U2_PKTS and switched and i2 >= len(U2_PKTS):
                    att["u2_exhausted"] = True
                    ev = {"attempt_index": attempt_index, "utterance": 2,
                          "i2": i2, "u2_pkts": len(U2_PKTS),
                          "ts": round(time.monotonic(), 6)}
                    self.u2_exhaustion_events.append(ev)
                    print("R1C_STATE U2_PKTS_EXHAUSTED " + json.dumps(ev),
                          file=sys.stderr)

                self.uplink_elapsed_s = round(time.monotonic() - t0, 4)
                self.uplink_stop_reason = "schedule_elapsed"
                # "early" = the loop ended materially BEFORE the requested
                # duration (a genuine premature stop), NOT the ~1 ms/frame send
                # overhead that makes sent slightly < intended.
                self.uplink_stopped_early = (
                    self.uplink_elapsed_s < speak_s - 0.25)
                if self.silence_frames_sent > sil_before:
                    print("R1C_STATE SILENCE_FRAMES_SENT n=%d"
                          % self.silence_frames_sent, file=sys.stderr)
                if U2_PKTS and i2 == 0:
                    # explicit outcome: utterance 2 was intentionally not sent
                    self.u2_gated_out = True
                    if gate and not self.playback_proven:
                        reason = "playback_not_proven"
                    elif not switched:
                        reason = "trigger_never_fired"
                    else:
                        reason = "switch_but_no_u2_sent"
                    self.u2_gate_reason = reason
                    att["u2_gated_out"] = True
                    att["u2_gate_reason"] = reason
                    print("R1C_STATE U2_GATED_OUT reason=%s "
                          "playback_proven=%s first_binary_rx=%s"
                          % (reason, self.playback_proven,
                             self.t_first_binary_rx), file=sys.stderr)
                _finalize_attempt(att, i1, i2, j_switched=switched)

        async def downlink():
            end = time.monotonic() + speak_s * ATTEMPTS + after_s
            while time.monotonic() < end:
                if self.stall_ms and time.monotonic() < self._stall_until:
                    await asyncio.sleep(0.05)      # emulate a slow reader
                    continue
                try:
                    msg = await ws.receive(timeout=0.5)
                except asyncio.TimeoutError:
                    continue                       # expected poll timeout
                except asyncio.CancelledError:
                    self.close_events.append({"reason": "cancelled"})
                    raise
                except Exception as e:  # noqa: BLE001
                    self._fail("downlink.receive", e)
                    self.close_events.append({
                        "reason": "receive_exception",
                        "exc_type": type(e).__name__, "message": str(e)})
                    return
                if msg.type == WSMsgType.BINARY:
                    if not self.playback_proven:
                        # First Opus frame proves upstream response audio is
                        # streaming -> playback has begun.
                        self.playback_proven = True
                        self.t_first_binary_rx = time.monotonic()
                        self.playback_first_frame_bytes = len(msg.data)
                        print("R1C_STATE PLAYBACK_PROVEN first_frame_bytes=%d"
                              % len(msg.data), file=sys.stderr)
                    self.rx_seq += 1
                    depth_before = self.fifo
                    try:
                        pcm_out = self.dec.decode(msg.data, OUT_FRAME_SAMPLES)
                        self.push(len(pcm_out) // 2)
                        err = None
                    except Exception as e:  # noqa: BLE001
                        self.decode_errors += 1
                        err = repr(e)
                    self.rx.append({
                        "rx_seq": self.rx_seq,
                        "t": round(time.monotonic(), 6),
                        "bytes": len(msg.data),
                        "fifo_before": depth_before,
                        "fifo_after": self.fifo,
                        "decode_error": err,
                    })
                elif msg.type == WSMsgType.TEXT:
                    try:
                        obj = json.loads(msg.data)
                    except Exception as e:  # noqa: BLE001
                        self._fail("downlink.text_json_parse", e,
                                   {"raw": msg.data[:200]})
                        continue
                    if obj.get("type") == "tts":
                        self.txt.append({"t": round(time.monotonic(), 6),
                                         "state": obj.get("state"),
                                         "ts_at_rx": self.rx_seq})
                        self.tts(obj.get("state"))
                elif msg.type in (WSMsgType.CLOSED, WSMsgType.ERROR,
                                  WSMsgType.CLOSING):
                    # explicit close reason + code, never a bare `return`
                    self.close_events.append({
                        "reason": "ws_" + msg.type.name.lower(),
                        "close_code": getattr(ws, "close_code", None),
                        "msg_data": getattr(msg, "data", None),
                        "msg_extra": getattr(msg, "extra", None),
                    })
                    self.ws_close_code = getattr(ws, "close_code", None)
                    return
            self.close_events.append({"reason": "downlink_window_elapsed"})

        t_up = asyncio.create_task(uplink())
        t_dn = asyncio.create_task(downlink())
        # emulated slow reader: stop draining the socket between 0.5 s and
        # 0.5+stall_ms (i.e. across the barge-in window) -> TCP backpressure
        if self.stall_ms:
            await asyncio.sleep(0.5)
            self._stall_until = time.monotonic() + self.stall_ms / 1000.0
        # return_exceptions=True so a task exception can never be consumed by
        # gather without surfacing -> every task outcome is recorded below.
        results = await asyncio.gather(t_up, t_dn, return_exceptions=True)
        for name, r in zip(("uplink", "downlink"), results):
            if isinstance(r, BaseException):
                self._fail("task:" + name, r,
                           {"sent_frames": self.sent_frames,
                            "intended_frames": self.intended_frames})
        if self._drain_task:
            self._drain_task.cancel()
        try:
            await ws.close()
        except Exception as e:  # noqa: BLE001
            self._fail("ws.close", e)
        finally:
            self.ws_close_code = getattr(ws, "close_code", None)
            self.ws_close_reason = getattr(ws, "close_reason", None)
            self.close_events.append({
                "reason": "client_close",
                "close_code": self.ws_close_code,
                "close_reason": self.ws_close_reason,
                "ws_closed": getattr(ws, "closed", None),
            })

    def summary(self):
        tts_stop_idx = [x["ts_at_rx"] for x in self.txt if x["state"] == "stop"]
        after = {}
        for stop_seq in tts_stop_idx:
            after[str(stop_seq)] = sum(1 for r in self.rx
                                       if r["rx_seq"] > stop_seq)
        return {
            "name": self.name,
            "rx_frames": len(self.rx),
            "rx_decode_errors": self.decode_errors,
            "fifo_max_samples": self.fifo_max,
            "fifo_max_s": self.fifo_max_s,
            "fifo_dropped_samples": self.fifo_dropped,
            "consumed_samples": self.consumed,
            "tts_events": self.txt,
            "clears": self.clears,
            "frames_after_each_tts_stop": after,
            # --- transmit / close instrumentation ---
            "speak_s": self.speak_s,
            "after_s": self.after_s,
            "intended_uplink_frames": self.intended_frames,
            "sent_uplink_frames": self.sent_frames,
            # --- ITEM 1: per-utterance accounting ---
            "u1_intended_frames": len(U1_PKTS),
            "u2_intended_frames": len(U2_PKTS),
            "u1_sent_frames": self.u1_sent_frames,
            "u2_sent_frames": self.u2_sent_frames,
            "silence_frames_sent": self.silence_frames_sent,
            "u2_switch_events": self.u2_switch_events,
            "u2_first_pkt_is_index0": self.u2_first_pkt_is_index0,
            "u2_gated_out": self.u2_gated_out,
            "u2_gate_reason": self.u2_gate_reason,
            # --- ITEM 2: playback-triggered interruption ---
            "interrupt_after_playback_ms": INTERRUPT_AFTER_PLAYBACK_MS,
            "up2_at": UP2_AT,
            "interrupt_trigger_mode": self.interrupt_trigger_mode,
            "interrupt_triggered": self.interrupt_triggered,
            "playback_proven": self.playback_proven,
            "playback_first_frame_bytes": self.playback_first_frame_bytes,
            # --- R-1d ITEM MULTI-ATTEMPT: repeat the full cycle N times ---
            "attempts": self.attempts,
            "attempts_total": len(self.attempts),
            "attempts_configured": ATTEMPTS,
            "interrupt_after_playback_ms_list": list(INTERRUPT_DELAYS),
            "intended_uplink_frames_total": self.intended_frames * ATTEMPTS,
            "u1_exhaustion_events": self.u1_exhaustion_events,
            "u2_exhaustion_events": self.u2_exhaustion_events,
            "uplink_failed_frame_index": self.uplink_fail_index,
            "uplink_elapsed_s": self.uplink_elapsed_s,
            "uplink_stop_reason": self.uplink_stop_reason,
            "uplink_stopped_early": self.uplink_stopped_early,
            "ws_close_code": self.ws_close_code,
            "ws_close_reason": self.ws_close_reason,
            "close_events": self.close_events,
            "probe_failed": self.failed,
            "probe_failures": self.failures,
        }


async def reset(session):
    try:
        async with session.post(BRIDGE_HTTP + "/diag/reset") as r:
            await r.json()
        return None
    except Exception as e:  # noqa: BLE001
        # A failed reset invalidates the counters -> record it, never silent.
        return _exc_record("reset:/diag/reset", e)


async def diag(session):
    async with session.get(BRIDGE_HTTP + "/diag") as r:
        return await r.json()


async def health(session):
    async with session.get(BRIDGE_HTTP + "/health") as r:
        return await r.json()


def correlate(rx, txt, sends):
    """Align client-received frames with bridge sends (same order, one conn).

    Distinguishes:
      * frames SENT after the generation was invalidated  -> bridge stale send
      * frames sent BEFORE invalidation but RECEIVED after the `tts stop`
        -> in-flight transport tail (socket / client buffer)
    """
    per_stop = []
    for ev in txt:
        if ev.get("state") != "stop":
            continue
        s = ev["ts_at_rx"]
        gens_after, inv_after, seqs, in_flight = {}, 0, [], 0
        for r in rx:
            if r["rx_seq"] <= s:
                continue
            k = r["rx_seq"] - 1
            if k >= len(sends):
                continue
            e = sends[k]
            g = e.get("gen")
            gens_after[g] = gens_after.get(g, 0) + 1
            seqs.append(e.get("frame_seq"))
            if e.get("invalidated"):
                inv_after += 1
            else:
                in_flight += 1
        per_stop.append({
            "stop_at_rx_seq": s,
            "frames_after_stop": len(seqs),
            "gen_distribution_after": gens_after,
            "frames_sent_after_invalidation": inv_after,
            "frames_inflight_before_invalidation": in_flight,
            "first_frame_seq_after": seqs[0] if seqs else None,
            "last_frame_seq_after": seqs[-1] if seqs else None,
        })
    return {
        "client_rx_frames": len(rx),
        "bridge_sent_frames": len(sends),
        "aligned_pairs": min(len(rx), len(sends)),
        "per_tts_stop": per_stop,
    }


def analyze_barge(d, fake):
    """ITEM 3: per-generation record for the cancelled barge generation plus
    the late-delta accounting, derived from the bridge /diag snapshot and the
    upstream emit log. Nothing here is assumed: every number is read back.
    """
    gens = d.get("generations") or {}
    sends = d.get("send_timeline") or []
    journal = d.get("journal_tail") or []
    up = fake.events or []
    out = {"found": False}
    cancelled = None
    for gs, st in sorted(gens.items(), key=lambda kv: int(kv[0])):
        if st.get("invalidated"):
            if cancelled is None or st.get("invalidated") == "barge_in":
                cancelled = (int(gs), st)
    if cancelled is None:
        out["reason"] = "no invalidated generation in /diag generations"
        return out
    g, st = cancelled
    out["found"] = True
    out["generation_id"] = g
    out["response_id"] = (st.get("resp_ids") or [None])[-1]
    out["invalidated_reason"] = st.get("invalidated")
    out["created_ts"] = st.get("created_ts")
    out["response_done_cancelled_ts"] = st.get("end_ts")
    out["graded_status"] = st.get("status")
    out["frames_encoded"] = st.get("frames_encoded")
    out["delta_events_accepted"] = st.get("delta_events")
    out["delta_bytes_accepted"] = st.get("delta_bytes")
    out["frames_queued"] = st.get("frames_queued")
    out["frames_sent"] = st.get("frames_sent")
    out["frames_dropped"] = st.get("frames_dropped")
    out["peak_queue_depth"] = st.get("peak_queue_depth")
    out["flush_discarded"] = st.get("flush_discarded")
    out["tts_starts"] = st.get("tts_starts")
    out["tts_stops"] = st.get("tts_stops")

    g_sends = [s for s in sends if s.get("gen") == g]
    seqs = [s["frame_seq"] for s in g_sends if s.get("frame_seq") is not None]
    out["frame_seq_range"] = [min(seqs), max(seqs)] if seqs else None
    after_inv = [s for s in g_sends if s.get("invalidated")]
    out["frames_sent_after_invalidation"] = after_inv
    out["n_frames_sent_after_invalidation"] = len(after_inv)

    def jl(**pred):
        return [e for e in journal
                if all(e.get(k) == v for k, v in pred.items())]
    snaps = jl(journal_kind="barge_snapshot", active_gen=g)
    invs = jl(journal_kind="generation_invalidated", gen=g)
    flushes = jl(journal_kind="flush", active_gen=g)
    steps = [e for e in journal if e.get("journal_kind") == "barge_step"]
    cancel_req = [e for e in steps if e.get("step") == "pacer_cancel_requested"]
    pacer_done = [e for e in steps if e.get("step") == "pacer_cancel_done"]
    qflush = [e for e in steps if e.get("step") == "queue_flushed"]
    tts_stop = jl(journal_kind="tts_stop", gen=g)
    speech = [e for e in journal if e.get("journal_kind") == "qwen_event"
              and e.get("etype") == "input_audio_buffer.speech_started"]
    out["barge_journal_counts"] = {
        "barge_snapshot": len(snaps), "generation_invalidated": len(invs),
        "flush": len(flushes), "barge_steps": len(steps),
        "pacer_cancel_requested": len(cancel_req), "tts_stop": len(tts_stop),
        "speech_started_events": len(speech),
    }

    if snaps:
        s = snaps[-1]
        out["queue_depth_at_invalidation"] = s.get("queue_depth")
        out["queue_max_at_invalidation"] = s.get("queue_max")
        out["last_queued_frame_seq_at_invalidation"] = s.get(
            "last_queued_frame_seq")
        out["last_sent_frame_seq_at_invalidation"] = s.get(
            "last_sent_frame_seq")
        out["tts_active_at_invalidation"] = s.get("tts_active")
        out["pacer_task_alive_at_invalidation"] = s.get("pacer_task")
        out["barge_candidate_at_invalidation"] = s.get("barge_candidate")
        out["current_resp_id_at_invalidation"] = s.get("current_resp_id")
        out["snapshot_ts"] = s.get("j_ts")
    if qflush:
        out["queue_depth_after_flush"] = qflush[-1].get("queue_depth")
    if cancel_req:
        out["pacer_cancel"] = {
            "pacer_task_id": cancel_req[-1].get("pacer_task_id"),
            "ts": cancel_req[-1].get("j_ts"),
            "queue_depth": cancel_req[-1].get("queue_depth")}
    if pacer_done:
        out["pacer_cancel_done_ts"] = pacer_done[-1].get("j_ts")
    if invs:
        out["invalidation_ts"] = invs[-1].get("j_ts")
    if flushes:
        out["flush_count"] = flushes[-1].get("discarded")
        out["flush_gen_distribution"] = flushes[-1].get("gen_distribution")
    if tts_stop:
        out["tts_stop"] = {"caller": tts_stop[-1].get("caller"),
                           "ts": tts_stop[-1].get("j_ts"),
                           "pacer_task_id": tts_stop[-1].get("pacer_task_id")}

    cancel_ts = st.get("end_ts") or 0.0
    b_speech = [e for e in speech if (e.get("j_ts") or 0) >= cancel_ts]
    out["speech_started_ts_bridge"] = (
        b_speech[0].get("j_ts") if b_speech else None)
    up_speech = [e for e in up if e.get("kind") == "speech_started"
                 and e.get("phase") == "barge"]
    out["speech_started_ts_upstream"] = (
        up_speech[0].get("ts") if up_speech else None)
    up_cancel = [e for e in up if e.get("kind") == "response_done"
                 and e.get("status") == "cancelled"]
    out["response_done_cancelled_ts_upstream"] = (
        up_cancel[0].get("ts") if up_cancel else None)

    # ---- late-delta accounting (ITEM 3) ----
    late_ev = [e for e in up if e.get("kind") == "late_delta_sent"]
    late_n = sum(int(e.get("n") or 0) for e in late_ev)
    out["late_delta_chunks_sent_by_mock"] = late_n
    pre_n = LIVE_PRE_DELTA_CHUNKS
    accepted = st.get("delta_events") or 0
    encoded = st.get("frames_encoded") or 0
    sent = st.get("frames_sent") or 0
    acc_late = max(0, accepted - pre_n)          # late delta events accepted
    rejected = max(0, late_n - acc_late)
    sent_late = max(0, sent - pre_n)             # frames beyond the pre set
    acc_but_not_sent = max(0, acc_late - sent_late)
    out["late_delta_classification"] = {
        "rejected": rejected,
        "accepted_but_not_sent": acc_but_not_sent,
        "sent": sent_late,
        "basis": ("delta_events(gen)=%d pre=%d -> accepted_late=%d; "
                  "frames_encoded(gen)=%d frames_sent(gen)=%d -> sent_late=%d"
                  % (accepted, pre_n, acc_late, encoded, sent, sent_late)),
    }
    out["late_delta_frames_reached_client"] = len(after_inv)
    return out


async def probe(session, test, scenario, keep_listening, stall_ms, speak_s,
                after_s):
    reset_rec = await reset(session)
    h0 = await health(session)
    fake = FakeQwen(scenario)
    app = web.Application()
    app.router.add_get("/api-ws/v1/realtime", fake.handler)
    app.router.add_get("/", fake.handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", FAKE_PORT)
    await site.start()
    client = ProbeClient("%s/%s" % (test, scenario), keep_listening, stall_ms)
    err = None
    err_rec = None
    try:
        await client.run(session, speak_s, after_s)
    except Exception as e:  # noqa: BLE001
        err = repr(e)
        err_rec = _exc_record("client.run", e)
    finally:
        await runner.cleanup()
    d = await diag(session)
    h1 = await health(session)
    sends = d.get("send_timeline", [])
    cs = client.summary()
    cs["correlation"] = correlate(client.rx, client.txt, sends)
    cs["rx_timeline"] = [{"rx_seq": r["rx_seq"], "fifo_after": r["fifo_after"],
                          "decode_error": r["decode_error"]} for r in client.rx]
    # ---- R-1d ITEM MULTI-ATTEMPT: attribute bridge generations to attempts --
    # A "generation" is created by the bridge on `response.created`
    # (app/diag.py on_response_created -> created_ts = time.monotonic()). The
    # probe runs in the SAME container/kernel as the bridge, so the client's
    # attempt window timestamps and `created_ts` share one CLOCK_MONOTONIC and
    # are directly comparable. Each generation falls in exactly one
    # (contiguous) attempt window; the last window is closed on the right.
    gens = d.get("generations") or {}
    atts = cs.get("attempts") or []
    for i, a in enumerate(atts):
        lo, hi = a.get("t_start"), a.get("t_end")
        ids = []
        if lo is not None and hi is not None:
            for g, st in (gens.items() if isinstance(gens, dict) else []):
                c = (st or {}).get("created_ts")
                if c is None:
                    continue
                if lo <= c < hi or (i == len(atts) - 1 and c == hi):
                    ids.append(g)
        try:
            ids = sorted(ids, key=lambda x: int(x))
        except Exception:  # noqa: BLE001
            ids = sorted(ids)
        a["new_generation_ids"] = ids
        a["new_generation_count"] = len(ids)
        a["produced_new_generation"] = bool(ids)
    cs["attempts_total"] = len(atts)
    cs["attempts_with_new_generation"] = sum(
        1 for a in atts if a.get("produced_new_generation"))
    cs["bridge_generation_count"] = d.get("generation_count")
    # `frames_in` etc. are cumulative on the bridge; /diag/reset has been
    # observed to answer {"ok": true} WITHOUT zeroing them. Report both the
    # delta and whether reset actually zeroed the counters, so an absolute
    # counter can never be misread as a per-run value.
    def _num(d_, k):
        try:
            return int(d_.get(k) or 0)
        except Exception:  # noqa: BLE001
            return None
    reset_effective = (h0.get("frames_in") == 0 and h0.get("ws_connections") == 0)
    deltas = {}
    for k in ("frames_in", "turns", "responses_completed", "qwen_sessions",
              "uplink_dropped", "upstream_errors"):
        a, b = _num(h1, k), _num(h0, k)
        deltas[k] = None if (a is None or b is None) else a - b
    return {
        "test": test, "scenario": scenario,
        "client_keep_listening": keep_listening,
        "client_stall_ms": stall_ms,
        "client": cs,
        "upstream_events": fake.events,
        "upstream_cancel_count": fake.cancel_count,
        "upstream_errors": fake.errors,
        "diag_assertions": d.get("assertions", {}),
        "diag_assertions_total": d.get("assertions_total", 0),
        # R-1d ITEM 6: send-intent accounting exposed by the new hooks
        "diag_send_intent_unresolved": d.get("send_intent_unresolved"),
        "diag_send_intent_unresolved_invalidated_gen": d.get(
            "send_intent_unresolved_invalidated_gen"),
        "diag_send_intents_n": len(d.get("send_intents") or []),
        "diag_per_conn": d.get("per_conn"),
        "diag_send_intervals_ms": d.get("send_intervals_ms"),
        "diag_generations": d.get("generations", {}),
        "diag_transcripts": d.get("transcripts"),
        "diag_send_timeline": sends,
        "diag_journal": d.get("journal_tail", []),
        "health_before": h0, "health_after": h1,
        "health_delta": deltas,
        "reset_effective": reset_effective,
        "reset_error": reset_rec,
        "client_error": err,
        "client_error_record": err_rec,
        # ---- R-1d ITEM 2/3: live-barge shape proof + per-gen accounting ----
        "barge_shape": fake.shape,
        "barge_seq_log": fake.seq_log,
        "barge_analysis": analyze_barge(d, fake),
        # ---- R-1d ITEM MULTI-ATTEMPT: per-attempt records + aggregate ----
        "attempts": cs.get("attempts"),
        "attempts_total": cs.get("attempts_total"),
        "attempts_with_new_generation": cs.get("attempts_with_new_generation"),
        # ---- R-1e ITEM 1: explicit per-generation frame accounting + overflow
        # verdict. Every number is read back from /diag, never inferred.
        "per_generation": per_generation_accounting(d),
        "overflow_verdict": overflow_verdict(d, h0, h1),
        "burst_delivery": fake.burst_stats,
        # ---- R-1e ITEM 2: capture scoping proof (see verify_capture_scope) --
        "capture_scope": verify_capture_scope(d),
    }


def per_generation_accounting(d):
    """R-1e: per-generation queued/sent/dropped/peak depth, read from /diag."""
    out = {}
    gens = d.get("generations") or {}
    for gs, st in sorted(gens.items(), key=lambda kv: int(kv[0])):
        st = st or {}
        out[str(gs)] = {
            "resp_ids": st.get("resp_ids"),
            "status": st.get("status"),
            "delta_events": st.get("delta_events"),
            "delta_bytes": st.get("delta_bytes"),
            "frames_encoded": st.get("frames_encoded"),
            "frames_queued": st.get("frames_queued"),
            "frames_sent": st.get("frames_sent"),
            "frames_dropped": st.get("frames_dropped"),
            "peak_queue_depth": st.get("peak_queue_depth"),
            "flush_discarded": st.get("flush_discarded"),
            "invalidated": st.get("invalidated"),
        }
    return out


def overflow_verdict(d, h0, h1):
    """R-1e ITEM 1: the exact fields the gate asks for, all read back.

    `audio_out_dropped` is a process-cumulative counter, so BOTH the absolute
    value and the delta across this run are reported; the delta is the number
    attributable to this scenario.
    """
    def _n(x):
        try:
            return int(x or 0)
        except Exception:  # noqa: BLE001
            return None
    gens = d.get("generations") or {}
    peak = 0
    for st in gens.values():
        st = st or {}
        try:
            peak = max(peak, int(st.get("peak_queue_depth") or 0))
        except Exception:  # noqa: BLE001
            pass
    a = d.get("assertions") or {}
    dropped_abs = _n(h1.get("audio_out_dropped"))
    dropped_delta = (None if dropped_abs is None or _n(h0.get("audio_out_dropped")) is None
                     else dropped_abs - _n(h0.get("audio_out_dropped")))
    return {
        "peak_queue_depth": peak,
        "audio_out_dropped_absolute": dropped_abs,
        "audio_out_dropped_delta_this_run": dropped_delta,
        "QUEUE_DROP_EVENT": _n(a.get("QUEUE_DROP_EVENT")),
        "assertions_full": dict(a),
        "assertions_total": d.get("assertions_total"),
        "send_intent_unresolved": d.get("send_intent_unresolved"),
        "live_pacers": (d.get("per_conn") or {}).get("live_pacers"),
        "DL_QUEUE_MAX_config": 256,
    }


async def main():
    global BRIDGE_WS, BRIDGE_HTTP, FAKE_PORT, WAVE, WAVE_GAP, U1_PKTS, U2_PKTS, UP2_AT
    global INTERRUPT_AFTER_PLAYBACK_MS, LATE_DELTA_CHUNKS, ATTEMPTS
    global INTERRUPT_DELAYS
    global BURST_CHUNKS, BURST_GAP_MS, OVERFLOW_CHUNKS, CAPTURE_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", default="all")
    ap.add_argument("--scenario", default=None, choices=SCENARIOS)
    ap.add_argument("--bridge-ws", default=BRIDGE_WS)
    ap.add_argument("--bridge-http", default=BRIDGE_HTTP)
    ap.add_argument("--fake-port", type=int, default=FAKE_PORT)
    ap.add_argument("--wave", default=WAVE, choices=("pattern", "sine", "file"))
    ap.add_argument("--wave-file", default="/tmp/rtl-diag/speech24.raw")
    ap.add_argument("--wave-gap", type=float, default=0.0)
    ap.add_argument("--uplink-file", default=None)
    ap.add_argument("--uplink-file2", default=None)
    ap.add_argument("--up2-at", type=float, default=1e9)
    ap.add_argument("--late-delta-chunks", type=int, default=LATE_DELTA_CHUNKS,
                    help="late response.audio.delta chunks emitted for the "
                         "CANCELLED response by the auto_cancel_* scenarios "
                         "(default %d)" % LATE_DELTA_CHUNKS)
    ap.add_argument("--interrupt-after-playback-ms", type=str, default="0",
                    help="0 = disabled (time-based --up2-at only); N>0 = begin "
                         "utterance 2 only after N ms of proven playback "
                         "(first binary downlink frame). Accepts a single int "
                         "(all attempts) or a comma-separated per-attempt list "
                         "e.g. 50,400,900 (the last value is reused when the "
                         "list runs out)")
    ap.add_argument("--attempts", type=int, default=1,
                    help="repeat the full cycle (utterance 1 -> playback proof "
                         "-> delay -> utterance 2 -> play out) N times inside "
                         "ONE client/Qwen session (default 1)")
    ap.add_argument("--keep-listening", default="1")
    ap.add_argument("--client-stall-ms", type=int, default=0)
    # Sentinel defaults (None): when omitted the per-test deterministic plan
    # values are used unchanged (mock t1/t2/t3 stay byte-for-byte identical).
    # When provided they OVERRIDE the plan -- previously --speak-s/--after-s
    # were parsed but never applied, which silently capped the real uplink.
    ap.add_argument("--speak-s", type=float, default=None)
    ap.add_argument("--after-s", type=float, default=None)
    # ---- R-1e ITEM 1: overflow_bursty delivery-shape knobs ----------------
    ap.add_argument("--burst-chunks", type=int, default=BURST_CHUNKS,
                    help="overflow_bursty: chunks per micro-burst, emitted "
                         "back-to-back with sub-ms spacing (default %d; the "
                         "real run measured 12-16)" % BURST_CHUNKS)
    ap.add_argument("--burst-gap-ms", type=float, default=BURST_GAP_MS,
                    help="overflow_bursty: gap between micro-bursts in ms "
                         "(default %g; the real run measured ~40)" % BURST_GAP_MS)
    ap.add_argument("--overflow-chunks", type=int, default=OVERFLOW_CHUNKS,
                    help="overflow_bursty: total chunks to stream (default %d "
                         "= %.1f s of 24 kHz audio)"
                         % (OVERFLOW_CHUNKS, OVERFLOW_CHUNKS * 0.02))
    # ---- R-1e ITEM 2: capture reset discipline ---------------------------
    ap.add_argument("--reset-capture", type=int, default=0, choices=(0, 1),
                    help="1 = TRUNCATE qwen_pcm24.raw / sent_opus.bin / "
                         "sent_opus.jsonl in --capture-dir BEFORE any traffic "
                         "starts (belt-and-braces). PREFERRED instead is a "
                         "fresh bridge side process, whose _capture_state then "
                         "starts at zero and agrees with the files")
    ap.add_argument("--capture-dir", default=CAPTURE_DIR,
                    help="directory holding the three capture files "
                         "(default: $RTL_DIAG_DIR or %s)" % CAPTURE_DIR)
    args = ap.parse_args()
    BRIDGE_WS = args.bridge_ws
    BRIDGE_HTTP = args.bridge_http
    FAKE_PORT = args.fake_port
    WAVE = args.wave
    WAVE_GAP = args.wave_gap
    UP2_AT = args.up2_at
    BURST_CHUNKS = args.burst_chunks
    BURST_GAP_MS = args.burst_gap_ms
    OVERFLOW_CHUNKS = args.overflow_chunks
    CAPTURE_DIR = args.capture_dir
    if BURST_CHUNKS < 1:
        raise SystemExit("--burst-chunks must be >= 1 (got %r)"
                         % (args.burst_chunks,))
    if BURST_GAP_MS < 0:
        raise SystemExit("--burst-gap-ms must be >= 0 (got %r)"
                         % (args.burst_gap_ms,))
    if OVERFLOW_CHUNKS < 1:
        raise SystemExit("--overflow-chunks must be >= 1 (got %r)"
                         % (args.overflow_chunks,))
    # ITEM 2: truncate BEFORE any traffic can be generated.
    if args.reset_capture:
        reset_capture(CAPTURE_DIR)
    INTERRUPT_DELAYS = parse_delay_list(args.interrupt_after_playback_ms)
    # The global keeps its historical meaning: the FIRST configured delay.
    # With a single plain integer this is exactly today's value.
    INTERRUPT_AFTER_PLAYBACK_MS = INTERRUPT_DELAYS[0]
    ATTEMPTS = args.attempts
    if ATTEMPTS < 1:
        raise SystemExit("--attempts must be >= 1 (got %r)" % (args.attempts,))
    if ATTEMPTS > 1 and not U2_PKTS and not args.uplink_file2:
        print("R1C_STATE WARN attempts=%d but no --uplink-file2 (utterance 2) "
              "was supplied; every attempt will be a no-op interruption"
              % ATTEMPTS, file=sys.stderr)
    if ATTEMPTS > 1:
        print("R1C_STATE MULTI_ATTEMPTS attempts=%d delays_ms=%s"
              % (ATTEMPTS, INTERRUPT_DELAYS), file=sys.stderr)
    LATE_DELTA_CHUNKS = args.late_delta_chunks
    if WAVE == "file":
        n = load_wave_file(args.wave_file)
        print("wave file frames=%d (%.2fs)" % (n, n * 0.02), file=sys.stderr)
    if args.uplink_file:
        e = opuslib.Encoder(16000, 1, opuslib.APPLICATION_VOIP)
        p1, f1 = load_uplink(args.uplink_file, e)
        U1_PKTS.extend(p1)
        LOAD_FAILURES.extend(f1)
        print("uplink1 packets=%d failed=%d" % (len(p1), len(f1)),
              file=sys.stderr)
        if args.uplink_file2:
            p2, f2 = load_uplink(args.uplink_file2, e)
            U2_PKTS.extend(p2)
            LOAD_FAILURES.extend(f2)
            print("uplink2 packets=%d failed=%d up2_at=%.1fs"
                  % (len(p2), len(f2), UP2_AT), file=sys.stderr)
    for f in LOAD_FAILURES:
        print("UPLINK_LOAD_FAILURE " + json.dumps(f), file=sys.stderr)
    args.speak_s_override = args.speak_s
    args.after_s_override = args.after_s

    kl = args.keep_listening == "1"
    plan = {
        "t1": [("long_pressure", kl, args.client_stall_ms, 3.0, 28.0)],
        "t2": [("barge_cancel_first", kl, 0, 4.0, 4.0),
               ("barge_cancel_first", kl, 1500, 4.0, 5.0),
               ("barge_repeat_content", kl, 0, 4.0, 4.0),
               ("barge_cancel_first", False, 0, 4.0, 4.0),
               # R-1d: the LIVE auto-cancel variant (see sc_auto_cancel)
               ("auto_cancel_live", kl, 0, 4.0, 5.0),
               ("auto_cancel_late_delta", kl, 0, 4.0, 7.0)],
        "t3": [("rapid_boundary", kl, 0, 4.0, 6.0)],
        # ---- R-1e ITEM 1: overflow via the MEASURED burst structure -------
        # Deliberately NOT part of `--test all`: t1/t2/t3 keep their exact
        # historical membership so `--test all` output stays comparable with
        # earlier gates. Run it with `--test t4` (or `--scenario
        # overflow_bursty`). speak_s/after_s give ~16 s of client window: the
        # response itself streams in ~2.3 s (900 chunks / 16 per burst / 40 ms
        # gap) and the pacer then needs ~5.5 s to drain 256 queued frames at
        # the measured ~47 fps, so the drain is fully observed.
        "t4": [("overflow_bursty", kl, 0, 4.0, 12.0)],
    }
    if args.test == "all":
        tests = ["t1", "t2", "t3"]
    else:
        tests = [args.test]

    results = []
    async with aiohttp.ClientSession() as session:
        for t in tests:
            for scen, klv, stall, sp, af in plan.get(t, []):
                if args.scenario and scen != args.scenario:
                    continue
                # explicit CLI override of the deterministic plan (defaults
                # keep the plan values -> mock behaviour unchanged)
                eff_sp = args.speak_s if args.speak_s is not None else sp
                eff_af = args.after_s if args.after_s is not None else af
                print("RUN %s/%s effective_speak_s=%s effective_after_s=%s "
                      "(plan=%s/%s override=%s/%s)" % (
                          t, scen, eff_sp, eff_af, sp, af,
                          args.speak_s, args.after_s), file=sys.stderr)
                try:
                    r = await probe(session, t, scen, klv, stall, eff_sp, eff_af)
                except Exception as e:  # noqa: BLE001
                    r = {"test": t, "scenario": scen, "error": repr(e),
                         "error_record": _exc_record("probe", e)}
                r["effective_speak_s"] = eff_sp
                r["effective_after_s"] = eff_af
                r["speak_s_overridden"] = args.speak_s is not None
                r["after_s_overridden"] = args.after_s is not None
                r["intended_uplink_frames"] = r.get("client", {}).get(
                    "intended_uplink_frames")
                r["sent_uplink_frames"] = r.get("client", {}).get(
                    "sent_uplink_frames")
                r["u1_sent_frames"] = r.get("client", {}).get("u1_sent_frames")
                r["u2_sent_frames"] = r.get("client", {}).get("u2_sent_frames")
                r["u2_intended_frames"] = r.get("client", {}).get(
                    "u2_intended_frames")
                r["interrupt_trigger_mode"] = r.get("client", {}).get(
                    "interrupt_trigger_mode")
                results.append(r)
                print("done %s/%s total_assertions=%s failed=%s" % (
                    t, scen, r.get("diag_assertions_total"),
                    r.get("client", {}).get("probe_failed")), file=sys.stderr)

    failures = list(LOAD_FAILURES)
    for r in results:
        if r.get("error"):
            failures.append(r.get("error_record")
                            or {"stage": "probe", "detail": repr(r.get("error"))})
        if r.get("client_error_record"):
            failures.append(r["client_error_record"])
        elif r.get("client_error"):
            failures.append({"stage": "client_error",
                             "detail": repr(r.get("client_error"))})
        if r.get("reset_error"):
            failures.append(r.get("reset_error")
                            if isinstance(r.get("reset_error"), dict)
                            else {"stage": "reset_error",
                                  "detail": repr(r.get("reset_error"))})
        f = r.get("client", {}).get("probe_failures") or []
        failures.extend(f)
        failures.extend(r.get("upstream_errors") or [])
    probe_ok = not failures

    print("R1C_RESULT_BEGIN")
    print(json.dumps({"probe_ok": probe_ok,
                      "load_failures": LOAD_FAILURES,
                      "failures": failures,
                      "results": results}, indent=1, default=str))
    print("R1C_RESULT_END")
    if failures:
        print("PROBE_FAILED count=%d" % len(failures), file=sys.stderr)
        for f in failures:
            print("PROBE_FAILURE " + json.dumps(f, default=str), file=sys.stderr)
    return 0 if probe_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
