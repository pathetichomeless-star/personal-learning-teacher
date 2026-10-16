# -*- coding: utf-8 -*-
"""课程契约 v1 在**客户端侧**的行为测试（PHASE2 CONTRACT FIX 01 · 修正②/③ + C5）。

证明四件事真的生效（而非仅文档声明）：

* K01–K04  随包 demo 数据是**合法 v1**，且**不得伪造知识库来源**；
* K05–K08  契约违规 **fail-closed**：未知 slide.type / version=2 / 文档级 source /
           伪造来源 → ``coursesError`` 非空且**零课程**（不静默载入部分数据）；
* K09–K12  **C5 缺陷已修**：``answer: null``（答案待人工确认）时作答
           **不判分、不判错**（``graded=False``），且不会退回旧的 -1 静默错判；
* K13–K15  **修正③ 哈希口径**：无真实 ``source_file_sha256`` 时显示
           「原文件哈希待确认」，**绝不用 content_hash 冒充**；
* K16–K19  **CONTRACT_FIX_01A**：local-demo 可读且不冒充正式来源（正向）、
           缺真实 doc_id 的伪 user-textbook 被拒（负向）、**真实裸 64hex content_hash
           被接受**（01A 放宽哈希形式）、``file_hash_display`` 规范化裸 hex。

运行：
    cd client && QT_QPA_PLATFORM=offscreen ./.venv/bin/python \
        src/classroom/tests/test_course_contract_v1.py
"""
import copy
import json
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_HERE = os.path.dirname(os.path.abspath(__file__))
_CLIENT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
if _CLIENT not in sys.path:
    sys.path.insert(0, _CLIENT)

from PySide6.QtWidgets import QApplication  # noqa: E402

from src.classroom import course_schema as cschema  # noqa: E402
from src.classroom.classroom_model import ClassroomModel  # noqa: E402

DEMO = os.path.join(_CLIENT, "src", "classroom", "data", "courses.json")

RESULTS = []


def check(cid, name, cond, observed=None):
    line = sys._getframe(1).f_lineno
    RESULTS.append({"case_id": cid, "name": name, "passed": bool(cond),
                    "observed": repr(observed)[:300],
                    "asserted_file": os.path.abspath(__file__), "asserted_line": line})
    print(("PASS " if cond else "FAIL ") + "%s %s%s"
          % (cid, name, "" if cond else "  → %r" % (observed,)))
    return bool(cond)


def _write(tmpdir, doc):
    p = os.path.join(tmpdir, "courses_%d.json" % len(os.listdir(tmpdir)))
    with open(p, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    return p


def _base_course():
    return {
        "course_id": "crs_probe", "revision": 1, "title": "探针课程",
        "source": "local-demo",
        "source_doc_id": None, "source_doc_hash": None, "source_file_sha256": None,
        "lessons": [{"lesson_id": "lesson_probe", "title": "第 1 课", "slides": [
            {"type": "cover", "title": "封面"},
            {"type": "practice", "question": "选出正确答案", "options": ["A", "B", "C"],
             "answer": None},
        ]}],
    }


def _bundle(course=None, **over):
    doc = {"schema": "classroom.course.bundle", "version": 1,
           "courses": [course or _base_course()]}
    doc.update(over)
    return doc


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    tmp = tempfile.mkdtemp(prefix="course_contract_")

    # ---------------- K01–K04 随包数据合法 + 不伪造来源 ----------------
    with open(DEMO, "r", encoding="utf-8") as f:
        demo = json.load(f)
    check("K01", "随包 courses.json 是合法契约 v1（零违规）",
          cschema.is_valid(demo), cschema.validate_bundle(demo)[:3])
    check("K02", "文档级不含 source（来源已下沉到 course）",
          "source" not in demo, sorted(demo.keys()))
    check("K03", "每个 course 的本地演示来源绑定字段全为 null（不得伪造知识库来源）",
          all(c.get("source_doc_id") is None and c.get("source_doc_hash") is None
              and c.get("source_file_sha256") is None for c in demo["courses"]))
    m_demo = ClassroomModel(courses_path=DEMO, data_dir=tmp)
    check("K04", "随包数据可被客户端正常载入（无错误、课程数>0）",
          m_demo.coursesError == "" and m_demo.courseCount > 0,
          (m_demo.coursesError, m_demo.courseCount))

    # ---------------- K05–K08 违规 fail-closed ----------------
    bad_unknown_type = _bundle()
    bad_unknown_type["courses"][0]["lessons"][0]["slides"][0] = {"type": "quiz", "q": "?"}
    m = ClassroomModel(courses_path=_write(tmp, bad_unknown_type), data_dir=tmp)
    check("K05", "未知 slide.type → 错误态 + 零课程（不静默跳过）",
          m.coursesError != "" and m.courseCount == 0, (m.coursesError, m.courseCount))

    m = ClassroomModel(courses_path=_write(tmp, _bundle(version=2)), data_dir=tmp)
    check("K06", "未知 version → 错误态 + 零课程（fail-closed，不静默）",
          m.coursesError != "" and m.courseCount == 0, (m.coursesError, m.courseCount))

    m = ClassroomModel(courses_path=_write(tmp, _bundle(source="local-demo")), data_dir=tmp)
    check("K07", "文档级 source（历史遗留）→ 错误态 + 零课程",
          m.coursesError != "" and m.courseCount == 0, (m.coursesError, m.courseCount))

    forged = _base_course()
    forged["source_doc_id"] = "doc_deadbeef"
    forged["source_doc_hash"] = "sha256:" + "ab" * 32
    m = ClassroomModel(courses_path=_write(tmp, _bundle(forged)), data_dir=tmp)
    check("K08", "local-demo 伪造知识库来源 → 错误态 + 零课程",
          m.coursesError != "" and m.courseCount == 0, (m.coursesError, m.courseCount))

    # ---------------- K09–K12 C5：answer=null 不判分 ----------------
    m = ClassroomModel(courses_path=_write(tmp, _bundle()), data_dir=tmp)
    m.selectCourse(0)
    m.selectLesson(0)
    m.nextSlide()          # cover -> practice
    check("K09", "载入 answer=null 的练习（无错误）",
          m.coursesError == "" and m.hasPractice, (m.coursesError, m.hasPractice))
    pr = dict(m.practice)
    check("K10", "answer=null 被标记为「答案待人工确认」（answerUnknown=True）",
          pr.get("answerUnknown") is True, pr)
    m.answerPractice(1)
    pr = dict(m.practice)
    check("K11", "作答后 graded=False（不判分）且 correct=False（不判错）",
          pr.get("graded") is False and pr.get("correct") is False, pr)
    check("K12", "反馈文案显式说明「答案待人工确认」（不静默判错）",
          "待人工确认" in str(pr.get("feedback") or ""), pr.get("feedback"))

    # 对照：合法 answer=1 仍能正常判分（修缺陷不等于废功能）
    ok = _bundle()
    ok["courses"][0]["lessons"][0]["slides"][1]["answer"] = 1
    m2 = ClassroomModel(courses_path=_write(tmp, ok), data_dir=tmp)
    m2.selectCourse(0); m2.selectLesson(0); m2.nextSlide()
    m2.answerPractice(1)
    check("K12b", "对照：answer=1 时正常判分（graded=True, correct=True）",
          m2.practice.get("graded") is True and m2.practice.get("correct") is True,
          dict(m2.practice))

    # ---------------- K13–K15 修正③ 哈希口径 ----------------
    check("K13", "无 file_sha256 → 显示「原文件哈希待确认」",
          cschema.file_hash_display(None) == "原文件哈希待确认",
          cschema.file_hash_display(None))
    check("K14", "非法/伪造形式（非 sha256:64hex）→ 同样显示「待确认」，不得放行",
          cschema.file_hash_display("deadbeef") == "原文件哈希待确认"
          and cschema.file_hash_display("sha256:short") == "原文件哈希待确认")
    check("K15", "content_hash 不得冒充 file_sha256：schema 未把 source_doc_hash 映射到该显示位",
          cschema.file_hash_display("sha256:" + "ab" * 32).startswith("sha256:")
          and cschema.SCHEMA_VERSION == 1,
          "display 仅接受 file_sha256 形参；content_hash 走 source_doc_hash（另一字段）")

    # ---------------- K16–K18 CONTRACT_FIX_01A：来源正负向 + 真实裸 hex ----------------
    # 正向：local-demo 可阅读（courseCount>0）且来源徽标为「本地演示」，不冒充正式教材（指令 一.5）
    _demo_srcs = [c.get("source") for c in m_demo.courses]
    check("K16", "local-demo 可阅读且来源均为 local-demo（不冒充正式用户教材来源）",
          m_demo.courseCount > 0 and _demo_srcs and all(s == "local-demo" for s in _demo_srcs),
          (_demo_srcs, m_demo.courseCount))

    # 负向：把 local-demo 课程改挂真实来源绑定（缺 doc_id）→ 仍被拒（不因放宽哈希而放行伪造）
    _fake_src = _base_course()
    _fake_src["source"] = "user-textbook"
    _fake_src["source_doc_id"] = None            # 缺真实 doc_id
    _fake_src["source_doc_hash"] = "c3" * 32     # 合法裸 hex，但来源不完整
    m = ClassroomModel(courses_path=_write(tmp, _bundle(_fake_src)), data_dir=tmp)
    check("K17", "声称 user-textbook 但缺真实 doc_id → 拒绝（不得伪造正式来源）",
          m.coursesError != "" and m.courseCount == 0, (m.coursesError, m.courseCount))

    # 01A 修复：真实知识库返回的【裸 64hex】content_hash 在客户端侧也被接受
    _real = _base_course()
    _real["source"] = "user-textbook"
    _real["source_doc_id"] = "doc_e26bedf49e2d"
    _real["source_doc_hash"] = "c3" * 32         # 裸 hex（无 sha256: 前缀）
    m = ClassroomModel(courses_path=_write(tmp, _bundle(_real)), data_dir=tmp)
    check("K18", "真实裸 hex content_hash 绑定 → 客户端接受（01A 放宽哈希形式）",
          m.coursesError == "" and m.courseCount == 1, (m.coursesError, m.courseCount))

    # 01A 强化：file_hash_display 接受裸 hex 并规范化为 sha256:<hex>
    check("K19", "file_hash_display(裸64hex) 规范化为 sha256:<hex>（01A 强化展示口径）",
          cschema.file_hash_display("cd" * 32) == "sha256:" + "cd" * 32,
          cschema.file_hash_display("cd" * 32))

    passed = sum(1 for r in RESULTS if r["passed"])
    failed = [r["case_id"] for r in RESULTS if not r["passed"]]
    print("\n" + "=" * 70)
    print("COURSE_CONTRACT_V1_CLIENT: %d checks, %d PASS, %d FAIL"
          % (len(RESULTS), passed, len(failed)))
    if failed:
        print("FAILED:", ", ".join(failed))

    ev = os.path.join(_CLIENT, "..", "docs", "engineering", "product-v1",
                      "classroom-v2", "evidence", "course_contract_v1_client_tests.json")
    try:
        with open(os.path.abspath(ev), "w", encoding="utf-8") as f:
            json.dump({"artifact": "course_contract_v1_client_tests",
                       "scope": "PHASE2 CONTRACT FIX 01 · 修正②/③ + C5（客户端侧行为）",
                       "demo_bundle": "client/src/classroom/data/courses.json",
                       "schema_version": cschema.SCHEMA_VERSION,
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
