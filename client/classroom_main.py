#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""XIAOZHI V4 学生课堂 —— 独立入口（RELEASE FIX 01）。

用法（开发）：
    client/.venv/bin/python client/classroom_main.py --size wide
    --size ∈ wide | medium | compact | narrow | fullscreen
    --geom-file <path>   将窗口几何写入 JSON（供外部截图/自动化）

用法（普通用户）：
    双击「小智 AI 学生课堂.app」（Finder；无终端窗口）。

隔离与 fail-closed（所有启动路径一致）：
* 数据目录 = XIAOZHI_CLASSROOM_DIR > XIAOZHI_DATA_DIR（需通过校验）> 默认独立演示目录
  （~/Library/Application Support/xiaozhi-classroom-demo）；解析失败或指向正式
  py-xiaozhi 数据目录时**拒绝启动**并给出图形化说明；
* 本入口不读取正式配置/密钥；唯一的网络面是「本机 Mock 老师列表」，
  且需隔离配置显式开启 + 环回地址 + 部署令牌（缺一不联网）；
* 本入口不建立任何 WebSocket / 语音连接；
* 启动失败时给出图形化错误说明（可用 XIAOZHI_CLASSROOM_NO_DIALOG=1 让它改为
  输出到标准输出，专供自动化测试）。
"""
import argparse
import os
import sys

_BASE = os.path.dirname(os.path.abspath(__file__))


def _resource_base() -> str:
    """资源根目录：源码运行 = 本文件目录；打包运行 = PyInstaller 解包目录。"""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    return _BASE


_BASE = _resource_base()
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
os.environ.setdefault("QT_API", "pyside6")

QML_DIR = os.path.join(_BASE, "src", "classroom", "qml")
WINDOW_QML = os.path.join(QML_DIR, "ClassroomWindow.qml")

SIZES = {
    "wide": (1360, 850, False),
    "medium": (1000, 740, False),
    "compact": (860, 700, False),
    "narrow": (620, 620, False),
    "fullscreen": (1360, 850, True),
}


def _error_log_path() -> str:
    """错误日志路径：优先课堂数据目录；不可用时退回 ~/Library/Logs。"""
    try:
        from src.classroom import classroom_env as cenv

        d, _err = cenv.resolve_classroom_dir()
        if d is not None:
            logs = d / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            return str(logs / "startup_error.log")
    except Exception:  # noqa: BLE001
        pass
    fallback = os.path.expanduser("~/Library/Logs/xiaozhi-classroom-demo-startup.log")
    try:
        os.makedirs(os.path.dirname(fallback), exist_ok=True)
    except OSError:
        pass
    return fallback


def _append_error_log(title: str, detail: str) -> str:
    path = _error_log_path()
    try:
        import time

        with open(path, "a", encoding="utf-8") as fh:
            fh.write("[%s] %s\n%s\n\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), title, detail))
    except Exception:  # noqa: BLE001
        pass
    return path


def show_startup_error(title: str, detail: str) -> None:
    """图形化错误说明；无法弹窗时写日志 + 标准输出（绝不静默失败）。"""
    log = _append_error_log(title, detail)
    if os.environ.get("XIAOZHI_CLASSROOM_NO_DIALOG") == "1":
        print("CLASSROOM_STARTUP_ERROR | %s | %s | log=%s"
              % (title, detail.replace("\n", " "), log), flush=True)
        return
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv[:1])
        box = QMessageBox()
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle("小智 AI 学生课堂 — 启动失败")
        box.setText(title)
        box.setInformativeText("%s\n\n错误日志：%s" % (detail, log))
        box.exec()
    except Exception:  # noqa: BLE001
        print("CLASSROOM_STARTUP_ERROR | %s | %s | log=%s"
              % (title, detail.replace("\n", " "), log), flush=True)


def _run(args) -> int:
    # 1) fail-closed：先解析并校验隔离目录，未通过则拒绝启动（不读任何配置）
    from src.classroom import classroom_env as cenv

    data_dir, err_or_source = cenv.resolve_classroom_dir()
    if data_dir is None:
        show_startup_error("隔离校验未通过，已拒绝启动（fail-closed）", str(err_or_source))
        return 3
    # 结构性隔离：本进程后续任何路径解析都只看到课堂演示目录
    os.environ["XIAOZHI_CLASSROOM_DIR"] = str(data_dir)
    os.environ["XIAOZHI_DATA_DIR"] = str(data_dir)
    print("CLASSROOM_ISOLATION dir=%s" % data_dir, flush=True)

    # R2-2：运行期事件日志（启动/退出请求/窗口关闭/可捕获未处理异常）。
    # 只记事件与时间：不记录学生对话、教材正文、密钥或 Token；600 权限+轮转+保留期；
    # 不重定向 stdout/stderr 全量；原生段崩溃与系统终止不在捕获范围（诚实口径）。
    from src.classroom import runtime_log

    log_path = runtime_log.init(data_dir)
    runtime_log.install_excepthook()
    # 版本描述：从构建信息读取（与 APP_BUILD 单一事实源同步，不再写死；
    # 源码运行读 client/build_info/，打包运行读包内资源；不可读时如实降级）。
    _ver_desc = "版本信息不可读"
    try:
        import json as _json_mod
        for _rel in ("classroom_build_info.json",
                     os.path.join("build_info", "classroom_build_info.json")):
            try:
                with open(os.path.join(_resource_base(), _rel), encoding="utf-8") as _fh:
                    _bi = _json_mod.load(_fh)
            except (OSError, ValueError):
                continue
            _ver_desc = "v%s build%s" % (_bi.get("app_version", "?"),
                                         _bi.get("app_build", "?"))
            break
    except Exception:  # noqa: BLE001
        pass
    runtime_log.log_event("app_start", "classroom %s log=%s" % (_ver_desc, log_path))

    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine

    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    app.aboutToQuit.connect(lambda: runtime_log.log_event("app_exit", "event_loop_returned"))

    from src.classroom.classroom_model import ClassroomModel

    model = ClassroomModel()
    model.loadSelectedTeacher()
    # HUMAN_GUI_ACCEPTANCE_FIX01 · P2-1：启动停在「我的书库」，不再自动打开演示课；
    # 学习位置由「继续上次学习」/打开课程时恢复（P1-1）。
    model.setPage(model.pageLibrary)
    model.refreshTeachers()
    if model.teachers:
        model.selectTeacher(model.teachers[0].get("teacher_id", ""))

    engine = QQmlApplicationEngine()
    # BUILD4-EXIT-FIX-01：连接 QML 引擎退出信号到应用退出（Qt 官方 main 模板做法）。
    # 背景：QQmlEngine.quit() 信号默认无接收者，QML 内 Qt.quit() 会静默失效
    # （libQt6Qml 仅打印 "no receivers connected" 警告，windowed 打包下不可见）。
    # 当前 QML 退出走 win.close() 窗口链；本连接为防御性保障——未来任何 Qt.quit()
    # 调用都将真实生效。
    engine.quit.connect(app.quit)
    engine.addImportPath(QML_DIR)
    engine.rootContext().setContextProperty("classroom", model)
    engine.load(QUrl.fromLocalFile(WINDOW_QML))

    roots = engine.rootObjects()
    if not roots:
        show_startup_error(
            "界面资源缺失或损坏",
            "课堂界面（QML）未能加载：%s\n请确认应用完整，或联系维护者重新安装。" % WINDOW_QML)
        return 2

    win = roots[0]

    w, h, fs = SIZES[args.size]
    win.setProperty("width", w)
    win.setProperty("height", h)
    if fs:
        win.setProperty("fullscreen", True)
    else:
        # 固定位置，便于外部按确定性区域做实机截图
        win.setProperty("x", 60)
        win.setProperty("y", 80)

    if args.geom_file:
        import json as _json

        def write_geom():
            try:
                g = {
                    "x": int(win.property("x")), "y": int(win.property("y")),
                    "w": int(win.property("width")), "h": int(win.property("height")),
                    "mode": str(win.property("classroomWindowMode")),
                    "fullscreen": bool(fs),
                }
                with open(args.geom_file, "w", encoding="utf-8") as fh:
                    _json.dump(g, fh)
                print("GEOM_READY %s" % _json.dumps(g), flush=True)
            except Exception as e:  # noqa: BLE001
                print("GEOM_ERROR %r" % (e,), flush=True)

        QTimer.singleShot(1200, write_geom)
    else:
        print("CLASSROOM_READY size=%s width=%d height=%d" % (args.size, w, h), flush=True)
    return app.exec()


def main() -> int:
    ap = argparse.ArgumentParser(description="小智 AI 学生课堂")
    ap.add_argument("--size", choices=sorted(SIZES.keys()), default="wide")
    ap.add_argument("--geom-file", default="",
                    help="把窗口几何写入该 JSON（供外部 screencapture -R 实机截图）")
    args = ap.parse_args()

    try:
        return _run(args)
    except Exception as e:  # noqa: BLE001 —— 任何未预期异常都给出图形化说明
        import traceback

        try:
            from src.classroom import runtime_log as _rlog
            _rlog.log_event("startup_failed",
                            "type=%s msg=%r" % (type(e).__name__, str(e)[:200]))
        except Exception:  # noqa: BLE001
            pass
        show_startup_error("课堂未能启动", "%s: %s\n\n%s"
                           % (type(e).__name__, e, traceback.format_exc()[-800:]))
        return 3


if __name__ == "__main__":
    sys.exit(main())
