# CLASSROOM V2 — 教材解析逐格式能力与依赖状态报告

> 阶段：P0（非付费）· 与 Phase 1 设计审定**并行且互不冲突**的后端验证
> 约束遵守：`NAS_CHANGED = NO` · `REAL_MODEL_REQUESTS = ZERO` · 只读、离线、不联网
> 基线：`3754e502701713ee420e19b5badee5c421a77f88`

---

## ⚠️ 版本与生效状态（**先读本节** · REV1B 修订）

本报告为**滚动修订文档**：§1–§10 记录**首轮**（REV1 阶段）的实测结论，§11 记录 **D2 EPUB 实施**。
为避免误读，**生效状态以本节为准**：

| 章节 / 表述 | 记录时的状态 | **当前生效状态** |
|---|---|---|
| §2 矩阵「EPUB = `UNSUPPORTED`」·「**仅五格式**」 | 首轮实测（**D2 实施前**） | ⛔ **已过期**。EPUB 文字型**已实现**（§11），`is_p0(.epub) = true`，探针实测 `PARSED` |
| §4.3「EPUB / PNG 均返回 `unsupported_content_type`」 | 首轮实测（D2 实施前） | ⛔ **仅 PNG 仍成立**；EPUB 已可解析 |
| §9「`parsers.py` **本轮未做任何修改**」 | 首轮（只读验证轮） | ⛔ **已过期**。D2 实施**已修改** `parsers.py`（+EPUB 支持） |
| §8「D2 EPUB 范围 = 待决策」 | 首轮 | ✅ **已裁定**：`D2 = EPUB_TEXT_ONLY_IN_P0`，**已实施**（§11） |
| §10 状态块 `SOURCE_MODIFIED = NO` | 首轮 | ⛔ **已过期** → 现为 **YES**（`parsers.py` + 测试 + 1 行文案） |
| **D3 OCR** | 首轮 `PENDING` | ✅ **已裁定**：`D3 = OCR_DEFERRED_TO_P1`（**仍未实现**，语义不变） |
| §11.4「**41/41** · **187/187**」 | 施工方**开发自验** | ⚠️ **降级为"开发自验"**：**独立 QA 复核待完成**（见 §12）；**不得**当作全仓回归通过 |

> **保留审计历史的原则**：被取代的段落**不删除**（便于审计追溯），但**必须**带上述标记。
> 任何对外引用本报告时，**应以本节 + §12 的生效状态为准**。

---

## 0. 结论摘要（首轮 + D2 增量）

| 项 | 结论 |
|---|---|
| P0 五格式（TXT/MD/PDF/DOCX/PPTX） | **全部 `PARSED` 成功**（`REAL_VERIFIED`） |
| 扫描件 PDF（无文本层） | **`scanned_pdf_no_text`**，诚实降级，观测达成 |
| 多栏排版 PDF | **缺陷已实证复现**：窄栏距下跨栏合并 → 文本粘连、**`error=None` 完全静默** |
| **EPUB（D2 实施后）** | **`PARSED`**（文字型，spine 定序，零新增依赖；**开发自验 41/41**，独立 QA 待完成，见 §11/§12） |
| 书页图片（OCR） | `unsupported_content_type`；**无任何 OCR 引擎**；**D3 已裁定推迟至 P1**（见 §5.2） |
| 解析执行位置 | **网关侧**（`gateway/app/admin/api_import.py`，10 条 HTTP 路由）——**已完整实现** |
| 客户端网络层 | **完全不存在**（V1 课堂是纯离线单机）→ V2 需新增 HTTP 客户端能力 |
| 依赖缺口定性 | 客户端缺 pdfminer/docx/pptx **不是缺陷**（客户端不解析）；网关镜像已钉版声明 |
| 交付结论 | `IMPLEMENTED`（D2 解析已交付）· 独立 QA **待完成**；D3 已裁定推迟 |

**一句话**：教材「解析」这件事**后端已经做完且做对了**——P0 五格式实测通过、扫描件诚实降级、D2 EPUB 文字型已实现。
真正的缺口是 ①多栏文档的**静默错序**（须在契约层显式暴露风险）；②**没有 UI、也没有客户端网络层**；
③扫描页 OCR 在架构上无处安放（**D3 已裁定推迟至 P1**）；④D2 的测试证据**尚待独立 QA 复核**（开发自验 ≠ 独立 QA）。

---

## 1. 验证方法与可复现命令

- **脚本**：`docs/engineering/product-v1/classroom-v2/evidence/parser_capability_probe.py`（v2）
- **产物**：`parser_capability_probe.json` / `parser_capability_probe.err`
- **被测对象**：`modules/knowledge/parsers.py`（首轮为**只读验证、未修改**；**D2 实施后已修改**，见 §11）
- **解释器**：`~/.workbuddy/binaries/python/envs/xiaozhi-p2b2/bin/python`（隔离 venv，含三件解析依赖）
- **样本生成**：TXT/MD 直写；DOCX/PPTX 由 `python-docx`/`python-pptx` 生成；PDF 由 macOS
  `cupsfilter` 真实渲染（**必须传文件路径**，stdin 方式会 rc=1 —— 这是首版探针 PDF 失败的根因）；
  双栏 PDF 为手工构造的最小合法 PDF（绝对定位，content stream 顺序故意打乱）
- **真实样本**：`prototypes/v4-release-progress/evidence/kb-fix-round/materials/fix-03-travel-story.pdf`（仓内既有）

```bash
cd docs/engineering/product-v1/classroom-v2/evidence
PYTHONPATH= ~/.workbuddy/binaries/python/envs/xiaozhi-p2b2/bin/python \
  parser_capability_probe.py > parser_capability_probe.json 2> parser_capability_probe.err
```

> 说明：探针运行在**隔离 venv**中，通过 `sys.path` 注入仓库根以导入真实 `modules.knowledge.parsers`。
> 未改动仓库任何源码、未触碰 NAS、未发起任何模型请求。

---

## 2. 逐格式能力矩阵（实测）

| 格式 | 用例 | 状态 | 字节 | 抽取字符 | `error` | 判定 |
|---|---|---|---|---|---|---|
| **TXT** | 合成（含 IPA + 中文） | `PARSED` | 74 | 64 | `null` | ✅ 可用 |
| **MD** | 合成（标题 + 列表 + 粗体） | `PARSED` | 54 | 44 | `null` | ✅ 可用（保留原始 Markdown 记号） |
| **PDF**(文本型) | cupsfilter 真实渲染 | `PARSED` | 11 836 | 183 | `null` | ✅ 可用 |
| **PDF**(真实样本) | 仓内 3 页既有 PDF | `PARSED` | 7 856 | 5 940 | `null` | ✅ 可用（真实世界样本通过） |
| **DOCX** | 合成（标题+段落+**表格**） | `PARSED` | 36 828 | 94 | `null` | ✅ 可用（表格线性化为 `a \| b`） |
| **PPTX** | 合成（标题+正文） | `PARSED` | 28 288 | 60 | `null` | ✅ 可用（带 `[slide n]` 分页标记） |
| PDF(扫描件) | 图片型 PDF | `REFUSED` | 6 525 | 0 | `scanned_pdf_no_text` | ✅ **诚实降级** |
| EPUB | 最小合法 EPUB | `UNSUPPORTED` | 485 | 0 | `unsupported_content_type` | ⛔ **历史（D2 前）** → 现为 `PARSED`（§11） |
| IMAGE(.png) | 合成书页图 | `UNSUPPORTED` | 2 060 | 0 | `unsupported_content_type` | ⚠️ 非 P0（**无 OCR**，D3 推迟至 P1） |

**P0 五格式 `p0_parsed_ok` = `[.txt, .md, .pdf, .docx, .pptx]`（5/5 通过）**
> ⛔ **上表为 D2 实施前（首轮）实测快照**。D2 实施后探针刷新为 **六格式全通过**（`.txt .md .pdf .docx .pptx .epub`，见 §11.4）。

### 2.1 可用的抽取质量（抽样）

- **DOCX 表格线性化**：`reservation | /ˌrezəˈveɪʃn/ 预订` —— 词条/音标/释义天然成对，**对「词汇表」类教材极友好**。
- **DOCX 换行**：段落与表格行以 `\n` 连接，结构信息**保留**。
- **PPTX 分页**：`[slide 1]\nHotel English · Check-in\nreservation /ˌrezəˈveɪʃn/` —— 天然带**幻灯片边界**，
  可直接映射到课程数据的 `slide` 语义切分（见 §7）。
- **PDF 渲染**：cupsfilter 输出的行内**保留了列间空格填充**（`Hotel English` 后有长串空格），
  属 pdfminer 的版面还原行为，**不影响内容，但会引入噪声空白**，切分前需归一化。
- **TXT/MD**：`\r\n`/`\r` 统一为 `\n` 并 `strip()`；MD **不剥离** `#`/`**` 记号（下游需自行处理）。

---

## 3. 依赖状态矩阵（实测 4 个解释器 + 网关镜像）

| 解释器 / 载体 | Python | pdfminer.six | python-docx | python-pptx | 用途 |
|---|---|---|---|---|---|
| `xiaozhi-p2b2`（隔离验收 venv） | 3.13.12 | ✅ OK | ✅ OK | ✅ OK | **本次验证载体** |
| `gateway/.venv-v4`（网关 V4 运行环境） | — | ✅ OK | ✅ OK | ✅ OK | **生产解析环境（就绪）** |
| `gateway/.venv`（网关旧环境） | — | ❌ MISSING | ❌ MISSING | ❌ MISSING | 若误用 → 诚实 `parser_unavailable` |
| `client/.venv`（Mac 客户端运行时） | 3.10.20 | ❌ MISSING | ❌ MISSING | ❌ MISSING | **不解析，符合分层设计** |
| `system`（`/usr/local/bin/python3`） | 3.13.13 | ❌ MISSING | ❌ MISSING | ❌ MISSING | 不可用于解析 |

### 3.1 声明点核对（关键澄清）

- **网关镜像已钉版声明**：`deploy/v4-candidate/Dockerfile` 第 54–56 行
  ```dockerfile
  "pdfminer.six==20260107" \
  "python-docx==1.2.0" \
  "python-pptx==1.0.2" \
  ```
  并在文件头记录「dependency precheck PASS 2026-10-10：20/20 packages resolve to manylinux aarch64 / universal wheels」。
  → **网关侧依赖已声明、已预检、已就绪**。
- **客户端未声明（`client/requirements.txt`）**：**不是缺陷，但必须在契约中显式固化**——
  客户端**不得**尝试本地解析（否则会在用户机器上静默失败或触发依赖膨胀）。
  → 结论：`client/requirements.txt` **无需**新增这三件；改为在接口契约中写明「解析仅由网关提供」。

> ⚠️ **风险点**：`gateway/.venv`（旧环境）缺三件。若有任何路径用旧环境启动网关，
> `/admin/knowledge/parsers` 会诚实地返回 `available:false + parser_unavailable`——
> **安全（fail-closed）但会静默降级为"没有解析能力"**。部署时必须确认用的是 V4 环境/镜像。

---

## 4. 边界行为实证

### 4.1 扫描件 / 无文本层 PDF → `scanned_pdf_no_text` ✅ 达成

- 构造：PNG 书页图 → `cupsfilter` → 无文本层 PDF（6 525 B）。
- 观测：`parse_file()` 返回 `(None, "scanned_pdf_no_text")`，`expectation_met = true`。
- 判定：**诚实降级成立**。P0 不做 OCR 是**明确设计**（`parsers.py:107` 注释："a text-less PDF is almost
  always a scan: no OCR in P0"），不是缺陷。前端必须把该码渲染为**可操作提示**（"这是扫描件，请上传可复制
  文字的版本，或等待 OCR 能力"），而非空白页。

### 4.2 多栏排版「静默错序」——**缺陷已复现**（`layout_order_defect_reproduced = true`）

**对照组**（同一构造器、同一视觉阅读顺序，仅改变栏距）：

| 用例 | 右栏起点 | 观测 | `error` | 判定 |
|---|---|---|---|---|
| `PDF(two-column-wide)` | x=330（栏距充足） | `LEFTCOL 1..3` → `RIGHTCOL 1..3`（正确分列） | `null` | ✅ 正确 |
| `PDF(two-column-narrow)` | x=280（栏距偏窄） | `LEFTCOL 1 reservation booking confirm detail`**`RIGHTCOL 1 deposit luggage passport`** | `null` | ❌ **错序且静默** |

**观测到的原始行（窄栏距）**：
```
LEFTCOL 1 reservation booking confirm detailRIGHTCOL 1 deposit luggage passport
```
→ 左右栏**跨栏粘连**，**两个字幕块之间没有任何分隔符**，且 `error = null`（调用方无从得知）。

**阈值刻画**（左栏起点 x=60，11 pt Helvetica，每行约 6.1 pt/字符）：

| 左栏行长 | 右栏 x | 是否跨栏合并 |
|---|---|---|
| 36 字符 | 250 | ✅ 合并 |
| 44 字符 | 280 | ✅ 合并（**粘连无空格**） |
| 49 字符 | 280 | ✅ 合并（粘连无空格） |
| 36 字符 | 320 | ❌ 不合并 |
| 44 字符 | 320 | ❌ 不合并 |
| 49 字符 | 320 | ✅ 合并 |

**结论**：pdfminer 的版面分析对「留白充足的干净分栏」**可靠**，但当左右栏间距小于其
`LAParams` 阈值时，会把两栏**当成同一逻辑行**并置，产出「粘连文本 + 零错误码」。

**影响面**（必须写进契约）：
- 真实的**双栏教科书 / 双栏讲义 / 双栏+旁注**排版均可能命中。
- 后果是**静默的语义污染**：切分器会把「右栏第一个词条」粘到「左栏最后一个词条」的尾部，
  生成错误的词汇表/例句——**比报错危险得多**，因为无任何信号。
- `parsers.py` **当前不返回任何版面告警**。

**候选缓解（Phase 2 由 EPIC-E 教材/教学承接，不属本轮改动）**：
1. `LAParams` 调参（`line_margin` / `char_margin` / `boxes_flow`）后**双跑比对**，差异超阈值即告警；
2. 引入轻量栏检测：按 x 直方图识别 gutter，再按栏序重排（**纯自研，零新增依赖**）；
3. **诚实兜底（最低成本、建议先行）**：契约层新增 `layout_suspect` 提示位
   → 导入预览页显示"检测到疑似多栏排版，请人工核对词条边界"，并**强制人工校对照常生效**。
4. 无论选哪条，**`anchor_hint` 与人工校对步骤是最终防线**（见 §7）。

### 4.3 未知扩展名 → `unsupported_content_type` ✅ 达成（**历史快照**）

> ⛔ **本小节为首轮（D2 实施前）观测**。当前：**EPUB 已可解析**（§11）；**PNG 仍返回 `unsupported_content_type`**。

EPUB / PNG 均返回 `unsupported_content_type`（**当时**），且 `is_p0() = false`。
→ 前端应据此渲染为**"暂不支持该格式"**（附支持格式清单），而非通用失败。
> 当前仅 **PNG / 图片型**适用；EPUB 已从"暂不支持"转为"支持（文字型）"——**前端能力表以 `GET /admin/knowledge/parsers` 真实返回为准**。

---

## 5. EPUB 与书页图片：实际能力与依赖状态（专章结论）

### 5.1 EPUB —— **D2 已实施并可解析**（`REAL_VERIFIED`）

> 产品负责人裁决：`D2 = EPUB_TEXT_ONLY_IN_P0`。已实施（见 §11）。
> **REV1B**：产品负责人**接受开发交付**，但明确 **独立 QA 待完成**——本节的 `REAL_VERIFIED` 指"施工方实测复现"，
> **不等于**独立 QA 通过（见 §12）。

| 项 | 结论 |
|---|---|
| **当前能力** | **`PARSED` 成功**；`.epub` 已在 `parsers.EXTS`，`is_p0() = true`，**零新增第三方依赖**（仅标准库 `zipfile` + `xml.etree.ElementTree`） |
| 抽取形态 | 按 **spine 顺序**输出，每章带 `[chapter n]` 边界标记 |
| 许可状态 | **未引入任何新库** → `ebooklib`（AGPL）等仍**不在依赖树中**，许可风险为零 |
| 安全边界 | 压缩包安全 + OPF/spine 定序 + HTML/XML 安全 + 异常格式拒绝，共 41 项测试（**开发自验**，见 §11.4/§12） |
| **QA 状态** | ⚠️ **独立 QA 待完成**（`INDEPENDENT_QA = PENDING`）；41 项为**施工方自验** |
| 尚未覆盖 | 图片型/固定版式 EPUB（`svg`/`img` 正文）、DRM/加密 EPUB（→ `encrypted`）、纵向排版等 → **P1 范围** |


### 5.2 书页图片 / 扫描页 OCR —— 当前 **完全不支持**，且**架构上无处安放**

| 项 | 结论 |
|---|---|
| 当前能力 | `unsupported_content_type`（`.png` 不在 `EXTS`）；扫描件 PDF → `scanned_pdf_no_text` |
| OCR 引擎 | **全仓与镜像内均无**（无 tesseract / PaddleOCR / ocrmypdf / RapidOCR） |
| 许可红线 | `ocrmypdf`、`phonemizer/espeak-ng` 等已列红线；主流开源 OCR 多为 GPL/AGPL 系 |
| 架构冲突 | 解析运行在**网关侧（Linux/ARM64 容器，NAS）**，NAS **无 macOS 框架**；而 macOS 原生 OCR（Vision）只能在**客户端**跑 |
| 唯一低风险候选 | **Apple Vision OCR（`pyobjc-framework-Vision`）**——设备端、离线、无网络、pyobjc 为宽松许可；`client/.venv` 已有 `Quartz`/`Cocoa`/`objc`，**缺 `Vision` 一个包** |
| 代价 | ①需新增 1 个依赖（macOS-only）；②OCR 必须**改在客户端执行**，与「解析在网关」分层**冲突**，需引入「客户端预处理 → 上传文本」的旁路；③结果质量需人工校对兜底 |
| 建议 → **裁定** | ✅ **`D3 = OCR_DEFERRED_TO_P1`**（见 §8）。在本轮**不实现**，扫描件保持**诚实降级**（`scanned_pdf_no_text` / `unsupported_content_type`），**不得**假装可用 |

---

## 6. 架构判定（本轮**新增的关键结论**）

### 6.1 教材导入解析**后端已完整实现**，且是**已挂载的 HTTP API**

`gateway/app/admin/api_import.py`（318 行）已实现并挂载 **10 条路由**：

| 方法 | 路径 | 语义 |
|---|---|---|
| GET | `/admin/knowledge/parsers` | 能力表（含 `available`/`reason`） |
| POST | `/admin/knowledge/import` | I1 上传（multipart，20 MB 单文件上限，`Idempotency-Key`） |
| GET | `/admin/knowledge/import` | 作业列表（`status`/`dataset_id` 过滤） |
| GET | `/admin/knowledge/import/{job_id}` | 作业详情（含预览） |
| POST | `/admin/knowledge/import/{job_id}/commit` | I4 提交（`confirm` 强制；**回读磁盘成功才报 `applied`**） |
| POST | `/admin/knowledge/import/{job_id}/cancel` | 取消 |
| POST | `/admin/knowledge/import/{job_id}/retry` | 重试 |
| GET | `/admin/knowledge/dataset/{ds_id}/imports` | 数据集作业 |
| POST | `/admin/knowledge/migrate` / `rollback` | 存储维护（显式 + 审计） |

关键工程性质（**已具备，无需重建**）：
- **8 态机 + 预览 TTL 30 min**（`modules/knowledge/imports.py`）；
- **上传绝不写库**，仅 `commit` 落盘，且**回读验证后才报成功**（`_disk_knowledge` + `_durable`）；
- 结构化错误码：`unsupported_content_type`(400) / `parser_unavailable`(422) / `duplicate_content`(409，
  带 `existing_doc_id`) / `cap_exceeded`(409) / `job_expired`(410) / `job_not_committable`(409) /
  `store_busy`(503) / `store_unavailable`(503) / `body_too_large`(413) / `confirm_required`(400)；
- 全部写入 `_audit`。

→ **决策：`INTEGRATE`（复用 API），严禁在客户端重建解析/导入流水线**（`DUPLICATE_IMPLEMENTATION = PROHIBITED`）。
→ 这**修正**了 Phase 0 审计 §10-G4 的表述：缺口**不是**"缺后端"，而是**"缺 UI + 缺客户端网络层"**。

### 6.2 UI 确实**完全不存在**

- `admin-v4/app.js`（2 590 行）/ `app-pro.js`（616 行）：**零** `knowledge` / `import` / `dataset` / `parse` 引用。
- `client/`：**零** `admin/knowledge` / `parsers` 引用。
- → 「书库 / 导入 / 解析进度 / 校对 / 发布」5 个页面的**界面**确为 **BUILD**（与 §10-G4 一致）。

### 6.3 客户端**完全无网络层**（V2 最大新增能力）

`client/src/classroom/` 下仅有 `classroom_env.py` / `classroom_model.py` / `qml/` / `data/`：
**没有任何 HTTP / aiohttp / websocket 客户端代码**，`classroom_main.py` 只读本地 JSON。

→ **V2 必须新增「网关 API 客户端」能力**，且需一并设计：
1. **网关地址与鉴权来源**（当前 `ADMIN_ENABLED` 默认 **0**、`ADMIN_BIND` 默认 **`127.0.0.1`**、
   Bearer Token 取自 `/app/secrets/admin_api_token`）→ **Mac 客户端默认无法访问**；
2. **网络态 UI**：离线 / 连接中 / 失败 / 重试 四态（Phase 1 设计稿「六类状态」已含离线与错误态，需补齐对接）；
3. **两条候选路径（**✅ 已裁定 = 路径 A**，见 §8）**：
   - **路径 A（推荐，零 NAS 改动）**：**本地环回网关**——沿用既有先例
     （`~/xz-acc/loopback_gateway.py`、`deploy/v4-acceptance/start_v4_acceptance.py`），
     在 Mac 上以环回地址起网关用于备课链路；**`NAS_CHANGED = NO` 天然满足**。
   - **路径 B（需授权）**：在**公共平面**新增一个窄口导入端点，沿用既有 `X-Vision-Token` 先例
     （`gateway/app/http.py:47-99`：独立令牌文件、恒时比较、**绝不使用 admin token**），
     并显式放行 LAN 绑定。**属新增攻击面 → 需产品负责人书面授权，本轮不得实施。**

---

## 7. 对 Phase 1 设计 / Phase 2 契约的增量

以下 5 项**应并入**既有设计稿与接口契约（不改变 Phase 1 的页面结构，只是补齐边界）：

| # | 增量 | 落点 |
|---|---|---|
| C-EX1 | 契约显式声明 **客户端永不本地解析**；解析仅经 `/admin/knowledge/parse` 族 | 接口合同 §3.2（三段契约） |
| C-EX2 | 新增版面风险提示位 `layout_suspect`（或等价物）：多栏疑似错序时**必须**在预览页提示并强制人工校对 | §3.6 课程数据契约 / 校对页 |
| C-EX3 | `scanned_pdf_no_text` / `unsupported_content_type` / `parser_unavailable` 三码的**中文可操作文案**与 UI 呈现（非空白页） | 六类状态规范（错误态） |
| C-EX4 | PPTX `[slide n]` 分页标记 → `slide` 语义切分的**直接映射**（已实测存在，降低切分难度） | §3.6 课程数据契约 |
| C-EX5 | DOCX 表格已线性化为 `词条 \| 音标 \| 释义` → 词汇表抽取的**首选结构**（优于正文段落） | §3.7 锚点精度 |

---

## 8. 待产品负责人决策项 → **已裁定（REV1A/REV1B）**

| # | 决策项 | 首轮选项 | **裁定结果** |
|---|---|---|---|
| D1 | 备课链路如何连网关 | A 本地环回网关／B 公共平面窄口端点 | ✅ **`D1 = MAC_LOOPBACK_ISOLATED`**（本机环回、独立验收环境；安全方案见 `security/`，部署见 `deploy/`） |
| D2 | EPUB 是否纳入 P0 | 纳入／延后 | ✅ **`D2 = EPUB_TEXT_ONLY_IN_P0`** —— **已实施**（§11）；**独立 QA 待完成**（§12） |
| D3 | 扫描页 OCR 是否做 | 不做／macOS Apple Vision | ✅ **`D3 = OCR_DEFERRED_TO_P1`** —— **本轮不实现**，保持诚实降级（`scanned_pdf_no_text` / `unsupported_content_type`） |

---

## 9. 证据文件与复现

| 文件 | 说明 |
|---|---|
| `docs/engineering/product-v1/classroom-v2/evidence/parser_capability_probe.py` | 探针 v2（只读、离线、可复现） |
| `docs/engineering/product-v1/classroom-v2/evidence/parser_capability_probe.json` | 完整结构化结果（依赖矩阵 + 10 用例） |
| `docs/engineering/product-v1/classroom-v2/evidence/parser_capability_probe.err` | stderr（空 = 无异常） |
| `modules/knowledge/parsers.py` | 被测对象。**首轮未修改**；**D2 实施后已修改**（+EPUB，见 §11.1） |
| `docs/engineering/product-v1/classroom-v2/evidence/epub_parser_security_tests.json` | **D2**：EPUB 安全测试证据（`safety_constants` / `dtd_policy` / 逐用例结果） |
| `gateway/tests/knowledge_epub_tests.py` | **D2**：EPUB 安全测试用例（**开发自验 41 项**，独立 QA 待完成） |
| `deploy/v4-candidate/Dockerfile` | 网关镜像依赖钉版声明（L54–56） |
| `gateway/app/admin/api_import.py` | 已实现的导入 API（10 路由）；D2 改 1 处文案去硬编码 |
| `prototypes/.../fix-03-travel-story.pdf` | 真实 PDF 样本 |

---

## 10. 状态块（**滚动修订 · REV1B 生效版**）

> 下方区分「首轮值」与「当前值」；**当前值生效**。

```
PHASE                = P0 后端验证（与 Phase 1 设计审定并行，互不冲突）
P0_FORMATS_VERIFIED  = TXT/MD/PDF/DOCX/PPTX  →  REAL_VERIFIED (5/5 PARSED)
REAL_PDF_SAMPLE      = REAL_VERIFIED（仓内既有 PDF，5 940 字符）
SCANNED_PDF          = REAL_VERIFIED（scanned_pdf_no_text，诚实降级）
TWO_COLUMN_DEFECT    = REAL_VERIFIED（静默错序已复现，宽/窄栏距对照 + 阈值刻画）
EPUB（当前）         = IMPLEMENTED（D2）· 文字型 · spine 定序 · 零新增依赖 · 开发自验 41/41
EPUB_INDEPENDENT_QA  = PENDING（⚠️ **独立 QA 待完成**；41/41 为施工方自验，非独立结论）
IMAGE_OCR            = UNSUPPORTED_BY_DESIGN · 无引擎 · **D3 = OCR_DEFERRED_TO_P1**（不新增云调用）
DEP_DECLARATION      = 网关镜像已钉版声明（Dockerfile L54-56）；客户端不解析（无需声明）
IMPORT_API           = IMPLEMENTED（gateway/app/admin/api_import.py，10 路由，8 态机，回读验证）
IMPORT_UI            = NOT_PRESENT（Web 管理端与客户端均无）→ BUILD
CLIENT_NETWORK_LAYER = NOT_PRESENT（V1 课堂纯离线）→ BUILD（V2 新增能力）
INTEGRATE_DECISION   = 教材导入 = INTEGRATE 后端 API + BUILD 客户端 UI（禁止重复实现）
DUPLICATE_IMPL       = PROHIBITED（已核验：客户端零解析代码）
DECISIONS（当前）    = D1 = MAC_LOOPBACK_ISOLATED / D2 = EPUB_TEXT_ONLY_IN_P0（已实施）/ D3 = OCR_DEFERRED_TO_P1
SOURCE_MODIFIED      = **YES**（当前）——D2 修改 `parsers.py`（+EPUB）· 新增 `gateway/tests/knowledge_epub_tests.py`
                        · `api_import.py` 1 行文案 · 2 个计数对齐测试（[首轮值 = NO，仅新增 docs/]）
NAS_CHANGED          = NO
REAL_MODEL_REQUESTS  = ZERO
FROZEN_SIX_FILES     = UNCHANGED（Tina 冻结六文件未触碰）
PROTECTED_AVATAR_SET = UNCHANGED（受保护数字人文件集合与基线一致）
NEXT                 = Phase 1 设计 REV1B 补正 → Phase 2 多 Agent 施工（主 UI 门禁）
```

---

*§1–§10 为**首轮只读验证**产物（未修改源码、未部署、未调用模型、未变更 NAS）；
§11 起为 **D2 实施记录**（**已修改 `parsers.py`** 等，见 §11.1/§10 状态块）。*

---

## 11. D2 实施记录：EPUB 文字型解析（`IMPLEMENTED`）

> 依据产品负责人裁决 `D2 = EPUB_TEXT_ONLY_IN_P0`：「必须执行压缩包安全、OPF/spine 顺序、HTML/XML 安全和异常格式拒绝测试。不得引入未经许可审核的库。」

### 11.1 交付与依赖

| 项 | 结论 |
|---|---|
| 改动文件 | `modules/knowledge/parsers.py`（+ EPub 支持）、`gateway/tests/knowledge_epub_tests.py`（新增）、`gateway/app/admin/api_import.py`（1 处文案去硬编码） |
| **新增第三方依赖** | **零**（仅标准库 `zipfile` + `xml.etree.ElementTree`） |
| 许可风险 | **无**（未引入 `ebooklib` 等 AGPL 库） |
| 新错误码 | `epub_malformed`（非 zip / 损坏 / 空 / 无 container / 无 rootfile / 无 spine）、`epub_unsafe`（超限 / 路径穿越 / ENTITY / 外部 DTD） |
| 复用错误码 | `encrypted`（加密归档）、`empty_extraction`（无可读文本）、`extract_failed` |

### 11.2 安全设计要点

| 面 | 措施 |
|---|---|
| **压缩包安全** | 条目数 ≤ 4096；单条目解压 ≤ 16 MiB；**全档解压总量 ≤ 64 MiB**；分块流式读取计数；拒绝绝对路径 / 盘符 / 反斜杠逃逸 / `..` 穿越 |
| **OPF/spine 顺序** | `META-INF/container.xml` → rootfile → OPF `manifest`/`spine` → **严格按 `itemref` 顺序**输出（**非**条目名、**非**字典序） |
| **HTML/XML 安全** | 解析**前**拒绝 `<!ENTITY ...>`（实体膨胀/XXE）、`<!DOCTYPE ... SYSTEM\|PUBLIC ...>`（外部 DTD 拉取）、`<!DOCTYPE ... [ ... ]>`（内部子集）；剥离 `<script>`/`<style>`/`<head>` 内容 |
| **异常格式拒绝** | 非 zip、空 zip、损坏 zip、无 container、container 指向缺失 rootfile、OPF 无 spine —— 全部返回**结构化错误码，绝不抛异常** |
| **诚实降级** | 单章 XML 不可解析 → **输出可见标记**（`[本章无法解析，内容缺失，需人工确认]`）而**非静默丢弃**；若**全部**章节不可读 → 仍报 `empty_extraction`（**不返回"只有标记的成功结果"**） |

### 11.3 总控裁决的两项修正（TC decision 2026-10-12）

施工方提出两处需裁决，总控裁定并实施：

1. **DTD 严格性（功能性阻塞）**：初版「拒绝任何 `<!DOCTYPE`」会**误杀绝大多数真实 EPUB**（其 XHTML 普遍带无害的 `<!DOCTYPE html>`）。
   → **裁决：精确化**。拒绝三种**危险**构造（`<!ENTITY>`、外部队 `SYSTEM/PUBLIC`、内部子集），**放行并剥离裸 `<!DOCTYPE html>`**（其自身无法定义实体）。
   实施于 `_epub_sanitize_xml()`；`EPUB_REJECT_DTD` / `EPUB_ALLOW_BARE_DOCTYPE` 为可一处调整的策略位。
2. **坏章节静默丢弃**：原实现跳过不可解析章节且无任何信号。
   → **裁决：可见降级**。改为输出显式标记，使缺口在预览/校对环节**可见**；全坏时仍 `empty_extraction`。

### 11.4 测试证据与自证伪（**施工方开发自验 · 独立 QA 待完成**）

> ⚠️ **REV1B 归属澄清**：以下全部为**施工方自验（developer self-verification）**。
> **独立 QA 尚未完成**（`INDEPENDENT_QA = PENDING`）；**不得**把本节数字表述为"独立验证通过"或"**全仓回归通过**"。
> 覆盖范围说明：`187/187` = `knowledge_epub_tests` 41 + `admin_v4_api_tests` 107 + `import_v4_tests` 39，
> **是本批相关测试子集**，**不是**全仓回归（全仓另有既有基线债务未纳入）。

- 测试：`gateway/tests/knowledge_epub_tests.py` → **41/41 通过（自验）**（含 C04a–C04e DTD 谱系、C09 空文本、C15/C15b 章节降级、C17 端到端进管线）。
- 证据 JSON：`docs/engineering/product-v1/classroom-v2/evidence/epub_parser_security_tests.json`
  （含 `safety_constants`、`dtd_policy`、逐用例真实结果）。
- 逐格式探针（刷新后）：`parser_capability_probe.json` → `p0_parsed_ok` = **六格式全通过**（`.txt .md .pdf .docx .pptx .epub`）；
  EPUB 预览实测显示 **spine 定序生效**（`a-first.xhtml` → `[chapter 1]`）且 `<script>` 被剥离。
- **相关测试子集**：`admin_v4_api_tests` **107/107** · `import_v4_tests` **39/39** · EPUB **41/41**（合计 **187/187**，**自验**）。
- **自证伪（总控亲自执行）**：
  - 将 sanitizer 退回「拒绝任何 DOCTYPE」→ **C04c 必然失败**，证明该用例真的在检验放宽行为；
  - 彻底移除 sanitizer → XXE 样本不再返回 `epub_unsafe`（退化为 `empty_extraction`），
    证明 `_epub_sanitize_xml` 是**产生确定性错误码的唯一命名门禁**；
    **诚实注记**：`xml.etree` 自身对未定义实体会抛错，构成**偶然的次级防护**，
    但它**不保证**覆盖全部实体膨胀向量，故**不以此替代**显式门禁。

### 11.5 未覆盖范围（明确边界）

- 图片型 / 固定版式 EPUB（正文为 `svg`/`img`）→ 提取为空，走 `empty_extraction`（**不猜内容**）；
- DRM / 加密 EPUB → `encrypted`；
- 纵向排版、MathML、EPUB2 NCX 目录树 → **P1**；
- **未做**：EPUB 内嵌字体的音标映射、脚注/注释重排。

---

## 12. QA 归属与复核状态（REV1B 新增 · **诚实声明**）

> 产品负责人 REV1B 明确要求：**EPUB 41/41 与 187/187 必须由独立 QA 重新核实，报告真实覆盖范围，不得当成全仓回归通过**。

| 项 | 状态 | 说明 |
|---|---|---|
| **EPUB 解析实施** | `IMPLEMENTED` | `parsers.py` +EPUB；零新增依赖（§11.1） |
| **D2 开发交付验收** | ✅ **产品负责人接受** | REV1B：接受开发交付 |
| **独立 QA（EPUB 41 项）** | ⚠️ **`PENDING`** | 现有 41/41 为**施工方自验**；**须由独立 QA 重新执行并出报告** |
| **独立 QA（相关子集 187）** | ⚠️ **`PENDING`** | 187 = EPUB 41 + admin_api 107 + import 39，**为本批相关子集**；**不得**表述为"全仓回归通过" |
| **回归真实覆盖范围** | **本批相关测试子集** | 全仓另有**既有基线债务**（`admin1_tests` 81/83、`r1f` 2× OpusError、`client_ui1` aiohttp reset 等，属环境性既有基线），**未纳入本批通过口径** |
| **总控自证伪** | ✅ 已执行 | 见 §11.4（退回旧 DTD 规则 → C04c 必失败；移除 sanitizer → XXE 退化） |
| **许可复核** | ✅ 无新增库 | 未引入 `ebooklib`(AGPL) 等；许可风险为零 |
| **边界核验** | ✅ | Tina 冻结六文件 `git diff` 为空；受保护数字人文件集合与基线一致、本次未触碰 |

**独立 QA 待办清单（供下一阶段执行）**：
1. 在**干净环境**重新运行 `knowledge_epub_tests.py`，核验 41/41 与逐用例断言**非自验性质**；
2. 独立构造**对抗样本**（路径穿越、超限压缩包、ENTITY 膨胀、外部 DTD、内部子集、坏 spine、加密归档），核验错误码与 §11.2 一致；
3. 独立核验**压缩包安全阈值**（4096 条 / 16 MiB 单条 / 64 MiB 总量）与**流式计数**是否真在解压前生效；
4. 独立核验 **spine 定序**（构造条目名顺序 ≠ spine 顺序的样本，断言输出按 spine）；
5. 独立核验**坏章节可见降级**与**全坏 → `empty_extraction`**；
6. 出独立 QA 报告，明确**覆盖范围**与**未覆盖范围**，并声明**非全仓回归**。
