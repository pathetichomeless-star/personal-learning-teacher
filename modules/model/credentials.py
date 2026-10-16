"""Provider credential store (contract §3).

Two concepts, deliberately separate:

* ``fingerprint``    — ``sha256(secret)[:16]``: **display only**, proves "configured".
* ``credential_ref`` — ``cred://<cred_id>/v<n>``: the opaque handle the adapter
  runtime passes to :meth:`CredentialStore.read_secret` to obtain the plaintext
  from the sealed store.  A fingerprint can never be turned back into a secret.

No response/record in this module contains plaintext: the sealed token lives in
the encrypted field and only :meth:`read_secret` (a controlled accessor) can open
it.  Rotation keeps the previous version so a rollback is possible.
"""

from __future__ import annotations

import hashlib
import time
import uuid

from modules.model._jsonstore import BaseJsonStore, ConfirmRequired, StoreUnavailable
from modules.model.crypto import KeyStoreError, load_or_create_key, seal, unseal

MAX_SECRET = 4096
MAX_LABEL = 60
MAX_PROVIDER_ID = 64


class CredentialError(ValueError):
    """Base class for credential refusals (400)."""


class CredentialInUse(CredentialError):
    """Deletion refused: an enabled model still references this credential."""


def fingerprint_of(secret: str) -> str:
    return hashlib.sha256(str(secret).encode("utf-8")).hexdigest()[:16]


class CredentialStore(BaseJsonStore):
    SCHEMA_VERSION = 1
    ROOT_KEYS = ("credentials",)

    def __init__(self, path, *, key_path=""):
        super().__init__(path)
        self.key_path = str(key_path or "")
        self._key = None

    # ---- key -------------------------------------------------------------

    def _k(self):
        if self._key is None:
            self._key = load_or_create_key(self.key_path)
        return self._key

    # ---- validation ------------------------------------------------------

    @staticmethod
    def _pid(value):
        s = str(value or "").strip()
        if not s:
            raise CredentialError("provider_id required")
        return s[:MAX_PROVIDER_ID]

    @staticmethod
    def _secret(value):
        s = str(value or "")
        if not s.strip():
            raise CredentialError("secret required")
        if len(s) > MAX_SECRET:
            raise CredentialError("secret too long (max %d)" % MAX_SECRET)
        return s

    # ---- public views ----------------------------------------------------

    @staticmethod
    def _public(rec):
        return {"id": rec["id"], "provider_id": rec["provider_id"],
                "label": rec.get("label"),
                "configured": True,
                "fingerprint": rec["versions"][str(rec["current_v"])]["fingerprint"],
                "credential_ref": _ref(rec["id"], rec["current_v"]),
                "current_v": rec["current_v"],
                "versions": sorted(int(v) for v in rec["versions"]),
                "created_at": rec.get("created_at"), "updated_at": rec.get("updated_at")}

    # ---- operations ------------------------------------------------------

    def find_by_provider(self, provider_id):
        pid = str(provider_id or "")
        for rec in self._data["credentials"].values():
            if rec.get("provider_id") == pid:
                return rec
        return None

    def is_configured(self, provider_id) -> bool:
        with self._lock:
            self._ensure_loaded()
            return self.find_by_provider(provider_id) is not None

    def current_ref(self, provider_id):
        rec = self.find_by_provider(provider_id)
        return _ref(rec["id"], rec["current_v"]) if rec else None

    def put(self, provider_id, secret, *, label=None):
        """Create the credential for a provider, or add a new version (rotate)."""
        pid, sec = self._pid(provider_id), self._secret(secret)
        with self._lock.exclusive():
            self.reload_if_changed()
            existing = self.find_by_provider(pid)
            now = time.time()
            token = seal(self._k(), sec)
            fp = fingerprint_of(sec)
            if existing:
                n = int(existing["current_v"]) + 1
                existing["versions"][str(n)] = {"token": token, "fingerprint": fp,
                                                "created_at": now, "retired": False}
                existing["current_v"] = n
                existing["updated_at"] = now
                if label is not None:
                    existing["label"] = str(label)[:MAX_LABEL]
                rec = existing
            else:
                cid = "cred_" + uuid.uuid4().hex[:12]
                rec = {"id": cid, "provider_id": pid,
                       "label": (str(label)[:MAX_LABEL] if label else None),
                       "current_v": 1,
                       "versions": {"1": {"token": token, "fingerprint": fp,
                                          "created_at": now, "retired": False}},
                       "created_at": now, "updated_at": now}
                self._data["credentials"][cid] = rec
            self._persist()
            return self._public(rec)

    def rotate(self, cred_id, secret, *, confirm=False):
        if confirm is not True:
            raise ConfirmRequired("confirm: true is required")
        sec = self._secret(secret)
        with self._lock.exclusive():
            self.reload_if_changed()
            rec = self._data["credentials"].get(str(cred_id or ""))
            if rec is None:
                raise CredentialError("unknown credential")
            n = int(rec["current_v"]) + 1
            rec["versions"][str(n)] = {"token": seal(self._k(), sec),
                                       "fingerprint": fingerprint_of(sec),
                                       "created_at": time.time(), "retired": False}
            rec["versions"][str(rec["current_v"])]["retired"] = True
            rec["current_v"] = n
            rec["updated_at"] = time.time()
            self._persist()
            return self._public(rec)

    def delete(self, cred_id, *, confirm=False, in_use=False):
        if confirm is not True:
            raise ConfirmRequired("confirm: true is required")
        if in_use:
            raise CredentialInUse("credential still referenced by an enabled model")
        with self._lock.exclusive():
            self.reload_if_changed()
            rec = self._data["credentials"].pop(str(cred_id or ""), None)
            if rec is None:
                raise CredentialError("unknown credential")
            self._persist()
            return {"deleted": rec["id"], "provider_id": rec["provider_id"]}

    def list(self, provider_id=None):
        with self._lock:
            self._ensure_loaded()
            rows = [self._public(r) for r in self._data["credentials"].values()
                    if provider_id is None or r.get("provider_id") == str(provider_id)]
            rows.sort(key=lambda r: (r.get("created_at") or 0, r["id"]))
            return rows

    def get(self, cred_id):
        with self._lock:
            self._ensure_loaded()
            rec = self._data["credentials"].get(str(cred_id or ""))
            return self._public(rec) if rec else None

    # ---- controlled accessor (adapter runtime only) ----------------------

    def read_secret(self, credential_ref):
        """Resolve a ``cred://`` ref to the plaintext secret.

        This is the ONLY path that yields plaintext.  Callers must never log,
        echo or persist the return value.
        """
        rec_id, ver = _parse_ref(credential_ref)
        with self._lock:
            self._ensure_loaded()
            rec = self._data["credentials"].get(rec_id)
            if rec is None:
                raise CredentialError("unknown credential")
            if str(ver) != str(rec["current_v"]):
                raise CredentialError("stale credential_ref")
            entry = rec["versions"].get(str(ver))
            if not entry:
                raise CredentialError("unknown version")
            return unseal(self._k(), entry["token"])


def _ref(cred_id, version) -> str:
    return "cred://%s/v%s" % (cred_id, version)


def _parse_ref(ref):
    s = str(ref or "")
    if not s.startswith("cred://") or "/v" not in s:
        raise CredentialError("malformed credential_ref")
    body = s[len("cred://"):]
    cred_id, _, ver = body.partition("/v")
    if not cred_id or not ver.isdigit():
        raise CredentialError("malformed credential_ref")
    return cred_id, ver
