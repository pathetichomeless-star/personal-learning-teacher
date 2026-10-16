#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探针 3：定位 delegate 对象的可达路径（视觉树 vs QObject 树）。"""
import os
import sys

CLIENT = "<project-root>/client"
QML = os.path.join(CLIENT, "src", "classroom", "qml")
OUT = "/tmp/xz-qa-cv1"
os.environ["XIAOZHI_DATA_DIR"] = OUT + "/data"
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
sys.path.insert(0, CLIENT)

from PySide6.QtCore import QObject, QPoint, QPointF, QRectF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickItem  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from src.utils.config_manager import initialize_config  # noqa: E402
initialize_config()
app = QGuiApplication.instance() or QGuiApplication(sys.argv)
from src.classroom.classroom_model import ClassroomModel  # noqa: E402

model = ClassroomModel()
model.refreshTeachers()
engine = QQmlApplicationEngine()
engine.addImportPath(QML)
engine.rootContext().setContextProperty("classroom", model)
engine.load(QUrl.fromLocalFile(os.path.join(QML, "ClassroomWindow.qml")))
win = engine.rootObjects()[0]
win.setProperty("width", 1360)
win.setProperty("height", 808)
win.setProperty("x", 60)
win.setProperty("y", 80)
QTest.qWait(800)


def scene_rect(item):
    tl = item.mapToScene(QPointF(0.0, 0.0))
    br = item.mapToScene(QPointF(float(item.width()), float(item.height())))
    return QRectF(tl, br)


def walk_visual(item, depth=0, maxdepth=99, out=None):
    if out is None:
        out = []
    out.append((depth, item))
    if depth >= maxdepth:
        return out
    for c in item.childItems():
        walk_visual(c, depth + 1, maxdepth, out)
    return out


# 打开老师对话框
for o in win.findChildren(QObject):
    try:
        if isinstance(o, QQuickItem) and "Button" in o.metaObject().className() \
           and o.property("text") == "更换老师" and o.isVisible():
            r = scene_rect(o)
            QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, QPoint(int(r.center().x()), int(r.center().y())))
            break
    except Exception:  # noqa: BLE001
        pass
QTest.qWait(1000)
print("dialog teachers:", len(model.teachers))

# 定位可见的 dialog ListView
lv = None
for o in win.findChildren(QObject):
    try:
        if o.metaObject().className() == "QQuickListView" and o.property("count") == 2 and o.isVisible():
            lv = o
            break
    except Exception:  # noqa: BLE001
        pass
print("ListView found:", lv is not None)
if lv is not None:
    print("ListView scene rect:", scene_rect(lv))
    print("--- QObject children of ListView (recursive) ---")
    for o in lv.findChildren(QObject):
        try:
            t = o.property("text")
            print("   %s text=%r" % (o.metaObject().className(), t))
        except Exception:  # noqa: BLE001
            pass
    print("--- visual tree under ListView (childItems) ---")
    for depth, it in walk_visual(lv):
        try:
            t = it.property("text")
            r = scene_rect(it)
            print("   %s%s text=%r vis=%s rect=(%.0f,%.0f)" %
                  ("  " * depth, it.metaObject().className(), t, it.isVisible(), r.x(), r.y()))
        except Exception:  # noqa: BLE001
            pass

# 视觉树：整个 contentItem 下含『模拟』的 item
print("--- VISUAL tree scan: items whose text contains 模拟/老师 B ---")
for depth, it in walk_visual(win.contentItem()):
    try:
        t = it.property("text")
        if isinstance(t, str) and ("模拟" in t or "小智" in t):
            r = scene_rect(it)
            print("   d=%d %s text=%r vis=%s rect=(%.0f,%.0f,%.0f,%.0f)" %
                  (depth, it.metaObject().className(), t, it.isVisible(), r.x(), r.y(), r.width(), r.height()))
    except Exception:  # noqa: BLE001
        pass

# overlay 视觉树
ov = win.overlay()
print("--- overlay type:", type(ov), "children:", len(ov.childItems()))
for depth, it in walk_visual(ov, maxdepth=6):
    try:
        t = it.property("text")
        if isinstance(t, str) and t.strip():
            r = scene_rect(it)
            print("   ov d=%d %s text=%r vis=%s rect=(%.0f,%.0f)" %
                  (depth, it.metaObject().className(), t, it.isVisible(), r.x(), r.y()))
    except Exception:  # noqa: BLE001
        pass

# 尝试点击「模拟老师 B」：直接从 overlay 视觉树找
target = None
for depth, it in walk_visual(ov):
    try:
        if it.property("text") == "模拟老师 B":
            target = it
    except Exception:  # noqa: BLE001
        pass
print("target from overlay:", target)
if target is not None:
    r = scene_rect(target)
    print("click at (%.0f, %.0f) vis=%s" % (r.center().x(), r.center().y(), target.isVisible()))
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, QPoint(int(r.center().x()), int(r.center().y())))
    QTest.qWait(400)
    print("selectedTeacherId =", model.selectedTeacherId)
