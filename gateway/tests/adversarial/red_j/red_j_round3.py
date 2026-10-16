"""RED-J ROUND 3 — independent cross-check / regression + defeat suite.

Post-fix target: commits e3c9b6c, b854778, 6d3c8a9.
Deterministic, mock-only, in-process.  Asserts on ROUTING DECISION / RENDERED
INSTRUCTIONS only.  No real-Qwen, no network, no audio, no product-source edits.

Run:
  DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python \
      tests/adversarial/red_j/red_j_round3.py
"""

import asyncio
import os
import sys
import tempfile
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
_GATEWAY = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
_REPO = os.path.dirname(_GATEWAY)
for p in (_GATEWAY, _REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

from app import behavior as link_mod                                    # noqa: E402
from modules.intent import behavior as intent                           # noqa: E402
from modules.memory.store import (BoundaryViolation, MemoryStore)       # noqa: E402
from modules.knowledge.store import (KnowledgeStore,                     # noqa: E402
                                     render_knowledge_block)
from modules.memory.store import render_memory_block                     # noqa: E402

RESULTS = []
FINDINGS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % detail) if (detail and not cond) else ""))


def note(msg):
    print("      " + msg)


def finding(fid, sev, surface, pre, repro, expected, actual, note_=""):
    FINDINGS.append(dict(id=fid, severity=sev, surface=surface, pre=pre,
                         repro=repro, expected=expected, actual=actual, note=note_))


class FakeQwen:
    def __init__(self):
        self.ins = "BASE"

    @property
    def instructions(self):
        return self.ins

    def set_instructions(self, t):
        self.ins = t

    async def send_instructions_update(self, t):
        self.ins = t
        return True


class FakeConn:
    def __init__(self, safe=True):
        self.safe = safe

    def is_safe_boundary(self):
        return self.safe


def _cfg(memory_file="", wb_url="", knowledge_file="", policy_file=""):
    return SimpleNamespace(MEMORY_FILE=memory_file, WORKBENCH_BASE_URL=wb_url,
                           KNOWLEDGE_FILE=knowledge_file, POLICY_FILE=policy_file)


def _t(text, item):
    return {"type": "conversation.item.input_audio_transcription.completed",
            "transcript": text, "item_id": item}


def _done():
    return {"type": "response.done", "response": {"status": "completed"}}


def route_one(u, **kw):
    st = intent.BehaviorState()
    for k, v in kw.items():
        setattr(st, k, v)
    return intent.route(u, st), st


# ===========================================================================
# R1. RED-J-01 defeat attempts — language switch phrasings
# ===========================================================================

def t_r1_language():
    # (a) CJK inability / refusal — the round-1 fix target
    for text, why in (("我不会说英语", "can't"),
                      ("我英语不好", "bad"),
                      ("我的英语很差", "very bad"),
                      ("我英语不行", "no good"),
                      ("别说英语了", "don't"),
                      ("我不想说英语", "don't want")):
        d, st = route_one(text)
        check("R1 CJK inability/refusal %r -> zh (no EN flip)" % text,
              st.language_override == "zh" and d.effective_language == "zh",
              "override=%r" % st.language_override)

    # (b) the SAME refusal expressed in English — defeat attempt
    flipped = []
    for text in ("don't speak English", "I can't speak English",
                 "I don't want to speak English", "please don't speak English"):
        d, st = route_one(text)
        if st.language_override == "en":
            flipped.append(text)
        check("R1 [DEFEAT?] English refusal %r must NOT force en" % text,
              st.language_override != "en",
              "override=%r" % st.language_override)
    if flipped:
        finding("RED-J-R3-01", "MAJOR", "modules/intent/behavior.py route() language "
                "override (inability/refusal guard is CJK-only)",
                "CHAT, user states (in English) that they cannot/won't speak English",
                "route(%r, BehaviorState())" % flipped[0],
                "same as the fixed CJK case: a refusal/inability statement must not "
                "force the session into English (it should stay Chinese)",
                "the EN-request branch matches the substring 'speak english', so %r all "
                "set language_override='en' — the round-1 fix (RED-J-01) only guards the "
                "CJK phrasings" % flipped,
                "the inability/refusal guard patterns only contain CJK chars; the later "
                "en branch still matches 'speak english' unconditionally")

    # (c) mixed-script refusal (benign: must not flip to en)
    d, st = route_one("别说 English 了")
    check("R1 mixed-script refusal does not flip to en",
          st.language_override != "en", "override=%r" % st.language_override)

    # positive controls: genuine requests still work
    for text in ("说英语", "Let's speak English", "我们来说英语吧"):
        d, st = route_one(text)
        check("R1 positive control %r -> en" % text, st.language_override == "en",
              "override=%r" % st.language_override)
    for text in ("说中文", "请用中文回答"):
        d, st = route_one(text)
        check("R1 positive control %r -> zh" % text, st.language_override == "zh",
              "override=%r" % st.language_override)


# ===========================================================================
# R2. RED-J-02/03 defeat attempts — precedence
# ===========================================================================

def t_r2_precedence():
    # (a) render contradiction on speed/difficulty — round-1 fix
    st = intent.BehaviorState()
    intent.route("以后说慢一点，记住", st)
    d = intent.route("快一点", st)
    b = intent.render_instructions(st, d, preferences=st.saved_prefs)
    check("R2 speed: explicit faster does not restate saved slow",
          "a bit faster than normal" in b and "speaking pace slow" not in b)

    st = intent.BehaviorState()
    intent.route("以后难一点，记住", st)
    d = intent.route("简单一点", st)
    b = intent.render_instructions(st, d, preferences=st.saved_prefs)
    check("R2 difficulty: explicit easier does not restate saved hard",
          "Difficulty: easy" in b and "difficulty hard" not in b)

    # (b) two saved prefs, only one overridden -> no contradiction, other kept
    st = intent.BehaviorState(saved_prefs={"speed": "slow", "difficulty": "hard"})
    st.speed, st.difficulty = "slow", "hard"
    d = intent.route("快一点", st)                       # explicit speed only
    b = intent.render_instructions(st, d, preferences=st.saved_prefs)
    check("R2 two prefs: overridden speed suppressed, difficulty kept",
          "speaking pace slow" not in b and "difficulty hard" in b
          and "a bit faster than normal" in b, b[-200:])

    # (c) explanation_language vs an EXPLICIT language override -> DEFEAT
    st = intent.BehaviorState(saved_prefs={"explanation_language": "en"})
    st.language_override = "zh"                          # explicit "说中文" earlier
    d = intent.route("hotel 是什么意思", st)
    b = intent.render_instructions(st, d, preferences=st.saved_prefs)
    expl_pref = "word explanations first in English" in b
    override = "(current override: zh)" in b
    check("R2 [DEFEAT] explicit zh override vs saved expl-lang=en contradiction",
          not (expl_pref and override),
          "expl_pref=%s override=%s" % (expl_pref, override))
    if expl_pref and override:
        finding("RED-J-R3-02", "MAJOR", "modules/intent/behavior.py render_instructions()",
                "saved explanation_language=en (disk/admin), then an explicit 说中文 "
                "(language_override=zh)",
                'state.saved_prefs={"explanation_language":"en"}; '
                'state.language_override="zh"; route("hotel 是什么意思"); render',
                "the explicit current request (zh) outranks the saved preference, so the "
                "block must not also assert 'word explanations first in English'",
                "the block states BOTH 'Current reply language: Chinese' + '(current "
                "override: zh)' AND 'The learner asked you to remember: word explanations "
                "first in English' — the saved-preference contradiction the speed/"
                "difficulty fix removed is still present for explanation_language",
                "the fix guards speed/difficulty equality but not explanation_language")

    # (d) explanation_language vs an explicit word-order request (explicit wins)
    st = intent.BehaviorState(saved_prefs={"explanation_language": "en"})
    d = intent.route("用中文解释 hotel 是什么意思", st)
    check("R2 explicit '用中文解释' wins over saved expl-lang=en",
          d.effective_language == "zh", "eff=%r ovr=%r" % (d.effective_language,
                                                           st.language_override))

    # (e) saved pref written by the ADMIN plane mid-session reverts an explicit change
    async def r2e():
        with tempfile.TemporaryDirectory() as td:
            mp = os.path.join(td, "memory.json")
            q = FakeQwen()
            link = link_mod.BehaviorLink(FakeConn(), q, config=_cfg(memory_file=mp))
            await link.on_qwen_event(_t("以后说慢一点，记住", "p1"))
            await link.on_qwen_event(_t("快一点", "p2"))
            before = link.state.speed
            # external control-plane writer (admin) rewrites the memory file
            m2 = MemoryStore(mp).load()
            m2.save_preference("speed", "slow")
            link._maybe_reload_stores()
            return before, link.state.speed
    before, after = asyncio.run(r2e())
    check("R2 [DEFEAT] admin-written saved pref reverts an explicit per-turn speed",
          not (before == "fast" and after == "slow"),
          "before=%s after=%s" % (before, after))
    if before == "fast" and after == "slow":
        finding("RED-J-R3-03", "MINOR", "gateway/app/behavior.py _maybe_reload_stores()",
                "saved speed=slow; user explicitly 快一点 (state fast); then an external "
                "(admin/control-plane) memory write changes the file signature",
                "BehaviorLink sequence: save slow -> 快一点 -> external "
                "MemoryStore.save_preference('speed','slow') -> _maybe_reload_stores()",
                "the explicit current-session request should survive a store reload; a "
                "reload should refresh saved_prefs but not silently override the running "
                "session state with a stale value",
                "state.speed is re-forced to the saved value on every reload, so the "
                "explicit 'faster' is reverted to 'slow' without any user turn",
                "reload branch re-applies saved speed/difficulty over live state")

    # (f) explicit override survives a reload (control)
    async def r2f():
        with tempfile.TemporaryDirectory() as td:
            mp = os.path.join(td, "memory.json")
            q = FakeQwen()
            link = link_mod.BehaviorLink(FakeConn(), q, config=_cfg(memory_file=mp))
            await link.on_qwen_event(_t("说中文", "q1"))
            m2 = MemoryStore(mp).load()
            m2.save_preference("speed", "slow")
            link._maybe_reload_stores()
            return link.state.language_override
    ovr = asyncio.run(r2f())
    check("R2 explicit language override survives a store reload",
          ovr == "zh", "override=%r" % ovr)


# ===========================================================================
# R3. progress smugglers through the normalize-then-match screen
# ===========================================================================

def _refused_value(v, key="note"):
    with tempfile.TemporaryDirectory() as td:
        ms = MemoryStore(os.path.join(td, "m.json")).load()
        try:
            ms.save("profile_fact", key, v)
            return False
        except BoundaryViolation:
            return True


def t_r3_smugglers():
    # (value, refused?) — refused is the OBSERVED screen outcome; the "gaps" are the
    # False rows that a progress-shaped value SHOULD have been refused on.
    smugglers = [
        ("第12課", True),           # traditional digits  -> caught
        ("第 12 课", True),
        ("Lesson Twelve", True),    # spelled-out English numeral -> caught
        ("已完成 第十二课", True),   # keyword 已完成 -> caught
        ("lesson #12", False),      # '#' not a separator   -> MISSED
        ("第十二课", False),         # Chinese NUMERALS      -> MISSED
        ("unit 12 done", False),    # reversed verb/noun    -> MISSED
        ("progress=12", False),     # bare 'progress' value -> MISSED
        ("12课", False),            # trailing numeral      -> MISSED
        ("我已学完第十二課", False), # shape '.' matches ONE char only -> MISSED
    ]
    for v, expect_refused in smugglers:
        got = _refused_value(v)
        note("smuggler %-18r refused=%s" % (v, got))
        check("R3 smuggler %r refused as expected" % v, got == expect_refused,
              "refused=%s expected=%s" % (got, expect_refused))
    still_open = [v for v, _ in smugglers if not _refused_value(v)]
    caught = [v for v, _ in smugglers if _refused_value(v)]
    note("CAUGHT : %r" % caught)
    note("MISSED : %r" % still_open)
    if still_open:
        finding("RED-J-R3-04", "MAJOR", "modules/memory/store.py looks_like_progress()",
                "user saves a profile_fact whose value claims course progress",
                "MemoryStore.save('profile_fact','note',V) for V in %r" % still_open,
                "progress-shaped values are refused (Workbench owns progress)",
                "these pass the screen: %r. MISSED = Chinese numerals (第十二课), trailing "
                "numerals (12课), '#' separator (lesson #12), bare English 'progress' "
                "(progress=12), reversed verb/noun (unit 12 done), and a 2-char gap after "
                "the verb (学完第十二课 — the '.' only matches one char). CAUGHT = "
                "第<digit>课 / Lesson Twelve / keyword 已完成" % still_open,
                "_PROGRESS_SHAPES only enumerates a few shapes; _PROGRESS_KEYWORDS omits "
                "bare 'progress'; '#' is not in _SEPARATORS_RE; the verb+课 shape uses a "
                "single-char wildcard")


# ===========================================================================
# R4. FALSE POSITIVES of the widened screen
# ===========================================================================

def t_r4_false_positives():
    ordinary = [
        "密码学", "学密码学", "密码学家",
        "进度条",
        "tokenize", "secretary", "passwordless",
        "我完成了作业", "我学到了很多",
    ]
    # values the widened screen should ALLOW (ordinary learner facts)
    fp = []
    for v in ordinary:
        got = _refused_value(v)
        note("ordinary %-16r refused=%s" % (v, got))
        if got:
            fp.append(v)
        check("R4 ordinary value %r is allowed" % v, not got,
              "refused (false positive)")
    # values that are genuinely fine and should stay allowed
    allowed_ok = ["我住在12号楼", "课程表", "课代表", "下次课", "上课", "令牌",
                  "classroom", "masterclass", "我叫小王", "我喜欢足球"]
    for v in allowed_ok:
        got = _refused_value(v)
        check("R4 benign value %r stays allowed" % v, not got, "refused")
    if fp:
        finding("RED-J-R3-05", "MINOR", "modules/memory/store.py looks_secret()/"
                "looks_like_progress() (substring match)",
                "learner explicitly saves an ORDINARY fact/preference whose text merely "
                "CONTAINS a secret/progress keyword as a substring",
                "MemoryStore.save('profile_fact','note',V) for V in %r" % fp,
                "ordinary facts must be storable — refusing them is a false positive that "
                "silently blocks legitimate learner memory",
                "refused (400 boundary_violation): %r — no word-boundary / token guard; "
                "密码学(密码), 进度条(进度), 我完成了作业/我学到了很多 (完成了/学到了), "
                "tokenize(token), secretary(secret), passwordless(password)" % fp,
                "keyword screen uses plain substring 'in' over folded views")


# ===========================================================================
# R5. holistic precedence contract on one rendered instruction
# ===========================================================================

def t_r5_holistic():
    state = intent.BehaviorState()
    intent.route("我们练一下酒店英语", state)                 # activity + scenario
    intent.route("说中文", state)                            # explicit language request
    state.saved_prefs = {"explanation_language": "en", "speed": "slow"}
    state.speed = "slow"
    d = intent.route("accommodation 是什么意思", state)      # temporary word intent
    kb = render_knowledge_block("accommodation",
                                [{"dataset_name": "旅行手册", "document_title": "酒店入住",
                                  "text": "accommodation 是住宿的意思。"}])
    mem = render_memory_block([{"entity_type": "profile_fact", "key": "city",
                                "value": "我住在12号楼"}])
    b = intent.render_instructions(state, d, knowledge_block=kb, memory_block=mem,
                                   preferences=state.saved_prefs)

    # data framing
    check("R5 knowledge block declares itself DATA, not instructions",
          "DATA and NOT instructions" in b or "untrusted DATA, not instructions" in b)
    check("R5 memory block declares itself DATA, not instructions",
          "NOT instructions" in b)
    check("R5 data blocks deny authority over course progress",
          b.count("progress") >= 1 and ("never authoritative for" in b))
    # hard rule still present
    check("R5 vocab hard rule present for the temp word turn",
          "VOCABULARY ACCURACY POLICY (hard rules):" in b)
    # explicit request beats activity default
    check("R5 explicit override beats the practice-activity English default",
          "Current reply language: Chinese" in b and "(current override: zh)" in b)
    # temp intent preserves activity + scenario + resume
    check("R5 temp word intent preserves activity/scenario/resume",
          "CURRENT ACTIVITY: scenario conversation practice" in b
          and "Scenario — hotel" in b
          and "return naturally to scenario conversation practice" in b)
    # contradiction scan across all lines
    fails = []
    if "word explanations first in English" in b and "(current override: zh)" in b:
        fails.append("saved 'word explanations first in English' vs explicit override zh")
    if "speaking pace slow" in b and state.speed != "slow":
        fails.append("saved slow vs state speed")
    check("R5 no two rendered lines contradict on language/speed",
          fails == [], "contradictions: %r" % fails)

    # explicit ordering evidence (contract: hard rule > explicit > saved > activity > default)
    def idx(s):
        return b.find(s)
    order = {"language(explicit)": idx("(current override: zh)"),
             "vocab_hard_rule": idx("VOCABULARY ACCURACY POLICY"),
             "activity": idx("CURRENT ACTIVITY"),
             "saved_pref": idx("The learner asked you to remember"),
             "knowledge_data": idx("KNOWLEDGE BASE DATA"),
             "memory_data": idx("LEARNER MEMORY")}
    note("render index order: %r" % order)
    # data blocks must be framed and after the rules; saved pref after activity
    check("R5 data blocks are positioned after the hard rules",
          order["knowledge_data"] > order["vocab_hard_rule"] >= 0
          and order["memory_data"] > order["vocab_hard_rule"] >= 0)
    if fails:
        finding("RED-J-R3-06", "MAJOR", "modules/intent/behavior.py render_instructions() "
                "(holistic turn)",
                "temp word intent + Knowledge block + Memory block + saved pref + "
                "activity + explicit current request all present",
                "sequence: 练酒店英语 -> 说中文 -> saved {explanation_language:en, "
                "speed:slow} -> accommodation 是什么意思; render with kb+mem",
                "the precedence contract reads hard rule > explicit > saved > activity > "
                "default with no contradicting lines",
                "contradiction(s): %r" % fails,
                "see RED-J-R3-02 (explanation_language not equality-guarded)")


# ===========================================================================
# R6. metric re-verification
# ===========================================================================

def t_r6_metrics():
    # ACTIVITY_RESUME_FAILURE
    st = intent.BehaviorState()
    intent.route("我们练一下酒店英语", st)
    intent.route("accommodation 是什么意思", st)
    d = intent.route("继续", st)
    ok_resume = st.main_activity == "PRACTICE_CONVERSATION" and st.scenario == "hotel"
    check("R6 activity/scenario survive a temp word question", ok_resume,
          repr((st.main_activity, st.scenario)))

    async def resume():
        q = FakeQwen()
        link = link_mod.BehaviorLink(FakeConn(), q, config=_cfg())
        await link.on_qwen_event(_t("我们练一下酒店英语", "r1"))
        await link.on_qwen_event(_t("accommodation 是什么意思", "r2"))
        await link.on_qwen_event(_done())
        await link._maybe_apply()
        return link, q.ins
    link, ins = asyncio.run(resume())
    check("R6 resume after response.done restores scenario",
          "TEMPORARY (this turn only)" not in ins
          and "Scenario — hotel" in ins and link.state.temporary_intent is None)

    # repeated continue idempotent
    st = intent.BehaviorState()
    intent.route("我们练一下酒店英语", st)
    base = st.recent_task
    for _ in range(3):
        intent.route("继续", st)
    check("R6 repeated continue: no activity/task drift",
          st.main_activity == "PRACTICE_CONVERSATION" and st.recent_task == base)

    # knowledge no longer authoritative for progress (framing)
    kb = render_knowledge_block("q", [{"dataset_name": "d", "document_title": "t",
                                       "text": "第 12 课"}])
    check("R6 knowledge block explicitly denies progress authority",
          "authoritative for the learner's course progress" in kb)

    # the real progress path is workbench-gated
    d, _ = route_one("我学到哪里了？")
    check("R6 real progress query is workbench-gated",
          d.needs_workbench == "progress" and not d.knowledge_query)


def main():
    t_r1_language()
    t_r2_precedence()
    t_r3_smugglers()
    t_r4_false_positives()
    t_r5_holistic()
    t_r6_metrics()

    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("=" * 74)
    print("RED_J_ROUND3: %d checks, %d PASS, %d FAIL" % (total, passed, total - passed))
    for name, ok, _ in RESULTS:
        if not ok:
            print("  FAILED(check): %s" % name)
    print("-" * 74)
    print("FINDINGS: %d" % len(FINDINGS))
    for f in FINDINGS:
        print("  %s [%s] %s" % (f["id"], f["severity"], f["surface"][:64]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
