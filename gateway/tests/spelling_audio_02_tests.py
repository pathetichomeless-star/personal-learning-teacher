"""SPELLING-AUDIO-02 — spelling intent coverage + always-on audio-safe rule.

Fixes the two confirmed injection gaps:
  A. natural letter-spelling phrasings (拼读/拼一下/一个字母一个字母/逐个字母/
     letter by letter/spell it out) now trigger the spelling intent (the Latin-
     word requirement keeps ordinary sentences from false-triggering);
  B. the audio-safe letter-spelling rule is ALWAYS rendered in the teaching
     lines (CHAT included) — the vocab policy block stays per-turn only;
  C. the stored (v19-style) policy upgrades through the sanctioned
     PolicyStore.apply path and persists across store instances.

Run:
    cd <project-root>/gateway
    .venv/bin/python tests/spelling_audio_02_tests.py
"""

import json
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_GATEWAY = _HERE.parent
_REPO = _GATEWAY.parent
for _p in (str(_GATEWAY), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from modules.intent import behavior as intent                   # noqa: E402
from modules.policy import persona as persona_mod               # noqa: E402
from modules.policy.persona import (DEFAULT_POLICY,             # noqa: E402
                                    PolicyStore, diff_keys,
                                    render_vocab_policy,
                                    render_teaching_lines,
                                    validate_policy)

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        (" - " + str(detail)) if (detail and not cond) else ""))
    return bool(cond)


RULE_MARKS = ("say only the English letter names",
              "(touch → T O U C H)",
              "Never insert or pronounce hyphens, dashes, or separator names")
FORBIDDEN_FORMATS = ("T-O-U-C-H", "T–O–U–C–H")


def chat_block(state=None):
    st = state or intent.BehaviorState()
    d = intent.route("今天我们随便聊聊", st)
    return intent.render_instructions(st, d)


def spelling_block(text):
    st = intent.BehaviorState()
    d = intent.route(text, st)
    block = intent.render_instructions(st, d)
    return d, block


# ---------------------------------------------------------------------------
# FIX B — always-on audio-safe rule in the teaching lines
# ---------------------------------------------------------------------------

def fix_b_cases():
    print("\n==== FIX B — always-on rule in rendered instructions ====")
    block = chat_block()
    for mark in RULE_MARKS:
        check("B rule mark present in CHAT: %s…" % mark[:40], mark in block,
              block[:220])
    check("B2 no connector-joined spelling format anywhere",
          all(f not in block for f in FORBIDDEN_FORMATS), BLOCK_SCAN(block))
    # ordinary reading instructions unchanged
    check("B3 ordinary reading instructions unchanged",
          "Corrections: at most one important mistake per turn" in block, block[:200])

    # mission cases 2/3 — VOCAB_LEARN / VOCAB_REVIEW keep the rule
    for act in ("VOCAB_LEARN", "VOCAB_REVIEW"):
        st = intent.BehaviorState()
        st.main_activity = act
        d = intent.Decision()
        blk = intent.render_instructions(st, d)
        check("B4 %s keeps the audio-safe rule" % act,
              "say only the English letter names" in blk, blk[:200])
    # mission case 1 — CHAT (the previously uncovered mode)
    check("B5 CHAT keeps the audio-safe rule (was the gap)",
          "say only the English letter names" in chat_block(), "chat block")

    # mission cases 10-12 — the format is generic (word-agnostic) and the
    # touch example anchors it; per-word output verified by human retest
    blk = render_vocab_policy(DEFAULT_POLICY)
    check("B6 vocab policy block keeps the audio-safe rule (v19 rule intact)",
          "letter by letter using ONLY English letter names" in blk
          and "(touch → T O U C H)" in blk, blk[:200])


def BLOCK_SCAN(block):
    return [f for f in FORBIDDEN_FORMATS if f in block] or "none"


# ---------------------------------------------------------------------------
# FIX A — natural phrasings trigger the spelling intent
# ---------------------------------------------------------------------------

def fix_a_cases():
    print("\n==== FIX A — spelling intent coverage ====")
    cases = [("拼读 touch", "touch"),                  # mission case 4
             ("怎么拼 touch", "touch"),                 # mission case 5 (compat)
             ("spell touch", "touch"),                  # mission case 6 (compat)
             ("touch letter by letter", "touch"),       # mission case 7
             ("拼读 thought", "thought"),                # mission case 11
             ("thought 怎么拼", "thought"),
             ("拼读 through", "through"),                # mission case 12
             ("please spell it out: through", "through"),
             ("一个字母一个字母拼 touch", "touch"),
             ("逐个字母拼读 thought", "thought")]
    for text, word in cases:
        st = intent.BehaviorState()
        d = intent.route(text, st)
        fired = (d.params.get("spelling") is True
                 and (d.temporary in (intent.EXPLAIN_WORD, intent.TRANSLATE)))
        named = (d.note and word in (d.note or "")) or d.params.get("word") == word \
            or d.params.get("word_zh") == word
        blk = intent.render_instructions(st, d)
        check("A spelling intent fires: %r" % text,
              fired and (word in blk or named), (d.temporary, d.params, d.note))

    # mission cases 8/9 — no false triggers on ordinary / negative sentences
    for text in ("今天天气不错我们出去走走吧",
                 "我们练一下酒店英语",
                 "这个拼读很难吗",                        # 拼读 without a word
                 "老师讲一下拼读的方法"):                   # 拼读 without a word
        st = intent.BehaviorState()
        d = intent.route(text, st)
        check("A-nf no false spelling trigger: %r" % text,
              d.params.get("spelling") is not True, (d.kind, d.params))


# ---------------------------------------------------------------------------
# FIX C — stored-policy upgrade + persistence (the staged-sidecar mechanism)
# ---------------------------------------------------------------------------

def fix_c_cases(tmpdir):
    print("\n==== FIX C — stored policy upgrade (PolicyStore.apply) ====")
    path = str(Path(tmpdir) / "policy.json")
    store = PolicyStore(path).load()

    # seed a v19-style stored policy: OLD spelling rule, NO spelling_audio_format
    old = json.loads(json.dumps(DEFAULT_POLICY))
    old["teaching"].pop("spelling_audio_format", None)
    old["teaching"]["canonical_spelling_rules"][2] = (
        "Spelling requests (怎么拼): spell the canonical word letter by letter — "
        "never spell its pronunciation.")
    store.apply(old, actor="v19-seed")
    before = store.active()["policy"]

    # the sanctioned upgrade: stored policy merged with the new code defaults
    # (deep-merge fills spelling_audio_format) + the audio-safe rule text
    candidate = json.loads(json.dumps(before))
    candidate["teaching"]["canonical_spelling_rules"][2] = \
        DEFAULT_POLICY["teaching"]["canonical_spelling_rules"][2]
    merged, errors = validate_policy(candidate)
    check("C1 upgraded candidate validates (merge fills the new field)",
          not errors
          and merged["teaching"]["spelling_audio_format"] ==
          DEFAULT_POLICY["teaching"]["spelling_audio_format"], errors[:3])
    store.apply(merged, actor="spelling-audio-02",
                reason="audio-safe spelling rule + persistent teaching field")

    # mission case 14 — the STORED policy really renders the rule
    act = store.active()["policy"]
    blk = intent.render_instructions(_chat_state(), _chat_dec(), policy=act)
    check("C2 stored policy renders the always-on rule",
          "say only the English letter names" in blk
          and "(touch → T O U C H)" in blk, blk[:220])
    check("C3 vocab policy block also carries the audio-safe rule",
          "letter by letter using ONLY English letter names" in
          render_vocab_policy(act), "vocab block")

    # mission case 15 — persistence across store instances (sidecar restart)
    store2 = PolicyStore(path).load()
    blk2 = intent.render_instructions(_chat_state(), _chat_dec(),
                               policy=store2.active()["policy"])
    check("C4 rule persists across store reload (restart semantics)",
          "say only the English letter names" in blk2, blk2[:200])

    # mission case 16 — nothing else lost
    changed = diff_keys(before, store.active()["policy"])
    check("C5 diff limited to the two spelling paths",
          set(changed) <= {"teaching.canonical_spelling_rules",
                           "teaching.spelling_audio_format"}, changed)
    check("C6 audit trail records the apply",
          any(a.get("actor") == "spelling-audio-02" for a in store.audit(10)),
          store.audit(10)[:2])


def _chat_state():
    st = intent.BehaviorState()
    return st


def _chat_dec():
    return intent.route("今天我们随便聊聊", intent.BehaviorState())


# ---------------------------------------------------------------------------

def amain(tmpdir):
    fix_b_cases()
    fix_a_cases()
    fix_c_cases(tmpdir)
    fails = [r for r in RESULTS if not r[1]]
    print("=" * 72)
    print("SPELLING_AUDIO_02_TESTS: %d checks, %d PASS, %d FAIL"
          % (len(RESULTS), len(RESULTS) - len(fails), len(fails)))
    if fails:
        print("FAILED CHECKS:")
        for name, _, detail in fails:
            print("  - %s %s" % (name, detail))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(amain(tempfile.mkdtemp(prefix="spelling-audio-02-")))
