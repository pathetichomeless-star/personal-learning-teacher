# R3-1 三个专项 Agent 报告（附录·要点存档）

> 全文以各 Agent 返回为准；本附录存档其判定、关键证据表与不可验证项。
> 总控已对三份报告的关键主张做独立交叉核对（官方文档复证、源码亲读、存储只读核验），一致。

---

## 附录 A — REAL_MODEL_COMPATIBILITY_REPORT（Agent A）

**判定：`MODEL_COMPATIBILITY = PARTIAL`** —— 端点/协议/鉴权/音色已获官方文档确认且与代码逐字一致；真实连接未验证；输出 pcm16 与 session.update 扩展字段两点存疑。

### A.1 引擎契约（代码证据）

| # | 事实 | 证据 |
|---|---|---|
| a | 模型 ID 来自 provider 模型记录 `model_key`；冻结默认 `qwen3.8-omni-flash-realtime` | `qwen.py:38` |
| b | WS URL = `wss://{workspace}.{region}.maas.aliyuncs.com/api-ws/v1/realtime?model=<key>`；鉴权仅 `Authorization: Bearer`（无 workspace 头 ⇒ workspace 必须在主机名内） | `qwen.py:36-37,231-235,266-269`；`teacher_voice.py:203-239` |
| c | `QwenConfig.ready`（real 模式）＝ api_key ∧ workspace_id ∧ `region=="cn-beijing"` | `qwen.py:213-217` |
| d | `provider_realtime_binding` 仅接受 `<workspace>.<region>.maas.aliyuncs.com`（前缀恰一个点），`http/ws→ws://`、`https/wss→wss://`；不匹配返回空 → 调用方 fail-closed | `teacher_voice.py:203-239` |
| e | 老师记录需 `voice.mode=="realtime"` + `model.realtime_model_id` | `teacher_voice.py:73,290-307` |
| f | 第二个非冻结 provider/model_key 可建（查重按 provider 内唯一）；`ensure_frozen_link` 只镜像运行期快照为只读行，不冻结新记录 | `registry.py:316-318` 等 |
| g | 音色无代码校验，原样下发 `session.update` | `qwen.py`（voice 透传） |

### A.2 官方文档确认（help.aliyun.com / 阿里云百炼）

* `qwen3.8-omni-flash-realtime`：公开模型（更新 2026-09-22），推理服务为百炼，地域=华北2(北京)/新加坡。
* "**通过 WebSocket 接入时，必须使用绑定业务空间的 WebSocket 地址**" ⇒ `{WorkspaceId}.cn-beijing.maas.aliyuncs.com` 形态官方成立。
* 免费额度：**100 万 token，仅北京，90 天**；计费：音频入 6 / 音频出 12 / 文本入 1.5 / 文本出 4.5（元/百万 token）；限流 60 RPM / 2M TPM。
* 音色：`qwen3.8-omni-flash-realtime` **默认 Tina**；合法音色 Tina/Cindy/Liora Mira/Raymond/Zane/Katerina/Ryan/Mia/Cici…（经 `session.audio.output.voice` 设置）。
* 客户端事件文档：默认音色 Qwen3.8=Tina、Qwen3.5 系列=Tina、`qwen3-omni-flash-realtime-2025-09-15`=Cherry；输入 pcm(16bit)/16k 默认。

### A.3 兼容性对照（要点）

| 维度 | 代码 | 官方 | 判定 |
|---|---|---|---|
| 主机形态 | `{workspace}.{region}.maas.aliyuncs.com` | 业务空间绑定地址 | 一致 |
| 路径/参数 | `/api-ws/v1/realtime?model=` | realtime WS | 一致 |
| 鉴权 | Bearer（无 workspace 头） | 业务空间绑定地址+Bearer | 一致 |
| region | 恒 `cn-beijing` | 北京/新加坡 | 一致（北京） |
| 默认音色 | 冻结 `Tina`；老师可自选 | 3.8 默认 Tina | 一致 |

### A.4 候选

* **C1（首选）**：`qwen3.8-omni-flash-realtime` + `Tina`。【官方文档确认】端点/鉴权/音色；【代码兼容判断】会话协议；【未验证】真实连接。
* **C2（备选）**：`qwen3-omni-flash-realtime` + `Cherry`。风险：官方一处输出格式 `pcm24` vs 引擎 `pcm16`，未确认不推荐。

### A.5 仅真实连接可确认

① 3.8 输出是否接受 `pcm16`；② `session.update` 额外 `model` 字段与 `session.finish` 的容忍度；③ 业务空间地址的 DNS/TLS/Bearer 握手；④ 实际计费。

---

## 附录 B — MAC_REAL_VOICE_PREFLIGHT_REPORT（Agent B）

**判定：`MAC_RUNTIME = READY`｜`ISOLATED_GATEWAY_READY = READY`｜`TEACHER_BINDING_READY = READY（机制）/ 未绑定（实际）`**

### B.1 客户端运行时【本机实测】

* `client/.venv` = Python 3.10.20；PySide6 6.10.1、websockets 15.0.1（支持 `additional_headers`）、aiohttp 3.13.2、sounddevice 0.5.3、opuslib（需 `DYLD_LIBRARY_PATH=client/libs/libopus/mac/arm64`）。
* 入口 `client/main.py --mode {gui,cli,tui,gpio}`；本报告只用 `--mode cli`，不启 GUI、不占音频设备。
* ws/wss 由 URL scheme 决定（`wss://` 才挂 ssl_context）；`websockets.connect(..., proxy=None)` 无代理。

### B.2 配置隔离（关键发现）【代码判断+实测】

* `XIAOZHI_DATA_DIR` 环境变量优先于 platformdirs 决定数据目录（`src/utils/resource_finder.py:37,82-91`），config/ 在其下。
* **实测**：设置该变量启动客户端后，真实 config.json **md5 前后不变** ⇒ 客户端整体隔离可行，零侵入。

### B.3 老师机制【代码判断（与总控亲读一致）】

* `websocket_protocol.py:48-84`：每次建连重读 `WEBSOCKET_URL/TEACHER_ID/TEACHER_VOICE_TOKEN`；`/xiaozhi/v1/`→`/xiaozhi/v1/teacher/?teacher_id=<urlencode>` + `X-Teacher-Token`。
* 401/409 **不回退**冻结链路；**无自动重连**（`enable_auto_reconnect` 定义存在但从未被调用）⇒ 测试可控、无静默重试。

### B.4 回环连通性 4/4【本机实测】

| 用例 | 观测 |
|---|---|
| 无令牌 | HTTP 401 `invalid_token` |
| 错令牌 | HTTP 401 `invalid_token` |
| 正确令牌+存在老师（模型故意未登记） | 409 `realtime_not_configured`（fail-closed 证明全链路） |
| 正确令牌+未知老师 | 409 `teacher_not_found` |

服务端隔离 venv aiohttp 3.14.5；127.0.0.1:61110；600 令牌文件；隔离 stores 均在 /tmp。

### B.5 PO 中文步骤

见主报告 §五（隔离目录 → 隔离网关 env 覆盖启动 → 连通性自检 → `XIAOZHI_DATA_DIR` 客户端隔离 → 收尾删除）。

### B.6 本地无法验证

真实音频往返、真实模型连接、wss/TLS、NAT/局域网、课堂记录收尾、客户端激活流程。

---

## 附录 C — REAL_AUDIO_SAFETY_GATE_REPORT（Agent C）

**判定：`SAFE_TO_PREPARE = YES`**（仅准备；真实连接仍被门禁阻塞）。**0 个 P0/P1/P2**；P3 级风险与登记项如下。

### C.1 门禁保持（全部实测复跑）

| 项 | 判定 | 证据 |
|---|---|---|
| R1 凭据隔离 | PRESERVED | `teacher_voice_seam_tests` **60/60**（独立 venv，与总控 xiaozhi-p2b2 venv 结果互证） |
| R2 上下文注入 | PRESERVED | `teacher_context_seam_tests` **83/83**；`teacher_context.py` sha `13d679c4…` 未变 |
| R3-0 enabled 门禁 | PRESERVED | `model_v4_tests` **72/72**；`default_resolver` 拒绝在位 |
| 默认关闭 Tina 不变 | PASS | 探针 8/8；路由默认不挂载；`/xiaozhi/v1/` 行为不变 |
| 冻结六文件 | UNCHANGED | sha256 与基线一致；`4669b59..214b9bd` 仅文档 |
| 数字人文件 | UNTOUCHED | 工作树 `M`/`??` 状态与轮前一致 |
| 私有记忆 | NOT_ENABLED | `memory_decision` 恒禁用 |
| 学习记录 | 未授权不写入 | 记录需 `TEACHING_FILE`+`STUDENT_ID`+模型绑定；无音频证据的发音声明被存储层拒绝（T10l） |

### C.2 传输安全（新风险面，P3·登记不改码）

* 服务端 `provider_realtime_binding` 接受 `http://`/`ws://` 且派生 `ws://` ⇒ 运维误配将得到明文连接（凭据头+音频）。
* 客户端模块级 `ssl._create_unverified_context()` ⇒ **wss 不校验证书**（中间人风险）；`proxy=None`（无代理，好）。
* 网关 `main()` 恒绑 `0.0.0.0` ⇒ 隔离网关对局域网可见（ws 明文）。
* 建议：Mac 本地回环 `ws://` 可接受；跨机/公网必须 `https://`→`wss://` 且修客户端证书校验；测试窗口开防火墙。

### C.3 计费暴露

| 步骤 | 费用 |
|---|---|
| 隔离网关 / 回环探测 / fail-closed 门禁验证 | **0 元** |
| 登记模型/凭据/老师（无真实连接） | **0 元** |
| 真实连接（唯一计费步） | 按量：音频入 6 / 音频出 12 / 文本入 1.5 / 文本出 4.5 元/百万 token（北京，官方口径）；有 100 万 token/90 天免费额度 |
| 防误花费护栏 | 三道 fail-closed 门禁（无启用模型/无凭据/旗标关）；**无用量熔断** |

### C.4 凭据供给（PO 须知）

`MODEL_CREDENTIALS_FILE`（密封 JSON，600）+ `MODEL_CREDENTIALS_KEY_FILE`（主密钥）；admin 永不回显明文（仅 fingerprint + opaque ref）；`POST /admin/model/credentials` 唯一写入面；凭据==全局凭据 → `credential_isolation_violation`。第二老师必须使用**独立业务空间 Key**。

### C.5 自我证伪

去掉 `model.enabled` 检查 / 去掉 `asyncio.shield` 的 /tmp 模块副本，均被自写探针抓住（disabled 被放行 / 收尾被跳过）⇒ 探针有鉴别力。

### C.6 阻塞至 PO 授权的清单

真实连接；凭据录入；模型登记/证据/启用；老师绑定；课堂记录开启。**本轮均未执行。**
