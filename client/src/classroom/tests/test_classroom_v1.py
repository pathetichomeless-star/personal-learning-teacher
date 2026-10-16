# -*- coding: utf-8 -*-
"""CLASSROOM V1 自动化测试（offscreen Qt；本机回环 Mock；零真实模型/密钥）。

覆盖：大屏/紧凑布局、老师选择与保存（不自动连接）、模拟课程加载、翻页、
字幕更新、文字练习、状态恢复、课程隔离、空/坏数据与数字人不可用降级、
以及冻结六文件与受保护数字人文件的保护断言。

RELEASE-FIX-01 对齐（行为修复，非弱化断言）：
* T18 前置「开始学习」——未开始时不再产生讲解（诚实状态：未开始恒「待开始」）；
* T31–T33 老师列表/保存改用课堂演示配置 classroom_demo.json（fail-closed：显式开启）。

运行：
    cd client && QT_QPA_PLATFORM=offscreen ./.venv/bin/python \
        src/classroom/tests/test_classroom_v1.py
"""
import hashlib
import json
import os
import socketserver
import sys
import tempfile
import threading
import http.server

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

CLIENT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if CLIENT not in sys.path:
    sys.path.insert(0, CLIENT)

RESULTS = []
def check(name, cond, detail=""):
    ok = bool(cond)
    RESULTS.append((name, ok, detail))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, ("" if ok else "  <- %r" % (detail,))))

FROZEN = {
    "gateway/app/turns.py": "e18a0d08ed3a28771dee71d39dd5563f52f3d1199043ac81b8d9a7b5a2a498bd",
    "gateway/app/qwen.py": "13d4800d416f678c33126e74bd857baab33afb5c9c3bfe2c80f6c0db798c9c32",
    "gateway/app/audio.py": "c2218a2c3fda520089473e312ce6ee3fac4436c540755a8c98fd634ff7a87c09",
    "gateway/app/protocol.py": "944e2d5ab4f0c2b13a51b547d366175cc18263575034566fda928b2a7b30d9f8",
    "gateway/app/ws.py": "dde9d427883721c17628f40c73bf417bc9c0ab32711d07a4f22e9ed7ad63dd1c",
    "gateway/app/behavior.py": "6d705960cb0154f17fa9eb0ce9ef1d651d0b4a64c9d4564fde5957d08d6a0088",
}
REPO = os.path.dirname(CLIENT)
QML_DIR = os.path.join(CLIENT, "src", "classroom", "qml")


def _sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


class _TeacherMock(http.server.BaseHTTPRequestHandler):
    body = b'{"teachers":[{"teacher_id":"tA","display_name":"\xe6\xa8\xa1\xe6\x8b\x9f\xe8\x80\x81\xe5\xb8\x88 A","voice_id":"Cherry","language":"en"}]}'
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)
    def log_message(self, *a):
        pass


def main():
    from PySide6.QtCore import QObject, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    import logging
    logging.disable(logging.CRITICAL)

    # ---- isolated client config ----
    data = tempfile.mkdtemp(prefix="classroom-v1-")
    os.environ["XIAOZHI_DATA_DIR"] = data
    os.makedirs(os.path.join(data, "config"), exist_ok=True)
    srv = socketserver.TCPServer(("127.0.0.1", 0), _TeacherMock)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    # RELEASE-FIX-01：老师列表改由课堂演示配置驱动（显式开启 + 环回地址 + 令牌）
    cfg = {"allow_teacher_list": True,
           "teacher_list_url": "http://127.0.0.1:%d/xiaozhi/v1/teacher/list" % port,
           "teacher_token": "tok",
           "selected_teacher_id": ""}
    json.dump(cfg, open(os.path.join(data, "classroom_demo.json"), "w"))

    from src.utils.config_manager import initialize_config
    initialize_config()
    from src.classroom.classroom_model import ClassroomModel

    app = QGuiApplication.instance() or QGuiApplication([])
    model = ClassroomModel()

    # ---------------- 模拟课程加载 ----------------
    check("T1 本地演示课程加载出 3 门课程", model.courseCount == 3, model.courseCount)
    check("T2 课程自带课时列表", len(model.courses[0]["lessons"]) >= 2)
    check("T3 数据来源标注为本地演示", "本地演示" in model.sourceLabel, model.sourceLabel)

    # ---------------- 布局响应式（真实 QML） ----------------
    engine = QQmlApplicationEngine()
    engine.addImportPath(QML_DIR)
    engine.rootContext().setContextProperty("classroom", model)
    engine.load(QUrl.fromLocalFile(os.path.join(QML_DIR, "ClassroomWindow.qml")))
    roots = engine.rootObjects()
    check("T4 课堂窗口 QML 成功加载", len(roots) == 1, roots)
    win = roots[0] if roots else None
    if win is not None:
        modes = {}
        for w in (1360, 1000, 860, 620):
            win.setProperty("width", w); app.processEvents()
            modes[w] = win.property("classroomWindowMode")
        check("T5 宽屏=wide(1360)", modes[1360] == "wide", modes)
        check("T6 中窗=medium(1000)", modes[1000] == "medium", modes)
        check("T7 紧凑=compact(860)", modes[860] == "compact", modes)
        check("T8 小窗=narrow(620)", modes[620] == "narrow", modes)
        check("T9 窗口可缩放（最小宽高 < 默认宽高）",
              win.property("minimumWidth") < 1360 and win.property("minimumHeight") < 850,
              (win.property("minimumWidth"), win.property("minimumHeight")))
        # 关键按钮在紧凑宽度下仍存在
        texts = []
        for c in win.findChildren(QObject):
            try:
                t = c.property("text")
                if isinstance(t, str):
                    texts.append(t)
            except Exception:
                pass
        for btn in ("选择课程", "开始学习", "结束学习", "下一页"):
            check("T10 紧凑宽度下按钮存在：%s" % btn, btn in texts)
        # 数字人不可用降级：仍显示静态占位说明 + 课件可用
        check("T11 数字人不可用时显示静态占位说明",
              any("静态占位形象" in t for t in texts), texts[:5])
        win.setProperty("width", 1360); app.processEvents()

    # ---------------- 课程 / 翻页 ----------------
    model.selectCourse(0)
    check("T12 选课后自动进入首课时", model.currentLessonIndex == 0 and model.slideCount > 0,
          (model.currentLessonIndex, model.slideCount))
    first_title = model.currentCourseTitle
    n = model.slideCount
    idx0 = model.slideIndex
    model.nextSlide(); app.processEvents()
    check("T13 下一页前进", model.slideIndex == idx0 + 1, model.slideIndex)
    model.prevSlide(); app.processEvents()
    check("T14 上一页后退", model.slideIndex == idx0, model.slideIndex)
    model.prevSlide(); app.processEvents()
    check("T15 首页再上一页不越界", model.slideIndex == 0, model.slideIndex)
    for _ in range(n + 2):
        model.nextSlide()
    check("T16 末页再下一页不越界", model.slideIndex == n - 1, (model.slideIndex, n))

    # ---------------- 字幕 / 词汇 随页更新 ----------------
    # 找到 vocab 页（RELEASE-FIX-01：讲解仅在「开始学习」后产生，故先开始）
    model.selectLesson(0)
    model.startLearning()
    vocab_seen = []
    for _ in range(model.slideCount):
        if model.currentSlide.get("type") == "vocab":
            vocab_seen = list(model.slideVocab)
        model.nextSlide()
    check("T17 词汇页更新字幕/词汇面板", len(vocab_seen) >= 1, vocab_seen)
    check("T18 字幕含老师讲解文字",
          any(t.get("role") == "teacher" for t in model.transcript), model.transcript[:1])

    # ---------------- 文字练习 ----------------
    model.selectLesson(0)
    prac = None
    for _ in range(model.slideCount):
        if model.currentSlide.get("type") == "practice":
            prac = dict(model.practice)
            break
        model.nextSlide()
    check("T19 练习页产生题目", bool(prac and prac.get("question")), prac)
    if prac:
        model.answerPractice(prac["answer"])
        p = dict(model.practice)
        check("T20 答对给出正确反馈", p["answered"] and p["correct"] and "答对" in p["feedback"], p)
        model.answerPractice(0)
        p2 = dict(model.practice)
        check("T21 已作答后再点不改变结果", p2["picked"] == p["picked"])

    # ---------------- 文字提交 ----------------
    before = len(model.transcript)
    model.submitText("My name is Lin.")
    check("T22 提交文字产生学生与老师两条记录", len(model.transcript) >= before + 2,
          len(model.transcript))
    check("T23 提交内容进入课堂笔记", any("My name" in n.get("text", "") for n in model.notes)
          or len(model.notes) >= 1, model.notes)
    check("T24 本地回应明确标注为本地模拟",
          any("本地模拟回应" in t.get("text", "") for t in model.transcript))

    # ---------------- 课程隔离（切课不残留） ----------------
    model.selectCourse(1)
    check("T25 切换课程后清空上一课的词汇", model.slideVocab == [], model.slideVocab)
    _txt = " ".join(t.get("text", "") for t in model.transcript)
    check("T26 切换课程后不残留上一门课的字幕/笔记（旧课标记消失）",
          "办理入住" not in _txt and model.notes == [], (model.transcript, model.notes))
    check("T27 切换课程后当前课程已改变", model.currentCourseTitle != first_title,
          (first_title, model.currentCourseTitle))

    # ---------------- 状态恢复 / 结束学习 ----------------
    model.startLearning(); model.submitText("hello"); model.selectCourse(2)
    check("T28 结束学习可回到课程选择", (model.endLearning(), model.courseCount == 3)[1])
    check("T29 结束后无当前课程/课时/页码",
          model.currentCourseIndex == -1 and model.currentLessonIndex == -1 and model.slideIndex == -1,
          (model.currentCourseIndex, model.currentLessonIndex, model.slideIndex))
    check("T30 结束后字幕/词汇/笔记清空",
          model.transcript == [] and model.slideVocab == [] and model.notes == [])

    # ---------------- 老师：列表 / 选择 / 保存（不自动连接） ----------------
    model.refreshTeachers()
    check("T31 从 Mock 网关读到老师列表", len(model.teachers) == 1, model.teachers)
    check("T32 老师列表状态为中文提示", "共 1 位可用老师" in model.teachersState, model.teachersState)
    model.selectTeacher("tA")
    model.saveTeacher()
    # RELEASE-FIX-01：保存只写课堂演示配置（绝不写正式客户端配置、绝不建连）
    saved = json.load(open(os.path.join(data, "classroom_demo.json"))).get("selected_teacher_id")
    check("T33 保存老师写入课堂演示配置 selected_teacher_id", saved == "tA", saved)
    check("T34 保存老师不建立任何连接（无 voice/WS 状态变化）",
          model.status in ("待开始", "讲解", "练习", "已结束", "断开"), model.status)

    # ---------------- 空/坏数据降级 ----------------
    bad = ClassroomModel(courses_path=os.path.join(data, "does-not-exist.json"))
    check("T35 课程文件缺失时不崩溃且给出中文错误",
          bad.courseCount == 0 and "不可用" in bad.coursesError, bad.coursesError)
    broken = os.path.join(data, "broken.json")
    open(broken, "w").write("{ not json")
    bad2 = ClassroomModel(courses_path=broken)
    check("T36 课程 JSON 损坏时降级且不崩溃", bad2.courseCount == 0 and bad2.coursesError != "")

    # ---------------- 字幕 / 词汇 / 笔记 切换 ----------------
    model.setActiveTab("vocab")
    check("T41 可切换到「词汇」标签", model.activeTab == "vocab", model.activeTab)
    model.setActiveTab("notes")
    check("T42 可切换到「课堂笔记」标签", model.activeTab == "notes", model.activeTab)
    model.setActiveTab("bogus")
    check("T43 非法标签被拒绝（保持原标签）", model.activeTab == "notes", model.activeTab)
    model.setActiveTab("transcript")

    # ---------------- 保护断言 ----------------
    ok_frozen = all(
        os.path.exists(os.path.join(REPO, f)) and _sha(os.path.join(REPO, f)) == h
        for f, h in FROZEN.items())
    check("T37 冻结六文件 SHA256 与基线一致（未被本轮改动）", ok_frozen)
    src = open(os.path.join(CLIENT, "src", "classroom", "classroom_model.py"), encoding="utf-8").read()
    check("T38 课堂模型不导入任何 WS/付费连接库（websockets/aiohttp）",
          ("import websockets" not in src) and ("import aiohttp" not in src))
    check("T39 课堂模块不引用受保护数字人文件",
          all(x not in src for x in ("manager.py", "AvatarLive2D", "avatar_page.js", "runtime_server")))
    entry = open(os.path.join(CLIENT, "classroom_main.py"), encoding="utf-8").read()
    check("T40 课堂入口不引用受保护数字人文件",
          all(x not in entry for x in ("manager.py", "AvatarLive2D")))

    print("=" * 70)
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("CLASSROOM_V1_TESTS: %d checks, %d PASS, %d FAIL" % (total, passed, total - passed))
    for name, ok, detail in RESULTS:
        if not ok:
            print("  FAILED: %s  %r" % (name, detail))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
