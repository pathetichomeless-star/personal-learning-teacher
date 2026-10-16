"""ADMIN-1 listener lifecycle (start/stop only; no audio-plane side effects).

``ADMIN_ENABLED=0`` (the default) means this module does nothing at all: an unchanged
production environment keeps exactly the current R-1f runtime (two listeners, no new port).

Fail-closed rule (unchanged): with no bearer token **and** no password store configured,
the listener refuses to start.  A deployment that configures ``ADMIN_USERS_FILE`` may run
without a bearer token (humans log in with account/password) — the bearer token remains
available for automation whenever configured.
"""

import logging

from aiohttp import web

from .app import create_admin_app
from .auth import TokenStore
from .password_auth import PasswordStore, SessionStore

log = logging.getLogger("rtl.admin.service")


async def start_admin_listener(*, admin_config, gateway_info, stores=None):
    """Start the third listener when explicitly enabled; fail closed without any identity."""
    if not admin_config.enabled:
        log.info("admin listener disabled (ADMIN_ENABLED=0)")
        return []
    store = TokenStore(admin_config.token_file, admin_config.token_env)
    store.reload()
    users_file = str(getattr(admin_config, "users_file", "") or "").strip()
    want_password = bool(users_file)
    if not store.configured and not want_password:
        # fail closed: no identity material -> no admin surface, audio plane untouched
        log.error("ADMIN_ENABLED=1 but no token configured "
                  "(ADMIN_API_TOKEN_FILE / ADMIN_API_TOKEN) and no password store "
                  "(ADMIN_USERS_FILE); admin listener NOT started")
        return []
    password_store = None
    session_store = None
    if want_password:
        sessions_file = (str(getattr(admin_config, "sessions_file", "") or "").strip()
                         or users_file + ".sessions")
        password_store = PasswordStore(users_file)
        session_store = SessionStore(
            sessions_file,
            ttl_s=int(getattr(admin_config, "session_ttl_s", 12 * 3600) or 12 * 3600),
            idle_s=int(getattr(admin_config, "session_idle_s", 30 * 60) or 30 * 60))
        password_store.load()
    app = create_admin_app(admin_config=admin_config, token_store=store,
                           gateway_info=gateway_info, stores=stores,
                           password_store=password_store, session_store=session_store)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, admin_config.bind, admin_config.port)
    await site.start()
    auth_desc = "bearer, source=%s" % store.source if store.configured else "bearer=off"
    if password_store is not None:
        auth_desc += "; password=%s" % ("initialized" if password_store.initialized
                                        else "not-initialized (loopback setup armed)")
    log.info("admin listener running on %s:%d (%s; %s)",
             admin_config.bind, admin_config.port,
             "ADMIN-1 + ADMIN-2 control plane" if stores is not None
             else "read-only", auth_desc)
    return [runner]


async def stop_admin_listener(runners):
    for runner in runners or []:
        try:
            await runner.cleanup()
        except Exception as e:                      # noqa: BLE001 - shutdown must not raise
            log.warning("admin listener cleanup failed: %s", e)