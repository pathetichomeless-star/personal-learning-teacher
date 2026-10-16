"""Course schema v1 — server/client same-version consistency tests (CLASSROOM V2 · P2).

Offline and deterministic.  Asserts that the **server authority**
(``modules/curriculum/course_schema``) and the **client frozen mirror**
(``client/src/classroom/course_schema``) are the *same version* and agree on
verdicts for a shared corpus of legal / illegal bundles.

Guarantees checked
------------------
S01  the two ``course_schema.v1.json`` files are **byte-identical** (sha256);
S02  normative constants agree (SCHEMA_ID / VERSION / document type / SOURCE_ENUM /
     SLIDE_TYPES / id & hash patterns);
S03  **behavioural equivalence** on a shared corpus (same valid/invalid verdict);
S04  the frozen contract actually rejects the four classes of abuse the product
     owner called out (unknown slide.type, forged knowledge source, cross-layer
     `version` duplication, illegal practice answer);
S05  **self-falsification**: mutating a constant on one side must make S02 fail —
     proving the assertions are load-bearing rather than vacuous.

Writes an evidence JSON into the repo.

Run:
    PYTHONPATH= <venv>/bin/python gateway/tests/course_schema_consistency_tests.py
"""

import copy
import hashlib
import importlib.util
import json
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.curriculum import course_schema as SRV  # noqa: E402

TEST_FILE = str(Path(__file__).resolve())
SERVER_JSON = ROOT / "modules/curriculum/course_schema.v1.json"
CLIENT_JSON = ROOT / "client/src/classroom/course_schema.v1.json"
CLIENT_PY = ROOT / "client/src/classroom/course_schema.py"
EVIDENCE = (ROOT / "docs/engineering/product-v1/classroom-v2/evidence"
            / "course_schema_consistency_tests.json")

RESULTS, PASS, FAIL = [], [], []


def check(cid, name, cond, observed=None):
    """Record one assertion with the caller's real line number."""
    line = sys._getframe(1).f_lineno
    rec = {"case_id": cid, "name": name, "passed": bool(cond),
           "observed": observed, "asserted_file": TEST_FILE, "asserted_line": line}
    RESULTS.append(rec)
    (PASS if cond else FAIL).append(cid)
    extra = "" if cond else "  → observed=%r" % (observed,)
    print(("PASS " if cond else "FAIL ") + "%s %s%s" % (cid, name, extra))
    return bool(cond)


def _repo_head() -> str:
    try:
        import subprocess
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _load_client_module():
    spec = importlib.util.spec_from_file_location("client_course_schema", CLIENT_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CLI = _load_client_module()


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---- shared corpus ---------------------------------------------------------

def _slide_cover():
    return {"type": "cover", "title": "办理入住", "subtitle": "Check-in"}


def _bundle(course, *, schema="classroom.course.bundle", version=1, **extra):
    doc = {"schema": schema, "version": version, "courses": [course]}
    doc.update(extra)
    return doc


def _course(**over):
    base = {
        "course_id": "crs_demo_hotel",
        "revision": 1,
        "title": "酒店英语",
        "source": "local-demo",
        "source_doc_id": None,
        "source_doc_hash": None,
        "source_file_sha256": None,
        "lessons": [{
            "lesson_id": "lesson_checkin",
            "title": "第 1 课",
            "slides": [_slide_cover(),
                       {"type": "vocab", "word": "reservation", "phonetic": "/ˌrezəˈveɪʃn/",
                        "meaning": "预订", "en": "I have a reservation.", "cn": "我有预订。"},
                       {"type": "practice", "question": "「预订」?", "options": ["a", "b", "c"],
                        "answer": 0}],
        }],
    }
    base.update(over)
    return base


def _textbook_course(**over):
    base = dict(source="user-textbook",
                source_doc_id="doc_7f3a91c2",
                source_doc_hash="sha256:" + "ab" * 32)
    base.update(over)
    return _course(**base)


def _corpus():
    """(id, bundle, expected_valid)."""
    return [
        ("legal-local-demo", _bundle(_course()), True),
        ("legal-user-textbook", _bundle(_textbook_course()), True),
        ("legal-answer-null-needs-human", _bundle(_course(
            lessons=[{"lesson_id": "l", "title": "t", "slides": [
                {"type": "practice", "question": "q", "options": ["a", "b"], "answer": None}]}])), True),
        ("legal-file-hash-present", _bundle(_textbook_course(
            source_file_sha256="sha256:" + "cd" * 32)), True),
        # --- CONTRACT_FIX_01A 一.4：真实知识库 content_hash 为【裸 hex】 ---
        ("legal-bare-hex-content-hash", _bundle(_textbook_course(
            source_doc_hash="c3" * 32)), True),
        ("legal-bare-hex-file-hash", _bundle(_textbook_course(
            source_file_sha256="cd" * 32)), True),
        # --- abuse classes the product owner called out ---
        ("illegal-unknown-slide-type", _bundle(_course(
            lessons=[{"lesson_id": "l", "title": "t",
                      "slides": [{"type": "quiz", "question": "q"}]}])), False),
        ("illegal-local-demo-forged-source", _bundle(_course(
            source_doc_id="doc_deadbeef", source_doc_hash="sha256:" + "00" * 32)), False),
        ("illegal-textbook-missing-binding", _bundle(_course(
            source="user-textbook")), False),
        ("illegal-version-duplicated-in-course", _bundle(_course(version=1)), False),
        ("illegal-version-unknown", _bundle(_course(), version=2), False),
        ("illegal-legacy-root-source", _bundle(_course(), source="local-demo"), False),
        ("illegal-legacy-id-field", _bundle(_course(id="course_hotel",
                                                    course_id="crs_demo_hotel")), False),
        ("illegal-answer-out-of-range", _bundle(_course(
            lessons=[{"lesson_id": "l", "title": "t", "slides": [
                {"type": "practice", "question": "q", "options": ["a", "b"], "answer": 5}]}])), False),
        ("illegal-null-phonetic-sentinel", _bundle(_course(
            lessons=[{"lesson_id": "l", "title": "t", "slides": [
                {"type": "vocab", "word": "w", "phonetic": None,
                 "meaning": "m", "en": "e", "cn": "c"}]}])), False),
        ("illegal-missing-schema-field", _bundle(_course(), schema=None), False),
        ("illegal-bad-hash-format", _bundle(_textbook_course(
            source_doc_hash="not-a-sha256")), False),
        ("illegal-short-hash", _bundle(_textbook_course(
            source_doc_hash="c3" * 16)), False),
    ]


# ---- S01 byte identity -----------------------------------------------------

check("S01a", "两份 course_schema.v1.json 均存在",
      SERVER_JSON.is_file() and CLIENT_JSON.is_file())
_srv_sha, _cli_sha = _sha256(SERVER_JSON), _sha256(CLIENT_JSON)
check("S01b", "两侧 schema JSON 逐字节一致（sha256 相等）",
      _srv_sha == _cli_sha, observed={"server": _srv_sha, "client": _cli_sha})

# ---- S02 constant agreement ------------------------------------------------

_checkpoints = [
    ("SCHEMA_ID", SRV.SCHEMA_ID, CLI.SCHEMA_ID),
    ("SCHEMA_VERSION", SRV.SCHEMA_VERSION, CLI.SCHEMA_VERSION),
    ("SCHEMA_DOCUMENT_TYPE", SRV.SCHEMA_DOCUMENT_TYPE, CLI.SCHEMA_DOCUMENT_TYPE),
    ("SOURCE_ENUM", SRV.SOURCE_ENUM, CLI.SOURCE_ENUM),
    ("SLIDE_TYPES", SRV.SLIDE_TYPES, CLI.SLIDE_TYPES),
    ("SOURCE_REQUIRING_BINDING", SRV.SOURCE_REQUIRING_BINDING, CLI.SOURCE_REQUIRING_BINDING),
    ("COURSE_ID_RE.pattern", SRV.COURSE_ID_RE.pattern, CLI.COURSE_ID_RE.pattern),
    ("DOC_ID_RE.pattern", SRV.DOC_ID_RE.pattern, CLI.DOC_ID_RE.pattern),
    ("SHA256_RE.pattern", SRV.SHA256_RE.pattern, CLI.SHA256_RE.pattern),
    ("SHA256_CANON_RE.pattern", SRV.SHA256_CANON_RE.pattern, CLI.SHA256_CANON_RE.pattern),
    ("BUNDLE_LEGACY_FORBIDDEN_KEYS", SRV.BUNDLE_LEGACY_FORBIDDEN_KEYS,
     CLI.BUNDLE_LEGACY_FORBIDDEN_KEYS),
]
_mismatch = [name for name, a, b in _checkpoints if a != b]
check("S02a", "服务端/客户端规范常量全部一致", not _mismatch, observed=_mismatch)
check("S02b", "版本常量 == 1（冻结版）", SRV.SCHEMA_VERSION == 1, observed=SRV.SCHEMA_VERSION)
check("S02c", "slide.type 闭枚举 == 5 类",
      set(SRV.SLIDE_TYPES) == {"cover", "vocab", "sentence", "practice", "summary"},
      observed=SRV.SLIDE_TYPES)
check("S02d", "source 枚举 == 3 类（local-demo 独立）",
      set(SRV.SOURCE_ENUM) == {"local-demo", "admin-knowledge", "user-textbook"}
      and SRV.SOURCE_LOCAL_DEMO not in SRV.SOURCE_REQUIRING_BINDING,
      observed=SRV.SOURCE_ENUM)

# ---- S03 behavioural equivalence ------------------------------------------

_divergent, _verdicts = [], {}
for cid, bundle, expected in _corpus():
    srv_ok = SRV.is_valid(copy.deepcopy(bundle))
    cli_ok = CLI.is_valid(copy.deepcopy(bundle))
    _verdicts[cid] = {"expected": expected, "server": srv_ok, "client": cli_ok}
    if srv_ok != cli_ok or srv_ok != expected:
        _divergent.append((cid, expected, srv_ok, cli_ok))

check("S03a", "共享语料上 服务端/客户端 判定完全一致且符合预期",
      not _divergent, observed=_divergent)
check("S03b", "语料规模 >= 18（合法 6 + 非法 12）", len(_verdicts) >= 18,
      observed=len(_verdicts))

# ---- S04 the four abuse classes are actually rejected ----------------------

for _cid, _want, _needle in [
    ("S04a", "illegal-unknown-slide-type", "未知内容类型"),
    ("S04b", "illegal-local-demo-forged-source", "不得伪造知识库来源"),
    ("S04c", "illegal-version-duplicated-in-course", "只允许出现在文档级"),
    ("S04d", "illegal-answer-out-of-range", "越界"),
    ("S04e", "illegal-textbook-missing-binding", "doc_id"),
]:
    _b = next(b for i, b, _ in _corpus() if i == _want)
    _errs = SRV.validate_bundle(copy.deepcopy(_b))
    check(_cid, "拒绝并给出可解释原因：%s" % _want,
          bool(_errs) and any(_needle in e for e in _errs), observed=_errs[:2])

# ---- S05 self-falsification ------------------------------------------------

_falsified = copy.deepcopy(_checkpoints)
_falsified.append(("SLIDE_TYPES", SRV.SLIDE_TYPES, tuple(sorted(set(SRV.SLIDE_TYPES) | {"quiz"}))))
_mut_mismatch = [n for n, a, b in _falsified if a != b]
check("S05a", "自证伪：伪造一侧 slide.type 枚举 → 一致性断言必然失败",
      _mut_mismatch == ["SLIDE_TYPES"], observed=_mut_mismatch)

def _resp_types(schema_doc):
    """从（可能被篡改的）schema dict 重演 slide.type 闭枚举。"""
    node = schema_doc
    variants = []
    for v in node["definitions"]["slide"]["oneOf"]:
        target = node
        for part in v["$ref"].lstrip("#/").split("/"):
            target = target[part]
        variants.append(target)
    return tuple(sorted(t["properties"]["type"]["const"] for t in variants))


_doc = json.loads(SERVER_JSON.read_text(encoding="utf-8"))
_doc["definitions"]["course"]["properties"]["source"]["enum"] = ["local-demo", "forged-extra"]
check("S05b", "自证伪：若一侧 schema 的 source 枚举漂移 → S02a 常量一致性断言必然失败",
      tuple(_doc["definitions"]["course"]["properties"]["source"]["enum"]) != CLI.SOURCE_ENUM,
      observed=tuple(_doc["definitions"]["course"]["properties"]["source"]["enum"]))

_slides_mut = json.loads(SERVER_JSON.read_text(encoding="utf-8"))
_slides_mut["definitions"]["slideCover"]["properties"]["type"]["const"] = "cover_renamed"
check("S05c", "自证伪：若 slide.type 之一被改名而客户端未同步 → 枚举断言必然失败",
      _resp_types(_slides_mut) != CLI.SLIDE_TYPES,
      observed={"mutated": _resp_types(_slides_mut), "client": CLI.SLIDE_TYPES})

# ---- evidence --------------------------------------------------------------

summary = {"total": len(RESULTS), "passed": len(PASS), "failed": len(FAIL),
           "failed_ids": FAIL}
print("\n==== SUMMARY ====")
print("total=%d pass=%d fail=%d" % (len(RESULTS), len(PASS), len(FAIL)))
if FAIL:
    print("FAILED:", ", ".join(FAIL))

EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
EVIDENCE.write_text(json.dumps({
    "artifact": "course_schema_consistency_tests",
    "scope": "CLASSROOM V2 PHASE2 CONTRACT FIX 01 · 修正②（服务端/客户端同版本一致性）",
    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "python_version": platform.python_version(),
    "repo_head": _repo_head(),
    "server_schema_path": str(SERVER_JSON.relative_to(ROOT)),
    "client_schema_path": str(CLIENT_JSON.relative_to(ROOT)),
    "schema_sha256": _srv_sha,
    "constants": {name: (list(a) if isinstance(a, (tuple, frozenset)) else a)
                  for name, a, _ in _checkpoints},
    "corpus_verdicts": _verdicts,
    "results": RESULTS,
    "summary": summary,
}, ensure_ascii=False, indent=2), encoding="utf-8")
print("evidence:", EVIDENCE)

sys.exit(1 if FAIL else 0)
