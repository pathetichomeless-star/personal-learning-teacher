"""ADMIN-1 configuration (runtime-injected only; disabled by default).

Hard rules (ADMIN-1 authorization):
- ``ADMIN_ENABLED`` defaults to **0**: an unchanged production environment must not start a
  new listener and must not alter current R-1f runtime behaviour.
- the bearer token is never committed, never in config.json, never logged.
"""

import os
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("rtl.admin.config")

DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 8112
DEFAULT_TOKEN_FILE = "/app/secrets/admin_api_token"


def _as_bool(raw):
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _as_int(raw, default):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class AdminConfig:
    """Resolved ADMIN-1 settings.  ``enabled`` is False unless explicitly switched on.

    P0 password authentication is **opt-in** via ``ADMIN_USERS_FILE`` (empty means
    the deployment keeps exactly the legacy bearer-only surface).
    """

    enabled: bool
    bind: str
    port: int
    token_file: str
    token_env: str
    ui_dir: str
    ui_v4_dir: str = ""
    users_file: str = ""            # ADMIN_USERS_FILE — password store (Argon2id)
    sessions_file: str = ""         # ADMIN_SESSIONS_FILE — server-side sessions
    cookie_secure: str = "auto"     # ADMIN_COOKIE_SECURE: auto | 1 | 0
    session_ttl_s: int = 12 * 3600  # ADMIN_SESSION_TTL_S — absolute session lifetime
    session_idle_s: int = 30 * 60   # ADMIN_SESSION_IDLE_S — idle timeout

    def describe_public(self):
        """Only fields that are safe to publish on the admin API (no token, no paths)."""
        return {"enabled": self.enabled, "bind": self.bind, "port": self.port}


def load_admin_config(env=None):
    """Read ADMIN_* from the environment; never raises, never reads secrets itself."""
    e = os.environ if env is None else env
    # repo layout: <repo>/gateway/app/admin/config.py -> <repo>/admin
    root = Path(__file__).resolve().parents[3]
    ui_default = str(root / "admin")
    v4_default = str(root / "admin-v4")
    return AdminConfig(
        enabled=_as_bool(e.get("ADMIN_ENABLED", "0")),
        bind=str(e.get("ADMIN_BIND", DEFAULT_BIND)).strip() or DEFAULT_BIND,
        port=_as_int(e.get("ADMIN_PORT", DEFAULT_PORT), DEFAULT_PORT),
        token_file=str(e.get("ADMIN_API_TOKEN_FILE", DEFAULT_TOKEN_FILE)).strip(),
        token_env=str(e.get("ADMIN_API_TOKEN", "")).strip(),
        ui_dir=str(e.get("ADMIN_UI_DIR", ui_default)).strip() or ui_default,
        ui_v4_dir=str(e.get("ADMIN_V4_UI_DIR", v4_default)).strip() or v4_default,
        users_file=str(e.get("ADMIN_USERS_FILE", "")).strip(),
        sessions_file=str(e.get("ADMIN_SESSIONS_FILE", "")).strip(),
        cookie_secure=str(e.get("ADMIN_COOKIE_SECURE", "auto")).strip() or "auto",
        session_ttl_s=_as_int(e.get("ADMIN_SESSION_TTL_S", 12 * 3600), 12 * 3600),
        session_idle_s=_as_int(e.get("ADMIN_SESSION_IDLE_S", 30 * 60), 30 * 60),
    )