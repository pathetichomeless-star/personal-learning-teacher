"""QML 引擎宿主：加载、上下文注入、根窗口操作."""

import os
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtQml import QQmlApplicationEngine

from src.logging import get_logger

logger = get_logger()


def _prepare_webengine_env() -> None:
    """AVATAR.ENGINE=live2d 时禁用 QtWebEngine 沙箱（必须在引擎创建前设置）。

    权衡（dev 机器）：QtWebEngine 多进程沙箱在受控/受限宿主下初始化失败
    （Chromium sandbox: Operation not permitted，见
    prototypes/avatar-runtime-lab/README.md §7.1），导致渲染子进程无法启动；
    本客户端仅加载本地 avatar_page.html（无远程内容），禁用沙箱的暴露面
    可接受。配置非 live2d 时不设置，保持零行为变化。
    """
    try:
        from src.avatar.engine import ENGINE_LIVE2D, resolve_avatar_engine
        from src.utils.config_manager import get_config

        engine, _ = resolve_avatar_engine(get_config().get_config)
        if engine == ENGINE_LIVE2D:
            os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
            logger.info("WebEngine: QTWEBENGINE_DISABLE_SANDBOX=1（AVATAR.ENGINE=live2d）")
    except Exception as e:                                   # noqa: BLE001
        # 配置缺席/异常 → 不设置环境变量，QML 侧走 canvas 回退
        logger.debug("WebEngine: 引擎配置解析跳过沙箱设置：%r", e)


def _show_window(window, *, activate: bool) -> None:
    """显示窗口；activate=False 时尽量不抢前台（macOS 全屏 Space 友好）."""
    if window is None:
        return

    if activate:
        window.show()
        window.raise_()
        window.requestActivate()
        return

    # QWidget 路径：ShowWithoutActivating
    set_attr = getattr(window, "setAttribute", None)
    if callable(set_attr):
        set_attr(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        try:
            window.show()
        finally:
            set_attr(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        return

    # QQuickWindow / QWindow：临时去掉可获焦，避免成为 key window
    # （macOS 上 key window 会把其它全屏 App 的 Space 挤掉）
    flags = window.flags()
    try:
        window.setFlags(flags | Qt.WindowType.WindowDoesNotAcceptFocus)
        window.show()
    finally:
        window.setFlags(flags)


class QmlAppHost:
    """只负责 QML 引擎生命周期与根对象访问，不碰业务逻辑."""

    def __init__(self) -> None:
        self._engine: QQmlApplicationEngine | None = None

    @property
    def engine(self) -> QQmlApplicationEngine | None:
        return self._engine

    def create_engine(self) -> QQmlApplicationEngine:
        _prepare_webengine_env()
        self._engine = QQmlApplicationEngine()
        return self._engine

    def inject_context(self, properties: dict) -> None:
        if not self._engine:
            raise RuntimeError("QML engine not created")
        ctx = self._engine.rootContext()
        for name, obj in properties.items():
            ctx.setContextProperty(name, obj)
        logger.debug("QmlAppHost: 已注入 QML 上下文 %s", list(properties))

    def load_main(self) -> None:
        if not self._engine:
            raise RuntimeError("QML engine not created")
        qml_dir = Path(__file__).parent / "qml"
        self._engine.addImportPath(str(qml_dir))
        main_qml = qml_dir / "main.qml"
        self._engine.load(QUrl.fromLocalFile(str(main_qml)))
        if not self._engine.rootObjects():
            logger.error("QmlAppHost: QML 加载失败")
            raise RuntimeError("Failed to load QML")
        logger.debug("QmlAppHost: 已加载 %s", main_qml)

    def root_window(self):
        if not self._engine:
            return None
        roots = self._engine.rootObjects()
        return roots[0] if roots else None

    def show_root(self, *, activate: bool = True) -> None:
        """显示主窗口.

        Args:
            activate: True=抢前台（托盘「显示窗口」/快捷键）；
                      False=仅显示、不 requestActivate（冷启动，避免挤掉 macOS 全屏 App）
        """
        _show_window(self.root_window(), activate=activate)

    def toggle_root_visible(self) -> None:
        window = self.root_window()
        if window is None:
            return
        if window.isVisible():
            window.hide()
        else:
            # 用户主动切换：需要到前台
            self.show_root(activate=True)

    def shutdown(self) -> None:
        if self._engine:
            self._engine.deleteLater()
            self._engine = None
