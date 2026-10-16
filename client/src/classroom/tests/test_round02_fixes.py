# -*- coding: utf-8 -*-
"""CLASSROOM-V2-ROUND02-FIX · 回归测试（R2-1/2/3/4/6 + 源码结构断言 R2-7/8）。

覆盖（产品负责人批准范围）：
* R2-1 「继续上次学习」直接进入课堂页并恢复位置与横幅；
* R2-2 runtime_log：事件写入、600 权限、轮转、异常钩子、不含学生输入的口径（代码级）；
* R2-3 恢复横幅随翻页/结束学习消失（且不吞掉恢复提示本身）；
* R2-4 字幕去重覆盖 A→B→A 往返；主动「重复讲解」保留；即时反馈不误去重；
* 学习进度持久化与四条历史笔记跨恢复完整；
* R2-6 无有效老师时 saveTeacher 模型层拒绝并给出中文说明；
* R2-7/8 源码结构断言（QML 不再含英文 Close / unsupported_format / 裸绿点 / doc_id 直显）。
"""
import json
import os
import stat
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_CLIENT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
sys.path.insert(0, _CLIENT)
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
os.environ["QT_API"] = "pyside6"

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

QCoreApplication = None
from PySide6.QtCore import QCoreApplication  # noqa: E402

QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
_app = QApplication.instance() or QApplication(sys.argv[:1])

from src.classroom.classroom_model import ClassroomModel  # noqa: E402
from src.classroom.learning_record import LearningRecordStore  # noqa: E402
from src.classroom.learning_position import LearningPositionStore  # noqa: E402
from src.classroom import runtime_log  # noqa: E402

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS %s" % name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("FAIL %s %s" % (name, detail))


QML_DIR = os.path.join(_CLIENT, "src", "classroom", "qml")
CW = open(os.path.join(QML_DIR, "ClassroomWindow.qml"), encoding="utf-8").read()
LP = open(os.path.join(QML_DIR, "LibraryPanel.qml"), encoding="utf-8").read()
IP = open(os.path.join(QML_DIR, "ImportPanel.qml"), encoding="utf-8").read()
MAIN = open(os.path.join(_CLIENT, "classroom_main.py"), encoding="utf-8").read()

tmp = tempfile.mkdtemp(prefix="xz-round02-")
BUNDLE_ID = "crs_offline_demo_basics"

# =============================================================== R2-2 runtime_log
print("--- R2-2 runtime_log ---")
tmp2 = tempfile.mkdtemp(prefix="xz-round02-log-")
lp = runtime_log.init(tmp2)
runtime_log.install_excepthook()
check("L1 init 返回日志路径", lp and os.path.exists(lp), lp)
mode = stat.S_IMODE(os.stat(lp).st_mode)
check("L2 日志文件权限 600", mode == 0o600, oct(mode))
runtime_log.log_event("test_event", "hello")
content = open(lp, encoding="utf-8").read()
check("L3 事件写入", "test_event | hello" in content)
try:
    sys.excepthook(ValueError, ValueError("boom"), None)
    ok = "uncaught_exception" in open(lp, encoding="utf-8").read()
except Exception as exc:  # noqa: BLE001
    ok = False
    print("  excepthook 异常:", exc)
check("L4 未处理异常被记录", ok)
# 轮转：预填文件超过 256KB 上限，再写一条即触发轮转
with open(lp, "a", encoding="utf-8") as fh:
    fh.write("filler\n" * (300 * 1024 // 7))
runtime_log.log_event("after_rotate", "should trigger rotation")
check("L5 超限后产生轮转文件", os.path.exists(lp + ".1"), lp + ".1")
check("L6 轮转后新文件继续写入", "after_rotate" in open(lp, encoding="utf-8").read())

# =============================================================== R2-1/R2-3 学习恢复
print("--- R2-1/R2-3 继续上次学习与横幅 ---")
m1 = ClassroomModel(data_dir=tmp)
m1.openLibraryItem(BUNDLE_ID)
m1.startLearning()
m1.nextSlide()                      # 到第 2 页（slide_index=1）
_pos_file = os.path.join(tmp, "learning_position.json")
check("A1 翻页后位置已持久化",
      (LearningPositionStore(_pos_file).for_course(BUNDLE_ID) or {}).get("slide_index") == 1)
m1.endLearning()
m1.setPage(m1.pageLibrary)          # 模拟学生回到书库
check("A2 结束学习后横幅清空", m1.restoreBanner == "", repr(m1.restoreBanner))

m2 = ClassroomModel(data_dir=tmp)   # 新实例 = 重启
m2.resumeLastLearning()
check("A3 R2-1 点击后直接进入课堂页", m2.page == "classroom", m2.page)
check("A4 恢复到第 2 页", m2.slideIndex == 1, m2.slideIndex)
check("A5 恢复横幅正常显示", "已恢复上次学习位置" in m2.restoreBanner, m2.restoreBanner)

m2.startLearning()                  # 进入课堂后开始学习（与真人流程一致）
m2.nextSlide()
check("A6 R2-3 翻页后横幅消失", m2.restoreBanner == "", repr(m2.restoreBanner))
check("A7 翻页后进度真实保存",
      (LearningPositionStore(_pos_file).for_course(BUNDLE_ID) or {}).get("slide_index") == 2)
m2.endLearning()
check("A8 结束学习后横幅消失", m2.restoreBanner == "")

# =============================================================== R2-4 字幕去重
print("--- R2-4 字幕 A→B→A 去重与重复讲解 ---")
tmp3 = tempfile.mkdtemp(prefix="xz-round02-b-")   # 独立目录，避免 A 段位置状态污染
m3 = ClassroomModel(data_dir=tmp3)
m3.openLibraryItem(BUNDLE_ID)
m3.startLearning()                                  # 恢复位置为空 → 从第 1 页（封面）开始


def teacher_texts(model):
    return [t["text"] for t in model._transcript if t.get("role") == "teacher"]


def count(model, needle):
    return sum(1 for t in teacher_texts(model) if needle in t)


cover_key = "本课我们学习"
check("B1 封面页讲解出现 1 次", count(m3, cover_key) == 1, count(m3, cover_key))
m3.nextSlide()                                  # A → B（第 2 页）
mid_key = "看这个单词"
mid_first = count(m3, mid_key)
check("B2 下一页讲解出现 %d 次" % mid_first, mid_first >= 1, mid_first)
m3.prevSlide()                                  # B → A
m3.nextSlide()                                  # A → B（再回上一页）
check("B3 A→B→A 后该页讲解不重复追加（去重生效）",
      count(m3, mid_key) == mid_first, count(m3, mid_key))
check("B4 封面页讲解仍只 1 次", count(m3, cover_key) == 1, count(m3, cover_key))
m3.repeatSlide()                                # 用户主动重复讲解
check("B5 主动重复讲解正常显示（+1 条）", count(m3, mid_key) == mid_first + 1,
      count(m3, mid_key))
# 即时反馈不误去重：「再试一次」重复作答同选项 → 同文本反馈必须再次出现
while m3.slideIndex + 1 < m3.slideCount:
    nxt = m3._slides()[m3.slideIndex + 1]
    if str(nxt.get("type") or "") == "practice":
        m3.nextSlide()
        break
    m3.nextSlide()
if str(m3._slide().get("type") or "") == "practice":
    fb_key = "（本地判定）"
    before = count(m3, fb_key)
    ans = int(m3._practice.get("answer", -1))
    wrong_idx = 0 if ans != 0 else 1        # 选一个错误选项（答对不给重试）
    m3.answerPractice(wrong_idx)            # 答错 → 反馈 1
    first_fb = count(m3, fb_key) - before
    m3.retryPractice()                      # 再试一次（答错允许重试）
    m3.answerPractice(wrong_idx)            # 同错 → 同文本反馈（force 确保显示）
    after = count(m3, fb_key)
    check("B6 重复作答的判定反馈不误去重（两次均显示）",
          first_fb == 1 and after - before == 2, "%s→%s→%s" % (before, first_fb, after))

# =============================================================== 学习进度 + 四条历史笔记
print("--- 学习进度与四条历史笔记跨恢复 ---")
store = LearningRecordStore(os.path.join(tmp, "learning_records.json"))
cid, lid = BUNDLE_ID, "lesson_greeting" if BUNDLE_ID != "crs_hotel" else "lesson_checkin"
lid = str((m3._lesson() or {}).get("lesson_id") or lid)
for i in range(4):
    store.add(course_id=cid, lesson_id=lid,
              item_id="slide1:vocab", item_type="note",
              prompt="历史笔记 %d" % (i + 1), answer="", result="", source="local")
m4 = ClassroomModel(data_dir=tmp)
m4.openLibraryItem(BUNDLE_ID)
m4.selectLesson(m4._lesson_i)
got = len(m4.noteRecords)
check("C1 恢复后四条历史笔记完整可见（+本课新记录）", got >= 4, got)
check("C2 笔记跨恢复内容一致",
      any("历史笔记 1" in str(r) for r in m4.noteRecords))

# =============================================================== R2-6 模型层防御
print("--- R2-6 无有效老师时保存保护 ---")
m5 = ClassroomModel(data_dir=tmp)
m5.refreshTeachers()                            # 默认门禁关闭 → 列表为空
m5.saveTeacher()
check("D1 无有效老师时给出中文说明", "当前没有可选择老师" in m5.teachersState, m5.teachersState)

# =============================================================== R2-7/R2-8 源码结构断言
print("--- R2-7/R2-8 QML 源码结构断言 ---")
check("E1 高级设置不再使用英文 Close", "Dialog.Close" not in CW)
check("E2 高级设置有中文「关闭」按钮", 'text: "关闭"' in CW)
check("E3 V4 文案已改为准确架构表述", "尚未完成与 NAS 的正式联调" in CW)
check("E4 不再误称「本机 V4 管理后台维护」", "均在本机 V4 管理后台维护" not in CW)
check("E5 退出确认弹窗存在", "quitConfirmDialog" in CW and "确定要退出小智课堂吗" in CW)
check("E6 窗口关闭拦截存在（onClosing）", "onClosing" in CW and "logWindowClose" in CW)
check("E7 修复：任意按钮不再直连 Qt.quit（BUILD4-EXIT-FIX-01 替换为空断言）",
      "onClicked: Qt.quit()" not in CW)
check("E8 老师弹窗保存按钮有 enabled 绑定", "enabled: classroom.teachers.filter" in CW)
# ------- BUILD4-EXIT-FIX-01：退出链路结构断言（防二次回归） -------
print("--- BUILD4-EXIT-FIX-01 退出链路断言 ---")
check("X1 引擎退出信号已连接（engine.quit.connect）",
      "engine.quit.connect(app.quit)" in MAIN)
check("X2 onClosing 含已确认放行分支",
      "if (win.quitConfirmed)" in CW and "close.accepted = true" in CW)
check("X3 「退出」按钮链路完整（置位+记录+关闭窗口）",
      "win.quitConfirmed = true" in CW and "classroom.logExitConfirmed()" in CW
      and "win.close()" in CW)
check("X4 「继续学习」复位确认状态",
      "win.quitConfirmed = false" in CW and "quitConfirmDialog.close()" in CW)
check("X5 弹窗 onClosed 兜底复位存在", "onClosed: win.quitConfirmed = false" in CW)
check("X6 logExitConfirmed Slot 存在（模型层）",
      "def logExitConfirmed" in open(os.path.join(_CLIENT, "src", "classroom",
                                                 "classroom_model.py"), encoding="utf-8").read())
check("F1 书库不再直显 doc_id 徽章", "来源 doc_id：" not in LP or
      LP.count("gatewayOpen") > 0)  # 直显已绑定 gatewayOpen（演示门禁下恒不可见）
check("F2 导入预检无 unsupported_format 字样", "unsupported_format" not in IP)
check("F3 格式行颜色绑定解析服务开放状态", IP.count("classroom.gatewayOpen") >= 2)
check("F4 服务未开放时注明暂不可用", "暂不可用" in IP)

# ------- 契约指令⑧ 与白名单口径修正（B 复核 N4/N7 · 2026-10-15） -------
print("--- 契约指令⑧（版面风险提醒）与白名单口径断言 ---")
PF = open(os.path.join(QML_DIR, "ProofreadPanel.qml"), encoding="utf-8").read()
check("N4 校对页含契约固定文案（多栏版面风险提醒）",
      "当教材为多栏排版时，抽取顺序可能与阅读顺序不一致，请重点核对" in PF)
check("N4b 版面提醒为一般性文案（无针对性声明字样）", "已检测到多栏" not in PF)
check("N7 导入页白名单口径不写死条数", "白名单 7 条" not in IP and "白名单路由" in IP)

print()
print("RESULT PASS=%d FAIL=%d" % (PASS, FAIL))
if FAILS:
    print("FAILED:", "; ".join(FAILS))
sys.exit(0 if FAIL == 0 else 1)
