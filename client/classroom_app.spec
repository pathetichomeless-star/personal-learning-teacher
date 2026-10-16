# -*- mode: python ; coding: utf-8 -*-
# 小智 AI 学生课堂 —— 本机 .app 打包（RELEASE FIX 01）
# 说明：本机构建、不签名、不公证（无 Apple 开发者账户依赖）；仅面向本机 Finder 双击体验。
# 构建：cd client && ./.venv/bin/pyinstaller --noconfirm --clean classroom_app.spec

import os  # noqa: F401
import json as _json

block_cipher = None

# 版本与构建信息从 tools/classroom_build_info.py 的产物读取（单一事实源，避免漂移）。
# 构建前必须先运行：  python3 tools/classroom_build_info.py
_BUILD_INFO_PATH = os.path.join("build_info", "classroom_build_info.json")
if not os.path.isfile(_BUILD_INFO_PATH):
    raise SystemExit(
        "缺少 %s：请先在仓库根运行 `python3 tools/classroom_build_info.py` 再打包。"
        % _BUILD_INFO_PATH)
with open(_BUILD_INFO_PATH, "r", encoding="utf-8") as _fh:
    _BUILD_INFO = _json.load(_fh)
APP_VERSION = str(_BUILD_INFO.get("app_version") or "2.0.0")
APP_BUILD = str(_BUILD_INFO.get("app_build") or "2")
print("BUILD_INFO: version=%s build=%s source_revision=%s files=%d"
      % (APP_VERSION, APP_BUILD, _BUILD_INFO.get("source_revision"),
         len(_BUILD_INFO.get("files") or [])))

# 无关 Qt 模块剪裁（课堂仅用 QtCore/QtGui/QtQml/QtQuick/QtQuickControls2）
_QEXCLUDES = [
    "tkinter",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtSerialPort", "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.QtQuick3D", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtSensors", "PySide6.QtSpatialAudio", "PySide6.QtStateMachine",
    "PySide6.QtTextToSpeech", "PySide6.QtUiTools", "PySide6.QtDBus",
    "PySide6.QtOpenGLWidgets", "PySide6.QtNetworkAuth",
]

a = Analysis(
    ["classroom_main.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("src/classroom/qml", "src/classroom/qml"),
        ("src/classroom/data", "src/classroom/data"),
        # 导入期必需：course_schema.py 在 import 时按 __file__ 同级读取该 JSON
        # （单一机器可读事实源）。缺它 → 冻结包启动即 FileNotFoundError。
        ("src/classroom/course_schema.v1.json", "src/classroom"),
        # 源码 ↔ 安装包一致性凭据（交付物 F）：随包分发，可事后逐字节复核
        (_BUILD_INFO_PATH, "."),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_QEXCLUDES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# ---- 收集后剪裁：QtQml 钩子会连带收集全部 QML 插件（含 WebEngine 等大件）。
# 课堂仅用 QtQuick / Controls / Layouts / Dialogs，以下均为未使用件（构建期删除，
# 删除发生在 ad-hoc 签名之前，签名仍有效）。
_PRUNE_TOKENS = (
    "QtWebEngine", "QtWebView", "QtWebChannel", "QtWebSockets",
    "QtPdf", "QtDesigner", "QtQuick3D", "Qt3D", "libavcodec", "Qt5Compat",
)


def _prune(items):
    kept = []
    for it in items:
        try:
            blob = " ".join(str(x) for x in it)
        except Exception:  # noqa: BLE001
            blob = str(it)
        if any(tok in blob for tok in _PRUNE_TOKENS):
            continue
        kept.append(it)
    return kept


_bin_before, _dat_before = len(a.binaries), len(a.datas)
a.binaries = _prune(a.binaries)
a.datas = _prune(a.datas)
print("PRUNE: binaries %d -> %d, datas %d -> %d"
      % (_bin_before, len(a.binaries), _dat_before, len(a.datas)))

# ---- 结构性前置校验：运行期必需资源必须在 datas 中，否则**直接失败**而不是产出坏包。
# （2026-10-12 实测教训：course_schema.v1.json 未加入 datas → 冻结包启动 FileNotFoundError）
_REQUIRED_DATAS = (
    "src/classroom/course_schema.v1.json",      # 导入期 open(SCHEMA_PATH)
    "src/classroom/qml/ClassroomWindow.qml",    # 主窗口
    "src/classroom/qml/NavBar.qml",             # V2 页面
    "src/classroom/data/courses.json",          # 随包本地演示课程
    "classroom_build_info.json",                # 一致性凭据
)
_present = {str(d[0]).replace("\\", "/") for d in a.datas}
_missing = [r for r in _REQUIRED_DATAS if r not in _present]
if _missing:
    raise SystemExit("打包前置校验失败：运行期必需资源缺失 %r（在 datas 中找不到）" % (_missing,))
print("DATAS GUARD OK: %d 项必需资源齐备" % len(_REQUIRED_DATAS))

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="xiaozhi-classroom",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="xiaozhi-classroom",
)

app = BUNDLE(
    coll,
    name="小智 AI 学生课堂.app",
    icon=None,
    bundle_identifier="local.xiaozhi.classroom-demo",
    version=APP_VERSION,
    info_plist={
        "CFBundleDisplayName": "小智 AI 学生课堂",
        "CFBundleName": "小智 AI 学生课堂",
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_BUILD,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
        "NSRequiresAquaSystemAppearance": False,
    },
)
