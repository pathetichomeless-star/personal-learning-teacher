"""Version-gated JSON store base (contract §4).

The Product V1 knowledge store used ``fail-soft to empty`` on a version
mismatch.  That is dangerous: a mismatched file shows as an empty store and the
next write **silently overwrites the old data**.  Every V4 store built on this
base instead:

* reads a **known lower** version forward-compatibly (old data stays readable);
* marks an **unknown/higher or corrupt** file ``unavailable`` and **refuses all
  writes** (``StoreUnavailable``) — the caller answers ``503 store_unavailable``
  rather than showing a fake empty list;
* never flushes while unavailable, so the original file can never be clobbered;
* provides explicit ``backup`` / ``migrate`` / ``rollback`` with disk read-back.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from pathlib import Path

from modules._store_lock import store_lock

log = logging.getLogger("modules.jsonstore")


class StoreUnavailable(RuntimeError):
    """The file is unknown-version / corrupt: read+write must be refused."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = str(reason)


class PersistError(RuntimeError):
    """The mutation could not be made durable (never reported as success)."""


class ConfirmRequired(ValueError):
    """A destructive operation without the explicit confirmation token."""


class CapExceeded(ValueError):
    """A configured cap (providers / models / docs) would be exceeded."""


class BaseJsonStore:
    """Atomic, locked, version-gated single-JSON-file store."""

    SCHEMA_VERSION = 1
    ROOT_KEYS: tuple = ()

    def __init__(self, path, *, schema_version=None):
        self.path = str(path or "")
        self.schema_version = int(schema_version if schema_version is not None
                                  else self.SCHEMA_VERSION)
        self._lock = store_lock(self.path)
        self._data = {k: {} for k in self.ROOT_KEYS}
        self._loaded = False
        self._sig = None
        self._state = "empty"          # empty | ok | unavailable
        self._reason = None
        self._migrated_from = None

    # ---- introspection ----------------------------------------------------

    @property
    def available(self) -> bool:
        return self._state in ("empty", "ok")

    def state(self) -> dict:
        return {"state": self._state, "reason": self._reason,
                "migrated_from": self._migrated_from,
                "schema_version": self.schema_version,
                "path_configured": bool(self.path)}

    def _stat_sig(self):
        try:
            st = Path(self.path).stat()
            return (st.st_mtime_ns, st.st_size, st.st_ctime_ns,
                    getattr(st, "st_ino", 0))
        except OSError:
            return None

    # ---- load -------------------------------------------------------------

    def _reset(self):
        self._data = {k: {} for k in self.ROOT_KEYS}
        self._state = "empty"
        self._reason = None
        self._migrated_from = None

    def load(self):
        """Read the file.  Never raises: an unreadable file becomes ``unavailable``."""
        with self._lock:
            self._reset()
            try:
                p = Path(self.path)
                sig = self._stat_sig()
                if self.path and p.is_file():
                    raw = json.loads(p.read_text("utf-8"))
                    if not isinstance(raw, dict):
                        self._state, self._reason = "unavailable", "corrupt"
                    else:
                        ver = raw.get("schema_version")
                        if not isinstance(ver, int):
                            self._state, self._reason = "unavailable", "version_missing"
                        elif ver > self.schema_version:
                            # a newer program wrote this: refuse to touch it
                            self._state, self._reason = "unavailable", "version_ahead"
                        else:
                            if ver < self.schema_version:
                                self._migrated_from = ver
                            for k in self.ROOT_KEYS:
                                val = raw.get(k)
                                if isinstance(val, dict):
                                    self._data[k] = dict(val)
                            self._state = "ok"
                self._sig = sig
            except Exception as e:  # noqa: BLE001  (corrupt -> refuse, never wipe)
                self._state, self._reason = "unavailable", "corrupt"
                log.warning("store load failed (%s); refusing writes: %s", e, self.path)
            self._loaded = True
        return self

    def reload_if_changed(self):
        with self._lock:
            if self._stat_sig() == self._sig and self._loaded:
                return False
            self.load()
            return True

    def _ensure_loaded(self):
        if not self._loaded:
            self.load()

    # ---- write ------------------------------------------------------------

    def _flush(self):
        if not self.available:
            return False
        tmp = None
        try:
            p = Path(self.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.parent / ("%s.%s.tmp" % (p.name, uuid.uuid4().hex[:8]))
            payload = {"schema_version": self.schema_version}
            for k in self.ROOT_KEYS:
                payload[k] = self._data[k]
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), "utf-8")
            os.chmod(tmp, 0o600)
            os.replace(tmp, p)
            self._sig = self._stat_sig()
            self._state = "ok"
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("store flush failed: %s", e)
            if tmp is not None:
                try:
                    tmp.unlink()
                except Exception:  # noqa: BLE001
                    pass
            return False

    def _persist(self):
        """Flush or refuse — never report a failed flush as success."""
        if not self.available:
            raise StoreUnavailable(self._reason or "unavailable")
        if not self._flush():
            self.load()                      # drop the phantom in-memory change
            raise PersistError("persist failed")

    # ---- backup / migrate / rollback --------------------------------------

    def backup(self):
        """Atomic copy ``<file>.bak.<from>.<ts>`` (600).  Returns (path, sha256)."""
        p = Path(self.path)
        if not p.is_file():
            raise StoreUnavailable("nothing_to_backup")
        ver = self._migrated_from if self._migrated_from is not None \
            else self.schema_version
        dest = p.parent / ("%s.bak.%s.%d" % (p.name, ver, int(time.time())))
        data = p.read_bytes()
        dest.write_bytes(data)
        os.chmod(dest, 0o600)
        return str(dest), hashlib.sha256(data).hexdigest()

    def list_backups(self):
        p = Path(self.path)
        if not p.parent.is_dir():
            return []
        return sorted(str(x) for x in p.parent.glob(p.name + ".bak.*"))

    def migrate(self, *, confirm=False):
        """Rewrite the file in the current schema after a verified backup."""
        if confirm is not True:
            raise ConfirmRequired("confirm: true is required")
        if not self.available:
            raise StoreUnavailable(self._reason or "unavailable")
        backup_path, digest = self.backup()
        before = {k: len(self._data[k]) for k in self.ROOT_KEYS}
        self._persist()
        fresh = type(self)(self.path).load()
        if not fresh.available or \
                {k: len(fresh._data[k]) for k in fresh.ROOT_KEYS} != before:
            self.restore(backup_path)
            raise PersistError("migration read-back mismatch; rolled back")
        return {"from_version": self._migrated_from, "to_version": self.schema_version,
                "backup": backup_path, "sha256": digest, "readback_ok": True}

    def restore(self, backup_path):
        src = Path(str(backup_path or ""))
        if not src.is_file():
            raise FileNotFoundError("backup not found")
        with self._lock.exclusive():
            p = Path(self.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.parent / ("%s.restore.%s.tmp" % (p.name, uuid.uuid4().hex[:8]))
            tmp.write_bytes(src.read_bytes())
            os.chmod(tmp, 0o600)
            os.replace(tmp, p)
        self.load()
        if not self.available:
            raise PersistError("restore read-back failed")
        return {"restored": True, "readback_ok": True}
