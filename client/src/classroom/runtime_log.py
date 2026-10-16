#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行期事件日志（CLASSROOM-V2-ROUND02-FIX · R2-2 · 退出可观测性）。

目的与诚实边界：
* 只记录「必要事件、时间、异常类型与技术状态」：应用启动、退出请求、
  窗口关闭事件、可捕获的未处理异常（Python 层）；
* **不记录**学生对话内容、教材正文、API 密钥或任何 Token；
* **不重定向、不持久化** stdout/stderr 全量输出（避免学生输入进入日志）；
* 原生段崩溃（SIGSEGV 等）与系统级终止无法由 Python 层捕获——本日志
  **不承诺**覆盖该类事件；
* 文件权限 600；单文件超限轮转（保留最近 2 份历史）；历史件超保留期删除。

事件行格式：`<时间> | <事件> | <技术性摘要(截断)>`
"""
import os
import threading
import time
from pathlib import Path

_MAX_BYTES = 256 * 1024      # 单文件上限（256KB）
_KEEP_ROTATED = 2            # 保留轮转历史份数
_KEEP_DAYS = 14              # 历史件保留天数
_lock = threading.Lock()
_path = None                 # type: Path | None


def init(data_dir) -> str:
    """初始化日志目录并做保留期清理；返回日志文件路径（失败返回空串，不影响启动）。"""
    global _path
    try:
        logs = Path(data_dir) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        os.chmod(logs, 0o700)
        _path = logs / "runtime.log"
        if not _path.exists():
            _path.touch(mode=0o600)
        os.chmod(_path, 0o600)
        _cleanup_history(logs)
        log_event("log_init", "runtime_log ready")
    except Exception:  # noqa: BLE001 —— 日志初始化失败绝不影响应用启动
        _path = None
    return str(_path) if _path is not None else ""


def log_event(event: str, detail: str = "") -> None:
    """追加一条事件；任何失败静默吞掉（日志绝不影响课堂功能）。"""
    if _path is None:
        return
    try:
        with _lock:
            if _path.exists() and _path.stat().st_size > _MAX_BYTES:
                _rotate()
            line = "%s | %s | %s\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), event, (detail or "")[:300])
            with open(_path, "a", encoding="utf-8") as fh:
                fh.write(line)
            os.chmod(_path, 0o600)
    except Exception:  # noqa: BLE001
        pass


def _rotate() -> None:
    try:
        for i in range(_KEEP_ROTATED, 0, -1):
            src = _path.with_name(_path.name + ".%d" % i)
            if i == _KEEP_ROTATED and src.exists():
                src.unlink()
            elif src.exists():
                src.rename(_path.with_name(_path.name + ".%d" % (i + 1)))
        if _path.exists():
            _path.rename(_path.with_name(_path.name + ".1"))
        _path.touch(mode=0o600)
    except Exception:  # noqa: BLE001
        pass


def _cleanup_history(logs: Path) -> None:
    cutoff = time.time() - _KEEP_DAYS * 86400
    try:
        for f in logs.glob("runtime.log.*"):
            if f.stat().st_mtime < cutoff:
                f.unlink()
    except Exception:  # noqa: BLE001
        pass


def install_excepthook() -> None:
    """捕获 Python 层未处理异常：只记异常类型、消息前缀与 traceback 位置摘要。"""

    def _hook(exc_type, exc, tb):
        try:
            frames = []
            t = tb
            while t is not None and len(frames) < 3:
                frames.append("%s:%s" % (
                    os.path.basename(t.tb_frame.f_code.co_filename), t.tb_lineno))
                t = t.tb_next
            log_event("uncaught_exception",
                      "type=%s msg=%r at=%s"
                      % (exc_type.__name__, str(exc)[:200], "<".join(frames)))
        except Exception:  # noqa: BLE001
            pass
        import sys
        try:
            sys.__excepthook__(exc_type, exc, tb)
        except Exception:  # noqa: BLE001
            pass

    import sys
    sys.excepthook = _hook

    def _thread_hook(args):
        try:
            log_event("thread_uncaught_exception",
                      "type=%s msg=%r" % (args.exc_type.__name__, str(args.exc)[:200]))
        except Exception:  # noqa: BLE001
            pass
        try:
            import sys as _sys
            _sys.__excepthook__(args.exc_type, args.exc, args.exc_traceback)
        except Exception:  # noqa: BLE001
            pass

    threading.excepthook = _thread_hook
