# HUMAN_GUI_ACCEPTANCE_ROUND01 — 缺陷台账（真人验收 · 第一轮）

- 验收对象：`小智 AI 学生课堂.app` v2.0.0 build 2
- 验收人：产品负责人（真人 GUI 操作，非模拟）
- 登记时间：2026-10-13（总控）
- 整改轮次：HUMAN_GUI_ACCEPTANCE_FIX01

## P1（必须修复）

| # | 缺陷 | 真实根因（总控审计） | 修复状态 |
|---|---|---|---|
| P1-1 | 学习记忆跨重启丢失（7/8 页+错题，重启后笔记空、回 1/8） | **learning_record.py 从未接入**：`classroom_model.py`/QML/入口零引用（仅测试引用）；笔记 `_notes`、练习反馈全内存态且 `endLearning()` 清空；学习位置无任何持久化；入口 `classroom_main.py:134` 每次启动强制 `selectCourse(0)+selectLesson(0)` | **已修**（见下） |
| P1-2 | 校对只有「确认无误」，无原文对照/可编辑/音标补充 | 校对条目仅回放 manifest `needs_review` 且无编辑能力、无原文来源展示、无分级门禁 | **已修**（见下） |
| P1-3 | AI 老师列表空、数字人静态「未」占位 | 当前事实：未接入真实老师服务（安全复核未通过）；此前界面未充分说明正式目标与现状 | **状态诚实化已修**：老师弹窗新增真实状态横幅；真实语音/数字人接入仍受独立安全复核门禁（未越权） |
| P1-4 | 自有教材真实导入未完成 | 真实导入服务受既定安全门禁（独立安全复核 NOT_COMPLETED） | **维持门禁**，界面如实显示不可用原因；不得用预制教材冒充 |

## P1-1 修复内容（结构级）

1. `learning_record.py`（既有，未改契约）真实接入 `classroom_model.py`：
   - 练习答错 → `mistake` 记录落盘；答对/未判分 → `note` 记录（result=correct/ungraded）；
   - 文本提交 → `note` 记录落盘。
2. 新增 `learning_position.py`：按课程隔离的学习位置（原子写、600、损坏隔离空启动）；`_goto_slide` 学习中真实保存；`endLearning` 不清位置（可续学）。
3. 打开课程即恢复保存位置（跨重启）+ 可见横幅「已恢复上次学习位置」；`resumeLastLearning()` 槽 + 书库「继续上次学习」入口。
4. GUI 管理：`noteRecords/noteRecordCount/deleteNoteRecord/clearCourseRecords/recordsNotice`——笔记页改为真实持久化记录（含错题），可查看/删除/清空本课。
5. 损坏降级：记录/位置文件损坏 → 隔离为 `*.corrupt-<ts>` + 中文提示，绝不崩溃、不删原文件。
6. 隔离：记录键 = course_id + lesson_id，跨课程不串；写至课堂隔离目录（`~/Library/Application Support/xiaozhi-classroom-demo/`），不触碰 modules/memory 与正式配置。

## P1-2 修复内容

1. 原文对照：`draftOriginalText`（知识库快照 readback 的原教材文本），条目内展示原书行。
2. 可编辑修正：音标（`applyPhoneticFix`，自动补闭合斜杠）、练习答案（`applyAnswerFix`，关键项）——写入草稿课件，课堂立即可见。
3. 关键/非关键分级（结构口径）：答案缺失/非法=关键（必须修正，无「接受」入口）；音标缺失=非关键（可接受但必须记录原因，`acceptEntryAsNonCritical`）。
4. 校对结果持久化：`saveProofread()` → 隔离目录 `proofread/<course_id>.json`（原子 600），打开课程自动回放（修正值重新写入课件）。
5. 发布门禁升级：新增第 ④ 道「关键问题已解决（关键项不可接受缺失）」；未修正关键项照实阻断。

## P2 整改（13 项）

1. ✅ 默认首页=我的书库，不再自动打开酒店英语演示课（`classroom_main.py` 移除强制开课）。
2. ✅ 书库「继续上次学习」入口（真实位置文件驱动）。
3. ✅ 随包演示课程标记「演示教材」徽章（origin=bundled-demo/bundled-local）。
4. ✅ 未选老师时讲解身份显示「本地文字演示（未选择 AI 老师）」（`narratorLabel`）。
5. ✅ 词汇与 IPA 分行、缺失音标诚实提示、统一「口音：未标注」标签（CourseArea+InteractionPanel）。
6. ✅ 练习标题改「本题无音频，为文本选择题，不构成听力测试」。
7. ✅ 练习提示改「（请选择下方答案）」。
8. ✅ 答错后「再试一次」按钮（`retryPractice`；错题记录保留）。
9. ✅ 小结播报答题情况/错题/复习建议（`_append_summary_stats`，来自真实落盘记录）。
10. ✅ 课堂笔记=持久化学习记录：查看/删除/清空本课。
11. ✅ 开发术语收敛：导入完成文案业务化（doc_id/content_hash 移入「诊断信息」折叠）；发布演练日志收进诊断折叠；Mock 事件日志中文化+技术细节降级为「诊断」行。
12. ✅ 发布页留白精简、门禁结果突出（删长说明、日志折叠）。
13. ✅ QML 与 REV1B 画布一致性：本轮改动均按既有主题 token（ClassroomTheme）落样式，未引入新视觉体系。

## 已通过项（不得回归——本轮全部复验通过）

Finder 双击无终端、书库导航、1–8 页翻页、单词/句型/中英课件展示、错答判定与解释、Mock 发布门禁阻断、Mock 双向对话事件与重置、无真实老师时文字课堂可用。
→ 复验证据：`ui_pages_probe` 58/58、`ui_layout_probe` 52/52（含 0 越界、弹窗可达、诚实降级断言）。

## 边界确认

本轮零改动：Tina 冻结六文件、受保护数字人 5 文件、NAS、正式配置、付费模型、Bearer Token 学生端接入、20 天课程体系。
