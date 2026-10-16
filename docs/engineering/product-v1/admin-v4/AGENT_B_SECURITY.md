# XIAOZHI V4 — 独立后端与数据安全审计（Agent B）

- **范围**：V4 未提交新增面（`modules/model/{registry,credentials,crypto,endpoint_policy,gating,probe,_jsonstore}.py`、`modules/knowledge/{store,imports,parsers}.py`、`modules/_jsonstore.py`、`modules/_store_lock.py`、`gateway/app/admin/{api,api_model,api_import,auth,app,views,stores,config}.py`、`gateway/app/main.py` 接线）。
- **日期**：2026-10-10。**分支**：`v4-admin-dev`。**性质**：只读；除本报告外未改动任何文件；未触碰 8119/8123；未调用付费模型；未 SSH NAS；未 commit。
- **权威依据**：`prototypes/admin-dual-mode-v4/XIAOZHI_ADMIN_V4_CONTRACT_FINAL.md`（§0 写骨架/错误码、§1 导入、§2 门禁、§3 凭据与 SSRF、§4 Schema 策略、§5 冻结只读）。冲突以契约为准。
- **方法**：契约精读 → 全量静态审查（grep 秘密流） → 在 `/tmp/audit_b/` 构造极端输入、用 `gateway/.venv-v4/bin/python` 运行 8 段复现脚本（真实 import 仓库模块，不写仓库内数据）。
- **复现脚本**：`/tmp/audit_b/t1_creds.py`、`t3_ssrf.py`、`t4_skeleton.py`、`t5_version_gate.py`、`t5_knowledge_gate.py`、`t6_import_api.py`、`t8_gating_api.py`、`t8b_gate_paths.py`。

---

## 0. 结论总表

| 编号 | 严重度 | 主题 | 判定 |
|---|---|---|---|
| **B-SSRF-1** | **Blocker** | SSRF 黑名单可被 IPv4-mapped IPv6（`::ffff:x.x.x.x`）绕过 | ❌ 不满足契约 §3.3 |
| B-SCHEMA-1 | Minor | 迁移读回仅校验条数，未校验内容哈希 | ⚠ 部分不满足 §4.2 |
| B-IMPORT-1 | Minor | 导入未做 mime 校验（仅扩展名） | ⚠ 不满足 §1.3 |
| B-IMPORT-2 | Minor | 未知扩展名错误码用 `unsupported_content_type`（契约 I1 用 `unsupported_format`） | ⚠ 文档/实现不一致 |
| B-IMPORT-3 | Minor | 过期预览的 scratch（`bin`/`txt`，含全文）未清理 | ⚠ TTL 隐私残留 |
| B-CRYPTO-1 | Minor | 未安装 `cryptography` 时凭据功能降级为 fail-closed（无明文回退，但无显式告警路径） | ℹ 见 §1.5 |
| B-AUDIT-1 | Minor | 审计在持久化读回**之前**写入，`persist_failed` 时审计仍记 `result:"ok"` | ⚠ |
| B-ROLLBACK-1 | Minor | `rollback` 的 `backup_id` 为未校验的任意路径，未限制为已知备份、未校验 sha256 | ⚠ |
| B-GATE-1 | Observation | 无管理端点暴露 `promote_realtime_safe`（§2.3 显式提升动作不可达） | ℹ fail-closed |
| B-AUTH-1 | Observation | 匿名/错误 token 的 401 体仅 `request_id` 不同（每请求随机，nonce 非 oracle） | ✅ 可接受 |

**通过（重点确认项）**：秘密卫生、鉴权常量时间与 fail-closed、门禁忽略请求体声明、`/test` 未授权 403 且不写入、冻结链路只读、版本门禁拒读写不静默清空、跨进程锁超时、DISK READ-BACK 新实例、幂等、重复内容 409 且 job 保持 `preview_ready`、上传大小上限、路径穿越不外逸、scratch 700/文件 600。

---

## 1. 秘密卫生（审计重点 1）

### 1.1 凭据加密与落盘权限 — ✅ 通过
证据 `/tmp/audit_b/t1_creds.py`：
```
public view: {... "fingerprint":"af02dd640d80c7d5", "credential_ref":"cred://cred_c8eeeffe2876/v1" ...}
file mode: 0o600        key  mode: 0o600
secret in file? False    token present? True    token is fernet (starts gAAAA): True
read_secret: True
after rotate current_v: 2 ref: cred://cred_c8eeeffe2876/v2
old ref rejected: stale credential_ref
delete no-confirm: ConfirmRequired confirm: true is required
grep plaintext in store dir: (none)
```
- 加密：`modules/model/crypto.py:59-71`（Fernet/AES-128-CBC+HMAC）；密钥独立文件、`os.chmod(tmp,0o600)`（`crypto.py:53-55`）。
- 落盘：密文写入 store，权限 600（`modules/_jsonstore.py:155`；`modules/knowledge/store.py:421`）。
- 受控读取边界：唯一明文出口 `credentials.py:184` `read_secret()`；旧 ref 失效校验在 `:196-197`；`_ref` 为不透明串（`:204-205`）。
- 响应/审计不含明文：`_public`（`credentials.py:77-86`）只回 `fingerprint`+`credential_ref`；API 响应实证 `LEAK: False`（`t8_gating_api.py`）。

### 1.2 日志/错误体 — ✅ 通过
grep（`gateway/app/admin`）：明文变量 `secret` 仅出现于 `api_model.py:378,444,470`（读取/校验），均**不进入** `log.*` 或响应；`_mguard` 兜底日志 `api_model.py:95`、`api_import.py:74`、`api.py:119` 记录 `repr(e)`，异常类消息（`CredentialError`/`KeyStoreError`）不含密钥值。错误响应经 `_err`（`api.py:61-68`）仅回 `error`/`detail`/`request_id`。

### 1.3 URL/查询/版本信息 — ✅ 通过（1 条 Minor 观察）
- `base_url` 在校验时拒绝 `user:pass@`（`endpoint_policy.py:86-87`），故凭据不会以 userinfo 形式进入 URL。
- 版本信息 `views.version_view` 仅回构建事实（`views.py:135-138`），无密钥字段。
- **B-URL-1（观察）**：`base_url` 的 query 段未剥离/校验，若操作员手动把 token 塞进 `?key=...` 会被原样回显（非凭据库数据、非契约强制项，记为观察而非缺陷）。

### 1.4 rotate 版本与旧 ref 失效 — ✅ 通过
`credentials.py:136-153`：先生成新版本、再原子切换 `current_v`，旧版本 `retired=True` 保留；`read_secret` 对非 `current_v` 的 ref 抛 `stale credential_ref`（实测通过）。密钥未变（`_k()` 复用），轮换期间旧会话不受影响。

### 1.5 依赖缺失降级（B-CRYPTO-1，Minor）
`crypto.py:22-28,37-38`：无 `cryptography` 时 `load_or_create_key` 抛 `KeyStoreError("crypto_unavailable")` —— **绝不回退明文**（符合“honest degradation”），但该错误在 `api_model._map` 中未被显式映射（`_map` 只映射 `CredentialError`），会走 `_mguard` 兜底 500 `internal_error`。当前 venv 已装（cryptography 50.0.2，实测可用），故为潜在 Minor。

---

## 2. 鉴权与 oracle（审计重点 2）— ✅ 通过

证据 `/tmp/audit_b/t8_gating_api.py`：
```
anon 401: 401 {'error': 'unauthorized'}
wrong 401: 401 {'error': 'unauthorized'}
IDENTICAL BODY (minus request_id): True
unauthorized path also on /admin/audit anon: 401
```
- 匿名/错误 token 同一 401 体（`auth.py:111-118`）；`reason` 仅进日志、不进响应体。
- 常量时间比较：`hmac.compare_digest`（`auth.py:84`）。
- fail-closed：token store 缺失/未配置/缺 Bearer 均 401（`auth.py:128-138`）；`service.start_admin_listener` 在启用但无 token 时拒绝启动（`service.py:25-27`）。
- **B-AUTH-1（观察）**：响应体差异仅 `request_id`（`os.urandom(6).hex()`，与 token 有效性无关），不构成 oracle，判定可接受。

---

## 3. SSRF（审计重点 3）

### 3.1 ❌ **Blocker：IPv4-mapped IPv6 绕过黑名单**
`endpoint_policy.py` 的黑名单（`:31-37`）只含 IPv4 网段 + `::1/fc00::/7/fe80::/10`，**缺 `::ffff:0:0/96`**；`_is_blocked`（`:48-53`）用 `ip in net`，对 `IPv6Address` 与 `IPv4Network` 的混合比较恒为 `False`，导致 IPv4-mapped 地址不被拦截。

实测（`/tmp/audit_b/t3_ssrf.py` 追加命令）：
```
ALLOW https://[::ffff:169.254.169.254]/ -> https://[::ffff:169.254.169.254]/
ALLOW https://[::ffff:192.168.1.1]/     -> https://[::ffff:192.168.1.1]/
ALLOW https://[::ffff:10.0.0.1]/        -> https://[::ffff:10.0.0.1]/
_is_blocked(::ffff:10.0.0.1)= False
ip.is_private(::ffff:10.0.0.1)= True
ip in 10.0.0.0/8 -> False
```
- 可达性：`provider_create`/`update_provider` 直接调用 `validate_endpoint`（`registry.py:194,234`）；`probe_verified` 复用同一校验（`probe.py:86`），故**探测路径同样不拦截**；实际 TCP 连接会落到内网/元数据地址。
- 影响：违反契约 §3.3「解析后校验 IP／拒绝元数据 `169.254.169.254` 与内网」；认证操作员可借此访问 NAS/内网/云元数据。DNS 解析返回 `::ffff:x.x.x.x` 亦同样绕过。
- **修复方向**（仅建议，未改动代码）：在 `_BLOCKED_NETS` 增补 `::ffff:0:0/96`，或在 `_is_blocked` 中先用 `ipaddress.ip_address(ip).ipv4_mapped` 归一化后再比对。

### 3.2 其余 SSRF 规则 — ✅ 通过
`/tmp/audit_b/t3_ssrf.py` 全量输出要点：
- scheme：`http://`（无 allow_local）→ `scheme_must_be_https`；`ftp://` → `scheme_not_allowed`。
- userinfo：`https://user:pass@host` → `userinfo_not_allowed`。
- 元数据主机：`metadata.google.internal`/`metadata`/`instance-data` → `metadata_host_not_allowed`。
- 字面私网/回环/CGNAT/链路本地：`127/8,10/8,172.16/12,192.168/16,169.254.169.254,0.0.0.0/8,100.64/10` 全部 `private_address_blocked`；括号 IPv6 `[::1] [fc00::1] [fe80::1]` 均被拒。
- DNS 重绑定：resolver 返回私网/元数据 IP → `private_address_blocked`。
- 端口：`https://host:8443` → `port_not_allowed`；`:443` 放行。
- allow_local：`http://127.0.0.1:11434`（allow_local）放行；`http://10.0.0.1:11434`（私网非回环）被拒；回环+公网混合解析被拒（`private_address_blocked`）。
- 重定向不跟随：`probe.py:41-46` 的 `_NoRedirect` 对任意重定向抛 `HTTPError`（未做网络外呼验证，判定为静态确认）。

---

## 4. 写骨架一致性（审计重点 4）— ✅ 通过（1 条 Minor）

证据 `/tmp/audit_b/t4_skeleton.py`：
```
store lock timeout -> StoreLockTimeout: store lock busy (>300 ms): ...
expired commit -> JobExpired: preview has expired        job after: expired
commit confirm=False -> ConfirmRequired
scratch dir mode: 0o700   file imp_*.txt 0o600   file imp_*.bin 0o600
commit cancelled -> JobNotCommittable      cancel applied -> JobNotCancellable
```
- **confirm 语义**：`confirm:true`（`api.py:247-251`、`api_import.py:199`）与 `confirm == 资源 id`（dataset/provider/model delete，`api.py:509`、`api_model.py:236,308`）。
- **VALIDATE 先于查重**：`add_document` 先校验全部字段再做重复查（`store.py:605-616`）；导入先校验 `dataset`/扩展名/解析器再入队（`api_import.py:148-159`）。
- **锁超时 → 503 store_busy**：`_store_lock.py:101-104` + 映射 `api.py:89-93`、`api_model.py:52-53`。
- **DISK READ-BACK 新实例**：`_disk_knowledge/_disk_registry/_disk_creds/_disk_memory_state`（`api.py:180-217`、`api_model.py:134-148`、`api_import.py:96-101`）均以 `Class(path).load()` 重读，`_durable`（`api.py:233-236`）不一致即 500 `persist_failed`。
- **reload_if_changed 合并并发写**：每个 `exclusive()` 段首行调用（`_jsonstore.py:130-135` + 各写方法）。
- **audit 失败不变更结果**：`_audit` 吞异常（`api.py:220-230`）。
- **B-AUDIT-1（Minor）**：多数写 handler 先 `_audit(...)` 后 `_durable(...)`（如 `api_model.py:326-328`、`api.py:302-305`），故读回失败时审计仍记录 `result:"ok"`，存在误导性审计条目。

---

## 5. 版本门禁（审计重点 5）— ✅ 通过（1 条 Minor）

`/tmp/audit_b/t5_version_gate.py`（BaseJsonStore）与 `t5_knowledge_gate.py`（KnowledgeStore）：

| 构造 | 期望 | 实测 |
|---|---|---|
| 高版本 `schema_version:9`/`version:5` | 拒读写 503，不静默清空 | `state=unavailable, reason=version_ahead`；写抛 `StoreUnavailable`；**原文件字节不变** ✅ |
| 半截 JSON | corrupt→unavailable，文件不变 | `reason=corrupt`；写抛 `StoreUnavailable`；字节不变 ✅ |
| 非 dict 根 / 缺版本 | unavailable | `corrupt` / `version_missing` ✅ |
| 低已知版本 `0` | 向前兼容读、数据可见 | `state=ok, migrated_from=0`，items 可见 ✅ |
| 备份 | 600 + sha256 | `bak.json.bak.1.<ts> mode=0o600 sha_ok=True` ✅ |
| 权限异常目录（0500） | 写失败、不谎报成功 | `store file lock unavailable`（降级为进程内锁）→ `_flush` 失败 → `PersistError` ✅ |

- **B-SCHEMA-1（Minor）**：`migrate` 读回仅比对**条数**（`_jsonstore.py:205-213`、`store.py:374-383`），未比对内容哈希；契约 §4.2 要求「条数 + 哈希」。另：`_jsonstore.migrate` 返回的 `sha256` 是**备份文件**的摘要，非新文件摘要。
- 失败不覆盖原文件：`_persist` 先判 `available`、`_flush` 失败即 `load()` 丢弃内存幻影（`_jsonstore.py:169-176`；`store.py:434-441`）。

---

## 6. 导入流水线（审计重点 6）— ✅ 通过（2 条 Minor）

`/tmp/audit_b/t6_import_api.py` 要点：
```
traversal upload: 200 {'status':'preview_ready','filename':'..%2F..%2Fevil.txt','format':'txt'}
escaped files: (none)
upload '/etc/passwd.txt': 200 preview_ready   upload 'x.exe': 400 unsupported_content_type
upload 'A.PDF': 200 failed extract_failed     （大写扩展名归一化为 .pdf）
idempotent same job: True
commit: 200 readback_ok=True                  dup commit: 409 duplicate_content + existing_doc_id
dup job state: {'status':'preview_ready','error_code':'duplicate_content'}
commit no confirm: 400 confirm_required       oversize upload: 413 body_too_large
commit unknown: 404 not_found
```
- **路径穿越**：`filename` 仅作为作业元数据/`source_uri` 字符串；真实读写路径由 `job_id` 派生（`imports.py:69-84`），实测无文件外逸。绝对路径/奇怪扩展名亦不外逸。✅
- **大小上限**：`api_import.py:124-128` 逐块累计 >20MB 抛 413。✅
- **解析器不执行内容**：`parsers.py` 各分派只做字节解码/库读取，无 `eval/exec/subprocess`。✅
- **scratch 权限**：目录 0700、文件 0600（`imports.py:71-84`），实测通过。✅
- **幂等键**：同 `Idempotency-Key` 返回同一 job（`imports.py:126-129`）。✅
- **重复内容**：commit 阶段 409 `duplicate_content` 且 job 保持 `preview_ready`、`error_code=duplicate_content`（`imports.py:266-270`）。✅
- **B-IMPORT-1（Minor）**：契约 §1.3 要求「扩展名与 mime 双重校验」，实现只用扩展名；multipart 的 `Content-Type` 被采集（`api_import.py:131`）但**未校验**。
- **B-IMPORT-2（Minor）**：未知扩展名返回 `unsupported_content_type`（`api_import.py:154-156`），而契约 I1 表格中该场景为 `unsupported_format`（§0.2 两码并存，语义重叠）。
- **B-IMPORT-3（Minor）**：TTL 到期/`commit` 时判定 `expired`（`imports.py:99-112,245-249`）**不清理 scratch**，`.bin`/`.txt`（含抽取全文）残留磁盘；仅 `cancel`（`:300`）与 commit 成功（`:284`）清理。

---

## 7. 冻结链路只读（审计重点 7）— ✅ 通过

- `modules/model` 全量 grep（`write_text|write_bytes|open(|os.replace|chmod`）仅 `crypto.py`（密钥）与 `probe.py`（读网络）；**无任何写 qwen/Tina 配置、环境变量或 `/app/secrets` 的路径**（`os.environ[`/`.setdefault` 无命中）。
- `ensure_frozen_link`（`registry.py:497-555`）只镜像既有链路为只读行（`frozen:True`），仅写 `MODEL_REGISTRY_FILE`；`frozen_link_snapshot`（`:564-575`）为纯构造。
- 冻结模型被门禁拒绝：`enable_gate` 命中 `frozen_model`（实测 `t8b`「9) frozen enable: (False,'frozen_model',None)」「10) frozen bind: ...」）。

---

## 8. 门禁绕过（审计重点 8）— ✅ 通过

`/tmp/audit_b/t8_gating_api.py`（请求体伪造 `verify/verified/capabilities`）：
```
ENABLE forged:       400 {"error":"evidence_missing","detail":"adapter_present"}
TEST verified unauth: 403 {"error":"test_not_authorized", ...}
evidence after unauth test: adapter_present          （未写入）
BIND forged:         400 evidence_missing
SET-DEFAULT forged:  400 evidence_missing
```
`/tmp/audit_b/t8b_gate_paths.py`（服务端状态驱动）：
```
1) 无证据 → evidence_missing
2) 有证据+无凭据 → credential_missing
3) 有证据+有凭据 → ok
4) bind text_chat → ok
5) bind oral_realtime（缺 realtime_audio/barge_in）→ capability_mismatch missing:...
7) promote(confirm) → realtime_safe
9) frozen enable → frozen_model   11) 冻结行 frozen=True evidence=realtime_safe
```
- 门禁判定**只读服务端存储状态**（`gating.py:26-55`）；`enable/set-default/bind-scene` handler 从不读请求体中的 `verify/verified/capabilities`。✅
- evidence 仅由 `/test` 真实探测成功（`api_model.py:384-385`）、显式 `promote_realtime_safe`（`registry.py:467`）、冻结检测（`registry.py:542`）写入；grep 确认无请求体写入路径。未授权 `/test` → 403 且 `evidence_level` 保持 `adapter_present`。✅
- **B-GATE-1（观察）**：`promote_realtime_safe` 无管理路由（`api_model.py:546-572` 路由表未含），契约 §2.3 步骤 3 的"显式运维动作"当前仅内部可达；属 fail-closed，不构成越权。

---

## 9. 审计卫生（审计重点 9）— ✅ 通过

`/tmp/audit_b/t8_gating_api.py`：
```
audit has secret? False
audit sample: [{"action":"model_provider_create","subject":"prov_...","changed":[]},
               {"action":"credential_write","subject":"cred_...","changed":["configured"]}, ...]
```
- `AdminAudit`（`stores.py:45-70`）按构造脱敏：仅 `action/actor/subject/changed(粗粒度路径)/result`，**无值、无秘密、无转录**。
- `/admin/audit` 返回 `recent()`（`api.py:723-727`），上限 200、单条 `changed` ≤40。

---

## 10. Blocker / Major / Minor 汇总

**Blocker（1）**
1. **B-SSRF-1**：`::ffff:x.x.x.x`（IPv4-mapped IPv6）绕过 SSRF 黑名单，可命中内网与云元数据（`169.254.169.254`）。证据 `endpoint_policy.py:31-53,108-112`；复现 `t3_ssrf.py` 追加命令。**建议修复后重跑验收。**

**Major（0）**

**Minor（6）**
1. **B-SCHEMA-1**：迁移读回未校验内容哈希（`_jsonstore.py:205-213`、`store.py:374-383`）。
2. **B-IMPORT-1**：导入缺 mime 校验（`api_import.py:148-159`）。
3. **B-IMPORT-2**：未知扩展名错误码 `unsupported_content_type` vs 契约 I1 的 `unsupported_format`。
4. **B-IMPORT-3**：过期预览 scratch（含全文）未清理（`imports.py:99-112,245-249`）。
5. **B-AUDIT-1**：审计先于读回写入，`persist_failed` 仍记 `result:"ok"`。
6. **B-CRYPTO-1 / B-ROLLBACK-1**：`KeyStoreError` 未显式映射（走兜底 500）；`rollback` 的 `backup_id` 为未校验任意路径且不校验 sha256（`api_import.py:275-284`、`_jsonstore.py:215-229`）。

**Observation（2）**：B-AUTH-1（401 体仅 `request_id` 不同，非 oracle）、B-GATE-1（无 `realtime_safe` 提升端点）。

**无法验证（未验证 + 原因）**
- 重定向不跟随的真实网络行为：未做外部网络外呼（约束「不调用付费模型、不动验收环境」），仅静态确认 `_NoRedirect`（`probe.py:41-46`）。
- 云元数据实际可达性：仅证明策略放行，未对被拦截地址发起真实连接。

---

## 11. 复现命令索引

```bash
PY=<project-root>/gateway/.venv-v4/bin/python
$PY /tmp/audit_b/t1_creds.py          # 凭据加密/权限/旋转
$PY /tmp/audit_b/t3_ssrf.py           # SSRF 全规则（含绕过）
$PY /tmp/audit_b/t4_skeleton.py       # 锁超时/TTL/confirm/scratch 权限
$PY /tmp/audit_b/t5_version_gate.py   # BaseJsonStore 版本门禁
$PY /tmp/audit_b/t5_knowledge_gate.py # KnowledgeStore 版本门禁
$PY /tmp/audit_b/t6_import_api.py     # 导入流水线（穿越/大小/幂等/重复）
$PY /tmp/audit_b/t8_gating_api.py     # 鉴权+门禁伪造+审计卫生（aiohttp TestClient）
$PY /tmp/audit_b/t8b_gate_paths.py    # 门禁正向/冻结路径
```

> 所有 `/tmp/audit_b/` 数据均为本轮临时构造，未写入仓库真实数据目录；未提交任何改动。

---

## 12. 复验（Re-verification，2026-10-10 二次独立执行）

**触发**：主控针对 §0 的 **B-SSRF-1** Blocker 实施了修复。本节由原发现者**亲手执行**复验（不采信描述）。

**修复位置（读取确认）**：
- `modules/model/endpoint_policy.py:49-53` 新增 `_norm()`（IPv4-mapped IPv6 → 按 IPv4 判定）；`:56-61` `_is_blocked()` 先归一化；`:64-77` 新增 `peer_allowed(ip, allow_local)`；`:133` loopback 判定同样归一化。
- `modules/model/probe.py:51-67` 新增 `_peer_checked_class()`（连接后立即校验实际 peer IP，违规 `close()` + `EndpointRejected("connected_ip_blocked")`）；`:70-94` `_PeerCheckedHTTP/HTTPSHandler` + `_opener(allow_local)`；`:142` `probe_verified` 用 `_opener(bool(provider.get("allow_local")))`。

### 12.1 原始利用载荷复验 — ✅ 全部被拒、公网不误伤
命令：`<project-root>/gateway/.venv-v4/bin/python`（内联脚本，见 §11 同类）；原始输出：
```
== original exploit payloads (mapped IPv6) ==
REJECT https://[::ffff:169.254.169.254]/ -> private_address_blocked
REJECT https://[::ffff:192.168.1.1]/       -> private_address_blocked
REJECT https://[::ffff:127.0.0.1]/         -> private_address_blocked
REJECT https://[::ffff:10.0.0.1]/          -> private_address_blocked
REJECT https://[::ffff:172.16.0.1]/        -> private_address_blocked
REJECT https://[::ffff:100.64.0.1]/        -> private_address_blocked
== public mapped addr must NOT be harmed ==
ALLOW  https://[::ffff:93.184.216.34]/ -> https://[::ffff:93.184.216.34]/  peer_allowed= True
_is_blocked(::ffff:10.0.0.1)= True  norm= 10.0.0.1 ; (::ffff:93.184.216.34) blocked= False
```
**结论：B-SSRF-1 的原始 4 个载荷 + 扩展 2 个全部被拒；公网映射地址不误伤。**

### 12.2 peer check 复验（真实 socket）— ✅ 生效且不误拒
`/tmp/audit_b/t9_peer.py`（本地 127.0.0.1 HTTP 服务）原始输出：
```
allow_local=False: refused -> connected_ip_blocked
allow_local=True:  allowed status= 200
probe allow_local=False: EndpointRejected private_address_blocked   （预连接即拒）
probe allow_local=True:  {'verified': True, 'network': True, 'reason': None}
validate loopback no-allow: refused -> private_address_blocked
```
审查实现未发现新缺陷：
- **HTTPS 语境**：`_PeerCheckedHTTPSHandler.https_open` 正确透传 `context=self._context`（`probe.py:80-88`）；`_peer_checked_class` 对 `HTTPConnection`/`HTTPSConnection` 共用同一 `connect()` 覆写，机制与协议无关。
- **allow_local 传递**：`probe_verified` 按 provider 传入（`probe.py:142`），实测 allow_local=True 放行回环、False 拒绝。
- **异常路径关 socket**：拒绝时先 `self.close()` 再抛（`probe.py:64-65`）；`do_open` 仅吞 `OSError`，`EndpointRejected(ValueError)` 正常上抛，被 `probe_verified` 的 `except Exception` 转成诚实失败（不崩溃）。
- **误拒公网**：`peer_allowed(93.184.216.34)=True`（§12.1），合法公网地址不误伤。
- **时机（契约 §3.3）**：HTTP 为「TCP 连接后、请求数据前」；HTTPS 为「TCP+TLS 握手后、请求数据前」（`super().connect()` 含握手）。均满足「发送请求数据前」，未泄露 Bearer。

### 12.3 回归测试原始输出
```
cd <project-root>/gateway
.venv-v4/bin/python tests/model_v4_tests.py   -> ==== SUMMARY ==== total=62 pass=62 fail=0
.venv-v4/bin/python tests/admin_v4_api_tests.py -> ==== SUMMARY ==== total=89 pass=89 fail=0
```
新回归用例经核对确实覆盖：mapped IPv6 4 例拒绝 + 公网映射 1 例放行（`model_v4_tests.py:125-135`）、`peer_allowed` 4 断言（`:138-145`）、真实 socket peer 校验拒绝/放行 2 例（`:148-165`）。

### 12.4 新增发现（修复残量）— B-SSRF-2（Minor，低可利用性）
`_norm()` 只处理 `::ffff:0:0/96`（`ipv4_mapped`），其余**嵌入式 IPv4** 形式仍未归一化，实测仍被放行：
```
ALLOW https://[2002:0a00:0001::]/         （6to4 → 10.0.0.1）      peer=True
ALLOW https://[2001:0000:...:3fff:fdd2]/  （Teredo）
ALLOW https://[64:ff9b::10.0.0.1]/        （NAT64 知名前缀 → 10.0.0.1）   peer=True
ALLOW https://[64:ff9b::169.254.169.254]/ （NAT64 → 元数据）
ALLOW https://[::10.0.0.1]/               （IPv4-compatible，已废弃）
```
- **可利用性判断：低**。这些形式需特定路由才连通：6to4/Teredo/`::a.b.c.d`（IPv4-compatible）在现代主机通常无路由，连接失败；NAT64 `64:ff9b::/96` 仅在 NAT64/DNS64 环境（IPv6-only 网络）经网关翻译，且知名前缀通常只映射全局 IPv4，不保证到达私网。
- **建议**（不强制）：对 `2002::/16`（`sixtofour`）、`2001::/32`（Teredo）、`64:ff9b::/96`、`::/96` 一并归一化/拦截，或将这些前缀直接加入黑名单。此外建议在 `peer_allowed` 中对带 scope 的 link-local（`fe80::1%en0`）保持拒绝（实测已 fail-closed，返回 False）。
- 已顺手确认 `peer_allowed("fe80::1%en0")=False`、`peer_allowed("fe80::1")=False`（fail-closed，良好）。

### 12.5 复验结论与最终计数
- **B-SSRF-1 Blocker：已关闭**（原始载荷全拒、公网不误伤、peer 实连校验生效、两套回归全绿）。
- 新增 **B-SSRF-2（Minor，低可利用性）**：其余嵌入式 IPv6 前缀未归一化。
- 最终计数：**Blocker 0、Major 0、Minor 7（原 6 + 新增 B-SSRF-2）、Observation 3（B-AUTH-1、B-GATE-1、HTTPS 握手先于 peer 校验但不含请求数据）**。
- 复验命令清单：`/tmp/audit_b/t9_peer.py`（peer 校验）+ §12.1/§12.4 内联命令 + §12.3 两套测试；未改动报告以外任何文件，未触碰 8119/8123，未调用付费模型。

---

## 13. 复验二（B-SSRF-2 修复，2026-10-10 二次独立执行）

**触发**：主控针对 §12.4 的 **B-SSRF-2** 追加修复。

**修复位置（读取确认）**：`modules/model/endpoint_policy.py:49` 新增 `_NAT64_NETS`（`64:ff9b::/96`、`64:ff9b:1::/48`）；`:52-70` 新增 `_embedded_v4s(a)`（mapped / `sixtofour` / `teredo` 的 (server,client) / NAT64 / 弃用 compatible，排除 `::`与`::1`）；`:81-86` `_is_blocked` 与 `:89-102` `peer_allowed` 改用 `_embedded_v4s`；`_norm`（`:73-78`）仅保留用于 loopback 例外。

### 13.1 指定载荷复验 — ✅ 目标 4 类全部关闭、公网不误伤
原始输出：
```
== requested payloads ==
REJECT https://[2002:7f00:1::]/v1                              -> private_address_blocked   （6to4→127.0.0.1）
REJECT https://[64:ff9b::a00:1]/v1                             -> private_address_blocked   （NAT64→10.0.0.1）
REJECT https://[2001:0:4136:e378:8000:63bf:f5ff:fffe]/v1       -> private_address_blocked   （Teredo client→10.0.0.1）
REJECT https://[::127.0.0.1]/v1                                -> private_address_blocked   （compatible）
== public NAT64 / mapped must NOT be harmed ==
ALLOW  https://[64:ff9b::5db8:d822]/v1  -> …（NAT64→93.184.216.34）  ✅
ALLOW  https://[::ffff:93.184.216.34]/v1 -> …                        ✅
```
抽取核对：`2002:7f00:1::→[127.0.0.1]`、`64:ff9b::a00:1→[10.0.0.1]`、Teredo`→[65.54.227.120, 10.0.0.1]`（server+client 双判定）、`::127.0.0.1→[127.0.0.1]`。回归：`169.254.169.254`/`10.0.0.1`/`[::ffff:169.254.169.254]` 仍拒，`api.openai.com`、合法全局 v6（`2606:4700::1111`、`2400:3200::1`、`2a00:1450:4001::200e`）均放行，无误伤；`fd00::1`（ULA）正确拦截。**B-SSRF-2 关闭。**

### 13.2 `_embedded_v4s` 误判/漏判审查
- 正确：Teredo 元组方向为 Python `(server, client)`，本用例 client=10.0.0.1 被捕获；`::`/`::1` 排除正确（`::1` 另由 `::1/128` 网络拦截）；NAT64 `/96` 与实测 `/48` 载荷均按低 32 位正确提取。
- **新增残留（B-SSRF-3，Minor，低可利用性）**：RFC6052 **SIIT「IPv4-translatable」前缀 `::ffff:0:0:0/96`** 未归一化，实测仍绕过：
```
ALLOW https://[::ffff:0:10.0.0.1]/v1          （应→10.0.0.1）
ALLOW https://[::ffff:0:169.254.169.254]/v1   （应→元数据）
_embedded_v4s(::ffff:0:10.0.0.1) = ['::ffff:0:a00:1']  blocked=False
```
  可利用性：**低**——仅 SIIT/NAT46/464XLAT 环境可映射到内网，现代主机通常无路由。建议：在 `_embedded_v4s` 增补 `::ffff:0:0:0/96`（低 32 位取 IPv4）。
- **观察（非漏洞）**：NAT64 `/48` 用 `int(a) & 0xFFFFFFFF` 提取属近似（真实 RFC6052 /48 为分段嵌入），对合法 `/48` 地址可能误判为 `0.0.0.0/8` 而**多拦**（fail-closed，安全侧）；`::`（未指定）`peer_allowed=True`（不可路由，风险可忽略）。

### 13.3 回归测试原始输出
```
cd <project-root>/gateway
.venv-v4/bin/python tests/model_v4_tests.py    -> ==== SUMMARY ==== total=67 pass=67 fail=0   （+5 例嵌入形式）
.venv-v4/bin/python tests/admin_v4_api_tests.py -> ==== SUMMARY ==== total=89 pass=89 fail=0
```
新用例确实覆盖 4 类拒绝 + 公网 NAT64 放行（`model_v4_tests.py:138-148`）。

### 13.4 复验二结论与最终计数
- **B-SSRF-2：已关闭**（6to4 / NAT64(/96,/48) / Teredo / IPv4-compatible 全部被拒，公网不误伤）。
- 新增 **B-SSRF-3（Minor，低可利用性）**：`::ffff:0:0:0/96`（SIIT IPv4-translatable）未归一化。
- **最终计数：Blocker 0、Major 0、Minor 7（B-SCHEMA-1、B-IMPORT-1/2/3、B-AUDIT-1、B-CRYPTO-1/B-ROLLBACK-1、B-SSRF-3）、Observation 4（B-AUTH-1、B-GATE-1、HTTPS 握手先于 peer 校验但不含请求数据、NAT64/48 掩码近似与 `::`）。**
- 复验命令：§13.1/§13.2 内联脚本（venv `<project-root>/gateway/.venv-v4/bin/python`）+ §13.3 两套测试；未改动报告以外任何文件，未触碰 8119/8123，未调用付费模型。