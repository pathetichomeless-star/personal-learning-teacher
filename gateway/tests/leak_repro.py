#!/usr/bin/env python3
"""FIX-A leak reproduction / regression harness (runs inside the container).

Usage:  python /app/tests/leak_repro.py [--mode normal|flapping]

  normal   -> (a) one connect/stream/close cycle leaves qwen_connected==0
              (b) 10 cycles: qwen_connected==0, ws_connections==0, fd count stable
              (c) no orphan reconnect while idle (qwen_sessions frozen)
  flapping -> (d) a fresh client still gets a full budget of exactly 5
              (requires the mock started with --scenario flapping)

Exits non-zero if any assertion fails.
"""

import argparse
import asyncio
import json
import sys
import time

import aiohttp
import opuslib

WS_URL = "ws://127.0.0.1:8110/xiaozhi/v1/"
HEALTH = "http://127.0.0.1:8111/health"
HELLO = {
    "type": "hello", "version": 1, "transport": "websocket",
    "audio_params": {"format": "opus", "sample_rate": 16000,
                     "channels": 1, "frame_duration": 20},
}
RECONNECT_MAX = 5


async def health(session):
    async with session.get(HEALTH) as r:
        return await r.json()


def fd_count():
    """Count ESTABLISHED TCP sockets (state 01) in this netns.

    Deliberately excludes TIME_WAIT (state 06) / CLOSE_WAIT churn so the metric
    measures real live sockets, not normal teardown transients.
    """
    try:
        n = 0
        with open("/proc/net/tcp") as f:
            next(f, None)
            for line in f:
                parts = line.split()
                if len(parts) > 3 and parts[3] == "01":
                    n += 1
        return n
    except Exception:  # noqa: BLE001
        return -1


async def one_cycle(session, enc, frame, uplink_frames=10):
    ws = await session.ws_connect(WS_URL)
    await ws.send_json(HELLO)
    await ws.receive(timeout=5)
    await ws.send_json({"session_id": "", "type": "listen",
                        "state": "start", "mode": "realtime"})
    for _ in range(uplink_frames):
        await ws.send_bytes(frame)
        await asyncio.sleep(0.03)
    await ws.close()


async def wait_zero(session, timeout=8.0):
    deadline = time.monotonic() + timeout
    h = await health(session)
    while time.monotonic() < deadline:
        if h["qwen_connected"] == 0 and h["ws_connections"] == 0:
            return h
        await asyncio.sleep(0.2)
        h = await health(session)
    return h


async def run_normal(session, enc, frame):
    ok = True
    # (a)
    await one_cycle(session, enc, frame)
    h = await wait_zero(session)
    print("(a) single cycle: qwen_connected=%d ws_connections=%d" % (
        h["qwen_connected"], h["ws_connections"]))
    ok &= h["qwen_connected"] == 0 and h["ws_connections"] == 0
    # (b)
    fds = []
    for i in range(10):
        await one_cycle(session, enc, frame)
        h = await wait_zero(session)
        fds.append(fd_count())
        print("(b) cycle %2d: qwen_connected=%d ws_connections=%d fds=%d" % (
            i + 1, h["qwen_connected"], h["ws_connections"], fds[-1]))
        ok &= h["qwen_connected"] == 0 and h["ws_connections"] == 0
    fd_delta = fds[-1] - fds[0] if len(fds) >= 2 else 0
    print("(b) fds first=%d last=%d delta=%d" % (fds[0], fds[-1], fd_delta))
    ok &= abs(fd_delta) <= 2
    # (c)
    h0 = await health(session)
    await asyncio.sleep(5.0)
    h1 = await health(session)
    print("(c) idle qwen_sessions %d -> %d (orphan reconnect if it rose)" % (
        h0["qwen_sessions"], h1["qwen_sessions"]))
    ok &= h1["qwen_sessions"] == h0["qwen_sessions"]
    print("NORMAL %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


async def run_flapping(session, enc, frame):
    h0 = await health(session)
    ws = await session.ws_connect(WS_URL)
    await ws.send_json(HELLO)
    await ws.receive(timeout=5)
    await ws.send_json({"session_id": "", "type": "listen",
                        "state": "start", "mode": "realtime"})
    start = time.monotonic()
    last = h0
    frozen_since = None
    while time.monotonic() - start < 30:
        await ws.send_bytes(frame)
        await asyncio.sleep(0.05)
        h = await health(session)
        if h["qwen_connect_errors"] != last["qwen_connect_errors"]:
            last = h
            frozen_since = time.monotonic()
        elif frozen_since is not None and time.monotonic() - frozen_since > 3.0:
            break
    for _ in range(30):
        await ws.send_bytes(frame)
        await asyncio.sleep(0.05)
    h2 = await health(session)
    await ws.close()
    delta = h2["qwen_connect_errors"] - h0["qwen_connect_errors"]
    frozen = h2["qwen_connect_errors"] == last["qwen_connect_errors"]
    print("(d) fresh client: qwen_connect_errors +%d, frozen=%s" % (delta, frozen))
    ok = (delta == RECONNECT_MAX) and frozen
    print("FLAPPING %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


async def main(mode):
    enc = opuslib.Encoder(16000, 1, opuslib.APPLICATION_VOIP)
    frame = enc.encode(b"\x09\x00" * 320, 320)
    async with aiohttp.ClientSession() as session:
        if mode == "flapping":
            return await run_flapping(session, enc, frame)
        return await run_normal(session, enc, frame)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="normal", choices=("normal", "flapping"))
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.mode)))