# RED-F (Realtime / Session State Machine) — Closure Re-Attack, Round 3

- **Agent**: RED-F (Realtime / Session State Machine) — round 3 (closure)
- **Trigger**: the product owner lifted the deferral and **authorized one
  narrowly-scoped change to `gateway/app/turns.py` for UI transcript /
  interrupt attribution only** (R-F-1 / R-F-5).
- **Fix commit**: `e9746ad` (fix + suite updates; start commit `7e6dbab`).
- **Hard locks**: read-only on product source by the attacking agent; local
  mock / deterministic harness only (no NAS sidecar contact, no primary);
  **no real-Qwen session** (budget 4/4 used, remaining 0).
- **Evidence scripts**: `gateway/tests/adversarial/red_f/red_f_round3.py` (new
  closure suite) + updated `red_f_round1.py` / `red_f_round2.py` semantics;
  pre-fix reproduction outputs kept under
  `docs/engineering/product-v1/adversarial/evidence/turns-fix/` (local
  convention, not committed).
- **Suite result**: round 1 **123/123**, round 2 **20/20**, round 3 **27/27** —
  all PASS; every metric group CONFIRMED; `R-F-1 = CLOSED`, `R-F-5 = CLOSED`.

## 1. The authorized fix — exact scope and semantics

`git show e9746ad -- gateway/app/turns.py` touches **five hunks, all inside UI
transcript / interrupted-notice attribution** (no audio, pacing, generation
ownership, cancellation or accounting line changed):

1. **New `Connection._ui_owns_generation(gen)`** — a response owns the
   live/current UI turn iff it is the **most recently created response** on the
   connection (`gen is self._recent_gen`).
2. **Assistant transcript forwarding** (`_on_qwen_event`): an event **with a
   `response_id`** is forwarded only for the owning response; superseded /
   never-created rids are dropped (`ui transcript dropped (stale rid=…)`).
   Id-less events keep the pre-existing tolerance — the guard applies only
   *"if response_id is present"*.
3. **`_count_response_done(status, ui_gen=None)`** — the `response.done
   {status=cancelled}` interrupted notice is emitted **only when the cancelled
   response still owns the live generation**; the owning turn key is **frozen at
   decision time** (`_ui_notify_interrupted(turn=self._ui_turn)`) so the
   fire-and-forget send cannot drift onto a newer `response.created`.
4. Call-site passes for the tombstone / superseded / seal paths (`ui_gen=gen`).

### Why "most recently created" is the correct ownership predicate

Three independent constraints pin the predicate (verified against the suites,
not assumed):

- **Post-seal transcripts of the newest response must still forward.** In the
  `clean_long` ordering (`CLIENT_UI_INTEGRATION`), the assistant transcript
  delta/final arrive **after** `response.done`; a stricter "current AND
  non-terminal" predicate would drop them and break the accepted suite.
- **The legit interrupt must survive the tombstone path.** In `rapid_barge`
  (`CLIENT_UI_INTEGRATION`), the barge-in invalidates the newest response
  locally, then its cancelled `response.done` arrives; a predicate keyed on
  `current_resp_id`/non-terminal would suppress the honest interrupted notice
  and break the suite.
- **The defect class is cross-turn mutation.** Both proven attacks are
  *supersession* attacks (a newer `response.created` exists); the newest-created
  predicate closes exactly that class while keeping every pinned legit path.

## 2. Pre-fix reproduction (recorded before modification)

Run on the pristine tree (`7e6dbab`, turns.py `533ca5db…`):

- `RED_F_ROUND1`: **123 checks, 121 PASS, 2 FAIL** — `A5.2` / `B3.2`
  (`LATE_FINAL_MUTATION=0` **FALSIFIED**). Exact stream for the late-final
  fixture: `{"text":"late-final-text","final":true,"turn":2}` — a **superseded
  r1 final stamped as the newest (r2) turn**, plus `{"interrupted":true,
  "turn":2}` — a **spurious interrupt on the healthy new turn**.
- `RED_F_ROUND2` end-to-end: **20 checks, 17 PASS, 3 FAIL** —
  `D1.3` (stale text presented as a turn's reply), `D2.2` (the learner-visible
  turn-2 reply was `STALE-R1-TEXT`; the real reply lost), `D3.1` (phantom
  `turn:0` bubble from a pre-created final). Metric
  `R-F-1 CLIENT-BOUNDARY LATE_FINAL_MUTATION=0` **FALSIFIED**.

## 3. Post-fix re-attack — the exact fixed cases now defended

All three suites re-run on `e9746ad`; the four checks that previously asserted
the **defect's existence** were updated to the **post-fix drop semantics**
(A5.1 / B3.1 in round 1; D1.1 / D1.2 titles in round 2 — each annotated in
place). Exact post-fix client-bound streams (round 2, Part D):

- **D1 (`late_done_after_new`)** — `[]`: the late final AND the late cancelled
  done are both dropped; zero transcript messages reach the client.
- **D2 (`late_final_midstream`)** — r1's own stream stays on turn 1
  (`R1 partial ` → `R1 FINAL ANSWER`); r2's real stream stays on turn 2
  (`Welcome ` → `to class` → `Welcome to class`); `STALE-R1-TEXT` is gone.
- **D3 (`precreated_final`)** — no `PRE-CREATED TEXT`, no `turn:0`; the real
  turn's post-seal text (`real turn text`, turn 1) still forwards.

Round-3 deterministic attacks (Part A) + e2e controls (Part B) + learner-visible
replay (Part C): **27/27**. Notably the e2e **B4 control caught a real race the
unit checks could not**: the interrupted notice for a barge-in-cancelled newest
response was initially stamped with the *newest* `_ui_turn` because the
fire-and-forget task read `_ui_turn` at *send* time; the decision-time turn
freeze (§1.3) closed it — the notice now carries the cancelled response's **own**
turn (1), deterministically.

## 4. Legit-path non-regression (explicit controls)

| control | evidence |
|---|---|
| normal delta/final forwarding (owning response) | R3-A4.1 |
| post-seal newest-response final forwarding (`clean_long` ordering) | R3-A5.1, R3-B3.2, `CLIENT_UI_INTEGRATION 19/19` |
| legit interrupt on barge-in (tombstone path, own turn, no fabricated text) | R3-A6.1, R3-B4.1/2, `CLIENT_UI_INTEGRATION 19/19` |
| mixed storm: stale r1 suppressed + owning r2 still notifies | R3-A7.1/2 |
| id-less output transcript tolerance preserved | R3-A8.1 |
| learner store: real turn-2 text shown; no stale text; no phantom turn | R3-C1.1/2, R3-C2.1/2, R3-C3.1 |

## 5. Audio surface untouched

- Diff audit: **no audio/pacing/generation/cancellation/accounting line in the
  `turns.py` diff** (changed lines are only the `_ui_*` helper, the transcript
  forwarding block, `_count_response_done` and its call sites).
- Round-1 metric groups: `OLD_AUDIO_RESUME=0` **CONFIRMED** (12 checks),
  `GENERATION_OWNERSHIP_FAULT=0` **CONFIRMED** (7), `AUDIO_ARCHITECTURE_CHANGED
  =NO` **CONFIRMED** (ARCH1–7), `SESSION_STATE_LEAK=0` **CONFIRMED** (14).
- Round-3 audio control: late superseded delta still guard-dropped, never
  admitted (R3-A9.1).

## 6. Frozen-surface byte-identity

```
git diff 7e6dbab..HEAD -- gateway/app/{audio,qwen,ws,protocol,counters}.py   # empty
git diff 2fd8d4f..HEAD -- gateway/app/{audio,qwen,ws,protocol,counters}.py   # empty
```

`turns.py` `533ca5db…` → `5c3f85e4…`; the other five files unchanged since the
pre-run baseline. `TURNS_PY_CHANGE_SCOPE = UI_TRANSCRIPT_ATTRIBUTION_ONLY`.

## 7. Official closure matrix (all on the committed tree)

| suite | result |
|---|---|
| `ADVERSARIAL_REPAIR_TESTS` | **123/123** |
| `R1F_REGRESSION` | 179/180 (1 = documented macOS dev-libopus `OpusError` env sentinel) |
| `BEHAVIOR1_TESTS` | **111/111** |
| `CLIENT_UI_TESTS` | **48/48** |
| `GUI_TRANSCRIPT_LIVE_TESTS` | **25/25** |
| `CLIENT_UI_INTEGRATION` | **19/19** |
| `PRODUCT_V1_INTEGRATION` | **33/33** |
| `CONCURRENCY_TESTS` (boundary C1–C6 + H13 + I10 + RED_G_ROUND2) | **23/23 + 45/45** |
| `RECONNECT_TESTS` (boundary R1–R4 + PV1 H12 + MVP I12) | PASS |
| `BARGE_IN_TESTS` (R1F barge/abort + MVP I9 + boundary F8) | PASS |
| `RED_F_ROUND1` | **123/123** (LATE_FINAL_MUTATION=0 CONFIRMED) |
| `RED_F_ROUND2` | **20/20** (client-boundary LATE_FINAL_MUTATION=0 CONFIRMED) |
| `RED_F_ROUND3` | **27/27** (R-F-1 CLOSED · R-F-5 CLOSED) |

## 8. Isolated test sidecar rebuilt from the corrected tree

- Staged tree `sha256 89bfd121…` verified on both ends; NAS `app/turns.py`
  `5c3f85e4…` == Mac (guard present).
- Rebuilt image `sha256:362f9467…`; **PRODUCT_V1_STRUCTURAL_PROBE: 65 checks,
  65 PASS, 0 FAIL** (mock mode, no Qwen session).
- Returned to the armed state: `QV1_QWEN_MODE=real`, `status=ok`,
  `qwen_connected=0`, `qwen_sessions=0`; rollback tag
  `xiaozhi-product-v1-sidecar:pre-closure` (`bcc71e78…`).
- Isolation: primary realtime / Workbench / accepted MVP / legacy stacks —
  `StartedAt` and `RestartCount=0` unchanged; no Qwen session opened; Mac client
  config `fa61ca44…` untouched; `py-xiaozhi` not launched.

## 9. Final adversarial verdicts

- Independent RED-F re-attack agent (fresh instance, read-only, no Qwen):
  **RED_F = PASS** — re-ran all three suites (123/123 · 20/20 · 27/27 verbatim),
  then attacked the guard with **28 NEW variants + 3 property-storm checks**
  (duplicate-created re-arm, transcript *delta* path, interleaved storms,
  duplicate terminals, sealed-mid-stream supersession, ghost rids, id-less
  tolerance, turn-key drift probes, 400-op scripted storm with a leak
  detector) — **all PASS**, 0 cross-rid / cross-turn leakage. Its raw report:
  `evidence/turns-fix/red_f_reattack_agent.md` (local). Informational
  observations (none a defeat of the R-F-1/R-F-5 threat model):
  - **ND-1** — a *duplicated* `response.created` for an already-superseded rid
    re-arms that rid as newest-created (both UI and the pre-existing audio gen
    selection). Requires a malformed upstream; the duplicate-created behaviour
    is pre-existing and pinned by round-1 `A2.15/A2.16`. Out-of-threat-model.
  - **ND-2** — a duplicated cancelled terminal for the *owning* response emits
    the notice once per terminal; the client store treats the second as a no-op
    (learner sees exactly one INTERRUPTED bubble). Owning response only — the
    R-F-7 assertion (no notice for a *superseded* response) is not violated.
  - **ND-3** — a non-string/unhashable `response_id` on a transcript event is
    now *dropped via a contained upstream exception* (`qwen._handle_text`
    try/except) instead of being forwarded; text is never emitted, the reader
    loop is unaffected. Same contained class as the documented `R-F-3/A6.3`
    (non-string delta). Strictly safer than pre-fix for this threat model.
- Independent cross-check agent: see addendum below (pending at first writing).
- `R-F-1 = CLOSED` · `R-F-5 = CLOSED` · `BLOCKERS_OPEN = 0` · `MAJORS_OPEN = 0`.

### Addendum — independent verification results

**Independent cross-check agent: CROSS_CHECK = PASS.** (Raw report:
`evidence/turns-fix/cross_check_agent.md`, local.) Key results, all derived
independently (own harness driving `app.turns.Connection` directly; the red_f
suites were only re-executed, never imported for its reproduction):

- **Hunk review APPROVED** — 4 hunks enumerated; every changed line is UI
  transcript / interrupted-notice attribution; counter accounting unchanged
  (both `responses_cancelled`/`responses_completed` increments remain
  unconditional — only the UI notice call is gated); zero forbidden
  audio/pacing/generation tokens in added lines. The "most-recently-created"
  predicate is explicitly assessed as the correct (and necessary) choice vs
  `_current_gen`, with the same reasoning as §1.
- **Frozen files byte-identical** — `git diff` empty vs both `7e6dbab` and
  `2fd8d4f`, plus identical blob hashes for all five files.
- **Client/modules/admin untouched** — `git diff 7e6dbab..HEAD` empty.
- **Own fixtures a–f: 17/17 PASS** — superseded late final/delta dropped;
  superseded cancelled done → no notice; owning cancelled → exactly one notice
  (own turn, null text); post-seal own final forwarded; id-less forwarded;
  ghost rid dropped. Predicate probes p1–p8 all PASS (incl. `_recent_gen`
  stability across seal / listen_start and the rapid-barge legit interrupt).
- **`CLIENT_UI1_INTEGRATION 19/19`** and **`RED_F_ROUND3 27/27`** re-executed by
  the second agent.
- **Deployed sidecar** — `/app/app/turns.py` sha256 `5c3f85e4…` == local;
  image `362f9467…`; `QWEN_MODE=real`; health `qwen_connected=0`,
  `qwen_sessions=0` — no session opened.
- Two LOW / informational **pre-existing** edge observations (E1: a
  contradictory duplicate `cancelled` after `completed` for the same rid still
  notifies; E2: a post-`close()` cancelled done is swallowed by the closed
  socket) — both stamp the response's **own** turn, identical to pre-fix
  behaviour, not required to change by the directive (hardening would be out of
  the authorized scope). Recorded, not actioned.

**Final closure verdicts:** `RED_F = PASS` · `CROSS_CHECK = PASS` ·
`R-F-1 = CLOSED` · `R-F-5 = CLOSED` · `BLOCKERS_OPEN = 0` · `MAJORS_OPEN = 0`.
