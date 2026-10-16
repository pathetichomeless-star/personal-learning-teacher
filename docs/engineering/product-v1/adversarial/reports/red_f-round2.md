# RED-F (Realtime / Session State) — Adversarial Validation, Round 2 (re-attack)

- **Agent**: RED-F (Realtime / Session State Machine) — round 2
- **Scope**: falsify the R-F-1 mitigation (consumer-side FINAL-immutability in
  `client/src/ui/shared/transcript.py`), re-check the realtime surface, re-run the
  round-1 suite, re-confirm the frozen surfaces.
- **Hard locks**: read-only on product source; only my own test dir + report
  written; local mock gateway only (`QWEN_MODE=mock`,
  `QWEN_WS_URL=ws://127.0.0.1:9277/...`); NAS / primary / Workbench never
  contacted; no secrets.
- **Evidence script**: `gateway/tests/adversarial/red_f/red_f_round2.py`
  (uses the round-1 harness + hostile upstream
  `gateway/tests/adversarial/red_f/adv_mock_qwen_server.py`, extended with two
  transcript-emitting scenarios `late_final_midstream`, `precreated_final`).
- **Round-2 suite result**: **20 checks, 17 PASS, 3 FAIL** (the 3 FAILs are the
  residual R-F-1 defeats — see below).

Reproduce:

```
cd <project-root>/gateway
DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python tests/adversarial/red_f/red_f_round2.py
DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python tests/adversarial/red_f/red_f_round1.py   # re-run
```

## 1. R-F-1 reproduced end-to-end again, replayed through the real client store

Captured the actual client-bound message stream from a LOCAL mock gateway
(`late_done_after_new`) and replayed it through the real
`src.ui.shared.transcript.TranscriptStore`:

```
gateway -> client transcript msgs:
  {"role":"assistant","text":"late-final-text","final":true,"turn":2}
  {"role":"assistant","text":null,"final":true,"interrupted":true,"turn":2}
store assistant bubbles after replay:
  {"role":"assistant","text":"late-final-text","state":"FINAL","turn":2}
```

- The gateway still mis-attributes (a late final stamped `turn:2`) — **D1.2 PASS**
  (residual gateway inaccuracy confirmed).
- The **interrupt stamp on a completed turn truly changes nothing** — the second
  message is a no-op (`C4`, `_apply_interrupted` refuses to re-mark a FINAL
  bubble); the learner's bubble state stays `FINAL`. **Confirmed.**
- **D1.3 FAIL**: the store nevertheless displays the stale text
  (`"late-final-text"`) as a turn's reply. The mitigation does **not** help here
  because the bubble did not pre-exist as FINAL — it is **created** by the stale
  final.

## 2. Attempts to DEFEAT the client guard (results per variant)

| Variant | Result |
|---|---|
| late final, SAME text (already FINAL) | no-op — guard holds (C1) |
| late delta after FINAL | dropped (C2) |
| late final for an OLDER turn number | dropped (C3) — but the gateway never emits older turns, so this guard is **inert** for the real attack |
| interrupted stamp on a FINAL turn | no-op (C4) |
| **late TEXT while the target turn is STREAMING** | **DEFEAT** — the stale text overwrites the streaming bubble, is marked FINAL, and the real turn's text is later dropped ("late audio for a completed turn"). C6/D2. |
| **late final while the target turn has NO bubble yet** | **DEFEAT** — the stale final creates the current turn's bubble with stale text. C5/D1. |
| **late final before any response.created (turn key 0)** | **DEFEAT** — phantom `turn:0` bubble with stale text. C10/D3. |
| late USER-role final over a streaming user bubble | **DEFEAT** (same class). C8. |
| two late finals in a row | first wins (still stale text), second ignored. C9. |
| turn=None message | overwrites the newest streaming turn. C7 — **latent** (gateway always sends an int turn; not reachable). |
| spurious interrupted (no bubble) then the real turn's final | INTERRUPTED bubble is created, then the real final erases the mark. C11a/C11b. |

**The most damaging, fully reachable defeat (D2, `late_final_midstream`)** — the
late r1 final lands *while r2 is still streaming*, so the target bubble is
`STREAMING`, not `FINAL`:

```
gateway -> client (same turn key 2 for two different responses):
  {"delta":"Welcome ",           final:false, turn:2}   # r2, streaming
  {"text":"STALE-R1-TEXT",       final:true,  turn:2}   # r1, LATE  <-- overwrite+finalize
  {"delta":"to class",           final:false, turn:2}   # r2  (dropped: turn now FINAL)
  {"text":"Welcome to class",    final:true,  turn:2}   # r2  (dropped)
store assistant bubbles:
  {"text":"R1 FINAL ANSWER","state":"FINAL","turn":1}
  {"text":"STALE-R1-TEXT", "state":"FINAL","turn":2}    # <-- WRONG; real text lost
```

The learner-visible turn-2 reply is `STALE-R1-TEXT`; r2's real reply
(`Welcome to class`) is **lost**. The mitigation's guard
(`if current["state"] == FINAL: return None`, transcript.py L74-79) only fires
when the target bubble is *already* FINAL; it does nothing for a STREAMING or
absent bubble.

## 3. Is the mitigation sufficient? (explicit judgement)

**No — PARTIALLY CLOSED.** It closes exactly one case, the one named in the
remediation wording: a late final can no longer **rewrite a bubble that is
already FINAL** (control `C12`; and the round-1 B3.2 message pair no longer
corrupts an *existing* final). But the product-observable defect
(**LATE_FINAL_MUTATION = 0 at the client boundary**) remains reachable in two
common shapes:

- **R-F-5 (residual, MAJOR)** — a stale/foreign final that arrives while the
  target turn is **not yet FINAL** (STREAMING, or no bubble yet) either creates
  the turn's bubble with text that does not belong to it, or overwrites the
  streaming bubble and finalizes it early, dropping the real text.
- **R-F-6 (new, MINOR)** — a `transcript.done` arriving before any
  `response.created` is stamped `turn:0` by the gateway and produces a phantom
  `turn:0` bubble.
- **R-F-7 (new, MINOR)** — a spurious `interrupted:true` for the current turn
  (e.g. from a superseded response's late `response.done status=cancelled`)
  creates an `INTERRUPTED` bubble; the real turn's subsequent delta/final then
  **absorbs into it and flips it to FINAL**, erasing the interrupt mark
  (transient wrong state).

**Residual gateway-side attribution inaccuracy (known, documented deferral —
`gateway/app/turns.py` frozen).** The gateway stamps **every** transcript event
with `self._ui_turn`, which advances only on `response.created`
(`_on_qwen_event` L576-581 → `_send_transcript`; `_ui_turn += 1` at L613). A late
`response.audio_transcript.*` (or a late cancelled `response.done` →
`_ui_notify_interrupted()`) for a superseded/cancelled response is therefore
**indistinguishable from the live turn's own transcript** at the client. Honest
quantification of user-visible impact: a cancelled/superseded reply's text can be
shown as the current turn's reply, the current turn's real reply text can be
lost, a transient/incorrect "已打断" mark can appear, and a phantom turn can be
displayed — i.e. **stale/incorrect transcript presentation**, no audio/security
impact (the audio plane is unaffected; see metrics). The consumer-side guard can
only defend the FINAL-rewrite sub-case; it cannot recover correctness for the
creation/streaming sub-cases because the messages carry no generation identity.

## Per-finding verdicts

| Finding | Verdict | Exact case |
|---|---|---|
| **R-F-1** (late final re-attributed to newest turn) | **PARTIALLY CLOSED** | CLOSED: rewrite of an already-FINAL bubble (C12). STILL REPRODUCIBLE: stale final **creates** the current turn's bubble (C5/D1.3) and stale final **overwrites a STREAMING** current turn (C6/D2.2). |
| **R-F-1c** (turn key 0, pre-created) | **STILL REPRODUCIBLE** | C10/D3.1 |
| **R-F-2** (superseded generation's queued frames still drain) | **STILL REPRODUCIBLE (expected, locked)** | Round-1 A2.14; gateway unchanged. |
| **R-F-3** (non-string delta uncounted) | **STILL REPRODUCIBLE (expected, locked)** | Round-1 A6.3; gateway unchanged. |
| **R-F-4** (diag SEND_INTENT_UNRESOLVED, log-only) | **UNCHANGED (INFO)** | — |

## 4. Round-1 suite re-run (123 checks) + metric verdicts

`red_f_round1.py` re-run against the current revision (`e3c9b6c`):
**123 checks, 121 PASS, 2 FAIL** in ~33 s. The 2 FAILs are the gateway-side
attribution assertions `A5.2`/`B3.2` (expected — the gateway is frozen; the
defect was deferred to the consumer).

```
OLD_AUDIO_RESUME = 0              [CONFIRMED]  (12 checks)
LATE_FINAL_MUTATION = 0           [FALSIFIED]  (gateway attribution; 2 checks — deferred)
SESSION_STATE_LEAK = 0            [CONFIRMED]  (14 checks)
GENERATION_OWNERSHIP_FAULT = 0    [CONFIRMED]  (7 checks)
AUDIO_ARCHITECTURE_CHANGED = NO   [CONFIRMED]  (7 checks)   # round-1 extra
```

Round-2 (client boundary):

```
R-F-1 CLIENT-BOUNDARY LATE_FINAL_MUTATION = 0   [FALSIFIED]  (8 checks; failing D1.3, D2.2, D3.1)
R-F-1 MITIGATION (already-FINAL rewrite blocked) [CONFIRMED]  (C1,C2,C3,C4,C12)
```

R-F-2 and R-F-3 are unchanged (locked gateway, expected).

## 5. Frozen-surface confirmation (byte-identical)

```
$ git diff 2fd8d4f..HEAD -- gateway/app/{turns,audio,qwen,ws,protocol,counters}.py
<no output>                      # 0 bytes
$ git diff --stat        -- gateway/app/{turns,audio,qwen,ws,protocol,counters}.py
<no output>                      # working tree also clean
```

sha256[:16] (identical to the round-1 baseline):
`turns 533ca5db18881b0d · audio c2218a2c3fda5200 · qwen 2727bc628c4dce9b ·
ws dde9d427883721c1 · protocol 944e2d5ab4f0c2b1 · counters b435ecafbbe83464`.

Only `client/src/ui/shared/transcript.py` was changed by the remediation commit
for R-F-1 (`git diff 2fd8d4f..HEAD` = the 7-line FINAL-immutability hunk), which
is not a frozen realtime surface.

## NEW findings (round 2)

**R-F-5 · RED-F · round2 · MAJOR · surface: client transcript store
(`client/src/ui/shared/transcript.py::TranscriptStore.apply`, L70-83)**
- Precondition: a stale/foreign final arrives while the target turn is not yet FINAL.
- Repro (deterministic C5/C6; end-to-end D1.3/D2.2):
  `apply(delta "Wel", turn=2)` then `apply(text "STALE-R1-TEXT", final=true, turn=2)`
  → bubble becomes `FINAL` with `STALE-R1-TEXT`; subsequent real turn-2 deltas/final
  are dropped.
- Expected: the current turn's text is never replaced by text that does not belong
  to it; a foreign final does not finalize the live turn.
- Actual: text overwritten/created with stale content; real text lost; bubble
  prematurely FINAL.
- Root cause: the mitigation guard only checks `current["state"] == FINAL`; it has
  no way to tell a stale final from the live turn's own final because the message
  carries no generation identity (gateway re-stamps `turn`).
- Status: OPEN (consumer hardening); root cause on the gateway side is the frozen
  `turn` re-stamping documented above.

**R-F-6 · RED-F · round2 · MINOR · surface: gateway turn keying
(`turns.py::_ui_turn`) observed via the store**
- Precondition: a `response.audio_transcript.done` arrives before any
  `response.created` on the connection.
- Repro (C10/D3.1, mock `precreated_final`): gateway forwards
  `{"text":"PRE-CREATED TEXT","final":true,"turn":0}`; the store materialises a
  phantom `turn:0` bubble.
- Expected: no bubble for a turn that was never announced.
- Actual: phantom `turn:0` bubble presented to the learner.
- Status: OPEN (only reachable via an adversarial/out-of-order upstream).

**R-F-7 · RED-F · round2 · MINOR · surface: client transcript store
(`_apply_interrupted`)**
- Precondition: a spurious `interrupted:true` for the current turn with no
  streaming bubble (e.g. a superseded response's late cancelled `response.done`).
- Repro (C11a/C11b): `apply(interrupted:true, turn=2)` creates an `INTERRUPTED`
  bubble; a later real turn-2 delta+final absorbs into that bubble and flips it to
  `FINAL`, erasing the interrupt mark.
- Expected: an interrupted bubble is not silently rewritten/un-interrupted, and a
  spurious interrupt is not created for a healthy turn.
- Actual: transient/incorrect `INTERRUPTED` state that is later overwritten.
- Status: OPEN. (The `FINAL`-turn case — `C4` — is correctly closed.)

## Explicit judgement on the R-F-1 mitigation

The consumer-side FINAL-immutability guard is a **correct but insufficient**
mitigation. It eliminates the exact "different late final rewrites an
already-completed bubble" symptom, and the interrupt branch correctly refuses to
re-mark a FINAL turn (both confirmed). However, the **product-observable
invariant (LATE_FINAL_MUTATION = 0 at the client boundary) is NOT achieved**:
the same root cause (the frozen gateway stamps any late transcript/terminal with
the newest `turn`) still yields a **wrong learner-visible transcript** whenever
the target bubble is not already FINAL — the common cases being (a) a stale final
that *creates* the current turn's bubble, (b) a stale final that *overwrites a
STREAMING* current turn and finalizes it early (definitive D2 evidence), and (c) a
pre-`response.created` final (phantom `turn:0`). Only a gateway-side attribution
fix (carrying the owning generation/response id onto the transcript turn key) can
close the class; the consumer cannot recover information it never receives.
