"""ADMIN-1 bearer authentication (fail closed; secrets never leave this module).

Rules enforced here:
- every ``/admin/*`` API route requires **either** the Bearer API token (automation
  identity — behaviour unchanged, byte-for-byte) **or** a valid password session
  cookie (human identity — P0 password login; see ``password_auth.py``);
- cookie-authenticated state-changing requests must carry the session's CSRF token
  (``X-CSRF-Token``); bearer requests are CSRF-immune by construction;
- anonymous and invalid tokens both return 401 with an identical body (no oracle);
- the token value is never logged, never returned, never included in an error body;
- when the listener is enabled but no token is configured, the listener refuses to start
  (see ``service.start_admin_listener``) and this middleware still fails closed.
"""

import hmac
import logging
import os
from pathlib import Path

from aiohttp import web

from .password_auth import CSRF_HEADER, SESSION_COOKIE

log = logging.getLogger("rtl.admin.auth")

# self-guarded endpoints (login/setup/status/logout/change-password): the bearer
# middleware must not shadow them — see api_auth.py for their internal guards.
PUBLIC_AUTH_PREFIX = "/admin/auth/"


class TokenStore:
    """Holds the admin bearer token in memory; re-reads its source when it changes."""

    def __init__(self, token_file, token_env=""):
        self._file = str(token_file or "")
        self._env = str(token_env or "")
        self._token = ""
        self._sig = None          # (mtime_ns, size) of the token file
        self._source = "none"

    # ---- loading -----------------------------------------------------------

    def reload(self):
        """Refresh from the token file (preferred) or the environment fallback.

        An unchanged source keeps the in-memory material: a reload must never *clear* a
        valid token just because the file did not change.
        """
        if self._file:
            p = Path(self._file)
            try:
                st = p.stat()
                sig = (st.st_mtime_ns, st.st_size)
                if sig == self._sig and self._source == "file":
                    return bool(self._token)
                raw = p.read_text("utf-8", errors="replace").strip() if st.st_size > 0 else ""
                if raw:
                    self._set(raw, "file", sig)
                    return True
                self._sig = sig
            except OSError:
                pass
        if self._env:
            if self._source != "env" or not self._token:
                self._set(self._env, "env", None)
            return bool(self._token)
        if self._token:
            self._set("", "none", None)
            log.info("admin token material cleared (no source configured)")
        return False

    def _set(self, token, source, sig):
        if token != self._token:
            # never log the value; only the fact that the material changed
            log.info("admin token material updated (source=%s, configured=%s)",
                     source, bool(token))
        self._token, self._source = token, source
        self._sig = sig

    # ---- use ---------------------------------------------------------------

    @property
    def configured(self):
        return bool(self._token)

    @property
    def source(self):
        """'file' | 'env' | 'none' — a label only, never a path or value."""
        return self._source

    def matches(self, presented):
        if not self._token or not presented:
            return False
        return hmac.compare_digest(presented, self._token)


def _bearer(request):
    header = request.headers.get("Authorization", "")
    if not header:
        return ""
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""
    return parts[1].strip()


@web.middleware
async def request_id_middleware(request, handler):
    """Attach a short request id (safe, non-secret) to every response."""
    rid = os.urandom(6).hex()
    request["request_id"] = rid
    try:
        response = await handler(request)
    except web.HTTPException as exc:            # pragma: no cover - pass through
        exc.headers["X-Request-Id"] = rid
        raise
    response.headers["X-Request-Id"] = rid
    return response


def unauthorized(request, reason="invalid_or_missing_token"):
    rid = request.get("request_id", "")
    log.warning("admin auth rejected path=%s reason=%s", request.path, reason)
    return web.json_response(
        {"error": "unauthorized", "request_id": rid},
        status=401,
        headers={"X-Request-Id": rid},
    )


def csrf_forbidden(request):
    rid = request.get("request_id", "")
    log.warning("admin csrf rejected path=%s reason=csrf_failed", request.path)
    return web.json_response(
        {"error": "csrf_failed", "request_id": rid},
        status=403,
        headers={"X-Request-Id": rid},
    )


@web.middleware
async def auth_middleware(request, handler):
    """Guard every ``/admin/*`` API route: password session cookie OR bearer token
    (ADMIN-1/ADMIN-2: authenticated operator; admin writes additionally require
    explicit confirmation tokens).  The bearer path is unchanged."""
    if not request.path.startswith("/admin/"):
        # static UI shell only (no operational data; see admin/app.js)
        return await handler(request)
    if request.path.startswith(PUBLIC_AUTH_PREFIX):
        # login / setup / logout / status / change-password guard themselves
        return await handler(request)

    # ---- session cookie path (human operators) --------------------------------
    sess_store = request.app.get("admin_session_store")
    sid = request.cookies.get(SESSION_COOKIE, "") if sess_store is not None else ""
    if sess_store is not None and sid:
        rec = sess_store.get(sid)
        if rec:
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                provided = request.headers.get(CSRF_HEADER, "")
                if not provided or not hmac.compare_digest(str(provided), str(rec.get("csrf") or "")):
                    return csrf_forbidden(request)
            request["admin_role"] = "OPERATOR"
            request["admin_auth_mode"] = "session"
            request["admin_user"] = str(rec.get("user") or "admin")
            sess_store.touch(sid)
            return await handler(request)

    # ---- bearer path (automation; unchanged rules and reason codes) -----------
    store = request.app.get("admin_token_store")
    if store is None:
        return unauthorized(request, "token_store_missing")
    store.reload()
    if not store.configured:
        return unauthorized(request, "auth_not_configured")
    presented = _bearer(request)
    if not presented:
        return unauthorized(request, "missing_bearer")
    if not store.matches(presented):
        return unauthorized(request, "invalid_token")
    request["admin_role"] = "OPERATOR"
    request["admin_auth_mode"] = "bearer"
    return await handler(request)