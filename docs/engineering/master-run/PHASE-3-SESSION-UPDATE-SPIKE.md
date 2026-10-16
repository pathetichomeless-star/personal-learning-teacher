# PHASE 3 — Qwen `session.update` capability spike (CONVERSATIONAL MVP)

Date: 2026-10-07 (Asia/Shanghai) · Method: **direct Qwen Realtime protocol probe** (not through the bridge),  
run inside the lab container (`xiaozhi-rtl-bridge`, uid 10001) which holds the runtime secret. Audio uplink:  
none. All steps timeout-bounded; **2 of the ≤4 authorized real sessions used**.

## Probe

`gateway/tests/spike_session_update.py` — connect → `session.update` #1 (production-shaped) →  
**second `session.update` at a SAFE BOUNDARY** (IDLE/LISTENING: no active generation, no TTS, no pacer) →  
`conversation.item.create` → `response.create` → instruction-following check → system-role item → valid-voice  
hot-apply (last, deliberately). Local logic validated first against `gateway/tests/spike_mock_upstream.py` (mock  
evidence, `SPIKE_VERDICTS` identical to the intended semantics). Raw evidence:  
`evidence/phase3_spike_round1.json`, `evidence/phase3_spike_round2.json`.

Official protocol references consulted before touching the service: Model Studio client-events  
(`session.update` validation + `session.updated` echo; `conversation.item.create`; `response.create`),  
server-events, and the qwen3.8 voice list.

## Verdicts (round 2, definitive)

| question                     | verdict                                            | raw evidence                                                                                                                                                                   |
| ---------------------------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `SESSION_UPDATE_MID_SESSION` | **SUPPORTED**                                      | round 2: `session.updated` ack in **65 ms**, echo carries the new `instructions`; no error. (round 1: same, 57 ms)                                                             |
| `INSTRUCTION_HOT_APPLY`      | **IMMEDIATE_AT_SAFE_BOUNDARY**                     | update #2 swapped `ALPHA→BRAVO` at idle; the immediately following `response.create` said **“BRAVO”** (transcript `BRAVO`, 4 audio deltas). Applied to the very next response. |
| `LANGUAGE_POLICY_HOT_APPLY`  | **IMMEDIATE_AT_SAFE_BOUNDARY**                     | language policy is carried by the same `instructions` channel; the ALPHA→BRAVO probe proves the channel's hot-apply semantics directly.                                        |
| `VOICE_HOT_APPLY`            | **SUPPORTED_MECHANICAL** (product will not use it) | valid voice (`Cindy`): update accepted, echo `voice=Cindy`, next generation completed with no error. Perceptual difference not verified here.                                  |
| `ITEM_CREATE_USER_TEXT`      | SUPPORTED                                          | `conversation.item.create` (role=user, `input_text`) + `response.create` produced a full response.                                                                             |
| `ITEM_CREATE_SYSTEM_ROLE`    | SUPPORTED                                          | role=system item accepted without error (kept as an optional injection path).                                                                                                  |
| `response.create`            | SUPPORTED                                          | deterministic response triggering works at idle.                                                                                                                               |

### Round-1 finding that shaped the design (kept as evidence)

A mid-session update carrying an **unsupported voice** (`Cherry` — belongs to older models) was  
**accepted and echoed** in `session.updated`, but the **next** `response.create` failed with  
`InternalError.Algo.InvalidParameter: Voice 'Cherry' is not supported` and the server **dropped the  
connection**. Consequence (binding for BEHAVIOR-1 wiring):

1. `session.updated` echo is an acceptance receipt, **not** a semantic validation of every value;
2. the product only ever hot-applies the frozen, validated fields — **`instructions` only**; provider/model/  
   voice stay exactly as the accepted R-1f session (Tina), never touched mid-session;
3. every hot-apply keeps a **read-back check** (echo `instructions` head) and falls back safely (log + next  
   boundary retry), never resending blind updates on mismatch.

## Consequences for the MVP route

- BEHAVIOR-1 may hot-apply an instruction block **at a safe boundary** (including the gap between  
  `input_audio_transcription.completed` and `response.created` — measured in the R-1f human-test diag at  
  **44–184 ms**, mean ≈105 ms) and the change takes effect **immediately on the next response**.
- Fallback is cheap: if an update is ever missed at the boundary, the state machine re-applies at the next  
  boundary (next turn), which matches the required `APPLIES_NEXT_*` degradation without any error path.
- Budget: 2/4 authorized real sessions consumed. Remaining: 2.

**PHASE 3 = COMPLETE → continue to PHASE 4 (BEHAVIOR-1).**
