# UNIFIED ADMIN UI (Chinese-first)

> **【历史快照 · 2026-10-13】** 本文为 PRODUCT V1 Final Completion Run 的 Phase 5 Unified Admin UI 分期报告；
> 有效结论已完整继承至权威主文档 `PDCA-BOARD.md`（对应阶段行与 Phase log，TASK_ID=PRODUCT-V1）。
> 本文逐字保留，不再单独维护。

Phase 5 of the Product V1 final completion run.  Status: **PASS** (ADMIN_UI_TESTS 23/23,
ADMIN2 67/67, ADMIN_SECURITY 29/29, ADMIN1 83/83).

## What was built

One coherent Chinese-first operator interface served by the admin listener from the static
allowlist (`admin/index.html` / `admin/app.js` / `admin/styles.css`) — zero external
dependencies, no CDN, LAN-only, desktop-responsive (CSS grid + media query + viewport meta).

Navigation (8 sections): 仪表盘 · 实时状态 · 诊断 · 角色与教学 · 记忆 · 知识库 ·
课程进度 · 意图 / 路由诊断.

| section | contents |
|---|---|
| 仪表盘 | gateway health (status/model/voice read-only), policy version, memory counts, knowledge counts, workbench state, explicit degradation warnings |
| 实时状态 | live sessions table + process-lifetime metrics incl. the three R-1f closure residuals |
| 诊断 | diag-summary, telemetry honesty line, memory boundary, knowledge health, workbench health, policy/routing health |
| 角色与教学 | structured form over the policy fields + language select, 预览 (validation errors / changed keys / rendered-instruction preview), 应用 (confirm dialog → apply → read-back), 版本历史 with per-version 回滚 (confirm), advanced raw-JSON editor (optional, for power users) |
| 记忆 | category summary, filter + search, per-item 编辑/删除 (confirm), per-category 清空 (confirm), provenance/confidence columns, diagnostics; explicit note "课程进度由 Workbench 管理，不存储在记忆中。" |
| 知识库 | dataset create/enable/disable/rename/delete (预览删除 shows doc/chunk counts + token), document add (text/markdown/pdf_text, source uri), per-document 重建索引/删除 (confirm), retrieval tester with sources/scores, diagnostics |
| 课程进度 | 只读 badge; status (fresh/stale/age/rev), current lesson, progress, reviews — no write path exists |
| 意图 / 路由诊断 | behavior policy summary, aggregated routing counters, per-session routing metadata (no raw transcripts) |

Requirements held: **no raw JSON required for common actions** (forms + prompts; raw JSON
only as an optional advanced/debug affordance), every destructive action behind
`window.confirm`, token in `sessionStorage` only (never in URLs, cleared on save/clear),
`request_id` surfaced on errors, and the eight UI states (AUTH_REQUIRED, AUTH_FAILED,
UPSTREAM_UNAVAILABLE, HEALTHY, DEGRADED, ERROR, EMPTY, LOADING).

## Small backend additions this phase required

* `GET /admin/knowledge/dataset/{ds_id}/documents` (+ `KnowledgeStore.list_documents`) so
  the 知识库 page can list document metadata (never raw text);
* `qwen_model` / `qwen_voice` allowlisted into `GET /admin/health` (dashboard read-only
  display); both come from the gateway's own qwen config.

## Tests

* `gateway/tests/admin_ui_tests.py` → **ADMIN_UI_TESTS 23/23**: every endpoint the JS calls
  must exist in the mounted route table (template/concat-normalized contract scan); GET/POST
  only; each destructive endpoint preceded by a confirmation dialog; preview/apply/rollback
  wiring; token hygiene; zero external URLs; Chinese nav/boundary notes/read-only badge;
  responsive markers; shell served unauthenticated with no data; content types; an
  integration smoke that every GET endpoint the UI uses answers 200 with stores wired.
* ADMIN1_TESTS UI section rewritten to the new reality (83 checks total): old
  "exactly six endpoints / GET-only / no write controls" phase-scoped assertions were
  replaced by contract + confirmation + Chinese-first checks while keeping every
  security invariant (sessionStorage-only, no URL tokens, no data in the shell, request id).
* ADMIN2 67/67 (+documents listing), ADMIN_SECURITY 29/29 (route table grew additively;
  suite is table-driven), KNOWLEDGE1 69/69.

## Rollback

Static assets are versioned in git; the listener serves them from `ADMIN_UI_DIR`
defaulting to the repo `admin/` directory.  Reverting the phase commit restores the
previous console; API compatibility makes either UI valid against the same backend.