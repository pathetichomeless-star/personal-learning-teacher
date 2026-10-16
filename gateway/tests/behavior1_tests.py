"""BEHAVIOR-1 deterministic suite (≥60 scenarios) + renderer + link contracts.

Runs standalone:  python tests/behavior1_tests.py   (from gateway/, venv)
No network, no Qwen, no audio.  Covers: Chinese chat, English practice,
scenario practice, speaking/vocab/reading/listening, word/grammar/translation
intents, temporary-intent + resume, 再来一次 / 继续 / 慢一点 / 快一点 / 难一点 /
简单一点, activity switches, single English word inside Chinese, ambiguous
fallback, language override, memory side effects, workbench blocks, hot-apply
boundary discipline and read-back verification.
"""

import asyncio
import os
import sys
import tempfile
import types

import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_GATEWAY = os.path.dirname(_HERE)
_REPO = os.path.dirname(_GATEWAY)
for p in (_GATEWAY, _REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

from app import behavior as link_mod                             # noqa: E402
from modules.adapters import workbench as wb                     # noqa: E402
from modules.intent import behavior as intent                    # noqa: E402
from modules.memory.store import (BoundaryViolation, MemoryStore)  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % detail) if (detail and not cond) else ""))


def fresh(**kw):
    st = intent.BehaviorState()
    for k, v in kw.items():
        setattr(st, k, v)
    return st


def seq(utterances, state=None, **kw):
    """Route a sequence; return (last_decision, state)."""
    st = state or fresh(**kw)
    d = None
    for u in utterances:
        d = intent.route(u, st)
    return d, st


def route_one(u, **kw):
    return seq([u], **kw)


# ===========================================================================
# A. language policy (pure)
# ===========================================================================

def t_language():
    d, st = route_one("我们随便聊聊")
    check("A1 chat zh default", d.kind == "ACTIVITY" and d.activity == "CHAT"
          and d.effective_language == "zh", repr(d))

    d, st = route_one("今天天气不错，心情挺好的")
    check("A2 chinese input stays zh in CHAT", d.kind == "NONE"
          and d.effective_language == "zh")

    d, st = route_one("How are you today?")
    check("A3 english input mirrors en in CHAT", d.kind == "NONE"
          and d.effective_language == "en")

    d, st = seq(["我们练一下酒店英语", "We need a quiet room please"])
    check("A4 practice stays en", st.main_activity == "PRACTICE_CONVERSATION"
          and d.effective_language == "en")

    d, st = seq(["我们练一下酒店英语", "我们需要一间安静的房间"])
    check("A5 chinese inside practice keeps activity+en policy",
          d.kind == "NONE" and st.main_activity == "PRACTICE_CONVERSATION"
          and d.effective_language == "en")

    d, st = route_one("我今天状态不错，想聊聊 weekend 的事")
    check("A6 single english word does NOT switch language",
          d.effective_language == "zh" and st.main_activity == "CHAT")

    d, st = seq(["你可以说中文吗？", "那开始吧"])
    check("A7 explicit zh request wins and persists",
          st.language_override == "zh" and d.effective_language == "zh")

    d, st = seq(["说英语", "今天我们聊什么？"])
    check("A8 explicit en request wins over zh input",
          st.language_override == "en" and d.effective_language == "en")

    d, st = route_one("你为什么用英文回答")
    check("A9 english complaint switches to zh",
          d.kind == "COMMAND" and st.language_override == "zh"
          and "apologise" in d.note)

    d, st = route_one("Can we speak English?")
    check("A10 english request (english text) -> en",
          st.language_override == "en" and d.effective_language == "en")

    d, st = route_one("这个用英文怎么说")
    check("A11 translate is not a language override",
          d.temporary == "TRANSLATE" and st.language_override is None)

    d, st = route_one("用中文跟我解释一下")
    check("A12 zh override in any activity",
          st.language_override == "zh" and d.kind == "COMMAND")


# ===========================================================================
# B. activity routing (pure)
# ===========================================================================

def t_activities():
    d, st = route_one("我们练一下酒店英语")
    check("B1 hotel practice", d.activity == "PRACTICE_CONVERSATION"
          and st.scenario == "hotel" and d.effective_language == "en")

    d, st = route_one("我们练一下餐厅点餐的英语对话")
    check("B2 restaurant scenario", st.scenario == "restaurant")

    d, st = route_one("我想背几个单词")
    check("B3 vocab learn", d.activity == "VOCAB_LEARN" and d.effective_language == "zh")

    d, st = route_one("我今天想学 hotel 这个词")
    check("B4 vocab learn with word", d.activity == "VOCAB_LEARN"
          and st.recent_word == "hotel")

    d, st = route_one("复习一下单词吧")
    check("B5 vocab review", d.activity == "VOCAB_REVIEW")

    d, st = route_one("练练口语")
    check("B6 speaking practice en", d.activity == "SPEAKING_PRACTICE"
          and d.effective_language == "en")

    d, st = route_one("我们读一篇文章吧")
    check("B7 reading", d.activity == "READING")

    d, st = route_one("练听力")
    check("B8 listening", d.activity == "LISTENING")

    d, st = seq(["我想背几个单词", "别背单词了，聊会儿天"])
    check("B9 switch vocab->chat naturally", d.activity == "CHAT"
          and st.main_activity == "CHAT" and d.kind == "ACTIVITY")

    d, st = seq(["我们随便聊聊", "我想背几个单词"])
    check("B10 switch chat->vocab", st.main_activity == "VOCAB_LEARN")

    d, st = route_one("我想学英语歌")
    check("B11 no rigid mode for free-form wish", d.kind == "NONE"
          and st.main_activity == "CHAT")

    d, st = route_one("我们 practice hotel 英语吧")
    check("B12 mixed-language practice request",
          st.main_activity == "PRACTICE_CONVERSATION" and st.scenario == "hotel")


# ===========================================================================
# C. commands (pure)
# ===========================================================================

def t_commands():
    d, st = route_one("说慢一点", main_activity="PRACTICE_CONVERSATION")
    check("C1 slow keeps activity", d.kind == "COMMAND" and st.speed == "slow"
          and st.main_activity == "PRACTICE_CONVERSATION" and "slow" in d.note)

    d, st = route_one("speak slower please")
    check("C2 english slow", st.speed == "slow")

    d, st = route_one("快一点")
    check("C3 fast", st.speed == "fast")

    d, st = route_one("正常语速")
    check("C4 normal speed", st.speed == "normal")

    d, st = route_one("这个太简单了，难一点")
    check("C5 harder keeps activity", st.difficulty == "hard"
          and d.kind == "COMMAND" and "do not mention" in d.note)

    d, st = route_one("太难了")
    check("C6 too-hard -> easier", st.difficulty == "easy")

    d, st = route_one("简单一点")
    check("C7 easier", st.difficulty == "easy")

    d, st = route_one("再来一次")
    check("C8 repeat resolved", d.params.get("repeat") and "repeat" in d.note)

    d, st = route_one("再说一遍")
    check("C9 repeat variant", d.params.get("repeat"))

    d, st = route_one("one more time")
    check("C10 repeat english", d.params.get("repeat"))

    d, st = route_one("继续")
    check("C11 continue", d.params.get("continue")
          and d.kind == "COMMAND")

    d, st = route_one("然后呢")
    check("C12 continue variant", d.params.get("continue"))

    d, st = seq(["我想背几个单词", "说慢一点"])
    check("C13 speed command does not exit activity",
          st.main_activity == "VOCAB_LEARN" and st.speed == "slow")

    d, st = seq(["我想背几个单词", "这个太简单了，难一点"])
    check("C14 difficulty keeps activity", st.main_activity == "VOCAB_LEARN"
          and st.difficulty == "hard")


# ===========================================================================
# D. temporary intents + resume (pure/render)
# ===========================================================================

def t_temporary():
    d, st = seq(["我们练一下酒店英语", "accommodation 是什么意思？"])
    check("D1 explain word in scenario", d.kind == "TEMP"
          and d.temporary == "EXPLAIN_WORD" and d.params["word"] == "accommodation"
          and st.recent_word == "accommodation")

    check("D2 explanation language zh", d.effective_language == "zh")

    check("D3 note has chinese-first + pronunciation + example",
          "FIRST its Chinese meaning" in d.note and "pronunciation" in d.note
          and "English example" in d.note)

    check("D4 note returns to main activity",
          "return naturally to scenario conversation practice" in d.note
          and st.main_activity == "PRACTICE_CONVERSATION")

    d, st = route_one("hotel 是什么意思")
    check("D5 explain word in chat", d.temporary == "EXPLAIN_WORD"
          and d.params["word"] == "hotel" and d.effective_language == "zh")

    d, st = route_one("我不懂这个单词")
    check("D6 unexplained word asks", d.temporary == "EXPLAIN_WORD"
          and d.params["word"] is None and "Ask ONE short question" in d.note)

    d, st = seq(["hotel 是什么意思", "这个词怎么读"])
    check("D7 recent word reuse", d.temporary == "EXPLAIN_WORD"
          and d.params["word"] == "hotel")

    d, st = route_one("翻译一下这句话")
    check("D8 translate", d.temporary == "TRANSLATE"
          and st.recent_sentence is not None)

    d, st = route_one("这句话为什么用现在完成时？")
    check("D9 grammar", d.temporary == "EXPLAIN_GRAMMAR"
          and "briefly in Chinese" in d.note)

    d, st = route_one("语法讲讲")
    check("D10 grammar variant", d.temporary == "EXPLAIN_GRAMMAR")

    # resume semantics at the renderer level
    d, st = seq(["我们练一下酒店英语", "accommodation 是什么意思？"])
    block = intent.render_instructions(st, d)
    check("D11 render carries temp + resume", "TEMPORARY (this turn only)" in block
          and "accommodation" in block)
    st.temporary_intent = None          # emulates the link's response.done clear
    block2 = intent.render_instructions(st, intent.Decision())
    check("D12 render resumes main activity after temp",
          "TEMPORARY (this turn only)" not in block2
          and "scenario conversation practice" in block2)


# ===========================================================================
# E. workbench intents (pure + render)
# ===========================================================================

def t_workbench():
    d, st = route_one("继续上次的课")
    check("E1 continue lesson", d.needs_workbench == "continue_lesson"
          and st.main_activity == "CONTINUE_LESSON")

    d, st = route_one("我们继续上课吧")
    check("E2 continue lesson variant", d.needs_workbench == "continue_lesson")

    d, st = route_one("我学到哪里了？")
    check("E3 progress query", d.temporary == "QUERY_PROGRESS"
          and d.needs_workbench == "progress")

    d, st = route_one("我的进度怎么样")
    check("E4 progress variant", d.needs_workbench == "progress")

    d, st = route_one("这个需要复习吗？")
    check("E5 review query", d.needs_workbench == "review"
          and d.temporary == "QUERY_PROGRESS")

    d, st = route_one("哪些需要复习")
    check("E6 review variant", d.needs_workbench == "review")

    ok = wb.Result(ok=True, data={"lesson_id": 12, "title": "一般过去时（规则动词 -ed）",
                                  "objectives": ["用 -ed 说过去做过的事。"]},
                   provenance=wb.Provenance(rev=77, age_s=5, fresh=True))
    block = intent.render_workbench_block(ok, kind="continue_lesson")
    check("E7 workbench block authoritative + real lesson",
          "authoritative" in block and "12" in block and "一般过去时" in block)

    deg = intent.render_workbench_block(None, kind="progress")
    check("E8 degrade line never invents",
          "UNAVAILABLE" in deg and "temporarily unavailable" in deg)

    stale = wb.Result(ok=True, data={"lesson_id": 12, "passed": 0,
                                     "review_required": 1, "due_count": 3,
                                     "next_due": "2026-10-05", "due_words": ["walked"]},
                      provenance=wb.Provenance(rev=77, age_s=200, stale=True))
    block = intent.render_workbench_block(stale, kind="progress")
    check("E9 stale labelled", "minute(s) old" in block and "due: 3" in block)


# ===========================================================================
# F. preferences + memory side effects (pure + store)
# ===========================================================================

def t_preferences():
    d, st = route_one("以后解释单词先用中文，记住。")
    check("F1 save explanation language", d.memory == {
        "op": "save", "key": "explanation_language", "value": "zh"}
        and st.saved_prefs.get("explanation_language") == "zh")

    d, st = route_one("以后说慢一点，记住")
    check("F2 save speed", d.memory.get("key") == "speed" and st.speed == "slow")

    d, st = route_one("以后难一点，记住")
    check("F3 save difficulty", d.memory.get("key") == "difficulty"
          and st.difficulty == "hard")

    d, st = route_one("忘掉这个偏好。")
    check("F4 forget", d.memory == {"op": "forget"})

    d, st = route_one("记住")
    check("F5 bare 记住 is not a preference", d.memory is None)

    # explanation language preference drives EXPLAIN_WORD rendering
    d, st = route_one("hotel 是什么意思",
                      saved_prefs={"explanation_language": "en"})
    check("F6 saved explanation language applies", d.effective_language == "en")

    d, st = route_one("hotel 是什么意思",
                      saved_prefs={"explanation_language": "zh"})
    check("F7 saved zh explanation default", d.effective_language == "zh")

    # store roundtrip + boundary
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "memory.json")
        ms = MemoryStore(path).load()
        ms.save_preference("explanation_language", "zh")
        ms.save_preference("speed", "slow")
        ms2 = MemoryStore(path).load()
        check("F8 store roundtrip", ms2.preferences() == {
            "explanation_language": "zh", "speed": "slow"})
        removed = ms2.forget()
        check("F9 forget most recent removes speed", removed == ["speed"]
              and ms2.preferences() == {"explanation_language": "zh"})
        try:
            ms2.save_preference("lesson_progress", "x")
            check("F10 boundary rejects progress key", False, "no error raised")
        except BoundaryViolation:
            check("F10 boundary rejects progress key", True)
        for bad in ("mastery:abc", "next_review", "course_state", "PASS"):
            try:
                ms2.save_preference(bad, "1")
                check("F11 boundary rejects %r" % bad, False, "no error")
            except BoundaryViolation:
                check("F11 boundary rejects %r" % bad, True)
        try:
            ms2.save_preference("speed", "warp")
            check("F12 closed enum rejected", False, "no error")
        except BoundaryViolation:
            check("F12 closed enum rejected", True)
        ms2.note_weak_word("accommodation")
        check("F13 weak word stored", ms2.vocab_items().get("accommodation"))
        check("F14 no progress keys assertion", ms2.assert_no_progress_keys() == [])
        raw = open(path, encoding="utf-8").read()
        check("F15 no transcripts in memory file",
              "transcript" not in raw and "我不懂" not in raw)


# ===========================================================================
# G. ambiguity / fallback / edge (pure)
# ===========================================================================

def t_edges():
    d, st = route_one("帮我练一下")
    check("G1 ambiguous -> clarify", d.clarify and "ambiguous" in d.note
          and st.main_activity == "CHAT")

    d, st = route_one("练一下")
    check("G2 bare practice -> clarify", d.clarify)

    d, st = route_one("嗯")
    check("G3 acknowledgement keeps state", d.kind == "NONE" and not d.clarify)

    d, st = route_one("123")
    check("G4 non-linguistic ignored", d.kind == "NONE")

    d, st = route_one("")
    check("G5 empty ignored", d.kind == "NONE")

    d, st = route_one("Can you help me practice?")
    check("G6 english ambiguous -> no mode change", d.kind == "NONE"
          and st.main_activity == "CHAT")
    check("G6b english effective language", d.effective_language == "en")

    d, st = seq(["我们练一下酒店英语", "帮我练一下"])
    check("G7 clarify stays inside activity",
          st.main_activity == "PRACTICE_CONVERSATION")

    long_text = "我们今天" + "很" * 500 + "开心"
    d, st = route_one(long_text)
    check("G8 long text handled", d.kind in ("NONE", "COMMAND", "ACTIVITY"))


# ===========================================================================
# H. renderer + link contracts (async)
# ===========================================================================

class FakeQwen:
    def __init__(self):
        self.ins = "BASE"
        self.updates = []

    @property
    def instructions(self):
        return self.ins

    def set_instructions(self, t):
        self.ins = t

    async def send_instructions_update(self, t):
        self.ins = t
        self.updates.append(t)
        return True


class FakeConn:
    def __init__(self):
        self.safe = True

    def is_safe_boundary(self):
        return self.safe


class FakeWorkbench:
    def __init__(self, res):
        self.res = res
        self.refreshes = 0
        self.closed = 0

    async def continue_lesson(self, **kw):
        return self.res

    async def query_progress(self, scope=None, **kw):
        return self.res

    async def refresh(self):
        self.refreshes += 1
        return True

    async def close(self):
        self.closed += 1


def _cfg(memory_file="", wb_url=""):
    return types.SimpleNamespace(MEMORY_FILE=memory_file,
                                 WORKBENCH_BASE_URL=wb_url)


def _transcript(text, item="i-%d"):
    return {"type": "conversation.item.input_audio_transcription.completed",
            "transcript": text, "item_id": item}


def t_link():
    async def main():
        # H1: initial instructions carry policy + no-labels directive
        q = FakeQwen()
        link = link_mod.BehaviorLink(FakeConn(), q, config=_cfg())
        check("H1 initial instructions rendered",
              "LANGUAGE POLICY" in q.ins and "NEVER mention" in q.ins
              and "小智" in q.ins)
        check("H1b initial activity chat", "free chat" in q.ins)

        # H2: hot-apply at safe boundary
        await link.on_qwen_event(_transcript("我们练一下酒店英语", "i1"))
        check("H2 hot-apply immediate", link.stats["hot_applies"] == 1
              and "scenario conversation practice" in q.ins
              and "hotel" in q.ins)

        # H3: deferral when unsafe, applied on boundary
        conn = FakeConn()
        conn.safe = False
        q3 = FakeQwen()
        link3 = link_mod.BehaviorLink(conn, q3, config=_cfg())
        await link3.on_qwen_event(_transcript("说慢一点", "j1"))
        check("H3a deferred when unsafe", link3.stats["boundary_deferrals"] >= 1
              and link3._pending and "SLOW" not in q3.ins)
        conn.safe = True
        await link3._maybe_apply()
        check("H3b applied at boundary", link3.stats["hot_applies"] >= 1
              and "SLOW" in q3.ins and not link3._pending)
        await link3.close()

        # H4: temporary intent + automatic resume
        q4 = FakeQwen()
        link4 = link_mod.BehaviorLink(FakeConn(), q4, config=_cfg())
        await link4.on_qwen_event(_transcript("我们练一下酒店英语", "k1"))
        await link4.on_qwen_event(_transcript("accommodation 是什么意思？", "k2"))
        check("H4a temp instruction applied",
              "TEMPORARY (this turn only)" in q4.ins
              and "accommodation" in q4.ins)
        await link4.on_qwen_event({"type": "response.done",
                                   "response": {"status": "completed"}})
        await link4._maybe_apply()
        check("H4b resume after response done",
              "TEMPORARY (this turn only)" not in q4.ins
              and "scenario conversation practice" in q4.ins
              and link4.state.temporary_intent is None)
        await link4.close()

        # H5/H6: memory save → new session applies; forget removes
        with tempfile.TemporaryDirectory() as td:
            mpath = os.path.join(td, "memory.json")
            q5 = FakeQwen()
            link5 = link_mod.BehaviorLink(FakeConn(), q5,
                                          config=_cfg(memory_file=mpath))
            await link5.on_qwen_event(_transcript("以后解释单词先用中文，记住。", "m1"))
            check("H5a save counted", link5.stats["pref_saves"] == 1)
            qn = FakeQwen()
            linkn = link_mod.BehaviorLink(FakeConn(), qn,
                                          config=_cfg(memory_file=mpath))
            check("H5b new session applies preference",
                  "word explanations first in 中文" in qn.ins)
            await linkn.on_qwen_event(_transcript("忘掉这个偏好。", "m2"))
            check("H6 forget removes", linkn.stats["pref_forgets"] == 1
                  and MemoryStore(mpath).load().preferences() == {})
            await link5.close()
            await linkn.close()

        # H7/H8: workbench block (ok / unavailable)
        res_ok = wb.Result(ok=True, data={"lesson_id": 12, "title": "U12",
                                          "objectives": ["obj1"]},
                           provenance=wb.Provenance(rev=77, age_s=3, fresh=True))
        q7 = FakeQwen()
        link7 = link_mod.BehaviorLink(FakeConn(), q7, config=_cfg())
        link7.workbench = FakeWorkbench(res_ok)
        await link7.on_qwen_event(_transcript("继续上次的课", "n1"))
        check("H7 workbench data in instruction",
              "authoritative" in q7.ins and "12" in q7.ins)
        await link7.on_qwen_event(_transcript("我学到哪里了？", "n2"))
        check("H7b progress answered", link7.stats["workbench_answers"] == 2)
        link7.workbench.res = wb.Result(ok=False, reason="sync_down")
        await link7.on_qwen_event(_transcript("这个需要复习吗？", "n3"))
        check("H8 degrade honest", "UNAVAILABLE" in q7.ins
              and link7.stats["workbench_unavailable"] == 1)
        # prefetch on speech started
        link7.on_speech_started()
        await asyncio.sleep(0.05)
        check("H8b prefetch fired", link7.workbench.refreshes == 1)
        await link7.close()
        check("H8c workbench closed", link7.workbench.closed == 1)

        # H9: read-back mismatch detection
        q9 = FakeQwen()
        link9 = link_mod.BehaviorLink(FakeConn(), q9, config=_cfg())
        await link9.on_qwen_event(_transcript("说慢一点", "o1"))
        await link9.on_qwen_event({"type": "session.updated",
                                   "session": {"instructions": "something else"}})
        check("H9 read-back mismatch flagged",
              link9.stats["readback_mismatches"] == 1)
        await link9.on_qwen_event({"type": "session.updated",
                                   "session": {"instructions": q9.ins}})
        check("H9b matching read-back clear",
              link9.stats["readback_mismatches"] == 1)
        await link9.close()

        # H10: duplicate item_id processed once
        q10 = FakeQwen()
        link10 = link_mod.BehaviorLink(FakeConn(), q10, config=_cfg())
        await link10.on_qwen_event(_transcript("我想背几个单词", "p1"))
        await link10.on_qwen_event(_transcript("我想背几个单词", "p1"))
        check("H10 duplicate item deduped", link10.stats["decisions"] == 1)
        await link10.close()

        # H11: identical render skipped
        q11 = FakeQwen()
        link11 = link_mod.BehaviorLink(FakeConn(), q11, config=_cfg())
        await link11.on_qwen_event(_transcript("说慢一点", "q1"))
        await link11.on_qwen_event(_transcript("说慢一点", "q2"))
        check("H11 identical re-render skipped",
              link11.stats["hot_applies"] == 1
              and link11.stats["hot_apply_skips_identical"] == 1)
        await link11.close()

        # H12: weak-word observation on explicit unknown
        with tempfile.TemporaryDirectory() as td:
            mpath = os.path.join(td, "memory.json")
            q12 = FakeQwen()
            link12 = link_mod.BehaviorLink(FakeConn(), q12,
                                           config=_cfg(memory_file=mpath))
            await link12.on_qwen_event(_transcript("我不认识 accommodation 这个词", "r1"))
            check("H12 weak word observed",
                  MemoryStore(mpath).load().vocab_items().get("accommodation"))
            await link12.close()

        # H13: english-only hot-apply payload discipline (static)
        src = open(os.path.join(_GATEWAY, "app", "qwen.py"), encoding="utf-8").read()
        m = re.search(r"async def send_instructions_update.*?_session_update_msg",
                      src, re.S)
        payload = m.group(0) if m else ""
        check("H13 hot-apply payload is instructions-only",
              '"session": {"instructions": self._instructions}' in payload)
        check("H13b no voice in hot-apply", '"voice"' not in payload)

        # H14: workbench adapter has no write path (static)
        wsrc = open(os.path.join(_REPO, "modules", "adapters", "workbench.py"),
                    encoding="utf-8").read()
        check("H14 adapter is GET-only",
              '"PUT"' not in wsrc and ".put(" not in wsrc
              and ".post(" not in wsrc and "sync/state" in wsrc)

        # H15: mirror-language survives into the hot-apply render
        q15 = FakeQwen()
        link15 = link_mod.BehaviorLink(FakeConn(), q15, config=_cfg())
        base_ins = q15.ins
        await link15.on_qwen_event(_transcript(
            "Can you tell me what you can do?", "s1"))
        check("H15 english chat hot-applies English policy",
              "Current reply language: English" in q15.ins
              and q15.ins != base_ins)
        await link15.on_qwen_event(_transcript("我们聊聊今天发生的事情", "s2"))
        check("H15b chinese turn flips the policy back",
              "Current reply language: Chinese" in q15.ins)
        await link15.close()

    asyncio.run(main())


def main():
    t_language()
    t_activities()
    t_commands()
    t_temporary()
    t_workbench()
    t_preferences()
    t_edges()
    t_link()
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("=" * 70)
    print("BEHAVIOR1_TESTS: %d checks, %d PASS, %d FAIL" %
          (total, passed, total - passed))
    for name, ok, detail in RESULTS:
        if not ok:
            print("  FAILED: %s %s" % (name, detail))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())