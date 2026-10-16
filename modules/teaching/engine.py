"""TEXT TEACHING ENGINE (P2-A) — prompt assembly + a **real** text-model call.

Ownership: `modules/teaching`.  Pure logic + one outbound HTTPS/HTTP request;
NO gateway/audio imports, no WebSocket, no audio.

Two hard rules:

* **No fabrication.**  :func:`call_text_model` returns text ONLY from a real HTTP
  response.  Any transport error, non-2xx status, malformed body or empty content
  raises :class:`TextModelError`.  There is no "fallback answer".
* **The model that is called IS the model that was verified.**  The caller passes
  the ``base_url`` / ``model_key`` that belong to the *same* registry model whose
  enable-gate evidence was checked; this module never substitutes a different
  model.  A local (loopback) upstream is reported honestly via ``is_local`` — it
  is a reproducible test model, never presented as a real cloud model.

The endpoint is re-validated here (SSRF) with the provider's own ``allow_local``
policy, and a cross-host redirect is refused.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from modules.model.endpoint_policy import EndpointRejected, validate_endpoint

log = logging.getLogger("teaching.engine")

DEFAULT_TIMEOUT = 20.0
MAX_RESPONSE_BYTES = 256 * 1024

# protocols whose *text* surface is an OpenAI-shaped POST
TEXT_PROTOCOL_PATHS = {
    "openai_compatible": "/v1/chat/completions",
    "dashscope": "/compatible-mode/v1/chat/completions",
}


class TextModelError(RuntimeError):
    """A real text call could not be completed (never a fabricated answer)."""

    def __init__(self, code, detail=""):
        super().__init__("%s%s" % (code, (": %s" % detail) if detail else ""))
        self.code = str(code)
        self.detail = str(detail)


def chat_url(protocol, base_url):
    """Build the chat-completions URL for a provider base URL.

    ``base_url`` may be a bare host, may already end in ``/v1``, or may be the
    full endpoint; the result carries exactly one chat-completions path.
    """
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        raise TextModelError("endpoint_missing", "provider base_url is empty")
    low = base.lower()
    if low.endswith("/chat/completions"):
        return base
    proto = str(protocol or "")
    if proto == "dashscope":
        if low.endswith("/compatible-mode/v1"):
            return base + "/chat/completions"
        return base + "/compatible-mode/v1/chat/completions"
    if low.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def compose_system(teaching_policy, *, course_id=""):
    """Compose the effective system instruction from a snapshotted policy.

    ``teaching_policy`` is the server-built snapshot (``system_instruction`` plus
    display fields).  An empty snapshot yields a neutral teaching instruction —
    never an empty system prompt, and never a claim of capabilities the teacher
    does not have.
    """
    policy = dict(teaching_policy or {})
    core = str(policy.get("system_instruction") or "").strip()
    if not core:
        core = "你是一位 AI 老师，请用清晰、耐心的方式开展教学。"
    lines = [core,
             "",
             "请只把上面「教材参考」中出现的内容当作事实依据；"
             "教材没有提到的内容，如实说明你没有该资料，不要编造。"
             "保持与学生的对话自然、简洁、适合学习。"]
    course = str(course_id or "").strip()
    if course:
        lines.append("本节课所在课程标识：%s。" % course)
    return "\n".join(lines)


def build_messages(history, student_text, *, max_history=12):
    """Build the OpenAI-style message list from the recent dialogue history."""
    msgs = []
    for t in (history or [])[-max(2, int(max_history)):]:
        role = t.get("role")
        if role not in ("student", "teacher"):
            continue
        msgs.append({"role": "user" if role == "student" else "assistant",
                     "content": str(t.get("text") or "")})
    msgs.append({"role": "user", "content": str(student_text or "")})
    return msgs


def _no_redirect():
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
            raise TextModelError("redirect_refused",
                                 "cross-host redirect refused")

    return _NoRedirect()


def call_text_model(*, protocol, base_url, model_key, secret, system, messages,
                    timeout=DEFAULT_TIMEOUT, allow_local=False, resolver=None,
                    opener=None):
    """Perform ONE real chat-completions call and return its text.

    Returns ``{"text": str, "model_key": str, "is_local": bool, "usage": dict}``.
    Raises :class:`TextModelError` on any failure — never returns invented text.
    """
    if not str(secret or "").strip():
        raise TextModelError("credential_missing", "no usable credential")

    # Re-validate the endpoint (SSRF) with the provider's own local policy.
    try:
        safe_base = validate_endpoint(base_url, allow_local=bool(allow_local),
                                      resolver=resolver)
    except EndpointRejected as e:  # noqa: PERF203
        raise TextModelError("endpoint_not_allowed", getattr(e, "reason", str(e)))

    url = chat_url(protocol, safe_base)
    body = json.dumps({"model": str(model_key or ""), "messages": (
        ([{"role": "system", "content": str(system)}] if str(system or "").strip()
         else []) + list(messages or [])),
        "stream": False}, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json",
                 "Authorization": "Bearer %s" % secret})

    # A raw secret must never reach a log line: the URL is logged without query,
    # and the request object (which carries the auth header) is never logged.
    log.info("teaching text call -> %s (model=%s)",
             urllib.parse.urlsplit(url)._replace(query="").geturl(), model_key)

    open_fn = opener or urllib.request.build_opener(_no_redirect()).open
    try:
        with open_fn(req, timeout=float(timeout)) as resp:
            raw = resp.read(MAX_RESPONSE_BYTES + 1)
    except TextModelError:
        raise
    except urllib.error.HTTPError as e:
        # status only — never echo a provider body that could carry secrets
        raise TextModelError("upstream_http_%d" % int(getattr(e, "code", 0) or 0))
    except urllib.error.URLError as e:
        raise TextModelError("upstream_unreachable", str(getattr(e, "reason", ""))[:120])
    except Exception as e:  # noqa: BLE001
        raise TextModelError("upstream_error", type(e).__name__)

    if len(raw) > MAX_RESPONSE_BYTES:
        raise TextModelError("upstream_too_large")
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        raise TextModelError("upstream_bad_json")

    text = _extract_text(data)
    if not str(text).strip():
        raise TextModelError("upstream_empty_content")
    return {"text": str(text).strip(), "model_key": str(model_key or ""),
            "is_local": bool(allow_local) and _is_loopback(safe_base),
            "usage": dict(data.get("usage") or {}) if isinstance(data, dict) else {}}


def _extract_text(data):
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] or {}
        msg = first.get("message")
        if isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                # OpenAI content-parts shape
                return "".join(str(p.get("text") or "") for p in content
                               if isinstance(p, dict))
        if isinstance(first.get("text"), str):
            return first["text"]
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    return ""


def _is_loopback(url):
    try:
        host = (urllib.parse.urlsplit(str(url)).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return False
    return host in ("127.0.0.1", "localhost", "::1")
