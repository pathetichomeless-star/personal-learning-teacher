# R3-1 真实语音验收准备 — 总控汇总报告

**分支**：`p2b2-teacher-voice`　**基线 HEAD**：`214b9bd`（R3-0 末）　**R3-0 代码提交**：`3b13c4c`（已在库内核验）
**本轮性质**：只读核验 + 验收准备。**未修改任何业务代码**（CODE_CHANGED=NO），未部署 NAS（NAS_CHANGED=NO），未发起任何真实模型调用或付费请求。

**基线核验（总控亲验）**：分支 `p2b2-teacher-voice`；HEAD `214b9bd`；`3b13c4c` 存在；冻结六文件 sha256 与 R2/R3-0 基线逐字节一致（`turns e18a0d08…` / `qwen 13d4800d…` / `audio c2218a2c…` / `protocol 944e2d5a…` / `ws dde9d427…` / `behavior 6d705960…`）；工作树仅含既有数字人未提交文件（本轮零触碰）。

---

## 一、最终状态字段

| 字段 | 结论 | 一句话依据 |
|---|---|---|
| `R3_1_PREFLIGHT` | **BLOCKED** | 预检**机制层全部就绪并实测通过**，但真实语音测试被三要素阻塞：非冻结实时模型、独立服务商凭据、产品负责人授权（见第八节最小决策清单） |
| `MODEL_COMPATIBILITY` | **PARTIAL** | 端点形态/模型/音色已获**官方文档确认**且与代码逐字一致；"输出 pcm16 是否被接受"与"`session.update` 附带 `model` 字段"两点**只能真实连接时确认** |
| `NON_FROZEN_MODEL_READY` | **NO** | 验收库中唯一非冻结 `realtime_safe` 是本地 Mock（`openai_compatible`、`enabled:False`、`http://127.0.0.1:8123/v1`），且本轮禁止登记/启用真实模型 |
| `INDEPENDENT_CREDENTIAL_READY` | **NO** | 凭据库中无任何独立服务商密钥；本轮禁止写入真实密钥 |
| `MAC_RUNTIME` | **READY** | 真实客户端 venv（Python 3.10.20 + PySide6 6.10.1 + websockets 15.0.1 + sounddevice 0.5.3 + opuslib）导入实测通过；入口 `client/main.py --mode {gui,cli,tui,gpio}` |
| `ISOLATED_GATEWAY_READY` | **READY** | 回环隔离网关实测 4/4：无令牌 401 / 错令牌 401 / 正确令牌+存在老师 409 `realtime_not_configured` / 正确令牌+未知老师 409 `teacher_not_found`——整条鉴权→老师解析→模型门禁链路 fail-closed 验证通过，零真实模型、零 NAS |
| `TEACHER_BINDING_READY` | **READY（机制）/ 未绑定（实际）** | 绑定机制与隔离配置路径实测就绪；实际绑定因 NON_FROZEN_MODEL_READY=NO 而未执行（本轮禁止） |
| `R1_CREDENTIAL_ISOLATION` | **PRESERVED** | Agent C 复跑 `teacher_voice_seam_tests` **60/60**；总控亲读 `build_teacher_qwen`（`teacher_voice.py:174-192`：先清空 api_key/workspace/region，real 模式缺自有凭据即 fail-closed） |
| `R2_CONTEXT_INJECTION` | **PRESERVED** | Agent C 复跑 `teacher_context_seam_tests` **83/83**；`teacher_context.py` sha256 `13d679c4…` 与 R3-0 提交逐字节一致；`memory_decision` 恒禁用 |
| `R3_0_MODEL_ENABLED_GATE` | **PRESERVED** | Agent C 复跑 `model_v4_tests` **72/72**；`default_resolver` 的 `model_disabled` 拒绝在位（`teacher_voice.py:384-385`） |
| `PRIVATE_MEMORY` | **NOT_ENABLED** | `teacher_context.memory_decision` 恒返回禁用 + `memory_scope_unavailable`；无任何挂载路径 |
| `TINA_FROZEN` | **UNCHANGED** | 冻结六文件逐字节未变；默认 `TEACHER_VOICE_WS=0` 时老师路由不挂载、`/xiaozhi/v1/` 行为不变（Agent C 探针 8/8） |
| `REAL_AUDIO_HUMAN_TEST` | **PENDING** | 本轮未发生任何真实音频/真实连接 |
| `CODE_CHANGED` | **NO** | 本轮仅新增本报告文档；`git diff 4669b59..214b9bd` 之后的代码为零改动 |
| `NAS_CHANGED` | **NO** | 无任何 NAS 交互；Agent B/C 全程禁止连接 192.0.2.1 |

---

## 二、三个专项 Agent 结论（证据摘录，全文见附录指针）

### Agent A — REAL_MODEL_COMPATIBILITY_REPORT：`MODEL_COMPATIBILITY = PARTIAL`

**最重要的结论（总控已用官方文档独立复证）**：

| 维度 | 代码实现 | 官方文档 | 判定 |
|---|---|---|---|
| 实时模型 ID | 冻结默认 `qwen3.8-omni-flash-realtime`（`qwen.py:38`）；老师侧来自 provider 模型记录 `model_key` | `qwen3.8-omni-flash-realtime` 为**公开模型**（百炼，更新 2026-09-22），北京/新加坡区 | **一致**【官方文档确认】 |
| WebSocket 主机形态 | `REAL_HOST_TMPL="{workspace}.{region}.maas.aliyuncs.com"`（`qwen.py:36`） | "**通过 WebSocket 接入时，必须使用绑定业务空间的 WebSocket 地址**" | **一致**【官方文档确认】 |
| 路径与模型传参 | `REAL_PATH="/api-ws/v1/realtime"` + `?model=<key>`（`qwen.py:37`、`teacher_voice.py:228-229`） | 官方 realtime WS 地址 + `?model=` 查询参数 | **一致**【官方文档确认】 |
| 鉴权 | 仅 `Authorization: Bearer <key>`（`qwen.py:231-235`，无 workspace 头） | 业务空间绑定地址 + Bearer Key | **一致**（workspace 由专属域名承载） |
| region | 恒 `cn-beijing`（`ready` 门禁 `qwen.py:216-217`） | 支持地域：华北2(北京)、新加坡 | **一致（北京）**【官方文档确认】 |
| 音色 | 老师记录 `voice.voice_id` 原样下发 | `qwen3.8-omni-flash-realtime` **默认音色 Tina**，经 `session.audio.output.voice` 设置；合法音色含 Tina/Cindy/Liora Mira/Raymond/Zane/Katerina/Ryan/Mia/Cici… | **Tina 合法**【官方文档确认】 |
| `provider_realtime_binding` | 要求 host 恰为 `<workspace>.<region>.maas.aliyuncs.com`（`teacher_voice.py:230-239`） | 业务空间绑定地址 | **MATCH**（与官方要求逐字一致） |

**候选模型（最多两个）**：

| 编号 | 模型 | 音色 | 依据分层 |
|---|---|---|---|
| **C1（首选）** | `qwen3.8-omni-flash-realtime` | `Tina`（默认） | 端点/鉴权/音色【官方文档确认】；引擎协议【代码兼容判断】；**真实连接未验证**。北京区**免费额度 100 万 token / 90 天**（自开通/模型发布/审批通过较晚者起算） |
| C2（备选） | `qwen3-omni-flash-realtime` | `Cherry`（该系列默认） | 官方文档存在且为 3.8 的前代系列；**风险**：官方文档一处写其输出格式为 `pcm24`，而引擎发送 `output_audio_format: pcm16` → 存在格式冲突疑点，未确认前不推荐 |

**仅能由真实连接确认的两点（诚实清单）**：① 3.8 模型是否接受**输出 `pcm16`**（客户端/引擎 16k 单声道；官方对输入明确 pcm/16k，输出格式文档存在 3.5 系列 pcm24 表述，3.8 输出格式未逐字确认）；② 引擎 `session.update` 附带的额外 `model` 字段与 `session.finish` 是否被当前 API 版本容忍（冻结链路在生产长期工作，属低风险但非零）。

**登记/证据/启用的授权位（代码实证）**：`MODEL_TEST_AUTHORIZED` / `MODEL_PROMOTE_AUTHORIZED` 默认 `"0"`（`main.py:66-69`）；`promote-realtime` 需 `confirm=true`（`api_model.py:407`）。证据阶梯 `id_only → adapter_present → verified → realtime_safe`；`oral_realtime` 场景需 `realtime_safe`。

### Agent B — MAC_REAL_VOICE_PREFLIGHT_REPORT：三个 READY

* **MAC_RUNTIME = READY**【本机实测】：`client/.venv` Python 3.10.20；PySide6 6.10.1 / websockets 15.0.1 / aiohttp 3.13.2 / sounddevice 0.5.3 / opuslib（`DYLD_LIBRARY_PATH=client/libs/libopus/mac/arm64`）全部可导入；入口 `client/main.py --mode {gui,cli,tui,gpio}`。
* **客户端老师机制**【代码判断 + 总控亲证】：`websocket_protocol.py:48-84` `_resolve_endpoint()` **每次建连重读** `WEBSOCKET_URL/TEACHER_ID/TEACHER_VOICE_TOKEN`；`/xiaozhi/v1/` → `/xiaozhi/v1/teacher/?teacher_id=<urlencode>` + `X-Teacher-Token` 头。401/409 **不回退**冻结链路、**无自动重连**（`enable_auto_reconnect` 定义存在但无人调用）。
* **客户端配置隔离（关键发现）**【代码判断 + 实测 md5 前后不变】：`XIAOZHI_DATA_DIR` 环境变量优先于 platformdirs 决定数据目录（`src/utils/resource_finder.py:37,82-91`），config/ 在其下 → **整个客户端配置可整体隔离，不碰真实配置**。
* **回环连通性 4/4**【本机实测】：隔离网关（`teacher_voice.mount`，127.0.0.1:61110）+ 隔离老师库 + 600 令牌文件：无令牌 401 `invalid_token`；错令牌 401；正确令牌+存在老师（`realtime_model_id` 故意不存在）409 `realtime_not_configured`；未知老师 409 `teacher_not_found`。**整条"鉴权→老师解析→R3-0 模型门禁"链路 fail-closed 验证通过，零真实模型、零 NAS、零付费。**
* **当前客户端配置**【本机实测，脱敏】：`WEBSOCKET_URL=<set, len=34, prefix "ws://1…">`（即 `ws://192.0.2.1:28310/xiaozhi/v1/`）；`TEACHER_ID=None`；`TEACHER_VOICE_TOKEN=None` → 客户端当前不走老师路由。
* **本地无法验证**：真实音频设备往返、真实模型连接、wss/TLS 终结、NAT/局域网行为、课堂记录收尾、客户端激活流程。

### Agent C — REAL_AUDIO_SAFETY_GATE_REPORT：`SAFE_TO_PREPARE = YES`（仅准备；真实连接仍被门禁）

* **R1/R2/R3-0 全部 PRESERVED**（复跑 60/60、83/83、72/72、`product_boundary_tests` 23/23；在独立 venv 下与总控此前的 xiaozhi-p2b2 venv 结果互相印证）。
* 冻结六文件逐字节未变；数字人未提交文件未被触碰；`4669b59..214b9bd` 仅文档。
* **凭据供给路径**：`MODEL_CREDENTIALS_FILE`（密封 JSON，600）+ `MODEL_CREDENTIALS_KEY_FILE`（主密钥）；admin 永不回显明文（仅 fingerprint + opaque ref）；`PUT /admin/model/credentials`（`api_model.py:604`）为唯一写入面；凭据==全局凭据 → `credential_isolation_violation` 拒绝。
* **传输安全（本轮最重要的新风险面）**：
  - 服务端 `provider_realtime_binding` **接受 `http://`/`ws://` 且会派生 `ws://`**（`teacher_voice.py:223-229`）→ 运维若把 provider base_url 配成 http，将得到**明文**实时连接（凭据头+音频明文）。
  - 客户端 `websocket_protocol.py` 模块级 `ssl._create_unverified_context()` → **wss 分支不校验服务器证书**（中间人风险）；客户端无代理（`proxy=None`，好）。
  - 网关 `main()` 恒绑 `0.0.0.0`（`main.py:152`）→ Mac 隔离运行时老师路由会对局域网暴露（ws 明文）。
  - **建议（不在本轮改代码）**：Mac 本地测试用 `127.0.0.1`（回环明文可接受）；一切跨机/公网必须 `https://` base_url（得 `wss://`）+ 后续修客户端证书校验；隔离网关运行期间开启 macOS 防火墙或断开局域网。
* **计费暴露**：回环/Mock/fail-closed 探测 **0 费用**；唯一计费步骤 = 真实连接到非冻结服务商（音频入 6 元/百万 token、音频出 12 元/百万 token、文本入 1.5、文本出 4.5，北京区口径【官方文档确认】）。**代码层防误花费护栏 = 三道 fail-closed 门禁（无启用模型/无凭据/旗标关闭即拒绝），此外没有预算/用量熔断** —— 如实告知。
* 自我证伪通过（去掉 enabled 检查 / 去掉 shield 的 /tmp 副本均被探针抓住）。

---

## 三、总控对四问的回答

**A. 是否已具备开展真实语音测试的技术条件？**
**机制与工程条件已就绪并实测**（客户端运行时、隔离网关、鉴权→解析→门禁链路、R1/R2/R3-0 保持、Tina 不变）；但**真实语音测试尚未就绪**——缺"模型、凭据、授权"三要素，且两项协议细节只能在真实连接时确认。

**B. 缺的到底是什么？**
① 一个**获授权的非冻结实时模型**：登记 provider+model（`dashscope` 协议、`realtime_audio/streaming/barge_in` 能力、业务空间绑定形态 base_url）→ 证据达到 `realtime_safe`（真跑测试或 PO 授权提升）→ `set_enabled(true)`；② 该模型所属业务空间的**独立 API Key**（密封入库，≠ Tina 的 Key）；③ **产品负责人授权**（登记动作 + 证据提升 + 计费知悉 + 隔离测试窗口）；④ 两项真实连接才能确认的协议点（可按"低风险、真实连接时观察"处理）。

**C. 哪种非冻结模型符合现有实时引擎？**
首选 **C1：`qwen3.8-omni-flash-realtime`（音色 `Tina`）**——端点/鉴权/音色官方文档确认、与引擎逐字一致、北京区 100 万 token 免费额度。备选 C2 `qwen3-omni-flash-realtime`（`Cherry`）有输出格式疑点，暂不推荐。

**D. 应当通过什么方式注册、验证和启用？**
全部经既有 admin 面（`/v4/` UI 或 `/admin/model/*` 路由，`api_model.py:584-611`）：`POST /admin/model/providers`（`protocol=dashscope`，`base_url=https://<业务空间ID>.cn-beijing.maas.aliyuncs.com`）→ `POST /admin/model/credentials`（密封入库）→ `POST /admin/model/models`（`model_key=qwen3.8-omni-flash-realtime`，能力 `realtime_audio/streaming/barge_in`）→ `bind-scene oral_realtime` → 证据（`MODEL_TEST_AUTHORIZED=1` 下 `POST /models/{id}/test` 真跑，或 `MODEL_PROMOTE_AUTHORIZED=1` 下 `promote-realtime` + `confirm=true`）→ `enable` → 老师 `model.realtime_model_id` 绑定。**任何一步都不改代码。**

**E. 如何在 Mac 隔离环境完成测试而不碰 NAS？**
网关侧：`gateway/` 下用隔离 venv 起服务，**全部用环境变量覆盖**（`WS_PORT=61110`、`PUBLIC_WS_URL=ws://127.0.0.1:61110/xiaozhi/v1/`、`QWEN_MODE=mock`、`TEACHER_VOICE_WS=1`、`TEACHER_VOICE_TOKEN_FILE=/tmp 下 600 文件`、`TEACHER_VOICE_DATA_DIR`、`TEACHER_FILE`、`MODEL_REGISTRY_FILE`、`MODEL_CREDENTIALS_FILE`、`MODEL_CREDENTIALS_KEY_FILE` 均指向专用隔离目录）——`config.json` 只被读取不被改写。客户端侧：`XIAOZHI_DATA_DIR=<专用目录>` 复制/初始化独立配置（实测真实 config md5 不变）+ `--mode cli`。**全程回环 127.0.0.1，不触 192.0.2.1。**

**F. 需要产品负责人提供哪些授权？是否存在费用？**
见第八节决策清单。费用：准备/回环/门禁验证 **0 元**；真实连接按量计费（上表口径），**可用北京区 100 万 token 免费额度覆盖初期验证**（90 天有效）；**代码层无用量熔断**，建议测试时设定时长上限并由 PO 在阿里云控制台设用量告警。

**G. 如何为第一位非冻结测试老师建立独立配置？**
老师记录需：`enabled:true`、`frozen:false`、`voice.mode="realtime"`、`voice.voice_id`（候选 `Tina`）、`model.realtime_model_id=<新模型 id>`；配合 `TEACHER_VOICE_TOKEN_FILE`（600 令牌）+ 客户端 `TEACHER_ID`/`TEACHER_VOICE_TOKEN`。老师解析门槛（`resolve_teacher`，`teacher_voice.py:290-307`）：存在→未删→`enabled`→非冻结→`voice.mode=="realtime"`；随后过 R3-0 `enabled` 门禁与其余六道门禁。

**H. 测试失败如何恢复？**
隔离原则保证"恢复"近乎零成本：① 网关进程直接结束（无守护、无开机项）；② 删除 `/tmp`/专用隔离目录即彻底清除；③ 客户端 `XIAOZHI_DATA_DIR` 方案**天然不动真实配置**（实测 md5 不变）；④ 若采用临时改配置方案，备份→改→用后还原（附 md5 校验）；⑤ NAS 与生产 Tina 全程零接触；⑥ 冻结六文件哈希可随时比对证明未动。

**I. 真实教学验收必须验证什么？哪些仍是未实现？**
**必须验证**：老师身份与模型隔离（两位老师互不串凭据/音色/教材）；真实麦克风输入；实时语音回复；播放与自然打断（barge_in）；教学规则实际生效（政策投影进 instruction）；授权教材实际生效（仅命中授权 dataset）；会话切换与资源释放（连接结束无残留会话/无孤儿记录）。
**保持未实现（不得虚报）**：私有学习记忆 **NOT_ENABLED**（fail-closed 设计）；发音/音标评分（无音频证据不产出，实时音频≠评分证据）；字面 instructions 直灌（冻结边界）；学生身份认证；NAS 增量部署；`enable_gate` 是否纳入 `enabled`（PO 决策）。

---

## 四、隔离连接方案（汇总）

```
┌─ Mac 本机（测试窗口期） ─────────────────────────────────────────────┐
│  客户端（隔离配置）                 隔离网关（专用端口 61110）          │
│  XIAOZHI_DATA_DIR=/tmp/xz-acc/client   env: TEACHER_VOICE_WS=1       │
│  WEBSOCKET_URL=ws://127.0.0.1:61110/xiaozhi/v1/                      │
│  TEACHER_ID=<第二老师>            TEACHER_VOICE_TOKEN_FILE(600)      │
│  TEACHER_VOICE_TOKEN=<令牌>  ──►  /xiaozhi/v1/teacher/?teacher_id=…   │
│  （--mode cli，不启 GUI）         X-Teacher-Token 恒时校验            │
│                                   ↓ resolve_teacher（enabled/非冻结） │
│                                   ↓ default_resolver（R3-0 enabled    │
│                                     门禁 + 冻结/协议/凭据/端点门禁）    │
│                                   ↓ turns.Connection（冻结引擎不动）   │
│  麦克风 → Opus 20ms 帧 ──────────► 逐老师 QwenConfig 拷贝              │
│                                   └─（真实模式）wss://{workspace}.     │
│                                      cn-beijing.maas.aliyuncs.com      │
│                                      /api-ws/v1/realtime?model=…       │
│                                      Authorization: Bearer <独立Key>   │
│  生产 Tina / NAS 192.0.2.1 —— 全程零接触                            │
└──────────────────────────────────────────────────────────────────────┘
```

隔离存储一览（全部专用目录，用后可整体删除）：
`teachers.json`、`model_registry.json`、`model_credentials.json`+`*.key`、`TEACHER_VOICE_DATA_DIR/<teacher_id>/{policy,knowledge}.json`、`TEACHING_FILE`（可选）。

---

## 五、产品负责人中文操作说明（准备态；真实连接前须先完成第八节批准）

> 以下步骤**不含**真实模型调用；第 4 步之后是否推进，取决于第八节批准。

1. **准备隔离目录**（示例）：
   ```sh
   mkdir -p /tmp/xz-acc/{client,stores,data,secrets}
   openssl rand -hex 32 > /tmp/xz-acc/secrets/teacher_voice_token
   chmod 600 /tmp/xz-acc/secrets/teacher_voice_token
   ```
2. **启动隔离网关**（`gateway/` 目录，隔离 venv；只读仓库文件，不写任何仓库路径）：
   ```sh
   cd <project-root>/gateway
   env XIAOZHI_ACC=1 \
       WS_PORT=61110 HTTP_PORT=61111 \
       PUBLIC_WS_URL=ws://127.0.0.1:61110/xiaozhi/v1/ \
       QWEN_MODE=mock \
       TEACHER_VOICE_WS=1 \
       TEACHER_VOICE_TOKEN_FILE=/tmp/xz-acc/secrets/teacher_voice_token \
       TEACHER_VOICE_DATA_DIR=/tmp/xz-acc/data \
       TEACHER_FILE=/tmp/xz-acc/stores/teachers.json \
       MODEL_REGISTRY_FILE=/tmp/xz-acc/stores/model_registry.json \
       MODEL_CREDENTIALS_FILE=/tmp/xz-acc/stores/model_credentials.json \
       MODEL_CREDENTIALS_KEY_FILE=/tmp/xz-acc/stores/model_credentials.key \
       <user-home>/.workbuddy/binaries/python/envs/xiaozhi-p2b2/bin/python app/main.py
   ```
   预期日志：`listening ws on 0.0.0.0:61110`；**注意**：进程绑 0.0.0.0，测试期间建议开启 macOS 防火墙或仅作短时窗口。
3. **连通性自检**（无真实模型，预期全部 fail-closed）：
   无令牌/错令牌 → HTTP 401；正确令牌+未配置模型的老师 → 409 `realtime_not_configured`；未知老师 → 409 `teacher_not_found`。（Agent B 已实测 4/4 通过。）
4. **客户端隔离配置**（不碰真实配置；`XIAOZHI_DATA_DIR` 优先，实测 md5 前后不变）：
   ```sh
   XIAOZHI_DATA_DIR=/tmp/xz-acc/client <project-root>/client/.venv/bin/python \
     <project-root>/client/main.py --mode cli
   ```
   首次运行会在隔离目录生成独立 `config/config.json`；把其中 `SYSTEM_OPTIONS.NETWORK.WEBSOCKET_URL` 设为 `ws://127.0.0.1:61110/xiaozhi/v1/`，并写入 `TEACHER_ID`/`TEACHER_VOICE_TOKEN`（令牌从 600 文件粘贴；不做明文手工编辑的话，可用一条一次性命令从文件读入写出）。
5. **收尾恢复**：结束网关进程；`rm -rf /tmp/xz-acc`；真实配置从未被触碰（可用 md5 复核）；冻结文件哈希比对（见文首六个值）。

---

## 六、待产品负责人批准的具体事项（最小决策清单）

| # | 决策 | 说明 | 费用影响 |
|---|---|---|---|
| P1 | **是否采购/启用候选模型 C1** `qwen3.8-omni-flash-realtime` | 需要一个**业务空间**及其绑定的 WS 地址；北京区有 100 万 token 免费额度（90 天） | 免费额度内 0 元；超出按量计费 |
| P2 | **独立 API Key** | 在（新建的）业务空间生成**独立 Key**，绝不复用 Tina 的 Key；经密封凭据面录入 | 0 元 |
| P3 | **授权位** `MODEL_TEST_AUTHORIZED` / `MODEL_PROMOTE_AUTHORIZED` | 允许一次真实测试跑（记录证据）或显式提升 `realtime_safe`；两者默认关闭 | 0 元（仅开闸） |
| P4 | **真实连接窗口** | 批准在 Mac 隔离环境发起真实 WS 连接的时段与时长上限 | 按量计费 |
| P5 | **课堂记录** | 是否设置 `TEACHING_FILE` + `TEACHER_VOICE_STUDENT_ID`（服务端标签）；不开则无任何学习记录 | 0 元 |
| P6 | **后续工程项（另行立项）** | ① 服务端禁用 `http/ws` base_url（强制 https→wss）；② 客户端 wss 证书校验；③ 用量熔断；④ `enable_gate` 是否纳入 `enabled` | 开发项，非本轮 |

---

## 七、未验证与阻塞原因（诚实清单）

**阻塞（导致 R3_1_PREFLIGHT=BLOCKED）**：
1. 无获授权的非冻结实时模型（`NON_FROZEN_MODEL_READY=NO`；现存唯一非冻结 realtime_safe 是本地 Mock，协议/端点均不符）。
2. 无独立服务商凭据（`INDEPENDENT_CREDENTIAL_READY=NO`）。
3. 无 PO 授权（登记/证据提升/启用/真实连接窗口均未授权）。

**未验证（与阻塞无关，属"只能真实连接时确认"）**：
4. `qwen3.8-omni-flash-realtime` 是否接受**输出 `pcm16`**（官方对输入 pcm/16k 明确；输出格式存在 3.5 系列 `pcm24` 表述，3.8 未逐字确认）。
5. 引擎 `session.update` 附带的额外 `model` 字段与 `session.finish` 是否被当前 API 版本容忍（冻结链路生产长期工作 → 低风险非零）。
6. 业务空间绑定 WS 地址的 DNS/TLS/Bearer 实际握手（本轮禁止外连）。
7. 真实音频设备往返、回声/打断实测、wss 证书链、NAT/局域网。
8. 课堂记录真实收尾（需 P5 授权后才可能产生）。

**本轮新登记的工程风险（不阻塞准备，阻塞跨机真实使用）**：服务端接受 `http/ws` base_url 可派生明文 `ws://`；客户端 wss 不校验证书；网关绑 0.0.0.0。→ 已列入 P6。

---

## 八、停止门禁遵守声明

本轮**未**创建任何真实连接、**未**借用 Tina 凭据、**未**修改冻结代码、**未**登记/启用/绑定任何真实模型、**未**将 Mock 结果表述为真实语音结果、**未**清理任何 Git 文件或测试数据、**未**使用 reset/stash/clean、**未**触碰数字人未提交文件、**未**部署或重启任何生产服务、**未**将任何密钥写入代码/聊天/报告/日志（涉及处一律脱敏）。三份 Agent 报告与本汇总为唯一产出。

---

## 九、状态演进摘要（2026-10-13 总控收录 · append-only，上文一~八节为 R3-1 时点原始记录，逐字未动）

> 本节由文档合并轮追加：把 R3-2A/2B/2C 三轮的**当前有效结论**收敛到本权威状态文档，后续 Agent 读本文件即可获得全链现状，无需逐份翻阅阶段报告。

| 轮次 | 交付物 | 当前有效结论 | 依据文档（同目录） |
|---|---|---|---|
| R3-2A | 真实模型接入准备 | `R3_2A_READY=YES`；环回启动器（三监听仅 127.0.0.1，局域网拒连）；云端登记强制 `https+443` → 派生必为 `wss://`；费用口径勘误：第 7 步取证属**独立计费授权门禁** | `R3_2A_PREPARATION_GUIDE.md`（v1.1） |
| R3-2B | 控制面板验收 | `ADMIN_UI_COVERAGE=COMPLETE`（六能力全中文图形界面）；当时 `VOICE_GUI_ENTRY=MISSING` → **已被 R3-2C 关闭**。原件 `R3_2B_PANEL_ACCEPTANCE_AUDIT.md` 已删除（PROJECT-DOC-MERGE-01 批准；恢复=项目外备份，tracked 亦可 git 取回） | `R3_2B_PANEL_ACCEPTANCE_AUDIT.md` |
| R3-2C | 用户界面补全+探针 | GUI 老师选择/切换/中文错误映射（18+2 码）/令牌保护 全 PASS；`realtime_probe_tests` 23/23；`REALTIME_SAFE_REAL_EVIDENCE=PENDING`（真实拨号待授权）；独立 SIM QA 通过（其 P2-1 已修复） | `R3_2C_IMPLEMENTATION_REPORT.md` + `R3_2C_INDEPENDENT_SIM_QA_REPORT.md` |

**截至 2026-10-13 的合并判定**：
1. `R3_1_PREFLIGHT` 仍 = **BLOCKED**；阻塞三要素不变：①非冻结实时模型 ②独立服务商凭据 ③PO 书面授权（与第七节一致，无变化）。
2. 已演进关闭项：R3-2B `VOICE_GUI_ENTRY=MISSING`（由 R3-2C 关闭）；本文件成文前的 P2B2 验收时点记录中"教学/记忆未接通"已由 R2（teacher_context 接入）关闭、"P1-D1 凭据继承缺口"已由 R1（`06314f8`）修复关闭。
3. 第七节未验证清单（输出 pcm16 / session.update 附加字段 / 真实握手 / 音频设备往返 / 课堂记录真实收尾）**维持**，均需真实连接窗口——**PENDING，不得以 Mock 结果替代**。
4. 冲突裁定：R3-2B MISSING vs R3-2C PASS → 版本演进，以 R3-2C 为准；详见 `docs/PROJECT_WORKLOG.md`【历史档案导航】冲突裁定记录。

---

## 十、当前有效技术事实库（2026-10-13 总控收敛 · **后续开发必读**；本节所列事实此后**仅在本节维护**，原轮次文档降为历史快照，仅调查历史缺陷时读取）

### 10.1 凭据隔离机制（R1 · 代码 `06314f8`，`gateway/app/teacher_voice.py`）

| # | 措施 | 机制 | fail-closed 错误码 |
|---|---|---|---|
| 1 | 构造期强制隔离 | `build_teacher_qwen(...)` 显式凭据参数；赋值前**无条件清空** `api_key/workspace_id/region`；全局凭据在老师路径**零读取点** | `credential_missing` / `realtime_endpoint_not_configured` |
| 2 | 凭据来源=服务商自有 | `default_resolver` 经 `creds.read_secret(current_ref(prov_id))` 读该老师服务商密封凭据 | `credential_missing` |
| 3 | 端点派生 | `provider_realtime_binding(base_url, model_key)` 仅从该服务商 `base_url` 派生 `(ws_url, workspace_id, region)`；主机须精确匹配 `.maas.aliyuncs.com`（防形近主机）；畸形 URL/非数字端口→空绑定 | `realtime_endpoint_not_configured` |
| 4 | 协议兼容门禁 | 仅 `protocol=="dashscope"` 且 `adapter=="builtin"` | `provider_incompatible`；冻结服务商→`frozen_provider` |
| 5 | 等值拒绝断言 | 老师凭据==全局凭据 → 直接拒绝 | `credential_isolation_violation` |
| 6 | region 约束 | 冻结引擎 `QwenConfig.ready` 恒要求 `cn-beijing`；公有主机（无 workspace）不支持属**预期行为** | 同 #3 |

### 10.2 上下文投影机制（R2 · 代码 `64a7d68`，核心=`gateway/app/teacher_context.py` 578 行）

| 通道 | 机制 | 验证方式 |
|---|---|---|
| 政策 | `render_system_instruction(rec)` 拆首行+正文 → 写 `<teacher_id>/policy.json` 的 `persona.role/personality/name` + `language.default`（全部为 `render_instructions` 真实渲染且 schema 声明过的字段） | `PolicyStore` 回读校验，失败不挂载 |
| 教材 | **白名单靠数据投影**（冻结 `behavior.py:334` 检索不传 `dataset_id` ⇒ 挂什么读什么）：授权且 enabled 的 dataset 投影为 `<teacher_id>/knowledge.json`；无授权→空路径+原因码，**绝不回退全库** | `KnowledgeStore` 回读 + 真实 `search()` 命中验证 |
| 记忆 | `memory_decision()` 恒禁用 + `memory_scope_unavailable`（无服务端可确定的学生身份，启用=无归属读写） | fail-closed 断言 |
| 课堂记录 | 包装 `conn.qwen.on_event` **只读**观察两条终态转写事件；三前提齐备才建 `modality="voice"` 记录：`TEACHING_FILE` + `TEACHER_VOICE_STUDENT_ID` + 已校验模型绑定；结束不传 `outcome`（无音频证据⇒无发音结论） | 存储层证据门禁 |
| 切换隔离 | 逐老师投影 + 逐连接 config；`WORKBENCH_BASE_URL` 全局继承缺口已修复 | — |

**结构性不可行（勿再尝试）**：字面 teacher instructions 直灌 `session.update.instructions` 被冻结边界阻塞（`turns.py:266` 硬编码 QwenClient 构造；`behavior.py:62` 只收 config；policy schema "Unknown keys are errors"）。

### 10.3 `default_resolver` 校验链（R3-0 · 12 步 + `model_disabled` 门禁位置）

顺序：① `realtime_model_id` 非空 → ② 注册表/凭据库可加载 → ③ 模型存在 → ④ **`frozen`** → ④.5 **`enabled`（R3-0 插入：`if not bool(rec.get("enabled")): raise model_disabled`；缺键视为停用 fail-closed）** → ⑤ `enable_gate`（证据≥verified + 场景 `oral_realtime` 需 `realtime_safe`；**其不读 `rec["enabled"]`**） → ⑥ provider 存在 → ⑦ provider 冻结 → ⑧ 协议兼容 → ⑨ 凭据读取 → ⑩ 端点绑定 → ⑪ `build_teacher_qwen`（真实连接参数产生点） → ⑫ 等值拒绝。

- **拒绝语义**：④.5 拒绝 ⇒ 不投影上下文（resolve:493 → project:505 → build_config:516 → ws.prepare:524 → Connection:526 → open_record:533，行号为 HEAD `3b13c4c`），handler 直接 409，**无静默回退**（T11o 断言重新启用取服务商自有凭据且全局凭据逐值不变）。
- **正交性**：`enabled`=运维意图 ⊥ `frozen`=冻结边界（`mdl_frozen_tina` 为 `enabled:True, frozen:True`）；`create_model` 默认 `enabled:False`、`mark_frozen` 强制 False → 缺键只可能来自手改/损坏。
- **自证伪教训**：T11m 缺键旧行为=完整解析并携带服务商凭据返回；R2 的 e2e 用桩解析器绕过 resolver（夹具盲区）→ T13a2 夹具诚实性断言钉住。

### 10.4 GUI 与端点契约（R3-2C · `ee1b3ab`+`a49b6c9`）

- **老师列表**：`GET /xiaozhi/v1/teacher/list`——与老师 WS 同一恒时令牌鉴权；仅返回 enabled+未删+非冻结+realtime 模式老师；白名单字段 `{teacher_id, display_name, voice_id, language}`；无令牌/错令牌同 401（无枚举 oracle）；随 `mount()` fail-closed 挂载。
- **切换语义**：保存仅断开旧连接（`PROTOCOL_DISCONNECT_REQUEST`），**绝不自动重连**——真实连接只由用户「开始对话」建立（防保存悄悄触发计费连接）。
- **错误映射**：`client/src/utils/teacher_errors.py`，18+2 个服务端拒绝码→中文；GUI 透传失败原因（不再固定"未连接"）；不回显令牌。客户端 `websocket_protocol.py:48-84 _resolve_endpoint()` 每次建连重读三键；401/409 **不回退**冻结链路。
- **实时探针**（`gateway/app/admin/realtime_probe.py`）：拨号→`session.created`→`session.update`（纯配置，**无音频**）→`session.updated`；三阶段区分、`audio="not_tested"`、`verified` 恒 False、20 秒上限必关连接；阶梯新增 `realtime_handshake`（adapter_present 与 verified 之间，**握手成功永不授予 realtime_safe**）；独立授权位 `MODEL_REALTIME_PROBE_AUTHORIZED`（默认 "0"）+ `confirm_realtime:true`；对停用模型允许探针（证据是启用的前置）；仅用服务商自有密封凭据。

### 10.5 测试基线（**唯一维护点**，截至 R3-2C；环境：隔离 venv `xiaozhi-p2b2`，`PYTHONPATH=` 内联清空，`DYLD_LIBRARY_PATH=client/libs/libopus/mac/arm64`，Mock 上游）

| 套件 | 结果 | | 套件 | 结果 |
|---|---|---|---|---|
| `teacher_voice_seam_tests.py` | **60/60** | | `persona_policy_tests.py` | 62/62 |
| `teacher_context_seam_tests.py` | **83/83** | | `admin2_tests.py` | 69/69 |
| `model_v4_tests.py` | 72/72 | | `product_v1_integration.py` | 33/33 |
| `teacher_v4_tests.py` | 46/46 | | `product_boundary_tests.py` | 23/23 |
| `teaching_v4_tests.py` | 36/36 | | `admin_ui_tests.py` | 23/23 |
| `teaching_assessment_v4_tests.py` | 28/28 | | `memory1_tests.py` | 19/19 |
| `voice_v4_tests.py` | 74/74 | | `mvp_integration.py` | 28/28 |
| `admin_v4_api_tests.py` | 107/107 | | `behavior1_tests.py` | 111/111 |
| `import_v4_tests.py` | 39/39 | | `vocab_accuracy_tests.py` | 79/79 |
| `admin_security_tests.py` | 29/29 | | `memory_v1_tests.py` | 61/61 |
| `knowledge1_tests.py` | 72/72 | | `workbench1_tests.py` | 25/25 |
| `realtime_probe_tests.py`（R3-2C 新增） | **23/23** | | | |

客户端（`client/.venv` Py3.10.20）：`test_client_ui_transcript` 48/48、`test_gui_transcript_live` 25/25。
**环境性失败（既有基线，非语音链引入）**：`admin1_tests` 81/83、`r1f_tests` 2×OpusError（dev libopus 哨兵）、`client_ui1_integration` aiohttp reset；`admin_security_tests` 需 `PYTHONPATH=` 清宿主 shim（否则 `mkdir(exist_ok=True)` 误报）。

### 10.6 冻结六文件 sha256（**唯一维护点**；R2=R3-0 两次施工前后逐字节一致）

```
e18a0d08ed3a28771dee71d39dd5563f52f3d1199043ac81b8d9a7b5a2a498bd  gateway/app/turns.py
13d4800d416f678c33126e74bd857baab33afb5c9c3bfe2c80f6c0db798c9c32  gateway/app/qwen.py
c2218a2c3fda520089473e312ce6ee3fac4436c540755a8c98fd634ff7a87c09  gateway/app/audio.py
944e2d5ab4f0c2b13a51b547d366175cc18263575034566fda928b2a7b30d9f8  gateway/app/protocol.py
dde9d427883721c17628f40c73bf417bc9c0ab32711d07a4f22e9ed7ad63dd1c  gateway/app/ws.py
6d705960cb0154f17fa9eb0ce9ef1d651d0b4a64c9d4564fde5957d08d6a0088  gateway/app/behavior.py
```

### 10.7 未关闭问题台账（收敛自五份文档的分散清单；已关闭项留痕）

| 来源 | 问题 | 状态 |
|---|---|---|
| P2B2 验收 P2-D1 | `TEACHER_VOICE_TOKEN` env 优先于令牌文件（生产建议仅 `TEACHER_VOICE_TOKEN_FILE`） | 开放（低风险） |
| P2B2 验收 P2-D2 | 409 响应回带内部 `detail`（建议收敛为对外不透明错误码） | 开放（低风险） |
| P2B2 验收 P2-D3 | P2-B1/P2-B2 两套语音栈并行（通道释放语义未复用） | 开放（架构观察） |
| P2B2 验收 P2-D4 | 验收库 50 位历轮测试老师（enabled=False）待清理 | 开放 |
| R3-1 Agent C | 传输三风险：服务端可派生 `ws://` 明文 / 客户端 wss 不校验证书 / 网关恒绑 `0.0.0.0` | 开放（已列 §P6 工程项） |
| R3-2C §五 | 多学生正式授权未实现（现=单一部署令牌受信模型） | 开放（独立身份体系工程） |
| R3-2C §五 | 音频能力 `audio=not_tested`、`verified` 恒 False | **PENDING**（真实连接取证） |
| R3-1 §七 | 真实连接才能确认的 8 项（输出 pcm16 / session.update 附加字段 / 握手 / 音频设备 / 课堂记录收尾等） | **PENDING** |

**已关闭（留痕，不得再报）**：P1-D1 凭据继承→R1；`default_resolver` 未校验 `enabled`（Agent C P1/D7）→R3-0；`VOICE_GUI_ENTRY` MISSING→R3-2C；教学/记忆未接通→R2。

### 10.8 决策清单单点声明

产品负责人决策项**唯一维护点 = 本文件 §六**（最小决策清单）。以下为时点快照、仅引用不再更新：P2B2 验收 §七 C1–C6（C1 已关闭）、R2 §八 D1–D7（D7 已关闭）、R3-0 §八。验收入口 `P2B2_REAL_VOICE_ACCEPTANCE_ENTRY.md` 的 G1–G6 为**操作门禁视角**，作为独立操作指南保留（其头部已含演进注记）。
