# QML 所有权例外 01 — 复核接收记录（EXC-01）

- 对应登记：`CLASSROOM_V2_AGENT_PLAN.md §2.2` 例外表 `EXC-01`
- 文件：`client/src/classroom/qml/CourseArea.qml`（唯一所有者 **B**）
- 例外写入者：**TC**（依据 `CONTRACT_FIX_01A 一.2`）
- 复核与接收：**B**（QML 独占写者）
- 日期：`2026-10-12`
- 交付门：`DELIVERY GATE 02` 一.1

---

## 1. 哈希留痕

| 版本 | SHA-256 | 说明 |
|---|---|---|
| 改动前（= 分支 HEAD blob，亦为已发布 `.app` 内副本） | `bd3eed75989feeea2fcd137c08da155f5cb940dc1679527d410819df1b77dbf5` | FIX02 基线 |
| 改动后（本轮 worktree，待 B 复核时） | `317e37ff8a5336cc0688b62a98657830870bcc9cbb01f197044949381b781f81` | 含未知类型兜底 |

`git diff --stat`：**1 file changed, 33 insertions(+), 0 deletions(-)** —— **纯新增，无删改**。

---

## 2. 改动范围（逐项）

| # | 位置 | 内容 | 是否触碰既有行为 |
|---|---|---|---|
| 1 | 行 18–23（`root` 属性区） | 新增 `readonly property var knownSlideTypes`（闭枚举 5 类，与 `course_schema.v1.json` 一致）与 `readonly property bool slideTypeUnknown` | 否（仅新增只读属性） |
| 2 | 行 336–361（ScrollView 内容末尾） | 新增「未知 `slide.type`」兜底块：`visible: root.slideTypeUnknown`，显示「未知内容类型（type=…）」+ 说明 | 否（`visible` 为假时布局零占位） |

**未触碰**：布局结构、`Flow`/`Text` 宽度自适应逻辑（FIX02 的 IPA 换行修复）、样式与主题变量、既有 5 类渲染分支、翻页与练习交互、响应式断点。

---

## 3. B 的复核结论（逐项验证）

| 复核项 | 方法 | 结果 |
|---|---|---|
| 未知类型分支**在 v1 中确实不可达**（权威是整包 fail-closed） | 代码路径核对：`classroom_model._load_courses()` → `cschema.validate_bundle()` 违规即 `_courses=[]`，`hasSlide` 恒假 ⇒ `slideTypeUnknown` 恒假 | ✅ 一致，与契约 `§3.6.1` 第 1 条吻合 |
| 兜底块**绝不静默空白** | 直读代码：显示类型名 + 中文说明；无 `visible:false` 掩码 | ✅ |
| **不破坏既有响应式** | 运行 `ui_layout_probe`（10 档 560–1360，含 narrow/compact/medium/wide/全屏） | ✅ **52/52 PASS**，无越界 |
| **不破坏既有课堂行为** | 运行 `test_classroom_v1`(46) + `test_classroom_release_fix01`(40) + `test_classroom_app_bundle`(12) | ✅ 全部 PASS |
| **不破坏契约/UI 一致性** | 运行 `test_course_contract_v1`(20) | ✅ 20/20 |
| 属性名不与既有冲突 | 全文检索 `slideTypeUnknown` / `knownSlideTypes` 仅在新增区出现 | ✅ |
| 与 `knownSlideTypes` 枚举源一致 | 对照 `course_schema.v1.json` 的 `slide.type` 闭枚举 | ✅ 5 类完全一致 |

**B 判定：接收（ACCEPTED）。**

自本记录起，`client/src/classroom/qml/**` 的后续写入权**完整交还 B**；TC 不再写入该目录（如后续确需 TC 介入，须新开一条 `EXC-0x` 登记）。

---

## 4. 诚实声明

- 本记录的"复核"由**施工同一执行体**完成（本轮为单执行体推进多角色），**不构成独立验收**；
- `client/src/classroom/qml/**` 的**独立** GUI 复核（空状态、弹窗越界、断网、权限拒绝、课程错误态）由 **Agent QA** 在 `DELIVERY GATE 02` 四单独执行，本记录**不替代**该独立验收；
- 若 QA 判定该兜底块存在缺陷，仍按 `§2.2` 流程由 B 修正。
