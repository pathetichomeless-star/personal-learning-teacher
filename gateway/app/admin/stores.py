"""ADMIN-2 control-plane store bundle + bounded, sanitized admin audit.

The bundle is wired by `main.py` from the same runtime config the gateway uses
(`POLICY_FILE` / `MEMORY_FILE` / `KNOWLEDGE_FILE` / `WORKBENCH_BASE_URL`).  When
the bundle is absent, `create_admin_app` mounts exactly the ADMIN-1 read-only
surface (full backward compatibility).

Every store instance here is the *same* on-disk source of truth the gateway
uses; live sessions pick changes up via their file-signature reloads (policy at
the next safe boundary) or on reconnect.
"""

import logging
import os
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger("rtl.admin.stores")


def _ensure_modules_importable():
    """Make `modules/` importable in both layouts (repo dev / container /app)."""
    here = Path(__file__).resolve()
    for base in (here.parents[2], here.parents[3]):
        if (base / "modules").is_dir():
            if str(base) not in sys.path:
                sys.path.insert(0, str(base))
            return str(base)
    return None


_ensure_modules_importable()

from modules.adapters.workbench import WorkbenchClient      # noqa: E402
from modules.knowledge.imports import ImportStore           # noqa: E402
from modules.knowledge.store import KnowledgeStore          # noqa: E402
from modules.memory.store import MemoryStore                # noqa: E402
from modules.model.credentials import CredentialStore       # noqa: E402
from modules.model.registry import ModelRegistry            # noqa: E402
from modules.policy.persona import PolicyStore              # noqa: E402
from modules.teacher.store import TeacherStore              # noqa: E402
from modules.teaching.store import TeachingSessionStore     # noqa: E402
from modules.voice.session import VoiceChannelStore         # noqa: E402


class AdminAudit:
    """Bounded in-memory admin action log.  Sanitized by construction: actions,
    coarse subjects (ids / entity names / changed field paths), never values,
    never transcripts, never secrets."""

    def __init__(self, cap=200):
        self._cap = int(cap)
        self._items = []
        self._lock = threading.Lock()

    def append(self, action, *, actor="admin", subject=None, changed=None,
               result="ok"):
        with self._lock:
            self._items.append({
                "ts": time.time(),
                "action": str(action),
                "actor": str(actor or "admin"),
                "subject": (str(subject) if subject is not None else None),
                "changed": [str(c) for c in (changed or [])][:40],
                "result": str(result),
            })
            self._items = self._items[-self._cap:]

    def recent(self, limit=50):
        with self._lock:
            return list(self._items[-max(1, int(limit)):])


class AdminStores:
    """Control-plane view of the product stores (created lazily, fail-soft)."""

    def __init__(self, *, policy_file="", memory_file="", knowledge_file="",
                 workbench_url="", model_registry_file="",
                 model_credentials_file="", model_credentials_key_file="",
                 knowledge_import_file="", knowledge_import_scratch="",
                 teacher_file="", teaching_file="", voice_file="",
                 realtime_snapshot=None,
                 test_authorized=False, promote_authorized=False,
                 realtime_probe_authorized=False):
        self.policy = self._try(lambda: PolicyStore(policy_file).load(),
                                bool(policy_file), "policy")
        self.memory = self._try(lambda: MemoryStore(memory_file).load(),
                                bool(memory_file), "memory")
        self.knowledge = self._try(lambda: KnowledgeStore(knowledge_file).load(),
                                   bool(knowledge_file), "knowledge")
        self.workbench = self._try(lambda: WorkbenchClient(workbench_url),
                                   bool(workbench_url), "workbench")
        # ---- V4 (additive) ----
        self.model_registry = self._try(
            lambda: ModelRegistry(model_registry_file).load().ensure_seeded(),
            bool(model_registry_file), "model_registry")
        self.model_credentials = self._try(
            lambda: CredentialStore(model_credentials_file,
                                    key_path=model_credentials_key_file).load(),
            bool(model_credentials_file), "model_credentials")
        self.knowledge_imports = self._try(
            lambda: ImportStore(knowledge_import_file,
                                scratch_dir=(knowledge_import_scratch or None)).load(),
            bool(knowledge_import_file), "knowledge_imports")
        # P1 multi-teacher: independent teacher-profile store (seeds frozen Tina).
        self.teacher = self._try(
            lambda: TeacherStore(teacher_file).load().ensure_seeded(),
            bool(teacher_file), "teacher")
        # P2-A teaching sessions: real text-teaching sessions + classroom records.
        self.teaching = self._try(
            lambda: TeachingSessionStore(teaching_file).load(),
            bool(teaching_file), "teaching")
        # P2-B1 voice channels: the audio-transport lifecycle of a voice classroom.
        # Additive and off by default: with no VOICE_FILE the voice surface simply
        # is not mounted and the frozen Tina link is untouched.
        self.voice = self._try(
            lambda: VoiceChannelStore(voice_file).load(),
            bool(voice_file), "voice")
        self.test_authorized = bool(test_authorized)
        # independent authorization for the explicit ``realtime_safe`` promotion
        # (contract §2.3 step 3); off unless the product owner switches it on.
        self.promote_authorized = bool(promote_authorized)
        # P2-B2-R3-2C: independent flag for the realtime-handshake evidence
        # channel (default off).  A probe writes at most `realtime_handshake`.
        self.realtime_probe_authorized = bool(realtime_probe_authorized)
        self.frozen_link = self._detect_frozen(realtime_snapshot)
        self.audit = AdminAudit()

    def _detect_frozen(self, snapshot):
        """Auto-detect the existing frozen Tina realtime link (read-only mirror)."""
        if self.model_registry is None or not snapshot:
            return None
        try:
            return self.model_registry.ensure_frozen_link(snapshot)
        except Exception as e:  # noqa: BLE001  (never fail the plane on detection)
            log.warning("frozen-link detection skipped: %r", e)
            return None

    @staticmethod
    def _try(factory, enabled, name):
        if not enabled:
            return None
        try:
            return factory()
        except Exception as e:  # noqa: BLE001  (fail-soft: the plane degrades honestly)
            log.warning("admin store %s unavailable: %r", name, e)
            return None

    def describe(self):
        return {"policy": self.policy is not None,
                "memory": self.memory is not None,
                "knowledge": self.knowledge is not None,
                "workbench": self.workbench is not None,
                "model_registry": self.model_registry is not None,
                "model_credentials": self.model_credentials is not None,
                "knowledge_imports": self.knowledge_imports is not None,
                "teacher": self.teacher is not None,
                "teaching": self.teaching is not None,
                "voice": self.voice is not None,
                "frozen_link_detected": self.frozen_link is not None}