# -*- coding: utf-8 -*-
"""微观测量：TextMetrics.width / implicitWidth / QFontMetricsF 在同一字体下的差异。"""
import os, sys, tempfile
CLIENT = "<user-home>/WorkBuddy/Worktrees/小智/p2b2-teacher-voice-f0edf42f/client"
sys.path.insert(0, CLIENT)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication, QFontMetricsF
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow

app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
qml = '''
import QtQuick
import QtQuick.Window
Window {
    width: 800; height: 300; visible: true
    TextMetrics { id: mw; font: tw.font; text: tw.text }
    Text { id: tw; text: "reservation"; font.family: "PingFang SC"; font.pixelSize: 40; font.bold: true }
    Text {
        id: tw2; y: 60; text: "reservation"
        font.family: "PingFang SC"; font.pixelSize: 40; font.bold: true
        wrapMode: Text.WrapAnywhere
        width: 600
    }
    Text {
        id: tw3; y: 140; text: "reservation"
        font.family: "PingFang SC"; font.pixelSize: 40; font.bold: true
        wrapMode: Text.WrapAnywhere
        width: Math.min(implicitWidth, 600)
    }
}
'''
tmp = tempfile.mkdtemp(); p = os.path.join(tmp, "m.qml"); open(p, "w").write(qml)
eng = QQmlApplicationEngine(); eng.load(QUrl.fromLocalFile(p))
app.processEvents()
o = eng.rootObjects()[0]
print("root:", o.metaObject().className())
ci = o.contentItem()
print("contentItem:", ci, "children:", len(ci.childItems()) if ci else None)
for c in (ci.childItems() if ci else []):
    print("  child:", c.metaObject().className())

def walk(it):
    out = [it]
    for c in it.childItems():
        out += walk(c)
    return out

for x in walk(o.contentItem()):
    try:
        if "Text" in x.metaObject().className():
            fm = QFontMetricsF(x.property("font"))
            txt = x.property("text")
            print("text=%-14r width=%.2f implicitW=%.2f h=%.1f QFontMetricsF=%.2f"
                  % (txt, float(x.property("width")), float(x.property("implicitWidth")),
                     float(x.property("height")), fm.horizontalAdvance(txt)))
    except Exception as e:
        print("ERR", e)
tm = None
for x in walk(o.contentItem()):
    try:
        if "TextMetrics" in x.metaObject().className():
            print("TextMetrics width=%.2f" % x.property("width"))
    except Exception:
        pass
