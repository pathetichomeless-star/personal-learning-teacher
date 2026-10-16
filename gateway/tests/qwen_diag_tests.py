"""QWEN_DIAG_TESTS — synthetic fixtures for the qwen.py upstream diagnostics.

Observability-only suite: drives a real `app.qwen.QwenClient` with scripted
frames through a stub websocket (NO network, NO real upstream, NO Qwen
session).  Verifies:

  * the authorized diagnostic fields are visible (unidentified frames,
    structured error codes, ws close codes, handshake timeline);
  * secrets never reach the log records (fake key / workspace / bearer /
    token / payload fixtures must not appear in any record);
  * dispatch + accounting behaviour is unchanged (forwarding map, counters,
    `session.update` payload, frozen constants).

17 numbered cases (C01..C17, incl. CJK-adjacency / mixed-case / control-char
adversarial cases from the independent review) + guard checks (G*).

Run:
    cd <project-root>/gateway
    DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python tests/qwen_diag_tests.py
"""

import asyncio
import base64
import json
import logging
import re
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import aiohttp                                                # noqa: E402
import app.qwen as qwen                                        # noqa: E402
from app.counters import counters                              # noqa: E402

RESULTS = []
LOG_RECORDS = []

# ---- fake credential-shaped fixtures (must NEVER appear in any log) --------
FAKE_KEY = "sk-FAKE1234567890abcdefFAKE"
FAKE_WORKSPACE = "ws-fake1234wsfake5678"
FAKE_BARE_ID = "abcd9efgh8ijkl7"
FAKE_BEARER = "Bearer eyJhbGciOiFAKE.eyJzdWIiOiJmYWtlIn0.FAKESIG"
FAKE_TOKEN = "FAKE-TOKEN-A1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6"
FAKE_B64 = base64.b64encode(b"\x00" * 400).decode("ascii")
# adversarial-review fixtures (I1/I2): NO separator after a CJK char, short
# values, mixed-case bare id
FAKE_CJK_KEY = "sk-abc123def"
FAKE_CJK_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.sig"
FAKE_CJK_HEX = "0123456789abcdef"
FAKE_CJK_WS = "ws-abc12345"
FAKE_MIXED_ID = "AbCd9EfGh8IjKl7M"
FAKE_SK_UPPER = "SK-abc123def"
FAKE_SK_TITLE = "Sk-abc123def"
FORBIDDEN_SUBSTRINGS = (
    FAKE_KEY, "FAKE1234567890abcdefFAKE", FAKE_WORKSPACE,
    "fake1234wsfake5678", FAKE_BARE_ID, "eyJhbGciOiFAKE", FAKE_TOKEN,
    FAKE_B64[:60], FAKE_CJK_KEY, FAKE_CJK_JWT[:40], FAKE_CJK_HEX,
    FAKE_CJK_WS, FAKE_MIXED_ID, FAKE_SK_UPPER, FAKE_SK_TITLE,
)


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        (" - " + str(detail)) if (detail and not cond) else ""))
    return bool(cond)


class _Capture(logging.Handler):
    def emit(self, record):
        try:
            LOG_RECORDS.append(record.getMessage())
        except Exception:  # noqa: BLE001
            pass


class StubWS:
    """Scripted websocket double: (delay_s, WSMessage | callable) items."""

    def __init__(self, script):
        self._script = list(script)
        self.sent = []
        self.closed = False

    async def _next(self):
        if not self._script:
            return None
        delay, msg = self._script.pop(0)
        if delay:
            await asyncio.sleep(delay)
        if callable(msg):
            msg = msg()
        return msg

    async def receive(self):
        msg = await self._next()
        if msg is None:
            return aiohttp.WSMessage(aiohttp.WSMsgType.CLOSED, None, None)
        return msg

    def __aiter__(self):
        return self

    async def __anext__(self):
        msg = await self._next()
        if msg is None:
            raise StopAsyncIteration
        return msg

    async def send_str(self, data):
        self.sent.append(data)

    async def close(self):
        self.closed = True

    def exception(self):
        return None


class StubSession:
    def __init__(self, ws):
        self._ws = ws
        self.closed = False

    async def ws_connect(self, *a, **k):
        return self._ws

    async def close(self):
        self.closed = True


def text_msg(kind, payload, extra=""):
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return aiohttp.WSMessage(kind, data, extra)


def created_msg():
    return text_msg(aiohttp.WSMsgType.TEXT,
                    {"type": "session.created",
                     "session": {"id": "sess_SYNTH_1"}})


def make_client():
    cfg = qwen.QwenConfig(mode="mock", ws_url="ws://127.0.0.1:9/xiaozhi",
                          model="m-synth", voice="v-synth", api_key="",
                          workspace_id="", region="cn-beijing",
                          reconnect_max=2, reconnect_base_ms=1,
                          stable_reset_s=30)
    forwarded = []

    async def _on_event(obj):
        forwarded.append(obj)

    client = qwen.QwenClient(cfg, _on_event)
    client._diag_begin()
    return client, forwarded


def log_text():
    return "\n".join(LOG_RECORDS)


def has(pattern):
    return re.search(pattern, log_text()) is not None


# ===========================================================================
# Frame-level cases (C01..C07, C12..C14) — direct `_handle_text`
# ===========================================================================

async def frame_cases():
    print("\n==== frame-level cases ====")

    # C01/C02 — normal session.created / session.updated handshake path
    client, _ = make_client()
    stub = StubWS([(0, created_msg())])
    ok = await client._recv_until_session_created(stub)
    check("C01 session.created consumed + timeline flagged",
          ok is True and client._diag_created is True
          and client._diag_created_t is not None
          and client._qwen_session_id == "sess_SYNTH_1",
          (ok, client._diag_created))
    client2, fwd2 = make_client()
    await client2._handle_text(json.dumps(
        {"type": "session.updated", "session": {"id": "sess_SYNTH_1"}}))
    check("C02 session.updated flagged + forwarded unchanged",
          client2._diag_updated is True and client2._diag_updated_t is not None
          and len(fwd2) == 1 and fwd2[0].get("type") == "session.updated",
          fwd2)

    # C03 — standard type=error event
    client, fwd = make_client()
    before = counters.snapshot()
    n_before = len(LOG_RECORDS)
    await client._handle_text(json.dumps(
        {"type": "error",
         "error": {"code": "rate_limit_exceeded", "type": "Throttling",
                   "status": 429, "message": "too many requests"}}))
    after = counters.snapshot()
    new = "\n".join(LOG_RECORDS[n_before:])
    check("C03 structured error code + type + status + message visible",
          "qwen upstream error event" in new
          and "error_code='rate_limit_exceeded'" in new
          and "error_type='Throttling'" in new and "status='429'" in new
          and "message='too many requests'" in new, new)
    check("C03b error counter behaviour unchanged (+1)",
          after["upstream_errors"] - before["upstream_errors"] == 1,
          (before["upstream_errors"], after["upstream_errors"]))
    check("C03c error frame not forwarded (existing behaviour)",
          len(fwd) == 0, fwd)

    # C04 — error frame with MISSING type (the production signature)
    client, fwd = make_client()
    n_before = len(LOG_RECORDS)
    await client._handle_text(json.dumps(
        {"error": {"code": "response_idle_timeout",
                   "message": "no response activity"}}))
    new = "\n".join(LOG_RECORDS[n_before:])
    check("C04 unidentified frame is NOT silently invisible",
          "qwen unidentified upstream event" in new, new)
    check("C04b safe error code visible from typeless frame",
          "error_code='response_idle_timeout'" in new
          and "shape=error" in new, new)
    check("C04c typeless frame still forwarded unchanged",
          len(fwd) == 1 and fwd[0].get("error", {}).get("code")
          == "response_idle_timeout", fwd)

    # C05 — nested error object
    client, fwd = make_client()
    n_before = len(LOG_RECORDS)
    await client._handle_text(json.dumps(
        {"error": {"code": "x_nested", "message": "outer",
                   "inner": {"secret_ish": "deep", "a": [1, 2]}}}))
    new = "\n".join(LOG_RECORDS[n_before:])
    check("C05 nested error object handled without crash; inner omitted",
          "qwen unidentified upstream event" in new
          and "error_code='x_nested'" in new and "secret_ish" not in new
          and "deep" not in new, new)

    # C06 — unexpected JSON fields
    client, fwd = make_client()
    payload = {"type": "session.updated", "session": {"id": "s"},
               "weird": [1, 2], "blob": {"x": 1}}
    await client._handle_text(json.dumps(payload))
    check("C06 unexpected fields: forwarded verbatim + still flagged",
          len(fwd) == 1 and fwd[0] == payload
          and client._diag_updated is True, fwd)
    client, fwd = make_client()
    n_before = len(LOG_RECORDS)
    await client._handle_text(json.dumps({"foo": {"bar": 1}, "n": 12345}))
    new = "\n".join(LOG_RECORDS[n_before:])
    check("C06b typeless + unexpected keys: keys visible, frame forwarded",
          "top_keys=['foo', 'n']" in new and len(fwd) == 1, new)

    # C07 — malformed frame (existing behaviour preserved)
    client, fwd = make_client()
    before = counters.snapshot()
    n_before = len(LOG_RECORDS)
    await client._handle_text('{"type": "response.')
    after = counters.snapshot()
    new = "\n".join(LOG_RECORDS[n_before:])
    check("C07 malformed frame: handled, counted, not forwarded",
          after["upstream_errors"] - before["upstream_errors"] == 1
          and len(fwd) == 0, fwd)
    check("C07b malformed frame log carries size only",
          "non-JSON upstream message ignored" in new, new)

    # C12 — fake API key + bearer in an error message
    client, fwd = make_client()
    n_before = len(LOG_RECORDS)
    await client._handle_text(json.dumps(
        {"error": {"code": "auth_check",
                   "message": "key %s rejected; header %s"
                              % (FAKE_KEY, FAKE_BEARER)}}))
    new = "\n".join(LOG_RECORDS[n_before:])
    check("C12 fake API key masked in logs",
          FAKE_KEY not in new and "FAKE1234567890abcdefFAKE" not in new
          and "[key]" in new, new)
    check("C12b bearer token masked in logs",
          "eyJhbGciOiFAKE" not in new and "bearer [redacted]" in new.lower(),
          new)

    # C13 — workspace id shapes in an error message
    client, fwd = make_client()
    n_before = len(LOG_RECORDS)
    await client._handle_text(json.dumps(
        {"error": {"code": "route_check",
                   "message": "workspace %s unknown (bare %s)"
                              % (FAKE_WORKSPACE, FAKE_BARE_ID)}}))
    new = "\n".join(LOG_RECORDS[n_before:])
    check("C13 workspace-shaped + bare id masked",
          "fake1234wsfake5678" not in new and FAKE_BARE_ID not in new
          and "[id]" in new, new)

    # C14 — sensitive payload (base64 blob, long token, ws url)
    client, fwd = make_client()
    n_before = len(LOG_RECORDS)
    await client._handle_text(json.dumps(
        {"error": {"code": "payload_check",
                   "message": "blob=%s token=%s url=wss://%s/api-ws"
                              % (FAKE_B64, FAKE_TOKEN, FAKE_WORKSPACE)}}))
    new = "\n".join(LOG_RECORDS[n_before:])
    check("C14 base64/go token/url masked; no raw payload",
          FAKE_B64[:60] not in new and FAKE_TOKEN not in new
          and "wss://" not in new and "[token]" in new and "[url]" in new,
          new)
    check("C14b logged message field bounded",
          max((len(line) for line in new.splitlines()), default=0) < 700,
          max((len(line) for line in new.splitlines()), default=0))

    # C15 — credentials directly after CJK text with NO separator (review I1)
    client, fwd = make_client()
    n_before = len(LOG_RECORDS)
    for i, value in enumerate((FAKE_CJK_KEY, FAKE_CJK_JWT, FAKE_CJK_HEX,
                               FAKE_CJK_WS), start=1):
        await client._handle_text(json.dumps(
            {"type": "error",
             "error": {"code": "e%d" % i, "message": "密钥%s 无效" % value}}))
    new = "\n".join(LOG_RECORDS[n_before:])
    check("C15 CJK-adjacent short credentials masked (no separator)",
          FAKE_CJK_KEY not in new and FAKE_CJK_JWT not in new
          and FAKE_CJK_HEX not in new and FAKE_CJK_WS not in new
          and "[key]" in new and "[id]" in new, new)
    check("C15b direct redaction of CJK-adjacent values",
          "[key]" in (qwen._diag_text("密钥" + FAKE_CJK_KEY) or "")
          and FAKE_CJK_HEX not in (qwen._diag_text("密钥" + FAKE_CJK_HEX) or "")
          and "[id]" in (qwen._diag_text("密钥" + FAKE_CJK_WS) or ""),
          qwen._diag_text("密钥" + FAKE_CJK_KEY))

    # C15c — case-variant SK-/Sk- prefixes (re-verify nit)
    client, fwd = make_client()
    n_before = len(LOG_RECORDS)
    for value in (FAKE_SK_UPPER, FAKE_SK_TITLE):
        await client._handle_text(json.dumps(
            {"type": "error",
             "error": {"code": "e9", "message": "key %s invalid" % value}}))
    new = "\n".join(LOG_RECORDS[n_before:])
    check("C15c case-variant sk- prefixes masked",
          FAKE_SK_UPPER not in new and FAKE_SK_TITLE not in new
          and "[key]" in new, new)

    # C16 — mixed-case bare id (review I2)
    client, fwd = make_client()
    n_before = len(LOG_RECORDS)
    await client._handle_text(json.dumps(
        {"type": "error",
         "error": {"code": "e5", "message": "id=%s" % FAKE_MIXED_ID}}))
    new = "\n".join(LOG_RECORDS[n_before:])
    check("C16 mixed-case bare id masked; digit-free words untouched",
          FAKE_MIXED_ID not in new and "[id]" in new
          and (qwen._diag_text("conversation") == "conversation"), new)

    # C17 — control characters stripped (review I3)
    client, fwd = make_client()
    n_before = len(LOG_RECORDS)
    await client._handle_text(json.dumps(
        {"type": "error",
         "error": {"code": "e6", "message": "a\u0000b\u001bc\u0007d"}}))
    new = "\n".join(LOG_RECORDS[n_before:])
    check("C17 control characters stripped from log records",
          "\x00" not in new and "\x1b" not in new and "\x07" not in new)


# ===========================================================================
# WS-level cases (C08..C11) — reader / handshake with stub ws
# ===========================================================================

async def ws_cases():
    print("\n==== websocket-level cases ====")

    # C08 — normal closure (client-initiated; code + reason visible)
    client, _ = make_client()
    client._ws = StubWS([(0, created_msg()),
                         (0, aiohttp.WSMessage(aiohttp.WSMsgType.CLOSE,
                                               1000, "normal"))])
    client._diag_created = True
    client._diag_created_t = time.monotonic()
    client._diag_update_sent = True
    client._closing = True
    await client._reader()
    txt = log_text()
    check("C08 normal closure: close code + reason visible",
          "qwen ws close" in txt and "close_code=1000" in txt
          and "close_reason='normal'" in txt, txt[-400:])
    check("C08b normal closure does not log 'closed unexpectedly'",
          "closed unexpectedly" not in txt, txt[-200:])

    # C09 — abnormal closure (server-side; reconnect accounting preserved)
    client, _ = make_client()
    client._ws = StubWS([(0, created_msg()),
                         (0, aiohttp.WSMessage(aiohttp.WSMsgType.CLOSE,
                                               1001, "going away"))])
    client._exhausted = True          # no reconnect task in tests
    client._diag_created = True
    before = counters.snapshot()
    await client._reader()
    after = counters.snapshot()
    txt = log_text()
    check("C09 abnormal closure: code visible + unexpected-close logged",
          "close_code=1001" in txt and "closed unexpectedly" in txt, txt[-400:])
    check("C09b abnormal closure counter behaviour unchanged",
          after["qwen_connect_errors"] - before["qwen_connect_errors"] == 1,
          (before["qwen_connect_errors"], after["qwen_connect_errors"]))

    # C10 — two-second premature closure (production signature)
    client, _ = make_client()
    client._ws = StubWS([(0, created_msg()),
                         (2.0, aiohttp.WSMessage(aiohttp.WSMsgType.CLOSE,
                                                 1005, ""))])
    client._exhausted = True
    client._diag_created = True
    client._diag_created_t = time.monotonic()
    client._diag_update_sent = True
    n_before = len(LOG_RECORDS)
    await client._reader()
    new = "\n".join(LOG_RECORDS[n_before:])
    m = re.search(r"lifetime_ms=(\d+)", new)
    life = int(m.group(1)) if m else -1
    check("C10 2 s premature closure: close_code=1005 + lifetime ~2000 ms",
          "close_code=1005" in new and 1900 <= life <= 2600, (life, new))
    check("C10b handshake timeline fields present on the close line",
          "created=True" in new and "updated=False" in new
          and "update_sent=True" in new and "created_ms=" in new
          and "updated_ms=None" in new, new)

    # C11 — empty close reason + code-less CLOSED frame
    client, _ = make_client()
    client._ws = StubWS([(0, created_msg()),
                         (0, aiohttp.WSMessage(aiohttp.WSMsgType.CLOSE,
                                               1000, ""))])
    client._exhausted = True
    client._diag_created = True
    n_before = len(LOG_RECORDS)
    await client._reader()
    new = "\n".join(LOG_RECORDS[n_before:])
    check("C11 empty close reason renders close_reason=None",
          "close_reason=None" in new and "close_code=1000" in new, new)
    client, _ = make_client()
    client._ws = StubWS([(0, created_msg()),
                         (0, aiohttp.WSMessage(aiohttp.WSMsgType.CLOSED,
                                               None, None))])
    client._exhausted = True
    client._diag_created = True
    n_before = len(LOG_RECORDS)
    await client._reader()
    new = "\n".join(LOG_RECORDS[n_before:])
    check("C11b code-less CLOSED frame handled (close_code=None, via=closed)",
          "via=closed" in new and "close_code=None" in new, new)


# ===========================================================================
# Guard checks (G*) — handshake path, behaviour freeze, global secret scan
# ===========================================================================

async def guard_cases():
    print("\n==== guard checks ====")

    # G1 — handshake incomplete path (stub session; no network)
    client, _ = make_client()
    stub_ws = StubWS([(0, aiohttp.WSMessage(aiohttp.WSMsgType.CLOSE,
                                            1001, "bye"))])
    client._session = StubSession(stub_ws)
    n_before = len(LOG_RECORDS)
    ok = await client._attempt_connect()
    new = "\n".join(LOG_RECORDS[n_before:])
    check("G1 handshake incomplete: not connected + diagnostic logged",
          ok is False and "qwen handshake incomplete" in new
          and "conn=qc" in new, new)

    # G2 — full connect path (stub session) keeps the connected log + conn id
    client, _ = make_client()
    stub_ws2 = StubWS([(0, created_msg())])
    client._session = StubSession(stub_ws2)
    n_before = len(LOG_RECORDS)
    ok = await client._attempt_connect()
    client._closing = True
    client._exhausted = True
    for _ in range(5):
        await asyncio.sleep(0)
    new = "\n".join(LOG_RECORDS[n_before:])
    sent_types = [json.loads(s).get("type") for s in stub_ws2.sent]
    check("G2 connect path: connected log + session.update sent unchanged",
          ok is True and "qwen connected" in new and "conn=qc" in new
          and sent_types == ["session.update"], (new, sent_types))

    # G3 — benign cancel-grace error keeps counters + gets its log
    client, _ = make_client()
    client._cancel_grace_until = time.monotonic() + 5.0
    before = counters.snapshot()
    n_before = len(LOG_RECORDS)
    await client._handle_text(json.dumps(
        {"type": "error", "error": {"code": "no_active_response"}}))
    after = counters.snapshot()
    new = "\n".join(LOG_RECORDS[n_before:])
    check("G3 cancel-grace error: benign log, no counter change",
          "benign cancel error ignored: no_active_response" in new
          and after["upstream_errors"] == before["upstream_errors"], new)

    # G4 — typeless frame does NOT touch upstream_errors (observability only)
    client, _ = make_client()
    before = counters.snapshot()
    await client._handle_text(json.dumps({"error": {"code": "zzz"}}))
    after = counters.snapshot()
    check("G4 typeless frame: zero counter change",
          after["upstream_errors"] == before["upstream_errors"],
          (before["upstream_errors"], after["upstream_errors"]))

    # G5 — session.update payload frozen
    client, _ = make_client()
    expected = {"type": "session.update",
                "session": {"model": "m-synth", "voice": "v-synth",
                            "instructions": qwen.TUTOR_INSTRUCTION,
                            "input_audio_format": "pcm16",
                            "output_audio_format": "pcm16",
                            "turn_detection": {"type": "server_vad",
                                               "threshold": 0.5,
                                               "silence_duration_ms": 800}}}
    check("G5 session.update payload byte-frozen (structure + defaults)",
          client._session_update_msg() == expected,
          client._session_update_msg())

    # G6 — frozen constants
    check("G6 constants frozen (timeout/grace/model/voice)",
          qwen.SESSION_CREATED_TIMEOUT == 5.0 and qwen.CANCEL_GRACE_S == 3.0
          and qwen.DEFAULT_MODEL == "qwen3.8-omni-flash-realtime"
          and qwen.DEFAULT_VOICE == "Tina", "")

    # G7 — redaction helpers are exception-safe on odd inputs
    check("G7 redaction helpers exception-safe (no crash, shape-masked)",
          qwen._diag_text({"a": 1}) is None
          and qwen._diag_text(b"bytes") is None
          and qwen._diag_text(None) is None
          and "sk-" not in (qwen._diag_text("k=" + FAKE_KEY) or "")
          and len(qwen._diag_text("x" * 5000) or "") <= 200, "")


async def amain():
    logger = logging.getLogger("rtl.qwen")
    capture = _Capture()
    old_level = logger.level
    logger.addHandler(capture)
    logger.setLevel(logging.DEBUG)
    try:
        await frame_cases()
        await ws_cases()
        await guard_cases()
    finally:
        logger.removeHandler(capture)
        logger.setLevel(old_level)

    # Global secret scan across every captured record
    all_text = log_text()
    leaked = [s for s in FORBIDDEN_SUBSTRINGS if s in all_text]
    check("G8 no fake secret appears in ANY log record", not leaked, leaked)
    check("G9 diagnostics actually produced records",
          len(LOG_RECORDS) >= 6, len(LOG_RECORDS))

    fails = [r for r in RESULTS if not r[1]]
    print("=" * 72)
    print("QWEN_DIAG_TESTS: %d checks, %d PASS, %d FAIL"
          % (len(RESULTS), len(RESULTS) - len(fails), len(fails)))
    if fails:
        print("FAILED CHECKS:")
        for name, _, detail in fails:
            print("  - %s %s" % (name, detail))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
