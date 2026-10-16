#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探针 2：彻底转储 InteractionPanel 与老师对话框子树。"""
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


# ---- 1. 所有 QQuickText 清单（不过滤） ----
all_objs = list(win.findChildren(QObject))
print("total QObjects under win:", len(all_objs))
texts = [(o, o.property("text")) for o in all_objs
         if o.metaObject().className() in ("QQuickText",)]
print("QQuickText count:", len(texts))
for o, t in texts:
    try:
        r = scene_rect(o)
        print("  TEXT %r vis=%s rect=(%.0f,%.0f,%.0f,%.0f)" % (t, o.isVisible(), r.x(), r.y(), r.width(), r.height()))
    except Exception as e:  # noqa: BLE001
        print("  TEXT %r ERR %r" % (t, e))

# ---- 2. Repeater / InteractionPanel 结构 ----
print("--- classes histogram ---")
from collections import Counter  # noqa: E402
c = Counter(o.metaObject().className() for o in all_objs)
for k, v in c.most_common(30):
    print("  %4d %s" % (v, k))

# ---- 3. 打开老师对话框，转储弹层子树 ----
for o in all_objs:
    try:
        if isinstance(o, QQuickItem) and "Button" in o.metaObject().className() \
           and o.property("text") == "更换老师" and o.isVisible():
            r = scene_rect(o)
            QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, QPoint(int(r.center().x()), int(r.center().y())))
            break
    except Exception:  # noqa: BLE001
        pass
QTest.qWait(1000)
print("--- after dialog open: teachers=", len(model.teachers), model.teachersState)
for o in list(win.findChildren(QObject)):
    try:
        cn = o.metaObject().className()
        if "ListView" in cn or "PopupItem" in cn or "Dialog" in cn:
            extra = ""
            if isinstance(o, QQuickItem):
                r = scene_rect(o)
                extra = " vis=%s rect=(%.0f,%.0f,%.0f,%.0f) w=%.0f h=%.0f" % (
                    o.isVisible(), r.x(), r.y(), r.width(), r.height(), o.width(), o.height())
            cnt = o.property("count")
            print("  %s count=%r%s" % (cn, cnt, extra))
    except Exception:  # noqa: BLE001
        pass
# dialog 内 Text 全量
print("--- after dialog open: all QQuickText with y>100 ---")
for o, t in [(o, o.property("text")) for o in win.findChildren(QObject)
             if o.metaObject().className() == "QQuickText"]:
    try:
        r = scene_rect(o)
        if r.y() > 90 and r.y() < 700 and isinstance(t, str) and t.strip():
            print("  %r vis=%s rect=(%.0f,%.0f,%.0f,%.0f)" % (t, o.isVisible(), r.x(), r.y(), r.width(), r.height()))
    except Exception:  # noqa: BLE001
        pass
img = win.grabWindow()
img.save(OUT + "/shots/probe2_dialog.png")
print("saved probe2_dialog.png")
