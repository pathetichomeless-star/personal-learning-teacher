# ADMIN-1 — AGENT C 安全 / 隐私审计（独立、只读）

- 仓库：`<project-root>`（本地 git，分支 `main`，基线 `ecb8209`）
- 审计对象（未提交）：`gateway/app/admin/*`、静态控制台 `admin/*`、`gateway/tests/admin1_*`、
  改动 `gateway/app/main.py` + `gateway/app/ws.py`
- 方法：**只读、独立复算**。自建敌对夹具（不复用 Lead 的 suite/报告），对六个端点做响应体 + 响应头 +
  日志的泄漏探测；结合 AST/源码通读、路由清单与遍历探测。
- 约束遵守：本报告是本次审计**唯一写入**的文件；不含任何真实密钥值，所有夹具值以 `<len=N>` 掩码表示。
- 结论：**C_ADMIN1_SECURITY = PASS**（未发现任何真实泄漏 / 暴露）。

---

## 1. 自建敌对夹具

全部为审计自造的假值，与 Lead 的 suite 无关：

- 我方 bearer token：`<len=31>`
- 假 API key：`<len=34>`
- 假 MySQL 口令：`<len=20>`
- 假 Redis 口令：`<len=20>`
- 假学习者转写句：`<len=46>`
- 假原始 session id：`<len=25>`
- 假原始 Qwen response id：`<len=26>`
- 假 workspace id：`<len=26>`
- 私有路径（作 token 文件）：`<len=38>`
- 私有路径（作 capture 目录）：`<len=37>`
- 进程环境哨兵变量值（检测 env dump）：`<len=23>`

注入点（各自可被 admin 代码“顺手复制”的地方）：

1. 敌对 `gateway_info` 可调用：在 `mode/ready` 之外附带 `token / api_key / mysql_password /
   redis_password / workspace_id / endpoint / secret_file`（含全部假密钥）。
2. 敌对 `diag.SNAPSHOT_PROVIDER`：返回 `transcripts / journal_tail / send_intents / send_timeline`
   以及 `per_conn / connections / capture.dir` 中的原始 id 与私有路径。
3. 敌对 `diag.capture_info`：带 `dir` 私有路径 + 额外密钥键。

## 2. 泄漏验证（六端点，合法 token）

对 `/admin/health,/version,/sessions,/metrics,/telemetry,/diag-summary` 逐一取 **响应体全文 + 全部响应头**，
断言 11 个夹具值（含全部假密钥、私有 token 路径、私有 capture 目录、env 哨兵值）**均不出现**：
结果 **全部 PASS**（body 与 header 各 11 项，合计 22 项全绿）。

- 日志：挂自我方 `logging.Handler`，在匿名 / 错 token / 合法 token 三种请求下，token 与全部夹具值
  均**未出现在日志**（PASS）。
- `diag-summary` 与 `health` 的允许列表示证见第 3、4 节。

## 3. 允许列表示证：`/admin/diag-summary`

- 源码通读（`gateway/app/admin/views.py` `diag_summary_view`）：响应由**显式键构造**，
  逐字段 `snap.get("…")` / `len(...)` 取聚合量；`transcripts`、`journal_tail`、`send_intents`、
  `send_timeline`、`per_conn`、`connections` 从未被引用（AST 字符串引用扫描亦无命中）。
- capture 仅取：`enabled` 布尔 + 三个固定文件名的**字节数**（`qwen_pcm24.raw / sent_opus.bin /
  sent_opus.jsonl`）。`capture_info()["dir"]` **从不读取**（敌对夹具注入 `dir` 后，响应体与响应头均无该值，
  且 JSON 中不存在 `"dir"` 键）。
- 敌对快照探测：响应 `capture == {"enabled": True, "bytes": {…}}`，其余敌对键全部缺席（PASS）。

## 4. 允许列表示证：`/admin/health`

- 源码只读取 `info.get("mode")` / `info.get("ready")`，以及 `counters.snapshot()` 的具名键。
- 敌对 `gateway_info` 附带的 `token/api_key/mysql_password/redis_password/workspace_id/endpoint/
  secret_file` 全部未出现在响应体或响应头（PASS）。

## 5. 认证令牌处理

- **文件优先 + 环境回退**：`TokenStore.reload()` 先读 `ADMIN_API_TOKEN_FILE`，空则回退 `ADMIN_API_TOKEN`；
  `source` 仅返回标签（`file|env|none`），**从不返回路径或值**。
- **恒定时间比较**：`hmac.compare_digest(presented, self._token)`（`auth.py`）。
- **不泄漏于 `/admin/version`**：`build_facts()` 仅输出 version/git_commit/build_time/schema/digest 占位，
  无 token 字段（探测 PASS）。
- **未配置即 fail-closed**：空 token 文件 + 无 env 时，`store.configured is False`，六端点全部 401
  （匿名与携带任意 bearer 均 401）；`start_admin_listener` 在 `ADMIN_ENABLED=1` 但无令牌时**不启动监听**
  并返回 `[]`（PASS）。
- **令牌文件路径不出现在 API**：`store._file`（自建 `.../tok`）在全部响应体/头中缺席（PASS）。
- **重复重载不清除有效令牌**（重点探测的 bug 类）：`reload()` 在文件签名 `(mtime_ns,size)` 未变且
  source 仍为 file 时**保留**内存令牌；连续 50 次 `reload()` 后 `configured` 仍为 True，且多轮六端点请求
  **保持 200**（PASS）。注：中间件每请求都会 `reload()`，因此对“在内存中清空”的抗干扰来自文件源本身，
  语义正确（非缺陷）。

## 6. 无外部系统耦合 / 无任意 shell-文件访问

- **导入面**：`gateway/app/admin/*` 仅 import `aiohttp`、stdlib、以及 `..diag`、`..counters`、
  `.version`、`.registry`。**无** manager-api / MySQL / Redis / workbench-sync / RAG / memory 相关导入。
- **全 gateway 字符串扫描**（`gateway/app`）：`manager-api|workbench|sync/state|mysql|redis|RAG|
  memory-service|knowledge-base` **零命中**。
- **shell / 网络 / docker**：`gateway/app` 内无 `subprocess / os.system / Popen / socket.socket /
  urllib / requests / docker`（仅在测试与 docs 中出现，非运行期代码）。
- **文件读取**：admin 包仅有两处文件访问——`auth.py` 读 token 文件、`views.py` 经固定 `UI_FILES`
  允许列返回静态 UI（`FileResponse`）。`UI_FILES` 为精确白名单映射，文件名不可由用户控制。
- **遍历探测**（合法 token）：`/admin/../etc/passwd`、`/admin/%2e%2e/etc/passwd`、
  `/admin/health/../../secret`、`/admin/env`、`/admin/config`、`/admin/debug` 全部被拒绝（400/403/404），
  无 `root:`、无 env 哨兵值、无 token 泄漏（PASS）。
- **静态 UI 遍历**（UI shell 按设计免鉴权，仅含无数据外壳）：`/../etc/passwd`、`/%2e%2e/etc/passwd`、
  `/etc/passwd`、`/app.js/../etc/passwd` 等均 404/拒绝，无文件内容回显（PASS）。

## 7. 环境变量转储不可达

- 路由清单（`admin_route_table()` = 11 条，全 GET）：六 API + `/`、`/index.html`、`/app.js`、
  `/styles.css`、`/favicon.ico`；音频应用为 7 条，无 `/env`、`/config`、`/debug`。
- 源码扫描：`os.environ` 仅出现于 `config.py`（只读 `ADMIN_*`）、`version.py`（只读 `GATEWAY_*`）、
  `main.py`、`qwen.py`、`diag.py`；**无任何 `json.dumps(os.environ)` 或字典展开式转储**。
- 探测：`/admin/env`、`/admin/config`、`/admin/debug` 均 404；注入 env 哨兵变量值在全部响应中缺席（PASS）。

## 8. 静态 UI 隐私

- `admin/index.html` 仅占位符，无运营数据、无密钥（`uptime_s":`、`ws_connections":`、token 值均无）。
- `admin/app.js`：token 仅存 `sessionStorage`（`TOKEN_KEY="xz_admin_token"`）；`localStorage` 仅出现在
  “never localStorage”的注释中，无实际调用；无 `location.` / `?token` / cookie / `console.log`。
- UI 仅调用六个端点（`API` 数组与 `LOADERS` 一致），全部 GET，无写/重置/模型/音色控件。
- 每次请求都带 `Authorization: Bearer`；token 输入框提交后即时清空，**不回显**。

## 9. Lead 套件复跑

- `DYLD_LIBRARY_PATH=/tmp/opus131/lib gateway/.venv/bin/python gateway/tests/admin1_tests.py`
- 结果：**ADMIN1_TESTS: 79/79 PASS**。
- 我方独立探针：探针一 60/61（唯一 FAIL 系我方断言遗漏 401，实为正确拒绝，经探针二确认为通过）；
  探针二 20/21（同上，`/admin/passwd` 返回 401 = 正确拒绝）。**两处均为探针自身判定瑕疵，非产品缺陷。**

## 10. 未能复现 / 残余说明

- 未启动真实 `main._run()` 观测第三监听端口（`ADMIN_ENABLED=1` 的实际 bind 行为）；仅以
  `create_admin_app` + `start_admin_listener` 在回环内做等价验证，音频面隔离由路由清单（7 条不变）佐证。
- 静态 UI 外壳对未鉴权者可读（按设计，外壳本身无任何运营数据）；这是**记录项，非泄漏**。

---

**判定：C_ADMIN1_SECURITY = PASS**（无真实泄漏/暴露证据）。
