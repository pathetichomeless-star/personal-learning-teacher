# -*- coding: utf-8 -*-
"""Knowledge-base real-sample format verification (CLASSROOM V2 · CONTRACT_FIX_01A 一.4).

Purpose
-------
Verify that the **frozen course Schema v1 regexes** actually match the *real*
values the existing knowledge base returns — using the real ``KnowledgeStore``
in an **isolated temporary directory** (production storage is never touched).

Motivation (the conflict this test closes)
------------------------------------------
``AGENT_PLAN §8.3`` binds a course to a knowledge document via
``source_doc_id`` + ``source_doc_hash`` (= the document's ``content_hash``).
BEFORE 01A the schema required ``^sha256:[0-9a-f]{64}$`` — but the real
``KnowledgeStore`` emits a **bare 64-hex** string with no ``sha256:`` prefix
(``store.py:140 _content_hash`` → ``hashlib.sha256(...).hexdigest()``;
``store.py:623 doc_id = "doc_" + uuid.uuid4().hex[:12]``).  A real user-textbook
course therefore FAILED schema validation.  01A widens the hash pattern to
accept both ``<64hex>`` and ``sha256:<64hex>``.

Guarantees checked
------------------
H01  a real document's ``doc_id`` matches ``DOC_ID_RE`` (``^doc_[A-Za-z0-9]{4,64}$``);
H02  its real ``content_hash`` matches the (widened) ``SHA256_RE`` — bare hex accepted;
H03  the same ``content_hash`` ALSO matches the strict canonical ``SHA256_CANON_RE`` after
     normalisation via ``canonical_sha256`` (prefix added);
H04  a course bound to these REAL values is schema-valid (end-to-end bridge);
H05  ``source_doc_hash`` and ``source_file_sha256`` are semantically distinct:
     a file's byte hash differs from its extracted-text content hash (no impersonation);
H06  a forged/non-existent binding format is still rejected (fail-closed, not weakened);
H07  the store was opened in an isolated temp dir and production storage was NOT touched.

Writes an evidence JSON into the repo.

Run:
    PYTHONPATH= <venv>/bin/python gateway/tests/knowledge_hash_format_tests.py
"""

import hashlib
import json
import platform
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.knowledge.store import KnowledgeStore          # noqa: E402
from modules.curriculum import course_schema as CS          # noqa: E402

TEST_FILE = str(Path(__file__).resolve())
EVIDENCE = (ROOT / "docs/engineering/product-v1/classroom-v2/evidence"
            / "knowledge_hash_format_tests.json")

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


def _repo_head() -> str:
    try:
        import subprocess
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


# ---- isolated real store (production untouched) ----------------------------

_TMP = Path(tempfile.mkdtemp(prefix="xz-classroom-kbformat-"))
_KB_PATH = _TMP / "knowledge.json"
_TEXT = ("Hotel English — Lesson 1. I would like to make a reservation. "
         "请问有双人房吗？The room rate is 320 per night.")
_FILE_BYTES = ("%PDF-1.7 fake-bytes for classroom format probe\n".encode("utf-8"))
_FILE_NAME = "user-textbook-sample.pdf"

_store = KnowledgeStore(str(_KB_PATH))
_ds = _store.create_dataset("classroom-probe", description="01A format verification")
_doc = _store.add_document(_ds["id"], _FILE_NAME, _TEXT,
                           source_type="pdf_text", source_uri="local://" + _FILE_NAME)

REAL_DOC_ID = _doc["id"]
REAL_CONTENT_HASH = _doc["content_hash"]

# ---- H01 doc_id format -----------------------------------------------------

check("H01a", "真实 doc_id 匹配 DOC_ID_RE（^doc_[A-Za-z0-9]{4,64}$）",
      bool(CS.DOC_ID_RE.match(REAL_DOC_ID)), observed=REAL_DOC_ID)
check("H01b", "真实 doc_id 前缀为 doc_",
      isinstance(REAL_DOC_ID, str) and REAL_DOC_ID.startswith("doc_"),
      observed=REAL_DOC_ID[:8] + "…")

# ---- H02 content_hash is BARE hex (the conflict 01A closes) -----------------

check("H02a", "真实 content_hash 为裸 64hex 且匹配（放宽后的）SHA256_RE",
      bool(CS.SHA256_RE.match(REAL_CONTENT_HASH)), observed=REAL_CONTENT_HASH)
check("H02b", "真实 content_hash 长度为 64",
      isinstance(REAL_CONTENT_HASH, str) and len(REAL_CONTENT_HASH) == 64,
      observed=len(REAL_CONTENT_HASH) if isinstance(REAL_CONTENT_HASH, str) else None)
check("H02c", "真实 content_hash 不含 sha256: 前缀（证明旧严格正则会误拒）",
      isinstance(REAL_CONTENT_HASH, str) and not REAL_CONTENT_HASH.startswith("sha256:"),
      observed=REAL_CONTENT_HASH[:12] + "…")
# 记录：旧严格正则（^sha256:[0-9a-f]{64}$）对真实值的判定，作为「冲突证据」留存
import re as _re  # noqa: E402
_STRICT = _re.compile(r"^sha256:[0-9a-f]{64}$")
check("H02d", "旧严格正则 ^sha256:[0-9a-f]{64}$ 对真实 content_hash 判定为【不匹配】（冲突证据）",
      not bool(_STRICT.match(REAL_CONTENT_HASH)), observed="strict_rejects_real_value")

# ---- H03 canonicalisation ---------------------------------------------------

check("H03a", "canonical_sha256(真实 content_hash) == sha256:<同 hex>",
      CS.canonical_sha256(REAL_CONTENT_HASH) == "sha256:" + REAL_CONTENT_HASH,
      observed=CS.canonical_sha256(REAL_CONTENT_HASH))
check("H03b", "规范化后满足 Canonical（前缀）形式 SHA256_CANON_RE",
      bool(CS.SHA256_CANON_RE.match(CS.canonical_sha256(REAL_CONTENT_HASH) or "")),
      observed=CS.canonical_sha256(REAL_CONTENT_HASH))

# ---- H04 end-to-end: a REAL-bound course validates --------------------------

REAL_COURSE = {
    "course_id": "crs_probe_realbinding",
    "revision": 1,
    "title": "真实来源课程（格式核验）",
    "source": "user-textbook",
    "source_doc_id": REAL_DOC_ID,
    "source_doc_hash": REAL_CONTENT_HASH,          # ← 裸 hex，直接来自真实 store
    "source_file_sha256": None,                     # 原文件哈希待确认
    "lessons": [{"lesson_id": "l1", "title": "Lesson 1",
                 "slides": [{"type": "cover", "title": "Hotel English"}]}],
}
REAL_BUNDLE = {"schema": "classroom.course.bundle", "version": 1,
               "courses": [REAL_COURSE]}
_errors = CS.validate_bundle(REAL_BUNDLE)
check("H04a", "绑定【真实】KnowledgeStore 返回值的课程通过冻结 schema v1 校验",
      not _errors, observed=_errors[:3])
check("H04b", "该绑定的 source_doc_id/source_doc_hash 与 store 返回值逐字相等",
      REAL_COURSE["source_doc_id"] == REAL_DOC_ID
      and REAL_COURSE["source_doc_hash"] == REAL_CONTENT_HASH)

# ---- H05 file-hash vs content-hash are distinct -----------------------------

FILE_SHA = hashlib.sha256(_FILE_BYTES).hexdigest()
check("H05a", "原文件字节哈希 != 知识库 content_hash（抽取文本哈希）—— 语义确实不同",
      FILE_SHA != REAL_CONTENT_HASH, observed={"file": FILE_SHA[:12] + "…",
                                               "content": REAL_CONTENT_HASH[:12] + "…"})
_b = json.loads(json.dumps(REAL_BUNDLE))
_b["courses"][0]["source_file_sha256"] = FILE_SHA   # 裸 hex 也应被接受
check("H05b", "同时携带真实原文件哈希（裸 hex）仍通过校验",
      not CS.validate_bundle(_b), observed=CS.validate_bundle(_b)[:3])
check("H05c", "sha256_matches 判定 裸hex 与 sha256:前缀 为同一摘要（比较口径统一）",
      CS.sha256_matches(REAL_CONTENT_HASH, "sha256:" + REAL_CONTENT_HASH))

# ---- H08 CONTRACT_FIX_01A 一.3：source_doc_hash × content_hash 四种组合交叉 ----
# 绑定校验必须对「裸 hex」与「sha256: 前缀」**同类型规范化后比较**：
#   (a) 裸   ↔ 裸    → 同一摘要 → True
#   (b) 裸   ↔ 前缀  → 同一摘要 → True   ← 01A 前会因字符串不等而误判不一致
#   (c) 前缀 ↔ 裸    → 同一摘要 → True
#   (d) 前缀 ↔ 前缀  → 同一摘要 → True
_HEX = REAL_CONTENT_HASH
_PRE = "sha256:" + _HEX
check("H08a", "交叉 (a) 裸hex ↔ 裸hex ⇒ 同一摘要", CS.sha256_matches(_HEX, _HEX) is True,
      observed="bare↔bare")
check("H08b", "交叉 (b) 裸hex(课程 source_doc_hash) ↔ 前缀(store) ⇒ 同一摘要",
      CS.sha256_matches(_HEX, _PRE) is True, observed="bare↔prefixed")
check("H08c", "交叉 (c) 前缀(课程 source_doc_hash) ↔ 裸hex(store) ⇒ 同一摘要",
      CS.sha256_matches(_PRE, _HEX) is True, observed="prefixed↔bare")
check("H08d", "交叉 (d) 前缀 ↔ 前缀 ⇒ 同一摘要", CS.sha256_matches(_PRE, _PRE) is True,
      observed="prefixed↔prefixed")
check("H08e", "不同摘要不得因规范化而被误判相同（比较仍具判别力）",
      CS.sha256_matches(_HEX, "sha256:" + "00" * 32) is False
      and CS.sha256_matches("not-a-hash", _HEX) is False, observed="distinct/illegal")
# 端到端：课程以【前缀形式】绑定真实 store 的【裸 hex】content_hash 也必须通过校验
_b2 = json.loads(json.dumps(REAL_BUNDLE))
_b2["courses"][0]["source_doc_hash"] = _PRE
check("H08f", "课程用 sha256: 前缀形式绑定真实 store 裸 hex ⇒ 仍通过冻结 schema 校验",
      not CS.validate_bundle(_b2), observed=CS.validate_bundle(_b2)[:2])

# ---- H06 forged binding still rejected (not weakened) -----------------------

_forged = json.loads(json.dumps(REAL_BUNDLE))
_forged["courses"][0]["source_doc_hash"] = "not-a-valid-hash"
check("H06a", "伪造/非法哈希仍被拒绝（fail-closed 未被放宽削弱）",
      not CS.is_valid(_forged), observed=CS.validate_bundle(_forged)[:2])

_forged2 = json.loads(json.dumps(REAL_BUNDLE))
_forged2["courses"][0]["source_doc_id"] = "document-123"      # 缺 doc_ 前缀
check("H06b", "非 doc_ 前缀的 doc_id 仍被拒绝",
      not CS.is_valid(_forged2), observed=CS.validate_bundle(_forged2)[:1])

# ---- H07 isolation ----------------------------------------------------------

_isolated = str(_KB_PATH).startswith(tempfile.gettempdir()) and "xz-classroom-kbformat-" in str(_KB_PATH)
check("H07a", "知识库打开于隔离临时目录（未触碰生产存储）",
      _isolated, observed=str(_KB_PATH))
check("H07b", "随机生成的 doc_id 两次调用不相同（非固定桩值）",
      _store.add_document(_ds["id"], "second", _TEXT + " v2")["id"] != REAL_DOC_ID)

# ---- evidence ---------------------------------------------------------------

summary = {"total": len(RESULTS), "passed": len(PASS), "failed": len(FAIL),
           "failed_ids": FAIL}
print("\n==== SUMMARY ====")
print("total=%d pass=%d fail=%d" % (len(RESULTS), len(PASS), len(FAIL)))
if FAIL:
    print("FAILED:", ", ".join(FAIL))

EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
EVIDENCE.write_text(json.dumps({
    "artifact": "knowledge_hash_format_tests",
    "scope": "CLASSROOM V2 CONTRACT_FIX_01A 一.4（真实知识库返回样本 × Schema 正则核验）",
    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "python_version": platform.python_version(),
    "repo_head": _repo_head(),
    "isolated_store_path": str(_KB_PATH),
    "production_storage_touched": False,
    "real_sample": {
        "doc_id": REAL_DOC_ID,
        "content_hash": REAL_CONTENT_HASH,
        "content_hash_len": len(REAL_CONTENT_HASH),
        "has_sha256_prefix": REAL_CONTENT_HASH.startswith("sha256:"),
        "file_sha256_of_probe_bytes": FILE_SHA,
    },
    "schema_patterns": {
        "DOC_ID_RE": CS.DOC_ID_RE.pattern,
        "SHA256_RE": CS.SHA256_RE.pattern,
        "SHA256_CANON_RE": CS.SHA256_CANON_RE.pattern,
    },
    "conflict_evidence": {
        "old_strict_pattern": _STRICT.pattern,
        "old_strict_rejects_real_content_hash": bool(not _STRICT.match(REAL_CONTENT_HASH)),
        "resolution": "01A 放宽 SHA256_RE 为 ^(?:sha256:)?[0-9a-f]{64}$，接受裸 hex 与前缀形式",
    },
    "results": RESULTS,
    "summary": summary,
}, ensure_ascii=False, indent=2), encoding="utf-8")
print("evidence:", EVIDENCE)

# cleanup isolated temp dir (never production)
try:
    for _p in sorted(_TMP.glob("**/*"), reverse=True):
        if _p.is_file():
            _p.unlink()
        elif _p.is_dir():
            _p.rmdir()
except Exception:  # noqa: BLE001
    pass

sys.exit(1 if FAIL else 0)
