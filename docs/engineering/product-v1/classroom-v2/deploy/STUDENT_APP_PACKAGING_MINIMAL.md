# 学生 `.app` 打包最小化清单（PHASE 2 · 修正④）

- 依据：产品负责人 **PHASE 2 LIMITED START** 修正④——
  「学生 `.app` 不打包无关 admin-v4 管理页面、管理端点、凭据或生产配置；网关仅保留必要学生课堂能力；
  **修改后的打包清单须交独立安全 Agent 核验**」
- 所有者：**Agent H**（打包链路）· 安全边界共审 **Agent G** · 核验 **Independent QA / 独立安全 Agent**
- 状态：**`SPECIFIED`**（清单已定；**独立安全核验 = PENDING**）
- 关联：`security/D1_MINIMAL_PRIVILEGE_IMPORT_ACCESS.md §3.7`（路由白名单）· `D1_LOCAL_SERVICE_LIFECYCLE.md §2`（bundle 结构）

---

## 0. 原则

| # | 原则 |
|---|---|
| N-1 | **默认排除**：未在「允许清单」显式列出的路径/模块，一律**不进** `.app`。 |
| N-2 | **能力最小**：网关只保留「学生课堂 + 教材导入（链路 A）+ 课程草稿（链路 B 非发布）」所需能力。 |
| N-3 | **凭据零容忍**：任何 token / 密钥 / 生产配置**不得**出现在产物中（含 `__pycache__`、`.pyc`、Qt 资源）。 |
| N-4 | **结构性保证**：不靠"记得别打包"，而靠 **PyInstaller `datas`/`hiddenimports` 白名单 + 收集后剪裁 + 构建期扫描**三重。 |
| N-5 | **变更须核验**：任何对 `client/classroom_app.spec` 或构建脚本的改动，**必须**经独立安全 Agent 核验方可交付。 |

---

## 1. 允许清单（学生 `.app` 可包含）

### 1.1 客户端侧（当前已符合）

| 路径 | 用途 |
|---|---|
| `client/classroom_main.py` | 学生课堂入口 |
| `client/src/classroom/**`（含 `qml/`、`data/`、`course_schema.*`） | 课堂 UI + 冻结契约 + 本地演示课程 |
| `client/src/classroom/classroom_env.py` | 隔离目录解析（fail-closed） |
| Qt 运行时子集 | 仅 `QtCore/QtGui/QtQml/QtQuick/QtQuickControls2`（+ Layouts/Dialogs） |

### 1.2 网关侧最小能力面（子进程；**待 G 白名单子应用实现后收敛**）

| 模块 | 允许理由 |
|---|---|
| `gateway/app/main.py` | 环回启动入口（**需改造为"学生模式"入口**，见 §4 待收敛） |
| `gateway/app/http.py` | HTTP 基座 + 恒时令牌比较先例 |
| `gateway/app/admin/api_import.py` | 链路 A 导入/解析路由（**Agent I 复用**） |
| `gateway/app/admin/api_auth.py` | 会话鉴权（**改造为 L-SESSION，而非 admin Bearer**） |
| `gateway/app/admin/stores.py`、`registry.py`（**仅导入所需部分**） | 存储访问 |
| `modules/knowledge/**` | 解析器 + 导入流水线 + 知识库存储 |
| `modules/curriculum/**` | 课程契约（v1 权威） |
| `modules/memory/**` | 本地结构化学习记录（Agent F） |
| `modules/policy/**` | 教学策略（若链路 A 需要） |

---

## 2. 拒绝清单（**不得**进入学生 `.app`）

### 2.1 管理 GUI / 静态面

| 路径 | 理由 |
|---|---|
| `admin-v4/**`（`app.js`、`app-pro.js`、`index.html`、`styles.css`，约 264 KB） | 管理端 Web GUI，与学生无关 |
| `admin/**`（约 44 KB） | 旧管理面 |
| 任何 `**/*.html` 管理页、`**/static/admin*` | 同上 |

### 2.2 管理端点 / 管理能力模块

| 路径 | 理由 |
|---|---|
| `gateway/app/admin/api_model.py` | 模型凭据写入 / 注册 / 门禁 / 探测 → **管理面，结构性不可达** |
| `gateway/app/admin/api_teacher.py` | 老师档案**写**操作 |
| `gateway/app/admin/api_voice.py`、`api_teaching.py` | 管理型编排面 |
| `gateway/app/admin/realtime_probe.py` | 实时能力探测（管理型） |
| `gateway/app/admin/password_auth.py` | 口令鉴权（学生端用 L-SESSION，不需要） |
| `gateway/app/admin/views.py` | 管理视图 |
| `gateway/app/admin/config.py`（生产配置面） | 生产配置 |
| `gateway/app/admin/version.py` | 管理版本面（除非学生端版本校验确需，届时**最小内联**） |
| 任何 `**/migrate*`、`**/rollback*`、`**/store/*`、`**/compact`、`**/gc` 路由 | **S3：存储维护 / 批量删除 / 管理型导出**，禁止 |

### 2.3 冻结与生产件

| 路径 | 理由 |
|---|---|
| `gateway/app/{turns,qwen,audio,protocol,ws,behavior}.py`（Tina 冻结六文件） | **冻结**：不打包、不修改、不引用 |
| `/app/secrets/**`、`**/admin_api_token*`、`**/*.key`、`**/*.pem` | 凭据 |
| `**/.env`、`.env.*`、`**/secrets/**`、`**/credentials*.json` | 凭据 / 生产配置 |
| NAS / 生产网关配置（`deploy/v4-candidate/**` 的生产 env） | 生产面 |
| 测试凭据 / `tests/**` | 非运行期 |

### 2.4 受保护数字人文件（不得进入**产物逻辑**，也不得被引用）

| 路径 | 理由 |
|---|---|
| `client/src/ui/gui/**`、`client/src/avatar/**`、`client/probe_avatar_qml_offscreen.py` | **受保护未提交基线**；D 只能**新建**适配层 |
| `docs/engineering/product-v1/avatar-vision-v0/**` | 文档，非产物 |

---

## 3. 构建期扫描规则（可执行断言）

> 与 `security/D1_…§3.6` 共用；**任一失败即构建失败**（不是警告）。

| # | 扫描 | 通过条件 |
|---|---|---|
| PK-1 | 产物内**路径名**扫描 | 命中 `admin-v4`、`admin/`、`secrets`、`.env`、`admin_api_token`、`*.pem`、`*.key` → **0 命中** |
| PK-2 | 产物内**文本**扫描（`*.py` / `*.pyc` 字符串表 / Qt 资源） | 命中 **token 形态**（长度 ≥ 24 的 base64url/hex 且非已知常量）→ **0 命中** |
| PK-3 | 产物内**模块导入图** | 不得出现 `api_model` / `password_auth` / `api_teacher` / `api_voice` / `realtime_probe` → **0 命中** |
| PK-4 | 路由表导出（学生模式入口） | 导出路由集合 **==** 白名单集合（`§3.7 A 组 7 条` + B 组待复核）；多一条即失败 |
| PK-5 | 冻结六文件 SHA256 | 与基线**逐字节一致**（未修改、未被替换为改写副本） |
| PK-6 | 受保护数字人文件 | 集合与基线**一致**；产物内**不含**其副本 |
| PK-7 | 环回绑定断言 | 运行期仅 `127.0.0.1`；产物内**无** `0.0.0.0` 绑定字符串 |
| PK-8 | 外连断言 | 启动至就绪期间**零外部连接**（抓包 / `lsof`） |

**体积基线（供回归对照）**：修正④交付时的 `client/dist/小智 AI 学生课堂.app` ≈ **155 MB**（FIX01 期）。
最小化后预期**不增加**；若增加 > 5 MB 须说明原因（例如新增解析依赖），否则视为回归。

---

## 4. 待收敛项（**已知，需在 Phase 2 关闭**）

| # | 项 | 说明 | 关闭责任 |
|---|---|---|---|
| C-1 | 学生模式网关入口 | 当前 `gateway/app/main.py` 会挂载**完整管理 app**（含 `api_model` 等）。须新增**学生模式入口**，只挂载白名单子应用 | **G**（白名单子应用）+ **H**（打包收敛） |
| C-2 | 鉴权形态 | `api_auth.py` 面向 admin Bearer；须改造为 **L-SESSION**（`security §3.3`） | **G**（独立安全复核前不得开放） |
| C-3 | 链路 B 发布路由 | **不得**进入产物（白名单 B 组待 S5 独立复核） | **G** |
| C-4 | 解析依赖入包 | 网关解析依赖（pdfminer/docx/pptx）进入子进程后体积上升，须重新核对 PK 基线 | **H** |
| C-5 | 端口/IPC 形态 | 子进程 `port 0` + 受保护 IPC（`deploy §3`）；实现须先过独立安全复核 | **G + H** |

---

## 5. 核验流程（独立安全 Agent）

```
H 提交产物 + 本清单变更  →  G 预审（白名单/鉴权/凭据面）
                        →  独立安全 Agent 执行 PK-1…PK-8 + 人工抽查
                        →  出具核验结论：
                             ☐ APPROVED（可交付）
                             ☐ APPROVED_WITH_CONDITIONS（列明条件）
                             ☐ REJECTED（列明阻断项）
                        →  TC 记录到 PHASE2_INTEGRATION_REPORT / MAC_APP_BUILD_REPORT
```

**核验人**：__________　**日期**：__________　**结论**：☐ APPROVED　☐ APPROVED_WITH_CONDITIONS　☐ REJECTED

---

## 6. 状态块

```
DELIVERABLE                = 学生 .app 打包最小化清单
STATUS                     = SPECIFIED（清单已定；实现待 Phase 2 收敛 C-1…C-5）
ALLOWLIST_CLIENT           = client/src/classroom/** + classroom_main.py + Qt 子集
ALLOWLIST_GATEWAY          = 导入/契约/记忆面（api_import · api_auth(L-SESSION) · knowledge · curriculum · memory）
DENYLIST_ADMIN_UI          = admin-v4/** · admin/**（不进产物）
DENYLIST_ADMIN_ENDPOINTS   = api_model · api_teacher · api_voice · api_teaching · realtime_probe · password_auth · views · config(生产)
DENYLIST_CREDENTIALS       = secrets/ · *.env · *.pem · *.key · admin_api_token · credentials*.json
DENYLIST_FROZEN            = gateway/app/{turns,qwen,audio,protocol,ws,behavior}.py
DENYLIST_PROTECTED_AVATAR  = client/src/ui/gui/** · client/src/avatar/** · probe_avatar_qml_offscreen.py
BUILD_SCAN_RULES           = PK-1…PK-8（任一失败即构建失败）
GATEWAY_MINIMAL_SURFACE    = 待 C-1 学生模式入口收敛
INDEPENDENT_SECURITY_REVIEW= PENDING（清单变更须核验）
NAS_CHANGED                = NO
REAL_MODEL_REQUESTS        = ZERO
```

*本清单为打包**规范**交付物；不代表产物已最小化，`C-1…C-5` 未关闭前不构成"已完成最小化"结论。*
