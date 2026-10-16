# PRODUCT V1 — GLOBAL PDCA BOARD

> **TASK_ID = PRODUCT-V1 ｜ 本文件为 Product V1 Final Completion Run 的权威主文档（LIVING DOCUMENT）**
> 依 ONE_TASK=ONE_LIVING_DOCUMENT 制度（PROJECT-DOC-MERGE-01 第二阶段批 1 收敛）：本板已含 12 阶段全历史
> （总表+Phase log 逐阶段 PLAN/DO/CHECK/ACT），为该任务的单一事实源。链内文件角色见文末「链收敛」节。

Run: PRODUCT V1 FINAL COMPLETION RUN (directive `PRODUCT-V1-RUN-DIRECTIVE.md`, 1396 lines).
Lead = only product-code writer. Reviewers A–F read-only; raw reports in `reviews/agent-<A-F>.md`.
START_COMMIT = `2fd8d4f`. Rollback tag `product-v1-pre-run` + bundle `admin0-backups/product-v1-pre-run.bundle`.

Status values: PLANNED / IN_PROGRESS / CHECKING / REWORK / PASS / DEFERRED_BY_AUTHORIZATION.

| Phase | PLAN | DO | CHECK | ACT | BLOCKERS | MAJORS | MINORS | TESTS | REVIEWER | STATUS |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 Baseline / rollback / PDCA init | done (`BASELINE.md`) | done (tag+bundle+manifest+board) | hygiene PASS, worktree clean | none needed | 0 | 0 | 0 | static/read-only | — | PASS (788da2a) |
| 1 Knowledge V1 | done (below) | done (store+router+link+tests+doc) | KNOWLEDGE1_TESTS 69/69; no drift in 6 accepted suites | probe noise-guard added (min_score 2); workbench fixture made date-relative | 0 | 0 | 0 | KNOWLEDGE1_TESTS | — | PASS (599609c) |
| 2 Memory V1 | done (below) | done (store v2+link+tests+doc) | MEMORY_V1 54/54 ×3; no drift | storage-key reload bug fixed; v1 migration | 0 | 0 | 0 | MEMORY_V1_TESTS | — | PASS (2e9fd20) |
| 3 Persona / Teaching Policy V1 | done (below) | done (policy module+renderer refactor+link+tests+doc) | PERSONA_POLICY 59/59; no drift in 8 suites | level-map merge semantics pinned; dead branch removed | 0 | 0 | 0 | PERSONA_POLICY_TESTS | — | PASS (b29edd9) |
| 4 ADMIN-2 control plane | done (below) | done (admin api/stores/registry+tests+doc) | ADMIN2 66/66 + ADMIN_SECURITY 29/29; ADMIN1 80/80 unchanged; 8 suites no drift | weakref fixture fix; workbench lazy-coro fix; confidence type guard | 0 | 0 | 0 | ADMIN2_TESTS + ADMIN_SECURITY_TESTS | — | PASS (2507a04) |
| 5 Unified Admin UI (Chinese-first) | done (below) | done (8-section console + docs endpoint + health model/voice + tests) | ADMIN_UI 23/23; ADMIN1 83/83 (UI section evolved); ADMIN2 67/67; SEC 29/29 | scanner prefix normalization; UI-section test evolution | 0 | 0 | 0 | ADMIN_UI_TESTS + UI contracts | — | PASS (84cd72a) |
| 6 Cross-module integration | done (below) | done (PV1 integration suite + reload-order fix) | PRODUCT_V1_INTEGRATION 33/33; 6-suite regression green | stale-retrieval-before-reload defect fixed | 0 | 0 | 0 | PRODUCT_V1_INTEGRATION | — | PASS (1d8220d) |
| 7 Master test matrix | done (below) | done (21 suites + boundary suite) | 21 suites run; 0 blockers; R-1f env sentinel baseline-proven | boundary suite added; r1f flake root-caused at baseline | 0 | 0 | 0 | full 18-suite matrix | — | PASS (52facaa) |
| 8 Multi-agent final review A–F | done | reviewers A–F ran; MAJORs repaired and re-checked | A PASS; B PASS; C PASS (re-check @90b8ab4); D PASS (re-check 2 @2cf4211); E PASS; F PASS | memory load-seam; notes→policy; block bound; tmp names; grammar note; vocab value-shape | 0 | 0 | 3 | reviewer re-runs until 6× PASS | A–F | PASS (2cf4211 + closing commit) |
| 9 NAS Product-V1 test sidecar | done (`PRODUCT-V1-DEPLOYMENT.md`) | done (isolated sidecar 28310-28312, own compose project; probe) | PRODUCT_V1_STRUCTURAL_PROBE 65/65 (also 65/65 locally pre-flight); isolation evidence recorded | MAJOR found + fixed: admin memory reads served a stale view vs conversation-time writes (`_fresh` reload in the four memory read handlers + 2 deterministic guards); two probe bugs fixed | 0 | 0 | 1 | structural probe (no real Qwen) | — | PASS |
| 10 Mac client arm | done | done (OTA-only 1-line diff, backup + hashes) | OTA → `ws://192.0.2.1:28310/…`; hello-only WS from the Mac OK; sidecar `qwen_sessions` still 0 | none needed | 0 | 0 | 0 | before/after hash + OTA/WS result | — | PASS |
| 11 Final human acceptance script | done | done (`FINAL-HUMAN-ACCEPTANCE.md`, Chinese, 25 items) | prepared only — NOT RUN | none needed | 0 | 0 | 0 | script review | — | PASS |
| 12 Final PDCA closeout | done | done (global CHECK/ACT, full matrix, commit) | all phases PASS; matrix green; primary untouched; Workbench writes 0; budget respected; rollback available; sidecar healthy; client armed; script prepared | none required | 0 | 0 | 4 | full matrix + client suites | — | PASS |

## Phase log

### Phase 0 — Baseline / Rollback / PDCA init

- PLAN: capture baseline facts (git, NAS containers, Mac OTA), define rollback, create manifest and this board. Acceptance: repository facts recorded, rollback artifacts verified, hygiene checks PASS.
- DO: tag `product-v1-pre-run` (`e8af29d…`), bundle `admin0-backups/product-v1-pre-run.bundle` (sha256 `fec3096d…`, mode 600), `BASELINE.md`, this board.
- CHECK: worktree clean; no secrets/transcripts/learner data tracked; gitignore covers secrets/backups/logs/evidence; NAS containers all `restarts=0` (primary realtime + Workbench untouched); Mac OTA = MVP sidecar :28211.
- ACT: none required.
- BLOCKERS = 0, MAJORS = 0, MINORS = 0. TESTS: static/read-only. STATUS: PASS (commit `788da2a`).

### Phase 1 — Knowledge V1

- PLAN: product-owned store at `modules/knowledge/store.py` (JSON file, closed schema, atomic 600 writes, `threading.RLock`). Stable IDs `ds_`/`doc_`/`chk_`. Data model dataset/document/chunk + tags/status/content hash/provenance/source URI. Ops: dataset create/rename/enable/disable/list/delete-with-preview+confirm; document add/inspect/delete/rebuild-chunks/list-chunks; search/retrieve; diagnostics; source attribution. Ingestion: plain text / Markdown / PDF-derived text via optional external `pdftotext` path (no OCR). Retrieval: deterministic token-overlap scoring (latin words + CJK bigrams), top-k ≤ 5, `MIN_SCORE` filter, disabled datasets excluded, bounded injection `MAX_INJECTION_CHARS`, provenance per hit, honest empty result. Conversation integration: router emits `knowledge_query` (explicit 知识库/资料 asks, or implicit question probe); the gateway link retrieves locally (bounded) and injects an ephemeral instruction block for that turn only — explicit miss renders an honest "no entry" line, implicit miss injects nothing. Acceptance: KNOWLEDGE1_TESTS covers ingestion/chunking/search/top-k/empty/duplicate/malformed/disable/delete/provenance/context bound/privacy/concurrency + router decision + link render; `docs/engineering/product-v1/KNOWLEDGE-V1.md` produced. Rollback: phase commit revertable; `KNOWLEDGE_FILE=""` disables the feature entirely (default). Frozen surfaces untouched: no audio/realtime edits; `ws.py`/`qwen.py` unchanged.
- DO: implemented `modules/knowledge/store.py` (store + chunker + search + bounded renderer + `extract_pdf_text`); router: `QUERY_KNOWLEDGE` temp intent + implicit `knowledge_query` probe (`is_question_shaped`); link: `KnowledgeStore` wiring (`KNOWLEDGE_FILE`), bounded retrieval (`KB_TOP_K=3`, `KB_PROBE_MIN_SCORE=2`), ephemeral `knowledge_block` injection, stats; `main.py` config; `knowledge1_tests.py` (69 checks); module README + `KNOWLEDGE-V1.md`.
- CHECK: KNOWLEDGE1_TESTS **69/69 PASS** (after fixing 5 initial assertion bugs of mine and adding the probe noise-guard — three first-run failures were real design findings: cross-dataset duplicate copy can outrank by chunk-id order (accepted, test relaxed to `any`), and a single CJK bigram ("时间") was enough for an implicit probe → raised to `min_score=2` for implicit probes). No drift: BEHAVIOR1 111/111, VOCAB_ACCURACY 79/79, MEMORY1 19/19, WORKBENCH1 25/25, MVP_INTEGRATION 28/28, ADMIN1 80/80, R-1F 179/180 (known env sentinel). Workbench fixture W2c/W3 failed for the *date* reason only (`2026-10-08` had become “today”); fixture made date-relative (test-side change, product behavior untouched).
- ACT: fixes applied during the phase (probe threshold; fixture dates); no BLOCKER/MAJOR remaining.
- BLOCKERS = 0, MAJORS = 0, MINORS = 0. STATUS: PASS (599609c).

### Phase 2 — Memory V1

- PLAN: upgrade `modules/memory/store.py` to the directive's V1 data model — closed entity set `preference/profile_fact/vocab_item/habit/continuity`; per-item `id/user_id/entity_type/key/value/source/confidence/created_at/updated_at/expires_at`; operations save/list/search/inspect/edit/delete/forget/forget-by-category/category-summary; per-user partition, atomic 600 writes, fail-soft corruption, caps; hard boundary for progress/secret/audio/transcript; bounded + relevance-filtered conversational injection (`context` + `render_memory_block`); v1 file migration. Existing APIs (`save_preference/note_weak_word/preferences/vocab_items/items/forget/assert_no_progress_keys`) preserved for the accepted Behavior-1/Workbench-1 contracts.
- DO: rewrote the store (schema v2); gateway link: `_memory_block` (per-turn, relevance-filtered, `MEM_CONTEXT_LIMIT=4`), ephemeral injection via `render_instructions(memory_block=…)`, stats `memory_injections`; `memory_v1_tests.py` (54 checks); `MEMORY-V1.md`.
- CHECK: MEMORY_V1_TESTS **54/54 PASS ×3 consecutive runs**; no drift — MEMORY1 19/19, BEHAVIOR1 111/111, KNOWLEDGE1 69/69, MVP_INTEGRATION 28/28, VOCAB_ACCURACY 79/79. One real bug found and fixed by the new suite: on reload, items were re-keyed by the human key, losing the `vocab:` storage-key scheme (`vocab_items()` empty after restart) — `load()` now re-derives the storage key; `from_json` migrates v1 keys.
- ACT: bug fix + v1-tests schema-field rename (`entity`→`entity_type`, matching the directive) applied; no BLOCKER/MAJOR remaining.
- BLOCKERS = 0, MAJORS = 0, MINORS = 0. STATUS: PASS (pending commit).

### Phase 3 — Persona / Teaching Policy V1

- PLAN: one authoritative structured policy (`modules/policy/persona.py`): closed schema (persona/language/teaching/activities/scenarios/limits), validation with bounds + closed keys, deep-merge-over-defaults for partial candidates, ONE renderer source (all prompt tables moved out of `modules/intent/behavior.py` verbatim), bounded rendered instruction (`max_instruction_chars`), versioned store (preview/apply/rollback/versions/audit, atomic 600, fail-soft), read-back via the existing `session.updated` echo check, hot apply only at the proven safe boundary through the instructions-only `session.update` path, hot reload at the next turn after an admin apply. Acceptance: verbatim anchors preserved (accepted suites pin them), PERSONA_POLICY_TESTS, `PERSONA-POLICY-V1.md`.
- DO: created `modules/policy/{__init__,persona}.py` + README; refactored `render_instructions` to compose from `render_*` policy helpers (VOCAB_LEARN composed from `teaching.vocabulary_format`; closing from persona+limits fields); `BehaviorLink` policy wiring (`POLICY_FILE`, `_maybe_reload_policy`, `policy_reloads` stat, `snapshot()["policy_version"]`); `main.py` config; `persona_policy_tests.py` (59 checks).
- CHECK: PERSONA_POLICY_TESTS **59/59 PASS** (first run 57/59 — two test expectations of mine were wrong about deep-merge semantics: closed level-maps fill missing keys from the defaults and reject only unknown keys; the then-unreachable "missing activities" branch was removed as dead code). No drift: BEHAVIOR1 111/111, VOCAB_ACCURACY 79/79, KNOWLEDGE1 69/69, MEMORY_V1 54/54, MEMORY1 19/19, WORKBENCH1 25/25, MVP_INTEGRATION 28/28, ADMIN1 80/80.
- ACT: dead branch removed; merge semantics pinned by tests. No BLOCKER/MAJOR.
- BLOCKERS = 0, MAJORS = 0, MINORS = 0. STATUS: PASS (b29edd9).

### Phase 4 — ADMIN-2 control plane

- PLAN: additive control plane over ADMIN-1 (mount only when the store bundle is wired — ADMIN-1 route table untouched in the no-stores build, keeping ADMIN1_TESTS 80/80 valid): PERSONA/POLICY (active/versions/audit/preview/apply/rollback), MEMORY (list/search/inspect/edit/delete/category-clear with confirm/diagnostics), KNOWLEDGE (datasets/documents CRUD, enable/disable, rebuild, retrieval test, diagnostics), WORKBENCH (read-only status/current/progress/reviews — no write route), BEHAVIOR (active + bounded routing metadata via the passive registry allowlist), the ADMIN-1 REALTIME six retained, plus a bounded sanitized admin audit. Every write: AUTH → VALIDATE → (PREVIEW) → EXPLICIT APPLY (confirm token) → READ-BACK → AUDIT. Store edits propagate to live sessions via file-signature reloads (policy at safe boundary; memory/knowledge next turn).
- DO: `gateway/app/admin/stores.py` (AdminStores + AdminAudit), `api.py` (28 routes, coded sanitized error mapping, 64 KB body cap), `app.py`/`service.py` additive mount, `main.py` wiring (stores only when ADMIN_ENABLED=1), registry behavior row (allowlist — recent_word never leaves the link), `WorkbenchClient.status()` public helper, memory/knowledge `reload_if_changed`, link `_maybe_reload_stores` (+ memory/knowledge reload counters), `admin2_tests.py` (66 checks), `admin_security_tests.py` (29 checks), `ADMIN-2.md`.
- CHECK: ADMIN2_TESTS **66/66**, ADMIN_SECURITY_TESTS **29/29**; ADMIN1 **80/80 unchanged**; no drift — MEMORY_V1 54/54, MEMORY1 19/19, KNOWLEDGE1 69/69, BEHAVIOR1 111/111, VOCAB 79/79, PERSONA_POLICY 59/59, WORKBENCH1 25/25, MVP_INTEGRATION 28/28. Four defects found by the new suites and fixed: workbench lazy-coro AttributeError on unconfigured store (500→honest 200), weakref-incompatible fixture (test), non-numeric confidence raised ValueError→500 (now 400 boundary), per-suite store-file isolation (test).
- ACT: all four fixes applied in-phase; no BLOCKER/MAJOR remaining.
- BLOCKERS = 0, MAJORS = 0, MINORS = 0. STATUS: PASS (2507a04).

### Phase 5 — Unified Admin UI (Chinese-first)

- PLAN: one coherent Chinese-first console over the ADMIN-1/ADMIN-2 APIs, zero external dependencies, LAN-only, desktop-responsive; 8 sections (仪表盘/实时状态/诊断/角色与教学/记忆/知识库/课程进度/意图·路由诊断); no raw JSON needed for common actions; every destructive action behind confirmation; token hygiene preserved. Acceptance: static UI-contract suite (endpoint-table contract scan, confirmation, Chinese-first, no external URLs), live serving checks, GET integration smoke; ADMIN-1 UI assertions evolved where the directive supersedes them (the API stays backward compatible).
- DO: rewrote `admin/{index.html,app.js,styles.css}` (vanilla JS, DOM-built with textContent — no innerHTML of server data); added `GET /admin/knowledge/dataset/{ds_id}/documents` + `KnowledgeStore.list_documents`; allowlisted `qwen_model`/`qwen_voice` into `GET /admin/health` (from the gateway's own config); `admin_ui_tests.py` (23 checks); rewrote the old ADMIN-1 UI acceptance block (six-endpoint/GET-only/no-write-controls assertions were ADMIN-1-phase-scoped and superseded; security invariants kept and extended); `UNIFIED-ADMIN-UI.md`.
- CHECK: ADMIN_UI_TESTS **23/23**; ADMIN1 **83/83**; ADMIN2 **67/67**; ADMIN_SECURITY **29/29**; KNOWLEDGE1 **69/69**. One contract-scanner bug fixed (a concatenation prefix `/admin/knowledge/dataset/` was compared as a route).
- ACT: scanner normalization fixed; no BLOCKER/MAJOR remaining.
- BLOCKERS = 0, MAJORS = 0, MINORS = 0. STATUS: PASS (84cd72a).

### Phase 6 — Cross-module product integration

- PLAN: one machine suite covering the directive's 13 scenarios over the real bridge app + mock Qwen + fake read-only workbench + the ADMIN-2 plane over the same store files; explicit ownership assertions (WORKBENCH_WRITES=0, progress duplication=0, ephemeral injections, sanitized audit); no real Qwen.
- DO: `gateway/tests/product_v1_integration.py` (33 checks, H1–H15); link fix: `_maybe_reload_stores()` at the top of `_on_input_completed` (admin edits visible to the same turn's routing/memory/retrieval); `PRODUCT-V1-INTEGRATION.md`.
- CHECK: PRODUCT_V1_INTEGRATION **33/33** — including the admin→knowledge→conversation path and the admin→policy→safe-boundary path with instructions-only payloads. Regression green: MVP_INTEGRATION 28/28, MEMORY_V1 54/54, KNOWLEDGE1 69/69, PERSONA_POLICY 59/59, BEHAVIOR1 111/111, ADMIN2 67/67.
- ACT: one real integration defect found by H8 and fixed in-phase (knowledge retrieval ran before the per-turn store reload → admin-added documents were invisible for one turn). No BLOCKER/MAJOR remaining.
- BLOCKERS = 0, MAJORS = 0, MINORS = 0. STATUS: PASS (1d8220d).

### Phase 7 — Master test matrix

- PLAN: run the directive's 18 named suites plus the continuity suites; re-assert the frozen constants; evidence the five ownership invariants (WORKBENCH_WRITES / MEMORY_PROGRESS_DUPLICATION / KNOWLEDGE_PROGRESS_DUPLICATION / SECRET_LEAKS / UNAUTH_WRITES); map CONCURRENCY/RECONNECT/BARGE_IN/PRIVACY to concrete checks.
- DO: added `gateway/tests/product_boundary_tests.py` (23 checks: frozen constants F1–F9 + concurrency C1–C6 + reconnect R1–R4 + privacy P1–P4); ran 21 suites; `MASTER-TEST-MATRIX.md`.
- CHECK: all suites green except the documented R-1f local dev-libopus sentinel (179/180). An intermittent second R-1f failure (`R test_segment_extrema`) was **reproduced at the pristine baseline commit 2fd8d4f** in a throwaway worktree → environment-only, not drift; worktree removed. Totals: CLIENT_UI 48/48, GUI_TRANSCRIPT_LIVE 25/25, CLIENT_UI_INTEGRATION 19/19, BEHAVIOR1 111/111, VOCAB 79/79, MEMORY_V1 54/54, KNOWLEDGE1 69/69, WORKBENCH1 25/25, PERSONA_POLICY 59/59, ADMIN1 83/83, ADMIN2 67/67, ADMIN_SECURITY 29/29, ADMIN_UI 23/23, MEMORY1 19/19, MVP_INTEGRATION 28/28, PRODUCT_V1_INTEGRATION 33/33, PRODUCT_BOUNDARY 23/23. Invariants all 0 as required.
- ACT: none needed beyond the baseline root-cause (documented).
- BLOCKERS = 0, MAJORS = 0, MINORS = 1 (local-libopus env sentinel, carried, non-blocking, NAS unaffected). STATUS: PASS (52facaa).

### Phase 8 — Multi-agent final review A–F

- PLAN: six independent read-only reviewers (A architecture, B knowledge, C memory, D persona/UX, E security, F integration); raw reports persisted to `reviews/agent-<A-F>.md`; Lead repairs BLOCKER/MAJOR; reviewers re-check.
- DO: all six reviewers ran; reports persisted. Initial verdicts: A PASS (3 MINOR), B PASS (2 MINOR + 2 INFO), **C FAIL (1 MAJOR: load-seam boundary bypass — loaded files could smuggle progress keys/secret values/unknown entities)**, **D FAIL (1 MAJOR: notes duplicated editable policy text; edits did not propagate)**, E PASS (INFO only), F PASS (env sentinel only).
- REPAIRS (this batch):
  * C-MAJOR: `MemoryStore.load()` now enforces the write-path boundary (`_item_passes_boundary`) — out-of-boundary items are dropped with a log; `boundary_diagnostics` now scans values too; `assert_no_progress_keys` exempts vocab words (a learner may genuinely not know the word “progress”); `note_weak_word` semantics documented; unique temp filenames for all three stores; memory mutators merge a concurrent writer first (`reload_if_changed`) since gateway+admin both write memory. New regression: MEMORY_V1 V14a–f (60/60).
  * D-MAJOR: per-turn notes no longer restate editable directive text — `route()`/`_explain_word()` take the active policy; spelling/word/vocab notes reference the VOCABULARY ACCURACY POLICY block or compose from `word_explanation_order`; VOCAB_LEARN note references the teaching format; link passes the active policy into routing. New regression: PERSONA_POLICY P1u/P1v (61/61).
  * B-MINOR: `render_knowledge_block` now bounds the WHOLE block (excerpt budget = max_chars − header); unique temp names; K9d added (KNOWLEDGE1 70/70).
  * Fix-with-fix defect caught by the suites: missing `uuid` import in `persona.py` made policy flush fail-soft silently (persona/admin2/security failures) — fixed immediately.
- CHECK: all affected suites green — PERSONA 61/61, MEMORY_V1 60/60, KNOWLEDGE1 70/70, ADMIN1 83/83, ADMIN2 67/67, ADMIN_SECURITY 29/29, ADMIN_UI 23/23, BEHAVIOR1 111/111, VOCAB 79/79, MVP 28/28, PRODUCT_V1 33/33, PRODUCT_BOUNDARY 23/23, CLIENT_UI1 19/19, MEMORY1 19/19, WORKBENCH1 25/25.
- ACT: reviewers C and D re-checking the repairs (appended to their raw reports); remaining MINORs (A: shared-workbench dead duplicate class, B: latent cross-instance lost update — unreachable today, E/A: INFO notes) are documented, non-blocking, no security/privacy/data-integrity/realtime risk in the current single-writer knowledge/policy topology.
- BLOCKERS = 0, MAJORS = 0. STATUS: IN_PROGRESS (re-checks closing).

RE-CHECK ROUND 1 (@90b8ab4): C = PASS — MAJOR closed (poisoned files dropped at load; value scans; probes re-run; MEMORY_V1 60/60, MEMORY1 19/19); residual MINOR: vocab_item poisoned *value* not validated at load.  D = FAIL — MAJOR partially closed: `teaching.grammar_explanation` still duplicated verbatim in the EXPLAIN_GRAMMAR note.

REPAIR ROUND 2 (@2cf4211): grammar note now composes `teaching.grammar_explanation` from the active policy (+P1w regression); vocab_item load validation now also enforces the fixed `{"status": "weak"}` value (+V14g); MEMORY-V1/KNOWLEDGE-V1 docs corrected (check counts, load-seam wording, whole-block bound).

RE-CHECK ROUND 2 (@2cf4211): D = PASS — MAJOR closed (probe re-run; full sweep of every note vs every policy string found no remaining verbatim policy phrase ≥4 words; PERSONA 62/62, BEHAVIOR1 111/111, VOCAB 79/79). C's residual MINOR closed by V14g (MEMORY_V1 61/61).

FINAL: AGENT_A = PASS, AGENT_B = PASS, AGENT_C = PASS, AGENT_D = PASS, AGENT_E = PASS, AGENT_F = PASS.
- BLOCKERS = 0, MAJORS = 0. STATUS: PASS (@2cf4211 + this closing commit).

### Phase 9 — NAS Product-V1 test sidecar

- PLAN: deploy an isolated Product-V1 sidecar (`/volume1/docker/xiaozhi-product-v1`, own compose project, ports 28310/28311/28312) persisting Memory/Knowledge/Policy in `./data` (uid 10001, 700) with runtime-only secrets (fresh NAS-generated admin token, copied Qwen secret; both 600/uid 10001), LAN-only, `QWEN_MODE=mock` for machine verification. Acceptance: the directive's verification list passes as a structural probe, no real Qwen session, primary/Workbench/legacy untouched. Rollback: `docker compose down` + `rm -rf` the directory (nothing shared). Frozen surfaces untouched.
- DO: adapted `deploy/mvp-sidecar/{Dockerfile,docker-compose.yml}` into `deploy/product-sidecar/` (adds the Product-V1 store env + `QV1_QWEN_MODE`), wrote `deploy/product-sidecar/probe_product_v1.py` (65 checks incl. an embedded mock Qwen upstream), staged `gateway/{app,config,tests}` + `modules/` + `admin/`→`admin-ui/`, transferred by tar+pipe (sha256 `9ab66e13…` verified both ends), built and started in mock mode.
- CHECK: **PRODUCT_V1_STRUCTURAL_PROBE 65/65 PASS on the NAS** (and a 65/65 local pre-flight against a Mac instance before shipping). Verification list covered: health · OTA(28310) · WS hello · full admin auth matrix (anon 401 / invalid 401 / valid on 21 GET + 14 POST routes; six ADMIN-1 routes 200) · admin surface absent from the audio app · no `/admin/diag/reset` · Workbench write verb 405 · GET on write-only path 405 · token absent from every served body · routing integration with mock Qwen (hello + listen-start → mock dial → routed input-transcription turn → learner-memory write visible through the ADMIN-2 API) · Memory CRUD + boundary refusals · Knowledge CRUD + search + provenance + rebuild + confirmed deletes + diagnostics · Workbench GET-only · persona preview/apply/read-back/rollback + audit. Isolation: primary realtime / Workbench / MVP sidecar / legacy stack StartedAt + Restarts unchanged (`PRODUCT-V1-DEPLOYMENT.md`).
  * **MAJOR found (Phase 9 CHECK):** the ADMIN-2 memory *reads* served a stale view — the gateway conversation path and the admin plane are two store instances over one file and `list_items`/`inspect`/`search` skipped the file-signature reload, so a preference saved during conversation did not appear in the console until some write happened. Reproduced deterministically, then fixed at the read seam (`_fresh()` = fail-soft `reload_if_changed()` in `memory_items`/`memory_search`/`memory_item`/`memory_diagnostics`; control-plane only, no audio-plane effect). Guarded by two new deterministic checks (ADMIN2 C15/C15b) which were proven to FAIL with the fix disabled.
- ACT: MAJOR fixed and re-verified; two probe defects fixed during pre-flight (async predicates in the wait helper; workbench/rollback payload shapes). Armed state: `QV1_QWEN_MODE=real` recreated → `status=ok`, `degraded_reasons=[]`, **`qwen_connected=0`, `qwen_sessions=0`** (no upstream session opened; budget 4/4 respected).
- BLOCKERS = 0, MAJORS = 0, MINORS = 1 (documented: the probe retries the WS hello once because this Mac's dev libopus intermittently raises `OpusError(bitrate)` on the first encoder construction — baseline-proven env sentinel, Debian `libopus0` in the image unaffected). STATUS: PASS.

### Phase 10 — Mac client arm

- PLAN: keep the accepted GUI transcript fix; back up the live client config; point **only** `OTA_VERSION_URL` at the Product V1 sidecar (the accepted mechanism — no direct WS-URL edit); record backup path, before/after SHA256, changed fields, OTA result, WS result, rollback. Do not launch `py-xiaozhi`, do not open an upstream session.
- DO: backup `config-backups/config_backup_productv1_arm_20261008_013545.json`; one-line replacement `…:28211/xiaozhi/ota/` → `…:28311/xiaozhi/ota/`.
- CHECK: before `94b069fa…`, after `fa61ca44…`, `diff` = exactly 1 line removed + 1 added (every other byte identical incl. `WEBSOCKET_URL`/`WEBSOCKET_ACCESS_TOKEN`). OTA from the Mac → `ws://192.0.2.1:28310/xiaozhi/v1/`; hello-only WS connect from the Mac → `{"type":"hello",…}`; sidecar `qwen_sessions` still **0** afterwards (no real session opened).
- ACT: none needed.
- BLOCKERS = 0, MAJORS = 0, MINORS = 0. STATUS: PASS.

### Phase 11 — One final human acceptance (PREPARE ONLY)

- PLAN: a Chinese script covering the directive's 25 items, ~20–25 scenarios, prepared but **not run**; the product owner executes it once.
- DO: `FINAL-HUMAN-ACCEPTANCE.md` — 25 scenarios (基础对话 / 词汇准确性与发音分离 / 学习控制 / 记忆 / 知识库 / Workbench / 控制台与人机交互), token-retrieval and health pre-checks, a record table, pass criteria (≥23/25 with items 4/5/21/22 mandatory and no fabrication), and the rollback commands.
- CHECK: script self-reviewed against the directive's 25-item list — all 25 items present; no execution performed; `py-xiaozhi` never launched.
- ACT: none needed.
- BLOCKERS = 0, MAJORS = 0, MINORS = 0. STATUS: PASS.

### Phase 12 — Final PDCA closeout

- Global PLAN: compare the final system against the Product V1 mission (Knowledge + Memory + Persona/Teaching Policy + ADMIN-2 + unified Chinese-first console + Behavior/Workbench/client transcript, cross-module integrated, independently reviewed, deployed to an isolated test sidecar, client armed, one human script).
- Global DO: complete — all phases 0–11 done; the only product-code change after Phase 8 is the Phase 9 memory-read seam fix (+ its guards).
- Global CHECK: every phase PDCA = PASS; the full matrix is green (KNOWLEDGE1 70/70, MEMORY_V1 61/61, PERSONA_POLICY 62/62, ADMIN2 69/69, ADMIN_SECURITY 29/29, ADMIN_UI 23/23, VOCAB_ACCURACY 79/79, WORKBENCH1 25/25, BEHAVIOR1 111/111, MEMORY1 19/19, ADMIN1 83/83, PRODUCT_V1_INTEGRATION 33/33, PRODUCT_BOUNDARY 23/23, MVP_INTEGRATION 28/28, CLIENT_UI1_INTEGRATION 19/19, CLIENT_UI1 48/48, GUI_TRANSCRIPT_LIVE 25/25, R1F 179/180 = documented dev-libopus env sentinel); A–F all PASS; primary realtime untouched (`2fd8d4f..HEAD` diff empty for turns/audio/qwen/ws/protocol/counters; StartedAt/Restarts unchanged); Workbench write count 0; real-Qwen budget respected (4/4 used, 0 opened this run); rollback tag + bundle + config backup available; test sidecar healthy; Mac client armed; human script prepared.
- Global ACT: no BLOCKER/MAJOR remains; 4 MINORs total are documented and non-blocking (probe WS-hello retry note; shared-workbench dead duplicate class; latent cross-instance lost update for knowledge/policy — unreachable in the single-writer topology; INFO notes).
- BLOCKERS = 0, MAJORS = 0, MINORS = 4. STATUS: PASS.
- Endpoint reached: **PRODUCT_V1_READY_FOR_SINGLE_HUMAN_ACCEPTANCE = YES** — STOP.
---

## 13. 链收敛（LIVING SECTION · 2026-10-13 PROJECT-DOC-MERGE-01 第二阶段批 1 追加）

> 本节为 PRODUCT V1 FINAL COMPLETION RUN（TASK_ID=PRODUCT-V1）链 12 份文档的角色裁定。本板 Phase log 已逐阶段
> 完整继承各分期报告的有效结论（测试数字、缺陷与修复、提交哈希、状态），无需逐份合并正文。

| 文档 | 角色 | 处置 |
|---|---|---|
| `PRODUCT-V1-RUN-DIRECTIVE.md`（1396 行） | **任务书（初始需求原件）** | 例外保留（不改动、不合并） |
| `BASELINE.md` | Phase 0 基线取证（仓库/回滚/NAS 容器/Mac config/Qwen 预算/卫生/冻结面清单） | **父任务阶段取证件（保留）**：属 PRODUCT-V1 本体的 Phase 0 记录，细节未被本板逐字覆盖 |
| `KNOWLEDGE-V1.md` | Phase 1 技术规格（数据模型字段表/chunk id 确定性算法/caps/MAX_INJECTION_CHARS=1200/min_score 语义/路由规则） | **独立子任务主文档（保留）**：子任务 `PRODUCT-V1-KNOWLEDGE` 的技术规格权威（兼接口契约性质），与父任务 PRODUCT-V1=子任务↔父任务关系 |
| `MEMORY-V1.md` | Phase 2 技术规格（五实体类字段表/边界语义/迁移规则） | **独立子任务主文档（保留）**：子任务 `PRODUCT-V1-MEMORY` 的技术规格权威 |
| `PERSONA-POLICY-V1.md` | Phase 3 技术规格（closed schema 全字段表/render 语义） | **独立子任务主文档（保留）**：子任务 `PRODUCT-V1-PERSONA-POLICY` 的技术规格权威 |
| `ADMIN-2.md` | Phase 4 技术规格（写路径六步模型/34 路由面全表/确认 token 语义） | **独立子任务主文档（保留）**：子任务 `PRODUCT-V1-ADMIN2` 的控制面规格（兼接口契约性质） |
| `UNIFIED-ADMIN-UI.md` | Phase 5 技术规格（8 区界面内容表/交互语义） | **独立子任务主文档（保留）**：子任务 `PRODUCT-V1-ADMIN-UI` 的界面规格 |
| `PRODUCT-V1-INTEGRATION.md` | Phase 6 技术规格（13 场景×证据对照表/测试 harness 构成） | **父任务阶段报告（保留）**：属 PRODUCT-V1 本体的 Phase 6 记录 |
| `MASTER-TEST-MATRIX.md` | Phase 7 技术规格（指令套件→21 套件全矩阵逐项结果/env sentinel 根因） | **父任务阶段报告（保留）**：属 PRODUCT-V1 本体的 Phase 7 记录 |
| `PRODUCT-V1-DEPLOYMENT.md` | Phase 9 部署规格（NAS 路径/端口映射/store 卷/密钥模式/probe 命令） | **父任务阶段部署记录（保留）**：属 PRODUCT-V1 本体的 Phase 9 记录 |

> **归属裁定（2026-10-13 统一验收核验）**：本板=父任务 **PRODUCT-V1** 的状态与流程权威（12 阶段 PLAN/DO/CHECK/ACT、缺陷与修复、提交哈希）。
> 9 份中 **5 份为独立子任务的主文档**（KNOWLEDGE/MEMORY/PERSONA-POLICY/ADMIN2/ADMIN-UI——不同功能，不强行并入本板），
> **4 份为父任务自身的阶段记录件**（BASELINE/INTEGRATION/MASTER-TEST-MATRIX/DEPLOYMENT）。二者互补、互不替代，
> 均不属「同任务重复版本」，不列入任何删除候选；后续 Agent 需要实现细节时按上表定向读取对应子任务主文档。
| `FINAL-HUMAN-ACCEPTANCE.md` | **有效待执行验收脚本**（Phase 11 产物） | 保留独立维护（25 场景脚本，状态=PREPARED NOT RUN） |
| `reviews/agent-<A-F>.md`（6 件） | Phase 8 独立评审原始报告 | **例外保留**（独立审计证据） |
| 回滚资产：tag `product-v1-pre-run` + `admin0-backups/product-v1-pre-run.bundle` | 回滚依据 | 不动 |

**当前真实状态（本板 Phase 12 终态）**：`PRODUCT_V1_READY_FOR_SINGLE_HUMAN_ACCEPTANCE = YES`；
人工验收脚本**未执行**；4 项 MINOR 已记录不阻断；此后 V2/Classroom 链在其上演进（见 WORKLOG 索引）。

（链收敛完成于 2026-10-13，PROJECT-DOC-MERGE-01 第二阶段批 1。）
