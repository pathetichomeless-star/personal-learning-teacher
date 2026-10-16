# V06_SEC_QA_REQUIREMENTS — V0.6 Mac 原生客户端集成的安全与 QA 需求

- date=2026-10-09 / head=f518778（branch `avatar-vision-v06-mac-native`）
- 编制：v06-sec-qa（只读安全/QA；本文为唯一写入物）
- 继承：`VISION_SECURITY_REVIEW.md`（V0 R1-R10）+ `V05_SECURITY_QA_TEST_DESIGN.md`（V05-R1..R10 + Layer E 17 例）+ `V0_QA_EXECUTION.md`（T-case 判定）——全部条款继续生效
- 目标面：V0.6 把视觉切片落到 **Mac 原生客户端**（`client/src/vision/`，PySide6/QML），经既有网关端点 `POST /xiaozhi/vision/` 提交。基线事实：客户端 `client/src/vision/` 尚不存在（本轮新增）；网关端点已存在且 V05 复审 PASS（`gateway/app/http.py:47-99`）。

---

## REQUIREMENTS（V06-R1..R8，编号可测）

### V06-R1 vision token 隔离：独立密钥、仅走传输头、零泄漏面
- **存储位置**：客户端持有的 vision token 只允许存放在**客户端配置层**——`client/src/utils/config_manager.py` 的配置体系（读取走 `get_config` :398-409，写入走 `update_config` :411-441）；实现时优先级：环境变量/本地 secret 文件 > 配置文件字段（如 `VISION.TOKEN`），且该字段默认空。
- **禁止位置（硬性）**：① 任何 `.qml` 文件（QML 属性/绑定对进程内任意字符串插桩可见，且随资源打包扩散）；② 任何 Git 跟踪文件（`git grep` 不得命中 token 值；参照 `secrets/` 目录的仓库外存放模式）；③ 日志（客户端沿用"只记 size/结果"约定，V0 R5）；④ 截图/预览帧/UI 文案。违者任一命中即缺陷。
- **传输形态**：token **只**出现在 HTTP 头 `X-Vision-Token`（网关侧唯一读取点 `gateway/app/http.py:65`，恒时比较 + fail-closed :67-69）；**禁止** URL/query/body 明文字段携带。**禁止**复用 admin token 或 WS Bearer token 顶替（V05-R1 继承；V05_FINAL_REVIEW 已证网关侧无 admin 回退路径，客户端侧不得主动构造此类头）。
- 测试锚点：客户端单测断言请求构造函数只设置 `X-Vision-Token` 头、URL 无 token 参数；`git grep` + 日志 grep 零命中（E6-a 模式继承）。

### V06-R2 摄像头：默认关、显式同意流、复用 capture_backend、资源无泄漏
- **默认 OFF**：`VISION.ENABLED=false`（config_manager DEFAULT_CONFIG 加法式新段，V0.5 审计口径）——关闭态不 import cv2 视觉模块、不枚举设备（`list_camera_devices` :333-433 逐个开 index 0-5，VISION_CLIENT_DESIGN 已标注隐性触发 TCC 弹窗，关闭态绝不可调用）、不出现视觉 UI。
- **显式同意流**：预览开启 = 用户显式点击；首次触发 macOS TCC 弹窗（AVFoundation 路径，VISION_CLIENT_DESIGN PERMISSION_MECHANICS）。打包态（PyInstaller .app）`py-xiaozhi.spec` 必须含 `NSCameraUsageDescription`，否则 SIGABRT 无弹窗。拒绝后不重试、不循环弹窗。
- **采集复用**：单帧采集走既有 `capture_backend.capture_jpeg`（:287-316）——12s 超时（`_CAPTURE_TIMEOUT_S` :23）+ finally release（:216-220）。预览长持有句柄规则（VISION_CLIENT_DESIGN RESOURCE_LIFECYCLE）：同一时刻至多一个 VideoCapture，重复开启先释放旧句柄；停止/关窗/断线/退出四条路径全部调用 `stop()`。
- **重复开合资源审计**：≥50 次"开预览→关预览"循环后，进程句柄数与摄像头占用无持续增长（lsof / psutil 采样，D2 模式）；macOS 摄像头绿灯在关闭后熄灭（manual 项）。
- 测试锚点：句柄循环断言可自动化（module 级起 controller，不起 QML）；TCC 弹窗为 manual。

### V06-R3 权限拒绝 → 纯语音降级
- 权限被拒/未决定：UI 显示引导文案（"系统设置→隐私与安全性→摄像头"），采集/提交按钮禁用，写 `CAMERA.permission_state`；**不隐藏重试、不阻塞**。
- 核心断言：该分支**不触碰音频插件任何函数**——语音回路（说话→ASR→TTS）照常可用（V0 R9 / V05-R9 继承，V05 E7 已证网关侧"拒绝后音频无恙"，客户端侧对应 module 级断言 vision 异常不进音频调用栈）。
- 测试锚点：权限分支逻辑 module 级可自动化（mock 权限层三分支）；真机 TCC 三分支 manual。

### V06-R4 图像处理：五条零容忍
1. **无显式动作不上传**：唯一触发源 = 用户点击"让小智看看"（或等价显式按钮）；无定时器/后台线程/预览帧自动上传；`take_photo` 语音触发与 VLCamera 直连旁路保持不装配（V0 审计硬条件 ① 继续成立，回归断言 `vl_camera.analyze` 零调用）。
2. **不跨会话复用**：已提交/已消费的帧立即丢弃（引用置 None），不进任何缓存/重试队列/后续会话（V0 R6 生命周期继承）。
3. **零落盘**：全链路内存字节；grep 无 `imwrite`/临时文件写入（V0 R5 已证现状，V0.6 新增代码不得引入）。
4. **图像内容零遥测**：不把图像字节或衍生内容喂给任何计数器/诊断/日志；日志只记 size/mime/结果（base_camera.py:54-56 先例；网关脱敏 qwen.py:79-81 不回传到客户端日志）。
5. **元数据剥离**：帧经 `cv2.imencode('.jpg')` 重编码（capture_backend.py:143 + compress 管线 1280px/q85 阶梯/≤190KB，VISION_CLIENT_DESIGN COMPRESSION_SPEC），输出无可解析 EXIF——A1-b/C4 断言对客户端压缩模块继续执行。
- 测试锚点：全部 module 级自动化（压缩函数单测 + 触发源审计 + grep 审计）。

### V06-R5 会话绑定：图像只进当前会话，多会话歧义显式拒绝
- 现状锚点：session_id 服务端 uuid4 生成（`gateway/app/protocol.py:9-10`）；V0.5 实现用模块级 `_ACTIVE_INSTANCES` 转发（qwen.py:466, 812-828），**未实现** design 要求的 session_id 解析（V05_FINAL_REVIEW deviation 1：多活动实例时的歧义未显式拒绝）。
- **V06 修复方向（与 V06_PROTOCOL_ARCHITECTURE 对齐）**：存在 >1 个 `_connected=True` 实例时，vision 提交必须**显式拒绝**（409 `ambiguous_session` 类，per GATEWAY_PROTOCOL_DESIGN.md:39-48, 83, 118 的设计原意），不得随机选实例、不得新建/落默认会话；单实例单设备部署现状下等价于"图像必然 rides 当前连接会话"。无活动连接 → 503 `not_connected`（已实现，http.py 状态表）。
- 图像派生文本以**数据身份**进 transcript（A5 注入断言继承）；禁止写 MEMORY/KNOWLEDGE/POLICY（main.py:36-39）。
- 测试锚点：双实例歧义用例（B 层可自动化：注册两个 connected 实例 → 提交 → 断言显式拒绝 + 零串图）；E5-a/b 继承。

### V06-R6 断开清理：断连即弃图，永不迟到投递
- **客户端侧**：连接断开/`hello_received` 失效时，所有 pending 图像缓冲（在途压缩、待提交队列）立即丢弃；重连后不重放任何旧图像事件（V05 E6-b 继承，落到 client/src/vision/ 的实际实现上）；发送前必须校验连接就绪（websocket_protocol.py:118 hello 置位前提，MAC_CLIENT_AUDIT WS_MESSAGE_SPEC）。
- **网关侧**：连接关闭路径丢弃该实例的 pending 图像（teardown 置 `_connected=False`，qwen.py:765-805）——并落实 V05_FINAL_REVIEW Finding-1 的一行修复：`_teardown` 中从 `_ACTIVE_INSTANCES` discard，消除 registry 引用泄漏（否则断开实例永久滞留集合）。
- 断连后到达的迟到的 `vision_result` 回包被客户端静默忽略，不进 transcript、不弹 UI。
- 测试锚点：识别在途时断开 → 重连 → 断言零重放、语音回合正常（B 层自动化）。

### V06-R7 回归闸门：冻结音频面 + 关闭态启动字节等价
- **套件清单（实施后全绿 + 前后逐项一致）**：
  1. `gateway/tests/vision_v0_tests.py`（13/13，V0_QA_EXECUTION 口径）
  2. `gateway/tests/v05_e2e_tests.py`（8/8）
  3. `node prototypes/tests/avatar_logic_tests.mjs`（16/16）+ `vision_logic_tests.mjs`（17/17）
  4. 三套回归基座：`admin_security_tests.py`(29) / `product_v1_integration.py`(33) / `behavior1_tests.py`(≥60)
- **diff 审计**：`git diff f518778..<实施HEAD>` 中 `gateway/app/audio.py`、`turns.py`、`protocol.py` 音频面、VAD/节奏模块**零字节改动**（D4 模式）；client 音频面 7+4+1 文件清单（MAC_CLIENT_AUDIT AUDIO_BOUNDARY）零 diff。
- **关闭态字节等价**：`VISION.ENABLED=false`（默认）时客户端启动路径与基线行为等价——不 import cv2/vision 模块、不枚举摄像头、不触发 TCC、不新增网络监听；网关侧 vision 路由存在但无客户端调用（启动期抓包/日志证明零 vision 请求）。可自动化断言：module import 审计 + 启动后 mock 网关 `/__log` 零 vision 事件。
- 任一失败 = 整轮 FAIL（V05 PASS_CRITERIA-2 硬门继承）。

### V06-R8 暴露面与 mock 边界不扩大（继承 V05-R7）
- 客户端提交仅指向网关既有 8111 平面端点；测试/预览辅助一律绑 `127.0.0.1:0`；无新增监听端口、无 CDN 外链；部署面绑定维持 compose LAN-only（deploy/product-sidecar/docker-compose.yml:24,49）。

---

## AUTOMATED_VS_MANUAL（客户端侧 13 项测试矩阵，无 GUI 可自动化 vs 必须 Mac 人工验收）

对应 V0 网关套件的 13 项守卫（V1…V9，vision_v0_tests）在 **Mac 客户端模块级**的可自动化判定：

| # | 项（客户端等价物） | 自动化（无 GUI，module 级） | 依据 |
|---|---|---|---|
| 1 | JPEG magic/类型校验（客户端压缩模块拒 PNG 改名/非法字节/空） | **yes** | 纯函数单测（vision_logic_tests 模式迁移到 client/src/vision/compress.py） |
| 2 | 尺寸/字节上限（1280px/190KB 本地拒绝，零网络请求） | **yes** | mock 日志零请求断言（C3/E2-a 模式） |
| 3 | 压缩质量阶梯与 EXIF 剥离 | **yes** | 固定 fixture 单测（C4/A1-b） |
| 4 | 限速器（间隔 ≥5s、≤6/min、超限禁用） | **yes** | 注入 fake clock 单测（V6a/V6b 客户端等价） |
| 5 | token 装载与请求构造（仅 X-Vision-Token 头、无 URL 泄漏、失败不发请求） | **yes** | 请求构造函数单测 + grep 审计（V06-R1 锚点） |
| 6 | 发送前提（未连接/hello 未置位 → 禁用不发送） | **yes** | websocket_protocol 状态 mock（B 层） |
| 7 | 失败降级（超时/拒绝 → 一次性提示、无重试风暴、音频无恙） | **yes** | module 级故障注入（A3/V7 客户端等价） |
| 8 | 断连弃图、零重放（V06-R6 客户端侧） | **yes** | 断开事件注入 + 队列断言（E6-b 模式） |
| 9 | 重复开合句柄无泄漏（V06-R2 审计） | **yes**（headless 起 controller，跳过 QML 渲染） | lsof/psutil 采样 |
| 10 | TCC 权限三分支真实弹窗 | **NO → manual** | 自动化环境无法弹系统框（C1 manual 部分） |
| 11 | 真实摄像头预览（真帧、真 fps、绿灯亮灭、对焦时序） | **NO → manual** | mock 帧不代表真实设备（C2 真机部分） |
| 12 | 打包态 .app 行为（NSCameraUsageDescription、签名后权限归属） | **NO → manual** | PyInstaller 产物仅真机可验 |
| 13 | 主观体验（预览流畅度、提交→回答延迟感受、语音+视觉并发听感） | **NO → manual** | 主观项（D1 真机采样 + 真人验收） |

**结论：13 项中 9 项可无 GUI 自动化（module/B 层），4 项（10-13）必须 Mac 真机人工验收**，人工项门禁方式沿 V05 MANUAL_GATES（截图留档 + 真机走查 + 真人验收，证据写 evidence/）。

---

## REGRESSION_GATE

`vision_v0_tests`(13) + `v05_e2e_tests`(8) + `avatar_logic_tests`(16) + `vision_logic_tests`(17) + 基座三套 `admin_security_tests`(29)/`product_v1_integration`(33)/`behavior1_tests`(≥60) 全绿前后一致；`git diff` 冻结音频面（gateway audio/turns/protocol 音频段 + client 音频 7+4+1 文件）零字节；`VISION.ENABLED=false` 启动等价断言（无 cv2 import/无设备枚举/零 vision 请求）。

## VERDICT

**feasible-with-conditions** —— 网关面已就绪且 V05 复审 PASS，V0.6 全部为客户端加法式改动，音频隔离四重保证可继承。放行硬条件：① V06-R1 token 三禁（QML/Git/日志）+ 仅传输头；② V06-R4 五条零容忍全过 grep/单测；③ V06-R5 多实例歧义显式拒绝落地（V05 deviation-1 修复）；④ V06-R6 网关 registry 一行修复 + 客户端断连弃图；⑤ V06-R7 全套回归绿 + 关闭态启动等价。任一缺失不得进入真机验收门禁。
