"""ADMIN_V4_API_TESTS — deterministic contract/interface/security/compat suite.

Runs standalone:  python tests/admin_v4_api_tests.py   (from gateway/, venv)

Covers the V4 additions (contract §1–§5) without any paid model call and without
network access:

* route inventory matches what is mounted (V4 additive);
* provider/model/credential/scene CRUD + disk read-back;
* the server-side enable gate (frozen / adapter / evidence / credential / scene);
* the protocol-vs-verified test levels (verified is authorization-gated);
* SSRF endpoint policy (private / metadata / non-https rejected);
* the knowledge import pipeline I1–I8 (upload ≠ commit), duplicate, cancel,
  not-retryable, expired, upload cap;
* store-unavailable reads AND writes return 503 (never a fake empty store);
* secrets never appear in any response;
* frozen Tina link is auto-detected and read-only.
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import aiohttp                                                  # noqa: E402
from aiohttp import web                                         # noqa: E402
from aiohttp.test_utils import TestClient, TestServer           # noqa: E402

from app.admin.app import admin_route_table, create_admin_app    # noqa: E402
from app.admin.auth import TokenStore                            # noqa: E402
from app.admin.config import load_admin_config                   # noqa: E402
from app.admin.stores import AdminStores                         # noqa: E402
from app.admin import api_import as api_import_mod               # noqa: E402
from modules.model.registry import ModelRegistry                 # noqa: E402
from modules.model.probe import _models_url                      # noqa: E402

FIX_TOKEN = "V4_TEST_BEARER_TOKEN_DO_NOT_LEAK_13579"
SECRET = "sk-v4-very-secret-value-should-never-appear"
AUTH = {"Authorization": "Bearer " + FIX_TOKEN}
RESULTS = []
FAKE_IP = lambda host: ["93.184.216.34"]                         # noqa: E731


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % (detail,)) if (detail and not cond) else ""))


class _Resp:
    def __init__(self, status):
        self.status = status

    def read(self, n=-1):
        return b'{"data":[]}'

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Opener:
    def __init__(self, status=200):
        self.status = status

    def open(self, req, timeout=None):
        return _Resp(self.status)


def _cfg(tmp):
    p = os.path.join(tmp, "tok")
    with open(p, "w") as fh:
        fh.write(FIX_TOKEN + "\n")
    os.chmod(p, 0o600)
    return load_admin_config(env={
        "ADMIN_ENABLED": "1", "ADMIN_BIND": "127.0.0.1", "ADMIN_PORT": "18131",
        "ADMIN_API_TOKEN_FILE": p, "ADMIN_API_TOKEN": ""})


def _stores(tmp, *, prefix="v4"):
    sub = os.path.join(tmp, prefix)
    os.makedirs(sub, exist_ok=True)
    return AdminStores(
        policy_file=os.path.join(sub, "policy.json"),
        memory_file=os.path.join(sub, "memory.json"),
        knowledge_file=os.path.join(sub, "knowledge.json"),
        workbench_url="",
        model_registry_file=os.path.join(sub, "registry.json"),
        model_credentials_file=os.path.join(sub, "creds.json"),
        model_credentials_key_file=os.path.join(sub, "creds.key"),
        knowledge_import_file=os.path.join(sub, "imports.json"),
        knowledge_import_scratch=os.path.join(sub, "scratch"),
        realtime_snapshot={"mode": "real", "model": "qwen3.8-omni-flash-realtime",
                           "voice": "Tina", "host": "dashscope.aliyuncs.com",
                           "frame_ms": 20},
        test_authorized=False)


def _app(tmp, stores):
    c = _cfg(tmp)
    ts = TokenStore(c.token_file, c.token_env)
    ts.reload()
    app = create_admin_app(admin_config=c, token_store=ts,
                           gateway_info=lambda: {"mode": "real", "ready": True},
                           stores=stores)
    app["model_endpoint_resolver"] = FAKE_IP
    app["model_probe_opener"] = _Opener(200)
    return app


async def _form(fields, filename, data, ctype="text/plain"):
    fd = aiohttp.FormData()
    for k, v in fields.items():
        fd.add_field(k, v)
    fd.add_field("file", data, filename=filename, content_type=ctype)
    return fd


async def amain():
    tmp = tempfile.mkdtemp(prefix="admin-v4-")
    stores = _stores(tmp)
    app = _app(tmp, stores)
    table = admin_route_table(stores=stores)

    async with TestClient(TestServer(app)) as cl:
        # ---- T0: route inventory / additive ------------------------------
        routes = {r.resource.canonical for r in app.router.routes()}
        check("T0 route table == mounted exactly",
              routes == {p for _, p in table}, sorted(routes - {p for _, p in table}))
        for p in ("/admin/model/providers", "/admin/model/models",
                  "/admin/model/credentials", "/admin/model/scenes",
                  "/admin/knowledge/import", "/admin/knowledge/parsers"):
            check("T0b route present %s" % p, p in routes)
        r = await cl.get("/v4/", headers=AUTH)
        check("T0c V4 UI shell served", r.status == 200 and "小智后台" in await r.text())

        # ---- T1: auth -----------------------------------------------------
        for path in ("/admin/model/providers", "/admin/model/models",
                     "/admin/model/credentials", "/admin/knowledge/import"):
            r = await cl.get(path)
            check("T1 anonymous 401 %s" % path, r.status == 401)
        a1 = await (await cl.get("/admin/model/providers")).json()
        a2 = await (await cl.get("/admin/model/providers",
                                 headers={"Authorization": "Bearer wrong"})).json()
        a1.pop("request_id", None); a2.pop("request_id", None)
        check("T1b anonymous vs invalid identical", a1 == a2, (a1, a2))

        # ---- T2: frozen Tina link detected & read-only --------------------
        r = await cl.get("/admin/model/models", headers=AUTH)
        j = await r.json()
        frozen = [m for m in j["models"] if m.get("frozen")]
        check("T2 frozen link detected", len(frozen) == 1 and frozen[0]["id"] == "mdl_frozen_tina")
        check("T2b frozen evidence realtime_safe",
              frozen and frozen[0]["evidence_level"] == "realtime_safe")
        fm = "mdl_frozen_tina"
        r = await cl.post("/admin/model/models/%s/disable" % fm, headers=AUTH, json={})
        check("T2c frozen disable refused", r.status == 400 and (await r.json())["error"] == "frozen_model")
        r = await cl.delete("/admin/model/models/%s" % fm, headers=AUTH, json={"confirm": fm})
        check("T2d frozen delete refused", r.status == 400 and (await r.json())["error"] == "frozen_model")
        r = await cl.post("/admin/model/models/%s/bind-scene" % fm, headers=AUTH,
                          json={"scene": "text_chat"})
        check("T2e frozen bind refused", r.status == 400)
        r = await cl.get("/admin/model/scenes", headers=AUTH)
        oral = [s for s in (await r.json())["scenes"] if s["id"] == "oral_realtime"][0]
        check("T2f frozen bound to oral_realtime default",
              oral["default"] == fm and fm in oral["bindings"])

        # ---- T3: SSRF endpoint policy -------------------------------------
        for bad, why in (("http://127.0.0.1:9/v1", "loopback http"),
                         ("https://10.1.2.3/v1", "private"),
                         ("https://169.254.169.254/latest", "metadata ip"),
                         ("https://metadata.google.internal/v1", "metadata host"),
                         ("https://user:pw@api.example.com/v1", "userinfo")):
            r = await cl.post("/admin/model/providers", headers=AUTH,
                              json={"name": "bad-" + why, "protocol": "openai_compatible",
                                    "base_url": bad})
            body = await r.json()
            check("T3 SSRF rejected (%s)" % why,
                  r.status == 400 and body.get("error") == "endpoint_not_allowed", body)

        # ---- T3b: base-URL 契约（probe 拼接规则；禁止重复/端点路径） -------
        # probe 规则：base 以 /v1 结尾 -> +/models；否则 +/v1/models。
        # 因此下列输入会在拼接后产生重复路径，必须在写入前拒绝。
        for bad, why in (("https://api.example.com/v1/v1", "duplicated /v1"),
                         ("https://api.example.com/v1/models", "endpoint /v1/models"),
                         ("https://api.example.com/models", "endpoint /models")):
            r = await cl.post("/admin/model/providers", headers=AUTH,
                              json={"name": "bad2-" + why, "protocol": "openai_compatible",
                                    "base_url": bad})
            body = await r.json()
            check("T3b base-url contract rejected (%s)" % why,
                  r.status == 400 and body.get("error") == "endpoint_not_allowed", body)
        r = await cl.post("/admin/model/providers", headers=AUTH, json={
            "name": "规范化地址", "protocol": "openai_compatible",
            "base_url": "https://api.example.com/v1/"})
        j = await r.json()
        check("T3b2 trailing slash normalized on store",
              r.status == 200 and j["provider"]["base_url"] == "https://api.example.com/v1", j)
        r = await cl.post("/admin/model/providers", headers=AUTH, json={
            "name": "规范化地址2", "protocol": "openai_compatible",
            "base_url": "https://api.example.com"})
        st = (await r.json())["provider"]["base_url"]
        check("T3b3 stored base + probe contract = exactly one /v1",
              st == "https://api.example.com"
              and _models_url(st) == "https://api.example.com/v1/models")

        # ---- T4: provider CRUD + read-back --------------------------------
        r = await cl.post("/admin/model/providers", headers=AUTH, json={
            "name": "星河 AI", "protocol": "openai_compatible",
            "base_url": "https://api.galaxy.internal/v1",
            "capabilities": ["text_llm", "streaming"]})
        j = await r.json()
        check("T4 provider create + readback", r.status == 200 and j.get("readback_ok") is True)
        pid = j["provider"]["id"]
        r = await cl.post("/admin/model/providers", headers=AUTH, json={
            "name": "星河 AI", "protocol": "openai_compatible",
            "base_url": "https://api.galaxy.internal/v1"})
        check("T4b duplicate provider 409", r.status == 409)
        r = await cl.put("/admin/model/providers/" + pid, headers=AUTH,
                         json={"name": "星河 AI v2"})
        check("T4c provider update", r.status == 200 and (await r.json())["provider"]["name"] == "星河 AI v2")
        r = await cl.get("/admin/model/providers", headers=AUTH)
        check("T4d provider listed", any(p["id"] == pid for p in (await r.json())["providers"]))

        # ---- T5: model CRUD + enable gate ---------------------------------
        r = await cl.post("/admin/model/models", headers=AUTH, json={
            "provider_id": pid, "model_key": "galaxy-model-x1",
            "capabilities": ["text_llm", "streaming"]})
        j = await r.json()
        check("T5 model create", r.status == 200 and j.get("readback_ok"))
        mid = j["model"]["id"]
        check("T5b new model disabled", j["model"]["enabled"] is False)

        r = await cl.post("/admin/model/models/%s/enable" % mid, headers=AUTH, json={})
        check("T5c enable without evidence -> evidence_missing",
              r.status == 400 and (await r.json())["error"] == "evidence_missing")

        # simulate a REAL test run (server-side evidence write only)
        stores.model_registry.set_evidence(mid, "adapter_present", source="simulated_ui")
        r = await cl.post("/admin/model/models/%s/enable" % mid, headers=AUTH, json={})
        check("T5d adapter_present is not enough",
              r.status == 400 and (await r.json())["error"] == "evidence_missing")

        stores.model_registry.set_evidence(mid, "verified", source="real_test")
        r = await cl.post("/admin/model/models/%s/enable" % mid, headers=AUTH, json={})
        check("T5e verified but no credential -> credential_missing",
              r.status == 400 and (await r.json())["error"] == "credential_missing")

        r = await cl.post("/admin/model/credentials", headers=AUTH,
                          json={"provider_id": pid, "secret": SECRET})
        j = await r.json()
        check("T5f credential written", r.status == 200 and j["credential"]["configured"] is True)
        check("T5g no plaintext in credential response", SECRET not in json.dumps(j))
        check("T5h credential_ref shape",
              j["credential"]["credential_ref"].startswith("cred://"))

        r = await cl.post("/admin/model/models/%s/enable" % mid, headers=AUTH, json={})
        check("T5i enable passes gate", r.status == 200 and (await r.json())["model"]["enabled"] is True)

        # scene gate: oral_realtime needs realtime_safe
        r = await cl.post("/admin/model/models/%s/bind-scene" % mid, headers=AUTH,
                          json={"scene": "oral_realtime"})
        check("T5j oral_realtime refused without realtime_safe",
              r.status == 400 and (await r.json())["error"] == "capability_mismatch")
        r = await cl.post("/admin/model/models/%s/bind-scene" % mid, headers=AUTH,
                          json={"scene": "text_chat"})
        check("T5k text_chat bind ok", r.status == 200 and (await r.json())["readback_ok"])
        r = await cl.post("/admin/model/models/%s/set-default" % mid, headers=AUTH,
                          json={"scene": "text_chat"})
        check("T5l set-default needs confirm",
              r.status == 400 and (await r.json())["error"] == "confirm_required")
        r = await cl.post("/admin/model/models/%s/set-default" % mid, headers=AUTH,
                          json={"scene": "text_chat", "confirm": True})
        check("T5m set-default ok", r.status == 200 and (await r.json())["default"]["scene"] == "text_chat")

        # unknown protocol can never be enabled
        r = await cl.post("/admin/model/providers", headers=AUTH, json={
            "name": "未知协议", "protocol": "custom_unknown",
            "base_url": "https://u.internal/v1"})
        pid2 = (await r.json())["provider"]["id"]
        r = await cl.post("/admin/model/models", headers=AUTH,
                          json={"provider_id": pid2, "model_key": "unknown-1"})
        mid2 = (await r.json())["model"]["id"]
        stores.model_registry.set_evidence(mid2, "verified", source="real_test")
        r = await cl.post("/admin/model/models/%s/enable" % mid2, headers=AUTH, json={})
        check("T5n unregistered adapter -> capability_mismatch",
              r.status == 400 and (await r.json())["error"] == "capability_mismatch")

        # ---- T6: test endpoint levels -------------------------------------
        r = await cl.post("/admin/model/models/%s/test" % mid, headers=AUTH,
                          json={"mode": "protocol"})
        j = await r.json()
        check("T6 protocol test offline & writes nothing",
              r.status == 200 and j["result"]["network"] is False and j["wrote_evidence"] is False)
        r = await cl.post("/admin/model/models/%s/test" % mid, headers=AUTH,
                          json={"mode": "verified", "confirm_verified": True})
        check("T6b verified test not authorized -> 403",
              r.status == 403 and (await r.json())["error"] == "test_not_authorized")
        app["model_test_authorized"] = True
        r = await cl.post("/admin/model/models/%s/test" % mid, headers=AUTH,
                          json={"mode": "verified", "confirm_verified": True})
        j = await r.json()
        check("T6c authorized verified test writes evidence",
              r.status == 200 and j["wrote_evidence"] is True and j["evidence_level"] == "verified", j)
        app["model_test_authorized"] = False
        r = await cl.post("/admin/model/models/%s/test" % fm, headers=AUTH,
                          json={"mode": "protocol"})
        check("T6d frozen model test refused",
              r.status == 400 and (await r.json())["error"] == "frozen_model")

        # ---- T6e/T6f: real loopback verified probe (no fake opener) --------
        # The mock and the admin app share ONE event loop, exactly like the
        # acceptance environment: a probe blocking the loop would deadlock
        # until timeout.  This is the regression guard for off-loop execution.
        async def _mock_models(request):
            return web.json_response({"object": "list",
                                      "data": [{"id": "mock-gpt-local"}]})
        mock_app = web.Application()
        mock_app.router.add_get("/v1/models", _mock_models)
        mock_srv = TestServer(mock_app)
        await mock_srv.start_server()
        app["model_probe_opener"] = None                    # real urllib opener
        app["model_endpoint_resolver"] = lambda host: ["127.0.0.1"]
        try:
            r = await cl.post("/admin/model/providers", headers=AUTH, json={
                "name": "loopback-mock", "protocol": "openai_compatible",
                "base_url": "http://127.0.0.1:%d/v1" % mock_srv.port,
                "allow_local": True, "capabilities": ["text_llm"]})
            pid3 = (await r.json())["provider"]["id"]
            await cl.post("/admin/model/credentials", headers=AUTH,
                          json={"provider_id": pid3, "secret": "sk-loopback-1"})
            r = await cl.post("/admin/model/models", headers=AUTH, json={
                "provider_id": pid3, "model_key": "mock-gpt-local",
                "capabilities": ["text_llm"]})
            mid3 = (await r.json())["model"]["id"]
            app["model_test_authorized"] = True
            r = await cl.post("/admin/model/models/%s/test" % mid3, headers=AUTH,
                              json={"mode": "verified", "confirm_verified": True})
            j = await r.json()
            check("T6e verified loopback probe succeeds (no loop deadlock)",
                  r.status == 200 and j["wrote_evidence"] is True
                  and j["evidence_level"] == "verified", j)

            # host-only base (provider-template convention) joins the same path
            r = await cl.post("/admin/model/providers", headers=AUTH, json={
                "name": "loopback-host", "protocol": "openai_compatible",
                "base_url": "http://127.0.0.1:%d" % mock_srv.port,
                "allow_local": True, "capabilities": ["text_llm"]})
            pid4 = (await r.json())["provider"]["id"]
            await cl.post("/admin/model/credentials", headers=AUTH,
                          json={"provider_id": pid4, "secret": "sk-loopback-2"})
            r = await cl.post("/admin/model/models", headers=AUTH, json={
                "provider_id": pid4, "model_key": "mock-gpt-local",
                "capabilities": ["text_llm"]})
            mid4 = (await r.json())["model"]["id"]
            r = await cl.post("/admin/model/models/%s/test" % mid4, headers=AUTH,
                              json={"mode": "verified", "confirm_verified": True})
            j = await r.json()
            check("T6f host-only base_url joins …/v1/models",
                  r.status == 200 and j["wrote_evidence"] is True, j)
        finally:
            app["model_test_authorized"] = False
            app["model_probe_opener"] = _Opener(200)
            app["model_endpoint_resolver"] = FAKE_IP
            await mock_srv.close()

        # ---- T6g..T6o: explicit realtime_safe promotion (contract §2.3) ----
        # M-C closure: the promotion path must be reachable in the admin face,
        # yet fail-closed: confirm + SEPARATE product-owner authorization, and
        # the stored evidence must already be ``verified``.
        r = await cl.post("/admin/model/models", headers=AUTH, json={
            "provider_id": pid3, "model_key": "mock-gpt-realtime",
            "capabilities": ["realtime_audio", "streaming", "barge_in"]})
        mid5 = (await r.json())["model"]["id"]
        r = await cl.post("/admin/model/models/%s/promote-realtime" % mid5,
                          headers=AUTH, json={})
        check("T6g promote requires confirm",
              r.status == 400 and (await r.json())["error"] == "confirm_required")
        r = await cl.post("/admin/model/models/%s/promote-realtime" % mid5,
                          headers=AUTH, json={"confirm": True})
        check("T6h promote unauthorized -> 403 promote_not_authorized",
              r.status == 403 and (await r.json())["error"] == "promote_not_authorized")
        app["model_promote_authorized"] = True
        r = await cl.post("/admin/model/models/%s/promote-realtime" % mid5,
                          headers=AUTH, json={"confirm": True})
        check("T6i promote before verified evidence -> evidence_missing",
              r.status == 400 and (await r.json())["error"] == "evidence_missing")
        app["model_test_authorized"] = True
        r = await cl.post("/admin/model/models/%s/test" % mid5, headers=AUTH,
                          json={"mode": "verified", "confirm_verified": True})
        app["model_test_authorized"] = False
        j = await r.json()
        check("T6j realtime model reaches verified via real test",
              r.status == 200 and j.get("evidence_level") == "verified", j)
        r = await cl.post("/admin/model/models/%s/promote-realtime" % mid5,
                          headers=AUTH, json={"confirm": True})
        j = await r.json()
        check("T6k authorized promote -> realtime_safe + readback",
              r.status == 200 and j.get("evidence_level") == "realtime_safe"
              and j.get("readback_ok") is True, j)
        check("T6k2 promote durable on disk (fresh instance read-back)",
              ModelRegistry(stores.model_registry.path).load().evidence_level(mid5)
              == "realtime_safe")
        app["model_test_authorized"] = True
        r = await cl.post("/admin/model/models/%s/test" % mid5, headers=AUTH,
                          json={"mode": "verified", "confirm_verified": True})
        app["model_test_authorized"] = False
        j = await r.json()
        check("T6k3 re-test does not demote realtime_safe",
              r.status == 200 and j.get("evidence_level") == "realtime_safe", j)
        r = await cl.get("/admin/model/models/%s" % mid5, headers=AUTH)
        check("T6k4 stored level still realtime_safe after re-test",
              (await r.json())["model"]["evidence_level"] == "realtime_safe")
        r = await cl.post("/admin/model/models/%s/bind-scene" % mid5, headers=AUTH,
                          json={"scene": "oral_realtime"})
        j = await r.json()
        check("T6l promoted model binds oral_realtime (M-C closure)",
              r.status == 200 and j.get("readback_ok") is True, j)
        r = await cl.get("/admin/model/scenes", headers=AUTH)
        oral2 = [s for s in (await r.json())["scenes"] if s["id"] == "oral_realtime"][0]
        check("T6l2 frozen Tina binding + default retained (never replaced)",
              fm in oral2["bindings"] and oral2["default"] == fm, oral2)
        r = await cl.post("/admin/model/models/%s/promote-realtime" % fm, headers=AUTH,
                          json={"confirm": True})
        check("T6m frozen model promote refused",
              r.status == 400 and (await r.json())["error"] == "frozen_model")
        check("T6n promote audited",
              "model_promote_realtime" in [a["action"] for a in stores.audit.recent(50)])
        app["model_promote_authorized"] = False
        r = await cl.get("/admin/health", headers=AUTH)
        j = await r.json()
        check("T6o health exposes V4 store bundle (wiring visibility)",
              isinstance(j.get("stores"), dict)
              and j["stores"].get("model_registry") is True
              and j["stores"].get("frozen_link_detected") is True, j.get("stores"))

        # ---- T7: credentials rotate/delete --------------------------------
        r = await cl.get("/admin/model/credentials?provider_id=%s" % pid, headers=AUTH)
        creds = (await r.json())["credentials"]
        cid = creds[0]["id"]
        r = await cl.post("/admin/model/credentials/%s/rotate" % cid, headers=AUTH,
                          json={"secret": "sk-rotated-222"})
        check("T7 rotate needs confirm", r.status == 400)
        r = await cl.post("/admin/model/credentials/%s/rotate" % cid, headers=AUTH,
                          json={"secret": "sk-rotated-222", "confirm": True})
        j = await r.json()
        check("T7b rotate keeps versions",
              r.status == 200 and j["credential"]["current_v"] == 2 and 1 in j["credential"]["versions"])
        check("T7c no plaintext after rotate", "sk-rotated-222" not in json.dumps(j))
        r = await cl.delete("/admin/model/credentials/%s" % cid, headers=AUTH,
                            json={"confirm": True})
        check("T7d delete refused while model enabled -> credential_in_use",
              r.status == 409 and (await r.json())["error"] == "credential_in_use")

        # ---- T8: knowledge import pipeline --------------------------------
        r = await cl.post("/admin/knowledge/dataset/create", headers=AUTH, json={"name": "教材A"})
        dsid = (await r.json())["dataset"]["id"]
        r = await cl.get("/admin/knowledge/parsers", headers=AUTH)
        parsers = (await r.json())["parsers"]
        check("T8 parsers all P0 present", len(parsers) == 6)   # five P0 + .epub (D2)

        form = await _form({"dataset_id": dsid}, "lesson1.txt", b"Chapter 1\n\nHello world.\n")
        r = await cl.post("/admin/knowledge/import", headers=AUTH, data=form)
        j = await r.json()
        check("T8b upload -> preview_ready (NOT applied)",
              r.status == 200 and j["status"] == "preview_ready" and j.get("doc_id") is None, j)
        jid = j["job_id"]
        docs = await (await cl.get("/admin/knowledge/dataset/%s/documents" % dsid, headers=AUTH)).json()
        check("T8c upload did NOT write the store", docs["count"] == 0, docs)

        r = await cl.post("/admin/knowledge/import/%s/commit" % jid, headers=AUTH, json={})
        check("T8d commit needs confirm", r.status == 400 and (await r.json())["error"] == "confirm_required")
        r = await cl.post("/admin/knowledge/import/%s/commit" % jid, headers=AUTH, json={"confirm": True})
        j = await r.json()
        check("T8e commit -> applied + readback", r.status == 200 and j["readback_ok"] is True
              and j["job"]["status"] == "applied", j)
        docs = await (await cl.get("/admin/knowledge/dataset/%s/documents" % dsid, headers=AUTH)).json()
        check("T8f document durable", docs["count"] == 1)

        r = await cl.post("/admin/knowledge/import/%s/commit" % jid, headers=AUTH, json={"confirm": True})
        check("T8g re-commit applied -> job_not_committable",
              r.status == 409 and (await r.json())["error"] == "job_not_committable")
        r = await cl.post("/admin/knowledge/import/%s/cancel" % jid, headers=AUTH, json={"confirm": True})
        check("T8h cancel applied -> job_not_cancellable",
              r.status == 409 and (await r.json())["error"] == "job_not_cancellable")
        r = await cl.post("/admin/knowledge/import/%s/retry" % jid, headers=AUTH, json={"confirm": True})
        check("T8i retry non-failed -> job_not_retryable",
              r.status == 409 and (await r.json())["error"] == "job_not_retryable")

        # duplicate content
        form = await _form({"dataset_id": dsid}, "lesson1-copy.txt", b"Chapter 1\n\nHello world.\n")
        r = await cl.post("/admin/knowledge/import", headers=AUTH, data=form)
        j2 = await r.json()
        r = await cl.post("/admin/knowledge/import/%s/commit" % j2["job_id"], headers=AUTH,
                          json={"confirm": True})
        body = await r.json()
        check("T8j duplicate_content on commit",
              r.status == 409 and body["error"] == "duplicate_content" and body.get("existing_doc_id"))
        st = await (await cl.get("/admin/knowledge/import/%s" % j2["job_id"], headers=AUTH)).json()
        check("T8k duplicate keeps preview_ready (not applied)", st["job"]["status"] == "preview_ready")
        await cl.post("/admin/knowledge/import/%s/cancel" % j2["job_id"], headers=AUTH, json={"confirm": True})

        # unsupported format
        form = await _form({"dataset_id": dsid}, "old.doc", b"\xd0\xcf\x11\xe0legacy")
        r = await cl.post("/admin/knowledge/import", headers=AUTH, data=form)
        check("T8l unsupported format 400",
              r.status == 400 and (await r.json())["error"] == "unsupported_content_type")

        # unknown dataset validated before anything else
        form = await _form({"dataset_id": "ds_does_not_exist"}, "x.txt", b"hi")
        r = await cl.post("/admin/knowledge/import", headers=AUTH, data=form)
        check("T8m unknown dataset -> 404 not_found", r.status == 404)

        # upload cap (patched small to stay fast; contract: refuse, never truncate)
        old_cap = api_import_mod.MAX_UPLOAD
        api_import_mod.MAX_UPLOAD = 4096
        try:
            form = await _form({"dataset_id": dsid}, "big.txt", b"x" * 8192)
            r = await cl.post("/admin/knowledge/import", headers=AUTH, data=form)
            check("T8n oversize upload -> 413 body_too_large",
                  r.status == 413 and (await r.json())["error"] == "body_too_large")
        finally:
            api_import_mod.MAX_UPLOAD = old_cap

        # expired preview
        old_ttl = stores.knowledge_imports.ttl
        stores.knowledge_imports.ttl = -1
        try:
            form = await _form({"dataset_id": dsid}, "expire.txt", b"will expire")
            r = await cl.post("/admin/knowledge/import", headers=AUTH, data=form)
            ejid = (await r.json())["job_id"]
            r = await cl.post("/admin/knowledge/import/%s/commit" % ejid, headers=AUTH,
                              json={"confirm": True})
            check("T8o expired preview -> 410 job_expired",
                  r.status == 410 and (await r.json())["error"] == "job_expired")
        finally:
            stores.knowledge_imports.ttl = old_ttl

        # idempotency key
        form = await _form({"dataset_id": dsid, "title": "idem"}, "idem.txt", b"idempotent body")
        h = dict(AUTH); h["Idempotency-Key"] = "k-1"
        r1 = await cl.post("/admin/knowledge/import", headers=h, data=form)
        j1 = await r1.json()
        form = await _form({"dataset_id": dsid, "title": "idem"}, "idem.txt", b"idempotent body")
        r2 = await cl.post("/admin/knowledge/import", headers=h, data=form)
        j2 = await r2.json()
        check("T8p idempotency key returns same job", j1["job_id"] == j2["job_id"])

        # import listing + dataset imports
        r = await cl.get("/admin/knowledge/import?limit=50", headers=AUTH)
        check("T8q import list", r.status == 200 and (await r.json())["count"] >= 1)
        r = await cl.get("/admin/knowledge/dataset/%s/imports" % dsid, headers=AUTH)
        check("T8r dataset imports", r.status == 200 and (await r.json())["count"] >= 1)

        # retrieval with source
        r = await cl.post("/admin/knowledge/search", headers=AUTH, json={"query": "Hello"})
        j = await r.json()
        check("T8s search returns source", j["count"] >= 1 and (j["results"][0]["source"] or {}).get("uri"))

        # ---- T9: store maintenance ---------------------------------------
        r = await cl.post("/admin/knowledge/migrate", headers=AUTH, json={})
        check("T9 migrate needs confirm", r.status == 400)
        r = await cl.post("/admin/knowledge/migrate", headers=AUTH, json={"confirm": True})
        j = await r.json()
        check("T9b migrate with backup + readback",
              r.status == 200 and j["migration"]["knowledge"]["readback_ok"] is True
              and j["migration"]["knowledge"].get("backup"), j)
        backup = j["migration"]["knowledge"]["backup"]
        r = await cl.post("/admin/knowledge/rollback", headers=AUTH,
                          json={"backup_id": backup, "confirm": True})
        check("T9c rollback readback", r.status == 200 and (await r.json())["readback_ok"] is True, await r.text())

        # ---- T10: secrets never leak --------------------------------------
        collected = []
        for path in ("/admin/model/providers", "/admin/model/models",
                     "/admin/model/credentials", "/admin/model/scenes",
                     "/admin/knowledge/import", "/admin/audit?limit=200",
                     "/admin/model/credentials/%s" % cid):
            rr = await cl.get(path, headers=AUTH)
            collected.append(await rr.text())
        blob = "\n".join(collected)
        check("T10 no secret plaintext anywhere",
              SECRET not in blob and "sk-rotated-222" not in blob)
        check("T10b no token in bodies", FIX_TOKEN not in blob)

        # ---- T11: write read-back honesty ---------------------------------
        r = await cl.post("/admin/model/models/%s/disable" % mid, headers=AUTH, json={})
        check("T11 disable model", r.status == 200 and (await r.json())["model"]["enabled"] is False)

    # ---- T12: store unavailable refuses reads AND writes (contract §4.2) --
    tmp2 = tempfile.mkdtemp(prefix="admin-v4-unavail-")
    sub = os.path.join(tmp2, "v4u")
    os.makedirs(sub, exist_ok=True)
    kpath = os.path.join(sub, "knowledge.json")
    with open(kpath, "w") as fh:
        json.dump({"version": 99, "datasets": {}, "documents": {}, "chunks": {}}, fh)
    stores2 = _stores(tmp2, prefix="v4u")
    app2 = _app(tmp2, stores2)
    async with TestClient(TestServer(app2)) as cl2:
        r = await cl2.get("/admin/knowledge/datasets", headers=AUTH)
        body = await r.json()
        check("T12 version-ahead read -> 503 store_unavailable",
              r.status == 503 and body["error"] == "store_unavailable", body)
        r = await cl2.post("/admin/knowledge/dataset/create", headers=AUTH, json={"name": "x"})
        check("T12b version-ahead write -> 503 store_unavailable", r.status == 503)
        # the original file must be intact (never silently wiped)
        with open(kpath) as fh:
            raw = json.load(fh)
        check("T12c original file untouched", raw.get("version") == 99, raw)

    # ---- T13: existing-deployment upgrade & fresh-install compatibility ----
    import hashlib
    from modules.knowledge.store import KnowledgeStore          # noqa: E402
    tmp3 = tempfile.mkdtemp(prefix="admin-v4-compat-")
    sub3 = os.path.join(tmp3, "compat")
    os.makedirs(sub3, exist_ok=True)
    # pre-existing (older deployment) knowledge store with real content
    kpath3 = os.path.join(sub3, "knowledge.json")
    k0 = KnowledgeStore(kpath3).load()
    ds0 = k0.create_dataset("既有课件库")
    k0.add_document(ds0["id"], "旧版课件", "legacy lesson about travel phrases")
    hash_before = hashlib.sha256(Path(kpath3).read_bytes()).hexdigest()
    stores3 = _stores(tmp3, prefix="compat")
    app3 = _app(tmp3, stores3)
    async with TestClient(TestServer(app3)) as cl3:
        r = await cl3.get("/admin/model/models", headers=AUTH)
        j = await r.json()
        frozen_n = len([m for m in j["models"] if m.get("frozen")])
        user_n = len([m for m in j["models"] if not m.get("frozen")])
        check("T13 upgrade keeps frozen Tina detected (read-only)",
              frozen_n == 1 and frozen_n == len(j["models"]),
              [m.get("name") for m in j["models"]])
        check("T13b empty 'my models' with frozen present (no-loss illusion avoided)",
              user_n == 0 and frozen_n == 1)
        r = await cl3.get("/admin/knowledge/datasets", headers=AUTH)
        j = await r.json()
        check("T13c pre-existing knowledge data kept on upgrade",
              any(d.get("name") == "既有课件库" for d in j["datasets"]),
              j.get("datasets"))
        r = await cl3.post("/admin/knowledge/search", headers=AUTH,
                           json={"query": "travel"})
        check("T13d pre-existing content searchable", r.status == 200
              and len((await r.json()).get("results") or []) >= 1)
        check("T13e upgrade boot did not rewrite pre-existing knowledge file",
              hashlib.sha256(Path(kpath3).read_bytes()).hexdigest() == hash_before)

    # fresh install: no files exist at all -> every V4 surface answers cleanly
    sub4 = os.path.join(tmp3, "fresh")
    os.makedirs(sub4, exist_ok=True)
    stores4 = _stores(tmp3, prefix="fresh")
    app4 = _app(tmp3, stores4)
    async with TestClient(TestServer(app4)) as cl4:
        r = await cl4.get("/admin/knowledge/datasets", headers=AUTH)
        j = await r.json()
        check("T13f fresh install: knowledge empty (not an error)",
              r.status == 200 and j.get("datasets") == [])
        r = await cl4.get("/admin/knowledge/parsers", headers=AUTH)
        check("T13g fresh install: parsers reported", r.status == 200)
        r = await cl4.get("/admin/model/scenes", headers=AUTH)
        check("T13h fresh install: scenes present", r.status == 200
              and len((await r.json()).get("scenes") or []) >= 1)
        r = await cl4.post("/admin/knowledge/dataset/create", headers=AUTH,
                           json={"name": "全新资料集"})
        check("T13i fresh install: first write works", r.status == 200
              and (await r.json()).get("readback_ok") is True)

    total = len(RESULTS)
    failed = [n for n, ok, _ in RESULTS if not ok]
    print("\n==== SUMMARY ====")
    print("total=%d pass=%d fail=%d" % (total, total - len(failed), len(failed)))
    if failed:
        for n in failed:
            print("FAILED:", n)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
