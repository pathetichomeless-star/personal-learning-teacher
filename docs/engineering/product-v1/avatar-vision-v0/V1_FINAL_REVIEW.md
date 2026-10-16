# V1_FINAL_REVIEW

date=2026-10-09 · head=203b14c (docs 569070d) · branch=avatar-vision-v06-mac-native · 基线=f518778
reviewer=v1-final-review（独立只读安全+QA 复核；唯一写入=本文件）

## BOUNDARY

- V1.0 delta（203b14c）= 7 文件、+381/-8，全部加法式：qml_bridge.py / plugins/vision.py / AvatarCanvas.qml / VisionPanel.qml + 触点×3（plugin_wiring.py 注册、manager.py 防御注入、MainWindow.qml Loader）。
- 冻结面实测：`git diff d5644f1..203b14c -- gateway/app/audio.py gateway/app/turns.py client/src/audio_codecs client/src/plugins/audio.py client/src/core client/src/protocols` = **零字节**。
- 触点最小化确认：plugin_wiring 仅 +4 行（import+注册）；manager.py 仅在 inject dict 追加防御性 try/import；MainWindow 仅新增 Loader（`typeof visionBridge !== "undefined"` 时才 active——bridge 缺席即 inactive，零实例化）。
- 音频路径无任何订阅侵入：VisionBridge 的事件入口（onTtsStart/onTtsStop/onInterrupted）是独立 Slot，由调用方主动推送，冻结链路零改动。

## SECURITY

- **令牌面**：X-Vision-Token 全 diff 唯一使用点 = qml_bridge.py:173（HTTP header）；`token` 不进日志（日志仅 `enabled=%s`，qml_bridge.py:113 / vision.py:35）、不进 QML 属性、不进 URL/query/body。✓
- **Admin Token 隔离**：视觉路径无任何 Admin Bearer/Admin 头引用（grep 证实，仅文档提及"绝不复用"）；网关 http.py:65-70 仅读 `secrets/vision_token`，恒时比较 + fail-closed（expected 空 → 401）。✓
- **图像字节零落盘**：diff 内无 wb/imwrite/tofile/write(raw|b64)——唯一文件操作为 `open(path,"rb")` 只读。✓
- **默认关闭**：`VISION.ENABLED` 缺省 False（vision.py:25-27）；enabled=False 时 submitImagePath 直接早退（qml_bridge.py:118-121），零网络；Loader inactive，无摄像头枚举/TCC 弹窗。✓
- **客户端守卫**：JPEG magic（\xff\xd8\xff）/≤190KB/5s 间隔/6-per-min 滑窗/8s 超时，双端（客户端+网关）各有一套，纵深成立。
- F2（minor）：threading_submit 的 done 回调在后台线程直接改 `_status` 并 emit 信号（qml_bridge.py:155-160）。Qt 信号跨线程投递为 queued、实际安全，但属"靠框架保证"而非显式排队，建议 V1.1 用 QMetaObject.invokeObject/信号中转显式化。

## HONESTY

- 报告声明与实物一致：明确"QML Canvas 参数驱动分层 2D rig ≠ Live2D Cubism"（V1_RELEASE_REPORT 引擎决策节 + V1_LIVE2D_LICENSE_EVALUATION VERDICT=fallback-2d-rig）；口型=协议包络近似（8-14Hz 计时器 12.5Hz tick）在面板内黄字自曝（VisionPanel.qml:41）；真实 RMS=冻结链路例外待 PO 批。
- 待人工验收清单诚实列出：真机 GUI 启动/面板操作/TCC 三分支/主观口型/真实 Qwen 识别，且明示"不得伪造通过"。门禁：未部署 NAS、未合并 main、零真实 Qwen 调用、零计费。✓
- Live2D 评估文档为官方来源逐条引用（Publication License / Expandable Application / AI-Chatbot 类别 / 样例模型条款），"MIT 不漂白专有 Core"结论正确。

## TESTS（本复核全部实跑）

| 套件 | 结果 |
|---|---|
| gateway tests/vision_v0_tests.py | 15/15 PASS |
| gateway tests/v05_e2e_tests.py | 8/8 PASS |
| gateway tests/product_v1_integration.py | 33/33 PASS |
| prototypes/tests/avatar_logic_tests.mjs | 16/16 PASS |
| prototypes/tests/vision_logic_tests.mjs | 17/17 PASS |
| client src/vision/tests/test_vision_module.py | 13/13 PASS |
| 离屏 QML 加载（QT_QPA_PLATFORM=offscreen，QQmlComponent 双文件） | 零错误（AvatarCanvas/VisionPanel 均 create 成功） |

## FINDINGS

- **F1（条件项，非阻断）**：vision.py:30 硬编码 `token=""`，未从 `ctx.config` 读取 `VISION.TOKEN`（V06 协议文档已定义该本地独立配置键）。后果：运行时任何测试图提交 → 网关 401 invalid_token，提交链路实际不可用（数字人口型/状态部分不受影响）。属 fail-closed 安全默认，无泄漏风险；但"启用视觉→提交成功"的真实闭环依赖 V1.1 补上配置读取。发布报告将"真实 Qwen 单图识别"列为待 PO 验收，部分覆盖此缺口，唯 token 配置接线未显式点名。
- F2（minor）：见 SECURITY——后台线程回调直接 emit，建议显式排队。
- F3（info）：vision.py:42 资源池注册 `bridge._env_timer.stop` 触碰私有成员；VisionPanel 测试图路径硬编码 /tmp/vision_test.jpg；AvatarCanvas 常驻 state= 调试角标——均为原型可接受项。

## VERDICT = PASS-with-conditions

条件：在启用任何真实视觉提交前（V1.1），VisionPlugin 必须从配置读取 `VISION.TOKEN` 注入 VisionBridge，替换硬编码空串；同时保留默认关闭与 fail-closed 行为不变。除此之外无安全缺陷、无诚实性问题、无冻结面破坏、102/102 测试全绿。
