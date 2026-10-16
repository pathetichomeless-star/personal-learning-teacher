# V1.0 Mac 真机 GUI 验收报告（avatar-vision-v0）

- 验收人：Agent D（mac-acceptance）
- 日期：2026-10-09
- 机器：本机 macOS（darwin，Apple Silicon，真实图形环境，非离屏）
- 分支：`avatar-vision-v06-mac-native`，HEAD `6b3ba65`
- 验收方式：真实窗口运行（PySide6/QML），截图 + 日志 + psutil 采样取证

## 一句话结论

**不通过（开箱即崩）**：视觉插件存在 4 处接口错用导致首次启动即崩溃、修复后又有 1 处 QML 名字遮蔽使视觉面板永久假死；全部为本地最小修补后才完成验收。修补共 2 个文件、未 commit，交团队复核。数字人画布可渲染但**无任何基线动画**（10 秒 20 帧像素级零变化）。

## 1. 预检结果

### 1.1 配置（路径 `~/Library/Application Support/py-xiaozhi/config/config.json`）

| 配置项 | 原值 | 验收期值 | 恢复 |
|---|---|---|---|
| `SYSTEM_OPTIONS.NETWORK.WEBSOCKET_URL` | `ws://192.0.2.1:28310/xiaozhi/v1/` | `ws://127.0.0.1:9/xiaozhi/v1/`（不可达本地） | ✅ 已恢复 |
| `SYSTEM_OPTIONS.NETWORK.OTA_VERSION_URL` | `http://192.0.2.1:28311/xiaozhi/ota/` | `http://127.0.0.1:9/xiaozhi/ota/`（不可达本地） | ✅ 已恢复 |
| `VISION`（段） | 不存在 | `{ENABLED: true, TOKEN: ""}` → 后改 false | ✅ 已移除 |
| `SYSTEM_OPTIONS.NETWORK.AUTHORIZATION_URL` | `https://xiaozhi.me/` | 未改（`--skip-activation` 下不会触达） | — |
| `CAMERA.Local_VL_url` | `https://open.bigmodel.cn/api/paas/v4/` | 未改（仅 MCP 相机工具使用；`VLapi_key` 为空，验收全程未调用） | — |

敏感字段（只记录存在性）：`WEBSOCKET_ACCESS_TOKEN` 存在（值未读取/未打印）；`CAMERA.VLapi_key` 为空；无其他 key 类字段。

### 1.2 启动方式（来自 client/README 与 main.py）

```
cd client && .venv/bin/python main.py --mode gui --protocol websocket --skip-activation
```

- venv：`client/.venv`（PySide6 6.10.1、qasync、PIL 可用）
- `--skip-activation` 跳过设备激活（日志：`跳过激活流程（调试模式）`）

### 1.3 视觉链路预检（代码层）

- 插件：`src/plugins/vision.py` 读 `VISION.ENABLED` / `VISION.TOKEN`；提交 endpoint 硬编码 `http://127.0.0.1:8111/xiaozhi/vision/`（**本地地址，无公网风险**）
- UI：`VisionPanel.qml` 提交按钮固定读取 `/tmp/vision_test.jpg`；`AvatarCanvas.qml` 设计有眨眼（2-5s 随机）与状态角标
- 冻结面未触碰：`audio_codecs`、`plugins/audio.py`、`core`、`protocols` 零改动

## 2. 启动命令 / PID

- 启动命令：见 1.2；日志：`/tmp/v1_gui_run1.log` … `/tmp/v1_gui_run10.log`（每次启动独立文件）
- 正式验收实例（run9）：PID **12891**（19:53:00 启动）
- 故障隔离实例（run10）：PID **14928**（20:00:38 启动）
- 同屏最多 1 个实例，用完即关 ✅

## 3. 为继续验收所做的最小修补（未 commit，交团队复核）

**重要：HEAD 6b3ba65 上视觉插件从未成功启动过（4 处接口错用 + 1 处 QML 遮蔽），说明该链路未经过任何冒烟测试。**

`git diff --stat`：`client/src/plugins/vision.py | 11 +++++------`、`client/src/ui/gui/qml/windows/MainWindow.qml | 9 +++++++--`

### client/src/plugins/vision.py（3 处）
1. 删除 `__init__` 中 `self.failed = False` —— `Plugin.failed` 是只读 property（`src/plugins/base.py:66`），赋值即 `AttributeError`，**启动即崩**
2. `except` 分支 `self.failed = True` → `self.mark_failed()`（同上原因）
3. setup 中 `ctx.config.get(...)` → `ctx.get_config().get_config(path, default)`：
   - PluginContext 协议暴露的是 `get_config()`（`src/bootstrap/adapters.py:47`），无 `ctx.config` 属性
   - `ConfigManager` 读接口是 `get_config(path, default)`（`src/utils/config_manager.py:398`），无 `.get()` 方法
4. `register_resources`：`pool.register(self.bridge._env_timer.stop)` → `pool.register("vision.env_timer", self.bridge._env_timer.stop)` —— 签名为 `register(name, cleanup)`（`src/core/resource_pool.py:31`），缺参导致**启动即崩**

### client/src/ui/gui/qml/windows/MainWindow.qml（1 处）
- 根级新增别名属性 `visionBridgeAlias`，Loader/VisionPanel 改用它 —— 原写法 `VisionPanel { visionBridge: typeof visionBridge !== "undefined" ? visionBridge : null }` 中右侧 `visionBridge` 被 VisionPanel 自身同名属性遮蔽，解析为 null，面板 UI 永久显示默认关闭态（详见 D5）

## 4. 逐项检查表

| # | 检查项 | 结果 | 证据 |
|---|---|---|---|
| a | 主窗口出现、无致命错误 | ✅ 通过（修补后） | 截图 `/tmp/v1_gui_main_fixed.png`；日志 `GuiViewManager: GUI 启动完成`（run9 行 112） |
| b | 数字人窗口/画布渲染 | ⚠️ 部分通过 | 画布渲染出人物（截图 main_fixed.png 底部）；**但无眨眼/呼吸动画**（见 D6）；默认 520 高窗口下画布大部分被裁剪（D9） |
| c | 视觉开关与状态文本 | ⚠️ 部分通过 | 开关与"视觉已开启/视觉关闭"状态文本可随配置正确显示（两张截图对比）；真实点击切换因系统辅助功能权限缺失无法执行（见 6.1）；另发现一次非用户触发的 `enabled=False` 日志（D7） |
| d | 视觉提交 fail-closed | ✅ 通过 | 8111 端口无监听（`Connection refused`，socket 直连验证）；离线全链路调用 `submitImagePath('/tmp/vision_test.jpg')`（20KB JPEG）→ 状态"已提交，等待识别…" → 8s 后 **"提交失败：http 502"**（502 来自本机 WorkBuddy 透明代理 `HTTP_PROXY=127.0.0.1:53166`，非真实服务）；非法路径→`读取失败：…No such file…`；非 JPEG→`仅支持 JPEG 图片`；开关关闭后提交→`视觉未开启`。**零真实云端调用** ✅ |
| e | 资源占用 | ✅ 通过 | 启动 8s：RSS 277MB、CPU 57%（加载期）；运行 7min：RSS 198MB、CPU 0.0%、33 线程、34 fds；+60s：RSS 202MB、CPU 0.0%（psutil，进程 12891） |
| f | 故障隔离（VISION.ENABLED=false） | ✅ 通过 | run10（PID 14928）正常启动，RSS 184MB、CPU 0%；面板正确显示"视觉关闭"、提交按钮禁用（截图 `/tmp/v1_disabled.png`）；表情/对话区渲染正常；插件缺席时 Loader inactive 零实例化 |
| g | 截图 | ✅ 完成 | `screencapture -x -l <winid>` 按窗口截图成功（Quartz 定位 winid）；首张全屏截图含与本验收无关的屏幕内容，已删除，仅保留窗口级截图 |

### 语音链路零云端触达验证

- 启动至待命全程：日志中无任何 WebSocket 连接尝试、无 OTA 请求（待命态不主动连接）
- WS 地址已设 `ws://127.0.0.1:9/`（discard 端口，即使连接也立即本地失败）
- 未启动任何 gateway 服务端；未使用 `QT_QPA_PLATFORM=offscreen`

## 5. 缺陷清单

| 编号 | 严重级 | 描述 | 证据/位置 |
|---|---|---|---|
| D1 | **S1 启动阻断** | `VisionPlugin.__init__` 赋值只读 property `failed` → 启动即崩 `AttributeError: can't set attribute 'failed'` | run1 日志；`vision.py:20` vs `base.py:66` |
| D2 | **S1 功能阻断** | `ctx.config` 属性不存在（协议为 `ctx.get_config()`）→ 插件初始化失败，视觉全链路不可用 | run3/run6 日志 `AttributeError("'PluginContextAdapter' object has no attribute 'config'")`；`adapters.py:47` |
| D3 | **S1 功能阻断** | `ConfigManager.get(...)` 不存在（实为 `get_config(path, default)`）→ 同上 | run7 日志 `AttributeError("'ConfigManager' object has no attribute 'get'")`；`config_manager.py:398` |
| D4 | **S1 启动阻断** | `pool.register()` 缺 `name` 参数 → `应用运行失败: ResourcePool.register() missing 1 required positional argument: 'cleanup'`，启动即退出 | run7 日志行 85；`resource_pool.py:31` |
| D5 | **S2 功能缺陷** | MainWindow.qml 中 `VisionPanel { visionBridge: … visionBridge … }` 同名属性自我遮蔽：Loader 用真 bridge 判活（面板渲染），面板内部却拿到 null → 开关恒显关闭、状态恒"视觉关闭"、提交按钮永久禁用（即使插件 enabled=True） | 截图 `/tmp/v1_gui_main_window.png`（修复前）vs `/tmp/v1_gui_main_fixed.png`（修复后）；`MainWindow.qml:105-113`（原） |
| D6 | **S2** | 数字人画布无基线动画：10 秒 20 帧像素级零变化（画布区 diff bbox=None），同窗口表情 emoji 同期多次变化（渲染管线正常）——设计的眨眼 2-5s 未生效。候选根因：`AvatarCanvas` 的 `Timer { running: root.visible }` 未触发或 `requestPaint` 被合并 | 连拍 `/tmp/v1_canvas_*.png`、`/tmp/v1_seq_*.png`；`AvatarCanvas.qml:77-80` |
| D7 | **S3 疑点** | 启动后约 13 秒出现一次非用户触发的 `VISION enabled=False` 日志（run9 19:53:13），此后 UI 持续显示"视觉已开启"——状态翻转来源与 UI 同步性均需排查（疑似 Qt 6.10 中程序化 checked 变化触发 `toggled`） | run9 日志行 82/120；截图 state_check.png |
| D8 | **S3 观察** | 存在一个 500x500 纯黑窗口（winid 5503，位于 (0,456)），用途不明 | 截图 `/tmp/v1_win5503.png` |
| D9 | **S3** | 默认窗口 420x520 下视觉面板底部（画布大部、`state=` 角标）被裁剪不可见；内容撑高后仍裁剪画布下半部——数字人主视图实际不可完整观看 | 截图对比（520 高 disabled.png vs 678 高 main_fixed.png） |
| D10 | **S3 观察** | 提交失败文案在本机代理环境下显示 `提交失败：http 502`（真因为目标端口无监听）；干净环境下应为连接拒绝。fail-closed 行为本身正确 | 8111 socket 直连 `Connection refused` + 代理 env 记录 |
| D11 | **S3 观察** | Event Tap 持续不可用（辅助功能权限），快捷键插件反复告警（环境权限问题，非代码缺陷） | run9 日志行 122-125 |

## 6. 待人工验收清单（本次未做、不得宣称通过）

1. **TCC 摄像头三分支**（授权/拒绝/未决定）——需真人操作系统授权弹窗
2. **真实 Tina 语音链路音频观测**（口型与真实 TTS 音频同步）——需真实会话
3. **主观口型自然度**——需真人观感评价
4. **真实 Qwen 单图识别**——PO 授权前禁止，本次仅验证本地 fail-closed
5. **UI 开关/按钮的真实点击**——本环境无辅助功能权限，CGEvent 点击被系统静默丢弃；已用离线 bridge 调用验证等价逻辑（状态机、提交门控、错误分支全部符合预期）+ 截图验证 UI 渲染，但真人点击路径未验证
6. **D7（enabled=False 之谜）根因确认**——需代码层排查 Qt toggled 语义

## 7. 现场清理记录

- ✅ 配置已恢复原值（WEBSOCKET_URL / OTA_VERSION_URL 逐字核对，VISION 段已移除；备份在 `/tmp/config.json.acceptance-backup`）
- ✅ 所有由本验收启动的客户端进程已退出（run1-run10 全部 kill，pgrep 确认无残留）
- ✅ 含无关屏幕内容的全屏截图已删除；窗口级证据截图保留于 `/tmp/`
- ✅ 未 git commit、未删除项目文件；代码修补保留在工作区供复核（见第 3 节）

## 8. 证据文件索引

| 文件 | 内容 |
|---|---|
| `/tmp/v1_gui_main_window.png` | D5 证据：面板渲染但假显"视觉关闭"、按钮禁用 |
| `/tmp/v1_gui_main_fixed.png` | 验收通过证据："视觉已开启"、按钮可用、画布渲染 |
| `/tmp/v1_disabled.png` | 故障隔离：ENABLED=false 正确关闭态 |
| `/tmp/v1_after_click.png`、`/tmp/v1_state_check.png` | 状态持续性（D7 相关） |
| `/tmp/v1_canvas_0..7.png`、`/tmp/v1_seq_0..19.png` | D6 画布静止帧证据 |
| `/tmp/v1_win5503.png` | D8 黑窗口 |
| `/tmp/v1_gui_run1..10.log` | 各次启动完整日志 |
| `/tmp/vision_test.jpg` | 20KB 测试 JPEG（640x480） |

---

# 整改后终验（Live2D 引擎）

- 验收人：Agent D（mac-acceptance）
- 日期：2026-10-09（晚于上轮，基线 6686e67 + 未提交集成改动，后由 engine-integrator 提交为 d177582）
- 被测：engine-integrator 集成的成熟 Live2D 引擎（Cubism Core + pixi-live2d-display 0.4.0 + Hiyori 官方样例）
- 门禁：与上轮相同（服务器地址改为 127.0.0.1:9 不可达、VISION.ENABLED=false、最多 1 实例用完即杀、真机窗口非 offscreen、不 commit、不打印密钥）

## 一句话结论

**不通过**：引擎解析、WebEngine 子进程、页面加载与模型内部链路全部健康（见 D12 证据链），但真机窗口中 **Hiyori 人物不可见、数字人区域 10 秒 20 帧像素级零变化**——D6"数字人动画存在性"对照验证失败（与上轮 Canvas 同样为零，整改目标未达成）。视觉开关故障隔离、进程清理、配置恢复全部通过。

## L1. 引擎解析预检 ✅

- 调用 `client/src/avatar/engine.py: resolve_avatar_engine(get_config)`，本机配置 `AVATAR.ENGINE` 缺省 + vendor 关键资产 7 项齐备 → 返回 `(engine='live2d', reason='')`。
- 运行期日志双确认（app.log）：
  - `src.vision.qml_bridge | AVATAR engine=live2d`
  - `src.ui.gui.qml_host | WebEngine: QTWEBENGINE_DISABLE_SANDBOX=1（AVATAR.ENGINE=live2d）`

## L2. 启动 ✅（附 1 条环境说明）

- 命令：`cd client && .venv/bin/python main.py --mode gui --protocol websocket --skip-activation`
- 日志 `GuiViewManager: GUI 启动完成`；`QtWebEngineProcess` 渲染子进程出现且带 `--no-sandbox`（证明 qml_host 沙箱注入生效），`AVATAR engine=live2d` 注入 QML 上下文 `avatarEngine`。
- 环境说明（非应用缺陷）：前两次以工具沙箱内 `nohup &` 方式启动，进程在命令结束后被沙箱回收、日志无痕（qasync 初始化后静默消失）；改用工具后台常驻模式后同代码启动完全正常。已核实非崩溃。

## L3. Live2D 真实渲染 ❌（核心不通过项）

- 默认窗口 420x520 下数字人区域仍在折叠线下（D9 复发，布局与基线一致，非本轮引入）。为完成观测，**临时**将 `MainWindow.qml` height 520→750 截图后逐字节还原（shasum 三方一致：还原后 = 提交 d177582 内 = 改动前备份，见 L8）。
- 750 高窗口截图：数字人区域仅显示页面角标 **`ready | state=idle`**，其余为纯背景色，**无任何人物形象**（截图 `/tmp/l2d_evidence/l2d_750.png`、`l2d_750_b.png`）。上轮 Canvas 线条人物至少可见，本轮 Live2D 人物完全不可见。

### 帧序列像素差分（D6 对照，上轮同手法）

- 20 帧 × 0.5s（约 10s），窗口级 `screencapture -l`，PIL 逐帧差分：
  - 数字人区域（2x 像素框 60,660–580,945）：**20 组相邻帧 diff 全部 bbox=None、nonzero_px=0**；首尾 diff 同样为零。
  - 全窗口同期唯一变化区域为表情 emoji bbox（411,252–520,358）@2x（渲染管线正常，与上轮 D6 观察一致）。
- **结论：本轮帧差分为零，"数字人动画存在性"不能从待人工清单移除**（原计划：若 Live2D 动画非零则以帧差分为证移除）。

### D12（新缺陷，S1）：Live2D 画布 GL 零输出——页面内部全绿但像素不落画布

经 CDP（`--remote-debugging-port=9333` 诊断实例）注入取证，页面内部状态逐项健康：

| 检查项 | 结果 |
|---|---|
| `window.__errors` / `__avatarError` | 空 / null，boot 无异常 |
| `__avatarReady` / `modelInfo()` | true；`id=Hiyori`、134 drawables、state=idle |
| WebGL 上下文 | WebGL 2.0，`isContextLost()=false`，无 `getError` |
| 纹理 | `_textures` 2 张均 `glIsTexture=true`；原生 GL 四边形采样出真实颜色（如 109,112,123,248） |
| 蒙版 | `_clippingManager` FBO `FRAMEBUFFER_COMPLETE`，蒙版已渲出（采样 B 通道 255）；blend 正确（蒙版 `blendFuncSeparate(0,769,0,771)`、正常绘制 `(1,771,1,771)` 均为 Cubism 标准值） |
| 绘制调用 | 每帧 117 次 `drawElements`（TRIANGLES、program LINKED、2 组顶点属性） |
| 顶点/动画 | drawable 顶点随 `internalModel.update` 变化（maxAbs 0.2721→0.2761），更新循环在跑（ticker 59.9fps） |
| **画布读回** | **`contentBBox()` 恒为 null——除背景色外零像素**；PIXI 图元对照实验（红色矩形）可正常读回，排除读回通路问题 |

即：加载→解析→更新→draw call 全链路正常执行，但像素从未出现在画布上；人物因此不可见、帧差分因此为零。另观测到 idle motion 未挂载（`motionGroup=Idle` 但 `currentMotion=null`、`idleMotionManager=false`，motion XHR 在 file:// 下疑似未加载成功）——即使解决渲染问题，动画也可能需要一并修复。对照实验：Chrome headless（--disable-gpu SwiftShader）下同一页面 boot 直接 ERROR，环境无法复现实验室浏览器成功路径，对照无效；建议 integrator 在真实 Chrome（带 GPU）复测同一 HTML 定位 QtWebEngine/ANGLE 差异。

## L4. 资源占用 ✅（附 CPU 观察）

| 时点 | 主进程 | QtWebEngineProcess | 子进程数 |
|---|---|---|---|
| 启动 ~10s（PID 38162） | RSS 378.4MB，CPU 55.8%（加载期） | RSS 257.3MB，CPU 17.0% | 1 |
| 稳定 10.6min（PID 40637） | RSS 394.0MB，CPU **73.2%**，51 线程 | RSS 166.7MB，CPU **28.2%** | 1 |

- 观察：待命态主进程 CPU 73% 显著高于上轮 Canvas 待命基线（~0%）。rAF ticker 以 60fps 持续渲染是引擎设计使然，但画布零输出下纯属空转；建议整改时一并评估不可见/被遮挡时降帧（psutil，进程 40637/40641）。

## L5. 故障隔离（VISION.ENABLED=false）✅

- 面板正确显示"启用视觉 **视觉关闭**"，"让小智看看（测试图）"提交按钮禁用（截图 `shot_initial.png`、`l2d_750.png`）；日志 `VISION enabled=False`、`VISION 插件就绪（enabled=False）`。
- 数字人引擎独立于视觉开关：visionBridge 关闭态下 live2d 引擎照常解析、WebEngine 照常启动（本轮核心验证项达成）。

## L6. 退出释放 ✅

- 全部实例（共 6 次启动，含 2 次被沙箱回收）结束验证：`pgrep main.py --mode gui` 无结果、`pgrep QtWebEngineProcess` 无结果、无 Chrome 残留进程、无僵尸进程。

## L7. 配置恢复 + 现场清理 ✅

- ✅ 配置逐字恢复（`diff` 干净）：`WEBSOCKET_URL=ws://192.0.2.1:28310/xiaozhi/v1/`、`OTA_VERSION_URL=http://192.0.2.1:28311/xiaozhi/ota/`；验收期临时添加的 `VISION` 段已移除；JSON 有效性校验通过；备份 `/tmp/config.json.bak-acceptance-l2d`。
- ✅ `MainWindow.qml` 临时高度改动逐字节还原：还原后 shasum `a2aa2641…695d48` = 改动前备份 = 提交 d177582 内该文件（三方一致）；`git status` 工作区干净（集成改动已由 engine-integrator 于 21:30:10 提交，早于本验收临时改动时刻，未混入）。
- ✅ 本验收未 commit 任何内容；未使用 `QT_QPA_PLATFORM=offscreen`；未打印任何密钥（`WEBSOCKET_ACCESS_TOKEN` 存在性同上轮记录，值未读取）。

## L8. 证据文件索引

| 文件 | 内容 |
|---|---|
| `/tmp/l2d_evidence/shot_initial.png` | 默认 420x520 窗口：视觉关闭正确、Live2D 区在折叠线下（D9 复发） |
| `/tmp/l2d_evidence/l2d_750.png`、`l2d_750_b.png` | 750 高窗口：`ready \| state=idle` 角标可见、**无人物** |
| `/tmp/l2d_evidence/seq/f00..f19.png` | 20 帧连拍（差分输入） |
| `/tmp/l2d_evidence/chrome_live2d.png` | Chrome headless 对照（boot ERROR，对照无效） |
| `/tmp/l2d_evidence/MainWindow.qml.bak` | 临时改动前备份（shasum 证据） |
| 客户端日志 app.log（21:24:47 段） | `AVATAR engine=live2d`、`QTWEBENGINE_DISABLE_SANDBOX=1`、`GUI 启动完成` |
| QtWebEngineProcess cmdline | `--no-sandbox`（诊断实例另含 `--remote-debugging-port=9333`） |

## L9. 终验结论与待人工清单更新

**结论：不通过。** 引擎替换在"接线层"成立（解析→WebEngine→页面→模型全部就绪），但"呈现层"失败（D12：GL 零输出 → 人物不可见、动画零变化）。

待人工/待整改清单（在上轮第 6 节基础上更新）：
1. **数字人动画存在性**——**保留待人工/待复测**（本轮帧差分为零，原移除条件"Live2D 渲染与动画成功"未满足；需 D12 修复后按同手法复测）
2. TCC 摄像头三分支——仍待人工（同上轮）
3. 真实 Tina 音频口型同步、主观自然度——仍待人工（同上轮）
4. 真实 Qwen 识别——仍待人工（同上轮）
5. 真人 UI 点击——仍待人工（本环境无辅助功能权限，同上轮；本轮窗口放大亦因此受阻，改用临时改高度方案完成观测）
6. **新增 D12 修复验证**（integrator）：真机窗口 Live2D 人物可见 + 非零帧差分 + 待命态 CPU 回落评估
