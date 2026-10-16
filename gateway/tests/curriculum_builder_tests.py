# -*- coding: utf-8 -*-
"""Curriculum builder + phonetics behaviour tests (CLASSROOM V2 · Agent E · Phase 2).

Verifies the *runnable* textbook→course engine, not a design claim:

E01  local-demo course builds and validates; three source bindings forced null;
E02  user-textbook course with a REAL binding builds and validates;
E03  user-textbook course WITHOUT a binding FAILS validation (fail-closed);
E04  unknown item ``kind`` raises (never silently skipped);
E05  illegal/missing practice ``answer`` → ``None`` + surfaced in needs_review
     (never defaulted to 0/-1 — the C5 defect class);
E06  a valid practice ``answer`` is preserved verbatim;
E07  known word → real en-GB (RP) IPA is attached;
E08  unknown word → ``phonetic`` **omitted** (no null sentinel, no invented IPA);
E09  no "Day N" / fixed 20-day structure leaks in; unit count is preserved;
E10  ``make_course_id`` always satisfies the frozen ``crs_…`` pattern;
E11  empty units → raises (no empty course);
E12  every lesson has an auto cover + auto summary;
E13  schema invariants: version only at doc level, source only at course level.

Run:
    PYTHONPATH= <venv>/bin/python gateway/tests/curriculum_builder_tests.py
"""

import json
import platform
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.curriculum import course_schema as CS          # noqa: E402
from modules.curriculum import phonetics as PH              # noqa: E402
from modules.curriculum import builder as B                 # noqa: E402

TEST_FILE = str(Path(__file__).resolve())
EVIDENCE = (ROOT / "docs/engineering/product-v1/classroom-v2/evidence"
            / "curriculum_builder_tests.json")

RESULTS, PASS, FAIL = [], [], []


def check(cid, name, cond, observed=None):
    line = sys._getframe(1).f_lineno
    rec = {"case_id": cid, "name": name, "passed": bool(cond),
           "observed": observed, "asserted_file": TEST_FILE, "asserted_line": line}
    RESULTS.append(rec)
    (PASS if cond else FAIL).append(cid)
    extra = "" if cond else "  → observed=%r" % (observed,)
    print(("PASS " if cond else "FAIL ") + "%s %s%s" % (cid, name, extra))
    return bool(cond)


def _repo_head():
    try:
        import subprocess
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


UNITS = [
    {"title": "办理入住 Check-in",
     "items": [
         {"kind": "vocab", "word": "reservation", "meaning": "预订",
          "en": "I have a reservation.", "cn": "我有预订。"},
         {"kind": "vocab", "word": "zyxwvu", "meaning": "（生僻词）",
          "en": "zyxwvu", "cn": "生僻词"},
         {"kind": "sentence", "en": "I would like a double room.", "cn": "我想要一间双人房。"},
         {"kind": "practice", "question": "「预订」怎么说？",
          "options": ["reservation", "luggage"], "answer": 0},
     ]},
    {"title": "退房 Check-out",
     "items": [
         {"kind": "vocab", "word": "luggage", "meaning": "行李",
          "en": "This is my luggage.", "cn": "这是我的行李。"},
     ]},
]

# ---- E01 local-demo ----
rep = B.build_local_demo(title="酒店英语（演示）", units=UNITS)
doc = rep.bundle
check("E01a", "local-demo 课程构建并通过冻结 schema v1 校验", CS.is_valid(doc))
check("E01b", "local-demo 三个来源绑定字段全为 null（不得伪造来源）",
      all(c["source_doc_id"] is None and c["source_doc_hash"] is None
          and c["source_file_sha256"] is None for c in doc["courses"]))
check("E01c", "doc 级不含 source（来源只在 course 级）", "source" not in doc)

# ---- E02/E03 user-textbook binding ----
_real_bind = dict(source="user-textbook",
                  source_doc_id="doc_e26bedf49e2d",
                  source_doc_hash="c3" * 32)
c2 = B.build_course(title="教材甲", units=UNITS, **dict(_real_bind, course_id="crs_textbook_a"))
_rep2 = B.build_bundle(courses=[c2], label="我的教材")
check("E02", "user-textbook 携带真实绑定 → 校验通过（含裸 hex content_hash）",
      CS.is_valid(_rep2.bundle))
try:
    B.build_bundle(courses=[B.build_course(title="教材乙", units=UNITS, source="user-textbook",
                                           course_id="crs_textbook_b")])
    _missing_ok = False
except CS.CourseSchemaError:
    _missing_ok = True
check("E03", "user-textbook 缺绑定 → 构建即失败（fail-closed）", _missing_ok)

# ---- E04 unknown kind ----
try:
    B.build_bundle(courses=[B.build_course(
        title="坏课", units=[{"title": "u", "items": [{"kind": "quiz", "q": "?"}]}])])
    _unknown_ok = False
except ValueError as e:
    _unknown_ok = "未知条目类型" in str(e)
check("E04", "未知条目 kind → 抛错（不得静默跳过）", _unknown_ok)

# ---- E05/E06 practice answer ----
rep5 = B.build_local_demo(title="答案测试", units=[{"title": "u", "items": [
    {"kind": "practice", "question": "q1", "options": ["a", "b"], "answer": 5},   # 越界
    {"kind": "practice", "question": "q2", "options": ["a", "b"]},               # 缺失
]}])
_slides = rep5.bundle["courses"][0]["lessons"][0]["slides"]
_pr = [s for s in _slides if s["type"] == "practice"]
check("E05a", "非法/缺失答案 → answer=None（绝不落 0/-1）",
      all(s["answer"] is None for s in _pr), [s["answer"] for s in _pr])
check("E05b", "不确定项被记入 needs_review（可见，不静默）",
      sum(1 for r in rep5.needs_review if r["reason"] == "answer_needs_human") == 2,
      rep5.needs_review)
rep6 = B.build_local_demo(title="答案保留", units=[{"title": "u", "items": [
    {"kind": "practice", "question": "q", "options": ["a", "b", "c"], "answer": 2}]}])
_pr6 = [s for s in rep6.bundle["courses"][0]["lessons"][0]["slides"] if s["type"] == "practice"]
check("E06", "合法答案 2 原样保留", _pr6 and _pr6[0]["answer"] == 2,
      _pr6[0]["answer"] if _pr6 else None)

# ---- E07/E08 phonetics ----
_vocab = [s for s in doc["courses"][0]["lessons"][0]["slides"] if s["type"] == "vocab"]
_known = next(s for s in _vocab if s["word"] == "reservation")
_unknown = next(s for s in _vocab if s["word"] == "zyxwvu")
check("E07", "已知词填入真实 en-GB (RP) 音标", _known.get("phonetic") == "ˌrezəˈveɪʃn",
      _known.get("phonetic"))
check("E07b", "音标口音标签为 en-GB (RP)（不冒充美音）",
      PH.accent() == "en-GB (RP)", PH.accent())
check("E08", "未知词省略 phonetic 字段（既不写 null 也不编造）",
      "phonetic" not in _unknown, _unknown)

# ---- E09 no 20-day plan; unit count preserved ----
_blob = json.dumps(doc, ensure_ascii=False)
check("E09a", "输出不含固定 20 天计划痕迹（Day N / 20 天）",
      not re.search(r"\bDay\s*\d+", _blob) and "20 天" not in _blob)
check("E09b", "课时数 == 用户教材 unit 数（2）", len(doc["courses"][0]["lessons"]) == 2,
      len(doc["courses"][0]["lessons"]))

# ---- E10 course_id pattern ----
_ids = [B.make_course_id(n) for n in ("酒店英语", "A", "x", "Long Name With Spaces 1234567890")]
check("E10", "make_course_id 全部满足 ^crs_[A-Za-z0-9_-]{4,64}$",
      all(CS.COURSE_ID_RE.match(i) for i in _ids), _ids)

# ---- E11 empty units ----
try:
    B.build_course(title="空", units=[])
    _empty_ok = False
except ValueError:
    _empty_ok = True
check("E11", "空 units → 抛错（不生成空课程）", _empty_ok)

# ---- E12 auto cover + summary ----
_lessons = doc["courses"][0]["lessons"]
check("E12", "每课自动含 cover 与 summary 幻灯片",
      all(l["slides"][0]["type"] == "cover" and any(s["type"] == "summary" for s in l["slides"])
          for l in _lessons))

# ---- E13 layer invariants ----
check("E13a", "version 只在文档级（course 内无 version）",
      doc["version"] == 1 and all("version" not in c for c in doc["courses"]))
check("E13b", "source 只在 course 级", all("source" in c for c in doc["courses"]))

# ---- evidence ----
summary = {"total": len(RESULTS), "passed": len(PASS), "failed": len(FAIL), "failed_ids": FAIL}
print("\n==== SUMMARY ====")
print("total=%d pass=%d fail=%d" % (len(RESULTS), len(PASS), len(FAIL)))
if FAIL:
    print("FAILED:", ", ".join(FAIL))

EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
EVIDENCE.write_text(json.dumps({
    "artifact": "curriculum_builder_tests",
    "scope": "CLASSROOM V2 PHASE2 · Agent E（教材→课程生成 + 音标）",
    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "python_version": platform.python_version(),
    "repo_head": _repo_head(),
    "phonetics_words": PH.known_count(),
    "accent_label": PH.accent(),
    "sample_bundle_course_count": len(doc["courses"]),
    "results": RESULTS,
    "summary": summary,
}, ensure_ascii=False, indent=2), encoding="utf-8")
print("evidence:", EVIDENCE)

sys.exit(1 if FAIL else 0)
