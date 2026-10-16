"""Qwen Realtime (qwen3.8-omni-flash-realtime) WebSocket client.

The same code speaks to the local mock upstream and to the real service; only
the configuration (endpoint + Authorization header) differs, so switching from
mock to real is a pure env/secret change with no code change.
"""

import asyncio
import base64
import itertools
import json
import logging
import os
import random
import re
import time
from pathlib import Path

import aiohttp

from .counters import counters

log = logging.getLogger("rtl.qwen")

# Exact tutor instruction injected into the session.
TUTOR_INSTRUCTION = (
    "You are a patient English speaking practice partner. Use clear natural "
    "English. Keep replies short and conversational, usually 1-3 sentences. "
    "If the learner makes an important English mistake, briefly correct at "
    "most one mistake, then continue the conversation. Ask at most one simple "
    "follow-up question. If the learner speaks Chinese because they are stuck, "
    "help briefly and guide the conversation back to English."
)

MOCK_DEFAULT_WS_URL = "ws://127.0.0.1:9977"
REAL_HOST_TMPL = "{workspace}.{region}.maas.aliyuncs.com"
REAL_PATH = "/api-ws/v1/realtime"
DEFAULT_MODEL = "qwen3.8-omni-flash-realtime"
DEFAULT_VOICE = "Tina"
CANCEL_GRACE_S = 3.0
SESSION_CREATED_TIMEOUT = 5.0

# ---- upstream diagnostics (observability only; never logs secrets) ---------
#
# Narrowly authorized diagnostics for the unidentified-frame / premature-close
# failure class.  Every logged field is bounded, single-line and redacted
# BEFORE it reaches the log; the raw frame is never logged, and a field that
# cannot be safely redacted is omitted.

_DIAG_TEXT_MAX = 180
_DIAG_FIELD_MAX = 80
_DIAG_REASON_MAX = 120
_DIAG_KEYS_MAX = 12
_DIAG_KEY_LEN_MAX = 40

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _mask_bare_id(match):
    """Mask a bare alnum id shape only when it contains a digit.

    Callable replacement keeps the scan linear (no lookbehind backtracking) and
    leaves digit-free English words untouched.
    """
    try:
        return ("[id]" if any(ch.isdigit() for ch in match.group(0))
                else match.group(0))
    except Exception:  # noqa: BLE001
        return "[id]"


_REDACT_PATTERNS = (
    (re.compile(r"wss?://\S+", re.I), "[url]"),
    (re.compile(r"bearer\s+\S+", re.I), "bearer [redacted]"),
    # anchors are Unicode-aware lookbehinds, not \b: a credential directly
    # after a CJK/word character (no separator) must still be masked; the
    # sk- prefix is matched case-insensitively (SK-/Sk- variants included).
    (re.compile(r"(?<![A-Za-z0-9])[sS][kK]-[A-Za-z0-9._\-]{2,}"), "[key]"),
    (re.compile(r"[A-Za-z0-9_\-]{32,}"), "[token]"),
    (re.compile(r"[A-Za-z0-9+/]{24,}={0,2}"), "[token]"),
    (re.compile(r"[a-fA-F0-9]{32,}"), "[token]"),
    (re.compile(r"(?<![A-Za-z0-9])ws-[a-z0-9\-]{6,}", re.I), "[id]"),
    (re.compile(r"[A-Za-z0-9]{12,}"), _mask_bare_id),
)


def _diag_redact(text):
    """Mask credential-shaped substrings (exception-safe; shape-based.

    A redaction error yields ``[redaction-failed]``; pattern non-matches pass
    through by design — masking is best-effort on shapes, never a raw dump.
    """
    s = str(text)
    for pattern, repl in _REDACT_PATTERNS:
        try:
            s = pattern.sub(repl, s)
        except Exception:  # noqa: BLE001
            return "[redaction-failed]"
    return s


def _diag_text(value, limit=_DIAG_TEXT_MAX):
    """Bounded single-line redacted scalar; None when unsafe or absent."""
    try:
        if value is None or isinstance(value, (dict, list, tuple, set, bytes,
                                               bytearray)):
            return None
        s = value if isinstance(value, str) else str(value)
        if len(s) > 8000:
            s = s[:8000]
        s = _CONTROL_CHARS.sub(" ", s)
        s = _diag_redact(s)
        s = s.replace("\r", " ").replace("\n", " ")
        s = " ".join(s.split())
        if not s:
            return None
        if len(s) > limit:
            s = s[:limit] + "..."
        return s
    except Exception:  # noqa: BLE001
        return None


def _diag_token(value, limit=_DIAG_FIELD_MAX):
    """Bounded identifier-like field (error code / type / status)."""
    return _diag_text(value, limit=limit)


def _diag_error_fields(obj):
    """Safe (bounded, redacted) diagnostic fields from an upstream frame."""
    out = {"error_present": False, "error_type": None, "error_code": None,
           "status": None, "message": None}
    try:
        raw_err = obj.get("error")
        out["error_present"] = bool(raw_err)
        err = raw_err if isinstance(raw_err, dict) else {}
        out["error_type"] = _diag_token(err.get("type"))
        out["error_code"] = _diag_token(err.get("code") or obj.get("code"))
        out["status"] = _diag_token(err.get("status") or obj.get("status")
                                    or obj.get("status_code"))
        msg = err.get("message") or obj.get("message")
        if msg is None and isinstance(raw_err, str):
            msg = raw_err
        out["message"] = _diag_text(msg)
    except Exception:  # noqa: BLE001
        pass
    return out


def _diag_keys(obj):
    """Bounded, redacted list of top-level field names (never raises)."""
    try:
        keys = []
        for key in list(obj.keys())[:_DIAG_KEYS_MAX]:
            safe = _diag_text(key, limit=_DIAG_KEY_LEN_MAX)
            if safe:
                keys.append(safe)
        return keys
    except Exception:  # noqa: BLE001
        return []


def _diag_shape(obj, fields):
    """Coarse structural classification of an unidentified frame."""
    try:
        if not obj:
            return "empty"
        if fields.get("error_present"):
            return "error"
        return "other"
    except Exception:  # noqa: BLE001
        return "unknown"


def _read_secret_file(path):
    values = {}
    if not path:
        return values
    try:
        p = Path(path)
        if not p.is_file():
            return values
        for line in p.read_text("utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            values[key.strip()] = val.strip()
    except Exception as e:  # noqa: BLE001
        log.warning("qwen secret file read failed: %s", e)
    return values


class QwenConfig:
    def __init__(self, mode, ws_url, model, voice, api_key, workspace_id,
                 region, reconnect_max, reconnect_base_ms, stable_reset_s):
        self.mode = mode
        self.ws_url = ws_url
        self.model = model
        self.voice = voice
        self.api_key = api_key
        self.workspace_id = workspace_id
        self.region = region
        self.reconnect_max = max(1, int(reconnect_max))
        self.reconnect_base_ms = max(1, int(reconnect_base_ms))
        self.stable_reset_s = max(1, int(stable_reset_s))

    @property
    def is_real(self):
        return self.mode == "real"

    @property
    def ready(self):
        if not self.is_real:
            return True
        return (bool(self.api_key) and bool(self.workspace_id)
                and self.region == "cn-beijing")

    @property
    def not_ready_reason(self):
        if not self.is_real:
            return ""
        if not self.api_key:
            return "missing API key (QWEN_REALTIME_API_KEY)"
        if not self.workspace_id:
            return "missing workspace id (QWEN_REALTIME_WORKSPACE_ID)"
        if self.region != "cn-beijing":
            return "region must be cn-beijing (got %r)" % (self.region,)
        return ""

    @property
    def headers(self):
        if self.is_real and self.api_key:
            return {"Authorization": "Bearer " + self.api_key}
        return {}

    @property
    def host(self):
        """Host only (no path/query) — safe to log."""
        url = self.ws_url or ""
        if "//" in url:
            return url.split("//", 1)[1].split("/", 1)[0]
        return url

    @classmethod
    def from_values(cls, values):
        mode = str(values.get("QWEN_MODE") or "mock").strip().lower()
        model = str(values.get("QWEN_MODEL") or "").strip() or DEFAULT_MODEL
        voice = str(values.get("QWEN_VOICE") or "").strip() or DEFAULT_VOICE
        ws_url = str(values.get("QWEN_WS_URL") or "").strip()
        workspace = str(values.get("QWEN_WORKSPACE_ID") or "").strip()
        region = "cn-beijing"
        api_key = ""

        if mode == "real":
            secret = _read_secret_file(str(values.get("QWEN_SECRET_FILE") or ""))
            api_key = (os.environ.get("QWEN_REALTIME_API_KEY")
                       or secret.get("QWEN_REALTIME_API_KEY", "")).strip()
            workspace = (workspace
                         or secret.get("QWEN_REALTIME_WORKSPACE_ID", "")).strip()
            region = (secret.get("QWEN_REALTIME_REGION") or region).strip() or region
            model = (str(values.get("QWEN_MODEL") or "").strip()
                     or secret.get("QWEN_REALTIME_MODEL") or model)
            voice = (str(values.get("QWEN_VOICE") or "").strip()
                     or secret.get("QWEN_REALTIME_VOICE") or voice)
            if not ws_url:
                ws_url = "wss://%s%s?model=%s" % (
                    REAL_HOST_TMPL.format(workspace=workspace, region=region),
                    REAL_PATH, model)
        else:
            if not ws_url:
                ws_url = MOCK_DEFAULT_WS_URL

        return cls(
            mode=mode, ws_url=ws_url, model=model, voice=voice,
            api_key=api_key, workspace_id=workspace, region=region,
            reconnect_max=values.get("QWEN_RECONNECT_MAX", 5),
            reconnect_base_ms=values.get("QWEN_RECONNECT_BASE_MS", 500),
            stable_reset_s=values.get("QWEN_STABLE_RESET_S", 30),
        )


class QwenClient:
    """One Qwen realtime session per XiaoZhi client connection."""

    def __init__(self, cfg, on_event, on_close=None, instructions=None):
        self.cfg = cfg
        self.on_event = on_event
        self.on_close = on_close
        # BEHAVIOR-1: instructions are supplied by the routing link; the fixed
        # tutor instruction remains the fallback when no link is attached.
        self._instructions = instructions or TUTOR_INSTRUCTION
        self._session = None
        self._ws = None
        self._reader_task = None
        self._connect_task = None
        self._stable_task = None
        self._connected = False
        # VISION V0 (input_image_buffer.append): per-session vision state
        self._audio_seen = False          # official ordering: audio must precede the first image
        self._vision_last_ts = None       # monotonic ts of the last accepted image
        self._vision_window = []          # rolling 60s accept timestamps
        self._vision_rejected = 0         # local rejection counter (diagnostics)
        self._connecting = False
        self._closing = False
        self._closed = False
        self._exhausted = False
        self._budget = cfg.reconnect_max
        self._counted = False
        self._qwen_session_id = None
        self._cancel_grace_until = 0.0
        self._not_ready_last_log = 0.0
        # DIAG (observability only): per-connection correlation id + handshake
        # timeline.  Carries no credentials and no payload bytes.
        self._diag_seq = itertools.count(1)
        self._diag_id = None
        self._diag_t0 = None
        self._diag_created = False
        self._diag_created_t = None
        self._diag_update_sent = False
        self._diag_updated = False
        self._diag_updated_t = None
        self._diag_close_code = None
        self._diag_close_reason = None
        self._diag_close_logged = False

    @property
    def connected(self):
        return self._connected

    # ---- diagnostic helpers (observability only) ---------------------------

    def _diag_begin(self):
        """Start a new per-connection diagnostic correlation (id + timeline)."""
        try:
            self._diag_id = "qc%d" % next(self._diag_seq)
            self._diag_t0 = time.monotonic()
            self._diag_created = False
            self._diag_created_t = None
            self._diag_update_sent = False
            self._diag_updated = False
            self._diag_updated_t = None
            self._diag_close_code = None
            self._diag_close_reason = None
            self._diag_close_logged = False
        except Exception:  # noqa: BLE001
            pass

    def _diag_ms_since(self, t0):
        """Milliseconds since a monotonic timestamp (None when absent)."""
        try:
            if t0 is None:
                return None
            return int(round((time.monotonic() - t0) * 1000.0))
        except Exception:  # noqa: BLE001
            return None

    def _diag_note_close(self, code, reason, via="close"):
        """Capture and log ONE websocket close (code + redacted bounded reason).

        Observability only: idempotent, never raises, never blocks.  The first
        close of a connection is logged; later captures only fill gaps.
        """
        try:
            if isinstance(code, int) and self._diag_close_code is None:
                self._diag_close_code = code
            reason_safe = _diag_text(reason, limit=_DIAG_REASON_MAX)
            if reason_safe and self._diag_close_reason is None:
                self._diag_close_reason = reason_safe
            if self._diag_close_logged:
                return
            self._diag_close_logged = True
            created_ms = (self._diag_ms_since(self._diag_created_t)
                          if self._diag_created else None)
            updated_ms = (self._diag_ms_since(self._diag_updated_t)
                          if self._diag_updated else None)
            log.info(
                "qwen ws close conn=%s via=%s close_code=%r close_reason=%r "
                "lifetime_ms=%s created=%s updated=%s update_sent=%s "
                "created_ms=%s updated_ms=%s",
                self._diag_id, via, self._diag_close_code,
                self._diag_close_reason, self._diag_ms_since(self._diag_t0),
                self._diag_created, self._diag_updated, self._diag_update_sent,
                created_ms, updated_ms)
        except Exception:  # noqa: BLE001
            pass

    # ---- lifecycle --------------------------------------------------------

    def request_connect(self):
        """Synchronous, idempotent, budget-aware connect trigger (no task churn)."""
        if self._connected or self._connecting or self._closing or self._exhausted:
            return
        if not self.cfg.ready:
            counters.qwen_connected = 0
            now = time.monotonic()
            if now - self._not_ready_last_log >= 10.0:
                self._not_ready_last_log = now
                log.error("qwen not ready (%s); staying disconnected",
                          self.cfg.not_ready_reason)
            return
        if self._budget <= 0:
            self._exhaust()
            return
        self._connecting = True
        self._connect_task = asyncio.create_task(self._connect_loop())

    async def ensure_connected(self):
        self.request_connect()

    def _exhaust(self):
        if not self._exhausted:
            self._exhausted = True
            log.error("qwen reconnect budget exhausted for this client session")

    async def _connect_loop(self):
        attempt = 0
        try:
            while not self._closing and not self._exhausted:
                if self._budget <= 0:
                    self._exhaust()
                    return
                attempt += 1
                self._budget -= 1
                if await self._attempt_connect():
                    self._schedule_stable_reset()
                    return
                counters.qwen_connect_errors += 1
                if self._budget <= 0:
                    self._exhaust()
                    return
                delay = min(self.cfg.reconnect_base_ms * (2 ** (attempt - 1)), 8000)
                delay *= random.uniform(0.8, 1.2)
                log.warning("qwen reconnect attempt %d failed; retry in %.0f ms "
                            "(budget left %d)", attempt, delay, self._budget)
                await asyncio.sleep(delay / 1000.0)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("qwen connect loop error: %s", e)
        finally:
            self._connecting = False

    async def _attempt_connect(self):
        ws = None
        self._diag_begin()
        try:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession()
            ws = await self._session.ws_connect(
                self.cfg.ws_url, headers=self.cfg.headers,
                heartbeat=20, max_msg_size=0)
            created = await asyncio.wait_for(
                self._recv_until_session_created(ws), SESSION_CREATED_TIMEOUT)
            if not created:
                log.warning("qwen handshake incomplete conn=%s elapsed_ms=%s "
                            "(session.created not received)",
                            self._diag_id, self._diag_ms_since(self._diag_t0))
                await self._safe_close_ws(ws)
                return False
            self._ws = ws
            self._connected = True
            self._audio_seen = False      # VISION V0: new session, fresh buffers
            self._vision_last_ts = None
            self._vision_window = []
            _ACTIVE_INSTANCES.add(self)   # VISION V0.5: 注册活跃实例
            counters.qwen_sessions += 1
            counters.qwen_connected += 1
            self._counted = True
            self._reader_task = asyncio.create_task(self._reader())
            await self._send_json(self._session_update_msg())
            self._diag_update_sent = True
            log.info("qwen connected mode=%s host=%s model=%s session=%s conn=%s",
                     self.cfg.mode, self.cfg.host, self.cfg.model,
                     self._qwen_session_id, self._diag_id)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("qwen connect attempt failed: %s", e)
            if ws is not None:
                await self._safe_close_ws(ws)
            self._ws = None
            return False

    async def _recv_until_session_created(self, ws):
        while True:
            msg = await ws.receive()
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    obj = json.loads(msg.data)
                except Exception:  # noqa: BLE001
                    continue
                if isinstance(obj, dict) and obj.get("type") == "session.created":
                    self._qwen_session_id = (obj.get("session") or {}).get("id")
                    self._diag_created = True
                    self._diag_created_t = time.monotonic()
                    return True
            elif msg.type in (aiohttp.WSMsgType.CLOSED,
                              aiohttp.WSMsgType.CLOSING,
                              aiohttp.WSMsgType.CLOSE,
                              aiohttp.WSMsgType.ERROR):
                return False

    async def _reader(self):
        ws = self._ws
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_text(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    log.warning("qwen ws error: %s", ws.exception())
                    self._diag_note_close(None, None, via="error")
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSE:
                    self._diag_note_close(
                        msg.data if isinstance(msg.data, int) else None,
                        msg.extra, via="close")
                    break
                elif msg.type in (aiohttp.WSMsgType.CLOSED,
                                  aiohttp.WSMsgType.CLOSING):
                    self._diag_note_close(
                        msg.data if isinstance(msg.data, int) else None,
                        msg.extra, via="closed")
                    break
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("qwen reader error: %s", e)
        finally:
            if not self._closing:
                self._handle_unexpected_close()

    def _handle_unexpected_close(self):
        self._connected = False
        self._ws = None
        self._reader_task = None
        self._cancel_stable()
        if self._counted:
            counters.qwen_connected = max(0, counters.qwen_connected - 1)
            self._counted = False
        if self._closing:
            return
        # an accepted-then-dropped connection counts as a failed attempt
        counters.qwen_connect_errors += 1
        log.warning("qwen connection closed unexpectedly; scheduling reconnect "
                    "(budget left %d, conn=%s close_code=%r)",
                    max(0, self._budget), self._diag_id,
                    self._diag_close_code)
        if self.on_close is not None:
            asyncio.create_task(self._safe_cb(self.on_close))
        if self._exhausted:
            return
        if not self._connecting:
            self.request_connect()

    async def _safe_cb(self, cb):
        try:
            await cb()
        except Exception as e:  # noqa: BLE001
            log.warning("qwen callback error: %s", e)

    # ---- stable-reset timer ----------------------------------------------

    def _schedule_stable_reset(self):
        self._cancel_stable()
        self._stable_task = asyncio.create_task(self._stable_watch())

    def _cancel_stable(self):
        task = self._stable_task
        self._stable_task = None
        if task is not None and not task.done():
            task.cancel()

    async def _stable_watch(self):
        try:
            await asyncio.sleep(self.cfg.stable_reset_s)
        except asyncio.CancelledError:
            return
        if self._connected and not self._closing:
            self._budget = self.cfg.reconnect_max
            log.info("qwen reconnect budget replenished after %ds stable",
                     self.cfg.stable_reset_s)

    # ---- inbound ----------------------------------------------------------

    async def _handle_text(self, raw):
        try:
            obj = json.loads(raw)
        except Exception:  # noqa: BLE001
            counters.upstream_errors += 1
            log.warning("qwen non-JSON upstream message ignored (%d bytes)", len(raw))
            return
        if not isinstance(obj, dict):
            counters.upstream_errors += 1
            log.warning("qwen non-object upstream message ignored")
            return
        etype = obj.get("type")
        if etype == "session.updated":
            self._diag_updated = True
            self._diag_updated_t = time.monotonic()
        if etype == "error":
            fields = _diag_error_fields(obj)
            if time.monotonic() <= self._cancel_grace_until:
                log.info("qwen benign cancel error ignored: %s conn=%s",
                         fields["error_code"] or "unknown", self._diag_id)
            else:
                counters.upstream_errors += 1
                log.warning("qwen upstream error event conn=%s error_code=%r "
                            "error_type=%r status=%r message=%r",
                            self._diag_id, fields["error_code"],
                            fields["error_type"], fields["status"],
                            fields["message"])
            return
        if etype is None:
            # Unidentified upstream frame (observability only — the frame is
            # still forwarded to the dispatcher unchanged below).  Observed in
            # the ~2 s premature-close failure class; log approved non-sensitive
            # fields only (bounded + redacted; raw frame never logged).
            try:
                fields = _diag_error_fields(obj)
                log.warning(
                    "qwen unidentified upstream event conn=%s top_keys=%r "
                    "shape=%s error_present=%s error_type=%r error_code=%r "
                    "status=%r message=%r",
                    self._diag_id, _diag_keys(obj),
                    _diag_shape(obj, fields), fields["error_present"],
                    fields["error_type"], fields["error_code"],
                    fields["status"], fields["message"])
            except Exception:  # noqa: BLE001  (diagnostics never disturb dispatch)
                pass
        try:
            await self.on_event(obj)
        except Exception as e:  # noqa: BLE001
            log.warning("qwen event handler error (%s): %s", etype, e)

    # ---- outbound ---------------------------------------------------------

    async def _send_json(self, obj):
        ws = self._ws
        if ws is None or ws.closed:
            raise ConnectionError("qwen websocket not connected")
        await ws.send_str(json.dumps(obj))

    # ---- BEHAVIOR-1 instruction surface (text plane only) ------------------

    @property
    def instructions(self):
        return self._instructions

    def set_instructions(self, text):
        """Set the instructions used by the next (re)connect's session.update."""
        self._instructions = str(text or "") or TUTOR_INSTRUCTION

    async def send_instructions_update(self, text):
        """Hot-apply `instructions` mid-session (BEHAVIOR-1).

        Instructions-only update — never touches model/voice/formats/VAD.
        The caller (BehaviorLink) is responsible for the SAFE-BOUNDARY guard;
        this method only writes the message.  Returns True when written.
        """
        if not self._connected or self._ws is None:
            return False
        self._instructions = str(text or "") or TUTOR_INSTRUCTION
        await self._send_json({"type": "session.update",
                               "session": {"instructions": self._instructions}})
        return True

    def _session_update_msg(self):
        return {
            "type": "session.update",
            "session": {
                "model": self.cfg.model,
                "voice": self.cfg.voice,
                "instructions": self._instructions,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "silence_duration_ms": 800,
                },
            },
        }

    async def send_append(self, pcm_bytes):
        if not self._connected or self._ws is None:
            return
        b64 = base64.b64encode(pcm_bytes).decode("ascii")
        self._audio_seen = True   # VISION V0: official ordering prerequisite
        await self._send_json({"type": "input_audio_buffer.append", "audio": b64})

    # ---- VISION V0: single-image input (official protocol, doc-verified) ----
    # Event: {"type":"input_image_buffer.append","image":"<base64 JPEG>"}
    # Semantics: the image buffer commits together with input_audio_buffer.commit;
    # at least one input_audio_buffer.append must precede the first image.
    # Guards (VISION_SECURITY_REVIEW R2/R4): JPEG magic, raw ≤190KB, base64
    # ≤256KB, ≥5s interval, ≤6/min, ordering.  Rejections NEVER touch the
    # audio path.
    _VISION_MIN_INTERVAL_S = 5.0
    _VISION_MAX_PER_MIN = 6
    _VISION_RAW_MAX_BYTES = 190 * 1024
    _VISION_B64_MAX_BYTES = 256 * 1024

    # ---- VISION V0.5: 模块级活跃实例注册表（HTTP 提交入口用） ----
    # 单会话 sidecar 架构：通常至多一个连接实例；submit_vision_image 寻找
    # 当前已连接实例并转发，turns.py 零改动。
    async def _register_active(self):
        _ACTIVE_INSTANCES.add(self)

    def _unregister_active(self):
        _ACTIVE_INSTANCES.discard(self)

    async def send_image(self, jpeg_bytes):
        """Submit ONE user-initiated JPEG frame.  Returns (True, "") on submit,
        (False, reason) on guard rejection.  Audio path untouched on rejection."""
        if not self._connected or self._ws is None:
            return False, "not_connected"
        if not isinstance(jpeg_bytes, (bytes, bytearray)) or len(jpeg_bytes) < 3 \
                or bytes(jpeg_bytes[:3]) != b"\xff\xd8\xff":
            self._vision_rejected += 1
            return False, "not_jpeg"
        if len(jpeg_bytes) > self._VISION_RAW_MAX_BYTES:
            self._vision_rejected += 1
            return False, "too_large_raw"
        now = time.monotonic()
        if not self._audio_seen:
            self._vision_rejected += 1
            return False, "ordering_audio_first"
        if self._vision_last_ts is not None \
                and now - self._vision_last_ts < self._VISION_MIN_INTERVAL_S:
            self._vision_rejected += 1
            return False, "rate_interval"
        self._vision_window = [t for t in self._vision_window if now - t < 60.0]
        if len(self._vision_window) >= self._VISION_MAX_PER_MIN:
            self._vision_rejected += 1
            return False, "rate_per_minute"
        b64 = base64.b64encode(bytes(jpeg_bytes)).decode("ascii")
        if len(b64) > self._VISION_B64_MAX_BYTES:
            self._vision_rejected += 1
            return False, "too_large_b64"
        await self._send_json({"type": "input_image_buffer.append", "image": b64})
        self._vision_window.append(now)
        self._vision_last_ts = now
        return True, ""

    async def send_cancel(self):
        if not self._connected or self._ws is None:
            return
        self._cancel_grace_until = time.monotonic() + CANCEL_GRACE_S
        await self._send_json({"type": "response.cancel"})

    async def send_finish(self):
        if self._ws is not None and not self._ws.closed:
            await self._send_json({"type": "session.finish"})

    async def _cancel_and_wait(self, task):
        """Cancel an internal task and never let its CancelledError escape."""
        if task is None or task.done() or task is asyncio.current_task():
            return
        task.cancel()
        try:
            await asyncio.gather(task, return_exceptions=True)
        except BaseException:  # noqa: BLE001  (also our own cancellation)
            pass

    async def close(self):
        """Idempotent, exception-free teardown. No step is skippable."""
        if self._closed:
            return
        self._closing = True
        try:
            try:
                await asyncio.wait_for(self.send_finish(), 1.0)
            except BaseException:  # noqa: BLE001
                pass
            await self._cancel_and_wait(self._stable_task)
            self._stable_task = None
            await self._cancel_and_wait(self._connect_task)
            self._connect_task = None
            await self._teardown()
        except BaseException as e:  # noqa: BLE001
            log.warning("qwen close step error: %r", e)
        finally:
            self._closed = True
            session = self._session
            self._session = None
            if session is not None and not session.closed:
                try:
                    await asyncio.gather(session.close(), return_exceptions=True)
                except BaseException:  # noqa: BLE001
                    pass

    async def _teardown(self):
        ws = self._ws
        self._ws = None
        self._connected = False
        _ACTIVE_INSTANCES.discard(self)   # V06-F1: 关闭即注销，杜绝引用泄漏
        if self._counted:
            counters.qwen_connected = max(0, counters.qwen_connected - 1)
            self._counted = False
        try:
            if ws is not None:
                await self._safe_close_ws(ws)
        finally:
            reader = self._reader_task
            self._reader_task = None
            await self._cancel_and_wait(reader)

    async def _safe_close_ws(self, ws):
        try:
            await asyncio.gather(ws.close(), return_exceptions=True)
        except BaseException:  # noqa: BLE001
            pass

# ---- VISION V0.5: 活跃 QwenClient 注册表（模块级，纯增量） ----
_ACTIVE_INSTANCES = set()


def submit_vision_image(jpeg_bytes):
    """HTTP 提交入口：寻找当前已连接的 QwenClient 并转发图像。

    返回 (True, "") 或 (False, reason)。无可连接实例 → not_connected。
    该函数不触碰 turns/audio/VAD（turns.py 零改动设计）。
    """
    connected = [i for i in list(_ACTIVE_INSTANCES)
                 if getattr(i, "_connected", False) and i._ws is not None]
    if not connected:
        return False, "not_connected"
    if len(connected) > 1:
        # V06-R5: 多活跃会话歧义必须显式拒绝——图片绝不错误进入他人会话
        return False, "ambiguous_session"
    return connected[0].send_image(jpeg_bytes)
