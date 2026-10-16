# V06_PROTOCOL_ARCHITECTURE — 协议架构只读审计（V0.6 Mac 原生切片）

- date: 2026-10-09 UTC
- head: `f518778`（branch `avatar-vision-v06-mac-native`）
- 编制: v06-proto-arch（只读审计代理；本文件为唯一写入物）
- 结论先行: **冲突成立，裁决为保留独立 HTTP 视觉端点；WS `vision_image` 消息不可行**（WS JSON 帧硬上限 64KB，一张合规 JPEG 的 base64 约 253KB，超限 4 倍）。链路本身完整，唯一缺口是**会话亲和（session affinity）**：客户端已携带 `session_id`，网关却完全忽略并任取第一个已连接实例——按简报禁令，必须补齐按会话绑定（方案 a），辅以单活跃会话不变量（方案 b）。

---

## 1. CHAIN_CONFIRMED — 现行 HTTP 链路（file:line 实证）

**客户端 → 网关 HTTP（8111 平面）→ Qwen 上游，三段全部在位且已测试：**

1. **HTTP 入口** `gateway/app/http.py:53-99` `make_vision_handler(config)`，路由注册于 `gateway/app/main.py:72`
   （`add_post("/xiaozhi/vision/", ...)`，紧邻既有 `/health` main.py:69 与 `/xiaozhi/ota/` main.py:70）：
   - 鉴权：`X-Vision-Token` 头（http.py:65）对 `secrets/vision_token`（http.py:54-55，`VISION_TOKEN_FILE`
     环境变量可覆盖）做 `hmac.compare_digest` 恒时比较（http.py:67-68）→ 401 `invalid_token`；
   - 体长上限 **320KB**（http.py:71-73，`content_length > 320*1024` → 413 `payload_too_large`），
     在 base64 解码之前先行拦截（aiohttp 默认 1MB 永远不会触及）；
   - 解析守卫：`bad_json` / `image_b64_missing` / `bad_base64` → 400（http.py:74-87）；
   - 转发：`qwen.submit_vision_image(raw)`（http.py:88-89）；
   - **状态映射**（http.py:92-97，与 GATEWAY_PROTOCOL_DESIGN.md:109-119 对齐）：
     `not_jpeg→415`，`too_large_raw/too_large_b64→413`，`rate_interval/rate_per_minute→429`，
     `ordering_audio_first→409`，`not_connected→503`，其余兜底 422。
2. **注册表转发** `gateway/app/qwen.py:815` `_ACTIVE_INSTANCES`（模块级集合）+
   `qwen.py:818-827` `submit_vision_image()`：遍历注册表，**取第一个 `_connected and _ws is not None`
   的实例**（qwen.py:824-826）；无连接 → `(False, "not_connected")`。音频/VAD/turns 零触碰
   （qwen.py:822 明示，turns.py 冻结不变）。
3. **五重上游守卫** `gateway/app/qwen.py:712-743` `QwenClient.send_image()`：
   未连接 :715-716；JPEG 魔数 `ff d8 ff` :717-720；raw ≤190KB :700,721-723；
   **排序前提 `_audio_seen`** :724-727；间隔 ≥5s :728-731；≤6/min :732-735；
   b64 ≤256KB :736-739；通过后发官方事件
   `{"type":"input_image_buffer.append","image":<b64>}` :740-743。任何拒绝均不触碰音频路径。

**WS 平面为什么不可行（冲突裁决依据）**：`gateway/app/protocol.py:6`
`MAX_JSON_BYTES = 65536`——WS 文本帧 64KB 硬上限；190KB raw JPEG ≈ 253KB base64，
超限约 4 倍。放大 WS 上限会把新增的大额分配引入每一帧客户端解析（冻结音频面的
DoS 暴露面，GATEWAY_PROTOCOL_DESIGN.md:28-31 论证）。故 MAC_CLIENT_AUDIT.md:86-108
的 WS_MESSAGE_SPEC（`vision_image` 文本帧 ≤60KB）**被裁决否决**，保留独立 HTTP 端点；
客户端现实现（`client/src/vision/controller.py:51-59`，POST JSON + `X-Vision-Token`）
与网关一致，无需回退。

## 2. SESSION_AFFINITY_FIX — 会话亲和缺口与修复 = **a + b 组合**

**GAP（实证）**：客户端已发送会话标识——`client/src/vision/controller.py:52`
请求体含 `"session_id": self.session_id`（构造时绑定，跨会话提交被拒，
controller.py:3-4）；但网关 `http.py:74-89` **从不读取 `session_id`**，
`submit_vision_image`（qwen.py:824-826）在多实例注册表中**任取第一个已连接实例**。
注册表是 set（qwen.py:815），多会话并存时归属不确定——简报明确禁止任意选择会话。
这与 GATEWAY_PROTOCOL_DESIGN.md:43-48 的既定口径（`session_id` 可选；缺省时要求
**恰好一个**活跃连接，歧义 → 409 `ambiguous_session`；提供但未命中 → 404
`unknown_session`）直接背离——实现缺失了整段会话解析。

**修复（a，主路径——按会话绑定）**：HTTP 请求体 `session_id` 与 QwenClient 会话标识
精确匹配。会话标识现成可用：`gateway/app/qwen.py:310` `self._qwen_session_id`，
在 `session.created` 时捕获（qwen.py:492-493）。机制：`submit_vision_image(jpeg_bytes,
session_id=None)` 增加参数——`session_id` 非空时遍历 `_ACTIVE_INSTANCES` 取
`inst._qwen_session_id == session_id` 且已连接的唯一实例；未命中/未连接 →
`(False, "unknown_session")` → HTTP **404**。
**修复（b，兜底——单活跃会话不变量）**：请求缺省 `session_id` 时，要求恰好一个
已连接实例：0 个 → `(False, "not_connected")` → **503**；≥2 个 →
`(False, "ambiguous_session")` → **409**（禁止静默任选）。两分支均在
`submit_vision_image` 内完成，`turns.py`/音频面零改动，注册表仍为只读遍历
（GATEWAY_PROTOCOL_DESIGN.md:46-48 的 observer-only 不变量保持）。

## 3. CLIENT_AUTH_PROVISION — Mac 客户端如何取得/存储视觉令牌

- **来源：本地配置项，独立预配，不走 OTA，绝不复用 Admin Token。**
  `client/src/vision/__init__.py:6-9`：`VISION.ENABLED`（默认 **False**，关闭时模块不加载、
  不申请摄像头、零网络请求，启动路径与冻结语音链路逐字节一致）、`VISION.TOKEN`
  （:8，注释明示"独立令牌，绝不复用 Admin Token"）、`VISION.ENDPOINT`
  （:9，默认 `http://127.0.0.1:8111/xiaozhi/vision/`）。
- **存储**：经客户端既有 ConfigManager（点路径读写，缺键返回默认值，
  MAC_CLIENT_AUDIT.md:53-57）落在本地配置文件，随 `VisionController(endpoint, token,
  session_id, enabled)` 构造注入（controller.py:12-16；测试同型
  client/src/vision/tests/test_vision_module.py:51,107）。
- **使用**：每次提交以 `X-Vision-Token` 头携带（controller.py:56），网关侧恒时比较
  （http.py:67-68）。**规则：永不使用 Admin Token**——网关侧密文是独立文件
  `secrets/vision_token`（http.py:54-55，admin 令牌文件为 `secrets/admin_api_token`，
  GATEWAY_PROTOCOL_DESIGN.md:62-64）；OTA 的公开 `test-token`（http.py:38-44）同样被排除
  （GATEWAY_PROTOCOL_DESIGN.md:18-19,71-72）。令牌缺失 → 网关 fail-closed 401
  （http.py:67-68，`not expected` 即拒）。
- **获取途径（部署）**：网关部署时以 `secrets/vision_token` 预配随机令牌；运维把同一
  令牌写入客户端 `VISION.TOKEN` 配置（新配文件，非升级迁移；`VISION.ENABLED` 默认
  false，旧配置天然兼容，MAC_CLIENT_AUDIT.md:123-133 同型论证）。

## 4. TIMING_ORDERING — 音频先行的时序规范

- **上游官方约束**：至少一个 `input_audio_buffer.append` 先于首帧图像
  （qwen.py:691-694 注释；VISION_PROTOCOL_REPORT.md:48）。网关执行：
  `send_append` 置 `_audio_seen=True`（qwen.py:688，每新会话复位，qwen.py:463），
  `send_image` 在 :724-727 强制，违反 → `ordering_audio_first` → HTTP 409。
- **提交时序**：图像随**下一次** `input_audio_buffer.commit` 一并提交（server_vad 由
  上游在用户说完时发出，GATEWAY_PROTOCOL_DESIGN.md:130-147）：用户发图后保持沉默 →
  图像驻留上游图像缓冲，等待下一轮；发图与"让小智看看"同轮 → 图像+语音并入当前
  turn 的 commit。
- **客户端义务：retry-after-next-speech（说后再试）**。收到 409 `ordering_audio_first`
  时，客户端**不得**在网关内排队自动重试（静默队列会把陈旧图像复活进无关轮次，
  GATEWAY_PROTOCOL_DESIGN.md:153-156）；客户端契约同型：`controller.py:39` 顺序前提
  "调用方必须已确认本轮存在音频 append（409 → 提示先说话）"。正确动作 = 用户下一次
  说话后（音频 append 持续流动使 `_audio_seen` 置位）重发同一帧。
- **重连复位**：Qwen 重连即新会话，`_audio_seen=False` 重新 enforcing（qwen.py:463）；
  竞态关闭 → 503 `not_connected`（GATEWAY_PROTOCOL_DESIGN.md:190-193）。

## 5. CLIENT_ERROR_TABLE — 客户端错误反馈表（状态/原因 → 中文文案）

| HTTP | reason（网关原样回传） | 客户端中文文案（一次性提示，不自动重试） |
|---|---|---|
| 401 | `invalid_token` | 视觉令牌无效或未配置，请检查 VISION.TOKEN |
| 400 | `bad_json` / `image_b64_missing` / `bad_base64` | 图像数据无效，请重新截取后再试 |
| 413 | `payload_too_large` / `too_large_raw` / `too_large_b64` | 图片过大，请缩小分辨率后重试（raw ≤190KB） |
| 415 | `not_jpeg` | 仅支持 JPEG 图像，请重新保存为 JPG |
| 429 | `rate_interval` | 发送太频繁，请等待约 5 秒再试 |
| 429 | `rate_per_minute` | 每分钟最多 6 张，请稍后再试 |
| 409 | `ordering_audio_first` | 请先说一句话，再让小智看（说后再试，勿自动重试） |
| 409 | `ambiguous_session` | 检测到多个会话，请在请求中携带 session_id |
| 404 | `unknown_session` | 会话已失效，请重新连接后再试 |
| 503 | `not_connected` | 小智尚未连接，请先连接设备 |
| 422 | （兜底 reason 透传） | 提交被拒绝，请稍后重试 |
| 0 | `network_error`（controller.py:68-71） | 网络错误，请检查网关地址 VISION.ENDPOINT |

反馈纪律：任何失败经 `on_error` 回调上报（controller.py:65-70），**绝不影响语音路径**；
文案一次性展示，不循环弹窗。

## 6. 遗留与验收钩子（非阻塞）

- `input_audio_buffer.clear` 是否清空图像缓冲：官方文档未述，UNCERTAIN
  （GATEWAY_PROTOCOL_DESIGN.md:184-188）；V0 网关图像路径从不发 clear，分支不可达。
- 200 受理后立即断连的半开窗口：图像已交上游、所属 turn 随会话丢失——固有语义，
  已记录不工程化（GATEWAY_PROTOCOL_DESIGN.md:193-197）。
- 验收沿用设计稿 H1-H8（GATEWAY_PROTOCOL_DESIGN.md:216-231），新增 H7 会话解析
  双分支（多连接无 session_id → 409 `ambiguous_session`；陈旧 session_id → 404
  `unknown_session`）为本审计的**必测项**。

---

## VERDICT

**PASS（有条件）**——保留独立 HTTP 视觉端点（裁决 WS `vision_image` 不可行，
protocol.py:6 的 64KB 帧上限是硬约束）；链路鉴权/体长/五重守卫/时序均已实证在位；
**唯一必须补齐的改动是会话亲和**：`submit_vision_image` 增加 `session_id` 精确匹配
（方案 a）+ 缺省时单活跃会话不变量与 409 `ambiguous_session`（方案 b），
客户端已发送 `session_id`（controller.py:52），改动收敛在 qwen.py:818-827 与
http.py 一处状态映射，音频面零触碰。补齐前，多会话场景的图像归属为未定义行为——
不阻塞 V0 单设备部署，但为 V1 多会话的硬前提。
