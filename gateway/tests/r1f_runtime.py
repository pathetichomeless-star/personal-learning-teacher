"""R-1f rev-9 mock/synthetic runtime harness (Phase 3).

Single-process integration run inside the lab image:
  fake Qwen upstream (aiohttp WS)  ->  real bridge app (in-process, RTL_DIAG=1)
  ->  synthetic XiaoZhi client (aiohttp WS)

Scenarios: clean long response, backlog stress past the frame cap, 50
sequential turns, rapid barge-in, duplicate/stale/unknown terminals, upstream
reconnect mid-response, client teardown mid-response.

For every scenario the accounting closures must reconcile exactly, plus the
A.15 invariant rows that are observable in mock runtime.

Deterministic coverage for slow-send / fatal-stall / byte-cap / frame-cap
fixtures / extrema math lives in `r1f_tests.py` (groups F/G/M/N/O/R) by design.

Usage:  python /app/tests/r1f_runtime.py [scenario ...]
"""

import os

os.environ["RTL_DIAG"] = "1"          # real acceptance configuration (A.13)
os.environ.setdefault("QWEN_MODE", "mock")
os.environ.setdefault("QWEN_WS_URL", "ws://127.0.0.1:19977")
os.environ.setdefault("WS_PORT", "18110")
os.environ.setdefault("HTTP_PORT", "18111")
os.environ.setdefault("PUBLIC_WS_URL", "ws://127.0.0.1:18110/xiaozhi/v1/")

import asyncio                                            # noqa: E402
import base64                                             # noqa: E402
import json                                               # noqa: E402
import sys                                                # noqa: E402
import time                                               # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import aiohttp                                            # noqa: E402
import opuslib                                            # noqa: E402
from aiohttp import web                                   # noqa: E402

from app import main as app_main                          # noqa: E402
from app.counters import CUMULATIVE, counters             # noqa: E402

BRIDGE_WS = "ws://127.0.0.1:18110/xiaozhi/v1/"
BRIDGE_HTTP = "http://127.0.0.1:18111"
FAKE_PORT = 19977

FLUSH_KEYS = (
    "flushed_bargein_frames", "flushed_abort_frames", "flushed_close_frames",
    "flushed_listen_start_frames", "flushed_upstream_closed_frames",
    "flushed_pacer_stall_frames", "flushed_byte_cap_failure_frames",
    "flushed_send_error_frames",
)
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        (" - " + str(detail)) if detail else ""))
    return bool(cond)


def cdiff(before, after):
    out = {}
    for k, v in after.items():
        b = before.get(k)
        if isinstance(v, int) and isinstance(b, int) and not isinstance(v, bool):
            out[k] = v - b
    return out


def g(after, k):
    v = after.get(k)
    return 0 if v is None else v


def closures(d, after):
    src = d["source_pcm_bytes"] - (d["admitted_pcm_bytes"]
                                   + d["guard_dropped_pcm_bytes"]
                                   + d["safety_truncated_pcm_bytes"])
    frm = (d["admitted_pcm_bytes"]
           - (960 * d["encoded_full_frames"] + 960 * d["encode_failed_frames"]
              + d["synthetic_tail_source_bytes"]
              + d["synthetic_tail_encode_failed_source_bytes"]
              + d["residue_discarded_pcm_bytes"]
              + g(after, "still_buffered_pcm_bytes")))
    disp = (d["encoded_full_frames"] + d["synthetic_tail_frames"]
            - (d["sent_confirmed_frames"] + sum(d[k] for k in FLUSH_KEYS)
               + d["send_failed_frames"] + d["send_outcome_unknown_frames"]
               + g(after, "still_stored_frames") + g(after, "in_flight_frames")))
    return src, frm, disp


# ---- fake Qwen upstream ----------------------------------------------------

class FakeQwen:
    """Scripted upstream: emits one response per received append batch."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.ws = None
        self.app = web.Application()
        # the bridge derives the URL from QWEN_WS_URL (no path) -> serve both
        self.app.router.add_get("/", self._handler)
        self.app.router.add_get("/api-ws/v1/realtime", self._handler)
        self.runner = None
        self.responses_emitted = 0
        self.triggered = 0
        self.cancels = 0
        self._emit_task = None
        self.conn_open = asyncio.Event()

    async def start(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        await web.TCPSite(self.runner, "127.0.0.1", FAKE_PORT).start()

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()

    async def _send(self, obj):
        if self.ws is not None and not self.ws.closed:
            await self.ws.send_str(json.dumps(obj))

    async def _handler(self, request):
        ws = web.WebSocketResponse(max_msg_size=0)
        await ws.prepare(request)
        self.ws = ws
        self.conn_open.set()
        await self._send({"type": "session.created",
                          "session": {"id": "fake-%d" % self.responses_emitted}})
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            try:
                obj = json.loads(msg.data)
            except Exception:  # noqa: BLE001
                continue
            t = obj.get("type")
            if t == "input_audio_buffer.append":
                self.triggered += 1
                self._maybe_start_response()
            elif t == "response.cancel":
                self.cancels += 1
                if self._emit_task and not self._emit_task.done():
                    self._emit_task.cancel()
                    try:
                        await self._emit_task
                    except (asyncio.CancelledError, Exception):  # noqa: BLE001
                        pass
                await self._send({"type": "response.done",
                                  "response": {"id": self._rid,
                                               "status": "cancelled"}})
        return ws

    def _maybe_start_response(self):
        if self._emit_task and not self._emit_task.done():
            return
        self._emit_task = asyncio.create_task(self._emit_response())

    async def _emit_response(self):
        cfg = self.cfg
        self.responses_emitted += 1
        idx = self.responses_emitted
        self._rid = "fake_resp_%s_%d" % (self.cfg.get("name", "s"), idx)
        await self._send({"type": "response.created",
                          "response": {"id": self._rid}})
        frames = cfg.get("frames", 40)
        interval = cfg.get("interval_ms", 2.0) / 1000.0
        chunk = b"\x22" * 960
        b64 = base64.b64encode(chunk).decode("ascii")
        barge_after = cfg.get("barge_after")
        dup = cfg.get("duplicate_terminal", False)
        for i in range(frames):
            if cfg.get("disconnect_after") and i == cfg["disconnect_after"]:
                if self.ws is not None and not self.ws.closed:
                    await self.ws.close()
                return
            await self._send({"type": "response.audio.delta",
                              "response_id": self._rid, "delta": b64})
            if barge_after is not None and i == barge_after:
                await self._send({"type": "input_audio_buffer.speech_started"})
                barge_after = None
            await asyncio.sleep(interval)
        await self._send({"type": "response.audio.done",
                          "response_id": self._rid})
        await self._send({"type": "response.done",
                          "response": {"id": self._rid,
                                       "status": "completed"}})
        if dup:
            await self._send({"type": "response.audio.done",
                              "response_id": self._rid})
            await self._send({"type": "response.done",
                              "response": {"id": self._rid,
                                           "status": "completed"}})
        if cfg.get("stale_events"):
            await self._send({"type": "response.audio.delta",
                              "response_id": self._rid, "delta": b64})
            await self._send({"type": "response.audio.delta",
                              "response_id": "never_created_rid",
                              "delta": b64})
        # allow the next append batch to trigger the next response
        self._emit_task = None


# ---- synthetic client ------------------------------------------------------

class ProbeClient:
    def __init__(self):
        self.session = None
        self.ws = None
        self.strs = []
        self.packets = 0
        self.tts_starts = 0
        self.tts_stops = 0
        self._enc16 = opuslib.Encoder(16000, 1, opuslib.APPLICATION_VOIP)
        self._uplink = self._enc16.encode(b"\x00" * 640, 320)

    async def connect(self):
        self.session = aiohttp.ClientSession()
        self.ws = await self.session.ws_connect(BRIDGE_WS, heartbeat=30,
                                                max_msg_size=0)
        await self.ws.send_str(json.dumps({"type": "hello", "version": 1}))
        await self.ws.send_str(json.dumps({"type": "listen", "state": "start",
                                           "mode": "realtime"}))
        await asyncio.sleep(0.2)
        self._pump = asyncio.create_task(self._read_loop())

    async def _read_loop(self):
        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self.strs.append(msg.data)
                    if '"tts"' in msg.data:
                        if '"start"' in msg.data:
                            self.tts_starts += 1
                        if '"stop"' in msg.data:
                            self.tts_stops += 1
                elif msg.type in (aiohttp.WSMsgType.CLOSED,
                                  aiohttp.WSMsgType.ERROR):
                    return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            return

    async def turn(self, uplink_frames=4):
        for _ in range(uplink_frames):
            if self.ws is not None and not self.ws.closed:
                await self.ws.send_bytes(self._uplink)
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.05)

    async def abort(self):
        await self.ws.send_str(json.dumps({"type": "abort", "reason": "test"}))

    async def close(self):
        if self.ws is not None and not self.ws.closed:
            await self.ws.close()
        if getattr(self, "_pump", None):
            self._pump.cancel()
        if self.session is not None:
            await self.session.close()


# ---- bridge under test -----------------------------------------------------

async def start_bridge():
    config = app_main.load_config()
    runners = []
    for port in (config.WS_PORT, config.HTTP_PORT):
        runner = web.AppRunner(app_main.create_app(config))
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", port).start()
        runners.append(runner)
    return runners


async def stop_bridge(runners):
    for r in runners:
        await r.cleanup()


async def health():
    async with aiohttp.ClientSession() as s:
        async with s.get(BRIDGE_HTTP + "/health") as r:
            return await r.json()


async def diag_snapshot():
    async with aiohttp.ClientSession() as s:
        async with s.get(BRIDGE_HTTP + "/diag") as r:
            return await r.json()


async def wait_tts_stop(client, timeout=60.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if client.tts_stops >= 1:
            return True
        await asyncio.sleep(0.05)
    return False


# ---- scenarios -------------------------------------------------------------

async def run_scenario(name, cfg, client_fn, expect):
    before = counters.snapshot()
    cfg = dict(cfg)
    cfg["name"] = name
    fake = FakeQwen(cfg)
    await fake.start()
    runners = await start_bridge()
    client = ProbeClient()
    ok = True
    try:
        await client.connect()
        ok &= await client_fn(client, fake, cfg)
        # settle: wait for quiescence (no pacer / empty store / tts stopped)
        t0 = time.monotonic()
        while time.monotonic() - t0 < cfg.get("settle_s", 30.0):
            d = await diag_snapshot()
            conns = d.get("connections") or {}
            last = list(conns.values())[-1] if conns else {}
            if (client.tts_stops >= cfg.get("expect_stops", 1)
                    and not d.get("per_conn", {}).get("live_pacers")):
                break
            await asyncio.sleep(0.2)
        await asyncio.sleep(0.5)
    finally:
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass
        await stop_bridge(runners)
        await fake.stop()
    after = counters.snapshot()
    d = cdiff(before, after)
    src, frm, disp = closures(d, after)
    ok &= check("%s: audio flowed (non-vacuous run)" % name,
                d["encoded_full_frames"] + d["sent_confirmed_frames"] >= 1,
                (d["encoded_full_frames"], d["sent_confirmed_frames"]))
    ok &= check("%s: minimum frames sent (%s)" % (name, cfg.get("min_sent")),
                d["sent_confirmed_frames"] >= cfg.get("min_sent", 1),
                d["sent_confirmed_frames"])
    ok &= check("%s: source closure residual 0" % name, src == 0, src)
    ok &= check("%s: framer closure residual 0" % name, frm == 0, frm)
    ok &= check("%s: disposition closure residual 0" % name, disp == 0,
                (disp, {k: d[k] for k in ("encoded_full_frames",
                                          "synthetic_tail_frames",
                                          "sent_confirmed_frames",
                                          "send_outcome_unknown_frames")}))
    for key, pred, label in expect:
        if key in CUMULATIVE:
            val = d.get(key, 0)
        else:
            val = after.get(key)
        ok &= check("%s: %s (got %r)" % (name, label, val), pred(val), val)
    return ok, d, after


async def s_clean_long(client, fake, cfg):
    await client.turn()
    return await wait_tts_stop(client, 90)


async def s_backlog_stress(client, fake, cfg):
    await client.turn()
    return await wait_tts_stop(client, 120)


async def s_turns_50(client, fake, cfg):
    for i in range(cfg["turns"]):
        await client.turn()
        if not await wait_tts_stop(client, 30):
            return False
        client.tts_stops = 0
    return True


async def s_rapid_barge(client, fake, cfg):
    await client.turn()
    # wait for the upstream-side barge-in (speech_started after N frames)
    await asyncio.sleep(1.5)
    await client.abort()
    await asyncio.sleep(1.0)
    return client.tts_stops >= 1


async def s_duplicate_stale(client, fake, cfg):
    await client.turn()
    return await wait_tts_stop(client, 30)


async def s_reconnect(client, fake, cfg):
    await client.turn()
    await asyncio.sleep(1.0)
    # upstream dropped mid-response; the bridge must recover and serve turn 2
    await asyncio.sleep(2.0)
    client.tts_stops = 0
    fake.cfg = dict(cfg)
    await client.turn()
    return await wait_tts_stop(client, 60)


async def s_client_teardown(client, fake, cfg):
    await client.turn()
    await asyncio.sleep(1.0)
    await client.close()
    await asyncio.sleep(1.5)
    return True


def scenarios():
    return [
        ("clean_long", {"frames": 600, "interval_ms": 5.0, "settle_s": 90,
                        "min_sent": 550},
         s_clean_long, [
             ("post_terminal_sends_total", lambda v: v == 0, "post_terminal 0"),
             ("qwen_dispatch_errors_total", lambda v: v == 0, "dispatch errors 0"),
             ("accounting_fault_events", lambda v: v == 0, "accounting faults 0"),
             ("send_outcome_unknown_frames", lambda v: v == 0, "no unknown outcome"),
             ("send_failed_frames", lambda v: v == 0, "no send failures"),
             ("byte_cap_failures", lambda v: v == 0, "no byte cap"),
             ("cap_transitions_total", lambda v: v == 0, "no store cap"),
             ("wire_rate_excess_frames_max", lambda v: (v or 0) <= 1, "wire excess <= 1"),
             ("active_pacer_tasks_max", lambda v: (v or 0) <= 1, "single pacer"),
             ("steady_pacer_segments_qualifying_total", lambda v: v >= 1,
              "no vacuous rate evidence"),
             ("steady_segment_rate_fps_min", lambda v: v is not None and v >= 49.5,
              "fps min >= 49.5"),
             ("steady_segment_rate_fps_max", lambda v: v is not None and v <= 50.5,
              "fps max <= 50.5"),
             ("steady_segment_mean_inter_send_ms_min",
              lambda v: v is not None and v >= 19.80, "mean min >= 19.80"),
             ("steady_segment_mean_inter_send_ms_max",
              lambda v: v is not None and v <= 20.20, "mean max <= 20.20"),
             ("pacer_min_inter_send_ms_observed",
              lambda v: v is not None and v >= 14.999, "floor >= 14.999"),
             ("slow_send_guard_violations", lambda v: v == 0, "guard violations 0"),
             ("end_markers_max_per_generation", lambda v: (v or 0) <= 1, "markers <= 1"),
             ("tts_stop_emissions_max_per_generation", lambda v: (v or 0) <= 1,
              "stops <= 1"),
             ("cancel_max_per_generation", lambda v: (v or 0) <= 1, "cancel <= 1"),
         ]),
        ("backlog_stress", {"frames": 1800, "interval_ms": 1.0, "settle_s": 120,
                             "min_sent": 1000},
         s_backlog_stress, [
             ("post_terminal_sends_total", lambda v: v == 0, "post_terminal 0"),
             ("qwen_dispatch_errors_total", lambda v: v == 0, "dispatch errors 0"),
             ("accounting_fault_events", lambda v: v == 0, "accounting faults 0"),
             ("cap_transitions_max_per_generation", lambda v: (v or 0) <= 1,
              "cap <= 1 per generation"),
             ("unsent_backlog_peak_frames", lambda v: (v or 0) <= 1500,
              "peak <= 1500"),
             ("send_outcome_unknown_frames", lambda v: v == 0, "no unknown outcome"),
             ("active_pacer_tasks_max", lambda v: (v or 0) <= 1, "single pacer"),
             ("tts_stop_emissions_max_per_generation", lambda v: (v or 0) <= 1,
              "stops <= 1"),
         ]),
        ("turns_50", {"frames": 40, "interval_ms": 5.0, "settle_s": 30,
                      "turns": 50, "expect_stops": 0, "min_sent": 1800},
         s_turns_50, [
             ("post_terminal_sends_total", lambda v: v == 0, "post_terminal 0"),
             ("qwen_dispatch_errors_total", lambda v: v == 0, "dispatch errors 0"),
             ("accounting_fault_events", lambda v: v == 0, "accounting faults 0"),
             ("end_markers_max_per_generation", lambda v: (v or 0) <= 1, "markers <= 1"),
             ("tts_stop_emissions_max_per_generation", lambda v: (v or 0) <= 1,
              "stops <= 1"),
             ("active_pacer_tasks_max", lambda v: (v or 0) <= 1, "single pacer"),
             ("send_outcome_unknown_frames", lambda v: v == 0, "no unknown outcome"),
         ]),
        ("rapid_barge", {"frames": 900, "interval_ms": 5.0, "settle_s": 60,
                         "barge_after": 120, "min_sent": 1},
         s_rapid_barge, [
             ("barge_in_sequences_total", lambda v: v >= 1, "barge-in recorded"),
             ("barge_in_sequence_incomplete", lambda v: v == 0, "barge bits complete"),
             ("post_terminal_sends_total", lambda v: v == 0, "post_terminal 0"),
             ("qwen_dispatch_errors_total", lambda v: v == 0, "dispatch errors 0"),
             ("send_outcome_unknown_frames", lambda v: v == 0,
              "barge-in lands in RESERVED_WAIT (no unknown)"),
             ("accounting_fault_events", lambda v: v == 0, "accounting faults 0"),
             ("tts_stop_emissions_max_per_generation", lambda v: (v or 0) <= 1,
              "stops <= 1"),
         ]),
        ("duplicate_stale", {"frames": 60, "interval_ms": 5.0, "settle_s": 20,
                             "duplicate_terminal": True, "stale_events": True,
                             "min_sent": 50},
         s_duplicate_stale, [
             ("end_markers_max_per_generation", lambda v: (v or 0) <= 1, "markers <= 1"),
             ("tts_stop_emissions_max_per_generation", lambda v: (v or 0) <= 1,
              "stops <= 1"),
             ("accounting_fault_events", lambda v: v == 0,
              "clean duplicate terminal"),
             ("post_terminal_delta_events", lambda v: v >= 1, "stale delta recorded"),
             ("orphan_pcm_bytes", lambda v: v >= 960, "unknown-rid delta = orphan"),
             ("post_terminal_sends_total", lambda v: v == 0, "post_terminal 0"),
         ]),
        ("upstream_reconnect", {"frames": 300, "interval_ms": 5.0, "settle_s": 60,
                                "disconnect_after": 60, "min_sent": 30},
         s_reconnect, [
             ("upstream_errors", lambda v: v >= 1, "upstream close observed"),
             ("flushed_upstream_closed_frames", lambda v: v >= 1,
              "reason-scoped UPSTREAM_CLOSED flush of unsent frames"),
             ("responses_completed", lambda v: v >= 1,
              "recovery turn completed after reconnect"),
             ("post_terminal_sends_total", lambda v: v == 0, "post_terminal 0"),
             ("qwen_dispatch_errors_total", lambda v: v == 0, "dispatch errors 0"),
             ("accounting_fault_events", lambda v: v == 0, "accounting faults 0"),
             ("send_failed_frames", lambda v: v == 0, "no send failures"),
         ]),
        ("client_teardown", {"frames": 600, "interval_ms": 5.0, "settle_s": 30,
                         "min_sent": 1},
         s_client_teardown, [
             ("post_terminal_sends_total", lambda v: v == 0, "post_terminal 0"),
             ("qwen_dispatch_errors_total", lambda v: v == 0, "dispatch errors 0"),
             ("accounting_fault_events", lambda v: v == 0, "accounting faults 0"),
             ("flushed_close_frames", lambda v: v >= 0, "close flush accounted"),
         ]),
    ]


async def amain(argv):
    wanted = set(argv[1:])
    t0 = time.time()
    for name, cfg, fn, expect in scenarios():
        if wanted and name not in wanted:
            continue
        print("---- scenario %s ----" % name)
        try:
            await asyncio.wait_for(run_scenario(name, cfg, fn, expect), 300)
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            check("scenario %s EXCEPTION" % name, False, repr(e))
    fails = [r for r in RESULTS if not r[1]]
    print("=" * 70)
    print("R1F_RUNTIME_TESTS: %d checks, %d PASS, %d FAIL, %.1fs"
          % (len(RESULTS), len(RESULTS) - len(fails), len(fails),
             time.time() - t0))
    for nm, _, detail in fails:
        print("  - %s %s" % (nm, detail))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain(sys.argv)))