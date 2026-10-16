"""At-rest sealing for model provider credentials (contract §3.2).

The secret is sealed (Fernet/AES-128-CBC+HMAC) with a key that lives in its own
``600`` file, separate from the credential store.  Nothing here ever returns the
key or the plaintext to a caller except through
:class:`~modules.model.credentials.CredentialStore.read_secret`, which is the
single controlled accessor used by the adapter runtime.
"""

from __future__ import annotations

import base64
import logging
import os
import threading
from pathlib import Path

log = logging.getLogger("modules.model.crypto")

_KEY_LOCK = threading.Lock()

try:  # optional dependency; absence degrades honestly rather than storing plaintext
    from cryptography.fernet import Fernet, InvalidToken
    _HAVE_FERNET = True
except Exception:  # noqa: BLE001
    Fernet = None  # type: ignore
    InvalidToken = Exception  # type: ignore
    _HAVE_FERNET = False


class KeyStoreError(RuntimeError):
    """The sealing key is missing/unusable, so secrets cannot be stored safely."""


def load_or_create_key(path) -> bytes:
    """Read the Fernet key at ``path`` (600), creating it on first use."""
    if not _HAVE_FERNET:
        raise KeyStoreError("crypto_unavailable (cryptography not installed)")
    if not path:
        raise KeyStoreError("key_path_required")
    with _KEY_LOCK:
        p = Path(str(path))
        if p.is_file():
            raw = p.read_text("utf-8").strip().encode("ascii", "ignore")
            try:
                base64.urlsafe_b64decode(raw)
            except Exception:  # noqa: BLE001
                raise KeyStoreError("key_unreadable")
            return raw
        p.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        tmp = p.parent / (p.name + ".tmp")
        tmp.write_bytes(key)
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
        return key


def seal(key: bytes, plaintext: str) -> str:
    if not _HAVE_FERNET:
        raise KeyStoreError("crypto_unavailable")
    return Fernet(key).encrypt(str(plaintext).encode("utf-8")).decode("ascii")


def unseal(key: bytes, token: str) -> str:
    if not _HAVE_FERNET:
        raise KeyStoreError("crypto_unavailable")
    try:
        return Fernet(key).decrypt(str(token).encode("ascii")).decode("utf-8")
    except InvalidToken:
        raise KeyStoreError("secret_unreadable")
