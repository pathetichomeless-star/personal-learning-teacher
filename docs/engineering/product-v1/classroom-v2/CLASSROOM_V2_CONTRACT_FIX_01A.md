# CLASSROOM V2 — PHASE 2 CONTRACT FIX 01A 差异记录

- 版本：**01A（增量补正 · 非重做设计）**
- 生成：总控工程 Agent（TC）
- 时间：`2026-10-12T22:26:45+0800`
- 施工基线：`HEAD = 3754e502701713ee420e19b5badee5c421a77f88`（分支 `p2b2-teacher-voice`）
- 上游指令：产品负责人裁定「**CONTRACT_FIX_01 有条件接受**」；**不得重做整套 Phase 1 设计**；仅做增量补正后立即启动获批的**非敏感 Phase 2** 多 Agent 施工。
- 本文件性质：**差异记录**（记录 01A 相对 01 的新增/订正项与实测证据），**不是新设计报告**。

> **交付原则声明**：本轮所有"完成"均以**可运行源码 + 实测测试**为准；设计/契约文本只用于**消除矛盾**与**记录边界**，
> 不以更多报告代替功能。凡未真正落地者，一律标注 `PENDING / NOT_COMPLETED`，不作不实声明。

---

## 0. 结论摘要（逐条对照产品负责人指令）

| 指令 | 内容 | 状态 | 关键证据 |
|---|---|---|---|
| 一.1 | 修 `AGENT_PLAN §7` 旧所有权 + D1 待决 → 以 §2 矩阵为准 | ✅ 完成 | `AGENT_PLAN §7`（313–323 行）：I 范围改为「教材结构化数据接口 + 校对数据契约 + KB API 适配，UI 由 B 落 QML」；`D1 = MAC_LOOPBACK_ISOLATED` 已裁定，原"待决项 D1"声明**作废** |
| 一.2 | 明确无效 `slide.type` 的 fail-closed 校验 ⊥ 可见错误 UI | ✅ 完成 | 新增 `AGENT_PLAN §3.6.1`（三层机制表）；`CourseArea.qml` 加 `slideTypeUnknown` 防御兜底块 |
| 一.3 | JSON 逐字节一致；Python 校验器按**行为**一致性测试，不作不实声明 | ✅ 完成 | 实测 JSON sha256 两侧相等；`.py` 改为 **AST body 一致**口径；`CONTRACT_FIX_01 §2.6` + `AGENT_PLAN §3.6 C1` 已订正 |
| 一.4 | 用**真实隔离** KB 返回核验 `content_hash`/`doc_id`/Schema 正则，不改生产存储 | ✅ 完成 | `knowledge_hash_format_tests.py` **17/17**；`production_storage_touched=False`；真实样本 `doc_9b2274c42441` + 裸 64hex |
| 一.5 | local-demo 可读、不可冒充正式来源的正负向测试 | ✅ 完成 | 客户端 `K16`（正向）/`K17`（负向伪造被拒）/`K18`（真实裸 hex 接受）/`K19`（展示规范化） |
| 二.1 | 消除 L-SESSION→L-ADMIN Bearer 代理与最小化打包的冲突 | ✅ 文档层完成 | `D1_MINIMAL_PRIVILEGE_IMPORT_ACCESS.md §3.2.1`；`ADMIN_PROXY_MODEL = ELIMINATED` |
| 二.2 | 核对学生模式真实路由表 / 模块依赖图 / 来源鉴权 / 资源归属 | ✅ 文档层完成 | 同文件 `§3.8.1–3.8.4`；白名单 `/cls/*` 7 条，`/admin/` 前缀 = 0 |
| 二.3 | `getpeereid` 不能单独证明对端 PID；P2 UDS 未验证则禁用 | ✅ 文档层完成 | 同文件 `§3.3`；`P2_UDS_FALLBACK = PROHIBITED_UNLESS_VERIFIED` |
| 三 | 同步 REV1B HTML 版本标识 / EPUB 状态 / 双哈希分栏 / Schema 名称 | ✅ 完成 | `canvas/classroom_v2_design_canvas.html`（REV1B，标签配平 502/502·171/171·3/3） |
| 四 | 并发控制：先记录工作区/受保护文件/冻结基线，再锁所有权 | ✅ 完成 | 见 §4；**未执行** reset/clean/stash |
| 五 | 立即启动非敏感 Phase 2 多 Agent 施工 | 🟡 部分完成 | 见 §5；B 的完整 QML UI / H 打包 / 独立 QA / 独立安全复核 **PENDING** |

**全局边界合规**：`FROZEN_SIX_UNCHANGED = YES`、`PROTECTED_AVATAR_UNCHANGED = YES`、`NAS_CHANGED = NO`、`REAL_MODEL_REQUESTS = ZERO`、`GIT_ADD_OR_COMMIT = NONE`。

---

## 1. 一 · TC 契约修订（5 项）

### 1.1 修正① — `AGENT_PLAN §7` 旧所有权与 D1 待决

**问题**：§7 原文保留 Phase 0 的旧口径（Agent I「新增 UI 页面」；「本地环回网关 vs 公共平面窄口端点」列为**待决项 D1**）。

**订正**：
- **Agent I 范围**（`§7` 313–318 行）：交付物 = ①教材结构化数据接口 + 校对数据契约（结构锚点/语义切分/"需人工确认"标记/页码章节元数据）；②知识库 API 适配层（**复用**既有 `/admin/knowledge/import*`）；③**不写 QML**（遵守 §2.1 A-1「QML 单写者=B」）；④**不重写** `modules/knowledge/**` 解析与流水线。
- **D1 裁定**（`§7` 320–323 行）：`D1 = MAC_LOOPBACK_ISOLATED`（本机环回网关、绑 `127.0.0.1`、最小权限会话鉴权、**学生端不持有管理员 Bearer**）。原「待决项 D1」表述**明文作废**。

> 与 `CLASSROOM_V2_UI_DESIGN.md §8` 第 5 项一致（该处已记录同一裁定）。

### 1.2 修正② — 无效 `slide.type`：fail-closed 校验 ⊥ 可见错误 UI

**问题**：C4 原文「不得静默跳过 → 渲染占位」，与"整包 fail-closed"存在歧义（占位是逐页行为，fail-closed 是整包行为）。

**订正**：新增 `AGENT_PLAN §3.6.1`，明确**三层非同一机制**：

| 层 | 机制 | 位置 | 结果 |
|---|---|---|---|
| ① 校验层（权威 · fail-closed） | `validate_bundle()` 遇未知 `type` → **整包判违规** | `modules/curriculum/course_schema.py` | 未知类型**永远到不了渲染层** |
| ② 可见错误 UI | `_load_courses()` 失败 → `_courses=[]` + `_load_error` → 空状态显「课程数据不可用」+ **具体原因** | `classroom_model.py` / `CourseArea.qml` | 用户看到**可解释原因**，非空白页 |
| ③ 渲染层占位（防御性兜底） | 若被绕过校验仍拿到未知类型 → 渲染「未知内容类型（type=…）」 | `CourseArea.qml`（`slideTypeUnknown`） | **绝不静默空白** |

**结论**：v1 中未知 `slide.type` 的**权威行为 = ①+②整包拒绝**；③ 在 v1 中**结构上不可达**（防御性保留，覆盖"校验被绕过/未来前向兼容"）。**不允许**用 ③ 替代 ①（不得"放宽校验、改由渲染层兜底"）。

**落地**：`client/src/classroom/qml/CourseArea.qml` 新增 `knownSlideTypes` + `slideTypeUnknown` 属性与兜底块（主检出 sha256 `317e37ff…`）。

### 1.3 修正③ — 一致性声明订正（消除不实声明）

**问题**：01 原文声称客户端镜像 `.py` 与权威 **逐字节一致**——**不实**。

**订正（实测口径，勿夸大）**：

| 产物 | 一致性口径 | 判据 |
|---|---|---|
| `course_schema.v1.json`（权威 vs 镜像） | **逐字节一致** | 两侧 sha256 相等 = `f5bc1cb28853816726c90b6c9b61ad4731b6183a8e69156ab8d6dc57b9eb7bba` |
| `course_schema.py`（权威 vs 镜像） | **仅模块 docstring 不同；代码体逐语句一致（AST body 相等）** | 测试以 AST 断言把关；**不声称 `.py` 逐字节一致** |

**已同步文本**：`CLASSROOM_V2_PHASE2_CONTRACT_FIX_01.md §2.6`、`AGENT_PLAN §3.6 C1`、`course_schema.py` 模块 docstring。

**本轮追加订正**：`AGENT_PLAN §3.6 C1` 原仍写「逐字节一致」，已于 01A 修正为上述双口径。

### 1.4 修正④（一.4）— 真实知识库格式核验 + Schema 正则放宽

**方法**：用**真实 `KnowledgeStore`** 在 `tempfile.mkdtemp()` 隔离目录采样，**绝不触碰生产存储**。

**实测事实**：

| 项 | 真实值 | 原 Schema 要求 | 结论 |
|---|---|---|---|
| `doc_id` | `doc_9b2274c42441` | `^doc_[A-Za-z0-9]{4,64}$` | ✅ 匹配（`store.py:623` `"doc_"+uuid4().hex[:12]`） |
| `content_hash` | `7a2229a8…874a`（**裸 64 hex，无 `sha256:` 前缀**） | `^sha256:[0-9a-f]{64}$` | ❌ **旧严格正则判定不匹配 → 真实返回值会被误拒**（冲突证据已固定） |
| `file_sha256`（探针字节） | `d2373c44…f253` | — | 与 `content_hash` **不同** → 证实"字节哈希 ⊥ 文本哈希" |

**修复**（`modules/curriculum/course_schema.{py,v1.json}` + 客户端镜像）：
- `SHA256_RE = ^(?:sha256:)?[0-9a-f]{64}$`（**放宽**：接受裸 hex 与前缀两种形式）；
- 新增 `SHA256_CANON_RE = ^sha256:[0-9a-f]{64}$`（规范形式）；
- 新增 `canonical_sha256()` / `sha256_matches()`（统一比较口径）/ `file_hash_display()`（展示统一为 `sha256:<hex>`）；
- **fail-closed 未被削弱**：伪造/非法哈希、非 `doc_` 前缀 `doc_id` 仍被拒（`H06a/H06b` 通过）。

**测试**：`gateway/tests/knowledge_hash_format_tests.py` **17/17**；证据 `evidence/knowledge_hash_format_tests.json`（`production_storage_touched = False`、`isolated_store_path` 指向系统临时目录）。

> **连带文档订正**：`AGENT_PLAN §3.6 来源绑定表` 与 `§3.7.1 哈希语义表` 原写死 `sha256:<64hex>`，已改为「接受 `^(?:sha256:)?[0-9a-f]{64}$`；实测 KB 输出裸 64hex；展示规范化 `sha256:<hex>`」。

### 1.5 修正⑤（一.5）— local-demo 可读、不可冒充正式来源

**测试**（`client/src/classroom/tests/test_course_contract_v1.py`，20/20）：

| 用例 | 方向 | 断言 |
|---|---|---|
| `K16` | **正向** | local-demo bundle **可正常阅读**，且全部课程 `source == "local-demo"`（不冒充正式用户教材） |
| `K17` | **负向** | 声称 `user-textbook` 但**缺真实 `doc_id`** → **拒绝**（不得伪造正式来源） |
| `K18` | 正向 | **真实裸 hex `content_hash`** 绑定 → 客户端**接受**（01A 放宽哈希形式生效） |
| `K19` | 正向 | `file_hash_display(裸 64hex)` → 规范化为 `sha256:<hex>` |

**配套**：`gateway/tests/curriculum_builder_tests.py` **19/19**（`E01–E13`：local-demo 三绑定强制 `null`、正式绑定、fail-closed、unknown kind、`answer=null`+`needs_review`、音标、**无 20 天痕迹**、`course_id` 正则、空 units、自动 cover/summary、层级不变式）；迁移工具 `tools/migrate_course_bundle_v1.py`（确定性+幂等，已对随包数据执行，`--check = OK-V1`）。

---

## 2. 二 · Agent G + 独立安全 Agent（文档层完成，**独立复核未执行**）

`docs/engineering/product-v1/classroom-v2/security/D1_MINIMAL_PRIVILEGE_IMPORT_ACCESS.md`（358 → 约 430 行）

### 2.1 消除 L-SESSION → L-ADMIN Bearer 代理模型（新增 `§3.2.1`）

| 维度 | 旧（**已废除**） | **新（01A）** |
|---|---|---|
| 形态 | 网关把 L-SESSION 映射为对 L-ADMIN 的**受限代理** | **独立受限的最小权限业务实现** |
| 凭据 | 学生进程间接使用**全权管理员 Bearer** | 学生进程**从不携带/加载**管理员凭据 |
| 加载面 | 加载 admin app / `auth.py`(TokenStore) / Bearer 文件 | **不加载** admin app、`auth.py`、`api_model`、`views`；**不读** admin token 密封文件 |
| 取数 | HTTP 代理 + Bearer | 进程内**直接共享 store 对象**，无 HTTP 代理、无 Bearer |
| 路径前缀 | `/admin/*` | `/cls/*`（7 条白名单） |

**与最小化打包（修正④）一致性**：学生 `.app` 本就不打包 admin 面与凭据 → 独立子应用模型与之一致，**结构性不可能**让学生端拿到全权凭据。
**状态位**：`ADMIN_PROXY_MODEL = ELIMINATED`、`ADMIN_APP_MOUNTED = NO`、`ADMIN_TOKEN_FILE_READ = NO`。

### 2.2 学生模式入口核验（新增 `§3.8.1–3.8.4`）

- `§3.8.1` **真实路由表**：对照现有 admin 面 10 条导入路由 → 学生白名单 **7 条 `/cls/knowledge/*`**，`/admin/` 前缀路由数 = **0**。
- `§3.8.2` **模块依赖图**：列出学生子应用的 import 面；明确 Bearer/TokenStore 仅在 `auth.py`，学生侧**不 import**。
- `§3.8.3` **来源鉴权**；`§3.8.4` **资源归属表**（store 归属、路径归属、写入方）。

### 2.3 `getpeereid` 事实更正（`§3.3`）

| 事实 | 说明 |
|---|---|
| `getpeereid(fd)` | 仅返回 `(uid, gid)` —— **不能证明对端 PID** |
| macOS 对端 PID | 需 `getsockopt(SOL_LOCAL, LOCAL_PEERPID)`（**另一 API**） |
| `SO_PEERCRED` | **Linux 专有**，macOS 不可用 |

**结论**：P2 UDS 兜底默认 **`PROHIBITED_UNLESS_VERIFIED`**；须实测 `LOCAL_PEERPID` 可用 + 预授权 + 独立复核，方允许启用。
**新增测试项**：`G-T22`（加载面不含 admin auth / 不读 token 文件）、`G-T23`（路由表仅 `/cls/*`）、`G-T24`（仅过 `getpeereid` 不放行）、`G-T25`（P2 未验证即启用 = 构建阻断）。

**⚠️ 门禁（未关闭）**：`独立安全审核 = NOT_COMPLETED`。**在独立安全审核通过前，不开放学生端白名单服务与最终发布 API。**

---

## 3. 三 · Agent A / B — REV1B 画布文案与契约映射同步

文件：`docs/engineering/product-v1/classroom-v2/design/canvas/classroom_v2_design_canvas.html`（891 行）

| 项 | 同步结果 |
|---|---|
| 版本标识 | 标题 → **REV1B** |
| EPUB 状态 | 硬规则 ②：EPUB **已实现（D2，文字型）**；**41 项开发自验，独立 QA 待完成**；OCR 仍标「暂不支持」 |
| 双哈希分栏 | 画板 E 溯源块拆为「**原文件 SHA-256（`source_file_sha256`）**」与「**知识库内容哈希（`content_hash`）**」两行 + **不可互换声明**；发布页来源字段补充裸 hex 与两哈希 |
| 正式 Schema 名称 | 画板 A2 产物行标注裸 hex 说明 + 正式 Schema 名 `classroom.course.bundle` |

标签配平核验：`div 502/502`、`span 171/171`、`p 3/3`（平衡）。**仅改文案与契约映射，未做新一轮视觉重设计。**

---

## 4. 四 · 并发控制（基线记录 + 所有权锁定）

**基线（本轮开工时记录）**：`HEAD = 3754e50…`、分支 `p2b2-teacher-voice`、工作区 **33 项变更（其中 32 项未跟踪）**。

**冻结六文件 SHA256（应恒不变；本轮 `git diff` = 空）**：

| 文件 | SHA256 |
|---|---|
| `gateway/app/turns.py` | `e18a0d08ed3a28771dee71d39dd5563f52f3d1199043ac81b8d9a7b5a2a498bd` |
| `gateway/app/qwen.py` | `13d4800d416f678c33126e74bd857baab33afb5c9c3bfe2c80f6c0db798c9c32` |
| `gateway/app/audio.py` | `c2218a2c3fda520089473e312ce6ee3fac4436c540755a8c98fd634ff7a87c09` |
| `gateway/app/protocol.py` | `944e2d5ab4f0c2b13a51b547d366175cc18263575034566fda928b2a7b30d9f8` |
| `gateway/app/ws.py` | `dde9d427883721c17628f40c73bf417bc9c0ab32711d07a4f22e9ed7ad63dd1c` |
| `gateway/app/behavior.py` | `6d705960cb0154f17fa9eb0ce9ef1d651d0b4a64c9d4564fde5957d08d6a0088` |

**受保护数字人文件 SHA256（本轮未触碰，与基线逐字节一致）**：

| 文件 | SHA256 |
|---|---|
| `client/src/ui/gui/manager.py` | `bd2de04b77ea9461ab2ca855b5543237a7c2c18bf6b312855a93f8a353d769c1` |
| `client/src/ui/gui/qml/components/AvatarLive2D.qml` | `32c1c16a8b1c5c906af91bd9ecc166632a4fcfabc079061ce7a90c8b7fcbd358` |
| `client/src/avatar/runtime/avatar_page.js` | `1243b98d346d8bfa39575ff7824e6f8b45805dd1d8d9110b3b60c5dcc12e38e5` |
| `client/probe_avatar_qml_offscreen.py` | `f3cb7ea33770e15eb964204925c71b12f943baac1767d137f7e555ffd4308ceb` |
| `client/src/avatar/runtime_server.py` | `a64046aea038d247b0fad63d76c7d756f882379ea3e8a2510dca2274586d88b` |

**所有权锁定**：以 `AGENT_PLAN §2`（宪法级矩阵）为准；各 Agent 仅在其授权目录写入，跨目录改动先报 TC。
**禁止项遵守**：本轮**未**执行 `reset` / `clean` / `stash`；**未**做全量覆盖或无选择性暂存；**未** `git add` / `commit`。

---

## 5. 五 · Phase 2 非敏感施工 — 各 Agent 实际源码交付

> 行数为实测（`wc -l`）；测试数为实测运行结果（非声明）。

| Agent | 交付物（源码） | 行数 | 测试（实测） | 状态 |
|---|---|---|---|---|
| **I** 教材结构化 / KB 适配 | `client/src/classroom/classroom_api.py`（stdlib `urllib`；`_headers()` **仅** `X-Classroom-Session`，**无 `Authorization` 分支**；`_OPENER = build_opener(ProxyHandler({}))` **绕过系统代理**；`health/parsers/list_imports/get_import/commit_import/cancel_import/retry_import`） | 134 | `CLASSROOM_API` **9/9** | ✅ |
| **E** 课件 / 音标 / 教学引擎 | `modules/curriculum/phonetics.py`（`ACCENT_LABEL="en-GB (RP)"`，~40 词真实 IPA，**未知返回 `None` 不猜**，`enrich_vocab` 未知**省略字段**不写 null）；`modules/curriculum/builder.py`（`make_course_id`/`item_to_slide`/`build_lesson`/`build_course`/`build_bundle`/`build_local_demo`，`assert_valid` fail-closed） | 114 + 195 | `CURRICULUM_BUILDER` **19/19** | ✅（课程生成层；**完整教学流程/练习判定引擎 = PENDING**） |
| **F** 学习记录 / 跨启动恢复 | `client/src/classroom/learning_record.py`（`LearningRecordStore`；`SCOPE="local-single-user"`；原子写 + `0o600`；损坏隔离为 `*.corrupt-<ts>` 空启动；**无 user_id/account 字段**） | 162 | `LEARNING_RECORD` **13/13** | ✅ |
| **D** 数字人适配 / 安全降级 | `client/src/classroom/avatar_adapter.py`（`AvatarAdapter`；`STATES=(listening/thinking/speaking/waiting/error)`；`set_audio_level()` 接受真实电平或 `None`；**`mouth_open()` 在 degraded/非 speaking/无真实信号时恒返 `0.0`，绝不伪造口型**） | 121 | `AVATAR_ADAPTER` **14/14** | ✅（**适配器层**；接入受保护数字人 = 由另行授权） |
| **C** 文字/语音 Mock 对话 | `client/src/classroom/voice_mock.py`（`VoiceMockSession`；`MODES=(local-demo/local-mock/real-online)`；`ERROR_REASONS` 数值码 + `STRING_REASONS` 中文映射；事件 `user_speech/partial_transcript/final_transcript/teacher_speaking/barge_in/error`；**`real-online` 未授权直接拒绝、零真实请求**） | 163 | `VOICE_MOCK` **15/15** | ✅ |
| **TC** 契约与镜像 | `modules/curriculum/course_schema.{py,v1.json}`（权威）+ `client/src/classroom/course_schema.{py,v1.json}`（镜像） | 346 + 344 | `COURSE_SCHEMA_CONSISTENCY` **16/16**、`COURSE_CONTRACT_V1_CLIENT` **20/20** | ✅ |
| **D2** EPUB（纯增量格式） | `modules/knowledge/parsers.py`（文字型 EPUB，`EPUB_MAX_*` 限额、DTD/ENTITY fail-closed）；测试 `gateway/tests/knowledge_epub_tests.py` | — | `EPUB_PARSER_SECURITY` **41/41** | 🟡 **开发自验完成；独立 QA = PENDING** |
| **B** 真实 QML UI / 响应式 | `client/src/classroom/qml/CourseArea.qml` **仅**加了未知类型兜底块 | — | `UI_PROBE` **52/52**、`V1_TESTS` **46/46**、`FIX01` **40/40**、`BUNDLE_E2E` **12/12** | 🟡 **完整 QML UI 未施工（PENDING）** |
| **G** 安全 | `security/D1_MINIMAL_PRIVILEGE_IMPORT_ACCESS.md`（文档层） | — | — | 🟡 **独立安全复核 = PENDING** |
| **H** 打包 / 隔离测试 | — | — | — | ❌ **未开始** |
| **QA** 独立复核 | — | — | — | ❌ **未执行** |

**全量回归（实测，2026-10-12）**：

- 服务端 4 套：`16 + 17 + 19 + 41 = 93`，**93/93 通过，失败 0**。
- 客户端 9 套：`20 + 46 + 40 + 52 + 12 + 13 + 14 + 15 + 9 = 221`，**221/221 通过，失败 0**。
- **合计 `314/314` 全绿，失败 0。**

> **跨文件计数对齐（非缺陷）**：EPUB 加入后解析器数 5→6，`knowledge_epub_tests` 内置**跨文件计数核查**，确认 3 处引用已同步 —— `admin_v4_api_tests.py`（`len(parsers) == 6`）、`import_v4_tests.py`（`len(kinds) == 6`）、`deploy/v4-acceptance/verify_v4_e2e.py`（仅遍历五扩展、无计数断言、仍通过）。

---

## 6. 未关闭门禁（PENDING）

| 门禁 | 内容 | 阻塞项 |
|---|---|---|
| **D2 独立 QA** | EPUB 解析的独立复核 | 41 项仅**开发自验**；`INDEPENDENT_QA = PENDING` |
| **D1 独立安全复核** | `§3.2.1` 独立最小权限子应用依赖图最小性 + `/cls/*` 白名单 + `G-T22–G-T25` | `INDEPENDENT_SECURITY_REVIEW = NOT_COMPLETED` |
| **打包独立安全核验** | `C-1…C-5`（`STUDENT_APP_PACKAGING_MINIMAL.md`） | Agent H 未开始 |
| **完整 QML UI / 响应式** | 书库/导入进度/校对/发布页骨架、三栏可调、多档响应式 | Agent B 未施工 |
| **教学引擎** | 讲解/练习/测验/小结**完整流程**与掌握度判定闭环 | 仅 `builder.py` 课程生成层 |
| **独立 QA（总）** | Schema / EPUB / GUI / 声音 Mock / 冻结保护 | 未执行 |

**硬门禁（产品负责人明令）**：
> **独立安全审核未通过前，不开放学生端白名单服务与最终发布 API。**
> 本轮**未实现**任何学生端白名单服务，**未实现**最终发布 API（链路 B 发布路由**本轮仅定契约**）。

---

## 7. 可运行 Mac 界面状态（如实报告）

| 项 | 状态 |
|---|---|
| 已打包 `.app` | `client/dist/小智 AI 学生课堂.app`（真机**免终端双击**、隔离 fail-closed、`env -i` 独立启动均已在 `FIX02` 轮实测通过） |
| **⚠️ 打包件滞后** | `.app` 内 `CourseArea.qml` = `bd3eed7598…`（**pre-FIX02，`slideTypeUnknown` 出现 0 次**）；主检出 `CourseArea.qml` = `317e37ff8a…`（**含 Ph2 未知类型兜底**）→ **`.app` 尚未含本轮 Ph2 QML 改动**，需 Agent H 重新打包 |
| 可运行入口 | `client/classroom_main.py` + `打开学生课堂.command`（`.command` 入口属 **FIX01 P1 遗留**，已由 `.app` 替代） |
| 真实模型 | **ZERO**（本轮无任何真实付费请求） |
| 生产 NAS | **未修改**（`NAS_CHANGED = NO`） |
| Tina 冻结文件 | **未修改**（六文件 `git diff` 空 + 哈希一致） |

**结论**：存在可运行的 Mac 界面（`FIX02` 基线），但**完整 QML UI 与打包件均滞后于本轮 Ph2 源码**；如实标注 `RUNNABLE_UI = FIX02_BASELINE`、`PH2_UI_REBUILD = PENDING`。

---

## 8. 边界合规声明（本轮）

- ✅ **不恢复固定 20 天课程**；用户自己的教材为正式课程来源；`local-demo` 不伪造知识库来源。
- ✅ **未修改** Tina 冻结六文件、**未触碰**受保护数字人文件、**未修改**生产 NAS。
- ✅ **零真实付费模型请求**。
- ✅ **未实现**最终发布路由（链路 B 发布路由本轮仅定契约）。
- ✅ **未** `git add` / `commit`；**未** `reset` / `clean` / `stash`；**未**全量覆盖或无选择性暂存。
- ✅ 未在独立安全审核通过前开放学生端白名单服务。

---

## 附：本轮 docs / 测试 / 证据 清单

**文档**：`CLASSROOM_V2_CONTRACT_FIX_01A.md`（本文件）、`CLASSROOM_V2_AGENT_PLAN.md`（v1.1 + §3.6.1 + §7 订正 + §3.6/§3.7.1 哈希口径订正）、`CLASSROOM_V2_PHASE2_CONTRACT_FIX_01.md`（§2.6 订正）、`CLASSROOM_V2_UI_DESIGN.md`、`design/canvas/classroom_v2_design_canvas.html`（REV1B）、`security/D1_MINIMAL_PRIVILEGE_IMPORT_ACCESS.md`。

**测试**：`gateway/tests/{course_schema_consistency_tests,knowledge_hash_format_tests,curriculum_builder_tests,knowledge_epub_tests}.py`；`client/src/classroom/tests/{test_course_contract_v1,test_learning_record,test_avatar_adapter,test_voice_mock,test_classroom_api}.py`。

**证据 JSON**：`docs/engineering/product-v1/classroom-v2/evidence/{course_schema_consistency_tests,knowledge_hash_format_tests,curriculum_builder_tests,epub_parser_security_tests,course_contract_v1_client_tests,learning_record_tests,avatar_adapter_tests,voice_mock_tests,classroom_api_tests}.json`。
