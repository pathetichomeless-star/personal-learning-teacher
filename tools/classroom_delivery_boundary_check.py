#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLASSROOM V2 · DELIVERY GATE 02 —— 边界与一致性检查（交付物 F）。

只读，不写任何文件（除 ``--out`` 证据 JSON），不联网，不修改 git 状态。

检查项
------
A. 冻结六文件（Tina）：工作树 sha256 必须等于 HEAD 且 git 状态干净。
B. 受保护数字人文件：工作树 sha256 必须等于 R3-0 起钉住的基线常量。
C. 未提交/未打标签：暂存区为空，HEAD 仍等于施工基线提交。
D. 网络面：课堂运行期源码（不含 tests/）不得出现非环回 URL 字面量。
E. 源码 ↔ 安装包一致性（若 .app 存在）：包内源码/资源逐字节等于工作树，
   且包内 build info 的 source_revision 与当前源码集合一致。

用法：
    python3 tools/classroom_delivery_boundary_check.py
    python3 tools/classroom_delivery_boundary_check.py --out <evidence.json>
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENT = os.path.join(REPO, "client")
BUNDLE = os.path.join(CLIENT, "dist", "小智 AI 学生课堂.app")
BUILD_INFO_SRC = os.path.join(CLIENT, "build_info", "classroom_build_info.json")

BASELINE_HEAD = "3754e502701713ee420e19b5badee5c421a77f88"

FROZEN_SIX = [
    "gateway/app/turns.py", "gateway/app/qwen.py", "gateway/app/audio.py",
    "gateway/app/protocol.py", "gateway/app/ws.py", "gateway/app/behavior.py",
]

# R3-0 起钉住的受保护数字人文件基线（逐字节）
PROTECTED = {
    "client/src/ui/gui/manager.py":
        "bd2de04b77ea9461ab2ca855b5543237a7c2c18bf6b312855a93f8a353d769c1",
    "client/src/ui/gui/qml/components/AvatarLive2D.qml":
        "32c1c16a8b1c5c906af91bd9ecc166632a4fcfabc079061ce7a90c8b7fcbd358",
    "client/src/avatar/runtime/avatar_page.js":
        "1243b98d346d8bfa39575ff7824e6f8b45805dd1d8d9110b3b60c5dcc12e38e5",
    "client/probe_avatar_qml_offscreen.py":
        "f3cb7ea33770e15eb964204925c71b12f943baac1767d137f7e555ffd4308ceb",
    "client/src/avatar/runtime_server.py":
        "a64046baea038d247b0fad63d76c7d756f882379ea3e8a2510dca2274586d88b",
}

# 允许出现的非环回 URL 情形（不是网络访问面）
_URL_OK_HOSTS = ("127.0.0.1", "localhost", "[::1]", "::1", "json-schema.org")
_URL_RE = re.compile(r"\b(?:https?|wss?)://([A-Za-z0-9._\-\[\]:]+)")

RESULTS = []


def check(name, cond, detail=""):
    ok = bool(cond)
    RESULTS.append({"name": name, "ok": ok, "detail": str(detail)[:400]})
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else "  <- %s" % (detail,)))
    return ok


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def git(*args) -> str:
    p = subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else ""


def head_blob_sha(rel: str) -> str:
    p = subprocess.run(["git", "-C", REPO, "show", "HEAD:%s" % rel],
                       capture_output=True)
    return hashlib.sha256(p.stdout).hexdigest() if p.returncode == 0 else ""


def _runtime_py():
    d = os.path.join(CLIENT, "src", "classroom")
    out = []
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".py") and fn != "__init__.py":
            out.append(os.path.join(d, fn))
    out.append(os.path.join(CLIENT, "classroom_main.py"))
    return out


def _string_literals(path: str):
    """AST 取字符串字面量（排除 docstring）——只看真正会参与运行期的常量。"""
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except SyntaxError:
        return []
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            b = getattr(node, "body", None)
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) \
                    and isinstance(b[0].value.value, str):
                docs.add(id(b[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        REPO, "docs", "engineering", "product-v1", "classroom-v2", "delivery-02",
        "test-results", "boundary_check.json"))
    a = ap.parse_args()

    # ---------------- A. 冻结六文件 ----------------
    bad = []
    for rel in FROZEN_SIX:
        p = os.path.join(REPO, rel)
        wt = sha256_file(p) if os.path.isfile(p) else "<missing>"
        if wt != head_blob_sha(rel):
            bad.append(rel)
    check("A01 冻结六文件（Tina）工作树 == HEAD（逐字节）", not bad, bad)
    check("A02 冻结六文件 git 状态干净（未修改/未暂存/未新增）",
          not git("status", "--porcelain", "--", *FROZEN_SIX).strip(),
          git("status", "--porcelain", "--", *FROZEN_SIX).strip())

    # ---------------- B. 受保护数字人文件 ----------------
    drift = {}
    for rel, want in PROTECTED.items():
        p = os.path.join(REPO, rel)
        got = sha256_file(p) if os.path.isfile(p) else "<missing>"
        if got != want:
            drift[rel] = {"want": want[:16], "got": got[:16]}
    check("B01 受保护数字人 5 文件 == R3-0 基线（逐字节）", not drift, drift)

    # ---------------- C. 未提交 / 未打标签 ----------------
    staged = [x for x in git("diff", "--cached", "--name-only").splitlines() if x.strip()]
    check("C01 暂存区为空（本轮未 git add）", not staged, staged[:5])
    check("C02 HEAD 仍为施工基线提交（未提交/未 amend）",
          git("rev-parse", "HEAD").strip() == BASELINE_HEAD,
          git("rev-parse", "HEAD").strip())

    # ---------------- D. 课堂运行期网络面 ----------------
    offenders = []
    for p in _runtime_py():
        for s in _string_literals(p):
            for m in _URL_RE.finditer(s):
                host = m.group(1).lower()
                if not any(host == h or host.startswith(h) for h in _URL_OK_HOSTS):
                    offenders.append("%s: %s" % (os.path.relpath(p, REPO), s[:60]))
    check("D01 课堂运行期源码无非环回 URL 字面量（无外部/付费网络面）",
          not offenders, offenders[:5])

    # D02 安全子进程：运行期源码不得出现任何子进程能力（独立安全复核通过前不接入）
    import re as _re
    SUBPROC_RE = _re.compile(r"\b(subprocess|os\.system|os\.popen|os\.exec[lv]|Popen)\b")
    sub_off = []
    for p in _runtime_py():
        src = open(p, encoding="utf-8").read()
        for i, line in enumerate(src.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if SUBPROC_RE.search(line):
                sub_off.append("%s:%d: %s" % (os.path.relpath(p, REPO), i, line.strip()[:60]))
    check("D02 课堂运行期源码无子进程能力（subprocess/os.system/Popen）",
          not sub_off, sub_off[:5])

    # ---------------- E. 源码 ↔ 安装包一致性 ----------------
    if not os.path.isdir(BUNDLE):
        check("E00 .app 存在（可做一致性核对）", False, BUNDLE)
    else:
        # frozen 包里 sys._MEIPASS == Contents/Frameworks（__file__ 亦解析到此）
        MEIPASS = os.path.join(BUNDLE, "Contents", "Frameworks")
        info_bundle = os.path.join(BUNDLE, "Contents", "Resources",
                                   "classroom_build_info.json")
        if not os.path.isfile(info_bundle):
            info_bundle = os.path.join(MEIPASS, "classroom_build_info.json")
        check("E01 包内含构建信息 classroom_build_info.json", os.path.isfile(info_bundle),
              info_bundle)
        info = {}
        if os.path.isfile(info_bundle):
            with open(info_bundle, encoding="utf-8") as fh:
                info = json.load(fh)

        # 运行期必需资源（缺任一 ⇒ 冻结包启动失败或界面缺失）
        REQUIRED_RUNTIME = (
            "src/classroom/course_schema.v1.json",     # 导入期 open(SCHEMA_PATH)
            "src/classroom/qml/ClassroomWindow.qml",
            "src/classroom/qml/NavBar.qml",
            "src/classroom/qml/LibraryPanel.qml",
            "src/classroom/qml/ImportPanel.qml",
            "src/classroom/qml/ProofreadPanel.qml",
            "src/classroom/qml/PublishPanel.qml",
            "src/classroom/data/courses.json",
            "classroom_build_info.json",
        )
        missing_req = [r for r in REQUIRED_RUNTIME
                       if not os.path.isfile(os.path.join(MEIPASS, r))]
        check("E02 包内运行期必需资源齐备（%d 项；含导入期 schema JSON）"
              % len(REQUIRED_RUNTIME), not missing_req, missing_req)

        # 随包数据（datas）逐字节 == 工作树
        def _is_shipped_data(rel: str) -> bool:
            rel = rel.replace(os.sep, "/")
            return (rel == "classroom_build_info.json"
                    or rel == "src/classroom/course_schema.v1.json"
                    or rel.startswith("src/classroom/qml/")
                    or rel.startswith("src/classroom/data/"))

        diff = []
        n_checked = 0
        for f in (info.get("files") or []):
            rel, want = f["path"], f["sha256"]
            if not _is_shipped_data(rel):
                continue          # 纯 Python 源码编译进 PYZ，无法按文件比对（由 E03 覆盖）
            cand = os.path.join(MEIPASS, rel)
            if not os.path.isfile(cand):
                diff.append("%s: 包内缺失" % rel)
                continue
            n_checked += 1
            got = sha256_file(cand)
            if got != want:
                diff.append("%s: 包内 %s != 记录 %s" % (rel, got[:12], want[:12]))
        check("E03 包内随包资源逐字节等于构建信息所记（%d 个文件）" % n_checked, not diff,
              diff[:5])

        # 当前工作树重算 source_revision 是否等于包内记录（说明打包后源码未被改动）
        sys.path.insert(0, os.path.join(REPO, "tools"))
        try:
            import classroom_build_info as cbi  # noqa: WPS433
            now = cbi.build_info()
            check("E04 当前源码集合 == 包内记录（打包后源码未改动）",
                  now["source_revision"] == info.get("source_revision"),
                  {"now": now["source_revision"][:16],
                   "bundle": str(info.get("source_revision"))[:16]})
            check("E05 包内 git_head / 源文件数与当前一致",
                  now["git_head"] == info.get("git_head")
                  and now["source_file_count"] == info.get("source_file_count"),
                  {"now": (now["git_head"][:12], now["source_file_count"]),
                   "bundle": (str(info.get("git_head"))[:12],
                              info.get("source_file_count"))})
        except Exception as e:  # noqa: BLE001
            check("E04 当前源码集合 == 包内记录（打包后源码未改动）", False, repr(e))

        # Info.plist 版本
        import plistlib
        with open(os.path.join(BUNDLE, "Contents", "Info.plist"), "rb") as fh:
            pl = plistlib.load(fh)
        check("E06 Info.plist 版本 == 构建信息版本",
              pl.get("CFBundleShortVersionString") == info.get("app_version")
              and str(pl.get("CFBundleVersion")) == str(info.get("app_build")),
              {"plist": (pl.get("CFBundleShortVersionString"), pl.get("CFBundleVersion")),
               "info": (info.get("app_version"), info.get("app_build"))})

    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r["ok"])
    ev = {"artifact": "classroom_delivery_boundary_check",
          "phase": "CLASSROOM V2 · DELIVERY GATE 02 · 交付物 F",
          "baseline_head": BASELINE_HEAD, "results": RESULTS,
          "summary": {"total": total, "passed": passed, "failed": total - passed,
                      "failed_ids": [r["name"] for r in RESULTS if not r["ok"]]}}
    try:
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(ev, fh, ensure_ascii=False, indent=2)
        print("evidence: %s" % a.out)
    except OSError as e:
        print("evidence write failed: %r" % (e,))
    print("=" * 66)
    print("BOUNDARY_CHECK: %d checks, %d PASS, %d FAIL" % (total, passed, total - passed))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
