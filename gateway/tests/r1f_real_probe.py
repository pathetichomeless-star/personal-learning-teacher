"""R-1f rev-9 real-Qwen controlled smoke probe (Phase 4).

Bounded paid usage: two WS sessions total (Phase 1 / Phase 2), each bounded by
timeouts and by the per-phase wall-clock budget.

Phase 1 (one session): U1 short answer -> U2 long-answer prompt -> U3 spoken
barge-in during playback -> U1 again (recovery).
Phase 2 (one session): U2 -> client `abort` mid-playback -> U1 completes ->
client WS reconnect -> U1 completes.

Evidence: JSON file with the event timeline, /health counter deltas,
/diag snapshot excerpts, closure residuals and the A.15 gate readings.

Usage (inside a container from the lab image):
  python /app/tests/r1f_real_probe.py --phase 1 --out /tmp/r1f_real_phase1.json
"""

import argparse
import asyncio
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(_HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(_HERE))

import aiohttp                                    # noqa: E402
import opuslib                                    # noqa: E402

BRIDGE_WS = "ws://127.0.0.1:28110/xiaozhi/v1/"
BRIDGE_HTTP = "http://127.0.0.1:28111"
ASSET_DIR = "/app/tests/assets"

FLUSH_KEYS = (
    "flushed_bargein_frames", "flushed_abort_frames", "flushed_close_frames",
    "flushed_listen_start_frames", "flushed_upstream_closed_frames",
    "flushed_pacer_stall_frames", "flushed_byte_cap_failure_frames",
    "flushed_send_error_frames",
)


def log_event(events, kind, **fields):
    rec = {"t": round(time.monotonic(), 3), "kind": kind}
    rec.update(fields)
    events.append(rec)
    print("EVENT %s" % json.dumps(rec, default=str), flush=True)


def load_opus(path, enc):
    raw = open(path, "rb").read()
    out = []
    for i in range(0, len(raw) - 639, 640):
        out.append(enc.encode(raw[i:i + 640], 320))
    return out


class RealProbe:
    def __init__(self, events):
        self.events = events
        self.session = None
        self.ws = None
        self.enc = opuslib.Encoder(16000, 1, opuslib.APPLICATION_VOIP)
        self.assets = {}
        self.tts_start_t = None
        self.tts_events = []
        self.packets = 0
        self.first_packet_t = None
        self.last_packet_t = None
        self._pump = None
        self._keepalive = None
        self._speaking = False
        self.last_text = None
        # Qwen server VAD only fires speech_stopped when the appended stream
        # continues with silence after the utterance -> stream silence frames
        # exactly like a real client microphone (always-on) does.
        self.silence_pkt = self.enc.encode(b"\x00" * 640, 320)

    async def connect(self):
        self.session = aiohttp.ClientSession()
        self.ws = await self.session.ws_connect(BRIDGE_WS, heartbeat=30,
                                                max_msg_size=0)
        await self.ws.send_str(json.dumps({"type": "hello", "version": 1}))
        await self.ws.send_str(json.dumps({"type": "listen", "state": "start",
                                           "mode": "realtime"}))
        await asyncio.sleep(0.3)
        self._pump = asyncio.create_task(self._read_loop())
        self._keepalive = asyncio.create_task(self._keepalive_loop())
        log_event(self.events, "client_connected")

    async def _keepalive_loop(self):
        """Always-on microphone: silence frames between utterances."""
        try:
            while True:
                await asyncio.sleep(0.02)
                if (not self._speaking and self.ws is not None
                        and not self.ws.closed):
                    await self.ws.send_bytes(self.silence_pkt)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            return

    async def _read_loop(self):
        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self.last_text = msg.data
                    try:
                        obj = json.loads(msg.data)
                    except Exception:  # noqa: BLE001
                        continue
                    if obj.get("type") == "tts":
                        state = obj.get("state")
                        self.tts_events.append((state, time.monotonic()))
                        if state == "start":
                            self.tts_start_t = time.monotonic()
                        log_event(self.events, "tts_" + str(state))
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    now = time.monotonic()
                    if self.first_packet_t is None:
                        self.first_packet_t = now
                    self.last_packet_t = now
                    self.packets += 1
                elif msg.type in (aiohttp.WSMsgType.CLOSED,
                                  aiohttp.WSMsgType.ERROR):
                    return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            return

    async def speak(self, name, pacing_ms=20.0, trail_s=1.2):
        pkts = self.assets[name]
        self._speaking = True
        log_event(self.events, "uplink_start", asset=name, packets=len(pkts))
        try:
            for p in pkts:
                if self.ws is None or self.ws.closed:
                    log_event(self.events, "uplink_aborted_ws_closed", asset=name)
                    return
                await self.ws.send_bytes(p)
                await asyncio.sleep(pacing_ms / 1000.0)
            # trailing silence so server VAD can fire speech_stopped
            n_trail = int(trail_s * 1000.0 / pacing_ms)
            for _ in range(n_trail):
                if self.ws is None or self.ws.closed:
                    break
                await self.ws.send_bytes(self.silence_pkt)
                await asyncio.sleep(pacing_ms / 1000.0)
        finally:
            self._speaking = False
        log_event(self.events, "uplink_end", asset=name)

    async def abort(self):
        await self.ws.send_str(json.dumps({"type": "abort",
                                           "reason": "probe_abort"}))
        log_event(self.events, "client_abort_sent")

    async def wait_packets(self, n, timeout):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if self.packets >= n:
                return True
            await asyncio.sleep(0.05)
        return False

    async def wait_tts_stop(self, timeout, since_index=0):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            stops = [t for s, t in self.tts_events[since_index:] if s == "stop"]
            if stops:
                return True
            await asyncio.sleep(0.05)
        return False

    async def close(self):
        if self._keepalive is not None:
            self._keepalive.cancel()
            self._keepalive = None
        if self.ws is not None and not self.ws.closed:
            await self.ws.close()
        if self._pump is not None:
            self._pump.cancel()
            self._pump = None
        if self.session is not None:
            await self.session.close()
            self.session = None


async def health():
    async with aiohttp.ClientSession() as s:
        async with s.get(BRIDGE_HTTP + "/health") as r:
            return await r.json()


async def diag():
    async with aiohttp.ClientSession() as s:
        async with s.get(BRIDGE_HTTP + "/diag") as r:
            return await r.json()


def summarise(before, after, dg, events):
    d = {k: after.get(k, 0) - before.get(k, 0)
         for k in after
         if isinstance(after.get(k), int) and isinstance(before.get(k), int)
         and not isinstance(after.get(k), bool)}
    src = d["source_pcm_bytes"] - (d["admitted_pcm_bytes"]
                                   + d["guard_dropped_pcm_bytes"]
                                   + d["safety_truncated_pcm_bytes"])
    g = lambda k: after.get(k) or 0
    frm = (d["admitted_pcm_bytes"]
           - (960 * d["encoded_full_frames"] + 960 * d["encode_failed_frames"]
              + d["synthetic_tail_source_bytes"]
              + d["synthetic_tail_encode_failed_source_bytes"]
              + d["residue_discarded_pcm_bytes"]
              + g("still_buffered_pcm_bytes")))
    disp = (d["encoded_full_frames"] + d["synthetic_tail_frames"]
            - (d["sent_confirmed_frames"] + sum(d[k] for k in FLUSH_KEYS)
               + d["send_failed_frames"] + d["send_outcome_unknown_frames"]
               + g("still_stored_frames") + g("in_flight_frames")))
    segs = dg.get("steady_segments") or []
    rates = [s.get("segment_rate_fps") for s in segs if s.get("qualifying")]
    means = [s.get("segment_mean_inter_send_ms") for s in segs
             if s.get("qualifying")]
    return {
        "deltas": d,
        "counter_delta_subset": {k: d.get(k) for k in (
            "source_pcm_bytes", "admitted_pcm_bytes", "guard_dropped_pcm_bytes",
            "safety_truncated_pcm_bytes", "orphan_pcm_bytes",
            "encoded_full_frames", "synthetic_tail_frames",
            "sent_confirmed_frames", "send_failed_frames",
            "send_outcome_unknown_frames", "post_terminal_sends_total",
            "qwen_dispatch_errors_total", "accounting_fault_events",
            "post_terminal_delta_events", "bad_base64_live_events",
            "byte_cap_failures", "cap_transitions_total",
            "pacer_starts", "pacer_rebases", "pacer_fatal_stalls",
            "pacer_short_interval_count", "slow_send_events",
            "slow_send_guard_violations", "barge_in_sequences_total",
            "barge_in_sequence_incomplete", "cancel_attempts",
            "cancel_send_errors", "responses_completed",
            "responses_cancelled", "upstream_errors")},
        "closure_residuals": {"source": src, "framer": frm, "disposition": disp},
        "health_readings": {k: after.get(k) for k in (
            "steady_pacer_segments_qualifying_total",
            "steady_segment_rate_fps_min", "steady_segment_rate_fps_max",
            "steady_segment_mean_inter_send_ms_min",
            "steady_segment_mean_inter_send_ms_max",
            "steady_segment_frames_max",
            "pacer_min_inter_send_ms_observed",
            "wire_rate_excess_frames_max", "active_pacer_tasks_max",
            "unsent_backlog_peak_frames", "audio_store_peak_frames",
            "end_markers_max_per_generation",
            "tts_stop_emissions_max_per_generation",
            "cancel_max_per_generation", "cap_transitions_max_per_generation",
            "pacer_wake_overshoot_mean_ms_observed",
            "residue_discarded_pcm_bytes", "audio_rebase_discarded_frames",
            "legacy_drop_oldest_calls")},
        "qualifying_segments": {
            "count": len(rates),
            "rate_fps_min": min(rates) if rates else None,
            "rate_fps_max": max(rates) if rates else None,
            "mean_ms_min": min(means) if means else None,
            "mean_ms_max": max(means) if means else None,
        },
        "diag_assertions": dg.get("assertions") or {},
        "diag_generations": dg.get("generations") or {},
        "events": events,
    }


async def phase1(probe, budget_s):
    t0 = time.monotonic()
    # 1) short answer
    await probe.speak("u1")
    ok1 = await probe.wait_tts_stop(30)
    log_event(probe.events, "phase1_turn1_done", ok=ok1,
              packets=probe.packets)
    # 2) long-answer prompt
    pk_before = probe.packets
    await probe.speak("u2")
    started = await probe.wait_packets(pk_before + 20, 40)
    log_event(probe.events, "phase1_turn2_started", ok=started)
    # let it play for a while, then barge in with real speech
    await asyncio.sleep(6.0)
    idx = len(probe.tts_events)
    await probe.speak("u3")
    barged = await probe.wait_tts_stop(20, since_index=idx)
    log_event(probe.events, "phase1_bargein", stop_seen=barged,
              tts_events=list(probe.tts_events[-6:]))
    await asyncio.sleep(1.0)
    # 3) recovery turn
    idx2 = len(probe.tts_events)
    await probe.speak("u1")
    recovered = await probe.wait_tts_stop(30, since_index=idx2)
    log_event(probe.events, "phase1_turn3_recovery_done", ok=recovered)
    return {"turn1": ok1, "turn2_started": started, "bargein_stop": barged,
            "recovery": recovered,
            "elapsed_s": round(time.monotonic() - t0, 1)}


async def phase2(probe, budget_s):
    t0 = time.monotonic()
    # 1) long response, then client abort mid-playback
    pk_before = probe.packets
    await probe.speak("u2")
    await probe.wait_packets(pk_before + 40, 40)
    await asyncio.sleep(3.0)
    idx = len(probe.tts_events)
    await probe.abort()
    aborted = await probe.wait_tts_stop(15, since_index=idx)
    log_event(probe.events, "phase2_abort", stop_seen=aborted)
    # 2) next turn completes
    idx2 = len(probe.tts_events)
    await probe.speak("u1")
    ok2 = await probe.wait_tts_stop(30, since_index=idx2)
    log_event(probe.events, "phase2_turn2_done", ok=ok2)
    # 3) client reconnect, final turn
    await probe.close()
    await asyncio.sleep(1.0)
    probe.ws = None
    probe.packets = 0
    await probe.connect()
    idx3 = len(probe.tts_events)
    await probe.speak("u1")
    ok3 = await probe.wait_tts_stop(30, since_index=idx3)
    log_event(probe.events, "phase2_reconnect_turn_done", ok=ok3)
    return {"abort_stop": aborted, "turn2": ok2, "reconnect_turn": ok3,
            "elapsed_s": round(time.monotonic() - t0, 1)}


async def wait_quiescence(timeout=90.0, poll=0.5):
    """Closures are asserted at generation quiescence (A.4.C): no queued
    encoded frames, no in-flight frame, no dl_buf residue."""
    t0 = time.monotonic()
    last = None
    while time.monotonic() - t0 < timeout:
        h = await health()
        last = (h.get("audio_store_current_frames"),
                h.get("in_flight_frames"),
                h.get("unsent_backlog_current_frames"),
                h.get("still_buffered_pcm_bytes"))
        if last == (0, 0, 0, 0):
            return True, last, round(time.monotonic() - t0, 1)
        await asyncio.sleep(poll)
    return False, last, round(time.monotonic() - t0, 1)


async def amain(args):
    events = []
    before = await health()
    # warm /diag snapshot (may be disabled -> verdict recorded)
    dg0 = await diag()
    probe = RealProbe(events)
    assets = {"u1": args.u1, "u2": args.u2, "u3": args.u3}
    for k, p in assets.items():
        probe.assets[k] = load_opus(p, probe.enc)
        log_event(events, "asset_loaded", asset=k, packets=len(probe.assets[k]))
    await probe.connect()
    try:
        if args.phase == "1":
            result = await asyncio.wait_for(phase1(probe, args.budget),
                                            args.budget)
        else:
            result = await asyncio.wait_for(phase2(probe, args.budget),
                                            args.budget)
        quiesced, gauge, waited = await wait_quiescence(args.quiesce_budget)
        log_event(events, "quiescence", ok=quiesced, gauges=list(gauge),
                  waited_s=waited)
    finally:
        after = await health()
        dg = await diag()
        await probe.close()
    summary = summarise(before, after, dg, events)
    summary["phase_result"] = result
    summary["quiescence"] = {"ok": bool(quiesced), "gauges": list(gauge),
                             "waited_s": waited}
    summary["diag_enabled"] = dg.get("enabled")
    summary["config"] = {
        "bridge_ws": BRIDGE_WS, "phase": args.phase,
        "assets": assets, "budget_s": args.budget,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    print("PROBE_SUMMARY %s" % json.dumps({
        "phase_result": result,
        "closure_residuals": summary["closure_residuals"],
        "health_readings": summary["health_readings"],
        "qualifying_segments": summary["qualifying_segments"],
        "diag_assertions": summary["diag_assertions"],
        "diag_enabled": summary["diag_enabled"],
    }, indent=2, default=str))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", default="1", choices=("1", "2"))
    ap.add_argument("--u1", default=os.path.join(ASSET_DIR, "u1.pcm16k.raw"))
    ap.add_argument("--u2", default=os.path.join(ASSET_DIR, "u2.pcm16k.raw"))
    ap.add_argument("--u3", default=os.path.join(ASSET_DIR, "u3.pcm16k.raw"))
    ap.add_argument("--budget", type=float, default=240.0)
    ap.add_argument("--quiesce-budget", type=float, default=120.0)
    ap.add_argument("--out", default="/tmp/r1f_real_probe.json")
    args = ap.parse_args()
    return asyncio.run(amain(args))


if __name__ == "__main__":
    sys.exit(main())