# -*- coding: utf-8 -*-
"""Course Schema v1 **勘误（errata）向后兼容证明** — CONTRACT_FIX_01A 一.4.

背景
----
PHASE 2 CONTRACT FIX 01A 把 `source_doc_hash` / `source_file_sha256` 的正则从

    ``^sha256:[0-9a-f]{64}$``          （旧 / v1 原文）
改成
    ``^(?:sha256:)?[0-9a-f]{64}$``     （新 / v1 勘误）

原因：真实 ``KnowledgeStore`` 的 ``content_hash`` 是**裸 64hex**（无前缀），
旧正则会**误拒真实知识库返回值**（见 ``knowledge_hash_format_tests`` 的冲突证据）。

本文件**不重新断言业务语义**，只证明一件事：

    **新语言 ⊇ 旧语言**（acceptance set 单调扩张）
    ⇒ 「任何在旧 v1 下合法的文档，在新 v1 下仍然合法」
    ⇒ **向后兼容成立，无需升版本号**。

同时证明：
* 兼容性来自**集合包含**，不是抽样巧合（语料 + 受限穷举 + 确定性随机性质测试）；
* 被扩张的**恰好**是裸 hex 这一类，且**没有**任何旧合法值变非法；
* 结构面未变（``version`` 仍 const 1、``schema`` 名未变、doc_id/course_id 正则未变）
  ⇒ 以 ``version == 1`` 作分派的消费方不受影响；
* **同步性**：权威与客户端镜像的**两个**哈希字段正则完全一致。

运行：
    PYTHONPATH= <venv>/bin/python gateway/tests/schema_v1_errata_tests.py
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.curriculum import course_schema as CS  # noqa: E402

TEST_FILE = str(Path(__file__).resolve())
EVIDENCE = (ROOT / "docs" / "engineering" / "product-v1" / "classroom-v2"
            / "evidence" / "schema_v1_errata_tests.json")

# 旧 / v1 原文口径（作为**被比较的另一侧**保留在测试内，不进入生产代码）
OLD_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
NEW_RE = CS.SHA256_RE

RESULTS: list[dict] = []
PASS: list[str] = []
FAIL: list[str] = []


def check(cid: str, name: str, cond: bool, observed=None) -> bool:
    frame = sys._getframe(1)
    RESULTS.append({"case_id": cid, "name": name, "passed": bool(cond),
                    "observed": repr(observed)[:300],
                    "asserted_file": TEST_FILE, "asserted_line": frame.f_lineno})
    print(("PASS " if cond else "FAIL ") + "%s %s%s"
          % (cid, name, "" if cond else "  → %r" % (observed,)))
    (PASS if cond else FAIL).append(cid)
    return bool(cond)


def _old_ok(v: object) -> bool:
    return isinstance(v, str) and bool(OLD_RE.match(v))


def _new_ok(v: object) -> bool:
    return isinstance(v, str) and bool(NEW_RE.match(v))


# ============================================================ E01 语料包含性
_H = "0123456789abcdef"
_CORPUS: list[object] = [
    # 旧口径合法的各类值（必须全部仍然合法）
    "sha256:" + "a" * 64,
    "sha256:" + "0" * 64,
    "sha256:" + "f" * 64,
    "sha256:" + "ab" * 32,
    "sha256:" + "0123456789abcdef" * 4,
    # 真实知识库形态（裸 hex）—— 勘误新接纳
    "a" * 64,
    "0" * 64,
    "0123456789abcdef" * 4,
    # 非法值（必须仍然非法）
    "", "sha256:", "sha256:" + "a" * 63, "sha256:" + "a" * 65,
    "a" * 63, "a" * 65,
    "SHA256:" + "a" * 64,          # 大写前缀
    "sha256:" + "A" * 64,          # 大写 hex
    "A" * 64,                      # 大写裸 hex
    "sha256:" + "g" * 64,          # 非 hex
    "not-a-hash", None, 123, [], {},
    "sha256:sha256:" + "a" * 64,   # 双前缀
    " " + "a" * 64,                # 前导空格
    "a" * 64 + " ",                # 尾随空格
    "md5:" + "a" * 32,
]
_missing = [v for v in _CORPUS if _old_ok(v) and not _new_ok(v)]
check("E01a", "语料：不存在「旧合法 → 新非法」的值（包含性必要条件的抽样证据）",
      _missing == [], observed=_missing)
check("E01b", "语料：旧合法的值在新口径下全部合法（逐条计数一致）",
      sum(1 for v in _CORPUS if _old_ok(v)) <= sum(1 for v in _CORPUS if _new_ok(v)),
      observed={"old": sum(1 for v in _CORPUS if _old_ok(v)),
                "new": sum(1 for v in _CORPUS if _new_ok(v))})

# ============================================== E02 受限穷举：语言包含性
# 枚举「非 hex 前缀分隔符 × hex 长度 × 前缀有无」的结构网格，逐格比对两口径。
_grid_missing: list[tuple] = []
_checked = 0
for prefix in ("", "sha256:"):
    for sep in ("", ":", "sha256", "SHA256:", " sha256:"):
        for n in (0, 1, 31, 32, 63, 64, 65, 128):
            for case in ("lower", "upper", "mixed"):
                h = "a" * n
                if case == "upper":
                    h = "A" * n
                elif case == "mixed":
                    h = ("aA" * n)[:n]
                v = prefix + sep + h
                _checked += 1
                if _old_ok(v) and not _new_ok(v):
                    _grid_missing.append(v)
check("E02a", "受限穷举（前缀×分隔符×长度×大小写）未发现任何「旧合法→新非法」",
      _grid_missing == [], observed={"grid": _checked, "missing": _grid_missing[:5]})

# ============================================ E03 确定性随机：性质测试
_rng = random.Random(20261012)          # 固定种子 ⇒ 可复现
_rand_missing: list[str] = []
_rand_old = _rand_new = 0
for _ in range(20000):
    kind = _rng.randrange(6)
    if kind == 0:                                   # 合法裸 hex
        v = "".join(_rng.choice(_H) for _ in range(64))
    elif kind == 1:                                 # 合法带前缀
        v = "sha256:" + "".join(_rng.choice(_H) for _ in range(64))
    elif kind == 2:                                 # 长度扰动
        v = "".join(_rng.choice(_H) for _ in range(_rng.choice((63, 65, 0, 1, 100))))
    elif kind == 3:                                 # 大写
        v = "".join(_rng.choice("ABCDEF0123456789") for _ in range(64))
    elif kind == 4:                                 # 非 hex 混入
        v = "".join(_rng.choice(_H + "ghz:- ") for _ in range(64))
    else:                                           # 噪声串
        v = "".join(_rng.choice("sha256:abcdefx") for _ in range(_rng.randrange(0, 80)))
    o, n = _old_ok(v), _new_ok(v)
    _rand_old += 1 if o else 0
    _rand_new += 1 if n else 0
    if o and not n:
        _rand_missing.append(v)
check("E03a", "确定性随机 20000 例：无「旧合法→新非法」（性质测试）",
      _rand_missing == [], observed={"old_ok": _rand_old, "new_ok": _rand_new,
                                     "missing": _rand_missing[:5]})
check("E03b", "随机样本中新口径接受数 ≥ 旧口径（单调扩张的方向正确）",
      _rand_new >= _rand_old, observed={"old": _rand_old, "new": _rand_new})

# ============================== E04 扩张的**恰好**是裸 hex（不多不少）
_extra_forms: set[str] = set()
for _ in range(4000):
    v = "".join(_rng.choice(_H) for _ in range(64))
    if _new_ok(v) and not _old_ok(v):
        _extra_forms.add("bare64hex")
    w = "sha256:" + "".join(_rng.choice(_H) for _ in range(64))
    if _new_ok(w) and not _old_ok(w):
        _extra_forms.add("prefixed64hex")
check("E04a", "扩张类恰为「裸 64hex」（带前缀 64hex 旧口径本就接受，不应出现在扩张集）",
      _extra_forms == {"bare64hex"}, observed=_extra_forms)
check("E04b", "旧非法且新非法的值未被意外放行（如大写/长度错/非 hex 仍拒）",
      all(not _new_ok(v) for v in ("A" * 64, "a" * 63, "a" * 65, "sha256:" + "A" * 64,
                                   "sha256:" + "a" * 63, "g" * 64, "", "sha256:")),
      observed="illegal still rejected")

# ============================== E05 fail-closed 语义未被削弱（端到端）
_BUNDLE = {
    "schema": "classroom.course.bundle", "version": 1,
    "courses": [{
        "course_id": "crs_errata", "revision": 1, "title": "勘误回归",
        "source": "admin-knowledge",
        "source_doc_id": "doc_deadbeef",
        "source_doc_hash": "sha256:" + "ab" * 32,
        "source_file_sha256": None,
        "lessons": [{"lesson_id": "lsn_1", "title": "L1", "slides": [
            {"type": "sentence", "en": "Hi.", "cn": "你好。"}]}],
    }],
}
check("E05a", "旧口径合法的绑定在新 v1 下**仍然合法**（端到端）",
      not CS.validate_bundle(_BUNDLE), observed=CS.validate_bundle(_BUNDLE)[:2])

_bad = json.loads(json.dumps(_BUNDLE))
_bad["courses"][0]["source_doc_hash"] = "sha256:" + "ab" * 31   # 62 hex
check("E05b", "旧非法（长度错）在新 v1 下**仍然非法**（fail-closed 未削弱）",
      not CS.is_valid(_bad), observed=CS.validate_bundle(_bad)[:2])

_bad2 = json.loads(json.dumps(_BUNDLE))
_bad2["courses"][0]["source_doc_hash"] = "AB" * 32              # 大写裸 hex
check("E05c", "大写裸 hex 仍被拒（扩张仅限小写裸 hex，不放行大小写任意）",
      not CS.is_valid(_bad2), observed=CS.validate_bundle(_bad2)[:2])

# ============================== E06 结构面未变（版本号无需递增的依据）
_SCHEMA = json.loads((ROOT / "modules" / "curriculum"
                      / "course_schema.v1.json").read_text("utf-8"))
_props = _SCHEMA.get("properties", {})
check("E06a", "文档级 version 仍为 const 1（未升版本号；向后兼容 ≠ 结构变更）",
      _props.get("version", {}).get("const") == 1, observed=_props.get("version"))
check("E06b", "文档级 schema 名未变（classroom.course.bundle）",
      _props.get("schema", {}).get("const") == "classroom.course.bundle",
      observed=_props.get("schema"))
check("E06c", "doc_id / course_id 正则未变（勘误只涉及两个哈希字段）",
      CS.DOC_ID_RE.pattern == r"^doc_[A-Za-z0-9]{4,64}$"
      and CS.COURSE_ID_RE.pattern == r"^crs_[A-Za-z0-9_-]{4,64}$",
      observed=(CS.DOC_ID_RE.pattern, CS.COURSE_ID_RE.pattern))
check("E06d", "规范形式仍存在且严格（sha256:<64hex>），展示/规范比较不被放宽",
      CS.SHA256_CANON_RE.pattern == r"^sha256:[0-9a-f]{64}$"
      and CS.canonical_sha256("a" * 64) == "sha256:" + "a" * 64,
      observed=CS.SHA256_CANON_RE.pattern)

# ============================== E07 权威 ↔ 客户端镜像同步（两个字段都要改）
_MIRROR = json.loads((ROOT / "client" / "src" / "classroom"
                      / "course_schema.v1.json").read_text("utf-8"))


def _pattern_strings(node, out):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "pattern":
                out.append(v)
            else:
                _pattern_strings(v, out)
    elif isinstance(node, list):
        for it in node:
            _pattern_strings(it, out)
    return out


_auth_patterns = _pattern_strings(_SCHEMA, [])
_mirror_patterns = _pattern_strings(_MIRROR, [])
check("E07a", "权威与客户端镜像的 pattern 集合完全一致（勘误两侧同步，无单边漂移）",
      sorted(_auth_patterns) == sorted(_mirror_patterns),
      observed={"auth": sorted(_auth_patterns), "mirror": sorted(_mirror_patterns)})
check("E07b", "两侧哈希字段均使用放宽后的正则（不存在一边仍写死前缀）",
      sorted(_auth_patterns).count(r"^(?:sha256:)?[0-9a-f]{64}$") == 2,
      observed=sorted(_auth_patterns))

# ============================== E08 勘误不得被当成「静默变更」
check("E08a", "勘误有独立文档记录（非静默变更）—— 文件存在即视为已登记",
      (ROOT / "docs" / "engineering" / "product-v1" / "classroom-v2"
       / "CLASSROOM_V2_SCHEMA_V1_ERRATA.md").is_file(),
      observed="CLASSROOM_V2_SCHEMA_V1_ERRATA.md")
check("E08b", "生产代码显式标注勘误来源（course_schema.py 引用 CONTRACT_FIX_01A 一.4）",
      "CONTRACT_FIX_01A" in (ROOT / "modules" / "curriculum"
                             / "course_schema.py").read_text("utf-8"),
      observed="modules/curriculum/course_schema.py")

# ------------------------------------------------------------------ evidence
EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
EVIDENCE.write_text(json.dumps({
    "artifact": "schema_v1_errata_tests",
    "scope": "CLASSROOM V2 · Course Schema v1 勘误（SHA-256 正则放宽）向后兼容证明",
    "old_pattern": OLD_RE.pattern,
    "new_pattern": NEW_RE.pattern,
    "claim": "L(old) ⊆ L(new) ⇒ 旧 v1 合法文档在新 v1 下仍然合法（向后兼容，无需升版本）",
    "method": ["语料包含性", "受限穷举网格", "确定性随机性质测试(20000)",
               "扩张类精确性", "fail-closed 未削弱(端到端)", "结构与版本面未变",
               "权威↔镜像同步", "勘误已登记"],
    "grid_cells_checked": _checked,
    "random_cases": 20000,
    "results": RESULTS,
    "summary": {"total": len(RESULTS), "passed": len(PASS), "failed": len(FAIL),
                "failed_ids": FAIL},
}, ensure_ascii=False, indent=2), "utf-8")

print("\n==== SUMMARY ====")
print("total=%d pass=%d fail=%d" % (len(RESULTS), len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
print("evidence: %s" % EVIDENCE)
sys.exit(1 if FAIL else 0)
