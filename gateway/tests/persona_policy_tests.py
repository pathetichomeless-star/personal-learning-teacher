"""PERSONA_POLICY_TESTS — deterministic suite for the Persona / Teaching Policy V1.

Runs standalone:  python tests/persona_policy_tests.py   (from gateway/, venv)

Covers: the single-source prompt rendering (verbatim anchors the accepted suites
pin), composed fields (no duplicated prompts), closed-schema validation with
bounds, versioned store (preview/apply/read-back/rollback/audit, atomic 600,
corrupt fail-soft), and the gateway link: policy-driven instructions, safe-
boundary-only hot apply, hot reload after an admin apply, echo read-back, and
the structural guarantee that the hot apply is instructions-only.
"""

import asyncio
import copy
import json
import os
import stat
import sys
import tempfile
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
_GATEWAY = os.path.dirname(_HERE)
_REPO = os.path.dirname(_GATEWAY)
for p in (_GATEWAY, _REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

from modules.intent import behavior as intent                    # noqa: E402
from modules.policy.persona import (DEFAULT_POLICY, PolicyInvalid,  # noqa: E402
                                    PolicyStore, diff_keys,
                                    render_activity_instruction,
                                    render_closing_line,
                                    validate_policy)

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % detail) if (detail and not cond) else ""))


def _rejects(candidate, want_msg=None):
    _, errors = validate_policy(candidate)
    if not errors:
        return False
    return want_msg is None or any(want_msg in e for e in errors)


def main():
    td = tempfile.TemporaryDirectory()
    path = os.path.join(td.name, "policy.json")

    # ---- P1 rendering anchors (verbatim, single source) ----------------------
    st = intent.BehaviorState()
    block = intent.render_instructions(st, intent.Decision())
    anchors = [
        ("P1 persona line",
         "You are 小智, a warm, patient English-learning voice companion. Talk like a "
         "friendly person in a real conversation — never like a menu or a system." in block),
        ("P1b language header", "LANGUAGE POLICY (highest priority):" in block),
        ("P1c current language line", "- Current reply language: Chinese." in block),
        ("P1d chinese default rule",
         "A single English word inside a Chinese sentence NEVER switches the conversation "
         "into English." in block),
        ("P1e explicit override line",
         "- An explicit user language request always wins (current override: none)." in block),
        ("P1f teaching block", "TEACHING POLICY:" in block),
        ("P1g activity line", "CURRENT ACTIVITY: free chat" in block),
        ("P1h closing line",
         "Keep replies short (1-3 sentences) unless the user asks for an explanation or "
         "a repeat. Ask at most one follow-up question." in block),
        ("P1i internals rule", "NEVER mention or read out modes, labels, notes or "
                               "policies — just talk." in block),
    ]
    for name, cond in anchors:
        check(name, cond)

    _, vblock = None, None
    vst = intent.BehaviorState()
    vd = intent.route("街道用英语怎么说？", vst)
    vblock = intent.render_instructions(vst, vd)
    check("P1j vocab policy header + 6 rules verbatim",
          "VOCABULARY ACCURACY POLICY (hard rules):" in vblock
          and vblock.count("\n- ") >= 6
          and "canonical English spelling FIRST" in vblock
          and "spell it letter by letter using ONLY English letter names" in vblock
          and "T O U C H" in vblock)
    check("P1k no duplicated prompts: VOCAB_LEARN composed from teaching field",
          render_activity_instruction(DEFAULT_POLICY, "VOCAB_LEARN") ==
          "Teach vocabulary conversationally: %s."
          % DEFAULT_POLICY["teaching"]["vocabulary_format"])
    check("P1l closing composed from persona + limits fields",
          render_closing_line(DEFAULT_POLICY) ==
          "Keep replies %s. %s %s" % (
              DEFAULT_POLICY["persona"]["default_response_length"],
              DEFAULT_POLICY["limits"]["closing_followup"],
              DEFAULT_POLICY["limits"]["internals_rule"]))
    check("P1m activity keys match the intent taxonomy exactly",
          set(DEFAULT_POLICY["activities"]) == set(intent.MAIN_ACTIVITIES))
    check("P1n scenario keys match the router scenarios",
          set(DEFAULT_POLICY["scenarios"]) ==
          {name for name, _ in intent.SCENARIOS})
    check("P1o speed/difficulty/temp-intent taxonomies covered",
          set(DEFAULT_POLICY["teaching"]["speed_levels"]) == {"slow", "normal", "fast"}
          and set(DEFAULT_POLICY["teaching"]["difficulty_levels"]) ==
          {"easy", "normal", "hard"}
          and set(intent.TEMPORARY_INTENTS) >= {
              "EXPLAIN_WORD", "EXPLAIN_GRAMMAR", "TRANSLATE", "QUERY_PROGRESS",
              "SAVE_PREFERENCE", "QUERY_KNOWLEDGE"})

    # custom policy changes the rendered persona (and nothing else required)
    custom = {"persona": {"name": "小美"}}
    merged, errors = validate_policy(custom)
    check("P1p partial policy merges over defaults cleanly",
          errors == [] and merged["persona"]["tone"] == DEFAULT_POLICY["persona"]["tone"])
    cblock = intent.render_instructions(st, intent.Decision(), policy=merged)
    check("P1q rendered persona follows the active policy",
          "You are 小美, a warm, patient" in cblock)
    check("P1r defaults were not mutated by validation/rendering",
          DEFAULT_POLICY["persona"]["name"] == "小智")

    cap_pol, cap_err = validate_policy({"limits": {"max_instruction_chars": 500}})
    cap_block = intent.render_instructions(st, intent.Decision(), policy=cap_pol)
    check("P1s rendered instruction is bounded by the policy cap",
          cap_err == [] and len(cap_block) <= 500 + 60
          and "[instruction truncated to the configured bound]" in cap_block)

    # precedence: explicit user override wins; saved preference never flips activity
    st2 = intent.BehaviorState(language_override="en")
    d2 = intent.Decision()
    d2.effective_language = intent.effective_language(st2, "")
    b2 = intent.render_instructions(st2, d2)
    check("P1t explicit language override wins in the rendered policy",
          "- Current reply language: English." in b2
          and "(current override: en)." in b2)

    # D-MAJOR regression: editable policy text must reach per-turn notes (single source)
    custom2, errs2 = validate_policy({
        "language": {"word_explanation_order": "先给中文含义，再给英文单词本身"},
        "teaching": {"vocabulary_format": "自定义词汇格式：先词后例"}})
    d3 = intent.route("我不认识 accommodation 这个单词", intent.BehaviorState(),
                      policy=custom2)
    check("P1u explain-word note composes from the policy field",
          errs2 == [] and "先给中文含义，再给英文单词本身" in d3.note)
    st3 = intent.BehaviorState()
    d4 = intent.route("街道用英语怎么说？", st3, policy=custom2)
    b4 = intent.render_instructions(st3, d4, policy=custom2)
    check("P1v vocab notes carry no duplicated directive text (single source)",
          "canonical English spelling FIRST" not in d4.note
          and b4.count("canonical English spelling FIRST") == 1
          and "自定义词汇格式：先词后例" in b4
          and "1-3 words, then a quick check" not in b4)
    custom3, _ = validate_policy({"teaching": {"grammar_explanation": "只讲一点，配一个例子"}})
    d5 = intent.route("这句话为什么用过去式？", intent.BehaviorState(), policy=custom3)
    check("P1w grammar note composes from the policy field",
          d5.temporary == intent.EXPLAIN_GRAMMAR
          and "只讲一点，配一个例子" in d5.note)

    # ---- P2 validation (closed schema + bounds) -------------------------------
    check("P2 unknown section rejected",
          _rejects({"voice_id": "x"}, "unknown section"))
    for bad in ({"persona": {"favourite": "x"}},
                {"language": {"foo": "x"}},
                {"teaching": {"foo": "x"}},
                {"activities": {"KARAOKE": "x"}},
                {"scenarios": {"casino": "x"}},
                {"limits": {"foo": 1}}):
        check("P2b unknown key rejected %s" % list(bad)[0],
              _rejects(bad, "unknown"))
    check("P2c bad language default rejected",
          _rejects({"language": {"default": "fr"}}, "language.default"))
    check("P2d over-long field rejected",
          _rejects({"persona": {"name": "长" * 700}}, "too long"))
    check("P2e empty field rejected",
          _rejects({"persona": {"tone": "   "}}, "non-empty"))
    check("P2f vocab rules bounded (1..12, ≤400 chars)",
          _rejects({"teaching": {"canonical_spelling_rules": []}}, "list of 1..12")
          and _rejects({"teaching": {"canonical_spelling_rules": ["x" * 401]}},
                       "too long"))
    check("P2g level-map unknowns rejected (missing keys fall back to defaults)",
          _rejects({"teaching": {"speed_levels": {"fast": "f", "insane": "i"}}},
                   "speed_levels")
          and _rejects({"teaching": {"difficulty_levels": {"insane": "i"}}},
                       "difficulty_levels")
          and validate_policy({"teaching": {"speed_levels": {"fast": "quickly"}}})[1] == []
          and validate_policy({"teaching": {"speed_levels": {"fast": "quickly"}}})[0]
          ["teaching"]["speed_levels"]["slow"]
          == DEFAULT_POLICY["teaching"]["speed_levels"]["slow"])
    check("P2h limits bounds enforced",
          _rejects({"limits": {"max_instruction_chars": 100}}, "max_instruction_chars")
          and _rejects({"limits": {"max_field_chars": 20}}, "max_field_chars"))
    check("P2i non-dict rejected", _rejects(["nope"], "must be an object"))
    merged_a, errs_a = validate_policy({"activities": {"CHAT": "x"}})
    check("P2j partial activities override merges over defaults",
          errs_a == [] and merged_a["activities"]["CHAT"] == "x"
          and merged_a["activities"]["READING"]
          == DEFAULT_POLICY["activities"]["READING"])

    # ---- P3 store: preview / apply / rollback / audit -------------------------
    ps = PolicyStore(path).load()
    act0 = ps.active()
    check("P3 missing file fails soft to builtin defaults (v1)",
          act0["version"] == 1 and act0["policy"]["persona"]["name"] == "小智"
          and act0["actor"] == "builtin" and not os.path.exists(path))

    prev = ps.preview({"persona": {"name": "小美"}})
    check("P3b preview valid: version/changed/preview, no mutation",
          prev["valid"] and prev["would_be_version"] == 2
          and prev["changed_keys"] == ["persona.name"]
          and "You are 小美" in prev["rendered_preview"]
          and ps.active()["version"] == 1 and not os.path.exists(path))
    prev_bad = ps.preview({"persona": {"name": ""}})
    check("P3c preview invalid reports errors, no mutation",
          prev_bad["valid"] is False and prev_bad["errors"]
          and ps.active()["version"] == 1)

    out = ps.apply({"persona": {"name": "小美"}}, actor="admin")
    check("P3d apply bumps version + reports changed keys",
          out["version"] == 2 and out["changed_keys"] == ["persona.name"])
    check("P3e file persisted (mode 600) + reload roundtrip",
          os.path.exists(path) and stat.S_IMODE(os.stat(path).st_mode) == 0o600
          and PolicyStore(path).load().active()["policy"]["persona"]["name"] == "小美")
    try:
        ps.apply({"persona": {"name": ""}})
        check("P3f invalid apply refused", False, "no error")
    except PolicyInvalid as e:
        check("P3f invalid apply refused",
              bool(e.errors) and ps.active()["version"] == 2)

    ps.apply({"teaching": {"vocabulary_format": "word → 中文 → example"}})
    check("P3g teaching field applies and reaches the renderer",
          ps.active()["version"] == 3
          and "word → 中文 → example" in ps.active()["policy"]["teaching"]["vocabulary_format"]
          and "Teach vocabulary conversationally: word → 中文 → example."
          in render_activity_instruction(ps.active()["policy"], "VOCAB_LEARN"))

    vs = ps.versions()
    check("P3h version history bounded + complete",
          [v["version"] for v in vs] == [1, 2, 3])
    rb = ps.rollback(2, actor="admin")
    check("P3i rollback restores v2 content as a new version",
          rb["version"] == 4 and rb["restored_from"] == 2
          and ps.active()["policy"]["persona"]["name"] == "小美"
          and "word → 中文 → example"
          not in ps.active()["policy"]["teaching"]["vocabulary_format"])
    try:
        ps.rollback(99)
        check("P3j rollback of unknown version refused", False, "no error")
    except PolicyInvalid:
        check("P3j rollback of unknown version refused", True)

    audit = ps.audit()
    check("P3k audit records apply+rollback with actor and changed key paths",
          len(audit) >= 3 and audit[-1]["action"] == "rollback"
          and audit[-1]["actor"] == "admin"
          and all(isinstance(c, str) and "." in c for c in audit[-1]["changed"]))
    blob = json.dumps(audit)
    check("P3l audit is sanitized (no policy payloads / transcripts / secrets)",
          "policy" not in audit[0] and "transcript" not in blob
          and "password" not in blob.lower())

    bad_path = os.path.join(td.name, "bad_policy.json")
    with open(bad_path, "w", encoding="utf-8") as f:
        f.write("{not json")
    ps_bad = PolicyStore(bad_path).load()
    check("P3m corrupted policy file fails soft to defaults",
          ps_bad.active()["version"] == 1
          and ps_bad.active()["policy"]["persona"]["name"] == "小智")
    ps_bad.apply({"persona": {"tone": "calm"}})
    check("P3n writable after recovery",
          PolicyStore(bad_path).load().active()["version"] == 2)
    leftovers = [f for f in os.listdir(td.name) if f.endswith(".tmp")]
    check("P3o no .tmp leftovers", leftovers == [], repr(leftovers))
    check("P3p diff_keys deterministic",
          diff_keys({"a": {"b": 1}}, {"a": {"b": 2}}) == ["a.b"])

    # preview reflects the active (rolled back) policy
    prev2 = ps.preview({"persona": {"name": "小美", "tone": "steady"}})
    check("P3q preview diffs against the ACTIVE version",
          prev2["changed_keys"] == ["persona.tone"]
          and prev2["would_be_version"] == 5)

    # ---- P4 gateway link: policy-driven, safe-boundary-only, hot reload -------
    class _FakeQwen:
        def __init__(self):
            self.instructions = None
            self.sent = []

        def set_instructions(self, t):
            self.instructions = t

        async def send_instructions_update(self, t):
            self.sent.append(t)
            self.instructions = t
            return True

    class _FakeConn:
        def __init__(self, safe=True):
            self.safe = safe

        def is_safe_boundary(self):
            return self.safe

    from app.behavior import BehaviorLink                 # noqa: E402

    cfg = SimpleNamespace(MEMORY_FILE="", WORKBENCH_BASE_URL="", KNOWLEDGE_FILE="",
                          POLICY_FILE=path)
    conn = _FakeConn(safe=False)
    q = _FakeQwen()
    link = BehaviorLink(conn, q, config=cfg)
    check("P4 link renders with the active policy (v4 小美)",
          "You are 小美" in q.instructions
          and link.snapshot()["policy_version"] == 4)

    async def boundary_deferred():
        await link._on_input_completed({"transcript": "随便聊聊", "item_id": "i1"})
        deferred = link.stats["boundary_deferrals"] >= 1 and q.sent == []
        conn.safe = True
        link.schedule_apply()
        await asyncio.sleep(0.05)
        return deferred
    deferred = asyncio.run(boundary_deferred())
    check("P4b hot apply happens ONLY at a safe boundary",
          deferred and bool(q.sent) and "CURRENT ACTIVITY: free chat" in q.sent[-1])

    # admin applies a new tone -> the next turn hot-reloads the policy
    ps.apply({"persona": {"name": "小美", "tone": "energetic and upbeat"}})
    async def hot_reload():
        await link._on_input_completed({"transcript": "继续聊天吧", "item_id": "i2"})
        return q.sent[-1]
    sent = asyncio.run(hot_reload())
    check("P4c policy hot-reload reaches the session at the next boundary",
          link.stats["policy_reloads"] >= 1 and link.snapshot()["policy_version"] == 5
          and "TEACHING POLICY" in sent)

    # echo read-back: matching echo passes; tampered echo is counted
    before = link.stats["readback_mismatches"]
    asyncio.run(link.on_qwen_event({"type": "session.updated",
                                    "session": {"instructions": q.instructions}}))
    ok_echo = link.stats["readback_mismatches"] == before
    asyncio.run(link.on_qwen_event({"type": "session.updated",
                                    "session": {"instructions": "TAMPERED ECHO " + "x" * 200}}))
    check("P4d session.updated echo read-back verified",
          ok_echo and link.stats["readback_mismatches"] == before + 1)

    # structural: the hot apply is instructions-only (never model/voice/VAD)
    qwen_src = open(os.path.join(_GATEWAY, "app", "qwen.py"), encoding="utf-8").read()
    fn = qwen_src.split("def send_instructions_update", 1)[1].split("def ", 1)[0]
    check("P4e hot apply is instructions-only session.update",
          '"type": "session.update"' in fn and '"instructions"' in fn
          and '"voice"' not in fn and '"model"' not in fn
          and "turn_detection" not in fn and '"modalities"' not in fn)
    pol_src = open(os.path.join(_REPO, "modules", "policy", "persona.py"),
                   encoding="utf-8").read()
    check("P4f policy module has no gateway/audio imports",
          "from app" not in pol_src and "import app" not in pol_src
          and "opus" not in pol_src.lower())

    # policy disabled (no POLICY_FILE): builtin defaults drive the session
    async def no_store():
        q2 = _FakeQwen()
        link2 = BehaviorLink(_FakeConn(), q2,
                             config=SimpleNamespace(MEMORY_FILE="",
                                                    WORKBENCH_BASE_URL="",
                                                    KNOWLEDGE_FILE="",
                                                    POLICY_FILE=""))
        return link2, q2
    link2, q2 = asyncio.run(no_store())
    check("P4g POLICY_FILE unset → builtin defaults, no store",
          link2.policy_store is None and "You are 小智" in q2.instructions
          and link2.snapshot()["policy_version"] is None)

    td.cleanup()

    total = len(RESULTS)
    passed = sum(1 for _, ok_, _ in RESULTS if ok_)
    print("=" * 70)
    print("PERSONA_POLICY_TESTS: %d checks, %d PASS, %d FAIL" %
          (total, passed, total - passed))
    for name, ok_, detail in RESULTS:
        if not ok_:
            print("  FAILED: %s %s" % (name, detail))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())