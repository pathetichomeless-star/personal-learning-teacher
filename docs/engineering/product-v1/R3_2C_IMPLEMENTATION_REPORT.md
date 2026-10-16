# R3-2C 实施报告 — 普通用户界面补全与 DashScope 验证通道

**分支** `p2b2-teacher-voice`　**检查点** `ee1b3ab`（19 文件，+~1100/−15）＋ 补丁提交（错误映射补齐）
**性质**：授权的最小开发轮；**MOCK 验证；零真实云端调用、零付费、零 NAS 交互**
**边界**：冻结六文件逐字节不变；数字人未提交文件（含 `manager.py`、`AvatarLive2D.qml`、`avatar_page.js` 等）零触碰。

---

## 一、最终状态字段

| 字段 | 结论 | 依据 |
|---|---|---|
| `R3_2C_GUI_SELECTION` | **PASS** | 设置窗「老师」区：下拉显示名称+音色、刷新、中文状态；名称→id 映射经 token 门禁列表端点 |
| `TEACHER_SWITCH` | **PASS** | 保存时结束旧会话并断开旧连接（`PROTOCOL_DISCONNECT_REQUEST`），**不自动重连** |
| `USER_VISIBLE_ERRORS` | **PASS** | 18+2 个服务端拒绝码全部映射中文（自验补齐 2 个漏码）；WS 路径与 GUI 状态均透传 |
| `TOKEN_PROTECTION` | **PASS** | 令牌由隔离配置预置；GUI 无该字段、无回显、无日志泄露（自验 grep）；列表/握手均令牌门禁 |
| `DASHSCOPE_PROBE_MOCK` | **PASS** | 新探针 23/23：Mock 上游正负向、授权门、凭据隔离、阶梯诚实 |
| `REALTIME_SAFE_REAL_EVIDENCE` | **PENDING** | 音频能力验证未实现（`audio=not_tested`）；真实拨号是后续授权门 |
| `INDEPENDENT_QA` | **NOT_COMPLETED（替代=总控自验）** | 独立 QA Agent 因平台额度 429 中断；总控按其任务书逐项自验并自证伪（见第四节）；**真人语音验收仍须独立 QA 复跑通过** |
| `REAL_MODEL_REQUESTS` | **ZERO** | 全程 Mock/回环 |
| `TINA_FROZEN` | **UNCHANGED** | 冻结六文件 sha256 与基线一致 |
| `DIGITAL_HUMAN_FILES` | **UNTOUCHED** | 工作树数字人改动与本轮前一致（manager.py +7 行等原样） |
| `NAS_CHANGED` | **NO** | 零 NAS 交互 |

---

## 二、交付内容（commit ee1b3ab + 补丁）

### A. Mac GUI 老师选择/切换（研发验收专用）

1. **老师列表端点**（`gateway/app/teacher_voice.py`）：`GET /xiaozhi/v1/teacher/list`，与老师 WS 同一恒时令牌鉴权；仅返回 enabled+非删除+非冻结+realtime 模式老师，白名单字段 `{teacher_id, display_name, voice_id, language}`；无令牌/错令牌同为 401（无枚举 oracle）；随 mount() fail-closed 挂载。
2. **设置窗「老师」区**（`SystemOptionsTab.qml`）：下拉显示**名称+音色**（用户不接触 teacher_id）、「刷新老师列表」、中文状态与提示；说明"部署令牌由隔离配置预置，无需填写，也不会显示"。
3. **切换语义**（对设计 Agent 方案的有意修正，理由已记录）：选择时告知"保存会结束当前通话"；**保存仅断开旧连接（新事件 `PROTOCOL_DISCONNECT_REQUEST`），绝不自动重连**——真实连接只由用户点「开始对话」建立（规则 6：保存不得悄悄触发计费连接）。同次保存含 MCP 变更时推迟其自动重连。
4. **错误提示**（`client/src/utils/teacher_errors.py` 共享映射）：WS 连接路径解析 `InvalidStatus`（仅老师路由生效）并映射中文；GUI 状态透传失败原因（修复了固定"未连接"丢弃详情的缺陷）；**不回显令牌**。

### B. DashScope 实时证据通道（诚实、Mock 验证）

1. **探针核心**（新 `gateway/app/admin/realtime_probe.py`）：拨号 → `session.created`（握手）→ `session.update`（纯配置消息，**无音频、无生成请求**）→ `session.updated`（会话兼容）；结果区分三阶段，`audio="not_tested"`、`verified` 恒 False；20 秒总限、必关连接。
2. **阶梯诚实扩展**：`EVIDENCE_LEVELS` 增 `realtime_handshake`（adapter_present 与 verified 之间）。自证伪证明：该序数被抬时拒绝码翻转（`evidence_missing` → `capability_mismatch`），E3 断言能捕捉此类绕过；握手成功**永不授予 realtime_safe**。
3. **独立授权位** `MODEL_REALTIME_PROBE_AUTHORIZED`（默认 "0"，四处接线与既有授权位同构）+ `confirm_realtime:true`；未授权 → 403 + 中文提示"实时握手验证需产品负责人独立授权（当前环境未开启）"。
4. **凭据隔离**：探针仅用服务商自有密封凭据（`creds.read_secret(current_ref(provider_id))`）；**无任何读取全局/Tina Key 的代码路径**；审计不含 URL/Key。
5. **对停用模型允许探针**（证据是启用的前置而非后果）；冻结模型/服务商先于拨号拒绝。
6. **admin UI**：能力页新列「实时握手验证（需授权）」+ 确认弹窗（可能计费/20 秒/无音频/后续门）+ 中文拒绝渲染；阶梯标签更新。

---

## 三、测试与证据

| 套件 | 结果 |
|---|---|
| `realtime_probe_tests.py`（新） | **23/23**（Mock 上游正负向、授权/确认门、凭据隔离 D1–D5、阶梯诚实 E1–E3、老师列表 F1–F6） |
| `teacher_voice_seam_tests`（R1） | 60/60 |
| `teacher_context_seam_tests`（R2） | 83/83 |
| `model_v4_tests`（R3-0） | 72/72 |
| `admin_v4_api_tests` | 107/107 |
| `teaching_v4_tests` / `voice_v4_tests` | 36/36 · 74/74 |
| 客户端 `test_client_ui_transcript` / `test_gui_transcript_live` | 48/48 · 25/25 |
| 客户端 9 个改动文件 | py_compile 通过 |
| 总控自证伪（E3 鉴别力） | 序数被抬 → 拒绝码翻转（`evidence_missing`→`capability_mismatch`）→ E3 可捕捉 ✔ |
| 自验补漏 | 客户端错误映射补齐 `teacher_voice_not_configured`、`provider_missing` 两漏码（程序化覆盖核对发现） |

---

## 四、独立 QA 替代说明（诚实声明）

原计划的独立 QA Agent（qaR32C）**因平台额度 429 中断，未能产出签收**（任务书：复跑 9 套件 + 代码级核验 + 自证伪）。本报告以**总控自验**替代：逐项执行了该任务书的可自动化部分（基线/哈希、19 文件清单、9 套件实跑、错误码程序化覆盖核对、E3 自证伪）；**凡属"独立第三方视角"的复核价值因此打了折扣，如实标注**。因此：

- `INDEPENDENT_QA` 字段如实记为 **NOT_COMPLETED（总控自验替代）**，而非 PASS；
- 依据前轮指令"必须通过独立 QA 后才允许真人语音验收"：`REAL_AUDIO_HUMAN_TEST` 保持 **PENDING**，真人验收前须在额度恢复后重跑独立 QA；
- QA 任务书全文保留于本报告附录指令（可直接复用重派）。

---

## 五、诚实边界与后续授权门

1. **研发验收专用**：GUI 选择器基于"单一部署令牌＝受信部署方"模型；**正式多学生授权选择未实现**（需按学生签发/吊销短时凭据与服务端作用域化可见性，属独立身份体系工程）。
2. **音频能力验证未实现**（`audio=not_tested`）：`verified`/`realtime_safe` 的真实取证需后续授权（真实握手探针或真实调用后如实写证，两案待 PO 决策，见 R3-2B 报告 P2-1）。
3. **真实拨号门**：`MODEL_REALTIME_PROBE_AUTHORIZED` 默认关；开启 + 确认 + 端点策略 + 服务商自有凭据 + 20 秒上限；时长/次数配额为后续授权门。
4. **Tina 路径不变**：无 TEACHER 键时 `_resolve_endpoint` 行为逐字节同旧；列表路由随 mount 门控不挂载。
5. 冻结 `QwenClient`/`BehaviorLink`/音频协议代码零改动；`manager.py` 及全部数字人文件零改动。
