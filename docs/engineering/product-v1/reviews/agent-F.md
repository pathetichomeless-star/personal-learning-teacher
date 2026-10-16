# AGENT F — Integration / Realtime / Regression Review

- **Reviewed commit:** `52facaa24b5b8c97f805e019e66b087faf9ac46b` ("product-v1: master test matrix … [phase 7]", 2026-10-08 01:03:50 +0800), baseline `2fd8d4f`
- **Date:** 2026-10-08 · **Reviewer:** Agent F (independent, read-only)
- **Method:** ran the directive suites myself (no real-Qwen drivers used; budget lock 4/4 respected) with `DYLD_LIBRARY_PATH=/tmp/opus131/lib`; inspected source + docs.

## Findings

### MINOR / ENV — R-1f carries the documented local libopus sentinel (no drift)
`B test_sentinel_harness EXCEPTION OpusError()` is the only failure; `R test_segment_extrema`
passed this run (R1/R2 PASS), so the intermittent 2nd-failure variant did **not** recur. This is
the known mac dev-libopus env sentinel, reproduced at baseline `2fd8d4f` per MASTER-TEST-MATRIX
L10/L64. Not product drift; NAS image unaffected. No action required.

### INFO — R-1f turn-engine invariants untouched (verified independently)
`git diff 2fd8d4f..52facaa --stat -- gateway/app/turns.py gateway/app/ws.py gateway/app/audio.py
gateway/app/qwen.py gateway/app/protocol.py gateway/app/counters.py` is **EMPTY**. Full-change
scope is additive (behavior.py, admin/*, modules/{intent,memory,knowledge,policy}, tests, docs).
R-1f constants Z1–Z7 and F1–F9 re-assert green.

### INFO — Behavior link is text-events-only, hot-applies only at the safe boundary
`gateway/app/behavior.py:186-203` `on_qwen_event` handles only
`input_audio_transcription.completed`, `response.done`, `session.updated`; every hook is wrapped
in `except` (L202) so it can never disturb the turn engine. Apply is gated:
`behavior.py:372` `if not self.conn.is_safe_boundary()`; `Connection.is_safe_boundary`
(`turns.py:263-266`) = no `_current_gen`, no `tts_active`, no `pacer_task`. `schedule_apply()` is
invoked only from safe points (`turns.py:531` listen-start, `turns.py:1109` TTS stop,
`behavior.py:199` response.done). `send_instructions_update` (`qwen.py:400-412`) writes a
**instructions-only** `session.update` (`{"session":{"instructions":…}}`), never model/voice/VAD
— independently confirmed by PV1 H10d asserting `session.keys()=={"instructions"}`.

### INFO — Barge-in unchanged
R-1f barge-in/abort section PASS (N8–N10, Q1–Q5); MVP `I9 barge-in stops playback (Path B)` PASS.
`_on_speech_started` calls the text-plane `behavior.on_speech_started()` **before** the untouched
barge-in path (`turns.py:624-635`).

### INFO — Reconnect / concurrency / transcript forward / ownership all green
- Reconnect: PV1 H12 `fresh transcript stream (no history replay)`, H12b forgotten pref absent,
  H12c fresh chat state, H12d workbench still authoritative; MVP I12/I12b/I12c PASS.
- Concurrency: PV1 H13/H13b/H13c (4 upstream conns, session C unaffected), boundary C5/C6, MVP
  I10/I10b/I10c PASS.
- Transcript forwarding: `client_ui1_integration.py` — user/assistant deltas+final forwarded,
  every message carries a turn key, interrupted notice kept, `R-1f closures stay 0 with transcript
  forwarding`, `accounting faults 0`.
- `WORKBENCH_WRITES = 0`: PV1 H14 fake workbench saw only GETs (`bad_methods == []`).

### INFO — No orphan / accounting faults
PV1 H15 `qwen_dispatch_errors_total==0 and responses_completed>0`; MVP I13c `no orphan /
accounting faults`; client_ui1 `source/framer/disposition closure residual 0`.

## Verbatim suite results (this run)

```
R1F_BRIDGE_TESTS: 180 checks, 179 PASS, 1 FAIL, 0.4s
  - B test_sentinel_harness EXCEPTION OpusError()      ← documented env sentinel
MVP_INTEGRATION_TESTS: 28 checks, 28 PASS, 0 FAIL
PRODUCT_V1_INTEGRATION: 33 checks, 33 PASS, 0 FAIL
CLIENT_UI1_INTEGRATION: 19/19 PASS
PRODUCT_BOUNDARY_TESTS: 23 checks, 23 PASS, 0 FAIL
```

All five directive targets match expected values (179/180 · 28/28 · 33/33 · 19/19 · 23/23).

## Verdict
No BLOCKER, no MAJOR. The single R-1f failure is the pre-existing environmental libopus sentinel.
Realtime invariants are intact; end-to-end integration, reconnect, barge-in, concurrency,
transcript forwarding, and ownership boundaries are all independently reproduced.

AGENT_F = PASS