"""ADMIN-1 aiohttp application (isolated from the audio/OTA application).

The admin app mounts **only** the six read-only admin routes and the static UI shell.
It deliberately does not mount, proxy or reuse ``/xiaozhi/*``, ``/diag*``, ``/health``,
the OTA endpoint or the WebSocket audio route.
"""

import logging
from pathlib import Path

from aiohttp import web

from . import views
from .auth import auth_middleware, request_id_middleware

log = logging.getLogger("rtl.admin.app")


def create_admin_app(*, admin_config, token_store, gateway_info, stores=None,
                     password_store=None, session_store=None):
    """Build the admin application (no side effects: the caller starts the listener).

    ``stores=None`` mounts exactly the ADMIN-1 six read-only routes; passing the
    ADMIN-2 store bundle additionally mounts the control-plane API (additive,
    backward compatible).  Passing ``password_store`` additionally mounts the P0
    account/password auth endpoints (``/admin/auth/*``, self-guarded).
    """
    app = web.Application(middlewares=[request_id_middleware, auth_middleware])
    app["admin_config"] = admin_config
    app["admin_token_store"] = token_store
    app["admin_password_store"] = password_store
    app["admin_session_store"] = session_store
    app["admin_gateway_info"] = gateway_info
    app["admin_ui_dir"] = Path(admin_config.ui_dir)
    app["admin_v4_ui_dir"] = Path(getattr(admin_config, "ui_v4_dir", "") or
                                  (Path(admin_config.ui_dir).parent / "admin-v4"))
    app["admin_stores"] = stores
    # V4 seams: test-authorization flag + injectable resolver/probe opener (tests).
    app["model_test_authorized"] = bool(getattr(stores, "test_authorized", False))
    # Explicit promotion (contract §2.3 step 3) needs its OWN authorization flag.
    app["model_promote_authorized"] = bool(getattr(stores, "promote_authorized", False))
    # P2-B2-R3-2C: the realtime-handshake probe has its OWN flag (default off).
    app["model_realtime_probe_authorized"] = bool(
        getattr(stores, "realtime_probe_authorized", False))
    app["model_endpoint_resolver"] = None
    app["model_probe_opener"] = None

    # exactly six read-only API routes
    app.router.add_get("/admin/health", views.health)
    app.router.add_get("/admin/version", views.version_view)
    app.router.add_get("/admin/sessions", views.sessions_view)
    app.router.add_get("/admin/metrics", views.metrics_view)
    app.router.add_get("/admin/telemetry", views.telemetry_view)
    app.router.add_get("/admin/diag-summary", views.diag_summary_view)

    # P0 account/password auth (mounted only when the password store is wired; the
    # legacy route tables stay unchanged so existing security suites keep their
    # exact-equality checks — see api_auth.auth_route_table())
    if password_store is not None:
        from . import api_auth
        api_auth.mount(app)

    # ADMIN-2 control plane (mounted only when the store bundle is wired)
    if stores is not None:
        from . import api as api_views
        api_views.mount(app)

    # static UI shell (fixed allowlist inside views.ui_shell)
    app.router.add_get("/", views.ui_shell)
    app.router.add_get("/index.html", views.ui_shell)
    app.router.add_get("/app.js", views.ui_shell)
    app.router.add_get("/styles.css", views.ui_shell)
    app.router.add_get("/favicon.ico", views.ui_shell)

    # V4 dual-mode UI shell (static; its API calls still need the bearer token)
    app.router.add_get("/v4", views.v4_shell)
    app.router.add_get("/v4/", views.v4_shell)
    app.router.add_get("/v4/index.html", views.v4_shell)
    app.router.add_get("/v4/app.js", views.v4_shell)
    app.router.add_get("/v4/app-pro.js", views.v4_shell)
    app.router.add_get("/v4/styles.css", views.v4_shell)
    return app


def admin_route_table(stores=None):
    """Route inventory used by the tests and the auditors."""
    table = [
        ("GET", "/admin/health"), ("GET", "/admin/version"), ("GET", "/admin/sessions"),
        ("GET", "/admin/metrics"), ("GET", "/admin/telemetry"), ("GET", "/admin/diag-summary"),
        ("GET", "/"), ("GET", "/index.html"), ("GET", "/app.js"), ("GET", "/styles.css"),
        ("GET", "/favicon.ico"),
        ("GET", "/v4"), ("GET", "/v4/"), ("GET", "/v4/index.html"),
        ("GET", "/v4/app.js"), ("GET", "/v4/app-pro.js"), ("GET", "/v4/styles.css"),
    ]
    if stores is not None:
        from . import api as api_views
        table = table + [tuple(x) for x in api_views.api_route_table(stores)]
    return table