# CLASSROOM V2 — PHASE 2 契约修正 01（CONTRACT FIX 01）

- 依据：产品负责人 **PHASE 2 LIMITED START** 裁定（`MAIN_UI_CONSTRUCTION_GATE = APPROVED_FOR_NON_SENSITIVE_P2`）
- 施工基线：`3754e502701713ee420e19b5badee5c421a77f88`
- 状态：**`COMPLETED`**（四项修正已落地并附可复现证据）
- 性质：**契约层冻结**。修正完成后才允许按 §5 分组进入并行施工。
- **授权边界**：本授权**不是**生产上线授权，**不是**链路 B 最终发布 API / 真实云语音 / NAS 部署授权。

---

## 0. 一页速览

| # | 修正项 | 关键产出 | 证据 |
|---|---|---|---|
| ① | **文件所有权锁定** | 宪法级所有权表 + 冲突仲裁规则（`CLASSROOM_V2_AGENT_PLAN.md §2`） | 本文 §1 |
| ② | **冻结唯一 Course Schema** | `modules/curriculum/course_schema.v1.json`（单一事实源）+ 客户端冻结镜像 + 校验器 + **一致性测试 16/16** | `gateway/tests/course_schema_consistency_tests.py`（服务端）· `client/src/classroom/tests/test_course_contract_v1.py`（客户端） |
| ③ | **哈希语义区分** | `source_file_sha256` ⊥ `source_doc_hash`；无真实值 → 「原文件哈希待确认」 | `course_schema.file_hash_display()` · 测试 K13–K15 |
| ④ | **打包最小化** | 学生 `.app` 允许清单 + 拒绝清单 + 构建期扫描规则 | `deploy/STUDENT_APP_PACKAGING_MINIMAL.md` |

---

## 1. 修正① · 文件所有权锁定

### 1.1 裁定（产品负责人原文要点）

1. **Agent B 独占** `client/src/classroom/qml/**`；
2. **Agent I** 提供教材数据接口、解析及网络适配，**不与 B 并发修改 QML**；
3. 共享 `classroom_model.py` 的所有改动**由 TC 串行协调**。

### 1.2 落地后的所有权表（覆盖 `AGENT_PLAN §2`）

| 路径域 | 唯一所有者 | 写入权限 | 变更须知 |
|---|---|---|---|
| `client/src/classroom/qml/**` | **B（独占）** | 仅 B | **任何他人不得写入**；E 提供契约、A 提供规范，均以**只读**方式交付 |
| `client/src/classroom/classroom_model.py` | **TC（串行协调）** | 仅 TC | B / F / I **不得直接改**；须提「变更请求」由 TC 排期落地（本轮 TC 已落地修 v1 与 C5） |
| `client/src/classroom/course_schema.py`、`course_schema.v1.json` | **TC（冻结镜像）** | 仅 TC | 权威在 `modules/curriculum/`；镜像**必须与权威同步**，由一致性测试把关 |
| `client/src/classroom/data/**`（课程 bundle） | **E**（数据）/ TC（迁移） | E | 必须通过 `tools/migrate_course_bundle_v1.py --check` |
| `client/src/classroom/classroom_env.py` | **TC 协调**（F/B 提请求） | 仅 TC | 隔离语义受 `test_classroom_release_fix01` 保护 |
| `modules/curriculum/**` | **E** | E | schema 演进须 **version 递增**；改后须重同步客户端镜像 |
| `modules/knowledge/**`（parsers/imports/store） | **I** | I | EXTEND，不得重写；保持诚实降级语义 |
| `modules/voice/**`、`gateway/app/teacher_voice.py` | **C** | C | 复用既有语音层，不重建 |
| `modules/memory/**` | **F** | F | 遵守既有硬边界（禁 mastery/review/progress 键） |
| `modules/teaching/**`、`modules/adapters/workbench.py` | **E** | E | workbench 只读契约，禁引入写路径 |
| `client/src/avatar/**`、`client/src/ui/gui/**`、`client/probe_avatar_qml_offscreen.py` | **受保护（未提交基线）** | **无所有者** | **D 只能新建 `AvatarAdapter` 等适配层新文件**，不得改这些 |
| `gateway/app/{turns,qwen,audio,protocol,ws,behavior}.py` | **冻结（Tina 六文件）** | **禁止任何人写入** | 测试 T37 会 SHA256 比对 |
| `admin-v4/**`、`admin/**` | **G** | G | **不得进入学生 `.app`**（见修正④） |
| `client/classroom_app.spec`、`tools/build_classroom_app.sh`、`client/dist/**` | **H** | H | 打包清单变更须交**独立安全 Agent 核验** |
| `gateway/app/admin/**` | **I**（导入面）/ **G**（安全面） | 见说明 | 白名单/鉴权改动属 G；导入路由实现属 I |
| `docs/engineering/product-v1/classroom-v2/**` | 各 Agent 写各自子目录 | — | 总报告由 TC 汇总 |
| 仓库根 `CLASSROOM_V2_*.md` | **TC** | 仅 TC | 最终交付件 |

### 1.3 并发冲突仲裁规则（硬性）

| # | 规则 |
|---|---|
| A-1 | **QML 单写者**：任一时刻 `client/src/classroom/qml/**` 只能有 B 在改。I/E 的新增 UI 需求**必须先由 A/B 落 QML**，I/E 只提供数据与契约。 |
| A-2 | **model 串行**：`classroom_model.py` 采用「**变更请求 → TC 排期 → 单次落地**」。TC 落地时须跑 `test_classroom_v1` + `test_classroom_release_fix01` + `test_course_contract_v1`。 |
| A-3 | **契约先行**：任何跨 Agent 字段必须先落到 `course_schema.v1.json`（或接口契约 §3），再各自实现。**禁止**口头约定字段。 |
| A-4 | **镜像同步**：改动 `modules/curriculum/course_schema.*` 后，**必须**在同一提交同步客户端镜像，否则一致性测试失败 = 构建红灯。 |
| A-5 | **冻结优先**：与他人文件冲突时，**冻结/受保护** > 已裁定契约 > 既有实现 > 新需求。 |

---

## 2. 修正② · 冻结唯一 Course Schema

### 2.1 冲突诊断（实测，非推断）

| 来源 | 结构 | 冲突点 |
|---|---|---|
| `AGENT_PLAN §3.8` | 顶层 `version` + `source` + `label` + `notice` + `courses[]` | 把 **来源放在文档级** |
| `AGENT_PLAN §8.3` | 单课程对象：`version` + `course_id` + `revision` + `source` + `source_doc_id` + `lessons` | **来源在课程级**、**version 也在课程级** |
| `client/src/classroom/data/courses.json`（迁移前） | 顶层 `version`/`source`/`label`/`notice` + `courses[].id` | 来源文档级、课程用 `id` 无 `revision` 无来源绑定 |

→ **三重冲突**：① 来源在哪一层；② `version` 是否重复出现；③ 课程标识是 `id` 还是 `course_id`。
实测迁移前对照冻结 schema 有 **46 处违规**。

### 2.2 冻结模型：**信封（Bundle）+ 课程（Course）两层**

```
CourseBundle（文档 / 传输与落盘信封）
├─ schema : "classroom.course.bundle"     ★ 文档类型常量（必填，const）
├─ version: 1                             ★ **唯一版本号，只在文档级**（必填，const）
├─ generated_at? : string
├─ label?  : string       ← 文档级人读标签（不是来源）
├─ notice? : string       ← 文档级免责/说明（不是来源）
└─ courses : [ Course, ... ]              ★ 非空

Course（单课程 = 唯一"课程"实体）
├─ course_id : "crs_xxx"                  ★ 取代历史 id
├─ revision  : int >= 1                   ★ 课程版本；发布幂等键 = course_id + revision
├─ title, subject?, level?, description?
├─ source : local-demo | admin-knowledge | user-textbook     ★ **仅在课程级**
├─ source_doc_id      : string | null     ★ 知识库 doc_id
├─ source_doc_hash    : string | null     ★ 知识库 content_hash（抽取文本哈希）
├─ source_file_sha256 : string | null     ★ 原文件字节哈希（≠ content_hash，见修正③）
└─ lessons : [ Lesson, ... ]              ★ 非空
   └─ Lesson { lesson_id, title, slides[] }
      └─ Slide { type ∈ 5 类闭枚举, ... }
```

### 2.3 层级唯一性（逐字段裁定 —— 消除全部歧义的**唯一口径**）

| 字段 | **唯一层级** | 允许层级 | 规则 |
|---|---|---|---|
| `schema` | **文档级** | 仅 Bundle | const `classroom.course.bundle`；缺失/不符 → 校验失败 |
| `version` | **文档级** | 仅 Bundle | const `1`；**course 内出现 `version` = 违规**（显式拒绝，消除双版本歧义） |
| `course_id` | **课程级** | 仅 Course | `^crs_[A-Za-z0-9_-]{4,64}$`；**不接受历史 `id`**（同时存在 = 违规） |
| `revision` | **课程级** | 仅 Course | `int >= 1` |
| `source` | **课程级** | 仅 Course | **文档级出现 `source` = 违规**（历史遗留，须下沉） |
| `source_doc_id` / `source_doc_hash` / `source_file_sha256` | **课程级** | 仅 Course | 三字段**必填**（无真实值时显式写 `null`，**不得缺字段**） |
| `lesson_id` | 课时级 | 仅 Lesson | 取代历史 `id` |
| `slide.type` | 幻灯片级 | 仅 Slide | 闭枚举 5 类 |

### 2.4 local-demo 兼容模式（**不得伪造知识库来源**）

| 规则 | 说明 |
|---|---|
| L-1 | `source = "local-demo"` 时，`source_doc_id` / `source_doc_hash` / `source_file_sha256` **必须全部为 `null`** —— 由 schema 的 `if/then` **结构性强制**（非 UI 提示） |
| L-2 | 携带任意非 null 绑定值的 `local-demo` 课程 → **校验失败**，客户端 `coursesError` + 零课程 |
| L-3 | UI 必须显示来源徽标「**本地演示**」；不得宣称已接入正式教材或 AI 生成 |
| L-4 | 随包 `data/courses.json` 是 local-demo bundle；**迁移工具不得为它编造 doc_id** |

### 2.5 正式课程来源绑定（**必须有真实来源**）

| `source` | `source_doc_id` | `source_doc_hash` | `source_file_sha256` |
|---|---|---|---|
| `user-textbook` | **必填**（`^doc_[A-Za-z0-9]{4,64}$`，须真实存在） | **必填**（`sha256:<64hex>`） | 可得则必填；不可得 → `null` + UI「原文件哈希待确认」 |
| `admin-knowledge` | **必填** | **必填** | 同上 |
| `local-demo` | `null`（强制） | `null`（强制） | `null`（强制） |

> **"真实"的定义**：发布时服务端须回读知识库校验 `doc_id` 存在且 `content_hash == source_doc_hash`
> （见 `AGENT_PLAN §8.3`）；**悬空 / 漂移 → 拒绝新发布**（已发布课程不级联删除）。

### 2.6 单一事实源与镜像

| 角色 | 落点 | 约束 |
|---|---|---|
| **机器可读权威** | `modules/curriculum/course_schema.v1.json`（JSON Schema draft-07） | 常量从本文件**派生**，杜绝"常量与 schema 各写一份" |
| **服务端校验器** | `modules/curriculum/course_schema.py` | 零新增依赖（**不** import `jsonschema`）；手写补足 draft-07 表达不了的约束 |
| **客户端冻结镜像** | `client/src/classroom/course_schema.v1.json` + `course_schema.py` | JSON **逐字节一致**（S01 断言 sha256 相等）；`.py` **仅模块 docstring 不同，代码体逐语句一致（AST 相等）**，行为一致性由 S03 语料判定断言 —— **不作「.py 逐字节一致」的不实声明**（CONTRACT_FIX_01A 一.3 订正）；客户端为独立包，运行期**不得** import `modules.*` |
| **禁止形态** | — | **禁止"两侧 import 同一份"**（客户端无仓库路径） |

**draft-07 表达不了、由手写补足的约束**：
1. `practice.answer < len(options)`（下标越界）；
2. `answer: null` = 「答案待人工确认」的语义（与越界区分）；
3. 跨层级唯一性（course 内不得出现 `version`；文档级不得出现 `source`）；
4. 历史字段互斥（`id` 与 `course_id` 不可共存）。

### 2.7 服务端/客户端**同版本一致性测试**（交付物）

`gateway/tests/course_schema_consistency_tests.py` —— **16/16 PASS**：

| 组 | 断言 |
|---|---|
| S01 | 两份 `course_schema.v1.json` **逐字节一致**（sha256 相等） |
| S02 | 规范常量一致（`SCHEMA_ID`/`SCHEMA_VERSION`/文档类型/`SOURCE_ENUM`/`SLIDE_TYPES`/三个正则/历史禁用键） |
| S03 | 共享语料（4 合法 + 10 非法）上**判定完全一致**且符合预期 |
| S04 | 五类滥用**确实被拒**并给出可解释原因（未知 type / 伪造来源 / 跨层 version / 答案越界 / 教材缺绑定） |
| S05 | **自证伪**：一侧枚举漂移 → 一致性断言必然失败 |

**真实自证伪（已执行）**：把客户端镜像的 `source` 枚举改成 `user-textbook-V2` → **S01b/S02a/S03a/S05a 四处 FAIL**；恢复后哈希回到 `0b3f323a…`，16/16 复绿。

**客户端侧行为测试**：`client/src/classroom/tests/test_course_contract_v1.py` —— **16/16 PASS**
（合法/违规 fail-closed / **C5 缺陷修复** / 修正③ 哈希口径）。

### 2.8 迁移（历史数据 → v1）

`tools/migrate_course_bundle_v1.py`（**确定性 + 幂等**）：

```bash
# 校验是否已是 v1
python tools/migrate_course_bundle_v1.py --in <file.json> --check
# 迁移（就地）
python tools/migrate_course_bundle_v1.py --in <file.json> --in-place
```

已对 `client/src/classroom/data/courses.json` 执行：**25 处改动**，迁移后 `--check` = `OK-V1`，复跑 = **幂等无改动**。
（涉及缺陷：`id=course_hotel → course_id=crs_hotel`；文档级 `source` 下沉并删除；补 `revision` 与三个绑定字段；`lessons[].id → lesson_id`。）

---

## 3. 修正③ · 哈希语义（`file_sha256` ⊥ `content_hash`）

### 3.1 实测现状（口径必须建立在事实之上）

| 事实 | 证据 |
|---|---|
| 当前导入管线**只计算抽取文本哈希**，**不计算原文件字节哈希** | `modules/knowledge/imports.py:96-97` `_hash(text) = sha256(_norm_text(text))`；`api_import.py` 取到 `file_bytes` 后**未**做哈希 |
| `KnowledgeStore` 文档记录 `content_hash` 指向**抽取文本** | `modules/knowledge/store.py:613` `h = _content_hash(body)`（`body` = 抽取后的文本） |
| 因此**不存在**可用的 `file_sha256` | — |

### 3.2 两个哈希的定义与边界（不可互换）

| 名称 | 定义 | 输入 | 用途 | 落点 |
|---|---|---|---|---|
| **`source_file_sha256`**（原文件 SHA-256） | 用户**上传原文件字节**的 SHA-256 | PDF/DOCX/EPUB **文件字节** | 溯源「这份课程来自哪一个上传文件」 | 课程契约字段（`sha256:<64hex>` 或 `null`） |
| **`source_doc_hash`**（知识库 `content_hash`） | 知识库对**抽取文本**归一化后的 SHA-256 | **抽取文本** | 知识库去重基线 / 发布来源一致性校验 | 课程契约字段（`sha256:<64hex>`） |

**关键结论**：
1. 二者输入不同（字节 vs 文本）、**不可互相推导**；
2. 同一份 PDF 的 `file_sha256`（字节）与 `content_hash`（文本）**必然不同**；
3. **严禁**把 `content_hash` 填进 `source_file_sha256` 冒充原文件哈希；
4. **严禁**把 `file_sha256` 当作知识库去重依据（会破坏既有去重基线）。

### 3.3 展示口径（诚实降级）

| 情形 | 界面必须显示 |
|---|---|
| `source_file_sha256` 是合法 `sha256:<64hex>` | 直接显示该哈希（可复制） |
| `null` / 缺失 / 格式非法 | **「原文件哈希待确认」** |
| `source_doc_hash` 合法 | 单独一栏显示为「**知识库内容哈希**」，**与上者分栏、分别标注**，绝不合并且不互相顶替 |

**唯一实现入口**：`course_schema.file_hash_display(value)` —— 非合法 `sha256:64hex` 一律返回「原文件哈希待确认」。
测试 K13/K14 覆盖「无值」与「非法/伪造值」两条路径；K15 断言 `source_doc_hash` **没有**被映射到该显示位。

---

## 4. 修正④ · 打包最小化

> 完整清单见 `deploy/STUDENT_APP_PACKAGING_MINIMAL.md`（含允许清单、拒绝清单、构建期扫描规则）。
> **要点**：学生 `.app` **不打包**无关 `admin-v4` 管理页面、管理端点、凭据与生产配置；网关侧**仅保留必要学生课堂能力**；清单变更须交**独立安全 Agent 核验**。

---

## 5. 并行施工分组（修正完成后的授权范围）

| Agent | 范围 | 明确禁止 |
|---|---|---|
| **B** | 统一 AppShell、书库、导入、解析进度、校对、发布页的**安全 UI 骨架**、响应式、深浅色、键盘操作、状态组件 | **发布操作只用隔离 Mock**；**不得**开放真实服务端发布路由 |
| **I** | 复用既有 knowledge 导入 API；结构锚点、校对数据契约、网络适配 | **不重建解析器**；**不重复实现导入流水线**；**不与 B 并发改 QML** |
| **C** | 复用语音层；麦克风权限、文字/语音事件状态机、字幕、错误提示、Mock 双向对话与打断测试 | **禁止真实收费模型请求** |
| **D** | **仅新建** `AvatarAdapter` 与静态降级 | **不得改受保护数字人文件**；**不得用假口型冒充音频驱动** |
| **E** | 课程 Schema、教材语义切分、音标、教学流程、练习判定；未知 `slide.type` 与非法答案的安全降级 | 不越界改他人文件 |
| **F** | 本地结构化学习记录、错题、复习、跨重启恢复、GUI 删除、损坏恢复 | **禁止冒充多学生身份隔离** |
| **G** | 最小权限安全设计、真实接口存在性核对、会话授权、链路 B 白名单独立复核准备 | **独立安全复核通过前不得开放实际发布路由**；**不得向学生端传递管理员 Bearer** |
| **H** | Finder 双击 `.app` 最小打包链、版本校验、子进程生命周期测试 | 需要安全 IPC 的集成阶段**必须等独立安全复核后放行** |
| **Independent QA** | EPUB 41 项 + 相关回归；接口/Schema/GUI/无假数据状态/Mac 打包/冻结保护 | 不得由施工方自证 |

---

## 6. 状态块

```
PHASE                      = PHASE 2 LIMITED START
GATE                       = MAIN_UI_CONSTRUCTION_GATE = APPROVED_FOR_NON_SENSITIVE_P2
CONTRACT_FIX_01            = COMPLETED（① 所有权 ② Schema ③ 哈希 ④ 打包）
SCOPE_ALLOWED              = 非敏感 UI / 解析适配 / 课程草稿 / 文字+Mock 语音 / 记忆 / 数字人适配 / 测试
SCOPE_FORBIDDEN            = 链路 B 最终发布服务端路由（独立安全复核前不得实现/开放/启用）
COURSE_SCHEMA_AUTHORITY    = modules/curriculum/course_schema.v1.json（draft-07）
COURSE_SCHEMA_VERSION      = 1（const）
CLIENT_MIRROR              = client/src/classroom/course_schema.v1.json（逐字节一致）
SCHEMA_CONSISTENCY_TESTS   = gateway/tests/course_schema_consistency_tests.py → 16/16 PASS
CLIENT_CONTRACT_TESTS      = client/src/classroom/tests/test_course_contract_v1.py → 16/16 PASS
SCHEMA_SELF_FALSIFICATION  = PASSED（篡改客户端镜像 → 4 断言 FAIL；恢复 → 16/16）
DEMO_BUNDLE_MIGRATION      = client/src/classroom/data/courses.json（v1；25 处改动；幂等）
HASH_SEMANTICS             = source_file_sha256 ⊥ source_doc_hash（file_hash_display 为唯一口径）
CLIENT_REGRESSION          = test_classroom_v1 46/46 · test_classroom_release_fix01 40/40
TINA_FROZEN                = UNCHANGED
PROTECTED_AVATAR_FILES     = UNCHANGED
NAS_CHANGED                = NO
REAL_MODEL_REQUESTS        = ZERO
NEXT                       = 按 §5 分组并行施工（四项修正完成后）
```

*本文件为契约冻结交付物；不代表功能已实现，也不构成生产上线/发布 API 授权。*
