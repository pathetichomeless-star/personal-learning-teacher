# -*- coding: utf-8 -*-
"""Textbook → course-bundle v1 builder (CLASSROOM V2 · Agent E · Phase 2).

Turns a *structured textbook description* (units → items) into a **frozen
contract v1** course bundle that passes :func:`modules.curriculum.course_schema.validate_bundle`.

Honesty rules (structural, not advisory)
----------------------------------------
* **User textbooks are the source of truth.** A course built from a real source
  MUST carry a real ``source_doc_id`` + ``source_doc_hash``; a ``local-demo``
  course MUST carry three ``null`` bindings — both enforced by the frozen schema,
  and this builder never lets the caller fake the other mode.
* **Never invent content.** Unknown item ``kind`` → raise (fail-closed); a missing
  or illegal practice ``answer`` becomes ``None`` ("答案待人工确认") and is reported
  in ``needs_review`` — it is **never** defaulted to 0/-1.
* **No fixed 20-day plan.** The module has no notion of "Day N"; it only reflects
  whatever units the user's own textbook actually has.

Public API
----------
``build_course(...)``   → one course dict (not yet validated)
``build_bundle(...)``   → a validated ``CourseBundle`` v1 dict
``BuildReport``         → ``{bundle, needs_review[]}`` (uncertain items surfaced)
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from . import course_schema as cschema
from . import phonetics

_KINDS = ("vocab", "sentence", "practice", "summary")

_UNIT_ID_SAFE = re.compile(r"[^A-Za-z0-9_-]+")


def _slug(text: str, *, fallback: str = "x") -> str:
    s = _UNIT_ID_SAFE.sub("_", str(text or "").strip())
    s = s.strip("_")
    return s or fallback


def make_course_id(name: str) -> str:
    """Build a schema-legal ``crs_…`` id from a human name.

    Guarantees the ``^crs_[A-Za-z0-9_-]{4,64}$`` pattern by padding short slugs.
    """
    slug = _slug(name, fallback="course")
    if len(slug) < 4:
        slug = (slug + "_course")[:64]
    return ("crs_" + slug)[:68]


@dataclass
class BuildReport:
    bundle: dict
    needs_review: list = field(default_factory=list)   # [{lesson, slide_index, reason}]
    notes: list = field(default_factory=list)


# --------------------------------------------------------------------------- #
# item → slide
# --------------------------------------------------------------------------- #
def item_to_slide(item: dict, *, where: str, review: list) -> dict:
    """Convert one textbook item into a schema-legal slide.

    Raises ``ValueError`` on an unknown ``kind`` (fail-closed — never silently skip).
    """
    if not isinstance(item, dict):
        raise ValueError("%s: item 必须是对象，得到 %r" % (where, type(item).__name__))
    kind = item.get("kind") or item.get("type")
    if kind not in _KINDS:
        raise ValueError("%s: 未知条目类型 %r（不得静默跳过）" % (where, kind))

    if kind == "vocab":
        slide = {"type": "vocab",
                 "word": str(item.get("word") or ""),
                 "meaning": str(item.get("meaning") or ""),
                 "en": str(item.get("en") or ""),
                 "cn": str(item.get("cn") or "")}
        if item.get("phonetic"):
            slide["phonetic"] = str(item["phonetic"])
        else:
            slide = phonetics.enrich_vocab(slide)          # 真实 IPA 或省略字段
            if "phonetic" not in slide:
                review.append({"where": where, "reason": "phonetic_unknown",
                               "word": slide["word"]})
        return slide

    if kind == "sentence":
        return {"type": "sentence",
                "en": str(item.get("en") or ""),
                "cn": str(item.get("cn") or "")}

    if kind == "practice":
        options = [str(o) for o in (item.get("options") or [])]
        raw = item.get("answer")
        answer = None
        if isinstance(raw, int) and not isinstance(raw, bool) and 0 <= raw < len(options):
            answer = raw
        else:
            # 关键：非法/缺失答案 → None（待人工确认），绝不落 0/-1 静默错判
            review.append({"where": where, "reason": "answer_needs_human",
                           "question": str(item.get("question") or ""),
                           "provided": raw})
        slide = {"type": "practice",
                 "question": str(item.get("question") or ""),
                 "options": options or ["A", "B"],
                 "answer": answer}
        if item.get("explain"):
            slide["explain"] = str(item["explain"])
        return slide

    # summary
    points = [str(p) for p in (item.get("points") or [])] or ["（本课小结）"]
    return {"type": "summary", "title": str(item.get("title") or "小结"), "points": points}


def build_lesson(unit: dict, *, index: int, review: list) -> dict:
    where = "unit[%d]" % index
    if not isinstance(unit, dict):
        raise ValueError("%s: unit 必须是对象" % where)
    title = str(unit.get("title") or ("第 %d 课" % (index + 1)))
    slides: list = []
    # 自动封面
    slides.append({"type": "cover", "title": title,
                   **({"subtitle": str(unit["subtitle"])} if unit.get("subtitle") else {})})
    for j, item in enumerate(unit.get("items") or []):
        slides.append(item_to_slide(item, where="%s.item[%d]" % (where, j), review=review))
    # 自动小结（若用户未显式提供 summary 条目）
    if not any(s.get("type") == "summary" for s in slides):
        slides.append({"type": "summary", "title": title + " · 小结",
                       "points": [str(p) for p in (unit.get("summary_points") or [])]
                       or ["本课内容已讲解完毕。"]})
    lesson_id = str(unit.get("lesson_id") or ("lesson_%d_%s" % (index + 1, _slug(title, fallback="u"))))
    return {"lesson_id": lesson_id, "title": title, "slides": slides}


def build_course(*, title: str, units: list, course_id: "str | None" = None,
                 source: str = "local-demo", revision: int = 1, subject: "str | None" = None,
                 level: "str | None" = None, description: "str | None" = None,
                 source_doc_id: "str | None" = None, source_doc_hash: "str | None" = None,
                 source_file_sha256: "str | None" = None, review: "list | None" = None) -> dict:
    """Build one course dict (un-validated; :func:`build_bundle` validates)."""
    review = review if review is not None else []
    if not units:
        raise ValueError("course 至少需要一个 unit（不得生成空课程）")
    course = {
        "course_id": course_id or make_course_id(title),
        "revision": int(revision),
        "title": str(title),
        "source": source,
        "source_doc_id": source_doc_id,
        "source_doc_hash": source_doc_hash,
        "source_file_sha256": source_file_sha256,
        "lessons": [build_lesson(u, index=i, review=review) for i, u in enumerate(units)],
    }
    for k, v in (("subject", subject), ("level", level), ("description", description)):
        if v:
            course[k] = str(v)
    return course


def build_bundle(*, courses: list, label: "str | None" = None, notice: "str | None" = None,
                 generated_at: "str | None" = None, review: "list | None" = None) -> BuildReport:
    """Assemble + **validate** a v1 bundle; raise ``CourseSchemaError`` if invalid."""
    review = review if review is not None else []
    doc: dict = {"schema": cschema.SCHEMA_DOCUMENT_TYPE,
                 "version": cschema.SCHEMA_VERSION,
                 "courses": courses}
    if label:
        doc["label"] = str(label)
    if notice:
        doc["notice"] = str(notice)
    doc["generated_at"] = generated_at or _now_iso()
    cschema.assert_valid(doc)          # fail-closed: 不合法直接抛错
    return BuildReport(bundle=doc, needs_review=list(review))


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def build_local_demo(*, title: str, units: list, label: str = "本地演示课程", **kw) -> BuildReport:
    """Convenience: a strictly local-demo course (three bindings forced ``null``)."""
    review: list = kw.pop("review", [])
    course = build_course(title=title, units=units, source="local-demo", review=review, **kw)
    # 结构性保证：local-demo 一律不绑定来源
    course["source_doc_id"] = None
    course["source_doc_hash"] = None
    course["source_file_sha256"] = None
    return build_bundle(courses=[course], label=label, review=review)
