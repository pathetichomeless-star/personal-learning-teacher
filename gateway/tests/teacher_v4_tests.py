"""TEACHER_V4_TESTS — P1 multi-teacher deterministic suite.

Runs standalone:  python tests/teacher_v4_tests.py   (from gateway/, venv)

No paid model call, no network.  Covers the eight required targeted checks:

  T1 teacher creation + restart persistence
  T2 multi-teacher configuration isolation
  T3 duplicating a teacher (and never inheriting the frozen realtime link)
  T4 default-teacher switching + enable/disable + delete protections
  T5 model capability check (server-side evidence, never the request body)
  T6 knowledge linkage + (student_id, teacher_id) learner-record isolation
     (T6f..T6m same-key cross-teacher overwrite guard + historical compat)
  T7 Tina frozen configuration unchanged
  T8 password-login surface not regressed
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from aiohttp.test_utils import TestClient, TestServer           # noqa: E402

from app.admin.app import admin_route_table, create_admin_app   # noqa: E402
from app.admin.auth import TokenStore                           # noqa: E402
from app.admin.config import load_admin_config                  # noqa: E402
from app.admin.password_auth import PasswordStore, SessionStore  # noqa: E402
from app.admin.stores import AdminStores                        # noqa: E402
from modules.memory.store import MemoryStore                    # noqa: E402
from modules.teacher.store import TeacherStore                  # noqa: E402

FIX_TOKEN = "TEACHER_V4_BEARER_TOKEN_DO_NOT_LEAK_24680"
AUTH = {"Authorization": "Bearer " + FIX_TOKEN}
RESULTS = []

FAKE_IP = lambda host: ["93.184.216.34"]                         # noqa: E731


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % (detail,)) if (detail and not cond) else ""))


def _cfg(tmp):
    p = os.path.join(tmp, "tok")
    with open(p, "w") as fh:
        fh.write(FIX_TOKEN + "\n")
    os.chmod(p, 0o600)
    return load_admin_config(env={
        "ADMIN_ENABLED": "1", "ADMIN_BIND": "127.0.0.1", "ADMIN_PORT": "18141",
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


async def amain():
    tmp = tempfile.mkdtemp(prefix="teacher-v4-")
    stores = _stores(tmp)
    app = _app(tmp, stores)
    table = admin_route_table(stores=stores)
    teacher_routes = {p for m, p in table if "/admin/teacher/" in p}

    # ---- T0 route inventory ------------------------------------------------
    mounted = {r.resource.canonical for r in app.router.routes()}
    check("T0 all teacher routes mounted",
          all(p in mounted for p in teacher_routes), str(sorted(teacher_routes)))

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

        async def delete(p, body):
            r = await cl.delete(p, headers=AUTH, json=body)
            return r.status, await r.json()

        # ---- seed ---------------------------------------------------------
        st, body = await get("/admin/teacher/teachers")
        check("T-seed Tina seeded and default",
              st == 200 and body["count"] == 1
              and body["default_teacher_id"] == "tina"
              and body["teachers"][0]["frozen"] is True, str(body)[:200])
        tina_before = body["teachers"][0]
        check("T-seed2 frozen Tina realtime link reported usable+read-only",
              tina_before["availability"]["effective_mode"] == "realtime"
              and tina_before["availability"]["realtime"]["usable"] is True
              and tina_before["availability"]["realtime"].get("read_only") is True,
              str(tina_before.get("availability")))

        # ---- T1 create + restart persistence ------------------------------
        st, created = await post("/admin/teacher/teachers", {
            "name": "数学王老师", "avatar": "W", "intro": "耐心讲数学",
            "subject": "math", "language": "zh", "teaching_style": "strict",
            "voice": {"mode": "text"}, "knowledge": {"dataset_ids": []}})
        tid = (created.get("teacher") or {}).get("teacher_id")
        check("T1a create teacher via API",
              st == 200 and tid and created["readback_ok"]
              and created["teacher"]["name"] == "数学王老师", str(created)[:200])
        check("T1b system instruction composed from style",
              "严格" in (created.get("teacher") or {}).get("system_instruction", ""))

        # restart: a NEW store + NEW app over the same files
        stores2 = _stores(tmp)
        app2 = _app(tmp, stores2)
        async with TestClient(TestServer(app2)) as cl2:
            r = await cl2.get("/admin/teacher/teachers", headers=AUTH)
            b = await r.json()
            names = {t["name"] for t in b["teachers"]}
            check("T1c teacher survives restart (new process)",
                  r.status == 200 and "数学王老师" in names, str(names))

        # ---- T2 config isolation between teachers -------------------------
        st, c2 = await post("/admin/teacher/teachers", {
            "name": "口语Amy", "subject": "english", "language": "en",
            "teaching_style": "encouraging", "voice": {"mode": "text"}})
        tid2 = c2["teacher"]["teacher_id"]
        st, one = await get("/admin/teacher/teachers/" + tid)
        st, two = await get("/admin/teacher/teachers/" + tid2)
        check("T2a teachers have distinct stable ids", tid != tid2 and tid != "tina")
        check("T2b configs are independent",
              one["teacher"]["subject"] == "math"
              and two["teacher"]["subject"] == "english"
              and one["teacher"]["teaching_style"] != two["teacher"]["teaching_style"])

        # ---- T3 duplicate -------------------------------------------------
        st, dup = await post("/admin/teacher/teachers/tina/duplicate", {"name": "Tina 二班"})
        d = dup.get("teacher") or {}
        check("T3a duplicate Tina -> new id, not default, not frozen",
              st == 200 and d.get("teacher_id") not in (None, "tina")
              and d.get("frozen") is False and d.get("is_default") is False,
              str(dup)[:200])
        check("T3b duplicate does NOT inherit frozen realtime link",
              (d.get("voice") or {}).get("mode") == "text"
              and not (d.get("model") or {}).get("realtime_model_id"),
              str(d.get("voice")) + str(d.get("model")))
        st, dup2 = await post("/admin/teacher/teachers/%s/duplicate" % tid, {})
        check("T3c duplicate custom teacher copies fields, new id",
              st == 200 and dup2["teacher"]["teacher_id"] != tid
              and dup2["teacher"]["subject"] == "math"
              and "副本" in dup2["teacher"]["name"], str(dup2)[:200])

        # ---- T4 default switch / enable-disable / delete protections ------
        st, sw = await post("/admin/teacher/teachers/%s/set-default" % tid, {})
        check("T4a switch default teacher",
              st == 200 and sw.get("default_teacher_id") == tid)
        st, b = await get("/admin/teacher/teachers")
        check("T4b only one default at a time",
              len([t for t in b["teachers"] if t.get("is_default")]) == 1
              and b["default_teacher_id"] == tid)
        # the previous default (Tina) must not be disable-able while... it is now not
        # default, but Tina is frozen and must stay enabled regardless
        st, r = await post("/admin/teacher/teachers/tina/disable", {})
        check("T4c frozen Tina cannot be disabled", st == 400, str(r)[:120])
        st, r = await delete("/admin/teacher/teachers/tina", {"confirm": "tina"})
        check("T4d frozen Tina cannot be deleted", st == 400, str(r)[:120])
        # current default cannot be disabled or deleted
        st, r = await post("/admin/teacher/teachers/%s/disable" % tid, {})
        check("T4e current default cannot be disabled", st == 400, str(r)[:120])
        st, r = await delete("/admin/teacher/teachers/%s" % tid, {"confirm": tid})
        check("T4f current default cannot be deleted", st == 400, str(r)[:120])
        # disable a non-default teacher, then delete it (soft)
        st, r = await post("/admin/teacher/teachers/%s/disable" % tid2, {})
        check("T4g non-default teacher can be disabled",
              st == 200 and r["teacher"]["enabled"] is False)
        st, r = await delete("/admin/teacher/teachers/%s" % tid2, {"confirm": "wrong"})
        check("T4h delete requires matching confirm token", st == 400, str(r)[:120])
        st, r = await delete("/admin/teacher/teachers/%s" % tid2, {"confirm": tid2})
        check("T4i delete custom teacher (soft)", st == 200 and r["deleted"]["soft"])
        st, b = await get("/admin/teacher/teachers")
        check("T4j soft-deleted teacher hidden from list",
              tid2 not in {t["teacher_id"] for t in b["teachers"]})
        # teachable name is not the identifier: two teachers may share a name
        st, a1 = await post("/admin/teacher/teachers", {"name": "同名老师",
                                                        "voice": {"mode": "text"}})
        st, a2 = await post("/admin/teacher/teachers", {"name": "同名老师",
                                                        "voice": {"mode": "text"}})
        check("T4k duplicate names allowed (id is the key)",
              a1["teacher"]["teacher_id"] != a2["teacher"]["teacher_id"])

        # ---- T5 model capability check ------------------------------------
        reg = stores.model_registry
        prov = reg.create_provider(name="验收DashScope", protocol="dashscope",
                                   base_url="https://dashscope.aliyuncs.com",
                                   capabilities=["text_llm", "streaming", "realtime_audio",
                                                 "barge_in"], resolver=FAKE_IP)
        mtext = reg.create_model(provider_id=prov["id"], model_key="text-model",
                                 capabilities=["text_llm", "streaming"])
        mrt = reg.create_model(provider_id=prov["id"], model_key="rt-model",
                               capabilities=["realtime_audio", "streaming", "barge_in"])
        stores.model_credentials.put(prov["id"], "sk-secret-never-leak")
        st, caps = await get("/admin/teacher/capabilities")
        text_row = next((m for m in caps["text_models"] if m["id"] == mtext["id"]), {})
        rt_row = next((m for m in caps["realtime_models"] if m["id"] == mrt["id"]), {})
        check("T5a unverified models NOT marked usable",
              caps["available"] and text_row.get("usable") is False
              and rt_row.get("usable") is False, str(caps)[:200])
        # a genuine verified run records evidence (server-side)
        reg.set_evidence(mtext["id"], "verified", source="test")
        reg.set_evidence(mrt["id"], "verified", source="test")
        st, caps = await get("/admin/teacher/capabilities")
        text_row = next(m for m in caps["text_models"] if m["id"] == mtext["id"])
        rt_row = next(m for m in caps["realtime_models"] if m["id"] == mrt["id"])
        check("T5b verified text model usable for dialogue",
              text_row["usable"] is True, str(text_row))
        check("T5c realtime needs realtime_safe (verified is not enough)",
              rt_row["usable"] is False, str(rt_row))
        reg.promote_realtime_safe(mrt["id"], operator="test", confirm=True)
        st, caps = await get("/admin/teacher/capabilities")
        rt_row = next(m for m in caps["realtime_models"] if m["id"] == mrt["id"])
        check("T5d realtime_safe model usable for realtime",
              rt_row["usable"] is True, str(rt_row))
        check("T5e no secret leaks in capability view",
              "sk-secret-never-leak" not in str(caps))
        # teacher binds the verified text model
        st, bnd = await post("/admin/teacher/teachers", {
            "name": "绑定模型老师", "voice": {"mode": "text"},
            "model": {"text_model_id": mtext["id"]}})
        check("T5f teacher availability reflects bound model",
              bnd["teacher"]["availability"]["text"]["usable"] is True,
              str(bnd["teacher"].get("availability")))

        # ---- T6 knowledge linkage + learner-record isolation --------------
        kb = stores.knowledge
        ds = kb.create_dataset("英语课件库")
        doc = kb.add_document(ds["id"], "Lesson 1", "hello world " * 30)
        st, linked = await put("/admin/teacher/teachers/%s" % tid, {
            "knowledge": {"dataset_ids": [ds["id"]], "course_ids": []}})
        st, got = await get("/admin/teacher/teachers/%s" % tid)
        resolved = (got["teacher"].get("knowledge") or {}).get("datasets") or []
        check("T6a teacher links existing knowledge dataset (resolved by name)",
              st == 200 and resolved and resolved[0]["id"] == ds["id"]
              and resolved[0]["name"] == "英语课件库", str(resolved))
        # knowledge linkage is by reference — the dataset is not copied
        check("T6b linkage is by stable id (no copy of the dataset)",
              len(kb.list_datasets()) == 1 and doc["dataset_id"] == ds["id"])

        mpath = os.path.join(tmp, "learn_memory.json")
        sa = MemoryStore(mpath, user="student1")
        sa.save("profile_fact", "name", "小明", teacher_id="tina")
        sa.save("profile_fact", "hobby", "象棋", teacher_id=tid)
        sb = MemoryStore(mpath, user="student2")
        sb.save("profile_fact", "name", "小红", teacher_id="tina")
        s1_tina = MemoryStore(mpath, user="student1").load().list_items(teacher_id="tina")
        s1_tid = MemoryStore(mpath, user="student1").load().list_items(teacher_id=tid)
        s2_tina = MemoryStore(mpath, user="student2").load().list_items(teacher_id="tina")
        check("T6c same student, different teachers -> isolated records",
              {i["value"] for i in s1_tina} == {"小明"}
              and {i["value"] for i in s1_tid} == {"象棋"},
              str([i["value"] for i in s1_tina]) + str([i["value"] for i in s1_tid]))
        check("T6d same teacher, different students -> isolated records",
              {i["value"] for i in s2_tina} == {"小红"})
        check("T6e records carry both student_id and teacher_id",
              all(i["user_id"] == "student1" and i["teacher_id"] == "tina"
                  for i in s1_tina))

        # ---- T6f..T6m same-key cross-teacher overwrite guard (repair) ------
        # the exact scenario from the repair order: student A + teacher 1 and
        # student A + teacher 2 save the SAME key; records must coexist.
        sa.save("profile_fact", "goal", "跟Tina练口语", teacher_id="tina")
        sa.save("profile_fact", "goal", "跟新老师学语法", teacher_id=tid)
        s1_reload = MemoryStore(mpath, user="student1").load()
        goals = {i["teacher_id"]: i["value"] for i in
                 s1_reload.list_items(entity="profile_fact")
                 if i["key"] == "goal"}
        check("T6f same key, two teachers -> both records kept (no overwrite)",
              goals.get("tina") == "跟Tina练口语"
              and goals.get(tid) == "跟新老师学语法", str(goals))
        it1 = sa.note_weak_word("apple", teacher_id="tina")
        it2 = sa.note_weak_word("apple", teacher_id=tid)
        check("T6g same vocab word, two teachers -> distinct records",
              it1 is not None and it2 is not None and it1.id != it2.id
              and it1.teacher_id == "tina" and it2.teacher_id == tid,
              "%s %s" % (it1 and it1.id, it2 and it2.id))
        s1_words = MemoryStore(mpath, user="student1").load()
        n_tina = sum(1 for i in s1_words.list_items(entity="vocab_item", teacher_id="tina")
                     if i["key"] == "apple")
        n_tid = sum(1 for i in s1_words.list_items(entity="vocab_item", teacher_id=tid)
                    if i["key"] == "apple")
        check("T6h vocab word visible under each teacher exactly once",
              n_tina == 1 and n_tid == 1, str((n_tina, n_tid)))
        s2_reload = MemoryStore(mpath, user="student2").load()
        s2_all = s2_reload.list_items()
        check("T6i student B sees none of student A's private records",
              all(i["user_id"] == "student2" for i in s2_all)
              and not any(i["value"] in ("小明", "象棋", "跟Tina练口语")
                          for i in s2_all), str(s2_all)[:120])
        # edit / delete must honour the same (student, teacher) ownership
        tid_goal = next(i for i in s1_reload.list_items(entity="profile_fact",
                                                        teacher_id=tid)
                        if i["key"] == "goal")
        s1_reload.edit(tid_goal["id"], value="改后的目标")
        s1_after_edit = MemoryStore(mpath, user="student1").load()
        g_tina = next(i for i in s1_after_edit.list_items(entity="profile_fact",
                                                          teacher_id="tina")
                      if i["key"] == "goal")
        g_tid = next(i for i in s1_after_edit.list_items(entity="profile_fact",
                                                         teacher_id=tid)
                     if i["key"] == "goal")
        check("T6j edit by item id touches only the owning teacher's record",
              g_tina["value"] == "跟Tina练口语" and g_tid["value"] == "改后的目标",
              str((g_tina["value"], g_tid["value"])))
        s1_after_edit.delete(tid_goal["id"])
        s1_after_del = MemoryStore(mpath, user="student1").load()
        check("T6k delete by item id removes only that teacher's record",
              any(i["key"] == "goal"
                  for i in s1_after_del.list_items(entity="profile_fact",
                                                   teacher_id="tina"))
              and not any(i["key"] == "goal"
                          for i in s1_after_del.list_items(entity="profile_fact",
                                                           teacher_id=tid)))
        # historical records without teacher_id: safe compat, no loss, no claim
        sa.save("profile_fact", "city", "上海")  # no teacher_id -> default scope
        s1_hist = MemoryStore(mpath, user="student1").load()
        hist = [i for i in s1_hist.list_items(entity="profile_fact", teacher_id="")
                if i["key"] == "city"]
        check("T6l historical no-teacher record keeps empty attribution",
              len(hist) == 1 and hist[0]["teacher_id"] == "", str(hist))
        check("T6m historical record is not claimed by any teacher filter",
              not any(i["key"] == "city" for i in
                      s1_hist.list_items(entity="profile_fact", teacher_id="tina"))
              and not any(i["key"] == "city" for i in
                          s1_hist.list_items(entity="profile_fact", teacher_id=tid)))

        # ---- T7 Tina frozen configuration unchanged ----------------------
        st, body = await get("/admin/teacher/teachers")
        tina_after = next(t for t in body["teachers"] if t["teacher_id"] == "tina")
        check("T7a Tina voice/model/name/frozen unchanged",
              tina_after["voice"] == tina_before["voice"]
              and tina_after["model"] == tina_before["model"]
              and tina_after["name"] == tina_before["name"]
              and tina_after["frozen"] is True
              and tina_after["origin"] == "builtin_frozen_default",
              str(tina_after.get("voice")))
        st, r = await put("/admin/teacher/teachers/tina",
                          {"voice": {"mode": "text", "voice_id": "hacked"}})
        check("T7b Tina voice cannot be rewritten", st == 400, str(r)[:120])
        # confirm the frozen realtime model in the registry is untouched
        froz = stores.model_registry.get_model("mdl_frozen_tina")
        check("T7c frozen realtime model untouched in registry",
              bool(froz) and froz.get("frozen") is True
              and froz.get("enabled") is True)

        # ---- T8 password-login surface not regressed ----------------------
        st, body = await get("/admin/auth/status")
        check("T8a factory password auth still mounted",
              st == 200 and "initialized" in body, str(body)[:120])
        check("T8b legacy bearer auth still enforced (401 without token)",
              (await cl.get("/admin/teacher/teachers")).status == 401)

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
