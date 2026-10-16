"""PRODUCT_V1_INTEGRATION — the full cross-module machine scenarios (directive Phase 6).

Real bridge app (aiohttp, ephemeral ports) + drivable mock Qwen + fake read-only
workbench + the ADMIN-2 control plane (in-process, same store files) + synthetic
clients.  Covers the 13 required scenarios:

  1 Chinese natural chat            8 Workbench authoritative progress
  2 English hotel practice          9 Knowledge hit → bounded injection
  3 Canonical vocabulary policy    10 Knowledge miss → honest, no fabrication
  4 Memory save (explicit)         11 Admin persona preview/apply/read-back → safe-boundary
  5 New session applies Memory     12 Reconnect: fresh transcript stream, Memory persists,
  6 Memory forget                      Workbench still authoritative
  7 Continue lesson (real data)    13 Two concurrent sessions → isolated state

Runs standalone:  python tests/product_v1_integration.py   (from gateway/, venv,
                   DYLD_LIBRARY_PATH must point at libopus)
"""

import asyncio
import json
import os
import sys
import tempfile
import time
import types
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
_GATEWAY = os.path.dirname(_HERE)
_REPO = os.path.dirname(_GATEWAY)
for p in (_GATEWAY, _REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

import aiohttp                                                       # noqa: E402
import opuslib                                                       # noqa: E402
from aiohttp import web                                              # noqa: E402

# DEV-ONLY shim (documented local libopus quirk — identical to mvp_integration)
import app.audio as _audio                                           # noqa: E402

_orig_enc24 = _audio.OpusEnc24


def _dev_enc24():
    try:
        return _orig_enc24()
    except opuslib.exceptions.OpusError:
        return opuslib.Encoder(24000, 1, opuslib.APPLICATION_VOIP)


_audio.OpusEnc24 = _dev_enc24

from aiohttp.test_utils import TestClient, TestServer                # noqa: E402

from app.admin import load_admin_config                              # noqa: E402
from app.admin.app import create_admin_app                           # noqa: E402
from app.admin.auth import TokenStore                                # noqa: E402
from app.admin.stores import AdminStores                             # noqa: E402
from app.main import create_app                                      # noqa: E402
from app.qwen import QwenConfig                                      # noqa: E402
from modules.knowledge.store import KnowledgeStore                   # noqa: E402
from modules.memory.store import MemoryStore                         # noqa: E402
from tests.mvp_mock_qwen import make_app as make_mock_app            # noqa: E402
from datetime import date, timedelta                                 # noqa: E402

RESULTS = []
FIX_TOKEN = "PV1_INTEGRATION_TOKEN_DO_NOT_LEAK_4242"


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % (detail if not cond else ""))[:300]))


# ---- fake workbench (read-only, records methods) ---------------------------

class FakeWB:
    def __init__(self):
        self.calls = []

    async def state(self, r):
        self.calls.append((r.method, r.path))
        today = date.today()
        return web.json_response({
            "rev": 77, "updatedAt": "2026-10-05T02:25:51Z",
            "state": {"version": 2, "currentLesson": 12,
                      "lessons": {"1": {"status": "review_required", "decision": "REVIEW"},
                                  "2": {"status": "passed", "decision": "PASS"}},
                      "reviews": [{"id": "r1", "refId": "12:walked", "done": False,
                                   "nextReviewAt": (today - timedelta(days=1)).isoformat()}]}})

    async def content(self, r):
        self.calls.append((r.method, r.path))
        return web.json_response({"lesson": 12, "unit": "一般过去时（规则动词 -ed）",
                                  "objectives": ["用 -ed 说过去做过的事。"]})

    def app(self):
        app = web.Application()
        app.router.add_route("*", "/sync/state", self.state)
        app.router.add_get("/workbench/content/day{day}.json", self.content)
        return app


class Client:
    def __init__(self):
        self.session = None
        self.ws = None
        self._task = None
        self.transcripts = []
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
                if msg.type == 1:
                    try:
                        obj = json.loads(msg.data)
                    except Exception:  # noqa: BLE001
                        continue
                    if obj.get("type") == "transcript":
                        self.transcripts.append(obj)
                    else:
                        self.other.append(obj)
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


async def wait_for(fn, timeout=8.0, poll=0.05):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        v = fn()
        if v:
            return v
        await asyncio.sleep(poll)
    return None


async def post(port, path, body):
    async with aiohttp.ClientSession() as s:
        async with s.post("http://127.0.0.1:%d%s" % (port, path), json=body) as r:
            return await r.json()


async def amain():
    tmp = tempfile.TemporaryDirectory()
    memory_file = os.path.join(tmp.name, "memory.json")
    knowledge_file = os.path.join(tmp.name, "knowledge.json")
    policy_file = os.path.join(tmp.name, "policy.json")
    Path(tmp.name, "admin_api_token").write_text(FIX_TOKEN + "\n")
    os.chmod(Path(tmp.name, "admin_api_token"), 0o600)

    mock_app, mock = make_mock_app()
    mock_runner = web.AppRunner(mock_app)
    await mock_runner.setup()
    mock_site = web.TCPSite(mock_runner, "127.0.0.1", 0)
    await mock_site.start()
    mock_port = mock_site._server.sockets[0].getsockname()[1]

    wb = FakeWB()
    wb_runner = web.AppRunner(wb.app())
    await wb_runner.setup()
    wb_site = web.TCPSite(wb_runner, "127.0.0.1", 0)
    await wb_site.start()
    wb_port = wb_site._server.sockets[0].getsockname()[1]

    qcfg = QwenConfig.from_values({
        "QWEN_MODE": "mock",
        "QWEN_WS_URL": "ws://127.0.0.1:%d/api-ws/v1/realtime" % mock_port,
    })
    bridge_cfg = types.SimpleNamespace(
        PUBLIC_WS_URL="ws://127.0.0.1:0/xiaozhi/v1/", WS_PORT=0, HTTP_PORT=0,
        FRAME_MS=20, MEMORY_FILE=memory_file, KNOWLEDGE_FILE=knowledge_file,
        POLICY_FILE=policy_file,
        WORKBENCH_BASE_URL="http://127.0.0.1:%d" % wb_port, qwen=qcfg)
    bridge = web.AppRunner(create_app(bridge_cfg))
    await bridge.setup()
    bsite = web.TCPSite(bridge, "127.0.0.1", 0)
    await bsite.start()
    bport = bsite._server.sockets[0].getsockname()[1]

    admin_cfg = load_admin_config(env={
        "ADMIN_ENABLED": "1", "ADMIN_BIND": "127.0.0.1", "ADMIN_PORT": "18116",
        "ADMIN_API_TOKEN_FILE": str(Path(tmp.name) / "admin_api_token"),
        "ADMIN_UI_DIR": str(Path(_REPO) / "admin"),
    })
    ts = TokenStore(admin_cfg.token_file, admin_cfg.token_env)
    ts.reload()
    admin_stores = AdminStores(policy_file=policy_file, memory_file=memory_file,
                               knowledge_file=knowledge_file,
                               workbench_url="http://127.0.0.1:%d" % wb_port)
    admin_app = create_admin_app(admin_config=admin_cfg, token_store=ts,
                                 gateway_info=lambda: {"mode": "mock", "ready": True},
                                 stores=admin_stores)
    AUTH = {"Authorization": "Bearer " + FIX_TOKEN}

    def last_update(conn=None, contains=None, exclude=None):
        for u in reversed(list(mock.updates)):
            if conn is not None and u["conn"] != conn:
                continue
            ins = (u["session"] or {}).get("instructions") or ""
            if contains is not None and contains not in ins:
                continue
            if exclude is not None and exclude in ins:
                continue
            return u
        return None

    def find_update(since, conn=None, contains=None, exclude=None):
        """Match only updates recorded AFTER index ``since`` (no stale matches)."""
        for u in list(mock.updates)[since:]:
            if conn is not None and u["conn"] != conn:
                continue
            ins = (u["session"] or {}).get("instructions") or ""
            if contains is not None and contains not in ins:
                continue
            if exclude is not None and exclude in ins:
                continue
            return u
        return None

    def ins_of(u):
        return (u or {}).get("session", {}).get("instructions") or ""

    try:
        async with TestClient(TestServer(admin_app)) as admin:
            # ---- H1: chat + hotel practice (scenarios 1 & 2) -------------------
            a = Client()
            await a.connect(bport)
            u0 = await wait_for(lambda: last_update(conn=1), 6)
            check("H1 initial instructions delivered (policy renderer)",
                  bool(u0) and "LANGUAGE POLICY" in ins_of(u0)
                  and "TEACHING POLICY:" in ins_of(u0))

            await post(mock_port, "/control/turn",
                       {"transcript": "我们练一下酒店英语",
                        "response_text": "Welcome to the Grand Hotel!", "chunks": 2})
            u1 = await wait_for(lambda: last_update(conn=1,
                                                    contains="scenario conversation practice"), 8)
            check("H1b hotel practice hot-applied (scenario 2)",
                  bool(u1) and "hotel" in ins_of(u1))

            await post(mock_port, "/control/turn",
                       {"transcript": "我们随便聊聊",
                        "response_text": "好呀，想聊点什么？", "chunks": 2})
            u2 = await wait_for(lambda: last_update(conn=1, contains="free chat"), 8)
            check("H1c back to Chinese free chat (scenario 1)",
                  bool(u2) and "Current reply language: Chinese." in ins_of(u2))

            # ---- H2: canonical vocabulary policy (scenario 3a) -----------------
            n = len(mock.updates)
            await post(mock_port, "/control/turn",
                       {"transcript": "街道用英语怎么说？",
                        "response_text": "street /striːt/ 街道。", "chunks": 2})
            u3 = await wait_for(lambda: find_update(
                n, conn=1, contains="VOCABULARY ACCURACY POLICY"), 8)
            check("H2 vocabulary request carries the canonical-spelling policy",
                  bool(u3) and "canonical English spelling FIRST" in ins_of(u3)
                  and "TEMPORARY (this turn only)" in ins_of(u3))
            resumed = await wait_for(lambda: find_update(
                n, conn=1, contains="free chat",
                exclude="TEMPORARY (this turn only)"), 8)
            check("H2b automatic resume after the vocabulary turn", bool(resumed))

            # ---- H3: explain-word temp intent (scenario 3b) --------------------
            await post(mock_port, "/control/turn",
                       {"transcript": "accommodation 是什么意思？",
                        "response_text": "住宿。", "chunks": 2})
            u4 = await wait_for(lambda: last_update(conn=1, contains="accommodation"), 8)
            check("H3 explain-word temp intent hot-applied (word carried)",
                  bool(u4) and "TEMPORARY (this turn only)" in ins_of(u4))

            # ---- H4: explicit memory save (scenario 4) -------------------------
            await post(mock_port, "/control/turn",
                       {"transcript": "以后解释单词先用中文，记住。",
                        "response_text": "好的，记住了。", "chunks": 2})
            await asyncio.sleep(0.4)
            check("H4 memory preference persisted on the explicit turn (scenario 4)",
                  MemoryStore(memory_file).load().preferences()
                  == {"explanation_language": "zh"})

            # ---- H5: new session applies memory (scenario 5) --------------------
            await a.close()
            await asyncio.sleep(0.3)
            b = Client()
            await b.connect(bport)
            ub0 = await wait_for(lambda: last_update(conn=2), 6)
            check("H5 new session applies the saved preference (scenario 5)",
                  bool(ub0) and "word explanations first in 中文" in ins_of(ub0))
            check("H5b fresh session starts from chat",
                  "free chat" in ins_of(ub0) and mock.connections == 2)

            # ---- H6: explicit forget (scenario 6) -------------------------------
            await post(mock_port, "/control/turn",
                       {"transcript": "忘掉这个偏好",
                        "response_text": "好的，已经忘掉了。", "chunks": 2})
            await asyncio.sleep(0.4)
            check("H6 memory preference forgotten via conversation (scenario 6)",
                  MemoryStore(memory_file).load().preferences() == {})

            # ---- H7: workbench answers (scenarios 7 & 8) ------------------------
            await post(mock_port, "/control/turn",
                       {"transcript": "继续上次的课",
                        "response_text": "好，我们继续第 12 课。", "chunks": 2})
            u5 = await wait_for(lambda: last_update(conn=2, contains="Resume lesson 12"), 8)
            check("H7 continue lesson uses real workbench data (scenario 7)",
                  bool(u5) and "一般过去时" in ins_of(u5))
            await post(mock_port, "/control/turn",
                       {"transcript": "我学到哪里了？",
                        "response_text": "你在第 12 课。", "chunks": 2})
            u6 = await wait_for(lambda: last_update(conn=2, contains="current lesson: 12"), 8)
            check("H7b progress answer from authoritative data (scenario 8)",
                  bool(u6) and "passed: 1" in ins_of(u6))

            # ---- H8: knowledge hit through the ADMIN plane (scenario 9) ---------
            ds = (await (await admin.post("/admin/knowledge/dataset/create", headers=AUTH,
                                          json={"name": "客服资料"})).json())["dataset"]
            doc = (await (await admin.post(
                "/admin/knowledge/document/add", headers=AUTH,
                json={"dataset_id": ds["id"], "title": "入住说明",
                      "text": "酒店入住时间是下午三点以后。退房时间是中午十二点前。\n\n"
                              "入住时请出示护照。",
                      "source_type": "text"})).json())["document"]
            await post(mock_port, "/control/turn",
                       {"transcript": "知识库里有没有关于酒店入住的信息？",
                        "response_text": "入住时间是下午三点以后。", "chunks": 2})
            u7 = await wait_for(lambda: last_update(conn=2,
                                                    contains="KNOWLEDGE BASE DATA"), 8)
            check("H8 admin-added knowledge reaches the conversation (scenario 9)",
                  bool(u7) and "下午三点" in ins_of(u7) and "入住说明" in ins_of(u7))
            kdocs = await (await admin.get(
                "/admin/knowledge/dataset/%s/documents" % ds["id"], headers=AUTH)).json()
            check("H8b admin read-back of the same store", kdocs["count"] == 1)

            # ---- H9: knowledge miss stays honest (scenario 10) ------------------
            await post(mock_port, "/control/turn",
                       {"transcript": "知识库里有关于量子计算的内容吗",
                        "response_text": "知识库里暂时没有这方面内容。", "chunks": 2})
            u8 = await wait_for(lambda: last_update(conn=2,
                                                    contains="no matching entry"), 8)
            check("H9 explicit knowledge miss renders the honest line (scenario 10)",
                  bool(u8))
            n_before = len(mock.updates)
            await post(mock_port, "/control/turn",
                       {"transcript": "月球上一天有多长时间",
                        "response_text": "约 27 天。", "chunks": 2})
            await asyncio.sleep(1.0)
            injected = [u for u in list(mock.updates)[n_before:]
                        if "KNOWLEDGE BASE DATA" in ins_of(u)]
            check("H9b implicit probe miss injects nothing (no fabricated data)",
                  injected == [])

            # ---- H10: admin persona preview/apply/read-back (scenario 11) -------
            pv = await (await admin.post("/admin/policy/preview", headers=AUTH,
                                         json={"policy": {"persona": {"name": "小美"}}})).json()
            check("H10 preview validates + shows changed keys (safe, no mutation)",
                  pv["valid"] and pv["changed_keys"] == ["persona.name"]
                  and pv["would_be_version"] == 2)
            ap = await (await admin.post("/admin/policy/apply", headers=AUTH,
                                         json={"policy": {"persona": {"name": "小美"}},
                                               "confirm": True})).json()
            check("H10b apply + read-back", ap["readback_ok"] is True
                  and ap["applied"]["version"] == 2)
            n_before = len(mock.updates)
            await post(mock_port, "/control/turn",
                       {"transcript": "你好呀", "response_text": "你好！", "chunks": 2})
            u9 = await wait_for(lambda: last_update(conn=2, contains="You are 小美"), 8)
            check("H10c new policy reaches the live session at the next turn",
                  bool(u9))
            check("H10d hot apply was instructions-only (no model/voice/VAD keys)",
                  bool(u9) and set((u9.get("session") or {}).keys()) == {"instructions"})

            # ---- H11: injection is ephemeral, never persisted -------------------
            kraw = open(knowledge_file, encoding="utf-8").read()
            mraw = open(memory_file, encoding="utf-8").read()
            check("H11 injected knowledge/instructions never persisted into stores",
                  "KNOWLEDGE BASE DATA" not in kraw and "KNOWLEDGE BASE DATA" not in mraw
                  and "小美" not in mraw)

            # ---- H12: reconnect (scenario 12) -----------------------------------
            await b.close()
            await asyncio.sleep(0.3)
            c = Client()
            await c.connect(bport)
            uc0 = await wait_for(lambda: last_update(conn=3), 6)
            check("H12 reconnect → fresh transcript stream (no history replay)",
                  c.transcripts == [] and mock.connections == 3)
            check("H12b fresh session lacks the forgotten preference",
                  bool(uc0) and "word explanations first in 中文" not in ins_of(uc0))
            check("H12c fresh session starts from chat (state not carried over)",
                  "free chat" in ins_of(uc0))
            await post(mock_port, "/control/turn",
                       {"transcript": "继续上次的课",
                        "response_text": "好，继续第 12 课。", "chunks": 2})
            uc1 = await wait_for(lambda: last_update(conn=3, contains="Resume lesson 12"), 8)
            check("H12d workbench still authoritative after reconnect", bool(uc1))

            # ---- H13: concurrent sessions isolated (scenario 13) ----------------
            d = Client()
            await d.connect(bport)
            await wait_for(lambda: last_update(conn=4), 6)
            await post(mock_port, "/control/turn",
                       {"transcript": "我想背几个单词",
                        "response_text": "好，我们来学几个词。", "chunks": 2})
            ud = await wait_for(lambda: last_update(conn=4, contains="vocabulary learning"), 8)
            check("H13 session D independent activity (scenario 13)", bool(ud))
            check("H13b session C unaffected by D",
                  last_update(conn=3, contains="vocabulary learning") is None)
            check("H13c four upstream connections total", mock.connections == 4)
            await d.close()
            await c.close()

            # ---- H14: ownership boundaries (static, whole run) -------------------
            bad_methods = [m for m, _ in wb.calls if m != "GET"]
            check("H14 WORKBENCH_WRITES = 0 (every adapter call was a GET)",
                  bad_methods == [], bad_methods)
            check("H14b memory has no progress-shaped keys (0 duplication)",
                  MemoryStore(memory_file).load().assert_no_progress_keys() == [])
            ks = KnowledgeStore(knowledge_file).load()
            check("H14c knowledge has no progress/transcript keys",
                  "progress" not in kraw.lower() and "transcript" not in kraw.lower()
                  and ks.diagnostics()["datasets"]["total"] == 1)
            blob = json.dumps([list(u.values()) for u in admin_stores.audit.recent(50)],
                              ensure_ascii=False)
            check("H14d admin audit carries no token/values/transcripts",
                  FIX_TOKEN not in blob and "下午三点" not in blob
                  and "transcript" not in blob.lower())

            # ---- H15: health integrity through the whole run ---------------------
            async with aiohttp.ClientSession() as hs:
                async with hs.get("http://127.0.0.1:%d/health" % bport) as r:
                    health = await r.json()
            check("H15 dispatch integrity (0 errors, responses > 0)",
                  health.get("qwen_dispatch_errors_total") == 0
                  and health.get("responses_completed", 0) > 0)

    finally:
        for runner in (bridge, mock_runner, wb_runner):
            try:
                await runner.cleanup()
            except Exception:  # noqa: BLE001
                pass
        tmp.cleanup()


def main():
    asyncio.run(amain())
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("=" * 70)
    print("PRODUCT_V1_INTEGRATION: %d checks, %d PASS, %d FAIL" %
          (total, passed, total - passed))
    for name, ok, detail in RESULTS:
        if not ok:
            print("  FAILED: %s %s" % (name, str(detail)[:200]))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())