"""ADMIN-1 deterministic test suite (API + auth + security + read-only + UI acceptance).

Covers the ADMIN-1 authorization Phases 2, 3, 7, 8 and the mechanically checkable parts of
Phase 10.  No network beyond loopback; no NAS, no manager-api, no workbench, no DB.

Local run (libopus is only needed because the audio app is imported for the isolation check):

    DYLD_LIBRARY_PATH=/tmp/opus/lib gateway/.venv/bin/python gateway/tests/admin1_tests.py
"""

import asyncio
import ast
import json
import logging
import os
import re
import sys
import tempfile
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from aiohttp.test_utils import TestClient, TestServer          # noqa: E402

from app import diag, main as app_main                          # noqa: E402
from app.admin import load_admin_config                         # noqa: E402
from app.admin import service as admin_service                  # noqa: E402
from app.admin.app import admin_route_table, create_admin_app   # noqa: E402
from app.admin.auth import TokenStore                            # noqa: E402
from app.admin.registry import sessions as admin_sessions        # noqa: E402
from app.counters import counters                                # noqa: E402

SIX = ["/admin/health", "/admin/version", "/admin/sessions",
       "/admin/metrics", "/admin/telemetry", "/admin/diag-summary"]
UI_DIR = _ROOT.parent / "admin"      # repo layout: <repo>/admin (the admin app's default)

# adversarial fixtures (Phase 7): none of these may ever appear in an admin response
FIX_TOKEN = "TEST_BEARER_TOKEN_DO_NOT_LEAK_0123456789"
FIX_TRANSCRIPT = "learner transcript private sentence"
FIX_RAW_SID = "raw-session-id-abc123"
FIX_RAW_RID = "raw-response-id-xyz789"
FIX_WORKSPACE = "ws-fixture-workspace-id-123456"
FIX_CAPTURE_DIR = "/private/tmp/capture-private-dir-fixture"

_results = []


def check(name, cond, detail=""):
    ok = bool(cond)
    _results.append(ok)
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       "" if ok else "  <- %r" % (detail,)))
    return ok


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


def _admin_config(tmpdir, ui_dir=UI_DIR, enabled=True):
    return load_admin_config(env={
        "ADMIN_ENABLED": "1" if enabled else "0",
        "ADMIN_BIND": "127.0.0.1",
        "ADMIN_PORT": "18112",
        "ADMIN_API_TOKEN_FILE": str(Path(tmpdir) / "admin_api_token"),
        "ADMIN_UI_DIR": str(ui_dir),
    })


def _hostile_gateway_info():
    # proves the health allowlist: extra keys must never be copied through
    return {"mode": "real", "ready": True, "workspace_id": FIX_WORKSPACE,
            "token": FIX_TOKEN, "endpoint": "wss://" + FIX_WORKSPACE + ".example"}


def _hostile_diag_snapshot():
    return {
        "enabled": True, "uptime_s": 12.5, "journal_entries": 7,
        "assertions": {"MULTIPLE_PACER_VIOLATION": 3}, "assertions_total": 3,
        "generation_count": 4, "connection_count": 1,
        "per_conn": {"sid": FIX_RAW_SID, "active_gen": 3, "active_resp_id": FIX_RAW_RID,
                     "live_pacers": [3], "invalidated_gens": [2], "tts_gen": None,
                     "conns_closed": 0},
        "connections": {FIX_RAW_SID: {"sid": FIX_RAW_SID}},
        "send_intervals_ms": {"p50": 20.0, "p95": 21.0, "min": 15.1, "max": 24.0, "n": 100},
        "steady_segments": [{"frames": 250, "rate": 49.99}],
        "transcripts": [{"input": FIX_TRANSCRIPT, "output": FIX_TRANSCRIPT}],
        "journal_tail": [{"step": "on_delta", "text": FIX_TRANSCRIPT}],
        "send_intents": [{"resp_id": FIX_RAW_RID, "frame_seq": 1}],
        "send_timeline": [{"t": 1.0}],
    }


def _hostile_capture_info():
    return {"enabled": True, "dir": FIX_CAPTURE_DIR, "qwen_pcm24.raw": 1234,
            "sent_opus.bin": 5678, "sent_opus.jsonl": 91011}


async def with_client(fn, tmpdir, *, ui_dir=UI_DIR, monkey_diag=True):
    """Start the ADMIN app in-process and hand a TestClient to ``fn``."""
    cfg = _admin_config(tmpdir, ui_dir=ui_dir)
    store = TokenStore(cfg.token_file, cfg.token_env)
    store.reload()
    app = create_admin_app(admin_config=cfg, token_store=store,
                           gateway_info=_hostile_gateway_info)
    orig_provider, orig_capture = diag.SNAPSHOT_PROVIDER, diag.capture_info
    if monkey_diag:
        diag.SNAPSHOT_PROVIDER = _hostile_diag_snapshot
        diag.capture_info = _hostile_capture_info
    try:
        async with TestClient(TestServer(app)) as client:
            return await fn(client, store)
    finally:
        diag.SNAPSHOT_PROVIDER, diag.capture_info = orig_provider, orig_capture


# ---- Phase 0/1: isolation + defaults --------------------------------------

def test_defaults_and_isolation():
    env_cfg = load_admin_config(env={})
    check("default ADMIN_ENABLED=0", env_cfg.enabled is False, env_cfg)
    check("default ADMIN_BIND=127.0.0.1", env_cfg.bind == "127.0.0.1", env_cfg.bind)
    check("default ADMIN_PORT=8112", env_cfg.port == 8112, env_cfg.port)

    audio_routes = sorted({r.resource.canonical for r in app_main.create_app(
        app_main.load_config()).router.routes()})
    check("audio app routes unchanged (7, no admin routes)",
          audio_routes == sorted(["/health", "/xiaozhi/ota/", "/xiaozhi/v1/",
                                  "/diag", "/diag/reset", "/diag/capture"]),
          audio_routes)

    tmp = tempfile.mkdtemp(prefix="admin1-iso-")
    cfg = _admin_config(tmp)
    store = TokenStore(cfg.token_file, cfg.token_env)
    store.reload()
    admin_app = create_admin_app(admin_config=cfg, token_store=store,
                                 gateway_info=lambda: {})
    paths = sorted({r.resource.canonical for r in admin_app.router.routes()})
    check("admin app mounts exactly the allowlist",
          paths == sorted([p for _, p in admin_route_table()]), paths)
    forbidden = ["/xiaozhi/v1/", "/xiaozhi/ota/", "/diag", "/diag/reset", "/diag/capture",
                 "/health"]
    check("admin app mounts no audio/OTA/diag/health route",
          not (set(forbidden) & set(paths)), sorted(set(forbidden) & set(paths)))
    check("no /admin write or reset route exists",
          not any(p.startswith("/admin/") and p not in SIX for p in paths),
          [p for p in paths if p.startswith("/admin/") and p not in SIX])


async def test_disabled_listener_starts_nothing():
    tmp = tempfile.mkdtemp(prefix="admin1-off-")
    runners = await admin_service.start_admin_listener(
        admin_config=_admin_config(tmp, enabled=False), gateway_info=lambda: {})
    check("ADMIN_ENABLED=0 starts no listener", runners == [], runners)

    # enabled but no token material -> fail closed (no listener), no token in logs
    cap = LogCapture()
    logging.getLogger().addHandler(cap)
    try:
        empty = Path(tmp) / "empty.txt"
        empty.write_text("")
        cfg = load_admin_config(env={
            "ADMIN_ENABLED": "1", "ADMIN_API_TOKEN_FILE": str(empty),
            "ADMIN_API_TOKEN": "", "ADMIN_UI_DIR": str(UI_DIR)})
        runners = await admin_service.start_admin_listener(
            admin_config=cfg, gateway_info=lambda: {})
    finally:
        logging.getLogger().removeHandler(cap)
    check("ADMIN_ENABLED=1 without token fails closed (no listener)", runners == [], runners)
    check("fail-closed log carries no secret", not any(FIX_TOKEN in r for r in cap.records),
          cap.records[:2])


# ---- Phase 2/7: authentication -------------------------------------------

async def test_auth(tmp):
    async def body(client, store):
        anon = {}
        for p in SIX:
            r = await client.get(p)
            anon[p] = r.status
        check("anonymous /admin/* -> 401 (all six)", set(anon.values()) == {401}, anon)

        bad = {}
        for p in SIX:
            r = await client.get(p, headers={"Authorization": "Bearer wrong-token"})
            bad[p] = r.status
        check("invalid token -> 401 (all six)", set(bad.values()) == {401}, bad)

        a1 = await client.get("/admin/health")
        a2 = await client.get("/admin/health", headers={"Authorization": "Bearer wrong"})
        b1, b2 = await a1.json(), await a2.json()
        b1.pop("request_id", None)
        b2.pop("request_id", None)
        check("401 bodies are identical apart from the request id (no oracle)", b1 == b2, (b1, b2))

        ok = {}
        hdr = {"Authorization": "Bearer " + FIX_TOKEN}
        for p in SIX:
            r = await client.get(p, headers=hdr)
            ok[p] = r.status
            if r.status == 200:
                await r.json()
        check("valid token -> 200 (all six)", set(ok.values()) == {200}, ok)

        r = await client.get("/admin/health", headers={"Authorization": FIX_TOKEN})
        check("malformed Authorization header -> 401", r.status == 401, r.status)
        r = await client.get("/admin/health", headers={"Authorization": "bearer " + FIX_TOKEN})
        check("lowercase scheme accepted", r.status == 200, r.status)
        return None
    return await with_client(body, tmp)


# ---- Phase 7/8: leak + schema + read-only ---------------------------------

async def test_contracts(tmp):
    async def body(client, store):
        hdr = {"Authorization": "Bearer " + FIX_TOKEN}
        bodies = {}
        for p in SIX:
            r = await client.get(p, headers=hdr)
            bodies[p] = await r.json()

        blob = json.dumps(bodies, ensure_ascii=False)
        for label, needle in (("bearer token", FIX_TOKEN),
                              ("transcript fixture", FIX_TRANSCRIPT),
                              ("raw session id", FIX_RAW_SID),
                              ("raw response id", FIX_RAW_RID),
                              ("workspace id", FIX_WORKSPACE),
                              ("capture private dir", FIX_CAPTURE_DIR),
                              ("token file path", store._file)):
            check("no %s in any response" % label, needle not in blob, label)
        for key in ("transcripts", "journal_tail", "send_intents", "send_timeline"):
            check("diag-summary omits %r (allowlist)" % key,
                  key not in json.dumps(bodies["/admin/diag-summary"]))

        # bounded + deterministic schemas
        again = {}
        for p in SIX:
            r = await client.get(p, headers=hdr)
            again[p] = await r.json()
        for p in SIX:
            check("%s key set deterministic" % p,
                  sorted(bodies[p].keys()) == sorted(again[p].keys()),
                  (sorted(bodies[p].keys()), sorted(again[p].keys())))
            check("%s payload bounded (<16KB)" % p,
                  len(json.dumps(bodies[p])) < 16384, len(json.dumps(bodies[p])))
        check("telemetry honest (unavailable + reason)",
              bodies["/admin/telemetry"].get("available") is False
              and bodies["/admin/telemetry"].get("reason") == "server_side_aggregator_unavailable",
              bodies["/admin/telemetry"])
        check("telemetry exposes no fake zero metrics",
              not any(k for k in bodies["/admin/telemetry"] if k.endswith("_count")),
              bodies["/admin/telemetry"])
        v = bodies["/admin/version"]
        check("version: image_digest honest null+source",
              v.get("image_digest") is None and v.get("image_digest_source") == "unavailable", v)
        check("version never returns the token", FIX_TOKEN not in json.dumps(v))
        h = bodies["/admin/health"]
        check("health reports admin auth configured",
              (h.get("admin") or {}).get("auth_configured") is True, h.get("admin"))
        check("health carries no extra gateway-info keys",
              not ({"workspace_id", "token", "endpoint"} & set(json.dumps(h).split('"'))), h)
        check("health exposes no secret paths",
              "/secrets" not in json.dumps(h) and FIX_CAPTURE_DIR not in json.dumps(h))
        s = bodies["/admin/sessions"]
        check("sessions list is sanitized (count present, no raw ids)",
              "count" in s and s["count"] == 0, s)
        d = bodies["/admin/diag-summary"]
        check("diag-summary keeps aggregates only",
              d.get("enabled") is True and d.get("assertions_total") == 3
              and d["capture"] == {"enabled": True,
                                   "bytes": {"qwen_pcm24.raw": 1234, "sent_opus.bin": 5678,
                                             "sent_opus.jsonl": 91011}}, d.get("capture"))
        check("diag-summary has no reset surface", d.get("resettable") is False)

        # read-only proof: full counter + diag snapshots unchanged by the six calls
        before, before_diag = counters.snapshot(), diag.SNAPSHOT_PROVIDER()
        before_sessions = admin_sessions.count()
        for p in SIX:
            await client.get(p, headers=hdr)
        after = counters.snapshot()
        check("no endpoint mutates gateway counters (uptime excluded)",
              {k: v for k, v in after.items() if k != "uptime_s"}
              == {k: v for k, v in before.items() if k != "uptime_s"},
              sorted(k for k in after if after[k] != before.get(k)))
        check("no endpoint mutates diagnostics",
              diag.SNAPSHOT_PROVIDER() == before_diag)
        check("no endpoint mutates the session registry",
              admin_sessions.count() == before_sessions)

        # unknown / traversal routes
        for p in ("/admin/env", "/admin/config", "/admin/debug", "/admin/../etc/passwd",
                  "/admin/%2e%2e/etc/passwd", "/admin/health/../../secret"):
            r = await client.get(p, headers=hdr)
            check("%s is rejected" % p, r.status in (400, 403, 404), r.status)
        return None
    return await with_client(body, tmp)


# ---- log hygiene ----------------------------------------------------------

async def test_logs_clean(tmp):
    cap = LogCapture()
    logging.getLogger().addHandler(cap)
    try:
        async def body(client, store):
            for p in SIX:
                await client.get(p)
                await client.get(p, headers={"Authorization": "Bearer wrong"})
                await client.get(p, headers={"Authorization": "Bearer " + FIX_TOKEN})
            return None
        await with_client(body, tmp)
    finally:
        logging.getLogger().removeHandler(cap)
    joined = "\n".join(cap.records)
    check("token never appears in logs", FIX_TOKEN not in joined)
    check("no secret values echoed in logs", FIX_TRANSCRIPT not in joined)
    check("auth rejections are logged without the token",
          any("admin auth rejected" in r for r in cap.records), cap.records[:2])


# ---- static source guards (read-only by construction) ---------------------

def test_source_guards():
    offenders = []
    for path in sorted((_ROOT / "app" / "admin").glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in ("inc", "set_gauge", "set_state"):
                if isinstance(node.value, ast.Name) and node.value.id == "counters":
                    offenders.append((path.name, node.attr))
            if isinstance(node, ast.Name) and node.id in ("subprocess",):
                offenders.append((path.name, node.id))
        text = path.read_text()
        for token in ("subprocess", "os.system", "urllib", "socket.socket", "Popen"):
            if token in text:
                offenders.append((path.name, token))
    check("admin package never writes counters / shells out / opens sockets",
          not offenders, offenders)

    views = (_ROOT / "app" / "admin" / "views.py").read_text()
    # AST-based: those keys must never be *referenced* (comments/docstrings exempt)
    hostile = {"journal_tail", "send_intents", "send_timeline", "transcripts"}
    used = set()
    for node in ast.walk(ast.parse(views)):
        if isinstance(node, ast.Attribute):
            used.add(node.attr)
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            used.add(str(node.slice.value))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            used.add(node.value)
    check("diag-summary never references hostile keys (allowlist-built)",
          not (hostile & used), sorted(hostile & used))
    check("capture dir is never copied into responses",
          "capture_info()" in views and 'cap_raw.get("dir"' not in views)

    ws = (_ROOT / "app" / "ws.py").read_text()
    check("registry hooks are lifecycle-only in ws.py",
          ws.count("admin_sessions.") == 2, ws.count("admin_sessions."))



def _strip_js_comments(src):
    """Remove /* */ and // comments so source guards test the CODE, not the prose."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", src)


def test_ui_acceptance():
    html = (UI_DIR / "index.html").read_text()
    js = _strip_js_comments((UI_DIR / "app.js").read_text())
    css = (UI_DIR / "styles.css").read_text()
    check("UI shell carries no backend data",
          "uptime_s\":" not in html and FIX_TOKEN not in html and "ws_connections\":" not in html)
    check("token kept in sessionStorage only",
          "sessionStorage" in js and "localStorage" not in js)
    check("token never placed in URL/query", "location." not in js and "?token" not in js)
    check("token rendered back never", "value = \"\"" in js)
    check("clear-token action exists", "clearToken" in html and "clearToken" in js)
    used = sorted(set(re.findall(r'"(/admin/[A-Za-z0-9\-/]+)"', js)))
    check("UI only calls /admin endpoints (no legacy paths)",
          len(used) >= 20 and all(p.startswith("/admin/") for p in used), used)
    forbidden = ("/admin/instruction", "/admin/language-policy", "/admin/provider",
                 "/admin/model", "/admin/voice", "/admin/memory-policy",
                 "/admin/knowledge-assignment", "/admin/session/reload", "/admin/diag/reset")
    hit = [x for x in forbidden if x in js or x in html]
    check("UI references no frozen / reset endpoint", not hit, hit)
    check("destructive actions require an explicit confirmation dialog",
          js.count("window.confirm(") >= 6, js.count("window.confirm("))
    check("common actions use forms (no raw JSON required)",
          js.count("el(\"input\")") >= 6 and js.count("el(\"textarea\")") >= 2
          and js.count("el(\"select\")") >= 2)
    check("Chinese-first navigation covers the seven sections",
          all(s in html for s in ("仪表盘", "实时状态", "诊断", "角色与教学", "记忆",
                                  "知识库", "课程进度"))
          and "路由诊断" in html)
    check("memory page states the Workbench boundary explicitly",
          "课程进度由 Workbench 管理，不存储在记忆中。" in js)
    check("workbench page carries the read-only badge", "只读" in js)
    check("telemetry-unavailable state is explicit in Chinese",
          "遥测" in js and "暂不可用" in js)
    check("all eight UI states are implemented",
          all(s in js for s in ("AUTH_REQUIRED", "AUTH_FAILED", "UPSTREAM_UNAVAILABLE",
                                "HEALTHY", "DEGRADED", "ERROR", "EMPTY", "LOADING")))
    check("no legacy manager-api / direct sync integration in the UI",
          not any(t in js for t in ("manager-api", "sync/state", "ielts")))
    check("request id shown on errors", "request_id" in js)
    check("no external/public dependencies in the UI",
          not re.search(r"https?://", html + js + css))
    check("CSS served with the shell", "styles.css" in html and len(css) > 500)


# ---- runner ---------------------------------------------------------------

async def amain():
    test_defaults_and_isolation()
    await test_disabled_listener_starts_nothing()
    tmp = tempfile.mkdtemp(prefix="admin1-")
    Path(tmp, "admin_api_token").write_text(FIX_TOKEN + "\n")
    os.chmod(Path(tmp, "admin_api_token"), 0o600)
    await test_auth(tmp)
    await test_contracts(tmp)
    await test_logs_clean(tmp)
    test_source_guards()
    test_ui_acceptance()
    total, passed = len(_results), sum(_results)
    print("\nADMIN1_TESTS: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))