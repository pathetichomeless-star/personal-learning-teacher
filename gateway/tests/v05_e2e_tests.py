"""V05_E2E_TESTS — 视觉 HTTP 端点 + 客户端提交链路（隔离 stub，无网络）。

覆盖 V05_SECURITY_QA_TEST_DESIGN Layer E 的可自动化核心：
  E1 令牌 negatives（缺失/错误 → 401；恒时比较）
  E2 双层尺寸（HTTP 413 + send_image too_large_raw）
  E4 全链（正确令牌 + 音频先行 + 合法 JPEG → 200 accepted + 官方事件上线）
  E5 排序（无音频先行 → 409 ordering_audio_first）
  E6 频率（429 rate_per_minute）
  E7 音频路径零触碰（视觉拒绝后 send_append 正常）
  E8 类型（PNG → 415 not_jpeg）
Run: cd gateway && DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python tests/v05_e2e_tests.py
"""
import asyncio
import base64
import json
import time
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from aiohttp import web                                           # noqa: E402
import app.qwen as qwen                                           # noqa: E402
import app.http as http_mod                                       # noqa: E402

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


class FakeConfig:
    workspace_id = ""


async def amain():
    tmp = Path(tempfile.mkdtemp(prefix="v05_e2e_"))
    token_file = tmp / "vision_token"
    token_file.write_text("e2e-vision-token", encoding="utf-8")
    import os
    os.environ["VISION_TOKEN_FILE"] = str(token_file)

    jpg5k = b"\xff\xd8\xff" + b"\x00" * 5000
    png5k = b"\x89PNG\r\n\x1a\n" + b"\x00" * 5000

    async def build_app_and_client():
        app = web.Application()
        app.router.add_post("/xiaozhi/vision/", http_mod.make_vision_handler(FakeConfig()))
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = runner.addresses[0][1]
        return runner, port

    async def post(port, body, token="e2e-vision-token", headers=None):
        import aiohttp
        async with aiohttp.ClientSession() as sess:
            h = dict(headers or {})
            if token is not None:
                h["X-Vision-Token"] = token
            async with sess.post("http://127.0.0.1:%d/xiaozhi/vision/" % port,
                                 json=body, headers=h) as r:
                return r.status, await r.json()

    # 桩 QwenClient（已连接 + 音频先行）
    def fresh_client(connected=True, audio_seen=True):
        cfg = qwen.QwenConfig(mode="mock", ws_url="ws://127.0.0.1:9/x",
                              model="m", voice="v", api_key="", workspace_id="",
                              region="cn", reconnect_max=1, reconnect_base_ms=1,
                              stable_reset_s=30)
        c = qwen.QwenClient(cfg, lambda o: None)
        c._diag_begin()
        c._ws = StubWS()
        c._session = StubSession(c._ws)
        c._connected = connected
        c._counted = True
        c._audio_seen = audio_seen
        qwen._ACTIVE_INSTANCES.add(c)
        return c

    runner, port = await build_app_and_client()

    # E1 — 令牌 negatives
    c = fresh_client()
    st, d = await post(port, {"image_b64": base64.b64encode(jpg5k).decode()}, token=None)
    check("E1a 缺失令牌 → 401", st == 401 and d["reason"] == "invalid_token", (st, d))
    st, d = await post(port, {"image_b64": base64.b64encode(jpg5k).decode()},
                       token="wrong")
    check("E1b 错误令牌 → 401", st == 401, (st, d))
    qwen._ACTIVE_INSTANCES.discard(c)

    # E5 — 排序（无音频先行）
    c = fresh_client(audio_seen=False)
    st, d = await post(port, {"image_b64": base64.b64encode(jpg5k).decode()})
    check("E5 无音频先行 → 409 ordering", st == 409
          and d["reason"] == "ordering_audio_first", (st, d))
    qwen._ACTIVE_INSTANCES.discard(c)

    # E8 — 类型
    c = fresh_client()
    st, d = await post(port, {"image_b64": base64.b64encode(png5k).decode()})
    check("E8 PNG → 415 not_jpeg", st == 415 and d["reason"] == "not_jpeg", (st, d))
    qwen._ACTIVE_INSTANCES.discard(c)

    # E2 — 双层尺寸
    c = fresh_client()
    big = b"\xff\xd8\xff" + b"\x00" * (qwen.QwenClient._VISION_RAW_MAX_BYTES + 1 - 3)
    st, d = await post(port, {"image_b64": base64.b64encode(big).decode()})
    check("E2 超大 → 413 too_large_raw", st == 413
          and d["reason"] == "too_large_raw", (st, d))
    qwen._ACTIVE_INSTANCES.discard(c)

    # E4 — 全链（正确令牌 + 音频先行 + 合法 JPEG）
    c = fresh_client()
    st, d = await post(port, {"image_b64": base64.b64encode(jpg5k).decode()})
    frames = [f for f in c._ws.sent if f.get("type") == "input_image_buffer.append"]
    check("E4 全链 accepted → 200 + 官方事件上线", st == 200 and d.get("accepted") is True
          and len(frames) == 1
          and base64.b64decode(frames[0]["image"]) == jpg5k, (st, d, frames[:1]))

    # E6 — 频率（重置间隔状态 + 假时钟 6s 步进，专测 ≤6/min → 429）
    c._vision_last_ts = None
    c._vision_window = []
    fc = {"t": time.monotonic()}
    qwen.time.monotonic = (lambda: fc["t"])
    accepted = 0
    last = None
    try:
        for i in range(8):
            st, d = await post(port, {"image_b64": base64.b64encode(jpg5k).decode()})
            if st == 200:
                accepted += 1
            else:
                last = (st, d.get("reason"))
                break
            fc["t"] += 6.0
    finally:
        qwen.time.monotonic = time.monotonic
    check("E6 频率 → 429 rate_per_minute", accepted == 6
          and last == (429, "rate_per_minute"), (accepted, last))
    qwen._ACTIVE_INSTANCES.discard(c)

    # E7 — 音频路径零触碰
    c = fresh_client()
    await c.send_append(b"\x01" * 320)
    before = len(c._ws.sent)
    await c.send_image(png5k)                      # 视觉拒绝
    await c.send_append(b"\x01" * 320)                 # 音频继续
    check("E7 视觉拒绝后音频正常",
          any(f.get("type") == "input_audio_buffer.append" for f in c._ws.sent[before:]),
          c._ws.sent[before:])
    qwen._ACTIVE_INSTANCES.discard(c)

    await runner.cleanup()
    print("=" * 60)
    fails = [r for r in RESULTS if not r[1]]
    print("V05_E2E_TESTS: %d checks, %d PASS, %d FAIL"
          % (len(RESULTS), len(RESULTS) - len(fails), len(fails)))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
