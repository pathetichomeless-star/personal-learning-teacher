#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLASSROOM V1 独立 QA 驱动 v2（真实窗口；QTest 真实鼠标事件；QKeyEvent 键入）。
遍历改用视觉树（delegate 非 QObject 可达）。不改动任何产品文件。

模式：full | fresh | corrupt
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time

CLIENT = "<project-root>/client"
QML = os.path.join(CLIENT, "src", "classroom", "qml")
OUT = "/tmp/xz-qa-cv1"
TOKEN = "QA-INDEPENDENT-DO-NOT-USE-0001"
MOCK_LOG = OUT + "/mock/requests.log"

CHEAT_FORBIDDEN = ("reservation", "reception", "rental", "办理入住", "Check-in")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="full")
    ap.add_argument("--data-dir", default=OUT + "/data")
    args = ap.parse_args()
    run_started_at = time.strftime("%H:%M:%S")

    os.environ["XIAOZHI_DATA_DIR"] = args.data_dir
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    os.environ.setdefault("QT_API", "pyside6")
    sys.path.insert(0, CLIENT)

    from PySide6.QtCore import QCoreApplication, QObject, QPoint, QPointF, QRectF, Qt, QUrl
    from PySide6.QtGui import QGuiApplication, QKeyEvent
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest

    from src.utils.config_manager import initialize_config
    initialize_config()
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)

    from src.classroom.classroom_model import ClassroomModel

    EV = {"mode": args.mode, "data_dir": args.data_dir, "checks": [], "texts": {},
          "rects": {}, "mock": {}, "shots": [], "walk": None}

    def check(name, cond, detail=""):
        EV["checks"].append({"name": name, "ok": bool(cond), "detail": str(detail)[:400]})
        print("QARESULT %s %s %s" % ("PASS" if cond else "FAIL", name, str(detail)[:200]), flush=True)

    def mock_lines():
        try:
            return open(MOCK_LOG, encoding="utf-8").read().splitlines()
        except FileNotFoundError:
            return []

    def mock_counts(lines):
        return {"list": sum(1 for l in lines if "LIST" in l),
                "ws": sum(1 for l in lines if "WS_REFUSE" in l),
                "unexpected": sum(1 for l in lines if "UNEXPECTED" in l)}

    def mock_counts_since(ts):
        """仅统计本次运行开始之后写入的请求行（时间戳前缀 HH:MM:SS）。"""
        return mock_counts([l for l in mock_lines() if l[:8] >= ts])

    # ---------------- 视觉树遍历 ----------------
    def walk_visual(root=None):
        out = []

        def rec(it):
            out.append(it)
            for c in it.childItems():
                rec(c)
        rec(root if root is not None else win.contentItem())
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
        for o in walk_visual():
            try:
                if not o.isVisible() or o.width() <= 0 or o.height() <= 0:
                    continue
                t = o.property("text")
                if isinstance(t, str) and t.strip():
                    out.append(t)
            except Exception:  # noqa: BLE001
                pass
        return out

    def snap_texts(tag):
        ts = visible_texts()
        EV["texts"][tag] = ts
        return ts

    def find_text_items(target, want_popup=None):
        res = []
        for o in walk_visual():
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

    def click_button(target):
        cands = []
        for o in walk_visual():
            try:
                if "Button" not in o.metaObject().className():
                    continue
                if o.width() <= 0 or o.height() <= 0 or not o.isVisible():
                    continue
                if o.property("text") == target:
                    cands.append(o)
            except Exception:  # noqa: BLE001
                pass
        if not cands:
            return False
        pop = [o for o in cands if in_popup(o)]
        real_click((pop or cands)[-1])
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

    def grab(tag):
        img = win.grabWindow()
        p = "%s/shots/%s.png" % (OUT, tag)
        img.save(p)
        EV["shots"].append(p)
        print("SHOT %s %dx%d" % (p, img.width(), img.height()), flush=True)

    def screencap(tag, full=False):
        p = "%s/shots/%s_screen.png" % (OUT, tag)
        if full:
            subprocess.run(["screencapture", "-x", p], check=False)
        else:
            x = int(win.property("x") or 0)
            y = int(win.property("y") or 0)
            w = int(win.property("width") or 0)
            h = int(win.property("height") or 0)
            subprocess.run(["screencapture", "-x", "-R", "%d,%d,%d,%d" % (x, y, w, h), p], check=False)
        EV["shots"].append(p)
        print("SHOT %s" % p, flush=True)

    def geometry_report(tag):
        items = []
        for o in walk_visual():
            try:
                cn = o.metaObject().className()
                if "Button" not in cn and "TextField" not in cn:
                    continue
                if o.width() <= 0 or o.height() <= 0 or not o.isVisible():
                    continue
                r = scene_rect(o)
                items.append({"cls": cn, "text": str(o.property("text") or ""),
                              "x": round(r.x(), 1), "y": round(r.y(), 1),
                              "w": round(r.width(), 1), "h": round(r.height(), 1),
                              "implicitW": round(float(o.property("implicitWidth") or 0), 1)})
            except Exception:  # noqa: BLE001
                pass
        W, H = win.property("width"), win.property("height")
        outside = [i for i in items if i["x"] < -1 or i["y"] < -1
                   or i["x"] + i["w"] > W + 1 or i["y"] + i["h"] > H + 1]
        overlaps = []
        for a in range(len(items)):
            for b in range(a + 1, len(items)):
                A, B = items[a], items[b]
                ix = min(A["x"] + A["w"], B["x"] + B["w"]) - max(A["x"], B["x"])
                iy = min(A["y"] + A["h"], B["y"] + B["h"]) - max(A["y"], B["y"])
                if ix > 2 and iy > 2:
                    overlaps.append([A["text"], B["text"], round(ix, 1), round(iy, 1)])
        squeezed = [i for i in items if i["implicitW"] > 0 and i["w"] < i["implicitW"] - 1]
        EV["rects"][tag] = {"window": [W, H], "controls": len(items),
                            "outside": outside, "overlaps": overlaps, "squeezed": squeezed}
        print("GEOM %s W=%s H=%s controls=%d outside=%d overlaps=%d squeezed=%d"
              % (tag, W, H, len(items), len(outside), len(overlaps), len(squeezed)), flush=True)

    # ---------------- bootstrap（与 classroom_main.py 相同序列） ----------------
    model = ClassroomModel()
    model.loadSelectedTeacher()
    model.selectCourse(0)
    model.selectLesson(0)
    model.nextSlide()
    model.refreshTeachers()

    engine = QQmlApplicationEngine()
    engine.addImportPath(QML)
    engine.rootContext().setContextProperty("classroom", model)
    engine.load(QUrl.fromLocalFile(os.path.join(QML, "ClassroomWindow.qml")))
    roots = engine.rootObjects()
    if not roots:
        print("QARESULT FAIL window_load", flush=True)
        return 2
    win = roots[0]
    if args.mode == "full":
        if model.teachers:
            model.selectTeacher(model.teachers[0].get("teacher_id", ""))
        win.setProperty("width", 1360)
        win.setProperty("height", 850)
    else:
        win.setProperty("width", 1000)
        win.setProperty("height", 740)
    win.setProperty("x", 60)
    win.setProperty("y", 80)
    QTest.qWait(900)
    try:
        scr = app.primaryScreen()
        EV["screen"] = {"avail": [scr.availableGeometry().width(), scr.availableGeometry().height()],
                        "dpr": scr.devicePixelRatio()}
    except Exception:  # noqa: BLE001
        pass
    check("window_visible", win.property("visible") is True, win.property("visible"))

    if args.mode == "fresh":
        m = mock_counts_since(run_started_at)
        EV["mock"]["after_bootstrap"] = m
        check("fresh_no_network_at_all", m["list"] == 0 and m["ws"] == 0 and m["unexpected"] == 0, m)
        st = model.teachersState
        check("fresh_state_message", st == "未配置服务地址（请在隔离配置中设置网关地址）", st)
        check("fresh_teachers_empty", len(model.teachers) == 0, model.teachers)
        cfg_path = os.path.join(args.data_dir, "config", "config.json")
        try:
            d = json.load(open(cfg_path, encoding="utf-8"))
            ok_json = d.get("SYSTEM_OPTIONS", {}).get("NETWORK", {}).get("WEBSOCKET_URL") is None
        except Exception as e:  # noqa: BLE001
            ok_json = "ERR:%r" % e
        check("fresh_default_config_created_without_url", ok_json is True, ok_json)
        ts = snap_texts("fresh")
        check("fresh_local_courses_available", any("本地演示" in t for t in ts) and any("选择课程" in t for t in ts), ts[:5])
        check("fresh_avatar_placeholder", any("静态占位" in t for t in ts))
        grab("fresh_after_boot")
        json.dump(EV, open(OUT + "/logs/driver_fresh.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        fails = sum(1 for c in EV["checks"] if not c["ok"])
        print("QA_MODE fresh checks=%d fails=%d" % (len(EV["checks"]), fails), flush=True)
        return 0 if fails == 0 else 1

    if args.mode == "corrupt":
        m = mock_counts_since(run_started_at)
        EV["mock"]["after_bootstrap"] = m
        check("corrupt_no_network_at_all", m["list"] == 0 and m["ws"] == 0 and m["unexpected"] == 0, m)
        st = model.teachersState
        check("corrupt_state_message", "未配置服务地址" in st, st)
        baks = glob.glob(os.path.join(args.data_dir, "config", "config.json.corrupt-*"))
        check("corrupt_config_backed_up", len(baks) >= 1, baks)
        ts = snap_texts("corrupt")
        check("corrupt_app_starts", any("小智 AI 学生课堂" in t for t in ts), ts[:4])
        grab("corrupt_after_boot")
        json.dump(EV, open(OUT + "/logs/driver_corrupt.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        fails = sum(1 for c in EV["checks"] if not c["ok"])
        print("QA_MODE corrupt checks=%d fails=%d" % (len(EV["checks"]), fails), flush=True)
        return 0 if fails == 0 else 1

    # ==================================================================== full
    mock0 = mock_counts(mock_lines())
    EV["mock"]["at_start"] = mock0

    # ---- 窗口尺寸 / 全屏 / 恢复 / 四档布局 ----
    check("mode_wide", win.property("classroomWindowMode") == "wide", win.property("classroomWindowMode"))
    snap_texts("start")
    grab("wide_360")
    screencap("wide_on_screen")
    geometry_report("wide_1360")

    check("fullscreen_enter_click", click_button("全屏"))
    QTest.qWait(1800)
    check("fullscreen_enter", win.property("fullscreen") is True, win.property("fullscreen"))
    grab("fullscreen")
    screencap("fullscreen_on_screen", full=True)
    check("fullscreen_exit_click", click_button("退出全屏"))
    QTest.qWait(1800)
    check("fullscreen_exit", win.property("fullscreen") is False, win.property("fullscreen"))
    check("after_restore_size", win.property("width") == 1360 and 700 <= win.property("height") <= 900,
          (win.property("width"), win.property("height"), EV.get("screen")))

    for w, h, want in ((1000, 740, "medium"), (860, 700, "compact"), (620, 620, "narrow")):
        win.setProperty("width", w)
        win.setProperty("height", h)
        QTest.qWait(600)
        got = win.property("classroomWindowMode")
        check("layout_%d" % w, got == want, got)
        geometry_report("w%d" % w)
        if want in ("compact", "narrow"):
            snap_texts("layout_%s" % want)
            grab("layout_%s" % want)
            if want == "narrow":
                screencap("narrow_on_screen")
    sw = [o for o in find_text_items("语音对话（不可用）")
          if "Button" in o.metaObject().className()]
    enabled = sw[0].property("enabled") if sw else None
    check("speech_button_disabled", bool(sw) and enabled is False, (len(sw), enabled))
    win.setProperty("width", 1360)
    win.setProperty("height", 850)
    QTest.qWait(600)

    # ---- 老师 A → B → 保存不自动联网 ----
    since = mock_counts(mock_lines())
    check("teacher_dialog_open_click", click_button("更换老师"))
    QTest.qWait(900)
    ts_td = snap_texts("teacher_dialog_A")
    check("teacher_dialog_visible", any("选择 AI 老师" in t for t in ts_td), ts_td[:5])
    check("teacher_A_listed", any("模拟老师 A" in t for t in ts_td) and any("模拟老师 B" in t for t in ts_td),
          [t for t in ts_td if "模拟" in t and "老师" in t][:4])
    check("teacher_meta_in_dialog", any("学科 en" in t and "Cherry" in t for t in ts_td),
          [t for t in ts_td if "音色" in t])
    check("token_not_in_ui_A", TOKEN not in "\n".join(ts_td))
    check("click_row_A", click_text("模拟老师 A", want_popup=True))
    QTest.qWait(250)
    check("select_A_before_save", model.selectedTeacherId == "tch_qa_a", model.selectedTeacherId)
    check("save_A_click", click_button("保存并切换"))
    QTest.qWait(450)
    disk = json.load(open(os.path.join(args.data_dir, "config", "config.json"), encoding="utf-8"))
    disk_tid = disk.get("SYSTEM_OPTIONS", {}).get("NETWORK", {}).get("TEACHER_ID")
    check("save_A_written_to_disk", disk_tid == "tch_qa_a", disk_tid)
    m_now = mock_counts(mock_lines())
    EV["mock"]["after_save_A"] = m_now
    check("save_A_no_new_requests", m_now["list"] == since["list"] + 1, (since, m_now))

    check("teacher_dialog_reopen_click", click_button("更换老师"))
    QTest.qWait(900)
    check("click_row_B", click_text("模拟老师 B", want_popup=True))
    QTest.qWait(250)
    check("select_B", model.selectedTeacherId == "tch_qa_b", model.selectedTeacherId)
    check("save_B_click", click_button("保存并切换"))
    QTest.qWait(450)
    disk = json.load(open(os.path.join(args.data_dir, "config", "config.json"), encoding="utf-8"))
    disk_tid = disk.get("SYSTEM_OPTIONS", {}).get("NETWORK", {}).get("TEACHER_ID")
    check("save_B_written_to_disk", disk_tid == "tch_qa_b", disk_tid)
    m_after_B = mock_counts(mock_lines())
    EV["mock"]["after_save_B"] = m_after_B
    check("save_B_no_extra_requests", m_after_B["list"] == m_now["list"] + 1, (m_now, m_after_B))
    check("no_ws_attempt_ever", m_after_B["ws"] == 0, m_after_B)
    ts_main = snap_texts("after_teacher_B")
    check("topbar_shows_B", any("老师：模拟老师 B" in t for t in ts_main), [t for t in ts_main if "老师：" in t][:3])
    check("panel_line_B", any("音色 Serena" in t for t in ts_main),
          [t for t in ts_main if "音色" in t])
    check("panel_subject_gap_documented",
          any(t.startswith("学科 —") and "Serena" in t for t in ts_main),
          {"note": "网关 teacher/list 白名单无 subject 字段；左栏 学科 —；对话框行用 language 显示为学科",
           "lines": [t for t in ts_main if t.startswith("学科")]})
    check("token_not_in_ui_B", TOKEN not in "\n".join(ts_main))
    grab("after_teacher_B")

    # ---- 选课（切换到 数字与时间，验证状态确实改变） ----
    title_before = model.currentCourseTitle
    check("open_course_dialog", click_button("选择课程"))
    QTest.qWait(800)
    ts_cd = snap_texts("course_dialog")
    check("course_dialog_visible", any("选择课程与课时" in t for t in ts_cd), ts_cd[:4])
    check("course_local_label", any("本地演示课程" in t for t in ts_cd))
    check("course_rows_listed", sum(1 for t in ts_cd if ("Hotel" in t or "Daily" in t or "Numbers" in t)) >= 3,
          [t for t in ts_cd if "·" in t][:6])
    check("click_course_numbers", click_text("数字与时间 · Numbers & Time", want_popup=True))
    QTest.qWait(350)
    check("click_lesson_time", click_text("第 1 课 · 询问时间 Telling time", want_popup=True))
    QTest.qWait(350)
    check("click_enter_classroom", click_button("进入课堂"))
    QTest.qWait(500)
    check("course_switched_from_hotel", model.currentCourseTitle == "数字与时间 · Numbers & Time"
          and model.currentCourseTitle != title_before,
          (title_before, model.currentCourseTitle, model.currentLessonTitle))
    check("cover_visible_after_switch", any("询问时间 Telling time" in t for t in visible_texts()))

    # ---- 连续翻页：cover → vocab → sentence → practice → summary ----
    # 先回到第 0 页
    for _ in range(8):
        if model.slideIndex <= 0:
            break
        click_button("上一页")
        QTest.qWait(250)
    check("back_to_first_slide", model.slideIndex == 0, model.slideIndex)
    walk = []
    for i in range(12):
        t = model.currentSlide.get("type")
        tsx = snap_texts("slide_%d_%s" % (model.slideIndex, t))
        walk.append((model.slideIndex, t))
        if t == "cover":
            check("cover_page", any("询问时间 Telling time" in x for x in tsx), tsx[:8])
            grab("course_cover")
        if t == "vocab":
            check("vocab_page_bilingual",
                  any("half past" in x for x in tsx) and any("七点半" in x for x in tsx)
                  and any("It's half past seven." in x for x in tsx), tsx[:40])
        if t == "sentence":
            check("sentence_page_bilingual",
                  any("The train leaves at a quarter to nine." in x for x in tsx)
                  and any("火车九点差一刻出发。" in x for x in tsx), tsx[:40])
        if t == "practice":
            check("practice_page_q", any("七点半" in x for x in tsx))
            check("practice_options_visible",
                  all(any(o in x for x in tsx) for o in
                      ["A. half past seven", "B. quarter past seven", "C. seven to half"]),
                  [x for x in tsx if x.startswith(("A.", "B.", "C."))])
        if model.slideIndex + 1 >= model.slideCount:
            break
        click_button("下一页")
        QTest.qWait(300)
    EV["walk"] = walk
    check("walk_hit_all_types", {w[1] for w in walk} >= {"cover", "vocab", "sentence", "practice", "summary"}, walk)

    # 上一页 / 重复讲解（用点击前后的索引变化核对）
    idx_before = model.slideIndex
    click_button("上一页")
    QTest.qWait(300)
    check("prev_slide_works", model.slideIndex == idx_before - 1, (idx_before, model.slideIndex))
    idx2 = model.slideIndex
    click_button("重复讲解")
    QTest.qWait(300)
    check("repeat_slide_keeps_index", model.slideIndex == idx2, (idx2, model.slideIndex))

    # 回到练习页
    while model.currentSlide.get("type") != "practice" and model.slideIndex + 1 < model.slideCount:
        click_button("下一页")
        QTest.qWait(250)
    check("practice_reached", model.currentSlide.get("type") == "practice", model.slideIndex)

    # ---- 完成选择题 ----
    check("click_option_A", click_text("A. half past seven"))
    QTest.qWait(300)
    p = dict(model.practice)
    check("practice_answer_correct", p.get("answered") and p.get("correct") is True and "答对了" in p.get("feedback", ""), p)
    ts_pp = snap_texts("practice_answered")
    check("practice_feedback_visible", any("答对了" in x for x in ts_pp), [x for x in ts_pp if "解析" in x][:2])
    check("practice_note_added", any("练习作答" in n.get("text", "") for n in model.notes), model.notes)
    grab("practice_answered")

    # ---- 文字提交（QKeyEvent 键入 + 回车） ----
    click_text("字幕")
    QTest.qWait(250)
    check("tab_transcript_reset", model.activeTab == "transcript", model.activeTab)
    field = None
    for o in walk_visual():
        try:
            if isinstance(o, QQuickItem) and o.isVisible() and o.width() > 0 \
               and str(o.property("placeholderText") or "").startswith("输入你的答案"):
                field = o
                break
        except Exception:  # noqa: BLE001
            pass
    check("input_field_found", field is not None)
    if field is not None:
        real_click(field)
        QTest.qWait(200)
        type_text("It is half past seven.")
        QTest.qWait(200)
        press_key(Qt.Key_Return)
        QTest.qWait(450)
        tr = "\n".join(t.get("text", "") for t in model.transcript)
        check("text_submit_student_line", "It is half past seven." in tr, tr[-140:])
        check("text_submit_local_reply", "（本地模拟回应）" in tr, tr[-140:])
        check("text_submit_note", any("It is half past seven." in n.get("text", "") for n in model.notes), model.notes)
        ts_tsn = snap_texts("after_text_submit")
        check("transcript_visible_lines",
              any("我：It is half past seven." in x for x in ts_tsn) and any("本地模拟回应" in x for x in ts_tsn),
              [x for x in ts_tsn if "本地模拟" in x or "我：" in x][:4])

    # ---- 标签切换：词汇 / 课堂笔记 / 字幕 ----
    check("click_tab_vocab", click_text("词汇"))
    QTest.qWait(300)
    check("tab_vocab", model.activeTab == "vocab", model.activeTab)
    ts_v = snap_texts("tab_vocab")
    check("vocab_tab_content", any("half past" in x for x in ts_v), ts_v[-8:])
    check("click_tab_notes", click_text("课堂笔记"))
    QTest.qWait(300)
    check("tab_notes", model.activeTab == "notes", model.activeTab)
    ts_n = snap_texts("tab_notes")
    check("notes_tab_content_has_practice_and_text",
          any("练习作答" in x for x in ts_n) and any("It is half past seven." in x for x in ts_n), ts_n[-8:])
    check("click_tab_transcript_back", click_text("字幕"))
    QTest.qWait(300)
    check("tab_transcript_back", model.activeTab == "transcript", model.activeTab)

    # ---- 切换另一门课：不残留 ----
    check("open_course_dialog_2", click_button("选择课程"))
    QTest.qWait(800)
    check("click_course_daily", click_text("日常口语 · Daily English", want_popup=True))
    QTest.qWait(300)
    check("click_enter_classroom_2", click_button("进入课堂"))
    QTest.qWait(500)
    blob_after = "\n".join(snap_texts("after_course_switch"))
    EV["transcript_after_switch"] = list(model.transcript)
    EV["notes_after_switch"] = list(model.notes)
    check("switch_course_title", model.currentCourseTitle == "日常口语 · Daily English", model.currentCourseTitle)
    check("no_old_course_residue",
          not any(x in blob_after for x in ("half past", "七点半", "Telling time", "quarter to nine")),
          [x for x in blob_after.splitlines() if any(y in x for y in ("half past", "七点半", "Telling"))][:5])
    blob_tr = "\n".join(t.get("text", "") for t in model.transcript)
    check("no_old_transcript", not any(x in blob_tr for x in ("half past", "七点半", "Telling time")), model.transcript[:3])
    check("no_old_notes", model.notes == [], model.notes[:2])
    check("no_old_practice", model.hasPractice is False, model.practice)
    grab("after_course_switch")

    # ---- 数字人未启用时课件仍显示 ----
    ts_av = snap_texts("avatar_check")
    check("avatar_placeholder_visible", any("数字人未启用" in t for t in ts_av))
    check("courseware_visible_without_avatar",
          any("日常口语" in t for t in ts_av) and any("打招呼" in t for t in ts_av),
          [t for t in ts_av if "日常" in t or "打招呼" in t][:4])

    # ---- 结束课堂并重新开始 ----
    check("click_end_learning", click_button("结束学习"))
    QTest.qWait(450)
    check("end_state_reset",
          model.currentCourseIndex == -1 and model.currentLessonIndex == -1 and model.slideIndex == -1,
          (model.currentCourseIndex, model.currentLessonIndex, model.slideIndex))
    ts_end = snap_texts("ended")
    check("end_empty_state", any("请选择一门课程开始学习" in t for t in ts_end), ts_end[:5])
    check("end_transcript_cleared", model.transcript == [] and model.notes == [])
    check("open_course_dialog_3", click_button("选择课程"))
    QTest.qWait(800)
    check("click_course_hotel_again", click_text("酒店英语 · Hotel English", want_popup=True))
    QTest.qWait(300)
    check("click_lesson_breakfast", click_text("第 2 课 · 预订早餐 Breakfast", want_popup=True))
    QTest.qWait(300)
    check("click_enter_classroom_3", click_button("进入课堂"))
    QTest.qWait(450)
    check("click_start_learning", click_button("开始学习"))
    QTest.qWait(450)
    check("restart_lesson2",
          model.currentLessonTitle == "第 2 课 · 预订早餐 Breakfast" and model.slideCount == 5 and
          model.currentCourseTitle == "酒店英语 · Hotel English",
          (model.currentCourseTitle, model.currentLessonTitle, model.slideCount))
    ts_re = snap_texts("restarted")
    check("restart_content_changed", any("预订早餐" in t for t in ts_re)
          and not any("打招呼 Greetings" in t for t in ts_re), ts_re[:6])
    grab("restarted")

    # ---- 全程网络收敛 / 令牌不外泄 ----
    m_final = mock_counts(mock_lines())
    EV["mock"]["final"] = m_final
    check("final_no_ws_no_unexpected", m_final["ws"] == 0 and m_final["unexpected"] == 0, m_final)
    check("final_request_budget", m_final["list"] <= mock0["list"] + 4, (mock0, m_final))
    ui_blob = "\n".join("\n".join(EV["texts"].get(t, [])) for t in EV["texts"])
    check("token_never_in_ui", TOKEN not in ui_blob)

    # 全部控件在窄窗下无遮挡（汇总）
    for tag in ("wide_1360", "w1000", "w860", "w620"):
        r = EV["rects"].get(tag, {})
        EV.setdefault("overlap_summary", {})[tag] = {
            "outside": len(r.get("outside", [])), "overlaps": len(r.get("overlaps", []))}

    json.dump(EV, open(OUT + "/logs/driver_full.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    fails = sum(1 for c in EV["checks"] if not c["ok"])
    print("QA_MODE full checks=%d fails=%d" % (len(EV["checks"]), fails), flush=True)
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
