# CLASSROOM V2 — 多 Agent 实施分工、接口合同与文件所有权矩阵

> **TASK_ID = CLASSROOM-V2-DESIGN ｜ 本文件为 V2 设计/施工链的协调契约权威主文档（LIVING DOCUMENT）**
> 依 ONE_TASK=ONE_LIVING_DOCUMENT 制度，本链采用**双权威**结构：本文件=分工/所有权/契约协调权威；
> `CLASSROOM_V2_UI_DESIGN.md`（REV1B，自带修订记录）=设计视觉权威。链内其余文档的收敛关系与全历史演进
> 见文末 **§9 V2 链文档收敛**（PROJECT-DOC-MERGE-01 批 2 追加）。

- 版本：**v1.1（PHASE 2 LIMITED START · 契约修正 01 同步）**（前身 v1 = Phase 0.5 接口合同草案）
- 制定：总控工程 Agent
- 依据：产品负责人总指令 §2 / §5 + Phase 0 基线审计（`CLASSROOM_V2_MASTER_AUDIT.md`）+ **`CLASSROOM_V2_PHASE2_CONTRACT_FIX_01.md`（四项契约修正权威）**
- 生效前提：**先调研、后设计、再开发**（`RESEARCH_FIRST = YES`）；`DUPLICATE_IMPLEMENTATION = PROHIBITED`
- 施工基线：`3754e502701713ee420e19b5badee5c421a77f88`

> 本文件是 Phase 2 并行施工的**冲突预防契约**。任何 Agent 只在其"拥有"的文件内写入；
> 跨所有权改动必须先报总控，由总控裁决归属。
>
> **v1.1 同步项**：§2 所有权矩阵与仲裁规则（修正①）、§3.6/§3.8 冻结唯一 Course Schema（修正②）、§3.7.1 哈希语义（修正③）、打包最小化见 `deploy/STUDENT_APP_PACKAGING_MINIMAL.md`（修正④）。

---

## 1. 角色与职责

| 代号 | 角色 | 主责 | 关键约束 |
|---|---|---|---|
| **TC** | 总控工程 Agent | 分工、接口合同、冲突裁决、集成、最终报告 | 不越权代写；结论必须亲自复算 |
| **A** | 画布与 UI/UX 总设计师 | 视觉系统、布局规范、组件规范、多状态画布、可落地 QML 规范（尺寸/状态/组件/资源）、设计复核 | 产出必须可在 PySide6/QML 落地，禁止只交效果图 |
| **I** | 教材导入与智能解析工程师（**新增，最高优先级**） | **复用既有 knowledge 导入 API**；提供教材数据接口、结构锚点解析、校对数据契约、网络适配；保留原始页码/章节/来源；"需人工确认"标记；版本管理 | **不重建解析器/不重复实现导入流水线**；**不与 B 并发修改 QML**（UI 需求经 A/B 落 QML）；本地优先；上云 OCR/模型须先告知并获授权；不得编造原书内容 |
| **B** | Mac 桌面 UI 开发（**QML 独占写者**） | 统一 AppShell、书库/导入/解析进度/校对/发布页安全 UI 骨架、三栏可调布局、响应式、弹窗边界、长文本/IPA 换行、键盘/焦点/滚动、高 DPI、无障碍 | `client/src/classroom/qml/**` **仅 B 可写**；发布操作**只用隔离 Mock**；**不开放真实服务端发布路由**；修选课弹窗右越界 |
| **C** | 实时语音与 AI 对话 | 麦克风权限/设备、音频输入输出、状态机、字幕事件、打断、异常中文提示、防重复连接、三模式（本地演示/Mock/真实在线）区分 | **复用** 既有语音适配层；**不直接改写 Tina 冻结链路**；真实付费调用禁止 |
| **D** | 数字人与 AI 老师形象 | 形象卡片、静态降级、听/思/讲/等/错状态、音频驱动口型接口、隐藏后课件区扩展、异常不崩 | **不改受保护未提交数字人文件**；禁止假口型冒充真实同步 |
| **E** | 课件、音标与教学引擎 | 课程目录/章节/课时、课件展示导航、英中例句音标、点读/跟读、讲解/练习/测验/小结、正误判定、课件-讲解-字幕同步 | 必须区分 20 天旧体系（已撤销）与用户教材；UK/RP 音标与 en-GB 音频须显式标注口音差异 |
| **F** | 学习记忆与学生体验 | 笔记/错题/待复习/掌握记录、课程与课时隔离、跨重启恢复、历史查询、GUI 删除、损坏恢复 | 结构化事件；默认不长期保存自由输入/录音；**不得冒充安全多学生记忆** |
| **G** | 服务端、配置与安全 | 老师选择（姓名/头像/声音）、学生界面去技术细节、管理员中文 GUI 配置、密钥仅经管理员导入、老师不可用原因、学生/管理员隔离、云请求授权与费用提示 | 不连 Tina 生产凭据；不自动升级模型验证证据等级；不改 NAS/生产 |
| **H** | Mac 打包与交付 | `.app` 生成（Finder 双击、免终端、不依赖 dev venv/`/tmp`、不读正式配置）、资源内嵌、版本可追溯、首开安全限制处理 | 不偷改系统安全设置；不付费签名/公证（除非另行授权） |
| **QA** | 独立质量与安全审计 | 代码/接口/权限/门禁审计、真实 QML 交互、课程 E2E、跨启动恢复、语音 Mock 正负向、数字人降级、安全自证伪、冻结与数字人哈希前后对比、安装包启动与版本一致性、**画布设计稿视觉验收** | **独立于施工者**；开发者自验≠独立 QA；被 429 等中断必须标 NOT_COMPLETED |

---

## 2. 文件所有权矩阵（写入权限）

> **本节为宪法级契约（PHASE2 CONTRACT FIX 01 · 修正① 裁定）。**
> 与 `CLASSROOM_V2_PHASE2_CONTRACT_FIX_01.md §1` 保持同口径；冲突时以该文档为准。

| 路径域 | 唯一所有者 | 写入权限 | 变更须知 |
|---|---|---|---|
| `client/src/classroom/qml/**`（含 `theme/`、`CourseArea.qml`） | **B（独占）** | 仅 B | A 提供规范、E 提供数据契约，均以**只读**交付；**任何他人不得写入**（含 I/E 的新增 UI 需求） |
| `client/src/classroom/classroom_model.py` | **TC（串行协调）** | 仅 TC | B / F / I **不得直接改**；须提「变更请求」由 TC 排期单次落地（本轮 TC 已落地 v1 校验 + C5 修复） |
| `client/src/classroom/course_schema.py`、`course_schema.v1.json` | **TC（冻结镜像）** | 仅 TC | 权威在 `modules/curriculum/`；镜像**必须与权威同步**，由一致性测试把关 |
| `client/src/classroom/data/**`（课程 bundle） | **E**（数据）/ TC（迁移） | E | 必须通过 `tools/migrate_course_bundle_v1.py --check` |
| `client/src/classroom/classroom_env.py` | **TC 协调**（F/B 提请求） | 仅 TC | 隔离语义受 `test_classroom_release_fix01`（T37–T40）保护 |
| `modules/curriculum/**` | **E** | E | schema 演进须 **version 递增**；改后须重同步客户端镜像 |
| `modules/knowledge/**`（parsers/imports/store） | **I** | I | EXTEND，不得重写；保持诚实降级语义 |
| `modules/voice/**`、`gateway/app/teacher_voice.py`、`teacher_context.py` | **C** | C | 复用既有语音层，不重建 |
| `modules/memory/**` | **F** | F | 遵守既有硬边界（禁 mastery/review/progress 键） |
| `modules/teaching/**`、`modules/adapters/workbench.py` | **E** | E | workbench 只读契约，禁引入写路径 |
| `modules/model/**`、`modules/teacher/**` | **G** | G | 凭据/门禁/端点策略/老师档案 |
| `client/src/ui/gui/**`、`client/src/avatar/**`、`client/probe_avatar_qml_offscreen.py` | **受保护（未提交基线）** | **无所有者** | **D 只能新建** `AvatarAdapter` 等适配层新文件，不得改这些 |
| `gateway/app/{turns,qwen,audio,protocol,ws,behavior}.py` | **冻结（Tina 六文件）** | **禁止任何人写入** | 测试 T37 会 SHA256 比对 |
| `gateway/app/admin/**` | **I**（导入面）/ **G**（安全面） | 见说明 | 白名单/鉴权改动属 G；导入路由实现属 I |
| `admin-v4/**`、`admin/**` | **G** | G | **不得进入学生 `.app`**（见修正④） |
| `client/classroom_app.spec`、`tools/build_classroom_app.sh`、`client/dist/**` | **H** | H | 打包清单变更须交**独立安全 Agent 核验** |
| `docs/engineering/product-v1/classroom-v2/**` | 各 Agent 写各自子目录 | — | 总报告由 TC 汇总 |
| 仓库根 `CLASSROOM_V2_*.md` | **TC** | 仅 TC | 最终交付件，他人不写 |

### 2.1 并发冲突仲裁规则（硬性 · 修正① 裁定）

| # | 规则 |
|---|---|
| **A-1** | **QML 单写者**：任一时刻 `client/src/classroom/qml/**` 只能有 B 在改。I/E 的新增 UI 需求**必须先由 A/B 落 QML**，I/E 只提供数据与契约。 |
| **A-2** | **model 串行**：`classroom_model.py` 采用「**变更请求 → TC 排期 → 单次落地**」。TC 落地时须跑 `test_classroom_v1` + `test_classroom_release_fix01` + `test_course_contract_v1`。 |
| **A-3** | **契约先行**：任何跨 Agent 字段必须先落到 `course_schema.v1.json`（或接口契约 §3/§8），再各自实现。**禁止**口头约定字段。 |
| **A-4** | **镜像同步**：改动 `modules/curriculum/course_schema.*` 后，**必须**在同一提交同步客户端镜像，否则一致性测试失败 = 构建红灯。 |
| **A-5** | **冻结优先**：与他人文件冲突时，**冻结/受保护** > 已裁定契约 > 既有实现 > 新需求。 |

### 2.2 所有权例外登记（**必须逐条留痕，事后交还所有者复核**）

> 例外 = 「非所有者因**已裁定的契约修正**而临时写入他人文件」。例外**不改变所有权**，
> 且**必须**在 `DELIVERY GATE` 交付时形成「复核接收记录」，由该文件唯一所有者确认或回退。
> 无登记的跨所有权写入一律视为违规。

| 例外编号 | 文件（受侵域） | 唯一所有者 | 实际写入者 | 原因（已裁定依据） | 范围 | 时间 | 复核接收 |
|---|---|---|---|---|---|---|---|
| **EXC-01** | `client/src/classroom/qml/CourseArea.qml` | **B（独占）** | **TC** | `CONTRACT_FIX_01A 一.2`：需在渲染层加「未知 `slide.type`」防御性兜底块，且 TC 当时正持该文件的契约修正上下文 | 仅新增 `knownSlideTypes` / `slideTypeUnknown` 属性与兜底块；**不动**既有布局/样式/交互 | 2026-10-12 | ✅ **B 已接收**（见 `ownership/QML_OWNERSHIP_EXCEPTION_01.md`；哈希与逐项核对） |

**EXC-01 收尾要求（已完成）**：①记录改动前后 SHA-256；②B 逐项复核（不破坏既有响应式/空状态/字体）；③确认后 **B 成为该文件的唯一后续写者**；④在 `DELIVERY GATE 02` 报告中如实披露。

---

## 3. 接口合同（跨 Agent 稳定契约）

### 3.1 统一课堂会话状态（防"左老师A/中课程B/右字幕旧会话"）
- 单一事实源：`ClassroomSession`（课程 · 课时 · 幻灯片 · 老师 · 语音状态 · 字幕 · 记忆游标）。
- 切换老师/课程/课时必须**原子替换会话**并清空上一会话的字幕/练习/临时态。
- **禁止**硬编码模拟数据掩盖功能缺失。

### 3.2 教材导入与解析契约（沿用 `modules/knowledge/imports.py`）

```
状态机：uploaded → parsing → preview_ready → committing → applied
                              ↘ failed / cancelled / expired
```
- 上传**绝不**直接写库；仅 `preview_ready` 后经**人工确认** `commit` 才写，且以 read-back 成功才报 `applied`。
- 解析结果须保留**原始页码/章节/来源**，支持逐页预览与原文对照。
- 不确定/缺失/答案不明确 → 标 `需人工确认`，**禁止编造**。
- 自动生成内容与原始内容**必须可区分并注明来源与性质**。
- 上云 OCR/模型前须**告知并获授权**；默认本地处理。

### 3.2.1 教材结构化抽取的三段边界契约（R1 × R2 协调一致，禁止双份实现）

| 段 | 归属 | 输入 → 输出 | 落点 |
|---|---|---|---|
| **A** | R1（解析层） | 文件 → 规范化文本，沿用现有 `(text, error_code)` 契约 | `modules/knowledge/parsers.py`（**现状不变**） |
| **B** | R1（解析层新增） | 文件 → **结构性锚点** `outline=[{level, title, page_or_offset, anchor_hint}]`；来源优先级：PDF outline/TOC → EPUB ncx/nav → docx Heading 样式 → pptx 标题占位符 → 扫描件降级 Docling；**不含语义判断** | `modules/knowledge/**`（新增，不重写现有三文件） |
| **C** | R2（语义层） | 锚点 → `course→lesson→slide` **语义切分** | `modules/curriculum/extract.py`（新增） |

**已知真实缺口（实现中必须处理，禁止静默掩盖）**：

1. `parsers.py` 的 PDF 路径走 **`pdfminer.six extract_text`（非 `pdftotext`）**：**多栏 PDF 会返回"顺序错乱但非空"的文本且不报错、无信号暴露** → 对"按正文正则切章节"属**静默错误**。段 C 必须以 **PDF outline 为权威信号**，并对正文正则加**顺序自检**。
2. `_parse_docx` 丢失 `p.style.name`（无 Heading 层级）；`_parse_pptx` 未区分标题占位符与正文 → **段 B 必须补齐**。

### 3.3 语音事件契约
- 事件：`user_speech / partial_transcript / final_transcript / teacher_speaking / barge_in / error(code)`。
- 三模式显式标注：`本地演示` / `本地模拟(Mock)` / `真实在线`；**Mock PASS ≠ 真实语音通过**。
- 异常码须映射为**中文原因**（非裸 1006/401/409）。

### 3.4 学习记忆事件契约（结构化）
```
{ course_id, lesson_id, item_id, item_type, prompt, answer, result, ts, source }
```
- 默认不落自由输入/录音/完整私人对话；默认仅"本机演示学习记录"。

### 3.5 数字人接口契约
- D 仅实现 `AvatarAdapter`（新文件）：`set_state(listening|thinking|speaking|waiting|error)`、`set_audio_level(v)`。
- 数字人不可用时降级为静态卡片，**不影响**课程/文字/语音；隐藏后课件区扩容。

### 3.6 课程数据契约 v1（**冻结唯一 Schema · 单一事实源**；总控定版）

> **权威文件**：`modules/curriculum/course_schema.v1.json`（draft-07）。本文为**摘要**，冲突时以权威 JSON Schema + `CLASSROOM_V2_PHASE2_CONTRACT_FIX_01.md §2` 为准。

**冻结模型 = 信封（Bundle）+ 课程（Course）两层**：

```
CourseBundle（文档 / 传输与落盘信封）
├─ schema : "classroom.course.bundle"   ★ 文档类型常量（必填，const）
├─ version: 1                           ★ **唯一版本号，只在文档级**（必填，const）
├─ generated_at? / label? / notice?     ← 文档级人读标签与说明（**不是来源**）
└─ courses : [ Course, ... ]            ★ 非空

Course（单课程 = 唯一"课程"实体）
├─ course_id : "crs_xxx"                ★ 取代历史 id
├─ revision  : int >= 1                 ★ 课程版本；发布幂等键 = course_id + revision
├─ title / subject? / level? / description?
├─ source : local-demo | admin-knowledge | user-textbook     ★ **仅在课程级**
├─ source_doc_id      : string | null   ★ 知识库 doc_id
├─ source_doc_hash    : string | null   ★ 知识库 content_hash（抽取文本哈希）
├─ source_file_sha256 : string | null   ★ 原文件字节哈希（≠ content_hash，见 §3.7）
└─ lessons : [ Lesson, ... ]            ★ 非空
   └─ Lesson { lesson_id, title, slides[] }   ← lesson_id 取代历史 id
      └─ Slide { type ∈ 5 类闭枚举 }          ← cover|vocab|sentence|practice|summary
```

**层级唯一性（逐字段裁定 —— 消除全部歧义的唯一口径）**：

| 字段 | 唯一层级 | 规则 |
|---|---|---|
| `schema` | 文档级 | const `classroom.course.bundle`；缺失/不符 → 校验失败 |
| `version` | 文档级 | const `1`；**course 内出现 `version` = 违规**（显式拒绝，消除双 version 歧义） |
| `source` | 课程级 | **文档级出现 `source` = 违规**（历史遗留，须下沉） |
| `course_id` | 课程级 | `^crs_[A-Za-z0-9_-]{4,64}$`；**不接受历史 `id`**（二者共存 = 违规） |
| `revision` | 课程级 | `int >= 1` |
| `source_doc_id`/`source_doc_hash`/`source_file_sha256` | 课程级 | 三字段**必填**（无真实值时显式写 `null`，**不得缺字段**） |
| `lesson_id` | 课时级 | 取代历史 `id` |
| `slide.type` | 幻灯片级 | 闭枚举 5 类 |

**定版约束（保留原 C1–C7 编号）**：

| # | 条款 | 说明 |
|---|---|---|
| **C1** | **单一事实源 + 冻结镜像** | 权威：`modules/curriculum/course_schema.py`（常量从 `course_schema.v1.json` **派生**）；客户端只读镜像 `client/src/classroom/course_schema.py`。**一致性口径（01A 订正，勿夸大）**：`course_schema.v1.json` **逐字节一致**（两侧 sha256 相等，实测 `f5bc1cb2…`）；`.py` **仅模块 docstring 不同**，**代码体逐语句一致**（由测试以 AST body 断言把关，**不得声称 `.py` 逐字节一致**）。由 `gateway/tests/course_schema_consistency_tests.py`（16/16）把关。客户端为独立 PyInstaller 包，运行期**不得** import `modules.*`；**禁止"两侧 import 同一份"**。 |
| **C2** | `source` 枚举定版 | `local-demo \| admin-knowledge \| user-textbook`（**课程级**） |
| **C3** | `version` 校验 **fail-closed** | 缺失/未知 → **不静默**，进入 `coursesError` 错误态 |
| **C4** | 未知 `slide.type` **不得静默跳过** | 渲染「未知内容类型（type=…）」占位 + 计入错误态提示 + 写日志 |
| **C5** | `practice.answer` 缺失/非法 | **不得落 `-1` 静默错判**（会把所有选项判错）→ 标记「答案待人工确认」，不计分、不判错，界面显式提示（**已修复**：`classroom_model._enter_slide_content` 置 `answerUnknown`，`answerPractice()` 不判分不判错） |
| **C6** | `phonetic` 缺失 | 直接**省略字段**，不得写 `null` 哨兵 |
| **C7** | `answer` 与选项重排 | 选项重排必须同步改 `answer`（UI 用 `index === answer` 判分） |

**来源绑定（**不得伪造知识库来源**）**：

| `source` | `source_doc_id` | `source_doc_hash` | `source_file_sha256` |
|---|---|---|---|
| `user-textbook` | **必填**（`^doc_[A-Za-z0-9]{4,64}$`，须真实存在） | **必填**（`^(?:sha256:)?[0-9a-f]{64}$`；**实测 KB 输出裸 64hex**） | 可得则必填；不可得 → `null` + UI「原文件哈希待确认」 |
| `admin-knowledge` | **必填** | **必填** | 同上 |
| `local-demo` | `null`（**结构性强制**） | `null`（**结构性强制**） | `null`（**结构性强制**） |

- `local-demo` 携带任意非 null 绑定值 → **校验失败**，客户端 `coursesError` + 零课程（schema `if/then` 强制，**非 UI 提示**）。
- 随包 `client/src/classroom/data/courses.json` 是 **local-demo bundle**；迁移工具**不得为它编造 doc_id**。
- 迁移工具：`tools/migrate_course_bundle_v1.py`（确定性 + 幂等）；已对随包数据执行（25 处改动，`--check` = `OK-V1`）。

> C4/C5 是**真实缺陷修复项**（静默空白页 / 静默错判），已在 Phase 2 关闭。

#### 3.6.1 无效 `slide.type`：fail-closed 校验 ⊥ 可见错误 UI（CONTRACT_FIX_01A 一.2）

两层机制**不是同一件事**，必须分清（消除 C4「占位」与「错误态」的歧义）：

| 层 | 机制 | 位置 | 结果 |
|---|---|---|---|
| **① 校验层（权威 · fail-closed）** | `course_schema.validate_bundle()` 发现未知 `type` → **整包判为违规** | `modules/curriculum/course_schema.py` | 未知类型**永远到不了渲染层** |
| **② 可见错误 UI（用户实际看到的）** | `classroom_model._load_courses()` 校验失败 → `_courses=[]` + `_load_error` → QML 空状态显示「课程数据不可用」+ **具体违规原因** | `classroom_model.py` / `CourseArea.qml` 空状态 | 用户看到**可解释的原因**，不是空白页 |
| **③ 渲染层占位（防御性兜底）** | 若被绕过校验仍拿到未知类型 → 渲染「未知内容类型（type=…）」 | `CourseArea.qml`（`slideTypeUnknown` 分支） | **绝不静默空白** |

**明确结论**：
1. **v1 中未知 `slide.type` 的权威行为 = 整包 fail-closed 拒绝**（②），**不是**逐页占位（③）。
   因整包被拒，③ 在 v1 中**结构上不可达**（防御性保留，覆盖"校验被绕过 / 未来版本前向兼容"）。
2. C4 的「不得静默跳过 → 空白页」由 **①+②** 保证：未知类型导致**整包不载入**并显式报错，
   而非"部分载入 + 该页空白"。**C4 的「渲染占位」表述仅指 ③ 这一兜底层**。
3. **不得**把 ③ 当作 ① 的替代（即：不允许"放宽校验、改由渲染层兜底"）——校验层必须先拒。
4. 测试覆盖：客户端 `K05`（未知 type → 错误态 + 零课程）、服务端 `S04a`（拒绝并给出可解释原因）。

### 3.7 教材锚点精度与仓储哈希（总控裁决，R1 提请）

- **本轮采纳选项 2**：段 A 沿用整篇 `extract_text()` 不变；`anchor_basis="page"`、`anchor_hint=null`。
- 理由：逐页提取会使 `_norm` 结果变化 → `store.py` 的 `_content_hash` 与 chunk `content_hash` 失配 → 已入库 PDF 去重/溯源基线失效，属**仓储级变更**，超出本轮解析域，且与 `imports.py`「拒绝而非截断」的确定性纪律耦合。
- 「字符级锚点（`anchor_basis="text_offset"`）+ PDF 内容哈希重基线化流程」列入**下一轮**，与 R6 联合评估。
- 段 B `order_confidence ∈ {authoritative, synthetic, unreliable}`；`unreliable` 直接转 `needs_review`，**不把不可信切分写库**。

#### 3.7.1 哈希语义区分（**修正③ 冻结 · `file_sha256` ⊥ `content_hash`**）

> 权威：`CLASSROOM_V2_PHASE2_CONTRACT_FIX_01.md §3`。**严禁混用、严禁互相冒充。**

| 名称 | 定义 | 输入 | 用途 | 落点 |
|---|---|---|---|---|
| **`source_file_sha256`**（原文件 SHA-256） | 用户**上传原文件字节**的 SHA-256 | PDF/DOCX/EPUB **文件字节** | 溯源「这份课程来自哪一个上传文件」 | 课程契约字段（接受 `^(?:sha256:)?[0-9a-f]{64}$` 或 `null`；展示规范化 `sha256:<hex>`） |
| **`source_doc_hash`**（知识库 `content_hash`） | 知识库对**抽取文本**归一化后的 SHA-256 | **抽取文本** | 知识库去重基线 / 发布来源一致性校验 | 课程契约字段（接受 `^(?:sha256:)?[0-9a-f]{64}$`；**实测 KB 输出裸 64hex**） |

**关键结论（不可违反）**：
1. 二者输入不同（字节 vs 文本）、**不可互相推导**；
2. 同一份 PDF 的 `file_sha256`（字节）与 `content_hash`（文本）**必然不同**；
3. **严禁**把 `content_hash` 填进 `source_file_sha256` 冒充原文件哈希；
4. **严禁**把 `file_sha256` 当作知识库去重依据（会破坏既有去重基线）。

**实测事实（口径建立在事实上）**：当前导入管线**只计算抽取文本哈希**，**不计算原文件字节哈希**
（`imports.py:96-97 _hash(text)`；`store.py:613 h = _content_hash(body)`）→ 因此**当前不存在可用的 `file_sha256`**。

**展示口径（诚实降级 · 唯一实现入口 `course_schema.file_hash_display(value)`）**：

| 情形 | 界面必须显示 |
|---|---|
| `source_file_sha256` 合法（裸 64hex 或 `sha256:<64hex>`） | 规范化为 `sha256:<hex>` 显示该哈希（可复制） |
| `null` / 缺失 / 格式非法 | **「原文件哈希待确认」** |
| `source_doc_hash` 合法 | 单独一栏显示为「**知识库内容哈希**」，与上者**分栏、分别标注**，绝不合并且不互相顶替 |

### 3.8 发布契约 v1（**对齐冻结唯一 Schema** · R2 定版 / 总控确认）

> 本节的**旧版曾把 `source` 放在文档级、`version` 出现在课程级** —— 已由 PHASE2 CONTRACT FIX 01 修正② 判为**违规**，以下为**对齐冻结 v1 的唯一口径**（详见 §3.6 与 `CLASSROOM_V2_PHASE2_CONTRACT_FIX_01.md §2`）。

**信封级（Bundle）**：`schema`(const `classroom.course.bundle`) · `version`(const `1`，**唯一**) · `generated_at?` · `label?` · `notice?` · `courses[]`(非空)。
（`label`/`notice` 是**文档级人读标签/说明，不是来源**；`source` **不得**出现在此层。）

**课程级（Course）**：`course_id` · `revision` · `title` · `subject?` · `level?` · `description?` · `source`(枚举) · `source_doc_id` · `source_doc_hash` · `source_file_sha256` · `lessons[]`。

- 生成端承诺：**永不输出未知 `slide.type`**（新增须"客户端 EXTEND + `version` 递增"先行）；`phonetic` optional；
  `vocab` 必供 `word/meaning/en/cn`；`practice.answer` 必供且 ∈ `[0, len(options))`，**或显式 `null`（答案待人工确认）**（draft-07 表达不了 → 两侧手写校验）。
- schema 权威与镜像落点见 C1（`modules/curriculum/` 权威 + 客户端镜像 + 一致性测试）。**禁止**按「两侧 import 同一份」实现（客户端为独立包）。
- **REV1B R2 增量（发布绑定）**：`course` 级**必须**携带 `source_doc_id` + `source_doc_hash`（= 来源文档 `content_hash`，见 §8.3），
  并在**发布时冻结**；schema 校验须把这二者纳入**必填**（缺失 → 校验失败，不得默认补空）。
  `source_file_sha256` 为第三绑定字段：可得则必填，不可得 → `null` + UI「原文件哈希待确认」（**不得用 `content_hash` 冒充**，见 §3.7.1）。
- **local-demo 强制**：`source = "local-demo"` 时三个绑定字段**必须全为 `null`**（结构性强制，非 UI 提示）。

---

## 4. 阶段与门禁

| 阶段 | 内容 | 产出 | 门禁 |
|---|---|---|---|
| P0 | 基线审计 + 基线统一 | `CLASSROOM_V2_MASTER_AUDIT.md` | ✅ 完成 |
| P0.5 | 六领域调研 + 复用决策 | 5 份调研交付物 | 调研齐 + 复用决策明确 |
| P1 | 画布整体设计 | `CLASSROOM_V2_UI_DESIGN.md` | 可在 QML 落地 + 六状态 + 书库系列页 |
| **P2-CF** | **PHASE 2 契约修正 01（前置）** | `CLASSROOM_V2_PHASE2_CONTRACT_FIX_01.md` | **✅ 完成**（① 所有权 ② 冻结 Schema ③ 哈希 ④ 打包） |
| **P2** | **并行施工（B/C/D/E/F/G/H/I）** | 各模块代码 + 测试 | **`MAIN_UI_CONSTRUCTION_GATE = APPROVED_FOR_NON_SENSITIVE_P2`**；文件所有权内、无越权；**链路 B 发布路由本轮不实现** |
| P3 | 集成 | `PHASE2_INTEGRATION_REPORT.md` | 会话状态统一、无假数据 |
| P4 | 联调回归 | 尺寸矩阵/异常/隔离/打包 | 全绿 |
| P5 | 独立 QA | `INDEPENDENT_QA_REPORT.md` | QA 独立于施工 |
| P6 | 真人验收准备 | `.app`（`MAC_APP_BUILD_REPORT.md`）+ `HUMAN_GUI_ACCEPTANCE_GUIDE.md`（原件已删除，PROJECT-DOC-MERGE-01 批准；恢复=项目外备份 `HUMAN_GUI_ACCEPTANCE_GUIDE.md`；现行复测入口=根目录 RETEST_GUIDE） | Finder 双击可用 |

> **P2 授权范围（产品负责人裁定）**：允许**非敏感 UI、解析适配、课程生成草稿、文字/Mock 语音、记忆、数字人适配及测试**进入 Phase 2。
> **禁止**在**独立安全复核前**实现、开放或启用**链路 B 最终发布服务端路由**。

---

## 5. 不可突破边界（全员强制）

1. 不改 Tina 冻结六文件（`gateway/app/{turns,qwen,audio,protocol,ws,behavior}.py`）。
2. 不读/用 Tina 生产密钥；不改 NAS/生产环境。
3. 不覆盖数字人受保护未提交文件（`client/src/ui/gui/**`、`client/src/avatar/**`、`client/probe_avatar_qml_offscreen.py`）。
4. 不执行破坏性 Git 清理（`reset/clean/stash`）；**本轮不 `git add`/`commit`**（改动全部 uncommitted）。
5. 不擅自调用真实付费模型；不把握手等同音频验证；**Mock PASS ≠ 真实语音通过**。
6. 不把部署 Token 当学生身份；不把演示进度冒充正式进度。
7. 不要求学生用终端/填 JSON/Token/URL（普通用户只用 GUI）。
8. 不伪造模型结果/字幕/语音/测试证据；不把 Mock 宣称为真实可用。
9. **不得伪造知识库来源**：`local-demo` 三绑定字段强制 `null`；正式来源必须有真实 `source_doc_id`/`source_doc_hash`。
10. **不得不当使用哈希**：`source_file_sha256` ⊥ `content_hash`，**严禁互相冒充**（见 §3.7.1）。
11. **未完成功能必须真实显示不可用原因**（不得静默空白/假数据掩盖）。
12. **不得向学生端传递管理员 Bearer**；**独立安全复核通过前不得开放实际发布路由**。
13. **绝不恢复固定 20 天学习计划**；用户教材是正式课程来源。
14. 遇保护边界阻断 → **继续其他独立任务并明确报告阻断原因**。

> **本次授权的边界**：本授权**不是**生产上线授权，**不是**链路 B 最终发布 API / 真实云语音 / NAS 部署授权。

---

## 6. 复用优先原则（调研驱动）

任何功能开工前必须确认结论之一：**REUSE / INTEGRATE / EXTEND / BUILD**。
选择 **BUILD** 必须给出"现有方案为何不适用"的证据。
已知必须 **禁止重复开发** 的既有资产见 `CLASSROOM_V2_MASTER_AUDIT.md` §6。

---

## 7. 后端验证新增判定（v1.1 · 见 `CLASSROOM_V2_PARSER_CAPABILITY_REPORT.md`）

> 来源：P0 只读验证（实测，非推断）。**这 4 条修正了 Phase 0 的能力盘点口径。**

| # | 判定 | 证据 |
|---|---|---|
| N1 | **教材导入解析后端已完整实现**，且是**已挂载的 10 条 HTTP 路由**（`upload→parse→preview→confirm→commit→read-back`，8 态机，预览 TTL 30min，`commit` 回读磁盘才报成功） | `gateway/app/admin/api_import.py`（318 行） |
| N2 | 教材导入 = **INTEGRATE 后端 API + BUILD 客户端 UI**；**严厉禁止**在客户端重建解析/导入流水线 | 客户端 `client/` 内 `admin/knowledge`、`parsers` 引用数 = **0** |
| N3 | 客户端**完全无网络层**（V1 课堂纯离线单机）→ V2 需**新增**「网关 API 客户端 + 网络四态 UI」能力 | `client/src/classroom/` 无任何 HTTP/WS 客户端代码 |
| N4 | 教材导入的 **UI 两侧皆不存在**（Web 管理端 `admin-v4/*.js` 亦零引用）→ 5 个页面确为 **BUILD** | `admin-v4/app.js`(2590 行) / `app-pro.js`(616 行) 零 `knowledge/import/dataset/parse` |

**对 Agent I 的范围修正（CONTRACT_FIX_01A 一.1 · 以 §2 最新所有权矩阵为准）**：Agent I 的交付物为
①**教材结构化数据接口 + 校对数据契约**（结构锚点 / 语义切分数据 / 「需人工确认」标记 /
  来源·页码·章节元数据）——**UI 呈现一律由 B 落 QML，I 不写 QML**（遵守 §2.1 A-1「QML 单写者」）；
②**知识库 API 适配层**（**复用**既有 `/admin/knowledge/import*` 导入 API；
  新增能力 = 客户端网关 API 客户端 + 网络四态数据；**与 G 协调地址与鉴权来源**）；
③**不得**重写 `modules/knowledge/**` 的解析与流水线（**EXTEND 也只允许补 EPUB 一类纯增量格式**）。

> **连网方式已裁定（非待决·01A 订正）**：`D1 = MAC_LOOPBACK_ISOLATED` —— 本机环回网关、
> 绑 `127.0.0.1`、最小权限会话鉴权（**学生端不得持有管理员 Bearer**，见 §8.5 与
> `security/D1_MINIMAL_PRIVILEGE_IMPORT_ACCESS.md`）。原 §7 中「本地环回网关 vs 公共平面窄口端点
> 为待决项 D1」的表述**作废**；`CLASSROOM_V2_UI_DESIGN.md §8` 第 5 项已记录该裁定。

**实测边界（须写入契约）**：P0 五格式 5/5 `PARSED`；扫描件 → `scanned_pdf_no_text`（诚实降级）；
**多栏排版存在「静默错序」缺陷**（窄栏距下跨栏粘连文本、`error=None`，已复现 + 阈值刻画）
→ 契约须新增版面风险提示位并强制人工校对（**C-EX2**）。


---

## 8. 双链路契约（REV1A 新增 · 产品负责人裁定「导入知识库 ≠ 发布可学习课程」）

> 设计侧约束见 `CLASSROOM_V2_UI_DESIGN.md` §4.9；画板见 `classroom_v2_design_canvas.html` 画板 A2。
> 本节的目的是**结构性防止两条链路被混为一谈**：它们有**不同产物、不同状态机、不同失败恢复、不同幂等键**。

### 8.1 链路总览

| 维度 | **链路 A · 导入教材 → 提交知识库** | **链路 B · 草稿 → 校对 → 发布可学习课程** |
|---|---|---|
| 状态 | **已实现（对接既有 API，禁止重建）** | **V2 新增（BUILD）** |
| 端点 | `POST /admin/knowledge/import`、`GET …/import[/{job_id}]`、`POST …/{job_id}/commit` | V2 新增路由（本轮仅定契约，**不实现**） |
| 执行体 | 网关（D1 下为**本机环回**进程，绑 `127.0.0.1`） | 客户端 + 网关（待 G 方案裁定） |
| **产物** | **知识库文档**：`doc_id` + 分块 + `content_hash` → **可检索的原文** | **可学习课程**：course schema v1（信封 `schema`/`version` + 课程 `course_id`/`revision`/`source`/`source_doc_id`/`source_doc_hash`/`source_file_sha256`/`lessons`）→ **可上课** |
| 幂等键 | `Idempotency-Key`（HTTP 头） | `course_id + revision`（课程 revision，单调递增） |
| **依赖** | **独立**（无前置） | **强依赖 A 的 `source_doc_id` 存在且 `content_hash == source_doc_hash`**（REV1B R2） |
| 落盘位置 | 知识库存储（`KnowledgeStore`） | 课程存储（V2 新增，与知识库**分离**） |

### 8.2 契约 A · 提交知识库（既有，只读引用）

```jsonc
// POST /admin/knowledge/import  (multipart: file, dataset_id, title?, preview_chars?)
// → 200 { available, job_id, status, format, ... }
// POST /admin/knowledge/import/{job_id}/commit  (body 必须含 confirm)
// → 200 { available, document: { id, chunk_count, ... }, readback_ok: true, job }
```

- **状态机（8 态）**：`uploaded → parsed → preview_ready → committed` ／ `cancelled` ／ `expired` ／ `failed`（＋重试回边）
- **硬语义（不得在客户端"简化"）**：
  1. **上传绝不写知识库**，只有 `commit` 才落盘；
  2. `commit` 后服务端**从磁盘回读**，仅当 `readback_ok=true` 才可对用户报「成功」；
  3. 预览 **TTL 30 min**，过期 → `job_expired`(410)；
  4. 内容重复 → `duplicate_content`(409) **且携带 `existing_doc_id`**（界面须提供"查看已有记录"，不得只报错）；
  5. 单文件 ≤ 20 MB → 超限 `body_too_large`(413)。
- **失败恢复**：`cancel` / `retry`（`job_not_cancellable`/`job_not_retryable` 是合法拒绝，界面须如实呈现）。
- **REV1B R2 补充（链路 B 的绑定源）**：`commit` 成功返回的 `document` 须含 **`id` + `content_hash` + `chunk_count` + `status`**（`_doc_public` 已提供，**不含正文**）。
  链路 B 的 `source_doc_id` / `source_doc_hash` **取自该返回体**；发布时以同一 `id` + `content_hash` 做存在性与一致性校验。

### 8.3 契约 B · 发布可学习课程（V2 新增，本轮定契约）

```jsonc
// 课程数据契约 v1（权威：modules/curriculum/course_schema.v1.json；客户端只读镜像）
// ── 信封级（Bundle）──────────────────────────────────────────────
// { "schema": "classroom.course.bundle",   // const，缺失/不符 → 校验失败
//   "version": 1,                          // const，**唯一版本号，只在文档级**；缺失/未知 → 错误态（fail-closed）
//   "label": "…", "notice": "…",           // 文档级人读标签/说明（**不是来源**）
//   "courses": [ … ] }                     // 非空
//   └─ 课程级（Course）──────────────────────────────────────────
//   { "course_id": "crs_…",                // 取代历史 id（二者共存 = 违规）
//     "revision": 1,                       // 课程版本（幂等键 = course_id + revision）
//     "title": "…",
//     "source": "user-textbook",           // 仅在课程级：user-textbook | admin-knowledge | local-demo
//     "source_doc_id": "doc_7f3a91c2",     // ← REV1B R2：必须指向链路 A 的真实产物（正式来源必填）
//     "source_doc_hash": "sha256:…",       // ← REV1B R2：发布时冻结的来源文档 content_hash
//     "source_file_sha256": "sha256:…",    // ← 修正③：原文件字节哈希；不可得 → null + UI「原文件哈希待确认」
//     "lessons": [ { "lesson_id": "…", "slides": [ { "type": "cover|vocab|sentence|practice|summary" } ] } ] }
//   ⚠ course 内出现 "version" = 违规；文档级出现 "source" = 违规（层级唯一性，见 §3.6）
```

> **R2 术语澄清（关键 · 已实测核对）**
> `KnowledgeStore`（`modules/knowledge/store.py`）的文档记录**当前不含 `revision` 字段**——
> 文档身份 = `id` + `content_hash` + `updated_at` + `status`（见 `add_document()` 落库结构）。
> 因此本契约把「知识库 revision 依赖」**如实落地为两个可校验量**：
> ① **`source_doc_id` 存在性 + `status == "ready"`**；② **`source_doc_hash`（= 文档 `content_hash`）冻结比对**。
> **不引入**虚构的"知识库 revision"字段。若后续 `KnowledgeStore` 引入版本化，再以可选 `source_revision` 绑定（**P0 不含，属推断延后项**）。

- **状态机**：`draft → proofreading → ready → published`（**＋ `blocked` 门禁态**）
- **门禁（结构性，非 UI 提示）**：
  ```
  publish_allowed == (critical_unresolved_count == 0) AND source_binding_valid
  source_binding_valid == (doc_exists(doc_id) AND doc.status == "ready" AND doc.content_hash == source_doc_hash)
  ```
  - `critical_unresolved_count > 0` ⇒ **发布接口必须拒绝**，且**客户端主按钮禁用并给出具体原因**；
  - **不得**存在"跳过校对直接发布"的代码路径；**不得**以默认值静默放行。
  - **关键项不可豁免（REV1B R1）**：门禁公式**不存在**"用户勾选接受即通过"的分支。
    关键未解决项只能通过**回溯校对页逐项解决**来消除，**不得**由任何前端开关、默认值或请求参数绕过。
  - **仅「可接受的非关键缺失」**允许带缺失发布，且必须**逐项记录**（写入 `accepted_gaps[]`）：
    ```jsonc
    "accepted_gaps": [
      { "item_id": "gap-29-page-answer",
        "severity": "non_critical",     // 仅允许 non_critical；critical 一律禁止入此数组
        "reason": "该页练习题在源教材中即无答案，不影响学习路径",
        "scope": ["lesson-12/slide-4"], // 影响范围（课时/页），必须可枚举
        "decided_by": "operator@local", // 历史：谁
        "decided_at": "2026-10-12T09:31:00Z", // 历史：何时（可追溯）
        "surfaced_in_course": true }    // 课程内对应位置持续显示「已知缺失」标记
    ]
    ```
    - **`severity: "critical"` 出现在 `accepted_gaps[]` 中 = 服务端硬拒绝**（无例外）。
    - 缺少 `reason` / `scope` / `decided_by` / `decided_at` 任一字段 → 拒绝（不得只存一句布尔"已接受"）。
- **来源依赖（REV1B R2，新增阻断位）**：
  - 发布前服务端**必须**校验：`source_doc_id` **存在**、文档 `status == "ready"`、且回读 `content_hash` 与 `source_doc_hash` **一致**；
    任一不满足 → 拒绝（错误码建议 `source_doc_missing` / `source_doc_invalid` / `source_content_drift`(409)，精确命名待 G 方案 S5 复核）。
  - **来源文档丢失 / 失效 ⇒ 禁止发起新的发布**（`publish_allowed = false`）。
  - **但已发布课程不得被级联删除或自动下架**——学生端保持可读（与 D-3「失败不互相吞掉」一致）。
  - 已存在草稿在**临时断网或导入失败后可以保留**（草稿本身不失效）；**恢复发布时必须重新通过来源校验**。
- **草稿的保存 / 回滚 / 发布幂等（REV1B R2）**：
  | 操作 | 语义 | 幂等键 | 约束 |
  |---|---|---|---|
  | 保存草稿 | `draft` 写入课程存储（与知识库存储分离） | `course_id + revision`（草稿 revision 单调递增） | 保存**不**触发门禁校验；草稿可带未解决关键项 |
  | 生成/重新生成草稿 | 覆盖当前未发布草稿，**不覆盖**已发布 revision | `course_id + (revision+1)` | 已发布版本保留，可回滚 |
  | 回滚 | 将 `current_revision` 指回上一个已发布 `revision` | `course_id + revision` | 回滚**不产生新 revision**；不回退已发布 revision |
  | 发布 | `ready` → `published`，绑定 `revision` | **`course_id + revision`** | 重复发布同一 `course_id + revision` → **返回既有结果，不产生副本**（HTTP 幂等语义） |
- **服务端门禁（REV1B R2，直接调用发布 API 同样被拒）**：
  - 门禁校验**不得**仅存在于客户端 / QML 层。发布路由**必须**在服务端独立执行：
    ① `critical_unresolved_count == 0`；② `accepted_gaps[]` 合法（无 critical、字段齐全）；③ 来源绑定有效（见上）。
  - **绕过 UI 直接 `POST` 发布接口**（curl / 脚本 / 学生端）与 UI 走**同一条**服务端校验路径；
    不满足 → **拒绝**（`publish_gate_blocked`），**不得**因为"请求未携带 UI 生成的 gating 字段"而放行。
  - 该路由的**精确路径 / HTTP 方法 / 资源归属（course_id 归属校验）/ revision 一致性 / 发布门禁**须按 **G 方案 S5** 逐条设计，
    **待独立安全复核通过后**方可实现（本轮不实现）。
- **失败恢复**：① 重新生成草稿（不覆盖已发布版本）；② 回滚到上一已发布 `revision`；③ 保留未发布草稿。

### 8.4 交互约束（结构性防混淆）

| # | 约束 | 反例（禁止） |
|---|---|---|
| D-1 | **A 成功 ≠ B 可发布**：知识库 `committed` 只解锁「生成课程草稿」，**不产生**「开始学习」入口 | 提交知识库后书库卡片直接出现「开始学习」 |
| D-2 | 书库卡片**同时**显示两套状态（知识库态 + 课程态） | 只显示一套，用户误以为可上课 |
| D-3 | **失败不互相吞掉**：A 失败不使 B 草稿失效；B 校对失败不清空 A 的文档 | 导入失败即删除课程草稿 |
| D-4 | **两套存储分离**：知识库存储与课程存储**不得**共用同一文件/集合 | 课程数据写进 `KnowledgeStore` |
| D-5 | `source_doc_id` 必须指向**真实存在**的知识库文档；悬空引用 → 错误态 | 用演示 doc_id 占位 |
| D-6 | **校对页无发布动作（REV1B R1）**：校对页只有校对操作 + 「进入发布流程」导航 | 校对页放「发布可学习课程」按钮 |
| D-7 | **关键项无豁免路径（REV1B R1）**：`publish_allowed` 不含"勾选接受即通过" | 一个 checkbox 就让 critical 项放行 |
| D-8 | **门禁在服务端（REV1B R2）**：绕过 UI 直接调用发布 API 同样被拒 | 门禁只写在 QML 里，curl 可绕过 |
| D-9 | **来源失效只阻断新发布（REV1B R2）**：不级联删除/下架已发布课程 | 来源被删 → 学生端课程一起消失 |

### 8.5 门禁与依赖

- 本契约**不授权**任何实现：链路 B 的落地须待 **G 的 D1 最小权限方案（S1–S5 裁定后修订版，仍待独立安全复核）** 与 **主 UI 设计门禁**（`MAIN_UI_CONSTRUCTION_GATE`：R1/R2/R7 补正已完成 → **允许进入 Phase 2**）双双通过。
- 链路 A **不得**新增客户端解析代码（`DUPLICATE_IMPLEMENTATION = PROHIBITED`）。
- **在 D1 安全方案获批前，不得把 `/admin/knowledge/import` 的管理员 Bearer 接入学生客户端。**
- **REV1B 依赖登记**：链路 B 的发布路由**强依赖** G 方案的 S5 逐条设计 + 独立安全复核；在 S5 通过前，`publish` 路由**不得**进入实现阶段。

---

## 9. V2 链文档收敛（LIVING SECTION · 2026-10-13 PROJECT-DOC-MERGE-01 批 2 追加）

> 本节为 Classroom V2 设计/施工链 11 份文档的**正文级整合**：继承链演进史、有效技术事实、门禁台账与取代关系。
> 契约类文件按「接口契约 Schema」例外保留原件；本节不取代任何契约正文（冲突时仍以 `PHASE2_CONTRACT_FIX_01` 为准，见 §2）。

### 9.1 链权威结构（双权威）

| 权威 | 管辖 | 依据 |
|---|---|---|
| **本文件（AGENT_PLAN v1.1）** | 角色分工（TC/A/I/B/C/D/E/F/G/H/QA）、文件所有权矩阵（§2 宪法级）、仲裁规则 A-1~A-5、契约 §3/§7/§8、链历史与台账 | 产品负责人总指令 §2/§5 + PHASE2_CONTRACT_FIX_01 四项修正同步 |
| **CLASSROOM_V2_UI_DESIGN.md（REV1B）** | 设计系统/令牌→QML 映射/布局规范/组件规范/画布唯一视觉依据 | 内含 REV1A→REV1B 修订记录；`MAIN_UI_CONSTRUCTION_GATE` 依据 |

### 9.2 链演进时间线（全历史）

| 阶段 | 文档 | 有效结论（正文级继承） |
|---|---|---|
| **Phase 0 基线审计** | MASTER_AUDIT（例外保留·审计快照） | ①施工基线统一：主检出 fast-forward 至 `3754e50`（FIX02 父提交恰为 `c298a4f`，无损）；②冻结六文件两次校验 SHA-256 全等；③数字人受保护文件快进前后完整保留；④`.app`↔源码↔提交一致（CourseArea.qml md5 同）；⑤旧「20 天课程」无硬依赖（全仓 1 处文本命中）；⑥后端存在大量可复用能力 → **REUSE/EXTEND 强制，禁止重复开发**；⑦自有代码 `LICENSE = PENDING PRODUCT OWNER`（合规未决） |
| **Phase 0.5 调研决策** | RESEARCH_SYNTHESIS（历史快照·风险台账仍有效引用） | 六领域 REUSE/INTEGRATE/EXTEND/BUILD 决策总表（教材解析=EXTEND 禁重写；语音=复用冻结层；数字人=复用 Live2D 分支+BUILD AvatarAdapter；UI=复用 V1 组件+BUILD 六态原语与书库 5 页；记忆=BUILD 持久化；**BUILD 仅 4 处重头**）；**不引入向量数据库**；三个真实缺陷入契约（多栏静默错序 P0、未知 `slide.type` 静默空白 P0、`practice.answer=-1` 静默错判 P0）；许可风险（EPUB 库 AGPL、Live2D Cubism 商业条款）须 PO 决策 |
| **Phase 1 设计** | UI_DESIGN（REV1A→REV1B，设计权威） | 设计原则 5 条、两条硬规则（设计样例≠真实状态；能力以 `GET /admin/knowledge/parsers` 真实返回为准，EPUB 文字型已实现/OCR 显示「暂不支持」）、令牌/布局/组件/QML 落地全规格；修订补正 R1–R12 已并入 §4.5/§4.6/§4.9/§9 |
| **设计差异链** | REV1A_DIFF / REV1B_DIFF（**被取代**·历史快照） | 逐条差异 ①–⑧ 与 REV1B 三补正（R1 校对页移除发布按钮/R2 链路 B 依赖/R7 溯源字段样例标注）、G 安全修订 S1–S5、H 部署修订 H1–H5+port 0 IPC、门禁证据——**结论已全部并入 UI_DESIGN 修订记录与本文 §3/§7/§8** |
| **契约修正** | PHASE2_CONTRACT_FIX_01（例外保留·四修正权威）+ CONTRACT_FIX_01A（例外保留·差异记录）+ SCHEMA_V1_ERRATA（例外保留·勘误 No.1） | 四修正=所有权锁定/Course Schema 冻结（信封+课程两层、单一事实源+镜像、同版本一致性测试）/哈希语义（`file_sha256`⊥`content_hash`）/打包最小化；01A 五项 TC 修订（无效 slide.type fail-closed+可见错误 UI、EXC-01 QML 跨所有权例外已由 B 复核接收等）；勘误=SHA-256 正则放宽（向后兼容已证明） |
| **Phase 2 施工** | 本文 v1.1 + 各 Agent 子目录 | Phase 2 有限启动；GUI 四面板 QML、classroom_api、`modules/curriculum/` 等功能源码已落地（见 INDEX CORRECTION 01 核实） |
| **DELIVERY GATE 02** | DELIVERY_GATE_02_REPORT（例外保留·交付证据） | A–F 全交付：可双击 `.app`（v2.0.0 build 2，158 MB，修掉包体启动即失败 P0）、19 张真实截图、离线解析→草稿→课堂展示、Mock 双向对话事件日志、独立 QA 摘要、一致性/冻结/数字人保护 13/13；测试=源码 277 + 网关 41 + 打包/E2E/Finder/边界 37 |

### 9.3 继承的有效技术事实（解析能力，源：PARSER_CAPABILITY_REPORT · 该报告仍为有效滚动文档）

- P0 五格式（TXT/MD/PDF/DOCX/PPTX）实测 `PARSED`（REAL_VERIFIED）；扫描件 PDF 诚实降级 `scanned_pdf_no_text`。
- **EPUB（D2）文字型已实现**：spine 定序、零新增依赖，开发自验 41/41（**独立 QA 待完成，不得当全仓回归**）；
  报告头部「生效状态」节为其 §1–§10 历史段落的唯一有效口径（EPUB 行已过期等，逐条标注）。
- **OCR（D3）已裁定推迟至 P1**：无任何 OCR 引擎，架构上无处安放；UI 在能力就绪前一律显示「暂不支持」。
- **多栏排版 PDF 静默错序缺陷已实证复现**（`error=None` 完全静默）→ 契约层须显式暴露（`layout_suspect` 留位，实现待 Phase 2）。
- 解析执行位置=**网关侧已完整实现**（`gateway/app/admin/api_import.py` 10 路由）；客户端网络层 V1 时不存在 → V2 新增。

### 9.4 当前门禁与未关闭台账（单点，替代各散文档状态块）

| 门禁/项 | 状态 |
|---|---|
| `MAIN_UI_CONSTRUCTION_GATE` | R1/R2/R7 补正完成 → **允许进入 Phase 2**（已进入并施工） |
| **硬门禁（产品负责人明令）** | **独立安全审核未通过前，不开放学生端白名单服务与最终发布 API**；发布路由本轮仅定契约（S5 依赖） |
| N1 D2 EPUB 独立 QA | PENDING（报告 §12 六条待办） |
| N2 D1 独立安全复核（S5+IPC） | NOT_COMPLETED（服务端门禁同路径验证） |
| N3 HUMAN_GUI_TEST（V1 FIX02 遗留） | PENDING（与 V2 无关，见 CLASSROOM-V1 链） |
| N4 多栏静默错序缓解 | 契约留位，实现待 Phase 2 |
| N5 许可待决（自有代码 LICENSE、Live2D 商业条款、EPUB AGPL） | 须产品负责人决策 |
| 打包滞后（01A 时点 `.app`=pre-FIX02 QML） | **已闭环**：GATE02 交付 build 2 → 中文入口任务三重验证 **Build 3**（包内 build_info=2.0.0 build3、CourseArea.qml=`eb016add` FIX02 版） |

### 9.5 链文档取代关系总表

| 文档 | 处置 |
|---|---|
| `CLASSROOM_V2_AGENT_PLAN.md` | **权威主文档**（本文件；§9 为收敛节） |
| `CLASSROOM_V2_UI_DESIGN.md` | **设计权威**（自带修订记录，继续独立维护） |
| `CLASSROOM_V2_PARSER_CAPABILITY_REPORT.md` | **有效滚动事实文档**（头部生效状态节为口径基准），继续独立维护 |
| `CLASSROOM_V2_PHASE2_CONTRACT_FIX_01.md` / `CLASSROOM_V2_CONTRACT_FIX_01A.md` / `CLASSROOM_V2_SCHEMA_V1_ERRATA.md` | **例外保留**（接口契约 Schema / 勘误）；冲突裁定权威 |
| `CLASSROOM_V2_MASTER_AUDIT.md` | **例外保留**（审计快照）；结论继承于 §9.2 |
| `CLASSROOM_V2_DELIVERY_GATE_02_REPORT.md` | **例外保留**（交付证据）；结论继承于 §9.2/§9.4 |
| `CLASSROOM_V2_REV1A_DIFF.md` / `CLASSROOM_V2_REV1B_DIFF.md` | 结论并入 §9.2 → **已删除**（PROJECT-DOC-MERGE-01 批准清理；恢复=项目外 `<offsite-backup>/merge01-20261013/docs/engineering/product-v1/classroom-v2/CLASSROOM_V2_REV1A_DIFF.md`，tracked 者另可 `git checkout HEAD --` 取回历史版）（REV1B_DIFF 同） |
| `CLASSROOM_V2_RESEARCH_SYNTHESIS.md` | 决策表继承于 §9.2、§7 风险台账继承于 §9.6 → **已删除**（PROJECT-DOC-MERGE-01 批准清理；恢复=项目外 `<offsite-backup>/merge01-20261013/docs/engineering/product-v1/classroom-v2/CLASSROOM_V2_RESEARCH_SYNTHESIS.md`，tracked 者另可 `git checkout HEAD --` 取回历史版） |
| 子目录 `api/ delivery-02/ demo/ deploy/ design/ evidence/ ownership/ research/ security/` | **原始证据/契约附件**，不收敛不移动 |

### 9.6 风险与未核实项台账（2026-10-13 补正：自 RESEARCH_SYNTHESIS §7 逐项继承；**原件已按产品负责人批准清理，技术内容已全部继承至本节，备份可恢复**——项目外 `<offsite-backup>/merge01-20261013/`，tracked 历史版另可 git 取回）

| 级 | 项 | §7 记录状态 | 当前映射（单点） |
|---|---|---|---|
| P0 | 多栏 PDF 静默错序 | 已定对策（outline 权威 + 顺序自检） | 契约已留位 `layout_suspect`，实现待 Phase 2（§9.4 N4） |
| P0 | 未知 `slide.type` 静默空白页 | 已定契约 C4 | 已入契约（CONTRACT_FIX_01A 修正②：fail-closed 校验 + 可见错误 UI） |
| P0 | `practice.answer=-1` 静默错判 | 已定契约 C5 | 已入契约（同上，C5 修复已落地） |
| P0 | 教材版权 + 自有代码许可未决 | 须产品负责人决策 | 仍开放（= §9.4 N5 之自有代码 LICENSE 项） |
| P1 | `ebooklib` AGPL 传染性 | 须决策 | 仍开放（§9.4 N5；D2 EPUB 路径当前零新增依赖，不受阻） |
| P1 | Live2D Cubism 商业条款 | 须决策（已有一手评估文件） | 仍开放（§9.4 N5；V1 已采用 QML Canvas 合规备选，见 AVATAR-VISION 链） |
| P1 | QML 玻璃模糊性能/HiDPI | **未核实**，建议玻璃 ≤3 处 | 仍开放（Phase 2 施工时须实测） |
| P1 | 深色模式硬编码色残留 | 须全量回归 | 仍开放（ClassroomTheme 新增深色轨道已入 UI_DESIGN，回归待 Phase 2） |
| P2 | Docling 能力与证据 | **未核实** | 仍开放（未选型，无依赖落地） |
| P2 | 云发音评估具体报价 | **未核实**（未选型） | 仍开放（未选型） |

（§9 收敛完成于 2026-10-13，PROJECT-DOC-MERGE-01 批 2；§9.6 为同日删除前安全补正追加。）
