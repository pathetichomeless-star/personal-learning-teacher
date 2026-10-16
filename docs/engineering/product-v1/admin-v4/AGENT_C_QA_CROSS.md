# XIAOZHI V4 — 独立 QA 交叉审核（Agent C）

- **角色**：独立 QA 交叉审核代理（全新视角，不采信任何下游结论）。
- **日期**：2026-10-10（Asia/Shanghai）。**分支**：`v4-admin-dev`，HEAD `d177582e1e4ec4737ca0ef8ec68966ce7fb7798d`（亲手 `git rev-parse` 复核）。
- **性质**：只读。除本报告外未修改任何文件；未重启/停止 127.0.0.1:8119 / 8123；未 SSH NAS；未调用付费模型；未 commit。所有数字均为亲手运行的原始输出。
- **被审对象**：`AGENT_A_ARCHITECTURE.md`、`AGENT_B_SECURITY.md`、`AGENT_D_FROZEN_REGRESSION.md`、`AGENT_F_B6_DEPLOY_REVIEW.md`、`RECOVERY_CHECKPOINT_20261010.md`，以及浏览器代理（E）摘要。

---

## 1. 核验矩阵（声明 / 核验方法 / 原始结果 / 采信）

| # | 来源 | 声明 | 我的核验方法 | 原始结果 | 采信 |
|---|---|---|---|---|---|
| V1 | RECOVERY | 分支 `v4-admin-dev`，HEAD `d177582…` | `git rev-parse` | `v4-admin-dev` / `d177582e1e4ec4737ca0ef8ec68966ce7fb7798d` | ✅ 一致 |
| V2 | RECOVERY | 工作树 13 个已修改跟踪文件 | `git status --porcelain=v1` | 13 个 `M`（client×4、docs×1、gateway/app/admin×5、gateway/app/main.py、gateway/tests/knowledge1_tests.py、modules/knowledge/store.py） | ✅ 一致 |
| V3 | RECOVERY | 18 组未跟踪新文件 | `git status --porcelain=v1` 计数 | 共 42 行；`??` 未跟踪条目 **29** 个（非 18） | ⚠️ 数量已增长（含审核报告等后续新增）；方向不矛盾 |
| V4 | A 复验 | 五套件合计 **331** 全绿（admin_v4=89、import_v4=39、model_v4=62、knowledge1=72、admin2=69） | 亲手 `for t in ...; .venv-v4/bin/python tests/$t.py` | admin_v4 `total=89 pass=89 fail=0`；import_v4 `39/39/0`；**model_v4 `total=67 pass=67 fail=0`**；knowledge1 `72/72/0`；admin2 `69/69/0` → **合计 336** | ⚠️ 套件全绿采信；**总计数 331→336**（model_v4 由 62 增至 67，B-SSRF-2 硬化后新增用例） |
| V5 | D | `admin_security_tests 29/29`、`admin_ui_tests 23/23`、`admin2_tests 69/69` | 亲手运行 | `29/29/0`、`23/23/0`、`69/69/0` | ✅ 一致 |
| V6 | D | 冻结语音链路 7 文件零改动 | `git diff HEAD -- turns/audio/qwen/diag/counters/protocol/http/behavior/ws .py` | 输出为空（exit 0） | ✅ 一致 |
| V7 | D | ADMIN P0 基线 `auth.py/registry.py/service.py` 零改动 | `git diff HEAD -- gateway/app/admin/{auth,registry,service}.py` | 输出为空（exit 0） | ✅ 一致 |
| V8 | B 复验 | B-SSRF-1（mapped IPv6）Blocker 已关闭 | 亲手构造 6 个原始 payload 调 `validate_endpoint` | `::ffff:169.254.169.254/192.168.1.1/127.0.0.1/10.0.0.1/172.16.0.1/100.64.0.1` 全部 `private_address_blocked` | ✅ 一致 |
| V9 | B 复验 | B-SSRF-2：其余嵌入 IPv4 形式（6to4/Teredo/NAT64/compatible）**仍放行**（Minor 开放） | 亲手构造 `2002:0a00:0001::`、`64:ff9b::10.0.0.1`、`64:ff9b::169.254.169.254`、`::10.0.0.1` | **全部 `private_address_blocked`（已拒）**；公网映射 `::ffff:93.184.216.34`、`2002:5db8:d822::` 放行不误伤 | ❌ 与 B 报告不符：**当前代码已硬化为全部拦截，B-SSRF-2 实际已关闭**（报告为旧状态） |
| V10 | B/A 复验 | 连接后 peer IP 校验生效且不误拒 | 亲手起本地 127.0.0.1 socket，用 `_opener(allow_local)` 直连 | `allow_local=False -> REFUSED connected_ip_blocked`；`allow_local=True -> ALLOWED status=200` | ✅ 一致 |
| V11 | B | 匿名/错误 token 401 体仅 `request_id` 不同（非 oracle） | `curl` 两次对比 | `{"error":"unauthorized","request_id":"9a07…"}` vs `…"bd42…"`，体一致仅 id 不同 | ✅ 一致 |
| V12 | B | peer_allowed 对带 scope link-local / None fail-closed | 亲手调用 | `peer_allowed("fe80::1%en0")=False`、`peer_allowed(None)=False`、`127.0.0.1`(no allow)=False、(allow)=True | ✅ 一致 |
| V13 | A | UI 调用与路由一一对应 | 提取 `admin-v4/*.js` 全部 `/admin/...`，比对 `admin_route_table`（85 路由） | 抽样 36/36 路径全部命中（见 §3） | ✅ 一致 |
| V14 | A 复验 | `promote_realtime_safe` 无管理路由（Observation） | 全仓 `grep` + 打印路由表过滤 | 仅 `modules/model/registry.py:467` 定义；路由表中 `promote/realtime` 命中为 `[]` | ✅ 确认（见 §5「苗头」） |
| V15 | B | m1 错误码 `"unknown protocol"` 等非 snake_case 仍开放 | `grep api_model.py` | `api_model.py:43-44` 仍为 `"unknown protocol"/"unknown_provider"/"unknown model"` | ✅ 一致（仍开放） |
| V16 | B | m2 `unsupported_content_type` 未入 §0.2 表 | `grep api_import.py` | `api_import.py:155` 仍 `unsupported_content_type` | ✅ 一致（仍开放） |
| V17 | B | B-AUDIT-1：审计先于读回写入 | `grep` 调用顺序 | 例 `api_model.py:196 _audit` → `:197 _durable`（多处以 audit 在前） | ✅ 一致（仍开放） |
| V18 | B | B-SCHEMA-1：migrate 读回仅比对条数，`sha256` 为备份摘要 | `grep _jsonstore.py` | `:205/:209` 仅比 `len()`；`:190` 返回备份文件摘要 | ✅ 一致（仍开放） |
| V19 | A | m3：/admin/health 未暴露 V4 store/registry | `curl` authed health 打印键 | 仅有 `qwen_*`、`admin.*`、`responses`、`build`；**无 `stores`/registry 字段** | ✅ 一致（仍开放） |
| V20 | B | m5：retry 未限次、解析无强制超时 | 查看 `imports.py` | `retry` 仅判 `RETRYABLE_ERRORS`，无尝试上限 | ✅ 一致（仍开放） |
| V21 | RECOVERY | 五格式解析器真实可用（pdfminer 20260107、docx 1.2.0、pptx 1.0.2） | 亲手导入版本 + import_v4 套件 | `pdfminer 20260107`、docx OK、`pptx 1.0.2`；import_v4 全绿 | ✅ 一致 |
| V22 | RECOVERY | 验收环境 E2E **70/70** | 亲手 `gateway/.venv-v4/bin/python /tmp/v4_e2e_verify.py` | **未能得到 70/70**：第 28 项 `FAIL provider create + readback` → `duplicate_provider`，脚本抛 `KeyError:'provider'` 崩溃（前 27 项 PASS） | ⚠️ **不可直接复现**（脚本非幂等 + 环境有状态）；见 §2 说明 |
| V23 | RECOVERY | 五格式真实解析已入库 | 只读查询 live `/admin/knowledge/datasets` | 数据集 `ds_b94fe3278b24` 有 **5 documents / 5 chunks**（上次成功运行的持久状态） | ✅ 旁证 E2E 曾真实跑通 |

> 浏览器代理（E）结论：**无法复跑**，仅做「证据可得性」评估。其 4 项 Minor（`model_key` 同名共存、`/@vite/client` 一次 ERR_ABORTED、隐藏 toast 残留 DOM、真实验证未弹授权确认）均为**交互层观察，缺可复现产物（无脚本/截图/日志）**，不采信为已验证。其中 `model_key` 同名共存一项，我独立查证 `registry.py:305-306`：`duplicate_model` 判定为 `provider_id == prov["id"] and model_key == key`（**按 provider 隔离**），两行同名属不同 provider，**符合设计**，非缺陷。

---

## 2. E2E 70/70 声明的独立核验结论（重点）

- `/tmp/v4_e2e_verify.py` 为**有状态、非幂等**脚本：以固定 `name/protocol/base_url`（"本地验收 Mock"/`http://127.0.0.1:8123/v1`）创建 Provider。
- 由于 8119 验收环境**保留**了上次成功运行的持久状态，重跑即在 `POST /admin/model/providers` 处返回 `duplicate_provider`，脚本在第 28 项崩溃。**这是脚本/环境状态问题，不是产品缺陷。**
- 我不能重启/重置验收环境（任务约束），故**无法在当前状态得到 70/70 原始 summary**。
- 但**旁证充分**：live 环境现存 `prov_c6ac33a246bf`(allow_local) + `mdl_ea54fe9502cb`(`evidence_level=verified`、`scenes=[text_chat]`) + 数据集 5 文档/5 块，与「provider→credential→model→真实探测→enable→bind text_chat→五格式入库」的完整链路**逐项吻合**，且脚本前 27 项（UI/鉴权/路由/解析器/冻结只读）本轮**再次 PASS**。
- **判定**：RECOVERY 的「70/70」声明**方向可信、有环境旁证，但当前不可独立复现**（属证据可得性缺陷，非造假证据）。

---

## 3. UI ↔ 路由一致性（亲手抽样）

`admin_route_table`（model_registry + knowledge_imports 均 wired）= **85 条**路由。从 `admin-v4/app.js` + `app-pro.js` 提取全部 `/admin/...`，抽样 36 条逐一比对：**36/36 全部命中**（`/admin/health`、`/admin/model/{providers,models,credentials,scenes,provider-templates}` 及其 `{id}/enable|disable|test|bind-scene|set-default|rotate`、`/admin/knowledge/{import,parsers,search,datasets,dataset/create|delete|enable|rename|diagnostics,document/delete,migrate}`、`/admin/memory/{items,search,delete,diagnostics}`、`/admin/policy/{active,audit,versions}`、`/admin/audit`、`/admin/knowledge/dataset/{id}/documents`、`/admin/knowledge/import/{id}/commit|cancel|retry`）。无调用不存在路由。
Token 卫生：`app.js:31` 统一附 `Bearer`；`:315/:319` **仅** `sessionStorage`；双模式 NAV（日常/专业）结构完整。
**结论：A 的静态一致性声明采信。**

---

## 4. 一致性交叉检查（报告间矛盾/陈旧点）

| # | 现象 | 性质 | 影响 |
|---|---|---|---|
| C1 | A/B 复验称五套件 331（model_v4=62）；实测 model_v4 **67**、五套件 **336** | 时间性陈旧（B-SSRF-2 硬化后新增 5 用例，报告未同步） | 无实质矛盾；数字需以本报告为准 |
| C2 | B 报告列 **B-SSRF-2 为开放 Minor**；实测该 Minor **所有形式已被拦截** | 报告状态**滞后于代码**：嵌入 IPv4 硬化已在 B 复验后落地 | B-SSRF-2 实际**已关闭**，非缺口 |
| C3 | F 报告「门禁② 未满足（理由：仓库内未发现针对真实 V4 实现的独立审计报告）」 | F 写作时 `admin-v4/` 仅 RECOVERY 一份；**A/B/D 报告在其后产生** | F 的门禁②判定**已被后续报告超期**：现有 3 份独立审计（+本报告），修复后 **0 Blocker / 0 Major** |
| C4 | RECOVERY 称「311 绿」，A 称「331」，实测「336」 | 时间性增长 | 无矛盾 |
| C5 | RECOVERY「18 组未跟踪」，实测 29 条 `??` | 时间性增长（新增报告等） | 无矛盾 |
| C6 | 无「声称通过但无证据」的功能性条目被发现（除 V22 E2E） | — | E2E 一项属证据可得性缺陷 |

---

## 5. 8 项需求独立判定（不照抄他代理）

> 证据来源：本报告 §1 核验矩阵 + 亲手运行的 7 套件 + live 8119 只读查询 + 源码抽查。

| # | 需求 | 判定 | 我的证据 |
|---|---|---|---|
| 1 | 真实 API 路由与前后端连接 | **满足** | 路由表 85 条 wired；UI 路径抽样 36/36 命中；live E2E UI `/v4/*` 200、未知 404；admin_ui U1/U17 PASS |
| 2 | Provider/Model/Adapter/API Key 安全 | **满足** | 凭据 Fernet 加密、权限 600、响应/审计无明文（admin_v4 T10/T10b；model_v4 凭据组）；401 非 oracle（V11）；SSRF 全部载荷拒绝（V8/V9/V10） |
| 3 | 模型持久化/验证/场景绑定 | **满足（带保留）** | DISK READ-BACK 新实例、evidence 阶梯、门禁七步（model_v4 全绿；live model `verified`+`text_chat`）；**保留**：自定义模型无法经 API 达到 `realtime_safe`（无路由，见苗头 M-C） |
| 4 | 五格式真实导入 | **满足** | pdfminer/docx/pptx 实装（V21）；import_v4 39/39；live 数据集 5 文档/5 块（V23）；source_type 覆盖 text/markdown/pdf_text/docx_text/pptx_text |
| 5 | 知识库解析/预览/确认入库/检索/来源展示 | **满足** | upload≠commit（T8b/T8c）、commit 读回、search 携带 doc/dataset 来源（T8s + E2E 项） |
| 6 | 日常/专业双模式真实界面 | **满足（交互仅静态核）** | app.js 双模式 NAV + app-pro.js 专业页；sessionStorage 令牌；live `/v4/*` 200。**交互层由 E 覆盖，我无法复跑** |
| 7 | 后台与真实运行服务配置/状态贯通 | **部分满足** | health 透传 qwen 运行态（mode/model/voice/connected/sessions）+ admin.*；**未**暴露 V4 store bundle / registry 可用性（A-m3，实测确认） |
| 8 | 首装与既有 Tina 升级兼容 | **满足** | T13（升级：冻结只读+既有知识保留+不改写原文件）、T13b（空模型≠丢失）、T13f–T13i（首装）全绿；另有 T12/T12b/T12c 版本门禁 |

**独立总判定：1/2/4/5/6/8 = 满足；3 = 满足（带 1 项功能可达性保留）；7 = 部分满足。无「未满足」项。**

---

## 6. 未关闭问题台账（汇总 + 上线门禁影响）

### 6.1 Blocker / Major（当前状态）
- **Blocker：0**（B-SSRF-1 已关闭，亲手复现 V8；无新 Blocker）。
- **Major：0**（A-M1 已关闭，亲手复现 V10）。
- **苗头（需产品确认是否升级 Major）**：
  - **M-C（功能可达性）**：`promote_realtime_safe` 仅存于 `registry.py:467`，**无任何管理路由**（路由表过滤 `promote/realtime` 为空）。契约 §2.3 步骤 3「显式运维提升 realtime_safe」在 admin 面**不可达**；非冻结模型因此**无法经 API 绑定 `oral_realtime`**（仅冻结链路经自动检测获 `realtime_safe`）。**无安全影响（fail-closed）**，但属需求 3 的功能缺口，建议产品负责人裁定契约意图。

### 6.2 Minor 台账与门禁影响

| 编号 | 来源 | 内容 | 影响上线门禁？ |
|---|---|---|---|
| m1 | A | 错误码 `"unknown protocol/…"` 非 snake_case（`api_model.py:43-44`） | 否（仅一致性） |
| m2 | A/B | `unsupported_content_type` 未入 §0.2 表（`api_import.py:155`） | 否 |
| m3 | A | health 未暴露 V4 store/registry（实测确认） | 否（可观测性；影响需求 7 完整度） |
| m5 | A | retry 未限次 / 解析无强制超时（`imports.py`） | 否（单文件 ≤20MB，风险低） |
| m6 | A | 模型/凭据 store 无 migrate/rollback 端点 | 否（低版本前向读+高版本拒写已生效） |
| B-SCHEMA-1 | B | migrate 读回仅比条数、sha256 为备份摘要 | 否 |
| B-IMPORT-1 | B | 导入缺 mime 校验（仅扩展名） | 否（扩展名白名单+路径派生已足够） |
| B-IMPORT-2 | B | 未知扩展名用 `unsupported_content_type` vs 契约 `unsupported_format` | 否 |
| B-IMPORT-3 | B | 过期预览 scratch（含全文）未清理 | 否（TTL 隐私残留，建议清理） |
| B-AUDIT-1 | B | 审计先于读回写入（`api_model.py` 多处） | 否（审计措辞问题） |
| B-CRYPTO-1 | B | 无 `cryptography` 时 `KeyStoreError` 走兜底 500 | 否（当前已装 50.0.2） |
| B-ROLLBACK-1 | B | `rollback.backup_id` 为未校验任意路径、不校验 sha256 | 否（可达性受 admin 鉴权限制）；建议收紧 |
| D-1 | D | `admin1_tests.py` 本地两 venv 均无法运行（缺 opuslib/libopus） | 否（环境依赖，非 V4 引入；覆盖缺口） |
| D-2 | D | `admin/api.py|views.py|app.py` 为 ADMIN P0 基线文件，本轮含加法式改动 | 否（三套安全/UI 套件全绿佐证） |
| E-1..E-4 | E | `model_key` 同名共存（我判定非缺陷）、/@vite/client 一次 ERR_ABORTED、隐藏 toast DOM、未弹授权确认 | 否（交互层观察，缺复现产物） |
| B-AUTH-1/B-GATE-1 | B | 401 非 oracle（OK）；`realtime_safe` 提升端点缺失 | B-GATE-1 见苗头 M-C |

### 6.3 B6 / 生产部署门禁（F 报告）
- **B6：BLOCKED**；门禁①部分满足、②（F 写作时缺证据，现已由 A/B/D+本报告补齐，**可重评**）、③ 无 ARM64 候选、④ 未满足。
- **均为「生产 NAS 部署」门禁，不影响本地 V4 验收环境结论**；任何生产部署仍须 `BLOCKED_NOT_DEPLOYED`、保留旧系统（含 <legacy-platform> 写入面未闭合）。

---

## 7. 最终 QA 结论

- **交叉核验是否通过：通过（PASS）**。A/B/D 的关键结论经亲手抽样（23 项核验矩阵）**方向一致、无造假**；无「声称通过但无证据」的功能性条目。测试全绿、冻结零改动、SSRF Blocker/Major 已关闭、UI↔路由一致均获独立确认。
- **需修正的表述**：(a) 五套件总计数以 **336**（非 331）为准；(b) **B-SSRF-2 已实际关闭**（B 报告状态滞后）；(c) **F 的门禁②判定已被后续独立审计超期**，建议按 0 Blocker/0 Major 重评。
- **证据可得性缺陷**：E2E「70/70」当前**不可复现**（脚本非幂等 + 环境有状态）；建议将 E2E 改造为可重置/幂等，以取得可重复的原始 summary。
- **风险陈述**：
  1. **功能可达性（M-C，未关闭）**：admin 面无 `realtime_safe` 提升路径，自定义模型绑 `oral_realtime` 不可达——**需产品裁定**，为唯一潜在 Major 苗头（无安全影响）。
  2. **生产部署风险**：B6 BLOCKED、无 ARM64 候选、<legacy-platform> 写入面未闭合、无独立恢复——**严禁生产部署**，与本轮 V4 代码质量无关。
  3. **可观测性**：需求 7 仅部分满足（health 未贯通 V4 store/registry）。
  4. **Minor 残余**：命名一致性、审计顺序、scratch 清理、rollback 路径校验等，均**不影响上线门禁**，建议纳入后续批次。
- **上线门禁结论**：V4 **本地功能验收层面无 Blocker、无 Major**（M-C 待裁定）；**生产部署门禁未满足**（B6/ARM64/恢复）。

---
**审核者边界**：本报告为独立只读审核；未改任何文件（除本报告）；未重启/停止 8119/8123；未 SSH NAS；未调用付费模型；未 commit。所有数字均为亲手运行原始输出。