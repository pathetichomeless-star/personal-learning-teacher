# MASTER TEST MATRIX (Phase 7)

> **【历史快照 · 2026-10-13】** 本文为 PRODUCT V1 Final Completion Run 的 Phase 7 主测试矩阵 分期报告；
> 有效结论已完整继承至权威主文档 `PDCA-BOARD.md`（对应阶段行与 Phase log，TASK_ID=PRODUCT-V1）。
> 本文逐字保留，不再单独维护。

Full deterministic matrix at commit `1d8220d` (worktree clean).  All runs local,
`DYLD_LIBRARY_PATH=/tmp/opus131/lib`, no real Qwen session (budget locked 4/4).

## Directive suites → runs

| directive name | suite | result |
|---|---|---|
| R1F_REGRESSION | `gateway/tests/r1f_tests.py` | **179/180** — 1 FAIL = the documented local dev-libopus env sentinel (`B test_sentinel_harness EXCEPTION OpusError`); an intermittent variant where `R test_segment_extrema` joins it was reproduced **at the pristine baseline commit 2fd8d4f** in a temp worktree (environment-only, NAS image unaffected) |
| CLIENT_UI_TESTS | `client/tests/test_client_ui_transcript.py` | **48/48** |
| GUI_TRANSCRIPT_LIVE_TESTS | `client/tests/test_gui_transcript_live.py` | **25/25** |
| CLIENT_UI_INTEGRATION | `gateway/tests/client_ui1_integration.py` | **19/19** |
| BEHAVIOR1_TESTS | `gateway/tests/behavior1_tests.py` | **111/111** |
| VOCAB_ACCURACY_TESTS | `gateway/tests/vocab_accuracy_tests.py` | **79/79** |
| MEMORY_V1_TESTS | `gateway/tests/memory_v1_tests.py` | **54/54** |
| KNOWLEDGE1_TESTS | `gateway/tests/knowledge1_tests.py` | **69/69** |
| WORKBENCH1_TESTS | `gateway/tests/workbench1_tests.py` | **25/25** |
| PERSONA_POLICY_TESTS | `gateway/tests/persona_policy_tests.py` | **59/59** |
| ADMIN1_TESTS | `gateway/tests/admin1_tests.py` | **83/83** |
| ADMIN2_TESTS | `gateway/tests/admin2_tests.py` | **67/67** |
| ADMIN_SECURITY_TESTS | `gateway/tests/admin_security_tests.py` | **29/29** |
| PRODUCT_V1_INTEGRATION | `gateway/tests/product_v1_integration.py` | **33/33** |
| CONCURRENCY_TESTS | `gateway/tests/product_boundary_tests.py` (C1–C6) + PV1 H13 + MVP I10 + KN K11 | **PASS** |
| RECONNECT_TESTS | boundary R1–R4 + PV1 H12 + MVP I12 | **PASS** |
| BARGE_IN_TESTS | R-1f barge-in/abort section + MVP I9 (Path B stop) + boundary F8 (safe-boundary gate) | **PASS** |
| PRIVACY_BOUNDARY_TESTS | boundary P1–P4 + MEMORY_V1 abuse + KN K10 + SEC leak scans + PV1 H11/H14 | **PASS** |
| (extra) ADMIN_UI_TESTS | `gateway/tests/admin_ui_tests.py` | **23/23** |
| (continuity) MEMORY1_TESTS / MVP_INTEGRATION | `memory1_tests.py` / `mvp_integration.py` | **19/19** / **28/28** |

Totals: **21 suites, 0 BLOCKER-level failures**; the single R-1f failure is the carried
environment-only sentinel.

## Frozen-surface re-assertion — NO DRIFT

`product_boundary_tests.py` F1–F9 (values imported from the live modules):

* F1 media frame **20 ms** (`turns.MEDIA_FRAME_MS`, `audio.FRAME_MS`, `DEFAULTS.FRAME_MS`)
* F2 send-start guard **15 ms** (`MIN_SEND_START_INTERVAL_MS`)
* F3 pacing slack **5 ms** (+ slow-send threshold 5 ms)
* F4 future caps `MAX_FUTURE_FRAMES=1500`, `MAX_FUTURE_AUDIO_BYTES=524288`,
  `MAX_REBASE_LATENESS_MS=250`
* F5 provider/mode/model/voice defaults (`QWEN_MODE=mock` default,
  `qwen3.8-omni-flash-realtime`, `Tina`)
* F6 VAD block frozen (`server_vad`, threshold 0.5, silence 800 ms)
* F7 Opus classes + `pcm16` formats present
* F8 generation ownership + `is_safe_boundary` present (`_current_gen`, `_GEN_SEQ`)
* F9 FIFO store/in-flight semantics present (`still_stored_frames`, `in_flight_frames`)

Plus R-1f's own constant checks (Z1–Z7) in the matrix run.

## Ownership invariants

| invariant | evidence | value |
|---|---|---|
| WORKBENCH_WRITES | PV1 H14 (fake workbench saw only GETs) + WORKBENCH1 no-write boundary | **0** |
| MEMORY_PROGRESS_DUPLICATION | PV1 H14b + MEMORY_V1 abuse matrix | **0** |
| KNOWLEDGE_PROGRESS_DUPLICATION | PV1 H14c | **0** |
| SECRET_LEAKS | ADMIN_SECURITY S1–S6/S10 + boundary P1–P3 (no token/secret in bodies or logs) | **0** |
| UNAUTH_WRITES | ADMIN_SECURITY S1/S1b (every admin route 401 without a valid bearer) | **0** |

## Notes

* The R-1f intermittent 2nd failure was investigated properly: reproduced at baseline in a
  throwaway worktree, so it is environmental (this Mac's dev libopus build) — not drift.
* Temp worktree removed; the only worktree remains the main checkout.