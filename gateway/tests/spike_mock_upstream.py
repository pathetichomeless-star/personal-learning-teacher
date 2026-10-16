"""Protocol mock for the Phase-3 session.update spike (mock/protocol evidence).

Emulates the Qwen protocol subset the spike probe exercises, so the probe's
logic (recv predicates, verdict classification, evidence JSON) can be validated
locally without touching the real service. The mock deliberately implements the
OpenAI/DashScope-shaped semantics: a SECOND `session.update` is accepted and
echoed as `session.updated`; `session.updated` echoes voice+instructions;
`response.create` is supported; system-role items are rejected (as a
deliberately conservative stub — the real service's behaviour is what the real
spike records).

Usage:  python gateway/tests/spike_mock_upstream.py [port]
Then:   python gateway/tests/spike_session_update.py \
            --url ws://127.0.0.1:9788/api-ws/v1/realtime --out /tmp/spike_mock.json
"""

import asyncio
import json
import sys

from aiohttp import web, WSMsgType


class Mock:
    def __init__(self):
        self.instructions = "ALPHA-default"
        self.voice = "Tina"
        self.resp_seq = 0

    async def handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_str(json.dumps({
            "type": "session.created",
            "session": {"id": "mock_sess", "model": "qwen3.8-omni-flash-realtime",
                        "voice": "Tina", "turn_detection": {"type": "server_vad"}}}))
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                obj = json.loads(msg.data)
                etype = obj.get("type")
                if etype == "session.update":
                    sess = obj.get("session") or {}
                    if "instructions" in sess:
                        self.instructions = sess["instructions"]
                    if "voice" in sess:
                        self.voice = sess["voice"]
                    await ws.send_str(json.dumps({
                        "type": "session.updated",
                        "session": {"voice": self.voice,
                                    "instructions": self.instructions}}))
                elif etype == "conversation.item.create":
                    item = obj.get("item") or {}
                    if item.get("role") == "system":
                        await ws.send_str(json.dumps({
                            "type": "error",
                            "error": {"type": "invalid_request_error",
                                      "code": "mock_system_role_rejected",
                                      "message": "mock rejects system role",
                                      "param": "item.role"}}))
                elif etype == "response.create":
                    self.resp_seq += 1
                    rid = "resp_%d" % self.resp_seq
                    await ws.send_str(json.dumps({"type": "response.created",
                                                  "response": {"id": rid}}))
                    word = "BRAVO" if "BRAVO" in self.instructions else "ALPHA"
                    await ws.send_str(json.dumps({
                        "type": "response.audio_transcript.delta",
                        "response_id": rid, "delta": word}))
                    await ws.send_str(json.dumps({
                        "type": "response.audio_transcript.done",
                        "response_id": rid, "transcript": word}))
                    await ws.send_str(json.dumps({
                        "type": "response.done",
                        "response": {"id": rid, "status": "completed"}}))
                elif etype == "session.finish":
                    break
        finally:
            await ws.close()
        return ws


async def amain(port):
    m = Mock()
    app = web.Application()
    app.router.add_get("/api-ws/v1/realtime", m.handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    print("mock spike upstream on ws://127.0.0.1:%d" % port, flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(amain(int(sys.argv[1]) if len(sys.argv) > 1 else 9788))