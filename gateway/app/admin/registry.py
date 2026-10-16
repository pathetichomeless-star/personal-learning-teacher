"""ADMIN-1 passive session registry (observer-only lifecycle hooks).

The registry is fed from the WebSocket handler's lifecycle only (connect / close) and holds
**weak references**, so a closed connection disappears without any bookkeeping inside hot
paths.  Nothing here is called from — or locks — the pacer loop, the Opus encode/decode path,
the audio callback, the FIFO/store paths or the Qwen delta loop.  Reading a session row only
reads already-existing attributes; it never mutates gateway state.
"""

import hashlib
import logging
import time
import weakref

log = logging.getLogger("rtl.admin.registry")


def _session_hash(conn, ordinal):
    """De-identified session label: sha256 of the session id (or the connection ordinal)."""
    ident = getattr(conn, "session_id", None) or "conn-%d" % ordinal
    return hashlib.sha256(str(ident).encode("utf-8")).hexdigest()[:16]


def _enum_label(value):
    return str(getattr(value, "value", None) or getattr(value, "name", None) or value)


class SessionRegistry:
    """Bounded, passive view over the live connections."""

    def __init__(self):
        self._refs = {}          # ordinal -> weakref.ref(Connection)
        self._opened = {}        # ordinal -> monotonic connect time

    # ---- lifecycle hooks (called from ws.py only) --------------------------

    def register(self, conn):
        try:
            ordinal = int(getattr(conn, "conn_ordinal", 0))
            self._refs[ordinal] = weakref.ref(conn)
            self._opened[ordinal] = time.monotonic()
        except Exception as e:                     # noqa: BLE001 - never break the WS path
            log.warning("registry.register skipped: %s", e)

    def discard(self, conn):
        try:
            ordinal = int(getattr(conn, "conn_ordinal", 0))
            self._refs.pop(ordinal, None)
            self._opened.pop(ordinal, None)
        except Exception as e:                     # noqa: BLE001
            log.warning("registry.discard skipped: %s", e)

    # ---- read side --------------------------------------------------------

    def count(self):
        self._gc()
        return len(self._refs)

    def _gc(self):
        for ordinal, ref in list(self._refs.items()):
            if ref() is None:
                self._refs.pop(ordinal, None)
                self._opened.pop(ordinal, None)

    def snapshot(self):
        """Return one sanitized row per live session (no raw ids, no transcripts)."""
        self._gc()
        now = time.monotonic()
        rows = []
        for ordinal in sorted(self._refs):
            conn = self._refs[ordinal]()
            if conn is None:
                continue
            try:
                rows.append(self._row(conn, ordinal, now, self._opened.get(ordinal)))
            except Exception as e:                 # noqa: BLE001 - read must never raise
                log.warning("registry row skipped: %s", e)
        return rows

    @staticmethod
    def _behavior_row(conn):
        """Bounded routing metadata from the connection's BehaviorLink (read-only).

        Allowlisted fields only: single words / transcripts never leave the link
        (privacy boundary) — this is routing state and counters, nothing else.
        """
        behavior = getattr(conn, "behavior", None)
        if behavior is None:
            return None
        try:
            snap = behavior.snapshot() or {}
        except Exception as e:                     # noqa: BLE001
            log.warning("registry behavior row skipped: %s", e)
            return None
        return {
            "activity": snap.get("activity"),
            "scenario": snap.get("scenario"),
            "temporary_intent": snap.get("temporary_intent"),
            "language_override": snap.get("language_override"),
            "speed": snap.get("speed"),
            "difficulty": snap.get("difficulty"),
            "pending_apply": bool(snap.get("pending_apply", False)),
            "policy_version": snap.get("policy_version"),
            "stats": {k: v for k, v in (snap.get("stats") or {}).items()
                      if isinstance(v, (int, float, bool, str)) or v is None},
        }

    @staticmethod
    def _row(conn, ordinal, now, opened):
        qwen = getattr(conn, "qwen", None)
        tts_active = bool(getattr(conn, "tts_active", False))
        pacer_active = getattr(conn, "pacer_task", None) is not None
        age = round(now - opened, 3) if opened is not None else None
        return {
            "session_id_hash": _session_hash(conn, ordinal),
            "state": _enum_label(getattr(conn, "state", "UNKNOWN")),
            "connected": True,
            "qwen_connected": bool(getattr(qwen, "connected", False)) if qwen is not None else False,
            "generation_active": bool(tts_active or pacer_active),   # derived
            "tts_active": tts_active,
            "pacer_active": pacer_active,
            # honestly not instrumented: no hot-path timestamping was added in ADMIN-1
            "last_activity_ms": None,
            "last_activity_reason": "not_instrumented",
            "age_s": age,
            "uptime_s": age,
            # ADMIN-2: bounded behavior/routing metadata (sanitized allowlist)
            "behavior": SessionRegistry._behavior_row(conn),
        }


sessions = SessionRegistry()