# -*- coding: utf-8 -*-
"""课程数据迁移：历史 courses.json → 冻结契约 v1（PHASE2 CONTRACT FIX 01 · 修正②）。

迁移是**确定性**且**幂等**的（再跑一次 = 无改动）。规则：

1. 根级新增 ``schema = "classroom.course.bundle"``；``version`` 保持 const 1。
2. 根级 ``source`` **下沉**到每个 course（仅当 course 自身缺失 ``source`` 时填充），
   然后**删除**根级 ``source``（v1 禁止文档级来源）。
3. ``courses[].id`` → ``course_id``，并归一为 ``crs_`` 前缀（``course_hotel`` → ``crs_hotel``）。
4. 新增 ``revision = 1``（缺失时）。
5. 新增三个来源绑定字段；``local-demo`` ⇒ 一律写 ``null``（**不得伪造知识库来源**）。
6. ``lessons[].id`` → ``lesson_id``。
7. 根级 ``label`` / ``notice`` 保留（它们是文档说明，不是课程来源）。

用法：
    python tools/migrate_course_bundle_v1.py --in <src.json> --out <dst.json>
    python tools/migrate_course_bundle_v1.py --in <file.json> --in-place
    python tools/migrate_course_bundle_v1.py --check <file.json>     # 只校验是否已是 v1

退出码：0 = 成功 / 已是 v1；1 = 迁移后仍不合法 或 参数错误。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.curriculum import course_schema as schema  # noqa: E402

BINDING_KEYS = ("source_doc_id", "source_doc_hash", "source_file_sha256")


def _normalize_course_id(raw: object) -> str:
    """历史 id → v1 course_id（确定性）。"""
    s = str(raw or "").strip()
    if s.startswith("crs_"):
        return s
    if s.startswith("course_"):
        s = s[len("course_"):]
    return "crs_" + (s or "unnamed")


def migrate(doc: dict) -> tuple[dict, list[str]]:
    """返回 (迁移后的新 doc, 变更说明列表)。输入不会被就地修改。"""
    out = json.loads(json.dumps(doc))  # deep copy
    changes: list[str] = []

    if out.get("schema") != schema.SCHEMA_DOCUMENT_TYPE:
        out["schema"] = schema.SCHEMA_DOCUMENT_TYPE
        changes.append("root: 设置 schema=%s" % schema.SCHEMA_DOCUMENT_TYPE)

    root_source = out.pop("source", None)
    if root_source is not None:
        changes.append("root: 删除文档级 source=%r（下沉到各 course）" % root_source)

    courses = out.get("courses") or []
    for i, c in enumerate(courses):
        if not isinstance(c, dict):
            continue
        where = "courses[%d]" % i

        if "id" in c:
            legacy = c.pop("id")
            if "course_id" not in c:
                c["course_id"] = _normalize_course_id(legacy)
                changes.append("%s: id=%r → course_id=%r" % (where, legacy, c["course_id"]))
            else:
                changes.append("%s: 删除历史字段 id=%r" % (where, legacy))

        if "source" not in c:
            c["source"] = root_source or schema.SOURCE_LOCAL_DEMO
            changes.append("%s: 设置 source=%r" % (where, c["source"]))

        if "revision" not in c:
            c["revision"] = 1
            changes.append("%s: 设置 revision=1" % where)

        for key in BINDING_KEYS:
            if key not in c:
                # local-demo（及任何缺少真实来源的场景）一律 null —— 不伪造
                c[key] = None
                changes.append("%s: 设置 %s=null" % (where, key))

        for j, lesson in enumerate(c.get("lessons") or []):
            if not isinstance(lesson, dict):
                continue
            if "id" in lesson and "lesson_id" not in lesson:
                lesson["lesson_id"] = lesson.pop("id")
                changes.append("%s.lessons[%d]: id → lesson_id" % (where, j))

    out["courses"] = courses
    return out, changes


def check_only(path: Path) -> int:
    doc = json.loads(path.read_text(encoding="utf-8"))
    errs = schema.validate_bundle(doc)
    if errs:
        print("NOT-V1  %s" % path)
        for e in errs[:20]:
            print("   -", e)
        return 1
    print("OK-V1   %s" % path)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="历史课程数据 → 冻结契约 v1 迁移")
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst")
    ap.add_argument("--in-place", action="store_true")
    ap.add_argument("--check", action="store_true", help="只校验，不写")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    src = Path(args.src)
    if not src.is_file():
        print("错误：源文件不存在 %s" % src, file=sys.stderr)
        return 1

    if args.check:
        return check_only(src)

    original = json.loads(src.read_text(encoding="utf-8"))
    migrated, changes = migrate(original)

    errs = schema.validate_bundle(migrated)
    if errs:
        print("迁移后仍不合法（%d 项）：" % len(errs), file=sys.stderr)
        for e in errs[:20]:
            print("   -", e, file=sys.stderr)
        return 1

    dst = src if args.in_place else Path(args.dst) if args.dst else None
    if dst is None:
        print("错误：需指定 --out 或 --in-place", file=sys.stderr)
        return 1

    already = False
    if dst.is_file():
        try:
            already = json.loads(dst.read_text(encoding="utf-8")) == migrated
        except Exception:  # noqa: BLE001
            already = False

    if already:
        if not args.quiet:
            print("幂等：无改动 %s" % dst)
        return 0

    dst.write_text(json.dumps(migrated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.quiet:
        print("迁移完成 → %s（%d 处改动）" % (dst, len(changes)))
        for c in changes[:40]:
            print("  ·", c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
