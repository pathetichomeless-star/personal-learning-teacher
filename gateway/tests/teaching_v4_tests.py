"""TEACHING_V4_TESTS — P2-A real text-teaching linkage suite.

Runs standalone:  python tests/teaching_v4_tests.py   (from gateway/, venv)

Everything here is a **real backend linkage** test: the admin app is exercised
over HTTP (aiohttp TestClient) and the teaching turn performs a **real HTTP call**
to a reproducible local mock model upstream (a second aiohttp server).  No paid
provider is contacted and nothing is fabricated: the reply text asserted in the
tests is exactly what the local upstream returned.

Coverage (the ten required checks of the P2-A order):

  T1 create a teacher, then start a teaching session
  T2 different teachers use their own model and teaching instruction
  T3 the correct linked material is retrieved and its source is returned
  T4 starting is refused when no usable text model is configured
  T5 records of different teachers / different students never mix
  T6 sessions (classroom records) survive a restart
  T7 password-login surface not regressed
  T8 the frozen Tina configuration is unchanged
"""

import asyncio
import json
import os
import socket
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from aiohttp import web                                        # noqa: E402
from aiohttp.test_utils import TestClient, TestServer          # noqa: E402

from app.admin.app import admin_route_table, create_admin_app  # noqa: E402
from app.admin.auth import TokenStore                          # noqa: E402
from app.admin.config import load_admin_config                 # noqa: E402
from app.admin.password_auth import PasswordStore, SessionStore  # noqa: E402
from app.admin.stores import AdminStores                       # noqa: E402
from modules.memory.store import MemoryStore                   # noqa: E402
from modules.teaching.store import TeachingSessionStore        # noqa: E402

FIX_TOKEN = "TEACHING_V4_BEARER_TOKEN_DO_NOT_LEAK_13579"
AUTH = {"Authorization": "Bearer " + FIX_TOKEN}
SECRET_ONE = "sk-teaching-secret-one-never-leak"
SECRET_TWO = "sk-teaching-secret-two-never-leak"
RESULTS = []

FAKE_IP = lambda host: ["93.184.216.34"]                        # noqa: E731


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % (detail,)) if (detail and not cond) else ""))


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---------------------------------------------------------------------------
# reproducible local model upstream (a real HTTP server, deterministic)
# ---------------------------------------------------------------------------

class MockUpstream:
    """A deterministic OpenAI-compatible upstream.  It really answers HTTP; its
    reply carries ``marker`` so a test can prove WHICH upstream was called."""

    def __init__(self, marker):
        self.marker = marker
        self.port = _free_port()
        self.seen = []          # recorded (system, last_user)
        self._runner = None

    @property
    def base_url(self):
        return "http://127.0.0.1:%d" % self.port

    async def start(self):
        async def models(request):
            return web.json_response({"object": "list", "data": [
                {"id": "mock", "object": "model", "owned_by": "test"}]})

        async def chat(request):
            try:
                body = await request.json()
            except Exception:  # noqa: BLE001
                body = {}
            msgs = body.get("messages") or []
            system = ""
            last_user = ""
            for m in msgs:
                if (m or {}).get("role") == "system":
                    system += str((m or {}).get("content") or "")
                if (m or {}).get("role") == "user":
                    last_user = str((m or {}).get("content") or "")
            self.seen.append((system, last_user))
            reply = ("[%s] 收到问题：%s ｜系统提示长度=%d"
                     % (self.marker, last_user[:60], len(system)))
            return web.json_response({
                "object": "chat.completion", "model": str(body.get("model") or "mock"),
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": reply}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

        app = web.Application()
        app.router.add_get("/v1/models", models)
        app.router.add_post("/v1/chat/completions", chat)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, "127.0.0.1", self.port).start()
        return self

    async def stop(self):
        if self._runner is not None:
            await self._runner.cleanup()


# ---------------------------------------------------------------------------
# admin app harness
# ---------------------------------------------------------------------------

def _cfg(tmp):
    p = os.path.join(tmp, "tok")
    with open(p, "w") as fh:
        fh.write(FIX_TOKEN + "\n")
    os.chmod(p, 0o600)
    return load_admin_config(env={
        "ADMIN_ENABLED": "1", "ADMIN_BIND": "127.0.0.1", "ADMIN_PORT": "18161",
        "ADMIN_API_TOKEN_FILE": p, "ADMIN_API_TOKEN": "",
        "ADMIN_USERS_FILE": os.path.join(tmp, "users.json"),
        "ADMIN_SESSIONS_FILE": os.path.join(tmp, "sessions.json")})


def _stores(tmp, sub="stores"):
    d = os.path.join(tmp, sub)
    os.makedirs(d, exist_ok=True)
    return AdminStores(
        policy_file=os.path.join(d, "policy.json"),
        memory_file=os.path.join(d, "memory.json"),
        knowledge_file=os.path.join(d, "knowledge.json"),
        workbench_url="",
        model_registry_file=os.path.join(d, "registry.json"),
        model_credentials_file=os.path.join(d, "creds.json"),
        model_credentials_key_file=os.path.join(d, "creds.key"),
        knowledge_import_file=os.path.join(d, "imports.json"),
        knowledge_import_scratch=os.path.join(d, "scratch"),
        teacher_file=os.path.join(d, "teachers.json"),
        teaching_file=os.path.join(d, "teaching.json"),
        realtime_snapshot={"mode": "real", "model": "qwen3.8-omni-flash-realtime",
                           "voice": "Tina", "host": "dashscope.aliyuncs.com",
                           "frame_ms": 20},
        test_authorized=False)


def _app(tmp, stores):
    c = _cfg(tmp)
    ts = TokenStore(c.token_file, c.token_env)
    ts.reload()
    app = create_admin_app(
        admin_config=c, token_store=ts,
        gateway_info=lambda: {"mode": "real", "ready": True},
        stores=stores,
        password_store=PasswordStore(c.users_file),
        session_store=SessionStore(c.sessions_file))
    app["model_endpoint_resolver"] = FAKE_IP
    return app


def _seed_text_model(stores, *, marker_url, model_key, secret):
    """Register a loopback openai_compatible provider + a verified, enabled model."""
    reg = stores.model_registry
    prov = reg.create_provider(name="本地测试服务-%s" % model_key,
                               protocol="openai_compatible", base_url=marker_url,
                               allow_local=True,
                               capabilities=["text_llm", "streaming"],
                               resolver=FAKE_IP)
    m = reg.create_model(provider_id=prov["id"], model_key=model_key,
                         capabilities=["text_llm", "streaming"])
    reg.set_evidence(m["id"], "verified", source="test")
    reg.set_enabled(m["id"], True)
    stores.model_credentials.put(prov["id"], secret)
    return prov, m


async def amain():
    tmp = tempfile.mkdtemp(prefix="teaching-v4-")
    up_one = await MockUpstream("UPSTREAM-ONE").start()
    up_two = await MockUpstream("UPSTREAM-TWO").start()
    try:
        await _run(tmp, up_one, up_two)
    finally:
        await up_one.stop()
        await up_two.stop()


async def _run(tmp, up_one, up_two):
    stores = _stores(tmp)
    app = _app(tmp, stores)
    table = admin_route_table(stores=stores)
    teaching_routes = {p for m, p in table if "/admin/teaching/" in p}

    mounted = {r.resource.canonical for r in app.router.routes()}
    check("T0 all teaching routes mounted",
          all(p in mounted for p in teaching_routes), str(sorted(teaching_routes)))

    prov_a, model_a = _seed_text_model(stores, marker_url=up_one.base_url,
                                       model_key="mock-model-one", secret=SECRET_ONE)
    prov_b, model_b = _seed_text_model(stores, marker_url=up_two.base_url,
                                       model_key="mock-model-two", secret=SECRET_TWO)

    kb = stores.knowledge
    ds_a = kb.create_dataset("英语课件库A")
    kb.add_document(ds_a["id"], "Lesson A",
                    "uniquetokenA 是本节课的重点词汇，表示问候。" * 5)
    ds_b = kb.create_dataset("数学课件库B")
    kb.add_document(ds_b["id"], "Lesson B",
                    "uniquetokenB 是分数加减的例题。" * 5)

    async with TestClient(TestServer(app)) as cl:
        async def get(p):
            r = await cl.get(p, headers=AUTH)
            return r.status, await r.json()

        async def post(p, body):
            r = await cl.post(p, headers=AUTH, json=body)
            return r.status, await r.json()

        async def put(p, body):
            r = await cl.put(p, headers=AUTH, json=body)
            return r.status, await r.json()

        # ---- T-seed -------------------------------------------------------
        st, ov = await get("/admin/teaching/overview")
        check("T0b overview available and honest about teachers",
              st == 200 and any(t["teacher_id"] == "tina" and t["can_teach_text"] is False
                                for t in ov["teachers"]), str(ov)[:200])

        # ---- T1 create teacher then start a session -----------------------
        st, ca = await post("/admin/teacher/teachers", {
            "name": "英语李老师", "subject": "english", "language": "zh",
            "teaching_style": "strict", "voice": {"mode": "text"},
            "model": {"text_model_id": model_a["id"]},
            "knowledge": {"dataset_ids": [ds_a["id"]]}})
        tid_a = ca["teacher"]["teacher_id"]
        check("T1a teacher created with text model + material",
              st == 200 and ca["teacher"]["availability"]["text"]["usable"] is True,
              str(ca.get("teacher", {}).get("availability")))

        st, s1 = await post("/admin/teaching/sessions",
                            {"teacher_id": tid_a, "student_id": "stu_1"})
        sess = s1.get("session") or {}
        check("T1b session started with server-resolved teacher config",
              st == 200 and sess.get("teacher_id") == tid_a
              and sess.get("student_id") == "stu_1"
              and sess.get("model_id") == model_a["id"]
              and sess.get("model_key") == "mock-model-one"
              and sess.get("knowledge_dataset_ids") == [ds_a["id"]]
              and sess.get("status") == "active", str(s1)[:260])
        check("T1c local test model labelled honestly",
              sess.get("model_is_local") is True
              and "student_id" in (s1.get("scope_note") or ""), str(s1.get("scope_note")))

        # ---- T3 material retrieval + source return (teacher A) ------------
        st, m1 = await post("/admin/teaching/sessions/%s/messages" % sess["session_id"],
                            {"text": "uniquetokenA 是什么意思？"})
        check("T3a real model call returns the upstream reply (not fabricated)",
              st == 200 and "UPSTREAM-ONE" in (m1.get("reply") or ""), str(m1)[:200])
        srcs = m1.get("sources") or []
        check("T3b retrieved material source returned to the classroom",
              srcs and all(s["dataset_id"] == ds_a["id"] for s in srcs)
              and any(s["document_title"] == "Lesson A" for s in srcs), str(srcs))
        check("T3c the retrieved material was really fed to the model",
              "Lesson A" in (up_one.seen[-1][0] if up_one.seen else ""),
              str(up_one.seen[-1][0])[:160] if up_one.seen else "no call")

        st, m1b = await post("/admin/teaching/sessions/%s/messages" % sess["session_id"],
                             {"text": "uniquetokenB 是什么？"})
        check("T3d teacher A cannot reach teacher B's material",
              st == 200 and not (m1b.get("sources") or [])
              and m1b.get("material_state") == "no_match", str(m1b)[:200])
        check("T3e no secret leaks into any teaching response",
              SECRET_ONE not in json.dumps(m1b) and SECRET_TWO not in json.dumps(m1b))

        # ---- T2 every teacher uses its own model + instruction ------------
        st, cb = await post("/admin/teacher/teachers", {
            "name": "数学赵老师", "subject": "math", "language": "zh",
            "teaching_style": "encouraging", "voice": {"mode": "text"},
            "model": {"text_model_id": model_b["id"]},
            "knowledge": {"dataset_ids": [ds_b["id"]]}})
        tid_b = cb["teacher"]["teacher_id"]
        st, s2 = await post("/admin/teaching/sessions",
                            {"teacher_id": tid_b, "student_id": "stu_1"})
        sid_b = s2["session"]["session_id"]
        check("T2a session B bound to its own model",
              s2["session"]["model_id"] == model_b["id"]
              and s2["session"]["model_key"] == "mock-model-two", str(s2["session"]))
        st, m2 = await post("/admin/teaching/sessions/%s/messages" % sid_b,
                            {"text": "uniquetokenB 怎么算？"})
        check("T2b teacher B answered by its OWN upstream (distinct model)",
              st == 200 and "UPSTREAM-TWO" in (m2.get("reply") or "")
              and "UPSTREAM-ONE" not in (m2.get("reply") or ""), str(m2)[:200])
        check("T2c teacher B retrieved its own material",
              any(s["dataset_id"] == ds_b["id"] for s in (m2.get("sources") or [])),
              str(m2.get("sources")))
        sys_a = up_one.seen[-1][0] if up_one.seen else ""
        sys_b = up_two.seen[-1][0] if up_two.seen else ""
        check("T2d per-teacher instruction differs (server-composed)",
              ("严格" in sys_a and "严格" not in sys_b)
              or ("鼓励" in sys_b and "鼓励" not in sys_a), (sys_a[:60], sys_b[:60]))

        # ---- T4 refusal when no usable text model -------------------------
        st, cc = await post("/admin/teacher/teachers", {
            "name": "未配模型老师", "voice": {"mode": "text"}})
        tid_c = cc["teacher"]["teacher_id"]
        st, r = await post("/admin/teaching/sessions", {"teacher_id": tid_c,
                                                        "student_id": "stu_1"})
        check("T4a start refused when no text model is configured",
              st == 400 and r.get("error") == "text_model_not_configured", str(r)[:200])
        # unverified model (enabled but with no verification evidence yet)
        reg = stores.model_registry
        m_unv = reg.create_model(provider_id=prov_a["id"], model_key="unverified-model",
                                 capabilities=["text_llm", "streaming"])
        reg.set_enabled(m_unv["id"], True)
        st, cd = await post("/admin/teacher/teachers", {
            "name": "未验证模型老师", "voice": {"mode": "text"},
            "model": {"text_model_id": m_unv["id"]}})
        st, r = await post("/admin/teaching/sessions",
                           {"teacher_id": cd["teacher"]["teacher_id"],
                            "student_id": "stu_1"})
        check("T4b start refused when the model has no verification evidence",
              st == 400 and r.get("error") == "evidence_missing", str(r)[:200])
        # disabled model
        reg.set_evidence(m_unv["id"], "verified", source="test")
        reg.set_enabled(m_unv["id"], True)
        st, ce = await post("/admin/teacher/teachers", {
            "name": "停用模型老师", "voice": {"mode": "text"},
            "model": {"text_model_id": m_unv["id"]}})
        tid_e = ce["teacher"]["teacher_id"]
        reg.set_enabled(m_unv["id"], False)
        st, r = await post("/admin/teaching/sessions", {"teacher_id": tid_e,
                                                        "student_id": "stu_1"})
        check("T4c start refused when the bound model is disabled",
              st == 400 and r.get("error") == "model_disabled", str(r)[:200])
        # no session was created by any refusal
        st, lst = await get("/admin/teaching/sessions?student_id=stu_1")
        check("T4d refused starts created no session",
              all(s["teacher_id"] not in (tid_c, tid_e)
                  for s in lst["sessions"]), str(lst["count"]))

        # ---- T8 frozen Tina unchanged + refuses text teaching -------------
        st, tina = await get("/admin/teacher/teachers/tina")
        tr = tina["teacher"]
        check("T8a frozen Tina config unchanged",
              tr["frozen"] is True and tr["voice"]["mode"] == "realtime"
              and tr["model"]["realtime_model_id"] == "mdl_frozen_tina"
              and tr["model"]["text_model_id"] == "", str(tr.get("model")))
        st, r = await post("/admin/teaching/sessions", {"teacher_id": "tina",
                                                        "student_id": "stu_1"})
        check("T8b frozen Tina cannot start text teaching",
              st == 400 and r.get("error") == "frozen_realtime_only", str(r)[:200])
        st, r = await put("/admin/teacher/teachers/tina",
                          {"voice": {"mode": "text", "voice_id": "x"}})
        check("T8c frozen Tina voice still not writable", st == 400, str(r)[:120])
        froz = stores.model_registry.get_model("mdl_frozen_tina")
        check("T8d frozen realtime model untouched",
              bool(froz) and froz.get("frozen") is True and froz.get("enabled") is True)

        # ---- T5 isolation across teachers and students --------------------
        st, s3 = await post("/admin/teaching/sessions",
                            {"teacher_id": tid_a, "student_id": "stu_2"})
        sid_a2 = s3["session"]["session_id"]
        st, e1 = await post("/admin/teaching/sessions/%s/end" % sess["session_id"], {
            "outcome": {"knowledge_points": ["问候语 Hello / Hi"],
                        "weak_points": ["第三人称单数 -s"],
                        "review_items": ["Lesson A 词汇"]},
            "memory_items": [{"entity": "profile_fact", "key": "goal",
                              "value": "跟英语李老师学口语"}]})
        check("T5a classroom outcome saved with the session",
              st == 200 and (e1["session"]["outcome"] or {}).get("knowledge_points")
              and e1["session"]["status"] == "ended", str(e1)[:240])
        st, e2 = await post("/admin/teaching/sessions/%s/end" % sid_b, {
            "memory_items": [{"entity": "profile_fact", "key": "goal",
                              "value": "跟数学赵老师学分数"}]})
        check("T5b same key, different teachers -> both saved (no overwrite)",
              st == 200 and len(e2["memory_saved"]) == 1, str(e2)[:200])
        mpath = os.path.join(tmp, "stores", "memory.json")
        a_items = MemoryStore(mpath, user="stu_1").load().list_items(teacher_id=tid_a)
        b_items = MemoryStore(mpath, user="stu_1").load().list_items(teacher_id=tid_b)
        check("T5c teacher-namespaced memory holds both 'goal' values",
              {i["value"] for i in a_items} == {"跟英语李老师学口语"}
              and {i["value"] for i in b_items} == {"跟数学赵老师学分数"},
              str([i["value"] for i in a_items]) + str([i["value"] for i in b_items]))
        check("T5d memory records carry student + teacher scope",
              all(i["user_id"] == "stu_1" and i["teacher_id"] == tid_a for i in a_items))
        stu1 = await get("/admin/teaching/sessions?student_id=stu_1")
        stu2 = await get("/admin/teaching/sessions?student_id=stu_2")
        check("T5e student scope filter separates classroom records",
              {s["student_id"] for s in stu1[1]["sessions"]} == {"stu_1"}
              and {s["student_id"] for s in stu2[1]["sessions"]} == {"stu_2"},
              str(stu1[1]["count"]) + "/" + str(stu2[1]["count"]))
        ta = await get("/admin/teaching/sessions?teacher_id=%s" % tid_a)
        check("T5f teacher scope filter separates classroom records",
              all(s["teacher_id"] == tid_a for s in ta[1]["sessions"])
              and any(s["session_id"] == sid_a2 for s in ta[1]["sessions"]))
        s2mem = MemoryStore(mpath, user="stu_2").load().items()
        check("T5g no cross-student memory leakage", s2mem == [], str(s2mem)[:120])
        victim = await get("/admin/teaching/sessions/%s" % sid_b)
        check("T5h a session keeps its own student scope (server-side)",
              victim[1]["session"]["student_id"] == "stu_1")

        # ---- T6 restart: classroom records survive ------------------------
        stores2 = _stores(tmp)
        app2 = _app(tmp, stores2)
        async with TestClient(TestServer(app2)) as cl2:
            r = await cl2.get("/admin/teaching/sessions/%s" % sess["session_id"],
                              headers=AUTH)
            b = await r.json()
            s = b.get("session") or {}
            check("T6a ended session readable after restart",
                  r.status == 200 and s.get("status") == "ended"
                  and s.get("turn_count", 0) >= 2, str(b)[:200])
            check("T6b turns survive restart",
                  len(s.get("turns") or []) == s.get("turn_count")
                  and any((t.get("sources") or []) for t in (s.get("turns") or [])),
                  str(s.get("turns"))[:200])
            check("T6c outcome survives restart",
                  (s.get("outcome") or {}).get("review_items") == ["Lesson A 词汇"],
                  str(s.get("outcome")))
            check("T6d store reloaded from disk is available",
                  stores2.teaching is not None and stores2.teaching.available)

        # ---- T7 password login not regressed ------------------------------
        st, body = await get("/admin/auth/status")
        check("T7a password-auth surface still mounted",
              st == 200 and "initialized" in body, str(body)[:120])
        check("T7b bearer still enforced (401 without token)",
              (await cl.get("/admin/teaching/overview")).status == 401)

    # ---- summary -----------------------------------------------------------
    ok = sum(1 for _, c, _ in RESULTS if c)
    print("\n%d/%d checks passed" % (ok, len(RESULTS)))
    if ok != len(RESULTS):
        print("FAILURES:")
        for n, c, d in RESULTS:
            if not c:
                print("  -", n, ("[%s]" % d) if d else "")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(amain())
