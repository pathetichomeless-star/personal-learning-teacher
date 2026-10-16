"""视觉插件（V1.0）：数字人桥 + 图像提交（默认关闭，零语音链路改动）。"""
from typing import TYPE_CHECKING

from src.avatar.engine import resolve_avatar_engine
from src.logging import get_logger
from src.plugins.base import Plugin
from src.vision.qml_bridge import VisionBridge

if TYPE_CHECKING:
    from src.bootstrap.protocols import PluginCommands, PluginContext

logger = get_logger()


class VisionPlugin(Plugin):
    name = "vision"
    priority = 60

    def __init__(self):
        super().__init__()
        self.bridge: VisionBridge | None = None

    async def setup(self, ctx: "PluginContext", cmd: "PluginCommands") -> None:
        try:
            # PluginContext 协议暴露 get_config()（adapters.py:47），返回 ConfigManager
            # （ConfigManager 读接口为 get_config(path, default)，无 .get() 方法）
            cfg = ctx.get_config() if hasattr(ctx, "get_config") else None
            enabled = bool(cfg and cfg.get_config("VISION.ENABLED", False))
            endpoint = "http://127.0.0.1:8111/xiaozhi/vision/"
            # V1_FINAL_REVIEW F1 闭合：token 从配置读取（VISION.TOKEN），不再硬编码空值
            token = str(cfg.get_config("VISION.TOKEN", "") or "") if cfg else ""
            self.bridge = VisionBridge(endpoint=endpoint, token=token)
            self.bridge.setEnabled(enabled)
            # 数字人引擎解析（纯逻辑见 src/avatar/engine.py）：配置缺失/非法值/
            # vendor 资产缺失一律回退 canvas-fallback；与视觉开关无关
            engine, reason = resolve_avatar_engine(
                cfg.get_config if cfg is not None else None)
            self.bridge.apply_engine(engine, reason)
            container = getattr(ctx, "container", None)
            if container is not None:
                container.vision_bridge = self.bridge
            logger.info("VISION 插件就绪（enabled=%s）", enabled)
        except Exception as e:                       # noqa: BLE001
            self.mark_failed()
            logger.warning("VISION 插件初始化失败（不影响语音）：%r", e)

    def register_resources(self, pool) -> None:
        if self.bridge is not None:
            # ResourcePool.register(name, cleanup)（resource_pool.py:31）
            pool.register("vision.env_timer", self.bridge._env_timer.stop)
