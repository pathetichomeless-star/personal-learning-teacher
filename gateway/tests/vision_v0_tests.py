"""VISION_V0_TESTS — gateway-level tests for the vision V0 slice.

Drives a real app.qwen.QwenClient with a stub websocket (NO network, NO real
upstream — same harness as qwen_diag_tests) and verifies send_image():

  V1  JPEG magic-byte guard
  V2  raw-size cap (190KB)
  V3  base64 cap (256KB — defensively unreachable via the raw cap, noted)
  V4  official ordering (≥1 audio append precedes the first image)
  V5  happy path: the EXACT official event shape on the wire
  V6  rate limits (≥5s interval + ≤6/min, fake clock)
  V7  degradation: rejections never touch the audio path
  V8  per-connection isolation (two clients, independent windows)
  V9  (re)connect resets the vision state

Run:
    cd <project-root>/gateway
    DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python tests/vision_v0_tests.py
"""

import asyncio
import base64
import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import aiohttp                                                # noqa: E402
import app.qwen as qwen                                       # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  <- " + str(detail)) if (detail and not cond) else ""))


class StubWS:
    def __init__(self):
        self.sent = []
        self.closed = False

    async def send_str(self, s):
        self.sent.append(json.loads(s))


class StubSession:
    def __init__(self, ws):
        self._ws = ws
        self.closed = False

    async def ws_connect(self, *a, **k):
        return self._ws

    async def close(self):
        self.closed = True


def make_client(fake_clock=None):
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
    client._ws = StubWS()
    client._session = StubSession(client._ws)
    client._connected = True
    client._counted = True
    if fake_clock is not None:
        qwen.time.monotonic = fake_clock
    return client, forwarded


def jpeg(n=5000):
    return b"\xff\xd8\xff" + b"\x00" * (n - 3)


def png(n=5000):
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * (n - 8)


def restore_clock():
    qwen.time.monotonic = time.monotonic


async def amain():
    print("==== VISION V0 — gateway-level guard tests ====")

    # V1 — JPEG magic-byte guard
    c, fwd = make_client()
    ok, why = await c.send_image(png(5000))
    check("V1 not_jpeg rejected", (ok, why) == (False, "not_jpeg"), (ok, why))
    check("V1b no frame sent on rejection", len(c._ws.sent) == 0, c._ws.sent)
    restore_clock()

    # V2 — raw-size cap
    c, _ = make_client()
    ok, why = await c.send_image(jpeg(qwen.QwenClient._VISION_RAW_MAX_BYTES + 1))
    check("V2 too_large_raw rejected", (ok, why) == (False, "too_large_raw"), (ok, why))
    restore_clock()

    # V3 — base64 cap (defensive belt: unreachable via the raw cap — documented)
    check("V3 base64 cap constant present",
          qwen.QwenClient._VISION_B64_MAX_BYTES == 256 * 1024, "constant")

    # V4 — official ordering
    c, _ = make_client()
    ok, why = await c.send_image(jpeg(5000))
    check("V4 ordering: image before audio rejected",
          (ok, why) == (False, "ordering_audio_first"), (ok, why))

    # V5 — happy path: exact official event shape
    c, fwd = make_client()
    await c.send_append(b"\x01" * 320)
    ok, why = await c.send_image(jpeg(5000))
    frames = [f for f in c._ws.sent if f.get("type") == "input_image_buffer.append"]
    check("V5 happy path accepted", (ok, why) == (True, ""), (ok, why))
    check("V5b wire event = official shape",
          len(frames) == 1 and frames[0]["type"] == "input_image_buffer.append"
          and isinstance(frames[0]["image"], str)
          and base64.b64decode(frames[0]["image"]) == jpeg(5000), frames[:1])
    check("V5c audio append also on wire (ordering prerequisite met)",
          any(f.get("type") == "input_audio_buffer.append" for f in c._ws.sent))

    # V6 — rate limits (fake clock)
    t = {"now": 1000.0}
    fake = (lambda: t["now"])
    c, _ = make_client(fake)
    await c.send_append(b"\x01" * 320)
    accepted = 0
    for i in range(8):
        ok, why = await c.send_image(jpeg(1000))
        accepted += 1 if ok else 0
        if not ok:
            first_reason = why
            break
        t["now"] += 6.0                    # 6s 步进：满足 ≥5s 间隔，触发 ≤6/min
    check("V6a >6/min rejected", accepted == 6 and first_reason == "rate_per_minute",
          (accepted, first_reason))
    restore_clock()
    c2, _ = make_client()
    await c2.send_append(b"\x01" * 320)
    ok1, _ = await c2.send_image(jpeg(1000))
    ok2, why2 = await c2.send_image(jpeg(1000))
    check("V6b <5s interval rejected", ok1 and (ok2, why2) == (False, "rate_interval"),
          (ok1, ok2, why2))
    restore_clock()

    # V7 — degradation: rejections never touch the audio path
    c, _ = make_client()
    ok, why = await c.send_image(png(5000))            # rejected
    sent_before = len(c._ws.sent)
    await c.send_append(b"\x01" * 320)                 # audio continues
    check("V7 audio path unaffected after vision rejection",
          any(f.get("type") == "input_audio_buffer.append" for f in c._ws.sent[sent_before:]),
          c._ws.sent[sent_before:])

    # V8 — per-connection isolation
    ca, _ = make_client()
    cb, _ = make_client()
    await ca.send_append(b"\x01" * 320)
    okb, whyb = await cb.send_image(jpeg(1000))
    check("V8 client B unaffected by client A's audio history",
          (okb, whyb) == (False, "ordering_audio_first"), (okb, whyb))

    # V10 — teardown 注销（V06-F1 回归：close 后注册表无泄漏引用）
    c, _ = make_client()
    await c.send_append(b"\x01" * 320)
    qwen._ACTIVE_INSTANCES.add(c)
    await c._teardown()
    check("V10 teardown 后注册表无泄漏引用",
          c not in qwen._ACTIVE_INSTANCES, qwen._ACTIVE_INSTANCES)

    # V11 — 多会话歧义显式拒绝（V06-R5：图片绝不进错会话）
    ca, _ = make_client()
    cb, _ = make_client()
    await ca.send_append(b"\x01" * 320)
    await cb.send_append(b"\x01" * 320)
    qwen._ACTIVE_INSTANCES.add(ca)
    qwen._ACTIVE_INSTANCES.add(cb)
    ok, why = qwen.submit_vision_image(jpeg(1000))
    check("V11 多活跃会话 → ambiguous_session",
          (ok, why) == (False, "ambiguous_session"), (ok, why))
    qwen._ACTIVE_INSTANCES.discard(ca)
    qwen._ACTIVE_INSTANCES.discard(cb)

    # V9 — (re)connect resets vision state
    c, _ = make_client()
    await c.send_append(b"\x01" * 320)
    await c.send_image(jpeg(1000))
    c._audio_seen = False                               # simulate a fresh session
    c._vision_window = []
    c._vision_last_ts = None
    ok, why = await c.send_image(jpeg(1000))
    check("V9 fresh session enforces ordering again",
          (ok, why) == (False, "ordering_audio_first"), (ok, why))

    restore_clock()
    print("=" * 60)
    fails = [r for r in RESULTS if not r[1]]
    print("VISION_V0_TESTS: %d checks, %d PASS, %d FAIL"
          % (len(RESULTS), len(RESULTS) - len(fails), len(fails)))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
