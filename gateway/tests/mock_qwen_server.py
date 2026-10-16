#!/usr/bin/env python3
"""Deterministic fake Qwen Realtime WebSocket upstream for the lab bridge.

Binds 127.0.0.1 only. Usage:
    python /app/tests/mock_qwen_server.py --port 9977 --scenario normal

Scenarios: normal, fragmented, cancel_benign, upstream_error, disconnect_mid,
malformed, rapid_turns, silence, late_done_after_cancel, flapping.
"""

import argparse
import asyncio
import base64
import json
import logging

from aiohttp import web, WSMsgType

log = logging.getLogger("mock.qwen")

SCENARIOS = ("normal", "fragmented", "cancel_benign", "upstream_error",
             "disconnect_mid", "malformed", "rapid_turns", "silence",
             "late_done_after_cancel", "flapping")

BENIGN_CANCEL_ERROR = {
    "type": "error",
    "error": {
        "type": "invalid_request_error",
        "code": "response_cancel_not_active",
        "message": "no active response to cancel",
        "param": None,
    },
}


def _pcm(total_bytes):
    """Deterministic, non-trivial s16le PCM payload."""
    return bytes((i * 7 + 11) & 0xFF for i in range(total_bytes))


def _b64(data):
    return base64.b64encode(data).decode("ascii")


async def _send(ws, obj):
    await ws.send_str(json.dumps(obj))


def _split_normal(total):
    return [total[i:i + 960] for i in range(0, len(total), 960)]


def _split_fragmented(total):
    """Deliberately odd-length splits, never aligned to 960 bytes."""
    out, i, step = [], 0, 1
    while i < len(total):
        out.append(total[i:i + step])
        i += step
        step = (step % 13) + 1
    return out


class MockServer:
    def __init__(self, scenario):
        self.scenario = scenario
        self.conn_count = 0
        self.disconnect_done = False
        self._resp_seq = 0
        self._active_resp_id = None

    def _next_resp(self):
        self._resp_seq += 1
        return "resp_%d" % self._resp_seq

    async def handler(self, request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        self.conn_count += 1
        my_conn = self.conn_count
        cancel_seen = asyncio.Event()
        log.info("mock conn#%d scenario=%s", my_conn, self.scenario)
        tasks = []
        try:
            await _send(ws, {"type": "session.created",
                             "session": {"id": "mock_sess_%d" % my_conn}})
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    obj = json.loads(msg.data)
                except Exception:  # noqa: BLE001
                    continue
                etype = obj.get("type")
                if etype == "session.update":
                    await _send(ws, {"type": "session.updated",
                                     "session": {"id": "mock_sess_%d" % my_conn}})
                    tasks.append(asyncio.create_task(
                        self._run_scenario(ws, my_conn, cancel_seen)))
                elif etype == "response.cancel":
                    await _send(ws, BENIGN_CANCEL_ERROR)
                    if self.scenario == "late_done_after_cancel":
                        # suppress the cancelled done here; sent late by the scenario
                        cancel_seen.set()
                    elif self._active_resp_id is not None:
                        await _send(ws, {"type": "response.done", "response": {
                            "id": self._active_resp_id, "status": "cancelled"}})
                        self._active_resp_id = None
                elif etype == "session.finish":
                    break
                # input_audio_buffer.append and anything else: ignored
        except Exception as e:  # noqa: BLE001
            log.warning("mock handler error: %s", e)
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
        return ws

    async def _run_scenario(self, ws, my_conn, cancel_seen):
        try:
            await asyncio.sleep(0.2)
            sc = self.scenario
            if sc == "silence":
                await self._silent(ws)
            elif sc == "rapid_turns":
                await self._turn(ws, gap=0.0, chunks_n=25)
                await asyncio.sleep(0.05)
                await self._turn(ws, gap=0.0, chunks_n=25)
            elif sc == "cancel_benign":
                await self._turn(ws, gap=0.03, chunks_n=120)
            elif sc == "upstream_error":
                await self._turn(ws, gap=0.02, chunks_n=40, inject_error=True)
            elif sc == "disconnect_mid":
                # Drop the upstream mid-response on every connection so the
                # bridge must clean up + reconnect (bounded) to recover.
                self.disconnect_done = True
                await self._turn(ws, gap=0.02, chunks_n=40, hard_close=True)
            elif sc == "malformed":
                await self._malformed(ws)
            elif sc == "fragmented":
                await self._turn(ws, gap=0.0, chunks_n=40, fragmented=True)
            elif sc == "late_done_after_cancel":
                await self._late_done_after_cancel(ws, cancel_seen)
            elif sc == "flapping":
                await asyncio.sleep(1.5)
                log.info("mock: dropping connection (flapping)")
                await ws.close()
            else:  # normal
                await self._turn(ws, gap=0.03, chunks_n=50)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("mock scenario error: %s", e)

    async def _turn(self, ws, gap=0.0, chunks_n=50, fragmented=False,
                    inject_error=False, hard_close=False):
        rid = self._next_resp()
        self._active_resp_id = rid
        await _send(ws, {"type": "input_audio_buffer.speech_started",
                         "audio_start_ms": 0, "item_id": "item_1"})
        await asyncio.sleep(0.03)
        await _send(ws, {"type": "input_audio_buffer.speech_stopped",
                         "audio_end_ms": 200, "item_id": "item_1"})
        await asyncio.sleep(0.02)
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid, "status": "in_progress"}})
        total = _pcm(chunks_n * 960)
        chunks = _split_fragmented(total) if fragmented else _split_normal(total)
        for idx, chunk in enumerate(chunks):
            await _send(ws, {"type": "response.audio.delta",
                             "response_id": rid, "item_id": "item_1",
                             "delta": _b64(chunk)})
            if inject_error and idx == len(chunks) // 2:
                await _send(ws, {"type": "error", "error": {
                    "type": "server_error", "code": "mock_mid_error",
                    "message": "injected mid-response error", "param": None}})
            if hard_close and idx == len(chunks) // 2:
                log.info("mock: closing mid-response (disconnect_mid)")
                await ws.close()
                return
            if gap:
                await asyncio.sleep(gap)
        await _send(ws, {"type": "response.audio.done", "response_id": rid})
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid, "status": "completed"}})
        if self._active_resp_id == rid:
            self._active_resp_id = None

    async def _silent(self, ws):
        rid = self._next_resp()
        self._active_resp_id = rid
        await _send(ws, {"type": "input_audio_buffer.speech_started",
                         "audio_start_ms": 0, "item_id": "item_1"})
        await asyncio.sleep(0.03)
        await _send(ws, {"type": "input_audio_buffer.speech_stopped",
                         "audio_end_ms": 200, "item_id": "item_1"})
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid, "status": "in_progress"}})
        await asyncio.sleep(0.05)
        await _send(ws, {"type": "response.audio.done", "response_id": rid})
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid, "status": "completed"}})
        self._active_resp_id = None

    async def _malformed(self, ws):
        rid = self._next_resp()
        self._active_resp_id = rid
        await _send(ws, {"type": "input_audio_buffer.speech_started",
                         "audio_start_ms": 0, "item_id": "item_1"})
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid, "status": "in_progress"}})
        await _send(ws, {"type": "some.unknown.event", "x": 1})
        await ws.send_str("this is not json {")
        await _send(ws, {"type": "response.audio.delta", "response_id": rid,
                         "delta": "!!!!not-valid-base64!!!!"})
        for chunk in _split_normal(_pcm(20 * 960)):
            await _send(ws, {"type": "response.audio.delta", "response_id": rid,
                             "item_id": "item_1", "delta": _b64(chunk)})
        await _send(ws, {"type": "response.audio.done", "response_id": rid})
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid, "status": "completed"}})
        self._active_resp_id = None

    async def _late_done_after_cancel(self, ws, cancel_seen):
        """resp1 plays; a barge-in cancels it; resp2 starts; THEN resp1's
        cancelled `response.done` arrives late (after resp2's created)."""
        rid1 = self._next_resp()
        self._active_resp_id = rid1
        await _send(ws, {"type": "input_audio_buffer.speech_started",
                         "audio_start_ms": 0, "item_id": "item_1"})
        await asyncio.sleep(0.03)
        await _send(ws, {"type": "input_audio_buffer.speech_stopped",
                         "audio_end_ms": 200, "item_id": "item_1"})
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid1, "status": "in_progress"}})
        for chunk in _split_normal(_pcm(60 * 960)):
            await _send(ws, {"type": "response.audio.delta", "response_id": rid1,
                             "item_id": "item_1", "delta": _b64(chunk)})
            await asyncio.sleep(0.02)
        # trigger the bridge's Path-B barge-in (speech while resp1 plays)
        await _send(ws, {"type": "input_audio_buffer.speech_started",
                         "audio_start_ms": 0, "item_id": "item_2"})
        try:
            await asyncio.wait_for(cancel_seen.wait(), 3.0)
        except asyncio.TimeoutError:
            log.warning("mock: no cancel seen for late_done_after_cancel")
        rid2 = self._next_resp()
        await _send(ws, {"type": "input_audio_buffer.speech_stopped",
                         "audio_end_ms": 200, "item_id": "item_2"})
        await _send(ws, {"type": "response.created",
                         "response": {"id": rid2, "status": "in_progress"}})
        self._active_resp_id = rid2
        # LATE: resp1's cancelled done AFTER resp2 created (must be ignored)
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid1, "status": "cancelled"}})
        for chunk in _split_normal(_pcm(40 * 960)):
            await _send(ws, {"type": "response.audio.delta", "response_id": rid2,
                             "item_id": "item_2", "delta": _b64(chunk)})
            await asyncio.sleep(0.02)
        await _send(ws, {"type": "response.audio.done", "response_id": rid2})
        await _send(ws, {"type": "response.done",
                         "response": {"id": rid2, "status": "completed"}})
        if self._active_resp_id == rid2:
            self._active_resp_id = None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9977)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--scenario", default="normal", choices=SCENARIOS)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    server = MockServer(args.scenario)
    app = web.Application()
    app.router.add_get("/", server.handler)
    app.router.add_get("/api-ws/v1/realtime", server.handler)
    log.info("mock qwen ws on ws://%s:%d (scenario=%s)",
             args.host, args.port, args.scenario)
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()