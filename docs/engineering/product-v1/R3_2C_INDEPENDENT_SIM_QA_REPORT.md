# XIAOZHI V4 — R3-2C 独立机器模拟审计报告（INDEPENDENT-SIM-QA）

**审计窗口**：独立质量审计窗口（不承担开发；未修改任何产品代码）
**日期**：2026-10-12　**分支**：`p2b2-teacher-voice`　**审计起点 HEAD**：`a49b6c9258181633ec78ae970804cecc3d136d3e`（= `a49b6c9`，与任务书一致）
**受审提交**：`ee1b3ab`（R3-2C 功能开发）+ `a49b6c9`（错误码映射补丁）
**执行环境**：本机隔离夹具（`/tmp/r32c_qa/`，12 个独立脚本 + 日志）、本机 Mock 服务（127.0.0.1）、Qt offscreen、无头 Chromium。**全部网络仅 127.0.0.1**。

> 方法与独立性声明：本窗口**未复用施工方测试代码**做结论，而是独立构造夹具并**自行编写**脚本（`qa_a_admin_api.py` / `qa_b_teacher_picker.py` / `qa_c_dashscope.py` / `qa_c_list.py` / `qa_d_isolation.py` / `qa_d_tina_route.py` / `qa_e_audit.py`），另对 9 个必跑套件做**原样复跑**。自证伪仅作用于 `/tmp` 下的 **gating.py 副本**，工程文件哈希审计前后不变。

> ⚠️ **重要更正**：审计开始时，交付路径 `docs/engineering/product-v1/R3_2C_INDEPENDENT_SIM_QA_REPORT.md` 已存在一份来源不明的旧草稿（mtime 02:42，其结论为本轮机器 PASS、并声称“显示老师名称 PASS”）。**本窗口不采用其任何结论**；下述内容全部出自本窗口实测。经独立实测，该草稿关于“老师名称显示 PASS”的结论**被证伪**（见 P2-1）。本文件为**本窗口的独立结论**，覆盖该旧草稿。

---

## 〇、门槛判定总表

```
BASELINE            = VERIFIED
GUI_AUTOMATION      = PASS      （admin 面板=真实无头浏览器全 GUI PASS；
                                  Mac 客户端=真实 QML 引擎 offscreen 组件级 PASS；
                                  桌面窗口级鼠标点击链路未自动化——如实标注，见 §六.C）
ADMIN_PANEL_SIM     = PASS
TEACHER_SELECTION   = FAIL      （选择/映射/保存/令牌安全均 PASS，但**所选老师名称在收起的下拉框中不显示**，见 P2-1）
TEACHER_SWITCH      = PASS
ERROR_MESSAGES      = PASS
DASHSCOPE_MOCK      = PASS
EVIDENCE_GATE       = PASS      （含有效自证伪）
CREDENTIAL_ISOLATION= PASS
CONTEXT_ISOLATION   = PASS
TINA_FROZEN         = UNCHANGED
DIGITAL_HUMAN       = UNTOUCHED
NAS_CHANGED         = NO
REAL_MODEL_REQUESTS = ZERO
INDEPENDENT_QA      = PASS_WITH_NOTES   （0 P0 / 0 P1 / **1 P2** / 3 P3）
HUMAN_TEST          = PENDING
```

---

## 一、基线锁定（BASELINE = VERIFIED）

| 项目 | 结果 |
|---|---|
| 分支 / HEAD | `p2b2-teacher-voice` @ `a49b6c9`（与任务书一致） |
| 冻结六文件 sha256 | 与 `P2B2_R3_0_MODEL_ENABLED_GATE_DELIVERY.md` §三记录的基线**逐字节一致 6/6**（turns `e18a0d08…`、qwen `13d4800d…`、audio `c2218a2c…`、protocol `944e2d5a…`、ws `dde9d427…`、behavior `6d705960…`） |
| R3-2C 两提交对冻结六文件 | diff **为空**（精确路径核对 6/6 clean） |
| R3-2C 两提交对数字人文件（manager.py / AvatarLive2D.qml / avatar_page.js） | diff **为空**；工作区数字人未提交改动与审计开始时一致（`M` 原样，本窗口只读未触碰） |
| diff 规模 | `ee1b3ab` 实测 **20 文件 +975/−21**；合并 `a49b6c9` 后 **21 文件 +1057/−21**（施工报告称“19 文件 +~1100/−15”→ 登记 **P3-1**） |

---

## 二、必须复跑的测试（9/9 套件全绿，528 项，0 失败）

网关套件使用 `client/.venv`（Python 3.10，含 aiohttp/cryptography）+ `PYTHONPATH=repo:gateway` 运行；客户端套件用 `client/.venv`。**说明**：仓库内 `gateway/.venv`（Python 3.14）缺 `cryptography`/`pyyaml`，无法直接跑 R1 凭据测试——本轮改用含依赖的隔离解释器，未改动任何环境或产品代码。

| 套件 | 本轮独立复跑 | 施工报告声明 | 一致 |
|---|---|---|---|
| `realtime_probe_tests` | **23/23** | 23/23 | ✓ |
| `teacher_voice_seam_tests` | **60/60** | 60/60 | ✓ |
| `teacher_context_seam_tests` | **83/83** | 83/83 | ✓ |
| `model_v4_tests` | **72/72** | 72/72 | ✓ |
| `admin_v4_api_tests` | **107/107** | 107/107 | ✓ |
| `teaching_v4_tests` | **36/36** | 36/36 | ✓ |
| `voice_v4_tests` | **74/74** | 74/74 | ✓ |
| `test_client_ui_transcript`（client venv） | **48/48** | 48/48 | ✓ |
| `test_gui_transcript_live`（Qt offscreen） | **25/25** | 25/25 | ✓ |

**既有失败基线**：以上 9 套件本轮**零失败**。既往登记的环境性失败（admin1_tests 81/83、r1f Opus、client_ui1 aiohttp reset）不在必跑清单内，维持既有登记，未静默忽略、亦未重分类。

### 本窗口独立脚本合计（不计入上表）

| 脚本 | 覆盖 | 结果 |
|---|---|---|
| `qa_a_admin_api.py` | QA-A API 层全流程 | **22/22** |
| `qa_b_teacher_picker.py` | QA-B 老师选择（Qt offscreen 真实组件） | **27/29**（2 FAIL = P2-1 复现） |
| `qa_c_dashscope.py` | QA-C 探针真实回环拨号 + 门禁 + 自证伪 | **30/30** |
| `qa_c_list.py` | 老师列表端点（令牌 oracle / 字段白名单） | **7/7** |
| `qa_d_isolation.py` | QA-D A/B 隔离（真实接口） | **23/23** |
| `qa_d_tina_route.py` | Tina 默认路由不变（真实 `_resolve_endpoint`） | **8/8** |
| `qa_e_audit.py` | QA-E 程序化代码审计 | **15/15** |

---

## 三、QA-A：管理控制面板（ADMIN_PANEL_SIM = PASS）

**分层声明（按要求区分，互不冒充）**：

- **真实 GUI 自动化**（无头 Chromium 驱动真实 `admin-v4` 静态界面 + 真实 `/admin/*` 后端，隔离令牌）：登录、服务商页、能力测试页、R3-2C 握手弹窗、中文拒绝 —— 全部 PASS。
- **API 层模拟**（真实 aiohttp HTTP 栈 + 隔离存储）：22/22。
- **静态代码检查**：能力页新列/阶梯标签/中文映射 —— 逐行核对。

**GUI 实测要点（无头浏览器）**：

| 步骤 | 实际现象 | 判定 |
|---|---|---|
| 登录页 | 中文登录页，令牌输入框 `#loginToken`（password 掩码）+「登录」按钮 | PASS |
| 令牌登录 | 输入 QA 令牌→「登录成功，令牌已保存到本次会话」，侧栏转为已连接、出现「退出登录」与日常导航 | PASS |
| 管理总览 | 「日常模式 · 真实数据」「学习与服务概况」四张统计卡（语音连接=模拟/未连接、我的模型=1 个、知识资料=0、课程进度=未接入） | PASS |
| 服务商管理 | 列出预置服务商「浏览器QA服务商」；「＋添加服务商」弹窗含「名称/协议/接口地址」 | PASS |
| 能力测试 | 表头含新列 **「实时握手验证（需授权）」** +「运行」；阶梯说明含「实时握手与会话已验证」「握手成功本身不授予 realtime_safe」 | PASS |
| 握手确认弹窗 | 点击后弹出含「**可能产生少量费用**；单次 **20 秒**内自动超时结束；**不发送任何音频**、不请求生成」 | PASS |
| 确认结果 | 弹出后页面出现中文拒绝「**实时握手验证需产品负责人独立授权（当前环境未开启）。**」 | PASS |
| 令牌安全 | 页面文本/属性/输入框均**无 QA 令牌明文**；令牌仅存于 `sessionStorage['xz_admin_token']` | PASS |

> 过程更正（诚实记录）：首轮浏览器验证时「管理总览」报「请求失败：error」。经排查根因为**本窗口隔离夹具缺 `knowledge_import_file`**，导致可选路由 `/admin/knowledge/parsers` 未挂载（404）而被首页 `Promise.all` 一票否决。补齐夹具后首页正常渲染、`/admin/knowledge/parsers` 返回 200。此为**本窗夹具缺陷、非产品缺陷**，特此更正（见 P3-3 的同类观察）。

**API 层实测（22 项）**：无令牌→401；带令牌→200；加服务商成功、明文 `http://` 端点被结构化拒绝；录入模拟凭据成功且**列表只回显指纹、零明文**；登记模型**默认 `enabled=False`**；未验证时 `bind-scene`/`enable` 均 **fail-closed 拒绝**；创建 realtime 老师成功、空名 400；`voice_id` 读回一致；老师 payload **无 token/secret/api_key 键**；`mode=realtime_handshake` 默认 **403 `realtime_probe_not_authorized`**；未知 mode→400。

---

## 四、QA-B：Mac 老师选择与切换（TEACHER_SELECTION = FAIL；TEACHER_SWITCH = PASS）

**执行方式**：真实 `SystemOptionsTab.qml` + 真实 PySide6 QML 引擎，`QT_QPA_PLATFORM=offscreen` 无头实例化；配置经 `XIAOZHI_DATA_DIR` 隔离（**未触碰真实客户端配置**）；断开语义调用**真实 `ConversationSession._on_protocol_disconnect_request`**；错误映射调用**真实 `teacher_error_cn`**。共 29 项，27 PASS / 2 FAIL。

| 任务书要求项 | 结果 | 证据 |
|---|---|---|
| 老师列表正常显示 | PASS | 下拉 `count==2`；`textRole == "display_name"`（列表项显示名称而非 id） |
| **显示老师名称与音色** | **FAIL** | 见下 **P2-1**：收起的下拉框恒显示「未选择老师」 |
| 正确映射 teacher_id | PASS | `teacherId=tB→currentIndex=1`、`=tA→0`、未知→-1、空列表→-1 |
| **不显示部署令牌** | PASS | QML 无令牌字段；**实时对象树所有 `text/displayText/placeholderText` 均无令牌串**；配置中令牌仅作请求头 |
| 选择老师后正确保存 | PASS | `teacherId` 经真实 getter/setter 写入配置路径 |
| 保存不会自动发起连接 | PASS | 真实 `PROTOCOL_DISCONNECT_REQUEST` 处理器：已连接→`disconnect()` 恰 1 次、**`connect()` = 0** |
| 切换老师正确关闭旧会话 | PASS | 断开前重置 `set_keep_listening(False)`（实测 keep_listening=False） |
| 用户点击开始才建连 | PASS | 未连接时零动作；代码路径不存在自动 connect |
| 无老师/停用/令牌错误中文反馈 | PASS | 缺地址→「未配置服务地址…」；缺令牌→「未配置部署令牌…」；HTTP 401→「部署令牌无效或缺失」；未知码→ None 兜底 |

### 【P2-1】老师选择框不显示所选老师名称（本轮 R3-2C 引入）

- **严重级别**：P2（用户可见功能缺陷，不涉及安全/门禁）
- **文件:行号**：[SystemOptionsTab.qml:334](file://<project-root>/client/src/ui/gui/qml/windows/settings/SystemOptionsTab.qml#L334)
  ```
  displayText: currentIndex >= 0 ? displayText : "未选择老师"
  ```
- **根因**：该绑定**自引用**（真分支返回 `displayText` 自身）。一旦初值为「未选择老师」，`currentIndex` 变化后重算仍取回旧值，故**永远不会翻到所选老师**。同级 `XComboBox.qml:28` 的 `contentItem.text` 绑定到 `root.displayText`，因此**收起的控件恒显示占位文案**（下拉展开时列表项走 delegate，另读 `modelData[display_name]`，名称可正常显示）。
- **复现（offscreen，可重复）**：把 `settingsModel.teachers` 设为 2 位老师，`teacherId="tB"` → `currentIndex==1` 但 `displayText=="未选择老师"`；`teacherId="tA"` → `currentIndex==0` 但 `displayText` 仍为「未选择老师」。
- **对照实验（决定性）**：同一引擎内三个最小 `ComboBox`——无绑定→`"bbb"`；**本轮自引用写法→恒 `"PLACEHOLDER"`**；`currentText` 写法→`"bbb"`。证明缺陷来自绑定本身，而非环境。
- **预期 / 实际**：预期收起控件显示所选老师名称（如「老师B」）；实际恒显示「未选择老师」。
- **最小整改建议（本窗口不施工）**：改为
  ```
  displayText: currentIndex >= 0 ? currentText : "未选择老师"
  ```
- **影响**：普通用户保存/切换老师后**无法在收起的下拉框确认当前选了谁**；`teacherId` 数据本身正确、保存与断开语义正确，故不影响隔离与计费安全，但影响 QA-B「显示老师名称」一项的可用性。

---

## 五、QA-C：DashScope 模拟验证（DASHSCOPE_MOCK / EVIDENCE_GATE = PASS）

**独立脚本**（`qa_c_dashscope.py`，30 项 + 列表端点 7 项）：
- **A 组（真实回环拨号，无注入）**：A1–A11 —— 对 `realtime_capability_probe` **真实拨号**本地 Mock WS：`network/handshake/session_compat` 全 True；`audio=not_tested`、`verified=False`；线上 `Authorization` 头 == 传入的服务商密钥；`session.update` 帧**仅含配置、无音频/无生成**；上游即关→`handshake_*`；错误事件→`server_error:*`；无 `session.updated`→`session_*` 且连接关闭；拒连→结构化失败不抛异常。
- **B/C 组（真实 HTTP 门禁）**：B1 授权位关→403 `realtime_probe_not_authorized` 且**探针未被调用**；B2 缺 `confirm_realtime`→403 且**零拨号**；B3–B8 授权+确认→200、写入等级=`realtime_handshake`、结果诚实、探针用**服务商自有端点与自有密钥**（≠全局/Tina Key）；B9 非 MaaS 端点→400 `realtime_binding_unavailable` **零拨号**；B10 冻结模型→400 `frozen_model` **零拨号**；B11 `verified` 仍受其自身 `test_not_authorized` 门禁（未被新 flag 旁路）。
- **E 组（阶梯诚实）**：仅 `realtime_handshake` 证据 → 真实 `enable_gate(scene="oral_realtime")` **拒绝 `evidence_missing`**；握手**永不**满足 `oral_realtime`。
- **D 组（有效自证伪）**：篡改 **`/tmp` 下 gating.py 副本** 的 `_ORDER`（把 `realtime_handshake` 抬到 `verified` 之上）→ 拒绝码**翻转**（`evidence_missing` → `capability_mismatch`），证明 E 组断言**能捕获阶梯绕过、非空洞**；工程 `gating.py` 哈希审计前后**不变**且仍拒绝。
- **老师列表端点（`qa_c_list.py`，7 项）**：无令牌与错令牌**同为 401 同码**（无枚举 oracle）；正确令牌→200 仅含**已启用实时非冻结**老师；仅返回 `{teacher_id, display_name, voice_id, language}`；响应**无令牌材料**。

**任务书清单逐项**：授权位默认关 ✓｜未确认拒绝 ✓｜错误凭据拒绝 ✓｜非法端点拒绝（零拨号）✓｜冻结模型拒绝（先于拨号）✓｜模拟握手成功 ✓｜模拟 `session.updated` ✓｜超时关闭 ✓｜失败清理 ✓｜不借用 Tina 凭据（线上实录）✓｜不产生真实请求（全 127.0.0.1）✓。
**realtime_handshake ≠ verified** ✓（结构性：阶梯序数在 verified 之前，且 E 组实证拒绝）。**无音频证据不得 realtime_safe** ✓。

**负向测试共 8 类**：上游即断 / 错误凭据(错误事件) / 会话超时 / 拒连 / 冻结模型 / 冻结服务商 / 未授权 / 缺确认。

---

## 六、QA-D：全链路隔离（CREDENTIAL_ISOLATION / CONTEXT_ISOLATION = PASS）

两位老师 A（英语/Cherry/服务商A/KEY-A/教材 ds_a）与 B（数学/VoiceB/服务商B/KEY-B/教材 ds_b），经**真实接口**（`default_resolver` / `project_teacher_context` / `KnowledgeStore` / `open_teaching_record`）验证，23/23 + 客户端 Tina 路由 8/8。

| 要求项 | 结果 | 证据 |
|---|---|---|
| 教学规则不能串用 | PASS | A/B 政策投影路径按 `teacher_id` 隔离、内容互异 |
| 教材授权不能串用 | PASS | A 投影只含 ds_a；**A 的存储检索不到 B 的教材**（交叉反证命中 0）；源库哈希不变 |
| 凭据不能串用 | PASS | 经真实 `default_resolver`：A=KEY-A、B=KEY-B，均 ≠ 全局 Tina Key；全局配置逐值未变 |
| 断开与重连无旧会话残留 | PASS | A 重复投影**字节级幂等**（policy/knowledge sha256 一致）；重连解析同一绑定 |
| 私有学生记忆仍 fail-closed | PASS | `memory_decision()==("", disabled)`；A/B 投影 memory 路径为空 |
| 未授权时课堂记录不写入 | PASS | 无 store→`not_configured`；无学生身份→`no_identity`；无绑定→`no_binding`；**期间会话表为空** |
| **Tina 默认路由保持不变** | PASS | 真实 `_resolve_endpoint`：无 `TEACHER_ID` → URL **逐字节同旧**、无 `X-Teacher-Token`、基础头不变；配置老师→老师路径+`teacher_id=`+令牌头（令牌**不入 URL**）；清除老师→立即复原；仅老师 id 无令牌→**留在 Tina 默认**（不半路由） |
| R2 旋钮缺省即关 | PASS | 未设 `data_dir` → policy/knowledge/memory 三路径全空 |

---

## 七、QA-E：独立代码审计（`ee1b3ab` + `a49b6c9`，21 文件逐文件）

已逐文件审阅全部改动（server: `api_model.py`/`app.py`/`realtime_probe.py`/`stores.py`/`main.py`/`teacher_voice.py`/`registry.py`/`realtime_probe_tests.py`；client: 10 文件；admin-v4: 2 文件；docs: 1 文件）。程序化审计 15/15：

- ✅ **未超授权范围**：改动全部落在“GUI 老师选择/切换 + DashScope 证据通道”。
- ✅ **无新的隐式连接**：客户端新增行中**无 `connect()`/`start_listening`/`connect_protocol`**；切换仅发 `PROTOCOL_DISCONNECT_REQUEST`。
- ✅ **无日志泄露**：新增日志**无插值令牌/密钥值**；列表 401 仅记 `invalid_token`（不区分缺/错，无 oracle）。
- ✅ **不绕过 enabled / evidence 门禁**：`model_test` 的 `frozen_model` 检查位于探针分支**之前**；`default_resolver` 的 `model_disabled`（R3-0）与 `enable_gate` 保持；探针写证据上限为 `realtime_handshake`，`enable_gate` 需 `>= verified`（oral_realtime 还需 `realtime_safe`），**结构性不受影响**（D 组自证伪实证）。
- ✅ **未误触冻结或数字人文件**：diff 为空（§一）。
- ✅ **异常路径无遗漏**：探针全异常捕获并分类 `reason`；断开处理器全捕获；列表端点 500 兜底。
- ✅ **探针无全局密钥路径**：`realtime_probe.py` **不 `import os`、不读文件、不 `getenv`**（唯一 `QWEN_SECRET_FILE` 出现在“说明不读它”的文档字符串中）。
- **错误码覆盖（程序化）**：教师路由服务端码 21 个，其中 GUI 可达 19 个 → **客户端中文映射 20 码全覆盖**；未映射的仅为 `teacher_id_required`（客户端只在 `teacher_id` **且** 令牌齐备时才走老师路由，普通 GUI 不可达）与 `not_found`（在 `model_missing` 之后不可达），登记 **P3-2**。

---

## 八、发现清单

| 级别 | 编号 | 描述 | 文件:行号 | 复现 | 预期/实际 | 最小整改建议 |
|---|---|---|---|---|---|---|
| **P2** | P2-1 | **老师选择框收起时恒显示「未选择老师」，不显示所选老师名称**（自引用 `displayText` 绑定） | [SystemOptionsTab.qml:334](file://<project-root>/client/src/ui/gui/qml/windows/settings/SystemOptionsTab.qml#L334) | 见 §四 复现 + 对照实验 | 预期显示「老师B」；实际恒「未选择老师」 | `displayText: currentIndex >= 0 ? currentText : "未选择老师"` |
| P3 | P3-1 | 施工报告 diff 数字与实测不符 | [R3_2C_IMPLEMENTATION_REPORT.md:3](file://<project-root>/docs/engineering/product-v1/R3_2C_IMPLEMENTATION_REPORT.md#L3) | `git diff --stat ee1b3ab^ ee1b3ab` | 报告「19 文件 +~1100/−15」；实测 **20 文件 +975/−21** | 勘误（不改代码） |
| P3 | P3-2 | `teacher_id_required`（及死码 `not_found`/`model_unusable`）无客户端中文映射；GUI 路径不可达 | teacher_voice.py:295 ↔ teacher_errors.py | 客户端无 `TEACHER_ID` 时不走老师路由 | 预期全码映射；实际 1 可达码外未映射 | 补 1 行映射（可选） |
| P3 | P3-3 | **既有（非 R3-2C）观察**：`admin-v4` 首页用 `Promise.all` 聚合 4 接口，含可选的 `/admin/knowledge/parsers`；当知识导入子系统未配置时该路由 404，导致**整页**显示笼统「请求失败：error」 | [app.js:497-499](file://<project-root>/admin-v4/app.js#L497-L499) | 以缺 `knowledge_import_file` 的 stores 装载后访问首页 | 预期仅相关卡片降级；实际整页报错 | 后续工程轮：将可选子系统移出整页 `Promise.all` 或单独降级 |

**P0/P1：不存在。**

---

## 九、最终明确回答（A–F）

**A. 哪些部分已机器实测？**
- 9 个必跑套件 **528 项**全绿（含真实 Qt offscreen QML 引擎 25 项）；
- QA-A **真实无头浏览器** 8 组 GUI 断言 + **真实 HTTP** 22 项 API 流程；
- QA-B **真实 QML 组件**（`SystemOptionsTab.qml`）+ **真实断开处理器** + **真实错误映射** 29 项；
- QA-C 探针**真实回环拨号** 11 项 + 门禁/凭据 11 项 + 阶梯/自证伪 5 项 + 列表端点 7 项；
- QA-D **真实接口** A/B 隔离 23 项 + 客户端 Tina 路由 8 项；
- QA-E 全量 diff 程序化核对 15 项；冻结六文件 sha256 复算比对。

**B. 哪些部分只是代码审查？**
- QA-E 中“设计意图”类判断（研发验收用的单部署令牌模型、正式多学生授权需独立身份体系）基于代码+文档审阅，非运行验证；
- 探针的**时长/次数配额**为审查结论（当前无配额，属后续授权门，P3 级已知边界）；
- `provider_realtime_binding` 的端点形状约束（`.maas.aliyuncs.com` + `<workspace>.<region>`）为代码审查（未对真实云端地址发起解析/连接）。

**C. 哪些测试未能执行？**
- **真实 DashScope/Qwen 调用**（任务书禁止）→ `REALTIME_SAFE_REAL_EVIDENCE=PENDING`；
- **NAS/生产访问**（任务书禁止）→ `NAS_CHANGED` 仅能作“提交内容无 NAS 痕迹”的限度证明；
- **Mac 客户端完整桌面窗口级鼠标点击链路**（offscreen 引擎无法替代真实窗口管理器事件）→ 已用组件级真实实例化 + 真实方法覆盖同一代码路径，**不伪报为全 GUI**；
- **真人音频测试**（`HUMAN_TEST=PENDING`，须 PO 在场授权）。

**D. 是否存在 P0/P1/P2？** —— **无 P0、无 P1；存在 1 个 P2（P2-1：老师选择框不显示所选名称）**，另有 3 个 P3。

**E. 是否允许进入普通用户人工点击验收？** —— **有条件允许（建议先修 P2-1）**。机器模拟层面：登录/凭据/证据/授权位/确认弹窗全部 fail-closed 且经真实栈实证；冻结链路逐字节不变、Tina 默认路由不变；凭据/上下文隔离全绿。但 QA-B 的“显示老师名称”一项**实测不通过**，属本轮受审功能内的用户可见缺陷，人工点击验收时**必然被观察到**。建议：**先按 P2-1 单行修复并回归 QA-B，再进入人工验收**；若 PO 决定先行验收，应把 P2-1 作为**已知问题**带入清单，避免误判为“新发现”。

**F. 是否允许真实付费模型测试？** —— **本轮不允许**（与任务书默认一致）。前置条件未变：PO 按指南完成 P1（业务空间+绑定地址）、P2（独立 API Key）、P3（隔离登记批准）、P4（真实连接窗口+用量告警），且 `MODEL_REALTIME_PROBE_AUTHORIZED` / `MODEL_TEST_AUTHORIZED` / `MODEL_PROMOTE_AUTHORIZED` 保持默认关闭直至 PO 显式授权。

---

## 十、合规声明

- 产品代码**零修改**；未执行 `git reset/stash/clean`；未打标签、未推送。
- 全部临时物在 `/tmp/r32c_qa/`（12 个审计脚本 + 日志 + 隔离 venv 夹具），未进入工程目录；自证伪仅修改 `/tmp` 下的 gating **副本**，工程文件哈希不变。
- 全部网络请求仅 `127.0.0.1`（本地 Mock / 隔离后台 / loopback 上游）；**零真实云端调用、零付费、零真实 Key**（凭据全为 QA 模拟值）。
- 未访问 NAS；未读取 `secrets/` 真实素材；未修改真实客户端配置（Qt 测试经 `XIAOZHI_DATA_DIR` 隔离）；数字人未提交文件全程只读未触碰。

**审计完成。本窗口到此停止，等待产品负责人裁决。**
