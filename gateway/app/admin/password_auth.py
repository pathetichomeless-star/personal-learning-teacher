"""P0 password authentication for the admin plane (human operators).

Two identities, both verified server-side (never in the browser):

- **humans** — username + password → server-side session; the browser holds only an
  HttpOnly session cookie (SameSite=Lax, ``Secure`` when served over HTTPS).  A
  per-session CSRF token is required on cookie-authenticated state-changing requests.
- **programs / automation** — the existing Bearer API token (``auth.py``: untouched,
  same strength, never weakened).

Security properties enforced here:

- passwords are stored as Argon2id hashes (argon2-cffi) — **no plaintext is ever
  stored, logged, returned, or written to any response**;
- the users file and the sessions file live in the operator's data directory with
  mode 0600 and are written atomically (tmp + ``os.replace``);
- sessions have an absolute TTL and an idle timeout; logout invalidates immediately;
- login failures are rate-limited per (peer, username) with exponential back-off —
  never a global lock (a lock must not be usable to deny service to the admin);
- the sessions file stores only the SHA-256 of each session id, so a leaked file
  does not directly yield usable cookies.

This module has no audio-plane or Tina-link side effects whatsoever.
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import time
from collections import deque
from pathlib import Path

log = logging.getLogger("rtl.admin.password_auth")

SESSION_COOKIE = "xz_admin_session"
CSRF_HEADER = "X-CSRF-Token"
COOKIE_PATH = "/admin"

MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 256

# ---- hashing (Argon2id) ---------------------------------------------------

try:                                                      # pragma: no cover - env dep
    from argon2 import PasswordHasher, Type
    from argon2.exceptions import (InvalidHashError, VerificationError,
                                   VerifyMismatchError)
    _HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4,
                             hash_len=32, salt_len=16, type=Type.ID)
    ARGON2_AVAILABLE = True
except Exception:                                         # noqa: BLE001 - fail closed
    _HASHER = None
    ARGON2_AVAILABLE = False
    log.error("argon2-cffi unavailable: password authentication will refuse to run "
              "(fail closed; install argon2-cffi)")


def password_problem(password):
    """Return a machine code when the password violates policy, else ''."""
    pw = str(password or "")
    if len(pw) < MIN_PASSWORD_LEN:
        return "password_too_short"
    if len(pw) > MAX_PASSWORD_LEN:
        return "password_too_long"
    if pw.strip() == "":
        return "password_blank"
    return ""


def hash_password(password):
    if not ARGON2_AVAILABLE:
        raise RuntimeError("argon2_unavailable")
    return _HASHER.hash(str(password))


def verify_password(stored_hash, password):
    """Constant-behaviour verify: any failure (bad hash, mismatch) is just False."""
    if not ARGON2_AVAILABLE or not stored_hash:
        return False
    try:
        return bool(_HASHER.verify(stored_hash, str(password or "")))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    except Exception:                                     # noqa: BLE001
        return False


def sha256_hex(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def constant_eq(a, b):
    return hmac.compare_digest(str(a or ""), str(b or ""))


# ---- peer / loopback ------------------------------------------------------

def is_loopback(peername):
    """True only for a genuine loopback peer address (tuple or host string)."""
    host = ""
    try:
        host = peername[0] if isinstance(peername, (tuple, list)) and peername else str(peername or "")
    except Exception:                                     # noqa: BLE001
        host = ""
    host = str(host or "")
    if not host:
        return False
    if host.startswith("::ffff:"):
        host = host.split("::ffff:", 1)[1]
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def peer_host(request):
    """Best-effort peer host for rate limiting (never trusted for authz)."""
    try:
        tr = request.transport
        peer = tr.get_extra_info("peername") if tr is not None else None
    except Exception:                                     # noqa: BLE001
        peer = None
    try:
        return str(peer[0]) if isinstance(peer, (tuple, list)) and peer else ""
    except Exception:                                     # noqa: BLE001
        return ""


# ---- atomic file helpers --------------------------------------------------

def _atomic_write(path, text):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp.%d" % os.getpid())
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, text.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.chmod(str(tmp), 0o600)
        os.replace(str(tmp), str(p))
        try:
            os.chmod(str(p), 0o600)
        except OSError:
            pass
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


# ---- users (password) store ----------------------------------------------

class PasswordStore:
    """File-backed administrator password (Argon2id hash only).

    File shape: ``{"version": 1, "username": "admin", "hash": "argon2id$...",
    "updated_at": <ts>}``.
    """

    def __init__(self, path, clock=None):
        self.path = str(path or "")
        self._clock = clock or time.time
        self._data = None
        self._sig = None

    # ---- load / state -----------------------------------------------------

    def load(self):
        if not self.path:
            self._data = None
            return None
        p = Path(self.path)
        try:
            st = p.stat()
            sig = (st.st_mtime_ns, st.st_size)
            if sig == self._sig and self._data is not None:
                return self._data
            raw = p.read_text("utf-8", errors="replace") if st.st_size > 0 else ""
            self._sig = sig
            data = json.loads(raw) if raw.strip() else None
            self._data = data if isinstance(data, dict) and data.get("hash") else None
        except FileNotFoundError:
            self._data = None
            self._sig = None
        except Exception as e:                            # noqa: BLE001 - never leak content
            log.warning("password store unreadable (refusing to treat as empty): %s",
                        type(e).__name__)
            self._data = "__unreadable__"
        return self._data

    @property
    def initialized(self):
        data = self.load()
        return isinstance(data, dict) and bool(data.get("hash"))

    @property
    def unreadable(self):
        return self._data == "__unreadable__"

    @property
    def username(self):
        data = self.load()
        if isinstance(data, dict):
            return str(data.get("username") or "admin")
        return "admin"

    # ---- verify / set -----------------------------------------------------

    def verify(self, username, password):
        """(ok, user_match) — verify hash; username compared in constant time."""
        data = self.load()
        if not isinstance(data, dict):
            return False
        if not constant_eq(str(username or ""), str(data.get("username") or "admin")):
            return False
        return verify_password(data.get("hash"), password)

    def set_password(self, password, username="admin"):
        problem = password_problem(password)
        if problem:
            raise ValueError(problem)
        if not ARGON2_AVAILABLE:
            raise RuntimeError("argon2_unavailable")
        data = {"version": 1, "username": str(username or "admin"),
                "hash": hash_password(password),
                "updated_at": float(self._clock())}
        _atomic_write(self.path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        self._sig = None
        self._data = None
        self.load()
        log.info("admin password set (username=%s; value never logged)", data["username"])


# ---- sessions -------------------------------------------------------------

class SessionStore:
    """File-backed server-side sessions (cookie value is the raw id; file stores hashes)."""

    def __init__(self, path, *, ttl_s=12 * 3600, idle_s=30 * 60, clock=None):
        self.path = str(path or "")
        self.ttl_s = max(60, int(ttl_s))
        self.idle_s = max(30, int(idle_s))
        self._clock = clock or time.time
        self._sessions = {}
        self._loaded = False
        self._last_persist = 0.0

    def _now(self):
        return float(self._clock())

    def load(self):
        if self._loaded:
            return
        self._loaded = True
        if not self.path:
            return
        try:
            raw = Path(self.path).read_text("utf-8", errors="replace")
            data = json.loads(raw) if raw.strip() else {}
            sessions = data.get("sessions") if isinstance(data, dict) else None
            if isinstance(sessions, dict):
                self._sessions = {k: v for k, v in sessions.items()
                                  if isinstance(v, dict)}
        except FileNotFoundError:
            self._sessions = {}
        except Exception as e:                            # noqa: BLE001
            log.warning("session store unreadable: %s (starting empty; "
                        "existing cookies become invalid, no data loss)", type(e).__name__)
            self._sessions = {}
        self._prune()

    def _prune(self):
        now = self._now()
        dead = [k for k, v in self._sessions.items()
                if now >= float(v.get("expires") or 0)
                or now - float(v.get("last_seen") or 0) > self.idle_s]
        for k in dead:
            self._sessions.pop(k, None)
        return bool(dead)

    def _persist(self, force=False):
        if not self.path:
            return
        now = self._now()
        if not force and now - self._last_persist < 60:
            return
        self._last_persist = now
        _atomic_write(self.path, json.dumps({"version": 1, "sessions": self._sessions},
                                            ensure_ascii=False, indent=1) + "\n")

    def count(self):
        self.load()
        self._prune()
        return len(self._sessions)

    def create(self, username):
        self.load()
        self._prune()
        sid = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        now = self._now()
        rec = {"user": str(username or "admin"), "csrf": csrf,
               "created": now, "last_seen": now, "expires": now + self.ttl_s}
        self._sessions[sha256_hex(sid)] = rec
        self._persist(force=True)
        return sid, dict(rec)

    def get(self, sid):
        """Return the session record for a valid (unexpired, non-idle) cookie, else None."""
        if not sid:
            return None
        self.load()
        key = sha256_hex(sid)
        rec = self._sessions.get(key)
        if not isinstance(rec, dict):
            return None
        now = self._now()
        if now >= float(rec.get("expires") or 0) or now - float(rec.get("last_seen") or 0) > self.idle_s:
            self._sessions.pop(key, None)
            self._persist(force=True)
            return None
        return dict(rec)

    def touch(self, sid):
        key = sha256_hex(sid)
        rec = self._sessions.get(key)
        if isinstance(rec, dict):
            rec["last_seen"] = self._now()
            self._persist(force=False)

    def destroy(self, sid):
        key = sha256_hex(sid)
        if self._sessions.pop(key, None) is not None:
            self._persist(force=True)
            return True
        return False

    def destroy_others(self, keep_sid=None):
        """Invalidate every session (optionally keeping the current one). Used on
        password change: other devices are logged out immediately."""
        self.load()
        keep = sha256_hex(keep_sid) if keep_sid else ""
        n = len(self._sessions)
        self._sessions = {k: v for k, v in self._sessions.items() if k == keep}
        if len(self._sessions) != n:
            self._persist(force=True)
        return n - len(self._sessions)

    def ttl_remaining(self, sid):
        rec = self.get(sid)
        if not rec:
            return 0
        return max(0, int(float(rec.get("expires") or 0) - self._now()))


# ---- login rate limiting --------------------------------------------------

class RateLimiter:
    """Per (peer, username) failure window with exponential back-off.

    Deliberately per-identity: one attacker guessing for ``admin`` must not block
    the real administrator using a correct password from another peer, and no
    global lock exists that could be abused to deny service.
    """

    def __init__(self, *, window_s=900, max_fails=5, base_block_s=60,
                 max_block_s=900, clock=None):
        self.window_s = int(window_s)
        self.max_fails = int(max_fails)
        self.base_block_s = int(base_block_s)
        self.max_block_s = int(max_block_s)
        self._clock = clock or time.time
        self._fails = {}                                   # key -> deque[ts]

    def _now(self):
        return float(self._clock())

    def _trim(self, key, now):
        dq = self._fails.get(key)
        if dq is None:
            return None
        while dq and now - dq[0] > self.window_s:
            dq.popleft()
        if not dq:
            self._fails.pop(key, None)
            return None
        return dq

    def check(self, key):
        """(allowed, retry_after_s)."""
        now = self._now()
        dq = self._trim(key, now)
        if dq is None or len(dq) < self.max_fails:
            return True, 0
        extra = len(dq) - self.max_fails
        block = min(self.max_block_s, self.base_block_s * (2 ** min(extra, 8)))
        wait = int(dq[-1] + block - now)
        if wait > 0:
            return False, wait
        return True, 0

    def record_failure(self, key):
        now = self._now()
        dq = self._trim(key, now) or deque()
        dq.append(now)
        self._fails[key] = dq
        # self-healing memory: a dormant key never grows forever
        if len(self._fails) > 4096:
            for k in list(self._fails.keys())[:1024]:
                self._fails.pop(k, None)

    def record_success(self, key):
        self._fails.pop(key, None)