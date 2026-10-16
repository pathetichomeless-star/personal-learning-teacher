# VISION / AVATAR V0 安全与隐私需求审计（只读预实现审计）

- 审计对象：vision V0（用户主动图像 + 单帧摄像头采集 → Qwen 会话识别）与 avatar V0（纯本地渲染）
- 审计方式：纯只读代码审计，本报告为唯一写入产物；分支 `admin-visual-v2` @ `e51d9a5`
- 日期：2026-10-09
- 代码基线：`client/`（py-xiaozhi Mac 客户端）、`gateway/app/`（WS/session 面）、摄像头/OS 权限机制
- 标记约定：`EXISTING` = 现有代码已提供机制（附 file:line）；`NEW` = V0 必须实现

---

## THREAT_MODEL

信任边界与资产：

1. **图像是高敏资产**：单帧摄像头画面可能包含人脸、屏幕内容、室内环境、文件文字。默认状态必须是"零捕获"，任何一帧的存在都需可归因到一次用户显式动作。
2. **LAN 信任模型（现状）**：WS 端点 `/xiaozhi/v1/` 无 Bearer 校验（gateway/app/ws.py:13-33；OTA 下发 `token: "test-token"`，gateway/app/http.py:35-39），网关绑定 `0.0.0.0`（gateway/app/main.py:101）。客户端确实发送 `Authorization: Bearer` 头（client/src/protocols/websocket_protocol.py:34-41），但网关侧未验证 —— 即 **当前 WS 的信任边界是"局域网内即信任"**。admin 控制台则有完整恒时比较 + fail-closed 鉴权（gateway/app/admin/auth.py:84, 122-138），两者安全等级不一致。V0 的图像不得把信任边界降得更低。
3. **现实有图像出网先例**：现行 `VLCamera` 直接把 base64 JPEG 发往第三方 VL API（智谱 glm-4v-plus，client/src/mcp/tools/camera/vl_camera.py:57-91），**绕过 Qwen 会话与网关**。V0 改走 Qwen 会话后，必须确认这条旁路被关闭/不再注册，否则形成未审计的图像外发通道。
4. **攻击者视角**：
   - 恶意 LAN 主机 → 若 vision 走新 HTTP 端点，可尝试未授权提交图像/打爆计费；
   - 会话串扰 → 图像帧注入到他人 session（session_id 为服务端生成的 uuid4，gateway/app/protocol.py:9-10，turns.py:192, 432 每连接私有）；
   - 计费放大 → 图像 token 远贵于语音，自动重试/连续采集可烧穿免费额度（docs/reference/config.yaml:644；evidence/model_switch_plus_state.txt:3 确认 free-tier stop 机制）；
   - 持久化残留 → 帧落盘/入日志/入记忆文件（MEMORY_FILE，gateway/app/main.py:36）造成隐私留存。
5. **macOS TCC**：仓库内无 Info.plist / NSCameraUsageDescription（grep 零命中）。OpenCV 经 AVFoundation 触发系统弹窗，权限挂在宿主解释器/终端二进制上；权限拒绝时现状只打日志（capture_backend.py:181-182, 204-205），无用户可见提示。

---

## REQUIREMENTS_R1_R10

### R1 摄像头：默认关、显式点击触发、状态可见、可停、权限拒绝处理
- **默认 OFF**：`NEW`。现状 `take_photo` 是 **LLM 语音触发** 的 MCP 工具（client/src/mcp/tools/camera/register.py:35-46, 48-71），用户说"看看"即可采集 —— 不满足 V0 "仅显式点击"。V0 必须提供 GUI 拍照按钮为唯一触发源，且 V0 期间不注册 `take_photo` 工具（或以配置显式禁用）。
- **单帧后释放**：`EXISTING`。`capture_jpeg` 打开设备→读帧→`cap.release()`（finally，capture_backend.py:216-220）并在 12s 超时保护下于一次性线程池执行（capture_backend.py:307-316）—— 设备不会长持；V0 沿用此单发模式。
- **可见状态指示 / STOP**：`NEW`。指示"采集中→已发送→完成"三态；STOP 等价于取消在途上传/推理，因单帧模式天然短命，STOP 只需丢弃缓冲（见 R6/R9）。
- **权限拒绝处理**：`NEW`。OpenCV 打开失败目前仅 log（capture_backend.py:181-182, 204-205）；V0 必须把失败映射为 GUI 明确文案（"macOS 未授予相机权限：系统设置→隐私与安全性→相机"），并保持语音主回路不受影响。

### R2 图像限制：JPEG-only、尺寸/字节上限、EXIF 剥离、类型嗅探、超限拒发
- **JPEG 编码即剥离元数据**：`EXISTING`（采集路径）。帧经 `cv2.imencode(".jpg", ...)` 重新编码（capture_backend.py:143），产物为全新 JPEG，天然不含 EXIF/GPS；默认 320px 长边 + resize（capture_backend.py:36, 129-146）远低于上限。
- **类型嗅探**：`NEW`。对任何外部来源图像（用户选择文件 / 剪贴板）做 magic-byte 检查（`FF D8 FF`），不得只看扩展名。
- **上限**：`NEW`（数值提案）。长边 ≤1280px、字节 ≤300KB；编码后超限先本地降采样再编码，仍超限则拒绝并提示，**不得在任何网络发送之后才发现超限**。
- **传输容量硬约束（设计必读）**：网关 JSON 文本帧有 64KB 硬帽 `MAX_JSON_BYTES`（gateway/app/protocol.py:6, 23-24）。300KB JPEG → base64 ≈ 400KB，**必超帽**。V0 图像必须走 WS binary 帧（现仅音频使用，turns.py:510）或为图像消息单独设帽，不得为图像放宽全局 JSON 帽。

### R3 速率限制：无连拍、无流式、无自动采集
- `NEW`。提案：**每 session ≤6 次/分钟，且两次采集间隔 ≥5s**；超限禁用按钮并显示倒计时。V0 无任何连续流式采集（现状也无：每次 capture 都是单帧，capture_backend.py:287-316）；无定时器/后台线程自动触发（V0 禁止引入）；v0 也不得把 `take_photo` 的语音触发与按钮触发叠加成双通道绕过限速 —— 限速计数必须覆盖所有触发源。

### R4 会话隔离：图像只属于当前 session
- **每连接私有 session_id**：`EXISTING`。session_id 服务端 uuid4 生成（protocol.py:9-10）、绑定 Connection 实例（turns.py:192, 432），连接关闭即销毁（turns.py:489）；admin 侧对外仅暴露哈希（api.py:651-694，见 SECURITY_AUDIT_REPORT.md）。
- **附加约束**：`NEW`。V0 图像帧必须携带当前连接 session_id 并由网关校验一致后才 append 给 Qwen；不匹配一律丢弃并计数。**禁止** vision 内容写入 MEMORY_FILE / KNOWLEDGE_FILE / POLICY_FILE（gateway/app/main.py:36-39）——跨会话记忆写入通道在 V0 对图像关闭。

### R5 无未授权采集：无后台线程、无磁盘帧、无图像遥测
- **无磁盘写入**：`EXISTING`。client 全 src grep 无 `imwrite`/帧落盘；截图走内存 BytesIO（client/src/mcp/tools/screenshot/screenshot_camera.py:146, 202, 339）。
- **日志不含图像内容**：`EXISTING`。仅记录字节数（base_camera.py:54-56）；网关日志对长 base64/令牌形态字符串有脱敏正则（gateway/app/qwen.py:79-81），V0 保持"只记 size/结果，不记内容"。
- **无静默遥测**：`NEW`。admin 观察面（ADMIN-1）是 lifecycle-only 注册、无热路径数据（ws.py:17-18）；V0 不得把图像字节或衍生描述喂给任何计数器/诊断快照（diag.py 的 SNAPSHOT 保持无图像字段）。

### R6 存储：图像即逝（memory-only），生命周期明确
- **内存即逝**：`EXISTING`（机制）。jpeg_data 仅是内存 dict（base_camera.py:25），覆盖写、不落盘。
- **V0 明确定义生命周期**：`NEW`。帧从点击采集 → 编码 → 上传 → Qwen 会话消费后**立即丢弃**（del 引用，不进入任何缓存/重试队列）；用户显式"保存"是唯一落盘路径，保存时提示含位置信息风险（若来源帧带 EXIF）。会话结束/连接断开时缓冲区必须清空（turns.py:489-493 的 close 路径）。

### R7 云成本/配额：每次采集计数 + 免费额度停止保护 + 无自动重试
- **计数基础设施**：`EXISTING`。counters `inc/gauge/snapshot`（gateway/app/counters.py:127-160）已在 `/health` 暴露（http.py:13-14）；V0 新增 `vision_captures_total`、`vision_bytes_total`、`vision_rejects_total{reason}`。
- **free-tier stop**：`EXISTING`（云侧机制，PO 已确认开启，evidence/model_switch_plus_state.txt:3；docs/reference/config.yaml:644）。V0 客户端/网关不替代它，但必须**不绕过**：`NEW` 禁止对图像推理失败做自动重试（Qwen 重连退避已有上限 5 次机制，gateway/app/main.py:31，图像消息不得独立加重试环）；单帧失败直接降级（R9）。GUI 显示本次会话累计采集次数（消费客户端侧计数或 /health 计数）。

### R8 Avatar：纯本地渲染、无相机/麦克风、无网络
- `NEW`（V0 全量）。现状仅 admin 控制台有"数字人（预留）"disabled 入口，无任何功能（UI_DESIGN_REPORT.md:197-209）——即 avatar 无既有代码，V0 从零构建并遵守：不打开任何 AVCapture/AVFoundation 音视频会话；零网络调用（无 fetch/WebSocket/CDN 资源）；渲染素材本地打包；**不读**语音回路之外的任何设备状态。avatar 崩溃不得波及语音主进程。

### R9 失败模式：视觉降级为纯语音，无残留状态
- **主回路独立**：`EXISTING`。语音 loop（turns.py 的 turn/pacing/backlog：MAX_FUTURE_FRAMES=1500、MAX_FUTURE_AUDIO_BYTES=512KB，turns.py:41-42, 889-910）与图像无耦合；现状 VL 失败也是返回 JSON 错误而非崩溃（vl_camera.py:103-106）。
- **V0 约束**：`NEW`。采集/上传/推理任一步失败：GUI 回到"待机"态、显示一次性错误文案、清空图像缓冲（R6）、释放设备（finally release 已有，capture_backend.py:216-220）、计数 `vision_rejects_total`；语音会话保持可用。**禁止**失败后留下半开的"视觉会话"状态或阻塞 audio 线程。

### R10 网关侧：任何新端点必须复用现有鉴权等级
- **WS 路线（推荐）**：`EXISTING`。复用既有 `/xiaozhi/v1/` 连接与 hello 握手（ws.py:13-33, turns.py:501-502, 554-558），图像作为该连接内的 binary/扩展消息 —— 不新增端口、不新增监听器（main.py:97-103 面不变），信任面不扩大。
- **若走 HTTP 新端点**：`NEW`，全部满足：`Authorization: Bearer` + `hmac.compare_digest` 恒时比较（复用 gateway/app/admin/auth.py:84, 122-138 模式）；绑定沿用既有 listener/ADMIN_BIND 且不得放宽（main.py:101；compose LAN-only 约束见 deploy/product-sidecar/docker-compose.yml:24, 49）；body 大小帽（admin 现行 64KB 先例，api.py:46, 118-120；图像按 R2 上限单独设帽）；每 IP/session 限速（R3 同值）。**注意**：现状 WS 不校验 Bearer —— 若 V0 图像走 WS，建议顺带在网关 hello 阶段校验客户端已发送的 Authorization 头（websocket_protocol.py:41），把 LAN 信任模型收紧一档；此项为 V0 可选加固、非阻塞项。

---

## DATA_LIFECYCLE

```
[用户点击] → 采集(单帧, 12s超时, 设备即释放)        capture_backend.py:287-316, 216-220
        → 内存 JPEG (≤1280px/≤300KB, 重编码已剥离EXIF) capture_backend.py:129-146
        → 上传(WS binary, 会话内, 限速)                R3/R10
        → Qwen 会话消费(推理, 不写记忆/知识/策略文件)     R4
        → 立即丢弃（引用清除, 不缓存不重试）              R6/R7
失败任一步 → 丢弃 + 降级语音 + 计数                  R9
用户显式保存 → 唯一落盘路径（提示风险）               R6
会话结束/断开 → 缓冲清空                            turns.py:489-493
落盘/日志/遥测默认态：零                            R5（grep 验证无 imwrite；日志仅 size）
```

唯一例外通道：现行 `VLCamera → 智谱 API` 直连外发（vl_camera.py:57-91）**必须**在 V0 中停用/不注册，否则生命周期图不成立（数据绕过上述全部环节直出公网）。

## COST_GUARDS

1. 每次 GUI 采集（所有触发源）过同一限速器：≤6 次/分钟、间隔 ≥5s（R3）。
2. 网关计数 `vision_captures_total / vision_bytes_total / vision_rejects_total`，经既有 /health 可查（R7）。
3. 图像推理失败**零自动重试**；Qwen 重连沿用既有退避上限（main.py:31），不叠加图像专属重试。
4. 云侧 free-tier stop 已开启为最后闸门（model_switch 证据）；V0 的 GUI 计数器让用户可见消耗，形成人为止损层。
5. 300KB/1280px 上限 + WS binary 传输，防止单帧 token 放大失控；禁止放宽全局 64KB JSON 帽（protocol.py:6）。

## VERDICT

**PASS（附条件放行）** —— 现有基线对 V0 有利：采集已是单帧+超时+即释放、无落盘、日志无图像内容、会话隔离机制完备、counters 免费可复用。V0 前必须落实的硬条件：① 关闭 `take_photo` 语音触发与 VLCamera 直连外发旁路，采集唯一入口为用户点击；② 实现类型嗅探/上限/限速/生命周期五件套（R2/R3/R6）；③ 图像传输不得突破 64KB JSON 帽（走 binary）；④ 失败降级不残留状态（R9）；⑤ avatar 零网络零设备（R8）。Bearer 校验在 WS hello 的收紧为建议项（R10 注）。
