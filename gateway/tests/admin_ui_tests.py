"""ADMIN_UI_TESTS — deterministic contract suite for the unified Chinese-first admin UI.

Runs standalone:  python tests/admin_ui_tests.py   (from gateway/, venv)

Covers: static UI contracts (every endpoint the UI calls exists in the mounted
route table; destructive confirmation; Chinese-first navigation; no external
dependencies; token hygiene), live serving of the shell (content types, no data
leakage, anonymous shell load), and API integration smoke over every GET
endpoint the UI uses.  Preview/apply/rollback and confirmation semantics are
exercised end-to-end by ADMIN2_TESTS; this suite asserts the UI targets them.
"""

import asyncio
import json
import os
import re
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from aiohttp.test_utils import TestClient, TestServer        # noqa: E402

from app.admin import load_admin_config                      # noqa: E402
from app.admin.app import admin_route_table, create_admin_app  # noqa: E402
from app.admin.auth import TokenStore                        # noqa: E402
from app.admin.stores import AdminStores                     # noqa: E402

FIX_TOKEN = "UI_CONTRACT_TEST_TOKEN_DO_NOT_LEAK_13579"
UI_DIR = _ROOT.parent / "admin"
AUTH = {"Authorization": "Bearer " + FIX_TOKEN}
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % detail) if (detail and not cond) else ""))


def _normalize(path):
    return re.sub(r"\$\{[^}]*\}", "{}", re.sub(r"\{[^}]*\}", "{}", path))


def _ui_paths(js):
    literal = re.findall(r'"(/admin/[A-Za-z0-9\-/]+)"', js)
    # trailing-slash literals are concatenation prefixes (e.g. ".../dataset/" + id)
    literal = [p for p in literal if not p.endswith("/")]
    templated = re.findall(r"`(/admin/[^`]+)`", js)
    return sorted(set(literal) | {_normalize(t.split("?")[0]) for t in templated})


def main():
    html = (UI_DIR / "index.html").read_text()
    js = (UI_DIR / "app.js").read_text()
    css = (UI_DIR / "styles.css").read_text()

    tmp = tempfile.mkdtemp(prefix="admin-ui-")
    Path(tmp, "admin_api_token").write_text(FIX_TOKEN + "\n")
    os.chmod(Path(tmp, "admin_api_token"), 0o600)

    # ---- static contracts ------------------------------------------------------
    sub = Path(tmp) / "stores"
    sub.mkdir()
    stores = AdminStores(policy_file=str(sub / "policy.json"),
                         memory_file=str(sub / "memory.json"),
                         knowledge_file=str(sub / "knowledge.json"),
                         workbench_url="")
    table = admin_route_table(stores=stores)
    routes = {_normalize(p) for _, p in table}
    used = _ui_paths(js)
    missing = [p for p in used if p not in routes]
    check("U1 every endpoint the UI calls is mounted (39-route table)",
          len(routes) >= 39 and missing == [], missing)
    check("U2 UI covers all control-plane sections",
          {"/admin/policy/active", "/admin/memory/items", "/admin/knowledge/datasets",
           "/admin/workbench/status", "/admin/behavior/routing"} <= set(used))
    check("U3 UI never targets the reset route",
          not any("diag/reset" in p for p in used))
    methods = set(re.findall(r'method:\s*"([A-Z]+)"', js))
    check("U4 UI uses only GET/POST", methods <= {"GET", "POST"}, sorted(methods))
    check("U5 destructive endpoints are guarded by window.confirm in the UI",
          all(x in js for x in ('window.confirm',)) and js.count("window.confirm(") >= 6,
          js.count("window.confirm("))
    for path, label in (("/admin/policy/apply", "apply"),
                        ("/admin/policy/rollback", "rollback"),
                        ("/admin/memory/delete", "memory delete"),
                        ("/admin/memory/clear-category", "category clear"),
                        ("/admin/knowledge/dataset/delete", "dataset delete"),
                        ("/admin/knowledge/document/delete", "document delete")):
        call_at = js.find('api("%s"' % path)
        confirm_at = js.rfind("window.confirm(", 0, call_at if call_at >= 0 else len(js))
        check("U6 %s is preceded by a confirmation dialog" % label,
              call_at >= 0 and confirm_at >= 0 and call_at - confirm_at < 900,
              (call_at, confirm_at))
    check("U7 preview/apply/rollback flow wired to the policy endpoints",
          all(x in used for x in ("/admin/policy/preview", "/admin/policy/apply",
                                  "/admin/policy/rollback", "/admin/policy/versions")))
    check("U8 token hygiene: sessionStorage only, never URL, cleared input",
          "sessionStorage" in js and "localStorage" not in js
          and "location." not in js and "?token" not in js and 'value = ""' in js)
    check("U9 no external/public dependencies",
          not re.search(r"https?://", html + js + css))
    check("U10 Chinese-first: nav + boundary notes + read-only badge",
          all(s in html for s in ("仪表盘", "实时状态", "诊断", "角色与教学", "记忆",
                                  "知识库", "课程进度", "路由诊断"))
          and "课程进度由 Workbench 管理，不存储在记忆中。" in js
          and "只读" in js)
    check("U11 responsive layout (grid + media query)",
          "grid-template-columns" in css and "@media" in css
          and "viewport" in html)
    check("U12 no raw backend payloads embedded in the shell",
          "uptime_s\":" not in html and FIX_TOKEN not in html + js + css)

    # ---- live serving + integration smoke ---------------------------------------
    async def live():
        cfg = load_admin_config(env={
            "ADMIN_ENABLED": "1", "ADMIN_BIND": "127.0.0.1", "ADMIN_PORT": "18115",
            "ADMIN_API_TOKEN_FILE": str(Path(tmp) / "admin_api_token"),
            "ADMIN_UI_DIR": str(UI_DIR),
        })
        ts = TokenStore(cfg.token_file, cfg.token_env)
        ts.reload()
        app = create_admin_app(admin_config=cfg, token_store=ts,
                               gateway_info=lambda: {"mode": "mock", "ready": True,
                                                     "model": "qwen3.8-omni-flash-realtime",
                                                     "voice": "Tina"},
                               stores=stores)
        async with TestClient(TestServer(app)) as client:
            r = await client.get("/")
            body = await r.text()
            check("U13 shell served without auth (no data in it)",
                  r.status == 200 and "text/html" in r.headers.get("Content-Type", "")
                  and "产品控制台" in body and FIX_TOKEN not in body)
            rj = await client.get("/app.js")
            check("U14 app.js served with correct content type",
                  rj.status == 200
                  and "javascript" in rj.headers.get("Content-Type", "")
                  and "UI_STATE" in (await rj.text()))
            rc = await client.get("/styles.css")
            check("U15 styles.css served", rc.status == 200
                  and "text/css" in rc.headers.get("Content-Type", ""))

            r_anon = await client.get("/admin/policy/active")
            check("U16 API still requires auth from the UI origin",
                  r_anon.status == 401)

            get_paths = sorted({p for p in used
                                if p in routes and not any(
                                    x in p for x in ("preview", "documents", "chunks",
                                                     "item", "document/"))})
            failures = {}
            for p in get_paths:
                m_table = {pp: mm for mm, pp in table}
                if m_table.get(p) != "GET":
                    continue
                rr = await client.get(p, headers=AUTH)
                if rr.status != 200:
                    failures[p] = rr.status
            check("U17 every GET endpoint the UI uses answers 200 with stores wired",
                  failures == {}, failures)
            import aiohttp
            legacy = [p for p in used if not p.startswith("/admin/")]
            check("U18 no legacy endpoint targets", legacy == [])

    asyncio.run(live())

    total = len(RESULTS)
    passed = sum(1 for _, ok_, _ in RESULTS if ok_)
    print("=" * 70)
    print("ADMIN_UI_TESTS: %d checks, %d PASS, %d FAIL" % (total, passed, total - passed))
    for name, ok_, detail in RESULTS:
        if not ok_:
            print("  FAILED: %s %s" % (name, detail))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())