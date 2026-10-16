# PRODUCT V1 CROSS-MODULE INTEGRATION

> **【历史快照 · 2026-10-13】** 本文为 PRODUCT V1 Final Completion Run 的 Phase 6 跨模块集成 分期报告；
> 有效结论已完整继承至权威主文档 `PDCA-BOARD.md`（对应阶段行与 Phase log，TASK_ID=PRODUCT-V1）。
> 本文逐字保留，不再单独维护。

Phase 6 of the Product V1 final completion run.  Status: **PASS**
(PRODUCT_V1_INTEGRATION 33/33).

## Harness

`gateway/tests/product_v1_integration.py` — the real bridge app (aiohttp, ephemeral ports,
mock Qwen mode) + drivable mock Qwen upstream + a fake **read-only** workbench (records every
method it sees) + the **ADMIN-2 control plane in-process over the same store files** (policy /
memory / knowledge) + synthetic clients.  No real Qwen session is opened (budget lock).

## The 13 required scenarios (all machine-verified)

| # | scenario | evidence |
|---|---|---|
| 1 | 我们随便聊聊 → Chinese chat | H1c: hot-applied instructions show `free chat` + `Current reply language: Chinese.` |
| 2 | 我们练一下酒店英语 → English hotel practice | H1b: `scenario conversation practice` + hotel scenario line |
| 3 | accommodation 是什么意思 → canonical vocab + resume | H2: VOCABULARY ACCURACY POLICY + `canonical English spelling FIRST` + TEMPORARY note; H2b automatic resume; H3 explain-word intent carries the word |
| 4 | 以后解释单词先用中文，记住 → Memory save | H4: store file shows `explanation_language=zh` (explicit_user) |
| 5 | new session → preference applied | H5: fresh session's instructions contain “word explanations first in 中文” |
| 6 | 忘掉这个偏好 → removed | H6: store preferences == {}; H12b a later fresh session lacks the line |
| 7 | 继续上次的课 → real current lesson | H7: `Resume lesson 12` + unit title from the fake workbench |
| 8 | 我学到哪里了？ → authoritative progress | H7b: `current lesson: 12; passed: 1` |
| 9 | knowledge-answerable question → bounded retrieval | H8: document added **through the ADMIN API** reaches the conversation as `KNOWLEDGE BASE DATA` with excerpt + source title; H8b admin read-back of the same store |
| 10 | knowledge miss → no fabrication | H9: explicit ask → `no matching entry` honesty line; H9b implicit probe miss injects nothing |
| 11 | admin persona change → preview → apply → read-back → safe-boundary | H10 trio: preview valid/no-mutation, apply `readback_ok`, and the next turn hot-applies `You are 小美`; H10d proves the applied payload is **instructions-only** |
| 12 | reconnect | H12: fresh transcript stream (no history replay), forgotten preference absent, session state fresh (chat), workbench still authoritative (`Resume lesson 12`) |
| 13 | two concurrent sessions | H13: session D switches to vocabulary learning while session C is unaffected; 4 upstream connections total; MVP_INTEGRATION re-verified this too |

## Ownership checks in the same run

* `WORKBENCH_WRITES = 0` — every adapter call observed by the fake workbench was a GET (H14).
* `MEMORY_PROGRESS_DUPLICATION = 0` — `assert_no_progress_keys()` clean (H14b).
* `KNOWLEDGE_PROGRESS_DUPLICATION = 0` — knowledge store has no progress/transcript keys (H14c).
* Injection is ephemeral: `KNOWLEDGE BASE DATA` / persona values never land in the stores (H11).
* Admin audit sanitized: no token, no document text, no transcripts (H14d).
* Dispatch integrity: 0 dispatch errors, responses > 0 (H15).

## Defect found and fixed by this phase

The link performed knowledge retrieval **before** the per-turn control-plane reload, so an
admin-added document was invisible for one turn (and could serve stale content).  Fix:
`_maybe_reload_stores()` now runs at the top of `_on_input_completed` (before routing, memory
side effects and retrieval), in addition to the pre-apply call.  Re-verified by H8.

## Regression

MVP_INTEGRATION 28/28, MEMORY_V1 54/54, KNOWLEDGE1 69/69, PERSONA_POLICY 59/59,
BEHAVIOR1 111/111, ADMIN2 67/67 — no drift.