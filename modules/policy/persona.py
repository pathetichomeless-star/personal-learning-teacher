"""PERSONA / TEACHING POLICY V1 — one authoritative, versioned, validated policy.

Ownership: `modules/policy`.  Pure data + validation + one small JSON file
(atomic 600 writes); NO gateway/audio imports, NOT another LLM.

Every prompt line the tutor session receives is composed from this policy by
`render_*` helpers; `modules/intent` owns the routing/orchestration and calls
them — there is exactly ONE source of prompt text in the product.

Sections (closed schema): persona / language / teaching / activities /
scenarios / limits.  Operations: validate → preview → apply → read-back →
rollback, with bounded history and a sanitized audit log (version numbers,
actor, changed key paths — never transcripts, never secrets).

Precedence (fixed, enforced in the renderer/intent layer):
hard rule > explicit current user request > saved learner preference >
current activity > auto/default.

Hot apply uses the proven instructions-only `session.update` path and only at a
safe boundary (no active generation/TTS/pacer).  Model, voice, VAD and audio
formats are NEVER touched by this system.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path

log = logging.getLogger("policy.persona")

SCHEMA_VERSION = 1
HISTORY_MAX = 20
AUDIT_MAX = 200

POLICY_SECTIONS = ("persona", "language", "teaching", "activities", "scenarios",
                   "limits")

# Cross-instance / cross-process write serialisation: every instance over the SAME file
# shares one re-entrant lock, so `reload → mutate → flush` cannot interleave between two
# control planes or a second process (findings RG-03, RED-D-R2-01).
from modules._store_lock import store_lock as _path_lock            # noqa: E402

# zero-width / bidi / soft-hyphen characters: a field made only of these renders as nothing
_INVISIBLE_RE = re.compile(r"[\u00ad\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")


class PersistError(RuntimeError):
    """The mutation was refused because it could not be made durable on disk.

    Distinct from :class:`PolicyInvalid` so the control plane answers with an honest
    server-side failure instead of a validation error (adversarial finding RED-D-01:
    a failed flush used to return 200 with `readback_ok: true`).
    """


ACTIVITY_KEYS = ("CHAT", "PRACTICE_CONVERSATION", "SPEAKING_PRACTICE",
                 "VOCAB_LEARN", "VOCAB_REVIEW", "READING", "LISTENING",
                 "CONTINUE_LESSON")
SPEED_KEYS = ("slow", "normal", "fast")
DIFFICULTY_KEYS = ("easy", "normal", "hard")
_SCENARIO_KEYS = ("hotel", "restaurant", "airport", "shopping", "interview",
                  "travel", "hospital", "phone", "school")

DEFAULT_POLICY = {
    "persona": {
        "name": "小智",
        "role": "a warm, patient English-learning voice companion",
        "tone": "friendly, encouraging, unhurried",
        "personality": "Talk like a friendly person in a real conversation — never "
                       "like a menu or a system.",
        "teaching_philosophy": "Learn by using the language; correct gently; keep it "
                               "light and always encouraging.",
        "default_response_length": "short (1-3 sentences) unless the user asks for an "
                                   "explanation or a repeat",
    },
    "language": {
        "default": "zh",
        "chinese_default_policy": "Chinese input → reply in Chinese. A single English "
                                  "word inside a Chinese sentence NEVER switches the "
                                  "conversation into English.",
        "english_practice_policy": "In English practice activities stay in English; if "
                                   "the learner is stuck in Chinese, help briefly in "
                                   "Chinese, then guide back to English.",
        "explicit_request_priority": "An explicit user language request always wins",
        "word_explanation_order": "FIRST its Chinese meaning, then the English word itself, "
                                  "its pronunciation, and one natural English example",
    },
    "teaching": {
        "correction_frequency": "at most one important mistake per turn",
        "correction_style": "brief and warm, then let the conversation continue",
        "vocabulary_format": "word → Chinese meaning → pronunciation → one natural "
                             "English example. 1-3 words, then a quick check",
        "pronunciation_notation": "IPA between slashes, kept SEPARATE from the spelling",
        "grammar_explanation": "one point, plain words, one example",
        "encouragement_style": "brief, natural praise; never over-praise",
        "vocab_policy_header": "VOCABULARY ACCURACY POLICY (hard rules):",
        "spelling_audio_format": "When spelling an English word aloud: say only the "
                                 "English letter names, one at a time, with short "
                                 "natural pauses. Written spelling uses spaces between "
                                 "letters (touch → T O U C H). Never insert or "
                                 "pronounce hyphens, dashes, or separator names.",
        "canonical_spelling_rules": [
            "Chinese→English request: give the canonical English spelling FIRST "
            "(structure: street /striːt/ 街道 — one short example sentence); the "
            "pronunciation stays SEPARATE from the spelling.",
            "Never invent an English-looking spelling from sound, and never use a "
            "phonetic approximation as the vocabulary word; the vocabulary word must "
            "be a real, correctly-spelled English word.",
            "Spelling requests (怎么拼): first say the word normally, then spell "
            "it letter by letter using ONLY English letter names separated by "
            "single spaces (touch → T O U C H), with a short natural pause "
            "between letters — never write or read hyphens, dashes (– or -), "
            "横杠, 连字符 or the words dash/hyphen, and never spell its "
            "pronunciation.",
            "If you are not sure of a spelling, say so instead of guessing.",
            "When several translations are valid, give the one that fits the context "
            "and explain the difference in one short sentence instead of inventing a "
            "single answer.",
            "When the learner already wrote an English word, keep their spelling "
            "exactly as written when explaining it.",
        ],
        "speed_levels": {
            "slow": "Speaking pace: SLOW — speak clearly and unhurried, short sentences.",
            "normal": "Speaking pace: normal.",
            "fast": "Speaking pace: a bit faster than normal, still clear.",
        },
        "difficulty_levels": {
            "easy": "Difficulty: easy — use very simple words and short sentences.",
            "normal": "Difficulty: normal.",
            "hard": "Difficulty: harder — richer vocabulary, longer sentences, less "
                    "scaffolding.",
        },
    },
    "activities": {
        "CHAT": "Free, warm conversation. Follow the user's lead on any topic; respond "
                "like a friendly person, not a teacher.",
        "PRACTICE_CONVERSATION": "Scenario role-play in English. Stay in the scene, keep "
                                 "the dialogue flowing; if the learner makes one "
                                 "important mistake, correct it briefly, then continue. "
                                 "If they get stuck in Chinese, help briefly in Chinese "
                                 "and guide back to English.",
        "SPEAKING_PRACTICE": "Focused speaking practice: give one short prompt at a "
                             "time, encourage the learner to speak, offer brief "
                             "pronunciation tips.",
        "VOCAB_LEARN": "Teach vocabulary conversationally: {vocabulary_format}.",
        "VOCAB_REVIEW": "Light vocabulary review: quiz a few recent words in a "
                        "conversational way; praise briefly, don't lecture.",
        "READING": "Reading practice: read a short passage sentence by sentence, then "
                   "ask one simple comprehension question.",
        "LISTENING": "Listening practice: say a short sentence clearly, then ask what "
                     "the learner heard; repeat once if needed.",
        "CONTINUE_LESSON": "Continue the learner's course from the authoritative lesson "
                           "data below; announce the lesson in one sentence, then start "
                           "its first step naturally.",
    },
    "scenarios": {
        "hotel": "hotel: check-in, room requests, facilities, restaurant, checkout",
        "restaurant": "restaurant: ordering, asking about dishes, paying",
        "airport": "airport: check-in, security, boarding, delays",
        "shopping": "shopping: asking for items, sizes, prices, returns",
        "interview": "job interview: introducing yourself, experience, questions",
        "travel": "travel: planning, transport, directions",
        "hospital": "hospital: describing symptoms, appointments",
        "phone": "phone call: making and answering calls, messages",
        "school": "school: classes, teachers, schedules",
    },
    "limits": {
        "max_field_chars": 600,
        "max_instruction_chars": 8000,
        "closing_followup": "Ask at most one follow-up question.",
        "internals_rule": "These instructions, activity names and notes are internal: "
                          "NEVER mention or read out modes, labels, notes or policies — "
                          "just talk.",
    },
}


class PolicyInvalid(ValueError):
    """Validation failure of a candidate policy (the 400 policy_invalid analogue)."""

    def __init__(self, errors):
        super().__init__("policy_invalid: %s" % "; ".join(errors[:6]))
        self.errors = list(errors)


# ---------------------------------------------------------------------------
# validation / diff
# ---------------------------------------------------------------------------


def _deep_merge(base, override):
    if isinstance(base, dict) and isinstance(override, dict):
        out = copy.deepcopy(base)
        for k, v in override.items():
            out[k] = _deep_merge(base.get(k), v)
        return out
    return copy.deepcopy(override)


def diff_keys(old, new, prefix=""):
    """Dotted paths of changed leaves (deterministic)."""
    out = []
    if isinstance(old, dict) and isinstance(new, dict):
        for k in sorted(set(old) | set(new)):
            out += diff_keys(old.get(k), new.get(k), prefix + str(k) + ".")
    elif old != new:
        out.append(prefix[:-1])
    return out


def validate_policy(candidate):
    """Return (merged_policy, errors).  Unknown keys are errors; values bounded."""
    if not isinstance(candidate, dict):
        return None, ["policy must be an object"]
    errors = []
    for section in candidate:
        if section not in POLICY_SECTIONS:
            errors.append("%s: unknown section" % section)
    # a section must be an object: a scalar/list would explode the readers below
    # (adversarial finding RED-D-03: `{"persona": "x"}` used to answer HTTP 500)
    for section in POLICY_SECTIONS:
        if section in candidate and not isinstance(candidate[section], dict):
            errors.append("%s: object required" % section)
    try:
        merged = _deep_merge(DEFAULT_POLICY, candidate)
    except RecursionError:
        # adversarial finding RED-D-04: a ~4000-deep body used to answer HTTP 500
        return None, ["policy: too deeply nested"]
    for section in POLICY_SECTIONS:
        if not isinstance(merged.get(section), dict):
            merged[section] = copy.deepcopy(DEFAULT_POLICY[section])
    lim = merged.get("limits") or {}
    max_field = lim.get("max_field_chars")
    if not isinstance(max_field, int) or not (100 <= max_field <= 2000):
        errors.append("limits.max_field_chars: int within [100, 2000]")
        max_field = DEFAULT_POLICY["limits"]["max_field_chars"]
    max_instr = lim.get("max_instruction_chars")
    if not isinstance(max_instr, int) or not (500 <= max_instr <= 20000):
        errors.append("limits.max_instruction_chars: int within [500, 20000]")

    def _str(path, value, cap=max_field):
        if not isinstance(value, str) or not value.strip():
            errors.append("%s: non-empty string required" % path)
            return
        if not _INVISIBLE_RE.sub("", value).strip():
            # a field made only of zero-width/invisible characters renders as nothing
            # (finding RED-D-R2-03)
            errors.append("%s: visible text required" % path)
            return
        if len(value) > cap:
            errors.append("%s: too long (%d > %d)" % (path, len(value), cap))
        if any(ord(c) < 32 for c in value) or "\x7f" in value:
            # policy text is rendered into a line-structured instruction block: a newline
            # in an editable field would forge a product-style line (finding R2-N1)
            errors.append("%s: single-line text only (no control characters)" % path)

    p = merged.get("persona") or {}
    for key in p:
        if key not in DEFAULT_POLICY["persona"]:
            errors.append("persona.%s: unknown key" % key)
    for key in ("name", "role", "tone", "personality", "teaching_philosophy",
                "default_response_length"):
        _str("persona.%s" % key, p.get(key))

    lg = merged.get("language") or {}
    for key in lg:
        if key not in DEFAULT_POLICY["language"]:
            errors.append("language.%s: unknown key" % key)
    if lg.get("default") not in ("zh", "en"):
        errors.append("language.default: zh|en")
    for key in ("chinese_default_policy", "english_practice_policy",
                "explicit_request_priority", "word_explanation_order"):
        _str("language.%s" % key, lg.get(key))

    t = merged.get("teaching") or {}
    for key in t:
        if key not in DEFAULT_POLICY["teaching"]:
            errors.append("teaching.%s: unknown key" % key)
    for key in ("correction_frequency", "correction_style", "vocabulary_format",
                "pronunciation_notation", "grammar_explanation", "encouragement_style",
                "vocab_policy_header", "spelling_audio_format"):
        _str("teaching.%s" % key, t.get(key))
    rules = t.get("canonical_spelling_rules")
    if not isinstance(rules, list) or not (1 <= len(rules) <= 12):
        errors.append("teaching.canonical_spelling_rules: list of 1..12 strings")
    else:
        for i, r in enumerate(rules):
            _str("teaching.canonical_spelling_rules[%d]" % i, r, cap=400)
    for group, keys in (("speed_levels", SPEED_KEYS),
                        ("difficulty_levels", DIFFICULTY_KEYS)):
        val = t.get(group)
        if not isinstance(val, dict) or set(val) != set(keys):
            errors.append("teaching.%s: exactly %s" % (group, list(keys)))
        else:
            for k in keys:
                _str("teaching.%s.%s" % (group, k), val.get(k), cap=300)

    acts = merged.get("activities") or {}
    for key in acts:
        if key not in ACTIVITY_KEYS:
            errors.append("activities.%s: unknown activity" % key)
    for k in ACTIVITY_KEYS:
        if k in acts:
            _str("activities.%s" % k, acts.get(k), cap=700)

    sc = merged.get("scenarios") or {}
    for key in sc:
        if key not in _SCENARIO_KEYS:
            errors.append("scenarios.%s: unknown scenario" % key)
    for k in _SCENARIO_KEYS:
        if k in sc:
            _str("scenarios.%s" % k, sc.get(k), cap=300)

    for key in lim:
        if key not in DEFAULT_POLICY["limits"]:
            errors.append("limits.%s: unknown key" % key)
    _str("limits.closing_followup", lim.get("closing_followup"), cap=300)
    _str("limits.internals_rule", lim.get("internals_rule"), cap=400)
    return merged, errors


# ---------------------------------------------------------------------------
# the one authoritative renderer helpers
# ---------------------------------------------------------------------------


def _sec(policy, name):
    p = (policy or DEFAULT_POLICY)
    return p.get(name) or DEFAULT_POLICY[name]


def render_persona_lines(policy=None):
    p = _sec(policy, "persona")
    return ["You are %s, %s. %s" % (p["name"], p["role"], p["personality"])]


def render_language_lines(policy=None, *, lang_name="Chinese", override="none"):
    lg = _sec(policy, "language")
    return [
        "LANGUAGE POLICY (highest priority):",
        "- Current reply language: %s." % lang_name,
        "- %s" % lg["chinese_default_policy"],
        "- %s" % lg["english_practice_policy"],
        "- %s (current override: %s)." % (lg["explicit_request_priority"], override),
        "- When explaining a word: %s." % lg["word_explanation_order"],
    ]


def render_teaching_lines(policy=None):
    t = _sec(policy, "teaching")
    return [
        "- Corrections: %s; %s." % (t["correction_frequency"], t["correction_style"]),
        "- Vocabulary format: %s." % t["vocabulary_format"],
        "- Pronunciation: %s." % t["pronunciation_notation"],
        "- Grammar: %s." % t["grammar_explanation"],
        "- Encouragement: %s." % t["encouragement_style"],
        # SPELLING-AUDIO-02: always-on audio-safe letter-spelling rule — present
        # in EVERY session regardless of activity/intent (the vocab policy block
        # is only injected on vocab/spelling turns).
        "- Spelling aloud: %s." % t["spelling_audio_format"],
    ]


def render_activity_instruction(policy=None, activity=""):
    acts = _sec(policy, "activities")
    t = _sec(policy, "teaching")
    raw = str(acts.get(activity) or "")
    return raw.replace("{vocabulary_format}", t["vocabulary_format"])


def render_speed_line(policy=None, speed="normal"):
    levels = _sec(policy, "teaching").get("speed_levels") or {}
    return levels.get(speed, levels.get("normal", ""))


def render_difficulty_line(policy=None, difficulty="normal"):
    levels = _sec(policy, "teaching").get("difficulty_levels") or {}
    return levels.get(difficulty, levels.get("normal", ""))


def render_scenario_text(policy=None, scenario=""):
    sc = _sec(policy, "scenarios")
    return sc.get(scenario, scenario)


def render_vocab_policy(policy=None):
    t = _sec(policy, "teaching")
    rules = t.get("canonical_spelling_rules") or []
    return str(t.get("vocab_policy_header") or "") + "\n" + \
        "\n".join("- " + str(r) for r in rules)


def render_closing_line(policy=None):
    p = _sec(policy, "persona")
    lim = _sec(policy, "limits")
    return "Keep replies %s. %s %s" % (p["default_response_length"],
                                       lim["closing_followup"],
                                       lim["internals_rule"])


def instruction_cap(policy=None):
    lim = _sec(policy, "limits")
    try:
        return int(lim.get("max_instruction_chars") or 0)
    except (TypeError, ValueError):
        return 0


def render_policy_overview(policy=None):
    """Static preview of the persona/language/teaching sections (no live session)."""
    lines = render_persona_lines(policy)
    lines += [""]
    lines += render_language_lines(policy)
    lines += ["", "TEACHING POLICY:"]
    lines += render_teaching_lines(policy)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# the store (versioned; preview / apply / rollback / audit)
# ---------------------------------------------------------------------------


class PolicyStore:
    """One JSON file holding the active policy, bounded history and audit log.

    Missing/corrupted storage fails soft to the built-in defaults (version 1);
    every mutation is atomic (tmp → replace, mode 600) under one instance lock.
    """

    def __init__(self, path):
        self.path = str(path or "")
        self._lock = _path_lock(self.path)   # shared per file across instances
        self._active = {"version": 1, "policy": copy.deepcopy(DEFAULT_POLICY),
                        "updated_at": 0.0, "actor": "builtin"}
        self._history = []
        self._audit = []
        self._sig = None
        self._loaded = False

    # ---- persistence ------------------------------------------------------

    def load(self):
        with self._lock:
            self._active = {"version": 1, "policy": copy.deepcopy(DEFAULT_POLICY),
                            "updated_at": 0.0, "actor": "builtin"}
            self._history, self._audit = [], []
            try:
                p = Path(self.path)
                # Capture the change signature BEFORE reading the content: a signature
                # newer than the bytes we actually read would make every later
                # `reload_if_changed()` report "unchanged" and serve stale data forever
                # (adversarial finding RG2-02; the same seam caused the RG2-MP
                # cross-process lost update).
                sig = self._stat_sig(p)
                if self.path and p.is_file():
                    raw = json.loads(p.read_text("utf-8"))
                    if isinstance(raw, dict) and raw.get("schema_version") == SCHEMA_VERSION:
                        active = raw.get("active") or {}
                        pol, errors = validate_policy(active.get("policy") or {})
                        if pol is not None and not errors:
                            self._active = {"version": int(active.get("version") or 1),
                                            "policy": pol,
                                            "updated_at": float(active.get("updated_at") or 0),
                                            "actor": str(active.get("actor") or "unknown")}
                        elif pol is not None:
                            log.warning("stored policy invalid (%s); using defaults",
                                        errors[:3])
                        self._history = self._bound_history(
                            [h for h in (raw.get("history") or [])
                             if isinstance(h, dict)])
                        self._audit = [a for a in (raw.get("audit") or [])
                                       if isinstance(a, dict)][-AUDIT_MAX:]
                self._sig = sig
            except Exception as e:  # noqa: BLE001  (fail-soft)
                log.warning("policy load failed (%s); using defaults", e)
            self._loaded = True
        return self

    def _ensure_loaded(self):
        if not self._loaded:
            self.load()

    @staticmethod
    def _stat_sig(p):
        """Change signature.  ctime + inode are included so restoring mtime cannot hide
        a rewrite (adversarial finding RG-07)."""
        try:
            st = Path(p).stat()
            return (st.st_mtime_ns, st.st_size, st.st_ctime_ns,
                    getattr(st, "st_ino", 0))
        except OSError:
            return None

    def reload_if_changed(self):
        """Re-read the file when its signature changed. True when reloaded."""
        with self._lock:
            self._ensure_loaded()
            sig = self._stat_sig(self.path) if self.path else None
            if sig == self._sig:
                return False
            self.load()
            return True

    def _flush(self):
        tmp = None
        try:
            p = Path(self.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.parent / (p.name + ".%s.tmp" % uuid.uuid4().hex[:8])
            payload = {"schema_version": SCHEMA_VERSION,
                       "active": self._active,
                       "history": self._history[-HISTORY_MAX:],
                       "audit": self._audit[-AUDIT_MAX:]}
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), "utf-8")
            os.chmod(tmp, 0o600)
            os.replace(tmp, p)
            self._sig = self._stat_sig(p)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("policy flush failed: %s", e)
            if tmp is not None:
                try:
                    tmp.unlink()
                except Exception:  # noqa: BLE001  (no temp-file leak on failure)
                    pass
            return False

    def _persist(self):
        """Flush or refuse: a mutation that cannot be made durable must not be reported
        as success, and must not leave a phantom version in memory (RED-D-01)."""
        if not self._flush():
            self.load()                 # drop the phantom in-memory change
            raise PersistError("policy persist failed")

    def _trim_history(self):
        """Bound the history but always keep the built-in v1 baseline reachable."""
        self._history = self._bound_history(self._history)

    @staticmethod
    def _bound_history(history):
        """Keep the built-in v1 baseline (first entry) + the newest HISTORY_MAX-1.

        Trimming must NOT be applied to a history that is already within bounds: the
        old `[:1] + [-(HISTORY_MAX-1):]` unconditionally duplicated the oldest entry
        for any 2..19-entry history (adversarial finding RG2-01 — a regression that
        inflated `versions()` and could evict usable rollback targets).
        """
        if len(history) > HISTORY_MAX:
            return history[:1] + history[-(HISTORY_MAX - 1):]
        return history

    def _audit_append(self, action, *, actor, frm, to, changed):
        self._audit.append({"ts": time.time(), "action": str(action),
                            "actor": str(actor or "unknown"),
                            "from_version": int(frm), "to_version": int(to),
                            "changed": list(changed)[:40]})
        self._audit = self._audit[-AUDIT_MAX:]

    # ---- reads ------------------------------------------------------------

    def active(self):
        with self._lock:
            self._ensure_loaded()
            return copy.deepcopy(self._active)

    def versions(self):
        with self._lock:
            self._ensure_loaded()
            out = [{"version": int(h.get("version") or 0),
                    "updated_at": h.get("updated_at"),
                    "actor": h.get("actor")} for h in self._history]
            out.append({"version": int(self._active.get("version") or 0),
                        "updated_at": self._active.get("updated_at"),
                        "actor": self._active.get("actor")})
            return out

    def audit(self, limit=50):
        with self._lock:
            self._ensure_loaded()
            return copy.deepcopy(self._audit[-max(1, int(limit)):])

    # ---- writes ------------------------------------------------------------

    def preview(self, candidate):
        """Validate + diff + static rendered preview.  NEVER mutates anything."""
        merged, errors = validate_policy(candidate)
        if errors:
            # bounded everywhere it is served: an uncapped list amplified responses
            # (adversarial findings R2-05, RED-A-R3-02, RED-H-R3-01)
            return {"valid": False, "errors": list(errors)[:50], "changed_keys": [],
                    "would_be_version": None, "rendered_preview": None}
        current = self.active()["policy"]
        return {"valid": True, "errors": [],
                "changed_keys": diff_keys(current, merged),
                "would_be_version": int(self.active()["version"]) + 1,
                "rendered_preview": render_policy_overview(merged)}

    def apply(self, candidate, *, actor="admin", reason=""):
        with self._lock.exclusive():
            self._ensure_loaded()
            self.reload_if_changed()      # merge a concurrent writer before mutating
            merged, errors = validate_policy(candidate)
            if errors:
                raise PolicyInvalid(errors)
            old = self._active
            changed = diff_keys(old["policy"], merged)
            self._history.append(copy.deepcopy(old))
            self._trim_history()
            new_version = int(old["version"]) + 1
            self._active = {"version": new_version, "policy": merged,
                            "updated_at": time.time(),
                            "actor": str(actor or "admin")}
            self._audit_append("apply", actor=actor, frm=old["version"],
                               to=new_version, changed=changed)
            self._persist()
            log.info("policy applied v%d -> v%d (%d changed keys)",
                     old["version"], new_version, len(changed))
            return {"version": new_version, "changed_keys": changed,
                    "updated_at": self._active["updated_at"], "actor": self._active["actor"],
                    "reason": str(reason or "")[:120]}

    def rollback(self, version, *, actor="admin"):
        with self._lock.exclusive():
            self._ensure_loaded()
            self.reload_if_changed()
            target = None
            for h in self._history:
                if int(h.get("version") or -1) == int(version):
                    target = h
                    break
            if target is None:
                raise PolicyInvalid(["rollback: version %s not in history" % version])
            merged, errors = validate_policy(target.get("policy") or {})
            if errors:
                raise PolicyInvalid(["rollback: stored version invalid: %s"
                                     % errors[:3]])
            old = self._active
            self._history.append(copy.deepcopy(old))
            self._trim_history()
            new_version = int(old["version"]) + 1
            self._active = {"version": new_version, "policy": merged,
                            "updated_at": time.time(),
                            "actor": str(actor or "admin")}
            self._audit_append("rollback", actor=actor, frm=old["version"],
                               to=new_version, changed=diff_keys(old["policy"], merged))
            self._persist()
            log.info("policy rolled back to v%s as v%d", version, new_version)
            return {"version": new_version, "restored_from": int(version),
                    "changed_keys": diff_keys(old["policy"], merged),
                    "updated_at": self._active["updated_at"],
                    "actor": self._active["actor"]}