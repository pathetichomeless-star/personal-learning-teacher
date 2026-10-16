# V06_MAC_UI_ASSEMBLY — Mac 原生客户端（PySide6/QML）数字人 + 视觉 V0.6 最小改动装配方案

- 日期：2026-10-09 / 基线：branch `avatar-vision-v06-mac-native` @ `f518778`（`git rev-parse` 已确认）
- 编制：v06-mac-ui（只读审计 + 装配方案；本文为唯一写入物）
- 上游依据：`MAC_CLIENT_AUDIT.md`（V0.5 客户端审计）、`VISION_CLIENT_DESIGN.md`（UX/压缩规格）、`AVATAR_AUDIO_SYNC_DESIGN.md` + `V06_AUDIO_SYNC_BLOCKER_ANALYSIS.md`（包络方案）、`V05_SECURITY_QA_TEST_DESIGN.md`（X-Vision-Token 口径）
- 原则：全部加法式、默认关闭（`VISION.ENABLED=false`）、音频冻结链零触碰、单提交可整体 revert

---

## FRAMEWORK（GUI 框架事实与装配点，file:line）

**技术栈**：PySide6 + QML + qasync。`client/main.py:16-20` 强制 `QSG_RHI_BACKEND=opengl`/`QT_API=pyside6`/`QT_QUICK_CONTROLS_STYLE=Basic`；GUI 模式建 `qasync.QEventLoop` + `QApplication`（main.py:159-185）。

**QML 宿主与上下文注入（VisionBridge 的挂载机制）**
- `client/src/ui/gui/qml_host.py:44-76`：`QmlAppHost` 持 `QQmlApplicationEngine`；`inject_context()`（:58-64）经 `rootContext().setContextProperty()` 注入；`load_main()`（:66-76）加载 `qml/main.qml`。
- `client/src/ui/gui/manager.py:52-66`：`GuiViewManager.start()` 注入 4 个上下文属性 `eventBridge/mainModel/settingsModel/emotionService`（:53-60）后 `load_main()`。**新 `visionBridge` 属性在此处条件注入（触点 TP4）**。

**窗口/面板结构（4 个 UI 触点 + VisionPanel 的落点）**
- `qml/main.qml:8-23`：根 = `MainWindow`；`SettingsWindow` 经 `Loader` 延迟加载（active=false → 打开设置才实例化）。
- `qml/windows/MainWindow.qml`（349 行，`AppWindow` 420×520）：`TitleBar` :27-41 → 状态标签 :55-68 → **表情显示区 Item :70-95**（AnimatedImage/emoji，数字人显示区的替换落点）→ `ChatPanel` :99-103（会话双语气泡，`mainModel.transcriptItems`，**零改动**）→ legacy 单行 :107-126 → 按钮行 :131-338（手动/自动/打断/输入发送/模式/设置）。
- `qml/windows/SettingsWindow.qml:20-28`：`tabConfig` 数组（7 页签）+ `StackLayout` :132-158 实例化各 Tab；`qml/windows/settings/CameraTab.qml`（368 行）：设备下拉 :81-89、测试/刷新 :91-136、VL 配置 :238-310 —— **"视觉"开关加在 CameraTab 顶部**。
- `qml/panels/ChatPanel.qml:30`：`model: mainModel.transcriptItems`——识别结果文本由 gateway `transcript` 事件回注（E4 流），**客户端会话文本路径零改动**；识别状态显示在 VisionPanel 内。

**插件注册（plugins/vision.py 的注册点）**
- 骨架：`client/src/plugins/base.py:14`（`Plugin`：name/priority/requires，`setup/start/stop/on_incoming_json` 钩子）；`client/src/plugins/manager.py:34-49`（`register`，按 priority 排序）、:191-195（**setup 异常 → mark_failed，不拖垮启动**）。
- 装配点：`client/src/bootstrap/plugin_wiring.py:52-83` `setup_plugins()`——现有 5 插件（mcp/audio/wake_word/ui/shortcuts）在 :77-83 `container.plugins.register(...)` 注册；**VisionPlugin 以条件式懒 import 加在此处（触点 TP2）**。
- 配置访问：模块级 `from src.utils.config_manager import get_config` 返回 ConfigManager 单例（settings_model.py:23,52 用法先例）；插件内 `ctx.get_config()`（protocols.py:66-70）。
- QML 侧发送命令面：`PluginCommands.send_text`（protocols.py:103-107）；V0.6 图像提交不走 WS，走既有 `VisionController.submit`（HTTP，见下）。

**既有视觉/头像资产（本方案直接消费，不新造采集逻辑）**
- `client/src/vision/controller.py`（已存在于工作区，v06-proto-arch 产出）：`VisionController.submit(jpeg_bytes)` :37-71 —— `validate_jpeg` → 频率守卫（5s 间隔/每分钟 6 次，:27-35）→ `urllib.request` POST `{"image_b64","session_id"}`，头 `Content-Type` + **`X-Vision-Token`**（:53-56），8s 超时（:58），401/4xx/网络错误经 `on_error` 回调上报（:60-71）。
- `client/src/vision/compress.py`：`MAX_BYTES=190KB`（:7）；`compress_jpeg` :27-48 —— `cv2.imdecode` → 最长边 ≤1280（INTER_AREA，:39-41）→ 质量阶梯 0.85→0.4（:42-47）；**重编码天然去 EXIF**（:4）；`validate_jpeg` :12-19（魔数/大小校验）。
- `client/src/avatar/states.py`（已存在，v06-audio-sync 产出）：5 状态机 idle/listening/thinking/speaking/interrupted（:7）；`to_interrupted()` 口型立即归零（:19-21）、`new_generation()` 代际复位（:23-27）——**嘴部同步 = 协议包络方案**（Blocker 分析 Option B：RMS 探针落冻结链被阻塞，V1 PO 门控）。
- 采集后端：`client/src/mcp/tools/camera/capture_backend.py` `capture_jpeg()` :287-316（per-call 开/关 VideoCapture + 12s 超时 + 单 worker 线程池）、`_encode_bgr_jpeg` :129-146（EXIF-free 先例）、`load_capture_config` :50-85。

---

## NEW_FILES（全新文件，5 个 + 2 个已就绪）

| # | 文件 | 内容 |
|---|---|---|
| 1 | `client/src/plugins/vision.py` | `VisionPlugin(Plugin)`：name="vision"、priority=55（先于 ui=60 setup，保证 bridge 在 GUI 启动前就绪）、requires=[]。`setup()`：读 `VISION.ENABLED`（默认 False）→ 关闭即 no-op 返回；开启则构造 `VisionBridge`（模块级 `get_vision_bridge()` 暴露）+ `AvatarStateMachine`，订阅 `Events.INCOMING_JSON`（event_bus.py:28；session.py:50 全量 JSON 上总线）与 `Events.DEVICE_STATE_CHANGED`（event_bus.py:23）。`register_resources(pool)` 注册 stop 清理（模式同 plugins/ui.py:98-100）。 |
| 2 | `client/src/vision/qml_bridge.py` | `VisionBridge(QObject)`：**QML 绑定面**。Signal：`previewChanged()`、`statusChanged(str)`（idle/capturing/submitting/done/timeout/error）、`avatarStateChanged(str)`、`avatarGenerationChanged(int)`。Slot：`togglePreview()`、`captureFrame()`（单帧冻结）、`pickImage(str)`（收 QML FileDialog 的 file URL）、`askXiaozhi()`（读压缩帧 → `VisionController.submit`）、`closePanel()`。含 `QQuickImageProvider`（preview 帧 QImage）+ ~4fps `QTimer` 预览取帧（跑 capture_backend 线程池）；头像侧把 tts/transcript/状态事件翻译为 `AvatarStateMachine` 迁移并转发 Qt 信号（包络表见 AVATAR_QML）。 |
| 3 | `client/src/ui/gui/qml/components/AvatarCanvas.qml` | 数字人 `Canvas` 组件（规格见 AVATAR_QML 节）。 |
| 4 | `client/src/ui/gui/qml/panels/VisionPanel.qml` | 数字人显示区 + 控制行：预览 `Image`（provider="vision"）、预览开关、单帧抓拍、`FileDialog` 图像选择、"让小智看看"、识别状态文本、**关闭按钮**（置 `visionBridge.visible=false` → Loader 卸载 → 回 emoji 表情区）。所有按钮 `enabled` 绑定连接/权限/频率守卫状态。 |
| 5 | `client/src/ui/gui/models/settings/vision.py` | `SettingsVisionMixin`（~30 行）：`visionEnabled` Property + setter 写 `VISION.ENABLED`（模式同 camera_options.py）。 |

已就绪（工作区未跟踪，直接消费）：`client/src/vision/{__init__,controller,compress}.py`、`client/src/avatar/states.py`。

---

## TOUCHPOINTS（4 处触点，精确 diff）

**TP1 `client/src/utils/config_manager.py` — DEFAULT_CONFIG 加 VISION 段**
DEFAULT_CONFIG :64-194 的 `MUSIC` 段（:186-193）之后追加（纯加法，`CONFIG_VERSION` 不升级）：
```python
        # VISION V0.6（默认关闭；开启才加载视觉/头像模块）
        "VISION": {
            "ENABLED": False,
            "TOKEN": "",                                        # 独立令牌，绝不复用 Admin Token
            "ENDPOINT": "http://127.0.0.1:8111/xiaozhi/vision/",
        },
```
缺键兼容：`get_config(path, default)` :398-409 对旧配置返回 default；`_migrate_config` :285-342 **不强制改**（可选 `setdefault("VISION", {"ENABLED": False})`）。

**TP2 `client/src/bootstrap/plugin_wiring.py` — 条件注册 VisionPlugin**
`setup_plugins()` :83 `container.plugins.register(...)` 之后追加：
```python
    # VISION V0.6：默认关闭。ENABLED=false 时零 import、零注册，启动逐字节一致
    from src.utils.config_manager import get_config as _cm
    if _cm().get_config("VISION.ENABLED", False):
        try:
            from src.plugins.vision import VisionPlugin
            container.plugins.register(VisionPlugin())
        except Exception:
            logger.error("vision 插件注册失败，已跳过", exc_info=True)
```

**TP3 设置面 — 开关 + 模型接线**
- `client/src/ui/gui/models/settings_model.py:29-38`：`SettingsModel` 基类列表加入 `SettingsVisionMixin`（+1 行 import）。
- `client/src/ui/gui/qml/windows/settings/CameraTab.qml`：页面标题（:51-56）下方加一行 `XSwitch`（"视觉功能（V0.6，默认关闭）"），`checked: settingsModel.visionEnabled`，`onToggled: settingsModel.visionEnabled = checked`，附文案"开启后主窗口出现数字人与视觉入口；提交使用独立视觉令牌"。

**TP4 GUI 面 — bridge 注入 + 主窗口 Loader**
- `client/src/ui/gui/manager.py` `inject_context`（:53-60）的 dict 后追加条件注入：
```python
        try:
            from src.plugins.vision import get_vision_bridge
            _vb = get_vision_bridge()
            if _vb is not None:
                props["visionBridge"] = _vb
        except Exception:
            pass
```
- `client/src/ui/gui/qml/windows/MainWindow.qml` 表情显示区 Item（:70-95）内追加：
```qml
        Loader {
            anchors.fill: parent
            active: typeof visionBridge !== "undefined" && visionBridge.visible
            source: "../panels/VisionPanel.qml"
        }
```
`visionBridge.visible` 默认 False → Loader inactive → 零元素实例化，表情区渲染路径与现状一致。

---

## AVATAR_QML（AvatarCanvas.qml — Canvas 轻量方案规格）

**为什么 Canvas**：零新依赖（不用 QtMultimedia/Lottie/WebEngine）；`Canvas` + `Timer` 30fps 重绘足够承载 2D 头像（圆脸/眼睛/嘴/耳朵微动效）；与既有 `EmotionDisplay.qml`（components/，41 行）同目录同 import 模式。

**组件结构**（新建 `qml/components/AvatarCanvas.qml`）：
```qml
Canvas {
    property string avatarState: "idle"        // idle|listening|thinking|speaking|interrupted
    property int generation: 0                 // mouthGen，代际复位
    property real mouthOpen: 0                 // 0..1，包络电平
    Timer { interval: 33; running: visible; repeat: true; onTriggered: tick() }   // 30fps，仅可见时跑
    onPaint: { /* 背景→脸部椭圆→双眼(眨眼)→嘴(椭圆高度=mouthOpen*maxH)→状态配饰 */ }
}
```
- **状态驱动**（`visionBridge.avatarStateChanged` → AvatarCanvas 属性；全部为既有事件，零音频文件触碰，Blocker 分析 Option B 接线表）：
  - `DEVICE_STATE_CHANGED → LISTENING/IDLE`（event_bus.py:23；session.py:70-80 断线自动覆盖）→ `to_listening()/to_idle()`：嘴硬归零（hardClose 契约，avatar_v0_logic.js:35-55）、眨眼保持。
  - `INCOMING_JSON {"type":"tts","state":"start"}`（gateway protocol.py:46-50，发射点 turns.py:1181）→ `to_speaking()` + `generation++` + mouthOpen=0 → 启动包络。
  - `INCOMING_JSON {"type":"tts","state":"stop"}` → `hardClose()`（mouthOpen 立即 0）+ 停包络。
  - thinking = **派生窗口**：user `transcript` `final:true`（新 turn id）→ `tts start` 之间（协议无专用 thinking 事件，constants.py:25-32 仅 IDLE/LISTENING/SPEAKING；`llm`/`stt` 为无发射点死路径，Blocker 分析 :55-59）→ 思考微表情，嘴闭合。
  - `interrupted`：`DEVICE_STATE_CHANGED` 本地打断路径（wake_word.py:103-106 / session.py:258-290，≤50ms）→ `to_interrupted()` 瞬态硬归零。
- **嘴部包络**：speaking 期间 8-14Hz 伪随机瓣动 + 起止斜坡（确定性模拟；诚实损失：无音量/停顿对应、起播有 FIFO 级错位、音乐不感知——Blocker 分析 HONEST_LOSS :47-53，验收按"预期内近似"口径）。
- **眨眼**：独立 3-5s 随机间隔眨眼 Timer（与状态无关，idle/listening 保留）。
- **代际绑定**：`generation` 在 tts start / SPEAKING 迁移 / user 新 turn 三点递增（AVATAR_AUDIO_SYNC_DESIGN GENERATION_BINDING :63-69），渲染端只见 `avatarGenerationChanged` 后复位嘴部，杜绝跨轮残影。
- **故障隔离**：tick()/onPaint 全部 try/except，连续 3 次异常 → `visible=false` 定格 + 状态条提示（FAULT_ISOLATION 口径）；组件零 import 音频模块。
- **关闭按钮**：VisionPanel 头部 `XIconButton`（controls/XIconButton.qml）→ `visionBridge.closePanel()`；关闭即停 30fps Timer、停预览、`avatarStateMachine.to_idle()`。

---

## DEFAULT_OFF_PROOF（VISION.ENABLED=false ⇒ 启动逐字节一致）

1. **导入隔离**：TP2 的 `from src.plugins.vision import ...` 位于 `if get_config("VISION.ENABLED", False)` 分支内——默认路径上该分支不求值为真，vision/qml_bridge.py、AvatarCanvas 状态翻译代码**零 import**；cv2 既有依赖（pyproject.toml:27 opencv-python-headless）加载面不变；`list_camera_devices()`（capture_backend.py:380-417，会弹 TCC 权限）绝不会被调用。
2. **配置面**：TP1 为 DEFAULT_CONFIG 纯加法；旧用户配置文件缺 `VISION` 键 → `get_config("VISION.ENABLED", False)`（config_manager.py:398-409 点路径缺键返回 default）→ False；`_migrate_config` :285-342 不升级版本 → 磁盘配置零改写。
3. **插件面**：未注册 VisionPlugin → PluginManager 拓扑排序/生命周期与现状完全一致（manager.py:89-215 输入集合不变）；即便开启后 setup 失败也仅 mark_failed（:191-195），不拖垮启动。
4. **QML 面**：`inject_context`（qml_host.py:58-64）不出现 `visionBridge` → QML `typeof visionBridge !== "undefined"` 为 false → TP4 的 Loader `active:false` → VisionPanel/AvatarCanvas 零实例化、零 Timer、零 Canvas 绑定；MainWindow.qml 其余元素树、SettingsWindow 7 页签布局逐字节同现状（TP3 仅在 CameraTab 增加一个默认 checked=false 的开关，不改变启动渲染）。
5. **音频冻结链**：diff 中不存在 `client/src/audio_codecs/`（7 文件）、`client/src/audio_processing/`、`plugins/audio.py`、`websocket_protocol.py` `send_audio`(:256-277)/`_on_incoming_audio`(:221-224) 任何一行——V05-R10/E9 冻结审计自动通过。
6. **网络面**：VisionController 仅在 `submit()` 调用时发请求且 `enabled=false` 首行即拒绝（controller.py:41-42）——默认态零 socket、零 HTTP。

## REVERT_PLAN（单提交回退）

全部改动收敛于**一个 commit**（新文件 7 + 触点 5 文件：config_manager.py、plugin_wiring.py、settings_model.py、CameraTab.qml、manager.py、MainWindow.qml + 文档本篇）。回退：
```bash
git revert <assembly-commit>   # 或 git checkout f518778 -- client/ 删除全部加法文件
```
无迁移、无数据文件、无密钥落盘（TOKEN 为用户配置项），revert 后无需任何清理步骤。

---

## VERDICT

**feasible（低风险）**。装配点全部实测锁定：4 触点 = ①config_manager.py DEFAULT_CONFIG（:64-194 加法段）②plugin_wiring.py:83 条件懒注册 ③SettingsModel mixin + CameraTab.qml 开关 ④gui/manager.py:53-60 条件注入 + MainWindow.qml:70-95 Loader。客户端已就绪 vision/（controller.py HTTP+X-Vision-Token :53-56、compress.py ≤190KB/EXIF-free :27-48）与 avatar/states.py（5 状态机），新写面仅 QML 面板/Canvas、bridge、plugin、settings mixin 共 5 个加法文件。嘴型走协议包络（Blocker 分析 Option B，零冻结链触碰；RMS 探针挂账 V1 PO 豁免）。默认关闭由"条件 import + 缺键配置 + QML typeof 守卫"三重保证，启动行为逐字节一致；单提交 revert 即全退。
