"""TEACHING SESSION V1 (P2-A) — one independent teaching session + its classroom
record, persisted in a single JSON file.

Ownership: `modules/teaching`.  Pure data + validation + one JSON file (atomic 600
writes, version-gated, locked); NO gateway/audio imports, NOT an LLM.

A **teaching session** is created from *server-stored* teacher configuration and
references everything by stable id — it never copies model, knowledge or memory
payloads:

* ``session_id``            — ``ses_`` + hex, the identifier;
* ``teacher_id``            — the teacher that is actually teaching;
* ``student_id``            — the learner scope (student partition);
* ``model_id`` / ``model_key`` — the registry model id **and** the concrete
  ``model_key`` that was actually called (they must stay consistent);
* ``knowledge_dataset_ids`` — the datasets this teacher is authorized to teach
  from; retrieval is confined to exactly this set (or empty = no material);
* ``course_id``             — optional, open-ended course reference;
* ``teaching_policy``       — the effective, snapshotted teaching instructions;
* ``started_at`` / ``ended_at`` / ``status``;
* ``modality``               — 交流方式 (``text`` / ``voice``); a voice class shares
  this record but its audio transport + lifecycle live in `modules.voice.session`;
* ``voice``                  — the voice configuration snapshot the class ran with;
* ``turns``                 — the classroom dialogue (student + teacher), each
  teacher turn carrying the material provenance actually used; a speech turn
  additionally carries the accepted-audio **metadata** (never audio bytes);
* ``outcome``               — the saved learning result at the end of the class,
  gated on real evidence (see the evidence-gate section below).

The record is the ONLY owner of learning outcomes.  The learner
:class:`modules.memory.store.MemoryStore` refuses progress-shaped data by
contract, so knowledge points / weak points / review items live here and never in
memory.
"""

from __future__ import annotations

import copy
import logging
import re
import time
import uuid

from modules._jsonstore import (BaseJsonStore, ConfirmRequired,  # noqa: F401
                                PersistError, StoreUnavailable)

log = logging.getLogger("teaching.store")

SCHEMA_VERSION = 1

STATUSES = ("active", "ended")

# 交流方式：文字 / 语音。  语音课堂与文字课堂共享教学记录归属，但音频传输与
# 生命周期由语音通道单独管理（见 modules.voice.session）。
MODALITIES = ("text", "voice")

MAX_SESSIONS = 5000
MAX_TURNS = 200
MAX_TURN_CHARS = 4000
MAX_NOTE_CHARS = 1000
MAX_OUTCOME_ITEMS = 40
MAX_ITEM_CHARS = 200
MAX_DATASETS = 50
MAX_ID_CHARS = 64
MAX_STUDENT_CHARS = 64
MAX_NAME_CHARS = 60
MAX_POLICY_CHARS = 4000
MAX_FORMAT_CHARS = 24

_TURN_ROLES = ("student", "teacher", "system")
_TURN_KINDS = ("text", "speech")

# ---------------------------------------------------------------------------
# 证据门禁（P2-B1 · 修正 P2-A 学习评价）
#
# 学习结果必须可以追溯到真实证据。  没有语音输入时**不得**生成或确认发音分数、
# 音素错误等音频评价；不确定的能力状态显示为「尚未评估」。  这是一条服务端硬
# 规则：不依赖前端自觉，也不因为请求体里写了就相信。
# ---------------------------------------------------------------------------

EVIDENCE_KINDS = ("text_dialogue", "audio_speech")

# 「音频评价」声明：命中即视为对发音 / 音素 / 语音表现给出结论。
_AUDIO_CLAIM_RE = re.compile(
    r"发音|音素|音标|口音|语音|读音|朗读|语调|声调|重音|连读|弱读|听力|录音|"
    r"音频|口齿|吐字|断句|语速|跟读|"
    r"pronunc|phonem|phonetic|accent|intonat|pronounce|speech|listening|"
    r"utterance|fluenc|pronunciation",
    re.IGNORECASE)

# 记录型字段：这些字段里的条目必须能追溯到真实对话 / 练习 / 评分证据。
_OUTCOME_ITEM_FIELDS = ("knowledge_points", "weak_points", "review_items")


class TeachingInvalid(ValueError):
    """A candidate session / turn failed validation."""

    def __init__(self, errors):
        errors = list(errors)
        super().__init__("teaching_invalid: %s" % "; ".join(errors[:6]))
        self.errors = errors


class SessionNotFound(ValueError):
    """Unknown session id (or soft-deleted)."""


def _clean(value, what, cap, *, required=False, allow_newline=False):
    s = "" if value is None else str(value).strip()
    if required and not s:
        raise TeachingInvalid(["%s: 不能为空" % what])
    if len(s) > cap:
        raise TeachingInvalid(["%s: 过长（%d > %d）" % (what, len(s), cap)])
    if allow_newline:
        # newlines allowed, raw control characters are not (prevents forged lines)
        if any(ord(c) < 32 and c != "\n" for c in s) or "\x7f" in s:
            raise TeachingInvalid(["%s: 含非法控制字符" % what])
    else:
        if any(ord(c) < 32 for c in s) or "\x7f" in s:
            raise TeachingInvalid(["%s: 只能是单行文本" % what])
    return s


def _id_list(values, what):
    if values is None:
        return []
    if not isinstance(values, (list, tuple)):
        raise TeachingInvalid(["%s: 需要字符串列表" % what])
    out = []
    for v in values:
        if not isinstance(v, str):
            raise TeachingInvalid(["%s: 列表元素必须是字符串" % what])
        s = v.strip()[:MAX_ID_CHARS]
        if s and s not in out:
            out.append(s)
    if len(out) > MAX_DATASETS:
        raise TeachingInvalid(["%s: 过多" % what])
    return out


def _audio_meta(audio):
    """Normalize the metadata of one accepted audio frame (never the payload).

    Only *counts and formats* are stored — no audio bytes, no derived score.  A
    frame with ``bytes <= 0`` is not evidence of speech and is dropped, so a
    caller cannot manufacture audio evidence by sending an empty object.
    """
    if audio is None:
        return None
    if not isinstance(audio, dict):
        raise TeachingInvalid(["audio: 需要对象"])
    try:
        nbytes = int(audio.get("bytes") or 0)
    except (TypeError, ValueError):
        raise TeachingInvalid(["audio.bytes: 需要整数"])
    if nbytes <= 0:
        return None
    out = {"bytes": min(nbytes, 100 * 1024 * 1024),
           "input_format": _clean(audio.get("input_format"), "audio.input_format",
                                 MAX_FORMAT_CHARS),
           "sample_rate": max(0, min(int(audio.get("sample_rate") or 0), 384000)),
           "duration_ms": max(0, min(int(audio.get("duration_ms") or 0), 3600000)),
           "source": _clean(audio.get("source"), "audio.source", MAX_NAME_CHARS),
           "adapter_id": _clean(audio.get("adapter_id"), "audio.adapter_id", MAX_ID_CHARS)}
    # 发音评分只在该语音适配器**确实提供**评分时才可能被记录；否则显式为 None。
    score = audio.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        out["score"] = None
    else:
        out["score"] = max(0.0, min(float(score), 100.0))
    issues = audio.get("issues") or []
    out["issues"] = []
    if isinstance(issues, (list, tuple)):
        for v in issues[:MAX_OUTCOME_ITEMS]:
            s = _clean(v, "audio.issues", MAX_ITEM_CHARS)
            if s and s not in out["issues"]:
                out["issues"].append(s)
    if out["score"] is None and not out["issues"]:
        out["assessment_supported"] = False
    else:
        out["assessment_supported"] = True
    return out


def derive_evidence(rec):
    """Which evidence kinds this session record genuinely contains.

    Derived from the stored turns only — a request body can never widen it.
    """
    kinds, audio_turns, scored_turns, dialogue_turns = set(), 0, 0, 0
    for t in (rec.get("turns") or []):
        if not isinstance(t, dict):
            continue
        audio = t.get("audio")
        if isinstance(audio, dict) and int(audio.get("bytes") or 0) > 0:
            kinds.add("audio_speech")
            audio_turns += 1
            if audio.get("assessment_supported"):
                scored_turns += 1
        if t.get("role") in ("student", "teacher"):
            dialogue_turns += 1
            if not (isinstance(audio, dict) and int(audio.get("bytes") or 0) > 0):
                kinds.add("text_dialogue")
    return {"kinds": sorted(kinds), "audio_turns": audio_turns,
            "scored_turns": scored_turns, "dialogue_turns": dialogue_turns}


def _snapshot_voice(voice):
    """The voice configuration a session was actually opened with (display copy).

    It is stored **by value** on purpose: the classroom record must show which
    sound / adapter / policy was in force even if the teacher is edited later.
    The authoritative configuration still lives in the teacher store.
    """
    if voice is None:
        return None
    if not isinstance(voice, dict):
        raise TeachingInvalid(["voice: 需要对象"])
    out = {
        "adapter_id": _clean(voice.get("adapter_id"), "voice.adapter_id", MAX_ID_CHARS),
        "voice_id": _clean(voice.get("voice_id"), "voice.voice_id", MAX_NAME_CHARS),
        "language": _clean(voice.get("language"), "voice.language", MAX_FORMAT_CHARS),
        "accent": _clean(voice.get("accent"), "voice.accent", MAX_FORMAT_CHARS),
    }
    speed = voice.get("speed")
    out["speed"] = None if speed is None else max(0.5, min(float(speed), 2.0))
    mode = str(voice.get("mode") or "")
    out["mode"] = mode if mode in ("text", "realtime") else ""
    return out


class TeachingSessionStore(BaseJsonStore):
    """One JSON file holding every teaching session (keyed by session_id)."""

    SCHEMA_VERSION = SCHEMA_VERSION
    ROOT_KEYS = ("sessions",)

    # ---- helpers ---------------------------------------------------------

    def _all(self):
        return self._data["sessions"]

    # ---- create ----------------------------------------------------------

    def create_session(self, *, teacher_id, student_id, model_id, model_key,
                       provider_id="", teacher_name="", knowledge_dataset_ids=None,
                       course_id="", teaching_policy=None, model_is_local=False,
                       knowledge_scope_note="", modality="text", voice=None):
        teacher_id = _clean(teacher_id, "teacher_id", MAX_ID_CHARS, required=True)
        student_id = _clean(student_id or "default", "student_id", MAX_STUDENT_CHARS,
                            required=True)
        model_id = _clean(model_id, "model_id", MAX_ID_CHARS, required=True)
        model_key = _clean(model_key, "model_key", MAX_ID_CHARS, required=True)
        modality = str(modality or "text")
        if modality not in MODALITIES:
            raise TeachingInvalid(["modality: 未知交流方式"])
        policy = dict(teaching_policy or {})
        with self._lock.exclusive():
            self.reload_if_changed()
            if not self.available:
                raise StoreUnavailable(self._reason or "unavailable")
            if len(self._all()) >= MAX_SESSIONS:
                raise TeachingInvalid(["会话数量已达上限（%d）" % MAX_SESSIONS])
            now = time.time()
            sid = "ses_" + uuid.uuid4().hex[:12]
            rec = {
                "session_id": sid,
                "teacher_id": teacher_id,
                "teacher_name": _clean(teacher_name, "teacher_name", MAX_NAME_CHARS),
                "student_id": student_id,
                "model_id": model_id,
                "model_key": model_key,
                "provider_id": _clean(provider_id, "provider_id", MAX_ID_CHARS),
                "model_is_local": bool(model_is_local),
                "modality": modality,
                "voice": _snapshot_voice(voice),
                "knowledge_dataset_ids": _id_list(knowledge_dataset_ids,
                                                  "knowledge_dataset_ids"),
                "course_id": _clean(course_id, "course_id", MAX_ID_CHARS),
                "teaching_policy": policy,
                "knowledge_scope_note": _clean(knowledge_scope_note,
                                               "knowledge_scope_note", MAX_ITEM_CHARS),
                "status": "active",
                "started_at": now,
                "ended_at": None,
                "turns": [],
                "turn_count": 0,
                "outcome": None,
            }
            self._all()[sid] = rec
            self._persist()
            return copy.deepcopy(rec)

    # ---- read ------------------------------------------------------------

    def get_session(self, session_id):
        with self._lock:
            self.reload_if_changed()
            rec = self._all().get(str(session_id or ""))
            return copy.deepcopy(rec) if rec else None

    def list_sessions(self, *, teacher_id=None, student_id=None,
                      include_active=True, limit=100):
        """Scoped listing.  ``teacher_id`` / ``student_id`` filter when not None."""
        with self._lock:
            self.reload_if_changed()
            rows = []
            for rec in self._all().values():
                if teacher_id is not None and rec.get("teacher_id") != str(teacher_id):
                    continue
                if student_id is not None and rec.get("student_id") != str(student_id):
                    continue
                if not include_active and rec.get("status") != "ended":
                    continue
                rows.append(copy.deepcopy(rec))
            rows.sort(key=lambda r: (-(r.get("started_at") or 0), r["session_id"]))
            return rows[:max(1, int(limit))]

    def counts(self):
        rows = list(self._all().values())
        active = [r for r in rows if r.get("status") == "active"]
        return {"total": len(rows), "active": len(active),
                "ended": len(rows) - len(active)}

    # ---- mutate ----------------------------------------------------------

    def append_turn(self, session_id, *, role, text, sources=None, model_id=None,
                    kind="text", audio=None):
        role = str(role or "")
        if role not in _TURN_ROLES:
            raise TeachingInvalid(["role: 未知角色"])
        kind = str(kind or "text")
        if kind not in _TURN_KINDS:
            raise TeachingInvalid(["kind: 未知轮次类型"])
        text = _clean(text, "text", MAX_TURN_CHARS, required=True, allow_newline=True)
        meta = _audio_meta(audio)
        if kind == "speech" and meta is None:
            # a speech turn without accepted audio is not evidence: record it as text
            kind = "text"
        with self._lock.exclusive():
            self.reload_if_changed()
            rec = self._all().get(str(session_id or ""))
            if rec is None:
                raise SessionNotFound("unknown session")
            if rec.get("status") != "active":
                raise TeachingInvalid(["session_status: 课堂已结束"])
            turns = rec.setdefault("turns", [])
            if len(turns) >= MAX_TURNS:
                raise TeachingInvalid(["turns: 单节课对话轮次已达上限（%d）" % MAX_TURNS])
            src = []
            for s in (sources or []):
                if not isinstance(s, dict):
                    continue
                src.append({
                    "dataset_id": str(s.get("dataset_id") or "")[:MAX_ID_CHARS],
                    "dataset_name": str(s.get("dataset_name") or "")[:MAX_NAME_CHARS],
                    "document_title": str(s.get("document_title") or "")[:MAX_NAME_CHARS],
                    "document_id": str(s.get("document_id") or "")[:MAX_ID_CHARS],
                })
            turn = {"role": role, "text": text, "at": time.time(),
                    "kind": kind,
                    "sources": src,
                    "model_id": (str(model_id)[:MAX_ID_CHARS] if model_id else None)}
            if meta is not None:
                turn["audio"] = meta
            turns.append(turn)
            rec["turn_count"] = len(turns)
            rec["last_activity_at"] = turn["at"]
            self._persist()
            return copy.deepcopy(turn)

    def end_session(self, session_id, *, outcome=None, simulated=False):
        with self._lock.exclusive():
            self.reload_if_changed()
            rec = self._all().get(str(session_id or ""))
            if rec is None:
                raise SessionNotFound("unknown session")
            if rec.get("status") == "ended":
                # idempotent: ending an ended session returns the stored outcome
                return copy.deepcopy(rec)
            evidence = derive_evidence(rec)
            rec["outcome"] = _normalize_outcome(
                outcome, evidence=evidence,
                simulated=bool(simulated) or bool(rec.get("model_is_local")))
            rec["status"] = "ended"
            rec["ended_at"] = time.time()
            self._persist()
            return copy.deepcopy(rec)


def _pronunciation_state(evidence, declared):
    """The honest pronunciation verdict for one class.

    A score is only ever recorded when the session really contains audio speech
    **and** the voice adapter genuinely reported a score.  Everything else is
    explicitly ``unassessed`` — never a made-up weakness.
    """
    has_audio = "audio_speech" in set(evidence.get("kinds") or ())
    if not has_audio:
        return {"status": "unassessed", "reason": "no_audio_evidence", "score": None,
                "issues": [],
                "note": "本节课没有语音输入，因此不生成发音分数或音素错误。"}
    if not evidence.get("scored_turns"):
        return {"status": "unassessed", "reason": "adapter_no_assessment", "score": None,
                "issues": [],
                "note": "本节课有语音输入，但所用语音适配器不提供发音评分，"
                        "因此不做发音评价。"}
    score = None
    issues = []
    if isinstance(declared, dict):
        raw = declared.get("score")
        if not isinstance(raw, bool) and isinstance(raw, (int, float)):
            score = max(0.0, min(float(raw), 100.0))
        for v in (declared.get("issues") or [])[:MAX_OUTCOME_ITEMS]:
            s = _clean(v, "outcome.pronunciation.issues", MAX_ITEM_CHARS)
            if s and s not in issues:
                issues.append(s)
    if score is None and not issues:
        return {"status": "unassessed", "reason": "no_score_returned", "score": None,
                "issues": [],
                "note": "语音适配器未返回可用的发音评分，故不给出结论。"}
    out = {"status": "assessed", "score": score, "issues": issues,
           "scored_turns": int(evidence.get("scored_turns") or 0),
           "note": "发音评价来自本节课的语音评分证据。"}
    return out


def _normalize_outcome(outcome, *, evidence=None, simulated=False):
    """Validate + gate the learning result of one class.

    Hard rules (P2-B1 §一):

    * an item is only stored when the session really contains the evidence it
      claims — no audio evidence means no pronunciation / phoneme verdicts;
    * a class with no evidence at all stores **no** learning claims, and the
      fields are reported as ``unassessed`` instead of being invented;
    * refused items are returned in ``rejected_items`` with a reason, so the UI
      can show what was dropped instead of silently losing it;
    * simulated (local test) results are labelled ``simulated: true``.
    """
    if outcome is None:
        outcome = {}
    if not isinstance(outcome, dict):
        raise TeachingInvalid(["outcome: 需要对象"])
    ev = dict(evidence or {})
    kinds = set(ev.get("kinds") or ())
    has_audio = "audio_speech" in kinds
    dialogue_turns = int(ev.get("dialogue_turns") or 0)
    has_any_evidence = bool(kinds) and (dialogue_turns > 0 or has_audio)

    out, rejected = {}, []
    for field in _OUTCOME_ITEM_FIELDS:
        vals = outcome.get(field) or []
        if not isinstance(vals, (list, tuple)):
            raise TeachingInvalid(["outcome.%s: 需要列表" % field])
        items = []
        for v in vals:
            s = _clean(v, "outcome.%s" % field, MAX_ITEM_CHARS)
            if not s or s in items:
                continue
            if not has_any_evidence:
                rejected.append({"field": field, "item": s,
                                 "reason": "no_evidence",
                                 "detail": "本节课没有可追溯的对话 / 语音 / 评分证据。"})
                continue
            if _AUDIO_CLAIM_RE.search(s) and not has_audio:
                rejected.append({"field": field, "item": s,
                                 "reason": "no_audio_evidence",
                                 "detail": "本节课没有语音输入，不能给出音频 / 发音评价。"})
                continue
            items.append(s)
        if len(items) > MAX_OUTCOME_ITEMS:
            items = items[:MAX_OUTCOME_ITEMS]
        out[field] = items

    notes = _clean(outcome.get("notes"), "outcome.notes", MAX_NOTE_CHARS,
                   allow_newline=True)
    if notes and not has_any_evidence:
        rejected.append({"field": "notes", "item": notes[:MAX_ITEM_CHARS],
                         "reason": "no_evidence",
                         "detail": "本节课没有可追溯的证据，备注未被记录为学习结果。"})
        notes = ""
    elif notes and _AUDIO_CLAIM_RE.search(notes) and not has_audio:
        rejected.append({"field": "notes", "item": notes[:MAX_ITEM_CHARS],
                         "reason": "no_audio_evidence",
                         "detail": "本节课没有语音输入，备注中的音频 / 发音评价未被记录。"})
        notes = ""

    out["notes"] = notes
    out["pronunciation"] = _pronunciation_state(ev, outcome.get("pronunciation"))
    out["evidence"] = {
        "kinds": sorted(kinds),
        "dialogue_turns": dialogue_turns,
        "audio_turns": int(ev.get("audio_turns") or 0),
        "scored_turns": int(ev.get("scored_turns") or 0),
        "source": "session_turns",
    }
    out["simulated"] = bool(simulated)
    if out["simulated"]:
        out["simulation_note"] = ("本节课使用的是本地模拟模型 / 隔离测试音频源，"
                                 "结果只用于验证教学流程，不代表真实教学效果。")
    if has_any_evidence:
        out["unassessed"] = []
    else:
        out["unassessed"] = ["knowledge_points", "weak_points", "review_items"]
    # 发音只要没有被真正评过，就如实列入「尚未评估」——有语音但没有评分能力时
    # 同样如此，绝不因为「有录音」就默认给出评价。
    if out["pronunciation"].get("status") != "assessed" \
            and "pronunciation" not in out["unassessed"]:
        out["unassessed"].insert(0, "pronunciation")
    out["rejected_items"] = rejected
    out["saved_at"] = time.time()
    return out


def public_outcome(outcome):
    """Read-side projection: a legacy record never becomes a pronunciation verdict.

    Records written before the evidence gate lack ``evidence``; they are shown as
    un-assessed rather than being silently counted as real learning results.
    Older data is preserved as-is and never rewritten.
    """
    if not outcome:
        return outcome
    out = copy.deepcopy(outcome)
    if "evidence" not in out:
        out["evidence"] = {"kinds": [], "legacy": True, "dialogue_turns": None,
                           "audio_turns": None, "scored_turns": None,
                           "source": "legacy_record"}
        out["legacy_record"] = True
    if not isinstance(out.get("pronunciation"), dict):
        out["pronunciation"] = {
            "status": "unassessed", "reason": "legacy_record", "score": None,
            "issues": [],
            "note": "该记录早于证据门禁，未包含音频证据，不作为发音评估结果。"}
    out.setdefault("simulated", False)
    out.setdefault("unassessed", [])
    out.setdefault("rejected_items", [])
    return out


def public_session(rec, *, include_turns=True):
    """A display-safe projection (no secrets; teacher/model ids as-is)."""
    if rec is None:
        return None
    out = {k: copy.deepcopy(rec.get(k)) for k in (
        "session_id", "teacher_id", "teacher_name", "student_id", "model_id",
        "model_key", "provider_id", "model_is_local", "knowledge_dataset_ids",
        "course_id", "status", "started_at", "ended_at", "turn_count",
        "knowledge_scope_note")}
    out["modality"] = str(rec.get("modality") or "text")
    out["voice"] = copy.deepcopy(rec.get("voice"))
    out["teaching_policy"] = copy.deepcopy(rec.get("teaching_policy") or {})
    out["outcome"] = copy.deepcopy(public_outcome(rec.get("outcome")))
    out["evidence"] = derive_evidence(rec)
    out["sources_used"] = _collect_sources(rec)
    if include_turns:
        out["turns"] = copy.deepcopy(rec.get("turns") or [])
    return out


def _collect_sources(rec):
    seen, out = set(), []
    for t in (rec.get("turns") or []):
        for s in (t.get("sources") or []):
            key = (s.get("dataset_id"), s.get("document_id"))
            if key in seen:
                continue
            seen.add(key)
            out.append(dict(s))
    return out
