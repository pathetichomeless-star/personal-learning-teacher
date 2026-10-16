# -*- coding: utf-8 -*-
"""XIAOZHI V4 学生课堂 —— 视图模型（独立组件，不改动既有 GUI/数字人代码）。

RELEASE FIX 01 边界（fail-closed）：
* 纯本地：本模块**不建立任何 WebSocket / 语音连接**；不读取正式 py-xiaozhi 配置；
* 唯一的网络面是「本机 Mock 老师列表」，且必须同时满足（默认全部关闭）：
    allow_teacher_list=True（显式开启）＋ 环回地址 ＋ 部署令牌；
  任何缺失 / 损坏 / 伪造配置都降级为“不联网”，并给出明确中文原因；
* 老师选择只写入课堂演示配置 ``classroom_demo.json`` 的 ``selected_teacher_id``，
  **绝不写入正式客户端配置、绝不自动建立连接**；
* 课件数据来自随包分发的本地演示课程（``data/courses.json``），明确标注「本地演示」；
* 教学文字为**确定性本地脚本**（同一输入必得同一输出），且仅在「开始学习」之后产生
  讲解与状态迁移（未开始时状态恒为「待开始」）。

对外为单一 QObject（QML 上下文名 ``classroom``）。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Property, Signal, Slot, QObject

from src.classroom import classroom_env as cenv
from src.classroom import course_schema as cschema
from src.classroom import runtime_log
from src.classroom.learning_record import LearningRecordStore
from src.classroom.learning_position import LearningPositionStore
from src.classroom.voice_mock import VoiceMockSession as _VoiceMockSession

_HERE = os.path.dirname(os.path.abspath(__file__))
COURSES_PATH = os.path.join(_HERE, "data", "courses.json")
# 随包离线演示（由 tools/classroom_offline_pipeline.py 生成）
DEMO_DIR = os.path.join(_HERE, "data", "demo")
DEMO_LIBRARY_DIR = os.path.join(DEMO_DIR, "library")
DEMO_KB_SNAPSHOT = os.path.join(DEMO_DIR, "kb_snapshot", "knowledge.json")

# ---- V2 页面（Agent B · REV1B 画布落地）----
PAGE_CLASSROOM = "classroom"
PAGE_LIBRARY = "library"
PAGE_IMPORT = "import"
PAGE_PROOFREAD = "proofread"
PAGE_PUBLISH = "publish"
PAGES = (PAGE_CLASSROOM, PAGE_LIBRARY, PAGE_IMPORT, PAGE_PROOFREAD, PAGE_PUBLISH)

# 学生侧解析能力表（**本地事实**，不来自网络）。available 为假必须给出真实原因。
LOCAL_FORMATS = (
    {"ext": ".txt", "label": "纯文本", "available": True, "reason": ""},
    {"ext": ".md", "label": "Markdown", "available": True, "reason": ""},
    {"ext": ".pdf", "label": "PDF（文字型）", "available": True,
     "reason": "需本机解析服务（未开放）"},
    {"ext": ".docx", "label": "Word", "available": True, "reason": "需本机解析服务（未开放）"},
    {"ext": ".pptx", "label": "PowerPoint", "available": True, "reason": "需本机解析服务（未开放）"},
    {"ext": ".epub", "label": "EPUB（文字型）", "available": True, "reason": "需本机解析服务（未开放）"},
    {"ext": "图片/扫描件", "label": "扫描件 OCR", "available": False,
     "reason": "OCR 暂不支持（文字型解析已实现，扫描件需 OCR）"},
)

# 本机解析服务开放状态（**硬门禁**：独立安全复核通过前恒为关闭）
GATEWAY_OPEN = False
GATEWAY_BLOCKED_REASON = ("本机解析服务尚未开放：等待独立安全复核通过。"
                          "届时将经 /cls/knowledge/* 白名单提供服务。")

MODE_DEMO = "demo"
TAB_TRANSCRIPT = "transcript"
TAB_VOCAB = "vocab"
TAB_NOTES = "notes"

STATUS_IDLE = "待开始"
STATUS_TEACHING = "讲解"
STATUS_PRACTICE = "练习"
STATUS_ENDED = "已结束"
STATUS_DISCONNECTED = "断开"

EMPTY_PRACTICE = {"question": "", "options": [], "answer": -1, "answerUnknown": False,
                  "answered": False, "picked": -1, "feedback": "", "graded": False,
                  "correct": False}


class ClassroomModel(QObject):
    coursesChanged = Signal()
    lessonChanged = Signal()
    slideChanged = Signal()
    teachersChanged = Signal()
    transcriptChanged = Signal()
    practiceChanged = Signal()
    statusChanged = Signal()
    notesChanged = Signal()
    tabChanged = Signal()
    pageChanged = Signal()
    libraryChanged = Signal()
    importChanged = Signal()
    proofreadChanged = Signal()
    publishChanged = Signal()
    voiceMockChanged = Signal()

    ALLOWED_TABS = (TAB_TRANSCRIPT, TAB_VOCAB, TAB_NOTES)

    def __init__(self, parent=None, courses_path: str | None = None,
                 demo_config_path: Optional[str] = None, data_dir: Optional[str] = None):
        super().__init__(parent)
        self._path = courses_path or COURSES_PATH
        self._doc = {}
        self._courses: list[dict] = []
        self._load_error = ""
        self._course_i = -1
        self._lesson_i = -1
        self._slide_i = -1
        self._status = STATUS_IDLE
        self._started = False
        self._teachers: list[dict] = []
        self._teachers_state = ""
        self._selected_teacher = ""
        self._transcript: list[dict] = []
        self._vocab: list[dict] = []
        self._notes: list[dict] = []
        self._tab = TAB_TRANSCRIPT
        self._practice = dict(EMPTY_PRACTICE)
        # 课堂演示配置路径：显式指定 > 由隔离目录解析（惰性）；不可解析时联网恒关闭
        self._data_dir: Optional[Path] = Path(data_dir).expanduser() if data_dir else None
        self._demo_cfg_path: Optional[Path] = Path(demo_config_path).expanduser() \
            if demo_config_path else None
        # ---- V2 页面态（REV1B 落地；FIX01-P2-1：默认停在「我的书库」）----
        self._page = PAGE_LIBRARY
        self._library: list[dict] = []
        self._library_error = ""
        self._import_state = "blocked"          # blocked | done | error
        self._import_stages: list[dict] = []
        self._import_message = GATEWAY_BLOCKED_REASON
        self._demo_manifest: dict = {}
        self._draft: dict = {}                  # 当前校对中的课程（来自书库条目）
        self._draft_kb_snapshot = ""            # 该课程来源所在的知识库快照路径
        self._draft_source_manifest: dict = {}
        self._proofread_entries: list[dict] = []  # FIX01-P1-2：可编辑校对条目
        self._proofread_state = ""
        self._proofread_log: list[dict] = []
        self._publish_gates: list[dict] = []
        self._publish_log: list[dict] = []
        self._publish_state = "未开始"
        # ---- 语音演练（Mock，显式启用；默认关闭，绝不冒充真实语音）----
        self._vm = None                          # VoiceMockSession | None
        self._vm_reply = ""
        self._vm_error = ""
        # ---- 学习记录 / 学习位置（HUMAN_GUI_ACCEPTANCE_FIX01 · P1-1）----
        # 真实落盘到课堂隔离目录；损坏安全降级；course_id 为归属键（本地单用户）。
        self._records: Optional[LearningRecordStore] = None
        self._records_error = ""
        self._positions: Optional[LearningPositionStore] = None
        self._restore_banner = ""                # 恢复上次学习位置时的可见提示
        self._load_courses()
        self._refresh_library()

    # ------------------------------------------------------------------ 课程
    def _load_courses(self) -> None:
        """加载课程 bundle 并**按冻结契约 v1 校验**（PHASE2 CONTRACT FIX 01 · 修正②）。

        fail-closed：契约违规时**不静默**载入部分数据，而是清空课程并给出中文原因
        （经 ``coursesError`` 暴露）。未知 ``version`` / 未知 ``slide.type`` /
        伪造知识库来源 / 来源绑定缺失 等一律在此拦下。
        """
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                self._doc = json.load(f)
        except Exception as e:  # noqa: BLE001
            self._doc = {}
            self._courses = []
            self._load_error = "课程数据不可用：%s" % type(e).__name__
            return

        violations = cschema.validate_bundle(self._doc)
        if violations:
            self._courses = []
            self._load_error = "课程数据不符合契约 v1：%s" % violations[0]
            return

        self._courses = list(self._doc.get("courses") or [])
        self._load_error = ""

    @Property("QVariantList", notify=coursesChanged)
    def courses(self):
        """QML 视图。**键名保持 ``id``**（QML 兼容，属 Agent B 域，本轮不改 QML）；
        值取自契约 v1 的 ``course_id``。另暴露来源徽标所需字段（设计规范 §7）。
        """
        return [{"index": i, "id": c.get("course_id"), "title": c.get("title") or "",
                 "subject": c.get("subject") or "", "level": c.get("level") or "",
                 "description": c.get("description") or "",
                 "source": c.get("source") or "",
                 "revision": c.get("revision") or 0,
                 "sourceDocId": c.get("source_doc_id") or "",
                 "fileHash": cschema.file_hash_display(c.get("source_file_sha256")),
                 "lessons": [{"index": j, "id": l.get("lesson_id"), "title": l.get("title") or ""}
                             for j, l in enumerate(c.get("lessons") or [])]}
                for i, c in enumerate(self._courses)]

    @Property(int, notify=coursesChanged)
    def courseCount(self):
        return len(self._courses)

    @Property(str, notify=coursesChanged)
    def coursesError(self):
        return self._load_error

    @Property(str, constant=True)
    def sourceLabel(self):
        return str(self._doc.get("label") or "本地演示课程")

    @Property(str, constant=True)
    def sourceNotice(self):
        return str(self._doc.get("notice") or "")

    # -------------------------------------------------------------- 当前课/课时
    def _course(self):
        if 0 <= self._course_i < len(self._courses):
            return self._courses[self._course_i]
        return None

    def _lessons(self):
        c = self._course()
        return (c.get("lessons") or []) if c else []

    def _lesson(self):
        ls = self._lessons()
        if 0 <= self._lesson_i < len(ls):
            return ls[self._lesson_i]
        return None

    def _slides(self):
        l = self._lesson()
        return (l.get("slides") or []) if l else []

    @Property(int, notify=lessonChanged)
    def currentCourseIndex(self):
        return self._course_i

    @Property(str, notify=lessonChanged)
    def currentCourseTitle(self):
        c = self._course()
        return (c.get("title") or "") if c else ""

    @Property(int, notify=lessonChanged)
    def lessonCount(self):
        return len(self._lessons())

    @Property(int, notify=lessonChanged)
    def currentLessonIndex(self):
        return self._lesson_i

    @Property(str, notify=lessonChanged)
    def currentLessonTitle(self):
        l = self._lesson()
        return (l.get("title") or "") if l else ""

    @Property("QVariantList", notify=lessonChanged)
    def lessons(self):
        return [{"index": j, "id": l.get("lesson_id"), "title": l.get("title") or ""}
                for j, l in enumerate(self._lessons())]

    # ------------------------------------------------------------------ 幻灯片
    @Property(int, notify=slideChanged)
    def slideIndex(self):
        return self._slide_i

    @Property(int, notify=slideChanged)
    def slideCount(self):
        return len(self._slides())

    def _slide(self):
        sl = self._slides()
        if 0 <= self._slide_i < len(sl) and isinstance(sl[self._slide_i], dict):
            return sl[self._slide_i]
        return {}

    @Property("QVariantMap", notify=slideChanged)
    def currentSlide(self):
        return self._slide()

    @Property(str, notify=slideChanged)
    def currentStepLabel(self):
        n = len(self._slides())
        if n == 0:
            return "尚未选择课时"
        return "教学步骤 %d / %d" % (self._slide_i + 1, n)

    # -------------------------------------------------------------------- 老师
    @Property("QVariantList", notify=teachersChanged)
    def teachers(self):
        return list(self._teachers)

    @Property(str, notify=teachersChanged)
    def teachersState(self):
        return self._teachers_state

    @Property(str, notify=teachersChanged)
    def selectedTeacherId(self):
        return self._selected_teacher

    def _teacher_row(self):
        for t in self._teachers:
            if t.get("teacher_id") == self._selected_teacher:
                return t
        return {}

    @Property("QVariantMap", notify=teachersChanged)
    def selectedTeacher(self):
        return self._teacher_row()

    @Property(str, notify=teachersChanged)
    def selectedTeacherName(self):
        t = self._teacher_row()
        return str(t.get("display_name") or (self._selected_teacher or "未选择老师"))

    @Property(str, constant=True)
    def narratorLabel(self):
        """P2-4：讲解身份诚实标注——未选择真实老师时明确为「本地文字演示」。"""
        t = self._teacher_row()
        if t.get("display_name"):
            return "老师：%s（本地文字演示，非真实语音）" % t.get("display_name")
        return "本地文字演示（未选择 AI 老师）"

    # -------------------------------------------------------------------- 状态
    @Property(str, notify=statusChanged)
    def status(self):
        return self._status

    @Property(bool, notify=statusChanged)
    def started(self):
        return self._started

    @Property(bool, constant=True)
    def speechAvailable(self):
        # 本轮无真实实时模型接入：语音入口恒定不可用（诚实标注，不用 1006 掩盖）
        return False

    @Property(str, constant=True)
    def speechUnavailableReason(self):
        return self._speech_unavailable_reason()

    @Property(str, constant=True)
    def modeLabel(self):
        return "本地演示"

    # ================================================== 语音演练（Mock 双向对话）
    # 硬边界：**不是**真实 AI 语音、不联网、不调用任何模型。
    # 演练必须由使用者显式启用；未启用时下方按钮不可达，页面只显示真实不可用原因。
    @Property(str, constant=True)
    def voiceMockBanner(self):
        return ("演练模式（Mock）：不联网、不调用任何真实模型、不采集麦克风音频；"
                "老师回复为「本地预设/回显」，不代表 AI 理解能力，也不产生真实语音。")

    @Property(str, constant=True)
    def voiceMockBlockedReason(self):
        return self._speech_unavailable_reason()

    @Property(bool, notify=voiceMockChanged)
    def voiceMockEnabled(self):
        return self._vm is not None

    @Property(str, notify=voiceMockChanged)
    def voiceMockState(self):
        return self._vm.state if self._vm is not None else "未启用"

    @Property(str, notify=voiceMockChanged)
    def voiceMockModeLabel(self):
        return self._vm.mode_label() if self._vm is not None else "未启用"

    @Property(str, notify=voiceMockChanged)
    def voiceMockReply(self):
        return self._vm_reply

    @Property(str, notify=voiceMockChanged)
    def voiceMockError(self):
        return self._vm_error

    @Property(str, notify=voiceMockChanged)
    def voiceMockTextOnly(self):
        return bool(self._vm is not None and self._vm.text_only)

    @Property("QVariantList", notify=voiceMockChanged)
    def voiceMockEvents(self):
        return list(self._vm.events) if self._vm is not None else []

    @Property(int, notify=voiceMockChanged)
    def voiceMockEventCount(self):
        return len(self._vm.events) if self._vm is not None else 0

    def _vm_canned(self) -> dict:
        """当前课件的词汇 → 本地预设回复（不生成新内容、不联网）。"""
        out: dict[str, str] = {}
        for v in (self._vocab or []):
            en = str(v.get("en") or "").strip().lower()
            cn = str(v.get("cn") or "").strip()
            if en:
                out[en] = "（本地预设回复，非 AI 生成）%s —— %s" % (v.get("en"), cn)
        return out

    @Slot()
    def voiceMockEnable(self):
        """显式启用演练（本地模拟；永不走 real-online）。"""
        if self._vm is None:
            self._vm = _VoiceMockSession(mode="local-mock", mic_granted=False)
            self._vm_reply = ""
            self._vm_error = ""
            self.voiceMockChanged.emit()

    @Slot()
    def voiceMockDisable(self):
        self._vm = None
        self._vm_reply = ""
        self._vm_error = ""
        self.voiceMockChanged.emit()

    @Slot()
    def voiceMockReset(self):
        if self._vm is not None:
            self._vm = _VoiceMockSession(mode="local-mock", mic_granted=False)
        self._vm_reply = ""
        self._vm_error = ""
        self.voiceMockChanged.emit()

    @Slot(str)
    def voiceMockSend(self, text: str):
        """一轮 Mock 双向对话（用户 → 老师）。**不发网络请求**。"""
        if self._vm is None:
            self._vm_error = "演练未启用"
            self.voiceMockChanged.emit()
            return
        t = str(text or "").strip()
        if not t:
            self._vm_error = "请输入要演练的内容"
            self.voiceMockChanged.emit()
            return
        res = self._vm.roundtrip(t, canned=self._vm_canned())
        if res.get("ok"):
            self._vm_reply = str(res.get("reply") or "")
            self._vm_error = ""
        else:
            self._vm_reply = ""
            self._vm_error = str(res.get("reason") or "")
        self.voiceMockChanged.emit()

    @Slot(result="QVariantList")
    def voiceMockEventLog(self):
        """事件日志（带时间戳；GUI 与证据共用同一份真实数据）。"""
        if self._vm is None:
            return []
        return [{"at": _now_ts(), **dict(e)} for e in self._vm.events]

    def _speech_unavailable_reason(self) -> str:
        return ("当前为本地演示课堂：未接入真实实时语音模型，语音不可用；"
                "文字学习与课件浏览正常。")

    # ------------------------------------------------------------ 文字/字幕
    @Property("QVariantList", notify=transcriptChanged)
    def transcript(self):
        return list(self._transcript)

    @Property("QVariantList", notify=slideChanged)
    def slideVocab(self):
        return list(self._vocab)

    @Property("QVariantList", notify=notesChanged)
    def notes(self):
        return list(self._notes)

    @Property(str, notify=tabChanged)
    def activeTab(self):
        return self._tab

    # -------------------------------------------------------------------- 练习
    @Property("QVariantMap", notify=practiceChanged)
    def practice(self):
        return dict(self._practice)

    @Property(bool, notify=practiceChanged)
    def hasPractice(self):
        return bool(self._practice.get("question"))

    # =================================================================== Slots
    @Slot(int)
    def selectCourse(self, index: int):
        if not (0 <= index < len(self._courses)):
            return
        self._course_i = index
        self._lesson_i = -1
        self._reset_lesson_state()
        self.lessonChanged.emit()
        # P1-1：优先恢复该课程保存的学习位置（无保存位置才进第一课时）
        self._apply_saved_position(self._course())
        if self._lesson_i < 0 and self._lessons():
            # 默认自动进入第一课时，减少普通用户操作步数
            self.selectLesson(0)
        elif self._lesson_i < 0:
            self.coursesChanged.emit()
        self.notesChanged.emit()

    @Slot(int)
    def selectLesson(self, index: int):
        ls = self._lessons()
        if not (0 <= index < len(ls)):
            return
        self._lesson_i = index
        self._reset_lesson_state()
        self.lessonChanged.emit()
        if self._slides():
            self._goto_slide(0)
        self.slideChanged.emit()

    def _reset_lesson_state(self):
        self._slide_i = -1
        self._vocab = []
        self._notes = []
        self._transcript = []
        self._practice = dict(EMPTY_PRACTICE)
        self.practiceChanged.emit()
        self.notesChanged.emit()
        self.transcriptChanged.emit()
        self.statusChanged.emit()

    def _goto_slide(self, index: int):
        sl = self._slides()
        if not (0 <= index < len(sl)):
            return
        # R2-3：用户翻页即视为「恢复提示已完成使命」，避免横幅残留造成误解。
        # 时序说明：恢复位置时先经此处清空、随后 _apply_saved_position 再写入提示，
        # 因此不会吞掉「已恢复上次学习位置」横幅本身。
        if self._restore_banner:
            self._restore_banner = ""
            self.notesChanged.emit()
        self._slide_i = index
        self._practice = dict(EMPTY_PRACTICE)
        self.practiceChanged.emit()
        self._enter_slide_content()
        # P1-1：学习进行中真实持久化「学到哪里」（原子写、按课程隔离）
        if self._started:
            c, l = self._course(), self._lesson()
            pos = self._position_store()
            if pos is not None and c is not None:
                try:
                    pos.save(course_id=str(c.get("course_id") or ""),
                             lesson_id=str((l or {}).get("lesson_id") or ""),
                             lesson_index=self._lesson_i, slide_index=self._slide_i,
                             title=str(c.get("title") or ""))
                except Exception:  # noqa: BLE001 —— 位置保存失败不影响学习
                    pass
            self.slideChanged.emit()
        if self._started:
            self._narrate_current_slide()

    def _enter_slide_content(self):
        """进入页面时的课件内容准备（词汇/练习装载；与是否已开始无关）。"""
        s = self._slide()
        t = str(s.get("type") or "")
        if t == "vocab":
            self._push_vocab(str(s.get("word") or ""), str(s.get("phonetic") or ""),
                             str(s.get("meaning") or ""))
        elif t == "practice":
            opts = [str(o) for o in (s.get("options") or [])]
            raw = s.get("answer")
            # 契约 C5：answer 缺失/非法 ⇒ 「答案待人工确认」，**不得落 -1 静默错判**
            unknown = not isinstance(raw, int) or isinstance(raw, bool) \
                or not (0 <= raw < len(opts))
            self._practice = {"question": str(s.get("question") or ""), "options": opts,
                              "answer": (-1 if unknown else int(raw)),
                              "answerUnknown": bool(unknown),
                              "answered": False, "picked": -1, "feedback": "",
                              "graded": False, "correct": False,
                              "explain": str(s.get("explain") or "")}
            self.practiceChanged.emit()

    def _narrate_current_slide(self, force: bool = False):
        """老师讲解 + 状态迁移 —— 仅在课堂已开始后调用（诚实状态：未开始恒「待开始」）。

        force=True：用户主动「重复讲解」——绕过 R2-4 去重，正常再次显示。
        """
        s = self._slide()
        t = str(s.get("type") or "")
        if t == "cover":
            pts = "；".join(str(p) for p in (s.get("points") or []))
            self._teacher_say("本课我们学习「%s」。%s"
                              % (s.get("title") or "",
                                 ("要点：%s。" % pts) if pts
                                 else "本页课件未提供要点清单。"), force=force)
            self._status = STATUS_TEACHING
        elif t == "vocab":
            w = str(s.get("word") or "")
            ph = str(s.get("phonetic") or "").strip()
            self._teacher_say("看这个单词 %s%s，意思是「%s」。例句：%s（%s）"
                              % (w, (" " + ph) if ph else "（课件未提供音标，不编造）",
                                 s.get("meaning") or "",
                                 s.get("en") or "", s.get("cn") or ""), force=force)
            self._status = STATUS_TEACHING
        elif t == "sentence":
            note = str(s.get("note") or "").strip()
            self._teacher_say("%s —— %s。%s" % (s.get("en") or "", s.get("cn") or "",
                                                note if note else ""), force=force)
            self._status = STATUS_TEACHING
        elif t == "practice":
            self._teacher_say("我们做一个小练习：%s（请选择下方答案）" % (s.get("question") or ""),
                              force=force)
            self._status = STATUS_PRACTICE
        elif t == "summary":
            pts = "；".join(str(p) for p in (s.get("points") or []))
            self._teacher_say("本课小结：%s" % (pts if pts else "（课件未提供小结要点）"),
                              force=force)
            self._append_summary_stats(force=force)
            self._status = STATUS_TEACHING
        self.statusChanged.emit()

    def _append_summary_stats(self, force: bool = False):
        """P2-9：小结时播报本课答题情况、错题与复习建议（来自真实落盘记录）。"""
        store = self._record_store()
        c, l = self._course(), self._lesson()
        if store is None or c is None:
            return
        cid = str(c.get("course_id") or "")
        lid = str((l or {}).get("lesson_id") or "")
        rows = [r for r in store.for_course(cid)
                if (not lid or r.get("lesson_id") == lid)
                and r.get("result") in ("correct", "wrong", "ungraded")]
        if not rows:
            self._teacher_say("（本课时还没有练习作答记录。）", force=force)
            return
        n_ok = sum(1 for r in rows if r.get("result") == "correct")
        wrongs = [r for r in rows if r.get("result") == "wrong"]
        self._teacher_say("（答题情况：共作答 %d 题，答对 %d 题，答错 %d 题。）"
                          % (len(rows), n_ok, len(wrongs)), force=force)
        if wrongs:
            names = "；".join((r.get("prompt") or "题目")[:24] for r in wrongs[:3])
            more = "（另有 %d 题未列出）" % (len(wrongs) - 3) if len(wrongs) > 3 else ""
            self._teacher_say("（需要复习：%s。建议明天先看错题再继续新内容。%s）"
                              % (names, more))
        else:
            self._teacher_say("（全部答对，可以直接进入下一课。）", force=force)

    def _teacher_say(self, text: str, force: bool = False):
        # R2-4：字幕去重覆盖 A→B→A 往返翻页——同一课时内**同文本**讲解不重复追加
        # （不只比较最后一条）；用户主动「重复讲解」与本地回应走 force=True，
        # 不受去重影响。_transcript 在切换课时/结束学习时清空，去重范围=本课时。
        if not force:
            for item in self._transcript:
                if item.get("role") == "teacher" and item.get("text") == text:
                    return
        self._transcript.append({"role": "teacher", "text": text})
        self.transcriptChanged.emit()

    def _student_say(self, text: str):
        self._transcript.append({"role": "student", "text": text})
        self.transcriptChanged.emit()

    def _push_vocab(self, word, phonetic, meaning):
        if word and not any(v.get("word") == word for v in self._vocab):
            self._vocab.append({"word": word, "phonetic": phonetic, "meaning": meaning})
            self.slideChanged.emit()

    @Slot()
    def startLearning(self):
        """开始学习：此后才产生讲解与「讲解/练习」状态（未开始恒「待开始」）。"""
        if not self._slides():
            return
        if self._started:
            return
        self._started = True
        if self._slide_i < 0:
            self._goto_slide(0)
        else:
            self._teacher_say("我们开始吧。")
            self._narrate_current_slide()
        self.statusChanged.emit()
        self.slideChanged.emit()

    @Slot()
    def nextSlide(self):
        if self._slide_i + 1 < len(self._slides()):
            self._goto_slide(self._slide_i + 1)
            self.slideChanged.emit()

    @Slot()
    def prevSlide(self):
        if self._slide_i > 0:
            self._goto_slide(self._slide_i - 1)
            self.slideChanged.emit()

    @Slot()
    def repeatSlide(self):
        """重复讲解：仅课堂已开始后有效（未开始不产生讲解）。

        R2-4：主动「重复讲解」为用户明确请求，绕过字幕去重正常显示。
        """
        if not self._started:
            return
        self._narrate_current_slide(force=True)
        self.slideChanged.emit()

    @Slot(str)
    def submitText(self, text: str):
        text = (text or "").strip()
        if not text:
            return
        self._student_say(text)
        self._notes.append({"text": text})
        self.notesChanged.emit()
        self._record_learning("note", prompt=text, answer="", result="")
        # 确定性本地回应（非大模型）：引用当前页重点
        s = self._slide()
        key = ""
        if s.get("type") == "vocab":
            key = str(s.get("word") or "")
        hint = ("很好，你写了「%s」。跟我读一遍：" % text) if not key else \
               ("很好，你写了「%s」。这一页的重点词是 %s，试着用它造句。" % (text, key))
        # R2-4：这是对学生本次提交的即时回应，不属于「页面讲解」，不走去重
        self._teacher_say("（本地模拟回应）" + hint, force=True)
        if self._started:  # 未开始时不得把状态改成「讲解/练习」
            self._status = STATUS_PRACTICE if self.hasPractice else STATUS_TEACHING
            self.statusChanged.emit()

    @Slot(int)
    def answerPractice(self, option_index: int):
        if not self.hasPractice or self._practice.get("answered"):
            return
        opts = self._practice.get("options") or []
        if not (0 <= option_index < len(opts)):
            return
        # 契约 C5：答案未知时**不判分、不判错**，只记录并显式提示（不得静默判错）
        if self._practice.get("answerUnknown"):
            self._practice["picked"] = option_index
            self._practice["answered"] = True
            self._practice["graded"] = False
            self._practice["correct"] = False
            self._practice["feedback"] = "答案待人工确认，本次不计分、不判错。"
            # R2-4：对本次作答的即时判定反馈，不走去重（「再试一次」重复作答时必须再次可见）
            self._teacher_say("（本地判定）" + self._practice["feedback"], force=True)
            self._notes.append({"text": "练习作答：%s → 答案待人工确认（未判分）"
                                        % opts[option_index]})
            self.notesChanged.emit()
            self._record_learning("note", prompt=self._practice.get("question") or "",
                                  answer=opts[option_index], result="ungraded")
            self.practiceChanged.emit()
            return
        correct = (option_index == int(self._practice.get("answer", -1)))
        self._practice["picked"] = option_index
        self._practice["answered"] = True
        self._practice["graded"] = True
        self._practice["correct"] = correct
        self._practice["feedback"] = ("答对了！" if correct else "再想想～") + \
            ("解析：" + str(self._practice.get("explain") or ""))
        # R2-4：对本次作答的即时判定反馈，不走去重（「再试一次」重复作答时必须再次可见）
        self._teacher_say("（本地判定）" + self._practice["feedback"], force=True)
        self._notes.append({"text": "练习作答：%s → %s" % (opts[option_index], "正确" if correct else "需复习")})
        self.notesChanged.emit()
        # P1-1：错题/正确作答真实落盘（错题跨重启保存；按课程/课时隔离）
        self._record_learning("mistake" if not correct else "note",
                              prompt=self._practice.get("question") or "",
                              answer=opts[option_index],
                              result="wrong" if not correct else "correct")
        self.practiceChanged.emit()

    @Slot()
    def retryPractice(self):
        """答错后「再试一次」：仅清除本次作答状态；错题记录保留（已入复习清单）。"""
        if not self.hasPractice or not self._practice.get("answered"):
            return
        if self._practice.get("graded") and self._practice.get("correct"):
            return
        self._practice["answered"] = False
        self._practice["picked"] = -1
        self._practice["feedback"] = ""
        self._practice["graded"] = False
        self._practice["correct"] = False
        self.practiceChanged.emit()

    @Slot(str)
    def setActiveTab(self, name: str):
        if name in self.ALLOWED_TABS and name != self._tab:
            self._tab = name
            self.tabChanged.emit()

    @Slot()
    def endLearning(self):
        self._started = False
        self._status = STATUS_ENDED
        self._notes = []
        self._vocab = []
        self._transcript = []
        self._practice = dict(EMPTY_PRACTICE)
        self._course_i = -1
        self._lesson_i = -1
        self._slide_i = -1
        # R2-3：结束学习后恢复提示一并消失（真实进度文件保留，不受影响）
        self._restore_banner = ""
        self.statusChanged.emit()
        self.transcriptChanged.emit()
        self.notesChanged.emit()
        self.lessonChanged.emit()
        self.slideChanged.emit()
        self.practiceChanged.emit()
        self._status = STATUS_IDLE
        self.statusChanged.emit()

    # ====================================================== 学习记录/位置（P1-1）
    def _ensure_data_dir(self) -> Optional[Path]:
        """惰性解析并缓存课堂数据目录（隔离校验复用 classroom_env，fail-closed）。"""
        if self._data_dir is None:
            resolved, _err = cenv.resolve_classroom_dir()
            self._data_dir = resolved
        return self._data_dir

    def _record_store(self) -> Optional[LearningRecordStore]:
        """学习记录存储（惰性构造）；不可用时给出中文原因，绝不静默丢弃写入。"""
        if self._records is None and not self._records_error:
            d = self._ensure_data_dir()
            if d is None:
                self._records_error = "无有效隔离数据目录，学习记录暂不能保存"
                return None
            try:
                self._records = LearningRecordStore(str(Path(d) / "learning_records.json"))
            except Exception as e:  # noqa: BLE001
                self._records_error = "学习记录初始化失败：%s" % type(e).__name__
        return self._records

    def _position_store(self) -> Optional[LearningPositionStore]:
        if self._positions is None:
            d = self._ensure_data_dir()
            if d is None:
                return None
            try:
                self._positions = LearningPositionStore(str(Path(d) / "learning_position.json"))
            except Exception:  # noqa: BLE001
                return None
        return self._positions

    def _record_learning(self, item_type: str, prompt: str = "", answer: str = "",
                         result: str = "") -> None:
        """把学习事件真实落盘（course/lesson 归属当前课堂；失败给出可见原因）。"""
        store = self._record_store()
        c = self._course()
        if store is None or c is None:
            return
        l = self._lesson()
        s = self._slide()
        try:
            store.add(course_id=str(c.get("course_id") or ""),
                      lesson_id=str((l or {}).get("lesson_id") or ""),
                      item_id="slide%d:%s" % (self._slide_i, str((s or {}).get("type") or "")),
                      item_type=item_type, prompt=prompt, answer=answer, result=result)
            self.notesChanged.emit()
        except Exception as e:  # noqa: BLE001
            self._records_error = "学习记录写入失败：%s" % type(e).__name__

    def _note_records(self) -> list:
        store = self._record_store()
        c = self._course()
        if store is None or c is None:
            return []
        cid = str(c.get("course_id") or "")
        out = []
        for i, r in enumerate(store.all()):
            if r.get("course_id") != cid:
                continue
            out.append({"index": i,
                        "kind": r.get("item_type") or "",
                        "prompt": r.get("prompt") or "",
                        "answer": r.get("answer") or "",
                        "result": r.get("result") or "",
                        "lesson_id": r.get("lesson_id") or "",
                        "time": time.strftime("%m-%d %H:%M", time.localtime(r.get("ts") or 0))})
        return out

    @Property("QVariantList", notify=notesChanged)
    def noteRecords(self):
        """本课程的历史学习记录（含错题；跨重启持久），供 GUI 查看/管理。"""
        return self._note_records()

    @Property(int, notify=notesChanged)
    def noteRecordCount(self):
        return len(self._note_records())

    @Property(str, notify=notesChanged)
    def recordsNotice(self):
        store = self._record_store()
        parts = []
        if self._records_error:
            parts.append(self._records_error)
        if store is not None and store.read_error:
            parts.append(store.read_error)
        pos = self._position_store()
        if pos is not None and pos.read_error:
            parts.append(pos.read_error)
        return "；".join(parts)

    @Slot(int)
    def deleteNoteRecord(self, index: int):
        store = self._record_store()
        if store is not None:
            try:
                store.delete_one(int(index))
            except Exception:  # noqa: BLE001
                self._records_error = "删除学习记录失败（下标无效）"
            self.notesChanged.emit()

    @Slot()
    def clearCourseRecords(self):
        store = self._record_store()
        c = self._course()
        if store is not None and c is not None:
            store.delete_course(str(c.get("course_id") or ""))
            self.notesChanged.emit()

    # 恢复上次学习位置
    @Property(str, notify=notesChanged)
    def restoreBanner(self):
        return self._restore_banner

    @Property("QVariantMap", notify=notesChanged)
    def resumeInfo(self):
        """「继续上次学习」入口数据（来自真实位置文件；空={}）。"""
        pos = self._position_store()
        return pos.last if pos is not None else {}

    def _apply_saved_position(self, course: dict) -> None:
        """打开课程后恢复其保存的学习位置（无保存则维持默认第 1 课时第 1 页）。"""
        pos = self._position_store()
        self._restore_banner = ""
        if pos is None or course is None:
            return
        saved = pos.for_course(str(course.get("course_id") or ""))
        if not saved:
            return
        li, si = int(saved.get("lesson_index") or 0), int(saved.get("slide_index") or 0)
        ls = course.get("lessons") or []
        if not (0 <= li < len(ls)):
            return
        self._lesson_i = li
        self._reset_lesson_state()
        self.lessonChanged.emit()
        slides = ls[li].get("slides") or []
        if 0 <= si < len(slides):
            self._goto_slide(si)
        self._restore_banner = ("已恢复上次学习位置：%s · 第 %d / %d 页"
                                % (ls[li].get("title") or "课时 %d" % (li + 1),
                                   self._slide_i + 1 if self._slide_i >= 0 else 1,
                                   len(slides) or 1))
        self.notesChanged.emit()

    @Slot()
    def resumeLastLearning(self):
        """「继续上次学习」：按位置文件打开对应课程并直接进入课堂页（R2-1）。"""
        pos = self._position_store()
        last = pos.last if pos is not None else {}
        cid = str(last.get("course_id") or "")
        if not cid:
            return
        for i, c in enumerate(self._courses):
            if str(c.get("course_id") or "") == cid:
                self.selectCourse(i)
                # R2-1：恢复后直接进入课堂页，学生无需再手动切换栏目
                self.setPage(PAGE_CLASSROOM)
                return
        # 课程在其他 bundle：定位书库条目并打开（openLibraryItem 会再恢复位置）
        if any(it.get("course_id") == cid for it in self._library):
            self.openLibraryItem(cid)
            self.setPage(PAGE_CLASSROOM)
        else:
            self._restore_banner = "上次学习的课程不在当前书库中，请在「书库」重新扫描后打开"
            self.notesChanged.emit()

    @Slot(str)
    def logExitRequested(self, source: str):
        """R2-2：记录一次退出请求（只记来源，不记录任何学生输入内容）。"""
        runtime_log.log_event("exit_requested", "source=%s" % (source or "unknown"))

    @Slot()
    def logWindowClose(self):
        """R2-2：记录窗口关闭事件（⌘W / 红叉等系统关闭路径）。"""
        runtime_log.log_event("window_close", "closing intercepted, confirm dialog shown")

    @Slot()
    def logExitConfirmed(self):
        """BUILD4-EXIT-FIX-01：记录退出确认点击（exit_confirmed）。

        判读规则：exit_confirmed 之后若无 app_exit，则代表「已确认却未退出」异常。
        """
        runtime_log.log_event("exit_confirmed", "user confirmed quit in dialog")

    # ====================================================== 老师：演示配置（fail-closed）
    def _demo_conf(self) -> dict:
        """课堂演示配置（含惰性目录解析）；无法解析时一律返回安全缺省。"""
        if self._demo_cfg_path is None:
            d = self._ensure_data_dir()
            if d is not None:
                self._demo_cfg_path = cenv.demo_config_path(d)
        if self._demo_cfg_path is None:
            return {"present": False, "corrupt": False, "allow": False,
                    "url": "", "token": "", "selected": ""}
        return cenv.load_demo_config(self._demo_cfg_path)

    def _teacher_endpoint(self):
        """返回 ``(url, token, "")`` 或 ``("", "", 中文原因)``。任一校验失败即不联网。"""
        conf = self._demo_conf()
        if conf.get("corrupt"):
            return "", "", "老师列表配置损坏：已按安全缺省关闭联网（请在隔离配置中修复后重试）"
        if not conf.get("allow"):
            return "", "", ("老师列表未启用（演示模式默认不联网）。"
                            "如需连接本机 Mock 网关，请在隔离配置中显式开启。")
        url, err = cenv.normalize_teacher_url(conf.get("url", ""))
        if url is None:
            return "", "", err
        token = conf.get("token", "")
        if not token:
            return "", "", "未配置部署令牌（由管理员在隔离配置中预置，界面不显示）"
        return url, token, ""

    @Slot()
    def refreshTeachers(self):
        url, token, err = self._teacher_endpoint()
        if not url:
            self._teachers_state = err or "老师列表不可用"
            self.teachersChanged.emit()
            return
        self._teachers_state = "正在获取老师列表…"
        self.teachersChanged.emit()
        self._fetch_teachers(url, token)

    def _fetch_teachers(self, url: str, token: str) -> None:
        import json as _json
        import urllib.error
        import urllib.request
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(url, headers={"X-Teacher-Token": token})
        try:
            with opener.open(req, timeout=5) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            rows = [t for t in (data.get("teachers") or [])
                    if isinstance(t, dict) and t.get("teacher_id")]
            self._teachers = rows
            self._teachers_state = ("共 %d 位可用老师" % len(rows)) if rows else \
                "网关暂无可用老师（请先在管理后台创建并启用）"
        except urllib.error.HTTPError as e:
            self._teachers_state = "获取失败（HTTP %s）：部署令牌无效或网关未开启老师服务" % e.code
        except Exception:
            self._teachers_state = "无法获取老师列表：无法连接网关（请确认本机 Mock 已启动）"
        self.teachersChanged.emit()

    @Slot(str)
    def selectTeacher(self, teacher_id: str):
        tid = (teacher_id or "").strip()
        if not tid:
            return
        self._selected_teacher = tid
        self.teachersChanged.emit()

    @Slot()
    def saveTeacher(self):
        """只写课堂演示配置的 selected_teacher_id；**绝不建立连接、绝不写正式配置**。

        R2-6：无「有效、可选择」的老师（条目 teacher_id 全空）时不保存，
        给出明确中文说明（QML 按钮同时禁用，此处为模型层防御）。
        """
        valid = [t for t in self._teachers if str(t.get("teacher_id") or "").strip()]
        if not valid:
            self._teachers_state = "当前没有可选择老师，暂无法保存切换；可刷新列表后重试。"
            self.teachersChanged.emit()
            return
        if self._demo_cfg_path is None:
            self._demo_cfg()
        if self._demo_cfg_path is None:
            self._teachers_state = "无有效隔离目录，无法保存老师选择"
            self.teachersChanged.emit()
            return
        ok = cenv.save_selected_teacher(self._demo_cfg_path, self._selected_teacher or "")
        self._teachers_state = ("已保存老师选择：%s（保存不会自动连接，也不会写入正式客户端配置）"
                                % self.selectedTeacherName) if ok else \
            "保存失败（隔离目录不可写）"
        self.teachersChanged.emit()

    @Slot()
    def loadSelectedTeacher(self):
        conf = self._demo_conf()
        self._selected_teacher = str(conf.get("selected") or "")
        self.teachersChanged.emit()

    # ====================================================== V2 页面导航（Agent B）
    @Property(str, notify=pageChanged)
    def page(self):
        return self._page

    @Property(str, constant=True)
    def pageLibrary(self):
        return PAGE_LIBRARY

    @Slot(str)
    def setPage(self, name: str):
        if name in PAGES and name != self._page:
            self._page = name
            self.pageChanged.emit()

    @Property("QVariantList", constant=True)
    def pages(self):
        return [{"key": PAGE_CLASSROOM, "label": "课堂"},
                {"key": PAGE_LIBRARY, "label": "书库"},
                {"key": PAGE_IMPORT, "label": "导入"},
                {"key": PAGE_PROOFREAD, "label": "校对"},
                {"key": PAGE_PUBLISH, "label": "发布"}]

    # ============================================================ 书库（真实扫描）
    def _scan_library_dir(self, dirpath: str, *, origin: str) -> list[dict]:
        out: list[dict] = []
        d = Path(dirpath)
        if not d.is_dir():
            return out
        for bundle in sorted(d.glob("*.course.json")):
            item = {"origin": origin, "kind": "bundle", "valid": False, "error": "",
                    "bundle_path": str(bundle), "manifest_path": "",
                    "course_id": "", "title": bundle.stem, "source": "",
                    "revision": 0, "courses": 0, "lessons": 0, "slides": 0,
                    "doc_id": "", "content_hash": "", "file_sha256": "",
                    "needs_review": 0, "kb_snapshot": ""}
            try:
                doc = json.loads(bundle.read_text("utf-8"))
            except Exception as e:  # noqa: BLE001
                item["error"] = "bundle 无法读取：%s" % type(e).__name__
                out.append(item)
                continue
            violations = cschema.validate_bundle(doc)
            if violations:
                item["error"] = "不符合契约 v1：%s" % violations[0]
                out.append(item)
                continue
            item["valid"] = True
            courses = doc.get("courses") or []
            c0 = courses[0] if courses else {}
            item["course_id"] = c0.get("course_id") or ""
            item["title"] = c0.get("title") or item["course_id"]
            item["source"] = c0.get("source") or ""
            item["revision"] = int(c0.get("revision") or 0)
            item["courses"] = len(courses)
            item["lessons"] = sum(len(c.get("lessons") or []) for c in courses)
            item["slides"] = sum(len(l.get("slides") or [])
                                 for c in courses for l in (c.get("lessons") or []))
            item["doc_id"] = c0.get("source_doc_id") or ""
            item["content_hash"] = c0.get("source_doc_hash") or ""
            item["file_sha256"] = c0.get("source_file_sha256") or ""
            mf = bundle.with_name(bundle.name.replace(".course.json", ".manifest.json"))
            if mf.is_file():
                item["manifest_path"] = str(mf)
                try:
                    m = json.loads(mf.read_text("utf-8"))
                    item["needs_review"] = len(m.get("needs_review") or [])
                    snap = ((m.get("knowledge") or {}).get("snapshot") or "")
                    if snap:
                        # manifest 内的 snapshot 相对**输出目录**记录；
                        # 依次尝试（输出目录 = manifest 的上级）再回退到同目录。
                        for base in (mf.parent.parent, mf.parent):
                            cand = (base / snap)
                            if cand.is_file():
                                item["kb_snapshot"] = str(cand.resolve())
                                break
                except Exception:  # noqa: BLE001
                    pass
            out.append(item)
        return out

    def _refresh_library(self) -> None:
        items: list[dict] = []
        # 1) 课堂隔离目录下的 library/（离线生成 / 用户导入）
        d = self._ensure_data_dir()
        if d is not None:
            items += self._scan_library_dir(str(Path(d) / "library"), origin="classroom-dir")
        # 2) 随包离线演示
        items += self._scan_library_dir(DEMO_LIBRARY_DIR, origin="bundled-demo")
        # 3) 随包本地演示课程（data/courses.json，local-demo）
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            violations = cschema.validate_bundle(doc)
            c0 = (doc.get("courses") or [{}])[0]
            items.append({
                "origin": "bundled-local", "kind": "builtin", "valid": not violations,
                "error": ("不符合契约 v1：%s" % violations[0]) if violations else "",
                "bundle_path": self._path, "manifest_path": "", "kb_snapshot": "",
                "course_id": c0.get("course_id") or "", "title": c0.get("title") or "随包本地演示课程",
                "source": c0.get("source") or "", "revision": int(c0.get("revision") or 0),
                "courses": len(doc.get("courses") or []),
                "lessons": sum(len(c.get("lessons") or []) for c in (doc.get("courses") or [])),
                "slides": sum(len(l.get("slides") or []) for c in (doc.get("courses") or [])
                              for l in (c.get("lessons") or [])),
                "doc_id": c0.get("source_doc_id") or "",
                "content_hash": c0.get("source_doc_hash") or "",
                "file_sha256": c0.get("source_file_sha256") or "", "needs_review": 0})
        except Exception as e:  # noqa: BLE001
            self._library_error = "随包课程不可用：%s" % type(e).__name__
        self._library = items
        self._library_error = self._library_error if not items else ""
        self.libraryChanged.emit()

    @Slot()
    def refreshLibrary(self):
        self._library_error = ""
        self._refresh_library()

    @Property("QVariantList", notify=libraryChanged)
    def libraryItems(self):
        return list(self._library)

    @Property(str, notify=libraryChanged)
    def libraryError(self):
        return self._library_error

    @Property(int, notify=libraryChanged)
    def libraryCount(self):
        return len(self._library)

    @Slot(str)
    def openLibraryItem(self, course_id: str):
        """从书库打开一门课：真实加载 + 契约校验 + 装载校对清单。"""
        cid = str(course_id or "")
        row = next((it for it in self._library if it.get("course_id") == cid), None)
        if row is None:
            return
        if not row.get("valid"):
            self._library_error = row.get("error") or "该条目不符合契约，无法打开"
            self.libraryChanged.emit()
            return
        try:
            doc = json.loads(Path(row["bundle_path"]).read_text("utf-8"))
        except Exception as e:  # noqa: BLE001
            self._library_error = "打开失败：%s" % type(e).__name__
            self.libraryChanged.emit()
            return
        violations = cschema.validate_bundle(doc)
        if violations:
            self._library_error = "打开失败：不符合契约 v1（%s）" % violations[0]
            self.libraryChanged.emit()
            return
        self._path = row["bundle_path"]
        self._doc = doc
        self._courses = list(doc.get("courses") or [])
        self._load_error = ""
        self._course_i = -1
        self._lesson_i = -1
        self._slide_i = -1
        self._started = False
        self._status = STATUS_IDLE
        self._transcript = []
        self._notes = []
        self._vocab = []
        self._practice = dict(EMPTY_PRACTICE)
        self.coursesChanged.emit()
        self.lessonChanged.emit()
        self.slideChanged.emit()
        self.statusChanged.emit()
        if self._courses:
            self.selectCourse(0)
        # 校对清单（来自 manifest 的真实 needs_review）
        self._draft = (doc.get("courses") or [{}])[0]
        self._draft_kb_snapshot = str(row.get("kb_snapshot") or "")
        self._draft_source_manifest = {}
        if row.get("manifest_path"):
            try:
                self._draft_source_manifest = json.loads(
                    Path(row["manifest_path"]).read_text("utf-8"))
            except Exception:  # noqa: BLE001
                self._draft_source_manifest = {}
        self._proofread_log = []
        self._publish_gates = []
        self._publish_log = []
        self._publish_state = "未开始"
        # FIX01-P1-2：构建真实校对条目（needs_review + 草稿扫描）并回放历史校对结果
        self._build_proofread_entries()
        self.proofreadChanged.emit()
        self.publishChanged.emit()
        self.setPage(PAGE_CLASSROOM)

    # ================================================== 导入 / 解析进度（真实记录）
    @Property("QVariantList", constant=True)
    def importFormats(self):
        return [dict(r) for r in LOCAL_FORMATS]

    @Property(bool, constant=True)
    def gatewayOpen(self):
        return GATEWAY_OPEN

    @Property(str, constant=True)
    def gatewayBlockedReason(self):
        return GATEWAY_BLOCKED_REASON

    @Property(str, notify=importChanged)
    def importState(self):
        return self._import_state

    @Property(str, notify=importChanged)
    def importMessage(self):
        return self._import_message

    @Property(str, notify=importChanged)
    def importDiagnostics(self):
        return getattr(self, "_import_diagnostics", "")

    @Property("QVariantList", notify=importChanged)
    def importStages(self):
        return list(self._import_stages)

    @Property(bool, notify=importChanged)
    def offlineDemoAvailable(self):
        return bool(self._demo_stages_source())

    def _demo_stages_source(self) -> dict:
        """随包离线演示的 manifest（真实阶段记录）。"""
        if self._demo_manifest:
            return self._demo_manifest
        d = Path(DEMO_LIBRARY_DIR)
        if not d.is_dir():
            return {}
        for mf in sorted(d.glob("*.manifest.json")):
            try:
                m = json.loads(mf.read_text("utf-8"))
                if m.get("stages"):
                    self._demo_manifest = m
                    return m
            except Exception:  # noqa: BLE001
                continue
        return {}

    @Property(str, notify=importChanged)
    def offlineDemoName(self):
        m = self._demo_stages_source()
        tb = (m.get("textbook") or {}).get("file") or ""
        c = (m.get("course") or {}).get("course_id") or ""
        return ("%s（课程 %s）" % (tb, c)) if tb else ""

    @Slot()
    def loadOfflinePipelineRecord(self):
        """显示**离线流水线的真实阶段记录**（解析进度页）。

        说明：本机解析服务未开放，此处的"进度"是离线流水线在生成演示课程时
        **真实记录**下来的阶段（不是动画、不是硬编码）。
        """
        m = self._demo_stages_source()
        if not m:
            self._import_state = "error"
            self._import_stages = []
            self._import_message = ("未找到离线演示记录。请先运行："
                                    "python tools/classroom_offline_pipeline.py --out <课堂数据目录>")
            self.importChanged.emit()
            return
        self._import_state = "done"
        self._import_stages = [dict(s) for s in (m.get("stages") or [])]
        kn = m.get("knowledge") or {}
        all_ok = all(s.get("ok") for s in self._import_stages)
        # P2-11：界面只说业务结果；技术标识（doc_id / content_hash）放诊断属性
        self._import_message = ("离线演示教材解析完成：%d 个阶段全部%s。"
                                "这是随包演示课程的生成记录，演练期间没有发起任何网络请求。"
                                % (len(self._import_stages),
                                   "成功" if all_ok else "未全部成功"))
        self._import_diagnostics = ("阶段数=%d 全部成功=%s 抽取字符=%s doc_id=%s "
                                    "content_hash=%s"
                                    % (len(self._import_stages), all_ok,
                                       ((m.get("parse") or {}).get("extracted_chars") or "?"),
                                       kn.get("doc_id") or "?",
                                       str(kn.get("content_hash") or "")))
        self.importChanged.emit()
        self.setPage(PAGE_IMPORT)

    # ============================================================== 教材校对
    # FIX01-P1-2：原文对照 + 可编辑修正 + 关键/非关键分级 + 校对结果持久化。
    # 关键性口径（结构性，非主观）：练习答案缺失/非法 = 关键（必须补答案，不得
    # 「接受缺失」绕过发布门禁）；音标缺失 = 非关键（可接受，但必须记录原因）。
    CRITICAL_REASONS = ("answer_unknown", "answer_missing")

    @Property(str, notify=proofreadChanged)
    def draftOriginalText(self):
        """原教材文本（来自知识库快照 readback；本地演示课程无来源时为空）。"""
        snap = self._draft_kb_snapshot or DEMO_KB_SNAPSHOT
        doc_id = str(self._draft.get("source_doc_id") or "")
        if not doc_id:
            return ""
        row = self._kb_lookup(snap, doc_id)
        return str((row or {}).get("text") or "")

    def _build_proofread_entries(self) -> None:
        """从真实 needs_review 清单 + 草稿扫描构建校对条目（可编辑、可持久化）。"""
        entries: list[dict] = []
        lessons = self._draft.get("lessons") or []
        orig = self.draftOriginalText

        def _orig_excerpt(word: str) -> str:
            if not orig or not word:
                return ""
            for i, line in enumerate(orig.splitlines()):
                if word.lower() in line.lower():
                    return line.strip()[:160]
            return ""

        def _find_vocab_slide(word: str):
            for li, l in enumerate(lessons):
                for si, s in enumerate(l.get("slides") or []):
                    if str(s.get("type") or "") == "vocab" and \
                            str(s.get("word") or "").lower() == str(word).lower():
                        return li, si
            return None

        def _scan_answer_slides():
            out = []
            for li, l in enumerate(lessons):
                for si, s in enumerate(l.get("slides") or []):
                    if str(s.get("type") or "") != "practice":
                        continue
                    opts = s.get("options") or []
                    raw = s.get("answer")
                    bad = not isinstance(raw, int) or isinstance(raw, bool) \
                        or not (0 <= raw < len(opts))
                    if bad:
                        out.append((li, si, s))
            return out

        for nr in (self._draft_source_manifest.get("needs_review") or []):
            if not isinstance(nr, dict):
                continue
            reason = str(nr.get("reason") or "")
            word = str(nr.get("word") or "")
            hit = _find_vocab_slide(word) if word else None
            entries.append({
                "where": str(nr.get("where") or ""),
                "reason": reason,
                "label": word or str(nr.get("question") or nr.get("where") or "未知条目"),
                "kind": "phonetic" if reason == "phonetic_unknown" else "other",
                "critical": reason in self.CRITICAL_REASONS,
                "editable": reason == "phonetic_unknown",
                "value": (str((lessons[hit[0]]["slides"][hit[1]]).get("phonetic") or "")
                          if hit else ""),
                "original": _orig_excerpt(word),
                "lesson_index": hit[0] if hit else -1,
                "slide_index": hit[1] if hit else -1,
                "resolved": False, "nonCritical": False, "note": ""})
        for li, si, s in _scan_answer_slides():
            entries.append({
                "where": "lesson[%d].slide[%d]" % (li, si),
                "reason": "answer_missing",
                "label": str(s.get("question") or "练习题")[:60],
                "kind": "answer", "critical": True, "editable": True,
                "value": "", "original": "",
                "options": [str(o) for o in (s.get("options") or [])],
                "lesson_index": li, "slide_index": si,
                "resolved": False, "nonCritical": False, "note": ""})
        self._proofread_entries = entries
        self._load_saved_proofread()

    @Property("QVariantList", notify=proofreadChanged)
    def proofreadEntries(self):
        return [dict(e) for e in self._proofread_entries]

    @Property(int, notify=proofreadChanged)
    def proofreadEntryTotal(self):
        return len(self._proofread_entries)

    @Property(int, notify=proofreadChanged)
    def proofreadCriticalUnresolved(self):
        return sum(1 for e in self._proofread_entries
                   if e.get("critical") and not e.get("resolved"))

    def _entry_target_slide(self, e: dict):
        li, si = e.get("lesson_index"), e.get("slide_index")
        try:
            return self._draft["lessons"][li]["slides"][si]
        except Exception:  # noqa: BLE001
            return None

    @Slot(int, str)
    def applyPhoneticFix(self, index: int, value: str):
        """补音标：写入草稿课件（课堂立即可见）并标记条目已修正。"""
        if not (0 <= index < len(self._proofread_entries)):
            return
        e = self._proofread_entries[index]
        s = self._entry_target_slide(e)
        v = str(value or "").strip()
        if s is None or e.get("kind") != "phonetic":
            return
        if v and not v.startswith("/"):
            v = "/" + v.lstrip("/")
        if v and not v.endswith("/"):
            v = v + "/"
        s["phonetic"] = v
        e["value"] = v
        e["resolved"] = bool(v)
        e["note"] = "已补充音标" if v else ""
        self.proofreadChanged.emit()

    @Slot(int, int)
    def applyAnswerFix(self, index: int, value: int):
        """补练习答案：写入草稿课件（关键项必须修正，不可「接受缺失」）。"""
        if not (0 <= index < len(self._proofread_entries)):
            return
        e = self._proofread_entries[index]
        s = self._entry_target_slide(e)
        if s is None or e.get("kind") != "answer":
            return
        opts = s.get("options") or []
        if not (0 <= value < len(opts)):
            return
        s["answer"] = int(value)
        e["value"] = str(opts[value])
        e["resolved"] = True
        e["note"] = "已补充答案：%s" % opts[value]
        self.proofreadChanged.emit()

    @Slot(int, str)
    def acceptEntryAsNonCritical(self, index: int, note: str):
        """非关键缺失可接受，但必须记录原因（关键项不接受，防止绕过门禁）。"""
        if not (0 <= index < len(self._proofread_entries)):
            return
        e = self._proofread_entries[index]
        if e.get("critical"):
            return
        note = str(note or "").strip()
        if not note:
            return
        e["resolved"] = True
        e["nonCritical"] = True
        e["note"] = "接受非关键缺失：%s" % note
        self.proofreadChanged.emit()

    @Slot(int)
    def reopenEntry(self, index: int):
        if 0 <= index < len(self._proofread_entries):
            e = self._proofread_entries[index]
            e["resolved"] = False
            e["nonCritical"] = False
            e["note"] = ""
            self.proofreadChanged.emit()

    @Property(str, notify=proofreadChanged)
    def proofreadSaveState(self):
        return self._proofread_state

    def _proofread_save_path(self):
        d = self._ensure_data_dir()
        if d is None or not self._draft:
            return None
        return Path(d) / "proofread" / ("%s.json" % self._draft.get("course_id") or "draft")

    @Slot()
    def saveProofread(self):
        """保存校对结果（原子写、600）；打开课程时自动回放。"""
        p = self._proofread_save_path()
        if p is None:
            self._proofread_state = "无法保存校对结果：无有效隔离目录或未打开课程"
            self.proofreadChanged.emit()
            return
        try:
            import tempfile
            payload = {"course_id": str(self._draft.get("course_id") or ""),
                       "saved_at": time.time(),
                       "entries": [{"where": e["where"], "label": e["label"],
                                    "resolved": e["resolved"],
                                    "nonCritical": e["nonCritical"], "note": e["note"],
                                    "value": e["value"]} for e in self._proofread_entries]}
            p.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".proofread.", dir=str(p.parent))
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=1)
            os.chmod(tmp, 0o600)
            os.replace(tmp, p)
            self._proofread_state = "校对结果已保存（%d 项）" % len(payload["entries"])
        except Exception as ex:  # noqa: BLE001
            self._proofread_state = "校对结果保存失败：%s" % type(ex).__name__
        self.proofreadChanged.emit()

    def _load_saved_proofread(self) -> None:
        """回放已保存的校对结果（匹配 where+label；修正值重新写入草稿课件）。"""
        p = self._proofread_save_path()
        if p is None or not p.is_file():
            return
        try:
            payload = json.loads(p.read_text("utf-8"))
            saved = {(s.get("where"), s.get("label")): s
                     for s in (payload.get("entries") or []) if isinstance(s, dict)}
        except Exception:  # noqa: BLE001 —— 损坏校对文件不阻断，照实提示
            self._proofread_state = "已保存的校对结果无法读取（文件损坏），按未校对处理"
            return
        for e in self._proofread_entries:
            s = saved.get((e["where"], e["label"]))
            if not s:
                continue
            e["resolved"] = bool(s.get("resolved"))
            e["nonCritical"] = bool(s.get("nonCritical"))
            e["note"] = str(s.get("note") or "")
            if e["kind"] == "phonetic" and s.get("value"):
                slide = self._entry_target_slide(e)
                if slide is not None:
                    slide["phonetic"] = str(s["value"])
                e["value"] = str(s["value"])

    @Property(str, notify=proofreadChanged)
    def draftTitle(self):
        return str(self._draft.get("title") or "")

    @Property(str, notify=proofreadChanged)
    def draftCourseId(self):
        return str(self._draft.get("course_id") or "")

    @Property(str, notify=proofreadChanged)
    def draftSource(self):
        return str(self._draft.get("source") or "")

    @Property("QVariantList", notify=proofreadChanged)
    def reviewItems(self):
        """兼容视图（旧 QML 字段名）；新 UI 请用 proofreadEntries。"""
        return [{"where": e["where"], "reason": e["reason"], "label": e["label"],
                 "resolved": e["resolved"], "note": e["note"]}
                for e in self._proofread_entries]

    @Property(int, notify=proofreadChanged)
    def reviewTotal(self):
        return len(self._proofread_entries)

    @Property(int, notify=proofreadChanged)
    def reviewUnresolved(self):
        return sum(1 for e in self._proofread_entries if not e.get("resolved"))

    @Property(str, notify=proofreadChanged)
    def proofreadState(self):
        if not self._draft:
            return "尚未打开课程：请先在「书库」中打开一门课程"
        if not self._proofread_entries:
            return "本课程没有需要人工确认的条目"
        if self.proofreadCriticalUnresolved > 0:
            return "校对中：仍有 %d 项关键问题未解决（关键项必须修正，不能跳过）" \
                   % self.proofreadCriticalUnresolved
        if self.reviewUnresolved == 0:
            return "校对完成：%d / %d 项已处理" % (self.reviewTotal, self.reviewTotal)
        return "校对中：已处理 %d / %d 项（非关键缺失须记录原因后接受）" \
               % (self.reviewTotal - self.reviewUnresolved, self.reviewTotal)

    @Property("QVariantList", notify=proofreadChanged)
    def proofreadLog(self):
        return list(self._proofread_log)

    # ==================================================== 课程发布（Mock 演练）
    @Property(str, constant=True)
    def publishMockBanner(self):
        return ("本页为「发布流程演练（Mock）」：不发任何网络请求、不写入任何发布存储。"
                "真实发布服务端路由本轮「未实现」，且在独立安全复核通过前不开放。")

    def _kb_lookup(self, snapshot_path: str, doc_id: str):
        """在知识库快照中查 doc_id —— store 落盘结构为 ``documents: {doc_id: {...}}``。"""
        try:
            raw = json.loads(Path(snapshot_path).read_text("utf-8"))
        except Exception:  # noqa: BLE001
            return None
        docs = raw.get("documents")
        if isinstance(docs, dict):
            row = docs.get(doc_id)
            return row if isinstance(row, dict) else None
        if isinstance(docs, list):
            for d in docs:
                if isinstance(d, dict) and d.get("id") == doc_id:
                    return d
        return None

    def _compute_publish_gates(self) -> list[dict]:
        gates: list[dict] = []
        # ① 课程契约校验
        try:
            doc = {"schema": cschema.SCHEMA_DOCUMENT_TYPE, "version": cschema.SCHEMA_VERSION,
                   "courses": [self._draft]} if self._draft else {}
            v = cschema.validate_bundle(doc) if doc else ["未打开课程"]
        except Exception as e:  # noqa: BLE001
            v = ["校验异常：%s" % type(e).__name__]
        gates.append({"name": "课程符合冻结契约 v1", "ok": not v,
                      "detail": "通过" if not v else str(v[0])})
        # ② 来源绑定有效
        src = str(self._draft.get("source") or "")
        snap_path = str(getattr(self, "_draft_kb_snapshot", "") or "")
        if not snap_path:
            snap_path = DEMO_KB_SNAPSHOT
        doc_id = str(self._draft.get("source_doc_id") or "")
        doc_hash = self._draft.get("source_doc_hash")
        if src == "local-demo":
            gates.append({"name": "来源绑定有效（知识库来源）", "ok": False,
                          "detail": "本地演示课程不具备知识库来源，不能作为正式课程发布"})
        elif not doc_id or not doc_hash:
            gates.append({"name": "来源绑定有效（知识库来源）", "ok": False,
                          "detail": "缺少 source_doc_id / source_doc_hash"})
        else:
            row = self._kb_lookup(snap_path, doc_id) if snap_path else None
            if row is None:
                gates.append({"name": "来源绑定有效（知识库来源）", "ok": False,
                              "detail": "知识库快照中找不到 doc_id=%s（无法证明来源存在）" % doc_id})
            else:
                same = cschema.sha256_matches(doc_hash, row.get("content_hash"))
                gates.append({"name": "来源绑定有效（知识库来源）", "ok": bool(same),
                              "detail": ("doc_id 存在且 content_hash 一致（%s）" % doc_id) if same
                              else "content_hash 与知识库不一致（可能内容已变更）"})
        # ③ 待人工确认项清零
        gates.append({"name": "待人工确认项已清零", "ok": self.reviewUnresolved == 0,
                      "detail": ("全部已处理" if self.reviewUnresolved == 0
                                 else "仍有 %d 项待处理" % self.reviewUnresolved)})
        # ④ 关键问题已解决（关键项必须修正；非关键缺失须记录原因后接受）
        gates.append({"name": "关键问题已解决（关键项不可接受缺失）",
                      "ok": self.proofreadCriticalUnresolved == 0,
                      "detail": ("通过" if self.proofreadCriticalUnresolved == 0
                                 else "仍有 %d 项关键问题未修正" % self.proofreadCriticalUnresolved)})
        return gates

    @Slot()
    def runPublishMock(self):
        self._publish_gates = self._compute_publish_gates()
        ok = sum(1 for g in self._publish_gates if g["ok"])
        total = len(self._publish_gates)
        self._publish_state = ("Mock 演练：%d / %d 项业务门禁通过；「未执行」真实发布"
                               % (ok, total))
        self._publish_log.append({"at": _now_ts(), "ok": ok, "total": total,
                                  "gates": [{"name": g["name"], "ok": g["ok"]}
                                            for g in self._publish_gates]})
        self.publishChanged.emit()

    @Property("QVariantList", notify=publishChanged)
    def publishGates(self):
        return [dict(g) for g in self._publish_gates]

    @Property(str, notify=publishChanged)
    def publishState(self):
        return self._publish_state

    @Property("QVariantList", notify=publishChanged)
    def publishLog(self):
        return list(self._publish_log)


def _now_ts() -> str:
    import time
    return time.strftime("%H:%M:%S")
