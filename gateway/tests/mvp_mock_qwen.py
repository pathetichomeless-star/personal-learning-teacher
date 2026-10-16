"""MVP integration mock Qwen upstream (drivable from the test).

Unlike `mock_qwen_server.py` (frozen R-1f scenarios), this mock is script-driven:
the test POSTs turns (transcript + response text) and the mock emits the full
QWEN event sequence (speech_started → input transcription → response with
transcript + audio deltas → done), records every `session.update` the bridge
sends (so instruction hot-applies can be asserted), and can inject raw events
(e.g. speech_started during playback for barge-in tests).

Endpoints:
  WS   /api-ws/v1/realtime        (Qwen protocol subset)
  POST /control/turn              {transcript, response_text, chunks, with_audio}
  POST /control/event             {event: "speech_started"|"response.done", ...}
  GET  /control/updates           recorded session.update payloads
  GET  /control/state             {connections, updates}
"""

import argparse
import asyncio
import base64
import json
import logging
from collections import deque

from aiohttp import web, WSMsgType

log = logging.getLogger("mock.mvp")

MAX_RECORDED_UPDATES = 200


def _pcm(n):
    return bytes((i * 5 + 3) & 0xFF for i in range(n))


class MvpMock:
    def __init__(self):
        self.connections = 0
        self.sockets = []           # (conn_id, ws) — active sockets
        self.updates = deque(maxlen=MAX_RECORDED_UPDATES)
        self.events_sent = 0
        self._lock = asyncio.Lock()

    def _last_ws(self):
        for cid, ws in reversed(self.sockets):
            if not ws.closed:
                return cid, ws
        return None, None

    async def handler(self, request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        async with self._lock:
            self.connections += 1
            cid = self.connections
            self.sockets.append((cid, ws))
        await ws.send_str(json.dumps(
            {"type": "session.created",
             "session": {"id": "mvp_mock_%d" % cid,
                         "voice": "Tina", "turn_detection":
                         {"type": "server_vad"}}}))
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    obj = json.loads(msg.data)
                except Exception:  # noqa: BLE001
                    continue
                etype = obj.get("type")
                if etype == "session.update":
                    sess = obj.get("session") or {}
                    self.updates.append({"conn": cid, "session": sess})
                    await ws.send_str(json.dumps(
                        {"type": "session.updated", "session": {
                            "voice": sess.get("voice", "Tina"),
                            "instructions": sess.get("instructions")}}))
                elif etype == "session.finish":
                    break
                # append / cancel / response.create etc.: no-op in this mock
        except Exception as e:  # noqa: BLE001
            log.warning("mvp mock handler: %s", e)
        finally:
            async with self._lock:
                self.sockets = [(c, w) for (c, w) in self.sockets if w is not ws]
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
        return ws

    async def control_turn(self, request):
        body = await request.json()
        cid, ws = self._last_ws()
        if ws is None:
            return web.json_response({"ok": False, "reason": "no_connection"},
                                     status=409)
        transcript = body.get("transcript", "")
        response_text = body.get("response_text", "ok")
        rid = "resp_mock_%d" % (self.events_sent + 1)
        with_audio = body.get("with_audio", True)

        async def send(obj):
            self.events_sent += 1
            await ws.send_str(json.dumps(obj))

        await send({"type": "input_audio_buffer.speech_started",
                    "audio_start_ms": 0, "item_id": "item_%s" % rid})
        await asyncio.sleep(0.02)
        await send({"type": "input_audio_buffer.speech_stopped",
                    "audio_end_ms": 200, "item_id": "item_%s" % rid})
        await send({"type": "conversation.item.input_audio_transcription.delta",
                    "item_id": "item_%s" % rid, "delta": transcript[:8]})
        await send({"type": "conversation.item.input_audio_transcription.completed",
                    "item_id": "item_%s" % rid, "transcript": transcript})
        await asyncio.sleep(0.02)
        await send({"type": "response.created",
                    "response": {"id": rid, "status": "in_progress"}})
        await send({"type": "response.audio_transcript.delta",
                    "response_id": rid, "delta": response_text[:12]})
        if with_audio:
            for i in range(int(body.get("chunks", 3))):
                await send({"type": "response.audio.delta", "response_id": rid,
                            "item_id": "item_%s" % rid,
                            "delta": base64.b64encode(_pcm(960)).decode()})
                await asyncio.sleep(0.01)
        await send({"type": "response.audio_transcript.done",
                    "response_id": rid, "transcript": response_text})
        await send({"type": "response.audio.done", "response_id": rid})
        await send({"type": "response.done",
                    "response": {"id": rid, "status": "completed"}})
        return web.json_response({"ok": True, "response_id": rid})

    async def control_event(self, request):
        body = await request.json()
        cid, ws = self._last_ws()
        if ws is None:
            return web.json_response({"ok": False, "reason": "no_connection"},
                                     status=409)
        ev = body.get("event")
        if ev == "speech_started":
            await ws.send_str(json.dumps(
                {"type": "input_audio_buffer.speech_started",
                 "audio_start_ms": 0, "item_id": "item_raw"}))
        elif ev == "response_done":
            await ws.send_str(json.dumps(
                {"type": "response.done",
                 "response": {"id": body.get("response_id") or "resp_raw",
                              "status": body.get("status", "completed")}}))
        else:
            return web.json_response({"ok": False, "reason": "unknown_event"},
                                     status=400)
        return web.json_response({"ok": True})

    async def control_updates(self, request):
        return web.json_response({"updates": list(self.updates),
                                  "connections": self.connections})

    async def control_state(self, request):
        return web.json_response({"connections": self.connections,
                                  "updates": len(self.updates),
                                  "events_sent": self.events_sent})


def make_app():
    m = MvpMock()
    app = web.Application()
    app.router.add_get("/api-ws/v1/realtime", m.handler)
    app.router.add_post("/control/turn", m.control_turn)
    app.router.add_post("/control/event", m.control_event)
    app.router.add_get("/control/updates", m.control_updates)
    app.router.add_get("/control/state", m.control_state)
    return app, m


async def run_forever(port):
    app, _ = make_app()
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    print("mvp mock qwen on ws://127.0.0.1:%d/api-ws/v1/realtime" % port,
          flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9789)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever(args.port))