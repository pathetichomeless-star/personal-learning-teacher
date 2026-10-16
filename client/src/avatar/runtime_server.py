"""AVATAR 运行时回环静态服务器（D12 整改）。

背景：AvatarLive2D.qml 原以 file:// 加载 avatar_page.html，QtWebEngine 下
file→file XHR 受 CORS 约束，motion3.json / motion 文件加载失败（终验 D12：
currentMotion=null、idle motion 未挂载）。本模块由 Python 侧起一个仅绑定
127.0.0.1 的静态文件服务器，页面改经 http://127.0.0.1:<ephemeral>/ 加载，
与实验室（tools/verify_chrome.py 走本地 HTTP）验证通道一致。

安全属性（详见 client/README.md「AVATAR 运行时本地服务器」一节）：
  - 仅绑定 127.0.0.1（回环，外部不可达）；
  - 仅静态文件、仅 GET/HEAD，无任何动态端点；
  - root 锁定 src/avatar/runtime/，translate_path 后强制 realpath 校验，
    拒绝路径穿越（../ / 绝对路径 / 符号链接逃逸一律 403）；
  - 禁用目录列表（目录请求 → 403）；
  - 端口为 ephemeral（port=0），无固定端口被扫描/抢占的风险；
  - 生命周期引用计数（acquire/release）：QML 组件挂载 acquire、销毁
    release，计数归零即 shutdown 线程；force_shutdown 供应用退出兜底。
"""

from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from src.logging import get_logger

logger = get_logger()

_RUNTIME_ROOT = Path(__file__).resolve().parent / "runtime"


class _LockedRootHandler(SimpleHTTPRequestHandler):
    """root 锁定 + 禁目录列表 + 拒穿越的静态 handler。"""

    # -- directory 参数（SimpleHTTPRequestHandler 自带）已把 cwd 锁到 root；
    #    但 normpath 后仍可能逃出 root（如 /../../x），需 realpath 复核。

    def translate_path(self, path):  # noqa: D102
        resolved = Path(super().translate_path(path)).resolve()
        root = Path(self.directory).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            raise PermissionError("path escapes runtime root") from None
        return str(resolved)

    def send_head(self):  # noqa: D102
        # 目录请求一律 403：禁用目录列表（SimpleHTTPRequestHandler 默认生成索引页）；
        # 穿越请求（translate_path raise PermissionError）同样 403
        try:
            target = Path(self.translate_path(self.path)).resolve()
            if target.is_dir():
                self.send_error(403, "Forbidden")
                return None
            return super().send_head()
        except PermissionError:
            self.send_error(403, "Forbidden")   # raise 发生在任何字节发出前，安全
            return None

    def log_message(self, format, *args):  # noqa: A002,N802
        logger.debug("avatar-runtime-server: %s", format % args)


class _RootedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class AvatarRuntimeServer(QObject):
    """QML 可见的回环静态服务器句柄（context property 注入）。"""

    urlChanged = Signal()

    def __init__(self, parent: QObject | None = None,
                 root: Path | None = None) -> None:
        super().__init__(parent)
        self._root = Path(root).resolve() if root else _RUNTIME_ROOT
        self._httpd: _RootedHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._refs = 0
        self._lock = threading.Lock()
        self._url = ""

    # ---- QML 面：url 只读属性 ----

    def _get_url(self) -> str:
        return self._url

    url = Property(str, _get_url, notify=urlChanged)

    # ---- QML 面：生命周期 ----

    @Slot()
    def acquire(self) -> None:
        """组件挂载：引用 +1，首引用时启动。"""
        with self._lock:
            self._refs += 1
            if self._httpd is None:
                self._start_locked()

    @Slot()
    def release(self) -> None:
        """组件销毁：引用 -1，归零即 shutdown（生命周期与组件绑定）。"""
        with self._lock:
            self._refs = max(0, self._refs - 1)
            if self._refs == 0 and self._httpd is not None:
                self._stop_locked()

    @Slot()
    def force_shutdown(self) -> None:
        """应用退出兜底：清引用并强制停止。"""
        with self._lock:
            self._refs = 0
            if self._httpd is not None:
                self._stop_locked()

    # ---- 内部 ----

    def _start_locked(self) -> None:
        handler = partial(_LockedRootHandler, directory=str(self._root))
        self._httpd = _RootedHTTPServer(("127.0.0.1", 0), handler)
        port = self._httpd.server_address[1]
        self._url = f"http://127.0.0.1:{port}"
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="avatar-runtime-server", daemon=True,
        )
        self._thread.start()
        logger.info("AVATAR 运行时服务器已启动：%s（root=%s，仅回环/仅静态/无目录列表）",
                    self._url, self._root)
        self.urlChanged.emit()

    def _stop_locked(self) -> None:
        httpd, thread = self._httpd, self._thread
        self._httpd, self._thread, self._url = None, None, ""
        try:
            httpd.shutdown()          # 停 serve_forever 循环
            httpd.server_close()
        except Exception:             # noqa: BLE001  关停失败不阻塞 UI
            logger.warning("avatar-runtime-server 关停异常", exc_info=True)
        if thread is not None:
            thread.join(timeout=2)
        logger.info("AVATAR 运行时服务器已停止（引用归零）")
        self.urlChanged.emit()
