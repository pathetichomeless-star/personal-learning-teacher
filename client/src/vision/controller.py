"""VISION V0.6 控制器：状态机 + 频率守卫 + HTTP 提交（零 PySide6 依赖）。

会话隔离：图像只提交到构造时绑定的 session 标识；跨会话提交被拒绝。
降级：任何失败通过 on_error 回调上报，绝不影响语音路径。
"""
import json
import urllib.error
import urllib.request


class VisionController:
    def __init__(self, endpoint, token, session_id, enabled=False,
                 min_interval_s=5.0, max_per_min=6, on_error=None):
        self.endpoint = endpoint
        self.token = token
        self.session_id = session_id
        self.enabled = enabled
        self._min_interval = min_interval_s
        self._max_per_min = max_per_min
        self._window = []
        self._last = None
        self._on_error = on_error

    def set_enabled(self, flag):
        self.enabled = bool(flag)

    def _allow(self, now):
        if self._last is not None and now - self._last < self._min_interval:
            return False, "rate_interval"
        self._window = [t for t in self._window if now - t < 60.0]
        if len(self._window) >= self._max_per_min:
            return False, "rate_per_minute"
        self._window.append(now)
        self._last = now
        return True, ""

    def submit(self, jpeg_bytes, now=None):
        """提交单帧。返回 (True, response_dict) / (False, reason)。
        顺序前提：调用方必须已确认本轮存在音频 append（409 → 提示先说话）。"""
        import time as _t
        if not self.enabled:
            return False, "vision_disabled"
        try:
            from src.vision.compress import validate_jpeg
        except ImportError:
            from vision.compress import validate_jpeg
        ok, why = validate_jpeg(jpeg_bytes)
        if not ok:
            return False, why
        now = now if now is not None else _t.monotonic()
        allowed, why = self._allow(now)
        if not allowed:
            return False, why
        body = json.dumps({"image_b64": base64_encode(jpeg_bytes),
                           "session_id": self.session_id}).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint, data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "X-Vision-Token": self.token})
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                return r.status == 200, json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read().decode("utf-8")).get("reason", "")
            except Exception:
                detail = ""
            if self._on_error:
                self._on_error(e.code, detail)
            return False, "http_%d:%s" % (e.code, detail)
        except Exception as e:
            if self._on_error:
                self._on_error(0, str(e))
            return False, "network_error"


def base64_encode(data):
    import base64
    return base64.b64encode(data).decode("ascii")
