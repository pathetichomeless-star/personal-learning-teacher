"""VISION V1.0 — QML 桥（数字人 + 视觉提交）。

VisionBridge(QObject)：向 QML 暴露数字人状态与口型包络；
视觉提交经 HTTP /xiaozhi/vision/（X-Vision-Token，专用令牌）。
口型 = 协议包络（tts start/stop 事件驱动，8-14Hz 伪随机幅度）；
真实逐样本 RMS 探针为冻结链路例外（V06_AUDIO_SYNC_BLOCKER_ANALYSIS），待 PO 批准。
"""
import json
import math
import random
import time
import urllib.error
import urllib.request

from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer

from src.logging import get_logger

logger = get_logger()

MIN_INTERVAL_S = 5.0
MAX_PER_MIN = 6
RAW_MAX = 190 * 1024

VISION_BRIDGE = None   # 模块级单例：插件 setup 时设置；GUI 注入时防御读取


class VisionBridge(QObject):
    avatarStateChanged = Signal()
    mouthLevelChanged = Signal()
    visionEnabledChanged = Signal()
    visionStatusChanged = Signal()
    avatarEngineChanged = Signal()
    transcriptAppended = Signal(str, str)

    def __init__(self, endpoint="http://127.0.0.1:8111/xiaozhi/vision/",
                 token="", parent=None):
        super().__init__(parent)
        self._avatar_state = "idle"       # idle/listening/thinking/speaking/interrupted
        self._mouth_level = 0.0
        self._enabled = False
        self._status = "视觉关闭"
        self._avatar_engine = "canvas-fallback"   # 引擎解析由 VisionPlugin.setup 写入
        self._endpoint = endpoint
        self._token = token
        self._generation = 0
        self._window = []
        self._last = None
        self._blink_timer = 0.0
        self._env_timer = QTimer(self)
        self._env_timer.setInterval(80)   # 12.5Hz 包络
        self._env_timer.timeout.connect(self._envelope_tick)
        global VISION_BRIDGE
        VISION_BRIDGE = self

    # ---- QML 属性 ----
    def _get_state(self): return self._avatar_state
    avatarState = Property(str, _get_state, notify=avatarStateChanged)

    def _get_mouth(self): return self._mouth_level
    mouthLevel = Property(float, _get_mouth, notify=mouthLevelChanged)

    def _get_enabled(self): return self._enabled
    visionEnabled = Property(bool, _get_enabled, notify=visionEnabledChanged)

    def _get_status(self): return self._status
    visionStatus = Property(str, _get_status, notify=visionStatusChanged)

    def _get_engine(self): return self._avatar_engine
    avatarEngine = Property(str, _get_engine, notify=avatarEngineChanged)

    def apply_engine(self, engine, reason=""):
        """写入解析后的数字人引擎（VisionPlugin.setup 调用；只读 Property）。"""
        engine = str(engine)
        if engine not in ("live2d", "canvas-fallback"):
            engine = "canvas-fallback"
        changed = engine != self._avatar_engine
        self._avatar_engine = engine
        if changed:
            self.avatarEngineChanged.emit()
        logger.info("AVATAR engine=%s%s", engine, ("（%s）" % reason) if reason else "")

    # ---- 语音事件订阅点（由客户端 TTS 事件调用；零音频链路改动） ----
    @Slot()
    def onTtsStart(self):
        self._generation += 1
        self._set_state("speaking")
        if not self._env_timer.isActive():
            self._env_timer.start()

    @Slot()
    def onTtsStop(self):
        self._mouth_level = 0.0
        self.mouthLevelChanged.emit()
        self._env_timer.stop()
        self._set_state("listening")

    @Slot()
    def onInterrupted(self):
        """打断：口型立即归零 + 包络停止。"""
        self._env_timer.stop()
        self._mouth_level = 0.0
        self.mouthLevelChanged.emit()
        self._set_state("interrupted")

    @Slot(str)
    def onTranscript(self, text):
        self.transcriptAppended.emit("tina", str(text))

    def _set_state(self, s):
        if self._avatar_state != s:
            self._avatar_state = s
            self.avatarStateChanged.emit()

    def _envelope_tick(self):
        if self._avatar_state != "speaking":
            return
        self._mouth_level = 0.15 + 0.75 * abs(math.sin(time.monotonic() * 9.0)) \
            * (0.75 + 0.25 * random.random())
        self.mouthLevelChanged.emit()

    # ---- 视觉开关与提交 ----
    @Slot(bool)
    def setEnabled(self, flag):
        self._enabled = bool(flag)
        self._status = "视觉已开启" if self._enabled else "视觉关闭"
        self.visionEnabledChanged.emit()
        self.visionStatusChanged.emit()
        logger.info("VISION enabled=%s", self._enabled)

    @Slot(str)
    def submitImagePath(self, path):
        """读取本地图片 → 校验/压缩（V1.0：直接读取 JPEG；压缩由采集端完成）→ 提交。"""
        if not self._enabled:
            self._status = "视觉未开启"
            self.visionStatusChanged.emit()
            return
        now = time.monotonic()
        if self._last is not None and now - self._last < MIN_INTERVAL_S:
            self._status = "提交过快（间隔 ≥5 秒）"
            self.visionStatusChanged.emit()
            return
        self._window = [t for t in self._window if now - t < 60.0]
        if len(self._window) >= MAX_PER_MIN:
            self._status = "超出每分钟频率上限"
            self.visionStatusChanged.emit()
            return
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError as e:
            self._status = "读取失败：%s" % e
            self.visionStatusChanged.emit()
            return
        if len(raw) < 3 or raw[:3] != b"\xff\xd8\xff":
            self._status = "仅支持 JPEG 图片"
            self.visionStatusChanged.emit()
            return
        if len(raw) > RAW_MAX:
            self._status = "图片超过 190KB，请压缩后重试"
            self.visionStatusChanged.emit()
            return
        import base64
        b64 = base64.b64encode(raw).decode("ascii")
        self._window.append(now)
        self._last = now
        self._status = "已提交，等待识别…"
        self.visionStatusChanged.emit()
        threading_submit(self._endpoint, self._token, b64, self._on_submit_done)

    def _on_submit_done(self, ok, payload):
        if ok:
            self._status = "已进入当前轮次"
        else:
            self._status = "提交失败：%s" % payload.get("reason", payload)
        self.visionStatusChanged.emit()


def threading_submit(endpoint, token, b64, done):
    """后台线程提交（8s 超时），结果经 done 回调（Qt 信号线程安全由调用方保证）。"""
    import threading

    def work():
        try:
            req = urllib.request.Request(
                endpoint, data=json.dumps({"image_b64": b64}).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json",
                         "X-Vision-Token": token})
            with urllib.request.urlopen(req, timeout=8) as r:
                payload = json.loads(r.read().decode("utf-8") or "{}")
                done(r.status == 200, payload)
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read().decode("utf-8") or "{}")
            except Exception:
                payload = {"reason": "http %d" % e.code}
            done(False, payload)
        except Exception as e:
            done(False, {"reason": str(e)})

    threading.Thread(target=work, daemon=True).start()
