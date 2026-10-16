# XIAOZHI V4 — 独立架构与最终需求符合性审计（Agent A）

- **范围**：V4 未提交改动（gateway/app/admin/{api,api_model,api_import,views,stores,app,config}.py、modules/model/*、modules/knowledge/{store,imports,parsers}.py、modules/_jsonstore.py、admin-v4/*、deploy/v4-acceptance/*、gateway/app/main.py 接线、gateway/tests/*）。
- **日期**：2026-10-10。**分支**：`v4-admin-dev`。
- **方法**：契约精读（`prototypes/admin-dual-mode-v4/XIAOZHI_ADMIN_V4_CONTRACT_FINAL.md`）→ 打印真实路由表比对 → 静态语义抽查（附 file:line）→ 运行 5 套确定性测试 → UI/API 路径一致性静态审查 → 需求 7/8 专项分析。
- **性质**：只读审计；除本报告外未修改任何文件，未启动/停止任何进程，未做任何付费调用或 NAS 操作。
- **权威依据**：契约 §0/§1/§2/§3/§4/§5/§7；其余文档按 §6 裁决表让位。

---

## 1. 端点逐条核验（契约要求 vs 实际实现 vs 证据）

真实路由通过以下命令打印（`admin_route_table(stores)` 在 model_registry + knowledge_imports 均 wired 时的完整清单）：

```
cd <project-root>/gateway && .venv-v4/bin/python -c "
from app.admin.app import admin_route_table; ...
class D: pass
d=D(); d.model_registry=1; d.knowledge_imports=1
for m,p in admin_route_table(d): print(m,p)"
```

### 1.1 §1.1 导入端点族 I1–I8

| # | 契约端点 | 实际实现 | 证据（file:line） | 结论 |
|---|---|---|---|---|
| I1 | `POST /admin/knowledge/import` | ✅ | `gateway/app/admin/api_import.py:143`（handler）、`:307`（挂载） | 符合 |
| I2 | `GET /admin/knowledge/import/{job_id}` | ✅ | `api_import.py:177`、`:309` | 符合 |
| I3 | `GET /admin/knowledge/import`（?status=&dataset_id=&limit=&offset=） | ✅ | `api_import.py:185`、`:308`；查询参数 `:188-191` | 符合 |
| I4 | `POST /admin/knowledge/import/{job_id}/commit`（confirm:true） | ✅ | `api_import.py:195`、`:310`；`_confirm` 于 `:199` | 符合 |
| I5 | `POST /admin/knowledge/import/{job_id}/cancel`（confirm:true） | ✅ | `api_import.py:216`、`:311` | 符合 |
| I6 | `POST /admin/knowledge/import/{job_id}/retry`（confirm:true） | ✅ | `api_import.py:229`、`:312` | 符合 |
| I7 | `GET /admin/knowledge/parsers` | ✅ | `api_import.py:243`、`:306` | 符合 |
| I8 | `GET /admin/knowledge/dataset/{ds_id}/imports` | ✅ | `api_import.py:248`、`:313` | 符合 |

额外（§4.2 要求）：`POST /admin/knowledge/migrate`（`api_import.py:259`）、`POST /admin/knowledge/rollback`（`:274`）已实现并挂载。

### 1.2 §2.1 模型管理端点族

| 契约族群 | 契约端点 | 实际实现 | 证据 | 结论 |
|---|---|---|---|---|
| Provider | `GET\|POST /admin/model/providers`、`PUT\|DELETE /…/{id}`、`GET /…/provider-templates` | ✅ | `api_model.py:546-572` 路由表、`:575-603` 挂载 | 符合 |
| Model | `GET\|POST /admin/model/models`、`PUT\|DELETE /…/{id}`、`POST /…/{id}/{enable\|disable\|set-default\|bind-scene}`、`POST /…/{id}/test` | ✅ | `api_model.py:554-563` | 符合 |
| Credential | `GET\|POST /admin/model/credentials`、`GET\|DELETE /…/{id}`、`POST /…/{id}/rotate` | ✅ | `api_model.py:564-568` | 符合 |
| Scene | `GET /admin/model/scenes`、`POST /…/{scene}/bind`、`POST /…/{scene}/unbind` | ✅ | `api_model.py:569-571` | 符合 |

补充：额外实现了 `GET /admin/model/providers/{id}`、`GET /admin/model/models/{id}`（单条读取），属加性、不冲突。

### 1.3 §3.4 凭据端点

| 契约端点 | 实际实现 | confirm | 响应含明文？ | 证据 |
|---|---|---|---|---|
| `GET /admin/model/credentials?provider_id=` | ✅ | — | 否 | `api_model.py:429-434`；`CredentialStore._public` 只回 fingerprint+credential_ref（`credentials.py:77-86`） |
| `POST /admin/model/credentials` | ✅ | 否 | 否 | `api_model.py:437-453` |
| `GET /admin/model/credentials/{id}` | ✅ | — | 否 | `api_model.py:456-462` |
| `POST /admin/model/credentials/{id}/rotate` | ✅ | ✅ | 否 | `api_model.py:465-478`；`credential_rotate` 调 `_confirm` |
| `DELETE /admin/model/credentials/{id}` | ✅ | ✅ | 否 | `api_model.py:481-497` |

结论：三族端点**全部存在且语义一致**，无缺失、无多余错挂。

---

## 2. 关键语义抽查（file:line 证据）

| 语义 | 是否真实实现 | 证据 |
|---|---|---|
| **upload ≠ commit** | ✅ | `modules/knowledge/imports.py:116-166` `create_job` 只写 `jobs`（不含 knowledge 文档）；入库唯一入口 `commit`（`imports.py:237-288`）。落地证据：`admin_v4_api_tests.py` T8b「upload -> preview_ready (NOT applied)」、T8c「upload did NOT write the store」PASS |
| **confirm 语义** | ✅ | I4/I5/I6 与 rotate/delete/set-default 均 `_confirm`（`api.py:247-251`）；`confirm` 缺失 → `400 confirm_required`（契约 §0.1/§0.2） |
| **DISK READ-BACK（新实例重读）** | ✅ | `api.py:175-217`（`_disk_*` 全部 `MStore/KStore/PStore(path).load()` 新实例）；导入 commit 读回 `api_import.py:206-208` + `imports.py:279-283`；模型读回 `api_model.py:134-147`。失败 → `500 persist_failed`（`api.py:233-236`） |
| **§0.2 错误码** | ✅（个别命名偏离，见 Minor） | `_err`（`api.py:61-68`）与各 `_map`（`api_model.py:40-83`、`api_import.py:35-63`）：confirm_required/capability_mismatch/evidence_missing/credential_missing/endpoint_not_allowed/frozen_model/malformed_document/unsupported_content_type/not_found/duplicate_*/cap_exceeded/*_in_use/job_not_*/parser_unavailable/job_expired/body_too_large/test_not_authorized/store_busy/store_unavailable/persist_failed/upstream_timeout/internal_error 全部存在 |
| **门禁七步顺序** | ✅ | `modules/model/gating.py:26-55`：1 存在→not_found；2 frozen→frozen_model；3 adapter→capability_mismatch；4 evidence≥verified→evidence_missing；5 credential→credential_missing；6 scene.need⊆caps→capability_mismatch；7 oral_realtime 需 realtime_safe→capability_mismatch。逐行与契约 §2.2 表一致。测试 `model_v4_tests.py`「实时语音：能力不足先被拒（契约步骤6先于7）」PASS |
| **evidence 阶梯** | ✅ | `registry.py:30`（id_only→adapter_present→verified→realtime_safe）；`evidence_level`（`:164-173`）仅从 `_data["evidence"]` 派生；`verified` 仅由 `model_test(mode=verified)` 在真实探测成功后 `set_evidence`（`api_model.py:384-386`）；`realtime_safe` 仅由 `promote_realtime_safe` 显式提升（`registry.py:467-475`）。服务端**不读**请求体 verify/verified/capabilities（`gating.py` 完全基于存储态） |
| **SSRF 防护** | ⚠️ 部分（见 Major-1） | `endpoint_policy.py:70-119`：scheme/端口/userinfo/元数据主机名/网段黑名单（含 127/8、10/8、169.254/16、::1、fc00::/7 等）/解析后逐一校验 IP 均已实现；`probe.py:41-50` 拒绝**一切**重定向（比「跨主机失败」更严）。**缺口**：未 pin 实际连接 IP |
| **版本门禁（§4.2 禁止静默清空）** | ✅ | `modules/knowledge/store.py:299-335`（`version_ahead`/`version_missing`/`corrupt`→`unavailable`，`_flush` 在 `:406-409` 拒写，`_persist` 在 `:434-441` 抛 `StoreUnavailable`）；通用基座 `modules/_jsonstore.py:97-175`。API 层读**与**写均 `503 store_unavailable`（`api.py:159-172` `_need_avail`）。测试 `admin_v4_api_tests.py` T12/T12b（读+写→503）、T12c（原文件未被覆盖）PASS；`import_v4_tests.py`「导入 store 高版本拒写/原文件未被覆盖」PASS |
| **冻结只读识别** | ✅ | `registry.py:497-555` `ensure_frozen_link` 仅把既有链路**镜像**为 `frozen:true` 只读行（写 MODEL_REGISTRY_FILE，不碰音频）；`stores.py:105-113` 自动检测；冻结项 enable/disable/set-default/bind-scene/delete 均被 `frozen_model` 拒绝（`gating.py:30`、`registry.py:370/435/398/348`）。测试 T2/T2b/T2c/T2d/T2e 与 `model_v4_tests.py` 冻结组 PASS |

---

## 3. 需求 7 / 8 专项分析

### 7. 管理后台与真实运行服务配置/状态贯通

`gateway/app/main.py:123-152`：仅当 `ADMIN_ENABLED=1` 时构建 `AdminStores`，从**同一运行配置**只读接入 `POLICY_FILE / MEMORY_FILE / KNOWLEDGE_FILE / WORKBENCH_BASE_URL / MODEL_*_FILE / KNOWLEDGE_IMPORT_*`，并把 **Qwen 实时快照**（`main.py:130-133`，来源为只读配置 `q.mode/model/voice/host/reconnect_max`）作为 `realtime_snapshot` 传入。

- 只读接入确认：`AdminStores`（`stores.py:73-103`）只做 `load()`，不写运行时配置；`frozen_link_snapshot`（`registry.py:564-575`）仅构造 dict。
- **不存在任何会改写冻结语音路径的代码**：全仓检索 `gateway/app/admin` 无 `session.update`/音频/WS 写入；`modules/**` 无 `from app`/gateway/audio 导入（`modules/__init__.py:7` 声明）；admin `registry.py` 对 qwen 仅**读**连接态。
- `/admin/health`（`views.py:92-132`）输出真实运行态：`status/degraded_reasons`、`qwen_mode/qwen_ready/qwen_model/qwen_voice/qwen_connected/qwen_sessions`、`active_sessions`、`admin.{enabled,bind,port,auth_configured,listener}`、build 事实。

**未覆盖点**：`/admin/health` **未**暴露 V4 store bundle 的接线/可用性（`AdminStores.describe()` 仅在验收启动器打印，未上网关 API）；`ModelRegistry.state()`/`available` 未出现在 health。记为 Minor-3。

### 8. 首次安装 vs 既有 Tina 升级兼容

- **首次安装（空 store / 无文件）**：`AdminStores._try`（`stores.py:115-123`）对空路径返回 `None`（该子面不挂载）；`ModelRegistry.ensure_seeded`（`registry.py:127-140`）写入场景定义但**不 seed 任何 Provider/Model**——模型中心初始为空，符合「我的模型为空」。UI 明确提示（`admin-v4/app.js:275`、`app.js:181-182`、`app-pro.js:25`）：「我的模型为空 ≠ 模型丢失」。
- **既有部署升级**：`ensure_frozen_link`（`registry.py:497-555`）在快照有 model 时自动镜像冻结 Tina 为只读；知识库旧 V1 文件经 `store.py:317-327` 前向兼容读取（`ver < SCHEMA_VERSION → migrated_from`），不改写结构。
- **覆盖缺口**：无「预置真实 V1 知识文件（含 datasets/documents/chunks）→ 升级后条数不变」的端到端兼容用例（仅版本门禁单测 K7/`model_v4_tests.py:62` 覆盖前向读取）；无「首装 + MODEL_REGISTRY_FILE 未配置时模型面 404」的显式用例。记为 Minor-4。

---

## 4. UI（admin-v4/）与真实 API 一致性（静态审查）

`admin-v4/app.js` / `app-pro.js` 中出现的全部 `/admin/...` 路径，**逐一比对已挂载路由**：全部命中，无调用不存在路由、无方法/路径拼接错误。抽样：

- 导入族：`/admin/knowledge/import`（`app.js:230`）、`…/{id}/commit|cancel|retry`（`app.js:136/141/145`）↔ I1/I4/I5/I6 ✅
- 模型族：`…/models/{id}/enable|disable|test|bind-scene|set-default`（`app-pro.js:40/44/49/62/74`）、`…/credentials/{id}/rotate|DELETE`（`app-pro.js:383/388`）↔ §2.1/§3.4 ✅
- 双模式导航：日常 4 项 + 专业 14 项的 `PAGES`（`app.js:154/194/254/279`、`app-pro.js` 全量）与 NAV（`app.js:71-94`）**一一对应**，无「页面未实现」空洞。
- 令牌仅存 `sessionStorage`、不落盘不打印（`app.js:2`）；`API()` 统一附 Bearer（`app.js:29-46`）。

结论：静态层面 UI↔API 完全一致。交互式验证由另一代理执行。

---

## 5. 测试原始摘要（确定性，无付费调用）

```
cd <project-root>/gateway
for t in admin_v4_api_tests import_v4_tests model_v4_tests knowledge1_tests admin2_tests; do
  .venv-v4/bin/python tests/$t.py; done
```

| 套件 | 结果 | 退出码 |
|---|---|---|
| `admin_v4_api_tests.py` | `total=80 pass=80 fail=0` | 0 |
| `import_v4_tests.py` | `total=39 pass=39 fail=0` | 0 |
| `model_v4_tests.py` | `total=51 pass=51 fail=0` | 0 |
| `knowledge1_tests.py` | `KNOWLEDGE1_TESTS: 72 checks, 72 PASS, 0 FAIL` | 0 |
| `admin2_tests.py` | `ADMIN2_TESTS: 69 checks, 69 PASS, 0 FAIL` | 0 |

**合计 311 checks，全部通过，0 失败。** 与恢复检查点文档所述「311 绿」一致。

---

## 6. 结论清单

### Blocker
- **无。** 契约 §1.1（I1–I8）、§2.1、§3.4 全部端点存在且语义一致；五格式导入、双模式 UI、main.py 接线、冻结只读、版本门禁、上传≠入库、confirm、DISK READ-BACK、门禁七步、evidence 阶梯均已真实实现并有测试证据。

### Major
- **M1（SSRF：未校验「实际连接 IP」/ DNS 重绑定窗口）** — `modules/model/endpoint_policy.py:70-119` 在创建/更新时校验解析出的全部 IP，`modules/model/probe.py:86-98` 连接前重新校验但用 `urllib` **再次独立解析**，未把已校验 IP pin 到实际连接；模块 docstring 亦自述「adapter 层必须额外复核实际连接 IP」，而 P0 无该层。
  - 影响：DNS 重绑定下，授权运维触发的真实探测可能连到内网/元数据地址（SSRF）。边界有限（仅管理员可建 provider + 需 `MODEL_TEST_AUTHORIZED=1` + 显式 `confirm_verified`）。
  - 建议：探测时用已校验 IP 直连（Host 头保留域名）或 socket 层 pin IP；实现 adapter 层的连接后 IP 复核。

### Minor
- **m1（错误码命名偏离 §0.2 编码化词表）** — `api_model.py:40-45,79-82` 将 `"unknown protocol"`/`"unknown_provider"`/`"unknown model"`（含空格）作为 error 码返回，非 §0.2 的 snake_case 编码。功能上均为 4xx，仅语义/一致性偏离。
- **m2（`invalid_multipart` 未入 §0.2 表）** — `api_import.py:109,147` 使用 `invalid_multipart`（400），§0.2 未列该码。
- **m3（/admin/health 未暴露 V4 store 接线/可用性）** — 需求 7 只透传 Qwen 运行态与 ADMIN 配置；`AdminStores.describe()`、`ModelRegistry.state()`/`available` 未上网关健康端点。建议 health 增 `stores` 字段以贯通「配置与状态」。
- **m4（升级/首装兼容用例覆盖不足）** — 缺「真实 V1 知识文件升级后条数不变」端到端用例与「首装未配置 MODEL_*_FILE」用例（见 §3.8）。
- **m5（重试未限次、解析无强制超时）** — 契约 §1.4 要求「有限次退避重试」与「解析总时长超上限→parse_timeout」；`imports.py:303-316` `retry` 无尝试次数上限，`imports.py:192-193` 的超时检查在同步解析**之后**，属防御性而非强制。风险低（单文件 ≤20MB）。
- **m6（模型/凭据 store 无 migrate/rollback 端点）** — §4.3 要求模型 store 适用「同样的 §4.2 规则」；`BaseJsonStore` 已提供版本门禁+backup/migrate/rollback（`_jsonstore.py:177-229`），但未暴露对应 `/admin/model/*` 迁移端点（§2.1/§3.4 端点表未要求）。当前低版本前向读 + 高版本拒写已生效，功能影响小。

### 核验边界声明
本审计为静态 + 确定性测试层面；未做浏览器端到端交互（由另一代理负责），未对 127.0.0.1:8119/8123 验收进程做任何操作。SSRF 结论基于代码走查，未构造真实 DNS 重绑定攻击验证。

---

## 复验（Re-verification）— 2026-10-10（原 A-Major 发现者独立复验）

针对主控对 **M1（SSRF 未校验实际连接 IP / DNS 重绑定窗口）** 的修复做独立复验（亲自执行，非仅信描述）。范围：`modules/model/probe.py`、`modules/model/endpoint_policy.py`、`gateway/tests/{model_v4_tests,admin_v4_api_tests}.py`。未修改本报告以外任何文件，未动 127.0.0.1:8119/8123，未做付费调用。

### R1. 静态审查：peer check 是否真正满足契约 §3.3「校验实际连接的 IP」

修复机制：`probe.py:51-67` `_peer_checked_class(base_cls, allow_local)` 生成 `HTTPConnection/HTTPSConnection` 子类，覆写 `connect()`：`super().connect()` 后立即 `peer = self.sock.getpeername()[0]`，交 `peer_allowed(peer, allow_local)` 判定，违规即 `self.close()` 并 `raise EndpointRejected("connected_ip_blocked")`；`probe.py:70-94` 用该类构造 `_PeerCheckedHTTP/HTTPSHandler` 并注入 `_opener(allow_local)`；`probe.py:142` `probe_verified` 以 `_opener(bool(provider.get("allow_local")))` 兜底（生产路径 `api_model` 传入的 `model_probe_opener` 默认 None，故走真实 opener）。

逐项判定：
- **时机**：http.client 在 `send()`→`connect()` 之后才发送请求字节，peer 校验先于任何请求数据 → 满足「连接后、发数据前」。
- **绕行路径**：唯一出口连接即 probe；注入 opener 仅存在于测试（`app.py:37` 生产为 None），不构成绕过；`_NoRedirect`（`probe.py:43-48`）拒绝一切重定向。
- **异常处理**：`getpeername` 抛 `OSError` → `peer=None` → `peer_allowed(None)=False` → fail-closed（`endpoint_policy.py:68-69`）；`EndpointRejected` 由 `probe_verified` 的 `except Exception` 归一为「验证未通过」，不崩溃、不谎报成功（`probe.py:152-156`）。
- **HTTPS 兼容**：`HTTPSConnection.connect()` 先建 TCP 再包 TLS，之后 `self.sock.getpeername()` 返回底层对端 IP，校验生效；`https_open` 传 `context=self._context`（`HTTPSHandler.__init__` 已置 None）→ 使用默认 SSL 上下文，无误拒。
- **不误拒合法公网**：`peer_allowed`（`endpoint_policy.py:64-77`）对非回环公网 IP 仅在命中黑名单时拒绝 → 公网放行。
- **附加修复（B 代理 Blocker）**：`endpoint_policy.py:49-53` `_norm()` 将 IPv4-mapped IPv6 归一为 IPv4，`_is_blocked`/loopback 判定/`peer_allowed` 均经 `_norm`，堵住 `::ffff:169.254.169.254` 等绕过。

结论：**满足契约 §3.3「校验实际连接的 IP」**，fail-closed、无生产绕行、HTTPS 兼容、不误拒公网。

### R2. 亲测（生产默认 opener 端到端 + 真实 socket）

命令（裸 `python -` 内联，未建文件）：
```
cd <project-root> && gateway/.venv-v4/bin/python - <<'PY'
from modules.model.probe import probe_verified, _peer_checked_class
# 本地 mock /v1/models + allow_local=True 的 openai_compatible provider ...
PY
```
原始输出：
```
allow_local=True via real _opener -> {'verified': True, 'network': True, 'reason': None, 'detail': '真实探测成功（免费元数据接口，未发起生成调用）'}
peer-check(no allow_local) -> refused: connected_ip_blocked
```
说明：合法回环（allow_local）经**真实生产 opener** 可正常连通并验证成功（不误拒）；同一 `_peer_checked_class` 在 `allow_local=False` 下对真实回环 socket **在连接后即拒绝**（`connected_ip_blocked`）。另：`allow_local=False` 的回环 base_url 由 `validate_endpoint` 第一层（`endpoint_policy.py:134-136`）先行 `private_address_blocked` 拒绝，构成纵深防御。

### R3. 五套件复跑（原始 total/pass/fail）

```
cd <project-root>/gateway
for t in admin_v4_api_tests import_v4_tests model_v4_tests knowledge1_tests admin2_tests; do
  .venv-v4/bin/python tests/$t.py; done
```

| 套件 | 复跑结果 | 退出码 | 对比首轮 |
|---|---|---|---|
| `admin_v4_api_tests.py` | `total=89 pass=89 fail=0` | 0 | 80→89（+T13 系列 9 项） |
| `import_v4_tests.py` | `total=39 pass=39 fail=0` | 0 | 39（持平） |
| `model_v4_tests.py` | `total=62 pass=62 fail=0` | 0 | 51→62（+peer/mapped 11 项） |
| `knowledge1_tests.py` | `KNOWLEDGE1_TESTS: 72 checks, 72 PASS, 0 FAIL` | 0 | 72（持平） |
| `admin2_tests.py` | `ADMIN2_TESTS: 69 checks, 69 PASS, 0 FAIL` | 0 | 69（持平） |

新增回归点名（全部 PASS）：
- `model_v4_tests.py`：拒绝 IPv4-mapped `::ffff:169.254.169.254/10.0.0.1/192.168.1.1/127.0.0.1`、`IPv4-mapped 公网地址不误伤`、`peer_allowed: 回环需 allow_local`、`peer_allowed: mapped 元数据地址拒绝`、`peer_allowed: 公网放行`、`peer_allowed: 未知 peer 拒绝`、`连接后 peer 校验拒绝回环（无 allow_local）`、`连接后 peer 校验放行回环（allow_local）`。
- `admin_v4_api_tests.py`：`T13`（既有部署升级：冻结只读识别、既有知识数据保留、可检索、启动不改写原文件）+ `T13b`（我的模型为空≠丢失）+ `T13f–T13i`（首次安装：空库非错误、解析器/场景可用、首次写入成功）。

**合计 331 checks，全部通过，0 失败**（首轮 311 → 复验 331，新增 20 项回归）。

### R4. 原 Minor 列表逐项现状

| 编号 | 内容 | 现状 |
|---|---|---|
| m4 | 升级/首装兼容用例不足 | **已修复**：T13/T13b/T13f–T13i 覆盖既有部署升级（保留数据、冻结只读、不改写原文件）与首次安装（空库、解析器、场景、首写） |
| m1 | 错误码命名偏离 §0.2（`"unknown protocol"`/`"unknown_provider"`/`"unknown model"` 含空格） | **仍开放**（`api_model.py:43-44,79-83`，本次未改） |
| m2 | `invalid_multipart` 未入 §0.2 表 | **仍开放**（`api_import.py:109,111,147`） |
| m3 | `/admin/health` 未暴露 V4 store bundle 接线/可用性 | **仍开放**（`views.py:92-132` 未增 `stores` 字段） |
| m5 | 重试未限次 / 解析无强制超时（§1.4） | **仍开放**（`imports.py:192-193,303-316`） |
| m6 | 模型/凭据 store 无 migrate/rollback 端点（§4.3 仅要求版本门禁） | **仍开放**（低版本前向读 + 高版本拒写已生效，功能影响小） |

### R5. 最终判定与计数

- **M1（原唯一 Major，SSRF 连接后 IP 校验缺失）：✅ 已关闭。** 静态审查满足 §3.3，生产路径实测拒绝/放行均正确，B 代理的 IPv4-mapped Blocker 一并关闭。
- **新引入的 Blocker / Major：无。** peer 校验为 fail-closed、HTTPS 兼容、不误拒公网地址；未发现绕行路径。
- **最终计数（复验后）**：Blocker **0** · Major **0** · Minor **5**（m1/m2/m3/m5/m6，均为命名/可观测性/边界健壮性类，非功能阻断）。