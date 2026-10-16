"""Compatibility shim.

The generic, version-gated JSON store base now lives at :mod:`modules._jsonstore`
(so `modules.knowledge` can use it without depending on `modules.model`).
This module only re-exports it for the existing `modules.model` imports.
"""

from modules._jsonstore import (BaseJsonStore, CapExceeded, ConfirmRequired,  # noqa: F401
                                PersistError, StoreUnavailable)

__all__ = ["BaseJsonStore", "CapExceeded", "ConfirmRequired",
           "PersistError", "StoreUnavailable"]
