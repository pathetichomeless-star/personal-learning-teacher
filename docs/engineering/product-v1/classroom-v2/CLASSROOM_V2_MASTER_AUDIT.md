# CLASSROOM V2 — 总控基线审计报告（Phase 0）

- 审计时间：2026-10-12 16:33 GMT+8
- 审计执行：总控工程 Agent（只读审计 + 一处无损基线同步）
- 仓库：`<project-root>`
- 分支：`p2b2-teacher-voice`
- 审计时 HEAD（施工基线统一后）：`3754e502701713ee420e19b5badee5c421a77f88`
- 审计时 HEAD（统一前）：`c298a4fdd93c37aef8667a6a6e5f428c0a4e9f49`

> 本报告是「先审计、再统一设计、再并行施工、再集成、再独立 QA」流程的第 0 阶段产物。
> 所有结论均可由下方命令复现；未验证项一律标注为**未核实/推断**，不填 PASS。

---

## 0. 结论摘要（Task-ordered）

1. **施工基线不一致问题已定位并解决**。主检出此前停在 `c298a4f`（不含 FIX02），而 FIX02 提交 `3754e50` 位于独立 worktree 分支。经核实 `3754e50` 的父提交**恰为** `c298a4f`，故以 **fast-forward** 无损方式将主检出统一到 `3754e50`（未产生合并提交、未触碰任何未提交文件）。
2. **Tina 冻结六文件在审计起点与统一后两次校验，SHA-256 与基线完全一致** —— 本轮起点对冻结链路零污染。
3. **数字人受保护未提交文件（5 个 modified + 1 个 untracked）在快进前后完整保留** —— 无覆盖、无丢失。
4. **已构建 `.app` 与源码、与 FIX02 提交一致**（`CourseArea.qml` md5 相同）。
5. **旧「20 天课程」在代码与课堂实现中不存在硬依赖**，全仓库文本命中仅 1 处（原型进度文档）。→ 解耦成本近似为零。
6. **仓库已存在大量可复用后端能力**（教材导入/解析流水线、知识库、模型注册与门禁、老师档案、语音适配层、教学引擎），**必须 REUSE/EXTEND，禁止重复开发**。
7. 发现一项**合规级未决项**：仓库自有代码 `LICENSE DECISION = PENDING PRODUCT OWNER`（见 `NOTICE.md`）——影响后续「以自有教材为主」的发布/分发合规表述。

---

## 1. 审计方法

- Git 层面：`status / log / branch -a -vv / worktree list / cat-file / merge-base --is-ancestor` 全部只读。
- 保护边界：对冻结六文件与 `.app` 内资源独立计算 `shasum -a 256` / `md5` 与基线比对。
- 能力盘点：按 `client/`、`gateway/`、`modules/`、`admin*/`、`tools/` 分层阅读目录与关键源文件头部。
- 需求纠偏审计：全仓库检索「20天 / 20 天 / 20-day / Workbench / 酒店英语」确定耦合面。
- **未执行**：任何 `reset / clean / stash`；任何生产/NAS 操作；任何真实付费模型调用。

---

## 2. Git 与工作树基线

### 2.1 分支与提交

| 对象 | 值 |
|---|---|
| 当前分支 | `p2b2-teacher-voice` |
| 审计起点 HEAD | `c298a4f`（CLASSROOM-V1-RELEASE-FIX-01 docs） |
| 统一后 HEAD | `3754e50`（CLASSROOM-V1-FIX-02） |
| FIX02 提交 `3754e502701713ee420e19b5badee5c421a77f88` | **存在**（`cat-file -t` = commit） |
| `3754e50^` | `c298a4f`（即主检出起点） → **可快进** |

### 2.2 历史提交链（近端）

```
3754e50 (ex workbuddy/p2b2-teacher-voice-f0edf42f) CLASSROOM-V1-FIX-02: 窄窗「单词+IPA」完整显示
c298a4f CLASSROOM-V1-RELEASE-FIX-01 docs: safety report + user guide + screenshots + test results
d185c28 CLASSROOM-V1-RELEASE-FIX-01: app entry + fail-closed isolation + responsive layout
6ea179e P2-B2-CLASSROOM-V1: standalone Mac student classroom
a608b4b P2-B2-R3-2C: fix teacher picker displayText self-reference (P2-1)
...
```

### 2.3 worktree 清单

| 路径 | HEAD | 分支 | 状态 |
|---|---|---|---|
| `<project-root>` | `c298a4f`→`3754e50` | `p2b2-teacher-voice` | 主检出 |
| `<user-home>/WorkBuddy/Worktrees/小智/p2b2-teacher-voice-f0edf42f` | `3754e50` | `workbuddy/p2b2-teacher-voice-f0edf42f` | FIX02 施工树（**已与主检出同点**） |
| `/private/tmp/p0_fix` | `31b024b` | `fix/admin-auth-p0` | prunable（历史遗留） |
| `/private/tmp/xiaozhi-admin-p0-rectification` | `f57b8cd` | `codex/admin-p0-rectification` | prunable（历史遗留） |

> 其他分支（`main` / `v4-admin-dev` / `admin-visual-v2` / `avatar-vision-v0` / `avatar-vision-v06-mac-native`）均**未改动**。

---

## 3. 施工基线统一（已执行，可追溯）

**问题**：过去独立 QA 发现「主工作树与 FIX02 工作树版本不一致」。事实核实：主检出源码 `client/src/classroom/qml/CourseArea.qml` 为 **pre-FIX02**（md5 `f6c70eaf…`），FIX02 树为 **post-FIX02**（md5 `eb6ff403…`）。

**执行**：
```
git merge --ff-only 3754e502701713ee420e19b5badee5c421a77f88
→ Updating c298a4f..3754e50  (Fast-forward, 15 files changed, +584 / -6)
```

**结果核验**：

| 项 | 值 | 判定 |
|---|---|---|
| 新 HEAD | `3754e50` | ✅ |
| `CourseArea.qml` md5 | `eb6ff4034f2430dc335778a402f7138d` | ✅ = FIX02 版 |
| 数字人未提交文件 | 全部保留（见 §4.2） | ✅ 未被覆盖 |
| 冻结六文件 | 哈希不变（见 §4.1） | ✅ |

> 快进仅改动 `CourseArea.qml` + 新增 `docs/.../release-fix02/**` 证据，与未提交文件路径**零重叠**，故无损。

---

## 4. 保护边界核验

### 4.1 Tina 冻结六文件（**不得修改**）

权威定义来源：`client/src/classroom/tests/test_classroom_v1.py` → `FROZEN`（T37 断言）。

| 文件 | 基线 SHA-256 | 统一后实测 | 判定 |
|---|---|---|---|
| `gateway/app/turns.py` | `e18a0d08ed3a28771dee71d39dd5563f52f3d1199043ac81b8d9a7b5a2a498bd` | 同左 | ✅ 一致 |
| `gateway/app/qwen.py` | `13d4800d416f678c33126e74bd857baab33afb5c9c3bfe2c80f6c0db798c9c32` | 同左 | ✅ 一致 |
| `gateway/app/audio.py` | `c2218a2c3fda520089473e312ce6ee3fac4436c540755a8c98fd634ff7a87c09` | 同左 | ✅ 一致 |
| `gateway/app/protocol.py` | `944e2d5ab4f0c2b13a51b547d366175cc18263575034566fda928b2a7b30d9f8` | 同左 | ✅ 一致 |
| `gateway/app/ws.py` | `dde9d427883721c17628f40c73bf417bc9c0ab32711d07a4f22e9ed7ad63dd1c` | 同左 | ✅ 一致 |
| `gateway/app/behavior.py` | `6d705960cb0154f17fa9eb0ce9ef1d651d0b4a64c9d4564fde5957d08d6a0088` | 同左 | ✅ 一致 |

### 4.2 数字人受保护未提交文件（**不得覆盖**）

| 状态 | 路径 |
|---|---|
| M | `client/probe_avatar_qml_offscreen.py` |
| M | `client/src/avatar/runtime/avatar_page.js` |
| M | `client/src/ui/gui/manager.py` |
| M | `client/src/ui/gui/qml/components/AvatarLive2D.qml` |
| M | `docs/engineering/product-v1/avatar-vision-v0/V1_MAC_GUI_ACCEPTANCE.md` |
| ?? | `client/src/avatar/runtime_server.py` |

> 上述 6 项在快进前后**逐项保留**。T39/T40 测试断言课堂模块与入口**不引用**这些文件（`manager.py` / `AvatarLive2D` / `avatar_page.js` / `runtime_server`），本轮施工必须继续遵守。

### 4.3 其他未跟踪产物（根目录，属既有交付，不得删除）

`CLASSROOM_V1_INDEPENDENT_QA_REPORT.md`、`CLASSROOM_V1_RELEASE_FIX02_INDEPENDENT_QA.md`、`docs/engineering/product-v1/{P2B2_ACCEPTANCE_REPORT.md, P2B2_REAL_VOICE_ACCEPTANCE_ENTRY.md, R3_2C_INDEPENDENT_SIM_QA_REPORT.md}`、`docs/engineering/product-v1/classroom-v1/qa-independent/`、以及提案文档 `小智中文后台_双模式与模型接入设计_V2.md` / `.zip`。

---

## 5. 交付物一致性（`.app` ↔ 源码 ↔ commit）

| 项 | 值 |
|---|---|
| `.app` 路径 | `<project-root>/client/dist/小智 AI 学生课堂.app` |
| Bundle ID / 版本 | `local.xiaozhi.classroom-demo` / `1.0.0` |
| 主可执行 | `Contents/MacOS/xiaozhi-classroom`，SHA-256 `146e47a3e3b8390ba5f4bc4aa2d9f6002c56b7f1dcaed7a8812c8de93476fe5f` |
| 包内 `CourseArea.qml` md5 | `eb6ff4034f2430dc335778a402f7138d` |
| 源码 `CourseArea.qml` md5 | `eb6ff4034f2430dc335778a402f7138d` |
| 判定 | **APP_MATCHES_SOURCE = YES** ✅（包内即 FIX02 版本） |

> 结论：当前 `.app` 已包含 FIX02 修复，且与统一后的源码一致。**但 V2 施工开始后源码将变化，故当前 `.app` 不得继续作为 V2 交付物**，需在 Phase 6 重新打包（见 §10、§13）。

---

## 6. 现有能力盘点（REUSE 候选，禁止重复开发）

### 6.1 后端业务模块 `modules/`

| 模块 | 关键文件 | 能力 | V2 价值 |
|---|---|---|---|
| `knowledge/` | `store.py`（37KB） | KnowledgeStore：数据集→文档→分块，**确定性词重叠检索**，原子 600 写，内容哈希，溯源，删除预览确认 | **教材检索基座（REUSE）** |
| `knowledge/` | `imports.py`（13KB） | 导入流水线 `upload→parse→preview→commit→read-back`；状态机 8 态；预览 TTL 30min；可取消/重试；上传绝不直接写库 | **「导入教材→解析→人工校对→发布」后端（REUSE/EXTEND）** |
| `knowledge/` | `parsers.py`（5.5KB） | P0 五格式 `.txt/.md/.pdf/.docx/.pptx`；依赖缺失→`parser_unavailable`；扫描 PDF→`scanned_pdf_no_text`；无 OCR、无网络 | **教材解析基座（EXTEND：补 EPUB/OCR）** |
| `model/` | `registry.py`(27KB)、`credentials.py`、`crypto.py`、`gating.py`、`endpoint_policy.py`、`probe.py` | 模型注册、密封凭据（只回显指纹）、授权位门禁、端点策略、能力探测 | **模型接入与门禁（REUSE）** |
| `teacher/` | `store.py`（26KB） | AI 老师档案持久化、创建/复制/切换/启停/删除 | **老师管理（REUSE）** |
| `teaching/` | `engine.py`、`store.py` | 多老师教学联动、会话存储、教材授权检索、学习结果保存 | **教学引擎（REUSE/EXTEND）** |
| `voice/` | `capability.py`、`engine.py`、`registry.py`、`session.py` | 通用语音适配层（能力探测/引擎注册/会话） | **语音适配层（REUSE）** |
| `memory/` | `store.py` | 记忆存储，**硬边界禁止** mastery/review/progress 类键 | 需遵守其边界，复习数据另建 store |
| `adapters/` | `workbench.py` | 外部英语学习工作台**只读**适配（GET-only，30s/300s 新鲜度，溯源） | 课程进度只读接入参考 |
| `_jsonstore.py` | `BaseJsonStore` | 原子写 + 600 权限 + 版本门控 + 损坏拒绝 + backup/migrate/rollback | **学习记录存储基座（REUSE）** |

### 6.2 网关 `gateway/`

| 文件 | 能力 | 边界 |
|---|---|---|
| `app/teacher_voice.py` | 老师实时语音路由（复用 `turns.Connection`，恒时令牌，逐老师凭据拷贝） | 新增，非冻结 |
| `app/teacher_context.py` | 教学上下文投影（政策→PolicyStore、教材→KnowledgeStore 回读、记忆恒禁用） | 新增，非冻结 |
| `app/main.py` / `app/admin/` | 网关与中文管理 API | 非冻结 |
| `app/{turns,qwen,audio,protocol,ws,behavior}.py` | **Tina 冻结六文件** | **禁止修改** |

### 6.3 客户端 `client/`

| 资产 | 能力 |
|---|---|
| `classroom_main.py` | 独立课堂入口（FIX01）：fail-closed 隔离校验、打包/源码双模资源解析、图形化错误、`--size`/`--geom-file` 自动化钩子 |
| `src/classroom/classroom_env.py` | 隔离目录解析（`XIAOZHI_CLASSROOM_DIR` > `XIAOZHI_DATA_DIR` > 默认演示目录），指向正式目录即拒绝启动 |
| `src/classroom/classroom_model.py`（22KB） | `ClassroomModel(QObject)`：课程/课时/幻灯片/老师/状态/标签页；`MODE_DEMO`；QML 上下文属性 |
| `src/classroom/qml/**` | `ClassroomWindow / CourseArea / InteractionPanel / TeacherAvatar / TeacherPanel` + `theme/ClassroomTheme.qml` |
| `src/classroom/tests/**` | `test_classroom_v1`(46) / `test_classroom_release_fix01`(40) / `ui_layout_probe` / `test_classroom_app_bundle`；含**冻结/数字人保护断言 T37–T40** |
| `src/classroom/data/courses.json` | 本地演示课程（3 门 × 2-1 课时，含 cover/vocab/sentence/practice/summary 幻灯片类型） |
| `classroom_app.spec` + `tools/build_classroom_app.sh` | PyInstaller 本机构建（不签名不公证），剪裁无关 Qt 模块 |
| `打开学生课堂.command` | 终端启动脚本（**已知 P1 缺陷**：暴露终端、依赖 dev venv、默认 /tmp 路径） |

### 6.4 数字人（既有成果，受保护）

- 分支 `avatar-vision-v0`（自研 Canvas rig）、`avatar-vision-v06-mac-native`（Live2D Cubism Web runtime）。
- 文档：`docs/engineering/product-v1/avatar-vision-v0/V1_LIVE2D_LICENSE_EVALUATION.md` 等 30 份。

---

## 7. 课程数据现状

| 数据源 | 位置 | 性质 | V2 定位 |
|---|---|---|---|
| 演示课程（酒店英语/日常口语/数字与时间） | `client/src/classroom/data/courses.json` | `source: "local-demo"`，**非正式教材** | **仅作明确标注的本地演示样本**，不得作为正式教学内容默认来源 |
| 用户自有教材 | 尚未进入仓库 | **第一优先级** | V2 核心：导入→解析→校对→发布 |
| 外部工作台进度 | `modules/adapters/workbench.py`（只读） | 外部权威数据 | 只读接入，**不得**将演示进度写成正式进度 |

> 演示课程 JSON 顶层已含诚实声明字段（`label` / `notice`）："本课程数据为随客户端分发的本地演示内容……不代表已接入正式教材或真实 AI 生成能力。"→ 该诚实口径必须延续到 V2。

---

## 8. 「20 天课程」解耦审计（**AUDIT_ONLY**）

- 全仓库检索 `20天 / 20 天 / 20-day / 20day / 二十天`：**仅 1 处文本命中**（`prototypes/v4-release-progress/DEPLOYMENT_STATUS.md`），位于历史原型进度文档。
- **代码、课堂实现、课程数据中不存在「20 天课程」硬依赖。**
- 结论：`LEGACY_20_DAY_DEPENDENCIES = AUDIT_ONLY`，实际解耦成本 ≈ 0（无需删除任何文件；不修改受保护既有功能）。
- 基线指令更新：**不再围绕 20 天课程新增功能；不将其列为验收目标；不将其作为产品规则**。若未来发现间接依赖，先报告影响范围再受控整改。

---

## 9. 许可与合规状态（**重大未决项**）

- `NOTICE.md` 明确：**本仓库自有代码 `LICENSE DECISION = PENDING PRODUCT OWNER`** —— 尚未授予任何许可。
- 混合来源：
  - `client/` = `py-xiaozhi` fork，**MIT**（Copyright (c) 2025 Junsen），上游许可原文保留于 `client/LICENSE`；
  - 外部未 vendored 依赖：旧 XiaoZhi server（MIT，镜像消费）、`word-master`（Apache-2.0）、英语学习工作台（MIT 内容 + 第三方内容排除，LAN-only，应用主体未授权）；
  - `THIRD_PARTY_LICENSES.md` 为机制化核验清单。
- **影响**：V2「以用户自有教材为主」涉及教材内容版权与再分发；自有代码授权未决。→ 在 Phase 3/6 的设计与交付文档中必须**显式声明**，不得默认「可自由分发」。

---

## 10. 能力缺口清单（V2 目标 − 现状）

| # | 目标能力 | 现状 | 缺口 | 建议路径 |
|---|---|---|---|---|
| G1 | 教材解析：EPUB / 扫描页 / 书页图片 OCR | `parsers.py` 五格式，**无 EPUB / 无 OCR** | 缺 EPUB、OCR、图片预处理 | EXTEND（复用 parsers 骨架） |
| G2 | 目录/章节自动识别 | 仅线性化文本 | 缺章节切分 | EXTEND |
| G3 | 音标/例句/练习/答案结构化抽取 | 无 | 缺教学结构抽取 + 人工确认标记 | BUILD/EXTEND |
| G4 | 书库/导入/解析进度/校对/发布 **GUI** | 仅后端流水线，**无 UI** | 缺 5 个页面 | BUILD（客户端 QML） |
| G5 | 课程草稿生成（课程/课时/内容/练习） | 无 | 缺编排 | EXTEND（复用 knowledge+model） |
| G6 | AI 老师围绕当前教材教学 | `teacher_context.py` 已有教材回读骨架 | 缺章节级绑定 | EXTEND |
| G7 | 学习记录持久化（笔记/错题/复习/掌握） | 客户端**仅内存**，`endLearning()` 清空 | 零持久化、无 SRS | BUILD（复用 `_jsonstore`） |
| G8 | 跨重启恢复 + 课程/课时隔离 | 无 | 缺失 | BUILD |
| G9 | 发音评估 / IPA / 跟读纠音 | 无 | 缺失 | INTEGRATE/BUILD |
| G10 | 真实打断（barge-in） | 未验证 | 缺语义验证 | EXTEND（冻结链路不可改，走适配层） |
| G11 | 数字人接入课堂 | 独立分支成果，未接入课堂 | 缺适配层 | INTEGRATE（**不改受保护文件**） |
| G12 | 三栏可调布局 + 深色模式 + 六状态 | FIX01 响应式已有 | 缺三栏可调/深色/书库系列状态 | EXTEND |
| G13 | 选课弹窗越界 / 窄窗控件裁剪 | FIX01/FIX02 已修主问题 | 需 V2 复核（新布局回归） | EXTEND |
| G14 | `.app` 免终端 + 版本可追溯 | 已有（但为 V1 内容） | 需 V2 重打包 | REUSE 构建链 |
| G15 | 独立 QA 全链路 | V1 已做过 | 需 V2 重做 | 流程 |

> **§10 修订（v1.1 · P0 实测）**：G1/G4 的"现状"栏已由只读验证补强——
> ①教材导入**后端不仅存在，且是已挂载的 10 条 HTTP 路由**（`gateway/app/admin/api_import.py`），
> 故 G4 缺口应读作"**缺 UI + 缺客户端网络层**"，而非"缺后端"；
> ②**客户端完全无网络层**（V1 课堂纯离线）→「网关 API 客户端 + 网络四态 UI」为 V2 **新增 BUILD 能力**；
> ③EPUB 可**零新增依赖 EXTEND**（zip + `lxml`，镜像已含 `lxml==6.1.3`）；
> ④扫描页 OCR 无引擎且与"解析在网关"分层冲突 → `PENDING` 决策。
> 详见 `CLASSROOM_V2_PARSER_CAPABILITY_REPORT.md`。G1 另注：**多栏排版存在已复现的"静默错序"缺陷**，须以契约风险位 + 强制人工校对兜底。

---

## 11. 风险清单

| 级别 | 风险 | 说明 | 缓解 |
|---|---|---|---|
| P0 | 施工基线再次分叉 | 多 worktree + 未提交数字人文件 | 已统一至 `3754e50`；后续**单点施工 + 明确文件所有权** |
| P0 | 冻结链路被误改 | 六文件被适配层"顺手改" | T37 断言 + 每阶段哈希复验；改动只能发生在**非冻结**新增文件 |
| P0 | 数字人未提交文件被覆盖 | 被课堂 QML 误引用/重写 | T39/T40 断言；施工前 `git status` 快照 + 哈希留证 |
| P1 | 重复造轮子 | 后端已有解析/导入流水线 | 本报告 §6 + 六领域调研的 REUSE 决策强制约束 |
| P1 | 冒充真实能力 | Mock 语音 / 演示进度 / 假口型 | 诚实口径（`source`/`notice`/`本地模拟`标记）写入设计规范 |
| P1 | 许可未决 | 自有代码无授权 + 教材版权 | §9 显式声明；不默认可分发 |
| P2 | `.command` 入口缺陷 | 终端暴露 / dev venv / `/tmp` | V2 以 `.app` 为唯一学生入口 |
| P2 | 打包体积 | Qt 插件连带收集 | 复用 spec 剪裁策略 |

---

## 12. 需求基线更新（本轮正式生效）

**撤销**此前任何「保留 20 天课程体系 / 固定学习周期」的指令。

| 键 | 值 |
|---|---|
| `20_DAY_CURRICULUM_REQUIRED` | **NO** |
| `USER_TEXTBOOK_FIRST` | **YES** |
| `FIXED_20_DAY_SCHEDULE` | **DISABLED** |
| `LEGACY_20_DAY_DEPENDENCIES` | **AUDIT_ONLY** |
| `USER_FILES_PROTECTED` | **YES** |
| `TINA_FROZEN` | **UNCHANGED** |
| `RESEARCH_FIRST` | **YES** |
| `DUPLICATE_IMPLEMENTATION` | **PROHIBITED** |
| `EXISTING_CAPABILITIES_AUDITED` | **YES** |
| `OPEN_SOURCE_LICENSES_REVIEWED` | **IN_PROGRESS（R1–R6 进行中）** |
| `IMPLEMENTATION_REQUIRES_REUSE_DECISION` | **YES** |

**正式主流程（新）**：
`我的书库 → 导入教材 → AI 解析 → 人工校对 → 发布课程 → 选择 AI 老师 → 开始学习`

**约束**：
- 无教材时显示**空状态 + 导入引导**，**不自动指定**任何内置课程；
- 演示课件必须显式标注「本地演示样本」；
- 解析结果**不得覆盖**已确认的原始教材数据；自动生成内容必须注明来源与性质。

---

## 13. 最终状态块（Phase 0）

```
CLASSROOM_V2_UI = PENDING
CANVAS_DESIGN_IMPLEMENTED = PENDING
MAC_APP_BUILD = PENDING (V1 .app 存在且与源码一致，但非 V2 内容)
FINDER_LAUNCH = PENDING (V1 已实测，V2 待重打包复验)
COURSE_SELECTOR = EXTEND (V1 已有，需接书库)
LESSON_ENGINE = EXTEND (V1 演示课件已有；教材驱动待建)
BILINGUAL_COURSEWARE = EXTEND
IPA_AND_PRONUNCIATION = PENDING
VOICE_INPUT_PIPELINE = EXTEND (modules/voice + teacher_voice 已有)
VOICE_OUTPUT_PIPELINE = EXTEND
VOICE_BARGE_IN = PENDING
VOICE_MOCK_E2E = PENDING
REAL_VOICE_AUDIO_TEST = BLOCKED (未授权付费模型)
AVATAR_INTEGRATION = PENDING (既有分支成果，受保护，未接入课堂)
TEACHER_SELECTION = EXTEND (V1 GUI 已有)
STUDENT_MEMORY_PERSISTENCE = PENDING (当前仅内存)
CROSS_RESTART_RECOVERY = PENDING
COURSE_PROGRESS_INTEGRATION = PENDING (20天已撤销，改教材章节关联)
ADMIN_GUI_CONFIGURATION = EXTEND (admin-v4 已有；教材解析管理待建)
RESPONSIVE_LAYOUT = EXTEND (FIX01/FIX02 已有)
SECURITY_AUDIT = PENDING
INDEPENDENT_QA = PENDING
HUMAN_GUI_TEST = PENDING
REAL_MODEL_REQUESTS = NONE (本轮零调用)
TINA_FROZEN = VERIFIED_UNCHANGED (六文件哈希两次一致)
DIGITAL_HUMAN_PROTECTED_FILES = PRESERVED (6 项未提交文件完整保留)
NAS_CHANGED = NO
READY_FOR_HUMAN_ACCEPTANCE = NO
GIT_COMMITS = base=3754e50 (p2b2-teacher-voice)
```

---

## 14. Phase 0 交付回执

- ✅ 基线审计完成（本文件）
- ✅ 施工基线统一（fast-forward 至 `3754e50`，可追溯）
- ✅ 冻结六文件 SHA-256 双重校验一致
- ✅ 数字人受保护文件完整保留
- ✅ `.app` ↔ 源码一致性确认
- ✅ `20_DAY_CURRICULUM_REQUIRED = NO` 等需求基线更新
- ⏳ 六领域成熟方案调研（R1–R6 并行进行中）
- ⏳ 复用决策清单 / 差距表 / 选型与许可审查 / 分工与依赖 / 最小集成验证方案（Phase 0.5，待调研回收）

*本报告为施工前置基线，后续阶段不得据以声称任何功能已实现。*
