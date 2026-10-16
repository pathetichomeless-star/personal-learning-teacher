"""One re-entrant, cross-process advisory lock per store file.

The Product V1 stores (memory / knowledge / policy) each live in a single JSON file that
is written by the gateway conversation path AND by the admin control plane.  Those are
separate *instances* inside one process (fixed by an in-process per-path lock), but a
maintenance script or a second container process can also open the same file — and an
optimistic `reload → mutate → flush` without a cross-process lock silently loses updates
(adversarial finding RED-D-R2-01: ~50% of committed writes lost with two processes).

The lock combines:
* a process-wide ``threading.RLock`` (cheap, re-entrant, taken for every critical
  section — reads included), and
* an advisory ``fcntl.flock`` on ``<store>.lock`` taken ONLY by writers, via
  :meth:`StoreLock.exclusive`, at depth 0, **non-blocking with a bounded deadline**.

The deadline matters: the gateway serves WebSocket audio, HTTP and the admin plane on ONE
event loop, so an unbounded blocking lock would let any local holder freeze the realtime
plane (adversarial finding RED-A-R3-01).  On timeout the write is refused
(:class:`StoreLockTimeout`) instead of either hanging or silently losing an update.
Reads never take the file lock — ``os.replace`` already makes them see either the old or
the new file.
"""

from __future__ import annotations

import fcntl
import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger("modules.store_lock")

_LOCKS: dict = {}
_GUARD = threading.Lock()

# bounded cross-process acquisition: normal contention is microseconds, so anything
# close to this deadline means an external holder and we refuse rather than stall
DEFAULT_TIMEOUT_MS = int(os.environ.get("XZ_STORE_LOCK_TIMEOUT_MS", "500"))
_POLL_S = 0.005


class StoreLockTimeout(RuntimeError):
    """The cross-process store lock could not be taken within the bounded deadline."""


class StoreLock:
    """Re-entrant in-process lock + (for writers) a bounded advisory cross-process lock."""

    def __init__(self, key: str, lock_path: str):
        self.key = key
        self.lock_path = lock_path
        self._rlock = threading.RLock()
        self._depth = 0
        self._fh = None
        self._warned = False

    # -- in-process lock (context manager) ----------------------------------
    def __enter__(self):
        self._rlock.acquire()
        return self

    def __exit__(self, *exc):
        self._rlock.release()
        return False

    def acquire(self, *args, **kwargs):
        return self._rlock.acquire(*args, **kwargs)

    def release(self):
        return self._rlock.release()

    # -- writer path: in-process lock + bounded cross-process lock ----------
    def exclusive(self):
        return _Exclusive(self)

    def _acquire_file_lock(self):
        """Best-effort, bounded, non-blocking advisory lock."""
        deadline = time.monotonic() + max(1, DEFAULT_TIMEOUT_MS) / 1000.0
        first = True
        while True:
            fh = None
            try:
                p = Path(self.lock_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                fh = open(self.lock_path, "a+")
                try:
                    os.chmod(self.lock_path, 0o600)
                except OSError:
                    pass
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._fh = fh
                return
            except BlockingIOError:
                if fh is not None:
                    try:
                        fh.close()
                    except Exception:  # noqa: BLE001
                        pass
                if time.monotonic() >= deadline:
                    raise StoreLockTimeout(
                        "store lock busy (>%d ms): %s"
                        % (DEFAULT_TIMEOUT_MS, self.lock_path))
                time.sleep(_POLL_S)
            except Exception as e:  # noqa: BLE001  (fail-soft: in-process lock remains)
                if fh is not None:
                    try:
                        fh.close()
                    except Exception:  # noqa: BLE001
                        pass
                if first and not self._warned:
                    self._warned = True
                    log.warning("store file lock unavailable (%s); "
                                "in-process lock only", e)
                return
            finally:
                first = False

    def _release_file_lock(self):
        if self._fh is None:
            return
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._fh.close()
        except Exception:  # noqa: BLE001
            pass
        self._fh = None


class _Exclusive:
    """Writer critical section: in-process lock + bounded cross-process lock."""

    def __init__(self, lock: StoreLock):
        self._lock = lock

    def __enter__(self):
        lk = self._lock
        lk._rlock.acquire()
        if lk._depth == 0:
            try:
                lk._acquire_file_lock()
            except StoreLockTimeout:
                lk._rlock.release()
                raise
        lk._depth += 1
        return lk

    def __exit__(self, *exc):
        lk = self._lock
        lk._depth -= 1
        if lk._depth <= 0:
            lk._depth = 0
            lk._release_file_lock()
        lk._rlock.release()
        return False


def store_lock(path) -> StoreLock:
    """The single shared lock for one store path (created on first use)."""
    try:
        key = str(Path(path).resolve())
    except Exception:  # noqa: BLE001  (never fail a write because of the key)
        key = str(path)
    with _GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = StoreLock(key, key + ".lock")
            _LOCKS[key] = lock
        return lock
