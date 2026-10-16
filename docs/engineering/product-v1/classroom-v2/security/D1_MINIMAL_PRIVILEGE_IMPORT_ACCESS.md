# D1 安全架构 — 最小权限导入访问方案（Agent G）

- 阶段：P0（非付费）· **设计交付**（`DESIGN_ONLY`，未实现、未部署）
- 依据：产品负责人 REV1A 裁决 `D1 = MAC_LOOPBACK_ISOLATED`
- **修订**：**REV1B**（产品负责人裁定 **有条件批准**；S1–S5 已逐项裁决，见 §6；未定义的 `Origin: null` **不再作为可信依据**）
- **增量修订**：**CONTRACT_FIX_01A** —— 二.1 **消除 L-SESSION → L-ADMIN 代理模型**（§3.2.1 独立最小权限子应用）；
  二.2 **学生模式路由表/模块依赖图/来源鉴权/资源归属核验**（§3.8）；二.3 **`getpeereid` 事实更正 + P2 默认禁用**（§3.3）
- 基线：`3754e502701713ee420e19b5badee5c421a77f88`
- 约束遵守：`NAS_CHANGED = NO` · `REAL_MODEL_REQUESTS = ZERO` · `TINA_FROZEN = UNCHANGED`
- 门禁：**本方案（REV1B 修订版）须经独立安全复核后，方可将白名单路由接入学生客户端**；`/admin/model/*` 等管理面**永不**接入

---

## 0. 结论摘要

| 项 | 结论 |
|---|---|
| 连网形态 | 客户端**只**访问 `127.0.0.1` 上的**本机环回网关**（独立验收环境），教材不出本机 |
| 鉴权形态 | **一次性会话密钥**（**匿名继承 fd / `socketpair`** 传递，短 TTL），**非**管理员 Bearer |
| 学生端持有物 | 仅**受限会话密钥**；**永不持有**管理员凭据 |
| **业务实现形态（01A 二.1）** | **独立受限的最小权限子应用**（`/cls/*` 7 条白名单）；**不存在** L-SESSION → L-ADMIN 代理；学生进程**从不加载** admin app / `auth.py` / Bearer 文件 |
| **会话令牌语义（REV1B）** | L-SESSION 是**访问环回代理的能力凭据**，**不是学生身份**，也不得被当作身份使用 |
| **P2 UDS 兜底（01A 二.3）** | **默认 PROHIBITED**；`getpeereid` 仅给 uid/gid、**不能**证明对端 PID；须实测 `LOCAL_PEERPID` 可用 + 预授权 + 独立复核方可启用 |
| 路由面 | **白名单**：仅导入/解析/课程面；admin 模型/凭据/生产面**一律 403**；**不开放**管理型导出/批量删除/存储维护 |
| 教材隔离 | 独立验收数据目录；指向正式目录即 **fail-closed 拒绝启动** |
| 凭据保护 | 不落盘、不进前端资源、不进日志、不需用户输入；**允许本机脱敏诊断包（不上传）** |
| 本轮实现状态 | **未实现**（`DESIGN_ONLY`）——仅方案，待独立安全复核 + 批准 |

---

## 1. 资产与威胁模型

### 1.1 受保护资产

| 资产 | 为何敏感 | 现有保护 |
|---|---|---|
| 用户教材原文（PDF/DOCX/PPTX/EPUB） | 用户私有内容，可能涉版权与隐私 | 仅存本机；本轮新增隔离目录 |
| 管理员 Bearer Token（`/app/secrets/admin_api_token`） | 可操作模型凭据、老师档案、知识库 | 密封文件 + 恒时比较；**本方案进一步禁止其进入客户端** |
| Tina 生产凭据 | 冻结链路核心 | 冻结六文件 + 不读生产密钥 |
| 正式网关数据目录 | 生产数据 | 本方案以 fail-closed 隔离拒绝 |
| NAS 服务 | 生产环境 | `NAS_CHANGED = NO` |

### 1.2 威胁清单（D1 形态下真实存在的）

| # | 威胁 | 场景 | 本方案对策 |
|---|---|---|---|
| T1 | **本机其他进程**调用环回导入端点 | 任意本机 App 扫端口后直接 POST | §3.3 会话密钥 + §3.4 来源校验 |
| T2 | **浏览器 / DNS rebinding / CSRF-like** | 恶意网页让浏览器向 `127.0.0.1:port` 发请求 | §3.4 Host/Origin 精确校验 + 自定义头 + **不开放 CORS** |
| T3 | **凭据泄漏到前端** | Token 写进 QML/JS/资源包 | §3.2 密钥仅进程内存；§3.6 构建期扫描 |
| T4 | **凭据进入日志** | 异常堆栈/调试日志打印 Token 或教材内容 | §3.6 日志脱敏白名单 |
| T5 | **学生端获得管理员权限** | 为图省事直接复用 admin Bearer | §3.5 能力受限会话密钥；§2 L0 绝对禁止 |
| T6 | **误连生产** | 端口/配置指向 NAS 或正式目录 | §3.5 目录 fail-closed + §3.4 目标地址断言 |
| T7 | **教材越界访问** | 会话被复用到非本次导入的文档 | §3.5 教材访问隔离（会话绑定导入批次） |
| T8 | **端口被抢占 / 服务被顶替** | 恶意进程先占端口冒充网关 | §3.3 端口由 OS 随机分配 + 就绪握手校验 |
| **T9** | **同用户进程经"可连接的 socket"无条件取走会话密钥**（REV1B S1 裁定针对的反模式） | 网关开一个"连上即发密钥"的 UDS/环回端口，同用户任意进程连上即拿到 L-SESSION | §3.3 **匿名继承 fd / `socketpair` 优先**；**严禁**无认证的"连接即发密钥"通道 |
| **T10** | **绕过 UI 直接调用发布 API** | 脚本/curl 直接 POST 发布接口，跳过客户端门禁 | §3.7 + 契约 §8.3：门禁在**服务端**独立强制执行，与 UI 同一路径 |

---

## 2. 设计原则与绝对禁止清单

### 2.1 五条原则

1. **最小权限**：学生端得到的凭据只够做"导入教材/生成课程"，**不够**做任何管理动作。
2. **凭据不落用户可见面**：不落盘、不进前端资源、不进日志、**不需用户输入**。
3. **默认拒绝**：路由白名单之外的**一律 403**；路径/来源/会话任一校验失败即拒绝，**不降级为放行**。
4. **物理隔离**：验收环境的数据目录、端口、凭据与生产**完全分离**；指向生产即拒绝启动。
5. **结构性不可能**（沿用项目既有安全标准）：不靠"记得别这么做"，而靠**代码路径不存在**。

### 2.2 L0 绝对禁止清单（硬性，无例外）

1. 学生 `.app`、QML、JS、静态资源、`Info.plist`、构建产物中**保存 / 硬编码 / 暴露**管理员 Bearer Token。
2. 把**管理员权限**直接交给普通学生客户端。
3. 使用 **Tina 生产密钥 / 正式网关数据目录 / NAS 服务**。
4. **开放局域网或公网**导入端点（含 `0.0.0.0` 绑定、UPnP、反向代理暴露）。
5. 把敏感凭据写入**日志 / 崩溃报告 / 诊断包**（脱敏后的本机诊断包**允许**导出，见 §3.6）。
6. 以**环境变量、命令行参数或配置文件**把长期凭据交给学生端进程（§3.3 用进程内传递替代）。
7. **把本机单用户会话令牌当学生身份**：L-SESSION 仅表示"可访问本机环回代理"，**不得**作为用户身份、授权主体或审计主体使用。
8. **通过同一用户其他进程可连接的 socket 无条件发放会话密钥**（REV1B S1 明确禁止）。
9. 在**未定义清楚**的前提下把 `Origin: null` 当作可信依据（REV1B 裁定：`null` 语义不明，**不作为信任来源**）。
10. 向学生端开放**管理型导出 / 批量删除 / 存储维护**类能力（REV1B S3）。

---

## 3. 方案设计

### 3.1 总体形态

```
┌──────────────────────── Mac（独立验收环境） ─────────────────────────┐
│                                                                     │
│   ┌─────────────────────┐   一次性会话密钥（**匿名继承 fd / socketpair**）  │
│   │  学生课堂 .app       │ ◄──────────────────────────────────┐    │
│   │  （客户端 UI 进程）  │    （**无监听点**：同用户其他进程不可接入）  │    │
│   └──────────┬──────────┘                                    │    │
│              │  HTTP 仅 127.0.0.1:<随机端口>                  │    │
│              │  X-Classroom-Session: <受限会话密钥>           │    │
│              ▼                                               │    │
│   ┌──────────────────────────────────────────┐               │    │
│   │  本机环回网关进程（.app 内嵌，子进程）    │───────────────┘    │
│   │  · bind 127.0.0.1 ONLY                   │  启动时生成并传递   │
│   │  · 受限路由白名单（§3.7）                 │                    │
│   │  · 数据目录 = 独立验收目录（§3.5）        │                    │
│   └──────────────────────────────────────────┘                    │
│                                                                   │
│   ✗ 不接触 NAS   ✗ 不使用管理员 Bearer   ✗ 不绑 0.0.0.0          │
└───────────────────────────────────────────────────────────────────┘
```

### 3.2 凭据分层（三层，能力递减）

| 层 | 凭据 | 持有者 | 能力 | 生命周期 |
|---|---|---|---|---|
| **L-ADMIN** | 管理员 Bearer（`/app/secrets/admin_api_token`） | **仅管理端进程**（学生模式**不加载**） | 全管理面 | 长期（密封文件） |
| **L-SESSION** | **一次性会话密钥**（32B CSPRNG，base64url） | 网关 ↔ 客户端（**仅内存**） | **仅白名单路由** | 单次 App 运行（§3.3） |
| **L-NONE** | 无 | 学生可操作面 | 无 | — |

> **⚠️ CONTRACT_FIX_01A 二.1 重大修订（消除冲突）**：原方案写「网关内部把 L-SESSION 映射为对 **L-ADMIN 的受限代理**」——
> **该模型已废除**。它与"学生 `.app` 最小化打包、不得携带或间接使用全权管理员凭据"**直接冲突**：
> 只要存在 L-SESSION → L-ADMIN 的代理关系，学生网关进程就**必须持有/使用管理员 Bearer**（即便不落盘），
> 违反 §2.2 L0 第 1/2/6 条，也使"结构性不可能"失效。

#### 3.2.1 学生网关 = **独立受限的最小权限业务实现**（**非** admin 代理 · 01A 二.1）

**核心裁定：学生模式不使用任何管理员凭据，不存在 L-SESSION → L-ADMIN 代理。**

| 维度 | 旧（已废除） | **新（01A）** |
|---|---|---|
| 业务实现 | 复用 admin app + 加一层白名单过滤 | **独立子应用**，只挂载白名单路由 |
| 鉴权 | 客户端持 L-SESSION → 网关用 L-ADMIN 代发 | **客户端持 L-SESSION → 网关直接用 L-SESSION 授权** |
| 凭据 | 学生网关进程**持有 L-ADMIN** | 学生网关进程**从不加载 L-ADMIN**（Bearer 文件不读、`TokenStore` 不实例化） |
| 触达 store | 经 admin HTTP 面 | **进程内直接共享 store 对象**（`KnowledgeStore`/`ImportStore`），无 HTTP 往返、无 Bearer |
| 打包 | 需含 admin 面 | **admin app / `auth.py` / `api_model` 等一律不入包**（见修正④打包清单） |

**结构性保证（不靠"记得别写"）**：
1. 学生模式入口**不 import** `gateway/app/admin/app.py`、`auth.py`（`auth_middleware`/`TokenStore`）、
   `api_auth.py`、`password_auth.py`、`api_model.py`、`api_voice.py`、`api_teaching.py`、`api_teacher.py`、
   `realtime_probe.py`、`views.py`（admin UI shell）。
2. 学生模式**不读** `admin_api_token` 密封文件（`XIAOZHI_ADMIN_TOKEN_FILE` 不解析；实例化前断言为空）。
3. 学生模式复用 `api_import.py` 的**处理器函数**时，**不挂载** `auth_middleware`，改挂 §3.4 的 L-SESSION 中间件。
   （经核实：`api_import` 依赖 `api.py` → `modules.{knowledge,memory,policy,intent}` 等**数据层**模块；
   **这些模块均不含管理员凭据**，Bearer 仅存在于 `auth.py` 的 `TokenStore`。故"不含 Bearer"成立。）
4. **越权路由根本不存在**：学生 app 的 route table 就是白名单本身（§3.8），漏写拒绝规则也不会越权。

> **与"最小化打包"的一致性**：修正④要求学生 `.app` 不打包 admin 面与凭据。01A 的独立子应用模型
> 让"不打包"成为**结构性必然**——因为学生模式**根本不引用** admin app 及其凭据模块。

> **REV1B 语义澄清（保留）**：L-SESSION **不是学生身份**。它不带任何用户属性（无 user_id / 无角色 / 无权限声明），
> 仅仅是"本机某次 App 运行期间访问环回代理的一次性能力凭据"。**不得**把它写入课程归属、审计主体、
> 学习记忆所有者等任何需要"身份"的字段；学生身份由既有产品体系另行确立（本方案不承担该职责）。

### 3.3 会话密钥的生成与传递（不落盘、不进前端 · **REV1B S1 裁定**）

> **裁定原文**：S1 改为**匿名继承 fd / `socketpair` 优先**；**严禁**通过**同一用户其他进程可连接的 socket 无条件发放会话密钥**。

**为什么原"Unix 域套接字 0600"方案不够（已自我否证）**：
`UDS + 0600` 只保证"**同一用户**"，而**同用户下的任意进程**（包括被诱导运行的脚本）都能 `connect()` 上去。
若通道语义是"连上即发密钥"，则 L-SESSION 对同用户进程**无条件可得**——这等于把密钥公开给同一用户会话内的所有进程，
与"最小权限、结构性不可能"的目标直接冲突（对应新增威胁 **T9**）。

**revised 方案（优先级从高到低）**：

| 优先 | 通道 | 语义 | 安全性质 |
|---|---|---|---|
| **P0（首选）** | **匿名继承 fd**（父进程创建 `os.pipe()` / `socket.socketpair(AF_UNIX)`，通过 `subprocess(pass_fds=…)` 交给子进程） | 密钥**只**沿这条已建立、不可被第三方 `connect()` 的匿名通道传递 | **不存在"可连接的监听点"** → 同用户其他进程**无法**接入（无 bind、无 listen、无路径名） |
| **P1（次选）** | **`socketpair()` + 启动握手**：父进程先创建 pair，把一端传给子进程；双方在该连接内完成**一次性**密钥交接 | 通道是**已建立连接**，非监听 socket | 同上：无监听点，第三方无法接入 |
| **P2（仅当 P0/P1 在目标 macOS 版本不可行时 · 默认禁用）** | UDS **+ 强制对端进程身份校验**（**见下方 01A 更正**）：对端 **uid==自身** **且 pid==已授权父进程 pid**；**一次性**发放（发放后立即关闭监听）；**且**必须先经**已建立的受保护 IPC** 完成一次授权 | 监听点存在，但**接入被强校验**且**只发一次** | 显著弱于 P0/P1；**默认禁止**；仅在"实测存在可用的对端身份校验机制 + 独立安全复核"双通过后方可采用 |

**⚠️ 01A 二.3 更正（关键事实订正）**：
原 P2 描述写「`LOCAL_PEERCRED`/`getpeereid` 校验对端 **uid==自身 且 pid==父进程**」——
**该表述不成立**。事实：

| API | 实际返回 | 能否证明 PID |
|---|---|---|
| `getpeereid(fd)`（macOS/BSD） | **仅 `(uid, gid)`** | **不能** —— 只证明"同一用户"，**无法**给出对端 pid |
| `getsockopt(fd, SOL_LOCAL, LOCAL_PEERPID)`（macOS 专有） | `pid_t` 对端 pid | 能给出 pid（另一 API，**非** `getpeereid`） |
| `SO_PEERCRED`（Linux） | `ucred{pid,uid,gid}` | 能（**但 macOS 不可用**） |

**结论（硬性）**：
1. **`getpeereid` 不能单独证明对端 PID**（它只给 uid/gid）——**不得**以 `getpeereid` 作为"对端是已授权父进程"的依据。
2. 若确需 P2，必须**实测确认目标 macOS 版本上 `LOCAL_PEERPID` 可用**并以其取得对端 pid；
   即便如此，pid 校验仍存在 **PID 复用竞态**，故**仍必须**叠加"**先经受保护 IPC 完成一次预授权**"，
   且**只发一次**、发放后**立即关闭监听**。
3. **在"实测可用的对端进程身份校验机制"未验证之前，P2 一律 PROHIBITED**（`P2_UDS_FALLBACK = PROHIBITED_UNLESS_VERIFIED`）；
   **禁止**以"`getpeereid` 校验过"为由启用 P2。
4. 该机制须经**独立安全复核**并以**结构性证明**（"不可能无条件发密钥"）通过后方可启用。

**统一禁令（无论采用哪一级）**：
1. **禁止**任何形式的"连接即无条件发放密钥"——发放**必须**伴随**对端身份/来源校验**或**先验授权**。
2. **禁止**把密钥写入：文件、环境变量、命令行参数、`UserDefaults`、日志、前端资源、剪贴板。
3. **禁止**密钥出现在 `ps` 可见的 argv/env 中。
4. 监听点（若存在，仅 P2）**必须在密钥发放后立即关闭**；密钥交接窗口 ≤ 1 次。

**生命周期与 TTL（REV1B S2 裁定：进程内会话 + 空闲 30 分钟过期）**：
- **载体**：**进程内**（网关进程内存 + 客户端进程内存），**不落盘**。
- **TTL**：与 App 进程同生命周期；**空闲 30 分钟即失效**（无请求即计时）；App 退出即失效。
- **轮换**：每次 App 启动重新生成；**不跨运行复用**。
- **重新授权必须走受保护 IPC（S2）**：会话因空闲过期、或需要刷新/重建时，
  **必须**沿 §3.3 P0/P1 的**已建立受保护 IPC** 重新完成授权与交接；
  **禁止**为了"方便恢复"而回退到"任何本机进程连上即发密钥"的通道（即 T9 的反模式）。
- **内存卫生**：不做不必要的字符串拷贝；错误消息中**永不回显**密钥。

> **对照既有先例**：网关已有 `X-Vision-Token`（`gateway/app/http.py:47-99`）——**独立令牌文件 + 恒时比较 + 绝不使用 admin token**。
> 本方案沿用其"专用凭据、能力受限、绝不共用 admin"的思想，但**改用进程内传递**，比"令牌文件"更强（文件会落盘）。

### 3.4 请求来源校验（防 T1/T2/T8）

对**每一个**环回请求，网关在进入业务逻辑前执行四道校验，任一失败即 `403`：

| 校验 | 规则 | 目的 |
|---|---|---|
| **C1 绑定** | socket 仅 `bind 127.0.0.1`（**禁止** `0.0.0.0` / `::`） | 物理上排除局域网/公网访问 |
| **C2 Host 精确匹配** | `Host` 必须**逐字**等于 `127.0.0.1:<当前端口>`（或 `localhost:<端口>` 白名单精确匹配） | 防 **DNS rebinding**（恶意域名解析到 127.0.0.1 时 `Host` 不含白名单值） |
| **C3 Origin（REV1B 收紧）** | **只要出现 `Origin` 头——无论取值是什么（含 `null`、含 `127.0.0.1` 自身）——一律 `403`**。 仅当**完全无** `Origin` 头时继续 | 防浏览器 CSRF-like 调用。**`null` 的语义未被明确定义，不作为可信依据**（REV1B 裁定）：它既可能来自 `file://`、沙箱 iframe，也可能被构造，**不能**据此判定"是本机原生客户端" |
| **C4 会话密钥** | `X-Classroom-Session` **恒时比较**（`hmac.compare_digest`）通过 | 防 T1 本机其他进程 |
| **C5 令牌≠身份（REV1B）** | 会话令牌**只**用于放行环回代理；**不得**作为用户身份/授权主体/审计主体写入任何业务字段 | 防"把本机会话当学生身份"的语义越权 |
| **附加** | **不发送** `Access-Control-Allow-Origin`（不开放 CORS）；自定义头要求保证简单请求不成立 | 浏览器预检即失败，普通网页无法构造 |

> **信任来源澄清（REV1B 重要）**：**没有任何单一请求头是"可信依据"**。
> 真正的信任来自 **①会话密钥（P0/P1 通道下发）+ ②绑定与 Host 校验**；
> `Origin` 缺席只是**必要条件**（用于排除浏览器），**不是**充分条件；
> `Origin: null` **既不充分也不可信**——一律拒绝。

**端口随机化**：由 OS 分配（`bind port 0`），启动后握手回传真实端口；**不固定、不写入前端资源**——降低 T8 端口抢占与暴力扫描命中率。

### 3.5 教材访问隔离（防 T6/T7）

1. **独立验收数据目录**：沿用既有 `classroom_env.py` 的 fail-closed 语义 —— 目录解析优先级
   `XIAOZHI_CLASSROOM_DIR` > `XIAOZHI_DATA_DIR` > **默认独立演示/验收目录**；
   **一旦解析结果指向正式数据目录 → 拒绝启动（非降级、非警告）**。
2. **物理分离**：验收目录与生产目录**不同路径、不同卷**（不共享父目录、不用软链接指向生产）。
3. **工作区绑定**：每次导入批次（`job_id`）落在**该批次专属子目录**；会话只可访问本批次产物；
   跨批次访问 → `403` 并记审计。
4. **目标地址断言**：网关启动时断言"我不使用 NAS 地址、不读生产密钥文件"；断言失败即退出。
5. **清除语义**：批次完成后可选清理原始上传件；清理**必须**限定在验收目录内（路径前缀校验 + 拒绝符号链接）。
6. **来源依赖校验（配合契约 §8.3 / REV1B R2）**：发布前服务端**必须**校验 `source_doc_id` 在**本验收目录内**存在、
   `status == "ready"`、且回读 `content_hash == source_doc_hash`；
   **跨目录/悬空/漂移 → 拒绝发布**（`403`/`409` + 审计），但**不删除**已发布课程。

### 3.6 敏感凭据保护（防 T3/T4）

| 面 | 规则 |
|---|---|
| **前端资源** | 构建期扫描：`client/**`（含 `dist/`、QML、JS、`Info.plist`）**不得**出现 token 形态字符串（长度 ≥ 24 的 base64url/hex 且非已知常量）；扫描失败即**构建失败** |
| **日志** | 白名单式脱敏：只允许记录 `job_id`、`doc_id`、状态码、错误码；**禁止**记录文件内容、会话密钥、端口以外的请求头、绝对路径中的用户名 |
| **错误响应** | 学生可见文案**不含**技术堆栈、路径、内部标识；技术细节只进本地诊断日志 |
| **崩溃/诊断包** | 导出前执行同一脱敏器；默认**本机保存、不上传**。**REV1B S4：允许用户本机导出脱敏诊断包**（脱敏失败即拒绝导出，不降级为"导出未脱敏版"） |
| **构建产物** | `dist/*.app` 内**不含** `.env`、`secrets/`、测试凭据；构建脚本显式排除并做产物扫描 |

### 3.7 最小权限路由白名单

> **默认拒绝**：未列出的路由一律 `403`（不是 404，也不是 501）。学生端会话**不可**触达管理面。

**A. 链路 A（导入/解析/知识库提交）— 已实现路由**

> **01A 二.2 注**：下表为**现有 admin 面**的已实现路径（供对照）。
> **学生模式实际挂载路径以 §3.8.1 为准**（`/cls/knowledge/*`，`/admin/` 前缀在学生 app 中**不存在**）。

| 允许（L-SESSION 可访问） | 方法 | 理由 |
|---|---|---|
| `/admin/knowledge/parsers` | GET | 读取能力表（**只读**，无敏感信息） |
| `/admin/knowledge/import` | POST / GET | 上传与作业列表 |
| `/admin/knowledge/import/{job_id}` | GET | 作业详情/预览 |
| `/admin/knowledge/import/{job_id}/commit` | POST | 确认提交（**必须带 confirm**） |
| `/admin/knowledge/import/{job_id}/cancel` | POST | 取消 |
| `/admin/knowledge/import/{job_id}/retry` | POST | 重试 |
| `/admin/knowledge/dataset/{ds_id}/imports` | GET | 批次查询 |

**B. 链路 B（课程草稿 / 校对 / 发布）— S5 逐条设计（本轮定契约，**待独立安全复核后放行**，不实现）**

> 设计原则：**路径精确**（不接受前缀通配）、**方法精确**、**资源归属校验**、**revision 显式**、**发布门禁服务端强制**。

| # | 路径（精确） | 方法 | 资源归属校验 | revision 语义 | 发布门禁 |
|---|---|---|---|---|---|
| C-1 | `/admin/course/draft` | `POST` | 新建草稿；**只写**验收数据目录内课程存储 | 新建 `revision=1`；若已有草稿 → 覆盖未发布草稿，`revision` **递增** | 无（草稿允许携带未解决项） |
| C-2 | `/admin/course/{course_id}/draft` | `GET` | `course_id` **必须**属于验收目录内本机实例；跨目录/不存在 → `403`/`404` + 审计 | 返回当前草稿 `revision` | 无 |
| C-3 | `/admin/course/{course_id}/draft` | `PUT` | 同上 | **乐观并发**：请求**必须**携带 `If-Match: <revision>`；不匹配 → `409`（防并发覆盖） | 无 |
| C-4 | `/admin/course/{course_id}/proofread` | `POST` | 同上 | 记录校对结论（`critical_unresolved_count`、`accepted_gaps[]`）；**不改** `revision` | 无（只记录，不发布） |
| C-5 | `/admin/course/{course_id}/publish` | `POST` | 同上 + **发布**写入课程存储 | 请求**必须**在 body 显式携带 `revision`，且**必须**与当前 `ready` revision **精确一致**；不一致 → `409`。**不接受**路径参数形式的 revision | **服务端强制**：① `critical_unresolved_count == 0`；② `accepted_gaps[]` 合法（无 `critical`、字段齐全）；③ 来源绑定有效（`source_doc_id` 存在 + `content_hash == source_doc_hash`）。任一失败 → `publish_gate_blocked`(`409`)，**与 UI 走同一校验路径** |
| C-6 | `/admin/course/{course_id}` | `GET` | 同上 | 返回**已发布** revision（学生端可读） | 无 |
| C-7 | `/admin/course/{course_id}/rollback` | `POST` | 同上 | 目标 revision **必须**是历史中**已发布**的 revision | 无（回滚**不产生新 revision**） |

**C. 明确拒绝（REV1B S3 + 管理面隔离；示例非穷举）**

| 拒绝的路由/能力 | 理由 |
|---|---|
| `/admin/model/*`（凭据写入、注册、门禁、探测） | 管理面 → 学生端**结构性不可达** |
| `/admin/auth/*`、`/admin/credential*` | 凭据面 |
| `/admin/teacher/*`（写操作） | 管理面 |
| `/admin/knowledge/migrate`、`/rollback` | **存储维护** → 破坏性（S3 明确禁止） |
| `/admin/knowledge/dataset/{create,rename,delete,enable}` | 破坏性写操作 |
| **课程面管理型导出**：`/admin/course/export*`、`/admin/course/*/export`、批量导出 | **S3：不开放管理型导出** |
| **课程/知识库批量删除**：`/admin/course/bulk*`、`/admin/course/{id}` `DELETE`、`/admin/knowledge/documents/bulk*` | **S3：不开放批量删除**（如需删除 → 管理端执行） |
| **存储维护**：任何 `/admin/*/store/*`、`/admin/*/compact`、`/admin/*/gc` | **S3：不开放存储维护** |
| 课程发布面的**前缀通配**（如 `/admin/course/` 直接放行） | 违反"路径精确"原则 |

> **实现要点（结构性保证）**：不要"在现有 admin app 上加一层过滤"，而是**独立挂载一份仅含白名单的子应用**。
> 这样"漏写一条拒绝规则"不会导致越权——**越权的路由根本不存在**。
> 课程面（B 组）**同法**：独立挂载，只含 C-1…C-7 七条精确路由。

### 3.8 学生模式入口核验（**真实路由表 / 模块依赖图 / 来源鉴权 / 资源归属** · 01A 二.2）

> 本节为**实测核验**（读取现有源码，非推断）。基线 `3754e50`。

#### 3.8.1 真实路由表（现有 admin 面 vs 学生模式白名单）

现有 admin app（`gateway/app/admin/app.py` + `api_import.py::api_route_table_import()`）合计导出：

| 分组 | 路由（方法） | 学生模式 |
|---|---|---|
| admin 只读 | `GET /admin/{health,version,sessions,metrics,telemetry,diag-summary}` | **❌ 不挂**（管理面） |
| UI shell | `GET /{,index.html,app.js,styles.css,favicon.ico,v4,v4/*}` | **❌ 不挂**（admin UI） |
| 凭据面 | `/admin/auth/*`、`/admin/credential*` | **❌ 不挂** |
| 导入面（10 条） | `GET /admin/knowledge/parsers` · `POST /admin/knowledge/import` · `GET /admin/knowledge/import` · `GET /admin/knowledge/import/{job_id}` · `POST …/{job_id}/commit` · `POST …/{job_id}/cancel` · `POST …/{job_id}/retry` · `GET /admin/knowledge/dataset/{ds_id}/imports` · `POST /admin/knowledge/migrate` · `POST /admin/knowledge/rollback` | **7 条打入白名单**；`migrate`/`rollback` **❌ 拒绝**（破坏性，S3） |
| 模型/老师/语音/教学 | `/admin/model/*`、`/admin/teacher/*`、`/admin/voice/*`、`/admin/teaching/*` | **❌ 不挂** |

**学生模式白名单（真实 7 条，方法精确）** —— 挂载于**独立子应用**，`/admin/` 前缀**不存在**于学生 app：

```
GET  /cls/knowledge/parsers                     → 能力表（只读）
POST /cls/knowledge/import                      → 上传（不写库）
GET  /cls/knowledge/import                      → 作业列表
GET  /cls/knowledge/import/{job_id}             → 作业详情/预览
POST /cls/knowledge/import/{job_id}/commit      → 提交（必须 confirm；服务端回读）
POST /cls/knowledge/import/{job_id}/cancel      → 取消
POST /cls/knowledge/import/{job_id}/retry       → 重试
```
> `dataset/{ds_id}/imports`（批次查询）作为**可选第 8 条**保留（只读、无敏感面），是否纳入待复核。
> 路径前缀由 `/admin/` 改为 `/cls/` 是**结构性隔离**的一部分：**学生 app 里根本不存在 `/admin/*`**。

#### 3.8.2 模块依赖图（学生模式实际加载面）

```
学生模式子应用 create_classroom_app()
├─ gateway/app/classroom/session_auth.py     （新：L-SESSION 中间件；§3.4 C1–C5）
├─ gateway/app/admin/api_import.py           （复用处理器，**不挂 admin auth 中间件**）
│   └─ gateway/app/admin/api.py              （共享响应/校验助手 _ok/_err/_confirm/_audit…）
│       ├─ modules.knowledge.store           （KnowledgeStore）
│       ├─ modules.knowledge.imports         （ImportStore）
│       ├─ modules.knowledge.parsers         （格式识别/解析）
│       ├─ modules.memory.store              （数据层，**不含凭据**）
│       ├─ modules.policy.persona            （数据层，**不含凭据**）
│       └─ modules.intent.behavior           （数据层，**不含凭据**）
├─ modules._store_lock                        （文件锁）
└─ （可选）modules.curriculum.course_schema   （课程数据契约 v1）

✗ 不加载：admin/app.py · admin/auth.py(TokenStore/auth_middleware) · admin/api_auth.py
✗ 不加载：admin/password_auth.py · admin/api_model.py · admin/api_voice.py
✗ 不加载：admin/api_teaching.py · admin/api_teacher.py · admin/realtime_probe.py · admin/views.py
✗ 不读：admin_api_token 密封文件（XIAOZHI_ADMIN_TOKEN_FILE 不解析）
```
> **核实结论**：Bearer 凭据**仅**存在于 `admin/auth.py::TokenStore`，且**仅**由 `auth_middleware` 使用。
> 学生模式既不加载该模块、也不挂该中间件 → **管理员 Bearer 结构性不可达**（`ADMIN_BEARER_IN_CLIENT = PROHIBITED`，
> `ADMIN_APP_MOUNTED = NO`）。

#### 3.8.3 来源鉴权（source auth）

学生模式**唯一**的鉴权来源 = §3.4 四道校验（C1 bind 127.0.0.1 + C2 Host 精确 + C3 任何 Origin 一律拒 +
C4 `X-Classroom-Session` 恒时比较）+ C5「令牌≠身份」。**不使用** admin Bearer、不使用密码会话 cookie。

#### 3.8.4 资源归属（resource ownership）

| 资源 | 归属校验 | 失败 |
|---|---|---|
| 导入作业 `job_id` | 必须属于**本会话本批次**（§3.5 工作区绑定） | `403` + 审计 |
| 批次目录 | 必须位于**独立验收目录**内（路径前缀 + 拒符号链接） | `403` |
| 课程 `course_id` | 必须属于**本机验收目录内实例**（C-2…C-7） | `403`/`404` + 审计 |
| 知识库 `doc_id`（发布绑定） | 必须在验收目录内存在 + `status=ready` + `content_hash == source_doc_hash` | `409` |

> **待独立安全复核项**：§3.8.1 的 7（或 8）条白名单、§3.8.2 的依赖图最小性、`/cls/` 前缀命名
> 均须经**独立安全 Agent** 复核后方可进入实现；**复核通过前不开放学生端白名单服务与最终发布 API**。

---

## 4. 与学生端的边界（明确划线）

| 项 | 学生端可见/可做 | 学生端**不可**见/不可做 |
|---|---|---|
| 凭据 | 仅 L-SESSION（内存，且不展示）；**且它不是身份** | L-ADMIN Bearer、Tina 凭据、任何长期密钥 |
| 地址 | 仅 `127.0.0.1:<随机端口>`（**UI 不展示**） | NAS 地址、生产 URL、管理员端口 |
| 配置 | 无 | 无 Token / URL / JSON 输入字段（沿用 FIX01 约定） |
| 能力 | 导入教材、解析、生成/校对/发布课程 | 模型凭据、老师档案写、**管理型导出**、**批量删除**、**存储维护**、迁移/回滚（课程回滚 C-7 除外） |
| 日志 | 无技术细节的**本机脱敏诊断包**（默认不上传） | 密钥、路径、文件内容 |
| 身份 | 无（会话令牌**不得**作为身份使用） | 任何以 L-SESSION 充当 user_id / 角色 / 授权主体的用法 |

---

## 5. 验收测试清单（可执行断言草案）

> 均为**断言式**用例，落地后须由**独立 QA** 执行（施工者自验 ≠ 独立 QA）。

| # | 用例 | 期望 | 断言方法 |
|---|---|---|---|
| G-T01 | 网关绑定地址 | **仅** `127.0.0.1` | 读取监听 socket，断言 addr 非 `0.0.0.0`/`::` |
| G-T02 | 无会话密钥请求白名单路由 | `403` | 裸 HTTP 请求 |
| G-T03 | 错误会话密钥 | `403`，且**不泄露**正确值 | 恒时比较；响应体不含任何 token 片段 |
| G-T04 | **恶意 Host**（`evil.test`）→ 环回 | `403` | 构造 `Host: evil.test` |
| G-T05 | 带 `Origin: https://evil.test` | `403` | 构造跨源请求 |
| **G-T05b** | 带 **`Origin: null`** | **`403`**（REV1B：`null` 不作可信依据） | 构造 `Origin: null`，断言被拒 |
| G-T06 | 浏览器预检 `OPTIONS` | **无** `Access-Control-Allow-Origin` | 检查响应头 |
| G-T07 | 访问 `/admin/model/*`、`/admin/knowledge/migrate` | `403`（**结构性不可达**） | 白名单外全部路由逐一探测 |
| G-T08 | 环境变量指向**正式数据目录** | **拒绝启动**（非降级） | 设置 `XIAOZHI_DATA_DIR=<正式目录>` 后启动，断言退出码非 0 |
| G-T09 | 会话访问**非本批次** `job_id` / 非本目录 `course_id` | `403` + 审计记录 | 跨批次/跨目录请求 |
| G-T10 | 构建产物凭据扫描 | **0 命中** | 对 `dist/**` 全量扫描 token 形态 |
| G-T11 | 日志脱敏 | 无密钥、无文件内容 | 跑完完整导入后审计日志文件 |
| G-T12 | 会话空闲 30 min | 失效（`403`）；**重新授权须走受保护 IPC** | 等待/伪造时钟；断言续期通道为 P0/P1 |
| G-T13 | 教材内容出网探测 | **0** 次外连 | 全流程抓包/`lsof` 断言无外部连接 |
| G-T14 | 生产面未被触碰 | 无变化 | `NAS` 侧与生产存储哈希比对（只读观测） |
| **G-T15（S1）** | 同用户**另一进程**尝试获取 L-SESSION | **无法获取** | ①枚举本机监听 socket，断言**不存在**"连上即发密钥"的通道；②若采用 P2 UDS，断言无对端凭据校验时 `403` 且**只在已完成一次预授权后**发放 |
| **G-T16（S1）** | `ps`/`/proc` argv+env 扫描 | **0** 命中密钥 | 启动后扫描本机进程表，断言密钥不出现在命令行/环境中 |
| **G-T17（S5）** | **绕过 UI 直接 `POST /admin/course/{id}/publish`**（关键项未解决） | **`409 publish_gate_blocked`** | 不带 UI 字段直接调用；断言服务端独立拒绝（**非**因缺字段而误放行） |
| **G-T18（S5）** | 发布 `revision` 与 `ready` revision 不一致 | `409` | 构造错配 revision |
| **G-T19（S5/R2）** | 来源 `doc_id` 悬空 / `content_hash` 漂移 | `409 source_doc_missing` / `source_content_drift` | 删除来源文档后发布；断言已发布课程**仍在**（不级联删） |
| **G-T20（S3）** | 访问 `/admin/course/export*`、`/admin/course/{id}` `DELETE`、`/admin/*/store/*` | `403`（结构性不可达） | 逐条探测，断言路由**不存在** |
| **G-T21（S2）** | 将 L-SESSION 当身份使用（如写入课程归属） | 代码审查命中即**阻断** | 静态扫描"会话令牌 → 业务身份字段"的赋值路径 |
| **G-T22（01A 二.1）** | 学生模式进程加载面 | **不含** admin auth 模块、**不读** token 文件 | ①断言学生 app 的 import 图不含 `admin.app`/`auth.py`/`api_model`/`views`；②以 monkeypatch 令 `XIAOZHI_ADMIN_TOKEN_FILE` 指向探针文件，断言**从未被 open**；③断言进程内不存在 `TokenStore` 实例 |
| **G-T23（01A 二.2）** | 学生模式路由表 | **仅** `/cls/*` 7 条（+可选第 8 条），**无** `/admin/*` | 遍历 app router，断言 `/admin/` 前缀路由数 = 0；白名单外全部 `403` |
| **G-T24（01A 二.3）** | 若启用 P2 UDS：仅过 `getpeereid`（uid 相同） | **不放行** | 构造同 uid 另一进程连接；断言仅 `getpeereid` 通过时**拒绝**发放密钥（须 `LOCAL_PEERPID` + 预授权） |
| **G-T25（01A 二.3）** | P2 未经验证即启用 | **禁止**（构建/评审阻断） | 断言未配置"已验证对端身份机制"时 P2 代码路径不可达 |

**自证伪要求（沿用项目标准）**：对 §3.4 的 C2 校验，须做**反向断言**——把 `Host` 校验函数临时改回"不校验"，
确认 G-T04 **必然失败**，以证明该门禁真的在起作用（而非用例本身构造无效）。
**同理（REV1B 新增）**：
- 把 C3 从"任何 `Origin` 一律拒"改回"`null` 放行"，确认 **G-T05b 必然失败**；
- 把 §3.3 通道临时替换为"UDS 连上即发密钥"，确认 **G-T15 必然失败**；
- 把 §3.7 的发布门禁从服务端移除、只留 UI，确认 **G-T17 必然失败**。

---

## 6. 产品负责人裁定（REV1B）与本方案对应落实

> **总裁定**：Agent G 方案 **有条件批准**（`CONDITIONALLY_APPROVED`）。以下 S1–S5 为裁决结果，本文件已按裁决落实。

| # | 事项 | **裁定** | 本文件落实位置 |
|---|---|---|---|
| S1 | 会话密钥传递通道 | **匿名继承 fd / `socketpair` 优先**；**严禁**通过同一用户其他进程可连接的 socket **无条件**发放会话密钥 | §3.3（P0/P1 首选，P2 需强校验 + 独立安全复核）、§2.2 第 8 条、§5 G-T15/T16 |
| S2 | 会话 TTL 与空闲超时 | **进程内会话 + 空闲 30 min 过期**；**重新授权须走受保护 IPC** | §3.3 生命周期段、§5 G-T12/T21 |
| S3 | 白名单是否含"导出/删除"类操作 | **不开放学生端管理型导出、批量删除、存储维护** | §3.7 C 组、§4 能力行、§5 G-T20 |
| S4 | 诊断包是否允许用户导出 | **允许本机脱敏诊断包**（默认不上传） | §3.6、§0 摘要、§4 日志行 |
| S5 | 链路 B（课程发布面）白名单 | **按精确路径 / HTTP 方法 / 资源归属 / revision / 发布门禁逐条设计；待独立安全复核后放行** | §3.7 B 组（C-1…C-7）、§5 G-T17/T18/T19 |

**产品负责人附加要求（已全部落实）**：
1. **默认拒绝 + 限 `127.0.0.1`** —— §3.4 C1、§3.7。
2. **不接受未经明确定义的 `Origin: null` 作为可信依据** —— §3.4 C3（任何 `Origin` 一律拒）+ 信任来源澄清。
3. **学生服务不内置不必要管理员功能与凭据** —— §3.7 C 组、§2.2 L0。
4. **不把本机单用户会话令牌当学生身份** —— §3.2 语义澄清、§3.4 C5、§2.2 第 7 条、§5 G-T21。
5. **不接触 Tina / NAS / 生产凭据** —— §3.5 目标地址断言 + §7 状态块。

**仍未关闭（阻塞实现）**：
- S5 课程发布路由**必须经独立安全复核通过**后方可进入实现；**本轮不实现**。
- P2（UDS 兜底）**默认 PROHIBITED**；若确需采用，须**实测 `LOCAL_PEERPID` 可用** + 预授权 + 独立安全复核 +
  给出"不可能无条件发密钥"的结构性证明；**不得**以 `getpeereid` 作为对端 PID 依据（01A 二.3）。
- **01A 二.1**：学生网关"独立最小权限子应用"模型（§3.2.1）的**依赖图最小性**与 `/cls/*` 白名单（§3.8）
  须经独立安全复核；**复核通过前不开放学生端白名单服务与最终发布 API**。
- 冻结六文件 / 受保护数字人文件 / NAS / 生产环境**未触碰**（约束不变）。

---

## 7. 状态块

```
DELIVERABLE              = D1 最小权限导入访问方案（Agent G · REV1B 修订）
STATUS                   = DESIGN_ONLY（未实现、未部署）
REVISION                 = REV1B（S1–S5 已裁定并落实）
APPROVAL                 = CONDITIONALLY_APPROVED（有条件批准）
D1_MODE                  = MAC_LOOPBACK_ISOLATED
BIND                     = 127.0.0.1 ONLY（禁止 0.0.0.0 / ::）
AUTH                     = L-SESSION 一次性会话密钥
SESSION_CHANNEL（S1）    = 匿名继承 fd / socketpair 优先（P0/P1）
SESSION_CHANNEL_BAN      = 严禁"同用户可连接 socket 无条件发密钥"（P2 需强校验 + 独立复核）
P2_UDS_FALLBACK（01A）   = PROHIBITED_UNLESS_VERIFIED（getpeereid 仅 uid/gid，不能证明 PID；须实测 LOCAL_PEERPID + 预授权 + 复核）
SESSION_SEMANTICS        = 能力凭据 ≠ 学生身份（禁止当身份使用）
AUTH_TTL（S2）           = 进程内会话 + 空闲 30min；重新授权走受保护 IPC
ADMIN_PROXY_MODEL（01A） = ELIMINATED（不存在 L-SESSION → L-ADMIN 代理）
STUDENT_BACKEND（01A）   = 独立最小权限子应用（/cls/* 白名单 7 条；进程内共享 store，无 HTTP 代理）
ADMIN_APP_MOUNTED        = NO（admin app / auth.py / api_model / views 一律不加载）
ADMIN_TOKEN_FILE_READ    = NO（学生模式不解析 admin_api_token 密封文件）
ADMIN_BEARER_IN_CLIENT   = PROHIBITED（结构性不可达）
ROUTE_POLICY             = 默认拒绝 + 白名单（独立挂载子应用，非过滤器）
ROUTE_WHITELIST_A        = 导入/解析/知识库提交（已实现 7 条）
ROUTE_WHITELIST_B（S5）  = 课程草稿/校对/发布 C-1…C-7（**待独立安全复核**，本轮不实现）
ROUTE_DENY（S3）         = 管理型导出 / 批量删除 / 存储维护 → 结构性不可达
SOURCE_VALIDATION        = bind + Host 精确 + **Origin（任何值含 null 一律拒）** + 恒时密钥（C1–C4）+ C5 令牌≠身份
DIAGNOSTIC_PACKAGE（S4） = 允许本机脱敏导出（默认不上传）
DATA_ISOLATION           = 独立验收目录 + fail-closed（指向正式目录即拒启）+ 来源依赖校验
CREDENTIAL_HYGIENE       = 不落盘/不进前端/不进日志/不需用户输入 + 构建期扫描
NON_CHANGE               = NAS 未动 / 生产源未改 / 冻结六文件未动
IMPLEMENTATION_AUTHORIZED= NO（待独立安全复核 + 批准；S5 未复核前发布路由不得实现）
NAS_CHANGED              = NO
REAL_MODEL_REQUESTS      = ZERO
BLOCKERS                 = S5 独立安全复核；P2 通道若采用需额外复核
```

*本文件为**安全设计**交付，不代表任何保护已生效。*
