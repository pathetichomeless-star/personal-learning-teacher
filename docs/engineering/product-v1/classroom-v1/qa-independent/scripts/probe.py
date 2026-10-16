#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探针：定位 (1) 对话框内条目为何未出现在遍历结果 (2) 文本坐标点击为何未触发 MouseArea。"""
import json
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
model.loadSelectedTeacher()
model.selectCourse(0)
model.selectLesson(0)
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


def chain(o):
    names = []
    cur = o
    while cur is not None:
        try:
            names.append(cur.metaObject().className())
            if isinstance(cur, QQuickItem):
                cur = cur.parentItem()
            else:
                cur = cur.parent()
        except Exception:  # noqa: BLE001
            break
    return " <- ".join(names[:8])


print("=== A. 打开老师对话框（点击按钮）===")
ok = False
for o in win.findChildren(QObject):
    try:
        if isinstance(o, QQuickItem) and "Button" in o.metaObject().className() \
           and o.property("text") == "更换老师" and o.isVisible():
            r = scene_rect(o)
            QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, QPoint(int(r.center().x()), int(r.center().y())))
            ok = True
            break
    except Exception:  # noqa: BLE001
        pass
print("clicked 更换老师:", ok, " teachers:", len(model.teachers), model.teachersState)
QTest.qWait(900)

print("--- 含『模拟』的对象清单 ---")
for o in win.findChildren(QObject):
    try:
        t = o.property("text")
        if isinstance(t, str) and "模拟" in t:
            extra = ""
            if isinstance(o, QQuickItem):
                r = scene_rect(o)
                extra = " vis=%s rect=(%.0f,%.0f,%.0f,%.0f)" % (o.isVisible(), r.x(), r.y(), r.width(), r.height())
            print("  cls=%s text=%r%s\n     chain: %s" % (o.metaObject().className(), t, extra, chain(o)))
    except Exception as e:  # noqa: BLE001
        print("  ERR", e)

print("--- 含『学科』的对象清单 ---")
for o in win.findChildren(QObject):
    try:
        t = o.property("text")
        if isinstance(t, str) and "学科" in t:
            extra = ""
            if isinstance(o, QQuickItem):
                r = scene_rect(o)
                extra = " vis=%s rect=(%.0f,%.0f,%.0f,%.0f)" % (o.isVisible(), r.x(), r.y(), r.width(), r.height())
            print("  cls=%s text=%r%s chain: %s" % (o.metaObject().className(), t, extra, chain(o)))
    except Exception:  # noqa: BLE001
        pass

img = win.grabWindow()
img.save(OUT + "/shots/probe_teacher_dialog.png")
print("shot probe_teacher_dialog.png")

# 尝试用坐标点击教师行（取『模拟老师 B』文本中心）
target = None
for o in win.findChildren(QObject):
    try:
        if isinstance(o, QQuickItem) and o.property("text") == "模拟老师 B" and o.width() > 0:
            target = o
    except Exception:  # noqa: BLE001
        pass
if target is not None:
    r = scene_rect(target)
    print("click B at (%.0f,%.0f) vis=%s" % (r.center().x(), r.center().y(), target.isVisible()))
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, QPoint(int(r.center().x()), int(r.center().y())))
    QTest.qWait(300)
    print("after click selectedTeacherId =", model.selectedTeacherId)
else:
    print("模拟老师 B item NOT FOUND")

# 找出点击位置上实际命中的 item
def item_at_pt(pt):
    cur = win.contentItem()
    p = QPointF(pt)
    for _ in range(40):
        child = cur.childAt(p.x(), p.y())
        if child is None or child is cur:
            break
        p = cur.mapToItem(child, p)
        cur = child
    return cur

if target is not None:
    r = scene_rect(target)
    hit = item_at_pt(QPointF(r.center().x(), r.center().y()))
    print("item_at center:", hit.metaObject().className(), "| chain:", chain(hit))

# ==== B. 标签点击探针 ====
print("=== B. 点击『词汇』标签 ===")
cands = []
for o in win.findChildren(QObject):
    try:
        if isinstance(o, QQuickItem) and o.property("text") == "词汇" and o.width() > 0:
            cands.append(o)
    except Exception:  # noqa: BLE001
        pass
print("candidates:", len(cands))
for c in cands:
    r = scene_rect(c)
    print("  cls=%s vis=%s rect=(%.0f,%.0f,%.0f,%.0f) chain=%s" %
          (c.metaObject().className(), c.isVisible(), r.x(), r.y(), r.width(), r.height(), chain(c)))
if cands:
    c = cands[-1]
    r = scene_rect(c)
    hit = item_at_pt(QPointF(r.center().x(), r.center().y()))
    print("hit at center:", hit.metaObject().className(), "chain:", chain(hit))
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, QPoint(int(r.center().x()), int(r.center().y())))
    QTest.qWait(300)
    print("after click activeTab =", model.activeTab)

img2 = win.grabWindow()
img2.save(OUT + "/shots/probe_after_clicks.png")
print("done")
