"""Capability probe for model verification (contract §2.2, §2.3).

Two strictly separated levels:

* :func:`probe_protocol` — **offline**, pure: is a real adapter registered for the
  protocol?  It performs no network I/O and writes nothing.  This is the honest
  ceiling of any *simulated* check.
* :func:`probe_verified` — a **real** reachability + auth check against the
  provider's own *metadata* endpoint.  It is gated by explicit authorization and
  by construction never issues a generation, so it cannot incur paid usage.  Only
  protocols with a free metadata endpoint are supported; everything else reports
  honestly that a paid verification would be required.

The probe re-validates the endpoint (SSRF) and refuses cross-host redirects.
"""

from __future__ import annotations

import http.client
import logging
import time
import urllib.error
import urllib.request

from modules.model.endpoint_policy import (EndpointRejected, peer_allowed,
                                           validate_endpoint)
from modules.model.registry import REGISTERED_ADAPTERS

log = logging.getLogger("modules.model.probe")

# Protocols whose metadata listing is free (no token spend).
# P2-B1: the audio-compatible protocol is an OpenAI-compatible endpoint too, so its
# model listing is free metadata as well — verifying it never issues a generation
# (and therefore can never bill an ASR / TTS request).
FREE_METADATA_PROTOCOLS = ("openai_compatible", "openai_audio_compatible")


class ProbeError(RuntimeError):
    """Base class for probe refusals."""


class NotAuthorized(ProbeError):
    """Real (potential-charge) verification was attempted without authorization."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A cross-host redirect is refused instead of followed (contract §3.3)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        raise urllib.error.HTTPError(req.full_url, code,
                                     "cross-host redirect refused", headers, fp)


def _peer_checked_class(base_cls, allow_local):
    """A connection class that re-verifies the **actually connected** peer IP
    right after connect (contract §3.3): a name that re-resolves inward between
    validation and connection is refused before any request data is sent."""

    class _Conn(base_cls):
        def connect(self):
            super().connect()
            try:
                peer = self.sock.getpeername()[0]
            except OSError:
                peer = None
            if not peer_allowed(peer, allow_local=allow_local):
                self.close()
                raise EndpointRejected("connected_ip_blocked")

    return _Conn


class _PeerCheckedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, allow_local):
        super().__init__()
        self._allow_local = allow_local

    def http_open(self, req):
        return self.do_open(_peer_checked_class(http.client.HTTPConnection,
                                                self._allow_local), req)


class _PeerCheckedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, allow_local):
        super().__init__()
        self._allow_local = allow_local

    def https_open(self, req):
        return self.do_open(_peer_checked_class(http.client.HTTPSConnection,
                                                self._allow_local), req,
                            context=self._context)


def _opener(allow_local=False):
    return urllib.request.build_opener(
        _NoRedirect, _PeerCheckedHTTPHandler(allow_local),
        _PeerCheckedHTTPSHandler(allow_local))


def _models_url(base):
    """Join the free metadata path tolerantly: both ``https://host`` and
    ``https://host/v1`` yield the ``…/v1/models`` listing endpoint."""
    return base + ("/models" if base.endswith("/v1") else "/v1/models")


def probe_protocol(protocol, adapter) -> dict:
    """Offline protocol check — no network, no state change."""
    ok = str(adapter) in REGISTERED_ADAPTERS
    return {
        "mode": "protocol",
        "protocol_ok": bool(ok),
        "verified": False,
        "network": False,
        "latency_ms": 0,
        "adapter": str(adapter),
        "detail": ("适配器已注册：%s" % adapter) if ok
                  else ("适配器未注册：%s（需先实现/注册适配器）" % adapter),
    }


def probe_verified(provider, secret, *, timeout=5.0, authorized=False,
                   opener=None, resolver=None) -> dict:
    """Perform a real, free metadata probe and return the honest outcome.

    Raises :class:`NotAuthorized` when authorization is missing.  On success the
    caller may write ``verified`` evidence; a failure writes nothing.
    """
    if authorized is not True:
        raise NotAuthorized("test_not_authorized")
    protocol = str(provider.get("protocol") or "")
    base = str(provider.get("base_url") or "").rstrip("/")
    # re-validate (the record may have been written by an older build)
    validate_endpoint(base, allow_local=bool(provider.get("allow_local")),
                      resolver=resolver)
    if protocol not in FREE_METADATA_PROTOCOLS:
        return {"mode": "verified", "verified": False, "network": False,
                "latency_ms": 0, "reason": "no_free_probe_for_protocol",
                "detail": "该协议没有免费元数据探测；需产品负责人授权后做付费验证"}
    url = _models_url(base)
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer %s" % str(secret or ""),
        "Accept": "application/json"})
    t0 = time.monotonic()
    try:
        with (opener or _opener(bool(provider.get("allow_local")))).open(
                req, timeout=timeout) as resp:
            resp.read(4096)
            code = int(getattr(resp, "status", None) or resp.getcode())
            ok = 200 <= code < 300
    except urllib.error.HTTPError as e:
        return {"mode": "verified", "verified": False, "network": True,
                "latency_ms": int((time.monotonic() - t0) * 1000),
                "reason": "http_%d" % int(getattr(e, "code", 0)),
                "detail": "上游返回错误状态，验证未通过"}
    except Exception as e:  # noqa: BLE001  (timeout / DNS / TLS -> honest failure)
        return {"mode": "verified", "verified": False, "network": True,
                "latency_ms": int((time.monotonic() - t0) * 1000),
                "reason": type(e).__name__.lower(),
                "detail": "连接失败，验证未通过"}
    return {"mode": "verified", "verified": bool(ok), "network": True,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "reason": None if ok else "non_2xx",
            "detail": "真实探测成功（免费元数据接口，未发起生成调用）" if ok
                      else "上游返回非 2xx，验证未通过"}
