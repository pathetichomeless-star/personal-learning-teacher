# R3-2A 非冻结真实模型接入准备 — 产品负责人操作指南（唯一交付物）

**分支** `p2b2-teacher-voice`　**基线 HEAD** `1ebc5b5`　**性质**：验收准备，**不含任何真实模型调用**
**本轮承诺**：不碰 Tina / 数字人 / NAS / 冻结六文件；不自动启用或提升任何模型；密钥永不经过聊天。

> **修订记录**
> v1.1（R3-2B，2026-10-11）：① 勘误费用口径——**第 7 步证据取证属独立计费授权门禁**（方式 A 是一次真实模型调用），移出"零费用"范围；② 全部启动命令显式增加 `QWEN_SECRET_FILE=`（空），阻断对本机 Tina 生产密钥文件的任何隐式加载（实测证据 E9）；③ 新增附录 A"百炼独立业务空间与独立 API Key 中文步骤"；④ 新增证据 E9–E10；⑤ 第 8 步措辞收紧为"仅走管理界面/后台 API"。

---

## 〇、最终状态字段

| 字段 | 结论 | 说明 |
|---|---|---|
| `R3_2A_READY` | **YES** | 准备完成且全部经隔离实测；真实连接仍需第八节批准 |
| `LOOPBACK_EXPOSURE` | **SAFE** | 前提＝用本指南第 3 步的**环回启动器**启动（stock `main()` 恒绑 `0.0.0.0`，不得用于验收）；实测三监听仅 `127.0.0.1`，局域网 IP 连接被拒 |
| `CLOUD_TRANSPORT` | **WSS_VERIFIED_CONFIG** | 登记入口强制 `https`+`443`+公网解析（`endpoint_policy.py:134-167`）→ 派生必为 `wss://`；云端 TLS 由 aiohttp 默认校验证书（`qwen.py:450-452` 未传 `ssl=`）；`http://` 云端 base_url 实测被拒 `scheme_must_be_https` |
| `TEST_TEACHER` | **PREPARED** | 验收老师载荷已定义并经隔离实例创建验证（音色 `Cindy`，与 Tina 可区分） |
| `MODEL_REGISTRATION` | **PREPARED** | `qwen3.8-omni-flash-realtime` 登记载荷已定义并经隔离演练验证；**未**启用、**未**提升证据 |
| `INDEPENDENT_CREDENTIAL` | **PENDING_USER_SETUP** | 录入面已备好（V4 管理界面表单）；等 PO 在**浏览器里**录入，密钥不经 Agent/聊天 |
| `ISOLATED_REAL_CONFIG` | **SAFE**（R3-2B 增补） | 前提＝启动命令显式 `QWEN_SECRET_FILE=`（空）。三组对照实测见 E9：硬化后 `ready=False`、凭据全空；本机 Tina 素材文件存在但不会被读取；老师路径凭据只来自隔离密封库 |
| `REAL_CONNECTION` | **NOT_AUTHORIZED** | 本轮零真实连接 |
| `HUMAN_AUDIO_TEST` | **PENDING** | — |
| `TINA_FROZEN` | **UNCHANGED** | 冻结六文件 sha256 与基线一致（见第三节 E1） |
| `NAS_CHANGED` | **NO** | 全程零 NAS 交互 |

---

## 一、本轮边界对照（指令十条 → 执行情况）

| # | 指令 | 执行 |
|---|---|---|
| 1 | 核对 HEAD 与 R1/R2/R3-0 门禁 | 已核（第三节 E1–E3） |
| 2 | 回环不暴露局域网；否则停并交最小整改 | stock `main()` **无法保证** → 交付最小整改＝环回启动器（已实测），并登记后续代码项（第六节） |
| 3 | 真实 Provider 只用 HTTPS/WSS | 结构性保证 + 负向实测（E4） |
| 4 | 准备 `qwen3.8-omni-flash-realtime` 配置清单，不自动启用/提升 | 已演练验证；演练注册表保持 `enabled=False`、无证据（E5） |
| 5 | 专用测试老师（独立绑定、可与 Tina 区分的合法音色） | `Cindy`（3.8 官方音色表内）；载荷经隔离创建验证 |
| 6 | 经既有后台安全录入独立 Key；密钥不经 Agent/聊天 | V4 管理界面表单（第 5 步）；密钥只在 PO 浏览器中出现一次 |
| 7 | 授权位 / 费用 / 时长 / 停止方式 | 第七节 |
| 8 | 私有记忆关、课堂记录不开 | 验收配置不设 `MEMORY_FILE`/`TEACHING_FILE`/`TEACHER_VOICE_STUDENT_ID` |
| 9 | 不碰 Tina / 数字人 / NAS / 冻结六文件 | 零触碰（E1） |
| 10 | 未批准不发起云端测试/不提升/不付费 | 本轮零真实连接 |

---

## 二、准备对象一览（第三位角色：第一位"非冻结真实老师"）

```
服务商（provider）   protocol=dashscope
                     base_url=https://<你的业务空间ID>.cn-beijing.maas.aliyuncs.com   ← 必须此形态
凭据（credential）   该业务空间自己的 DashScope API Key（绝不复用 Tina 的 Key）
模型（model）        model_key=qwen3.8-omni-flash-realtime
                     capabilities=["realtime_audio","streaming","barge_in"]
场景绑定             oral_realtime
证据（evidence）     本轮不动（保持 adapter_present；真实验证后另行取证/提升）
启用（enabled）      本轮不动（保持 False；R3-0 门禁实测拒绝 model_disabled）
老师（teacher）      voice.mode="realtime"、voice.voice_id="Cindy"、
                     model.realtime_model_id=<上面登记的模型 id>
```

---

## 三、门禁证据（总控本轮实测；E 编号供 QA 对照）

| 编号 | 证据 | 结果 |
|---|---|---|
| E1 | 冻结六文件 sha256（turns `e18a0d08…`/qwen `13d4800d…`/audio `c2218a2c…`/protocol `944e2d5a…`/ws `dde9d427…`/behavior `6d705960…`）；工作树仅既有数字人改动 | 一致/零触碰 |
| E2 | R1/R2/R3-0 复跑（R3-0 轮已测，本轮未改代码故延续有效）：`teacher_voice_seam_tests` 60/60、`teacher_context_seam_tests` 83/83、`model_v4_tests` 72/72 | 全绿 |
| E3 | 老师解析门槛（`teacher_voice.py:290-307`）：存在→未删→enabled→非冻结→`voice.mode=="realtime"`；随后 R3-0 `enabled` 门禁（:384-385）与其余六道门禁 | 亲读确认 |
| E4 | **登记入口负向实测**（隔离演练）：`http://<workspace>.cn-beijing.maas.aliyuncs.com` → `EndpointRejected: scheme_must_be_https`；`https://127.0.0.1` 与 `https://192.0.2.1` → `private_address_blocked` | 明文/私网全被拒 |
| E5 | **登记正向演练**（隔离临时注册表）：provider+model+`bind_scene(oral_realtime)` 全部被真实存储代码接受；`enabled=False`、`frozen=False`、`evidence_level=adapter_present`；`default_resolver` → **`model_disabled`**；仅启用不提升 → **`evidence_missing`** | 载荷可用且不会自动放行 |
| E6 | **回环隔离实测**（环回启动器 + 隔离存储 + 600 令牌）：`lsof` 三监听全部 `127.0.0.1`（61110/61111/61112）；对局域网 IP `192.168.1.16` 访问网关与 admin **均被拒**；admin 回环 200 | 无局域网暴露 |
| E7 | **老师路由四例**（真实客户端 venv 运行时 + `proxy=None`）：无令牌 401 `invalid_token`；错令牌 401；正确令牌+已登记老师（模型未登记）409 `model_missing`；未知老师 409 `teacher_not_found` | 全链路 fail-closed |
| E8 | **收尾实测**：`pkill`（SIGINT/SIGTERM 等价路径）后 `lsof` 为空；令牌文件 600 | 停止方式有效 |
| E9 | **`QWEN_MODE=real` 配置来源三组对照**（R3-2B 实测，脱敏输出）：A（`QWEN_SECRET_FILE=` 显式置空）→ `ready=False`、`not_ready="missing API key"`、api_key/workspace 全空；B（指向本机 `~/Desktop/小智/secrets/qwen-realtime.env`，**该文件确实存在**）→ **`ready=True`、密钥非空**——证明显式中和是必须项；C（默认 `/app/secrets/...`）→ 本机路径不存在 → `ready=False`（仅"路径恰好不存在"，非结构保证）。另：仓库 `config.json` 无任何密钥键（grep 实证）；shell 无 `QWEN_*` 环境变量 | 硬化后隔离成立 |
| E10 | **R3-2B 复验环回隔离**（硬化环境重跑）：lsof 三监听全 `127.0.0.1`；局域网 IP 访问网关与 admin 均拒；`health` 显示 `qwen_connected=0`；老师路由抽查 409 `model_missing`（fail-closed 不变） | 复验通过 |

---

## 四、产品负责人逐步操作说明

> 第 1–3 步＝纯本地准备（0 费用、无真实连接）。第 4–6 步与第 8 步＝登记动作（0 费用、仍无真实连接）。
> **第 7 步＝独立计费授权门禁**：方式 A（真跑测试）是一次**真实模型调用**，会产生费用且属于独立授权；方式 B（显式提升）本身不计费，但以其前置的真实取证为前提。**第 7 步不得视为"零费用登记"的一部分**，且未获单独批准前整步跳过（模型保持未启用，门禁会如实拒绝）。
> 第 9–10 步＝真实连接（**须先完成第八节批准**，否则停在第 8 步即可，环境可随时销毁）。

### 第 1 步　创建隔离目录与令牌

```sh
mkdir -p ~/xz-acc/{stores,data,secrets,client}
openssl rand -hex 32 > ~/xz-acc/secrets/teacher_voice_token
openssl rand -hex 32 > ~/xz-acc/secrets/admin_api_token
chmod 600 ~/xz-acc/secrets/*
```

### 第 2 步　创建环回专用启动器（唯一 sanctioned 启动方式）

把下面内容存为 `~/xz-acc/loopback_gateway.py`。它与生产 `app.main.main()` 用**完全相同**的路由与门禁代码，唯一差异是三个监听全部绑定 `127.0.0.1`（生产 `main()` 恒绑 `0.0.0.0`，会把老师入口暴露到局域网——因此验收期间禁止用 `app/main.py` 直启）。

```python
"""R3-2A 环回专用启动器（验收准备，非生产）。仓库零改动。"""
import asyncio, logging, signal, sys
from pathlib import Path
GATEWAY = Path("<project-root>/gateway")     # 按实际仓库路径调整
sys.path[:0] = [str(GATEWAY), str(GATEWAY.parent)]
from aiohttp import web
from app.main import create_app, load_config
from app.admin.config import load_admin_config
from app.admin.service import start_admin_listener
BIND = "127.0.0.1"

async def main():
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger("r32a.loopback")
    config = load_config()                       # 环境变量覆盖在此生效
    q = config.qwen
    if q.is_real and not q.ready:
        log.error("qwen real NOT READY: %s (不崩溃、不连接)", q.not_ready_reason)
    app = create_app(config)                     # 同一套路由（含旗标门控的老师路由）
    runners = []
    for port in (config.WS_PORT, config.HTTP_PORT):
        r = web.AppRunner(app); await r.setup()
        await web.TCPSite(r, BIND, port).start()            # ← 唯一差异
        runners.append(r); log.info("listening %s:%d", BIND, port)
    admin_cfg = load_admin_config()
    stores = None
    if admin_cfg.enabled:
        from app.admin.stores import AdminStores
        from modules.model.registry import frozen_link_snapshot
        snap = frozen_link_snapshot(mode=q.mode, model=q.model, voice=q.voice,
                                    host=getattr(q, "host", ""), frame_ms=config.FRAME_MS,
                                    reconnect_max=getattr(q, "reconnect_max", None))
        stores = AdminStores(policy_file=config.POLICY_FILE, memory_file=config.MEMORY_FILE,
                             knowledge_file=config.KNOWLEDGE_FILE, workbench_url=config.WORKBENCH_BASE_URL,
                             model_registry_file=config.MODEL_REGISTRY_FILE,
                             model_credentials_file=config.MODEL_CREDENTIALS_FILE,
                             model_credentials_key_file=config.MODEL_CREDENTIALS_KEY_FILE,
                             knowledge_import_file=config.KNOWLEDGE_IMPORT_FILE,
                             knowledge_import_scratch=config.KNOWLEDGE_IMPORT_SCRATCH,
                             teacher_file=config.TEACHER_FILE, teaching_file=config.TEACHING_FILE,
                             voice_file=config.VOICE_FILE, realtime_snapshot=snap,
                             test_authorized=str(config.MODEL_TEST_AUTHORIZED).strip() in ("1","true","yes"),
                             promote_authorized=str(config.MODEL_PROMOTE_AUTHORIZED).strip() in ("1","true","yes"))
    runners += await start_admin_listener(admin_config=admin_cfg,
        gateway_info=lambda: {"mode": "real" if q.is_real else "mock",
                              "ready": bool(q.ready), "model": q.model, "voice": q.voice},
        stores=stores)
    stop = asyncio.Event(); loop = asyncio.get_running_loop()
    for s in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(s, stop.set)
    await stop.wait()
    for r in runners:
        await r.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
```

### 第 3 步　启动 + 自检（0 费用、无真实模型）

**启动前密钥隔离自检（E9）**——证明不会隐式加载 Tina 生产密钥：
```sh
grep -n "QWEN_REALTIME\|QWEN_SECRET\|api_key" <project-root>/gateway/config/config.json
# 预期：无输出（仓库 config.json 无任何密钥键）
env | grep -E "^QWEN_" || echo "(当前 shell 无 QWEN_* 环境变量)"
ls /app/secrets/qwen-realtime.env 2>&1        # 预期：No such file or directory
```

```sh
# 隔离老师库与注册表（首次运行会自动建空库；老师登记在第 8 步）
cd <project-root>/gateway
env WS_PORT=61110 HTTP_PORT=61111 \
    PUBLIC_WS_URL=ws://127.0.0.1:61110/xiaozhi/v1/ \
    QWEN_MODE=mock \
    QWEN_SECRET_FILE= \
    TEACHER_VOICE_WS=1 \
    TEACHER_VOICE_TOKEN_FILE=$HOME/xz-acc/secrets/teacher_voice_token \
    TEACHER_VOICE_DATA_DIR=$HOME/xz-acc/data \
    TEACHER_FILE=$HOME/xz-acc/stores/teachers.json \
    MODEL_REGISTRY_FILE=$HOME/xz-acc/stores/model_registry.json \
    MODEL_CREDENTIALS_FILE=$HOME/xz-acc/stores/model_credentials.json \
    MODEL_CREDENTIALS_KEY_FILE=$HOME/xz-acc/stores/model_credentials.key \
    ADMIN_ENABLED=1 ADMIN_BIND=127.0.0.1 ADMIN_PORT=61112 \
    ADMIN_API_TOKEN_FILE=$HOME/xz-acc/secrets/admin_api_token \
    DYLD_LIBRARY_PATH=<project-root>/client/libs/libopus/mac/arm64 \
    PYTHONPATH= \
    <user-home>/.workbuddy/binaries/python/envs/xiaozhi-p2b2/bin/python \
    ~/xz-acc/loopback_gateway.py
```
> **`QWEN_SECRET_FILE=` 必须保留（显式置空）**：程序默认值是生产容器路径 `/app/secrets/qwen-realtime.env`（`main.py:30`），本机恰好不存在该路径才安全；且**本机存在 Tina 生产密钥素材文件**（`~/Desktop/小智/secrets/qwen-realtime.env`，实测：指向它时 `ready=True`、密钥非空——见 E9-B）。显式置空后无论文件是否存在都结构性地不读取（`qwen.py:175-178`：空路径直接返回空表）。

自检（另开终端）：
```sh
lsof -nP -iTCP -sTCP:LISTEN | grep -E '6111[012]'     # 三行都必须是 127.0.0.1:…
curl -s --noproxy '*' http://127.0.0.1:61111/health   # 200
LANIP=$(ipconfig getifaddr en0); curl -s --noproxy '*' --max-time 2 "http://$LANIP:61111/health" \
  && echo "!! 不该成功" || echo "局域网已隔离 ✔"
```
> **启动方式注意（QA 建议）**：请**原样在前台终端运行**上述命令，**不要**经 `nohup`/`sudo` 启动——macOS SIP 会剥掉 `DYLD_*` 环境变量，导致 opuslib 报 "Could not find Opus library"。需要后台跑时，用终端复用（tmux/screen）而不是 nohup。
> 注意：验收配置**刻意不设** `MEMORY_FILE`（私有记忆关）、`TEACHING_FILE`/`TEACHER_VOICE_STUDENT_ID`（课堂记录不开）——即指令第 8 条，缺失即关闭，无需额外开关。

### 第 4 步　登记服务商（0 费用）

浏览器打开 `http://127.0.0.1:61112/`（仅本机可达），用 `~/xz-acc/secrets/admin_api_token` 的令牌登录 → 模型中心 → 新建服务商：
- 名称：`R3-2A验收服务商`；协议：`dashscope`；
- 地址：`https://<你的业务空间ID>.cn-beijing.maas.aliyuncs.com`（**必须 https、不带路径与端口**；该域名须能公网解析，登记时会校验）。

### 第 5 步　录入独立 API Key（密钥不经过聊天）

同一界面"凭据"表单：选择第 4 步的服务商，把该业务空间的 DashScope Key 粘贴进密钥框，保存。
（底层即 `POST /admin/model/credentials`，密钥被加密密封落盘 `model_credentials.json`+主密钥文件；界面与接口都只回显指纹，不回显明文。**请不要把 Key 发给任何对话或脚本。**）

### 第 6 步　登记模型并绑定场景（0 费用）

模型中心 → 新建模型：服务商=第 4 步服务商；模型标识 `qwen3.8-omni-flash-realtime`；能力勾选 `realtime_audio / streaming / barge_in`；然后绑定场景 `oral_realtime`。
> 登记后模型保持 **未启用**、证据保持 **未验证** ——这是预期状态（本轮实测：此时老师连接会被 `model_disabled` 如实拒绝）。

### 第 7 步　证据取证（⚠️ 独立计费授权门禁——不属于零费用步骤）

> **本步是一扇独立的授权门**：它与第 4–6/8 步的"零费用登记"**无关**，必须获得第八节 P4（或专门的取证批准）后才可执行。未批准时**整步跳过**——模型保持未启用，老师连接会被 `model_disabled` 如实拒绝，不影响任何已完成的准备。
>
> **⚠️ R3-2B 勘误（工程实测）**：当前代码下面板"真实验证"对 **`dashscope` 协议模型不产生任何网络调用**——探测协议白名单仅含 `openai_compatible`/`openai_audio_compatible`（`modules/model/probe.py:35`），dashscope 直接返回 `no_free_probe_for_protocol`（零计费、**但也零证据**）。因此**方式 A 当前无法为验收模型取得 `verified` 证据**，第 8 步启用会停在 `400 evidence_missing`，第 10 步不可达。真实取证通道（对 dashscope 发起一次授权真实握手并写入证据）需要另行工程方案，已登记待产品负责人批准。在此解决之前，第 7/8/10 步处于**结构性待命**，这是 fail-safe 方向（多拦不放）。

- 方式 A：`MODEL_TEST_AUTHORIZED=1` 重启网关后，在模型中心对该模型执行"测试"——**对 `openai_compatible` 类服务商是一次免费元数据请求（不计费、不写 generation）**；**对 `dashscope` 模型当前不发起网络、不产生证据（见上方勘误）**；
- 方式 B：`MODEL_PROMOTE_AUTHORIZED=1` 且已有 `verified` 证据时，显式"提升 realtime_safe"（需 `confirm=true`；本地写状态不计费）。
- **本指南发布时两者都未开启**；证据未达标前，启用模型也无法通过门禁（实测 `evidence_missing`）。

### 第 8 步　启用模型并登记验收老师

模型中心 → 启用（`enable`）第 6 步的模型 → 记下模型 id（形如 `mdl_xxxxxxxx`）。
创建验收老师（管理界面"老师"页 → 新建；底层即 `POST /admin/teacher/teachers` + `/enable`）：

| 字段 | 值 |
|---|---|
| 名称 | `R3-2A验收老师` |
| 启用 | 是（`enabled=true`） |
| 交流方式 | `realtime` |
| 音色 | `Cindy`（3.8 官方音色表内的合法值，与 Tina 可区分） |
| 实时模型 | 第 6 步的模型 id |
| 交互 | `barge_in=true`（验收需要测自然打断） |

记下老师 id（形如 `tch_xxxxxxxx`）。此后老师连接门禁链＝令牌 → 老师解析 → `enabled` → 冻结/协议/凭据/端点 → 放行。

### 第 9 步　客户端隔离配置（不碰真实配置）

```sh
XIAOZHI_DATA_DIR=$HOME/xz-acc/client \
DYLD_LIBRARY_PATH=<project-root>/client/libs/libopus/mac/arm64 \
<project-root>/client/.venv/bin/python <project-root>/client/main.py --mode cli
```
首次运行会在 `~/xz-acc/client/config/config.json` 生成独立配置；将其 `SYSTEM_OPTIONS.NETWORK` 设为：
`WEBSOCKET_URL = ws://127.0.0.1:61110/xiaozhi/v1/`、`TEACHER_ID = <第 8 步老师 id>`、`TEACHER_VOICE_TOKEN = <teacher_voice_token 文件内容>`。
（真实配置目录零触碰；实测该环境变量下读写全部落在隔离副本。）

### 第 10 步　真实连接窗口（须第八节 P4 批准）

**前置条件（QA 提示）**：必须先完成第 7 步证据取证——否则模型虽已启用但证据仍是 `adapter_present`，老师连接会被如实拒绝 `409 evidence_missing`（QA 独立实测确认）。

批准后：把网关的 `QWEN_MODE=mock` 改为 `QWEN_MODE=real` 重启（**同一启动器、同一组环境变量，`QWEN_SECRET_FILE=` 必须保持显式置空**——本机存在 Tina 生产密钥素材文件，绝不能把 `QWEN_SECRET_FILE` 指向它；见 E9-B）。老师路径的凭据**只**来自密封凭据库（第 5 步录入的独立 Key），全局 `QwenConfig` 与老师路径无关（R1 清继承 + 同值拒绝）。`ready` 门禁会校验凭据/业务空间/区域，未就绪只会报错不崩溃 → 启动客户端 → 正常对话。**建议单次 ≤10 分钟。**

### 第 11 步　停止与恢复（任何时刻可执行）

1. 网关终端 `Ctrl-C`（或 `pkill -f loopback_gateway.py`）；`lsof -nP -iTCP -sTCP:LISTEN | grep 6111` 应为空；
2. 客户端直接退出；
3. `rm -rf ~/xz-acc` 销毁全部隔离物（含令牌与凭据库副本）；
4. 照常启动客户端（不带 `XIAOZHI_DATA_DIR`）即恢复 Tina 常规用法；NAS 与生产全程未被触碰。

---

## 五、费用、时长与消耗护栏

| 项 | 数值 |
|---|---|
| 准备 / 登记（第 1–6、8 步）/ 回环自检 | **0 元**（无真实连接） |
| **第 7 步方式 A：真跑测试取证** | **R3-2B 勘误：对 `dashscope` 模型当前零网络、零计费、但也零证据**（探测白名单仅含 openai 兼容协议，`probe.py:35`）——真实取证通道需另行工程方案，见第 7 步勘误块 |
| 第 7 步方式 B：显式提升 `realtime_safe` | **0 元**（本地写状态），但以其前置的真实取证为前提 |
| 免费额度 | `qwen3.8-omni-flash-realtime` 北京区 **100 万 token / 90 天**（自开通、模型发布或审批通过较晚者起算）【官方文档确认】 |
| 超额单价（北京） | 音频入 6 / 音频出 12 / 文本入 1.5 / 文本出 4.5 元每百万 token |
| 预计测试时长 | 单次 5–10 分钟；免费额度可覆盖多轮验收；即使超额，单轮也仅个位数人民币量级 |
| 消耗护栏 | 三道 fail-closed 门禁（无启用模型/无凭据/旗标关）之外**没有用量熔断**——建议在阿里云控制台设置用量告警，并遵守单次时长上限 |

## 六、登记的后续工程项（本轮不改码）

1. `app.main` 增加 `WS_HOST`（默认 `127.0.0.1`）或等价能力，消除"环回启动器"这一手动步骤；
2. `provider_realtime_binding` 对**非环回**主机强制 `https→wss`（当前仅登记入口强制 https；手改存储文件可绕过——深度防御缺口）；
3. 客户端 wss 证书校验（当前模块级 `_create_unverified_context` 不校验）；
4. 用量熔断/预算闸。

## 七、诚实边界

- 本轮**没有**任何真实连接：`wss://…maas.aliyuncs.com` 的 DNS/TLS/Bearer 握手、`qwen3.8-omni-flash-realtime` 是否接受输出 `pcm16`、`session.update` 附带 `model` 字段与 `session.finish` 的容忍度、音色实际听感——均只能在第 10 步真实窗口确认。
- 凭据尚未录入（`INDEPENDENT_CREDENTIAL=PENDING_USER_SETUP`）；模型/老师尚未在真实存储登记（本指南只交付载荷与步骤，实际登记发生在隔离目录中由 PO 执行）。
- 隔离演练中的 `ws-acceptance-placeholder` 域名使用注入 DNS 证明"载荷形状被接受"；真实业务空间域名的解析在 PO 登记时自然发生。

## 八、需产品负责人批准的事项

| # | 事项 | 费用 |
|---|---|---|
| P1 | 在百炼创建**独立业务空间**并获得其绑定 WS 地址（`https://<业务空间ID>.cn-beijing.maas.aliyuncs.com`），步骤见附录 A | 0 |
| P2 | 为该业务空间生成**独立 API Key**（不复用 Tina；建议"自定义"权限收敛到单一模型），步骤见附录 A | 0 |
| P3 | 批准按第 4–6、8 步在隔离目录登记（服务商/凭据/模型/老师；模型保持未启用）。**不含第 7 步** | 0 |
| P4 | **批准第 7 步证据取证与第 10 步真实连接窗口** + 阿里云控制台用量告警。⚠️ R3-2B 勘误：当前面板对 `dashscope` 模型拿不到证据（第 7 步勘误块）——**P4 批准前需先解决真实取证通道的工程方案**，否则第 8/10 步不可达 | 第 10 步真实连接按量计费（免费额度内 0 元） |
| P5 | （可选）课堂记录是否在真实验收时开启（需 `TEACHING_FILE`+`TEACHER_VOICE_STUDENT_ID`） | 0 |

## 九、独立 QA 签收（2026-10-11，qaR32A 实际运行后回填）

**结论：`QA_PASS_WITH_NOTES` —— 0 个 P0 / 0 个 P1 / 0 个 P2 / 3 个 P3（均为操作性/表述建议，已并入本指南）。**

QA 独立复现（非转抄）：自建 /tmp 隔离存储 + 令牌 + **自写启动器**（62210–62212），复现回环隔离（lsof 全 `127.0.0.1`；局域网 IP 192.168.1.6 连网关与 admin 均拒连；回环 health 200）；老师路由四例同码（401×2 / 409 `model_missing` / 409 `teacher_not_found`）；登记演练独立复跑（含三个负端点拒绝码逐一吻合、`model_disabled`/`evidence_missing` 阶梯）；复跑三套件 60/60、83/83、72/72；六文件 sha256 与 E1 一致；HEAD 仍 `1ebc5b5`、工作树仍为既有数字人改动。

**QA 证伪探针**：自构 `0.0.0.0` 变体（一次性端口 63333，短暂）——lsof 显示 `*:63333`、LAN IP 实际可达（200），其 127.0.0.1 检查正确 FAIL，变体已停无残留。这同时实证了 stock `main()` 的危险与本指南"环回启动器为唯一 sanctioned 方式"的必要性。

**QA 三项建议（已并入）**：
| 编号 | 建议 | 处置 |
|---|---|---|
| P3-1 | 勿经 `nohup`/`sudo` 启动（SIP 剥 `DYLD_*` → opuslib 报错） | 已写入第 3 步"启动方式注意" |
| P3-2 | 第 8 步勿暗示手改存储文件，统一走管理界面/后台 API | 指南已在 QA 阅读同期改为"管理界面'老师'页 → 新建；底层即 `POST /admin/teacher/teachers` + `/enable`" |
| P3-3 | 第 10 步显式声明"须先完成第 7 步取证，否则 `409 evidence_missing`" | 已写入第 10 步前置条件 |

**QA 无法核实（与指南诚实边界一致）**：真实 workspace 域名 DNS/TLS/Bearer 握手、Cindy 音色实际听感、`session.update` 容忍度（须 P4 真实窗口）；免费额度/单价为文档级声明（QA 仅核对标注存在，遵守禁连云端约束）。

QA 隔离物全部清理、仓库零改动、未发起任何真实连接。

---

## 附录 A　阿里云百炼独立业务空间与独立 API Key 中文步骤（R3-2B 增补）

> 目的：给第二位老师一套**与 Tina 完全隔离**的计费与凭据来源（独立业务空间 = 独立成本核算 + 独立权限 + 独立 Key）。
> 口径来源：阿里云百炼官方文档《获取与配置 API Key》《业务空间管理》（help.aliyun.com/zh/model-studio/get-api-key 等）；控制台菜单名可能随版本微调，以控制台实际为准。
> **密钥纪律**：Key 只在百炼控制台弹窗中出现一次，复制后存入你自己的密码管理器；随后仅在**第 5 步的管理界面表单**里粘贴一次。不要发给任何对话、脚本或日志。

**A1　创建独立业务空间**
1. 登录 [阿里云百炼控制台](https://bailian.console.aliyun.com/)，右上角地域切换到**华北2（北京）**（免费额度与 WS 地址绑定北京）。
2. 首次使用先**开通模型服务**（按页面提示签署协议；免费额度自开通之日起 90 天内有效）。
3. 右上角**设置 → 业务空间管理**：使用默认业务空间，或**新增业务空间**（建议命名 `xz-acceptance`，用于独立成本核算与权限隔离）。复制该空间的 **Workspace ID**。
4. 为该业务空间**授权模型**：在业务空间管理中对子空间进行模型授权，勾选 `qwen3.8-omni-flash-realtime`（子空间的 Key 只能调用已授权模型——官方规则）。
5. 记录业务空间绑定的 WS 接入信息：按官方《实时调用指南》"建立连接"，业务空间专属 WebSocket 地址形如 `https://<业务空间ID>.cn-beijing.maas.aliyuncs.com`（即第 4 步登记服务商时填的 base_url）。

**A2　创建独立 API Key（归属该业务空间）**
1. 右上角**设置 → API-KEY**（需主账号或具备 API-Key 页面权限的账号）→ **创建 API Key**。
2. 弹窗中：**归属业务空间**＝A1 创建的 `xz-acceptance`（不要选"默认业务空间"）；权限建议选**自定义**——可访问模型范围仅勾选 `qwen3.8-omni-flash-realtime`（可再配 IP 白名单）。
3. 创建成功后弹窗**一次性**显示完整明文 Key——立即复制保存到你的密码管理器；关闭后无法再查看明文（丢失只能重置/新建）。
4. （可选加固）之后可在 API Key 列表随时**禁用/重置**该 Key（北京地域支持），作为测试结束后的额外保险。

**A3　与本项目对接**
- 业务空间 ID → 第 4 步服务商 `base_url`；
- API Key → 第 5 步管理界面凭据表单（仅粘贴一次）；
- 模型标识 → 第 6 步 `qwen3.8-omni-flash-realtime`；
- 限额：每主账号最多 20 个业务空间、每空间最多 20 个 Key——独立空间不会挤占 Tina 所在空间的 Key 配额。

**A4　与 Tina 的隔离关系（官方口径）**
- API Key 的调用权限完全由其**归属业务空间**决定，跨空间 Key 互不可用；
- 独立空间 ⇒ 独立计费核算，Tina 的用量与第二老师的用量在账单上天然分离；
- 第 5 步录入后，`default_resolver` 的 belt-and-braces 仍会拒绝任何等于全局 Tina Key 的凭据（双保险）。
