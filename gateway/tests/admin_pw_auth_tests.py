"""ADMIN_PW_AUTH_TESTS — deterministic suite for P0 account/password authentication.

Runs standalone:  python tests/admin_pw_auth_tests.py   (from gateway/, venv)

Covers the required acceptance scenarios: first-install setup (loopback only /
authenticated migration), correct + wrong password, login rate limiting, refresh
persistence, logout invalidation, password change + recovery, bearer API
compatibility, unauthenticated access, CSRF on cookie writes — plus security
invariants: no plaintext anywhere (files/logs/bodies), 0600 files, Argon2id hash,
session-file stores hashes not raw ids, route tables unchanged for the legacy suites.
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
from app.admin.api_auth import auth_route_table                # noqa: E402
from app.admin.app import admin_route_table, create_admin_app  # noqa: E402
from app.admin.auth import TokenStore                          # noqa: E402
from app.admin.password_auth import (CSRF_HEADER, SESSION_COOKIE,  # noqa: E402
                                     PasswordStore, RateLimiter, SessionStore,
                                     hash_password, is_loopback, verify_password)
from app.admin.stores import AdminStores                       # noqa: E402

FIX_TOKEN = "PW_SUITE_BEARER_TOKEN_DO_NOT_LEAK_97531"
TEST_PW = "AcceptancePw-0001"          # ephemeral, temp dirs only; never a real credential
NEW_PW = "AcceptancePw-0002"
UI_DIR = _ROOT.parent / "admin"
AUTH = {"Authorization": "Bearer " + FIX_TOKEN}
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % (detail,)) if (detail and not cond) else ""))


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        try:
            self.records.append(record.getMessage() % record.args
                                if record.args else record.getMessage())
        except Exception:                                        # noqa: BLE001
            self.records.append(str(record.msg))


def _make(tmp, *, users="admin_users.json", sessions="admin_sessions.json",
          token=True, stores=True):
    tok_path = Path(tmp) / "admin_api_token"
    if token and not tok_path.exists():
        tok_path.write_text(FIX_TOKEN + "\n")
        os.chmod(tok_path, 0o600)
    cfg = load_admin_config(env={
        "ADMIN_ENABLED": "1", "ADMIN_BIND": "127.0.0.1", "ADMIN_PORT": "18116",
        "ADMIN_API_TOKEN_FILE": str(tok_path), "ADMIN_API_TOKEN": "",
        "ADMIN_UI_DIR": str(UI_DIR),
        "ADMIN_USERS_FILE": str(Path(tmp) / users) if users else "",
        "ADMIN_SESSIONS_FILE": str(Path(tmp) / sessions) if sessions else "",
    })
    ts = TokenStore(cfg.token_file, cfg.token_env)
    ts.reload()
    bundle = None
    if stores:
        sub = Path(tmp) / "pw_stores"
        sub.mkdir(exist_ok=True)
        bundle = AdminStores(policy_file=str(sub / "policy.json"),
                             memory_file=str(sub / "memory.json"),
                             knowledge_file=str(sub / "knowledge.json"),
                             workbench_url="")
    pw = PasswordStore(cfg.users_file) if cfg.users_file else None
    ss = SessionStore(cfg.sessions_file) if cfg.sessions_file else None
    app = create_admin_app(admin_config=cfg, token_store=ts,
                           gateway_info=lambda: {"mode": "mock", "ready": True},
                           stores=bundle, password_store=pw, session_store=ss)
    return app, cfg, pw, ss


def _body_of(response_payload):
    return {k: v for k, v in response_payload.items() if k != "request_id"}


async def amain():
    tmp = tempfile.mkdtemp(prefix="admin-pw-")
    app, cfg, _pw, _ss = _make(tmp)
    cap = LogCapture()
    logging.getLogger().addHandler(cap)

    async with TestClient(TestServer(app)) as client:
        jar = client.session.cookie_jar

        # ---- F1: public status ------------------------------------------------
        r = await client.get("/admin/auth/status")
        j = await r.json()
        check("F1 status is public 200 and reports not initialized",
              r.status == 200 and j["initialized"] is False
              and j["authenticated"] is False and j["setup_allowed"] is True, j)
        check("F1b cookie_secure auto->False on plain http", j["cookie_secure"] is False)

        # ---- F2: password policy ---------------------------------------------
        r = await client.post("/admin/auth/setup", json={"password": "short"})
        check("F2 weak password refused (too short)",
              r.status == 400 and (await r.json())["error"] == "password_too_short")
        r = await client.post("/admin/auth/setup", json={"password": "x" * 300})
        check("F2b oversized password refused", r.status == 400)

        # ---- F3: first-install setup (loopback anonymous) ----------------------
        r = await client.post("/admin/auth/setup", json={"password": TEST_PW})
        set_cookie = r.headers.getall("Set-Cookie", [])
        sc = " ".join(set_cookie)
        j = await r.json()
        check("F3 setup ok -> 200 with session", r.status == 200 and j["ok"] is True
              and j["auth_mode"] == "session" and bool(j.get("csrf")), (r.status, j))
        check("F3b cookie flags: HttpOnly + SameSite=Lax + Path=/admin, no Secure on http",
              "HttpOnly" in sc and "SameSite=Lax" in sc and "Path=/admin" in sc
              and "Secure" not in sc, sc)

        users_file = Path(cfg.users_file)
        users_text = users_file.read_text()
        check("F3c users file exists mode 600", users_file.exists()
              and (os.stat(users_file).st_mode & 0o777) == 0o600)
        check("F3d no plaintext in users file; Argon2id hash stored",
              TEST_PW not in users_text and "$argon2id$" in users_text)
        check("F3e setup is one-shot (second call -> 409)",
              (await client.post("/admin/auth/setup", json={"password": NEW_PW})).status == 409)

        # ---- F4: session alone opens the API (no bearer anywhere) -------------
        r = await client.get("/admin/health")                 # no Authorization header
        check("F4 session cookie alone -> /admin/health 200 (no bearer)",
              r.status == 200, r.status)
        r = await client.get("/admin/policy/active")
        check("F4b session cookie works on ADMIN-2 read routes", r.status == 200)

        # ---- F5: login ---------------------------------------------------------
        cl2 = TestClient(TestServer(app))                     # separate jar (anonymous)
        await cl2.start_server()
        r = await cl2.post("/admin/auth/setup", json={"password": TEST_PW})
        check("F5 duplicate setup from another client still refused",
              r.status == 409)
        await cl2.close()

        limiter = app["admin_login_limiter"]
        limiter.record_success("127.0.0.1|admin")             # deterministic limiter start
        cl3 = TestClient(TestServer(app))
        await cl3.start_server()
        r = await cl3.post("/admin/auth/login", json={"username": "admin", "password": "wrong-pw-1"})
        wrong_body = _body_of(await r.json())
        check("F5b wrong password -> 401 invalid_credentials",
              r.status == 401 and wrong_body["error"] == "invalid_credentials")
        r = await cl3.post("/admin/auth/login", json={"username": "nobody", "password": "wrong-pw-1"})
        nobody_body = _body_of(await r.json())
        check("F5c unknown user vs wrong password: identical body (no oracle)",
              wrong_body == nobody_body, (wrong_body, nobody_body))
        r = await cl3.post("/admin/auth/login", json={"username": "admin", "password": TEST_PW})
        jl = await r.json()
        csrf1 = jl.get("csrf", "")
        ck = cl3.session.cookie_jar.filter_cookies(cl3.make_url("/admin/")).get(SESSION_COOKIE)
        sid1 = ck.value if ck else ""
        check("F5d correct password -> 200 + csrf + cookie",
              r.status == 200 and jl["ok"] is True and bool(csrf1) and bool(sid1), (r.status, jl))

        # ---- F6: rate limiting (per peer+username) -----------------------------
        cl4 = TestClient(TestServer(app))
        await cl4.start_server()
        statuses = []
        for _ in range(5):
            rr = await cl4.post("/admin/auth/login", json={"username": "admin", "password": "bad-pw"})
            statuses.append(rr.status)
        r6 = await cl4.post("/admin/auth/login", json={"username": "admin", "password": "bad-pw"})
        j6 = await r6.json()
        check("F6 five failures allowed then 429 with retry_after_s",
              statuses == [401] * 5 and r6.status == 429
              and int(j6.get("retry_after_s", 0)) > 0, (statuses, r6.status, j6))
        r7 = await cl4.post("/admin/auth/login", json={"username": "admin", "password": TEST_PW})
        check("F6b correct password also blocked while rate-limited (no bypass)",
              r7.status == 429)
        r8 = await cl4.post("/admin/auth/login", json={"username": "someone-else", "password": "bad-pw"})
        check("F6c limiter is per identity (other username not blocked)", r8.status == 401)

        # ---- F7: refresh persistence + restart persistence ---------------------
        r = await cl3.get("/admin/auth/status")
        j = await r.json()
        check("F7 refresh-equivalent: same cookie still authenticated",
              r.status == 200 and j["authenticated"] is True and j["auth_mode"] == "session")
        ss2 = SessionStore(cfg.sessions_file)                 # simulate a process restart
        check("F7b session survives a store restart (persisted)", ss2.get(sid1) is not None)
        sessions_text = Path(cfg.sessions_file).read_text()
        check("F7c sessions file stores hash of the id, not the raw cookie value",
              sid1 not in sessions_text and "csrf" in sessions_text
              and len(sid1) > 20)

        # ---- F8: CSRF on cookie-authenticated writes ---------------------------
        r = await cl3.post("/admin/policy/apply", json={"policy": {"persona": {"name": "x"}},
                                                        "confirm": True})
        check("F8 cookie write without CSRF header -> 403 csrf_failed",
              r.status == 403 and (await r.json())["error"] == "csrf_failed")
        r = await cl3.post("/admin/policy/apply", headers={CSRF_HEADER: csrf1},
                           json={"policy": {"persona": {"name": "小美"}}, "confirm": True})
        check("F8b cookie write with CSRF passes auth (reaches confirmation semantics)",
              r.status == 200, r.status)
        r = await cl3.get("/admin/health")
        check("F8c GET needs no CSRF", r.status == 200)

        # ---- F9: second session + password change invalidation -----------------
        cl5 = TestClient(TestServer(app))
        await cl5.start_server()
        limiter.record_success("127.0.0.1|admin")             # clear F6 back-off window
        r = await cl5.post("/admin/auth/login", json={"username": "admin", "password": TEST_PW})
        jl2 = await r.json()
        csrf2 = jl2.get("csrf", "")
        check("F9 second device login ok", r.status == 200 and bool(csrf2))

        r = await cl3.post("/admin/auth/change-password", headers={CSRF_HEADER: csrf1},
                           json={"old_password": "nope", "new_password": NEW_PW})
        check("F9b change-password with wrong old password -> 401",
              r.status == 401 and (await r.json())["error"] == "invalid_credentials")
        r = await cl3.post("/admin/auth/change-password", headers={CSRF_HEADER: csrf1},
                           json={"old_password": TEST_PW, "new_password": NEW_PW})
        jch = await r.json()
        check("F9c change-password ok; other sessions invalidated",
              r.status == 200 and jch["ok"] is True
              and int(jch["sessions_invalidated"]) >= 1, (r.status, jch))
        r = await cl5.get("/admin/health")
        check("F9d second device logged out immediately after password change",
              r.status == 401, r.status)
        r = await cl3.get("/admin/health")
        check("F9e changing session stays valid", r.status == 200)

        cl6 = TestClient(TestServer(app))
        await cl6.start_server()
        r = await cl6.post("/admin/auth/login", json={"username": "admin", "password": TEST_PW})
        check("F9f old password no longer works", r.status == 401)
        r = await cl6.post("/admin/auth/login", json={"username": "admin", "password": NEW_PW})
        jl3 = await r.json()
        csrf3 = jl3.get("csrf", "")
        check("F9g new password works", r.status == 200 and bool(csrf3))

        # ---- F10: logout --------------------------------------------------------
        r = await cl6.post("/admin/auth/logout", headers={CSRF_HEADER: csrf3})
        sc = " ".join(r.headers.getall("Set-Cookie", []))
        check("F10 logout -> 200 + cookie cleared",
              r.status == 200 and SESSION_COOKIE in sc and "Max-Age=0" in sc, sc)
        r = await cl6.get("/admin/health")
        check("F10b session invalid immediately after logout", r.status == 401)
        r = await cl6.post("/admin/auth/logout", headers={CSRF_HEADER: csrf3})
        check("F10c logout is idempotent (already gone -> 200)", r.status == 200)

        # ---- F11: bearer compatibility (automation surface unchanged) ----------
        r = await client.get("/admin/health", headers=AUTH)
        check("F11 bearer token still works (read)", r.status == 200)
        r = await client.post("/admin/policy/apply", headers=AUTH, json={"policy": {}})
        check("F11b bearer write needs no CSRF (confirmation semantics reached)",
              r.status == 400 and (await r.json())["error"] == "confirm_required", r.status)
        r = await client.get("/admin/policy/active")
        check("F11c anonymous still 401 (no oracle regression)",
              r.status == 401)
        a1 = _body_of(await (await client.get("/admin/health")).json())
        b1 = _body_of(await (await client.get("/admin/health",
                                              headers={"Authorization": "Bearer wrong"})).json())
        a2 = _body_of(await (await client.get("/admin/health",
                                              headers={"Authorization": "Bearer wrong"})).json())
        check("F11d invalid bearer identical to anonymous", a1 == a2 == b1, (a1, a2, b1))
        r = await client.post("/admin/auth/change-password", headers=AUTH,
                              json={"new_password": TEST_PW})
        jr = await r.json()
        check("F11e token-identity reset works (recovery path) and invalidates sessions",
              r.status == 200 and jr["auth_mode"] == "bearer"
              and int(jr["sessions_invalidated"]) >= 1, (r.status, jr))
        cl7 = TestClient(TestServer(app))
        await cl7.start_server()
        r = await cl7.post("/admin/auth/login", json={"username": "admin", "password": TEST_PW})
        check("F11f reset password is the active one", r.status == 200)

        # ---- F12: audit trail ---------------------------------------------------
        r = await client.get("/admin/audit?limit=200", headers=AUTH)
        entries = (await r.json())
        actions = " ".join(str(a.get("action", "")) for a in
                           (entries.get("audit") or entries.get("entries") or []))
        check("F12 auth actions audited (setup/login ok+fail/rate-limit/change/logout)",
              all(x in actions for x in ("auth.setup.ok", "auth.login.ok", "auth.login.fail",
                                         "auth.login.rate_limited", "auth.password_change",
                                         "auth.password_reset")), actions[:400])

        # ---- F13: no plaintext in logs ------------------------------------------
        logs = "\n".join(cap.records)
        check("F13 no password/bearer value in logs",
              TEST_PW not in logs and NEW_PW not in logs and FIX_TOKEN not in logs)

        # ---- F14: legacy route tables untouched; auth table additive -----------
        legacy = {p for _, p in admin_route_table(stores=None)}
        check("F14 legacy route table has no auth endpoints",
              not any(p.startswith("/admin/auth/") for p in legacy))
        bundle = app["admin_stores"]
        expected = {p for _, p in admin_route_table(stores=bundle)} | {p for _, p in auth_route_table()}
        mounted = {r.resource.canonical for r in app.router.routes()}
        check("F14b mounted == legacy(+ADMIN-2) + auth endpoints exactly",
              mounted == expected, sorted(mounted ^ expected)[:6])

        await cl3.close()
        await cl4.close()
        await cl5.close()
        await cl6.close()
        await cl7.close()

    # ---- F15: non-loopback anonymous setup refused; bearer migration allowed ---
    tmp2 = tempfile.mkdtemp(prefix="admin-pw-net-")
    app2, cfg2, _p2, _s2 = _make(tmp2, token=True, stores=False)
    from app.admin import api_auth as api_auth_mod
    orig_loopback = api_auth_mod._loopback
    api_auth_mod._loopback = lambda request: False          # simulate a network peer
    try:
        async with TestClient(TestServer(app2)) as c2:
            r = await c2.post("/admin/auth/setup", json={"password": TEST_PW})
            check("F15 anonymous network setup refused -> 403 setup_forbidden",
                  r.status == 403 and (await r.json())["error"] == "setup_forbidden", r.status)
            r = await c2.post("/admin/auth/setup", headers=AUTH, json={"password": TEST_PW})
            check("F15b authenticated bearer migration allowed from network peer",
                  r.status == 200)
    finally:
        api_auth_mod._loopback = orig_loopback

    # ---- F16: helper units (loopback / hashing / limiter clock / expiry) -------
    check("F16 is_loopback: 127.0.0.1/::1 true, LAN false",
          is_loopback(("127.0.0.1", 1)) and is_loopback(("::1", 1))
          and not is_loopback(("192.168.1.9", 1)) and not is_loopback(None))
    h = hash_password(TEST_PW)
    check("F16b argon2id roundtrip verify", h.startswith("$argon2id$")
          and verify_password(h, TEST_PW) and not verify_password(h, TEST_PW + "x"))

    now = {"t": 1000.0}
    # stores clamp ttl/idle to safe minimums (60s / 30s); the fake clock jumps past them
    ss3 = SessionStore(str(Path(tmp) / "fake_sessions.json"),
                       ttl_s=60, idle_s=30, clock=lambda: now["t"])
    sid, rec = ss3.create("admin")
    now["t"] += 31
    check("F16c idle timeout expires a session", ss3.get(sid) is None)
    sid, rec = ss3.create("admin")
    now["t"] += 61
    check("F16d absolute TTL expires a session", ss3.get(sid) is None)
    rl = RateLimiter(window_s=60, max_fails=2, base_block_s=10, clock=lambda: now["t"])
    now["t"] = 2000.0
    rl.record_failure("k"); rl.record_failure("k")
    ok1, wait1 = rl.check("k")
    now["t"] += 11
    ok2, wait2 = rl.check("k")
    check("F16e limiter blocks then self-heals after back-off window",
          (not ok1) and wait1 > 0 and ok2 and wait2 == 0, (ok1, wait1, ok2, wait2))

    total = len(RESULTS)
    passed = sum(1 for _, ok_, _ in RESULTS if ok_)
    print("=" * 70)
    print("ADMIN_PW_AUTH_TESTS: %d checks, %d PASS, %d FAIL" %
          (total, passed, total - passed))
    for name, ok_, detail in RESULTS:
        if not ok_:
            print("  FAILED: %s %s" % (name, detail))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))