"""MEMORY-1 (minimal) deterministic suite — closed schema + hard boundary.

Runs standalone:  python tests/memory1_tests.py   (from gateway/, venv)
Verifies: preference roundtrip, closed enums, progress-shaped write rejection
(`400 boundary_violation` analogue), per-user isolation, forget semantics,
weak-vocab subset, corruption fail-soft, file mode, and the read-only
no-progress assertion.  Explicitly asserts NOTHING progress/transcript-shaped
can enter the store.
"""

import json
import os
import re
import stat
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_GATEWAY = os.path.dirname(_HERE)
_REPO = os.path.dirname(_GATEWAY)
for p in (_GATEWAY, _REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

from modules.memory.store import BoundaryViolation, MemoryStore  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % detail) if (detail and not cond) else ""))


def main():
    td = tempfile.TemporaryDirectory()
    path = os.path.join(td.name, "memory.json")

    # ---- M1: save / reload / apply ----------------------------------------
    ms = MemoryStore(path).load()
    ms.save_preference("explanation_language", "zh")
    ms.save_preference("speed", "slow")
    ms.save_preference("difficulty", "hard")
    ms2 = MemoryStore(path).load()
    check("M1 roundtrip all three preferences", ms2.preferences() == {
        "explanation_language": "zh", "speed": "slow", "difficulty": "hard"})

    # ---- M2: boundary rejections (progress-shaped) --------------------------
    forbidden = ["progress", "lesson", "lesson_progress", "mastery:1", "next_review",
                 "pass", "review_state", "repeat_count", "course_progress",
                 "课程进度", "复习计划", "掌握度"]
    all_rejected = True
    for key in forbidden:
        try:
            ms2.save_preference(key, "x")
            all_rejected = False
            print("      NOT REJECTED: %r" % key)
        except BoundaryViolation:
            pass
    check("M2 progress-shaped keys rejected (boundary_violation)", all_rejected)

    # ---- M3: closed enums ---------------------------------------------------
    rejected = 0
    for key, bad in (("speed", "warp"), ("explanation_language", "fr"),
                     ("difficulty", "extreme")):
        try:
            ms2.save_preference(key, bad)
        except BoundaryViolation:
            rejected += 1
    check("M3 invalid values rejected", rejected == 3)

    # ---- M4: unknown key rejected (closed set) ------------------------------
    try:
        ms2.save_preference("favourite_color", "blue")
        check("M4 closed key set", False, "no error")
    except BoundaryViolation:
        check("M4 closed key set", True)

    # ---- M5: no transcript storage possible ---------------------------------
    try:
        ms2.save_preference("speed", "今天用户说了一大段话" * 20)
        check("M5 free text cannot enter preferences", False, "no error")
    except BoundaryViolation:
        check("M5 free text cannot enter preferences", True)
    raw = open(path, encoding="utf-8").read()
    check("M5b file has no transcript-ish keys",
          "transcript" not in raw and "audio" not in raw)

    # ---- M6: forget semantics ------------------------------------------------
    ms3 = MemoryStore(path).load()
    removed = ms3.forget("speed")
    check("M6 forget by key", removed == ["speed"]
          and "speed" not in ms3.preferences())
    removed = ms3.forget()
    check("M6b forget latest (difficulty)", removed == ["difficulty"],
          repr(removed))
    check("M6c forget unknown key is a no-op", ms3.forget("nope") == [])

    # ---- M7: per-user isolation ---------------------------------------------
    path2 = os.path.join(td.name, "memory2.json")
    ua = MemoryStore(path2, user="userA").load()
    ub = MemoryStore(path2, user="userB").load()
    ua.save_preference("speed", "slow")
    check("M7 user isolation", MemoryStore(path2, user="userB").load()
          .preferences() == {})

    # ---- M8: weak vocab subset ----------------------------------------------
    ms4 = MemoryStore(os.path.join(td.name, "memory3.json")).load()
    ms4.note_weak_word("Accommodation")          # normalized to lower-case
    ms4.note_weak_word("walked")
    check("M8 weak words stored", set(ms4.vocab_items()) == {"accommodation",
                                                             "walked"})
    check("M8b non-word rejected", ms4.note_weak_word("你好") is None
          and ms4.note_weak_word("") is None)

    # ---- M9: corruption fail-soft -------------------------------------------
    bad_path = os.path.join(td.name, "corrupt.json")
    with open(bad_path, "w", encoding="utf-8") as f:
        f.write("{not json")
    ms5 = MemoryStore(bad_path).load()
    check("M9 corrupt file fail-soft", ms5.preferences() == {})
    ms5.save_preference("speed", "fast")         # still writable after recovery
    check("M9b writable after recovery",
          MemoryStore(bad_path).load().preferences() == {"speed": "fast"})

    # ---- M10: file mode 600 --------------------------------------------------
    mode = stat.S_IMODE(os.stat(path).st_mode)
    check("M10 file mode 600", mode == 0o600, oct(mode))

    # ---- M11: no-progress assertion + schema hygiene --------------------------
    ms6 = MemoryStore(path).load()
    check("M11 no progress keys assertion clean",
          ms6.assert_no_progress_keys() == [])
    items = ms6.items()
    ok = all(it["entity_type"] in ("preference", "vocab_item")
             and it.get("source") and it.get("confidence") is not None
             for it in items)
    check("M11b provenance + confidence on every item", ok)

    # ---- M12: atomic write / no temp leftovers -------------------------------
    leftovers = [f for f in os.listdir(td.name) if f.endswith(".tmp")]
    check("M12 no .tmp leftovers", leftovers == [], repr(leftovers))

    # ---- M13: item cap --------------------------------------------------------
    cap_path = os.path.join(td.name, "cap.json")
    ms7 = MemoryStore(cap_path).load()
    for i in range(210):
        ms7.note_weak_word("word%03d" % i)       # excess is silently refused
    stored = len(MemoryStore(cap_path).load().items())
    check("M13 item cap enforced (silent refusal beyond cap)",
          stored <= 200, repr(stored))

    td.cleanup()

    total = len(RESULTS)
    passed = sum(1 for _, ok_, _ in RESULTS if ok_)
    print("=" * 70)
    print("MEMORY1_TESTS: %d checks, %d PASS, %d FAIL" %
          (total, passed, total - passed))
    for name, ok_, detail in RESULTS:
        if not ok_:
            print("  FAILED: %s %s" % (name, detail))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())