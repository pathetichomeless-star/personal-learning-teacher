"""VOICE ENGINE (P2-B1) — real ASR / TTS calls for the composed voice pipeline.

Ownership: `modules/voice`.  Pure logic + one outbound HTTP request per call; NO
gateway/audio imports, no WebSocket, no Opus/VAD, and — critically — **nothing
here touches the frozen Tina realtime link**: this module speaks plain HTTP to a
configured provider, it does not open the production audio session.

Two hard rules, identical in spirit to the P2-A text engine:

* **No fabrication.**  :func:`call_asr` returns a transcript ONLY from a real HTTP
  response; :func:`call_tts` returns audio ONLY from a real HTTP response.  Any
  transport error, non-2xx status, malformed body or empty payload raises
  :class:`VoiceUpstreamError`.  There is no fallback transcript and no synthetic
  waveform.
* **The upstream that is called IS the one that was verified.**  The caller passes
  the ``base_url`` / ``model_key`` of the model whose registry evidence and
  credential were checked; this module never substitutes another provider.

The endpoint is re-validated here (SSRF) with the provider's own ``allow_local``
policy, and a cross-host redirect is refused.
"""

from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from modules.model.endpoint_policy import EndpointRejected, validate_endpoint

log = logging.getLogger("voice.engine")

DEFAULT_TIMEOUT = 20.0
MAX_RESPONSE_BYTES = 512 * 1024
MAX_AUDIO_BYTES = 4 * 1024 * 1024

# protocols whose speech surface is an OpenAI-shaped POST
ASR_PATHS = {
    "openai_audio_compatible": "/v1/audio/transcriptions",
    "openai_compatible": "/v1/audio/transcriptions",
}
TTS_PATHS = {
    "openai_audio_compatible": "/v1/audio/speech",
    "openai_compatible": "/v1/audio/speech",
}


class VoiceUpstreamError(RuntimeError):
    """A real speech call could not be completed (never a fabricated result)."""

    def __init__(self, code, detail=""):
        super().__init__("%s%s" % (code, (": %s" % detail) if detail else ""))
        self.code = str(code)
        self.detail = str(detail)


def _endpoint_url(base_url, protocol, path_map, default_path):
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        raise VoiceUpstreamError("endpoint_missing", "provider base_url is empty")
    low = base.lower()
    for tail in tuple(path_map.values()) + (default_path,):
        if low.endswith(tail):
            return base
    if low.endswith("/v1"):
        return base + default_path[len("/v1"):]
    return base + default_path


def asr_url(protocol, base_url):
    p = ASR_PATHS.get(str(protocol or ""), "/v1/audio/transcriptions")
    return _endpoint_url(base_url, protocol, ASR_PATHS, p)


def tts_url(protocol, base_url):
    p = TTS_PATHS.get(str(protocol or ""), "/v1/audio/speech")
    return _endpoint_url(base_url, protocol, TTS_PATHS, p)


def _no_redirect():
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
            raise VoiceUpstreamError("redirect_refused",
                                     "cross-host redirect refused")

    return _NoRedirect()


def _post_json(*, url, secret, payload, timeout, allow_local, resolver, opener,
               accept="application/json"):
    try:
        safe_base = validate_endpoint(url, allow_local=bool(allow_local),
                                      resolver=resolver)
    except EndpointRejected as e:
        raise VoiceUpstreamError("endpoint_not_allowed",
                                 getattr(e, "reason", str(e)))
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        safe_base, data=body, method="POST",
        headers={"Content-Type": "application/json", "Accept": accept,
                 "Authorization": "Bearer %s" % secret})
    log.info("voice upstream call -> %s",
             urllib.parse.urlsplit(safe_base)._replace(query="").geturl())
    open_fn = opener or urllib.request.build_opener(_no_redirect()).open
    try:
        resp = open_fn(req, timeout=float(timeout))
    except VoiceUpstreamError:
        raise
    except urllib.error.HTTPError as e:
        raise VoiceUpstreamError("upstream_http_%d" % int(getattr(e, "code", 0) or 0))
    except urllib.error.URLError as e:
        raise VoiceUpstreamError("upstream_unreachable",
                                 str(getattr(e, "reason", ""))[:120])
    except Exception as e:  # noqa: BLE001
        raise VoiceUpstreamError("upstream_error", type(e).__name__)
    try:
        raw = resp.read(MAX_RESPONSE_BYTES + 1)
        ctype = str(resp.headers.get("Content-Type") or "").lower()
    except Exception as e:  # noqa: BLE001
        raise VoiceUpstreamError("upstream_error", type(e).__name__)
    finally:
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass
    if len(raw) > MAX_RESPONSE_BYTES:
        raise VoiceUpstreamError("upstream_too_large")
    return raw, ctype


def call_asr(*, protocol, base_url, model_key, secret, audio_bytes, audio_format,
             sample_rate, language="", timeout=DEFAULT_TIMEOUT, allow_local=False,
             resolver=None, opener=None):
    """Transcribe **real** audio bytes through the configured ASR model.

    Returns ``{"text": str, "is_local": bool, "upstream": str}``.  Raises on any
    failure — an empty or malformed response is never turned into a transcript.
    """
    if not str(secret or "").strip():
        raise VoiceUpstreamError("credential_missing", "no usable credential")
    if not isinstance(audio_bytes, (bytes, bytearray)) or not audio_bytes:
        raise VoiceUpstreamError("empty_audio", "no audio payload")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise VoiceUpstreamError("audio_too_large")
    payload = {"model": str(model_key or ""),
               "input_audio": {"data": base64.b64encode(bytes(audio_bytes)).decode(),
                               "format": str(audio_format or "pcm16"),
                               "sample_rate": int(sample_rate or 0)}}
    if str(language or "").strip():
        payload["language"] = str(language)[:16]
    url = asr_url(protocol, base_url)
    raw, _ctype = _post_json(url=url, secret=secret, payload=payload,
                             timeout=timeout, allow_local=allow_local,
                             resolver=resolver, opener=opener)
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        raise VoiceUpstreamError("upstream_bad_json")
    text = ""
    if isinstance(data, dict):
        for key in ("text", "transcript", "result"):
            if isinstance(data.get(key), str):
                text = data[key]
                break
    if not str(text).strip():
        raise VoiceUpstreamError("upstream_empty_transcript")
    return {"text": str(text).strip()[:2000], "is_local": bool(allow_local),
            "upstream": str(base_url)}


def call_tts(*, protocol, base_url, model_key, secret, text, voice_id="",
             audio_format="pcm16", sample_rate=24000, speed=None,
             timeout=DEFAULT_TIMEOUT, allow_local=False, resolver=None, opener=None):
    """Synthesize speech for ``text`` through the configured TTS model.

    Returns ``{"audio_bytes": int, "format": str, "content_type": str, "is_local": bool}``
    — only *metadata* is returned to callers; the PCM/Opus payload itself is not
    persisted anywhere (a classroom record stores counts, never audio).
    """
    if not str(secret or "").strip():
        raise VoiceUpstreamError("credential_missing", "no usable credential")
    if not str(text or "").strip():
        raise VoiceUpstreamError("empty_text")
    payload = {"model": str(model_key or ""), "input": str(text)[:4000],
               "voice": str(voice_id or ""), "format": str(audio_format or "pcm16"),
               "sample_rate": int(sample_rate or 0)}
    if speed is not None:
        payload["speed"] = float(speed)
    url = tts_url(protocol, base_url)
    raw, ctype = _post_json(url=url, secret=secret, payload=payload,
                            timeout=timeout, allow_local=allow_local,
                            resolver=resolver, opener=opener,
                            accept="application/json, audio/*")
    if ctype.startswith("audio/"):
        nbytes = len(raw)
    else:
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            raise VoiceUpstreamError("upstream_bad_json")
        b64 = ""
        if isinstance(data, dict):
            for key in ("audio", "audio_b64", "data", "output_audio"):
                v = data.get(key)
                if isinstance(v, str) and v:
                    b64 = v
                    break
        if not b64:
            raise VoiceUpstreamError("upstream_empty_audio")
        try:
            nbytes = len(base64.b64decode(b64, validate=False))
        except Exception:  # noqa: BLE001
            raise VoiceUpstreamError("upstream_bad_audio")
    if nbytes <= 0:
        raise VoiceUpstreamError("upstream_empty_audio")
    return {"audio_bytes": min(nbytes, MAX_AUDIO_BYTES), "format": str(audio_format),
            "content_type": ctype or "application/octet-stream",
            "is_local": bool(allow_local)}
