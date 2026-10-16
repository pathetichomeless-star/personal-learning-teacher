"""VOCAB_ACCURACY_TESTS — vocabulary teaching policy + routing (deterministic).

Machine-first audit suite (no model calls — a mock cannot prove Qwen factual
accuracy; that is what the single real-session matrix is for):

* Chinese→English vocabulary requests route to vocabulary/translation teaching
  (all natural variants in the audit matrix);
* the rendered instruction carries the VOCABULARY ACCURACY POLICY (canonical
  spelling first; never invent a spelling from sound; pronunciation separate
  from spelling; 怎么拼 = letter-by-letter; no guessing; context for multiple
  translations; learner's spelling preserved);
* English→Chinese explanation keeps the learner's spelling;
* one English word inside Chinese does not flip the session language;
* a temporary vocabulary explanation resumes the previous activity;
* pseudo-spelling FIXTURES (strit/shep/hotal/acommodation) are rejected by the
  test-side validator below — a regression fixture check, NOT a runtime
  blacklist (the product never uses this validator).

Runs standalone:  python tests/vocab_accuracy_tests.py   (from gateway/, venv)
"""

import asyncio
import os
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
_GATEWAY = os.path.dirname(_HERE)
_REPO = os.path.dirname(_GATEWAY)
for p in (_GATEWAY, _REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

from app import behavior as link_mod                              # noqa: E402
from modules.intent import behavior as intent                     # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % detail) if (detail and not cond) else ""))


def route_one(text, state=None, **kw):
    st = state or intent.BehaviorState(**kw)
    d = intent.route(text, st)
    block = intent.render_instructions(st, d)
    return d, st, block


POLICY = "VOCABULARY ACCURACY POLICY"


# ---------------------------------------------------------------------------
# A. Chinese → English vocabulary requests (matrix: nouns / verbs / travel /
#    pronunciation-confusable / natural variants)
# ---------------------------------------------------------------------------

CN_EN = [
    ("A1 street", "街道用英语怎么说？"),
    ("A2 hotel", "酒店用英语怎么说"),
    ("A3 room", "房间怎么说"),
    ("A4 table", "桌子用英语怎么说？"),
    ("A5 window", "窗户用英语怎么说"),
    ("A6 airport", "机场用英语怎么说？"),
    ("A7 leave", "离开用英语怎么说"),
    ("A8 live", "居住用英语怎么说"),
    ("A9 arrive", "到达用英语怎么说"),
    ("A10 book/reserve", "预订用英语怎么说"),
    ("A11 ship", "船用英语怎么说"),
    ("A12 sheep", "羊用英语怎么说"),
    ("A13 accommodation", "住宿用英语怎么说"),
    ("A14 front desk", "前台用英语怎么说"),
    ("A15 luggage", "行李用英语怎么说"),
    ("A16 variant 是什么", "街道是什么？"),
    ("A17 variant 英文里…怎么说", "英文里的街道怎么说？"),
    ("A18 variant 的英文是什么", "街道的英文是什么？"),
    ("A19 variant bare 怎么说", "房间怎么说"),
    ("A20 context sentence", "在酒店预订房间用英语怎么说？"),
]


def t_cn_en():
    for name, text in CN_EN:
        d, st, block = route_one(text)
        check("A %s routes to teaching" % name,
              d.kind == "TEMP" and d.temporary in ("TRANSLATE", "EXPLAIN_WORD"),
              repr((d.kind, d.temporary)))
        check("A %s carries vocab policy" % name, POLICY in block)

    # deictic subjects stay ordinary conversation
    for wrong in ("这是什么？", "他叫什么？", "我为啥不能去？"):
        d, _, block = route_one(wrong)
        check("A negative %r stays chat" % wrong,
              d.kind == "NONE" and POLICY not in block, repr(d.kind))

    # definition-shaped vocabulary questions get the explicit vocabulary-first note
    # (real session m19: the model answered with a Chinese definition otherwise)
    d, st, block = route_one("街道是什么？")
    check("A21 definition-shaped question carries the vocabulary-first note",
          d.temporary == "TRANSLATE"
          and d.params.get("word_zh") == "街道"
          and "ENGLISH WORD for「街道」" in d.note
          and "Do NOT answer with only a Chinese definition" in d.note,
          repr(d.note)[:160])
    d2, _, _ = route_one("酒店是什么？")
    check("A21b other subjects covered", d2.params.get("word_zh") == "酒店")


# ---------------------------------------------------------------------------
# B. spelling requests (怎么拼)
# ---------------------------------------------------------------------------

def t_spelling():
    for name, text, word in (("B1 street", "street 怎么拼？", "street"),
                             ("B2 hotel", "hotel 怎么拼？", "hotel"),
                             ("B3 accommodation", "accommodation 怎么拼？",
                              "accommodation")):
        d, st, block = route_one(text)
        check("B %s spelling routes to EXPLAIN_WORD" % name,
              d.temporary == "EXPLAIN_WORD" and d.params.get("word") == word
              and d.params.get("spelling") is True, repr(d.params))
        check("B %s spelling note is letter-by-letter" % name,
              "letter by letter" in d.note and POLICY in block)

    d, st, block = route_one("街道怎么拼？")
    check("B4 chinese-only spelling routes to TRANSLATE+spelling",
          d.temporary == "TRANSLATE" and d.params.get("spelling") is True,
          repr(d.params))
    check("B4b chinese-only spelling note letter-by-letter",
          "letter by letter" in d.note)


# ---------------------------------------------------------------------------
# C. English → Chinese explanation keeps the learner's spelling
# ---------------------------------------------------------------------------

def t_en_cn():
    for name, text, word in (("C1 street", "street 是什么意思？", "street"),
                             ("C2 accommodation", "accommodation 是什么意思？",
                              "accommodation")):
        d, st, block = route_one(text)
        check("C %s routes to EXPLAIN_WORD with preserved word" % name,
              d.temporary == "EXPLAIN_WORD" and d.params.get("word") == word
              and POLICY in block, repr(d.params))
    d, _, block = route_one("hotel 是什么意思？")
    check("C3 policy preserves the learner's spelling",
          "keep their spelling exactly as written" in block)


# ---------------------------------------------------------------------------
# D. context-sensitive translations
# ---------------------------------------------------------------------------

def t_context():
    d, _, block = route_one("预订用英语怎么说")
    check("D1 multiple valid translations -> context rule present",
          "several translations are valid" in block
          and "explain the difference" in block)
    d, _, block = route_one("前台用英语怎么说")
    check("D2 front desk variant covered by policy", POLICY in block)
    d, _, block = route_one("在酒店预订房间用英语怎么说？")
    check("D3 sentence context still routes to teaching",
          d.temporary == "TRANSLATE" and POLICY in block)


# ---------------------------------------------------------------------------
# E. policy structure (the required rules, verbatim coverage)
# ---------------------------------------------------------------------------

def t_policy():
    _, _, block = route_one("街道用英语怎么说？")
    checks = [
        ("E1 canonical spelling FIRST", "canonical English spelling FIRST" in block),
        ("E2 never invent from sound", "Never invent an English-looking spelling" in block),
        ("E3 pronunciation separate from spelling",
         "pronunciation stays SEPARATE from the spelling" in block),
        ("E4 spelling requests letter-by-letter, never pronunciation",
         "spell it letter by letter using ONLY English letter names" in block
         and "never spell its pronunciation" in block
         and "T O U C H" in block
         and "T-O-U-C-H" not in block and "T–O–U–C–H" not in block),
        ("E5 no guessing when unsure", "say so instead of guessing" in block),
        ("E6 context instead of fabricated single answer",
         "instead of inventing a single answer" in block),
    ]
    for name, cond in checks:
        check("E %s" % name, cond)


# ---------------------------------------------------------------------------
# F. pseudo-spelling fixtures (TEST-SIDE validator; not a runtime blacklist)
# ---------------------------------------------------------------------------

_CANONICAL = {
    "street", "hotel", "room", "table", "window", "airport", "leave", "live",
    "arrive", "book", "reserve", "booking", "reservation", "ship", "sheep",
    "accommodation", "lodging", "reception", "desk", "luggage", "baggage",
}
_WORDS_OK = _CANONICAL | {
    "the", "is", "are", "a", "an", "of", "and", "or", "to", "in", "on", "at",
    "very", "busy", "today", "you", "your", "it", "this", "that", "means",
    "front", "say", "in", "english", "chinese", "we", "can", "stay", "here",
}


def _edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def looks_like_pseudo_spelling(token):
    """Test-side fixture validator: near-miss of a canonical word (edit distance
    ≤2, same first letter) that is not itself a known word."""
    tok = token.lower()
    if tok in _WORDS_OK:
        return False
    for canon in _CANONICAL:
        if tok[0] == canon[0] and 3 <= len(tok) and _edit_distance(tok, canon) <= 2:
            return True
    return None


def t_fixtures():
    for bad in ("strit", "shep", "hotal", "acommodation"):
        check("F fixture %r flagged as pseudo-spelling" % bad,
              looks_like_pseudo_spelling(bad) is True)
    for good in ("street", "ship", "sheep", "hotel", "accommodation", "busy"):
        check("F canonical/normal %r accepted" % good,
              looks_like_pseudo_spelling(good) is False)


# ---------------------------------------------------------------------------
# G. link-level: resume, language stability, policy reaches Qwen
# ---------------------------------------------------------------------------

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
    def is_safe_boundary(self):
        return True


def _transcript(text, item):
    return {"type": "conversation.item.input_audio_transcription.completed",
            "transcript": text, "item_id": item}


def t_link():
    async def main():
        cfg = types.SimpleNamespace(MEMORY_FILE="", WORKBENCH_BASE_URL="")

        # G1: vocabulary explanation resumes the previous activity
        q = FakeQwen()
        link = link_mod.BehaviorLink(FakeConn(), q, config=cfg)
        await link.on_qwen_event(_transcript("我们练一下酒店英语", "v1"))
        await link.on_qwen_event(_transcript("accommodation 是什么意思？", "v2"))
        check("G1 vocab temp applied with policy",
              "TEMPORARY (this turn only)" in q.ins and POLICY in q.ins
              and "accommodation" in q.ins)
        await link.on_qwen_event({"type": "response.done",
                                  "response": {"status": "completed"}})
        await link._maybe_apply()
        check("G1b resumed to hotel practice without policy noise",
              "TEMPORARY (this turn only)" not in q.ins
              and "scenario conversation practice" in q.ins
              and POLICY not in q.ins)
        await link.close()

        # G2: one English word inside Chinese does not flip the language
        q2 = FakeQwen()
        link2 = link_mod.BehaviorLink(FakeConn(), q2, config=cfg)
        await link2.on_qwen_event(_transcript("我今天想学 hotel 这个词", "w1"))
        check("G2 single english word keeps zh",
              "Current reply language: Chinese" in q2.ins)
        await link2.close()

        # G3: spelling turn reaches Qwen with the letter-by-letter policy
        q3 = FakeQwen()
        link3 = link_mod.BehaviorLink(FakeConn(), q3, config=cfg)
        await link3.on_qwen_event(_transcript("hotel 怎么拼？", "x1"))
        check("G3 spelling instruction hot-applied",
              "letter by letter" in q3.ins and POLICY in q3.ins)
        await link3.close()

    asyncio.run(main())


def main():
    t_cn_en()
    t_spelling()
    t_en_cn()
    t_context()
    t_policy()
    t_fixtures()
    t_link()
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("=" * 70)
    print("VOCAB_ACCURACY_TESTS: %d checks, %d PASS, %d FAIL" %
          (total, passed, total - passed))
    for name, ok, detail in RESULTS:
        if not ok:
            print("  FAILED: %s %s" % (name, detail))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())