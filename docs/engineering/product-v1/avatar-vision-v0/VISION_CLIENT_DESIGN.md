# VISION_CLIENT_DESIGN — Mac 客户端（py-xiaozhi）V0 视觉 UX 设计

- 基线：branch `admin-visual-v2` @ `e51d9a5`
- 编制：v0-mac-ux（只读审计 + 设计；本文为唯一写入物）
- 关联交付物：`VISION_PROTOCOL_REPORT.md`（v0-protocol）、`VISION_V0_TEST_PLAN.md`（v0-qa-planner）、`VISION_SECURITY_REVIEW.md`（v0-security）

---

## CLIENT_AUDIT（client/ 审计，file:line）

**技术栈与入口**

- 主入口 `client/main.py`：argparse 选 mode（gui/cli/tui/gpio）与 protocol（mqtt/websocket，默认 websocket）→ `ServiceContainer`（`client/main.py:108-124`、`client/main.py:123`）。
- GUI = **PySide6 + QML + qasync**（`client/main.py:16-20` 强制 QT_API=pyside6；`client/main.py:159-185` 建 qasync 事件循环）。依赖：`client/pyproject.toml:27`（`opencv-python-headless>=4.9.0`）、`client/pyproject.toml:65`（`PySide6>=6.6.0`）。
- 插件化装配：`client/src/bootstrap/container.py` + 插件（`client/src/plugins/base.py`），优先级：audio=10（`client/src/plugins/audio.py:25`）、mcp=20（`client/src/plugins/mcp.py:21`）。

**已有 GUI（QML）**

- `client/src/ui/gui/manager.py:17` GuiViewManager → `MainWindowController`（`client/src/ui/gui/main_controller.py`）；窗口：`client/src/ui/gui/qml/windows/MainWindow.qml`、`SettingsWindow.qml`；面板：`ChatPanel.qml`/`ControlPanel.qml`/`EmotionPanel.qml`（`client/src/ui/gui/qml/panels/`）。
- **设置页已有 CameraTab**：`client/src/ui/gui/qml/windows/settings/CameraTab.qml`（设备下拉 cameraCombo:81、刷新按钮:91、VL 配置字段:263-297）；模型层 `client/src/ui/gui/models/settings/camera_devices.py`、`camera_options.py`。

**已有摄像头/视觉栈（重要：V0 大量复用，不必新造）**

- 采集后端统一层 `client/src/mcp/tools/camera/capture_backend.py`：
  - `CaptureConfig`（:27-37，来自 `CAMERA.*` 配置），`load_capture_config()`（:50-85）。
  - `capture_jpeg()`（:287-316）：**每次采集临时开 VideoCapture → 读帧 → 编 JPEG → finally release（:216-220）**，整段跑在单 worker 线程池，12s 超时保护（:23, :307-316）。auto 后端 = OpenCV 失败回退 picamera2（:298-305）。
  - `list_camera_devices()`（:333-433）供设置页枚举（CameraTab 已消费）。
- 相机抽象 `client/src/mcp/tools/camera/base_camera.py`：`BaseCamera.capture_frame()`（:33-57）调用 capture_backend；`analyze(question, image_data)` 抽象接口（:76-82），已支持外部图像字节。
- 两个实现：
  - `client/src/mcp/tools/camera/vl_camera.py:19` **VLCamera**：OpenAI 兼容 HTTP 直连 GLM-4v（:32-41，`CAMERA.Local_VL_url` + `CAMERA.VLapi_key`），base64 JPEG，流式收集结果（:85-101）。
  - `client/src/mcp/tools/camera/normal_camera.py:17` NormalCamera：HTTP 上传 `explain_url`（:45-97）。
- MCP 工具 `take_photo`：`client/src/mcp/tools/camera/register.py:34-72`（`asyncio.to_thread(camera.capture)` → `analyze`）。
- 截图工具 `client/src/mcp/tools/screenshot/screenshot_camera.py`：`analyze(question, image_data)`（:420-438）已演示"外部图像字节 → VL"路径。
- 工厂与装配：`create_camera()`（`register.py:17-31`，VL key+url 齐全则 VLCamera，否则 NormalCamera）；`client/src/plugins/mcp.py:49-55` 在 McpPlugin.setup 懒创建并注入 McpServer（`client/src/mcp/mcp_server.py:37` set_camera）。
- **注意**：在本仓库 gateway 下，MCP 往返不生效——gateway 只认 hello/listen/abort/二进制音频（`gateway/app/turns.py:494-508`，未知类型忽略 :507-508）。即 `take_photo` 的 MCP 结果今天到不了 Tina 的语音回合。

**协议客户端（client ↔ gateway:28310）**

- `client/src/protocols/protocol.py`：基类回调 + 消息方法 `send_text`(:76)、`send_audio`(:82)、`send_start_listening`(:127)、`send_stop_listening`(:144)、`send_mcp_message`(:210)。
- `client/src/protocols/websocket_protocol.py`：连接（:47-91，`SYSTEM_OPTIONS.NETWORK.WEBSOCKET_URL` + Bearer token/Device-Id/Client-Id 头 :40-45）、hello 握手（:99-118）、`send_audio`(:256)、`send_text`(:279)、`max_size=10MB`(:75)。
- 配置默认值：`client/src/utils/config_manager.py:91-105`（CAMERA 段：index/device/backend/640x480/warm_up/VL url/key/model，**VLapi_key 默认空**）。

**gateway 客户端协议面（接收侧约束）**

- 入站仅 `hello` / `listen`(start/stop/detect) / `abort`（`gateway/app/turns.py:501-508`）；二进制帧一律当作 opus 音频解码（`gateway/app/turns.py:510-524`）。
- JSON 文本帧硬上限 **65536 字节**（`gateway/app/protocol.py:6` MAX_JSON_BYTES）→ base64 图像（≥253KB）**不可能**走现有文本帧。
- HTTP 面仅有 `/health`、diag 三个、`/xiaozhi/ota/`（`gateway/app/http.py:13-40`），均为加法式扩展点。
- 回程：`transcript` 事件（user/assistant 文本，`gateway/app/protocol.py:55-68`）+ `tts` 状态 + 音频。

## PERMISSION_MECHANICS（macOS 摄像头权限：最少侵入方案）

- opencv 的 macOS VideoCapture 走 **AVFoundation**（cap.AVFOUNDATION）。首次 `cv2.VideoCapture(0)` 会触发 macOS TCC 摄像头弹窗；权限归属"responsible process"：
  - 开发态（uv/python 直跑）：权限记到宿主 App（Terminal/iTerm/VS Code）——一次授权后该终端一直有效。
  - 打包态（PyInstaller，`client/py-xiaozhi.spec` 打成 .app）：Info.plist 必须含 **NSCameraUsageDescription**，否则首次访问直接 SIGABRT（无弹窗）。
- opencv-python-headless 去掉的是 GUI 模块，**videoio 保留**，采集/枚举不受影响。
- 隐性触发点：`list_camera_devices()`（capture_backend.py:380-417）逐个打开 index 0-5 并读帧 → **用户没开视觉时绝不可调用**，否则设置页一开就弹权限框/亮绿灯。现有 CameraTab 的"刷新设备"按钮即有此行为，V0 文案需注明"扫描摄像头会触发系统授权"。
- **结论（最少侵入）**：不加 pyobjc/AVFoundation 绑定、不引 QtMultimedia 新依赖，直接复用 opencv 采集路径（与 Pi/桌面上游一致）；仅两条附带事项：①打包 spec 增 NSCameraUsageDescription；②GUI 内首次成功开摄像头后写一次配置标记 `CAMERA.permission_state`，用于"权限被拒"分支的 UI 判断（结合 C1 测试分支）。pyobjc 探测授权状态（AVCaptureDevice.authorizationStatus）列为 V1 可选增强，V0 以"尝试打开失败 + 系统拒绝"推断即可。

## UX_FLOW（V0 交互流程）

**总开关：`VISION.ENABLED`，默认 `false`（config_manager DEFAULT_CONFIG 新段；不加新依赖、不影响旧配置）**

1. **关闭态（默认）**：主窗口不出现任何视觉入口；不 import cv2 相关视觉模块、不枚举摄像头、不触发系统弹窗。
2. **开启**：设置 → CameraTab 顶部新增"视觉（V0）"开关。开启后主窗口 ControlPanel 出现"视觉"按钮。
3. **点击开启预览** → 首次触发系统权限弹窗（AVFoundation）：
   - 允许 → 预览窗口（QML Popup，约 480×360）；
   - 拒绝 → 预览窗口显示状态文案"摄像头权限被拒（系统设置 → 隐私与安全性 → 摄像头）"，"让小智看看"按钮禁用；**不重试、不循环弹窗**。
4. **预览窗口**：QML `VideoOutput` 画面（经 QQuickImageProvider，~5fps 取流）+ 状态指示（绿=预览中 / 灰=关闭 / 黄=识别中）+ "让小智看看"按钮 + "停止"按钮（关闭预览并释放摄像头）+ 设备下拉（复用 CameraTab 的 camera_devices 模型）。
5. **"让小智看看"** → 冻结当前帧（预览暂停在最后帧）→ 按钮转"识别中…"（黄）→ 压缩 → 提交。
6. **提交路径（推荐）**：HTTP `POST /xiaozhi/vision/`（gateway http.py 加法式端点）→ gateway 调 `qwen.send_image()`（按 VISION_PROTOCOL_REPORT：`input_image_buffer.append`，同会话）→ 图像进入与音频**同一个 Qwen realtime 会话** → 用户继续语音问"这是什么" → **Tina 语音回答**（response.audio 路径零改动）。
   - 推荐理由：a) gateway 文本帧 64KB 上限（protocol.py:6）排除了 WS JSON 带 base64；b) 二进制帧被 gateway 固定当作 opus（turns.py:510），改二进制语义必然触碰冻结音频路径；c) http.py 是加法式非冻结文件，符合 QA D4 冻结审计；d) 图像与音频同会话 ⇒ Tina 能"看见并说"，无需客户端本地 TTS（客户端无 TTS 引擎）。
   - 备选回退（协议报告 4 条， proven in-repo）：VLCamera 直连 GLM-4v 拿文本，经文本平面注入会话（`conversation.item.create`）。V0 只做推荐路径，回退路径仅记录不实现。
7. **回答**：transcript（assistant）进 ChatPanel + Tina 语音播放；识别完成后预览恢复，状态回绿。
8. **关闭**：关预览窗口 / 关开关 → 释放摄像头 → UI 回到关闭态。

## AUDIO_LOOP_ISOLATION（与现有音频循环的关系证明）

**不得修改边界（音频面文件清单）**：

- `client/src/plugins/audio.py`（AudioPlugin：采集回调 `_on_encoded_audio`:223、发送 `_send_audio_async`:234、TTS 播放 `on_incoming_audio`:168、音乐暂停/恢复:178-203）
- `client/src/audio_codecs/` 全部：`audio_codec.py`（PortAudio 流 + Opus 编解码）、`opus_codec.py`、`audio_buffer.py`、`audio_converter.py`、`stream_manager.py`
- `client/src/audio_processing/` 全部：`aec_engine.py`、`wake_word_detect.py`
- `client/src/protocols/` 全部（尤其 `websocket_protocol.py:256` send_audio）
- `client/src/core/`（state_manager/task_manager/event_bus/resource_pool）——只读复用

**隔离论证**：

1. 视觉采集跑在**独立线程**：capture_backend 已将整次采集放单 worker 线程池 + 12s 超时（capture_backend.py:307-316）；预览取流同样放独立 grabber 线程。音频捕获在 PortAudio 回调线程（audio_codec 内部），二者无共享状态、无公共锁。
2. 视觉提交走 **HTTP 连接**（aiohttp/requests 独立 socket），与音频 WS（websocket_protocol）无共享连接、无共享队列。
3. 图像进入语音回合发生在 **gateway 内部**（qwen.send_image 注入同一 realtime 会话），客户端侧音频收发路径零改动。
4. 全部视觉代码收敛在**新模块** `client/src/vision/`（一个 plugin + 一个 QML panel + 一个 controller），插件模式与 McpPlugin 同构（plugins/mcp.py 结构）；对 audio 插件**零 import、零修改**。唯一的耦合点是 EventBus 订阅连接状态（只读监听 `on_connection_state_changed`），失败降级不写入音频状态。
5. 崩溃隔离：vision 模块顶层 try/except 包裹（同 plugins/mcp.py:46-59 的"注册失败不拖垮启动"模式），vision 异常不进音频插件调用栈。

## COMPRESSION_SPEC（压缩规格）

- 输入：预览线程当前 BGR 帧（或 capture_jpeg 输出）。
- 步骤：①最长边缩放到 **≤1280px**（INTER_AREA，复用 `_encode_bgr_jpeg` 的缩放逻辑，capture_backend.py:136-142）；②`cv2.imencode('.jpg', quality=85)`；③若 >190KB，按 quality 85→80→75→70→60 迭代；④仍 >190KB 则再降分辨率 1024→854→720px 重复。
- 上限取 **190KB 而非 300KB**：Qwen 文档要求 base64 后 ≤256KB、原始图建议 ≤190KB（VISION_PROTOCOL_REPORT SIZE_FPS_LIMITS）；190KB → base64 ≈253KB，贴近 256KB 红线，故客户端以 190KB 收口（任务书 300KB 与协议报告冲突，从协议报告，QA 侧 A1-b/C4 亦按协议报告口径）。
- EXIF：解码后重编码天然剥离全部元数据（opencv imencode 不携带 EXIF）；规格上显式断言"输出无可解析 EXIF"（对应 A1-b）。
- 输出：单帧 JPEG，分辨率 ≤1280px，≤190KB，无 EXIF。加密传输由 HTTPS/网关承担，客户端不落盘、不写临时文件（全部内存字节）。

## RESOURCE_LIFECYCLE（资源释放）

- **摄像头句柄**：沿用"用完即释"哲学——单帧抓取本就 per-call 开/关（capture_backend.py:216-220 finally release）。V0 预览持有一个长生命周期 VideoCapture：由 VisionPreviewController 独占持有，规则：①预览窗口打开才创建；②同一时刻至多一个（重复开启先释放旧句柄，对应 C2）；③"停止"按钮/关窗/断线/退出四条路径都调用 `stop()` → `cap.release()` + 置 None；④graber 线程以 `threading.Event` 停止标志退出，release 后不再读帧。
- **预览窗口**：QML Popup destroy 时向 controller 发 stop；controller 持 QQuickImageProvider 弱引用，最后一批 QImage 释放引用即回收（PySide6 QQuickImageProvider 持图仅 last-frame，单帧 ~640×480×3 ≈ 0.9MB，有界）。
- **内存**：压缩全程内存字节，不落盘；提交后 buf 引用置 None；VL/HTTP 响应文本只留最后一轮（对应 D2 有界性）。
- **断开/退出清理**：VisionPlugin `register_resources(pool)` 注册清理函数（模式同 plugins/mcp.py:79-94）→ ResourcePool 关闭序列执行：停 grabber、release 摄像头、取消在途 HTTP 请求（防 D2 句柄泄漏）。进程退出主路径：TaskManager.request_shutdown（main.py:188-207）已串联资源池。
- **绿灯指示**：release 成功后状态回灰；macOS 摄像头指示灯熄灭可作为人工验收点（QA MANUAL_GATES）。

## DEGRADATION（失败降级）

| 场景 | 行为 | 语音影响 |
|---|---|---|
| 权限拒绝/未决定 | 预览区显示引导文案，"让小智看看"禁用；不重试、不弹循环窗；写 `CAMERA.permission_state=denied` | 无 |
| 无摄像头/打开失败 | 状态"未找到可用摄像头"，capture_jpeg 返回 None（capture_backend.py:180-182 已有），UI 提示 | 无 |
| 采集超时 | 12s 超时返回 None（capture_backend.py:310-316 已有），预览显示超时提示，预览可手动停止 | 无 |
| 压缩失败/超限 | 本地提示"图片处理失败"，不提交任何网络请求（对应 C3 零调用断言） | 无 |
| 提交 HTTP 失败/超时 | 按钮"识别中"→ 恢复可点，预览继续；错误仅记日志 + UI 一次性提示；**无重试风暴**（≤1 次自动重试或不重试） | 无 |
| gateway vision 端点不存在（旧网关） | 404 → 同上静默降级 | 无 |
| 预览线程异常死亡 | controller 捕获后置状态"预览已停止"，可手动重启预览 | 无 |

核心保证：**所有失败路径都不触碰音频插件的任何函数**；用户随时可继续正常语音对话（说话→ASR→Tina 回复）。vision 会话期间 gateway 侧若 response 进行中则拒收图像（协议报告：仅无 response 在飞时发送），客户端收到拒绝同样静默降级。

## CARRIER_RECOMMENDATION（实现载体建议）

**推荐：client/ 内独立可选模块 `client/src/vision/`（plugin + QML panel + controller），特性开关 `VISION.ENABLED` 默认 false。**

- 结构：`client/src/vision/plugin.py`（VisionPlugin，模仿 plugins/mcp.py 骨架）、`client/src/vision/preview.py`（grabber 线程 + QQuickImageProvider）、`client/src/vision/submit.py`（压缩 + HTTP 提交）、`client/src/ui/gui/qml/panels/VisionPanel.qml`、ControlPanel/SettingsWindow 各加一个入口。
- 改动面（估算）：全新文件 ~5 个 + 触点 4 处（config_manager 加 VISION 段、container/plugin_wiring 注册插件、ControlPanel.qml 加按钮、SettingsWindow/CameraTab 加开关）。全部为**加法式**，可回滚性 = revert 这 9 个文件，音频面零文件进入 diff（D4 审计自然通过）。
- 风险：中低。最大风险点是 QML 触点与 qasync 线程交互（grabber 线程 → QML 图像更新须走 signals，不得直接操作 UI）；采集层零新逻辑（复用 capture_backend）。
- **权衡对比——独立本地工具页（如 web 页/独立 app）**：改动面更小、完全不碰 client，但：①无法复用客户端的 Device-Id/token 与连接状态；②用户要在两个窗口间切换，体验割裂；③后续 V1（自动感知、数字人同屏）必须迁移回 client。V0 验证期可用它做技术验证，但不作为交付形态。
- **权衡——直接扩 MCP take_photo + VL 直连**：零 gateway 改动，但今天 gateway 忽略 MCP（turns.py:507），且 VL 直连答案无法从 Tina 嘴里说出（无客户端 TTS），不符合"小智语音回答"验收。仅作协议报告记录的回退路径。

## V0_NON_GOALS（V0 不做的事）

1. 连续视频流 / 实时推帧（Qwen 建议 1fps 的流式图像不在 V0；V0 只单帧）。
2. 自动上传（任何无用户点击触发的抓拍/上传；无定时器抓帧）。
3. 后台抓拍（预览关闭/窗口最小化/应用后台时不采帧）。
4. 服务端/云端发起的视觉请求（一切由用户点击驱动）。
5. 图像本地持久化（不落盘、不写相册、不进日志——日志只记 size/mime 元数据，呼应安全评审）。
6. 多图、图库选图、屏幕截图复用进 vision（screenshot 工具保持现状独立）。
7. 数字人/嘴型（归 AVATAR 线，本设计不含）。
8. pyobjc 权限状态探测、QtMultimedia、新原生依赖。

## VERDICT

**可行，低风险，强烈建议按上述载体实施。** 关键事实：客户端已具备完整采集层（capture_backend）与设置页相机 UI（CameraTab），V0 新增的只有"预览 + 一个按钮 + 压缩收口 + HTTP 提交"；提交路径唯一可行解是 gateway 加法式 HTTP 端点转 qwen.send_image（WS 文本帧 64KB 上限与二进制=opus 的既定语义排除了另外两条路）；图像与音频同会话 ⇒ Tina 语音回答零额外机制。音频隔离由"新模块 + 独立线程 + 独立连接 + 加法式 diff"四重保证，与 QA 的 D4/D5 冻结审计兼容。唯一需要在实施前敲定的跨团队依赖：gateway 侧 `POST /xiaozhi/vision/` 端点与 `qwen.send_image()` 的实现（协议报告已给出 doc-verified 规格与 MOCK 边界）。
