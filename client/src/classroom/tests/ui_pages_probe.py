# -*- coding: utf-8 -*-
"""CLASSROOM V2 页面探针 —— 书库 / 导入 / 校对 / 发布 / 课堂（DELIVERY GATE 02 · Agent B）。

真实窗口 + 真实鼠标/键盘事件；产品 QML/Model 原样加载。
覆盖：栏目切换、书库列表与打开、导入能力表与硬门禁横幅、解析进度（真实阶段记录）、
      校对确认、发布门禁演练、错误态（无效课程 bundle）、弹窗不越界、多档响应式、截图。

运行（需要真实显示环境，不能 offscreen）：
    cd client && PYTHONPATH= ./.venv/bin/python src/classroom/tests/ui_pages_probe.py

输出：UIRESULT 行 + ui_pages.json + 截图（docs/.../classroom-v2/delivery-02/）。
本探针为**开发自验**工具，不构成独立 QA。
"""
import argparse
import json
import os
import sys
import tempfile

CLIENT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
REPO = os.path.dirname(CLIENT)
if CLIENT not in sys.path:
    sys.path.insert(0, CLIENT)

DEFAULT_OUT = os.path.join(REPO, "docs", "engineering", "product-v1", "classroom-v2", "delivery-02")

RESULTS = []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=DEFAULT_OUT)
    a = ap.parse_args()
    shots = os.path.join(a.outdir, "screenshots")
    logs = os.path.join(a.outdir, "test-results")
    os.makedirs(shots, exist_ok=True)
    os.makedirs(logs, exist_ok=True)

    data_dir = tempfile.mkdtemp(prefix="cls-v2-pages-")
    # 错误态夹具：一个**故意不合契约**的 bundle → 书库必须如实显示不可用原因
    lib = os.path.join(data_dir, "library")
    os.makedirs(lib, exist_ok=True)
    with open(os.path.join(lib, "crs_broken.course.json"), "w", encoding="utf-8") as fh:
        json.dump({"schema": "classroom.course.bundle", "version": 1,
                   "courses": [{"course_id": "crs_broken", "revision": 1, "title": "损坏课程",
                                "source": "user-textbook", "source_doc_id": None,
                                "source_doc_hash": None, "source_file_sha256": None,
                                "lessons": [{"lesson_id": "l1", "title": "L", "slides": [
                                    {"type": "vocab", "word": "x", "meaning": "y", "en": "", "cn": ""}]}]}]},
                  fh, ensure_ascii=False)

    os.environ["XIAOZHI_CLASSROOM_DIR"] = data_dir
    os.environ["XIAOZHI_DATA_DIR"] = data_dir
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    os.environ.setdefault("QT_API", "pyside6")

    from PySide6.QtCore import QCoreApplication, QPoint, QPointF, QRectF, Qt, QUrl
    from PySide6.QtGui import QGuiApplication, QKeyEvent
    from PySide6.QtQml import QQmlApplicationEngine
    # 必须显式导入 QtQuick：否则 rootObjects()[0] 仅以 QWindow 基类型暴露，
    # 拿不到 contentItem()（视觉树入口），探针会在第一次 walk() 崩溃。
    from PySide6.QtQuick import QQuickItem  # noqa: F401
    from PySide6.QtTest import QTest

    from src.classroom.classroom_model import ClassroomModel

    EV = {"pages": {}, "checks": []}

    def check(name, cond, detail=""):
        ok = bool(cond)
        RESULTS.append((name, ok, detail))
        EV["checks"].append({"name": name, "ok": ok, "detail": str(detail)[:300]})
        print("PAGERESULT %s %s %s" % ("PASS" if ok else "FAIL", name, str(detail)[:200]), flush=True)

    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])

    QML = os.path.join(CLIENT, "src", "classroom", "qml")
    model = ClassroomModel()
    model.selectCourse(0)
    model.selectLesson(0)

    engine = QQmlApplicationEngine()
    engine.addImportPath(QML)
    engine.rootContext().setContextProperty("classroom", model)
    engine.load(QUrl.fromLocalFile(os.path.join(QML, "ClassroomWindow.qml")))
    roots = engine.rootObjects()
    if not roots:
        check("pages_window_load", False, "QML 未加载")
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

    def in_popup(item):
        cur = item.parentItem()
        while cur is not None:
            if "PopupItem" in cur.metaObject().className():
                return True
            cur = cur.parentItem()
        return False

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

    def _btns(target):
        res = []
        for o in walk():
            try:
                if "Button" not in o.metaObject().className():
                    continue
                if o.width() <= 0 or o.height() <= 0 or not o.isVisible():
                    continue
                if o.property("text") == target:
                    res.append(o)
            except Exception:  # noqa: BLE001
                pass
        return res

    def click_button(target):
        c = _btns(target)
        if not c:
            return False
        pop = [o for o in c if in_popup(o)]
        real_click((pop or c)[-1])
        return True

    def click_button_in_card(card_text, button_text):
        """点击与某卡片标题同属一张卡片的按钮。

        书库每张卡都有同名按钮（「打开并进入课堂」），按"最后一次出现"点击会点错卡片；
        这里用场景矩形判定"同卡"（水平有交集）并取垂直距离最近的按钮。
        """
        titles = []
        for o in walk():
            try:
                if not o.isVisible() or o.width() <= 0 or o.height() <= 0:
                    continue
                t = o.property("text")
                if isinstance(t, str) and card_text in t:
                    titles.append(o)
            except Exception:  # noqa: BLE001
                pass
        btns = _btns(button_text)
        if not titles or not btns:
            return False
        best, bestd = None, float("inf")
        for b in btns:
            br = scene_rect(b)
            for t in titles:
                tr = scene_rect(t)
                if min(br.right(), tr.right()) - max(br.left(), tr.left()) <= 0:
                    continue
                d = abs(br.top() - tr.top())
                if d < bestd:
                    best, bestd = b, d
        if best is None:
            return False
        real_click(best)
        return True

    def press_escape():
        QTest.keyClick(win, Qt.Key_Escape)
        app.processEvents()
        QTest.qWait(260)

    def type_text(s):
        # QTest.keyClicks 不接受 QQuickWindow；与 ui_layout_probe 一致走 QKeyEvent。
        for ch in s:
            QCoreApplication.sendEvent(
                win, QKeyEvent(QKeyEvent.Type.KeyPress, 0, Qt.NoModifier, ch))
            QCoreApplication.sendEvent(
                win, QKeyEvent(QKeyEvent.Type.KeyRelease, 0, Qt.NoModifier, ch))
            app.processEvents()

    def press_enter():
        QCoreApplication.sendEvent(
            win, QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Return, Qt.NoModifier, "\r"))
        QCoreApplication.sendEvent(
            win, QKeyEvent(QKeyEvent.Type.KeyRelease, Qt.Key_Return, Qt.NoModifier, "\r"))
        app.processEvents()

    def set_size(w, h):
        win.setProperty("width", w)
        win.setProperty("height", h)
        QTest.qWait(600)

    def overflow(tag):
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
                              "x": round(r.x(), 1), "w": round(r.width(), 1)})
            except Exception:  # noqa: BLE001
                pass
        W, H = win.property("width"), win.property("height")
        out = [c for c in ctrls if c["x"] < -1 or c["x"] + c["w"] > W + 1]
        EV["pages"].setdefault(tag, {})["window"] = [W, H]
        EV["pages"][tag]["controls"] = len(ctrls)
        EV["pages"][tag]["outside"] = out
        return out

    def shot(tag):
        img = win.grabWindow()
        p = os.path.join(shots, tag + ".png")
        img.save(p)
        print("SHOT %s %dx%d" % (p, img.width(), img.height()), flush=True)
        return p

    def goto(page):
        model.setPage(page)
        QTest.qWait(450)

    set_size(1360, 850)

    # ------------------------------------------------------------ P01 导航
    vt = visible_texts()
    check("P01a 导航条含 5 个栏目",
          all(x in vt for x in ("课堂", "书库", "导入", "校对", "发布")),
          [x for x in vt if x in ("课堂", "书库", "导入", "校对", "发布")])
    check("P01b 起始在「我的书库」页（FIX01-P2-1：不再自动打开演示课）",
          model.page == "library", model.page)

    # ------------------------------------------------------------ P02 书库
    goto("library")
    vt = visible_texts()
    shot("v2_library_wide")
    check("P02a 书库页标题在位", any(x == "书库" for x in vt))
    check("P02b 书库列出离线演示课程", any("离线演示：基础问候" in x for x in vt), vt[:8])
    check("P02c 书库列出随包本地演示课程",
          any("酒店英语" in x for x in vt), [x for x in vt if "酒店" in x][:2])
    check("P02d **错误态**：损坏课程如实显示不可用原因",
          any("不可用：" in x and "契约" in x for x in vt),
          [x for x in vt if "不可用" in x][:2])
    check("P02e 书库宽屏无控件越界", overflow("library_1360") == [], overflow("library_1360")[:3])
    check("P02e2 书库如实显示离线演示的待确认项数",
          any("待人工确认" in x for x in vt), [x for x in vt if "待人工确认" in x][:2])

    # 打开离线演示课程（按卡片定位按钮；若按"最后一个"会点到别的卡片）
    clicked = click_button_in_card("离线演示", "打开并进入课堂")
    QTest.qWait(700)
    check("P02f 打开离线演示课程 → 进入课堂且课程已切换",
          clicked and model.currentCourseTitle.startswith("离线演示"),
          (clicked, model.currentCourseTitle))
    check("P02g 打开后页签自动回到「课堂」", model.page == "classroom", model.page)

    # ------------------------------------------------------------ P03 导入
    goto("import")
    vt = visible_texts()
    shot("v2_import_wide")
    check("P03a 硬门禁横幅显示「本机解析服务：未开放」",
          any("本机解析服务：未开放" in x for x in vt), [x for x in vt if "解析服务" in x][:2])
    check("P03b 横幅含真实原因（等待独立安全复核）",
          any("独立安全复核" in x for x in vt))
    check("P03c 能力表列出各格式", all(any(e in x for x in vt) for e in (".txt", ".md", ".pdf")))
    check("P03d OCR 如实标注暂不支持", any("OCR 暂不支持" in x for x in vt))
    check("P03e 导入页无控件越界", overflow("import_1360") == [], overflow("import_1360")[:3])

    # ------------------------------------------------- P04 解析进度（真实记录）
    clicked = click_button("查看离线流水线记录（解析进度）")
    QTest.qWait(600)
    vt = visible_texts()
    shot("v2_import_progress_wide")
    check("P04a 点击后加载离线流水线真实阶段记录",
          clicked and model.importState == "done" and len(model.importStages) >= 5,
          (model.importState, len(model.importStages)))
    check("P04b 阶段名可见（read_bytes / parse / kb_commit / validate）",
          all(any(s in x for x in vt) for s in ("read_bytes", "parse", "kb_commit", "validate")),
          [x for x in vt if x in ("read_bytes", "parse", "kb_commit", "validate")])
    check("P04c 进度文案声明未发起网络请求（P2-11：界面为业务化文案）",
          any("没有发起任何网络请求" in x or ("网络" in x and "没有" in x) for x in vt),
          [x for x in vt if "网络" in x][:2])

    # ------------------------------------------------------------ P05 校对
    goto("proofread")
    vt = visible_texts()
    shot("v2_proofread_wide")
    check("P05a 校对页显示待确认项（真实 needs_review）",
          model.reviewTotal > 0 and any("校对中" in x or "校对完成" in x for x in vt),
          (model.reviewTotal, [x for x in vt if "校对" in x][:2]))
    check("P05b 音标未知项按事实说明（未编造音标）",
          any("未编造音标" in x for x in vt), [x for x in vt if "音标" in x][:2])
    before = model.reviewUnresolved

    def proofread_field():
        # 找到第一条未解决音标条目的输入框（placeholder 含「音标」）
        cands = []
        for o in walk():
            try:
                if not o.isVisible() or "TextField" not in o.metaObject().className():
                    continue
                ph = o.property("placeholderText")
                if isinstance(ph, str) and "输入音标" in ph:
                    cands.append(o)
            except Exception:  # noqa: BLE001
                pass
        return cands[0] if cands else None

    def click_button_near(anchor):
        """点击与 anchor 同一行的同名按钮（中心垂直距离 < 30px）——
        防止「点最后一个同名按钮」点到别的条目（V1 已知坑）；
        不要求水平相交：同行行尾按钮与填充宽度输入框之间有间距。"""
        btns = _btns("应用音标")
        if not btns:
            return False
        ar = scene_rect(anchor)
        best, bestd = None, float("inf")
        for b in btns:
            br = scene_rect(b)
            d = abs(br.center().y() - ar.center().y())
            if d < 30 and d < bestd:
                best, bestd = b, d
        if best is None:
            return False
        real_click(best)
        return True

    tf = proofread_field()
    clicked = False
    if tf is not None:
        tf.setProperty("text", "/həˈləʊ/")
        app.processEvents()
        QTest.qWait(200)
        clicked = click_button_near(tf)
    QTest.qWait(400)
    check("P05c 补音标并「应用音标」→ 未处理计数减少（FIX01-P1-2：可编辑修正）",
          clicked and model.reviewUnresolved == before - 1,
          (before, model.reviewUnresolved, clicked))
    check("P05d 校对页无控件越界", overflow("proofread_1360") == [], overflow("proofread_1360")[:3])

    # ------------------------------------------------------------ P06 发布
    goto("publish")
    shot("v2_publish_before_wide")
    vt = visible_texts()
    check("P06a 发布页显示 Mock 横幅（不发网络 / 未实现真实路由）",
          any("演练" in x and "Mock" in x for x in vt), [x for x in vt if "Mock" in x][:2])
    clicked = click_button("运行发布门禁演练")
    QTest.qWait(500)
    shot("v2_publish_after_wide")
    vt = visible_texts()
    gates = {g["name"]: g["ok"] for g in model.publishGates}
    check("P06b 门禁演练产出门禁清单", clicked and len(model.publishGates) == 4, gates)
    check("P06c 来源绑定门禁**真实通过**（doc_id 存在且 content_hash 一致）",
          gates.get("来源绑定有效（知识库来源）") is True, gates)
    check("P06d 待确认项门禁如实为未通过（尚有未确认项）",
          gates.get("待人工确认项已清零") is False, gates)
    check("P06e 发布状态文案声明「未执行真实发布」",
          "未执行" in model.publishState, model.publishState)
    check("P06f 发布页无控件越界", overflow("publish_1360") == [], overflow("publish_1360")[:3])

    # -------------------------------- P07 全部处理后 → 门禁全绿（判别力）
    model.setPage("proofread")
    QTest.qWait(300)
    for _ in range(12):
        if model.reviewUnresolved == 0:
            break
        tf2 = proofread_field()
        if tf2 is None:
            break
        if not str(tf2.property("text") or "").strip():
            tf2.setProperty("text", "/aɪ/")
        app.processEvents()
        click_button_near(tf2)
        QTest.qWait(260)
    check("P07pre 关键问题清零（关键项必须修正，不可接受缺失）",
          model.proofreadCriticalUnresolved == 0 and model.reviewUnresolved == 0,
          (model.proofreadCriticalUnresolved, model.reviewUnresolved))
    model.runPublishMock()
    QTest.qWait(300)
    ok = sum(1 for g in model.publishGates if g["ok"])
    check("P07a 全部处理后 4/4 业务门禁通过（门禁随真实状态变化）",
          ok == 4, [(g["name"], g["ok"]) for g in model.publishGates])

    # ------------------------------------------------------ P08 弹窗不越界
    model.setPage("classroom")
    QTest.qWait(400)

    # ① 课程弹窗（含课件/课时两个列表 + 「进入课堂」）
    ok = click_button("选择课程")
    QTest.qWait(700)
    check("P08a 课程弹窗已打开", ok and any("选择课程与课时" in x for x in visible_texts()))
    out = overflow("course_dialog_1360")
    check("P08b 课程弹窗无控件越界", out == [], out[:3])
    check("P08c 「进入课堂」按钮全部落在窗口内（可达）",
          bool([b for b in _btns("进入课堂") if in_popup(b)]), "进入课堂")
    shot("v2_course_dialog_wide")
    closed = click_button("进入课堂")
    QTest.qWait(500)
    press_escape()
    QTest.qWait(400)

    # ② 老师选择弹窗（交付物 B：老师选择截图）
    # 宽/中档左栏按钮文案为「更换老师」，紧凑/窄档左条为「换老师」——两种都接受。
    ok = click_button("更换老师") or click_button("换老师")
    QTest.qWait(900)
    if not any("选择 AI 老师" in x for x in visible_texts()):
        ok2 = click_button("更换老师") or click_button("换老师")
        QTest.qWait(900)
        ok = ok or ok2
    check("P08d 老师弹窗已打开（老师选择）",
          any("选择 AI 老师" in x for x in visible_texts()),
          (closed, ok, [x for x in visible_texts() if "老师" in x][:4]))
    out = overflow("teacher_dialog_1360")
    check("P08e 老师弹窗无控件越界（弹窗确已打开）",
          any("选择 AI 老师" in x for x in visible_texts()) and out == [], out[:3])
    shot("v2_teacher_dialog_wide")
    click_button("取消")
    QTest.qWait(300)

    # ③ 高级设置弹窗
    ok = click_button("高级设置")
    QTest.qWait(600)
    out = overflow("advanced_dialog_1360")
    check("P08f 高级设置弹窗无控件越界", ok and out == [], (ok, out[:3]))
    shot("v2_advanced_dialog_wide")
    press_escape()
    QTest.qWait(300)

    # ------------------------------------------------------ P09 课堂页回归
    model.setPage("classroom")
    QTest.qWait(400)
    check("P09a 课堂页底栏可见（开始学习可达）", click_button("开始学习"), "开始学习")
    QTest.qWait(300)
    check("P09b 开始学习后进入讲解态", model.started and model.status == "讲解",
          (model.started, model.status))
    check("P09c 文字输入可用", (model.submitText("v2 pages probe") or True)
          and any("v2 pages probe" in t.get("text", "") for t in model.transcript))
    shot("v2_classroom_offline_demo_wide")

    # ------------------------------- P12 语音演练（Mock 双向对话 · 交付物 D）
    check("P12a 底栏含独立的「语音演练（Mock）」入口",
          bool(_btns("语音演练（Mock）")), [b.property("text") for b in _btns("语音演练（Mock）")])
    check("P12b 真实语音入口仍为不可用（不与 Mock 混淆）",
          bool(_btns("语音对话（不可用）")) and not model.speechAvailable,
          (bool(_btns("语音对话（不可用）")), model.speechAvailable))
    ok = click_button("语音演练（Mock）")
    QTest.qWait(800)
    vt = visible_texts()
    check("P12c 演练弹窗已打开且横幅声明不联网/本地预设",
          ok and any("演练模式（Mock）" in x for x in vt)
          and any("本地预设" in x for x in vt),
          (ok, [x for x in vt if "Mock" in x][:2]))
    out = overflow("voice_mock_dialog_1360")
    check("P12d 演练弹窗无控件越界", out == [], out[:3])
    shot("v2_voice_mock_before_wide")

    check("P12e 默认未启用（不自动冒充真实语音）", not model.voiceMockEnabled,
          model.voiceMockEnabled)
    ok = click_button("启用演练（Mock）")
    QTest.qWait(400)
    check("P12f 显式启用成功且模式=本地模拟(Mock)",
          ok and model.voiceMockEnabled and model.voiceMockModeLabel == "本地模拟(Mock)",
          (ok, model.voiceMockEnabled, model.voiceMockModeLabel))
    check("P12g 音频未采集（诚实标注 text-only）", model.voiceMockTextOnly,
          model.voiceMockTextOnly)

    n0 = model.voiceMockEventCount
    # 通过真实 GUI 输入 → 发送（一轮双向对话）
    ok = False
    _ph_seen = []
    for o in walk():
        try:
            if "TextField" not in o.metaObject().className():
                continue
            ph = o.property("placeholderText")
            _ph_seen.append((str(ph)[:30], bool(o.isVisible()), bool(o.property("enabled"))))
            if not o.isVisible():
                continue
            if isinstance(ph, str) and ph.startswith("输入学生在演练"):
                try:
                    real_click(o)
                    QTest.qWait(180)
                    type_text("hello")
                    QTest.qWait(180)
                    press_enter()
                    ok = True
                except Exception as _e:  # noqa: BLE001
                    _ph_seen.append(("EXC", repr(_e)[:120]))
                break
        except Exception:  # noqa: BLE001
            pass
    QTest.qWait(500)
    events = model.voiceMockEventLog()
    types = [e.get("type") for e in events]
    check("P12h GUI 发送触发一轮 Mock 双向事件（final_transcript→teacher_speaking→teacher_done）",
          ok and types[-3:] == ["final_transcript", "teacher_speaking", "teacher_done"],
          (ok, types[-4:], _ph_seen))
    check("P12i 事件日志条数递增且含真实文本",
          len(events) == n0 + 3
          and any(e.get("text") == "hello" for e in events)
          and any("hello" in str(e.get("text") or "") for e in events),
          (n0, len(events)))
    check("P12j GUI 显示老师回复（本地预设/回显，含 Mock 声明）",
          ("Mock" in model.voiceMockReply or "本地预设" in model.voiceMockReply)
          and any("老师（Mock）：" in x for x in visible_texts()),
          model.voiceMockReply[:60])
    check("P12k 会话状态回到 idle（一轮结束）", model.voiceMockState == "idle",
          model.voiceMockState)
    shot("v2_voice_mock_after_wide")
    EV["voice_mock"] = {"banner": model.voiceMockBanner, "mode": model.voiceMockModeLabel,
                        "state_after": model.voiceMockState, "reply": model.voiceMockReply,
                        "text_only": bool(model.voiceMockTextOnly),
                        "event_count": len(events), "events": events}
    click_button("关闭")
    QTest.qWait(300)

    # ------------------------------------------- P10 窄窗 620：五页零越界
    set_size(620, 620)
    for page in ("classroom", "library", "import", "proofread", "publish"):
        goto(page)
        out = overflow("narrow_" + page)
        check("P10.%s 620px 下无控件越界" % page, out == [], out[:3])
        if page != "classroom":
            shot("v2_%s_narrow620" % page)
    goto("library")
    shot("v2_library_narrow620")

    # 620 下课程弹窗同样不得越界（FIX01/FIX02 只测页面、从未测过弹窗）
    goto("classroom")
    ok = click_button("选择课程")
    QTest.qWait(700)
    out = overflow("course_dialog_620")
    check("P10.dlg 620px 课程弹窗无控件越界", ok and out == [], (ok, out[:3]))
    shot("v2_course_dialog_narrow620")
    press_escape()
    QTest.qWait(300)
    set_size(1360, 850)

    # ------------------------------------------- P11 断网：老师列表诚实降级
    model.refreshTeachers()
    QTest.qWait(500)
    check("P11a 未配置老师列表 → 诚实中文原因（不虚构在线老师）",
          "未启用" in model.teachersState or "未配置" in model.teachersState,
          model.teachersState)
    check("P11b 老师列表为空（不硬编码假老师）", len(model.teachers) == 0, len(model.teachers))

    # ------------------------------------------------------------ 汇总证据
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = [n for n, ok, _ in RESULTS if not ok]
    summary = {"artifact": "ui_pages_probe",
               "scope": "CLASSROOM V2 · DELIVERY GATE 02 · 页面探针（Agent B 开发自验）",
               "pages": EV["pages"], "checks": EV["checks"],
               "summary": {"total": len(RESULTS), "passed": passed,
                           "failed": len(failed), "failed_ids": failed},
               "note": "开发自验工具，**不构成**独立 QA（见 DELIVERY GATE 02 四）"}
    with open(os.path.join(logs, "ui_pages.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    # 交付物 D：Mock 双向对话的事件日志（GUI 实际驱动产生的真实事件流）
    if EV.get("voice_mock"):
        with open(os.path.join(logs, "voice_mock_event_log.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"artifact": "voice_mock_dialogue_event_log",
                       "source": "ui_pages_probe.py P12（真实 GUI 输入 → 发送）",
                       "honesty": "Mock 演练：不联网、不调用模型、不采集音频；"
                                  "回复为本地预设/回显",
                       **EV["voice_mock"]}, fh, ensure_ascii=False, indent=2)
    print("\n" + "=" * 72)
    print("UI_PAGES_PROBE: %d checks, %d PASS, %d FAIL" % (len(RESULTS), passed, len(failed)))
    if failed:
        print("FAILED:", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
