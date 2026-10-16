# MEMORY V1 — learner memory (preferences / profile / weak vocab / habits / continuity)

> **【历史快照 · 2026-10-13】** 本文为 PRODUCT V1 Final Completion Run 的 Phase 2 Memory V1 分期报告；
> 有效结论已完整继承至权威主文档 `PDCA-BOARD.md`（对应阶段行与 Phase log，TASK_ID=PRODUCT-V1）。
> 本文逐字保留，不再单独维护。

Phase 2 of the Product V1 final completion run.  Status: **PASS** (MEMORY_V1_TESTS 61/61).

## Ownership

`modules/memory/store.py`.  **The Workbench remains the only authority** for lesson,
progress, PASS/REVIEW/REPEAT, mastery, review dates, next review and course completion —
Memory can never store any of it (interface-enforced).  Memory also never stores raw audio,
whole transcripts or secrets, and nothing is captured automatically: explicit user save /
explicit user forget only.

## Entity classes (closed set)

| class | meaning | key/value rules |
|---|---|---|
| `preference` | closed keys `explanation_language(zh\|en)` / `speed(slow\|normal\|fast)` / `difficulty(easy\|normal\|hard)` | enum-validated |
| `profile_fact` | small durable fact the learner stated ("name=小王") | key ≤40 chars, value ≤300 chars |
| `vocab_item` | word the learner explicitly said they don't know | latin word only, stored weak |
| `habit` | recurring stated behavior ("prefers short answers") | as profile_fact |
| `continuity` | small session-to-session context ("hotel check-in practice") | as profile_fact |

Every item: `id, user_id, entity_type, key, value, source, confidence, created_at,
updated_at, expires_at?` — `MemoryItem.to_json()` (v1 files storing `entity` migrate
fail-soft to `entity_type`; v1 vocab storage keys normalize to the human word).

Storage-key scheme: `preference` → key; `vocab_item` → `vocab:<word>`; others → `<entity>:<key>`.

## Operations

save (generic + `save_preference`) / note_weak_word / list_items(entity, include_expired) /
search (token overlap, expired excluded) / inspect(id) / edit(id, value?, confidence?) /
delete(id) / forget(key=None → most recent preference) / **forget_category(entity, confirm=entity)**
/ category_summary / context (conversational injection) / boundary_diagnostics /
`assert_no_progress_keys`.

Persistence: one JSON file (schema v2), per-user partition, atomic tmp→replace, mode 600,
corrupted storage fails soft to empty (still writable).  Caps: 200 items/user,
key ≤ 40, value ≤ 300, confidence ∈ [0,1], optional `expires_at` (expired items are
excluded from search/context/preferences but still inspectable).

## Hard boundary (abuse-tested)

Rejected with `BoundaryViolation`: progress-shaped keys
(`progress|lesson|mastery|pass|review|repeat|decision|course|syllabus|next_review|score|grade|课程|进度|复习|掌握|课文`)
on **every** entity; secret-shaped keys/values (`password|secret|token|api_key|credential|密码|身份证|银行卡|信用卡`);
narrow progress-shaped values (`课程进度|掌握度|复习日期|next_review|lesson_progress|course_progress|mastery`);
raw bytes (audio); over-long values (transcript-sized); unknown entity classes
(`fact`/`mistake`/`audio` rejected — closed set).

The same boundary is enforced **at the load seam** (Phase-8 repair, reviewer C MAJOR):
crafted/v1/corrupt-recovered files cannot smuggle out-of-boundary items in — `load()`
drops them (logged), `boundary_diagnostics()` scans keys AND values, and
`assert_no_progress_keys()` exempts `vocab_item` entries (a learner may genuinely not know
the word “progress”; the word shape and its fixed `{"status": "weak"}` value are validated
instead).  Memory mutators merge a concurrent writer first (`reload_if_changed`) since both
the gateway (explicit saves) and the admin plane write this file; flushes use unique temp
names.

## Bounded conversational injection

`MemoryStore.context(query, limit=4, max_chars=400)` — relevance-filtered token overlap on
key+value, preferences excluded (they travel through the preference line), deterministic
`(score desc, updated_at desc, id asc)` ordering; `render_memory_block` renders the bounded
ephemeral `LEARNER MEMORY (… explicit consent …)` block.  Gateway link computes it per turn
(`MEM_CONTEXT_LIMIT=4`), hot-applies at the safe boundary, clears after the turn; stats
`memory_injections`.  A plain turn never creates a file (no auto-capture).

## Tests

`gateway/tests/memory_v1_tests.py` → **MEMORY_V1_TESTS: 54 checks, 54 PASS** (3 consecutive
runs; covers every operation, migration, expiry, cap, corruption, abuse matrix, bounded
injection, and the link flow: 记住 → persisted; new session → applied; 忘掉这个偏好 →
removed; weak word stored; plain turn → nothing captured).

Regression at Phase 2 (no drift): MEMORY1 19/19, BEHAVIOR1 111/111, KNOWLEDGE1 69/69,
MVP_INTEGRATION 28/28, VOCAB_ACCURACY 79/79.

## Rollback

`MEMORY_FILE=""` (default) disables Memory entirely.  Phase commit revertible; run rollback
tag `product-v1-pre-run` + bundle.

## Notes

One real bug found by the new suite and fixed: reload re-keyed items by the *human* key,
losing the `vocab:` storage-key scheme, so `vocab_items()` lost words after a restart —
`load()` now re-derives the storage key; v1 files migrate in `from_json`.