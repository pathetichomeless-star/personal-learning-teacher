"""TEACHER PROFILE V1 (P1) — multiple AI teachers, persisted and switchable.

Ownership: `modules/teacher`.  Pure data + validation + one small JSON file
(atomic 600 writes, version-gated, locked); NO gateway/audio imports, NOT another
LLM.

A **teacher profile** is an independent, stable record identified by a generated
``teacher_id`` (the NAME is never the identifier).  Every teacher independently
stores: name / avatar / intro; subject + teaching language; teaching style and a
composed system instruction; references to model bindings (by stable id); a voice
capability descriptor; references to knowledge datasets / courses (by stable id);
a default teaching strategy; enabled state, version and timestamps.

References are **by stable id** — a teacher never copies model / knowledge /
memory payloads.  Teacher configuration is therefore separate from the model
registry, the knowledge store and the learner memory.

The existing production teacher **Tina** is materialised as the default record
``teacher_id == "tina"`` with ``frozen: True``.  Its frozen realtime voice/model
link is **read-only**: the store refuses to change or clear it, refuses to delete
or disable Tina, and never lets a new/duplicated teacher inherit the protected
realtime credentials (a copy is downgraded to text teaching unless it is given
its own, separately-verified realtime model).
"""

from __future__ import annotations

import copy
import logging
import re
import time
import uuid

from modules._jsonstore import BaseJsonStore, ConfirmRequired, StoreUnavailable

log = logging.getLogger("teacher.store")

SCHEMA_VERSION = 1

# ---- closed vocabularies (labels are display-only; ids are the contract) ----

SUBJECTS = ("english", "chinese", "math", "science", "history", "art", "coding",
            "general", "other")
SUBJECT_LABELS = {
    "english": "英语", "chinese": "语文", "math": "数学", "science": "科学",
    "history": "历史", "art": "艺术", "coding": "编程", "general": "综合",
    "other": "其他",
}

LANGUAGES = ("zh", "en", "bi")
LANGUAGE_LABELS = {"zh": "中文为主", "en": "英文为主", "bi": "中英双语"}

STYLES = ("patient", "strict", "encouraging", "custom")
STYLE_LABELS = {
    "patient": "耐心引导", "strict": "严格纠错", "encouraging": "鼓励互动",
    "custom": "自定义教学要求",
}
STYLE_INSTRUCTIONS = {
    "patient": "你是耐心的引导者：多鼓励、分步讲解、允许学生慢慢来，从不催促。",
    "strict": "你是严格的纠错者：及时、准确地指出每一个重要错误并给出正确说法，"
              "要求学生在同一处不再重复犯错。",
    "encouraging": "你是积极的互动伙伴：多用提问和肯定带动学生开口，"
                   "用轻松的对话让学生愿意多表达。",
    "custom": "请严格遵循老师给出的自定义教学要求。",
}

VOICE_MODES = ("text", "realtime")
VOICE_MODE_LABELS = {"text": "文字教学", "realtime": "语音教学"}

ACCENTS = ("american", "british", "neutral", "other")
ACCENT_LABELS = {"american": "美式发音", "british": "英式发音", "neutral": "中性发音",
                 "other": "其他口音"}

# 语音配置是**独立于模型 / 声音 / 性格 / 知识库**的配置对象：
#   * ``model``      —— 模型绑定（按 id 引用 registry）
#   * ``voice``      —— 语音配置（声音 / 语言 / 口音 / 语速 / 交互策略 / 适配器）
#   * ``teaching_style`` + ``custom_instruction`` —— 角色性格 / 教学风格
#   * ``knowledge``  —— 知识库与课程引用
# 四者互不覆盖，老师之间也互不覆盖（每条记录按自己的 teacher_id 保存）。
VOICE_INTERACTION_DEFAULTS = {"barge_in": False, "allow_transcript": True,
                              "max_turn_seconds": 120}
MIN_SPEED, MAX_SPEED = 0.5, 2.0
MIN_TURN_SECONDS, MAX_TURN_SECONDS = 5, 600

# Custom teachers are NOT capped at "three or five" — the only bound is a sane,
# configurable maximum that protects the store.
MAX_TEACHERS = 200
MAX_NAME = 40
MAX_INTRO = 300
MAX_INSTRUCTION = 4000
MAX_DATASETS = 50

DEFAULT_TEACHER_ID = "tina"

# Fields that belong to the frozen production realtime link and must stay read-only
# on the frozen Tina record.
FROZEN_PROTECTED_KEYS = ("voice", "model")

# zero-width / bidi / soft-hyphen characters: a field made only of these renders as
# nothing (same guard as the policy store).
_INVISIBLE_RE = re.compile(r"[\u00ad\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")


class TeacherInvalid(ValueError):
    """A candidate teacher record failed validation."""

    def __init__(self, errors):
        errors = list(errors)
        super().__init__("teacher_invalid: %s" % "; ".join(errors[:6]))
        self.errors = errors


class NotFound(ValueError):
    pass


class Duplicate(ValueError):
    pass


class FrozenTeacher(ValueError):
    """The record is the frozen production teacher and must not be changed."""


def render_system_instruction(rec):
    """Compose the teacher's system instruction from style + custom instruction.

    Deterministic, single source: the effective instruction always reflects the
    current style/subject/language.  A custom style uses the teacher's own text.
    """
    style = str(rec.get("teaching_style") or "patient")
    subject = SUBJECT_LABELS.get(str(rec.get("subject") or ""), str(rec.get("subject") or ""))
    lang = LANGUAGE_LABELS.get(str(rec.get("language") or "zh"),
                               str(rec.get("language") or ""))
    custom = str(rec.get("custom_instruction") or "").strip()
    if style == "custom" and custom:
        core = custom
    else:
        core = STYLE_INSTRUCTIONS.get(style, STYLE_INSTRUCTIONS["patient"])
        if custom:
            core = "%s\n补充要求：%s" % (core, custom)
    return "教学科目：%s；教学语言：%s。\n%s" % (subject, lang, core)


def _clean(value, what, cap, *, required=False):
    if value is None:
        s = ""
    else:
        s = str(value).strip()
    if required and not s:
        raise TeacherInvalid(["%s: 不能为空" % what])
    if len(s) > cap:
        raise TeacherInvalid(["%s: 过长（%d > %d）" % (what, len(s), cap)])
    # single-line only for short fields; instruction fields allow newlines but never
    # raw control characters (prevents forged instruction lines).
    if any(ord(c) < 32 and c not in ("\n",) for c in s) or "\x7f" in s:
        raise TeacherInvalid(["%s: 含非法控制字符" % what])
    if s and not _INVISIBLE_RE.sub("", s).strip():
        raise TeacherInvalid(["%s: 需要可见文本" % what])
    return s


def _one_line(value, what, cap, *, required=False):
    s = _clean(value, what, cap, required=required)
    if "\n" in s:
        raise TeacherInvalid(["%s: 只能是单行文本" % what])
    return s


class TeacherStore(BaseJsonStore):
    """One JSON file holding every teacher profile (keyed by teacher_id)."""

    SCHEMA_VERSION = SCHEMA_VERSION
    ROOT_KEYS = ("teachers",)

    # ---- seed ------------------------------------------------------------

    def ensure_seeded(self):
        """Materialise the frozen default teacher (Tina) once."""
        with self._lock.exclusive():
            self._ensure_loaded()
            if not self.available:
                return self
            if DEFAULT_TEACHER_ID not in self._data["teachers"]:
                now = time.time()
                self._data["teachers"][DEFAULT_TEACHER_ID] = _tina_seed(now)
                try:
                    self._persist()
                except StoreUnavailable:
                    pass
        return self

    # ---- helpers ---------------------------------------------------------

    def _all(self):
        return self._data["teachers"]

    def list_teachers(self, *, include_deleted=False):
        with self._lock:
            self.reload_if_changed()
            rows = []
            for rec in self._all().values():
                if not include_deleted and rec.get("deleted"):
                    continue
                rows.append(dict(rec))
            rows.sort(key=lambda r: (not r.get("is_default"),
                                     r.get("created_at") or 0, r["teacher_id"]))
            return rows

    def get_teacher(self, teacher_id):
        with self._lock:
            self.reload_if_changed()
            rec = self._all().get(str(teacher_id or ""))
            return dict(rec) if rec else None

    def default_teacher(self):
        for rec in self.list_teachers():
            if rec.get("is_default"):
                return rec
        return None

    def counts(self):
        rows = self.list_teachers(include_deleted=True)
        active = [r for r in rows if not r.get("deleted")]
        return {"total": len(active),
                "enabled": len([r for r in active if r.get("enabled")]),
                "frozen": len([r for r in active if r.get("frozen")])}

    # ---- validation ------------------------------------------------------

    @staticmethod
    def _validate(body, *, partial=False):
        """Return a normalized dict of fields.  Unknown keys are ignored, but the
        values that are present are validated (bounded, single-line where required).

        A ``None`` value means "not provided here" (the API passes every field), so
        it is dropped rather than treated as an invalid value.
        """
        body = {k: v for k, v in (body or {}).items() if v is not None}
        out = {}
        if "name" in body:
            out["name"] = _one_line(body.get("name"), "name", MAX_NAME, required=True)
        elif not partial:
            raise TeacherInvalid(["name: 不能为空"])
        if "avatar" in body:
            out["avatar"] = _one_line(body.get("avatar"), "avatar", 8)
        if "intro" in body:
            out["intro"] = _clean(body.get("intro"), "intro", MAX_INTRO)
        if "subject" in body:
            subj = str(body.get("subject") or "")
            if subj not in SUBJECTS:
                raise TeacherInvalid(["subject: 未知科目"])
            out["subject"] = subj
        if "language" in body:
            lang = str(body.get("language") or "")
            if lang not in LANGUAGES:
                raise TeacherInvalid(["language: 未知语言"])
            out["language"] = lang
        if "teaching_style" in body:
            st = str(body.get("teaching_style") or "")
            if st not in STYLES:
                raise TeacherInvalid(["teaching_style: 未知教学方式"])
            out["teaching_style"] = st
        if "custom_instruction" in body:
            out["custom_instruction"] = _clean(body.get("custom_instruction"),
                                               "custom_instruction", MAX_INSTRUCTION)
        if "default_strategy" in body:
            out["default_strategy"] = _clean(body.get("default_strategy"),
                                             "default_strategy", MAX_INSTRUCTION)
        if "voice" in body:
            out["voice"] = TeacherStore._validate_voice(body.get("voice"))
        if "model" in body:
            out["model"] = TeacherStore._validate_model(body.get("model"))
        if "knowledge" in body:
            out["knowledge"] = TeacherStore._validate_knowledge(body.get("knowledge"))
        return out

    @staticmethod
    def _validate_voice(voice):
        """语音配置：交流方式 / 语音适配器 / 声音 / 语言 / 口音 / 语速 / 交互策略。

        ``speed`` 只在所引用的语音适配器**确实支持语速调节**时才有意义；此处只做
        取值域校验，是否真正生效由语音适配层在开课时如实判定（不支持就明确拒绝，
        不会假装生效）。
        """
        if voice is None:
            voice = {}
        if not isinstance(voice, dict):
            raise TeacherInvalid(["voice: 需要对象"])
        mode = str(voice.get("mode") or "text")
        if mode not in VOICE_MODES:
            raise TeacherInvalid(["voice.mode: 未知交流方式"])
        accent = str(voice.get("accent") or "american")
        if accent not in ACCENTS:
            raise TeacherInvalid(["voice.accent: 未知口音"])
        speed = voice.get("speed")
        if speed is not None and speed != "":
            try:
                speed = float(speed)
            except (TypeError, ValueError):
                raise TeacherInvalid(["voice.speed: 需要数字"])
            if not (MIN_SPEED <= speed <= MAX_SPEED):
                raise TeacherInvalid(["voice.speed: 需在 %.1f – %.1f 之间"
                                      % (MIN_SPEED, MAX_SPEED)])
        else:
            speed = None
        return {
            "mode": mode,
            "adapter_id": _one_line(voice.get("adapter_id"), "voice.adapter_id", 64),
            "voice_id": _one_line(voice.get("voice_id"), "voice.voice_id", 40),
            "accent": accent,
            "language": _one_line(voice.get("language"), "voice.language", 16) or "en",
            "speed": speed,
            "interaction": TeacherStore._validate_interaction(voice.get("interaction")),
        }

    @staticmethod
    def _validate_interaction(it):
        """语音交互策略（打断 / 转写 / 单轮上限）。缺省即不声明能力。"""
        base = dict(VOICE_INTERACTION_DEFAULTS)
        if it is None:
            return base
        if not isinstance(it, dict):
            raise TeacherInvalid(["voice.interaction: 需要对象"])
        for k in ("barge_in", "allow_transcript"):
            if k in it and it[k] is not None:
                if not isinstance(it[k], bool):
                    raise TeacherInvalid(["voice.interaction.%s: 需要布尔值" % k])
                base[k] = bool(it[k])
        secs = it.get("max_turn_seconds")
        if secs is not None and secs != "":
            try:
                secs = int(secs)
            except (TypeError, ValueError):
                raise TeacherInvalid(["voice.interaction.max_turn_seconds: 需要整数"])
            if not (MIN_TURN_SECONDS <= secs <= MAX_TURN_SECONDS):
                raise TeacherInvalid(["voice.interaction.max_turn_seconds: 需在 %d – %d 之间"
                                      % (MIN_TURN_SECONDS, MAX_TURN_SECONDS)])
            base["max_turn_seconds"] = secs
        return base

    @staticmethod
    def _validate_model(model):
        """模型绑定对象（与声音、性格、知识库相互独立）。

        ``text_model_id`` / ``realtime_model_id`` 供文字课堂与实时语音使用；
        ``asr_model_id`` / ``tts_model_id`` 供**组合式语音管线**（ASR + LLM + TTS）
        使用——把语音管线的两个语音面也放在这里，是为了让「模型」这一个配置对象
        自洽，而不是把模型塞进声音配置里。  缺省为空即「未配置」，不会回落到别人
        的模型。
        """
        if model is None:
            model = {}
        if not isinstance(model, dict):
            raise TeacherInvalid(["model: 需要对象"])
        return {
            "text_model_id": _one_line(model.get("text_model_id"),
                                       "model.text_model_id", 64),
            "realtime_model_id": _one_line(model.get("realtime_model_id"),
                                           "model.realtime_model_id", 64),
            "asr_model_id": _one_line(model.get("asr_model_id"),
                                      "model.asr_model_id", 64),
            "tts_model_id": _one_line(model.get("tts_model_id"),
                                      "model.tts_model_id", 64),
        }

    @staticmethod
    def _validate_knowledge(k):
        if k is None:
            k = {}
        if not isinstance(k, dict):
            raise TeacherInvalid(["knowledge: 需要对象"])
        ds = k.get("dataset_ids") or []
        cr = k.get("course_ids") or []
        if not isinstance(ds, (list, tuple)) or any(not isinstance(x, str) for x in ds):
            raise TeacherInvalid(["knowledge.dataset_ids: 需要字符串列表"])
        if not isinstance(cr, (list, tuple)) or any(not isinstance(x, str) for x in cr):
            raise TeacherInvalid(["knowledge.course_ids: 需要字符串列表"])
        if len(ds) > MAX_DATASETS:
            raise TeacherInvalid(["knowledge.dataset_ids: 过多"])
        default_course = str(k.get("default_course") or "")
        if default_course and default_course not in cr:
            raise TeacherInvalid(["knowledge.default_course: 必须属于已选课程"])
        return {"dataset_ids": list(dict.fromkeys(ds)), "course_ids": list(cr),
                "default_course": default_course}

    # ---- writes ----------------------------------------------------------

    def create_teacher(self, *, name, duplicate_of=None, **fields):
        name = _one_line(name, "name", MAX_NAME, required=True)
        with self._lock.exclusive():
            self.reload_if_changed()
            if not self.available:
                raise StoreUnavailable(self._reason or "unavailable")
            if len([r for r in self._all().values() if not r.get("deleted")]) >= MAX_TEACHERS:
                raise TeacherInvalid(["老师数量已达上限（%d）" % MAX_TEACHERS])
            norm = self._validate(dict(fields, name=name), partial=False)
            now = time.time()
            tid = "tch_" + uuid.uuid4().hex[:12]
            rec = _blank_teacher(tid, now)
            rec.update(norm)
            if rec.get("teaching_style") == "custom" \
                    and not str(rec.get("custom_instruction") or "").strip():
                raise TeacherInvalid(["custom_instruction: 自定义教学方式需要填写要求"])
            rec["duplicate_of"] = duplicate_of
            # a brand-new teacher is never the default and never frozen
            rec["is_default"] = False
            rec["frozen"] = False
            rec["system_instruction"] = render_system_instruction(rec)
            rec["version"] = 1
            self._all()[tid] = rec
            self._persist()
            return copy.deepcopy(rec)

    def update_teacher(self, teacher_id, **body):
        tid = str(teacher_id or "")
        with self._lock.exclusive():
            self.reload_if_changed()
            rec = self._all().get(tid)
            if rec is None or rec.get("deleted"):
                raise NotFound("unknown teacher")
            if rec.get("frozen"):
                # the frozen production link's voice/model config is read-only
                touched = [k for k in FROZEN_PROTECTED_KEYS if k in body]
                if touched:
                    raise FrozenTeacher(
                        "冻结老师的语音/模型配置只读：%s" % "、".join(touched))
            norm = self._validate(body, partial=True)
            for k, v in norm.items():
                rec[k] = v
            style = rec.get("teaching_style")
            if style == "custom" and not str(rec.get("custom_instruction") or "").strip():
                raise TeacherInvalid(["custom_instruction: 自定义教学方式需要填写要求"])
            rec["system_instruction"] = render_system_instruction(rec)
            rec["version"] = int(rec.get("version") or 1) + 1
            rec["updated_at"] = time.time()
            self._persist()
            return copy.deepcopy(rec)

    def duplicate_teacher(self, teacher_id, *, new_name=None):
        src = self.get_teacher(teacher_id)
        if src is None or src.get("deleted"):
            raise NotFound("unknown teacher")
        base = str(new_name or "").strip() or (str(src.get("name")) + " 副本")
        copy_body = {
            "name": base[:MAX_NAME],
            "avatar": src.get("avatar") or "",
            "intro": src.get("intro") or "",
            "subject": src.get("subject"),
            "language": src.get("language"),
            "teaching_style": src.get("teaching_style"),
            "custom_instruction": src.get("custom_instruction") or "",
            "default_strategy": src.get("default_strategy") or "",
            "knowledge": copy.deepcopy(src.get("knowledge") or {}),
            "model": copy.deepcopy(src.get("model") or {}),
            "voice": copy.deepcopy(src.get("voice") or {}),
        }
        # Never inherit the protected realtime credentials of the frozen link: a copy
        # that carried a realtime voice is downgraded to text teaching with no
        # realtime model, and honestly reports that state.
        src_voice = src.get("voice") or {}
        src_model = src.get("model") or {}
        if src.get("frozen") or src_voice.get("mode") == "realtime":
            copy_body["voice"] = {"mode": "text",
                                  "voice_id": "",
                                  "accent": src_voice.get("accent") or "american",
                                  "language": src_voice.get("language") or "en"}
            copy_body["model"] = {"text_model_id":
                                  src_model.get("text_model_id") or "",
                                  "realtime_model_id": "",
                                  # 语音管线的两个语音面是普通模型引用，不是受保护的
                                  # 实时语音凭据，因此随副本保留（明确落在副本自己名下）。
                                  "asr_model_id": src_model.get("asr_model_id") or "",
                                  "tts_model_id": src_model.get("tts_model_id") or ""}
        return self.create_teacher(name=copy_body.pop("name"),
                                   duplicate_of=src["teacher_id"], **copy_body)

    def set_default(self, teacher_id):
        tid = str(teacher_id or "")
        with self._lock.exclusive():
            self.reload_if_changed()
            rec = self._all().get(tid)
            if rec is None or rec.get("deleted"):
                raise NotFound("unknown teacher")
            if not rec.get("enabled"):
                raise TeacherInvalid(["default_on_disabled: 停用的老师不能设为默认"])
            for other in self._all().values():
                other["is_default"] = (other["teacher_id"] == tid)
            rec["updated_at"] = time.time()
            self._persist()
            return copy.deepcopy(rec)

    def set_enabled(self, teacher_id, enabled: bool):
        tid = str(teacher_id or "")
        with self._lock.exclusive():
            self.reload_if_changed()
            rec = self._all().get(tid)
            if rec is None or rec.get("deleted"):
                raise NotFound("unknown teacher")
            if rec.get("frozen") and not enabled:
                raise FrozenTeacher("冻结的默认老师不能停用")
            if rec.get("is_default") and not enabled:
                raise TeacherInvalid(["default_protected: 默认老师不能停用，请先切换默认老师"])
            rec["enabled"] = bool(enabled)
            rec["updated_at"] = time.time()
            self._persist()
            return copy.deepcopy(rec)

    def delete_teacher(self, teacher_id, *, confirm=None):
        tid = str(teacher_id or "")
        with self._lock.exclusive():
            self.reload_if_changed()
            rec = self._all().get(tid)
            if rec is None or rec.get("deleted"):
                raise NotFound("unknown teacher")
            if confirm != tid:
                raise ConfirmRequired("confirm 必须等于老师 ID")
            if rec.get("frozen"):
                raise FrozenTeacher("冻结的默认老师不能删除")
            if rec.get("is_default"):
                raise TeacherInvalid(["default_protected: 默认老师不能删除，请先切换默认老师"])
            # soft delete: the record is preserved so historical learning records that
            # reference this teacher_id stay attributable.
            rec["deleted"] = True
            rec["enabled"] = False
            rec["deleted_at"] = time.time()
            rec["updated_at"] = time.time()
            self._persist()
            return {"deleted": tid, "soft": True}


# ---------------------------------------------------------------------------
# record shapes
# ---------------------------------------------------------------------------

def _blank_teacher(teacher_id, now):
    return {
        "teacher_id": teacher_id,
        "name": "",
        "avatar": "",
        "intro": "",
        "subject": "english",
        "language": "zh",
        "teaching_style": "patient",
        "custom_instruction": "",
        "system_instruction": "",
        "model": {"text_model_id": "", "realtime_model_id": "",
                  "asr_model_id": "", "tts_model_id": ""},
        "voice": {"mode": "text", "adapter_id": "", "voice_id": "",
                  "accent": "american", "language": "en", "speed": None,
                  "interaction": dict(VOICE_INTERACTION_DEFAULTS)},
        "knowledge": {"dataset_ids": [], "course_ids": [], "default_course": ""},
        "default_strategy": "鼓励为主，纠错温和，保持对话流畅。",
        "enabled": True,
        "is_default": False,
        "frozen": False,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }


def _tina_seed(now):
    """The existing production teacher, materialised read-only."""
    rec = _blank_teacher(DEFAULT_TEACHER_ID, now)
    rec.update({
        "name": "Tina",
        "avatar": "T",
        "intro": "小智内置的英语老师：语气温和、耐心引导，适合日常口语与词汇练习。",
        "subject": "english",
        "language": "zh",
        "teaching_style": "patient",
        "custom_instruction": "",
        "model": {"text_model_id": "", "realtime_model_id": "mdl_frozen_tina",
                  "asr_model_id": "", "tts_model_id": ""},
        "voice": {"mode": "realtime", "adapter_id": "", "voice_id": "Tina",
                  "accent": "american", "language": "en", "speed": None,
                  "interaction": dict(VOICE_INTERACTION_DEFAULTS)},
        "knowledge": {"dataset_ids": [], "course_ids": [], "default_course": ""},
        "default_strategy": "鼓励为主，纠错温和，保持对话流畅。",
        "enabled": True,
        "is_default": True,
        "frozen": True,
        "version": 1,
    })
    rec["system_instruction"] = render_system_instruction(rec)
    rec["origin"] = "builtin_frozen_default"
    return rec
