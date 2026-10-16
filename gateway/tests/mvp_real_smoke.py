"""CONVERSATIONAL MVP — bounded REAL Qwen smoke (ONE session).

Runs INSIDE the MVP sidecar container.  Drives the real pipeline with the
behavior/memory/workbench link active:

  turn 1: asset `u1` short utterance -> expect a completed response
  turn 2: asset `u2` long utterance -> playback starts, then spoken barge-in
          with `u3` mid-playback (Path B must stop playback)
  turn 3: `u1` again -> recovery

Evidence written to --out (JSON): tts timeline, packet counts, transcripts
received by the client, health deltas, closure residuals.  The transcript of
each turn is recorded so the behavior link's routing (log-grepped separately)
can be correlated.

Usage (inside the container):
  python /app/tests/mvp_real_smoke.py --out /tmp/mvp_real_smoke.json
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

WS = "ws://127.0.0.1:8110/xiaozhi/v1/"
HTTP = "http://127.0.0.1:8111"
ASSETS = os.path.join(_HERE, "assets")

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
    print("EVENT %s" % json.dumps(rec, default=str)[:300], flush=True)


def load_opus(path, enc):
    raw = open(path, "rb").read()
    return [enc.encode(raw[i:i + 640], 320)
            for i in range(0, len(raw) - 639, 640)]


class Smoke:
    def __init__(self, events):
        self.events = events
        self.session = None
        self.ws = None
        self.enc = opuslib.Encoder(16000, 1, opuslib.APPLICATION_VOIP)
        self.assets = {}
        self.tts_events = []
        self.packets = 0
        self.first_packet_t = None
        self.last_packet_t = None
        self.transcripts = []
        self._pump = None
        self._keepalive = None
        self._speaking = False
        self.silence_pkt = self.enc.encode(b"\x00" * 640, 320)

    async def connect(self):
        self.session = aiohttp.ClientSession()
        self.ws = await self.session.ws_connect(WS, heartbeat=30,
                                                max_msg_size=0)
        await self.ws.send_str(json.dumps({"type": "hello", "version": 1}))
        await self.ws.send_str(json.dumps({"type": "listen", "state": "start",
                                           "mode": "realtime"}))
        await asyncio.sleep(0.3)
        self._pump = asyncio.create_task(self._read_loop())
        self._keepalive = asyncio.create_task(self._keepalive_loop())
        log_event(self.events, "client_connected")

    async def _keepalive_loop(self):
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
                    try:
                        obj = json.loads(msg.data)
                    except Exception:  # noqa: BLE001
                        continue
                    t = obj.get("type")
                    if t == "tts":
                        self.tts_events.append((obj.get("state"),
                                                time.monotonic()))
                        log_event(self.events, "tts_" + str(obj.get("state")))
                    elif t == "transcript":
                        self.transcripts.append(obj)
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

    async def speak(self, name, trail_s=1.2):
        pkts = self.assets[name]
        self._speaking = True
        log_event(self.events, "uplink_start", asset=name, packets=len(pkts))
        try:
            for p in pkts:
                if self.ws is None or self.ws.closed:
                    return
                await self.ws.send_bytes(p)
                await asyncio.sleep(0.02)
            for _ in range(int(trail_s * 50)):
                if self.ws is None or self.ws.closed:
                    break
                await self.ws.send_bytes(self.silence_pkt)
                await asyncio.sleep(0.02)
        finally:
            self._speaking = False
        log_event(self.events, "uplink_end", asset=name)

    async def wait_tts_stop(self, timeout, since=0):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if any(s == "stop" for s, _ in self.tts_events[since:]):
                return True
            await asyncio.sleep(0.05)
        return False

    async def close(self):
        for attr in ("_keepalive", "_pump"):
            t = getattr(self, attr)
            if t is not None:
                t.cancel()
                setattr(self, attr, None)
        if self.ws is not None and not self.ws.closed:
            await self.ws.close()
        if self.session is not None:
            await self.session.close()
            self.session = None


async def health():
    async with aiohttp.ClientSession() as s:
        async with s.get(HTTP + "/health") as r:
            return await r.json()


async def amain(args):
    events = []
    before = await health()
    smoke = Smoke(events)
    for k in ("u1", "u2", "u3"):
        smoke.assets[k] = load_opus(os.path.join(ASSETS, k + ".pcm16k.raw"),
                                    smoke.enc)
        log_event(events, "asset_loaded", asset=k, packets=len(smoke.assets[k]))
    await smoke.connect()
    result = {}
    try:
        # turn 1
        idx = len(smoke.tts_events)
        await smoke.speak("u1")
        result["turn1_done"] = await smoke.wait_tts_stop(30, since=idx)
        log_event(events, "turn1", ok=result["turn1_done"])

        # turn 2 + spoken barge-in
        pk_before = smoke.packets
        idx = len(smoke.tts_events)
        await smoke.speak("u2")
        result["turn2_audio_started"] = await wait_packets(smoke,
                                                           pk_before + 20, 40)
        await asyncio.sleep(5.0)
        idx_b = len(smoke.tts_events)
        await smoke.speak("u3")
        result["bargein_stop"] = await smoke.wait_tts_stop(20, since=idx_b)
        log_event(events, "bargein", stop=result["bargein_stop"])

        # turn 3 recovery
        await asyncio.sleep(1.0)
        idx = len(smoke.tts_events)
        await smoke.speak("u1")
        result["turn3_recovery"] = await smoke.wait_tts_stop(30, since=idx)
        log_event(events, "turn3", ok=result["turn3_recovery"])

        # quiescence
        result["quiesced"] = await wait_quiescence(60)
    finally:
        after = await health()
        await smoke.close()

    deltas = {k: after.get(k, 0) - before.get(k, 0) for k in after
              if isinstance(after.get(k), int)
              and isinstance(before.get(k), int)
              and not isinstance(after.get(k), bool)}
    closure = {
        "source": deltas.get("source_pcm_bytes", 0) - (
            deltas.get("admitted_pcm_bytes", 0)
            + deltas.get("guard_dropped_pcm_bytes", 0)
            + deltas.get("safety_truncated_pcm_bytes", 0)),
        "framer": deltas.get("admitted_pcm_bytes", 0) - (
            960 * deltas.get("encoded_full_frames", 0)
            + deltas.get("synthetic_tail_source_bytes", 0)
            + deltas.get("residue_discarded_pcm_bytes", 0)
            + (after.get("still_buffered_pcm_bytes") or 0)),
        "disposition": deltas.get("encoded_full_frames", 0)
        + deltas.get("synthetic_tail_frames", 0)
        - (deltas.get("sent_confirmed_frames", 0)
           + sum(deltas.get(k, 0) for k in FLUSH_KEYS)
           + deltas.get("send_failed_frames", 0)
           + deltas.get("send_outcome_unknown_frames", 0)
           + (after.get("still_stored_frames") or 0)
           + (after.get("in_flight_frames") or 0)),
    }
    evidence = {
        "probe": "mvp_real_smoke",
        "result": result,
        "closure_residuals": closure,
        "health_after": {k: after.get(k) for k in (
            "qwen_connected", "qwen_sessions", "responses_completed",
            "responses_cancelled", "barge_ins", "upstream_errors",
            "qwen_dispatch_errors_total", "accounting_fault_events",
            "orphan_pcm_bytes", "pacer_starts", "pacer_rebases",
            "pacer_fatal_stalls", "audio_store_peak_frames")},
        "deltas": {k: deltas.get(k) for k in (
            "source_pcm_bytes", "admitted_pcm_bytes", "encoded_full_frames",
            "sent_confirmed_frames", "barge_in_sequences_total",
            "responses_completed", "responses_cancelled")},
        "packets": smoke.packets,
        "transcripts": smoke.transcripts[-30:],
        "tts_events": [(s, round(t, 3)) for s, t in smoke.tts_events],
        "events": events,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(evidence, f, ensure_ascii=False, indent=2, default=str)
    print("SMOKE_RESULT %s" % json.dumps(result, default=str))
    print("SMOKE_CLOSURES %s" % json.dumps(closure, default=str))
    print("SMOKE_TRANSCRIPTS %s" % json.dumps(
        [{"role": t.get("role"), "text": (t.get("text") or t.get("delta") or "")[:60],
          "final": t.get("final")} for t in smoke.transcripts[-8:]],
        ensure_ascii=False))
    print("SMOKE_DONE out=%s" % args.out)
    return 0


async def wait_packets(smoke, n, timeout):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if smoke.packets >= n:
            return True
        await asyncio.sleep(0.05)
    return False


async def wait_quiescence(timeout=60, poll=0.5):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        h = await health()
        if (h.get("audio_store_current_frames"), h.get("in_flight_frames"),
                h.get("unsent_backlog_current_frames"),
                h.get("still_buffered_pcm_bytes")) == (0, 0, 0, 0):
            return True
        await asyncio.sleep(poll)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/mvp_real_smoke.json")
    args = ap.parse_args()
    return asyncio.run(amain(args))


if __name__ == "__main__":
    sys.exit(main())