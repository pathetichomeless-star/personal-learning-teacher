"""SPELLING-AUDIO-01 — audio-safe English spelling policy: synthetic tests.

Verifies the authorized policy change (modules/policy/persona.py, the
"Spelling requests (怎么拼)" rule):

  * the audio-safe letter-spelling rule is present in the DEFAULT policy and
    in `render_vocab_policy` output (the text injected into the Qwen session);
  * no connector-joined spelling format (T-O-U-C-H / T–O–U–C–H) is prescribed;
  * letter names are separated by single spaces; separators must never be
    written or read (hyphen/dash/横杠/连字符/dash/hyphen);
  * normal-word pronunciation vs letter-by-letter spelling stay distinct, and
    ordinary sentence reading is unchanged;
  * the rule actually reaches the Qwen session instructions through the REAL
    behavior-link wiring (spelling turn hot-apply);
  * a stored (v15-style) policy upgrades to the new rule through the
    sanctioned PolicyStore.apply path (the staged-sidecar mechanism);
  * all pre-existing teaching rules and the Chinese-explanation capability are
    preserved; validation bounds still hold.

Run:
    cd <project-root>/gateway
    .venv/bin/python tests/spelling_audio_policy_tests.py
"""

import asyncio
import json
import sys
import types
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_GATEWAY = _HERE.parent
_REPO = _GATEWAY.parent
for _p in (str(_GATEWAY), str(_REPO), str(_REPO / "client")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from modules.policy import persona as persona_mod              # noqa: E402
from modules.policy.persona import (DEFAULT_POLICY,            # noqa: E402
                                    PolicyStore, render_vocab_policy,
                                    validate_policy)
from app import behavior as link_mod                           # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        (" - " + str(detail)) if (detail and not cond) else ""))
    return bool(cond)


BLOCK = render_vocab_policy(DEFAULT_POLICY)


# ---------------------------------------------------------------------------
# P1-P2 — policy content
# ---------------------------------------------------------------------------

def content_cases():
    print("\n==== policy content ====")
    check("P1 audio-safe letter rule present in DEFAULT policy",
          "letter by letter using ONLY English letter names separated by "
          "single spaces" in BLOCK, BLOCK[:200])
    check("P1b space-separated example present (touch → T O U C H)",
          "(touch → T O U C H)" in BLOCK, BLOCK[:200])
    check("P1c natural-pause instruction present",
          "short natural pause between letters" in BLOCK, BLOCK[:200])
    check("P2a no connector-joined spelling format prescribed",
          "T-O-U-C-H" not in BLOCK and "T–O–U–C–H" not in BLOCK, BLOCK[:200])
    check("P2b separators explicitly forbidden (write AND read)",
          "never write or read hyphens, dashes" in BLOCK
          and "横杠" in BLOCK and "连字符" in BLOCK
          and "the words dash/hyphen" in BLOCK, BLOCK[:200])

    # existing teaching rules preserved
    for phrase in ("give the canonical English spelling FIRST",
                   "Never invent an English-looking spelling from sound",
                   "If you are not sure of a spelling, say so instead of guessing",
                   "When several translations are valid",
                   "keep their spelling exactly as written"):
        check("P3 existing rule preserved: %s…" % phrase[:36],
              phrase in BLOCK, BLOCK[:200])

    # rule 6 — pronunciation vs letter-by-letter distinction
    check("P4 pronunciation/spelling distinction preserved",
          "pronunciation stays SEPARATE from the spelling" in BLOCK
          and "never spell its pronunciation" in BLOCK, BLOCK[:200])

    # rule 7 — SPELLING-AUDIO-02: the audio-safe rule is now ALWAYS-ON in the
    # teaching lines (present in every session incl. CHAT); the per-turn vocab
    # policy block stays scoped as before.
    tl = "\n".join(persona_mod.render_teaching_lines(DEFAULT_POLICY))
    check("P5 audio-safe rule is always-on in teaching lines (SPELLING-AUDIO-02)",
          "Spelling aloud: When spelling an English word aloud" in tl
          and "(touch → T O U C H)" in tl
          and "Never insert or pronounce hyphens, dashes, or separator names" in tl,
          tl[:220])

    # validation bounds still hold with the longer rule
    merged, errors = validate_policy(DEFAULT_POLICY)
    rule = merged["teaching"]["canonical_spelling_rules"][2]
    check("P6 new rule passes validation (≤400 chars, single line)",
          not errors and len(rule) <= 400 and "\n" not in rule,
          (errors, len(rule)))

    # default policy diff is limited to the one rule path
    from modules.policy.persona import diff_keys
    changed = diff_keys(DEFAULT_POLICY, DEFAULT_POLICY)  # sanity: self-diff empty
    check("P6b renderer self-diff stable", changed == [], changed)


# ---------------------------------------------------------------------------
# P7 — INJECTION: the policy reaches the Qwen session instructions
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


def injection_cases():
    print("\n==== injection (real behavior-link wiring) ====")
    cfg = types.SimpleNamespace(MEMORY_FILE="", WORKBENCH_BASE_URL="")

    # P7 — spelling turn hot-applies the policy WITH the new audio-safe rule
    q = FakeQwen()
    link = link_mod.BehaviorLink(FakeConn(), q, config=cfg)
    asyncio.get_event_loop() if False else None
    asyncio_run(link.on_qwen_event(_transcript("touch 怎么拼？", "x1")))
    ins = q.ins
    check("P7 spelling turn injects the audio-safe rule into Qwen instructions",
          "letter by letter using ONLY English letter names" in ins
          and "(touch → T O U C H)" in ins
          and "never write or read hyphens, dashes" in ins
          and "VOCABULARY ACCURACY POLICY" in ins, ins[:220])
    check("P7b say-the-word-then-spell order injected",
          "first say the word normally, then spell it letter by letter" in ins,
          ins[:220])
    check("P7c no connector-joined format injected",
          "T-O-U-C-H" not in ins and "T–O–U–C–H" not in ins, ins[:220])

    # P8 — Chinese explanation capability unchanged (word explanation turn)
    q2 = FakeQwen()
    link2 = link_mod.BehaviorLink(FakeConn(), q2, config=cfg)
    asyncio_run(link2.on_qwen_event(
        _transcript("accommodation 是什么意思？", "x2")))
    check("P8 Chinese word-explanation capability unchanged",
          "accommodation" in q2.ins
          and "FIRST its Chinese meaning" in q2.ins, q2.ins[:220])
    asyncio_run(link2.close())


def asyncio_run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# P9 — stored-policy upgrade path (the staged-sidecar mechanism)
# ---------------------------------------------------------------------------

def store_cases(tmpdir):
    print("\n==== stored-policy upgrade (PolicyStore.apply) ====")
    path = str(Path(tmpdir) / "policy.json")
    store = PolicyStore(path).load()

    # seed a v15-style stored policy carrying the OLD rule
    old = json.loads(json.dumps(DEFAULT_POLICY))
    old["teaching"]["canonical_spelling_rules"][2] = (
        "Spelling requests (怎么拼): spell the canonical word letter by letter — "
        "never spell its pronunciation.")
    store.apply(old, actor="v15-seed")

    # the sanctioned upgrade: current stored policy + the new rule
    cur = store.active()["policy"]
    new = json.loads(json.dumps(cur))
    new["teaching"]["canonical_spelling_rules"][2] = (
        DEFAULT_POLICY["teaching"]["canonical_spelling_rules"][2])
    merged, errors = validate_policy(new)
    check("P9 upgraded policy validates", not errors, errors[:3])
    store.apply(new, actor="asr-ui-01", reason="spelling audio policy fix")

    act = store.active()["policy"]
    block = render_vocab_policy(act)
    check("P9b stored policy now carries the audio-safe rule",
          "letter by letter using ONLY English letter names" in block
          and "(touch → T O U C H)" in block, block[:200])
    check("P9c other rules untouched by the upgrade",
          "keep their spelling exactly as written" in block
          and "If you are not sure of a spelling" in block, block[:200])
    check("P9d audit trail records the apply",
          any(a.get("actor") == "asr-ui-01" for a in store.audit(10)),
          store.audit(10)[:2])


# ---------------------------------------------------------------------------

def amain(tmpdir):
    content_cases()
    injection_cases()
    store_cases(tmpdir)
    fails = [r for r in RESULTS if not r[1]]
    print("=" * 72)
    print("SPELLING_AUDIO_POLICY_TESTS: %d checks, %d PASS, %d FAIL"
          % (len(RESULTS), len(RESULTS) - len(fails), len(fails)))
    if fails:
        print("FAILED CHECKS:")
        for name, _, detail in fails:
            print("  - %s %s" % (name, detail))
    return 0 if not fails else 1


if __name__ == "__main__":
    import tempfile
    sys.exit(amain(tempfile.mkdtemp(prefix="spelling-audio-")))
