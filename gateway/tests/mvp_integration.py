"""CONVERSATIONAL MVP integration regression.

Real bridge app (aiohttp, ephemeral ports) + drivable mock Qwen + fake
workbench + two synthetic clients.  Verifies the full conversational loop:
initial instruction policy, natural activity routing hot-apply, temporary
intent + automatic resume, language override, workbench answers (ok + down),
memory persistence across sessions, transcript UI forwarding, barge-in while
behavior is active, concurrency isolation, and dispatch integrity.

Runs standalone:  python tests/mvp_integration.py   (from gateway/, venv,
                   DYLD_LIBRARY_PATH must point at libopus)
"""

import asyncio
import json
import os
import sys
import tempfile
import time
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
_GATEWAY = os.path.dirname(_HERE)
_REPO = os.path.dirname(_GATEWAY)
for p in (_GATEWAY, _REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

import aiohttp                                                       # noqa: E402
import opuslib                                                       # noqa: E402
from aiohttp import web                                              # noqa: E402

# DEV-ONLY shim: this Mac's dev libopus build rejects OPUS_SET_BITRATE through
# ctypes (the documented R-1f local-environment quirk — the NAS image ships its
# own libopus where the frozen factory works; R-1f's sentinel harness fails
# locally for exactly this reason).  The shim only tolerates that one ctl
# failure; frame encoding and the pacing path are unchanged.
import app.audio as _audio                                           # noqa: E402

_orig_enc24 = _audio.OpusEnc24


def _dev_enc24():
    try:
        return _orig_enc24()
    except opuslib.exceptions.OpusError:
        return opuslib.Encoder(24000, 1, opuslib.APPLICATION_VOIP)


_audio.OpusEnc24 = _dev_enc24

from app.main import create_app                                      # noqa: E402
from app.qwen import QwenConfig                                      # noqa: E402
from tests.mvp_mock_qwen import make_app as make_mock_app            # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % (detail if not cond else ""))[:300]))


# ---- fake workbench (read-only, aiohttp) ----------------------------------

WB_STATE = {
    "rev": 77, "updatedAt": "2026-10-05T02:25:51Z",
    "state": {"version": 2, "currentLesson": 12,
              "lessons": {"1": {"status": "review_required", "decision": "REVIEW"},
                          "2": {"status": "passed", "decision": "PASS"}},
              "reviews": [{"id": "r1", "refId": "12:walked",
                           "nextReviewAt": "2026-10-05", "done": False}]},
}
WB_CONTENT = {"lesson": 12, "unit": "一般过去时（规则动词 -ed）",
              "objectives": ["用 -ed 说过去做过的事。"]}


class FakeWB:
    def __init__(self):
        self.requests = []

    async def state(self, r):
        self.requests.append(r.path)
        return web.json_response(WB_STATE)

    async def content(self, r):
        self.requests.append(r.path)
        return web.json_response(WB_CONTENT)

    def app(self):
        app = web.Application()
        app.router.add_get("/sync/state", self.state)
        app.router.add_get("/workbench/content/day{day}.json", self.content)
        return app


# ---- synthetic client ------------------------------------------------------

class Client:
    def __init__(self):
        self.session = None
        self.ws = None
        self._task = None
        self.transcripts = []
        self.tts_states = []
        self.bin_frames = 0
        self.other = []

    async def connect(self, port):
        self.session = aiohttp.ClientSession()
        self.ws = await self.session.ws_connect(
            "ws://127.0.0.1:%d/xiaozhi/v1/" % port, heartbeat=30)
        self._task = asyncio.create_task(self._reader())
        await self.ws.send_str(json.dumps({"type": "hello", "version": 1}))
        await self.ws.send_str(json.dumps({"type": "listen", "state": "start",
                                           "mode": "realtime"}))
        await asyncio.sleep(0.2)

    async def _reader(self):
        try:
            async for msg in self.ws:
                if msg.type == 1:  # TEXT
                    try:
                        obj = json.loads(msg.data)
                    except Exception:  # noqa: BLE001
                        continue
                    t = obj.get("type")
                    if t == "transcript":
                        self.transcripts.append(obj)
                    elif t == "tts":
                        self.tts_states.append(obj.get("state"))
                    else:
                        self.other.append(obj)
                elif msg.type == 2:  # BINARY
                    self.bin_frames += 1
        except Exception:  # noqa: BLE001
            pass

    async def close(self):
        if self._task is not None:
            self._task.cancel()
            self._task = None
        if self.ws is not None and not self.ws.closed:
            await self.ws.close()
        self.ws = None
        if self.session is not None:
            await self.session.close()
            self.session = None


async def wait_for(fn, timeout=6.0, poll=0.05):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        v = fn()
        if v:
            return v
        await asyncio.sleep(poll)
    return None


async def amain():
    tmp = tempfile.TemporaryDirectory()
    memory_file = os.path.join(tmp.name, "memory.json")

    # mock Qwen
    mock_app, mock = make_mock_app()
    mock_runner = web.AppRunner(mock_app)
    await mock_runner.setup()
    mock_site = web.TCPSite(mock_runner, "127.0.0.1", 0)
    await mock_site.start()
    mock_port = mock_site._server.sockets[0].getsockname()[1]

    # fake workbench
    wb = FakeWB()
    wb_runner = web.AppRunner(wb.app())
    await wb_runner.setup()
    wb_site = web.TCPSite(wb_runner, "127.0.0.1", 0)
    await wb_site.start()
    wb_port = wb_site._server.sockets[0].getsockname()[1]

    # bridge under test
    qcfg = QwenConfig.from_values({
        "QWEN_MODE": "mock",
        "QWEN_WS_URL": "ws://127.0.0.1:%d/api-ws/v1/realtime" % mock_port,
    })
    bridge_cfg = types.SimpleNamespace(
        PUBLIC_WS_URL="ws://127.0.0.1:0/xiaozhi/v1/", WS_PORT=0, HTTP_PORT=0,
        FRAME_MS=20, MEMORY_FILE=memory_file,
        WORKBENCH_BASE_URL="http://127.0.0.1:%d" % wb_port, qwen=qcfg)
    bridge = web.AppRunner(create_app(bridge_cfg))
    await bridge.setup()
    bsite = web.TCPSite(bridge, "127.0.0.1", 0)
    await bsite.start()
    bport = bsite._server.sockets[0].getsockname()[1]

    def last_update(conn=None, contains=None):
        for u in reversed(list(mock.updates)):
            if conn is not None and u["conn"] != conn:
                continue
            ins = (u["session"] or {}).get("instructions") or ""
            if contains is None or contains in ins:
                return ins
        return None

    def update_count():
        return len(mock.updates)

    try:
        # ---- I1: connect + initial instruction policy ---------------------
        a = Client()
        await a.connect(bport)
        ins0 = await wait_for(lambda: last_update(conn=1), 5)
        check("I1 initial session.update received", ins0 is not None)
        check("I1b policy + no-labels in initial instructions",
              ins0 and "LANGUAGE POLICY" in ins0 and "NEVER mention" in ins0)
        check("I1c initial activity chat", ins0 and "free chat" in ins0)

        # ---- I2: natural activity routing hot-apply ------------------------
        n0 = update_count()
        await aiohttp_client_post(mock_port, "/control/turn",
                                  {"transcript": "我们练一下酒店英语",
                                   "response_text": "Welcome to the Grand Hotel!",
                                   "chunks": 3})
        ins1 = await wait_for(lambda: last_update(contains="scenario conversation practice"), 6)
        check("I2 practice hot-applied", ins1 is not None and "hotel" in ins1,
              repr(ins1)[:120])
        check("I2b updates increased", update_count() > n0)

        # ---- I3: transcript UI forwarding ----------------------------------
        got_user = await wait_for(lambda: any(
            t.get("role") == "user" and t.get("final") for t in a.transcripts), 5)
        check("I3 user transcript FINAL forwarded to client", bool(got_user))
        got_assist = await wait_for(lambda: any(
            t.get("role") == "assistant" for t in a.transcripts), 5)
        check("I3b assistant transcript forwarded", bool(got_assist))

        # ---- I4: speed command keeps activity -------------------------------
        await aiohttp_client_post(mock_port, "/control/turn",
                                  {"transcript": "说慢一点",
                                   "response_text": "Sure, slower.",
                                   "chunks": 2})
        ins2 = await wait_for(lambda: last_update(contains="Speaking pace: SLOW"), 6)
        check("I4 slow hot-applied", ins2 is not None)
        check("I4b activity kept practice", ins2 and "scenario conversation practice" in ins2)

        # ---- I5: temporary intent + automatic resume ------------------------
        await aiohttp_client_post(mock_port, "/control/turn",
                                  {"transcript": "accommodation 是什么意思？",
                                   "response_text": "住宿的意思。",
                                   "chunks": 2})
        ins3 = await wait_for(lambda: last_update(contains='TEMPORARY (this turn only)'), 6)
        check("I5 temp explain hot-applied",
              ins3 is not None and "accommodation" in ins3, repr(ins3)[:120])
        resumed = await wait_for(
            lambda: next((u for u in reversed(list(mock.updates))
                          if u["conn"] == 1
                          and "TEMPORARY (this turn only)"
                          not in ((u["session"] or {}).get("instructions") or "")
                          and "scenario conversation practice"
                          in ((u["session"] or {}).get("instructions") or "")), None), 8)
        check("I5b resumed to practice automatically", resumed is not None)

        # ---- I6: language override ------------------------------------------
        await aiohttp_client_post(mock_port, "/control/turn",
                                  {"transcript": "你可以说中文吗？",
                                   "response_text": "当然可以。",
                                   "chunks": 2})
        ins4 = await wait_for(lambda: last_update(
            contains="Current reply language: Chinese") and last_update(
            contains="override: zh"), 6)
        check("I6 zh override hot-applied", ins4 is not None)

        # ---- I7: workbench answers -------------------------------------------
        await aiohttp_client_post(mock_port, "/control/turn",
                                  {"transcript": "继续上次的课",
                                   "response_text": "好，我们继续第 12 课。",
                                   "chunks": 2})
        ins5 = await wait_for(lambda: last_update(contains="Resume lesson 12"), 6)
        check("I7 continue-lesson real data", ins5 is not None
              and "一般过去时" in ins5, repr(ins5)[:150])
        await aiohttp_client_post(mock_port, "/control/turn",
                                  {"transcript": "我学到哪里了？",
                                   "response_text": "你在第 12 课。",
                                   "chunks": 2})
        ins6 = await wait_for(lambda: last_update(contains="current lesson: 12"), 6)
        check("I7b progress real data", ins6 is not None and "passed: 1" in ins6,
              repr(ins6)[:150])

        # ---- I8: memory save (explicit) ---------------------------------------
        await aiohttp_client_post(mock_port, "/control/turn",
                                  {"transcript": "以后解释单词先用中文，记住。",
                                   "response_text": "好的，记住了。",
                                   "chunks": 2})
        await asyncio.sleep(0.4)
        mem = json.load(open(memory_file, encoding="utf-8"))
        pref = (mem["users"]["default"]["items"].get("explanation_language") or {})
        check("I8 memory preference persisted",
              pref.get("value") == "zh" and pref.get("source") == "explicit_user")

        # ---- I9: barge-in while behavior active --------------------------------
        await aiohttp_client_post(mock_port, "/control/turn",
                                  {"transcript": "继续",
                                   "response_text": "Let me tell you a long story about the hotel.",
                                   "chunks": 30})
        await wait_for(lambda: a.tts_states.count("start") >= 1 and a.bin_frames > 0, 5)
        stops_before = a.tts_states.count("stop")
        await aiohttp_client_post(mock_port, "/control/event",
                                  {"event": "speech_started"})
        stop_seen = await wait_for(lambda: a.tts_states.count("stop") > stops_before, 5)
        check("I9 barge-in stops playback (Path B)", bool(stop_seen),
              repr(a.tts_states[-6:]))

        # ---- I10: concurrency isolation ----------------------------------------
        b = Client()
        await b.connect(bport)
        await wait_for(lambda: last_update(conn=2) is not None, 5)
        await aiohttp_client_post(mock_port, "/control/turn",
                                  {"transcript": "我想背几个单词",
                                   "response_text": "好，我们来学几个词。",
                                   "chunks": 2})
        insb = await wait_for(lambda: last_update(conn=2, contains="vocabulary learning"), 6)
        check("I10 session B independent (vocab)", insb is not None)
        check("I10b session A not switched by B",
              last_update(conn=1, contains="vocabulary learning") is None)
        check("I10c two upstream connections", mock.connections == 2)
        await b.close()
        await asyncio.sleep(0.3)

        # ---- I11a: review answer from real data (cache fresh) -------------------
        await aiohttp_client_post(mock_port, "/control/turn",
                                  {"transcript": "这个需要复习吗？",
                                   "response_text": "有一个复习项到期。",
                                   "chunks": 2})
        ins7 = await wait_for(lambda: last_update(conn=1, contains="Review items due: 1"), 8)
        check("I11a review data real (due 1)", ins7 is not None, repr(ins7)[:150])

        # ---- I11b: NEW session with workbench DOWN (no cache) -> degrade --------
        await wb_runner.cleanup()
        c = Client()
        await c.connect(bport)
        check("I11b third upstream connection", mock.connections == 3)
        await aiohttp_client_post(mock_port, "/control/turn",
                                  {"transcript": "我学到哪里了？",
                                   "response_text": "……",
                                   "chunks": 2})
        ins7b = await wait_for(lambda: last_update(conn=3, contains="UNAVAILABLE"), 8)
        check("I11b workbench down + no cache -> degrade line",
              ins7b is not None and "temporarily unavailable" in ins7b,
              repr(ins7b)[:150])
        await c.close()

        # ---- I12: reconnect -> new session applies memory ------------------------
        await a.close()
        await asyncio.sleep(0.4)
        a2 = Client()
        await a2.connect(bport)
        ins8 = await wait_for(lambda: last_update(conn=4), 6)
        check("I12 reconnect new session", ins8 is not None and mock.connections == 4)
        check("I12b memory preference applied on new session",
              ins8 and "word explanations first in 中文" in ins8)
        check("I12c fresh session starts from chat activity",
              ins8 and "free chat" in ins8)

        # ---- I13: integrity ------------------------------------------------------
        async with a2.session.get("http://127.0.0.1:%d/health" % bport) as r:
            health = await r.json()
        check("I13 dispatch integrity", health.get("qwen_dispatch_errors_total") == 0,
              repr(health.get("qwen_dispatch_errors_total")))
        check("I13b responses completed > 0", health.get("responses_completed", 0) > 0)
        check("I13c no orphan / accounting faults",
              health.get("orphan_pcm_bytes") == 0
              and health.get("accounting_fault_events") == 0,
              repr({k: health.get(k) for k in ("orphan_pcm_bytes",
                                               "accounting_fault_events")}))
        await a2.close()

    finally:
        try:
            await bridge.cleanup()
        except Exception:  # noqa: BLE001
            pass
        try:
            await mock_runner.cleanup()
        except Exception:  # noqa: BLE001
            pass
        try:
            await wb_runner.cleanup()
        except Exception:  # noqa: BLE001
            pass
        tmp.cleanup()


async def aiohttp_client_post(port, path, body):
    async with aiohttp.ClientSession() as s:
        async with s.post("http://127.0.0.1:%d%s" % (port, path),
                          json=body) as r:
            return await r.json()


def main():
    asyncio.run(amain())
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("=" * 70)
    print("MVP_INTEGRATION_TESTS: %d checks, %d PASS, %d FAIL" %
          (total, passed, total - passed))
    for name, ok, detail in RESULTS:
        if not ok:
            print("  FAILED: %s %s" % (name, str(detail)[:200]))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())