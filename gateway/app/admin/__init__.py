"""ADMIN-1 只读控制面（与音频/OTA 应用完全隔离）。

ADMIN-1 read-only control plane, isolated from the audio/OTA application.

Design references: docs/architecture/ADMIN-ARCH-1.md, docs/architecture/api-boundaries.md,
docs/architecture/security-model.md.  Scope is locked to ADMIN-1: six read-only endpoints,
bearer authentication, zero external-system dependencies, no writes of any kind.
"""

from .config import AdminConfig, load_admin_config          # noqa: F401
from .registry import sessions                              # noqa: F401
from .service import start_admin_listener, stop_admin_listener  # noqa: F401
from .version import GATEWAY_VERSION, SCHEMA_VERSION        # noqa: F401