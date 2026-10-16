# CONVERSATIONAL MVP — INTEGRATION REGRESSION (local)

Date: 2026-10-07 · Status: **PASS** · Evidence: `evidence/mvp-local-suites.txt`

## Suites (all green)

| suite | result | notes |
|---|---|---|
| R-1f deterministic (bridge) | **179/180** | baseline-identical; the 1 failure is the documented local dev-libopus `OpusError` (sentinel harness only; the NAS image ships its own libopus) |
| CLIENT-UI-1 integration (gateway) | **19/19** | transcript forwarding + closures with the new behavior link active |
| CLIENT-UI-1 client suite | **48/48** | client source untouched in this run |
| ADMIN-1 deterministic | **80/80** | admin plane untouched |
| ADMIN-1 load | **29/29** | |
| BEHAVIOR-1 | **111/111** (final; 109 at first pass + 2 mirror-language checks) | ≥60 required scenarios included |
| MEMORY-1 | **19/19** | |
| WORKBENCH-1 | **25/25** | |
| Conversational MVP integration | **28/28** | real bridge app + drivable mock Qwen + fake workbench + 2 clients |

## Integration coverage (mvp_integration.py)

Initial policy instructions · natural activity routing hot-apply (practice+hotel) ·
speed command keeps activity · temporary intent hot-applied **and** auto-resumed to the
main activity after `response.done` · zh language override · workbench continue-lesson
(real lesson 12 + title) · workbench progress (real counts) · explicit memory save →
**new session applies it** · barge-in while behavior is active (Path B playback stop) ·
two concurrent sessions isolated (A practice, B vocab; connections=2) · workbench down
+ cold cache → honest degrade line · reconnect → fresh session with memory preference ·
health integrity (dispatch errors 0, responses completed >0, no orphan/accounting faults).

## Audio-plane invariants

Locked constants re-asserted (20/15/5 ms, caps, thresholds — group Z of R-1f);
FIFO/pacer/barge-in/generation-ownership behavior is exercised by the R-1f and load
suites with the behavior link active. The behavior link never touches Opus/pacer code
paths; its only Qwen traffic is `session.update{instructions}` at safe boundaries.