#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线教材流水线：**解析 → 隔离知识库提交 → 课程草稿 → 校验**（CLASSROOM V2 · DELIVERY GATE 02 C）。

本工具是「离线解析 → 课程草稿 → 课堂展示」演示的**唯一**实现入口，全部在**本机离线**完成：

    1. 读取教材文件字节，计算 ``source_file_sha256``（原文件**字节**哈希）；
    2. 用**既有真实解析器** ``modules.knowledge.parsers.parse_file`` 抽取纯文本；
    3. 把抽取值提交到**隔离** ``KnowledgeStore``（临时/输出目录，**绝不碰生产存储**），
       拿到真实的 ``doc_id`` 与 ``content_hash``（抽取文本哈希）——二者**语义不同、不可互换**；
    4. 用 ``modules.curriculum.builder`` 把结构化条目构建为**冻结契约 v1** 课程，
       来源绑定为 ``user-textbook`` + 真实 ``doc_id`` / ``content_hash``；
    5. ``course_schema.assert_valid`` **fail-closed** 校验；通过后才写出产物。

产物（写入 ``--out``）：

    library/<course_id>.course.json      # v1 课程 bundle（客户端可直接加载）
    library/<course_id>.manifest.json    # 真实阶段记录 + 绑定核验（供「解析进度」页显示）
    kb_snapshot/knowledge.json           # 隔离知识库快照（供课堂做来源绑定复核）
    library/index.json                   # 书库索引

边界（硬性）
------------
* **零网络**：不发起任何 HTTP/WS 请求；不读任何密钥或正式配置；
* **不触碰生产存储**：知识库只建在 ``--out`` 下；
* **不恢复 20 天固定课程**：课次完全来自教材自身结构；
* **不伪造来源**：``doc_id`` / ``content_hash`` 必须来自真实 store 返回值。

用法：
    PYTHONPATH= <venv>/bin/python tools/classroom_offline_pipeline.py \
        --textbook docs/engineering/product-v1/classroom-v2/demo/sample_textbook.md \
        --out client/src/classroom/data/demo
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.curriculum import builder, course_schema as cschema  # noqa: E402
from modules.knowledge import parsers  # noqa: E402
from modules.knowledge.store import KnowledgeStore  # noqa: E402

DEFAULT_TEXTBOOK = (ROOT / "docs" / "engineering" / "product-v1" / "classroom-v2"
                    / "demo" / "sample_textbook.md")


# ---------------------------------------------------------------- 教材结构解析
def parse_structured_text(text: str) -> list[dict]:
    """把「标记化教材」解析为 builder 可用的 unit 列表（确定性、无模型）。

    标记（本演示约定的**最小结构化格式**）：
        ``# 标题``            课程/课次标题
        ``## 第N课 …``        一个 unit（课次）
        ``### 词汇|句型|练习|小结``  分节
        ``- word | meaning | en | cn``  词汇条目
        ``en | cn``           句型条目
        ``题干 | 选项1;选项2 | 正确索引 | 解析``  练习条目
        其余非空行            作为小结要点
    """
    units: list[dict] = []
    cur: dict | None = None
    section = ""

    def _new_unit(title: str) -> dict:
        return {"title": title, "items": [], "summary_points": []}

    for raw in (text or "").splitlines():
        line = raw.rstrip()
        s = line.strip()
        if not s:
            continue
        if s.startswith("## "):
            cur = _new_unit(s[3:].strip())
            units.append(cur)
            section = ""
            continue
        if s.startswith("### "):
            section = s[4:].strip()
            continue
        if s.startswith("# "):
            continue                      # 文档标题（不作为课次）
        if s.startswith(">") or s.startswith("---"):
            continue                      # 说明/分隔
        if cur is None:
            continue

        if section.startswith("词汇") and s.startswith("-"):
            parts = [p.strip() for p in s[1:].split("|")]
            parts += [""] * (4 - len(parts))
            cur["items"].append({"kind": "vocab", "word": parts[0], "meaning": parts[1],
                                 "en": parts[2], "cn": parts[3]})
        elif section.startswith("句型"):
            parts = [p.strip() for p in s.split("|")]
            parts += [""] * (2 - len(parts))
            cur["items"].append({"kind": "sentence", "en": parts[0], "cn": parts[1]})
        elif section.startswith("练习"):
            parts = [p.strip() for p in s.split("|")]
            if len(parts) >= 3:
                opts = [o.strip() for o in parts[1].split(";") if o.strip()]
                try:
                    ans = int(parts[2])
                except (TypeError, ValueError):
                    ans = None
                cur["items"].append({"kind": "practice", "question": parts[0],
                                     "options": opts, "answer": ans,
                                     "explain": parts[3] if len(parts) > 3 else ""})
        elif section.startswith("小结"):
            cur["summary_points"].append(s)
        else:
            cur["summary_points"].append(s)

    for u in units:
        u["items"] = u["items"] or [{"kind": "sentence", "en": "(本课无结构化条目)", "cn": ""}]
    return units


# ---------------------------------------------------------------------- 主流程
def run(textbook: Path, out: Path, *, course_title, dataset_name, course_id=None,
        quiet=False) -> dict:
    stages: list[dict] = []
    t0 = time.time()

    def stage(name: str, detail: str, ok: bool = True) -> None:
        stages.append({"stage": name, "detail": detail, "ok": bool(ok),
                       "elapsed_ms": int((time.time() - t0) * 1000)})
        if not quiet:
            print("  [%s] %s — %s" % ("OK " if ok else "ERR", name, detail), flush=True)

    if not textbook.is_file():
        raise SystemExit("教材文件不存在：%s" % textbook)

    # 1) 原文件字节哈希
    raw = textbook.read_bytes()
    file_sha = hashlib.sha256(raw).hexdigest()
    stage("read_bytes", "%s（%d 字节，sha256=%s…）" % (textbook.name, len(raw), file_sha[:12]))

    # 2) 真实解析器抽取纯文本（parse_file 返回 (text, error_code)）
    ext = parsers.ext_of(textbook.name)
    ok, reason = parsers.parser_available(ext)
    if not ok:
        stage("parse", "格式 %s 无可用解析器：%s" % (ext, reason), ok=False)
        raise SystemExit("解析器不可用：%s（%s）" % (ext, reason))
    text, err = parsers.parse_file(str(textbook), ext)
    if err or text is None:
        stage("parse", "解析失败：%s" % (err or "empty"), ok=False)
        raise SystemExit("解析失败：%s" % err)
    text = str(text)
    extractor = (parsers.EXTS.get(ext) or {}).get("parser") or ext
    stage("parse", "解析器=%s，抽取 %d 字符" % (extractor, len(text)))

    # 3) 隔离知识库提交（真实 doc_id + content_hash）
    out.mkdir(parents=True, exist_ok=True)
    kb_dir = out / "kb_snapshot"
    kb_dir.mkdir(parents=True, exist_ok=True)
    kb_file = kb_dir / "knowledge.json"
    if kb_file.exists():
        kb_file.unlink()                       # 确定性重建（避免沿用旧随机 doc_id）
    store = KnowledgeStore(str(kb_file))
    ds = store.create_dataset(dataset_name)
    source_type = (parsers.EXTS.get(ext) or {}).get("source_type") or "text"
    doc = store.add_document(ds["id"], textbook.stem, text, source_type=source_type)
    doc_id, content_hash = doc["id"], doc["content_hash"]
    stage("kb_commit", "隔离库 %s；doc_id=%s；content_hash=%s…（裸 hex）"
          % (kb_file.name, doc_id, content_hash[:12]))

    # 4) 结构化 → 课程草稿（来源绑定 user-textbook）
    units = parse_structured_text(text)
    if not units:
        stage("structure", "未识别到任何课次（检查教材标记）", ok=False)
        raise SystemExit("未识别到课次")
    stage("structure", "识别 %d 个课次 / %d 个条目"
          % (len(units), sum(len(u["items"]) for u in units)))

    review: list = []
    course = builder.build_course(
        title=course_title, units=units, course_id=course_id, source="user-textbook",
        subject="英语", level="入门",
        description="由离线流水线从教材《%s》生成（演示）。" % textbook.stem,
        source_doc_id=doc_id, source_doc_hash=content_hash,
        source_file_sha256=file_sha, review=review)
    report = builder.build_bundle(
        courses=[course],
        label="离线演示课程（来源：演示知识库快照，非正式用户教材）",
        notice=("本课程由 tools/classroom_offline_pipeline.py 离线生成；"
                "source_doc_id 指向随包演示知识库快照，**不是**正式用户知识库。"),
        review=review)
    stage("build_course", "course_id=%s，课次 %d，待人工确认 %d 项"
          % (course["course_id"], len(course["lessons"]), len(report.needs_review)))

    # 5) fail-closed 校验
    violations = cschema.validate_bundle(report.bundle)
    if violations:
        stage("validate", "契约校验失败：%s" % violations[0], ok=False)
        raise SystemExit("契约校验失败：%s" % violations)
    stage("validate", "通过冻结契约 v1（JSON schema + 手写校验）")

    # 6) 绑定复核（读回 store，证明来源真实）
    reread = store.get_document(doc_id)
    bound_ok = bool(reread) and cschema.sha256_matches(
        course["source_doc_hash"], (reread or {}).get("content_hash"))
    stage("binding_check",
          "回读 store：doc 存在=%s；content_hash 与课程 source_doc_hash 一致=%s"
          % (bool(reread), bound_ok))

    lib = out / "library"
    lib.mkdir(parents=True, exist_ok=True)
    course_id = course["course_id"]
    bundle_path = lib / ("%s.course.json" % course_id)
    bundle_path.write_text(json.dumps(report.bundle, ensure_ascii=False, indent=2), "utf-8")

    manifest = {
        "artifact": "classroom_offline_pipeline",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "textbook": {"file": textbook.name, "bytes": len(raw),
                     "source_file_sha256": file_sha, "ext": ext},
        "parse": {"extractor": extractor,
                  "extracted_chars": len(text),
                  "page_anchor_basis": "page", "anchor_hint": None},
        "knowledge": {"snapshot": "kb_snapshot/knowledge.json",
                      "dataset_id": ds["id"], "doc_id": doc_id,
                      "content_hash": content_hash,
                      "content_hash_note": "裸 64hex（无 sha256: 前缀）——见 SCHEMA_V1_ERRATA"},
        "course": {"course_id": course_id, "revision": course["revision"],
                   "lessons": len(course["lessons"]),
                   "slides": sum(len(l["slides"]) for l in course["lessons"]),
                   "source": course["source"]},
        "needs_review": report.needs_review,
        "binding_check": {"doc_readback_ok": bool(reread), "hash_matches": bound_ok},
        "stages": stages,
        "bundle_file": bundle_path.name,
    }
    (lib / ("%s.manifest.json" % course_id)).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")

    # 书库索引（保留既有条目，按 course_id 覆盖）
    index_path = lib / "index.json"
    index: dict = {"generated_at": manifest["generated_at"], "items": []}
    if index_path.exists():
        try:
            old = json.loads(index_path.read_text("utf-8"))
            if isinstance(old, dict) and isinstance(old.get("items"), list):
                index["items"] = [i for i in old["items"]
                                  if isinstance(i, dict) and i.get("course_id") != course_id]
        except Exception:  # noqa: BLE001
            pass
    index["items"].append({"course_id": course_id, "bundle": bundle_path.name,
                           "manifest": "%s.manifest.json" % course_id,
                           "title": course["title"], "source": course["source"]})
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), "utf-8")

    n_stages = len(stages)
    if not quiet:
        print("\n产物：")
        print("  %s" % bundle_path)
        print("  %s" % (lib / ("%s.manifest.json" % course_id)))
        print("  %s" % kb_file)
        print("  %s" % index_path)
        print("阶段：%d，全部成功=%s" % (n_stages, all(s["ok"] for s in stages)))
    return {"bundle": report.bundle, "manifest": manifest, "out": str(out)}


def main() -> int:
    ap = argparse.ArgumentParser(description="离线教材流水线（解析→知识库→课程草稿）")
    ap.add_argument("--textbook", default=str(DEFAULT_TEXTBOOK))
    ap.add_argument("--out", required=True, help="输出目录（课堂数据目录或演示目录）")
    ap.add_argument("--course-title", default="离线演示：基础问候")
    ap.add_argument("--dataset", default="离线演示教材")
    ap.add_argument("--course-id", dest="course_id", default="crs_offline_demo_basics")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    print("离线流水线：textbook=%s" % a.textbook)
    run(Path(a.textbook).expanduser().resolve(), Path(a.out).expanduser().resolve(),
        course_title=a.course_title, dataset_name=a.dataset,
        course_id=a.course_id, quiet=a.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
