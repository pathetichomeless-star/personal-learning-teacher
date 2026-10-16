"""BEHAVIOR-1 — natural activity routing, language policy and context model.

Ownership: `modules/intent` (pure logic; NO gateway/audio imports, NO I/O).

The router is a deterministic rule-based classifier over the **input
transcription text** of each user turn.  It maintains the session-scoped
context model (main activity / temporary intent / resume state / recency /
language / speed / difficulty) and produces:

* a :class:`Decision` — what happened mechanically (never spoken to the user);
* a rendered instruction block (:func:`render_instructions`) which the gateway
  hot-applies to the Qwen session at a safe boundary.

Design rules (binding, from the CONVERSATIONAL MVP authorization):

* internal labels (CHAT/VOCAB_LEARN/…) are never spoken; the renderer says so
  explicitly and the Decision note is instruction-side only.
* Chinese input → Chinese by default; one English word inside Chinese NEVER
  switches the conversation to English; explicit practice switches to English;
  an explicit user language request always wins.
* temporary intents (EXPLAIN_WORD …) never destroy the main activity: the
  renderer instructs "explain, then return to <main activity>".
* recency fields (`recent_word/sentence/passage/task`) are session-scoped,
  in-memory only, never logged and never persisted (privacy boundary).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from modules.policy import persona as policy_mod

# ---------------------------------------------------------------------------
# vocabularies
# ---------------------------------------------------------------------------

CHAT = "CHAT"
PRACTICE_CONVERSATION = "PRACTICE_CONVERSATION"
SPEAKING_PRACTICE = "SPEAKING_PRACTICE"
VOCAB_LEARN = "VOCAB_LEARN"
VOCAB_REVIEW = "VOCAB_REVIEW"
READING = "READING"
LISTENING = "LISTENING"
CONTINUE_LESSON = "CONTINUE_LESSON"

MAIN_ACTIVITIES = (CHAT, PRACTICE_CONVERSATION, SPEAKING_PRACTICE, VOCAB_LEARN,
                   VOCAB_REVIEW, READING, LISTENING, CONTINUE_LESSON)

EXPLAIN_WORD = "EXPLAIN_WORD"
EXPLAIN_GRAMMAR = "EXPLAIN_GRAMMAR"
TRANSLATE = "TRANSLATE"
QUERY_PROGRESS = "QUERY_PROGRESS"
SAVE_PREFERENCE = "SAVE_PREFERENCE"
QUERY_KNOWLEDGE = "QUERY_KNOWLEDGE"

TEMPORARY_INTENTS = (EXPLAIN_WORD, EXPLAIN_GRAMMAR, TRANSLATE, QUERY_PROGRESS,
                     SAVE_PREFERENCE, QUERY_KNOWLEDGE)

# Decision kinds
K_NONE = "NONE"
K_ACTIVITY = "ACTIVITY"
K_COMMAND = "COMMAND"
K_TEMP = "TEMP"
K_PREF = "PREF"

SCENARIOS = (
    ("hotel", ("酒店", "宾馆", "入住", "客房", "hotel")),
    ("restaurant", ("餐厅", "点餐", "吃饭", "饭店", "restaurant")),
    ("airport", ("机场", "值机", "登机", "airport")),
    ("shopping", ("购物", "买东西", "商店", "shopping", "shop")),
    ("interview", ("面试", "interview")),
    ("travel", ("旅行", "旅游", "出行", "travel")),
    ("hospital", ("医院", "看病", "doctor")),
    ("phone", ("打电话", "电话", "phone call")),
    ("school", ("学校", "校园", "上课", "school")),
)

_ACTIVITY_LABELS = {
    CHAT: "free chat",
    PRACTICE_CONVERSATION: "scenario conversation practice",
    SPEAKING_PRACTICE: "speaking practice",
    VOCAB_LEARN: "vocabulary learning",
    VOCAB_REVIEW: "vocabulary review",
    READING: "reading practice",
    LISTENING: "listening practice",
    CONTINUE_LESSON: "continuing the lesson",
}

_LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]{1,}")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# tokens never treated as the "word" the learner asks about
_STOPWORDS = {
    "i", "a", "an", "the", "you", "me", "my", "we", "us", "it", "this", "that",
    "what", "does", "do", "did", "is", "are", "was", "were", "can", "could",
    "please", "word", "words", "mean", "means", "meaning", "say", "said",
    "speak", "english", "chinese", "ok", "okay", "hi", "hello", "hey",
    "again", "one", "more", "time", "how", "and", "or", "to", "in", "on",
    "of", "for", "with", "so", "yes", "no", "wait", "stop", "go", "let",
    "s", "t", "m", "re",
}

# ---------------------------------------------------------------------------
# context model
# ---------------------------------------------------------------------------


@dataclass
class BehaviorState:
    """Session-scoped context model (in-memory only; never persisted)."""

    main_activity: str = CHAT
    scenario: str | None = None
    temporary_intent: dict | None = None      # {"name": str, "params": {...}}
    resume_note: str | None = None            # human phrase of what to return to
    recent_word: str | None = None
    recent_sentence: str | None = None        # last user utterance (capped; memory only)
    recent_passage: str | None = None
    recent_task: str | None = None            # internal label of the recent task
    language_override: str | None = None      # "zh"|"en" explicit (session)
    speed: str = "normal"                     # slow|normal|fast
    difficulty: str = "normal"                # easy|normal|hard
    saved_prefs: dict = field(default_factory=dict)  # from MEMORY-1
    explicit_prefs: set = field(default_factory=set)  # prefs the USER set this session
    clarify_pending: bool = False


@dataclass
class Decision:
    """Mechanical routing result of one user turn (never spoken)."""

    kind: str = K_NONE
    note: str = ""                    # internal instruction-side note
    activity: str | None = None
    temporary: str | None = None
    params: dict = field(default_factory=dict)
    language_override: str | None = None
    effective_language: str = "zh"
    needs_workbench: str | None = None       # "continue_lesson"|"progress"|"review"
    knowledge_query: str | None = None       # bounded probe text (link retrieves)
    knowledge_explicit: bool = False         # explicit 知识库/资料 ask
    memory: dict | None = None               # {"op": "save"|"forget", ...}
    clarify: bool = False
    changed_state: bool = False


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def looks_english(text: str) -> bool:
    """Majority-latin signal: no CJK chars and at least one latin word."""
    t = _norm(text)
    if not t:
        return False
    if _CJK_RE.search(t):
        return False
    return bool(_LATIN_WORD_RE.search(t))


def extract_word(text: str) -> str | None:
    """First meaningful latin token of the utterance (lower-cased as spoken)."""
    for m in _LATIN_WORD_RE.finditer(text or ""):
        w = m.group(0)
        if w.lower() in _STOPWORDS:
            continue
        if len(w) < 2:
            continue
        return w
    return None


def detect_scenario(text: str) -> str | None:
    t = (text or "").lower()
    for name, keys in SCENARIOS:
        for k in keys:
            if k in t:
                return name
    return None


def _has(text: str, *pats: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in pats)


_QUESTION_RE = re.compile(
    r"[？?]\s*$|吗[？?。.!！]?$|是什么|为什么|怎么样|怎么办|在哪里|在哪儿|"
    r"哪里|哪儿|几点|多少|多久|多长时间|是谁|"
    r"^(what|why|how|where|who|when|which|whose)\b",
    re.IGNORECASE)


def is_question_shaped(text: str) -> bool:
    """Question-like utterance (used only as a bounded knowledge *probe* hint)."""
    return bool(_QUESTION_RE.search(_norm(text)))


_DEICTIC_PREFIX = ("你", "我", "他", "她", "它", "这", "那", "谁", "什", "为", "怎", "哪")


def _cjk_thing_is_what(t: str) -> str | None:
    """"街道是什么？" style vocabulary requests → the subject, else None.

    Conservative: only a short CJK subject (2–8 chars) followed by
    是什么/是啥/叫啥/叫什么.  Deictic/pronoun subjects ("这是什么", "他叫什么")
    are excluded — those are ordinary conversation, not vocabulary questions.
    """
    m = re.fullmatch(r"([\u4e00-\u9fff]{2,8})(是什么|是啥|叫啥|叫什么)[？?。.!！]?", t)
    if not m:
        return None
    subject = m.group(1)
    if subject[0] in _DEICTIC_PREFIX:
        return None
    return subject


def effective_language(state: BehaviorState, text: str,
                       temporary: str | None = None) -> str:
    """Explicit user request wins > activity default > input language mirror."""
    if state.language_override:
        return state.language_override
    temp = temporary or (state.temporary_intent or {}).get("name")
    if temp == EXPLAIN_WORD:
        pref = str(state.saved_prefs.get("explanation_language") or "zh")
        return "en" if pref.startswith("en") else "zh"
    if state.main_activity in (PRACTICE_CONVERSATION, SPEAKING_PRACTICE):
        return "en"
    if state.main_activity == CHAT:
        return "en" if looks_english(text) else "zh"
    return "zh"


# ---------------------------------------------------------------------------
# the router
# ---------------------------------------------------------------------------


def route(text: str, state: BehaviorState,
          policy: dict | None = None) -> Decision:
    """Classify one user utterance and advance the context state.

    ``policy`` (the active PERSONA/TEACHING policy) supplies the substantive
    instruction text referenced/composed by per-turn notes — the policy module
    stays the single source of prompt text (no duplicated directive text here).

    Deterministic precedence:
      preferences/forget → language complaint/override → translate →
      workbench intents → commands (speed/difficulty/repeat/continue) →
      activity switches → temporary intents → clarify → none.
    """
    pol = policy or policy_mod.DEFAULT_POLICY
    raw = text or ""
    t = _norm(raw)
    d = Decision()
    d.effective_language = effective_language(state, t)
    low = t.lower()

    if not t or not (_CJK_RE.search(t) or _LATIN_WORD_RE.search(t)):
        return d  # empty / non-linguistic input: keep everything

    # -- 1. SAVE_PREFERENCE -------------------------------------------------
    m = _match_save_preference(t)
    if m is not None:
        key, value, human = m
        state.saved_prefs[key] = value
        if key == "explanation_language":
            pass  # applied for EXPLAIN_WORD rendering
        elif key == "speed":
            state.speed = value
            state.explicit_prefs.add(key)
        elif key == "difficulty":
            state.difficulty = value
            state.explicit_prefs.add(key)
        d.kind = K_PREF
        d.memory = {"op": "save", "key": key, "value": value}
        d.temporary = SAVE_PREFERENCE
        d.note = ("The user asked you to remember a preference (%s). Confirm very "
                  "briefly in Chinese (one short sentence) and continue naturally; "
                  "do not treat this as a new activity." % human)
        state.temporary_intent = {"name": SAVE_PREFERENCE, "params": {"key": key}}
        d.changed_state = True
        d.effective_language = state.language_override or "zh"
        return d

    # -- 2. forget ----------------------------------------------------------
    if _has(t, r"(忘掉|忘记|删除|清掉|去掉).{0,6}(偏好|这个|那条|它|记忆)",
            r"别记(住)?(这个|了)", r"不用(记|记住)"):
        d.kind = K_PREF
        d.memory = {"op": "forget"}
        d.temporary = SAVE_PREFERENCE
        d.note = ("The user asked you to forget a saved preference. Confirm very "
                  "briefly in Chinese (one short sentence); do not change activity.")
        state.temporary_intent = {"name": SAVE_PREFERENCE, "params": {"key": "_forget"}}
        d.changed_state = True
        d.effective_language = state.language_override or "zh"
        return d

    # -- 3. translate / Chinese→English vocabulary requests ------------------
    _vocab_subject = _cjk_thing_is_what(t)
    if (_has(t, r"翻译", r"translate", r"用(英文|英语|中文)(怎么)?(说|讲|表达)",
             r"(英文|英语|中文)怎么说")
            or _has(t, r"^[\u4e00-\u9fff]{1,8}(怎么|咋)(说|讲|念|表达|拼|拼写)[？?。.!！]?$",
                    r"(英文|英语)(里|中)?的?.{0,12}(怎么|咋)(说|讲|念|表达)",
                    r"的(英文|英语)(是)?(什么|啥|咋说|怎么说)?[？?。.!！]?$")
            or _vocab_subject is not None):
        spelling = _has(t, r"怎么拼", r"咋拼", r"怎么拼写", r"怎么拼啊",
                        r"how do you spell", r"spell",
                        # SPELLING-AUDIO-02: natural letter-spelling phrasings
                        r"拼读", r"拼一下", r"一个字母一个字母", r"逐个字母",
                        r"letter by letter")
        d.kind = K_TEMP
        d.temporary = TRANSLATE
        state.recent_sentence = raw.strip()[:200]
        if spelling:
            d.params["spelling"] = True
            d.note = ("TEMPORARY (this turn only): the user asks how to SPELL a Chinese "
                      "term in English. Spell it letter by letter following the "
                      "VOCABULARY ACCURACY POLICY below (pronunciation stays separate). "
                      "Then return naturally to %s."
                      % _ACTIVITY_LABELS[state.main_activity])
        elif _vocab_subject is not None:
            # "X是什么？" reads like a definition question, but the learner wants the
            # English vocabulary — the real session showed the model answering with a
            # Chinese definition unless the ask is made unambiguous.
            d.params["word_zh"] = _vocab_subject
            d.note = ("TEMPORARY (this turn only): the learner is asking for the ENGLISH "
                      "WORD for「%s」. Even though the question sounds like a definition, "
                      "they want the vocabulary: follow the VOCABULARY ACCURACY POLICY "
                      "below for the answer structure. Do NOT answer with only a Chinese "
                      "definition. Then return naturally to %s."
                      % (_vocab_subject, _ACTIVITY_LABELS[state.main_activity]))
        else:
            d.note = ("TEMPORARY (this turn only): the user wants a Chinese term or "
                      "sentence in English. Follow the VOCABULARY ACCURACY POLICY below "
                      "(spelling first, pronunciation separate). Then return naturally "
                      "to %s."
                      % _ACTIVITY_LABELS[state.main_activity])
        state.temporary_intent = {"name": TRANSLATE, "params": d.params}
        d.effective_language = state.language_override or "zh"
        d.changed_state = True
        return d

    # -- 4. language override / complaint -----------------------------------
    if _has(t, r"(用|说|讲|换).{0,3}中文", r"中文(回答|交流|对话|说话)", r"讲中文",
            r"说中文", r"用中文跟?我", r"不要(说|用|讲)(英文|英语)",
            r"别说(英文|英语)", r"中文说",
            r"为(什么|啥).{0,8}(英文|英语)",
            # English-language forms of the same explicit request (mirror of the EN
            # branch below); imperative/please forms only, so a question that merely
            # mentions Chinese is not hijacked.
            r"speak (in )?chinese", r"switch to chinese", r"in chinese please",
            r"(reply|respond|answer|talk|continue|say it|write)\s+in chinese"):
        state.language_override = "zh"
        d.language_override = "zh"
        d.kind = K_COMMAND
        d.note = ("The user explicitly wants Chinese (they may be unhappy about English "
                  "replies). Switch to Chinese now; if they complained, apologise briefly "
                  "in Chinese; continue the current activity naturally.")
        d.changed_state = True
        d.effective_language = "zh"
        return d
    # A *negative* statement about the learner's own English (inability or refusal) is a
    # limitation, NOT a request to switch: "我不会说英语" / "I can't speak English" must
    # not flip the session to English (adversarial findings RED-J-01, RED-J-R3-01).
    # Kept narrow so a vocabulary question such as "不知道这个词的英语" is never hijacked
    # (the EN forms require a speech/ability verb, so "I don't know the English word"
    # is not matched).
    if _has(t, r"(不|没|别|难以).{0,3}(会|懂|能).{0,4}(英文|英语)",
            r"(不|别).{0,2}(说|讲|用).{0,2}(英文|英语)",
            r"(英文|英语).{0,3}(不好|不行|很差|太差)",
            r"(can'?t|cannot|can not|don'?t|do not|won'?t|will not)\s+(really\s+)?"
            r"(want to\s+|need to\s+|like to\s+)?"
            r"(speak|talk|use|say|answer|reply|respond|communicate)\b.{0,14}\benglish\b",
            r"\benglish\b.{0,10}\b(is|so)\b.{0,10}(bad|poor|weak|terrible|hard|difficult)",
            r"\bmy english\b.{0,4}(bad|poor|weak|terrible|not good|no good)"):
        state.language_override = "zh"
        d.language_override = "zh"
        d.kind = K_COMMAND
        d.note = ("The learner says they cannot (or do not want to) speak English. "
                  "Reassure them briefly in Chinese and continue the current activity in "
                  "Chinese; do not switch to English.")
        d.changed_state = True
        d.effective_language = "zh"
        return d
    if _has(t, r"(用|说|讲).{0,3}(英文|英语)", r"(英文|英语)(回答|交流)",
            r"speak english", r"in english please", r"switch to english",
            r"说英语"):
        state.language_override = "en"
        d.language_override = "en"
        d.kind = K_COMMAND
        d.note = ("The user explicitly asked for English. Comply immediately and "
                  "continue the current activity in English.")
        d.changed_state = True
        d.effective_language = "en"
        return d

    # -- 5. workbench intents ----------------------------------------------
    if _has(t, r"继续上次的课", r"继续上次", r"上次的课", r"接着上次", r"继续上课",
            r"继续学(习)?(吧|上次)?$", r"上次学到"):
        d.kind = K_ACTIVITY
        d.activity = CONTINUE_LESSON
        d.needs_workbench = "continue_lesson"
        state.main_activity = CONTINUE_LESSON
        state.scenario = None
        state.recent_task = "continue_lesson"
        d.note = ("The user wants to continue their course from where they left off. "
                  "The learning system data (authoritative) is provided below: announce "
                  "the lesson briefly in Chinese and start it naturally.")
        d.changed_state = True
        d.effective_language = state.language_override or "zh"
        return d
    if _has(t, r"(学到|学到哪|学得|学到哪儿).{0,4}(哪里|哪儿|哪|怎么样|如何)",
            r"学习进度", r"我的进度", r"进度(怎么样|如何)?$", r"学到什么(程度|了)",
            r"(现在|目前).{0,4}(学到|在第)哪"):
        d.kind = K_TEMP
        d.temporary = QUERY_PROGRESS
        d.needs_workbench = "progress"
        d.note = ("The user asks about their learning progress. The learning system data "
                  "(authoritative) is provided below: answer in Chinese from that data "
                  "only; never invent progress.")
        state.temporary_intent = {"name": QUERY_PROGRESS, "params": {}}
        d.changed_state = True
        d.effective_language = state.language_override or "zh"
        return d
    if _has(t, r"(需要|要|该).{0,4}复习(吗|么)?", r"复习(吗|么)$", r"要(不要|用)?复习",
            r"哪(些|个).{0,4}需要复习"):
        d.kind = K_TEMP
        d.temporary = QUERY_PROGRESS
        d.needs_workbench = "review"
        d.note = ("The user asks whether something needs review. The learning system "
                  "data (authoritative) is provided below: answer in Chinese from that "
                  "data only; never invent review state.")
        state.temporary_intent = {"name": QUERY_PROGRESS, "params": {"scope": "review"}}
        d.changed_state = True
        d.effective_language = state.language_override or "zh"
        return d

    # -- 5b. explicit knowledge-base asks ------------------------------------
    if (_has(t, r"知识库", r"资料库")
            or (_has(t, r"资料", r"文档", r"笔记", r"文件")
                and _has(t, r"查|搜|找|有没有|存了|收录|记录"))):
        d.kind = K_TEMP
        d.temporary = QUERY_KNOWLEDGE
        d.knowledge_query = t[:120]
        d.knowledge_explicit = True
        d.note = ("TEMPORARY (this turn only): the user is asking about the KNOWLEDGE "
                  "BASE. Use the KNOWLEDGE BASE DATA below if it is present; if it says "
                  "no matching entry, answer honestly in Chinese that the knowledge "
                  "base has no such information — never invent. Then return naturally "
                  "to %s." % _ACTIVITY_LABELS[state.main_activity])
        state.temporary_intent = {"name": QUERY_KNOWLEDGE, "params": {}}
        d.changed_state = True
        d.effective_language = state.language_override or "zh"
        return d

    # -- 6. commands --------------------------------------------------------
    if _has(t, r"(说|讲|语速)?慢(一)?(点|些|点儿)", r"慢一点", r"慢点", r"slower",
            r"speak (more )?slowly", r"slow down"):
        state.speed = "slow"
        state.explicit_prefs.add("speed")
        d.kind = K_COMMAND
        d.params["speed"] = "slow"
        d.effective_language = effective_language(state, t)
        d.note = ("The user asked you to slow down. Acknowledge in one short sentence "
                  "in %s and continue the current activity at a slower pace."
                  % _LANG_NAME[d.effective_language])
        d.changed_state = True
        return d
    if _has(t, r"(说|讲|语速)?快(一)?(点|些|点儿)", r"快一点", r"快点", r"faster",
            r"speak (more )?quickly"):
        state.speed = "fast"
        state.explicit_prefs.add("speed")
        d.kind = K_COMMAND
        d.params["speed"] = "fast"
        d.effective_language = effective_language(state, t)
        d.note = ("The user asked you to speed up. Acknowledge in one short sentence "
                  "in %s and continue the current activity a bit faster."
                  % _LANG_NAME[d.effective_language])
        d.changed_state = True
        return d
    if _has(t, r"正常(语速|速度)", r"像平时一样(说|讲)"):
        state.speed = "normal"
        state.explicit_prefs.add("speed")
        d.kind = K_COMMAND
        d.effective_language = effective_language(state, t)
        d.note = ("The user asked for the normal speaking pace. Acknowledge briefly in "
                  "one short sentence and continue.")
        d.changed_state = True
        return d
    if _has(t, r"(难|harder|更难)(一)?(点|些|点儿)", r"难一点", r"难点儿", r"再难",
            r"harder", r"太简单"):
        state.difficulty = "hard"
        state.explicit_prefs.add("difficulty")
        d.kind = K_COMMAND
        d.params["difficulty"] = "hard"
        d.note = ("The user wants it harder while staying in the current activity. "
                  "Continue %s with richer vocabulary / longer sentences; do not mention "
                  "levels or modes." % _ACTIVITY_LABELS[state.main_activity])
        d.changed_state = True
        d.effective_language = effective_language(state, t)
        return d
    if _has(t, r"(简单|容易|easier)(一)?(点|些|点儿)", r"简单一点", r"简单点",
            r"太?难(了|一点)?[，,。!]?$", r"easier", r"太难了"):
        state.difficulty = "easy"
        state.explicit_prefs.add("difficulty")
        d.kind = K_COMMAND
        d.params["difficulty"] = "easy"
        d.note = ("The user wants it easier while staying in the current activity. "
                  "Continue %s with simpler, shorter language; do not mention levels."
                  % _ACTIVITY_LABELS[state.main_activity])
        d.changed_state = True
        d.effective_language = effective_language(state, t)
        return d
    if _has(t, r"再来(一次|一遍|一回|一个)", r"再(说|读|讲)(一次|一遍)",
            r"重复(一下|一遍|一次)?$", r"one more time", r"^again[.!]?$",
            r"say (it|that) again", r"repeat"):
        d.kind = K_COMMAND
        d.params["repeat"] = True
        state.recent_task = (state.recent_task or "the recent content")
        d.note = ("The user asked you to repeat (again). Repeat your previous reply or "
                  "the recent practice item naturally and completely — you have the "
                  "whole conversation history; do not explain that you are repeating.")
        d.changed_state = True
        d.effective_language = effective_language(state, t)
        return d
    if _has(t, r"继续[吧!。.~～]?$", r"接着(说|讲|来|做)", r"然后呢",
            r"^go on", r"^continue[.!]?$"):
        d.kind = K_COMMAND
        d.params["continue"] = True
        d.note = ("The user wants to continue. Resume the recent task/flow naturally "
                  "(%s)." % (state.recent_task or _ACTIVITY_LABELS[state.main_activity]))
        d.changed_state = True
        d.effective_language = effective_language(state, t)
        return d

    # -- 7. activity switches ----------------------------------------------
    if "聊" in t and _has(t, r"(别|不要|不).{0,8}(背|学|练|复习)"):
        return _switch_activity(d, state, CHAT, t, raw)
    if _has(t, r"随便聊", r"聊(聊|一?会儿?天|天|会天)", r"闲聊", r"聊天",
            r"说说话", r"^chat", r"let'?s chat", r"just (chat|talk)"):
        return _switch_activity(d, state, CHAT, t, raw)
    if _has(t, r"练(一?下|习)?.*(英语|口语|对话|发音)", r"(英语|口语).*(练习|练一下|练练)",
            r"情景(练习|对话)", r"场景(练习|对话)", r"role.?play", r"对话练习",
            r"口语练习", r"练口语", r"练语音"):
        if _has(t, r"口语", r"发音", r"语音") and not _has(t, r"对话|情景|场景", r"英语对"):
            return _switch_activity(d, state, SPEAKING_PRACTICE, t, raw)
        return _switch_activity(d, state, PRACTICE_CONVERSATION, t, raw)
    if _has(t, r"练.*(对话|情景|场景|酒店|餐厅|机场|面试|机场|旅行|医院|购物)",
            r"(英语|英文).*(对话|情景|场景|练习)") and not _has(t, r"听|读"):
        return _switch_activity(d, state, PRACTICE_CONVERSATION, t, raw)
    if (detect_scenario(t) is not None
            and _has(t, r"练", r"practice", r"英语", r"english", r"对话")):
        return _switch_activity(d, state, PRACTICE_CONVERSATION, t, raw)
    if _has(t, r"(背|学|记|来)(几个)?(新)?(单词|词汇)", r"想?学.{0,14}(单词|词)",
            r"背单词", r"学单词", r"单词学习", r"vocab.*(learn|study)"):
        d0 = _switch_activity(d, state, VOCAB_LEARN, t, raw)
        w = extract_word(t)
        if w:
            state.recent_word = w
        return d0
    if _has(t, r"复习.{0,4}(单词|词汇|词语)", r"(单词|词汇).*(复习|review)", r"检查.{0,4}单词",
            r"review.{0,6}(words|vocab)"):
        return _switch_activity(d, state, VOCAB_REVIEW, t, raw)
    if _has(t, r"读(一?段|一?篇|读)?(文章|课文|短文|段落)?", r"阅读", r"reading",
            r"朗读") and _has(t, r"读|阅读|reading|朗读"):
        if _has(t, r"(阅读|读文章|读一段|读一篇|读课文|短文|段落|reading)"):
            return _switch_activity(d, state, READING, t, raw)
    if _has(t, r"听(力|写|一段|录音|材料)", r"练耳", r"听力练习", r"listening"):
        if _has(t, r"听力|听写|练耳|listening|听录音|听材料|听一段"):
            return _switch_activity(d, state, LISTENING, t, raw)

    # -- 8. temporary intents ----------------------------------------------
    # SPELLING-AUDIO-02 fix A: natural letter-spelling phrasings (拼读/拼一下/
    # 一个字母一个字母/letter by letter/…) now trigger the spelling intent; the
    # Latin-word requirement keeps ordinary sentences without a word subject
    # from false-triggering.  "spell" is un-anchored (\bspell\b) so mid-sentence
    # "please spell touch" works too.
    if _has(t, r"怎么拼", r"咋拼", r"怎么拼写", r"怎么拼啊", r"how do you spell",
            r"\bspell\b", r"\bspell it out\b", r"\bletter by letter\b",
            r"拼读", r"拼一下", r"拼出来", r"一个字母一个字母", r"逐个字母") \
            and _LATIN_WORD_RE.search(t):
        # SPELLING-AUDIO-02: the trigger verb is not the subject — strip the
        # spelling trigger phrases before word extraction ("spell it out:
        # through" must yield "through", not "spell").
        t_word = re.sub(r"\bhow (do|to) you spell\b|\bspell (it |them |the word )?out\b|"
                        r"\bspell\b|\bletter by letter\b|怎么拼|怎么拼写|咋拼|拼读|拼一下|"
                        r"拼出来|一个字母一个字母|逐个字母", " ", t, flags=re.IGNORECASE)
        w = extract_word(t_word) or extract_word(t) or state.recent_word
        return _explain_word(d, state, w, t, spelling=True, policy=pol)
    if (_has(t, r"不(认识|懂|会)", r"没见过",
             r"不知道(这个|这|那个)?(单词|词)")
            and ("词" in t or _LATIN_WORD_RE.search(t))):
        w = extract_word(t) or state.recent_word
        return _explain_word(d, state, w, t, policy=pol)
    if _has(t, r"(不)?懂.{0,4}(这个)?(单词|词|意思)", r"(这个)?(单词|词).{0,6}(不懂|不知道)"):
        w = extract_word(t) or state.recent_word
        return _explain_word(d, state, w, t, policy=pol)
    if _has(t, r"什么意思", r"啥意思", r"是什么意思", r"怎么读", r"怎么念", r"读音",
            r"what does .* mean"):
        w = extract_word(t) or state.recent_word
        if w:
            return _explain_word(d, state, w, t, policy=pol)
        return _explain_word(d, state, None, t, policy=pol)
    if _has(t, r"语法", r"时态", r"grammar", r"为什么(用|是)", r"这句话.{0,6}(为什么|怎么)"):
        d.kind = K_TEMP
        d.temporary = EXPLAIN_GRAMMAR
        state.recent_sentence = raw.strip()[:200]
        d.note = ("TEMPORARY (this turn only): explain the grammar briefly in Chinese — "
                  "%s. Then return naturally to %s."
                  % (pol["teaching"]["grammar_explanation"],
                     _ACTIVITY_LABELS[state.main_activity]))
        state.temporary_intent = {"name": EXPLAIN_GRAMMAR, "params": {}}
        d.changed_state = True
        d.effective_language = state.language_override or "zh"
        return d

    # -- 9. clarify / none ---------------------------------------------------
    if _has(t, r"(帮|教|陪)我(练|学|复习)", r"^练(习|一下|一练)?[吧!。.~～]?$",
            r"^学(习|一下)?[吧!。.~～]?$", r"^复习[吧!。.~～]?$"):
        d.kind = K_NONE
        d.clarify = True
        state.clarify_pending = True
        d.note = ("The user's request is ambiguous. Ask ONE short, friendly question in "
                  "Chinese to find out what they want (which practice / which topic); "
                  "stay in %s meanwhile; do not switch activities yet."
                  % _ACTIVITY_LABELS[state.main_activity])
        d.changed_state = True
        d.effective_language = state.language_override or "zh"
        return d

    # -- 10. implicit knowledge probe ----------------------------------------
    # A question that nothing else claimed may be answerable from the knowledge
    # base.  The router only marks the probe; the gateway link retrieves locally
    # and injects an ephemeral block ONLY when the store actually has a match
    # (honest silence on a miss — no fabricated data, no extra instruction).
    if is_question_shaped(t):
        d.knowledge_query = t[:120]

    return d  # K_NONE: continue naturally in the current activity


_LANG_NAME = {"zh": "Chinese", "en": "English"}


def _switch_activity(d: Decision, state: BehaviorState, activity: str,
                     text: str, raw: str) -> Decision:
    scen = detect_scenario(text)
    state.main_activity = activity
    state.scenario = scen
    state.temporary_intent = None
    state.clarify_pending = False
    state.recent_task = "activity:%s%s" % (activity, (":" + scen) if scen else "")
    d.kind = K_ACTIVITY
    d.activity = activity
    d.params["scenario"] = scen
    d.changed_state = True
    if activity == CHAT:
        d.note = ("The user wants to just chat now. Switch to warm free conversation in "
                  "the user's language; do not drill, quiz or correct unless asked.")
    elif activity == PRACTICE_CONVERSATION:
        d.note = ("The user wants scenario conversation practice%s. Set the scene in one "
                  "short English sentence and start the role-play naturally."
                  % ((" (%s)" % scen) if scen else ""))
    elif activity == SPEAKING_PRACTICE:
        d.note = ("The user wants speaking practice. Start with one short simple prompt "
                  "and keep the turn going.")
    elif activity == VOCAB_LEARN:
        d.note = ("The user wants to learn some words. Follow the teaching policy's "
                  "vocabulary format below, keeping it natural, then a quick check.")
    elif activity == VOCAB_REVIEW:
        d.note = ("The user wants a quick vocabulary review. Quiz a few recent words "
                  "conversationally; keep it light.")
    elif activity == READING:
        d.note = ("The user wants reading practice. Read a short passage sentence by "
                  "sentence, checking understanding briefly.")
    elif activity == LISTENING:
        d.note = ("The user wants listening practice. Say a short sentence clearly, then "
                  "ask what they heard; keep it light.")
    d.effective_language = effective_language(state, text)
    if activity in (PRACTICE_CONVERSATION, SPEAKING_PRACTICE):
        d.effective_language = "en"
    return d


def _explain_word(d: Decision, state: BehaviorState, word: str | None,
                  text: str, spelling: bool = False,
                  policy: dict | None = None) -> Decision:
    pol = policy or policy_mod.DEFAULT_POLICY
    d.kind = K_TEMP
    d.temporary = EXPLAIN_WORD
    if word:
        state.recent_word = word
    d.params["word"] = word
    if spelling:
        d.params["spelling"] = True
        if word:
            d.note = ("TEMPORARY (this turn only): the user asks how to SPELL \"%s\". "
                      "Spell it letter by letter following the VOCABULARY ACCURACY "
                      "POLICY below (pronunciation separate). Then return naturally to %s."
                      % (word, _ACTIVITY_LABELS[state.main_activity]))
        else:
            d.note = ("TEMPORARY (this turn only): the user asks how to spell a word but "
                      "did not say which one. Ask ONE short question in Chinese to get "
                      "the word. Then return naturally to %s."
                      % _ACTIVITY_LABELS[state.main_activity])
    elif word:
        d.note = ("TEMPORARY (this turn only): explain the word \"%s\" — %s. Then "
                  "return naturally to %s."
                  % (word, pol["language"]["word_explanation_order"],
                     _ACTIVITY_LABELS[state.main_activity]))
    else:
        d.note = ("TEMPORARY (this turn only): the user wants a word explained but did not "
                  "say which one%s. Ask ONE short question in Chinese to get the word, "
                  "or pick the most recent unclear word from the conversation if there is "
                  "one. Then return naturally to %s."
                  % ((" (most recent word: %s)" % state.recent_word)
                     if state.recent_word else "",
                     _ACTIVITY_LABELS[state.main_activity]))
    state.temporary_intent = {"name": EXPLAIN_WORD, "params": {"word": word}}
    d.changed_state = True
    d.effective_language = effective_language(state, text, temporary=EXPLAIN_WORD)
    return d


_SAVE_PATTERNS = (
    (r"以后.{0,8}(解释|讲).{0,6}(单词|词|意思).{0,6}(先)?(用)?中文",
     "explanation_language", "zh", "单词解释先用中文"),
    (r"以后.{0,8}(解释|讲).{0,6}(单词|词|意思).{0,6}(先)?(用)?英文",
     "explanation_language", "en", "单词解释先用英文"),
    (r"以后.{0,6}(说|讲)(慢|慢一点|慢点)", "speed", "slow", "以后说话慢一点"),
    (r"以后.{0,6}(说|讲)(快|快一点|快点)", "speed", "fast", "以后说话快一点"),
    (r"以后.{0,6}(难|难一点|难一些)", "difficulty", "hard", "以后难度高一点"),
    (r"以后.{0,6}(简单|容易)(一点|一些)?", "difficulty", "easy", "以后简单一点"),
)


def _match_save_preference(t: str):
    """Return (key, value, human_phrase) when the utterance commits a preference.

    The user must explicitly ask to remember ("记住/记一下/…") AND state the
    preference itself ("以后…").  Anything weaker is not persisted
    (MEMORY-1 stores explicit preferences only).
    """
    must_commit = _has(t, r"记住", r"记一下", r"记着", r"remember", r"别忘了")
    if not must_commit:
        return None
    for pat, key, value, human in _SAVE_PATTERNS:
        if re.search(pat, t):
            return key, value, human
    return None


# ---------------------------------------------------------------------------
# renderer
# ---------------------------------------------------------------------------

# Prompt text lives in `modules/policy/persona.py` (the single source); the
# renderer below composes every line from the active policy via its helpers.
# Internal activity labels stay here (routing taxonomy, never spoken).


def render_instructions(state: BehaviorState, decision: Decision | None = None,
                        *, workbench_block: str | None = None,
                        knowledge_block: str | None = None,
                        memory_block: str | None = None,
                        preferences: dict | None = None,
                        policy: dict | None = None) -> str:
    """Render the full instruction block for the Qwen session.

    Deterministic; every prompt line is composed from the active policy
    (`modules/policy/persona.py` — the single source) plus the per-turn routing
    state: activity, temporary-intent note (with the resume instruction) and the
    authoritative workbench data (or its explicit degrade line).  The rendered
    block is bounded by the policy's ``max_instruction_chars``.  Internal labels
    are for the model only and are explicitly marked as never spoken.
    """
    pol = policy or policy_mod.DEFAULT_POLICY
    dec = decision or Decision()
    lang = dec.effective_language or effective_language(state, "")
    lang_name = _LANG_NAME.get(lang, "Chinese")
    lines = policy_mod.render_persona_lines(pol)
    lines.append("")
    lines.extend(policy_mod.render_language_lines(
        pol, lang_name=lang_name,
        override=state.language_override or "none"))
    lines.append("")
    lines.append("TEACHING POLICY:")
    lines.extend(policy_mod.render_teaching_lines(pol))
    lines.append("")
    lines.append("CURRENT ACTIVITY: %s" % _ACTIVITY_LABELS.get(state.main_activity,
                                                              state.main_activity))
    lines.append(policy_mod.render_activity_instruction(pol, state.main_activity))
    if state.main_activity == PRACTICE_CONVERSATION and state.scenario:
        lines.append("Scenario — %s."
                     % policy_mod.render_scenario_text(pol, state.scenario))
    lines.append(policy_mod.render_speed_line(pol, state.speed))
    lines.append(policy_mod.render_difficulty_line(pol, state.difficulty))

    if (dec.temporary in (EXPLAIN_WORD, TRANSLATE)
            or state.main_activity in (VOCAB_LEARN, VOCAB_REVIEW)):
        lines.append("")
        lines.append(policy_mod.render_vocab_policy(pol))

    if dec.note:
        lines.append("")
        lines.append(dec.note)
    if state.temporary_intent and dec.temporary is None:
        # a still-open temporary intent from the previous turn
        name = state.temporary_intent.get("name")
        lines.append("TEMPORARY (still open): %s — finish it, then return to %s."
                     % (name, _ACTIVITY_LABELS.get(state.main_activity, "")))

    if workbench_block:
        lines.append("")
        lines.append(workbench_block)

    if knowledge_block:
        lines.append("")
        lines.append(knowledge_block)

    prefs = preferences or state.saved_prefs or {}
    if prefs:
        pref_bits = []
        # A saved preference is only restated when it does NOT contradict the effective
        # state: an explicit current request outranks it (precedence contract), so
        # mentioning the stale saved value would hand the model two conflicting
        # instructions (adversarial findings RED-J-02 / RED-J-03 / RED-J-R3-02 /
        # RED-J-R3-06).
        if prefs.get("explanation_language"):
            pref_lang = ("zh" if str(prefs["explanation_language"]).startswith("zh")
                         else "en")
            if pref_lang == lang:
                pref_bits.append("word explanations first in %s"
                                 % ("中文" if pref_lang == "zh" else "English"))
        if prefs.get("speed") and prefs["speed"] == state.speed:
            pref_bits.append("speaking pace %s" % prefs["speed"])
        if prefs.get("difficulty") and prefs["difficulty"] == state.difficulty:
            pref_bits.append("difficulty %s" % prefs["difficulty"])
        if pref_bits:
            lines.append("")
            lines.append("The learner asked you to remember: %s."
                         % "; ".join(pref_bits))

    if memory_block:
        lines.append("")
        lines.append(memory_block)

    lines.append("")
    lines.append(policy_mod.render_closing_line(pol))
    out = "\n".join(lines)
    cap = policy_mod.instruction_cap(pol)      # bounded rendered instruction
    if cap and len(out) > cap:
        out = out[:cap] + "\n[instruction truncated to the configured bound]"
    return out


DEGRADE_LINE = ("Progress information is temporarily unavailable — do not invent any "
                "progress; say in Chinese that the learning system was not reachable "
                "just now and suggest trying again shortly.")


def render_workbench_block(result, *, kind: str) -> str:
    """Render the authoritative workbench block (or the explicit degrade line).

    `result` is an adapters.workbench.Result-like object; this renderer only
    consumes the already-normalized fields (never invents values).
    """
    if result is None or not getattr(result, "ok", False):
        return ("LEARNING SYSTEM DATA: UNAVAILABLE. %s" % DEGRADE_LINE)
    data = result.data
    prov = getattr(result, "provenance", None)
    age = getattr(prov, "age_s", None)
    stale = bool(getattr(prov, "stale", False))
    lines = ["LEARNING SYSTEM DATA (authoritative — read-only, do not remember it, "
             "never invent beyond it):"]
    if kind == "continue_lesson":
        lines.append("- Resume lesson %s%s."
                     % (data.get("lesson_id"),
                        (" — \"%s\"" % data["title"]) if data.get("title") else ""))
        if data.get("objectives"):
            lines.append("- Objectives: %s" % "; ".join(data["objectives"][:3]))
        lines.append("Announce it in one short Chinese sentence and start naturally.")
    elif kind == "review":
        if data.get("due_count") is not None:
            lines.append("- Review items due: %s." % data["due_count"])
        if data.get("next_due"):
            lines.append("- Next review date: %s." % data["next_due"])
        for w in (data.get("due_words") or [])[:4]:
            lines.append("- Due word: %s" % w)
        lines.append("Answer in Chinese using only these numbers/words.")
    else:  # progress
        bits = []
        if data.get("lesson_id") is not None:
            bits.append("current lesson: %s%s"
                        % (data["lesson_id"],
                           (" (\"%s\")" % data["title"]) if data.get("title") else ""))
        if data.get("passed") is not None:
            bits.append("passed: %s" % data["passed"])
        if data.get("review_required") is not None:
            bits.append("need review: %s" % data["review_required"])
        if data.get("repeat_required") is not None:
            bits.append("need repeat: %s" % data["repeat_required"])
        if data.get("due_count") is not None:
            bits.append("review items due: %s" % data["due_count"])
        if bits:
            lines.append("- " + "; ".join(bits) + ".")
        lines.append("Answer in Chinese using only these values.")
    if stale and age is not None:
        # never say "about 0 minute(s) old" for a sub-minute age (adversarial finding
        # R-E-1); round to the nearest minute with a floor of one
        lines.append("- This data is about %d minute(s) old — mention that it may not be "
                     "the very latest." % max(1, int(round(age / 60.0))))
    return "\n".join(lines)