# 学生客户端 ↔ 本机网关：`/cls/knowledge/*` 接口契约（v1）

- 文档类型：**接口契约**（CONTRACT_FIX_01A 一.2 · `DELIVERY GATE 02` 一.2）
- 消费者：学生课堂客户端（`client/src/classroom/classroom_api.py`）
- 提供者：本机环回学生网关（**独立最小权限子应用**，见 `security/D1_MINIMAL_PRIVILEGE_IMPORT_ACCESS.md §3.2.1 / §3.8`）
- 状态：**契约已冻结；服务端实现待独立安全复核通过后开放**（`STUDENT_WHITELIST_SERVICE = NOT_OPEN`）
- 生成：总控工程 Agent（TC）· `2026-10-12`

---

## 1. 三条不可协商的边界

| # | 边界 | 含义 |
|---|---|---|
| **B-1** | **路径前缀必须是 `/cls/`** | 学生客户端**只**知道 `/cls/*`。`/admin/knowledge/*` 是**既有内部接口**（网关/管理面复用），**不向学生开放**，学生客户端中**不存在**任何 `/admin/` 路径常量。 |
| **B-2** | **唯一鉴权头 `X-Classroom-Session`** | 学生会话能力令牌。**绝不**携带 `Authorization` / 管理员 Bearer。客户端代码中**不存在** Authorization 分支（由 `CLASSROOM_API I04a` 断言）。 |
| **B-3** | **环回 only** | base_url 必须为 `127.0.0.1`/`localhost`/`::1`；**不跟随**任何指向非环回地址的重定向；绕过系统代理（`CLASSROOM_API I01/I08–I13`）。 |

**路由等价关系**：`/cls/knowledge/X` 与内部 `/admin/knowledge/X` 由**同一处理函数**实现（`gateway/app/admin/api_import.py`），
但学生侧**独立挂载**了一份**仅含下表 7 条白名单**的子应用——越权路由**根本不存在**（不是"过滤掉"）。

---

## 2. 白名单（**恰好 7 条**）

| # | 方法 | 路径（精确） | 用途 | 幂等键 | 客户端方法 |
|---|---|---|---|---|---|
| 1 | `GET` | `/cls/health` | 存活探测（**非**知识库面；本机只读） | — | `health()` |
| 2 | `GET` | `/cls/knowledge/parsers` | 解析能力表（驱动"暂不支持"的诚实 UI） | — | `parsers()` |
| 3 | `POST` | `/cls/knowledge/import` | 上传教材（`multipart/form-data`）→ 建导入作业 | `Idempotency-Key`(头) | `start_import(...)` |
| 4 | `GET` | `/cls/knowledge/import` | 作业列表（本机当前批次） | — | `list_imports()` |
| 5 | `GET` | `/cls/knowledge/import/{job_id}` | 作业详情/预览（含 8 态机状态） | — | `get_import(job_id)` |
| 6 | `POST` | `/cls/knowledge/import/{job_id}/commit` | 确认提交（**必须** `{"confirm": true}`） | — | `commit_import(job_id)` |
| 7 | `POST` | `/cls/knowledge/import/{job_id}/cancel` | 取消 | — | `cancel_import(job_id)` |
| 8 | `POST` | `/cls/knowledge/import/{job_id}/retry` | 重试 | — | `retry_import(job_id)` |

> 说明：`/cls/health` 属**存活面**（无知识库写、无敏感信息），与 D1 §3.8.1 的 7 条知识库白名单并列计入，故本表共 8 行 = 1 条存活 + 7 条知识库面。

**学生侧显式不提供**（结构性不存在）：`/cls/knowledge/migrate`、`/cls/knowledge/rollback`、任何 `dataset` 破坏性写（create/rename/delete/enable）、任何 `store/*` 维护、任何批量删除、任何管理型导出。

---

## 3. 请求/响应契约

### 3.1 通用

- 请求头：`X-Classroom-Session: <token>`（必填）、`Accept: application/json`；JSON 体时 `Content-Type: application/json`。
- 成功：HTTP 2xx + JSON 对象（空体视为 `{}`）。
- 失败：HTTP 4xx/5xx + `{"error": "<code>", "detail": "<中文说明>"}`。

### 3.2 `GET /cls/health`
```json
200 {"ok": true, "version": "v2"}
```

### 3.3 `GET /cls/knowledge/parsers`
```json
200 {"available": true,
     "parsers": [{"ext": ".pdf",  "available": true},
                 {"ext": ".epub", "available": true},
                 {"ext": ".png",  "available": false, "reason": "OCR_DEFERRED"}]}
```
> `available=false` 必须**照实**驱动 UI 的「暂不支持」文案（**禁止**前端硬编码"支持"）。

### 3.4 `POST /cls/knowledge/import`（multipart）
字段：`file`(必填，二进制) · `dataset_id`(必填) · `title?` · `preview_chars?`
```json
200 {"available": true, "job_id": "job_…", "status": "parsed", "format": "pdf"}
```
- 单文件 ≤ 20 MB；超限 → `413 body_too_large`。
- **上传绝不写知识库**，只有 `commit` 才落盘。

### 3.5 `GET /cls/knowledge/import` / `…/{job_id}`
```json
200 {"available": true, "jobs": [ … ]}            // 列表
200 {"available": true, "job_id": "…", "status": "preview_ready",
     "preview": "…", "source_type": "pdf", "extracted_chars": 12345}   // 详情
```
**状态机（8 态）**：`uploaded → parsed → preview_ready → committed` ／ `cancelled` ／ `expired` ／ `failed`（＋重试回边）。

**硬语义（客户端**不得**简化）**：
1. 预览 **TTL 30 min**，过期 → `410 job_expired`；
2. 内容重复 → `409 duplicate_content` **且携带 `existing_doc_id`**（UI 须提供「查看已有记录」，不得只报错）；
3. `cancel`/`retry` 在非法态是**合法拒绝**（`job_not_cancellable`/`job_not_retryable`），UI 须如实呈现。

### 3.6 `POST …/{job_id}/commit`
请求体 **必须** `{"confirm": true}`。
```json
200 {"available": true, "readback_ok": true,
     "document": {"id": "doc_…", "content_hash": "<裸64hex>", "chunk_count": 42, "status": "ready"},
     "job": { … }}
```
- **服务端从磁盘回读**，仅当 `readback_ok=true` 才可向用户报「成功」。
- `document.id` / `document.content_hash` 即链路 B 的 `source_doc_id` / `source_doc_hash` 来源。
- ⚠️ `content_hash` 为 **裸 64hex**（无 `sha256:` 前缀）——见 `CLASSROOM_V2_SCHEMA_V1_ERRATA.md`；客户端与校验器必须接受该形式。

### 3.7 `POST …/{job_id}/cancel` ｜ `…/{job_id}/retry`
```json
200 {"available": true, "status": "cancelled"}
```

### 3.8 错误码（客户端须映射为中文，不得只显 SQL/英文）

| code | HTTP | 中文（示例） |
|---|---|---|
| `body_too_large` | 413 | 文件超过 20 MB 上限 |
| `unsupported_format` | 415 | 该格式暂不支持（见能力表） |
| `scanned_pdf_no_text` | 422 | 扫描件无可提取文本（需 OCR，当前不支持） |
| `duplicate_content` | 409 | 内容重复，已有记录：`existing_doc_id` |
| `job_expired` | 410 | 预览已过期（30 分钟），请重新上传 |
| `job_not_cancellable` / `job_not_retryable` | 409 | 当前状态不允许该操作 |
| `forbidden_route` | 403 | 该操作不在学生模式可用范围内 |
| `session_invalid` | 401 | 学生会话无效或已过期 |
| `redirect_blocked` | 3xx | 网关返回了重定向，已拒绝跟随（客户端侧生成） |

---

## 4. 客户端实现对齐（实测）

| 契约条目 | 客户端 | 状态 |
|---|---|---|
| 仅 `/cls/*` | `classroom_api.py` 内无 `/admin/` 常量 | ✅ |
| 唯一会话头 | `_headers()` 仅 `X-Classroom-Session` | ✅ `I04a/I04b` |
| 环回 + 无外跳 | `_is_loopback` + `_LoopbackOnlyRedirectHandler` + 终址复核 | ✅ `I01/I08–I13` |
| `commit` 带 `confirm` | `commit_import()` 发 `{"confirm": true}` | ✅ `I07` |
| 能力表驱动降级 | `parsers()` 返回 `available` | ✅ `I03a` |
| 上传（multipart） | `start_import()` | ✅ `I14a–c`（对齐测试） |
| 错误码→中文 | `ClassroomApiError.code` 透出；UI 映射 | ⚠️ UI 层（Agent B）落地 |

---

## 5. 开放条件（**硬门禁**）

> **独立安全审核通过前，本白名单服务与最终发布 API 一律不开放。**
> 在未开放期间，客户端必须显示**真实不可用原因**（"本机解析服务尚未开放：等待独立安全复核"），
> **禁止**硬编码成功数据、禁止把 Mock 结果伪装成真实解析结果。
