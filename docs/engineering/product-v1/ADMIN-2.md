# ADMIN-2 CONTROL PLANE

> **【历史快照 · 2026-10-13】** 本文为 PRODUCT V1 Final Completion Run 的 Phase 4 ADMIN-2 Control Plane 分期报告；
> 有效结论已完整继承至权威主文档 `PDCA-BOARD.md`（对应阶段行与 Phase log，TASK_ID=PRODUCT-V1）。
> 本文逐字保留，不再单独维护。

Phase 4 of the Product V1 final completion run.  Status: **PASS** (ADMIN2_TESTS 66/66,
ADMIN_SECURITY_TESTS 29/29, ADMIN1_TESTS 80/80 unchanged).

## Model

ADMIN-1's six read-only routes stay byte-compatible.  ADMIN-2 is an **additive mount**:
`create_admin_app(stores=…)` mounts the control-plane API; without the store bundle the app
is exactly the ADMIN-1 surface (`admin_route_table()` unchanged for that case, proven by the
untouched ADMIN1_TESTS).  Every write follows:

**AUTH → VALIDATE → PREVIEW (where meaningful) → EXPLICIT APPLY (confirm token) → READ-BACK
(re-read from the store) → AUDIT** — no silent mutation anywhere.

## Surface (34 routes total; 28 new)

| section | routes |
|---|---|
| PERSONA/POLICY | `GET active/versions/audit`, `POST preview/apply/rollback` — apply/rollback require `confirm: true`; apply returns `readback_ok` + active version; rollback restores a history version as a new version (audited in the policy store) |
| MEMORY | `GET items/search/item/{id}/diagnostics`, `POST edit/delete/clear-category` — delete needs `confirm: true`, clear-category needs `confirm == entity`; edits are boundary-validated (progress/secret values → 400) |
| KNOWLEDGE | `GET datasets/dataset/{id}/preview/document/{id}/document/{id}/chunks/diagnostics`, `POST dataset/create/rename/enable/delete`, `document/add/delete/rebuild`, `search` — deletes need confirmation tokens; duplicate → 409 + existing id; malformed → 400 |
| WORKBENCH | `GET status/current/progress/reviews` — **no write route exists** (all four are GET-only; unconfigured degrades to `available:false`) |
| BEHAVIOR | `GET active/routing` — policy version, taxonomies, aggregated routing counters and bounded per-session routing metadata (allowlist; the link's `recent_word` never leaves it, no transcripts) |
| REALTIME | ADMIN-1 six routes retained unchanged |
| AUDIT | `GET /admin/audit` — bounded in-memory, sanitized action log (ts/action/actor/subject/changed-paths/result; no values, no secrets, no transcripts) |

**Not added:** `/admin/diag/reset` (proven absent by tests).

## Security

Same bearer model as ADMIN-1 (middleware guards every `/admin/*` path; `hmac.compare_digest`;
token file preferred; anonymous vs invalid token → identical 401 body, no oracle).  Extra
hardening: 64 KB body cap (413), invalid/non-object JSON → 400, bad query ints → 400,
coded sanitized errors (no store internals, no paths, no values), fail-closed 503s when a
store is not configured, 600-mode store files, and token/value/transcript non-leakage checks
across bodies and logs.

## Live propagation (control plane → sessions)

Policy applies are picked up by live sessions at the next **safe boundary**
(`_maybe_reload_stores` → `reload_if_changed` → hot apply via the instructions-only
`session.update`).  Memory/knowledge stores refresh by file signature at the next turn
(`memory_reloads` / `knowledge_reloads` counters).  Nothing in this phase touches the audio
plane, model, voice, VAD or formats.

## Wiring

`main.py` builds `AdminStores(policy_file, memory_file, knowledge_file, workbench_url)` from
the same runtime config only when `ADMIN_ENABLED=1`, and passes it to
`start_admin_listener(..., stores=…)`.  `AdminStores` construction is fail-soft (a broken
store degrades to `503 not_configured`, never a crash).

## Tests

* `gateway/tests/admin2_tests.py` → **ADMIN2_TESTS 66/66** — every route, both happy and
  refusal paths (confirmations, boundary/secret rejection, duplicates, malformed, unknown
  ids), read-backs, audit content, workbench GET-only against a fake workbench (only GETs
  observed), behavior routing with a fake session, route-table hygiene.
* `gateway/tests/admin_security_tests.py` → **ADMIN_SECURITY_TESTS 29/29** — auth on all 34
  routes, no-oracle 401s, input hardening, leak scans (bodies + logs), sanitized 500→4xx
  mapping, route table equality, fail-closed, permissions, constant-time compare.
* Regression: ADMIN1 80/80, MEMORY_V1 54/54, MEMORY1 19/19, KNOWLEDGE1 69/69, BEHAVIOR1
  111/111, VOCAB 79/79, PERSONA_POLICY 59/59, WORKBENCH1 25/25, MVP_INTEGRATION 28/28.

## Rollback

`ADMIN_ENABLED=0` (default) starts nothing; without stores the ADMIN-2 routes are absent;
phase commit revertible; run rollback tag `product-v1-pre-run` + bundle.