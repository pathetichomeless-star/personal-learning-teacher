# -*- coding: utf-8 -*-
"""RELEASE-FIX-01 真实窗口布局探针（四档 + 全屏；几何越界 / 点击可达 / 输入可用 / 截图）。

真实屏幕窗口 + 真实鼠标（QTest）/键盘（QKeyEvent）事件；产品 QML/Model 原样加载。
遍历使用**视觉树**（ListView/Repeater 委托项不经 QObject 树可达——QA 轮结论）。

运行（需要真实显示环境，不能 offscreen）：
    cd client && PYTHONPATH= ./.venv/bin/python src/classroom/tests/ui_layout_probe.py

输出：UIRESULT 行 + 几何 JSON + 截图（默认写入 docs/.../classroom-v1/release-fix01/）。
本探针为**开发自验**工具，不构成独立 QA。
"""
import argparse
import http.server
import json
import os
import socketserver
import sys
import tempfile
import threading

CLIENT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
REPO = os.path.dirname(CLIENT)
if CLIENT not in sys.path:
    sys.path.insert(0, CLIENT)

DEFAULT_OUT = os.path.join(REPO, "docs", "engineering", "product-v1", "classroom-v1",
                           "release-fix01")
MOCK_TOKEN = "tok-ui-probe"

RESULTS = []
MOCK = {"hits": 0}


class _Mock(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/xiaozhi/v1/teacher/list"):
            MOCK["hits"] += 1
            if self.headers.get("X-Teacher-Token", "") != MOCK_TOKEN:
                self.send_response(401)
                self.end_headers()
                return
            body = json.dumps({"teachers": [
                {"teacher_id": "t_a", "display_name": "模拟老师甲", "voice_id": "Cherry", "language": "en"},
                {"teacher_id": "t_b", "display_name": "模拟老师乙"},
            ]}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *a):
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=DEFAULT_OUT)
    args = ap.parse_args()
    shots_dir = os.path.join(args.outdir, "screenshots")
    logs_dir = os.path.join(args.outdir, "test-results")
    os.makedirs(shots_dir, exist_ok=True)
    os.makedirs(logs_dir, exist_ok=True)

    srv = socketserver.TCPServer(("127.0.0.1", 0), _Mock)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    data_dir = tempfile.mkdtemp(prefix="cls-fix01-ui-")
    demo_cfg = os.path.join(data_dir, "classroom_demo.json")
    with open(demo_cfg, "w", encoding="utf-8") as fh:
        json.dump({"allow_teacher_list": True,
                   "teacher_list_url": "http://127.0.0.1:%d/xiaozhi/v1/teacher/list" % port,
                   "teacher_token": MOCK_TOKEN,
                   "selected_teacher_id": ""}, fh)

    os.environ["XIAOZHI_CLASSROOM_DIR"] = data_dir
    os.environ["XIAOZHI_DATA_DIR"] = data_dir
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    os.environ.setdefault("QT_API", "pyside6")

    from PySide6.QtCore import QCoreApplication, QObject, QPoint, QPointF, QRectF, Qt, QUrl
    from PySide6.QtGui import QGuiApplication, QKeyEvent
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest

    from src.classroom.classroom_model import ClassroomModel

    EV = {"sizes": {}, "checks": []}

    def check(name, cond, detail=""):
        ok = bool(cond)
        RESULTS.append((name, ok, detail))
        EV["checks"].append({"name": name, "ok": ok, "detail": str(detail)[:300]})
        print("UIRESULT %s %s %s" % ("PASS" if ok else "FAIL", name, str(detail)[:180]), flush=True)

    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])

    QML = os.path.join(CLIENT, "src", "classroom", "qml")
    # 隔离说明：data_dir 由上方 XIAOZHI_CLASSROOM_DIR 环境变量指向本进程独占的
    # tempfile 目录（含自建环回 Mock 老师服务配置），不得再传 data_dir 覆盖。
    # FIX01-P1-1 后新增 _fresh_course0()：每档宽度开始前清除已保存的学习位置，
    # 避免「位置恢复」把断言预期页推到上次保存页（恢复功能本身工作正常）。
    model = ClassroomModel()
    model.loadSelectedTeacher()

    def _fresh_course0():
        ps = model._position_store()
        if ps is not None:
            for it in model.libraryItems:
                ps.clear_course(str(it.get("course_id") or ""))
        model.selectCourse(0)
        model.selectLesson(0)

    _fresh_course0()
    model.setPage("classroom")  # FIX01-P2-1 默认页改为书库后，布局探针显式进课堂页
    model.refreshTeachers()
    if model.teachers:
        model.selectTeacher(model.teachers[0].get("teacher_id", ""))

    engine = QQmlApplicationEngine()
    engine.addImportPath(QML)
    engine.rootContext().setContextProperty("classroom", model)
    engine.load(QUrl.fromLocalFile(os.path.join(QML, "ClassroomWindow.qml")))
    roots = engine.rootObjects()
    if not roots:
        check("ui_window_load", False, "QML 未加载")
        return 2
    win = roots[0]
    win.setProperty("x", 40)
    win.setProperty("y", 60)
    QTest.qWait(900)

    # ---------------- 视觉树工具 ----------------
    def walk():
        out = []

        def rec(it):
            out.append(it)
            for c in it.childItems():
                rec(c)
        rec(win.contentItem())
        return out

    def scene_rect(item):
        tl = item.mapToScene(QPointF(0.0, 0.0))
        br = item.mapToScene(QPointF(float(item.width()), float(item.height())))
        return QRectF(tl, br)

    def in_popup(item):
        cur = item.parentItem()
        while cur is not None:
            if "PopupItem" in cur.metaObject().className():
                return True
            cur = cur.parentItem()
        return False

    def visible_texts():
        out = []
        for o in walk():
            try:
                if not o.isVisible() or o.width() <= 0 or o.height() <= 0:
                    continue
                t = o.property("text")
                if isinstance(t, str) and t.strip():
                    out.append(t)
            except Exception:  # noqa: BLE001
                pass
        return out

    def find_text_items(target, want_popup=None):
        res = []
        for o in walk():
            try:
                if o.width() <= 0 or o.height() <= 0 or not o.isVisible():
                    continue
                if o.property("text") == target:
                    res.append(o)
            except Exception:  # noqa: BLE001
                pass
        if want_popup is None:
            return res
        pop = [o for o in res if in_popup(o)]
        nop = [o for o in res if not in_popup(o)]
        return (pop or nop) if want_popup else (nop or pop)

    def real_click(item):
        r = scene_rect(item)
        QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier,
                         QPoint(int(r.center().x()), int(r.center().y())))
        app.processEvents()

    def click_text(target, want_popup=None):
        cands = find_text_items(target, want_popup)
        if not cands:
            return False
        cands.sort(key=lambda o: 0 if o.metaObject().className() == "QQuickText" else 1)
        real_click(cands[-1])
        return True

    def _button_cands(target):
        cands = []
        for o in walk():
            try:
                if "Button" not in o.metaObject().className():
                    continue
                if o.width() <= 0 or o.height() <= 0 or not o.isVisible():
                    continue
                if o.property("text") == target:
                    cands.append(o)
            except Exception:  # noqa: BLE001
                pass
        return cands

    def click_button(target):
        cands = _button_cands(target)
        if not cands:
            return False
        pop = [o for o in cands if in_popup(o)]
        real_click((pop or cands)[-1])
        return True

    def click_button_where(target, y_pred):
        cands = [o for o in _button_cands(target) if y_pred(scene_rect(o).center().y())]
        if not cands:
            return False
        real_click(cands[-1])
        return True

    def type_text(s):
        for ch in s:
            QCoreApplication.sendEvent(win, QKeyEvent(QKeyEvent.Type.KeyPress, 0, Qt.NoModifier, ch))
            QCoreApplication.sendEvent(win, QKeyEvent(QKeyEvent.Type.KeyRelease, 0, Qt.NoModifier, ch))
            app.processEvents()

    def press_key(key):
        QCoreApplication.sendEvent(win, QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.NoModifier, "\r"))
        QCoreApplication.sendEvent(win, QKeyEvent(QKeyEvent.Type.KeyRelease, key, Qt.NoModifier, "\r"))
        app.processEvents()

    def input_field():
        for o in walk():
            try:
                if isinstance(o, QQuickItem) and o.isVisible() and o.width() > 0 \
                   and str(o.property("placeholderText") or "").startswith("输入你的答案"):
                    return o
            except Exception:  # noqa: BLE001
                pass
        return None

    def input_width():
        f = input_field()
        return round(f.width(), 1) if f else -1

    def close_popups():
        press_key(Qt.Key_Escape)
        QTest.qWait(250)
        press_key(Qt.Key_Escape)
        QTest.qWait(150)

    def set_size(w, h):
        win.setProperty("width", w)
        win.setProperty("height", h)
        QTest.qWait(650)

    def bounds_report(tag):
        ctrls = []
        for o in walk():
            try:
                cn = o.metaObject().className()
                if "Button" not in cn and "TextField" not in cn:
                    continue
                if o.width() <= 0 or o.height() <= 0 or not o.isVisible():
                    continue
                r = scene_rect(o)
                ctrls.append({"text": str(o.property("text") or ""), "cn": cn,
                              "x": round(r.x(), 1), "y": round(r.y(), 1),
                              "w": round(r.width(), 1), "h": round(r.height(), 1)})
            except Exception:  # noqa: BLE001
                pass
        W, H = win.property("width"), win.property("height")
        outside = [c for c in ctrls if c["x"] < -1 or c["y"] < -1
                   or c["x"] + c["w"] > W + 1 or c["y"] + c["h"] > H + 1]
        EV["sizes"].setdefault(tag, {})["window"] = [W, H]
        EV["sizes"][tag]["controls"] = len(ctrls)
        EV["sizes"][tag]["outside"] = outside
        return outside

    def grab(tag):
        img = win.grabWindow()
        p = os.path.join(shots_dir, tag + ".png")
        img.save(p)
        print("SHOT %s %dx%d" % (p, img.width(), img.height()), flush=True)
        return p

    def drawer_obj():
        for o in win.findChildren(QObject):
            try:
                if "Drawer" in o.metaObject().className():
                    return o
            except Exception:  # noqa: BLE001
                pass
        return None

    # ================================================== 620 × 620（narrow）
    set_size(620, 620)
    check("U62 mode=narrow", win.property("classroomWindowMode") == "narrow",
          win.property("classroomWindowMode"))
    out62 = bounds_report("narrow620")
    check("U62 控件全部在窗口内（0 越界）", len(out62) == 0,
          [c["text"] for c in out62][:8])
    step = find_text_items("教学步骤 1 / 5")
    check("U62 课件区可见（教学步骤标签在位且位于左条右侧）",
          bool(step) and scene_rect(step[0]).x() >= 90,
          (bool(step), [round(scene_rect(s).x(), 1) for s in step]))
    check("U62 输入框宽度 ≥ 200", input_width() >= 200, input_width())
    check("U62 开始学习按钮可点击", click_button("开始学习") and model.started,
          (model.started, model.status))
    before = model.slideIndex
    check("U62 课件区「下一页」可点击（翻页生效）",
          click_button("下一页") and model.slideIndex == before + 1, model.slideIndex)
    f = input_field()
    if f:
        real_click(f)
        QTest.qWait(150)
        type_text("hello narrow 620")
        press_key(Qt.Key_Return)
        QTest.qWait(350)
    check("U62 文字输入可用（提交进入字幕）",
          any("hello narrow 620" in t.get("text", "") for t in model.transcript),
          [t.get("text") for t in model.transcript if "hello" in t.get("text", "")][:1])
    grab("after_narrow_620")
    # 换老师（弹窗 + 保存 + 展示）
    check("U62 换老师按钮可点击", click_button("换老师"))
    QTest.qWait(800)
    check("U62 老师弹窗可见", any("选择 AI 老师" in x for x in visible_texts()))
    check("U62 老师信息默认文案（缺字段不显示“学科 —”）",
          any("教学语言 未提供" in x and "音色 默认" in x for x in visible_texts()),
          [x for x in visible_texts() if "教学语言" in x][:3])
    check("U62 选择老师乙", click_text("模拟老师乙", want_popup=True))
    QTest.qWait(200)
    check("U62 保存并切换", click_button("保存并切换"))
    QTest.qWait(350)
    saved = json.load(open(demo_cfg, encoding="utf-8")).get("selected_teacher_id")
    check("U62 保存写入隔离配置（t_b）", saved == "t_b", saved)
    check("U62 左条显示老师乙",
          any(x == "模拟老师乙" for x in visible_texts()),
          [x for x in visible_texts() if "模拟" in x][:3])
    # 选课
    check("U62 选择课程可点击", click_button("选择课程"))
    QTest.qWait(700)
    check("U62 课程弹窗可见", any("选择课程与课时" in x for x in visible_texts()))
    ok1 = click_text("日常口语 · Daily English", want_popup=True)
    QTest.qWait(250)
    ok2 = click_button("进入课堂")
    QTest.qWait(400)
    check("U62 切换课程并进入（无旧课残留）",
          ok1 and ok2 and model.currentCourseTitle == "日常口语 · Daily English"
          and not any("办理入住" in t.get("text", "") for t in model.transcript),
          (ok1, ok2, model.currentCourseTitle))
    # 底部「更多」菜单：结束学习可达（y>窗口底部-90 判定底栏）
    H = win.property("height")
    check("U62 底部更多菜单可打开",
          click_button_where("更多", lambda y: y > H - 90))
    QTest.qWait(350)
    check("U62 底部菜单含「结束学习」", bool(find_text_items("结束学习", want_popup=True)),
          [x for x in visible_texts() if "结束" in x][:3])
    check("U62 菜单内结束学习可点击", click_text("结束学习", want_popup=True))
    QTest.qWait(400)
    check("U62 结束学习生效（状态复位）", model.currentCourseIndex == -1,
          (model.currentCourseIndex, model.status))
    close_popups()
    # 顶部「更多」菜单：退出课堂可达（y<90 判定顶栏）
    check("U62 顶部更多菜单可打开",
          click_button_where("更多", lambda y: y < 90))
    QTest.qWait(350)
    vt = visible_texts()
    check("U62 顶部菜单含「退出课堂」「高级设置」",
          any("退出课堂" in x for x in vt) and any("高级设置" in x for x in vt),
          [x for x in vt if "退出" in x or "高级" in x][:3])
    close_popups()
    ev62 = json.load(open(demo_cfg, encoding="utf-8"))
    check("U62 演示配置未被隐式开启/篡改（allow 仍为 True、令牌仍在）",
          ev62.get("allow_teacher_list") is True and ev62.get("teacher_token") == MOCK_TOKEN)

    # ================================================== 860 × 700（compact）
    set_size(860, 700)
    check("U86 mode=compact", win.property("classroomWindowMode") == "compact",
          win.property("classroomWindowMode"))
    out86 = bounds_report("compact860")
    check("U86 控件全部在窗口内（0 越界；含「结束学习」完整）", len(out86) == 0,
          [c["text"] for c in out86][:8])
    endbtns = [o for o in _button_cands("结束学习")]
    end_ok = False
    if endbtns:
        r = scene_rect(endbtns[-1])
        end_ok = (r.x() + r.width()) <= win.property("width") + 1
    check("U86 「结束学习」完整显示", bool(endbtns) and end_ok,
          [(round(scene_rect(b).x(), 1), round(scene_rect(b).width(), 1)) for b in endbtns])
    check("U86 输入框宽度 ≥ 200", input_width() >= 200, input_width())
    # 真实点击恢复课堂
    ok1 = click_button("选择课程")
    QTest.qWait(700)
    ok2 = click_text("酒店英语 · Hotel English", want_popup=True)
    QTest.qWait(250)
    ok3 = click_button("进入课堂")
    QTest.qWait(350)
    check("U86 选课回课堂（点击链路）",
          ok1 and ok2 and ok3 and model.slideCount == 5
          and model.currentCourseTitle.startswith("酒店英语"),
          (ok1, ok2, ok3, model.currentCourseTitle))
    grab("after_compact_860")
    check("U86 底栏「结束学习」可点击（点击生效）",
          click_button("结束学习") and model.currentCourseIndex == -1,
          (model.currentCourseIndex, model.status))

    # ================================================== 1000 × 740（medium）
    set_size(1000, 740)
    _fresh_course0()
    model.setPage("classroom")
    QTest.qWait(250)
    check("U100 mode=medium", win.property("classroomWindowMode") == "medium",
          win.property("classroomWindowMode"))
    out100 = bounds_report("medium1000")
    check("U100 控件全部在窗口内（0 越界）", len(out100) == 0, [c["text"] for c in out100][:8])
    iw = input_width()
    check("U100 输入框不再被压缩（≥ 200px，旧值 65px）", iw >= 200, iw)
    f = input_field()
    if f:
        real_click(f)
        QTest.qWait(150)
        type_text("medium input ok")
        press_key(Qt.Key_Return)
        QTest.qWait(350)
    check("U100 文字输入可用", any("medium input ok" in t.get("text", "") for t in model.transcript))
    check("U100 「展开字幕」在位并打开抽屉", click_button("展开字幕"))
    QTest.qWait(600)
    d = drawer_obj()
    drawer_open = bool(d.property("visible")) if d is not None else False
    check("U100 字幕抽屉打开", drawer_open, d)
    if d is not None and drawer_open:
        try:
            d.close()
        except Exception:  # noqa: BLE001
            try:
                d.setProperty("visible", False)
            except Exception:  # noqa: BLE001
                pass
        QTest.qWait(400)
        try:
            check("U100 字幕抽屉可关闭", not bool(d.property("visible")))
        except Exception:  # noqa: BLE001
            pass
    check("U100 宽屏专属「语音对话」在 medium 隐藏（折叠进菜单）",
          not find_text_items("语音对话（不可用）"), None)
    check("U100 底部更多菜单可打开", click_button("更多"))
    QTest.qWait(350)
    voice_items = find_text_items("语音对话（不可用：未接入真实实时语音）", want_popup=True)
    check("U100 菜单内语音项存在且诚实禁用",
          bool(voice_items) and voice_items[0].property("enabled") is False,
          [i.property("enabled") for i in voice_items])
    close_popups()
    grab("after_medium_1000")

    # ================================================== 1360 × 850（wide）+ 全屏
    set_size(1360, 850)
    QTest.qWait(300)
    check("U136 mode=wide", win.property("classroomWindowMode") == "wide",
          win.property("classroomWindowMode"))
    out136 = bounds_report("wide1360")
    check("U136 控件全部在窗口内（0 越界）", len(out136) == 0, [c["text"] for c in out136][:8])
    vt = visible_texts()
    check("U136 三栏结构在位（AI 老师面板 + 互动面板标签 + 课件区）",
          any(x == "AI 老师" for x in vt) and any(x == "课堂笔记" for x in vt)
          and any("教学步骤" in x for x in vt), vt[:4])
    check("U136 左栏老师信息=「教学语言 未提供 · 音色 默认」（缺字段默认文案，非“学科 —”）",
          any("教学语言 未提供 · 音色 默认" in x for x in vt),
          [x for x in vt if "教学语言" in x][:2])
    check("U136 宽屏完整底栏（语音禁用项 + 重复讲解 + 下一页 + 结束学习）",
          bool([o for o in walk() if "Button" in o.metaObject().className()
                and o.isVisible() and o.property("text") == "语音对话（不可用）"])
          and bool(_button_cands("重复讲解")) and bool(_button_cands("下一页"))
          and bool(_button_cands("结束学习")), None)
    check("U136 高级设置弹窗打开", click_button("高级设置"))
    QTest.qWait(500)
    check("U136 高级设置内容在位（不显示密钥字段）",
          any("高级设置（维护者）" in x for x in visible_texts())
          and any("不显示 WebSocket 地址、部署令牌" in x for x in visible_texts()),
          [x for x in visible_texts() if "高级" in x][:2])
    if not click_text("Close", want_popup=True):
        press_key(Qt.Key_Escape)
    QTest.qWait(350)
    check("U136 高级设置关闭",
          not any("高级设置（维护者）" in x for x in visible_texts()))
    check("U136 全屏进入", click_button("全屏"))
    QTest.qWait(1800)
    check("U136 全屏态", win.property("fullscreen") is True, win.property("fullscreen"))
    grab("after_fullscreen")
    check("U136 全屏退出", click_button("退出全屏"))
    QTest.qWait(1800)
    check("U136 恢复正常（fullscreen=False）", win.property("fullscreen") is False,
          win.property("fullscreen"))
    grab("after_wide_1360")

    win.close()
    QTest.qWait(200)
    srv.shutdown()

    with open(os.path.join(logs_dir, "ui_geometry.json"), "w", encoding="utf-8") as fh:
        json.dump(EV, fh, ensure_ascii=False, indent=1)
    total = len(RESULTS)
    passed = sum(1 for _n, ok, _d in RESULTS if ok)
    print("CLASSROOM_UI_PROBE: %d checks, %d PASS, %d FAIL" % (total, passed, total - passed), flush=True)
    for name, ok, detail in RESULTS:
        if not ok:
            print("  FAILED: %s  %r" % (name, detail), flush=True)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
