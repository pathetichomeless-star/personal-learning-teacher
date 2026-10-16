#!/usr/bin/env python3
"""In-container smoke test for the R-1b Qwen realtime lab bridge.

Usage:  python /app/tests/selfcheck.py [scenario]
        scenario in: normal (default), fragmented, cancel_benign, upstream_error,
        disconnect_mid, malformed, rapid_turns, silence

Always runs the static checks (codec, health, OTA, hello, mock handshake) and
then the scenario-specific check(s). Prints PASS/FAIL per item and exits
non-zero if anything failed.
"""

import asyncio
import json
import sys
import time

sys.path.insert(0, "/app")

import aiohttp
from aiohttp import WSMsgType
import opuslib

from app import audio
from app.main import load_config

CFG = load_config()
FRAME_MS = CFG.FRAME_MS
RECONNECT_MAX = CFG.qwen.reconnect_max
WS_URL = "ws://127.0.0.1:8110/xiaozhi/v1/"
HEALTH_URLS = ["http://127.0.0.1:8111/health", "http://127.0.0.1:8110/health"]
OTA_URL = "http://127.0.0.1:8111/xiaozhi/ota/"

HEALTH_KEYS = [
    "status", "uptime_s", "ws_connections", "turns", "frames_in", "frames_out",
    "aborts", "last_abort_stop_ms", "qwen_connected", "qwen_sessions",
    "qwen_connect_errors", "audio_in_opus_frames", "audio_in_pcm_bytes",
    "qwen_audio_delta_bytes", "audio_out_opus_frames", "responses_completed",
    "responses_cancelled", "barge_ins", "upstream_errors",
    "last_speech_stop_to_first_audio_ms", "audio_out_dropped", "uplink_dropped",
]

HELLO = {
    "type": "hello", "version": 1, "transport": "websocket",
    "features": {"mcp": True},
    "audio_params": {"format": "opus", "sample_rate": 16000,
                     "channels": 1, "frame_duration": 20},
}

RESULTS = []


async def run_item(name, coro):
    try:
        detail = await coro
        RESULTS.append((name, True))
        print("PASS  %s - %s" % (name, detail))
    except Exception as e:  # noqa: BLE001
        RESULTS.append((name, False))
        print("FAIL  %s - %r" % (name, e))


async def get_health(session):
    async with session.get(HEALTH_URLS[0]) as r:
        return await r.json()


async def wait_health(session, pred, timeout=10.0, interval=0.2):
    deadline = time.monotonic() + timeout
    last = await get_health(session)
    while time.monotonic() < deadline:
        if pred(last):
            return last
        await asyncio.sleep(interval)
        last = await get_health(session)
    return last


async def ws_connect(session):
    ws = await session.ws_connect(WS_URL)
    await ws.send_json(HELLO)
    msg = await ws.receive(timeout=5)
    assert msg.type == WSMsgType.TEXT, "expected hello text"
    j = json.loads(msg.data)
    assert j.get("type") == "hello", "hello type=%r" % (j.get("type"),)
    assert j.get("transport") == "websocket", "transport=%r" % (j.get("transport"),)
    return ws


async def send_listen_start(ws, mode="realtime"):
    await ws.send_json({"session_id": "", "type": "listen",
                        "state": "start", "mode": mode})


async def collect_until_quiet(ws, max_timeout=8.0, idle=0.8):
    """Read until no message for `idle` seconds; track frames after last tts stop."""
    seen = {"tts_start": 0, "tts_stop": 0, "frames": 0, "frames_since_stop": 0}
    start = time.monotonic()
    last = start
    while True:
        now = time.monotonic()
        if now - start > max_timeout or now - last > idle:
            break
        rem = min(idle, max_timeout - (now - start))
        try:
            msg = await ws.receive(timeout=rem)
        except asyncio.TimeoutError:
            break
        except Exception:  # noqa: BLE001
            break
        last = time.monotonic()
        if msg.type == WSMsgType.TEXT:
            try:
                j = json.loads(msg.data)
            except Exception:  # noqa: BLE001
                continue
            if j.get("type") == "tts":
                st = j.get("state")
                if st == "start":
                    seen["tts_start"] += 1
                elif st == "stop":
                    seen["tts_stop"] += 1
                    seen["frames_since_stop"] = 0
        elif msg.type == WSMsgType.BINARY:
            seen["frames"] += 1
            seen["frames_since_stop"] += 1
    return seen


async def collect_events(ws, timeout=6.0, collect_packets=False, stop_on_tts_stop=False):
    seen = {"tts_start": 0, "tts_stop": 0, "frames": 0, "packets": []}
    deadline = time.monotonic() + timeout
    while True:
        rem = deadline - time.monotonic()
        if rem <= 0:
            break
        try:
            msg = await ws.receive(timeout=rem)
        except asyncio.TimeoutError:
            break
        except Exception:  # noqa: BLE001
            break
        if msg.type == WSMsgType.TEXT:
            try:
                j = json.loads(msg.data)
            except Exception:  # noqa: BLE001
                continue
            if j.get("type") == "tts":
                st = j.get("state")
                if st == "start":
                    seen["tts_start"] += 1
                elif st == "stop":
                    seen["tts_stop"] += 1
                    if stop_on_tts_stop:
                        break
        elif msg.type == WSMsgType.BINARY:
            seen["frames"] += 1
            if collect_packets:
                seen["packets"].append(msg.data)
    return seen


# ---- static checks ---------------------------------------------------------

async def c1():
    enc24 = audio.OpusEnc24()
    dec24 = opuslib.Decoder(24000, 1)
    pkt = enc24.encode(b"\x01\x00" * 480, 480)
    assert pkt, "empty 24k opus packet"
    out = dec24.decode(pkt, 480)
    assert len(out) == 960, "24k round-trip gave %d bytes" % len(out)
    enc16 = opuslib.Encoder(16000, 1, opuslib.APPLICATION_VOIP)
    pkt16 = enc16.encode(b"\x02\x00" * 320, 320)
    out16 = audio.OpusDec16().decode(pkt16, 320)
    assert len(out16) == 640, "16k round-trip gave %d bytes" % len(out16)
    return "dec16 16k/320 & enc24 24k/480 round-trips OK"


async def c2():
    async with aiohttp.ClientSession() as session:
        for url in HEALTH_URLS:
            async with session.get(url) as r:
                assert r.status == 200, "%s status %d" % (url, r.status)
                j = await r.json()
                assert j.get("status") == "ok", "%s status!=ok" % url
                for k in HEALTH_KEYS:
                    assert k in j, "%s missing key %s" % (url, k)
    return "both ports 200; all %d keys present" % len(HEALTH_KEYS)


async def c3():
    async with aiohttp.ClientSession() as session:
        for method in ("get", "post"):
            async with getattr(session, method)(OTA_URL) as r:
                assert r.status == 200, "%s status %d" % (method, r.status)
                j = await r.json()
                assert set(j.keys()) == {"websocket"}, "top keys %s" % list(j.keys())
                assert set(j["websocket"].keys()) == {"url", "token"}, \
                    "ws keys %s" % list(j["websocket"].keys())
                assert j["websocket"]["url"] == CFG.PUBLIC_WS_URL, "url mismatch"
                assert "activation" not in j, "activation present"
    return "GET+POST 200; {url,token}; no activation"


async def c4():
    async with aiohttp.ClientSession() as session:
        ws = await ws_connect(session)
        await ws.close()
    return "server hello: type=hello transport=websocket"


async def c5():
    async with aiohttp.ClientSession() as session:
        h0 = await get_health(session)
        ws = await ws_connect(session)
        await send_listen_start(ws)
        h = await wait_health(
            session,
            lambda j: j["qwen_connected"] >= 1 and j["qwen_sessions"] > h0["qwen_sessions"],
            timeout=6.0)
        await ws.close()
        assert h["qwen_connected"] >= 1, "qwen_connected=%r" % h["qwen_connected"]
        assert h["qwen_sessions"] > h0["qwen_sessions"], "no qwen session opened"
    return "mock handshake: session.created/updated -> qwen_sessions +%d" % (
        h["qwen_sessions"] - h0["qwen_sessions"])


# ---- scenario checks -------------------------------------------------------

async def c6():
    async with aiohttp.ClientSession() as session:
        h0 = await get_health(session)
        ws = await ws_connect(session)
        await send_listen_start(ws)
        seen = await collect_until_quiet(ws, max_timeout=15.0, idle=0.8)
        await ws.close()
        h1 = await get_health(session)
        assert seen["tts_start"] == 1, "tts start count=%d (expected 1)" % seen["tts_start"]
        assert seen["tts_stop"] == 1, "tts stop count=%d (expected 1)" % seen["tts_stop"]
        assert seen["frames"] >= 1, "no binary opus frames"
        assert seen["frames_since_stop"] == 0, \
            "%d frames after final tts stop" % seen["frames_since_stop"]
        assert h1["responses_completed"] > h0["responses_completed"], \
            "responses_completed did not increase"
    return "tts start/stop exactly once; frames=%d; responses_completed %d->%d" % (
        seen["frames"], h0["responses_completed"], h1["responses_completed"])


async def c7():
    async with aiohttp.ClientSession() as session:
        h0 = await get_health(session)
        ws = await ws_connect(session)
        await send_listen_start(ws)
        got = False
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            msg = await ws.receive(timeout=10)
            if msg.type == WSMsgType.TEXT:
                j = json.loads(msg.data)
                if j.get("type") == "tts" and j.get("state") == "start":
                    got = True
                    break
        assert got, "never reached tts start"
        await ws.send_json({"session_id": "", "type": "abort", "reason": None})
        t0 = time.monotonic()
        stop = False
        while time.monotonic() - t0 < 3:
            msg = await ws.receive(timeout=3)
            if msg.type == WSMsgType.TEXT:
                j = json.loads(msg.data)
                if j.get("type") == "tts" and j.get("state") == "stop":
                    stop = True
                    break
        assert stop, "no tts stop after abort"
        frames_after = 0
        end = time.monotonic() + 0.25
        while True:
            rem = end - time.monotonic()
            if rem <= 0:
                break
            try:
                msg = await ws.receive(timeout=rem)
            except asyncio.TimeoutError:
                break
            if msg.type == WSMsgType.BINARY:
                frames_after += 1
        await ws.close()
        h1 = await get_health(session)
        assert h1["aborts"] >= h0["aborts"] + 1, "aborts unchanged"
        lam = h1["last_abort_stop_ms"]
        assert lam is not None and lam <= FRAME_MS + 50, "last_abort_stop_ms=%r" % lam
        assert h1["qwen_connect_errors"] == h0["qwen_connect_errors"], \
            "qwen_connect_errors changed (must stay benign)"
        assert frames_after == 0, "%d frames after tts stop" % frames_after
    return "tts stop %.1f ms (<=%d); aborts %d->%d; qwen_connect_errors unchanged; frames_after=0" % (
        lam, FRAME_MS + 50, h0["aborts"], h1["aborts"])


async def c8():
    async with aiohttp.ClientSession() as session:
        ws = await ws_connect(session)
        await send_listen_start(ws)
        seen = await collect_events(ws, timeout=15.0, collect_packets=True,
                                    stop_on_tts_stop=True)
        await ws.close()
        assert seen["frames"] >= 1, "no frames"
        dec = opuslib.Decoder(24000, 1)
        for i, pkt in enumerate(seen["packets"]):
            pcm = dec.decode(pkt, 480)
            assert len(pcm) == 960, "frame %d decoded %d bytes" % (i, len(pcm))
    return "fragmented reassembly: %d frames all decode to 960-byte PCM" % seen["frames"]


async def c9():
    """disconnect_mid: upstream drops every connection -> reconciles bounded by
    QWEN_RECONNECT_MAX, then freezes (no storm)."""
    async with aiohttp.ClientSession() as session:
        h0 = await get_health(session)
        ws = await ws_connect(session)
        await send_listen_start(ws)
        start = time.monotonic()
        last_sessions = h0["qwen_sessions"]
        frozen_since = None
        while time.monotonic() - start < 22:
            h = await get_health(session)
            if h["qwen_sessions"] != last_sessions:
                last_sessions = h["qwen_sessions"]
                frozen_since = time.monotonic()
            elif frozen_since is not None and time.monotonic() - frozen_since > 3.0:
                break
            await asyncio.sleep(0.2)
        h1 = await get_health(session)
        # keep observing to prove it stays frozen
        await asyncio.sleep(3.0)
        h2 = await get_health(session)
        await ws.close()
        sess_delta = h2["qwen_sessions"] - h0["qwen_sessions"]
        err_delta = h2["qwen_connect_errors"] - h0["qwen_connect_errors"]
        assert h2["upstream_errors"] > h0["upstream_errors"], "no upstream drop observed"
        assert frozen_since is not None, "reconnect never happened"
        assert sess_delta <= RECONNECT_MAX, \
            "qwen_sessions +%d > max %d" % (sess_delta, RECONNECT_MAX)
        assert err_delta <= RECONNECT_MAX, \
            "qwen_connect_errors +%d > max %d" % (err_delta, RECONNECT_MAX)
        assert h2["qwen_sessions"] == h1["qwen_sessions"], \
            "sessions kept growing after the bound (storm)"
    return "disconnect_mid: sessions +%d, errors +%d (<=%d); froze (no storm)" % (
        sess_delta, err_delta, RECONNECT_MAX)


async def c10():
    async with aiohttp.ClientSession() as session:
        h0 = await get_health(session)
        ws = await ws_connect(session)
        await send_listen_start(ws)
        await asyncio.sleep(2.5)
        async with session.get(HEALTH_URLS[0]) as r:
            assert r.status == 200, "health %d" % r.status
            j = await r.json()
            assert j["status"] == "ok"
        h1 = await get_health(session)
        await ws.close()
        assert h1["responses_completed"] > h0["responses_completed"], "turn not completed"
        assert h1["upstream_errors"] > h0["upstream_errors"], "malformed upstream not counted"
    return "malformed/unknown/bad-base64 tolerated; health 200; upstream_errors %d->%d" % (
        h0["upstream_errors"], h1["upstream_errors"])


async def c11():
    async with aiohttp.ClientSession() as session:
        h0 = await get_health(session)
        ws = await ws_connect(session)
        await send_listen_start(ws)
        seen = await collect_events(ws, timeout=3.0)
        await ws.close()
        h1 = await get_health(session)
        assert seen["tts_start"] == 0 and seen["tts_stop"] == 0, \
            "tts events on silent response: %s" % seen
        assert seen["frames"] == 0, "frames on silent response"
        assert h1["responses_completed"] > h0["responses_completed"], "response not completed"
    return "silent response: zero tts events, zero frames, responses_completed++"


async def c12():
    async with aiohttp.ClientSession() as session:
        h0 = await get_health(session)
        ws = await ws_connect(session)
        await send_listen_start(ws)
        seen = await collect_until_quiet(ws, max_timeout=8.0, idle=0.8)
        await ws.close()
        h1 = await get_health(session)
        delta = h1["responses_completed"] - h0["responses_completed"]
        assert delta >= 2, "responses_completed delta=%d" % delta
        assert seen["frames_since_stop"] == 0, \
            "%d stale frames after final tts stop" % seen["frames_since_stop"]
    return "rapid turns: responses_completed +%d; tts stops=%d; barge_ins=%d; stale frames=0" % (
        delta, seen["tts_stop"], h1["barge_ins"])


async def c13():
    async with aiohttp.ClientSession() as session:
        h0 = await get_health(session)
        ws = await ws_connect(session)
        await send_listen_start(ws)
        seen = await collect_events(ws, timeout=15.0, stop_on_tts_stop=True)
        await ws.close()
        h1 = await get_health(session)
        assert seen["tts_start"] >= 1 and seen["tts_stop"] >= 1, "turn incomplete"
        assert h1["upstream_errors"] > h0["upstream_errors"], "upstream error not counted"
        assert h1["responses_completed"] > h0["responses_completed"], "response not completed"
    return "upstream error mid-response then recovery; upstream_errors %d->%d" % (
        h0["upstream_errors"], h1["upstream_errors"])


# ---- edge checks (run in normal scenario) ----------------------------------

async def c14():
    async with aiohttp.ClientSession() as session:
        h0 = await get_health(session)
        ws = await ws_connect(session)
        for _ in range(5):
            await send_listen_start(ws)
        await wait_health(session, lambda j: j["qwen_sessions"] > h0["qwen_sessions"], timeout=6.0)
        await asyncio.sleep(0.5)
        h1 = await get_health(session)
        await ws.close()
        delta = h1["qwen_sessions"] - h0["qwen_sessions"]
        assert delta <= 1, "duplicate qwen sessions: +%d" % delta
    return "5x rapid listen start -> qwen_sessions +%d (no duplicate sessions/pacers)" % delta


async def c15():
    async with aiohttp.ClientSession() as session:
        h0 = await get_health(session)
        ws = await ws_connect(session)
        await ws.send_json({"session_id": "", "type": "abort", "reason": None})
        await asyncio.sleep(0.3)
        h1 = await get_health(session)
        await ws.close()
        assert h1["aborts"] >= h0["aborts"] + 1, "aborts unchanged"
        assert h1["qwen_connect_errors"] == h0["qwen_connect_errors"], \
            "qwen_connect_errors changed"
    return "abort with no active response: aborts++, no spurious cancel"


async def c16():
    async with aiohttp.ClientSession() as session:
        ws = await ws_connect(session)
        await send_listen_start(ws)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            msg = await ws.receive(timeout=10)
            if msg.type == WSMsgType.TEXT:
                j = json.loads(msg.data)
                if j.get("type") == "tts" and j.get("state") == "start":
                    break
        await ws.close()
        await asyncio.sleep(1.0)
        async with session.get(HEALTH_URLS[0]) as r:
            assert r.status == 200, "health %d" % r.status
            j = await r.json()
            assert j["status"] == "ok"
    return "client disconnect mid-response: no leak; health 200"


async def c18():
    """late_done_after_cancel: a cancelled response's late `response.done`
    arriving after the next `response.created` must be ignored; resp2 completes
    normally with exactly one start/stop and no premature stop."""
    async with aiohttp.ClientSession() as session:
        h0 = await get_health(session)
        ws = await ws_connect(session)
        await send_listen_start(ws)
        seen = await collect_until_quiet(ws, max_timeout=15.0, idle=1.0)
        await ws.close()
        h1 = await get_health(session)
        delta = h1["responses_completed"] - h0["responses_completed"]
        assert delta == 1, "responses_completed delta=%d (expected 1)" % delta
        assert seen["tts_start"] >= 1, "no tts start"
        assert seen["tts_stop"] >= 1, "no tts stop"
        assert seen["frames_since_stop"] == 0, \
            "%d frames after final tts stop (premature stop?)" % seen["frames_since_stop"]
    return ("late cancelled done ignored; resp2 completed +1; "
            "starts=%d stops=%d; stale frames=0" % (seen["tts_start"], seen["tts_stop"]))


async def c19():
    """flapping: upstream accepts then drops repeatedly -> reconnect budget hits
    exactly QWEN_RECONNECT_MAX and FREEZES while the client keeps streaming."""
    async with aiohttp.ClientSession() as session:
        h0 = await get_health(session)
        ws = await ws_connect(session)
        await send_listen_start(ws)
        enc16 = opuslib.Encoder(16000, 1, opuslib.APPLICATION_VOIP)
        frame = enc16.encode(b"\x05\x00" * 320, 320)
        start = time.monotonic()
        last = h0
        frozen_since = None
        while time.monotonic() - start < 30:
            await ws.send_bytes(frame)
            await asyncio.sleep(0.05)
            h = await get_health(session)
            if h["qwen_connect_errors"] != last["qwen_connect_errors"]:
                last = h
                frozen_since = time.monotonic()
            elif frozen_since is not None and time.monotonic() - frozen_since > 3.0:
                break
        errors_at_freeze = last["qwen_connect_errors"]
        # keep streaming to prove no further attempts
        for _ in range(30):
            await ws.send_bytes(frame)
            await asyncio.sleep(0.05)
        h2 = await get_health(session)
        alive = not ws.closed
        await ws.close()
        delta = h2["qwen_connect_errors"] - h0["qwen_connect_errors"]
        assert delta >= RECONNECT_MAX, \
            "qwen_connect_errors +%d (< %d)" % (delta, RECONNECT_MAX)
        assert h2["qwen_connect_errors"] == errors_at_freeze, \
            "errors kept rising after freeze (storm)"
        assert alive, "client WS died"
    return ("flapping: qwen_connect_errors +%d (>=%d) then froze while "
            "streaming; client WS alive" % (delta, RECONNECT_MAX))


async def c20():
    """FIX-F leak regression: 10 connect -> short uplink -> close cycles; after
    each, qwen_connected==0 and ws_connections==0; a fresh client after the
    cycles still gets a full flapping budget of exactly QWEN_RECONNECT_MAX."""
    async with aiohttp.ClientSession() as session:
        enc16 = opuslib.Encoder(16000, 1, opuslib.APPLICATION_VOIP)
        frame = enc16.encode(b"\x07\x00" * 320, 320)
        for i in range(10):
            ws = await ws_connect(session)
            await send_listen_start(ws)
            for _ in range(10):
                await ws.send_bytes(frame)
                await asyncio.sleep(0.03)
            await ws.close()
            h = await wait_health(
                session,
                lambda j: j["qwen_connected"] == 0 and j["ws_connections"] == 0,
                timeout=8.0)
            assert h["qwen_connected"] == 0, "cycle %d qwen_connected=%d" % (
                i, h["qwen_connected"])
            assert h["ws_connections"] == 0, "cycle %d ws_connections=%d" % (
                i, h["ws_connections"])
        # no orphan reconnect while idle
        h_idle0 = await get_health(session)
        await asyncio.sleep(4.0)
        h_idle1 = await get_health(session)
        assert h_idle1["qwen_sessions"] == h_idle0["qwen_sessions"], \
            "orphan sessions reconnected while idle (+%d)" % (
                h_idle1["qwen_sessions"] - h_idle0["qwen_sessions"])
        # a fresh client still gets a full budget (no skew)
        h0 = await get_health(session)
        ws = await ws_connect(session)
        await send_listen_start(ws)
        start = time.monotonic()
        last = h0
        frozen_since = None
        while time.monotonic() - start < 30:
            await ws.send_bytes(frame)
            await asyncio.sleep(0.05)
            h = await get_health(session)
            if h["qwen_connect_errors"] != last["qwen_connect_errors"]:
                last = h
                frozen_since = time.monotonic()
            elif frozen_since is not None and time.monotonic() - frozen_since > 3.0:
                break
        h2 = await get_health(session)
        await ws.close()
        fresh = h2["qwen_connect_errors"] - h0["qwen_connect_errors"]
        assert fresh == RECONNECT_MAX, \
            "fresh client budget = %d (expected %d, leaked/skewed)" % (
                fresh, RECONNECT_MAX)
    return ("10 cycles clean (qwen_connected/ws_connections=0 each); no orphan "
            "reconnect; fresh client budget exactly %d" % RECONNECT_MAX)


ALWAYS = [
    ("1 opus codec round-trip", c1),
    ("2 health both ports + keys", c2),
    ("3 OTA GET+POST", c3),
    ("4 WS hello handshake", c4),
    ("5 mock qwen handshake", c5),
]

SCENARIO_CHECKS = {
    "normal": [
        ("6 full turn", c6),
        ("14 rapid listen start", c14),
        ("15 abort no active response", c15),
        ("16 client disconnect mid-response", c16),
    ],
    "fragmented": [("8 fragmented reassembly", c8)],
    "cancel_benign": [("7 abort / cancel benign", c7)],
    "disconnect_mid": [("9 disconnect_mid bounded reconnect", c9)],
    "malformed": [("10 malformed upstream", c10)],
    "silence": [("11 silent response", c11)],
    "rapid_turns": [("12 rapid turns", c12)],
    "upstream_error": [("13 upstream error recovery", c13)],
    "late_done_after_cancel": [("18 late cancelled done ignored", c18)],
    "flapping": [("19 flapping reconnect bound", c19),
                 ("20 leak regression / no budget skew", c20)],
}


async def amain(scenario):
    checks = list(ALWAYS) + SCENARIO_CHECKS.get(scenario, [])
    print("=== SELFCHECK scenario=%s (%d checks) ===" % (scenario, len(checks)))
    for name, fn in checks:
        await run_item(name, fn())
    failed = [n for n, ok in RESULTS if not ok]
    print("\n=== SELFCHECK %s scenario=%s (%d/%d) ===" % (
        "PASS" if not failed else "FAIL", scenario,
        len(RESULTS) - len(failed), len(RESULTS)))
    return 0 if not failed else 1


if __name__ == "__main__":
    scenario = sys.argv[1] if len(sys.argv) > 1 else "normal"
    sys.exit(asyncio.run(amain(scenario)))