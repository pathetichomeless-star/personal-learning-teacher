# VISION/AVATAR V0.5 安全需求与 QA 测试设计（V05_SECURITY_QA_TEST_DESIGN）

- 基线：branch `avatar-vision-v0` @ `fec64a8`（冻结语音基线 tag `XIAOZHI-VOICE-V1-HUMAN-ACCEPTED` 不得改变）
- 编制：v05-sec-qa（只读安全/QA 设计；本文为唯一写入物）
- 继承：`VISION_SECURITY_REVIEW.md`（R1-R10，V0 审计）+ `VISION_V0_TEST_PLAN.md`（A/B/C/D 层用例，全量继承继续执行）
- 目标面：V0.5 客户端集成 —— 客户端 HTTP 视觉提交 + 网关 WS vision 事件→Qwen + avatar 播放同步 + 集成浏览器预览
- 硬边界：不触碰真实 Qwen / 真实云视觉；全部自动化用例本地可跑；mock 网络仅 `127.0.0.1`

---

## NEW_SURFACE（V0.5 新增面，审计对象清单）

| 面 | 位置/计划 | 说明 |
|---|---|---|
| HTTP 视觉端点 | `gateway/app/http.py` 加法式端点 `POST /xiaozhi/vision/`，挂 **8111**（HTTP/OTA app，非 8110 WS、非 8112 admin） | 客户端提交 `image_b64`；鉴权头 **`X-Vision-Token`** 比对 `secrets/vision_token`（新密钥，非 admin token） |
| send_image 守卫 | `gateway/app/qwen.py`（协议报告 VISION_PROTOCOL_REPORT.md:64-65 规格） | JPEG-only、raw <190KB（base64 后 <256KB）、限速 1/s、audio-first 顺序约束、response in-flight 期间拒收 |
| 客户端视觉模块 | `client/src/vision/`（plugin + preview + submit，VISION_CLIENT_DESIGN.md 载体） | 采集→压缩（≤1280px/≤190KB/无EXIF）→HTTP 提交；`VISION.ENABLED` 默认 false |
| avatar 播放同步 | avatar 线（v05-avatar-sync 设计） | transcript/TTS → 嘴型振幅/状态机 envelope；纯本地消费 |
| 集成浏览器预览 | `tools/mock_client_gateway.py`（计划中，尚无代码） | WS mock 网关 + 静态预览页；必须绑 `127.0.0.1` 临时端口 |

信任边界注意：V0 审计（VISION_SECURITY_REVIEW.md THREAT_MODEL-2）确认 WS 面"LAN 即信任"；V0.5 新 HTTP 端点**不得**延续该弱模型——vision 端点必须自带独立鉴权（V05-R1），且 8111 的暴露面维持既有 compose 约束（红队 red_i 曾发现 `HostIp=""` 致三端口绑 0.0.0.0，V0.5 不得复现）。

---

## SECURITY_REQUIREMENTS（V05-R1…R10，编号可测）

### V05-R1 vision token 独立密钥与恒时比较
- `secrets/vision_token` 为**新增独立密钥**；端点只认 `X-Vision-Token`，**禁止**接受 admin token / WS Bearer token 顶替（`hmac.compare_digest` 恒时比较，复用 `gateway/app/admin/auth.py:84,122-138` 模式）。
- 缺失/错误/空 token 一律 401 fail-closed；**token 不得出现在 URL/query**；日志、counters、错误响应不得含 token 明文或前缀泄漏。
- 测试锚点：E1-a/b/c。

### V05-R2 尺寸限制双层收口（客户端压缩 + 网关守卫）
- 客户端层：压缩输出 ≤1280px / ≤190KB raw / JPEG（VISION_CLIENT_DESIGN COMPRESSION_SPEC），超限本地拒绝、**不发任何网络请求**。
- 网关层：`send_image` 守卫独立拒绝 raw ≥190KB（或 base64 ≥256KB）→ 413，**不依赖客户端自律**（curl 直打必须被拦）。
- 两层独立生效：绕过客户端直接打端点时网关层必须兜住；禁止为图像放宽全局 64KB JSON 帽（`gateway/app/protocol.py:6`）。
- 测试锚点：E2-a/b、A1-b/C4（继承）。

### V05-R3 类型收口：JPEG-only 双层
- 客户端 magic-byte（`FF D8 FF`）+ 网关 send_image JPEG-only 守卫；PNG 改名、非法字节、空文件双层均拒。
- 测试锚点：E2-c、A1-a（继承）。

### V05-R4 速率与成本守卫（沿用 V0 R3/R7 并落到 send_image）
- 网关 send_image 限速 1/s（协议报告 doc-verified）；客户端按钮侧限速（间隔 ≥5s）继续覆盖所有触发源；图像推理失败**零自动重试**。
- counters：`vision_captures_total / vision_bytes_total / vision_rejects_total{reason}` 经 /health 可查。
- 测试锚点：E2-d、A3（继承）。

### V05-R5 会话绑定：图像只进当前会话（跨会话串图 = 最高优先级缺陷）
- HTTP 提交必须落到**发起提交的客户端连接所绑定的服务端 session**（session_id 服务端 uuid4，`gateway/app/protocol.py:9-10`）；客户端不得自报 session_id 且被采信。
- 无活动会话/连接已断时提交 → 明确拒绝（409/410 类），**不得**新建会话或落到默认会话。
- 图像产物（识别文本）只进入本会话状态；禁止写 MEMORY/KNOWLEDGE/POLICY 文件（`gateway/app/main.py:36-39`，V0 R4 继续成立）。
- 测试锚点：E5-a/b、A4/A5（继承）。

### V05-R6 无落盘、日志无图像内容（继承 V0 R5/R6）
- 全链路内存即逝：客户端不写盘不写临时文件；mock 网关请求日志环形缓冲**只存元数据**（时间戳/body 长度/Content-Type），不落图像字节。
- 网关/客户端日志只记 size 与结果，长 base64/令牌形态字符串沿用既有脱敏（`gateway/app/qwen.py:79-81`）。
- 测试锚点：E6-a（日志审计 grep）、D2（继承）。

### V05-R7 暴露面不扩大
- mock_client_gateway 与全部测试 mock 绑 `127.0.0.1:0` 临时端口；部署面 8110/8111/8112 绑定维持 compose LAN-only 约束（`deploy/product-sidecar/docker-compose.yml:24,49`），vision 端点不得新增监听器/新端口。
- 浏览器静态预览资源本地打包，无 CDN 外链。
- 测试锚点：E7-a、E4。

### V05-R8 avatar 纯本地（继承 V0 R8）
- avatar 零网络（无 fetch/WS/CDN）、零摄像头/麦克风；播放同步只消费本地状态（transcript/tts/振幅事件）；avatar 崩溃不波及语音主回路。
- 测试锚点：E8-a、C6-C8（继承）。

### V05-R9 失败降级无残留（继承 V0 R9）
- 采集/压缩/提交/推理任一步失败：语音会话不受影响、无重试风暴、缓冲清空、计数 reject；断线重连后不重放过期图像。
- 测试锚点：E6-b、A3/B4（继承）。

### V05-R10 回归闸门：冻结语音基线不动
- 实施后重跑：`vision_v0_tests` 全绿 + 回归基座三套（`admin_security_tests.py`(29) / `product_v1_integration.py`(33) / `behavior1_tests.py`(≥60)）前后逐项一致 + 冻结文件 diff 审计（`gateway/app/audio.py`、`protocol.py` 音频面、VAD/节奏模块零字节改动）。
- 测试锚点：E9、D4/D5（继承）。

---

## QA_MATRIX（Layer E 新增用例；A/B/C/D 层 V0 用例全量继承执行）

| ID | 层 | 步骤 | 预期 | 可自动化 |
|---|---|---|---|---|
| **E1-a** | B | 对 `POST /xiaozhi/vision/` 发无 token / 空 token / 错误 token / **admin token 冒充** 四种请求（合法小 JPEG body） | 全部 401 fail-closed；错误响应与日志无 token 回显；`vision_rejects_total{reason=auth}` 递增 | yes |
| **E1-b** | B | 正确 token 提交合法图像 | 200/202，进入 send_image 路径；mock Qwen 收到 `input_image_buffer.append` 且 base64 解码后为合法 JPEG | yes |
| **E1-c** | A | token 比对函数单测 | 使用恒时比较（代码审查 + 计时抖动弱断言）；token 从 secrets 读取而非硬编码 | yes |
| **E2-a** | C | 对固定大帧 fixture 跑客户端压缩函数（Node/Python 单测，扩展 C4） | 输出 JPEG ≤190KB raw、≤1280px、无 EXIF；超限输入被本地拒绝且 mock 日志零请求 | yes |
| **E2-b** | B | curl 直打端点（绕过客户端）：191KB / 1MB / base64 后 >256KB 的 JPEG | 网关守卫 413 拒收，mock Qwen 收到零图像事件；拒绝计数递增 | yes |
| **E2-c** | B | 类型负样本双层测试：PNG 改名 .jpg、`FF D8` 截断、空 body | 客户端层与网关层各自拒绝（A1-a 断言 + 端点层断言） | yes |
| **E2-d** | B | 2s 内连续提交 3 次合法图像（同会话） | 第 2/3 次被 1/s 限速拒绝；无自动重试补发 | yes |
| **E3** | B | 传输面核查（代码审查 + 断言） | vision 仅走 HTTP 端点：WS JSON 64KB 帽数值不变（protocol.py:6）、二进制帧仍全量按 opus 处理（turns.py:510）、无新增监听端口 | yes |
| **E4** | E2E | mock_client_gateway 全链路：预览页点击 → 客户端压缩 → POST /xiaozhi/vision/ → WS vision 事件 → mock Qwen 识别回注 → transcript → avatar envelope（振幅/状态机） | 端到端一次通过：图像派生文本以数据身份进 transcript；avatar 嘴型/状态按 envelope 迁移；真实 Qwen/云零调用（mock 请求日志证明）；mock 网关仅绑 127.0.0.1 | yes |
| **E5-a** | B | 跨会话串图：连接 A 提交图像，连接 B 同时纯语音对话（扩展 A4 至 HTTP 路径） | B 的 transcript/状态/回复零 A 图像痕迹；图像派生文本只在 A | yes |
| **E5-b** | B | 无会话提交：不发 hello / 发 hello 后立即断开再 POST | 拒绝（不新建会话、不落默认会话）；`vision_rejects_total{reason=session}` 递增 | yes |
| **E6-a** | D | 日志/落盘审计：全链路跑 10 轮后 grep 客户端与 mock 网关输出、扫描临时目录 | 日志仅 size/元数据；零图像字节落盘；token 不出现在任何日志行 | yes |
| **E6-b** | B | 重连中视觉：识别在途时 WS 断开 → 客户端重连（扩展 B2 场景 12） | 旧图像缓冲丢弃、重连后不重放图像事件；重连后语音回合正常；无残留视觉会话状态 | yes |
| **E7-a** | D | 绑定审计：启动 mock_client_gateway 与被测网关，`lsof -iTCP` 检查监听地址 | mock 仅 127.0.0.1；部署面绑定与 compose 约束一致（无 0.0.0.0 回归，red_i 项不复发） | yes |
| **E8-a** | C | avatar 隔离：avatar 模块强制抛错/断网（mock 层注入） | 语音主回路照常；avatar 崩溃可恢复或可重启；无网络外呼（请求日志证明） | yes |
| **E9** | D | 回归闸门：实施 HEAD 重跑 vision_v0_tests + 三套基座 + `git diff` 冻结文件审计 | 全绿且逐项一致；冻结音频面零字节 diff（或 QA 裁定豁免清单） | yes |
| **E10** | D | 资源/延迟方法（扩展 D1/D2 到全链路含 avatar）：截图→识别→transcript→avatar 呈现，≥20 次取 P50/P95；50 轮循环采样 RSS 与句柄 | P95 记录并留档（本地阈值实施时标定，默认沿用 D1 的 ≤2s 口径）；内存有界（D2 阈值沿用） | yes |

用例总数：V0 既有表全量继承 + E 层 17 项新增（E1×3、E2×4、E3、E4、E5×2、E6×2、E7、E8、E9、E10）。

---

## PASS_CRITERIA

1. **E 层全部 yes 项绿** + V0 既有 A/B/C/D 用例的自动化部分绿（partial 项 manual 部分有留档）。
2. **安全硬门**：E1（token 四负样本 + admin token 冒充被拒）、E2-b（绕过客户端仍被网关拦截）、E5（跨会话零串图）、E6-a（零落盘/日志无图像/token）、E7-a（绑定不扩大）全部通过——任一失败即整轮 FAIL。
3. **回归闸门（V05-R10/E9）**：`vision_v0_tests` + 三套回归基座全绿且前后逐项一致；冻结音频文件零字节 diff。
4. **Mock 边界证明**：全链路 E2E（E4）在 127.0.0.1 mock 内完成，真实 Qwen/云视觉零调用可由请求日志交叉证明。
5. 证据留档：E6-a/E7-a/E9/E10 输出写入本目录 `evidence/`（含 commit 号与时间戳），由独立只读复审核对。

## MANUAL_GATES（本地不可自动化，留待真实会话）

| 项 | 原因 | 门禁方式 |
|---|---|---|
| 真实摄像头 TCC 三分支 | 自动化环境无法真实弹出系统权限框 | 真机走 C1 三分支并截图留档 |
| 真实云识别质量 | mock 只证链路与形状 | 真实会话抽样 ≥10 张真实图像，人工判定识别可用性 |
| 主观嘴型同步 | 主观项，振幅序列断言不覆盖自然度 | 真人验收一轮：语音回答与嘴型同步、无感知延迟劣化（对照冻结基线听感） |
| LAN 真机暴露面 | 自动化仅覆盖 lsof 断言 | 部署后从另一台 LAN 主机扫描 8110/8111/8112，vision 端点无 token 不可达 |

## VERDICT

**可行，附实施硬条件**：V0 基线（R1-R10 审计通过 + 24 项用例框架）可直接承载 V0.5；新增面收敛在 1 个加法式 HTTP 端点 + send_image 守卫 + 独立客户端模块 + 本地 avatar/预览，无冻结音频面触碰。放行条件：① vision token 独立密钥 + 恒时比较 + 不入 URL/日志（V05-R1）；② 尺寸/类型双层收口且网关层独立兜底（V05-R2/R3，E2-b 为硬断言）；③ 会话绑定严格——无会话拒收、跨会话零串图（V05-R5）；④ mock_client_gateway 仅 127.0.0.1、日志只存元数据（V05-R6/R7）；⑤ E9 回归闸门全绿。五条任一缺失不得进入真实会话门禁。
