# -*- coding: utf-8 -*-
"""Loopback gateway API client for the classroom (CLASSROOM V2 · Agent I · Phase 2).

A tiny, **dependency-free** (stdlib ``urllib``) client the student UI uses to
talk to the local gateway.  It adapts the *existing* knowledge-import API; it does
**not** re-implement parsing or the import pipeline.

Hard boundaries
---------------
* **Never sends an admin Bearer.** The only auth header is
  ``X-Classroom-Session`` (the restricted loopback capability, see D1 §3.4).
  There is no code path that can attach ``Authorization``.
* **Loopback only.** The base URL is asserted to be ``127.0.0.1`` / ``localhost``.
* **No off-loopback redirects.** A malicious / compromised loopback service must not
  be able to bounce this client to ``evil.test`` or ``file://`` — the redirect
  handler refuses any hop whose target is not loopback, and the final URL of every
  response is re-verified before the body is trusted (CONTRACT_FIX_01A 一.5).
* **Network four-states** are modelled explicitly so the UI can show
  ``离线 / 连接中 / 在线 / 错误`` — no silent failures.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request

STATES = ("offline", "connecting", "online", "error")
_ALLOWED_HOSTS = ("127.0.0.1", "localhost", "::1")
_ALLOWED_SCHEMES = ("http", "https")

# 学生侧**唯一**允许访问的路径集合（契约 `api/STUDENT_CLS_KNOWLEDGE_CONTRACT.md §2`）。
# 对齐测试 I14 断言：本模块中出现的每个路径字面量都必须落在该白名单内，
# 且**不存在**任何 `/admin/` 前缀 —— 学生客户端结构上够不到管理面。
WHITELIST_PATHS = (
    ("GET", "/cls/health"),
    ("GET", "/cls/knowledge/parsers"),
    ("POST", "/cls/knowledge/import"),
    ("GET", "/cls/knowledge/import"),
    ("GET", "/cls/knowledge/import/{job_id}"),
    ("POST", "/cls/knowledge/import/{job_id}/commit"),
    ("POST", "/cls/knowledge/import/{job_id}/cancel"),
    ("POST", "/cls/knowledge/import/{job_id}/retry"),
)


def _host_is_loopback(host) -> bool:
    if not host:
        return False
    return str(host).strip("[]").lower() in _ALLOWED_HOSTS


def _safe_origin(url: str) -> str:
    """只回显 scheme://host[:port]，绝不回显可能含凭据的完整 URL。"""
    try:
        p = urllib.parse.urlsplit(str(url or ""))
    except ValueError:
        return "<unparsable>"
    host = p.hostname or ""
    if ":" in host:
        host = "[%s]" % host
    return "%s://%s%s" % (p.scheme or "?", host, (":%d" % p.port) if p.port else "")


class _LoopbackOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """只允许**环回内部**的重定向；任何指向非环回地址的跳转一律拒绝。

    ``urllib`` 默认会跟随 301/302/303/307/308。作为只应与本机网关通信的客户端，
    跟随到任意主机就是一次 SSRF：环回服务（或本机被占用的端口）可把会话令牌
    带出去。这里在**跳转发生前**校验目标，非环回即抛 ``HTTPError``。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _is_loopback(newurl):
            raise urllib.error.HTTPError(
                req.full_url, code,
                "拒绝跳转到非环回地址：%s" % _safe_origin(newurl), headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _LoopbackOnlyProxyHandler(urllib.request.ProxyHandler):
    """显式空代理：环回请求**必须绕过任何系统代理**（HTTP(S)_PROXY 环境变量）。"""

    def __init__(self):
        super().__init__({})


# 环回请求**必须绕过任何系统代理**，且**不得被重定向到非环回地址**。
_OPENER = urllib.request.build_opener(
    _LoopbackOnlyProxyHandler(), _LoopbackOnlyRedirectHandler())


class ClassroomApiError(Exception):
    def __init__(self, message, *, status=None, code=None, detail=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.detail = detail


class ClassroomApiClient:
    """Minimal HTTP client for the loopback classroom gateway."""

    def __init__(self, base_url: str, *, session_token: str = "", timeout: float = 5.0):
        if not _is_loopback(base_url):
            raise ValueError("base_url 必须是本机环回地址（127.0.0.1/localhost/::1），得到 %r" % base_url)
        self.base_url = base_url.rstrip("/")
        self.session_token = str(session_token or "")
        self.timeout = float(timeout)
        self.state = "offline"
        self.last_error = ""

    # ---- auth (session-only, never bearer) --------------------------------
    def _headers(self, *, json_body: bool = False) -> dict:
        # 结构性保证：这里**只有** X-Classroom-Session；不存在 Authorization 分支
        h = {"Accept": "application/json", "X-Classroom-Session": self.session_token}
        if json_body:
            h["Content-Type"] = "application/json"
        return h

    # ---- core request -----------------------------------------------------
    def _send(self, req: urllib.request.Request) -> dict:
        """统一的发送/解析/错误分类（所有端点共用，避免各端点各自漏一道防线）。"""
        self.state = "connecting"
        try:
            with _OPENER.open(req, timeout=self.timeout) as resp:
                # 二次防线：即便某条路径绕过了重定向处理器，也绝不信任非环回的最终地址
                final = resp.geturl()
                if not _is_loopback(final):
                    self.state = "error"
                    self.last_error = "网关把请求导向了非环回地址，已拒绝：%s" % _safe_origin(final)
                    raise ClassroomApiError(self.last_error, code="redirect_blocked")
                raw = resp.read()
                self.state = "online"
                try:
                    return json.loads(raw.decode("utf-8")) if raw else {}
                except ValueError:
                    raise ClassroomApiError("响应不是合法 JSON", status=resp.status)
        except urllib.error.HTTPError as e:
            self.state = "error"
            detail = ""
            code = None
            # 任何**未被跟随**的 3xx 都意味着重定向被拦下（本客户端的处理器或 stdlib 的
            # 非 http(s) 拦截）。语义上都是「跳转被拒绝」，统一归类为 redirect_blocked。
            if e.code in (301, 302, 303, 307, 308):
                self.last_error = ("网关响应了重定向（HTTP %d），已拒绝跟随：%s"
                                   % (e.code, str(e.reason or "")))
                raise ClassroomApiError(self.last_error, status=e.code,
                                        code="redirect_blocked")
            try:
                payload = json.loads(e.read().decode("utf-8"))
                code = payload.get("error")
                detail = payload.get("detail") or ""
            except Exception:  # noqa: BLE001
                pass
            self.last_error = "网关返回 %d %s" % (e.code, code or "")
            raise ClassroomApiError(self.last_error, status=e.code, code=code, detail=detail)
        except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
            self.state = "error"
            self.last_error = "无法连接本机网关（%s）" % type(e).__name__
            raise ClassroomApiError(self.last_error)
        except ClassroomApiError:
            raise
        except Exception as e:  # noqa: BLE001
            self.state = "error"
            self.last_error = "请求失败（%s）" % type(e).__name__
            raise ClassroomApiError(self.last_error)

    def request(self, method: str, path: str, *, body: "dict | None" = None) -> dict:
        url = self.base_url + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method.upper(),
                                     headers=self._headers(json_body=body is not None))
        return self._send(req)

    # ---- knowledge endpoints (existing API, adapted) ----------------------
    def health(self) -> dict:
        return self.request("GET", "/cls/health")

    def parsers(self) -> dict:
        """`available` capability table (drives the '暂不支持' UI honestly)."""
        return self.request("GET", "/cls/knowledge/parsers")

    def start_import(self, *, dataset_id: str, filename: str, content: bytes,
                     title: "str | None" = None, preview_chars: "int | None" = None) -> dict:
        """上传教材（``multipart/form-data``）——契约 §3.4。

        纯 stdlib 组装 multipart 体（无第三方依赖）。**上传不写知识库**：只有
        ``commit_import()`` 才落盘（既有 API 硬语义，客户端不得简化）。
        """
        import uuid
        boundary = "----cls%s" % uuid.uuid4().hex
        crlf = b"\r\n"
        buf = bytearray()

        def _text(name: str, value: str) -> None:
            buf.extend(("--%s%s" % (boundary, "\r\n")).encode())
            buf.extend(('Content-Disposition: form-data; name="%s"%s' % (name, "\r\n")).encode())
            buf.extend(crlf)
            buf.extend(str(value).encode("utf-8"))
            buf.extend(crlf)

        _text("dataset_id", str(dataset_id))
        if title is not None:
            _text("title", str(title))
        if preview_chars is not None:
            _text("preview_chars", str(int(preview_chars)))
        # file part
        buf.extend(("--%s%s" % (boundary, "\r\n")).encode())
        buf.extend(('Content-Disposition: form-data; name="file"; filename="%s"%s'
                    % (str(filename).replace('"', ""), "\r\n")).encode())
        buf.extend(b"Content-Type: application/octet-stream\r\n")
        buf.extend(crlf)
        buf.extend(bytes(content or b""))
        buf.extend(crlf)
        buf.extend(("--%s--%s" % (boundary, "\r\n")).encode())

        h = self._headers()
        h["Content-Type"] = "multipart/form-data; boundary=%s" % boundary
        req = urllib.request.Request(self.base_url + "/cls/knowledge/import",
                                     data=bytes(buf), method="POST", headers=h)
        return self._send(req)

    def list_imports(self) -> dict:
        return self.request("GET", "/cls/knowledge/import")

    def get_import(self, job_id: str) -> dict:
        return self.request("GET", "/cls/knowledge/import/%s" % job_id)

    def commit_import(self, job_id: str) -> dict:
        # 既有 API 硬语义：commit 必须带 confirm
        return self.request("POST", "/cls/knowledge/import/%s/commit" % job_id,
                            body={"confirm": True})

    def cancel_import(self, job_id: str) -> dict:
        return self.request("POST", "/cls/knowledge/import/%s/cancel" % job_id)

    def retry_import(self, job_id: str) -> dict:
        return self.request("POST", "/cls/knowledge/import/%s/retry" % job_id)

    def snapshot(self) -> dict:
        return {"state": self.state, "base_url": self.base_url,
                "has_session": bool(self.session_token), "last_error": self.last_error}


def _is_loopback(url: str) -> bool:
    """严格判定：scheme ∈ {http,https} 且 hostname 恰为 127.0.0.1 / localhost / ::1。"""
    try:
        parts = urllib.parse.urlsplit(str(url or ""))
    except ValueError:
        return False
    if parts.scheme not in _ALLOWED_SCHEMES:
        return False
    return _host_is_loopback(parts.hostname)
