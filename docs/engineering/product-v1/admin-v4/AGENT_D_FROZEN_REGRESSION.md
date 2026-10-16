# Agent D · 冻结面回归审计报告（V4 未破坏 Tina 冻结链路 / ADMIN P0 基线）

- 审计角色：独立回归审计代理（Agent D），**只读**
- 仓库：`<project-root>`，分支 `v4-admin-dev`，HEAD `d177582`
- 审计范围：V4 是否改动「Tina 冻结实时语音链路」与「ADMIN P0 安全基线」
- 约束遵守：未改任何源文件（仅写本报告）；未停止/重启任何进程（127.0.0.1:8119 / 8123 未触碰）；未调用付费模型；未 SSH NAS；未 commit；测试输出均为原始粘贴

---

## 0. 结论（TL;DR）

**HOLD：Tina 冻结链路未被 V4 触碰 —— 成立。**

- 冻结语音链路文件（`turns.py / audio.py / qwen.py / diag.py / counters.py / protocol.py / http.py`）**零改动**（`git diff HEAD` 空）。
- ADMIN P0 基线文件 `admin/auth.py / registry.py / service.py` **零改动**（`git diff HEAD` 空）。
- V4 对 `main.py` 的接线为**只读快照**，不写 qwen/Tina 配置、不切换模型、不改音频路径。
- 三套历史回归套件全绿：`admin_security_tests 29/29`、`admin_ui_tests 23/23`、`admin2_tests 69/69`。
- `admin1_tests.py` 因缺 opuslib / 系统 Opus 库**无法运行**（非 V4 引入，如实记录，未伪造）。
- V4 新模块 import 边界纯净：`modules/model/*`、`modules/knowledge/*` 不 import gateway 音频/协议模块；`gateway/app/admin/*` 不触碰音频写路径。
- 冻结条目实证只读：`ensure_frozen_link` 只写模型注册表 JSON，原始 qwen 配置字典不变，且冻结条目拒绝一切变更。

Blocker：0；Major：0；Minor：2（见 §6）。

---

## 1. 工作树改动核对（`git status --porcelain=v1` / `git diff --stat`）

原始输出（未提交改动）：

```
 M client/probe_avatar_qml_offscreen.py
 M client/src/avatar/runtime/avatar_page.js
 M client/src/ui/gui/manager.py
 M client/src/ui/gui/qml/components/AvatarLive2D.qml
 M docs/engineering/product-v1/avatar-vision-v0/V1_MAC_GUI_ACCEPTANCE.md
 M gateway/app/admin/api.py
 M gateway/app/admin/app.py
 M gateway/app/admin/config.py
 M gateway/app/admin/stores.py
 M gateway/app/admin/views.py
 M gateway/app/main.py
 M gateway/tests/knowledge1_tests.py
 M modules/knowledge/store.py
```

`git diff --stat` 汇总：13 files changed, 766 insertions(+), 73 deletions(-)（另有大量未跟踪新增文件：`modules/model/`、`modules/knowledge/imports.py`、`modules/knowledge/parsers.py`、`gateway/app/admin/api_model.py`、`api_import.py`、`admin-v4/`、`gateway/tests/*_v4_tests.py` 等）。

### 判定表：每个已修改文件是否属于冻结面

| 文件 | 是否改动 | 是否冻结面 | 判定 |
|---|---|---|---|
| `gateway/app/main.py` | 是 | 冻结语音链路入口（**非纯冻结逻辑文件**） | 仅新增 V4 配置键 + **只读** `frozen_link_snapshot()` 调用，无写路径（见 §2.2） |
| `gateway/app/admin/api.py` | 是 | **ADMIN P0 基线**（ADMIN-2 控制面） | 增量：新增 `StoreUnavailable→503` 映射、`_need_avail()` 只读守卫、V4 路由条件挂载；**不改认证/鉴权核心** |
| `gateway/app/admin/app.py` | 是 | **ADMIN P0 基线**（ADMIN-1 应用装配） | 增量：注册 `/v4/*` 静态壳与 V4 store 接线位；隔离于音频/OTA 应用 |
| `gateway/app/admin/config.py` | 是 | **ADMIN P0 基线** | 增量：新增 `ui_v4_dir` 字段/默认值，无副作用 |
| `gateway/app/admin/stores.py` | 是 | **ADMIN P0 基线** | 增量：惰性创建 V4 store + `_detect_frozen()` 只读镜像；fail-soft |
| `gateway/app/admin/views.py` | 是 | **ADMIN P0 基线** | 增量：新增 `v4_shell()` 静态文件服务；既有 `ui_shell` 行为不变 |
| `modules/knowledge/store.py` | 是 | 非冻结（KNOWLEDGE-1 存储） | 增量：`StoreUnavailable` 拒写语义 + docx/pptx 源类型；不涉及音频 |
| `gateway/tests/knowledge1_tests.py` | 是 | 非冻结（系统测试） | 新增 K7f–K7i 用例（拒绝损坏/更新版本文件）；不涉及音频 |
| `client/*`（4 文件） | 是 | 非冻结（客户端） | Live2D/avatar 相关，与网关冻结链路无关 |
| `docs/.../V1_MAC_GUI_ACCEPTANCE.md` | 是 | 非冻结（文档） | 文档 |

> **高亮**：`auth.py / registry.py / service.py`（ADMIN-1 鉴权与生命周期基线）**未出现在改动列表**，`git diff HEAD` 为空 —— ADMIN P0 基线未被改写。

---

## 2. 冻结文件逐文件核对

### 2.1 冻结文件 diff（原始输出：空）

命令：

```
git diff HEAD -- gateway/app/turns.py gateway/app/audio.py gateway/app/qwen.py \
                 gateway/app/diag.py gateway/app/counters.py gateway/app/protocol.py \
                 gateway/app/http.py gateway/app/behavior.py gateway/app/ws.py
```

输出：**（空，exit 0）**

`git diff HEAD -- gateway/app/admin/auth.py gateway/app/admin/registry.py gateway/app/admin/service.py --stat`
输出：**（空）**

### 2.2 `gateway/app/*.py` 全量核对（除 `admin/` 与 `main.py`/`ws.py`）

| 文件 | 是否改动 | 判定 |
|---|---|---|
| `gateway/app/turns.py` | 否 | 冻结语音主链路 —— 未触碰 |
| `gateway/app/audio.py` | 否 | Opus 编解码 —— 未触碰 |
| `gateway/app/qwen.py` | 否 | Qwen 实时上游 —— 未触碰 |
| `gateway/app/diag.py` | 否 | R-1c 诊断 —— 未触碰 |
| `gateway/app/counters.py` | 否 | 计数器 —— 未触碰 |
| `gateway/app/protocol.py` | 否 | 协议 —— 未触碰 |
| `gateway/app/http.py` | 否 | OTA/Vision HTTP —— 未触碰 |
| `gateway/app/behavior.py` | 否 | BEHAVIOR-1 —— 未触碰 |
| `gateway/app/__init__.py` | 否 | 未触碰 |

### 2.3 `main.py` V4 接线是否为只读

`main.py` diff 仅含 3 处增量（`git diff HEAD -- gateway/app/main.py`）：

1. `DEFAULTS` 新增 6 个 V4 键（`MODEL_REGISTRY_FILE` 等，默认空 = 不挂载）。
2. `load_config()` 透传上述键。
3. `_run()` 中 `admin_cfg.enabled` 分支：

```python
from modules.model.registry import frozen_link_snapshot
# read-only snapshot of the EXISTING (frozen) realtime link — detection
# only; nothing here changes the audio path.
frozen_snap = frozen_link_snapshot(
    mode=q.mode, model=q.model, voice=q.voice,
    host=getattr(q, "host", ""), frame_ms=config.FRAME_MS,
    reconnect_max=getattr(q, "reconnect_max", None))
stores = AdminStores(..., realtime_snapshot=frozen_snap, test_authorized=...)
```

判定：**只读**。`frozen_link_snapshot(...)` 为纯函数，仅构造 dict 并返回（见 §5）；传入的 `q.mode/model/voice` 取自既有配置且**未被回写**；无任何写 qwen 配置、切换模型、改变音频路径的代码。`AdminStores._detect_frozen()` 失败亦 fail-soft，不影响实时链路。

---

## 3. 历史回归套件原始结果（禁止调用付费模型）

### 3.1 `admin_security_tests.py`

```
ADMIN_SECURITY_TESTS: 29 checks, 29 PASS, 0 FAIL
```

（含 S1 匿名 401、S1c 无 oracle、S2 路由表匹配、S4 token 不入日志、S9 无 token 不启动监听、S10 `hmac.compare_digest` 等 —— 全部 PASS）

### 3.2 `admin_ui_tests.py`

```
ADMIN_UI_TESTS: 23 checks, 23 PASS, 0 FAIL
```

（U1「39-route table」、U4 仅 GET/POST、U5/U6 危险操作二次确认、U16 UI 来源仍需鉴权等 —— 全部 PASS）

### 3.3 `admin2_tests.py`

```
ADMIN2_TESTS: 69 checks, 69 PASS, 0 FAIL
```

（A1–A7 路由/405、B1–B13 策略、C1–C15 记忆边界、D1–D17 知识库、E1–E6 Workbench、F1–F7 行为、G1–G2 审计 —— 全部 PASS）

### 3.4 `admin1_tests.py`（**无法运行**，如实记录）

先按要求用 `.venv-v4`：

```
ModuleNotFoundError: No module named 'opuslib'
  (gateway/app/audio.py:9  import opuslib)
```

再回退到 `gateway/.venv`（3.14）：

```
Exception: Could not find Opus library. Make sure it is installed.
  (gateway/.venv/lib/python3.14/site-packages/opuslib/api/__init__.py:20)
```

原因：`.venv-v4` 未安装 `opuslib` 包；`.venv` 安装了 `opuslib` 但**系统缺少 Opus 共享库（libopus）**。属环境依赖缺失，**非 V4 引入**。未安装依赖、未改写测试、未伪造输出。

### 3.5 三套可运行套件汇总

| 套件 | 结果 |
|---|---|
| `admin_security_tests.py`（历史 29） | **29 PASS / 0 FAIL** |
| `admin_ui_tests.py`（历史 23） | **23 PASS / 0 FAIL** |
| `admin2_tests.py`（历史 69） | **69 PASS / 0 FAIL** |
| `admin1_tests.py` | 无法运行（缺 opuslib / libopus） |

---

## 4. V4 新模块 import 边界

对 `modules/model/*.py`、`modules/knowledge/*.py` 全量检索 import：**无任何 gateway / audio / opus / vad / turns / protocol 模块导入**。

- `modules/model/`：仅依赖 `modules.model.*`、标准库（`hashlib/json/time/uuid/ipaddress/socket/urllib`）与可选 `cryptography`（`crypto.py`）。
- `modules/knowledge/`：仅依赖 `modules._jsonstore`、`modules._store_lock`、`modules.knowledge.*` 与可选 `pdfminer/docx/pptx`（`parsers.py`）。
- 出现 "protocol/audio/vad/realtime" 的命中均为**标识符、能力常量或注释**（如 `PROTOCOLS`、`realtime_audio` 能力名、"server-side (Qwen realtime)" 说明文本），**非 gateway 导入**。

对 `gateway/app/admin/*.py` 检索音频写路径：命中均为**只读计数器/字段名**（`views.py` 读取 counters 快照：`audio_in_opus_frames`、`turns`、`barge_ins` 等）；`api_model.py`、`api_import.py` 仅操作模型注册表 / 凭证 / 知识库导入。**无音频写路径**。

> 注：`gateway/app/ws.py:7  from .admin.registry import sessions as admin_sessions` 为 **ADMIN-1 既有的被动只读观察**接线，`ws.py` 未改动（不在改动列表），非 V4 引入。

---

## 5. 冻结 Tina 只读识别行为实证

用 `.venv-v4` 构造 `ModelRegistry` + 快照，直接调用 `ensure_seeded / ensure_frozen_link / frozen_link_snapshot`：

```
SNAPSHOT: {"mode": "real", "model": "qwen3.8-omni-flash-realtime", "voice": "Tina",
           "host": "dashscope.aliyuncs.com", "region": "", "frame_ms": 20,
           "reconnect_max": 5, "vad": "server-side (Qwen realtime)",
           "opus_frame_ms": 20, "barge_in": true}
snapshot-is-copy (tamper did not leak): True
qwen_cfg UNCHANGED after ensure_seeded+ensure_frozen_link: True
returned frozen record frozen= True enabled= True origin= detected_frozen_link
files created in scratch dir: ['models.json', 'models.json.lock']
registry has frozen provider: True
registry has frozen model: True model_key= qwen3.8-omni-flash-realtime voice= Tina
frozen model marked read-only (frozen True) and enables realtime_safe evidence: realtime_safe
registry mode: 0o600
```

冻结条目拒绝一切变更实证：

```
update_model  REFUSED (FrozenModel): model is frozen
set_enabled   REFUSED (FrozenModel): model is frozen
delete_model  REFUSED (FrozenModel): model is frozen
bind_scene    REFUSED (FrozenModel): model is frozen
```

结论：`ensure_frozen_link` **只写模型注册表 JSON 文件（mode 600）**，原始 qwen 配置字典保持逐字节不变；快照为独立副本；冻结 provider/model 标记 `frozen:true`、`origin:detected_frozen_link`，对所有写操作抛 `FrozenModel`。**对实时语音链路零写回。**

---

## 6. 非冻结面改动独立复核（Lead 重启后修复项）

| 文件 | 冻结面 | 复核结论 |
|---|---|---|
| `modules/model/probe.py` | 否（纯逻辑） | 仅 `urllib` 免费元数据探测 + `validate_endpoint` SSRF 复校 + 拒跨域重定向；无 gateway/audio 依赖；`probe_protocol` 纯离线 |
| `gateway/app/admin/api_model.py` | 否（admin 面） | 仅模型注册表/凭证/场景操作与错误映射；无音频写路径 |
| `gateway/tests/admin_v4_api_tests.py` | 否（测试） | 注入 `realtime_snapshot` 仅用于构造 admin 测试应用；不触音频运行时 |
| `gateway/tests/model_v4_tests.py` | 否（测试） | 纯 model 模块单测；`realtime_audio` 仅为能力字符串 |

判定：上述修复**未引入对冻结语音路径的行为变化**（无 import、无调用、无共享状态写入）。

---

## 7. 问题清单

### Blocker
- 无。

### Major
- 无。

### Minor
1. **[Minor] `admin1_tests.py` 无法在任一本地 venv 运行**：`.venv-v4` 无 `opuslib`；`.venv` 缺系统 `libopus`。建议在验收环境补齐 libopus 后补跑（与 V4 无关，仅覆盖缺口）。
2. **[Minor] `gateway/app/admin/api.py` / `views.py` / `app.py` 属 ADMIN P0 基线文件，本次为 V4 增量修改**。改动为**加法式**（新增 `StoreUnavailable` 映射、只读守卫 `_need_avail`、`/v4` 静态壳、V4 路由条件挂载），未触碰认证/鉴权核心；三套安全/UI 套件全绿佐证基线未回归。建议在最终验收注记中明示「ADMIN P0 基线文件含审查过的加法式改动」。

---

## 8. 审计证据来源（只读命令）

```
git status --porcelain=v1
git diff --stat
git diff HEAD -- <冻结文件列表>            # 空
git diff HEAD -- gateway/app/main.py
git diff HEAD -- gateway/app/admin/{api,app,config,stores,views}.py
git diff HEAD -- modules/knowledge/store.py gateway/tests/knowledge1_tests.py
gateway/.venv-v4/bin/python tests/admin_security_tests.py   # 29 PASS
gateway/.venv-v4/bin/python tests/admin_ui_tests.py         # 23 PASS
gateway/.venv-v4/bin/python tests/admin2_tests.py           # 69 PASS
gateway/.venv-v4/bin/python tests/admin1_tests.py           # 无法运行（缺 opuslib）
gateway/.venv/bin/python     tests/admin1_tests.py          # 无法运行（缺 libopus）
# + 内联 python 实证（不落盘源文件，仅 /tmp 临时目录）
```

**审计结论：HOLD —— Tina 冻结实时语音链路与 ADMIN P0 安全基线均未被 V4 破坏，成立。**