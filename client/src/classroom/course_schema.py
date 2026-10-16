# -*- coding: utf-8 -*-
"""CLASSROOM V2 —— 课程数据契约 v1 的**客户端冻结镜像**（禁止直接编辑）。

⚠️ 本文件是 ``modules/curriculum/course_schema.py`` 的**冻结副本**。
   修改权威实现后必须重新同步本文件与同目录 ``course_schema.v1.json``，
   否则 ``gateway/tests/course_schema_consistency_tests.py`` 会失败。
   客户端为独立 PyInstaller 包，**运行期不得** import ``modules.*`` ——
   故此处必须保持「自带 schema + 自带校验器」的独立形态。

设计要点（PHASE 2 CONTRACT FIX 01 · 修正②）：

* **单一机器可读事实源** = 同目录 ``course_schema.v1.json``（JSON Schema draft-07）。
  本模块的常量（``SCHEMA_VERSION`` / ``SLIDE_TYPES`` / ``SOURCE_ENUM`` …）**从该文件派生**，
  避免「常量与 schema 各写一份」的漂移。
* **零新增依赖**：不 import ``jsonschema``。draft-07 表达不了的两条约束
  （``answer < len(options)``、以及跨层级唯一性/来源绑定的一致性）在此**手写补足**。
* **层级唯一（消除冲突）**：``version`` 只在文档级；``source`` 与来源绑定只在 course 级。
* **不得伪造知识库来源**：``source == "local-demo"`` 时三个来源绑定字段必须为 ``null``；
  ``user-textbook`` / ``admin-knowledge`` 必须有真实的 ``source_doc_id`` + ``source_doc_hash``。
* **哈希语义区分**：``source_doc_hash`` = 知识库 ``content_hash``（抽取文本哈希）；
  ``source_file_sha256`` = 原文件字节哈希。**二者不可互相推导、不可互相冒充**。
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Iterable

_HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(_HERE, "course_schema.v1.json")

SCHEMA_FILE_NAME = "course_schema.v1.json"

# ---- 从 JSON Schema 派生常量（防漂移）-----------------------------------------
with open(SCHEMA_PATH, "r", encoding="utf-8") as _f:
    SCHEMA_DOC: dict = json.load(_f)

SCHEMA_ID: str = SCHEMA_DOC["$id"]
SCHEMA_DOCUMENT_TYPE: str = SCHEMA_DOC["properties"]["schema"]["const"]
SCHEMA_VERSION: int = SCHEMA_DOC["properties"]["version"]["const"]

SOURCE_ENUM: tuple[str, ...] = tuple(
    SCHEMA_DOC["definitions"]["course"]["properties"]["source"]["enum"]
)
SOURCE_REQUIRING_BINDING: tuple[str, ...] = tuple(
    s for s in SOURCE_ENUM if s != "local-demo"
)
SOURCE_LOCAL_DEMO: str = "local-demo"

def _resolve_ref(ref: str) -> dict:
    """解析 ``#/definitions/x`` 形式的本地引用。"""
    node: Any = SCHEMA_DOC
    for part in ref.lstrip("#/").split("/"):
        node = node[part]
    return node


def _variants(container: dict) -> tuple[dict, ...]:
    """取出 ``oneOf`` 各分支（支持 ``$ref`` 与内联两种写法）。"""
    return tuple(
        _resolve_ref(v["$ref"]) if "$ref" in v else v
        for v in container["oneOf"]
    )


_SLIDE_VARIANTS: tuple[dict, ...] = _variants(SCHEMA_DOC["definitions"]["slide"])

# slide.type 闭枚举 —— 从 oneOf 各分支的 type const 派生
SLIDE_TYPES: tuple[str, ...] = tuple(
    sorted(v["properties"]["type"]["const"] for v in _SLIDE_VARIANTS)
)

COURSE_ID_RE = re.compile(r"^crs_[A-Za-z0-9_-]{4,64}$")
DOC_ID_RE = re.compile(r"^doc_[A-Za-z0-9]{4,64}$")
# SHA-256 文本形式：**既接受裸 64 位小写 hex，也接受 sha256: 前缀形式**。
# 依据 CONTRACT_FIX_01A 一.4 实测：既有 KnowledgeStore 的 content_hash 输出为**裸 hex**
# （store.py:623 doc_id = "doc_"+uuid4().hex[:12]；:140 _content_hash → hashlib.sha256().hexdigest()）。
# 若只接受带前缀形式，真实知识库返回的 content_hash 会被误判为非法 → 正式课程无法通过校验。
SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
# 规范化形式（自描述、带算法前缀）：唯一的比较/展示规范口径。
SHA256_CANON_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

# 文档级允许的键（v1 封版：不得出现 source —— 来源必须下沉到 course）
BUNDLE_ALLOWED_KEYS: frozenset[str] = frozenset(
    SCHEMA_DOC["properties"].keys()
)
# 历史兼容键：曾出现在文档级，v1 起**不得**出现（须下沉/删除）
BUNDLE_LEGACY_FORBIDDEN_KEYS: frozenset[str] = frozenset({"source"})

SLIDE_ALLOWED_KEYS: dict[str, frozenset[str]] = {
    v["properties"]["type"]["const"]: frozenset(v["properties"].keys())
    for v in _SLIDE_VARIANTS
}

COURSE_ALLOWED_KEYS: frozenset[str] = frozenset(
    SCHEMA_DOC["definitions"]["course"]["properties"].keys()
)
LESSON_ALLOWED_KEYS: frozenset[str] = frozenset(
    SCHEMA_DOC["definitions"]["lesson"]["properties"].keys()
)


class CourseSchemaError(ValueError):
    """课程 bundle 违反冻结契约 v1。``errors`` 为全部违规点（非首个）。"""

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors) or "course schema violation")


# --------------------------------------------------------------------------- #
# 手写补足：draft-07 表达不了的约束
# --------------------------------------------------------------------------- #
def _check_answer_in_range(where: str, slide: dict) -> list[str]:
    """``practice.answer`` 必须为 null（待确认）或 0 <= answer < len(options)。"""
    answer = slide.get("answer")
    options = slide.get("options")
    if answer is None:
        return []
    if not isinstance(answer, int) or isinstance(answer, bool):
        return ["%s.answer: 必须是整数下标或 null（待人工确认），得到 %r" % (where, answer)]
    if not isinstance(options, list):
        return ["%s.options: 必须为数组" % where]
    if not (0 <= answer < len(options)):
        return [
            "%s.answer: 下标 %d 越界（options 长度 %d）—— 禁止落 -1/越界值静默错判"
            % (where, answer, len(options))
        ]
    return []


def _check_unknown_keys(where: str, obj: dict, allowed: Iterable[str]) -> list[str]:
    allowed = frozenset(allowed)
    extra = sorted(set(obj.keys()) - allowed)
    return ["%s: 未知字段 %s（v1 封版，未知字段一律拒绝）" % (where, extra)] if extra else []


def _check_source_binding(where: str, course: dict) -> list[str]:
    """来源绑定一致性 + 不得伪造知识库来源 + 哈希语义区分。"""
    errs: list[str] = []
    src = course.get("source")
    doc_id = course.get("source_doc_id")
    doc_hash = course.get("source_doc_hash")
    file_hash = course.get("source_file_sha256")

    for key in ("source_doc_id", "source_doc_hash", "source_file_sha256"):
        if key not in course:
            errs.append("%s.%s: v1 必填（无真实值时显式写 null）" % (where, key))
    if errs:
        return errs

    if src == SOURCE_LOCAL_DEMO:
        # 结构性禁止伪造知识库来源
        for key, val in (("source_doc_id", doc_id), ("source_doc_hash", doc_hash),
                         ("source_file_sha256", file_hash)):
            if val is not None:
                errs.append(
                    "%s.%s: source=local-demo 时必须为 null（不得伪造知识库来源），得到 %r"
                    % (where, key, val)
                )
        return errs

    if src in SOURCE_REQUIRING_BINDING:
        if not isinstance(doc_id, str) or not DOC_ID_RE.match(doc_id):
            errs.append("%s.source_doc_id: %s 必须提供真实知识库 doc_id，得到 %r"
                        % (where, src, doc_id))
        if not isinstance(doc_hash, str) or not SHA256_RE.match(doc_hash):
            errs.append(
                "%s.source_doc_hash: %s 必须提供 SHA-256 形式的 content_hash"
                "（裸 64hex 或 sha256:<64hex>），得到 %r"
                % (where, src, doc_hash)
            )
        if file_hash is not None:
            if not isinstance(file_hash, str) or not SHA256_RE.match(file_hash):
                errs.append(
                    "%s.source_file_sha256: 须为 sha256:<64hex> 或 null（无真实原文件哈希时必须为 null，"
                    "不得用 content_hash 冒充），得到 %r" % (where, file_hash)
                )
        return errs

    # source 不在枚举内（枚举校验在别处报错），此处不再重复
    return errs


# --------------------------------------------------------------------------- #
# 逐层校验
# --------------------------------------------------------------------------- #
def validate_slide(where: str, slide: Any) -> list[str]:
    if not isinstance(slide, dict):
        return ["%s: slide 必须是对象，得到 %r" % (where, type(slide).__name__)]
    stype = slide.get("type")
    if stype not in SLIDE_TYPES:
        return [
            "%s.type: 未知内容类型 %r（闭枚举 %s）—— 不得静默跳过"
            % (where, stype, "|".join(SLIDE_TYPES))
        ]
    errs = _check_unknown_keys(where, slide, SLIDE_ALLOWED_KEYS[stype])

    # 各类型必填字段（与 JSON Schema 对齐）
    required = {
        "cover": ("title",),
        "vocab": ("word", "meaning", "en", "cn"),
        "sentence": ("en", "cn"),
        "practice": ("question", "options", "answer"),
        "summary": ("title", "points"),
    }[stype]
    for key in required:
        if key not in slide:
            errs.append("%s.%s: 必填字段缺失（type=%s）" % (where, key, stype))
    if "phonetic" in slide and slide["phonetic"] is None:
        errs.append("%s.phonetic: 缺失时应省略字段，不得写 null 哨兵" % where)
    if stype == "practice":
        errs.extend(_check_answer_in_range(where, slide))
    if stype == "summary" and "points" in slide and not slide["points"]:
        errs.append("%s.points: 至少 1 条小结要点" % where)
    if stype == "practice" and isinstance(slide.get("options"), list) and len(slide["options"]) < 2:
        errs.append("%s.options: 至少 2 个选项" % where)
    return errs


def validate_lesson(where: str, lesson: Any) -> list[str]:
    if not isinstance(lesson, dict):
        return ["%s: lesson 必须是对象" % where]
    errs = _check_unknown_keys(where, lesson, LESSON_ALLOWED_KEYS)
    for key in ("lesson_id", "title", "slides"):
        if key not in lesson:
            errs.append("%s.%s: 必填字段缺失" % (where, key))
    slides = lesson.get("slides")
    if not isinstance(slides, list) or not slides:
        errs.append("%s.slides: 必须为非空数组" % where)
        return errs
    for i, slide in enumerate(slides):
        errs.extend(validate_slide("%s.slides[%d]" % (where, i), slide))
    return errs


def validate_course(where: str, course: Any) -> list[str]:
    if not isinstance(course, dict):
        return ["%s: course 必须是对象" % where]
    errs = _check_unknown_keys(where, course, COURSE_ALLOWED_KEYS)
    for key in ("course_id", "revision", "title", "source", "lessons"):
        if key not in course:
            errs.append("%s.%s: 必填字段缺失" % (where, key))
    cid = course.get("course_id")
    if not isinstance(cid, str) or not COURSE_ID_RE.match(cid):
        errs.append("%s.course_id: 须形如 crs_xxxx（v1 不接受历史字段 id），得到 %r" % (where, cid))
    if "id" in course:
        errs.append("%s.id: 历史字段，v1 已由 course_id 取代（须迁移，不可同时存在）" % where)
    rev = course.get("revision")
    if not isinstance(rev, int) or isinstance(rev, bool) or rev < 1:
        errs.append("%s.revision: 必须为 >=1 的整数，得到 %r" % (where, rev))
    src = course.get("source")
    if src not in SOURCE_ENUM:
        errs.append("%s.source: 必须是 %s 之一，得到 %r"
                    % (where, "|".join(SOURCE_ENUM), src))
    if "version" in course:
        errs.append("%s.version: version 只允许出现在文档级（消除双 version 歧义）" % where)
    errs.extend(_check_source_binding(where, course))
    lessons = course.get("lessons")
    if not isinstance(lessons, list) or not lessons:
        errs.append("%s.lessons: 必须为非空数组" % where)
        return errs
    for i, lesson in enumerate(lessons):
        errs.extend(validate_lesson("%s.lessons[%d]" % (where, i), lesson))
    return errs


def validate_bundle(doc: Any) -> list[str]:
    """返回全部违规点（空列表 = 合法）。**不抛异常**，由调用方决定 fail-closed 行为。"""
    if not isinstance(doc, dict):
        return ["$: bundle 必须是对象，得到 %r" % type(doc).__name__]
    errs: list[str] = []
    if doc.get("schema") != SCHEMA_DOCUMENT_TYPE:
        errs.append("$.schema: 必须为 %r，得到 %r" % (SCHEMA_DOCUMENT_TYPE, doc.get("schema")))
    ver = doc.get("version")
    if ver != SCHEMA_VERSION:
        errs.append(
            "$.version: 未知/缺失版本 %r（本客户端/服务端支持 const %d）—— fail-closed，不得静默"
            % (ver, SCHEMA_VERSION)
        )
    errs.extend(_check_unknown_keys("$", doc, BUNDLE_ALLOWED_KEYS))
    for legacy in sorted(BUNDLE_LEGACY_FORBIDDEN_KEYS & set(doc.keys())):
        errs.append(
            "$.%s: 文档级来源字段已废弃 —— source 必须下沉到每个 course（PHASE2 CONTRACT FIX 01）"
            % legacy
        )
    courses = doc.get("courses")
    if not isinstance(courses, list) or not courses:
        errs.append("$.courses: 必须为非空数组")
        return errs
    for i, course in enumerate(courses):
        errs.extend(validate_course("$.courses[%d]" % i, course))
    return errs


def is_valid(doc: Any) -> bool:
    return not validate_bundle(doc)


def assert_valid(doc: Any) -> dict:
    """合法则原样返回；否则抛 :class:`CourseSchemaError`（附全部违规点）。"""
    errs = validate_bundle(doc)
    if errs:
        raise CourseSchemaError(errs)
    return doc


# --------------------------------------------------------------------------- #
# 便捷判定（供 UI / 契约层复用）
# --------------------------------------------------------------------------- #
def requires_knowledge_binding(source: str) -> bool:
    """该来源是否**必须**绑定真实知识库文档。"""
    return source in SOURCE_REQUIRING_BINDING


def canonical_sha256(value: Any) -> "str | None":
    """把任意合法 SHA-256 文本规范为 ``sha256:<64hex>``。

    接受「裸 64hex」与「sha256:<64hex>」两种输入；不合法返回 ``None``。
    **发布来源一致性校验必须用本函数对两侧规范化后再比较**，避免
    「知识库裸 hex」与「契约前缀 hex」被误判为不一致（CONTRACT_FIX_01A 一.4）。
    """
    if not isinstance(value, str) or not SHA256_RE.match(value):
        return None
    hexpart = value[7:] if value.startswith("sha256:") else value
    return "sha256:" + hexpart.lower()


def sha256_matches(a: Any, b: Any) -> bool:
    """两侧 SHA-256 文本是否为**同一摘要**（忽略可选 ``sha256:`` 前缀与大小写）。"""
    ca, cb = canonical_sha256(a), canonical_sha256(b)
    return ca is not None and ca == cb


def file_hash_display(value: Any) -> str:
    """原文件哈希的**诚实**展示口径（修正③ · 01A 强化）。

    合法 SHA-256（裸 64hex 或 ``sha256:`` 前缀）→ 规范化为 ``sha256:<64hex>`` 展示；
    无真实 ``file_sha256`` 时返回「原文件哈希待确认」；
    **绝不**回退去展示 ``content_hash``（二者语义不同）。
    """
    canon = canonical_sha256(value)
    return canon if canon is not None else "原文件哈希待确认"
