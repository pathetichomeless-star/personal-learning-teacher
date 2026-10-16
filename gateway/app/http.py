"""HTTP endpoints: GET /health, POST+GET /xiaozhi/ota/, POST /xiaozhi/vision/."""
import base64 as _b64
import hmac as _hmac
import json as _json
import os as _os


import logging

from aiohttp import web

from . import diag
from .counters import counters

log = logging.getLogger("rtl.http")


async def health(request):
    return web.json_response(counters.snapshot())


async def diag_view(request):
    """R-1c read-only diagnostic view (serves {"enabled": false} when off)."""
    return web.json_response(diag.SNAPSHOT_PROVIDER())


async def diag_reset(request):
    """Clear the in-memory R-1c journal/assertions (no behavior change)."""
    diag.RESET_PROVIDER()
    return web.json_response({"ok": True})


async def diag_capture(request):
    return web.json_response(diag.capture_info())


async def ota(request, config):
    # Strictly scoped payload: MUST NOT contain an "activation" key or any
    # other fields.
    return web.json_response({
        "websocket": {
            "url": config.PUBLIC_WS_URL,
            "token": "test-token",
        },
    })

# ---- VISION V0.5: 客户端图像提交端点（8111 平面，专用令牌鉴权） ----
# 鉴权：X-Vision-Token vs secrets/vision_token（恒时比较）——绝不使用 Admin Bearer。
# 守卫：体长上限 → base64 解码 → QwenClient.send_image 五重守卫（尺寸/频率/排序）。
# 音频/VAD/turns 零改动：仅经 qwen.submit_vision_image 模块级注册表转发。


def make_vision_handler(config):
    token_path = _os.environ.get("VISION_TOKEN_FILE",
                                 "/app/secrets/vision_token")

    def _token():
        try:
            with open(token_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return ""

    async def vision(request):
        provided = request.headers.get("X-Vision-Token", "")
        expected = _token()
        if not expected or not _hmac.compare_digest(
                provided.encode("utf-8"), expected.encode("utf-8")):
            return web.json_response({"accepted": False,
                                      "reason": "invalid_token"}, status=401)
        if request.content_length and request.content_length > 320 * 1024:
            return web.json_response({"accepted": False,
                                      "reason": "payload_too_large"}, status=413)
        try:
            data = _json.loads(await request.text())
        except Exception:
            return web.json_response({"accepted": False,
                                      "reason": "bad_json"}, status=400)
        b64 = data.get("image_b64")
        if not isinstance(b64, str) or not b64:
            return web.json_response({"accepted": False,
                                      "reason": "image_b64_missing"}, status=400)
        try:
            raw = _b64.b64decode(b64, validate=True)
        except Exception:
            return web.json_response({"accepted": False,
                                      "reason": "bad_base64"}, status=400)
        from app import qwen as _qwen
        ok, reason = await _qwen.submit_vision_image(raw)
        if ok:
            return web.json_response({"accepted": True})
        # 状态映射（GATEWAY_PROTOCOL_DESIGN）：415 类型 / 413 尺寸 / 429 频率 /
        # 409 排序 / 503 无连接
        status = {"not_jpeg": 415, "too_large_raw": 413, "too_large_b64": 413,
                  "rate_interval": 429, "rate_per_minute": 429,
                  "ordering_audio_first": 409, "not_connected": 503}.get(reason, 422)
        return web.json_response({"accepted": False, "reason": reason}, status=status)

    return vision
