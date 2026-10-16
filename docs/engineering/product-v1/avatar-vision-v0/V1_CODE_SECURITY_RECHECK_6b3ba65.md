# V1_CODE_SECURITY_RECHECK @ 6b3ba65

date=2026-10-09 · head=**6b3ba658f62df095818ef49e3392c06809bfa179** · branch=avatar-vision-v06-mac-native · 基线=d5644f1 · V1.0 delta 起点=203b14c
reviewer=code-reviewer（独立只读复核；唯一写入=本文件）

> **修复后首次独立复核声明**：F1 修复提交 6b3ba65 之后再无任何独立复核记录（全 docs/ 检索 `6b3ba65` 零命中；`git log` 中其后仅 e337f02/569070d 两份文档且均先于该提交——V1_FINAL_REVIEW.md 明确记录其审查对象为 head=203b14c）。本文件即 F1 闭合后的**首次独立复核**，全部结论基于本机实跑证据。

---

## 六项逐条结论

### 1. F1 Token 配置读取修复 — **PASS**

- `git show 6b3ba65`：仅 1 文件 `client/src/plugins/vision.py`，+3/-1。diff 内容：删除硬编码 `token = ""`，改为 `cfg_get = getattr(ctx.config, "get", None)` + `token = str(cfg_get("VISION.TOKEN", "") or "") if cfg_get else ""`（vision.py:30-31）。
- 现行代码逐项核对（client/src/plugins/vision.py）：
  - token 从 `ctx.config` 读取 `VISION.TOKEN`（:31）✓
  - 空值/缺键/None 均回退 `""`（`or ""`）✓
  - fail-closed 保持：`VISION.ENABLED` 缺省 False（:25-27），`self.bridge.setEnabled(enabled)`（:33）✓
  - 整个 setup 包裹 try/except，异常路径 `self.failed=True` 且不影响语音（:38-40）✓
- **实跑七分支验证**（mock ctx 驱动 `VisionPlugin.setup()`，client/.venv 真实执行）：

| 分支 | enabled | token 注入 | failed |
|---|---|---|---|
| ENABLED=True + TOKEN="abc123" | True | **True（修复生效）** | False |
| ENABLED=True + TOKEN="" | True | False（""回退） | False |
| ENABLED=True 无 TOKEN 键 | True | False（默认""） | False |
| 无任何键（出厂默认） | **False（fail-closed）** | False | False |
| ENABLED=False + TOKEN 有值 | False | True（无害，bridge 不启用） | False |
| config 无 .get 方法 | — | False（不崩溃，""） | False |
| TOKEN=None | True | False（`or ""` 兜底） | False |

  七分支全部无异常。日志输出仅 `VISION enabled=...`，**token 不进日志** ✓。
- 评估结论：修复最小、正确、类型安全（str() 强转 + `or ""` 双兜底），异常与缺属性路径均安全。质量合格。

### 2. F1 修复后有独立复核 — **PASS（本报告即首次）**

- 检索证据：`grep -r "6b3ba65" docs/` → 零命中；`git log --oneline` 确认 6b3ba65 为 HEAD，其前最后一份复核文档 V1_FINAL_REVIEW.md（e337f02）自述 `head=203b14c`（V1_FINAL_REVIEW.md:3）。
- 结论：本文件为修复后首次独立复核，含实跑证据（见第 1 项七分支表 + 测试矩阵）。

### 3. 视觉图片与当前会话绑定可靠 — **PASS**

- **恒时比较**：gateway/app/http.py:67-68 `hmac.compare_digest(provided, expected)`；且 expected 为空（token 文件缺失/为空）时直接 401，fail-closed（http.py:67 `if not expected or ...`）✓
- **ambiguous_session 显式拒绝（be55c39）在 HEAD 仍生效**：`git show be55c39` 确认其引入该逻辑于 gateway/app/qwen.py；现行 HEAD qwen.py:828-830：多活跃连接时 `return False, "ambiguous_session"`，映射 409（http.py:96）。测试 V11（vision_v0_tests "多活跃会话 → ambiguous_session"）实跑 PASS ✓
- **绑定/防污染路径**：
  - 单会话 sidecar：`submit_vision_image` 只筛选 `_connected` 且 `_ws` 非空的实例（qwen.py:824-825），无可连实例 → `not_connected`(503)（qwen.py:826-827）
  - 图像进入**发起提交的那个** QwenClient 实例的 `send_image`，与该会话的音频缓冲同流提交（`input_image_buffer.append` 与 `input_audio_buffer.commit` 同会话语义，qwen.py:691-694 注释 + qwen.py:740）
  - ordering 守卫：会话内必须先有音频才接受图像（`_audio_seen`，qwen.py:725-727），新会话重置（qwen.py:463-465）
  - teardown 即注销（`_ACTIVE_INSTANCES.discard`，qwen.py:796），杜绝跨会话残留引用；意外断线实例被 `_connected` 过滤（qwen.py:824）
- **图片字节零落盘**：客户端唯一文件操作为 `open(path,"rb")` 只读（qml_bridge.py:133）；gateway 侧仅内存 base64 解码/编码后经 WS 转发（http.py:84、qwen.py:736-740），全链无 wb/imwrite/tofile 写路径 ✓
- 客户端提交守卫：开关早退（qml_bridge.py:118-121）、5s 间隔（:123）、6/min 滑窗（:127-131）、JPEG magic（:139）、190KB 上限（:143）；token 仅用于 `X-Vision-Token` header（qml_bridge.py:173），不进 URL/body/日志/QML 属性 ✓

### 4. 音频冻结代码零改动 — **PASS**

- `git diff d5644f1..HEAD -- gateway/app/audio.py gateway/app/turns.py client/src/audio_codecs client/src/plugins/audio.py client/src/core client/src/protocols` 输出 **0 字节**（实测 `| wc -c` = 0）。
- `git show 6b3ba65 --name-only`：仅 `client/src/plugins/vision.py` ✓
- 203b14c..HEAD 全量 delta：vision.py(+3/-1) + 三份 docs，无其他代码触点。

### 5. 无真实云端调用及费用 — **PASS**

- **代码面**：gateway 无 dashscope/openai/HTTP REST 视觉调用点（grep 仅命中 qwen.py 实时 WS host 模板与测试/文档）。视觉图像的下游 = QwenClient 已连接的上游 WS（`input_image_buffer.append`）；上游由 `QWEN_MODE` 决定。
- **开关与默认值**：代码默认 `QWEN_MODE=mock`（qwen.py:247 + main.py DEFAULTS:25）；本机生效配置 `gateway/config/config.json` 实读 **QWEN_MODE=mock**（无 KEY/SECRET/WORKSPACE 键）。real 模式还需 api_key+workspace+region 三者齐备才 ready（qwen.py:213-217），缺任一即 `staying disconnected`（qwen.py:394-401）。
- **密钥存在性（不打印值）**：本地 `secrets/qwen-realtime.env` 存在但被 `.gitignore:9 (**/secrets/)` 覆盖，`git ls-files secrets/` 零输出——**未入库** ✓。gateway/secrets/ 目录本地不存在 → vision_token 文件缺失 → 视觉端点恒 401（fail-closed）。客户端运行时配置（~/Library/Application Support/py-xiaozhi/config/config.json）实读：`VISION.ENABLED=True`、`VISION.TOKEN=<空串>`。
- **日志外呼痕迹**：logs/（仓库根 3 个日志，576 行）与客户端运行日志（app.log 等）grep `aliyuncs|mode=real|dashscope|realtime|wss://` 全部零命中。无真实 Qwen/DashScope 外呼证据。
- **测试全 mock**：product_v1_integration 自述 "drivable mock Qwen + fake read-only workbench"；vision_v0_tests/v05_e2e_tests 使用进程内 mock 上游（本机 127.0.0.1），实跑输出确认 0 外呼。

### 6. 无未授权第三方 SDK / 模型文件入库 — **PASS**

- `git ls-files | grep -iE 'live2d|cubism|moc3|model3.json|pixi'` → 唯一命中为**文档** `V1_LIVE2D_LICENSE_EVALUATION.md`（许可评估报告本身），无任何 SDK 二进制/模型文件 ✓
- `git diff --diff-filter=A d5644f1..HEAD` 新增文件逐一定性：**全部为文本**（.py/.qml/.mjs/.js/.html/.md），无 .wav/.bin/.so/模型文件增量；仓库现存 client/assets/sounds/*.wav 为基线前既有多语言提示音，非本次新增。
- 203b14c..HEAD（V1.0 delta）新增仅 3 份 docs（V1_FINAL_REVIEW / V1_RELEASE_REPORT / V1_LIVE2D_LICENSE_EVALUATION）。
- QML Canvas 分层 2D rig 为自绘实现，未引入 Live2D Cubism Core（与 V1_RELEASE_REPORT "fallback-2d-rig" 声明一致）。

---

## 测试矩阵（全部本机实跑）

| 套件 | 运行方式 | 结果 |
|---|---|---|
| gateway/tests/vision_v0_tests.py | gateway/.venv/bin/python（gateway/ 目录） | **15/15 PASS** |
| gateway/tests/v05_e2e_tests.py | 同上 | **8/8 PASS** |
| gateway/tests/product_v1_integration.py | 同上 + `DYLD_LIBRARY_PATH=client/libs/libopus/mac/arm64`（测试自述要求指向 libopus；本机无 brew opus，用仓库自带 dylib） | **33/33 PASS** |
| client/src/vision/tests/test_vision_module.py | client/.venv/bin/python（client/ 目录，独立脚本非 pytest） | **13/13 PASS** |
| prototypes/tests/avatar_logic_tests.mjs | node（prototypes/ 目录） | **16/16 PASS** |
| prototypes/tests/vision_logic_tests.mjs | node | **17/17 PASS** |
| VisionPlugin.setup 七分支实跑 | client/.venv/bin/python 临时探针（未改任何文件） | **7/7 符合预期** |

合计 **102/102 + 7/7**，无 FAIL、无 SKIP。product_v1_integration 初次因本机缺 libopus 报错，属环境问题非代码问题，按测试文档说明指向仓库自带 dylib 后全绿。

---

## 新发现缺陷

- **F4（minor，部署接线项，非安全缺陷）**：gateway/docker-compose.yml 仅挂载 `qwen-realtime.env`，未挂载 `vision_token`（http.py:54-55 默认读 `/app/secrets/vision_token`）。后果：该部署形态下视觉端点恒 401（fail-closed，安全无虞），但"启用视觉→提交成功"闭环在该部署不可用。同态：本机客户端运行时配置 `VISION.ENABLED=True` 而 `VISION.TOKEN` 为空——处于"开启但必然 401"的无效状态。整改建议：V1.1 部署文档补 vision_token 挂载 + 双端 token 配置清单（客户端 config 与网关 secrets 各一份，同值）。
- 前轮 F2（后台线程回调直接 emit，qml_bridge.py:155-160）、F3（私有成员访问等原型项）在 HEAD 未变，维持 advisory 级，不阻断。
- 无新增安全缺陷。

---

## 附：mac-acceptance 未提交修补复核（2026-10-09，HEAD 6b3ba65 + 工作区 diff）

对象：`client/src/plugins/vision.py`（4 处）+ `client/src/ui/gui/qml/windows/MainWindow.qml`（1 处），未 commit。判定：**全部正确，可提交**。

**vision.py 四处逐一核实**：
1. 删除 `self.failed = False` ✓ —— `Plugin.failed` 为只读 property（base.py:65-68，无 setter），赋值即 AttributeError；`_failed` 已在 `Plugin.__init__`（base.py:41-43）置 False。实跑探针确认构造后 `p.failed is False`。
2. `self.failed = True` → `self.mark_failed()` ✓ —— mark_failed（base.py:70-72）语义一致。实跑异常分支（ctx.get_config 抛错）：failed=True、bridge=None、仅 warning 不影响语音。
3. `ctx.config.get(...)` → `ctx.get_config().get_config(path, default)` ✓ —— 协议 protocols.py:66、实现 adapters.py:47-48（运行时 ctx 即 PluginContextAdapter，container.py:77→102）、ConfigManager.get_config(config_manager.py:398)。**关键发现**：旧写法 `getattr(ctx, "config", None)` 在真实运行时恒 None → 旧插件永远 disabled——静态审计与 mock 探针（当时注入了 .config 形状的假 ctx）均无法暴露此错用，印证了"视觉链路从未跑通冒烟"。
4. `pool.register("vision.env_timer", stop)` ✓ —— ResourcePool.register(name, cleanup)（client/src/core/resource_pool.py:31），与其他插件惯例一致（wake_word/ui/mcp 均带名注册）。实跑 register_resources → `[('vision.env_timer', True)]`。
- F1 语义保持：token 仍从配置读、空值回退 ""、ENABLED 缺省 False、fail-closed 不变。`py_compile` 通过。修补后五分支实跑（有值/空串/缺键/无 get_config/异常）全部符合预期。

**MainWindow.qml 一处核实** ✓ —— 遮蔽机制确认：VisionPanel.qml:9 自身 `property var visionBridge` 使旧绑定的 RHS `visionBridge` 恒解析为自身 null。修补为根级别名 `visionBridgeAlias`（MainWindow.qml:22；`id: root` 在 :10）+ `root.visionBridgeAlias` 两处引用（:113/:115）。bridge 缺席时 alias=null → Loader inactive（零实例化行为保持）。`pyside6-qmllint` 零错误（仅 unqualified-access 风格警告，与 eventBridge/mainModel 既有模式一致；lint 建议改引 alias 本身不可采纳——根级必须引用 context property）。

**回归**：client vision 13/13、prototypes vision_logic 17/17 PASS。改动仅 2 文件，均不在音频冻结路径。

**流程建议（同意并补充）**：GUI 冒烟测试应真实走 `PluginManager.setup_all + register_resources`（用 PluginContextAdapter 形状的 ctx），并断言 VisionPlugin.failed=False 与 register 调用签名；建议将本修补以独立提交（如 "VISION V1.0: fix plugin context/resource/QML-wiring interface misuse"）入库。

---

## 总体判定

**PASS — HEAD 6b3ba65 可作为整改基线。**

- F1 修复正确且经七分支实跑验证；fail-closed 全链保持（客户端默认关 + 网关空 token 恒 401 + 上游 mock 默认）。
- 音频冻结面 d5644f1..HEAD 零字节；6b3ba65 提交面最小（仅 vision.py）。
- 会话绑定/歧义拒绝/恒时比较/零落盘全部在位并有测试覆盖（V11 等）。
- 零真实云端调用、零费用风险；secrets 未入库；无专有 SDK/模型文件。
- 唯一新增项 F4 为部署接线文档级整改，不影响代码基线资格。

---

# 集成复核（Live2D 引擎集成，2026-10-09，基线 6686e67 + 工作区未提交改动）

reviewer=code-reviewer（第三轮，独立安全/QA 视角）· 对象：engine-integrator 交付的 7 个已跟踪文件改动 + 新增纯文本文件（vendor 不入库）

## 1. JS 注入面安全 — **PASS**

- **AvatarLive2D.qml 两处动态 runJavaScript**（AvatarLive2D.qml:65-72）：
  - 口型：`"__avatarAPI.setMouthOpen(" + Number(root.mouthLevel) + ")"` —— `Number()` 恒产生合法 JS 数字字面量（含 NaN/Infinity 亦为安全 token），**无字符串注入路径** ✓
  - 状态：`JSON.stringify(root.avatarState)` 包裹 + 页面侧白名单二次校验（avatar_page.js:193-199 `valid.indexOf(s) < 0` 即拒绝，白名单=idle/listening/thinking/speaking/interrupted）✓
  - readyProbe 定时器内的 runJavaScript 均为常量字符串（AvatarLive2D.qml:51）✓
- **avatar_page.js / avatar_page.html**：MODEL_URL 与三个 `<script src>` 全部为**本地相对路径**（avatar_page.js:27、avatar_page.html:27-30）；grep `eval(|innerHTML|document.write|http://|https://` 对页面 JS 与 probe 均零命中；徽标更新用 `textContent`（avatar_page.js:89）非 innerHTML ✓
- **WebEngineView 设置**（AvatarLive2D.qml:28-29）：`localContentCanAccessFileUrls: true`（模型 XHR file://→file:// 必需，已在注释说明）、`localContentCanAccessRemoteUrls: false` ✓；页面无任何远程内容加载点。
- runtimeUrl 相对路径实测解析正确：components/ 上溯 4 级 → `src/avatar/runtime/avatar_page.html` 存在 ✓。

## 2. qml_host.py 沙箱禁用作用域 — **PASS（附 F6 语义备注）**

- `_prepare_webengine_env`（qml_host.py:14-33）：仅当 `resolve_avatar_engine` 返回 live2d 时设置 `QTWEBENGINE_DISABLE_SANDBOX=1`——进程内 `os.environ`，非系统级；docstring 说明了权衡依据（Chromium sandbox 在受限宿主初始化失败 + 仅加载本地内容）✓
- 调用点在 `create_engine()`（qml_host.py:78），早于 QQmlApplicationEngine 创建，满足 WebEngine"引擎创建前设置"的时序要求 ✓
- 异常路径：try/except 全包 + `logger.debug` 静默跳过（qml_host.py:31-33），配置缺席/异常不设环境变量，QML 侧落 canvas ✓
- `get_config()` 未初始化时抛 RuntimeError（config_manager.py:39-44），被该 except 捕获——"配置未初始化跳过"实测成立 ✓
- VISION 默认关闭语义不变：引擎解析与 `VISION.ENABLED`（缺省 False）互不影响；sandbox 环境变量只影响渲染进程能力，不改变任何开关默认值 ✓

## 3. fetch 脚本供应链 — **PASS**

- **sha256 强校验**：JS 三库 curl 后逐文件比对硬编码哈希、不匹配即 `exit 1`（fetch_avatar_runtime.sh:37-43）；Hiyori 18 文件走 api.github.com Git Blobs API（base64 二进制安全，规避 Contents API 1MB 截断），下载后逐文件 sha256 校验（:142-147）+ 遍历后完整性兜底复检（:155-159）——改动任一文件必失败 ✓
- 无 `curl | bash` 模式（仅 `curl -o 文件`）；无任何密钥读写/传输操作；`set -euo pipefail` + mktemp/trap 清理 ✓
- **幂等**：已存在且哈希匹配即 SKIP（:31-34、:136-138），实测本机 vendor 三 JS 库 shasum 与脚本清单逐一吻合（25ae93…/403f2f…/af1267…）✓
- **gitignore 实测**：`git check-ignore -v` 对 vendor 内 4 个文件（2 JS 库 + moc3 + model3.json）全部命中 `client/.gitignore:50:src/avatar/runtime/vendor/` ✓
- **入库清单 dry-run**：`git add -A --dry-run` 实测 **25 个文件**，除 backups/ 5 文件外全部为文本（.py/.qml/.js/.html/.md/.sh/.gitignore）——**但发现 F5 阻塞项，见"新发现缺陷"**。

## 4. 回归测试矩阵（全部本机实跑，2026-10-09）

| 套件 | 运行方式 | 结果 |
|---|---|---|
| client/src/vision/tests/test_vision_module.py | client/ 目录直跑（自执行脚本） | **13/13 PASS** |
| gateway/tests/vision_v0_tests.py | gateway/.venv/bin/python | **15/15 PASS** |
| gateway/tests/v05_e2e_tests.py | 同上 | **8/8 PASS** |
| gateway/tests/product_v1_integration.py | 同上 + `DYLD_LIBRARY_PATH=client/libs/libopus/mac/arm64` | **33/33 PASS** |
| prototypes/tests/avatar_logic_tests.mjs | node（prototypes/ 目录） | **16/16 PASS** |
| prototypes/tests/vision_logic_tests.mjs | node | **17/17 PASS** |
| client/src/avatar/tests/test_avatar_engine.py（新增） | client/ 目录直跑 | **11/11 PASS** |

合计 **113/113**，零 FAIL、零 SKIP。

## 5. 冻结面 — **PASS**

- `git diff --stat -- gateway/app/audio.py gateway/app/turns.py client/src/audio_codecs client/src/plugins/audio.py client/src/core client/src/protocols` 输出 **0 字节**（实测）✓
- 已跟踪改动收敛在 7 文件：.gitignore / vision.py / manager.py / VisionPanel.qml / MainWindow.qml / qml_host.py / qml_bridge.py，均不在冻结路径 ✓

## 6. 引擎切换语义与生命周期 — **PASS（附 F6）**

- 四路径实测（单测 11 断言 + 逻辑审读）：
  1. **bridge 缺席**：manager.py:63-65 仅在 VISION_BRIDGE 存在时注入 `avatarEngine`；缺席时 MainWindow.qml:24 `typeof avatarEngine === "undefined"` → 默认 "canvas-fallback" → canvas Loader ✓
  2. **配置缺失**：ConfigManager.get_config 缺键返回 default（config_manager.py:409-410）→ live2d → 由 vendor 资产门控；**vendor 缺（git 不带 vendor，出厂/新 clone 恒缺）→ canvas-fallback + reason "运行时资产缺失"** ✓（出厂语义安全；见 F6 的默认值语义备注）
  3. **非法值**：`webgl3` 等一律 canvas-fallback + reason 含原始值（engine.py:53-54）✓
  4. **vendor 缺文件**：单文件缺失（含 3b 缺 moc3 细分用例）即整组回退 + reason 指明缺失文件（engine.py:59-61）✓
- apply_engine 二次防御：非白名单值强转 canvas-fallback（qml_bridge.py:73-75）；日志 `AVATAR engine=...（reason）` 不含敏感数据 ✓
- **双 Loader 切换无泄漏**：VisionPanel 两 Loader active 互补（`=== "live2d"` / `!== "live2d"`），切换时 Loader 自动销毁旧实例；AvatarLive2D `Component.onDestruction` 停止加载 + destroyInstance + clearHttpCache（AvatarLive2D.qml:87-92，均 try/catch 包裹，销毁期 runJavaScript 失败无害——WebEngineView 随组件整体销毁，渲染进程与 WebGL 上下文由框架回收）✓
- 同名遮蔽规避：avatarEngineAlias 根级别名与 visionBridgeAlias 同模式（MainWindow.qml:23-24），VisionPanel 内 `root.avatarEngineAlias` 显式引用 ✓

## 7. 新发现缺陷

- **F5（major，提交阻塞项，非代码缺陷）**：`git add -A --dry-run` 实测入库清单 25 文件中含 `backups/XIAOZHI-VOICE-V1-HUMAN-ACCEPTED/` 5 文件，其中 **repo.bundle 为 60MB Git bundle 二进制**（本地验收备份产物；mac_client_config.json 已核查无真实凭据——VLapi_key/MUSIC.URL_API_KEY 均为空串，WEBSOCKET_ACCESS_TOKEN 10 字符非密钥形态）。与"入库清单零二进制"的交付声明不符；60MB bundle 一旦入库将永久膨胀仓库历史。**整改**：提交前将 `backups/` 加入根 .gitignore（或移出仓库目录/删除），剔除后清单 20 文件全文本、声明即成立。其余 20 文件逐一核对均为预期交付物。
- **F6（minor，语义一致性，不阻断）**：`DEFAULT_ENGINE = live2d`（engine.py:11）使"配置系统缺席/键缺失 + vendor 齐备"路径解析为 live2d，与模块 docstring 自述"配置缺失……一律回退 canvas-fallback"（engine.py:4-5）及本复核任务的四路径声明不符——fail-safe 缺省应为 canvas（opt-in 启用 live2d）。实际风险有限：git 永不带 vendor，出厂/新 clone 该路径必经资产门控落 canvas；且 qml_host/插件两处解析同用一函数，无发散。建议二选一：改默认值为 canvas-fallback，或修订 docstring 明示"缺省 live2d + 资产门控"。
- 前轮 F2/F3/F4 在 HEAD 未变，维持 advisory，不阻断。

## 集成复核总体判定

**不可提交（现状）——唯一阻塞项 F5：`backups/`（60MB repo.bundle 二进制）会被 `git add -A` 收进提交，与交付声明不符且有仓库历史永久膨胀风险。**

剔除 backups/（加 ignore 或移出）后即可提交：代码面全部 PASS——JS 注入面无注入路径、页面零外部请求零 eval、沙箱禁用仅 live2d 时本进程生效且异常静默降级、fetch 脚本强校验幂等无供应链风险、vendor 实测被忽略、冻结面零字节、引擎四路径出厂语义安全、Loader 销毁路径无泄漏、回归 113/113 全绿。F6 为 advisory，建议随本次或下轮整改。
