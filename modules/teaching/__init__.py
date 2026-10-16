"""TEACHING (P2-A): real text-teaching sessions — session store + text-model engine.

Ownership: `modules/teaching`.  Pure logic + one JSON file (atomic 600 writes,
version-gated, cross-process locked); NO gateway/audio imports, no WebSocket.

Two strictly separated pieces:

* :mod:`modules.teaching.store`  — an independent **teaching session** record
  (session_id / teacher_id / student_id / model_id / knowledge_dataset_ids /
  course_id / teaching_policy / start·end / status / turns / outcome).  It never
  copies model or knowledge payloads: it references them by stable id.
* :mod:`modules.teaching.engine` — prompt assembly plus a **real** OpenAI-compatible
  text call.  It never fabricates a completion: a failed call raises instead of
  returning invented content.

The classroom record owns learning *outcomes* (knowledge points / weak points /
review items) because the learner :class:`modules.memory.store.MemoryStore` has a
hard boundary that refuses progress-shaped data by contract.  Durable learner
memory (explicit facts / weak vocabulary) is written to the memory store with the
``(student_id, teacher_id)`` scope, never from this module.

P2-B1 adds an **evidence gate**: a learning result must be traceable to real
dialogue / speech / scoring evidence.  With no audio input there is no
pronunciation verdict (the field is reported ``unassessed``), and refused items
are returned with an explicit reason instead of being invented.
"""

from modules.teaching.store import (  # noqa: F401
    EVIDENCE_KINDS, MODALITIES, STATUSES, TeachingSessionStore, SessionNotFound,
    TeachingInvalid, derive_evidence, public_outcome,
)
from modules.teaching.engine import (  # noqa: F401
    TextModelError, call_text_model, chat_url, compose_system,
)

__all__ = [
    "TeachingSessionStore", "SessionNotFound", "TeachingInvalid", "STATUSES",
    "MODALITIES", "EVIDENCE_KINDS", "derive_evidence", "public_outcome",
    "TextModelError", "call_text_model", "chat_url", "compose_system",
]
