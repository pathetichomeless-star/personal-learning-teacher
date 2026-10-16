# V1_RELEASE_REPORT — Live2D 风格动漫英语老师 V1.0 开发版
分支 avatar-vision-v06-mac-native · commit 203b14c · 基线 f518778（V0.5/V0.6 双 PASS）
## 引擎决策
Live2D Cubism = 专有许可（收入门槛/AI 界面审查类目/WebView 摩擦）→ 按授权条款 7 采用合规备选：
QML Canvas 参数驱动分层 2D rig（Live2D 风格：头发/脸/眼/眉/腮红/嘴/服装分层 + 状态表情参数映射），
零专有依赖。three-vrm（MIT）= V2 升级路径。评估详见 V1_LIVE2D_LICENSE_EVALUATION.md。
## 交付清单（全部加法式）
qml_bridge.py（VisionBridge：五状态/口型包络/提交守卫/中文状态反馈）· plugins/vision.py（默认关闭）·
AvatarCanvas.qml（分层动漫教师 rig）· VisionPanel.qml（开关/状态/测试图提交/画布）·
触点×3（plugin_wiring/manager 注入/MainWindow Loader——bridge 缺席时 inactive，启动与冻结基线一致）。
## 验证
离屏 QML 冒烟：双组件零错误加载 ✓ · vision_v0 15/15 · v05_e2e 8/8 · product_v1 33/33 · 客户端模块 13/13 ·
逻辑层 33/33 · 音频冻结零 diff · 回滚：单 revert。
## 待人工验收（不得伪造通过）
真机 PySide6 GUI 启动 + 视觉面板操作 + TCC 摄像头三分支（V1.1）+ 主观口型自然度 +
真实 Qwen 单图识别（PO 授权）。真实 RMS 探针 = 冻结链路例外待批。
## 门禁状态
未部署 NAS · 未合并 main · 零真实 Qwen 调用 · 零计费 · Full Stack 未动。

---

## 链收敛（LIVING SECTION · 2026-10-13 PROJECT-DOC-MERGE-01 批 5 追加）

> **TASK_ID = AVATAR-VISION ｜ 本文件为数字人视觉链权威主文档**。链内 28 份 V0→V1 文档为**阶段演进证据**
> （设计/协议/安全/QA/验收各一，多属独立审计快照例外），正文逐字保留、不逐份合并；本节提供全历史单点。

### A. 链演进时间线

| 阶段 | 文档群 | 有效结论 |
|---|---|---|
| **V0 设计与协议** | VISION_CLIENT_DESIGN / VISION_PROTOCOL_REPORT / GATEWAY_PROTOCOL_DESIGN / VISION_SECURITY_REVIEW / VISION_V0_TEST_PLAN / AVATAR_ENGINE_RECOMMENDATION / AVATAR_AUDIO_SYNC_DESIGN / MAC_CLIENT_AUDIT | 视觉客户端与网关协议设计定稿；引擎选型评估；音画同步设计；安全评审 |
| **V0 验证** | V0_QA_EXECUTION / V0_SECURITY_VERIFICATION | QA 执行与安全验证（vision_v0 15/15 等） |
| **V0.5** | V05_FINAL_REVIEW / V05_SECURITY_QA_TEST_DESIGN | 阶段终审 + 安全 QA 测试设计（基线 f518778，V0.5/V0.6 双 PASS） |
| **V0.6 音画同步攻坚** | V06_AUDIO_AVATAR_SYNC_REPORT / V06_AUDIO_SYNC_BLOCKER_ANALYSIS / V06_PROTOCOL_ARCHITECTURE / V06_PROTOCOL_SECURITY_REVIEW / V06_MAC_INTEGRATION_REPORT / V06_MAC_UI_ASSEMBLY / V06_NATIVE_CLIENT_QA / V06_SEC_QA_REQUIREMENTS / V06_FINAL_REVIEW / V06_RELEASE_READINESS | 原生 Mac 客户端路线（分支 `avatar-vision-v06-mac-native`）；音画同步 blocker 分析；协议安全评审；发布就绪评审 |
| **V1.0 开发版（本文件）** | V1_LIVE2D_LICENSE_EVALUATION / V1_ENGINE_LICENSE_AUDIT_V2 / V1_CODE_SECURITY_RECHECK_6b3ba65 / V1_FINAL_REVIEW / V1_MAC_GUI_ACCEPTANCE / 本文件 | **引擎决策**：Live2D Cubism=专有许可（收入门槛/AI 界面审查类目/WebView 摩擦）→ 按授权条款 7 采用合规备选 **QML Canvas 参数驱动分层 2D rig**（零专有依赖；three-vrm MIT=V2 升级路径）；交付全部加法式（VisionBridge/plugins/vision.py 默认关闭/AvatarCanvas.qml/VisionPanel.qml + 3 触点，bridge 缺席时 inactive）；验证=vision_v0 15/15·v05_e2e 8/8·product_v1 33/33·客户端模块 13/13·逻辑层 33/33·音频冻结零 diff；回滚=单 revert |
| **V1 真机 GUI 验收（Agent D 独立）** | V1_MAC_GUI_ACCEPTANCE（HEAD `6b3ba65`） | **首轮不通过（开箱即崩）**：视觉插件 4 处接口错用致首次启动即崩 + 1 处 QML 名字遮蔽致视觉面板永久假死 → **本地最小修补 2 文件（未 commit）后完成验收**；数字人画布可渲染但**无任何基线动画**（10 秒 20 帧像素级零变化） |

### B. 验收与未完成状态（四类分列，单点口径 · 2026-10-13 补正）

**B-1 Agent 已完成的本地验证（开发方/独立 Agent 机器与真机验证，均非产品负责人验收）**
- 离屏 QML 冒烟与套件：vision_v0 15/15、v05_e2e 8/8、product_v1 33/33、客户端模块 13/13、逻辑层 33/33、音频冻结零 diff。
- Agent D 真机 GUI 验证（`V1_MAC_GUI_ACCEPTANCE.md`，HEAD `6b3ba65`）：**首轮不通过（开箱即崩：4 处接口错用 + 1 处 QML 名字遮蔽）→ 本地最小修补后通过**；画布可渲染但无基线动画（10 秒 20 帧像素级零变化）。

**B-2 修复后仍未提交的代码（受保护未提交集合的一部分）**
- Agent D 验收轮的最小修补 **2 个文件未 commit**（交团队复核）；与后续各轮持续核验 UNTOUCHED 的数字人受保护未提交文件（5 modified + 1 untracked）同属该集合。
- 门禁口径不变：未部署 NAS · 未合并 main · 零真实 Qwen 调用 · 零计费 · Full Stack 未动。

**B-3 产品负责人尚未验收的事项（「人工验收」= PO 层面，Agent 不得代行或代签）**
- V1 开发版整体的人工验收/签收：未执行（本链自 V1 交付起即标注「待人工验收（不得伪造通过）」，至今未获 PO 签收）。
- Classroom V2 链中数字人相关验收项（V2 正式验收门未关闭的一部分）。

**B-4 尚未完成验证的能力（须 PO 授权或后续版本，禁止宣称已验证）**
- TCC 摄像头三分支（V1.1 范围）；主观口型自然度评估；真实 Qwen 单图识别（真实付费调用须 PO 授权）；
  真实 RMS 探针（冻结链路例外，待批）；基线动画（当前画布无任何动画）。

> **口径声明**：B-1 的「GUI 验证通过」= Agent 在本机经最小修补后的技术验证；**不等于** B-3 的产品负责人验收，
> 也**不覆盖** B-4 的任何能力。四类不得混写：任何「已完成」表述仅指 B-1；「待执行」表述仅指 B-3/B-4。
>
> 补充事实：V1 开发版交付本身 = COMPLETED（全部加法式，单 revert 可回滚）；V4 生产已于 2026-10-10 部署 NAS
> （镜像 v4-repair-9df3587，见 PROJECT_WORKLOG 状态节）。

### C. 处置规则

- 本目录全部 28 份 MD = **阶段演进证据**：设计/协议/许可/安全类按审计快照例外保留；QA/验收类按独立证据例外保留。
- 后续 Agent 默认只读本文件（含本节）即可理解链全历史；需要逐轮细节时再按上表定位原始文档。
- 本链与 Classroom 链的接口：Classroom V1 仅提供**稳定容器**（静态占位回退，见 CLASSROOM_V1_TEST_REPORT §6.2/§6.3）；
  `AvatarAdapter` 等 V2 适配层为**新建文件**，不得改受保护未提交数字人文件（AGENT_PLAN §2 所有权矩阵）。

（链收敛完成于 2026-10-13，PROJECT-DOC-MERGE-01 批 5。）
