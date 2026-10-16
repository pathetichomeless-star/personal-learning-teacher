"""P0 admin auth endpoints (account/password sessions) — mounted alongside bearer auth.

Endpoints (all under ``/admin/auth/``, exempted from the bearer middleware and
**self-guarded here**):

- ``GET  /admin/auth/status``          public, non-secret state for the login page
- ``POST /admin/auth/setup``           first-install (loopback only) or migration
                                       (authenticated bearer) — one-shot
- ``POST /admin/auth/login``           username + password → server-side session cookie
- ``POST /admin/auth/logout``          immediate session invalidation
- ``POST /admin/auth/change-password`` logged-in change (old password required) or
                                       token-identity reset (bearer), never anonymous

Rules honoured here:
- no plaintext password or session id is ever logged or echoed;
- anonymous callers can never initialise a **non-loopback** deployment (403), and
  an initialised deployment refuses setup entirely (409) — upgrades migrate through
  an authenticated bearer session, never through an open endpoint;
- failures are audited (action codes only) and rate-limited per (peer, username).
"""

import logging

from aiohttp import web

from .password_auth import (CSRF_HEADER, SESSION_COOKIE, COOKIE_PATH,
                            RateLimiter, constant_eq, is_loopback,
                            password_problem, peer_host)

log = logging.getLogger("rtl.admin.api_auth")

MAX_BODY = 8 * 1024


def _rid(request):
    return request.get("request_id", "")


def _ok(request, payload):
    payload = dict(payload)
    payload["request_id"] = _rid(request)
    return web.json_response(payload)


def _err(request, status, code, detail=None, extra=None):
    body = {"error": code}
    if detail:
        body["detail"] = str(detail)
    if extra:
        body.update(extra)
    body["request_id"] = _rid(request)
    return web.json_response(body, status=status)


async def _body(request):
    if request.content_length and request.content_length > MAX_BODY:
        raise web.HTTPRequestEntityTooLarge(max_size=MAX_BODY, actual_size=request.content_length)
    try:
        data = await request.json()
    except Exception:                                        # noqa: BLE001
        raise web.HTTPBadRequest()
    if not isinstance(data, dict):
        raise web.HTTPBadRequest()
    return data


def _audit(request, action, subject=None):
    """Best-effort audit append; never fails the request (action codes only)."""
    try:
        stores = request.app.get("admin_stores")
        audit = getattr(stores, "audit", None) if stores is not None else None
        if audit is not None:
            audit.append(action, subject=subject)
    except Exception:                                        # noqa: BLE001
        pass


def _pw(request):
    return request.app.get("admin_password_store")


def _sess(request):
    return request.app.get("admin_session_store")


def _limiter(request):
    lim = request.app.get("admin_login_limiter")
    return lim


def _token_ok(request):
    """True when the request carries the valid API bearer token (automation identity)."""
    store = request.app.get("admin_token_store")
    if store is None:
        return False
    try:
        store.reload()
    except Exception:                                        # noqa: BLE001
        return False
    if not store.configured:
        return False
    header = request.headers.get("Authorization", "")
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    return store.matches(parts[1].strip())


def _cookie_sid(request):
    return request.cookies.get(SESSION_COOKIE, "")


def _session_rec(request):
    store = _sess(request)
    sid = _cookie_sid(request)
    if store is None or not sid:
        return None, ""
    rec = store.get(sid)
    return rec, sid


def _loopback(request):
    """Setup eligibility check (loopback peers only for anonymous first-install)."""
    try:
        tr = request.transport
        peer = tr.get_extra_info("peername") if tr is not None else None
    except Exception:                                        # noqa: BLE001
        peer = None
    return is_loopback(peer)


def _cookie_secure(request):
    cfg = request.app.get("admin_config")
    mode = str(getattr(cfg, "cookie_secure", "auto") or "auto").strip().lower()
    if mode in ("1", "true", "yes", "on"):
        return True
    if mode in ("0", "false", "no", "off"):
        return False
    # auto: Secure whenever the request itself is HTTPS (direct or trusted proxy)
    return request.scheme == "https"


def _set_session_cookie(request, response, sid, max_age):
    response.set_cookie(
        SESSION_COOKIE, sid,
        max_age=max_age, path=COOKIE_PATH, httponly=True, samesite="Lax",
        secure=_cookie_secure(request),
    )
    return response


def _login_success(request, username, rec, sid):
    resp = _ok(request, {
        "ok": True, "user": username, "auth_mode": "session",
        "csrf": rec.get("csrf", ""),
        "session_expires_at": int(rec.get("expires") or 0),
    })
    return _set_session_cookie(request, resp, sid, max_age=int(rec.get("expires") or 0)
                               - int(rec.get("created") or 0))


def _limiter_key(request, username):
    return "%s|%s" % (peer_host(request) or "unknown", str(username or "").strip().casefold())


# ---- handlers --------------------------------------------------------------

async def auth_status(request):
    """Public, non-secret status. Also used by the UI right after boot/login."""
    pw = _pw(request)
    if pw is None:
        return _err(request, 503, "auth_not_available")
    pw.load()
    if getattr(pw, "unreadable", False):
        return _err(request, 503, "auth_unreadable")
    initialized = pw.initialized
    authed = False
    auth_mode = None
    csrf = ""
    user = None
    expires = 0
    rec, _sid = _session_rec(request)
    if rec:
        authed, auth_mode, csrf = True, "session", str(rec.get("csrf") or "")
        user = str(rec.get("user") or "admin")
        expires = int(rec.get("expires") or 0)
    elif _token_ok(request):
        authed, auth_mode = True, "bearer"
        user = pw.username
    return _ok(request, {
        "initialized": initialized, "authenticated": authed, "auth_mode": auth_mode,
        "user": user, "csrf": csrf, "session_expires_at": expires,
        "setup_allowed": (not initialized) and (_loopback(request) or _token_ok(request)),
        "cookie_secure": _cookie_secure(request),
    })


async def auth_setup(request):
    """First-install (loopback) or authenticated migration (bearer) — one-shot."""
    pw = _pw(request)
    sess = _sess(request)
    if pw is None or sess is None:
        return _err(request, 503, "auth_not_available")
    pw.load()
    if getattr(pw, "unreadable", False):
        return _err(request, 503, "auth_unreadable")
    if pw.initialized:
        _audit(request, "auth.setup.denied", subject="already_initialized")
        return _err(request, 409, "already_initialized")
    try:
        body = await _body(request)
    except web.HTTPException as exc:
        return _err(request, exc.status, "invalid_json" if exc.status == 400 else "body_too_large")
    token_identity = _token_ok(request)
    if not token_identity and not _loopback(request):
        # never allow anonymous initialisation from a network peer
        _audit(request, "auth.setup.denied", subject="non_loopback")
        log.warning("admin setup refused for non-loopback anonymous peer")
        return _err(request, 403, "setup_forbidden")
    problem = password_problem(body.get("password"))
    if problem:
        return _err(request, 400, problem)
    username = str(body.get("username") or "admin").strip() or "admin"
    try:
        pw.set_password(body.get("password"), username=username)
    except ValueError as e:
        return _err(request, 400, str(e))
    except RuntimeError:
        return _err(request, 503, "hash_unavailable")
    sid, rec = sess.create(username)
    _audit(request, "auth.setup.ok", subject=username)
    return _login_success(request, username, rec, sid)


async def auth_login(request):
    pw = _pw(request)
    sess = _sess(request)
    if pw is None or sess is None:
        return _err(request, 503, "auth_not_available")
    pw.load()
    if getattr(pw, "unreadable", False):
        return _err(request, 503, "auth_unreadable")
    if not pw.initialized:
        return _err(request, 409, "not_initialized")
    try:
        body = await _body(request)
    except web.HTTPException as exc:
        return _err(request, exc.status, "invalid_json" if exc.status == 400 else "body_too_large")
    username = str(body.get("username") or "").strip()
    password = body.get("password")
    lim = _limiter(request)
    key = _limiter_key(request, username)
    if lim is not None:
        allowed, wait = lim.check(key)
        if not allowed:
            _audit(request, "auth.login.rate_limited", subject=username or "-")
            return _err(request, 429, "rate_limited", extra={"retry_after_s": wait})
    if not username or not isinstance(password, str) or not password:
        if lim is not None:
            lim.record_failure(key)
        _audit(request, "auth.login.fail", subject=username or "-")
        return _err(request, 401, "invalid_credentials")
    if not pw.verify(username, password):
        if lim is not None:
            lim.record_failure(key)
        _audit(request, "auth.login.fail", subject=username)
        return _err(request, 401, "invalid_credentials")
    if lim is not None:
        lim.record_success(key)
    sid, rec = sess.create(username)
    _audit(request, "auth.login.ok", subject=username)
    return _login_success(request, username, rec, sid)


async def auth_logout(request):
    sess = _sess(request)
    sid = _cookie_sid(request)
    if sess is not None and sid:
        rec = sess.get(sid)
        if rec:
            # state-changing cookie action: require the session CSRF token
            provided = request.headers.get(CSRF_HEADER, "")
            if not provided or not constant_eq(provided, rec.get("csrf")):
                return _err(request, 403, "csrf_failed")
            sess.destroy(sid)
            _audit(request, "auth.logout", subject=str(rec.get("user") or "admin"))
    resp = _ok(request, {"ok": True})
    resp.del_cookie(SESSION_COOKIE, path=COOKIE_PATH)
    return resp


async def auth_change_password(request):
    """Logged-in change (old password required) or token-identity reset. Never anonymous."""
    pw = _pw(request)
    sess = _sess(request)
    if pw is None or sess is None:
        return _err(request, 503, "auth_not_available")
    pw.load()
    if getattr(pw, "unreadable", False):
        return _err(request, 503, "auth_unreadable")
    if not pw.initialized:
        return _err(request, 409, "not_initialized")
    rec, sid = _session_rec(request)
    token_identity = _token_ok(request)
    if rec:
        provided = request.headers.get(CSRF_HEADER, "")
        if not provided or not constant_eq(provided, rec.get("csrf")):
            return _err(request, 403, "csrf_failed")
    elif not token_identity:
        return _err(request, 401, "unauthorized")
    try:
        body = await _body(request)
    except web.HTTPException as exc:
        return _err(request, exc.status, "invalid_json" if exc.status == 400 else "body_too_large")
    new_password = body.get("new_password")
    problem = password_problem(new_password)
    if problem:
        return _err(request, 400, problem)
    if rec:
        # human session: the current password is required (reset must not bypass auth)
        old_password = body.get("old_password")
        lim = _limiter(request)
        key = _limiter_key(request, str(rec.get("user") or "admin"))
        if lim is not None:
            allowed, wait = lim.check(key)
            if not allowed:
                return _err(request, 429, "rate_limited", extra={"retry_after_s": wait})
        if not isinstance(old_password, str) or not pw.verify(str(rec.get("user") or "admin"), old_password):
            if lim is not None:
                lim.record_failure(key)
            _audit(request, "auth.password_change.fail", subject=str(rec.get("user") or "admin"))
            return _err(request, 401, "invalid_credentials")
        if lim is not None:
            lim.record_success(key)
    # password changed → every other device is logged out immediately
    try:
        pw.set_password(new_password)
    except ValueError as e:
        return _err(request, 400, str(e))
    except RuntimeError:
        return _err(request, 503, "hash_unavailable")
    killed = sess.destroy_others(keep_sid=sid or None)
    action = "auth.password_change" if rec else "auth.password_reset"
    _audit(request, action, subject=pw.username)
    return _ok(request, {"ok": True, "sessions_invalidated": killed,
                         "auth_mode": "session" if rec else "bearer"})


def mount(app):
    """Mount the auth endpoints (called only when a password store is wired)."""
    app["admin_login_limiter"] = app.get("admin_login_limiter") or RateLimiter()
    app.router.add_get("/admin/auth/status", auth_status)
    app.router.add_post("/admin/auth/setup", auth_setup)
    app.router.add_post("/admin/auth/login", auth_login)
    app.router.add_post("/admin/auth/logout", auth_logout)
    app.router.add_post("/admin/auth/change-password", auth_change_password)


def auth_route_table():
    """Inventory for the dedicated auth test suite (the legacy route tables stay
    byte-identical so existing security suites keep their exact-equality checks)."""
    return [
        ("GET", "/admin/auth/status"),
        ("POST", "/admin/auth/setup"),
        ("POST", "/admin/auth/login"),
        ("POST", "/admin/auth/logout"),
        ("POST", "/admin/auth/change-password"),
    ]