"""ADMIN2_TESTS — deterministic functional suite for the ADMIN-2 control plane.

Runs standalone:  python tests/admin2_tests.py   (from gateway/, venv)

Covers every required ADMIN-2 surface over loopback only: PERSONA/POLICY
(active/versions/audit/preview/apply/rollback + read-back), MEMORY
(list/search/inspect/edit/delete/category-clear/diagnostics), KNOWLEDGE
(datasets/documents CRUD, enable/disable, rebuild, retrieval test, diagnostics),
WORKBENCH (read-only status/current/progress/reviews — no write route),
BEHAVIOR (active policy + bounded routing metadata, never raw transcripts),
the admin audit, and ADMIN-1 backward compatibility of the six read-only routes.
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

from aiohttp import web                                      # noqa: E402
from aiohttp.test_utils import TestClient, TestServer        # noqa: E402

from app.admin import load_admin_config                      # noqa: E402
from app.admin.app import admin_route_table, create_admin_app  # noqa: E402
from app.admin.auth import TokenStore                        # noqa: E402
from app.admin.registry import sessions as admin_sessions    # noqa: E402
from app.admin.stores import AdminStores                     # noqa: E402
from modules.memory.store import MemoryStore                 # noqa: E402
from types import SimpleNamespace                            # noqa: E402

FIX_TOKEN = "ADMIN2_TEST_TOKEN_DO_NOT_LEAK_987654321"
UI_DIR = _ROOT.parent / "admin"
AUTH = {"Authorization": "Bearer " + FIX_TOKEN}

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % detail) if (detail and not cond) else ""))


def _cfg(tmpdir):
    return load_admin_config(env={
        "ADMIN_ENABLED": "1", "ADMIN_BIND": "127.0.0.1", "ADMIN_PORT": "18113",
        "ADMIN_API_TOKEN_FILE": str(Path(tmpdir) / "admin_api_token"),
        "ADMIN_UI_DIR": str(UI_DIR),
    })


def _stores(tmpdir, *, workbench_url="", name="default"):
    sub = Path(tmpdir) / name
    sub.mkdir(parents=True, exist_ok=True)
    return AdminStores(policy_file=str(sub / "policy.json"),
                       memory_file=str(sub / "memory.json"),
                       knowledge_file=str(sub / "knowledge.json"),
                       workbench_url=workbench_url)


async def with_client(fn, tmpdir, *, workbench_url="", name="default"):
    cfg = _cfg(tmpdir)
    token_store = TokenStore(cfg.token_file, cfg.token_env)
    token_store.reload()
    stores = _stores(tmpdir, workbench_url=workbench_url, name=name)
    app = create_admin_app(admin_config=cfg, token_store=token_store,
                           gateway_info=lambda: {"mode": "mock", "ready": True},
                           stores=stores)
    async with TestClient(TestServer(app)) as client:
        await fn(client, stores, tmpdir)


HOTEL_DOC = (
    "酒店入住时间是下午三点以后。退房时间是中午十二点前。\n\n"
    "入住时请出示护照，前台会核对预订信息。\n\n"
    "Hotel breakfast is served on the second floor from 7 to 10 am."
)


async def t_routes(tmpdir):
    # route inventory: additive, no reset, workbench GET-only
    table = admin_route_table(stores=_stores(tmpdir))
    paths = [p for _, p in table]
    check("A1 route table includes the six ADMIN-1 routes",
          all(p in paths for p in ("/admin/health", "/admin/version", "/admin/sessions",
                                   "/admin/metrics", "/admin/telemetry",
                                   "/admin/diag-summary")))
    check("A2 no /admin/diag/reset, ever", "/admin/diag/reset" not in paths)
    wb = [(m, p) for m, p in table if p.startswith("/admin/workbench/")]
    check("A3 workbench routes exist and are all GET (read-only)",
          len(wb) == 4 and all(m == "GET" for m, _ in wb), wb)
    check("A4 admin_route_table() without stores stays ADMIN-1-only",
          admin_route_table() == [x for x in admin_route_table()]
          and all(not p.startswith("/admin/policy") for _, p in admin_route_table()))

    async def body(client, _, __):
        r = await client.post("/admin/workbench/status", headers=AUTH)
        check("A5 POST to a workbench path is refused (405)", r.status == 405,
              r.status)
        r2 = await client.get("/admin/knowledge/search", headers=AUTH)
        check("A6 GET on a write path is refused (405)", r2.status == 405, r2.status)
        r3 = await client.post("/admin/diag/reset", headers=AUTH)
        check("A7 /admin/diag/reset does not exist", r3.status == 404, r3.status)
    await with_client(body, tmpdir, name="routes")


async def t_policy(tmpdir):
    async def body(client, stores, _):
        r = await (await client.get("/admin/policy/active", headers=AUTH)).json()
        check("B1 active policy: v1 defaults + rendered preview",
              r["version"] == 1 and r["policy"]["persona"]["name"] == "小智"
              and "You are 小智" in r["rendered_preview"])

        pv = await (await client.post("/admin/policy/preview", headers=AUTH,
                                      json={"policy": {"persona": {"name": "小美"}}})).json()
        check("B2 preview: valid + changed keys + would-be version, no mutation",
              pv["valid"] and pv["changed_keys"] == ["persona.name"]
              and pv["would_be_version"] == 2
              and (await (await client.get("/admin/policy/active", headers=AUTH)).json())
              ["version"] == 1)

        bad = await client.post("/admin/policy/preview", headers=AUTH,
                                json={"policy": {"persona": {"name": ""}}})
        check("B3 preview invalid is reported (200 with valid=false)",
              bad.status == 200 and (await bad.json())["valid"] is False)

        noconf = await client.post("/admin/policy/apply", headers=AUTH,
                                   json={"policy": {"persona": {"name": "小美"}}})
        check("B4 apply without confirmation refused",
              noconf.status == 400 and (await noconf.json())["error"] == "confirm_required")

        applied = await (await client.post(
            "/admin/policy/apply", headers=AUTH,
            json={"policy": {"persona": {"name": "小美"}}, "confirm": True})).json()
        check("B5 apply: explicit confirm + read-back ok",
              applied["applied"]["version"] == 2 and applied["readback_ok"] is True)
        act = await (await client.get("/admin/policy/active", headers=AUTH)).json()
        check("B6 read-back from the store shows the new persona",
              act["version"] == 2 and act["policy"]["persona"]["name"] == "小美"
              and os.path.exists(stores.policy.path))

        inv = await client.post("/admin/policy/apply", headers=AUTH,
                                json={"policy": {"persona": {"name": ""}}, "confirm": True})
        check("B7 invalid apply refused with policy_invalid + errors",
              inv.status == 400 and (await inv.json())["error"] == "policy_invalid"
              and (await inv.json()).get("errors"))

        vers = await (await client.get("/admin/policy/versions", headers=AUTH)).json()
        check("B8 versions list", [v["version"] for v in vers["versions"]] == [1, 2])
        aud = await (await client.get("/admin/policy/audit", headers=AUTH)).json()
        check("B9 policy audit records the apply (sanitized)",
              any(a["action"] == "apply" and a["to_version"] == 2
                  for a in aud["audit"]))

        rb_noconf = await client.post("/admin/policy/rollback", headers=AUTH,
                                      json={"version": 1})
        check("B10 rollback without confirmation refused", rb_noconf.status == 400)
        rb = await (await client.post("/admin/policy/rollback", headers=AUTH,
                                      json={"version": 1, "confirm": True})).json()
        check("B11 rollback restores v1 as a new version + read-back",
              rb["applied"]["restored_from"] == 1 and rb["readback_ok"]
              and rb["active"]["version"] == 3)
        act2 = await (await client.get("/admin/policy/active", headers=AUTH)).json()
        check("B12 rolled-back policy serves the restored persona",
              act2["version"] == 3 and act2["policy"]["persona"]["name"] == "小智")
        rb_bad = await client.post("/admin/policy/rollback", headers=AUTH,
                                   json={"version": 99, "confirm": True})
        check("B13 rollback of an unknown version refused", rb_bad.status == 400)
    await with_client(body, tmpdir, name="policy")


async def t_memory(tmpdir):
    async def body(client, stores, _):
        stores.memory.save_preference("explanation_language", "zh")
        stores.memory.save("profile_fact", "name", "小王")
        stores.memory.note_weak_word("accommodation")

        items = await (await client.get("/admin/memory/items", headers=AUTH)).json()
        check("C1 items list + category summary",
              items["count"] == 3
              and items["category_summary"]["preference"]["count"] == 1
              and items["category_summary"]["vocab_item"]["count"] == 1)
        filt = await (await client.get("/admin/memory/items?entity=profile_fact",
                                       headers=AUTH)).json()
        check("C2 entity filter", filt["count"] == 1
              and filt["items"][0]["key"] == "name")
        sq = await (await client.get("/admin/memory/search?q=小王", headers=AUTH)).json()
        check("C3 search by value", sq["count"] == 1)
        miss = await client.get("/admin/memory/search?q=", headers=AUTH)
        check("C4 empty query refused", miss.status == 400)

        fid = [i for i in items["items"] if i["key"] == "name"][0]["id"]
        one = await (await client.get("/admin/memory/item/" + fid, headers=AUTH)).json()
        check("C5 inspect by id", one["item"]["value"] == "小王")
        nf = await client.get("/admin/memory/item/mem_nope", headers=AUTH)
        check("C6 unknown id -> 404", nf.status == 404)

        ed = await (await client.post("/admin/memory/edit", headers=AUTH,
                                      json={"id": fid, "value": "小李"})).json()
        check("C7 edit + read-back", ed["item"]["value"] == "小李"
              and ed["readback_ok"] is True)
        bad_ed = await client.post("/admin/memory/edit", headers=AUTH,
                                   json={"id": fid, "value": "我的课程进度是第3课"})
        check("C8 progress-shaped edit refused (boundary_violation)",
              bad_ed.status == 400
              and (await bad_ed.json())["error"] == "boundary_violation")
        sec_ed = await client.post("/admin/memory/edit", headers=AUTH,
                                   json={"id": fid, "value": "my password is hunter2"})
        check("C9 secret-shaped edit refused", sec_ed.status == 400)

        dl = await client.post("/admin/memory/delete", headers=AUTH, json={"id": fid})
        check("C10 delete without confirmation refused (confirm_required)",
              dl.status == 400 and (await dl.json())["error"] == "confirm_required")
        dl2 = await (await client.post("/admin/memory/delete", headers=AUTH,
                                       json={"id": fid, "confirm": True})).json()
        check("C11 confirmed delete + read-back", dl2["deleted"] and dl2["readback_ok"])

        cc_bad = await client.post("/admin/memory/clear-category", headers=AUTH,
                                   json={"entity": "vocab_item", "confirm": "preference"})
        check("C12 category clear needs the exact category token",
              cc_bad.status == 400)
        cc = await (await client.post("/admin/memory/clear-category", headers=AUTH,
                                      json={"entity": "vocab_item",
                                            "confirm": "vocab_item"})).json()
        check("C13 confirmed category clear", cc["removed"] == 1
              and cc["category_summary"]["vocab_item"]["count"] == 0)

        # C15: two-writer topology — the gateway conversation path writes through a
        # *separate* store instance over the same file; admin reads must not serve a
        # stale view (regression: list reads used to skip the file-signature reload).
        gw = MemoryStore(stores.memory.path).load()
        gw.save("profile_fact", "city", "上海")
        vis = await (await client.get("/admin/memory/items", headers=AUTH)).json()
        check("C15 gateway-side write is visible to admin reads (no stale view)",
              any(i["key"] == "city" for i in vis["items"]))
        check("C15b refreshed instance also serves the item by id",
              (await (await client.get(
                  "/admin/memory/item/%s" % [i for i in vis["items"]
                                             if i["key"] == "city"][0]["id"],
                  headers=AUTH)).json())["item"]["value"] == "上海")

        dg = await (await client.get("/admin/memory/diagnostics", headers=AUTH)).json()
        check("C14 boundary diagnostics clean after the whole flow",
              dg["boundary"]["forbidden_keys_present"] == []
              and dg["boundary"]["secret_keys_present"] == [])
    await with_client(body, tmpdir, name="memory")


async def t_knowledge(tmpdir):
    async def body(client, stores, _):
        ds_list = await (await client.get("/admin/knowledge/datasets", headers=AUTH)).json()
        check("D1 datasets list starts empty", ds_list["count"] == 0)

        ds = (await (await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                                       json={"name": "客服资料", "tags": ["hotel"]}))
              .json())["dataset"]
        check("D2 dataset create + ds_ id", ds["id"].startswith("ds_"))
        rn = await (await client.post("/admin/knowledge/dataset/rename", headers=AUTH,
                                      json={"id": ds["id"], "name": "常见问题"})).json()
        check("D3 rename + read-back", rn["dataset"]["name"] == "常见问题"
              and rn["readback_ok"])
        off = await (await client.post("/admin/knowledge/dataset/enable", headers=AUTH,
                                       json={"id": ds["id"], "enabled": False})).json()
        check("D4 disable + read-back", off["dataset"]["status"] == "disabled"
              and off["readback_ok"])
        await client.post("/admin/knowledge/dataset/enable", headers=AUTH,
                          json={"id": ds["id"], "enabled": True})

        doc = (await (await client.post(
            "/admin/knowledge/document/add", headers=AUTH,
            json={"dataset_id": ds["id"], "title": "入住说明", "text": HOTEL_DOC,
                  "source_uri": "internal://front-desk"})).json())["document"]
        check("D5 document add + chunks + read-back",
              doc["id"].startswith("doc_") and doc["chunk_count"] >= 1)
        dup = await client.post("/admin/knowledge/document/add", headers=AUTH,
                                json={"dataset_id": ds["id"], "title": "dup",
                                      "text": HOTEL_DOC})
        check("D6 duplicate content -> 409 with existing id",
              dup.status == 409 and (await dup.json())["error"] == "duplicate_content"
              and (await dup.json())["existing_doc_id"] == doc["id"])
        mal = await client.post("/admin/knowledge/document/add", headers=AUTH,
                                json={"dataset_id": ds["id"], "title": "bad", "text": "  "})
        check("D7 malformed (empty) document -> 400", mal.status == 400)
        unk = await client.post("/admin/knowledge/document/add", headers=AUTH,
                                json={"dataset_id": "ds_nope", "title": "x",
                                      "text": "hello"})
        check("D8 unknown dataset -> 400 knowledge_error",
              unk.status == 400
              and (await unk.json())["error"] == "knowledge_error")

        srch = await (await client.post("/admin/knowledge/search", headers=AUTH,
                                        json={"query": "酒店退房是几点"})).json()
        check("D9 retrieval test returns the doc with provenance",
              srch["count"] >= 1 and srch["results"][0]["document_id"] == doc["id"]
              and srch["results"][0]["document_title"] == "入住说明")

        insp = await (await client.get("/admin/knowledge/document/" + doc["id"],
                                       headers=AUTH)).json()
        check("D10 document inspect (metadata + preview, no raw text field)",
              insp["inspection"]["chunk_count"] == doc["chunk_count"]
              and "text" not in insp["inspection"]["document"])
        chunks = await (await client.get("/admin/knowledge/document/%s/chunks" % doc["id"],
                                         headers=AUTH)).json()
        check("D11 chunk listing", chunks["count"] == doc["chunk_count"])
        docs = await (await client.get("/admin/knowledge/dataset/%s/documents" % ds["id"],
                                       headers=AUTH)).json()
        check("D11b dataset documents listing (metadata only, no raw text)",
              docs["count"] == 1 and docs["documents"][0]["title"] == "入住说明"
              and "text" not in docs["documents"][0])
        rb = await (await client.post("/admin/knowledge/document/rebuild", headers=AUTH,
                                      json={"id": doc["id"]})).json()
        check("D12 rebuild + read-back", rb["readback_ok"]
              and rb["rebuilt"]["chunks"] == doc["chunk_count"])

        dl = await client.post("/admin/knowledge/document/delete", headers=AUTH,
                               json={"id": doc["id"]})
        check("D13 document delete requires confirmation", dl.status == 400)
        prev = await (await client.get("/admin/knowledge/dataset/%s/preview" % ds["id"],
                                       headers=AUTH)).json()
        check("D14 dataset delete preview (counts + confirm token)",
              prev["preview"]["documents"] == 1
              and prev["preview"]["confirm_token"] == ds["id"])
        ds_bad = await client.post("/admin/knowledge/dataset/delete", headers=AUTH,
                                   json={"id": ds["id"], "confirm": "wrong"})
        check("D15 dataset delete needs the exact id token", ds_bad.status == 400)
        done = await (await client.post("/admin/knowledge/dataset/delete", headers=AUTH,
                                        json={"id": ds["id"], "confirm": ds["id"]})).json()
        check("D16 confirmed dataset delete removes docs+chunks",
              done["deleted"]["documents"] == 1 and done["readback_ok"])

        dg = await (await client.get("/admin/knowledge/diagnostics", headers=AUTH)).json()
        check("D17 diagnostics counts collapse after delete",
              dg["diagnostics"]["datasets"]["total"] == 0
              and dg["diagnostics"]["chunks"] == 0)
    await with_client(body, tmpdir, name="knowledge")


async def t_workbench_disabled(tmpdir):
    async def body(client, _, __):
        for path in ("status", "current", "progress", "reviews"):
            r = await (await client.get("/admin/workbench/" + path, headers=AUTH)).json()
            if not (r["available"] is False
                    and r["reason"] == "workbench_not_configured"):
                check("E1 workbench unconfigured degrades honestly (%s)" % path, False, r)
                return
        check("E1 workbench unconfigured degrades honestly (all four)", True)
    await with_client(body, tmpdir, name="wb_disabled")


async def t_workbench_readonly(tmpdir):
    from datetime import date, timedelta
    today = date.today()
    state = {"rev": 9, "updatedAt": "2026-10-05T02:25:51Z",
             "state": {"version": 2, "currentLesson": 12,
                       "lessons": {"1": {"decision": "PASS"},
                                   "2": {"decision": "REVIEW"}},
                       "reviews": [{"refId": "12:walked", "done": False,
                                    "nextReviewAt": (today - timedelta(days=1)).isoformat()},
                                   {"refId": "12:talked", "done": True,
                                    "nextReviewAt": (today - timedelta(days=9)).isoformat()}]}}
    calls = []

    async def sync_state(request):
        calls.append(request.method)
        return web.json_response(state)

    async def content(request):
        calls.append(request.method)
        if request.match_info["day"] == "12":
            return web.json_response({"lesson": 12, "unit": "一般过去时",
                                      "objectives": ["目标一", "目标二"]})
        return web.Response(status=404)

    fake = web.Application()
    fake.router.add_route("*", "/sync/state", sync_state)
    fake.router.add_get("/workbench/content/day{day}.json", content)
    server = TestServer(fake)
    await server.start_server()
    base = str(server.make_url("")).rstrip("/")

    async def body(client, stores, _):
        st = await (await client.get("/admin/workbench/status", headers=AUTH)).json()
        check("E2 workbench status: fresh rev + read_only flag",
              st["available"] and st["provenance"]["rev"] == 9
              and st["read_only"] is True)
        cur = await (await client.get("/admin/workbench/current", headers=AUTH)).json()
        check("E3 current lesson via the read-only adapter",
              cur["available"] and cur["data"]["lesson_id"] == 12
              and cur["provenance"]["rev"] == 9)
        pr = await (await client.get("/admin/workbench/progress", headers=AUTH)).json()
        check("E4 progress: counts from the authoritative state only",
              pr["data"]["passed"] == 1 and pr["data"]["review_required"] == 1
              and pr["data"]["due_count"] == 1)
        rv = await (await client.get("/admin/workbench/reviews", headers=AUTH)).json()
        check("E5 reviews scope strips other fields", "passed" not in rv["data"]
              and rv["data"]["due_count"] == 1)
        # interaction log: the adapter only ever issued GETs (no write path exists)
        check("E6 adapter is GET-only (fake server saw only GETs)",
              bool(calls) and all(m == "GET" for m in calls), calls)
    try:
        await with_client(body, tmpdir, workbench_url=base, name="wb_readonly")
    finally:
        await server.close()


async def t_behavior(tmpdir):
    async def body(client, stores, _):
        act = await (await client.get("/admin/behavior/active", headers=AUTH)).json()
        check("F1 behavior active: policy version + taxonomies + note",
              act["available"] and act["policy_version"] == 1
              and len(act["activities"]) == 8 and len(act["temp_intents"]) == 6
              and "never stored" in act["note"])
        check("F2 vocab policy header comes from the policy",
              act["vocab_policy_header"] == "VOCABULARY ACCURACY POLICY (hard rules):")
        rt0 = await (await client.get("/admin/behavior/routing", headers=AUTH)).json()
        check("F3 routing with no sessions", rt0["count"] == 0)

        fake_behavior = SimpleNamespace(snapshot=lambda: {
            "activity": "PRACTICE_CONVERSATION", "scenario": "hotel",
            "temporary_intent": "EXPLAIN_WORD", "language_override": None,
            "speed": "slow", "difficulty": "normal", "pending_apply": False,
            "policy_version": 1, "recent_word": "NEVER-EXPOSE-THIS-WORD",
            "stats": {"decisions": 4, "hot_applies": 3}})

        class _FakeConn:                     # plain class: weakref-able (registry)
            pass

        fake_conn = _FakeConn()
        fake_conn.conn_ordinal = 1001
        fake_conn.state = "LISTENING"
        fake_conn.tts_active = False
        fake_conn.pacer_task = None
        fake_conn.qwen = None
        fake_conn.behavior = fake_behavior
        admin_sessions.register(fake_conn)
        try:
            rt = await (await client.get("/admin/behavior/routing", headers=AUTH)).json()
            row = rt["sessions"][0]
            check("F4 routing row carries bounded metadata only",
                  rt["count"] == 1 and row["behavior"]["activity"] == "PRACTICE_CONVERSATION"
                  and row["behavior"]["stats"]["decisions"] == 4)
            check("F5 raw recent word never leaves the link",
                  "recent_word" not in row["behavior"]
                  and "NEVER-EXPOSE-THIS-WORD" not in json.dumps(rt))
            act2 = await (await client.get("/admin/behavior/active", headers=AUTH)).json()
            check("F6 routing stats aggregate across sessions",
                  act2["routing_stats"].get("decisions") == 4
                  and act2["active_sessions"] == 1)
        finally:
            admin_sessions.discard(fake_conn)

        aud = await (await client.get("/admin/audit", headers=AUTH)).json()
        check("F7 admin audit exists (bounded, sanitized shape)",
              isinstance(aud["audit"], list)
              and all(set(a) == {"ts", "action", "actor", "subject", "changed", "result"}
                      for a in aud["audit"]))
    await with_client(body, tmpdir, name="behavior")


async def t_audit_flow(tmpdir):
    async def body(client, stores, _):
        await client.post("/admin/policy/apply", headers=AUTH,
                          json={"policy": {"persona": {"name": "小美"}}, "confirm": True})
        await client.post("/admin/memory/clear-category", headers=AUTH,
                          json={"entity": "habit", "confirm": "habit"})
        aud = await (await client.get("/admin/audit", headers=AUTH)).json()
        actions = [a["action"] for a in aud["audit"]]
        check("G1 writes are audited (policy_apply, memory_clear_category)",
              "policy_apply" in actions and "memory_clear_category" in actions)
        blob = json.dumps(aud["audit"])
        check("G2 audit carries no values / secrets / transcripts",
              "小美" not in blob and FIX_TOKEN not in blob
              and "password" not in blob.lower() and "transcript" not in blob.lower())
    await with_client(body, tmpdir, name="audit")


async def amain():
    tmp = tempfile.mkdtemp(prefix="admin2-")
    Path(tmp, "admin_api_token").write_text(FIX_TOKEN + "\n")
    os.chmod(Path(tmp, "admin_api_token"), 0o600)
    await t_routes(tmp)
    await t_policy(tmp)
    await t_memory(tmp)
    await t_knowledge(tmp)
    await t_workbench_disabled(tmp)
    await t_workbench_readonly(tmp)
    await t_behavior(tmp)
    await t_audit_flow(tmp)

    total = len(RESULTS)
    passed = sum(1 for _, ok_, _ in RESULTS if ok_)
    print("=" * 70)
    print("ADMIN2_TESTS: %d checks, %d PASS, %d FAIL" % (total, passed, total - passed))
    for name, ok_, detail in RESULTS:
        if not ok_:
            print("  FAILED: %s %s" % (name, detail))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))