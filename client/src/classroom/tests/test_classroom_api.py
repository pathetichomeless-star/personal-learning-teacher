# -*- coding: utf-8 -*-
"""Loopback gateway client tests (CLASSROOM V2 · Agent I · Phase 2).

I01  non-loopback base_url is rejected (client can only talk to 127.0.0.1);
I02  a real request against a local mock server drives state → online;
I03  parsers / health endpoints parse the JSON payload;
I04  **the client never sends ``Authorization``** — only ``X-Classroom-Session``;
I05  HTTP error → structured ``ClassroomApiError`` + state=error (no crash);
I06  unreachable port → state=error with a Chinese reason (no crash);
I07  commit carries ``confirm`` (existing API hard semantics).
I08–I13  **CONTRACT_FIX_01A 一.5** —— 环回客户端**禁止跳转到非 127.0.0.1**：
    I08 302 → 外部主机（evil.test）被拒绝（redirect_blocked）；
    I09 302 → ``file://`` 被拒绝；
    I10 307 → 外部主机被拒绝；
    I11 **环回内部**重定向（→ 同机另一路径）**允许**（不误伤正常网关）；
    I12 旧字符串匹配可被 ``?u=//127.0.0.1:8080`` 绕过 → 新实现严格拒绝；
    I13 base_url 非 http/https（``file://``/``ftp://``）被构造器拒绝。

Run:
    cd client && PYTHONPATH= ./.venv/bin/python src/classroom/tests/test_classroom_api.py
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
_CLIENT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
if _CLIENT not in sys.path:
    sys.path.insert(0, _CLIENT)

from src.classroom.classroom_api import (  # noqa: E402
    ClassroomApiClient, ClassroomApiError, _is_loopback)

RESULTS = []
SEEN = {"headers": [], "paths": [], "bodies": [], "ctype": []}


def check(cid, name, cond, observed=None):
    line = sys._getframe(1).f_lineno
    RESULTS.append({"case_id": cid, "name": name, "passed": bool(cond),
                    "observed": repr(observed)[:300],
                    "asserted_file": os.path.abspath(__file__), "asserted_line": line})
    print(("PASS " if cond else "FAIL ") + "%s %s%s"
          % (cid, name, "" if cond else "  → %r" % (observed,)))
    return bool(cond)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def _record(self):
        SEEN["headers"].append({k.lower(): v for k, v in self.headers.items()})
        SEEN["paths"].append(self.path)

    def _json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, code, location):
        self.send_response(code)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._record()
        if self.path == "/cls/health":
            return self._json(200, {"ok": True, "version": "v2"})
        if self.path == "/cls/knowledge/parsers":
            return self._json(200, {"available": True, "parsers": [
                {"ext": ".pdf", "available": True}, {"ext": ".epub", "available": True},
                {"ext": ".png", "available": False, "reason": "OCR_DEFERRED"}]})
        if self.path.startswith("/cls/knowledge/import/forbidden"):
            return self._json(403, {"error": "forbidden_route"})
        if self.path == "/cls/knowledge/import":
            return self._json(200, {"available": True, "jobs": []})
        # 恶意重定向用例（一.5）
        if self.path == "/cls/redirect/external":
            return self._redirect(302, "http://evil.test/steal")
        if self.path == "/cls/redirect/file":
            return self._redirect(302, "file:///etc/passwd")
        if self.path == "/cls/redirect/external-307":
            return self._redirect(307, "http://evil.test/steal")
        if self.path == "/cls/redirect/loopback":
            port = self.server.server_address[1]
            return self._redirect(302, "http://127.0.0.1:%d/cls/health" % port)
        return self._json(404, {"error": "not_found"})

    def do_POST(self):
        self._record()
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        SEEN["bodies"].append(raw.decode("utf-8", "replace") if raw else "")
        SEEN["ctype"].append(self.headers.get("Content-Type") or "")
        if self.path == "/cls/knowledge/import":
            return self._json(200, {"available": True, "job_id": "job_new",
                                    "status": "parsed", "format": "txt"})
        if self.path.endswith("/commit"):
            return self._json(200, {"available": True, "readback_ok": True})
        if self.path.endswith("/cancel"):
            return self._json(200, {"available": True, "status": "cancelled"})
        return self._json(404, {"error": "not_found"})


def main():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = "http://127.0.0.1:%d" % port

    # I01 loopback only
    try:
        ClassroomApiClient("http://evil.test:1234")
        bad = False
    except ValueError:
        bad = True
    check("I01", "非环回 base_url 被拒绝（只能连 127.0.0.1）", bad)

    c = ClassroomApiClient(base, session_token="sess-abc")
    h = c.health()
    check("I02", "health 请求成功 → 状态 online", c.state == "online" and h.get("ok") is True,
          (c.state, h))

    p = c.parsers()
    ext = {row["ext"]: row["available"] for row in p["parsers"]}
    check("I03a", "parsers 能力表解析正确（含 available=false 的诚实降级）",
          ext.get(".epub") is True and ext.get(".png") is False, ext)
    check("I03b", "list_imports 正常解析", "jobs" in c.list_imports())

    # I04 never Authorization
    seen_has_auth = any("authorization" in hh for hh in SEEN["headers"])
    seen_session = any("x-classroom-session" in hh for hh in SEEN["headers"])
    check("I04a", "客户端从不发送 Authorization 头（无 admin Bearer 路径）", not seen_has_auth)
    check("I04b", "客户端发送 X-Classroom-Session 会话头", seen_session)

    # I07 commit carries confirm
    n0 = len(SEEN["bodies"])
    c.commit_import("job_1")
    body = SEEN["bodies"][n0] if len(SEEN["bodies"]) > n0 else ""
    check("I07", "commit 请求体含 confirm=true（既有 API 硬语义）",
          '"confirm"' in body and "true" in body, body)

    # I05 HTTP error structured
    try:
        c.request("GET", "/cls/knowledge/import/forbidden")
        ok = False
        err = None
    except ClassroomApiError as e:
        ok = True
        err = e
    check("I05", "403 → 结构化 ClassroomApiError（code=forbidden_route）+ state=error",
          ok and err.status == 403 and err.code == "forbidden_route" and c.state == "error",
          (err.status, err.code, c.state) if ok else None)

    # I06 unreachable
    c2 = ClassroomApiClient("http://127.0.0.1:1", session_token="x", timeout=1.0)
    try:
        c2.health()
        ok = False
    except ClassroomApiError as e:
        ok = e.status is None
    check("I06", "无法连接 → error 状态 + 中文原因（不崩溃）",
          ok and c2.state == "error" and "无法连接" in c2.last_error, c2.last_error)

    # ---------------------------------------------------------------- 一.5 重定向
    def _try_redirect(path):
        cc = ClassroomApiClient(base, session_token="sess-abc", timeout=3.0)
        try:
            cc.request("GET", path)
            return None, cc
        except ClassroomApiError as e:
            return e, cc

    e8, c8 = _try_redirect("/cls/redirect/external")
    check("I08", "302 → 外部主机被拒绝（redirect_blocked，不跟随）",
          e8 is not None and e8.code == "redirect_blocked" and c8.state == "error",
          (e8.code if e8 else None, c8.last_error))

    e9, c9 = _try_redirect("/cls/redirect/file")
    check("I09", "302 → file:// 被拒绝（非 http/https ⇒ 非环回）",
          e9 is not None and e9.code == "redirect_blocked", (e9.code if e9 else None))

    e10, c10 = _try_redirect("/cls/redirect/external-307")
    check("I10", "307 → 外部主机被拒绝（307 同样不跟随）",
          e10 is not None and e10.code == "redirect_blocked", (e10.code if e10 else None))

    e11, c11 = _try_redirect("/cls/redirect/loopback")
    check("I11", "环回内部重定向被允许（不误伤正常网关）→ 拿到 health 结果",
          e11 is None and c11.state == "online", (e11.code if e11 else "ok"))

    # I12 旧字符串匹配可被查询串绕过 → 新实现必须严格拒绝
    bypass = "http://evil.test/?u=//127.0.0.1:8080"
    check("I12", "旧字符串匹配可被 `?u=//127.0.0.1:8080` 绕过；新实现严格拒绝",
          _is_loopback(bypass) is False, _is_loopback(bypass))
    check("I12b", "正常环回地址仍被接受（127.0.0.1 / localhost / [::1]）",
          _is_loopback("http://127.0.0.1:28310/x") and _is_loopback("http://localhost:1/")
          and _is_loopback("http://[::1]:9/y"), None)

    # I13 非 http/https base_url 被构造器拒绝
    bad_scheme = []
    for u in ("file://127.0.0.1/etc/passwd", "ftp://127.0.0.1/x"):
        try:
            ClassroomApiClient(u)
            bad_scheme.append(u)
        except ValueError:
            pass
    check("I13", "非 http/https 的 base_url 被构造器拒绝（file:// 与 ftp://）",
          bad_scheme == [], bad_scheme)

    # ------------------------------------------------- 一.2 /cls 契约对齐（I14）
    import re as _re
    from src.classroom import classroom_api as _mod

    src = open(_mod.__file__, "r", encoding="utf-8").read()
    # 源码里出现的 "/cls/..." 路径字面量（排除白名单表与文档串中的模板）
    used = set(_re.findall(r'"(/cls/[^"]*)"', src))
    used |= {p.replace(" ", "") for p in _re.findall(r'"(/cls/[^"]*%s)"', src)}
    allowed = {p for _, p in _mod.WHITELIST_PATHS}
    # 载入时把 "%s" 形式规范为 {job_id}
    norm = {u.replace("%s", "{job_id}") for u in used}
    stray = sorted(u for u in norm if u not in allowed)
    check("I14a", "客户端只用契约白名单内的 /cls/ 路径（无越界路径）",
          stray == [], {"used": sorted(norm), "stray": stray})

    # AST 级：只看**代码字符串字面量**（排除 docstring 里对边界的说明性提及）
    import ast as _ast
    _tree = _ast.parse(src)
    _docs = set()
    for _n in _ast.walk(_tree):
        if isinstance(_n, (_ast.Module, _ast.ClassDef, _ast.FunctionDef, _ast.AsyncFunctionDef)):
            _d = _ast.get_docstring(_n, clean=False)
            if _d:
                _docs.add(_d)
    _lits = [n.value for n in _ast.walk(_tree)
             if isinstance(n, _ast.Constant) and isinstance(n.value, str)]
    _code_lits = [s for s in _lits if s not in _docs]
    bad_lits = {
        "admin": [s for s in _code_lits if s.strip().startswith("/admin")],
        "auth": [s for s in _code_lits if s.strip().lower() == "authorization"],
    }

    check("I14b", "客户端**代码字面量**中不存在 /admin/ 路径或 Authorization 头（管理面结构不可达）",
          bad_lits["admin"] == [] and bad_lits["auth"] == [],
          bad_lits)

    ctype0 = len(SEEN["ctype"])
    up = c.start_import(dataset_id="ds_demo", filename="sample.txt",
                        content="Hello world.\n你好。".encode("utf-8"),
                        title="演示教材", preview_chars=200)
    body = SEEN["bodies"][-1] if SEEN["bodies"] else ""
    ctypes = SEEN["ctype"][ctype0:] or [SEEN["ctype"][-1] if SEEN["ctype"] else ""]
    check("I14c", "start_import 走 POST /cls/knowledge/import 且为 multipart/form-data",
          up.get("job_id") == "job_new" and any("multipart/form-data" in ct for ct in ctypes),
          (up, ctypes))
    check("I14d", "multipart 体含 dataset_id / file 部件与文件内容（stdib 组装正确）",
          'name="dataset_id"' in body and 'name="file"' in body
          and "Hello world." in body and 'filename="sample.txt"' in body,
          body[:160])

    srv.shutdown()

    passed = sum(1 for r in RESULTS if r["passed"])
    failed = [r["case_id"] for r in RESULTS if not r["passed"]]
    print("\n" + "=" * 70)
    print("CLASSROOM_API: %d checks, %d PASS, %d FAIL" % (len(RESULTS), passed, len(failed)))
    if failed:
        print("FAILED:", ", ".join(failed))

    ev = os.path.join(_CLIENT, "..", "docs", "engineering", "product-v1",
                      "classroom-v2", "evidence", "classroom_api_tests.json")
    try:
        with open(os.path.abspath(ev), "w", encoding="utf-8") as f:
            json.dump({"artifact": "classroom_api_tests",
                       "scope": "CLASSROOM V2 PHASE2 · Agent I（环回网关 API 适配）",
                       "results": RESULTS,
                       "summary": {"total": len(RESULTS), "passed": passed,
                                   "failed": len(failed), "failed_ids": failed}},
                      f, ensure_ascii=False, indent=2)
        print("evidence:", os.path.abspath(ev))
    except Exception as e:  # noqa: BLE001
        print("evidence 写入失败（不影响结论）:", e)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
