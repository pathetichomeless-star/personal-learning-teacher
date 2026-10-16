"""ADMIN V4 realtime capability probe (P2-B2-R3-2C) — the honest evidence
channel for `dashscope` realtime models.

Why this exists
---------------
The free metadata probe (`modules/model/probe.py`) only covers the
OpenAI-compatible protocols; a `dashscope` realtime model had NO way to obtain
real verification evidence, so it could never pass `enable_gate`
(`evidence_missing`) and the teacher route stayed unreachable (fail-safe, but
also fail-stuck).  This module adds the missing channel — strictly gated:

* a dedicated authorization flag (``MODEL_REALTIME_PROBE_AUTHORIZED``, default
  off) PLUS an explicit ``confirm_realtime`` in the request body;
* the dial uses the PROVIDER'S OWN sealed credential (``CredentialStore``) —
  the global/Tina key is never read (no code path reaches ``QWEN_SECRET_FILE``
  or the global env key);
* only endpoints that pass the endpoint policy and the realtime binding
  derivation are dialled;
* the result HONESTLY distinguishes the stages: ``handshake`` (session.created
  received) and ``session_compat`` (session.updated after a session.update
  CONFIGURATION message — no audio and no generation request is ever sent, so
  the probe triggers no model inference); the audio stage is **not**
  implemented yet and is always reported as ``audio: "not_tested"``;
* a successful handshake/session writes the ladder level
  ``realtime_handshake`` — BETWEEN ``adapter_present`` and ``verified`` — so it
  can never be confused with full capability verification and can never satisfy
  ``enable_gate`` by itself (which requires ``>= verified`` and, for
  ``oral_realtime``, ``realtime_safe``).  A failed probe writes NO evidence.

This round is MOCK-verified only (local mock WS upstream); a real Bailian dial
is a later, separately authorized gate.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

import aiohttp

log = logging.getLogger("rtl.admin.realtime_probe")

#: server events that mark each honest stage
_SESSION_CREATED = "session.created"
_SESSION_UPDATED = "session.updated"

#: hard ceilings for the probe (a later authorization gate may tune these)
HANDSHAKE_TIMEOUT_S = 5.0
SESSION_TIMEOUT_S = 5.0
OVERALL_DEADLINE_S = 20.0


async def _await_event(ws, want_type, timeout_s):
    """Await server frames until ``want_type`` or timeout.

    Returns ``(ok, reason)``.  Non-matching JSON events are skipped; an ``error``
    event aborts with a readable reason; a closed socket aborts.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False, "timeout"
        try:
            msg = await ws.receive(timeout=remaining)
        except asyncio.TimeoutError:
            return False, "timeout"
        if msg.type == aiohttp.WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
            except Exception:
                continue                      # non-JSON frame: skip
            ev = str(data.get("type") or "")
            if ev == want_type:
                return True, None
            if ev == "error":
                err = data.get("error") or {}
                return False, "server_error:%s" % (
                    err.get("code") or err.get("message") or "error")
            continue                          # other server events: keep waiting
        if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING,
                        aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
            return False, "connection_closed"
        # binary keep-alives: ignore


async def realtime_capability_probe(ws_url, api_key, *, model, voice,
                                    timeout_s=HANDSHAKE_TIMEOUT_S,
                                    overall_deadline_s=OVERALL_DEADLINE_S):
    """Dial the model's realtime endpoint and report the honest stages.

    Returns a JSON-safe dict::

        {mode, network, handshake, session_compat, audio, verified,
         latency_ms, reason, detail}

    ``network=True`` means a socket was actually opened (billing-capable — the
    caller must have enforced the authorization gate + confirm).  ``verified``
    is ALWAYS False here: the audio stage is a later, separately authorized
    gate, so this probe can never fabricate full capability evidence.
    """
    out = {"mode": "realtime_handshake", "network": False, "handshake": False,
           "session_compat": False, "audio": "not_tested", "verified": False,
           "latency_ms": None, "reason": None, "detail": {}}
    headers = {"Authorization": "Bearer " + str(api_key or "")}
    deadline = time.monotonic() + max(1.0, float(overall_deadline_s))
    timeout = aiohttp.ClientTimeout(total=max(1.0, float(overall_deadline_s)),
                                    sock_connect=max(1.0, float(overall_deadline_s)))
    t0 = time.monotonic()
    try:
        async with aiohttp.ClientSession(timeout=timeout) as sess:
            ws = await sess.ws_connect(
                ws_url, headers=headers, heartbeat=10, max_msg_size=0)
            out["network"] = True
            try:
                ok, why = await _await_event(
                    ws, _SESSION_CREATED,
                    min(timeout_s, max(0.5, deadline - time.monotonic())))
                out["handshake"] = bool(ok)
                if not ok:
                    out["reason"] = "handshake_%s" % (why or "failed")
                    return out
                out["latency_ms"] = int((time.monotonic() - t0) * 1000)
                # session.update is a CONFIGURATION message: no audio, no
                # generation request, no model inference -> not billable by
                # itself.  Its acknowledgement (session.updated) proves the
                # server accepted the session shape (会话兼容).
                update = {"type": "session.update", "session": {
                    "model": str(model or ""),
                    "voice": str(voice or ""),
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "turn_detection": {"type": "server_vad", "threshold": 0.5,
                                       "silence_duration_ms": 800},
                }}
                await ws.send_str(json.dumps(update, ensure_ascii=False))
                ok2, why2 = await _await_event(
                    ws, _SESSION_UPDATED,
                    min(SESSION_TIMEOUT_S, max(0.5, deadline - time.monotonic())))
                out["session_compat"] = bool(ok2)
                if not ok2:
                    out["reason"] = "session_%s" % (why2 or "failed")
                    return out
                out["detail"] = {"stages": ["handshake", "session_compat"],
                                 "audio": "not_tested"}
                return out
            finally:
                try:
                    await ws.close()
                except Exception:  # noqa: BLE001  (close best-effort)
                    pass
    except asyncio.TimeoutError:
        out["reason"] = "timeout" if out["network"] else "connect_timeout"
        return out
    except Exception as e:  # noqa: BLE001  (a probe must never raise into the API)
        out["reason"] = "exception:%s" % (type(e).__name__)
        return out
