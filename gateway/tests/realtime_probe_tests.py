"""REALTIME_PROBE_TESTS — P2-B2-R3-2C isolated verification.

Covers (MOCK ONLY — zero real Bailian, zero network beyond 127.0.0.1, zero
billing):

  A. probe core (gateway/app/admin/realtime_probe.py) against a LOCAL mock WS
     upstream: handshake + session_compat stages, honest flags
     (audio=not_tested, verified always False), close-cleanup;
  B. negative: upstream closes before session.created → handshake False;
  C. authorization: flag off → 403 `realtime_probe_not_authorized`; flag on but
     confirm_realtime missing → 403; flag on + confirm → runs;
  D. credential isolation: the probe dials the provider's OWN endpoint with the
     PROVIDER'S OWN sealed key (never the global/Tina key); frozen model and
     frozen provider are refused;
  E. ladder/gating honesty: success writes `realtime_handshake` (never
     verified/realtime_safe) and a model with ONLY that evidence is still
     refused by enable_gate with `evidence_missing`;
  F. teacher-list endpoint (gateway/app/teacher_voice.py): token-gated 401s,
     display-fields-only, frozen/disabled/text teachers excluded.

Run:  gateway venv  python tests/realtime_probe_tests.py   (from gateway/)
"""

import asyncio
import json
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_GATEWAY = os.path.dirname(_HERE)
_REPO = os.path.dirname(_GATEWAY)
for p in (_GATEWAY, _REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

import aiohttp                                                      # noqa: E402
from aiohttp import web, test_utils                                 # noqa: E402

from app.admin.app import create_admin_app                          # noqa: E402
from app.admin.auth import TokenStore                               # noqa: E402
from app.admin.config import load_admin_config                      # noqa: E402
from app.admin.stores import AdminStores                            # noqa: E402
from app.admin.realtime_probe import realtime_capability_probe      # noqa: E402
from app.teacher_voice import TEACHER_LIST_PATH, make_list_handler  # noqa: E402
from modules.model.credentials import CredentialStore               # noqa: E402
from modules.model.gating import enable_gate                        # noqa: E402
from modules.model.registry import ModelRegistry                    # noqa: E402
from modules.teacher.store import TeacherStore                      # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name +
          (("  → " + str(extra)) if extra and not cond else ""))


FIX_TOKEN = "probe-test-token"


# ---------------------------------------------------------------------------
# mock realtime upstream (local, loopback)
# ---------------------------------------------------------------------------

class MockRealtime:
    """Tiny WS upstream speaking the minimal realtime handshake."""

    def __init__(self):
        self.app = web.Application()
        self.app.router.add_get("/rt", self._handler)
        self.seen_headers = {}
        self.seen_query = {}
        self.mode = "ok"                     # ok | close_immediately
        self.runner = None
        self.port = None

    async def _handler(self, request):
        self.seen_headers = dict(request.headers)
        self.seen_query = dict(request.query)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        if self.mode == "close_immediately":
            await ws.close()
            return ws
        await ws.send_json({"type": "session.created"})
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except Exception:
                    continue
                if data.get("type") == "session.update":
                    await ws.send_json({"type": "session.updated"})
                    break
        await ws.close()
        return ws

    async def start(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        return "ws://127.0.0.1:%d/rt" % self.port

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()


# ---------------------------------------------------------------------------
# admin app harness (mirrors admin_v4_api_tests)
# ---------------------------------------------------------------------------

def _cfg(tmp):
    p = os.path.join(tmp, "tok")
    with open(p, "w") as fh:
        fh.write(FIX_TOKEN + "\n")
    os.chmod(p, 0o600)
    return load_admin_config(env={
        "ADMIN_ENABLED": "1", "ADMIN_BIND": "127.0.0.1", "ADMIN_PORT": "18133",
        "ADMIN_API_TOKEN_FILE": p, "ADMIN_API_TOKEN": ""})


def _stores(tmp, *, probe_authorized):
    sub = os.path.join(tmp, "stores")
    os.makedirs(sub, exist_ok=True)
    return AdminStores(
        policy_file="", memory_file="", knowledge_file="", workbench_url="",
        model_registry_file=os.path.join(sub, "registry.json"),
        model_credentials_file=os.path.join(sub, "creds.json"),
        model_credentials_key_file=os.path.join(sub, "creds.key"),
        knowledge_import_file="", knowledge_import_scratch="",
        teacher_file="", teaching_file="", voice_file="",
        realtime_snapshot=None,
        test_authorized=False, promote_authorized=False,
        realtime_probe_authorized=probe_authorized)


def _app(tmp, stores, probe_fn):
    c = _cfg(tmp)
    ts = TokenStore(c.token_file, c.token_env)
    ts.reload()
    app = create_admin_app(admin_config=c, token_store=ts,
                           gateway_info=lambda: {"mode": "mock", "ready": True},
                           stores=stores)
    app["model_realtime_probe_fn"] = probe_fn
    return app


async def amain():
    tmp = tempfile.mkdtemp(prefix="r32c-probe-")
    AUTH = {"Authorization": "Bearer " + FIX_TOKEN}

    # ---------------- fixture: registry + provider + model + credential -----
    sub = os.path.join(tmp, "stores")
    reg = ModelRegistry(os.path.join(sub, "registry.json")).load().ensure_seeded()
    creds = CredentialStore(os.path.join(sub, "creds.json"),
                            key_path=os.path.join(sub, "creds.key")).load()
    prov = reg.create_provider(
        name="验收服务商", protocol="dashscope",
        base_url="https://ws-acc-test.cn-beijing.maas.aliyuncs.com",
        resolver=lambda host: ["203.0.113.10"])
    mdl = reg.create_model(provider_id=prov["id"],
                           model_key="qwen3.8-omni-flash-realtime",
                           capabilities=["realtime_audio", "streaming",
                                         "barge_in"])
    creds.put(prov["id"], "PROBE-KEY-PROVIDER-A")
    GLOBAL_KEY = "TINA-GLOBAL-KEY-NOT-FOR-PROBES"

    seen = {"calls": []}

    async def fake_probe(ws_url, api_key, *, model, voice, **kw):
        seen["calls"].append({"ws_url": ws_url, "api_key": api_key,
                              "model": model, "voice": voice})
        return {"mode": "realtime_handshake", "network": True,
                "handshake": True, "session_compat": True,
                "audio": "not_tested", "verified": False,
                "latency_ms": 12, "reason": None, "detail": {}}

    # ---------------- C/E: authorization + ladder + gating ------------------
    stores = _stores(tmp, probe_authorized=False)
    app = _app(tmp, stores, fake_probe)
    url = "/admin/model/models/%s/test" % mdl["id"]
    async with test_utils.TestClient(test_utils.TestServer(app)) as cl:
        r = await cl.post(url, json={"mode": "realtime_handshake",
                                     "confirm_realtime": True}, headers=AUTH)
        b = await r.json()
        check("C1 授权位关闭 → 403 realtime_probe_not_authorized",
              r.status == 403 and b["error"] == "realtime_probe_not_authorized",
              str(r.status))
        check("C1b 门禁关闭时探针未被调用", len(seen["calls"]) == 0)

    stores2 = _stores(tmp, probe_authorized=True)
    app2 = _app(tmp, stores2, fake_probe)
    app2["model_realtime_probe_fn"] = fake_probe
    url2 = "/admin/model/models/%s/test" % mdl["id"]
    async with test_utils.TestClient(test_utils.TestServer(app2)) as cl:
        r = await cl.post(url2, json={"mode": "realtime_handshake"}, headers=AUTH)
        b = await r.json()
        check("C2 授权开启但缺 confirm_realtime → 403",
              r.status == 403 and b["error"] == "realtime_probe_not_authorized",
              str(r.status))

        r = await cl.post(url2, json={"mode": "realtime_handshake",
                                      "confirm_realtime": True}, headers=AUTH)
        body = await r.json()
        check("C3 授权+确认 → 200 且 wrote_evidence=True",
              r.status == 200 and body.get("wrote_evidence") is True, str(r.status))
        check("E1 证据等级 = realtime_handshake（非 verified/realtime_safe）",
              body.get("evidence_level") == "realtime_handshake")
        check("E2 结果诚实：audio=not_tested、verified=False",
              body["result"]["audio"] == "not_tested"
              and body["result"]["verified"] is False)

        # D: credential isolation — the probe dialed the PROVIDER's own endpoint
        call = seen["calls"][-1]
        check("D1 探针使用服务商自有端点（host 为该 provider）",
              call["ws_url"].startswith("wss://ws-acc-test.cn-beijing.maas.aliyuncs.com/")
              and "model=qwen3.8-omni-flash-realtime" in call["ws_url"], call["ws_url"])
        check("D2 探针使用服务商自有密封凭据（绝非全局/Tina Key）",
              call["api_key"] == "PROBE-KEY-PROVIDER-A"
              and call["api_key"] != GLOBAL_KEY)
        check("D3 全局 Key 从未进入探针参数",
              all(c["api_key"] != GLOBAL_KEY for c in seen["calls"]))

    # E3: the recorded level is honest and gating still refuses.
    # (fresh instance: the handler wrote through ITS OWN AdminStores instance)
    fresh = ModelRegistry(os.path.join(sub, "registry.json")).load()
    lvl = fresh.evidence_level(mdl["id"])
    ok, code, _detail = enable_gate(fresh, creds, mdl["id"], scene="oral_realtime",
                                    action="teaching")
    check("E3 仅 realtime_handshake 证据 → enable_gate 仍拒绝（evidence_missing）",
          lvl == "realtime_handshake" and not ok and code == "evidence_missing",
          "%s/%s/%s" % (lvl, ok, code))

    # D4: frozen model refused before any dial (freeze through the SAME
    # instance the handler reads — cross-instance reads don't reload)
    stores2.model_registry.mark_frozen(mdl["id"], True)
    async with test_utils.TestClient(test_utils.TestServer(app2)) as cl:
        r = await cl.post(url2, json={"mode": "realtime_handshake",
                                      "confirm_realtime": True}, headers=AUTH)
        b = await r.json()
        check("D4 冻结模型 → 400 frozen_model（探针不拨号）",
              r.status == 400 and b["error"] == "frozen_model", str(r.status))
    stores2.model_registry.mark_frozen(mdl["id"], False)

    # D5: frozen PROVIDER refused (hand-written record: provider frozen, model not)
    raw = json.loads(open(os.path.join(sub, "registry.json"),
                          encoding="utf-8").read())
    raw["providers"][prov["id"]]["frozen"] = True
    open(os.path.join(sub, "registry.json"), "w", encoding="utf-8").write(
        json.dumps(raw, ensure_ascii=False))
    stores2.model_registry.load()      # re-read the hand-edited file
    async with test_utils.TestClient(test_utils.TestServer(app2)) as cl:
        r = await cl.post(url2, json={"mode": "realtime_handshake",
                                      "confirm_realtime": True}, headers=AUTH)
        b = await r.json()
        check("D5 冻结服务商 → 400 frozen_provider", r.status == 400
              and b["error"] == "frozen_provider", str(r.status))

    # ---------------- A/B: probe core against the local mock upstream -------
    mock = MockRealtime()
    base = await mock.start()
    try:
        mock.mode = "ok"
        out = await realtime_capability_probe(
            base + "?model=qwen3.8-omni-flash-realtime", "MOCK-KEY",
            model="qwen3.8-omni-flash-realtime", voice="Cindy")
        check("A1 Mock 上游：handshake=True（收到 session.created）",
              out["handshake"] is True, str(out))
        check("A2 Mock 上游：session_compat=True（session.update→updated）",
              out["session_compat"] is True)
        check("A3 结果诚实：audio=not_tested、verified=False",
              out["audio"] == "not_tested" and out["verified"] is False)
        check("A4 请求头带 Bearer、query 带模型",
              mock.seen_headers.get("Authorization") == "Bearer MOCK-KEY"
              and mock.seen_query.get("model") == "qwen3.8-omni-flash-realtime")

        mock.mode = "close_immediately"
        mock.seen_headers = {}
        out2 = await realtime_capability_probe(
            base + "/rt", "MOCK-KEY", model="m", voice="v")
        check("B1 上游立即关闭 → handshake=False 且不写证据的原料",
              out2["handshake"] is False and out2["verified"] is False
              and out2["session_compat"] is False, str(out2["reason"]))
    finally:
        await mock.stop()

    # ---------------- F: teacher-list endpoint ------------------------------
    tpath = os.path.join(tmp, "teachers.json")
    tstore = TeacherStore(tpath).load().ensure_seeded()
    t_ok = tstore.create_teacher(
        name="R3-2C验收老师", enabled=True,
        voice={"mode": "realtime", "adapter_id": "", "voice_id": "Cindy",
               "accent": "american", "language": "en", "speed": None,
               "interaction": {"barge_in": True, "allow_transcript": True,
                               "max_turn_seconds": 120}},
        model={"text_model_id": "", "realtime_model_id": "mdl_x", "asr_model_id": "",
               "tts_model_id": ""})
    t_disabled = tstore.create_teacher(
        name="停用的实时老师", enabled=False,
        voice={"mode": "realtime", "adapter_id": "", "voice_id": "Zane",
               "accent": "american", "language": "en", "speed": None,
               "interaction": {"barge_in": False, "allow_transcript": True,
                               "max_turn_seconds": 120}},
        model={"text_model_id": "", "realtime_model_id": "mdl_x", "asr_model_id": "",
               "tts_model_id": ""})
    tstore.set_enabled(t_disabled["teacher_id"], False)
    tstore.create_teacher(
        name="文字老师", enabled=True,
        voice={"mode": "text", "adapter_id": "", "voice_id": "", "accent": "american",
               "language": "en", "speed": None,
               "interaction": {"barge_in": False, "allow_transcript": True,
                               "max_turn_seconds": 120}},
        model={"text_model_id": "", "realtime_model_id": "", "asr_model_id": "",
               "tts_model_id": ""})

    lapp = web.Application()
    lapp.router.add_get(TEACHER_LIST_PATH, make_list_handler(tstore, FIX_TOKEN))
    lurl = TEACHER_LIST_PATH
    async with test_utils.TestClient(test_utils.TestServer(lapp)) as cl:
        r = await cl.get(lurl)
        check("F1 无令牌 → 401", r.status == 401, str(r.status))
        r = await cl.get(lurl, headers={"X-Teacher-Token": "wrong"})
        b = await r.json()
        check("F2 错令牌 → 401（与无令牌同码，无枚举 oracle）",
              r.status == 401 and b["error"] == "invalid_token")
        r = await cl.get(lurl, headers={"X-Teacher-Token": FIX_TOKEN})
        body = await r.json()
        ids = [t["teacher_id"] for t in body.get("teachers", [])]
        text = json.dumps(body, ensure_ascii=False)
        check("F3 正确令牌 → 200，仅含启用的实时非冻结老师",
              r.status == 200 and t_ok["teacher_id"] in ids
              and len(ids) == 1, text[:160])
        check("F4 冻结 tina / 停用 / 文字老师 均不在列表",
              "tina" not in ids
              and "停用的实时老师" not in text and "文字老师" not in text)
        row = body["teachers"][0]
        check("F5 仅返回展示字段（id/名称/音色/语言），无内部键",
              set(row.keys()) == {"teacher_id", "display_name", "voice_id",
                                  "language"} and row["voice_id"] == "Cindy",
              str(sorted(row.keys())))
        check("F6 响应不含任何令牌/密钥材料", FIX_TOKEN not in text)

    print("\n==== SUMMARY ====")
    print("total=%d pass=%d fail=%d" % (len(PASS) + len(FAIL), len(PASS), len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
