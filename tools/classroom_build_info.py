#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「小智 AI 学生课堂.app」构建信息（源码 ↔ 安装包一致性凭据）。

用途（DELIVERY GATE 02 · 交付物 F）
------------------------------------
打包**之前**运行；产出的 JSON 会被 ``client/classroom_app.spec`` 打进 .app 内
（``Contents/Resources/classroom_build_info.json``），因此可以事后逐字节回答：

* 这个 .app 是用哪一份源码构建的？（``source_revision`` + ``files[].sha256``）
* 包里那份 QML 与当前工作树是否一致？（比对 ``files[].sha256``）
* 有没有在打包之后偷偷改过源码？（重新计算 source_revision 是否相等）

只读源码，不写除 ``--out`` 之外的任何文件，不联网。

用法：
    python3 tools/classroom_build_info.py            # 写入 client/build_info/classroom_build_info.json
    python3 tools/classroom_build_info.py --print    # 只打印，不落盘
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENT = os.path.join(REPO, "client")

APP_VERSION = "2.0.0"
APP_BUILD = "6"  # BUILD6：B 复核 N4（契约指令⑧版面提醒）+ N7（白名单口径）+ 日志版本动态化；含 EXIT-FIX-01 与 ROUND02 修复

# 进入 .app 的运行期源码集合（不含 tests/ —— 它们不进包）
SOURCE_GLOBS = (
    "classroom_main.py",
    "classroom_app.spec",
    "src/classroom/course_schema.v1.json",
)
SOURCE_DIRS = (
    "src/classroom",          # 顶层 *.py（tests/ 由 _skip 排除）
    "src/classroom/qml",
    "src/classroom/data",
)


def _skip(rel: str) -> bool:
    rel = rel.replace(os.sep, "/")
    if "__pycache__" in rel:
        return True
    if rel.startswith("src/classroom/tests/"):
        return True
    if rel.endswith((".pyc", ".pyo", ".DS_Store")):
        return True
    return False


def _collect() -> list:
    out = []
    for rel in SOURCE_GLOBS:
        p = os.path.join(CLIENT, rel)
        if os.path.isfile(p):
            out.append(rel)
    for d in SOURCE_DIRS:
        base = os.path.join(CLIENT, d)
        for root, dirs, files in os.walk(base):
            dirs[:] = [x for x in dirs if x != "__pycache__" and x != "tests"]
            for fn in files:
                p = os.path.join(root, fn)
                rel = os.path.relpath(p, CLIENT)
                if _skip(rel):
                    continue
                out.append(rel)
    return sorted(set(out))


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git(*args) -> str:
    try:
        p = subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True, timeout=30)
        return p.stdout.strip() if p.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


def build_info() -> dict:
    files = []
    for rel in _collect():
        p = os.path.join(CLIENT, rel)
        try:
            files.append({"path": rel.replace(os.sep, "/"),
                          "sha256": _sha256_file(p),
                          "bytes": os.path.getsize(p)})
        except OSError:
            continue
    lines = "".join("%s\t%s\n" % (f["path"], f["sha256"]) for f in files)
    rev = hashlib.sha256(lines.encode("utf-8")).hexdigest()
    porcelain = _git("status", "--porcelain")
    return {
        "artifact": "classroom_build_info",
        "phase": "CLASSROOM V2 · DELIVERY GATE 02",
        "app_version": APP_VERSION,
        "app_build": APP_BUILD,
        "bundle_name": "小智 AI 学生课堂.app",
        "git_head": _git("rev-parse", "HEAD") or "unknown",
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD") or "unknown",
        "git_dirty_entries": len([x for x in porcelain.splitlines() if x.strip()]),
        "source_revision": rev,
        "source_file_count": len(files),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "generator": "tools/classroom_build_info.py",
        "honesty": ("git_* 字段仅作参考：本工作树按授权**未提交**；"
                    "真正的可复算凭据是 source_revision（对 files[] 的确定性哈希）。"),
        "files": files,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="生成学生课堂 .app 构建信息")
    ap.add_argument("--out", default=os.path.join(CLIENT, "build_info", "classroom_build_info.json"))
    ap.add_argument("--print", dest="do_print", action="store_true")
    a = ap.parse_args()
    info = build_info()
    blob = json.dumps(info, ensure_ascii=False, indent=2)
    if a.do_print:
        print(blob)
        return 0
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(blob)
    os.replace(tmp, a.out)
    print("BUILD_INFO %s" % a.out)
    print("  app_version      = %s (build %s)" % (info["app_version"], info["app_build"]))
    print("  git_head         = %s (%s, dirty=%d)"
          % (info["git_head"][:12], info["git_branch"], info["git_dirty_entries"]))
    print("  source_revision  = %s" % info["source_revision"])
    print("  source_files     = %d" % info["source_file_count"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
