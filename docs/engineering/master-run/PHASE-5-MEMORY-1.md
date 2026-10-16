# PHASE 5 — MEMORY-1 MINIMAL (preferences only)

Date: 2026-10-07 · Status: **PASS** · Evidence: `evidence/mvp-local-suites.txt`
(`MEMORY1_TESTS: 19/19`, plus link-level H5/H6/H12 in `BEHAVIOR1_TESTS` and I8/I12 in
`MVP_INTEGRATION_TESTS`)

## Scope delivered

`modules/memory/store.py` — per-user partition (single user `default` for the MVP),
JSON file (atomic write, mode 600), closed entity set `preference | vocab_item` only.

* **Preferences (closed keys)**: `explanation_language` (zh|en), `speed`
  (slow|normal|fast), `difficulty` (easy|normal|hard) — enum-validated.
* **Explicit only**: a preference is stored only when the user explicitly commits
  ("记住/记一下/remember") AND states it ("以后…"); bare "记住" stores nothing (F5).
* **Weak vocabulary (safe subset)**: stored only on an explicit "I don't know this word"
  turn with a concrete word (M8, H12).
* **Forget**: "忘掉这个偏好。" removes the most recently updated preference (F9/F4/H6);
  unknown keys are a no-op.
* **Boundary (hard)**: progress-shaped keys (`progress/lesson/mastery/pass/review/
  repeat/next_review/course/课程/进度/复习/掌握…`) raise `BoundaryViolation`
  (the `400 boundary_violation` analogue, 12 keys tested); free text cannot enter
  preferences; the file contains no transcript/audio-shaped data (M2/M5).
  `assert_no_progress_keys()` is the read-only periodic assertion hook.
* **Provenance**: every item carries `source=explicit_user` + `confidence` (M11b).
* **Fail-soft**: corrupt file → start empty, still writable (M9); cap 200 items/user.

## Required behaviors (authorization)

| requirement | evidence |
|---|---|
| “以后解释单词先用中文，记住。” → save | I8 (file contains `explanation_language=zh`, source explicit_user); F1 |
| new session → preference applies | I12b (fresh session initial instructions contain "word explanations first in 中文"); H5b |
| “忘掉这个偏好。” → remove | H6/F9; file then has no preferences |
| NOT stored: progress/PASS/REVIEW/REPEAT/mastery/review dates/raw audio/transcripts | M2/M5/M11; workbench remains authoritative (see Phase 7) |

## Wiring

`BehaviorLink` loads preferences at construction (applied to the **initial** session
instruction), performs save/forget as bounded local file operations, and refreshes its
in-memory preference view afterwards. Enabled only when `MEMORY_FILE` is configured;
empty (default) = pure R-1f behaviour, no memory.