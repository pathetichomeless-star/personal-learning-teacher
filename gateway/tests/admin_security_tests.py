"""ADMIN_SECURITY_TESTS — deterministic security suite for the admin plane (ADMIN-1 + ADMIN-2).

Runs standalone:  python tests/admin_security_tests.py   (from gateway/, venv)

Covers: bearer auth on EVERY admin route (anonymous/invalid → 401 with an
identical body — no oracle), fail-closed behaviour (no stores → routes absent;
store not configured → 503; no token → no listener), input hardening (invalid
JSON, oversized body, bad query ints, missing confirmation tokens), token
non-leakage in bodies/logs, sanitized error mapping, no reset route, workbench
GET-only, file permissions of written stores, and the constant-time compare
implementation.
"""

import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from aiohttp.test_utils import TestClient, TestServer          # noqa: E402

from app.admin import load_admin_config                        # noqa: E402
from app.admin import service as admin_service                 # noqa: E402
from app.admin.app import admin_route_table, create_admin_app  # noqa: E402
from app.admin.auth import TokenStore                          # noqa: E402
from app.admin.stores import AdminStores                       # noqa: E402
from app.admin.registry import sessions as admin_sessions      # noqa: E402

FIX_TOKEN = "SEC_TEST_BEARER_TOKEN_DO_NOT_LEAK_24680"
FIX_TRANSCRIPT = "learner private sentence never to leak"
UI_DIR = _ROOT.parent / "admin"
AUTH = {"Authorization": "Bearer " + FIX_TOKEN}
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % detail) if (detail and not cond) else ""))


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        try:
            self.records.append(record.getMessage() % record.args
                                if record.args else record.getMessage())
        except Exception:                                       # noqa: BLE001
            self.records.append(str(record.msg))


def _cfg(tmpdir, *, enabled=True, token=True):
    tok_path = Path(tmpdir) / "admin_api_token"
    if token and not tok_path.exists():
        tok_path.write_text(FIX_TOKEN + "\n")
        os.chmod(tok_path, 0o600)
    return load_admin_config(env={
        "ADMIN_ENABLED": "1" if enabled else "0",
        "ADMIN_BIND": "127.0.0.1", "ADMIN_PORT": "18114",
        "ADMIN_API_TOKEN_FILE": str(tok_path),
        "ADMIN_API_TOKEN": "",
        "ADMIN_UI_DIR": str(UI_DIR),
    })


def _stores(tmpdir, *, memory=True, knowledge=True, policy=True):
    sub = Path(tmpdir) / "sec_stores"
    sub.mkdir(exist_ok=True)
    return AdminStores(policy_file=str(sub / "policy.json") if policy else "",
                       memory_file=str(sub / "memory.json") if memory else "",
                       knowledge_file=str(sub / "knowledge.json") if knowledge else "",
                       workbench_url="")


def _client(tmpdir, stores):
    cfg = _cfg(tmpdir)
    token_store = TokenStore(cfg.token_file, cfg.token_env)
    token_store.reload()
    app = create_admin_app(admin_config=cfg, token_store=token_store,
                           gateway_info=lambda: {"mode": "mock", "ready": True},
                           stores=stores)
    return app


def _strip_rid(payload):
    if isinstance(payload, dict):
        return {k: v for k, v in payload.items() if k != "request_id"}
    return payload


async def amain():
    tmp = tempfile.mkdtemp(prefix="admin-sec-")
    stores = _stores(tmp)
    app = _client(tmp, stores)
    table = admin_route_table(stores=stores)
    api_paths = [p for _, p in table if p.startswith("/admin/")]

    async with TestClient(TestServer(app)) as client:
        # ---- S1: auth on every route -------------------------------------
        anon = {}
        for p in api_paths:
            r = await client.get(p)
            anon[p] = r.status
        check("S1 anonymous GET -> 401 on every admin route",
              set(anon.values()) == {401}, {k: v for k, v in anon.items() if v != 401})
        post_paths = [p for m, p in table if m == "POST" and p.startswith("/admin/")]
        anon_post = {}
        for p in post_paths:
            r = await client.post(p, json={})
            anon_post[p] = r.status
        check("S1b anonymous POST -> 401 on every write route",
              set(anon_post.values()) == {401},
              {k: v for k, v in anon_post.items() if v != 401})

        bodies = set()
        for token in ("", "Bearer wrong-token", "Bearer "):
            r = await client.get("/admin/policy/active",
                                 headers={"Authorization": token} if token else {})
            bodies.add(json.dumps(_strip_rid(await r.json()), sort_keys=True))
        check("S1c anonymous vs invalid token: identical body (no oracle)",
              len(bodies) == 1 and "unauthorized" in bodies.pop())

        r_ok = await client.get("/admin/health", headers=AUTH)
        check("S1d valid token works on ADMIN-1", r_ok.status == 200)

        # ---- S2: route hygiene -------------------------------------------------
        routes = sorted({r.resource.canonical for r in app.router.routes()})
        check("S2 mounted routes == documented table exactly",
              routes == sorted({p for _, p in table}), routes)
        check("S2b no reset route", "/admin/diag/reset" not in routes)
        wb_posts = [r.resource.canonical for r in app.router.routes()
                    if r.resource.canonical.startswith("/admin/workbench/")
                    and "GET" not in (r.method,)]
        check("S2c workbench paths exist only for GET",
              all(p in routes for p in ("/admin/workbench/status",)) and not wb_posts,
              wb_posts)
        r404 = await client.post("/admin/diag/reset", headers=AUTH)
        check("S2d unknown route -> 404", r404.status == 404)

        # ---- S3: input hardening ----------------------------------------------
        bad_json = await client.post("/admin/policy/apply", headers=AUTH,
                                     data=b"not json")
        check("S3 invalid JSON -> 400 invalid_json",
              bad_json.status == 400
              and (await bad_json.json())["error"] == "invalid_json")
        arr = await client.post("/admin/policy/preview", headers=AUTH, json=["x"])
        check("S3b non-object JSON -> 400", arr.status == 400)
        big = await client.post("/admin/memory/edit", headers=AUTH,
                                data=b"x" * (70 * 1024))
        check("S3c oversized body -> 413", big.status == 413, big.status)
        qi = await client.get("/admin/memory/items?limit=abc", headers=AUTH)
        check("S3d bad query int -> 400 invalid_query",
              qi.status == 400 and (await qi.json())["error"] == "invalid_query")

        destructive = [
            ("/admin/policy/apply", {"policy": {"persona": {"name": "x"}}}),
            ("/admin/policy/rollback", {"version": 1}),
            ("/admin/memory/delete", {"id": "mem_x"}),
            ("/admin/memory/clear-category", {"entity": "habit"}),
            ("/admin/knowledge/dataset/delete", {"id": "ds_x"}),
            ("/admin/knowledge/document/delete", {"id": "doc_x"}),
        ]
        missing = {}
        for p, body in destructive:
            body.setdefault("confirm", False)
            r = await client.post(p, headers=AUTH, json=body)
            missing[p] = (r.status, (await r.json()).get("error"))
        check("S3e every destructive write needs an explicit confirmation token",
              all(s == 400 and e == "confirm_required" for s, e in missing.values()),
              missing)
        wrong_cat = await client.post("/admin/memory/clear-category", headers=AUTH,
                                      json={"entity": "habit", "confirm": "preference"})
        check("S3f mismatched confirmation token refused", wrong_cat.status == 400)

        # ---- S4: leak checks ------------------------------------------------------
        cap = LogCapture()
        logging.getLogger().addHandler(cap)
        try:
            stores.memory.save("profile_fact", "name", "小王")
            await client.get("/admin/policy/active", headers=AUTH)
            await client.post("/admin/policy/apply", headers=AUTH,
                              json={"policy": {"persona": {"name": "小美"}},
                                    "confirm": True})
            await client.get("/admin/memory/items", headers=AUTH)
            await client.post("/admin/memory/edit", headers=AUTH,
                              json={"id": "mem_nope", "value": "x"})
            await client.get("/admin/health", headers=AUTH)
            logs = "\n".join(cap.records)
        finally:
            logging.getLogger().removeHandler(cap)
        check("S4 token never appears in logs", FIX_TOKEN not in logs)
        check("S4b learner values never appear in logs", "小王" not in logs
              and "小美" not in logs, logs[-200:] if ("小王" in logs or "小美" in logs) else "")

        payloads = []
        for p in api_paths:
            r = await client.get(p, headers=AUTH)
            payloads.append(await r.text())
        blob = "\n".join(payloads)
        check("S4c no token / store paths / transcripts in any response",
              FIX_TOKEN not in blob and tmp not in blob
              and FIX_TRANSCRIPT not in blob)
        check("S4d no secret-shaped strings in responses",
              "password" not in blob.lower() and "api_key" not in blob.lower())

        # ---- S5: sanitized errors ---------------------------------------------------
        bad_conf = await client.post("/admin/memory/edit", headers=AUTH,
                                     json={"id": "mem_x", "confidence": "abc"})
        check("S5 bad confidence -> 4xx boundary (never a 500 leak)",
              bad_conf.status == 400
              and (await bad_conf.json())["error"] == "boundary_violation",
              bad_conf.status)
        unknown = await client.post("/admin/memory/edit", headers=AUTH,
                                    json={"id": "mem_missing", "value": "v"})
        check("S5b unknown id in edit -> 400 boundary (safe)",
              unknown.status == 400)

        # ---- S6: store permission + fail-closed ------------------------------------
        pfile = Path(stores.policy.path)
        check("S6 written store files are mode 600",
              pfile.exists() and (os.stat(pfile).st_mode & 0o777) == 0o600)
        check("S6b store availability flags are booleans only",
              all(isinstance(v, bool) for v in stores.describe().values()))

    # stores not configured: routes still mounted, honest 503s
    bare = _stores(tmp, memory=False, knowledge=False, policy=False)
    app_bare = _client(tmp, bare)
    async with TestClient(TestServer(app_bare)) as client2:
        r = await client2.get("/admin/policy/active", headers=AUTH)
        check("S7 unconfigured store -> 503 (fail closed, no fallback data)",
              r.status == 503 and (await r.json())["error"] == "policy_not_configured")
        r2 = await client2.get("/admin/memory/items", headers=AUTH)
        check("S7b memory not configured -> 503", r2.status == 503)
        r3 = await client2.get("/admin/workbench/status", headers=AUTH)
        check("S7c workbench not configured -> available=false", r3.status == 200
              and (await r3.json())["available"] is False)

    # no stores wired at all -> ADMIN-1 surface only (routes absent)
    cfg = _cfg(tmp)
    ts = TokenStore(cfg.token_file, cfg.token_env)
    ts.reload()
    app1 = create_admin_app(admin_config=cfg, token_store=ts,
                            gateway_info=lambda: {})
    async with TestClient(TestServer(app1)) as client3:
        r = await client3.get("/admin/policy/active", headers=AUTH)
        check("S8 without stores the ADMIN-2 routes do not exist (404)",
              r.status == 404)
        r2 = await client3.get("/admin/health", headers=AUTH)
        check("S8b ADMIN-1 six routes still work without stores", r2.status == 200)

    # no token configured -> listener refuses to start (fail closed)
    tmp2 = tempfile.mkdtemp(prefix="admin-sec-notoken-")
    Path(tmp2, "admin_api_token").write_text("")
    runners = await admin_service.start_admin_listener(
        admin_config=_cfg(tmp2, token=False), gateway_info=lambda: {}, stores=stores)
    check("S9 ADMIN_ENABLED=1 without token -> no listener at all", runners == [])

    src = (_ROOT / "app" / "admin" / "auth.py").read_text()
    check("S10 constant-time comparison implemented (hmac.compare_digest)",
          "hmac.compare_digest" in src)

    total = len(RESULTS)
    passed = sum(1 for _, ok_, _ in RESULTS if ok_)
    print("=" * 70)
    print("ADMIN_SECURITY_TESTS: %d checks, %d PASS, %d FAIL" %
          (total, passed, total - passed))
    for name, ok_, detail in RESULTS:
        if not ok_:
            print("  FAILED: %s %s" % (name, detail))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))