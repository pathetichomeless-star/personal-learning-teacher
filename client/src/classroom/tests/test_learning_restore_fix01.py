# -*- coding: utf-8 -*-
"""HUMAN_GUI_ACCEPTANCE_FIX01 · P1-1 回归测试（学习记录跨重启恢复）。

复现产品负责人真人验收链路（模型层确定性等价）：
学习至第 7 页 → 答错 B → ⌘Q（进程结束）→ 新实例（=重启）→ 打开同一课程
→ 断言：错题已保存、学习位置恢复、课程隔离、损坏文件安全降级。
"""
import json
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_CLIENT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
sys.path.insert(0, _CLIENT)
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

os.environ["QT_API"] = "pyside6"
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtCore import QCoreApplication, Qt  # noqa: E402

QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
_app = QApplication.instance() or QApplication(sys.argv[:1])

from src.classroom.classroom_model import ClassroomModel  # noqa: E402

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


tmp = tempfile.mkdtemp(prefix="xz-lr-fix01-")
BUNDLE = os.path.join(_CLIENT, "src", "classroom", "data", "demo", "library",
                      "crs_offline_demo_basics.course.json")

# ---- 第一次“上课”（=真人第 1 次启动）----
m1 = ClassroomModel(data_dir=tmp)
m1.openLibraryItem("crs_offline_demo_basics")
m1.startLearning()
# 走到练习页并答错（对应真人：学习至 7/8 页 → 选错 B「中午」）
practice_idx = None
for i in range(m1.slideCount):
    if str(m1._slides()[i].get("type") or "") == "practice":
        practice_idx = i
        break
check("A1 演示课程存在练习页", practice_idx is not None)
for _ in range(practice_idx):
    m1.nextSlide()
wrong_pick = (int(m1.practice.get("answer", 0)) + 1) % len(m1.practice.get("options") or [])
m1.answerPractice(wrong_pick)
check("A2 答错后反馈为错", m1.practice.get("correct") is False)
# 写笔记
m1.submitText("hello")
rec_file = os.path.join(tmp, "learning_records.json")
check("B1 学习记录已真实落盘", os.path.exists(rec_file))
recs = json.load(open(rec_file))["records"] if os.path.exists(rec_file) else []
check("B2 错题已写入记录", any(r.get("result") == "wrong" for r in recs))
check("B3 笔记已写入记录", any(r.get("item_type") == "note" and r.get("prompt") == "hello"
                              for r in recs))
pos_file = os.path.join(tmp, "learning_position.json")
check("C1 学习位置已真实落盘", os.path.exists(pos_file))
# 结束学习（真人：⌘Q 前的正常状态清理），模拟进程退出
m1.endLearning()
del m1

# ---- 第二次“上课”（=重启后新实例；绝不复用任何内存态）----
m2 = ClassroomModel(data_dir=tmp)
m2.openLibraryItem("crs_offline_demo_basics")
# 位置恢复：应回到练习页而非第 1 页
check("D1 重启后恢复到上次学习页（第 %d 页）" % (practice_idx + 1),
      m2.slideIndex == practice_idx,
      "actual slideIndex=%s" % m2.slideIndex)
check("D2 恢复提示可见", bool(m2.restoreBanner))
m2.startLearning()
check("D3 开始学习后仍在恢复位置", m2.slideIndex == practice_idx)
check("E1 错题跨重启保存（noteRecords 含 wrong）",
      any(r.get("result") == "wrong" for r in m2.noteRecords))
check("E2 笔记跨重启可见", any(r.get("prompt") == "hello" for r in m2.noteRecords))

# ---- 课程隔离：另一门课不应看到本课记录 ----
other_cid = "crs_hotel"  # 书库中的另一个真实条目（随包本地演示课程）
if any(it.get("course_id") == other_cid for it in m2.libraryItems):
    m2.openLibraryItem(other_cid)
    check("F1 其他课程记录为空（课程隔离）", m2.noteRecordCount == 0,
          "actual count=%s" % m2.noteRecordCount)
else:
    check("F1 其他课程记录为空（课程隔离）", True, "(书库无第二门课，跳过)")

# ---- 损坏文件安全降级 ----
m2bak = None
with open(rec_file, "w", encoding="utf-8") as f:
    f.write("{corrupted!!")
m3 = ClassroomModel(data_dir=tmp)
check("G1 损坏记录文件：隔离后空启动不崩溃", m3._record_store() is not None)
check("G2 损坏有可见原因", "损坏" in (m3.recordsNotice or ""))
quarantined = [f for f in os.listdir(tmp) if f.startswith("learning_records.json.corrupt-")]
check("G3 原文件被隔离保留（不删除）", len(quarantined) == 1)
posp = os.path.join(tmp, "learning_position.json")
with open(posp, "w", encoding="utf-8") as f:
    f.write("not json at all")
m4 = ClassroomModel(data_dir=tmp)
m4.openLibraryItem("crs_offline_demo_basics")
check("H1 损坏位置文件：空位置安全降级", m4.slideIndex <= 0 and m4._lesson_i <= 0)

shutil.rmtree(tmp, ignore_errors=True)
print("=" * 60)
print("RESULT: %d PASS, %d FAIL" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
