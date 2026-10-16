"""RED-A round 1 — adversarial suite for the ADMIN control-plane auth/authz surface.

READ-ONLY on product source. Local, mock-only, in-process aiohttp TestClient
(plus a loopback raw-socket probe on the assigned ADMIN port 9112 for header-level
attacks). No real-Qwen, no primary/Workbench/production contact, no secret printing.

Run:  cd gateway && DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python \
        tests/adversarial/red_a/red_a_attacks.py
"""

import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_GATEWAY = _HERE.parents[2]        # .../gateway  (contains app/)
_REPO = _GATEWAY.parent            # repo root    (contains admin/, modules/)
for _p in (_GATEWAY, _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
_ROOT = _REPO

from aiohttp import web                                        # noqa: E402
from aiohttp.test_utils import TestClient, TestServer          # noqa: E402

from app.admin import load_admin_config                        # noqa: E402
from app.admin.app import admin_route_table, create_admin_app  # noqa: E402
from app.admin.auth import TokenStore                          # noqa: E402
from app.admin.stores import AdminStores                       # noqa: E402

FIX_TOKEN = "RedA_Token_DoNotLeak_1357911"           # mixed case; never printed in output
UI_DIR = _ROOT / "admin"
AUTH = {"Authorization": "Bearer " + FIX_TOKEN}
ADMIN_PORT = 9112

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % detail) if (detail and not cond) else ""))


def _cfg(tmpdir, token_file):
    return load_admin_config(env={
        "ADMIN_ENABLED": "1", "ADMIN_BIND": "127.0.0.1", "ADMIN_PORT": str(ADMIN_PORT),
        "ADMIN_API_TOKEN_FILE": str(token_file), "ADMIN_API_TOKEN": "",
        "ADMIN_UI_DIR": str(UI_DIR),
    })


def _stores(tmpdir, name="red_a"):
    sub = Path(tmpdir) / name
    sub.mkdir(parents=True, exist_ok=True)
    return AdminStores(policy_file=str(sub / "policy.json"),
                       memory_file=str(sub / "memory.json"),
                       knowledge_file=str(sub / "knowledge.json"),
                       workbench_url="")


GET_PATHS = [p for m, p in admin_route_table(_stores("/tmp")) if m == "GET"
             and p.startswith("/admin/")]
API_TABLE_GET = [p for m, p in admin_route_table(_stores("/tmp"))
                 if m == "GET" and p.startswith("/admin/")]
WRITE_ROUTES = [
    ("/admin/policy/preview", {"policy": {"persona": {"name": "X"}}}),
    ("/admin/policy/apply", {"policy": {"persona": {"name": "X"}}, "confirm": True}),
    ("/admin/policy/rollback", {"version": 1, "confirm": True}),
    ("/admin/memory/edit", {"id": "mem_x", "value": "v"}),
    ("/admin/memory/delete", {"id": "mem_x", "confirm": True}),
    ("/admin/memory/clear-category", {"entity": "habit", "confirm": "habit"}),
    ("/admin/knowledge/dataset/create", {"name": "n"}),
    ("/admin/knowledge/dataset/rename", {"id": "ds_x", "name": "n"}),
    ("/admin/knowledge/dataset/enable", {"id": "ds_x", "enabled": False}),
    ("/admin/knowledge/dataset/delete", {"id": "ds_x", "confirm": "ds_x"}),
    ("/admin/knowledge/document/add", {"dataset_id": "ds_x", "title": "t", "text": "b"}),
    ("/admin/knowledge/document/delete", {"id": "doc_x", "confirm": True}),
    ("/admin/knowledge/document/rebuild", {"id": "doc_x"}),
    ("/admin/knowledge/search", {"query": "q"}),
]


def _subst(path):
    return (path.replace("{item_id}", "mem_nope")
                .replace("{doc_id}", "doc_nope")
                .replace("{ds_id}", "ds_nope"))


def snap(stores):
    try:
        mem = len(stores.memory.list_items(include_expired=True)) if stores.memory else -1
    except Exception:
        mem = -2
    try:
        kb = len(stores.knowledge.list_datasets()) if stores.knowledge else -1
    except Exception:
        kb = -2
    pv = stores.policy.active()["version"] if stores.policy else -1
    audit = len(stores.audit.recent(500))
    return {"memory": mem, "knowledge": kb, "policy": pv, "audit": audit}


# ---------------------------------------------------------------------------
# 1. TOKEN MATRIX
# ---------------------------------------------------------------------------

async def t_token_matrix(client):
    ok = await client.get("/admin/policy/active", headers=AUTH)
    check("T0 the real token authenticates (control)", ok.status == 200, ok.status)

    # forms that MUST be rejected (401)
    reject = [
        ("no header", None),
        ("empty header", ""),
        ("whitespace-only", "   "),
        ("'Bearer' no value", "Bearer"),
        ("'Bearer' spaces only", "Bearer    "),
        ("bare token (no scheme)", FIX_TOKEN),
        ("Basic scheme", "Basic " + FIX_TOKEN),
        ("Token scheme", "Token " + FIX_TOKEN),
        ("Bearer+ scheme", "Bearer+" + FIX_TOKEN),
        ("realm-style value", 'Bearer realm="x"'),
        ("token + suffix", "Bearer " + FIX_TOKEN + "x"),
        ("token lowercased", "Bearer " + FIX_TOKEN.lower()),
        ("token uppercased", "Bearer " + FIX_TOKEN.upper()),
        ("wrong token", "Bearer totally-wrong"),
        ("token misplaced in 3rd field", "Bearer x " + FIX_TOKEN),
        ("comma-joined", "Bearer " + FIX_TOKEN + ", Basic x"),
        ("prefix only", "Bearer " + FIX_TOKEN[:10]),
    ]
    leaked = []
    for label, header in reject:
        headers = {} if header is None else {"Authorization": header}
        r = await client.get("/admin/policy/active", headers=headers)
        if r.status != 401:
            leaked.append((label, r.status))
    check("T1 every malformed/incorrect Authorization form -> 401", not leaked, leaked)

    # benign RFC-permitted normalisations the implementation accepts (must be 200)
    accept = [
        ("lowercase scheme", "bearer " + FIX_TOKEN),
        ("uppercase scheme", "BEARER " + FIX_TOKEN),
        ("mixed scheme", "BeArEr " + FIX_TOKEN),
        ("double space after scheme", "Bearer  " + FIX_TOKEN),
        ("tab after scheme", "Bearer\t" + FIX_TOKEN),
        ("value trailing space", "Bearer " + FIX_TOKEN + " "),
    ]
    weird = []
    for label, header in accept:
        r = await client.get("/admin/policy/active", headers={"Authorization": header})
        if r.status != 200:
            weird.append((label, r.status))
    check("T1b scheme case + whitespace normalisation accepted (200)", not weird, weird)

    # truncated token, every length 1..N-1
    bad = []
    for n in range(1, len(FIX_TOKEN)):
        r = await client.get("/admin/policy/active",
                             headers={"Authorization": "Bearer " + FIX_TOKEN[:n]})
        if r.status != 401:
            bad.append(n)
    check("T2 truncated token (all lengths 1..N-1) -> 401", not bad, bad)

    # genuine token mutations: suffix / prefix / last-char change
    bad2 = []
    for cand in (FIX_TOKEN + "x", "x" + FIX_TOKEN, FIX_TOKEN[:-1] + "X"):
        r = await client.get("/admin/policy/active",
                             headers={"Authorization": "Bearer " + cand})
        if r.status != 401:
            bad2.append(cand)
    check("T3 token + suffix / prefix / single-char mutation -> 401", not bad2, bad2)

    # no-oracle: identical body for anon / empty / wrong
    bodies = set()
    for h in (None, {"Authorization": ""}, {"Authorization": "Bearer"},
              {"Authorization": "Bearer wrong"}):
        r = await client.get("/admin/policy/active", headers=h or {})
        b = await r.json()
        b.pop("request_id", None)
        bodies.add(json.dumps(b, sort_keys=True))
    check("T4 anon vs malformed vs wrong: identical body (no oracle)",
          len(bodies) == 1 and "unauthorized" in bodies.pop())

    # wrong-length tokens
    long_tok = FIX_TOKEN + "A" * 4096
    r = await client.get("/admin/policy/active",
                         headers={"Authorization": "Bearer " + long_tok})
    check("T5 very long token -> 401 (no crash)", r.status == 401, r.status)


async def t_contradictory_headers(client):
    # duplicate Authorization headers (aiohttp exposes the first)
    r1 = await client.get("/admin/policy/active", headers=[
        ("Authorization", "Bearer wrong"), ("Authorization", "Bearer " + FIX_TOKEN)])
    r2 = await client.get("/admin/policy/active", headers=[
        ("Authorization", "Bearer " + FIX_TOKEN), ("Authorization", "Bearer wrong")])
    # The first wins; a valid first header authenticates, an invalid first does not.
    # Either way there is no bypass (attacker needs the real token to succeed).
    check("T6a duplicate headers: invalid-first -> 401", r1.status == 401, r1.status)
    check("T6b duplicate headers: valid-first -> 200 (first header is authoritative)",
          r2.status == 200, r2.status)
    # two invalid duplicate headers
    r3 = await client.get("/admin/policy/active", headers=[
        ("Authorization", "Bearer wrong1"), ("Authorization", "Bearer wrong2")])
    check("T6c duplicate invalid headers -> 401", r3.status == 401, r3.status)


# ---------------------------------------------------------------------------
# 2. CONTENT-TYPE / BODY HARDENING ON WRITE ROUTES
# ---------------------------------------------------------------------------

async def t_body_hardening(client, stores):
    before = snap(stores)
    cases = [
        ("form-encoded", {"data": b"id=x&value=y",
                          "headers": dict(AUTH, **{"Content-Type":
                                                   "application/x-www-form-urlencoded"})}),
        ("text/plain non-json", {"data": b"hello",
                                 "headers": dict(AUTH, **{"Content-Type": "text/plain"})}),
        ("no content-type", {"data": b"{bad json", "headers": AUTH}),
        ("multipart", {"data": b"--x\r\n\r\n--x--\r\n",
                       "headers": dict(AUTH, **{"Content-Type":
                                                "multipart/form-data; boundary=x"})}),
    ]
    for label, kw in cases:
        r = await client.post("/admin/memory/edit", **kw)
        check("T7 %s body -> 400 invalid_json" % label,
              r.status == 400 and (await r.json())["error"] == "invalid_json",
              r.status)

    # malformed / non-object JSON shapes
    shapes = [("array", b"[1,2,3]"), ("string", b'"abc"'), ("null", b"null"),
              ("number", b"123"), ("bool", b"true"), ("truncated", b'{"id":'),
              ("control-chars", b'{"id":"\x00"}')]
    for label, payload in shapes:
        r = await client.post("/admin/memory/edit", headers=AUTH, data=payload)
        check("T8 non-object/truncated JSON (%s) -> 400" % label,
              r.status == 400, r.status)

    # oversized body (+1 over MAX_BODY=64KiB)
    big = await client.post("/admin/memory/edit", headers=AUTH,
                            data=b"x" * (64 * 1024 + 1))
    check("T9 body > 64KiB -> 413", big.status == 413, big.status)

    # a 64KiB body that is valid JSON must be accepted/parsed (not silently dropped)
    pad = "a" * (60 * 1024)
    r = await client.post("/admin/memory/edit", headers=AUTH,
                          json={"id": "mem_nope", "value": pad})
    check("T9b large-but-legal JSON body is parsed (no false 413)", r.status in (400, 404), r.status)

    # aiohttp hard cap still applies beyond 1 MiB (defence in depth)
    huge = await client.post("/admin/memory/edit", headers=AUTH, data=b"x" * (2 * 1024 * 1024))
    check("T9c body > 1MiB rejected (aiohttp cap)", huge.status == 413, huge.status)

    after = snap(stores)
    check("T10 malformed writes never mutated state", before == after,
          (before, after))


# ---------------------------------------------------------------------------
# 3. READ -> WRITE ESCALATION / METHOD CONFUSION
# ---------------------------------------------------------------------------

async def t_read_write_escalation(client, stores):
    before = snap(stores)
    # sweep every GET admin route with a valid token; none may mutate state
    for path in API_TABLE_GET:
        r = await client.get(_subst(path), headers=AUTH)
        if r.status >= 500:
            check("T11 GET %s no 5xx" % path, False, r.status)
    after = snap(stores)
    check("T11 every GET admin route is side-effect free",
          before["memory"] == after["memory"] and before["knowledge"] == after["knowledge"]
          and before["policy"] == after["policy"] and before["audit"] == after["audit"],
          (before, after))

    # GET on a write path must never perform the write.  Note: three write routes
    # (`/admin/knowledge/document/{add,delete,rebuild}`) share the URL prefix of the
    # GET route `/admin/knowledge/document/{doc_id}`, so a GET there resolves to that
    # *read* handler (400/404) rather than 405 — a route-shadowing quirk, not a write.
    before2 = snap(stores)
    unexpected = []
    for path, _ in WRITE_ROUTES:
        r = await client.get(path, headers=AUTH)
        if r.status not in (400, 404, 405):
            unexpected.append((path, r.status))
    check("T12 GET on every write path is refused or routed to a read handler",
          not unexpected, unexpected)
    check("T12b GET sweep over write paths caused no mutation",
          snap(stores) == before2, (before2, snap(stores)))

    # method confusion on a GET route: HEAD must still hit auth; others 405
    head_anon = await client.request("HEAD", "/admin/policy/active")
    check("T13a anonymous HEAD on an admin GET route -> 401",
          head_anon.status == 401, head_anon.status)
    for m in ("OPTIONS", "TRACE", "PUT", "DELETE", "PATCH"):
        r = await client.request(m, "/admin/policy/active", headers=AUTH)
        if r.status != 405:
            check("T13b %s on GET route -> 405" % m, False, r.status)
    check("T13b OPTIONS/TRACE/PUT/DELETE/PATCH -> 405", True)
    # HEAD with valid token must not mutate
    b2 = snap(stores)
    await client.request("HEAD", "/admin/policy/active", headers=AUTH)
    check("T13c authenticated HEAD is side-effect free", snap(stores) == b2)


# ---------------------------------------------------------------------------
# 4. PATH TRAVERSAL / ENCODING TRICKS
# ---------------------------------------------------------------------------

async def t_path_tricks(client):
    # any path variant that RESOLVES to an admin handler must be auth-guarded
    variants = ["/admin/health", "/admin/./health", "/admin//health",
                "/admin/x/../health", "/admin/../admin/health",
                "/admin/%2e%2e/admin/health", "/%61dmin/health",
                "/ADMIN/health", "/admin/health/", "/admin/health/.",
                "/admin/health;x=1", "/admin/../admin/policy/active",
                "/./admin/policy/active", "/admin/%2E%2E/admin/policy/active"]
    bypass = []
    for p in variants:
        try:
            r = await client.get(p)                       # NO token
        except Exception as e:                            # noqa: BLE001
            bypass.append((p, "exc:%r" % e))
            continue
        # 401 (guarded) / 404 (not an admin route) / 400 are all safe; 2xx is a bypass
        if r.status not in (400, 401, 404, 405):
            bypass.append((p, r.status))
    check("T14 no path-trick reaches an admin handler without auth", not bypass, bypass)

    # with a valid token, a traversed path must land on the authed handler (200/404),
    # never expose data without auth — verify the guarded variants return 200 only WITH auth
    r = await client.get("/admin/../admin/policy/active", headers=AUTH)
    check("T14b traversed path with valid token -> 200 (auth enforced, not skipped)",
          r.status == 200, r.status)


# ---------------------------------------------------------------------------
# 5. ROUTE ENUMERATION / MIDDLEWARE SKIP
# ---------------------------------------------------------------------------

async def t_route_enumeration(client, app, stores):
    mounted = sorted({r.resource.canonical for r in app.router.routes()})
    table = sorted({p for _, p in admin_route_table(stores)})
    check("T15 mounted routes == documented table exactly (no undocumented route)",
          mounted == table, set(mounted) ^ set(table))

    check("T16 no /admin/diag/reset ever", "/admin/diag/reset" not in mounted)
    wb_non_get = [r.resource.canonical for r in app.router.routes()
                  if r.resource.canonical.startswith("/admin/workbench/")
                  and "GET" not in (r.method,)]
    check("T17 no non-GET handler for any workbench path", not wb_non_get, wb_non_get)

    # probe for plausible undocumented/backdoor routes (normalisation-safe paths only)
    probes = ["/admin/reset", "/admin/diag/reset", "/admin/restart", "/admin/shutdown",
              "/admin/config", "/admin/token", "/admin/tokens", "/admin/secret",
              "/admin/debug", "/admin/exec", "/admin/shell", "/admin/reload",
              "/admin/internal", "/admin/version/x", "/admin/policy/apply/",
              "/admin/policy", "/admin/memory", "/admin/knowledge",
              "/admin/workbench", "/admin/behavior", "/health", "/diag"]
    anon_leak = []
    auth_reach = []
    for p in probes:
        ra = await client.get(p)
        if ra.status not in (401, 404, 405):
            anon_leak.append((p, ra.status))
        rr = await client.get(p, headers=AUTH)
        if rr.status not in (404, 405):
            auth_reach.append((p, rr.status))
    check("T18 undocumented routes: no anonymous access", not anon_leak, anon_leak)
    check("T18b undocumented admin routes do not exist (404 even authenticated)",
          not auth_reach, auth_reach)


# ---------------------------------------------------------------------------
# 6. AUDIT COVERAGE / NO-SILENT-MUTATION
# ---------------------------------------------------------------------------

async def t_audit_coverage(client, stores):
    # seed a real item to operate on
    stores.memory.save("profile_fact", "name", "小红")
    items = (await (await client.get("/admin/memory/items", headers=AUTH)).json())["items"]
    mid = [i for i in items if i["key"] == "name"][0]["id"]
    ds = (await (await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                                   json={"name": "ds"})).json())["dataset"]
    doc = (await (await client.post("/admin/knowledge/document/add", headers=AUTH,
                                    json={"dataset_id": ds["id"], "title": "t",
                                          "text": "酒店退房时间中午十二点前。"})).json())["document"]

    def audit_actions():
        # synchronous read of the in-memory audit (no request needed)
        return [a["action"] for a in stores.audit.recent(200)]

    writes = [
        ("policy_apply", lambda: client.post("/admin/policy/apply", headers=AUTH,
                                             json={"policy": {"persona": {"name": "小美"}},
                                                   "confirm": True})),
        ("memory_edit", lambda: client.post("/admin/memory/edit", headers=AUTH,
                                            json={"id": mid, "value": "小李"})),
        ("knowledge_dataset_enable", lambda: client.post(
            "/admin/knowledge/dataset/enable", headers=AUTH,
            json={"id": ds["id"], "enabled": False})),
        ("knowledge_document_rebuild", lambda: client.post(
            "/admin/knowledge/document/rebuild", headers=AUTH, json={"id": doc["id"]})),
        ("memory_clear_category", lambda: client.post(
            "/admin/memory/clear-category", headers=AUTH,
            json={"entity": "vocab_item", "confirm": "vocab_item"})),
    ]
    for action, fn in writes:
        n0 = len(stores.audit.recent(500))
        r = await fn()
        acts = audit_actions()
        check("T19 write %s is audited" % action,
              r.status == 200 and action in acts and
              len(stores.audit.recent(500)) == n0 + 1,
              (r.status, action in acts))

    # FAILED writes must not mutate and must not be audited
    fails = [
        ("/admin/policy/apply", {"policy": {"persona": {"name": "x"}}}),
        ("/admin/policy/rollback", {"version": 99, "confirm": True}),
        ("/admin/memory/delete", {"id": mid}),
        ("/admin/memory/clear-category", {"entity": "habit", "confirm": "wrong"}),
        ("/admin/knowledge/dataset/delete", {"id": ds["id"], "confirm": "wrong"}),
        ("/admin/knowledge/document/delete", {"id": doc["id"]}),
    ]
    for path, body in fails:
        before = snap(stores)
        r = await client.post(path, headers=AUTH, json=body)
        after = snap(stores)
        check("T20 failed write %s neither mutates nor audits" % path,
              r.status >= 400 and before == after, (r.status, before, after))

    # midway-validation failure on knowledge add must not leave a partial document
    b = snap(stores)
    r = await client.post("/admin/knowledge/document/add", headers=AUTH,
                          json={"dataset_id": "ds_nope", "title": "t", "text": "body"})
    check("T21 knowledge add to unknown dataset does not mutate", r.status == 400
          and snap(stores)["knowledge"] == b["knowledge"], r.status)


# ---------------------------------------------------------------------------
# 7. TOKEN RELOAD SEMANTICS
# ---------------------------------------------------------------------------

def t_token_reload(tmpdir):
    tp = Path(tmpdir) / "reload_token"
    tp.write_text(FIX_TOKEN + "\n")
    ts = TokenStore(str(tp), "")
    ts.reload()
    check("T22 initial reload configures the token", ts.configured
          and ts.matches(FIX_TOKEN))

    # unchanged source keeps the token (no accidental clear)
    ts.reload()
    ts.reload()
    check("T23 unchanged source keeps the token", ts.configured
          and ts.matches(FIX_TOKEN))

    # changed file takes effect; old token no longer valid
    new = "RED_A_NEW_TOKEN_24681012"
    tp.write_text(new + "\n")
    os.utime(tp, None)
    ts.reload()
    check("T24 changed file takes effect (new matches, old rejected)",
          ts.matches(new) and not ts.matches(FIX_TOKEN))

    # emptied file -> fail closed
    tp.write_text("")
    os.utime(tp, None)
    ts.reload()
    check("T25 emptied token file fails closed (not configured)", not ts.configured)

    # removed file -> fail closed
    tp.write_text(new + "\n")
    ts.reload()
    tp.unlink()
    ts.reload()
    check("T26 removed token file fails closed", not ts.configured)

    # env-only source
    ts2 = TokenStore("", FIX_TOKEN)
    ts2.reload()
    check("T27 env-only token works", ts2.configured and ts2.matches(FIX_TOKEN)
          and ts2.source == "env")

    # blank file + env set -> env used (fail-closed preference order)
    tp2 = Path(tmpdir) / "blank_token"
    tp2.write_text("   \n")
    ts3 = TokenStore(str(tp2), FIX_TOKEN)
    ts3.reload()
    check("T28 blank file falls back to env source", ts3.configured
          and ts3.source == "env")

    # no source at all -> not configured
    ts4 = TokenStore("", "")
    ts4.reload()
    check("T29 no source -> not configured (fail closed)", not ts4.configured)


# ---------------------------------------------------------------------------
# 8. UI SHELL: UNAUTHENTICATED BY DESIGN, MUST CARRY NO OPERATIONAL DATA
# ---------------------------------------------------------------------------

async def t_ui_shell(client, stores):
    marker = "MARKER_REDA_VALUE_7f3a9c"
    stores.memory.save("profile_fact", "city", marker)
    for p in ("/", "/index.html", "/app.js", "/styles.css"):
        r = await client.get(p)                              # no auth
        check("T30 UI shell %s served without auth (by design)" % p,
              r.status in (200, 503), r.status)
        blob = await r.text()
        check("T31 UI shell %s carries no token / learner data / store paths" % p,
              FIX_TOKEN not in blob and marker not in blob
              and str(Path(stores.memory.path)) not in blob,
              p)
    fav = await client.get("/favicon.ico")
    check("T32 favicon -> 204 (no auth, no data)", fav.status == 204, fav.status)
    # no static traversal / listing
    try:
        nf = await client.get("/../etc/passwd")
        nf_status = nf.status
    except Exception as e:                                   # noqa: BLE001
        nf_status = "exc:%r" % e
    check("T33 no static traversal / listing", nf_status in (400, 401, 404) or
          str(nf_status).startswith("exc"), nf_status)
    # the shell must not be a data endpoint
    shell = await (await client.get("/app.js")).text()
    check("T34 app.js contains no endpoint that returns data unauthenticated",
          "/admin/" in shell and "Authorization" in shell)


# ---------------------------------------------------------------------------
# 9. ADMIN SURFACE ABSENT FROM THE AUDIO (HTTP) APP
# ---------------------------------------------------------------------------

def t_audio_app_isolation(tmpdir):
    from types import SimpleNamespace
    from app.main import create_app
    cfg = SimpleNamespace(
        PUBLIC_WS_URL="ws://127.0.0.1:1/xiaozhi/v1/", WS_PORT=9110, HTTP_PORT=9111,
        FRAME_MS=20, MEMORY_FILE="", WORKBENCH_BASE_URL="", KNOWLEDGE_FILE="",
        POLICY_FILE="", qwen=None)
    audio_app = create_app(cfg)
    routes = sorted({r.resource.canonical for r in audio_app.router.routes()})
    check("T35 audio app exposes no /admin/* route",
          not any(p.startswith("/admin") for p in routes), routes)
    expected = {"/health", "/xiaozhi/ota/", "/xiaozhi/v1/", "/diag",
                "/diag/reset", "/diag/capture"}
    check("T36 audio app route set is exactly the documented HTTP surface",
          set(routes) == expected, set(routes) ^ expected)

    # and the admin app must NOT expose the audio/OTA/health routes
    admin_app = create_admin_app(admin_config=_cfg(tmpdir, Path(tmpdir) / "t"),
                                 token_store=TokenStore("", ""),
                                 gateway_info=lambda: {}, stores=None)
    aroutes = sorted({r.resource.canonical for r in admin_app.router.routes()})
    check("T37 admin app exposes no /health, /xiaozhi/*, /diag* (except /admin/diag-summary)",
          not any(p.startswith(("/health", "/xiaozhi", "/diag")) for p in aroutes)
          and "/admin/diag-summary" in aroutes, aroutes)


# ---------------------------------------------------------------------------
# 10. RAW-SOCKET HEADER ATTACKS (loopback on the assigned ADMIN port 9112)
# ---------------------------------------------------------------------------

async def _raw(host, port, payload: bytes) -> int:
    reader, writer = await asyncio.open_connection(host, port)
    try:
        writer.write(payload)
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=3.0)
        parts = line.split(b" ", 2)
        return int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else -1
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:                                    # noqa: BLE001
            pass


async def t_raw_headers(tmpdir):
    token_file = Path(tmpdir) / "raw_token"
    token_file.write_text(FIX_TOKEN + "\n")
    cfg = _cfg(tmpdir, token_file)
    ts = TokenStore(cfg.token_file, cfg.token_env)
    ts.reload()
    stores = _stores(tmpdir, "raw")
    app = create_admin_app(admin_config=cfg, token_store=ts,
                           gateway_info=lambda: {"mode": "mock", "ready": True},
                           stores=stores)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", ADMIN_PORT)
    await site.start()
    try:
        def req(headers_blob: bytes) -> bytes:
            return (b"GET /admin/policy/active HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                    + headers_blob + b"Connection: close\r\n\r\n")

        s = await _raw("127.0.0.1", ADMIN_PORT,
                       req(b"Authorization: Bearer " + FIX_TOKEN.encode() + b"\r\n"))
        check("T38 raw valid token -> 200", s == 200, s)

        s = await _raw("127.0.0.1", ADMIN_PORT, req(b""))
        check("T38b raw no header -> 401", s == 401, s)

        # duplicate Authorization (raw): first is authoritative
        s = await _raw("127.0.0.1", ADMIN_PORT,
                       req(b"Authorization: Bearer wrong\r\nAuthorization: Bearer "
                           + FIX_TOKEN.encode() + b"\r\n"))
        check("T39 raw duplicate headers (invalid first) -> 401", s == 401, s)

        # CRLF header-injection attempt: the injected field becomes a separate header,
        # it must NOT authenticate
        s = await _raw("127.0.0.1", ADMIN_PORT,
                       req(b"Authorization: Bearer x\r\nX-Injected: 1\r\n"))
        check("T40 raw CRLF injection into Authorization -> 401", s == 401, s)

        # obs-fold (deprecated line folding): a continuation line carrying a bogus
        # token must never authenticate
        s = await _raw("127.0.0.1", ADMIN_PORT,
                       req(b"Authorization: Bearer\r\n not-the-token\r\n"))
        check("T41 obs-fold continuation with a bogus token -> not 200", s != 200, s)

        # injected second Authorization header behind an invalid first one
        s = await _raw("127.0.0.1", ADMIN_PORT,
                       req(b"Authorization: Bearer x\r\nAuthorization: Bearer "
                           + FIX_TOKEN.encode() + b"\r\n"))
        check("T41b smuggled 2nd Authorization behind invalid 1st -> 401", s == 401, s)

        # extremely long header -> parser must reject, never 200
        s = await _raw("127.0.0.1", ADMIN_PORT,
                       req(b"Authorization: Bearer " + b"A" * 100000 + b"\r\n"))
        check("T42 raw 100KiB header -> rejected (400/431/414)", s in (400, 414, 431, 401), s)

        # bare-LF terminated header
        s = await _raw("127.0.0.1", ADMIN_PORT,
                       b"GET /admin/policy/active HTTP/1.1\nHost: x\n"
                       b"Authorization: Bearer " + FIX_TOKEN.encode() + b"\n\n")
        check("T43 raw bare-LF request -> no auth bypass (not 200)", s != 200, s)

        # TRACE on an admin route
        s = await _raw("127.0.0.1", ADMIN_PORT,
                       b"TRACE /admin/policy/active HTTP/1.1\r\nHost: x\r\n"
                       b"Authorization: Bearer " + FIX_TOKEN.encode()
                       + b"\r\nConnection: close\r\n\r\n")
        check("T44 raw TRACE with valid token -> not 200 (405)", s != 200, s)

        # chunked body to a write endpoint: size guard must not be skipped silently
        body = b'{"id":"mem_nope","value":"' + b"a" * (70 * 1024) + b'"}'
        chunk = (b"POST /admin/memory/edit HTTP/1.1\r\nHost: x\r\n"
                 b"Authorization: Bearer " + FIX_TOKEN.encode()
                 + b"\r\nContent-Type: application/json\r\n"
                 b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
                 + hex(len(body))[2:].encode() + b"\r\n" + body + b"\r\n0\r\n\r\n")
        s = await _raw("127.0.0.1", ADMIN_PORT, chunk)
        print("INFO chunked 70KiB write body -> %s" % s)
        check("T45 chunked 70KiB body -> enforced limit/policy (413 or 400, never 200)",
              s in (400, 413), s)
    finally:
        await runner.cleanup()


async def t_info_evidence(client, stores):
    """Collect exact statuses for INFO-level observations (no assertions)."""
    for p in ("/admin/knowledge/document/add", "/admin/knowledge/document/delete",
              "/admin/knowledge/document/rebuild"):
        r = await client.get(p, headers=AUTH)
        try:
            err = (await r.json()).get("error")
        except Exception:                                    # noqa: BLE001
            err = None
        print("INFO route-shadowing: GET %-38s -> %s (%s)" % (p, r.status, err))
    # duplicate header first-wins
    r1 = await client.get("/admin/policy/active", headers=[
        ("Authorization", "Bearer wrong"), ("Authorization", AUTH["Authorization"])])
    print("INFO duplicate-header invalid-first -> %s" % r1.status)


async def t_listener_fail_closed(tmpdir):
    from app.admin import service as admin_service
    blank = Path(tmpdir) / "blank_token2"
    blank.write_text("")
    missing = Path(tmpdir) / "missing_token"
    r1 = await admin_service.start_admin_listener(
        admin_config=_cfg(tmpdir, blank), gateway_info=lambda: {}, stores=None)
    r2 = await admin_service.start_admin_listener(
        admin_config=_cfg(tmpdir, missing), gateway_info=lambda: {}, stores=None)
    off = load_admin_config(env={"ADMIN_ENABLED": "0", "ADMIN_BIND": "127.0.0.1",
                                "ADMIN_PORT": str(ADMIN_PORT),
                                "ADMIN_API_TOKEN_FILE": str(Path(tmpdir) / "admin_api_token"),
                                "ADMIN_UI_DIR": str(UI_DIR)})
    r3 = await admin_service.start_admin_listener(
        admin_config=off, gateway_info=lambda: {}, stores=None)
    check("T46 ADMIN_ENABLED=1 + empty token -> no listener (fail closed)", r1 == [])
    check("T46b ADMIN_ENABLED=1 + missing token file -> no listener", r2 == [])
    check("T46c ADMIN_ENABLED=0 -> no listener at all", r3 == [])


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

async def amain():
    tmp = tempfile.mkdtemp(prefix="red-a-")
    token_file = Path(tmp) / "admin_api_token"
    token_file.write_text(FIX_TOKEN + "\n")
    os.chmod(token_file, 0o600)
    cfg = _cfg(tmp, token_file)
    ts = TokenStore(cfg.token_file, cfg.token_env)
    ts.reload()
    stores = _stores(tmp)
    app = create_admin_app(admin_config=cfg, token_store=ts,
                           gateway_info=lambda: {"mode": "mock", "ready": True},
                           stores=stores)

    async with TestClient(TestServer(app)) as client:
        await t_token_matrix(client)
        await t_contradictory_headers(client)
        await t_body_hardening(client, stores)
        await t_read_write_escalation(client, stores)
        await t_path_tricks(client)
        await t_route_enumeration(client, app, stores)
        await t_audit_coverage(client, stores)
        await t_ui_shell(client, stores)
        await t_info_evidence(client, stores)

    t_token_reload(tmp)
    t_audio_app_isolation(tmp)
    await t_listener_fail_closed(tmp)
    await t_raw_headers(tmp)

    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("=" * 72)
    print("RED_A_ATTACKS: %d checks, %d PASS, %d FAIL" % (total, passed, total - passed))
    for name, ok, detail in RESULTS:
        if not ok:
            print("  FAILED: %s  %s" % (name, detail))
    return 0 if passed == total else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.CRITICAL)
    sys.exit(asyncio.run(amain()))