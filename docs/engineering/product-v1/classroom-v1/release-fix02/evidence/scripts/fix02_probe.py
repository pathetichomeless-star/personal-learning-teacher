# -*- coding: utf-8 -*-
"""FIX-02 验证探针：单词 + IPA 音标在窄窗的完整可读性（真实 cocoa 渲染）。
覆盖 560/620/640/860/1000/1360 + 全屏；含长单词/长音标合成样例、中文释义、英文例句、
上一页/下一页、纵向滚动。不修改产品课件数据（合成样例仅存在于 /tmp 临时课程文件）。
"""
import json
import os
import sys
import tempfile

CLIENT = "<user-home>/WorkBuddy/Worktrees/小智/p2b2-teacher-voice-f0edf42f/client"
if CLIENT not in sys.path:
    sys.path.insert(0, CLIENT)
SHOTS = "/tmp/xz-qa-fix02/shots"
LOGS = "/tmp/xz-qa-fix02/logs"
os.makedirs(SHOTS, exist_ok=True)
os.makedirs(LOGS, exist_ok=True)

data = tempfile.mkdtemp(prefix="qa-fix02-")
os.environ["XIAOZHI_CLASSROOM_DIR"] = data
os.environ["XIAOZHI_DATA_DIR"] = data
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
os.environ.setdefault("QT_API", "pyside6")

from PySide6.QtCore import QPointF, QRectF, Qt, QUrl
from PySide6.QtGui import QFontMetricsF, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from src.classroom.classroom_model import ClassroomModel

RESULTS = []
EV = {"cases": {}, "checks": []}


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    EV["checks"].append({"name": name, "ok": bool(cond), "detail": str(detail)[:400]})
    print("F2RESULT %s %s | %s" % ("PASS" if bool(cond) else "FAIL", name, str(detail)[:230]), flush=True)


# ---------------- 合成“更长单词 + 音标”样例（不写产品课件） ----------------
LONG_CASES = [
    {"word": "internationalization", "phonetic": "/ˌɪntəˌnæʃnələˈzeɪʃn/",
     "meaning": "国际化", "en": "Internationalization is a long word.",
     "cn": "国际化是一个很长的单词。"},
    {"word": "photosynthesis", "phonetic": "/ˌfəʊtəʊˈsɪnθəsɪs/",
     "meaning": "光合作用", "en": "Plants use photosynthesis.", "cn": "植物进行光合作用。"},
    {"word": "congratulations", "phonetic": "/kənˌɡrætʃuˈleɪʃnz/",
     "meaning": "恭喜", "en": "Congratulations on your success!", "cn": "祝贺你成功！"},
]
tmp_courses = os.path.join(data, "synthetic_courses.json")
with open(tmp_courses, "w", encoding="utf-8") as fh:
    json.dump({"version": 1, "source": "local-demo", "label": "QA 合成课程（非产品数据）",
               "notice": "合成测试样例，不进入产品课件。",
               "courses": [{"id": "c_syn", "title": "QA 长词测试", "subject": "english", "level": "测试",
                            "description": "仅用于窄窗渲染验证",
                            "lessons": [{"id": "l_syn", "title": "长单词与长音标",
                                         "slides": [{"type": "cover", "title": "长词测试", "subtitle": "long",
                                                     "points": ["a", "b"]}] +
                                                    [{"type": "vocab", "word": c["word"],
                                                      "phonetic": c["phonetic"], "meaning": c["meaning"],
                                                      "en": c["en"], "cn": c["cn"]} for c in LONG_CASES]}]}]},
              fh, ensure_ascii=False)

app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
QML = os.path.join(CLIENT, "src", "classroom", "qml")


def build_model(courses_path=None):
    m = ClassroomModel(courses_path=courses_path) if courses_path else ClassroomModel()
    m.selectCourse(0); m.selectLesson(0)
    return m


def walk(win):
    out = []
    def rec(it):
        out.append(it)
        for c in it.childItems():
            rec(c)
    rec(win.contentItem())
    return out


def srect(it):
    tl = it.mapToScene(QPointF(0, 0))
    br = it.mapToScene(QPointF(float(it.width()), float(it.height())))
    return QRectF(tl, br)


def find_text_exact(win, s):
    for o in walk(win):
        try:
            if o.property("text") == s and o.width() > 0 and o.isVisible():
                return o
        except Exception:
            pass
    return None


def viewport_rect(win):
    best = None
    for o in walk(win):
        try:
            cn = o.metaObject().className()
            if ("ScrollView" in cn or "QQuickFlickable" in cn) and o.isVisible() and o.width() > 0:
                r = srect(o)
                if best is None or r.width() * r.height() > best.width() * best.height():
                    best = r
        except Exception:
            pass
    return best


def flickable(win):
    best = None
    for o in walk(win):
        try:
            if "QQuickFlickable" in o.metaObject().className() and o.isVisible() and o.width() > 0:
                return o
        except Exception:
            pass
    return best


def goto_vocab(m, idx=0):
    m.selectLesson(0)
    seen = 0
    for _ in range(m.slideCount):
        if m.currentSlide.get("type") == "vocab":
            if seen == idx:
                return True
            seen += 1
        m.nextSlide()
    return False


def measure_case(win, m, tag):
    """在当前 vocab 页测量 word 与 ipa 的几何与裁剪。"""
    w = str(m.currentSlide.get("word") or "")
    p = str(m.currentSlide.get("phonetic") or "")
    vp = viewport_rect(win)
    res = {"tag": tag, "win": [win.property("width"), win.property("height")],
           "viewport_right": round(vp.x() + vp.width(), 1) if vp else None,
           "viewport_w": round(vp.width(), 1) if vp else None,
           "word": w, "phonetic": p}
    for label, s in (("word", w), ("ipa", p)):
        it = find_text_exact(win, s)
        if it is None:
            res[label] = None
            continue
        fm = QFontMetricsF(it.property("font"))
        natural = fm.horizontalAdvance(s)
        r = srect(it)
        res[label] = {
            "text": it.property("text"),
            "natural_w": round(natural, 1),
            "item_w": round(r.width(), 1),
            "item_h": round(r.height(), 1),
            "x": round(r.x(), 1),
            "right": round(r.x() + r.width(), 1),
            "wrapped": r.height() > fm.height() * 1.5,
            "within_viewport": (vp is not None) and (r.x() + r.width() <= vp.x() + vp.width() + 1.0),
            "overhang_px": round((r.x() + r.width()) - (vp.x() + vp.width()), 1) if vp else None,
            "text_preserved": it.property("text") == s,
        }
    return res


def run_suite(win, m, tag_prefix, widths):
    for W, H, fs in widths:
        if fs:
            win.setProperty("fullscreen", True)
            QTest.qWait(1200)
            wsel = "fullscreen"
        else:
            win.setProperty("fullscreen", False)
            win.setProperty("width", W); win.setProperty("height", H); QTest.qWait(600)
            wsel = str(W)
        goto_vocab(m, 0)
        QTest.qWait(400)
        res = measure_case(win, m, "%s_%s" % (tag_prefix, wsel))
        EV["cases"]["%s_%s" % (tag_prefix, wsel)] = res
        for label in ("word", "ipa"):
            d = res.get(label)
            if not d:
                check("%s %s 文本可定位" % (wsel, label), False, res)
                continue
            check("%s %s 文本完整未篡改" % (wsel, label), d["text_preserved"], d["text"])
            check("%s %s 不越出课件视口（无裁剪）" % (wsel, label), d["within_viewport"],
                  {"right": d["right"], "vp_right": res["viewport_right"], "overhang": d["overhang_px"]})
        # 音标尾部闭合斜杠
        ipa = res.get("ipa")
        check("%s IPA 结尾为闭合斜杠" % wsel, bool(ipa) and ipa["text"].strip().endswith("/"),
              ipa["text"] if ipa else None)


def main():
    win = None
    engine = QQmlApplicationEngine()
    engine.addImportPath(QML)
    model = build_model()
    engine.rootContext().setContextProperty("classroom", model)
    engine.load(QUrl.fromLocalFile(os.path.join(QML, "ClassroomWindow.qml")))
    roots = engine.rootObjects()
    if not roots:
        check("窗口加载", False)
        return 2
    win = roots[0]
    win.setProperty("x", 40); win.setProperty("y", 50)
    QTest.qWait(700)

    widths = [(560, 500, False), (620, 620, False), (640, 600, False),
              (860, 700, False), (1000, 740, False), (1360, 850, False), (0, 0, True)]

    # ---- A. 正式课件：reservation + /ˌrezəˈveɪʃn/ ----
    run_suite(win, model, "prod", widths)

    # ---- B. 合成长单词 / 长音标样例（每个宽度 × 3 例） ----
    model2 = build_model(tmp_courses)
    engine.rootContext().setContextProperty("classroom", model2)
    QTest.qWait(300)
    for W, H, fs in widths:
        if fs:
            win.setProperty("fullscreen", True); QTest.qWait(1000); wsel = "fullscreen"
        else:
            win.setProperty("fullscreen", False)
            win.setProperty("width", W); win.setProperty("height", H); QTest.qWait(500)
            wsel = str(W)
        for i, c in enumerate(LONG_CASES):
            goto_vocab(model2, i); QTest.qWait(350)
            res = measure_case(win, model2, "long%s_%s" % (i, wsel))
            EV["cases"]["long%s_%s" % (i, wsel)] = res
            ipa = res.get("ipa"); wd = res.get("word")
            check("长例%d@%s word 不裁剪" % (i, wsel), bool(wd) and wd["within_viewport"], wd)
            check("长例%d@%s IPA 完整（含闭合斜杠、不裁剪）" % (i, wsel),
                  bool(ipa) and ipa["within_viewport"] and ipa["text"].endswith("/"),
                  {"text": ipa["text"] if ipa else None, "overhang": ipa["overhang_px"] if ipa else None})
        win.grabWindow().save(os.path.join(SHOTS, "fix02_long_%s.png" % wsel))

    # ---- C. 释义 / 例句 / 翻页 / 纵向滚动（在 620 与 1360 各测） ----
    engine.rootContext().setContextProperty("classroom", model)
    model.selectCourse(0); model.selectLesson(0)
    for W, H in ((620, 620), (1360, 850)):
        win.setProperty("fullscreen", False)
        win.setProperty("width", W); win.setProperty("height", H); QTest.qWait(600)
        goto_vocab(model, 0); QTest.qWait(400)
        texts = []
        for o in walk(win):
            try:
                t = o.property("text")
                if isinstance(t, str) and t.strip():
                    texts.append(t)
            except Exception:
                pass
        check("%s 中文释义在位" % W, any("释义：预订" in t for t in texts), [t for t in texts if "释义" in t][:1])
        check("%s 英文例句在位" % W,
              any("I have a reservation under the name Li." in t for t in texts),
              [t for t in texts if "reservation under" in t][:1])
        # 翻页
        model.selectLesson(0)
        QTest.qWait(200)
        i0 = model.slideIndex
        model.nextSlide(); QTest.qWait(250)
        ok_next = model.slideIndex == i0 + 1
        model.prevSlide(); QTest.qWait(250)
        ok_prev = model.slideIndex == i0
        check("%s 下一页/上一页可用" % W, ok_next and ok_prev, (ok_next, ok_prev))
        # 纵向滚动
        model.selectLesson(0)
        goto_vocab(model, 0); QTest.qWait(300)
        fl = flickable(win)
        can = False
        fits = False
        info = None
        if fl is not None:
            ch = float(fl.property("contentHeight") or 0)
            hh = float(fl.property("height") or 0)
            info = {"contentHeight": ch, "height": hh}
            if ch > hh + 1:
                try:
                    fl.setProperty("contentY", min(60.0, ch - hh))
                    QTest.qWait(150)
                    can = float(fl.property("contentY") or 0) > 0
                except Exception:
                    can = False
            else:
                fits = True  # 内容未溢出，无需滚动即为正确
        check("%s 课件纵向滚动可用（溢出时可滚动；未溢出则无需）" % W, can or fits, info)

    # ---- D. 宽屏排版未破坏 ----
    win.setProperty("width", 1360); win.setProperty("height", 850)
    model.selectCourse(0); model.selectLesson(0); goto_vocab(model, 0)
    QTest.qWait(500)
    vr = measure_case(win, model, "wide_final")
    EV["cases"]["wide_final"] = vr
    same_line = (vr["word"] and vr["ipa"] and abs(vr["word"]["x"] - vr["ipa"]["x"]) > 1
                 and abs(vr["word"]["item_h"] - vr["ipa"]["item_h"]) < 6)
    check("1360 单词与音标同行（宽屏排版保持）", bool(same_line),
          {"word": vr["word"], "ipa": vr["ipa"]})
    win.grabWindow().save(os.path.join(SHOTS, "fix02_wide_1360.png"))
    win.setProperty("width", 620); QTest.qWait(500)
    goto_vocab(model, 0); QTest.qWait(400)
    win.grabWindow().save(os.path.join(SHOTS, "fix02_narrow_620.png"))

    win.close(); QTest.qWait(150)
    with open(os.path.join(LOGS, "fix02_evidence.json"), "w", encoding="utf-8") as fh:
        json.dump(EV, fh, ensure_ascii=False, indent=1)
    total = len(RESULTS); passed = sum(1 for _n, o, _d in RESULTS if o)
    print("FIX02_PROBE: %d checks, %d PASS, %d FAIL" % (total, passed, total - passed), flush=True)
    for n, o, d in RESULTS:
        if not o:
            print("  FAILED: %s  %r" % (n, d), flush=True)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
