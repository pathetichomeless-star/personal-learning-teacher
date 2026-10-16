# -*- coding: utf-8 -*-
"""Local learning-record behaviour tests (CLASSROOM V2 · Agent F · Phase 2).

L01  add + count;
L02  **cross-restart recovery** (a second instance reads the same file);
L03  **corruption recovery** — quarantine, empty start, no crash, flag set;
L04  on-disk file is mode 0o600 and is valid JSON;
L05  mistakes view (item_type=mistake OR result wrong/incorrect);
L06  review queue de-duplicates by item_id (keeps the latest);
L07  mastery ratio is bounded and correct;
L08  GUI deletion (one / by course);
L09  **not a multi-student system** — scope marker present, no user-id field;
L10  unknown item_type is rejected (no silent write).

Run:
    cd client && PYTHONPATH= ./.venv/bin/python src/classroom/tests/test_learning_record.py
"""

import json
import os
import stat
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_CLIENT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
if _CLIENT not in sys.path:
    sys.path.insert(0, _CLIENT)

from src.classroom.learning_record import LearningRecordStore, SCOPE  # noqa: E402

RESULTS = []


def check(cid, name, cond, observed=None):
    line = sys._getframe(1).f_lineno
    RESULTS.append({"case_id": cid, "name": name, "passed": bool(cond),
                    "observed": repr(observed)[:300],
                    "asserted_file": os.path.abspath(__file__), "asserted_line": line})
    print(("PASS " if cond else "FAIL ") + "%s %s%s"
          % (cid, name, "" if cond else "  → %r" % (observed,)))
    return bool(cond)


def main():
    tmp = tempfile.mkdtemp(prefix="learnrec_")
    path = os.path.join(tmp, "learning", "records.json")

    st = LearningRecordStore(path)
    st.add(course_id="crs_a", lesson_id="l1", item_id="s1", item_type="note",
           prompt="reservation", answer="预订", result="ok")
    st.add(course_id="crs_a", lesson_id="l1", item_id="s2", item_type="mistake",
           prompt="luggage", answer="行李", result="wrong")
    st.add(course_id="crs_a", lesson_id="l2", item_id="s3", item_type="review",
           prompt="double room", result="pending")
    st.add(course_id="crs_b", lesson_id="l1", item_id="s1", item_type="mastery",
           prompt="hello", result="ok")
    check("L01", "add + count == 4", st.count() == 4, st.count())

    # L02 cross-restart
    st2 = LearningRecordStore(path)
    check("L02", "跨重启恢复：新实例读到 4 条", st2.count() == 4, st2.count())

    # L04 file mode / valid json
    mode = stat.S_IMODE(os.stat(path).st_mode)
    with open(path, encoding="utf-8") as f:
        disk = json.load(f)
    check("L04", "磁盘文件 mode=0o600 且为合法 JSON",
          mode == 0o600 and disk.get("scope") == SCOPE, (oct(mode), disk.get("scope")))

    # L05 mistakes
    check("L05", "错题本含 1 条（result=wrong）", len(st2.mistakes()) == 1,
          [r["item_id"] for r in st2.mistakes()])

    # L06 review dedupe
    st2.add(course_id="crs_a", lesson_id="l2", item_id="s3", item_type="review",
            prompt="double room v2", result="pending")
    rq = st2.review_queue("crs_a")
    check("L06", "待复习按 item_id 去重（s3 只 1 条，且为最新）",
          len(rq) == 1 and rq[0]["prompt"] == "double room v2",
          [(r["item_id"], r["prompt"]) for r in rq])

    # L07 mastery
    m = st2.mastery("crs_a")
    check("L07", "掌握度在 (0,1] 且 <1（含 1 条错题）", 0.0 < m < 1.0, m)
    check("L07b", "无记录课程掌握度 = 0.0", st2.mastery("crs_none") == 0.0)

    # L08 delete
    n = st2.delete_course("crs_b")
    check("L08a", "按课程删除返回删除条数", n == 1 and st2.count() == 4, (n, st2.count()))
    st2.delete_one(0)
    check("L08b", "按记录删除后 count 减少", st2.count() == 3, st2.count())

    # L09 not multi-student
    keys = set()
    for r in st2.all():
        keys |= set(r.keys())
    check("L09", "无 user_id/account 字段且全部带 scope=local-single-user（非多学生隔离）",
          not ({"user_id", "account", "student_id"} & keys)
          and all(r.get("scope") == SCOPE for r in st2.all()), sorted(keys))

    # L10 unknown type rejected
    try:
        st2.add(course_id="crs_a", lesson_id="l", item_id="i", item_type="chat")
        ok = False
    except ValueError:
        ok = True
    check("L10", "未知 item_type → 拒绝写入", ok)

    # L03 corruption recovery (own file, isolated)
    bad = os.path.join(tmp, "bad.json")
    with open(bad, "w", encoding="utf-8") as f:
        f.write("{ this is not json")
    st3 = LearningRecordStore(bad)
    quarantined = [p for p in os.listdir(tmp) if p.startswith("bad.json.corrupt-")]
    check("L03", "损坏文件 → 隔离 + 空启动 + 标记（不崩溃）",
          st3.count() == 0 and st3.recovered_from_corruption
          and st3.read_error != "" and len(quarantined) == 1,
          (st3.count(), st3.recovered_from_corruption, quarantined))
    # 损坏后可继续正常写入
    st3.add(course_id="crs_c", lesson_id="l", item_id="i", item_type="note", prompt="x")
    check("L03b", "隔离后可继续正常写入", st3.count() == 1)

    passed = sum(1 for r in RESULTS if r["passed"])
    failed = [r["case_id"] for r in RESULTS if not r["passed"]]
    print("\n" + "=" * 70)
    print("LEARNING_RECORD: %d checks, %d PASS, %d FAIL" % (len(RESULTS), passed, len(failed)))
    if failed:
        print("FAILED:", ", ".join(failed))

    ev = os.path.join(_CLIENT, "..", "docs", "engineering", "product-v1",
                      "classroom-v2", "evidence", "learning_record_tests.json")
    try:
        with open(os.path.abspath(ev), "w", encoding="utf-8") as f:
            json.dump({"artifact": "learning_record_tests",
                       "scope": "CLASSROOM V2 PHASE2 · Agent F（本机学习记录）",
                       "results": RESULTS,
                       "summary": {"total": len(RESULTS), "passed": passed,
                                   "failed": len(failed), "failed_ids": failed}},
                      f, ensure_ascii=False, indent=2)
        print("evidence:", os.path.abspath(ev))
    except Exception as e:  # noqa: BLE001
        print("evidence 写入失败（不影响结论）:", e)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
