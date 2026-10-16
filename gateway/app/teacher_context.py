"""P2-B2-R2 TEACHER TEACHING CONTEXT — a NON-FROZEN projection layer that feeds
P2-A's teaching rules, material retrieval and classroom records into the P2-B2
teacher realtime voice session.

Why this file exists (P2-B2-R2 MINIMAL_CONTEXT_DESIGN, NEED_FROZEN_CHANGE = NO)
------------------------------------------------------------------------------
`turns.Connection` hands the whole per-connection config to `BehaviorLink`, whose
ONLY config reads are four keys -- `MEMORY_FILE`, `WORKBENCH_BASE_URL`,
`KNOWLEDGE_FILE`, `POLICY_FILE` (all `getattr(..., "")`).  The rendered
`instructions` therefore come from whatever those three stores contain.  That is
the entire injection surface, and it lives OUTSIDE the frozen files.

Three consequences drive this module:

* **TEACHER POLICY** — the teacher's own instruction can be injected as a
  *policy projection*: `modules/teacher/store.py::render_system_instruction` is
  reused (never re-implemented) and its declared fields are written into a
  `PolicyStore`-shaped file that `render_instructions` actually renders.
* **MATERIAL** — the frozen `behavior.py` searches whatever file is mounted
  WITHOUT a dataset filter, so a whitelist can only be enforced by making the
  mounted file *itself* contain only the authorised datasets.  Hence the
  knowledge **projection**: copy only `teacher.knowledge.dataset_ids` (and only
  the enabled ones) out of the global knowledge base.  Complete private
  knowledge is never injected wholesale, and an empty authorisation degrades to
  general teaching honestly (never to the whole library).
* **MEMORY** — there is no trustworthy student identity on this path, and
  `BehaviorLink` builds its `MemoryStore` with the default user.  Per the
  acceptance rules the private memory read/write is therefore **DISABLED**
  (fail-closed) rather than defaulted to "authorised".  See
  ``MEMORY_REASON_DISABLED``.

Nothing here touches the audio plane.  The optional classroom-record observer
wraps `QwenClient.on_event` — a plain instance attribute (qwen.py) — to READ the
real upstream transcript events; it never inspects, delays or modifies audio.

Frozen files are read-only dependencies and are never modified:
gateway/app/{turns,qwen,audio,protocol,ws,behavior}.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import tempfile

log = logging.getLogger("rtl.teacher_context")

# --- honest reason codes (a disabled feature is never reported as "isolated") --
POLICY_REASON_OK = "policy_projected"
POLICY_REASON_UNAVAILABLE = "policy_teacher_record_unavailable"
POLICY_REASON_INVALID = "policy_projection_unusable"

KB_REASON_OK = "knowledge_projected"
KB_REASON_SOURCE_MISSING = "knowledge_source_not_configured"
KB_REASON_NO_AUTH = "knowledge_no_authorized_dataset"
KB_REASON_EMPTY = "knowledge_authorized_dataset_empty"
KB_REASON_UNREADABLE = "knowledge_source_unreadable"
KB_REASON_INVALID = "knowledge_projection_unusable"

MEMORY_REASON_DISABLED = "memory_scope_unavailable"

RECORD_REASON_NOT_CONFIGURED = "teaching_store_not_configured"
RECORD_REASON_NO_IDENTITY = "teaching_record_identity_unavailable"
RECORD_REASON_NO_BINDING = "teaching_record_model_binding_unavailable"
RECORD_REASON_STORE_UNAVAILABLE = "teaching_store_unavailable"
RECORD_REASON_OK = "teaching_record_active"

#: Real upstream events that carry the FINAL transcript text (mirrors the two
#: the frozen engine itself maps to UI transcripts: turns.py::_transcript_args).
TRANSCRIPT_EVENTS = {
    "conversation.item.input_audio_transcription.completed": "student",
    "response.audio_transcript.done": "teacher",
}

_INVISIBLE_RE = re.compile("[\u00ad\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
_CTRL_RE = re.compile("[\x00-\x1f\x7f]")
_WS_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def sanitize_line(text, cap):
    """Single-line, visible text.

    The policy schema rejects control characters ("a newline in an editable field
    would forge a product-style line") and invisible-only values, so every
    projected string goes through here before it is written.
    """
    s = _INVISIBLE_RE.sub("", str(text if text is not None else ""))
    s = _CTRL_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    if cap and len(s) > int(cap):
        s = s[:int(cap)].rstrip()
    return s


def safe_component(name):
    """A single, safe path component (never a traversal, never a separator).

    Defence in depth: teacher ids are validated upstream, but a projection writes
    a real path, so a control character or a separator must never reach it.
    """
    s = str(name or "").strip()
    if not s or s in (".", ".."):
        return ""
    if _CTRL_RE.search(s) or _INVISIBLE_RE.search(s):
        return ""
    if os.sep in s or "/" in s or "\\" in s or ":" in s:
        return ""
    return s


def _read_bytes(path):
    with open(str(path), "rb") as f:
        return f.read()


def _ensure_dir(path):
    """Create + tighten the containing directory to 0700.

    Projections hold a teacher's OWN teaching rules, so they must not be readable
    by other local accounts.  This runs on EVERY projection — not just on the
    first write — so a directory that was widened externally is re-tightened even
    when the projected content itself is unchanged.
    """
    d = os.path.dirname(os.path.abspath(str(path)))
    os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:  # not ours to change (e.g. a read-only mount)
        pass
    return d


def _atomic_write_bytes(path, data):
    """tmp -> os.replace, mode 600 (same discipline as the product stores)."""
    d = _ensure_dir(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _write_if_changed(path, data):
    """Idempotent, deterministic write (avoids needless reload churn).

    The directory is hardened even on the "nothing changed" path, so the early
    return can never leave a widened directory behind.
    """
    _ensure_dir(path)
    try:
        if _read_bytes(path) == data:
            return False
    except OSError:
        pass
    _atomic_write_bytes(path, data)
    return True


def _dump(doc):
    return json.dumps(doc, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# A. teacher policy projection
# ---------------------------------------------------------------------------

def build_teacher_policy(rec):
    """``(partial_policy, fields)`` for THIS teacher's own instruction.

    Reuses the single authoritative renderer (`render_system_instruction`) and
    only writes fields that (a) exist in the policy schema and (b) are actually
    rendered by `render_instructions` -- `persona.name`, `persona.role`,
    `persona.personality` (+ the validated `language.default`).

    Returns ``({}, [])`` when nothing trustworthy can be built; the caller then
    mounts NO policy file at all (the neutral built-in default stays in place --
    another teacher's prompt is never substituted).
    """
    if not isinstance(rec, dict):
        return {}, []
    try:
        from modules.policy.persona import DEFAULT_POLICY, validate_policy
        from modules.teacher.store import render_system_instruction
    except Exception as e:  # noqa: BLE001
        log.warning("teacher context: policy deps unavailable: %r", e)
        return {}, []
    # NOTE: the file carries the POLICY schema version (the reader that matters),
    # never this module's own version.
    try:
        cap = int((DEFAULT_POLICY.get("limits") or {}).get("max_field_chars") or 0)
    except (TypeError, ValueError):
        cap = 0
    cap = cap or 600

    try:
        full = str(render_system_instruction(rec) or "")
    except Exception as e:  # noqa: BLE001
        log.warning("teacher context: system instruction render failed: %r", e)
        full = ""
    head, _sep, core = full.partition("\n")

    persona = {}
    name = sanitize_line(rec.get("name"), 120)
    if name:
        persona["name"] = name
    role = sanitize_line(head.rstrip("。").strip(), cap)
    if role:
        persona["role"] = role
    personality = sanitize_line(core, cap)
    if personality:
        persona["personality"] = personality

    policy = {}
    if persona:
        policy["persona"] = persona
    lang = str(rec.get("language") or "").strip()
    if lang in ("zh", "en"):
        policy["language"] = {"default": lang}
    if not policy:
        return {}, []

    # the schema is the authority (unknown keys / bad values are errors)
    try:
        _merged, errors = validate_policy(policy)
    except Exception as e:  # noqa: BLE001
        log.warning("teacher context: policy validation failed: %r", e)
        return {}, []
    if errors:
        log.warning("teacher context: projected policy rejected: %s", errors[:3])
        return {}, []

    fields = []
    for section in sorted(policy):
        for key in sorted(policy[section]):
            fields.append("%s.%s" % (section, key))
    return policy, fields


def verify_policy_file(path, policy):
    """Read the file back through the real PolicyStore and confirm our fields."""
    try:
        from modules.policy.persona import PolicyStore
        active = PolicyStore(path).load().active() or {}
        got = active.get("policy") or {}
    except Exception as e:  # noqa: BLE001
        log.warning("teacher context: policy read-back failed: %r", e)
        return False
    for section, values in policy.items():
        cur = got.get(section)
        if not isinstance(cur, dict):
            return False
        for key, want in values.items():
            if cur.get(key) != want:
                return False
    return True


def project_teacher_policy(rec, target_path):
    """``(state, reason, fields, policy)`` -- write + read-back verify the file."""
    policy, fields = build_teacher_policy(rec)
    if not policy:
        return "disabled", POLICY_REASON_UNAVAILABLE, [], {}
    try:
        from modules.policy.persona import SCHEMA_VERSION as schema_version
    except Exception:  # noqa: BLE001  (the builder above already imported it)
        return "disabled", POLICY_REASON_INVALID, [], {}
    # ``updated_at: 0`` (not the wall clock) so that re-projecting the SAME
    # teacher is byte-identical and never rewrites the file (the projection is a
    # pure function of the teacher record, not of the moment it was written).
    doc = {
        "schema_version": int(schema_version),
        "active": {"version": 1, "policy": policy, "updated_at": 0,
                   "actor": "teacher_voice"},
        "history": [],
        "audit": [],
    }
    try:
        _write_if_changed(target_path, _dump(doc))
    except Exception as e:  # noqa: BLE001
        log.warning("teacher context: policy write failed: %r", e)
        return "disabled", POLICY_REASON_INVALID, [], {}
    if not verify_policy_file(target_path, policy):
        return "disabled", POLICY_REASON_INVALID, [], {}
    return "ok", POLICY_REASON_OK, fields, policy


# ---------------------------------------------------------------------------
# B. authorised material projection
# ---------------------------------------------------------------------------

def project_teacher_knowledge(source_path, dataset_ids, target_path):
    """``(state, reason, info)`` -- a whitelist enforced by construction.

    Copy ONLY the teacher's authorised, enabled datasets (their documents and
    their original chunks) out of the global knowledge base into a per-teacher
    file.  The frozen retrieval then searches a file that simply cannot contain
    anything else.

    An empty / absent authorisation degrades to general teaching honestly: the
    caller mounts NO knowledge file rather than the whole library.
    """
    info = {"dataset_ids": [], "datasets": 0, "chunks": 0, "sha256": ""}
    want = [str(x) for x in (dataset_ids or []) if str(x or "").strip()]
    if not want:
        return "disabled", KB_REASON_NO_AUTH, info
    src = str(source_path or "").strip()
    if not src or not os.path.isfile(src):
        return "disabled", KB_REASON_SOURCE_MISSING, info
    try:
        raw = json.loads(_read_bytes(src).decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("teacher context: knowledge source unreadable: %r", e)
        return "disabled", KB_REASON_UNREADABLE, info
    if not isinstance(raw, dict):
        return "disabled", KB_REASON_UNREADABLE, info

    src_ds = raw.get("datasets") if isinstance(raw.get("datasets"), dict) else {}
    src_docs = raw.get("documents") if isinstance(raw.get("documents"), dict) else {}
    src_chunks = raw.get("chunks") if isinstance(raw.get("chunks"), dict) else {}

    datasets, docs, chunks, used = {}, {}, {}, []
    for did in want:
        rec = src_ds.get(did)
        # an authorised dataset that is disabled / missing is NEVER substituted
        if not isinstance(rec, dict) or str(rec.get("status") or "") != "enabled":
            continue
        datasets[did] = rec
        used.append(did)
    if not datasets:
        return "disabled", KB_REASON_NO_AUTH, info

    for doc_id, doc in src_docs.items():
        if isinstance(doc, dict) and str(doc.get("dataset_id") or "") in datasets:
            docs[doc_id] = doc
    for chunk_id, chunk in src_chunks.items():
        if isinstance(chunk, dict) and str(chunk.get("document_id") or "") in docs:
            chunks[chunk_id] = chunk
    if not chunks:
        info["dataset_ids"] = sorted(used)
        info["datasets"] = len(datasets)
        return "disabled", KB_REASON_EMPTY, info

    # the file must carry the KNOWLEDGE schema version the reader validates
    from modules.knowledge.store import SCHEMA_VERSION as kb_schema_version
    doc = {"version": int(kb_schema_version), "datasets": datasets,
           "documents": docs, "chunks": chunks}
    try:
        data = _dump(doc)
        _write_if_changed(target_path, data)
    except Exception as e:  # noqa: BLE001
        log.warning("teacher context: knowledge write failed: %r", e)
        return "disabled", KB_REASON_INVALID, info

    info = {"dataset_ids": sorted(used), "datasets": len(datasets),
            "chunks": len(chunks), "sha256": _sha(data)[:16]}
    ok, reason = _verify_knowledge(target_path, used)
    if not ok:
        return "disabled", reason, info
    return "ok", KB_REASON_OK, info


def _verify_knowledge(path, dataset_ids):
    """Load the projection through the REAL KnowledgeStore and search it.

    This is the objective check that the material a teacher is authorised for is
    actually retrievable by the very code path the frozen engine uses.
    """
    try:
        from modules.knowledge.store import KnowledgeStore
        st = KnowledgeStore(path).load()
        if not st.available or st.state().get("state") != "ok":
            return False, KB_REASON_INVALID
        for did in dataset_ids:
            docs = st.list_documents(dataset_id=did)
            probe = ""
            for d in docs:
                got = st.list_chunks(d.get("id"), limit=1)
                if got:
                    probe = str(got[0].get("text") or "")
                    break
            if not probe:
                continue
            # only searchable text can be probed; a tokenless chunk (pure
            # punctuation / emoji) is not a verification failure
            if not re.search(r"[a-z0-9\u4e00-\u9fff]", probe.lower()):
                continue
            hits = st.search(probe[:40], dataset_id=did, min_score=1)
            if not hits:
                return False, KB_REASON_INVALID
        return True, KB_REASON_OK
    except Exception as e:  # noqa: BLE001
        log.warning("teacher context: knowledge verification failed: %r", e)
        return False, KB_REASON_INVALID


# ---------------------------------------------------------------------------
# C. memory scope decision (fail-closed)
# ---------------------------------------------------------------------------

def memory_decision():
    """``(path, reason)`` -- private memory stays DISABLED on this path.

    There is no server-authoritative student identity here, and `BehaviorLink`
    would build one shared `MemoryStore` (default user) for every student of the
    teacher.  Reading or writing private memory under those conditions is not
    "isolated", it is "unattributed", so by the acceptance rules it is DISABLED
    until a trustworthy identity source exists.  Activating it needs a product
    decision plus a write-back design -- it is NOT silently enabled here.
    """
    return "", MEMORY_REASON_DISABLED


# ---------------------------------------------------------------------------
# whole-connection projection
# ---------------------------------------------------------------------------

def project_teacher_context(*, teacher, data_dir, knowledge_source=""):
    """Materialise this teacher's own policy + material projections.

    Returns a context record used to configure the connection and to report
    honestly:

        {"teacher_id", "policy": {...}, "knowledge": {...}, "memory": {...}}

    Every failure leaves the corresponding path EMPTY (fail-closed): a
    half-applied context is never presented as a working one.
    """
    tid = str((teacher or {}).get("teacher_id") or "")
    rec = {
        "teacher_id": tid,
        "policy": {"state": "disabled", "reason": POLICY_REASON_UNAVAILABLE,
                   "path": "", "fields": [], "built": {}},
        "knowledge": {"state": "disabled", "reason": KB_REASON_SOURCE_MISSING,
                      "path": "", "dataset_ids": [], "datasets": 0, "chunks": 0},
        "memory": {"state": "disabled", "reason": MEMORY_REASON_DISABLED, "path": ""},
    }
    comp = safe_component(tid)
    base = str(data_dir or "").strip()
    if not base or not comp:
        return rec
    d = os.path.join(base, comp)

    p_state, p_reason, p_fields, p_built = project_teacher_policy(
        teacher, os.path.join(d, "policy.json"))
    rec["policy"] = {
        "state": p_state, "reason": p_reason,
        "path": (os.path.join(d, "policy.json") if p_state == "ok" else ""),
        "fields": p_fields,
        # the partial policy as injected (so callers/tests never re-render it)
        "built": p_built,
    }

    authorized = ((teacher or {}).get("knowledge") or {}).get("dataset_ids") or []
    k_state, k_reason, k_info = project_teacher_knowledge(
        knowledge_source, authorized, os.path.join(d, "knowledge.json"))
    rec["knowledge"] = {
        "state": k_state, "reason": k_reason,
        "path": (os.path.join(d, "knowledge.json") if k_state == "ok" else ""),
        "dataset_ids": k_info.get("dataset_ids") or [],
        "datasets": k_info.get("datasets") or 0,
        "chunks": k_info.get("chunks") or 0,
    }

    mem_path, mem_reason = memory_decision()
    rec["memory"] = {"state": "disabled", "reason": mem_reason, "path": mem_path}
    return rec


# ---------------------------------------------------------------------------
# D. classroom records from REAL transcripts (observer; default OFF)
# ---------------------------------------------------------------------------

def realtime_transcript(obj):
    """``(role, text)`` for a REAL final transcript event, else ``None``.

    Only the two terminal events are used: deltas are cumulative/revisable
    previews, and a partial preview must never be recorded as a learner turn.
    """
    if not isinstance(obj, dict):
        return None
    role = TRANSCRIPT_EVENTS.get(str(obj.get("type") or ""))
    if role is None:
        return None
    text = str(obj.get("transcript") or "").strip()
    if not text:
        return None
    return role, text


class TeachingRecordObserver:
    """Records REAL realtime transcripts into the P2-A classroom record.

    * observation is SYNCHRONOUS and allocation-light -- it runs inside the
      upstream receive path, so it must never await or block (`observe`);
    * writes happen on a worker thread during the drain, never in the receive
      path (`drain`/`finish`);
    * the session is ended with NO outcome, so the store's evidence gate derives
      everything: with no audio evidence there is no pronunciation or learning
      verdict to fabricate.
    """

    MAX_PENDING = 400
    #: mirror of the teaching store's own per-turn cap (modules/teaching/store.py
    #: ``MAX_TURN_CHARS``): an over-long upstream transcript is truncated here
    #: rather than rejected at write time, so a single runaway turn can never
    #: silently drop the rest of the class.
    MAX_TURN_CHARS = 4000

    def __init__(self, store, session_id):
        self._store = store
        self.session_id = str(session_id)
        self._pending = []
        self.stats = {"observed": 0, "written": 0, "dropped": 0, "errors": 0,
                      "truncated": 0}
        self.attached = False

    def observe(self, obj):
        """Read-only tap: NEVER raises, NEVER awaits, NEVER touches audio."""
        try:
            got = realtime_transcript(obj)
            if got is None:
                return
            self.stats["observed"] += 1
            if len(self._pending) >= self.MAX_PENDING:
                self.stats["dropped"] += 1
                return
            role, text = got
            if len(text) > self.MAX_TURN_CHARS:
                text = text[:self.MAX_TURN_CHARS]
                self.stats["truncated"] += 1
            self._pending.append((role, text))
        except Exception:  # noqa: BLE001  (an observer never breaks the session)
            pass

    def attach(self, conn):
        """Wrap ``conn.qwen.on_event`` (a plain instance attribute) read-only."""
        qwen = getattr(conn, "qwen", None)
        original = getattr(qwen, "on_event", None)
        if qwen is None or not callable(original):
            return False
        observer = self

        async def tapped(obj):
            observer.observe(obj)
            return await original(obj)

        try:
            qwen.on_event = tapped
        except Exception as e:  # noqa: BLE001
            log.warning("teacher context: transcript tap not installed: %r", e)
            return False
        self.attached = True
        return True

    async def drain(self):
        while self._pending:
            role, text = self._pending.pop(0)
            try:
                await asyncio.to_thread(
                    self._store.append_turn, self.session_id,
                    role=role, text=text, kind="text")
                self.stats["written"] += 1
            except Exception as e:  # noqa: BLE001
                self.stats["errors"] += 1
                log.warning("teacher context: turn not recorded: %r", e)

    async def finish(self):
        """Drain, then end the session WITHOUT an outcome (nothing invented)."""
        await self.drain()
        try:
            await asyncio.to_thread(self._store.end_session, self.session_id)
        except Exception as e:  # noqa: BLE001
            self.stats["errors"] += 1
            log.warning("teacher context: classroom record not closed: %r", e)
        return dict(self.stats)


def open_teaching_record(*, store, student_id, teacher, binding, dataset_ids,
                         policy=None, course_id=""):
    """``(observer, reason)`` -- OFF unless configured BOTH ways.

    A classroom record is written only when the deployment supplies a teaching
    store AND a SERVER-side student label.  The client can never declare either,
    and an unattributed record is never invented.
    """
    if store is None:
        return None, RECORD_REASON_NOT_CONFIGURED
    student = str(student_id or "").strip()
    if not student:
        # no trustworthy identity -> no private/attributable record is created
        return None, RECORD_REASON_NO_IDENTITY
    if not binding or not binding.get("model_id") or not binding.get("model_key"):
        return None, RECORD_REASON_NO_BINDING
    try:
        sess = store.create_session(
            teacher_id=str(teacher.get("teacher_id") or ""), student_id=student,
            model_id=binding["model_id"], model_key=binding["model_key"],
            provider_id=str(binding.get("provider_id") or ""),
            teacher_name=str(teacher.get("name") or ""),
            knowledge_dataset_ids=list(dataset_ids or []),
            course_id=str(course_id or ""),
            teaching_policy=dict(policy or {}),
            modality="voice", voice=(teacher.get("voice") or {}))
    except Exception as e:  # noqa: BLE001
        log.warning("teacher context: classroom record not opened: %r", e)
        return None, RECORD_REASON_STORE_UNAVAILABLE
    return TeachingRecordObserver(store, sess["session_id"]), RECORD_REASON_OK
