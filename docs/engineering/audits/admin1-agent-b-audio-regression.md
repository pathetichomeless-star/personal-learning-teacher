# ADMIN-1 · Agent B — R-1f 音频回归审计

- 范围：ADMIN-1 工作树（未提交）对 R-1f 音频行为的影响。
- 基线：`ecb8209`（本地 `main`），纯净副本 `/tmp/admin1-baseline/gateway`（`git archive`）。
- 约束：只读。本审计仅写入本文件。
- 测试环境（dev-only）：`DYLD_LIBRARY_PATH=/tmp/opus131/lib gateway/.venv/bin/python`（aiohttp 3.14.4 + 本地 libopus 1.3.1）。
- 结论：**B_ADMIN1_AUDIO = PASS**（无真实回归）。

---

## 1. 源码冻结核对（独立复核）

方法：把 `docs/admin0/baseline-manifest.sha256` 中 `rtl-lab/app/*` 与 `rtl-lab/config/config.json` 记录，逐条与今日 `gateway/app/*`、`gateway/config/config.json` 的 `shasum -a 256` 对比。

| 基线路径 (rtl-lab/…) | 基线 sha256 | 今日 (gateway/…) sha256 | 状态 |
|---|---|---|---|
| app/`__init__.py` | `e3b0c442…` | `e3b0c442…` | 字节一致 |
| app/`audio.py` | `c2218a2c…` | `c2218a2c…` | 字节一致 |
| app/`counters.py` | `b435ecaf…` | `b435ecaf…` | 字节一致 |
| app/`diag.py` | `8cc31768…` | `8cc31768…` | 字节一致 |
| app/`http.py` | `63d26c20…` | `63d26c20…` | 字节一致 |
| app/`main.py` | `e19ee609…` | `639305f0…` | **已变更** |
| app/`protocol.py` | `35b5fa7b…` | `35b5fa7b…` | 字节一致 |
| app/`qwen.py` | `75685213…` | `75685213…` | 字节一致 |
| app/`turns.py` | `06a41cf9…` | `06a41cf9…` | 字节一致 |
| app/`ws.py` | `1322a759…` | `dde9d427…` | **已变更** |
| config/`config.json` | `670c1c9d…` | `670c1c9d…` | 字节一致 |

**仅 `main.py` 与 `ws.py` 变更**，其余干系文件字节一致，从而：

- Pacing 常量冻结：`turns.py` 字节一致，实测 `MEDIA_FRAME_MS = 20.0`、`MIN_SEND_START_INTERVAL_MS = 15.0`、`PACING_SLACK_MS = 5.0`（第 32–34 行），另 `MAX_FUTURE_FRAMES/MAX_FUTURE_AUDIO_BYTES/MAX_REBASE_LATENESS_MS/SLOW_SEND_THRESHOLD_MS` 亦在确定性套件 Z1–Z7 中逐一断言通过。
- Opus / FIFO 代码冻结：`audio.py` 字节一致。
- provider / model / voice 冻结：`qwen.py` 与 `config/config.json` 字节一致。
- 计数契约冻结：`counters.py` 字节一致（A.14 契约）。
- 诊断冻结：`diag.py`、`http.py` 字节一致。

### 已变更两文件的差异范围

`git diff HEAD` 统计：`2 files changed, 15 insertions(+), 0 deletions(-)`（纯新增，无删除/改写）。

- `gateway/app/main.py`：在 `_run()` 内新增 `from .admin import load_admin_config, start_admin_listener, stop_admin_listener`；构建完两个音频 runner 后调用 `start_admin_listener(...)`；`stop.wait()` 之后在 runner 清理前调用 `stop_admin_listener(admin_runners)`。其余逻辑（`load_config`、`create_app` 的 7 条音频/OTA/diag 路由、信号处理）未动。
- `gateway/app/ws.py`：新增 `from .admin.registry import sessions as admin_sessions`；在 `conn = Connection(...)` 之后（`on_connect` 之前）`admin_sessions.register(conn)`；`finally` 内 `admin_sessions.discard(conn)`。

结论：diff 恰为「(a) `main._run()` 的 admin start/stop 调用 + (b) `ws.py` 的两处 registry 生命周期调用」，无其他改动。

---

## 2. 既有套件（当前树 vs 纯净基线，同解释器 + 同 libopus）

命令与结果（尾部摘要）：

```
# 当前树
cd gateway && DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python tests/r1f_tests.py
R1F_BRIDGE_TESTS: 180 checks, 179 PASS, 1 FAIL, 0.4s
FAILED CHECKS:
  - B test_sentinel_harness EXCEPTION OpusError()

# 纯净基线
cd /tmp/admin1-baseline/gateway && DYLD_LIBRARY_PATH=/tmp/opus131/lib \
  <project-root>/gateway/.venv/bin/python tests/r1f_tests.py
R1F_BRIDGE_TESTS: 180 checks, 179 PASS, 1 FAIL, 0.4s
FAILED CHECKS:
  - B test_sentinel_harness EXCEPTION OpusError()
```

**两侧计数完全相同（180 / 179 / 1），且为同一失败项。** 该失败在纯净基线上同样出现，确认为本地 macOS libopus 构建的环境事实，**不是 ADMIN-1 引入**（独立复核，非沿用 Lead 结论）。

### Mock 运行时 harness（`r1f_runtime.py`，全场景）

```
# 当前树（全场景，顺序执行）
R1F_RUNTIME_TESTS: 93 checks, 92 PASS, 1 FAIL, 97.7s
  - backlog_stress: minimum frames sent (1000) 50

# 纯净基线（全场景，顺序执行）
R1F_RUNTIME_TESTS: 93 checks, 92 PASS, 1 FAIL, 98.2s
  - backlog_stress: minimum frames sent (1000) 55

# 单场景复跑（当前树）
cd gateway && … python tests/r1f_runtime.py backlog_stress
R1F_RUNTIME_TESTS: 13 checks, 13 PASS, 0 FAIL, 32.6s
```

全场景顺序执行时 `backlog_stress` 的「minimum frames sent」在**基线与当前树同样失败**（50 vs 55，均为真实时序抖动导致的少量帧），单场景隔离复跑则 13/13 通过。判定：顺序全跑下的该失败为既有的时序性 flake，**非 ADMIN-1 回归**。

---

## 3. Admin 负载回归（`admin1_load.py`）

```
cd <project-root> && DYLD_LIBRARY_PATH=/tmp/opus131/lib \
  gateway/.venv/bin/python gateway/tests/admin1_load.py
…
ADMIN1_LOAD: 29/29 PASS
load summary: requests=450 max_ms=3.8  {"clean_long": {"pacer_rebases": 0, "sent_confirmed": 600,
  "segments_qualifying": 1, "fps": [49.9954749836169, 49.9954749836169]},
  "rapid_barge": {"pacer_rebases": 0, "sent_confirmed": 34, "segments_qualifying": 1,
  "fps": [49.9954749836169, 49.9954749836169]}}
```

逐项核对（health/metrics/sessions 每 ~150 ms、diag-summary 每第三轮，共 450 次请求，最大响应 3.8 ms）：

- pacer fatal stalls：0 ✔（clean_long / rapid_barge 均 PASS）
- slow-send guard violations：0 ✔
- short intervals：0 ✔
- store-cap transitions：0 ✔（`no store-cap transitions`）
- wire excess ≤ 1：0.0 ✔
- 单一 pacer：`single pacer (got 1)` / `single pacer ever` ✔
- closures：source / framer / disposition 残差均 0 ✔
- post-terminal sends：0 ✔
- **通过并非来自 pacing rebase 恢复**：两场景 `pacer_rebases = 0`；`segments_qualifying = 1`；稳态段速率门在带内——`fps = 49.9955 ∈ [49.5, 50.5]`、`mean ∈ [19.80, 20.20]`（干净跑的 rate gate 在带内）。✔

---

## 4. Admin 面无法扰动音频面（证据）

- **独立监听器 / 独立端口**：`service.start_admin_listener` 仅在 `ADMIN_ENABLED=1` 且已配置 token 时，`web.AppRunner(app)` + `web.TCPSite(runner, ADMIN_BIND, ADMIN_PORT)`（默认 `127.0.0.1:8112`）启动**第三个**监听器；默认 `ADMIN_ENABLED=0` 直接 `return []`，不加端口、不改音频运行时。音频应用仍为 `create_app` 的 7 条路由（未新增 admin 路由）。
- **处理器有界**：`views.py` 全部采用 allowlist 构造器输出，测试断言各响应 `< 16KB` 且键集确定。
- **registry 仅弱引用 + 仅由 WS 生命周期喂入**：`SessionRegistry` 只存 `weakref.ref(Connection)`；`register`/`discard` 在 `gateway` 全仓仅出现于 `app/ws.py`（`grep` 确认，另有 `diag.py` 的无关 `live_pacers.discard`）。`snapshot()` 仅对连接做 `getattr` 只读（`state`/`tts_active`/`pacer_task`/`qwen`），不写、不加锁、不改变量。
- **AST/导入证据**：对 `gateway/app/admin/*.py` 做 AST 扫描，admin 包的非标准库导入仅为 `aiohttp` 以及网关只读快照源 `..diag`（`diag.SNAPSHOT_PROVIDER` / `diag.capture_info`）与 `..counters`（`counters.snapshot`）。**未导入** `turns` / `audio` / `qwen` / `http` / `ws` / `main`。`views.py` 中出现的 `pacer_task`/`audio_store`/`qwen`/`turns` 全部是**指标名字符串字面量**（`METRIC_KEYS`、`FLUSH_KEYS`）与注释；`version.py` 的 `socket` 仅出现在 docstring。`counters.snapshot()`（字节一致于基线）为纯读构造字典，无副作用。
- **是否存在 admin 代码在 pacer 任务或 send loop 内运行**：**不存在**。`turns.py` 中零处 `admin` 引用；registry 的 `register` 在 WS 处理器任务内、`on_connect` 之前调用，`discard` 在同任务的 `finally` 内——均非 pacer 任务，且不阻塞/加锁 send loop。admin 请求处理器是 admin 站点上独立的请求任务，与 pacer 协程无 await 交点。控制面与音频面仅有两处接触点：`main._run()`（启停）与 `ws.py`（生命周期注册），均不在 pacer/send 热路径。

---

## 5. 复现命令汇总（裁剪）

```bash
# 1) 冻结核对
cd <project-root> && git diff --stat HEAD -- gateway/
for f in gateway/app/*.py; do shasum -a 256 "$f"; done
shasum -a 256 gateway/config/config.json
grep -nE 'MEDIA_FRAME_MS|MIN_SEND_START_INTERVAL_MS|PACING_SLACK_MS' gateway/app/turns.py

# 2) 确定性套件（当前 vs 基线）
cd gateway        && DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python tests/r1f_tests.py
cd /tmp/admin1-baseline/gateway && DYLD_LIBRARY_PATH=/tmp/opus131/lib \
  <project-root>/gateway/.venv/bin/python tests/r1f_tests.py

# 3) Mock 运行时（全场景 + 单场景）
cd gateway && DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python tests/r1f_runtime.py
cd gateway && DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python tests/r1f_runtime.py backlog_stress

# 4) Admin 负载
cd <project-root> && DYLD_LIBRARY_PATH=/tmp/opus131/lib \
  gateway/.venv/bin/python gateway/tests/admin1_load.py

# 5) AST/引用扫描（admin 包对外部模块与热路径 token 的引用）
grep -rnE 'import|pacer|_send_loop|AudioStore|fifo|framer|opus|encode|decode|Task\(' gateway/app/admin
```

无任何 NAS / Workbench / 容器改动；未打印任何密钥。

---

## 判定

源码冻结成立（仅 `main.py`/`ws.py` 纯新增 15 行 admin 生命周期调用）；确定性套件当前树与纯净基线计数逐位一致（180/179/1，失败项同为 `test_sentinel_harness EXCEPTION OpusError()`，环境性）；admin 负载 29/29 PASS，`pacer_rebases=0`、无稳步门越界，通过不依赖 rebase 恢复；admin 面在独立的 AppRunner/端口上、有界、只读、仅经 WS 生命周期喂入弱引用，且无任何代码路径在 pacer 任务或 send loop 内执行。

**B_ADMIN1_AUDIO = PASS**