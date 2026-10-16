# XIAOZHI P2-B2 — 真实语音验收入口（产品负责人操作手册）

> **当前状态：不可执行（HUMAN_TEST_BLOCKED）。**
> 本手册为"解除阻塞后即可照做"的逐步操作说明。在 §0 前置门禁未全部满足前，**请勿执行 §2 及以后步骤**。
> 本手册不涉及、也不需要任何 NAS 操作。
>
> **状态演进注记（2026-10-13 总控收录 · append-only，不改动上文与下文原文）**：本手册主体为 P2B2 验收时点记录，其时点后已发生的关闭项——§0 的 G4（P1-D1 凭据继承）已由 R1（提交 `06314f8`）修复关闭；§6 的"教学/记忆未接通"已由 R2（teacher_context 接入）关闭、"P1 潜在凭据缺口"已由 R1 关闭；Mac GUI 老师入口缺失已由 R3-2C 补全（中文错误映射 18+2 码）。**当前仍阻塞**：G1（非冻结实时模型=0）、G2（PO 书面授权）、G3（独立服务商凭据）、G6（绑定实时模型的老师=0）、G5（验收指向本机隔离实例还是 NAS 待确认）。全部解除后即可照本手册执行。当前状态汇总见同目录 `R3_1_REAL_AUDIO_READINESS_REPORT.md` §九。

---

## §0 前置门禁（全部满足后方可执行，缺一即停）

| 编号 | 条件 | 判定方法 | 当前 |
|---|---|---|---|
| G1 | 存在一个**非冻结**、已验证、可用于 `oral_realtime` 的实时语音模型 | 管理面"AI 模型与连接"中该模型状态为"实时安全"且非内置只读 | ✗ 未满足 |
| G2 | 该模型已获产品负责人**书面授权**用于真实调用 | 授权记录 | ✗ 未满足 |
| G3 | 该模型的**真实凭据已安全落位**（600 权限，不打印、不入库明文） | 凭据文件存在且权限正确 | ✗ 未满足 |
| G4 | **P1-D1（逐老师凭据继承）已关闭**或已确认替代方案 | 见验收报告 §五 P1-D1 | ✗ 未满足 |
| G5 | 真实连接环境**可达**（客户端与网关互通） | 连通性探测。注：客户端当前 `WEBSOCKET_URL = ws://192.0.2.1:28310/xiaozhi/v1/`（NAS 产品边车端口），需先确认验收指向本地隔离实例还是 NAS | ✗ 未确认 |
| G6 | 已为验收老师绑定 `realtime_model_id` 与 `voice.voice_id` | 当前**非冻结且绑定实时模型的老师数 = 0** | ✗ 未满足 |
| G7 | 已验证**不影响生产 Tina**（隔离端口 / 隔离数据目录） | 见 §1 隔离要求 | ✗ 未确认 |

**任一条件为 ✗ → 立即停止于 `HUMAN_TEST_BLOCKED`，不重试、不自行放宽。**

---

## §1 隔离要求（硬约束）

1. **独立端口**：不得占用生产端口（WS 8110 / HTTP 8111 / 管理面 28310-28312）。本机隔离建议：网关 WS/HTTP 使用独立端口，例如 `WS_PORT=18110`、`HTTP_PORT=18111`。
2. **独立数据目录**：全部存储指向临时隔离目录，禁止指向生产数据。
3. **不修改冻结代码**、**不部署 NAS**、**不打开生产付费授权开关**（`MODEL_TEST_AUTHORIZED` / `MODEL_PROMOTE_AUTHORIZED` 生产保持 `0`）。
4. **凭据不落日志**：令牌与 API Key 一律不打印、不写文档、不进对话。
5. 隔离环境可以授权（`MODEL_TEST_AUTHORIZED=1`）**仅限**本地 mock 或无付费密钥的场景；一旦涉及真实凭据，须先完成 G2/G3/G4。

---

## §2 启动隔离联调实例（网关侧）

在仓库根目录执行（用隔离 venv，勿污染用户环境）：

```bash
V=<user-home>/.workbuddy/binaries/python/envs/xiaozhi-p2b2
LIB="<repo>/admin0-backups/pre-monorepo-originals/py-xiaozhi/libs/libopus/mac/arm64"
RUN=/tmp/xiaozhi-p2b2-accept          # 隔离数据目录
mkdir -p "$RUN/secrets"

# 1) 生成部署令牌（不打印其内容）
python3 -c "import secrets;open('$RUN/secrets/teacher_voice_token','w').write(secrets.token_urlsafe(32))"
chmod 600 "$RUN/secrets/teacher_voice_token"

# 2) 启动（示例：flag 打开 + 隔离存储 + 完整老师/模型存储）
cd gateway
env -u PYTHONPATH DYLD_LIBRARY_PATH="$LIB" \
  TEACHER_VOICE_WS=1 \
  TEACHER_VOICE_TOKEN_FILE="$RUN/secrets/teacher_voice_token" \
  TEACHER_VOICE_DATA_DIR="$RUN/teacher-data" \
  TEACHER_FILE="$RUN/teachers.json" \
  MODEL_REGISTRY_FILE="$RUN/model_registry.json" \
  MODEL_CREDENTIALS_FILE="$RUN/model_credentials.json" \
  MODEL_CREDENTIALS_KEY_FILE="$RUN/model_credentials.key" \
  WS_PORT=18110 HTTP_PORT=18111 \
  "$V/bin/python" -m app.main
```

**启动成功自检**：日志出现 `teacher voice WS mounted at /xiaozhi/v1/teacher/` 才算挂载成功。
若出现 `TEACHER_VOICE_WS=1 but no token configured` 或 `teacher store unavailable` → **未挂载**（fail-closed），不得继续。

---

## §3 负向验证（真人测试前必做，均为"应当被拒绝"）

| 步骤 | 操作 | 期望结果 |
|---|---|---|
| N1 | 不带 `X-Teacher-Token` 连接 `/xiaozhi/v1/teacher/?teacher_id=<A>` | HTTP 401，**不建立连接** |
| N2 | 带**错误**令牌连接 | HTTP 401 |
| N3 | 带正确令牌，`teacher_id` 为不存在的老师 | HTTP 409 `teacher_not_found` |
| N4 | 带正确令牌，`teacher_id=tina`（冻结老师） | HTTP 409 `frozen_realtime_only`，**Tina 不被接管** |
| N5 | 带正确令牌，老师为**文本模式** | HTTP 409 `voice_mode_text` |
| N6 | 老师已启用但**无可用实时模型** | HTTP 409 `realtime_not_configured`（**不得冒充成功**） |

任一项不符合期望 → 停止，登记缺陷，不启动修复开发。

---

## §4 真人语音验收（产品负责人本人执行）

> 全程由**产品负责人本人**操作与判定；自动化 Agent 的主观描述不作为验收结论。

**准备 A — 客户端运行时（已就绪，无需安装）**

真实客户端运行时为 `client/.venv`（Python 3.10.20），已含：`PySide6 6.10.1`、`sounddevice 0.5.3`、`sherpa_onnx 1.13.0`、`soxr`、`numpy`、`websockets 15.0.1`、`aiohttp`、`pynput`；Opus 由内置 `client/libs/libopus/mac/arm64/libopus.dylib` + `client/src/utils/opus_loader.py` 加载。**启动客户端请使用该 venv，不要使用系统 Python 或网关测试 venv。**

**准备 B — 客户端端点配置**（文件：`<user-home>/Library/Application Support/py-xiaozhi/config/config.json`，键路径 `SYSTEM_OPTIONS.NETWORK.*`）

- `WEBSOCKET_URL` → 隔离实例地址，例如 `ws://127.0.0.1:18110/xiaozhi/v1/`
  （**当前值为 `ws://192.0.2.1:28310/xiaozhi/v1/`，指向 NAS；执行前须先确认 G5**）
- `TEACHER_ID` → 待验收老师的 `teacher_id`
- `TEACHER_VOICE_TOKEN` → §2 步骤 1 生成的部署令牌

客户端将在**每次连接时**重新解析端点：未配置 `TEACHER_ID` 时 URL/headers 与现状**逐值一致**（可先做此回归再配置老师）。

### A. Tina 原有链路回归
- 清空 `TEACHER_ID` / `TEACHER_VOICE_TOKEN`，连接 `ws://<host>:<port>/xiaozhi/v1/`，确认与既有行为一致。
- **仅在获得真实调用授权与安全测试条件后执行**。

### B. 新老师真实麦克风通话
- 配置 `TEACHER_ID=<老师A>`，正常说话，确认有真实应答与回放。

### C. 老师使用自己的声音、教学规则及模型回答
- 确认音色 = 老师A 的 `voice.voice_id`；教学风格/规则 = 老师A 的配置；后端模型 = 老师A 的 `model.realtime_model_id`。

### D. 自然打断
- 在老师说话中途插话，记录真实表现（是否停止、延迟、是否残留播放）。

### E. 切换到第二位老师
- 切换 `TEACHER_ID=<老师B>` 重新连接，确认**模型、声音、教材均不串用**（与 A 不同）；确认 A 的旧会话已释放。

### F. 结束并重新连接
- 结束会话后重连，确认旧会话释放、学习记录归属正确（同一 `student_id` 下不同老师互不覆盖）。

### G. 模型不可用时的提示
- 停用老师B 的模型后重连，确认给出**明确失败提示**，且**不冒充成功**。

### 记录要求
- 每项记录：时间、老师、连接结果、音色/模型是否一致、异常现象、原始日志片段（**不得包含令牌/密钥**）。
- 录制/文本证据自行保管，**不输出学生原始录音**至本仓库或对话。

---

## §5 完成后交回材料

1. §3 负向验证结果表（6 项）。
2. §4 A–G 逐项结论（PASS / FAIL / 现象描述）。
3. 是否观察到"声音/教材/模型串用"、"旧会话未释放"、"冒充成功"三类问题。
4. 若发现缺陷：**只登记**，交由产品负责人决定是否启动修复。

---

## §6 为什么现在不能执行（对照当前证据）

| 阻塞点 | 证据 |
|---|---|
| 无非冻结实时模型 | **直接读库**（`.xiaozhi-v4-acceptance/stores/model_registry.json`）：非冻结 `realtime_safe` = **0**；`modules/voice/registry.py:80,86` 真实适配器 `available=False` |
| 无校验对象 | **直接读库**（`teachers.json`）：非冻结且绑定 `realtime_model_id` 的老师 = **0 位**（唯一绑定者是冻结 Tina） |
| 默认未挂载 | `gateway/app/main.py:58` `TEACHER_VOICE_WS="0"`；`gateway/config/config.json` 未设置该项 |
| 教学/记忆未接通 | `gateway/app/teacher_voice.py` 零引用 `modules.teaching` / `modules.memory`（全仓 grep） |
| P1 潜在凭据缺口 | `teacher_voice.py:137` 浅拷贝继承 `api_key`；`gateway/app/qwen.py:233-234` 以 `Bearer <api_key>` 认证 |
| 连接可达性未确认 | 客户端 `WEBSOCKET_URL = ws://192.0.2.1:28310/xiaozhi/v1/`（NAS），本机对 NAS 可达性此前记录为不可达 |

> **已排除的阻塞点（重要更正）**：真实客户端运行时**齐备**（`client/.venv`：PySide6 6.10.1 / sounddevice 0.5.3 / sherpa_onnx / libopus + opus_loader），不构成阻塞。

参见同目录 `P2B2_ACCEPTANCE_REPORT.md`（原件已删除，PROJECT-DOC-MERGE-01 批准；恢复=项目外备份 `<offsite-backup>/merge01-20261013/docs/engineering/product-v1/`）。
