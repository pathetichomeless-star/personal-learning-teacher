# MAC_CLIENT_AUDIT — Mac 客户端（py-xiaozhi）V0.5 视觉切片审计

- 基线：branch `avatar-vision-v0` @ `fec64a80`（docs: deploy-log #93 — ADMIN-VISUAL-V2 production release + VISION/AVATAR V0）
- 编制：v05-mac-client（只读审计；本文为唯一写入物）
- 范围：`client/`（py-xiaozhi Python 客户端）——明确 V0.5（图像选择 + 摄像头单帧 + "让小智看看" → WS 视觉消息）在不触碰音频路径的前提下的精确接入点
- 诚实声明：审计期间 shell/Glob 输出存在环境噪声，QML settings 子目录下个别文件名未能二次复核；所有 file:line 引用均来自已成功 Read 且行数经 `wc -l` 交叉验证的文件。未验证项在文中显式标注 `[未复核]`。

---

## CLIENT_AUDIT（客户端审计，file:line）

**技术栈与入口**

- 主入口 `client/main.py`（264 行）：argparse 选 mode（gui/cli/tui/gpio）与 protocol（mqtt/websocket，默认 websocket）→ `start_app()`（main.py:108-124）→ 激活流程 `handle_activation()`（main.py:76-105）→ `ServiceContainer`（bootstrap 容器，main.py:123-124）。
- GUI = **PySide6 + QML + qasync**：main.py:16-20 强制 `QSG_RHI_BACKEND=opengl`、`QT_API=pyside6`、`QT_QUICK_CONTROLS_STYLE=Basic`；GUI 模式建 `qasync.QEventLoop` + `QApplication`（main.py:159-185）；SIGINT 经 TaskManager 优雅关闭（main.py:188-207）。
- 插件/扩展机制：`client/src/plugins/`（`base.py`、`manager.py`、`audio.py`、`ui.py`、`mcp.py`、`wake_word.py`、`shortcuts/`、`ui_presenter.py`）——V0.5 视觉模块按同一插件骨架注册（优先级/生命周期细节见 base.py，本次未逐行复核 `[未复核]`）。
- QML 资源：`client/src/ui/gui/qml/`（`main.qml`、`panels/{ChatPanel,ControlPanel,EmotionPanel}.qml`、`windows/{MainWindow,SettingsWindow,ActivationWindow}.qml` + `windows/settings/` 设置页签目录）。设置页中相机相关页签的具体文件名 `[未复核]`（实现前以 SettingsWindow.qml 的页签装配代码为准）。

**WS 协议客户端（client ↔ gateway，默认端口 28310 由配置 `SYSTEM_OPTIONS.NETWORK.WEBSOCKET_URL` 决定）**

`client/src/protocols/websocket_protocol.py`（395 行，`WebsocketProtocol(Protocol)`）：

- 连接：`connect()` :47-140，`websockets.connect` 带 Bearer/Device-Id/Client-Id 头（:40-45），`max_size=10MB`（:75, :89）。
- **hello/auth 流**：连接成功即发客户端 hello（:100-114）：`{"type":"hello","version":1,"features":{"mcp":true},"transport":"websocket","audio_params":{opus…}}`，经 `send_text()` 发出；等待服务器 hello，`_handle_server_hello()` :349-372 校验 `transport=="websocket"`（:356）后置 `hello_received` 并回调 `_on_audio_channel_opened`。**hello 之后连接即进入自由 JSON 文本阶段**。
- **接收分发**：`_message_handler()` :199-254 —— 文本帧 `json.loads` 后：`type=="hello"` 走 `_handle_server_hello`，**其余一切 JSON 原样回调 `_on_incoming_json(data)`（:217-218）**；二进制帧一律回调 `_on_incoming_audio`（:221-224）。即客户端接收侧对未知 type 天然放行，新增 `vision_result` 类回包无需改协议层。
- **发送面**：`send_text(message)` :279-322 —— 任意 JSON 文本帧复用同一条 WS 连接（含关闭态守卫 :283-302 与关闭码 1000/1001/1005 判定）；`send_audio(data)` :256-277 仅走二进制。**`send_text()` 即 V0.5 视觉消息的唯一发送通道，零协议层改动**。
- 音频通道守卫：`is_audio_channel_opened()` :324-336 / `open_audio_channel()` :338-347。

**音频采集/播放线程（DO-NOT-TOUCH 边界，完整文件清单）**

- `client/src/audio_codecs/`（全部 7 文件）：`audio_buffer.py`、`audio_codec.py`、`audio_converter.py`、`music_decoder.py`、`opus_codec.py`、`rtl_client_telemetry.py`、`stream_manager.py`
- `client/src/audio_processing/`（全部）：`aec_engine.py`、`wake_word_detect.py`、`keyword_converters/`（`base.py`、`bpe_converter.py`、`pinyin_converter.py`、`__init__.py`）
- `client/src/plugins/audio.py`（音频插件装配）
- `websocket_protocol.py` 中的 `send_audio` :256-277 与 `_on_incoming_audio` 分支 :221-224（只读复用，禁改）

**既有相机资产（V0.5 大量复用，不新造）**

`client/src/mcp/tools/camera/capture_backend.py`（463 行）：

- `CaptureConfig` dataclass :27-37（camera_index/device/backend=auto|opencv|picamera2/640×480/warm_up_frames=5/jpeg_max_side）。
- `load_capture_config()` :50-85 从 ConfigManager 读 `CAMERA.*`。
- `_encode_bgr_jpeg()` :129-146：BGR→最长边缩放（INTER_AREA）→ `cv2.imencode(".jpg")`，**天然剥离 EXIF**。
- `capture_jpeg(cfg)` :287-316：**每次采集临时开 VideoCapture → 读帧（含预热）→ 编码 → finally release（:216-220）**；整段跑在单 worker `ThreadPoolExecutor`，超时 `_CAPTURE_TIMEOUT_S = 12.0`（:23, :307-316）。
- `list_camera_devices()` :333-433（Linux /dev/video* 优先 + OpenCV index 枚举 + picamera2 CSI，供设置页枚举）；`apply_device_selection()` :436-463。

`client/src/mcp/tools/camera/vl_camera.py`（106 行，**后续要旁路的 VL 直连**）：

- `VLCamera(BaseCamera)` :19：OpenAI 兼容 HTTP 直连 GLM-4v——`api_key=CAMERA.VLapi_key`（:33）、`base_url=CAMERA.Local_VL_url`（默认 `https://open.bigmodel.cn/api/paas/v4/`，:34-37）、`model=CAMERA.models`（默认 `glm-4v-plus`，:40）。
- `capture()` :43-47 → `capture_frame()`；`analyze(question, image_data)` :49-106：图像 base64 → `chat.completions.create`（stream）→ 本地文本。**该路径完全绕过 gateway，V0.5 后续关闭方式 = 不再装配 VLCamera（见 INTEGRATION_POINTS），文件本身保留只读**。

**配置**

`client/src/utils/config_manager.py`（500 行）：

- `DEFAULT_CONFIG` 字典 :64-194；现有 `CAMERA` 段 :91-105（camera_index/device/backend/frame/fps/warm_up/`Local_VL_url`/`VLapi_key`/`models`）。
- 读取 `get_config(path, default)` :398-409（点路径，缺键返回 default）；写入 `update_config(path, value, save=)` :411-441（中间节点自动补 dict）；批量 `update_configs` :443-459。
- 版本化迁移 `_migrate_config()` :285-342（按 CONFIG_VERSION 前向迁移，磁盘版本为准）。

---

## INTEGRATION_POINTS（V0.5 视觉模块精确接入点）

**新增文件（全部加法式，预计 ~5 个新文件 + 4 处触点）**

| 文件 | 内容 |
|---|---|
| `client/src/vision/__init__.py` | 模块出口；`VISION.ENABLED` false 时整体 no-op |
| `client/src/vision/controller.py` | VisionController：预览线程（独立 grabber 线程复用 capture_backend 的 OpenCV 路径）+ "让小智看看" 单帧冻结 + 压缩 + 经 `send_text` 提交 |
| `client/src/vision/compress.py` | JPEG 压缩收口（规格见 WS_MESSAGE_SPEC）：1280px→q85→按 85/80/75/70/60 降质迭代→仍超限降分辨率 |
| `client/src/plugins/vision.py` | 插件装配（骨架对齐 `src/plugins/base.py`/`manager.py`），优先级独立于 audio(10)/mcp(20) |
| `client/src/ui/gui/qml/panels/VisionPanel.qml` | 预览 + 按钮（QQuickImageProvider，~5fps 取流；预览关闭/窗口最小化不采帧） |

**触点（4 处）**

1. `config_manager.py` DEFAULT_CONFIG :64-194 追加 `"VISION": {"ENABLED": False}` 段（CONFIG 段 91-105 旁，纯加法）。
2. `src/plugins/manager.py` 注册 VisionPlugin（加法式；注册失败不拖垮启动，顶层 try/except 包裹）。
3. `SettingsWindow.qml` 装配处加一个"视觉（V0）"开关（绑定 `VISION.ENABLED`）。
4. GUI 入口：`VisionPanel` 由 `VISION.ENABLED` 门控，开关开启后才出现在 ControlPanel。

**发送路径（唯一）**：VisionController → `WebsocketProtocol.send_text(json.dumps({"type":"vision_image","image_b64":…}))`（websocket_protocol.py:279）→ 同一连接同一会话。回包经 `_on_incoming_json`（:217-218）→ `type=="vision_result"` → 更新 VisionPanel 状态 + 文本进对话/语音（TTS 由 gateway 侧既有路径承担，客户端零改动）。

**VL 旁路的关闭（V0.5 之后）**：移除 `vl_camera.py` 的装配调用（其注册/工厂点位于 mcp 工具注册链 `[未复核]`），`capture_backend.py` 与 `list_camera_devices()` 全量保留复用；设置页中 VL 专用字段（api_key/url/model）随开关隐藏。

---

## WS_MESSAGE_SPEC（client→gateway 视觉消息）

- 通道：既有 WS 文本帧（`send_text`，websocket_protocol.py:279-322），**禁止**二进制帧（二进制被固定当作 opus 音频，:221-224）。
- 方向：仅 client→gateway；发送前提：`connected==True` 且服务器 hello 已完成（即 `hello_received` 已置位，:118）。
- 形状（与 `{"type":"vision_image","image_b64":…}` 约定一致）：

```json
{
  "type": "vision_image",
  "image_b64": "<base64 JPEG，无 data: 前缀>",
  "source": "camera | picker",
  "session_id": "<可选，回显用>"
}
```

- 回包（gateway→client，经 `_on_incoming_json`）：

```json
{ "type": "vision_result", "ok": true, "text": "…", "session_id": "…" }
```

- 大小收口：gateway 文本帧硬上限 64KB（`MAX_JSON_BYTES=65536`，gateway 侧口径）。base64 膨胀 ≈ 4/3，故客户端压缩目标定为 **JPEG ≤ 48KB → b64 ≈ 64KB 内**，实际按 b64 后整帧消息 ≤ 60KB 留安全余量。压缩管线：最长边 1280px（INTER_AREA）→ `imencode(".jpg", q=85)` → 质量阶梯 85/80/75/70/60 → 仍超限则 1024→854→720px 重复。全程内存字节，不落盘。
- 失败语义：发送前连接未就绪→静默禁用按钮；发送后 10s 无 `vision_result`→UI 一次性提示"识别超时"，不自动重试（≤1 次手动重试）。

---

## AUDIO_BOUNDARY（音频面隔离论证）

1. 视觉采集：复用 `capture_backend.py` 的 per-call 线程池模型（:287-316，单 worker + 12s 超时）；预览另起独立 grabber 线程。与 PortAudio 回调线程（audio_codecs 内部）无共享状态、无公共锁。
2. 视觉提交走 **既有 WS 连接上的文本帧**（`send_text` :279），与 `send_audio` :256 的二进制音频共用一条 TCP 但帧类型隔离；不新增连接、不改音频帧的任何编码/时序。
3. 客户端音频收发路径**零文件改动**：`audio_codecs/` 7 文件、`audio_processing/` 全部、`plugins/audio.py`、`send_audio`/`_on_incoming_audio` 分支均只读。
4. 视觉模块异常隔离：VisionPlugin 顶层 try/except，注册/运行失败仅记日志并禁用视觉 UI，不进入音频插件调用栈，不影响说话→ASR→TTS 回路。

---

## CONFIG

- 新增段（DEFAULT_CONFIG :64-194 内追加，`CONFIG_VERSION` 不强制升级——`get_config` :398 对缺键返回 default，旧配置文件天然兼容）：

```json
"VISION": {
  "ENABLED": false,
  "COMMIT_MAX_B64_KB": 60,
  "PREVIEW_FPS": 5
}
```

- 若需要让"升级后默认仍关"在迁移链中显式可见，可在 `_migrate_config`（:285-342）追加一步 `config.setdefault("VISION", {"ENABLED": False})`（可选，非必需）。
- VL 关闭不删配置键：`CAMERA.VLapi_key/Local_VL_url/models`（:102-104）保留，仅停止装配 VLCamera。

---

## RISKS

| 风险 | 等级 | 缓解 |
|---|---|---|
| 64KB 文本帧上限与图像大小竞态 | 中 | 客户端按 ≤60KB 收口压缩；gateway 侧超限静默丢弃 + `vision_result{ok:false}` 回执（gw-protocol 侧职责，已对齐口径） |
| QML 文件名/装配点未逐行复核 | 低 | 实现前以 SettingsWindow.qml 页签装配代码为准；本审计已标注 `[未复核]` 项 |
| macOS 摄像头权限（TCC）弹窗时机 | 低 | 沿用 capture_backend 既有 OpenCV 打开路径；权限拒绝→预览区引导文案，按钮禁用，不循环弹窗 |
| 预览线程与 qasync 事件循环交互 | 中 | 预览帧经 QQuickImageProvider + signals 进 QML，grabber 线程不直接触碰 UI 对象 |
| VL 旁路残留导致双路径并存 | 低 | V0.5 装配处显式不注册 VLCamera；回归用例断言 `vl_camera.analyze` 零调用 |

---

## VERDICT

**可行，低风险，按上述载体实施。** 关键事实：①`WebsocketProtocol.send_text()`（websocket_protocol.py:279）即视觉消息唯一发送通道，协议层零改动，接收侧对未知 type 天然放行（:217-218）；②采集层 `capture_backend.py`（capture_jpeg :287-316 + 12s 超时 + EXIF 剥离）全量复用，压缩收口新增于 `vision/compress.py`；③音频面 7+4+1 个文件 + 2 个协议分支构成硬边界，V0.5 全部为加法式改动（~5 新文件 + 4 触点），可回滚 = revert 这些文件；④配置 `VISION.ENABLED` 默认 false，旧配置免迁移。唯一跨团队依赖：gateway 侧接受 `vision_image` type 并回 `vision_result`（gw-protocol 队友范围，本审计口径已对齐其 64KB 上限）。
