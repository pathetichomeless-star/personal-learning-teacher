# R-1f REV-9 PRODUCT-OWNER FINAL LOCAL DESIGN CORRECTION (persisted artefact)

Persisted by the team-lead on 2026-10-06 for review traceability (same practice as the rev-7/rev-8
decision files). This file is a verbatim copy of the product-owner correction text received for
R-1f rev-9. It is the authoritative input for the rev-9 revision; where it differs from any draft
or kit, this text governs. The rev-8 architecture is FINAL; the locked list below is NOT reopenable.

---

R-1f REV-9 PRODUCT-OWNER FINAL LOCAL DESIGN CORRECTION
MULTI-AGENT DESIGN REVIEW ONLY

Rev-8 Agent F review is ACCEPTED.

Current verdict:

DESIGN_REVIEW_BLOCKERS = 1
DESIGN_REVIEW_MAJORS   = 1
DESIGN_REVIEW_MINORS   = 5
DESIGN_REVIEW          = REVISE

Proceed with ONE FINAL LOCAL DESIGN CORRECTION ROUND.

DO NOT implement code.
DO NOT modify runtime config.
DO NOT rebuild/restart containers.
DO NOT touch english-learning-workbench or protected stacks.

Rev-8 architecture remains accepted.

LOCKED — DO NOT REOPEN:

MEDIA_FRAME_MS = 20.0
MIN_SEND_START_INTERVAL_MS = 15.0
PACING_SLACK_MS = 5.0

Also do NOT reopen:

- collections.deque single encoded downlink store
- SEND_FORBIDDEN / SEALED_DRAINING split
- byte-cap 12-step lifecycle
- media-clock-epoch wire-rate definition
- wire_rate_excess_frames_max <= 1
- per-segment extrema acceptance
- mechanical AST rule
- PcmFifo partial-underfill counters
- slow-send state machine

This is a LOCAL correction only.

==================================================
ROLE SEPARATION
==================================================

Lead:
- only writer
- owns final merge and provenance
- must record every correction explicitly

Agent A — PACER / EPOCH:
- E4 correction
- wire-rate regression proof
- pacing numeric hygiene

Agent B — ACCOUNTING REGRESSION:
- READ-ONLY
- verify no rev-9 correction damages closures / terminal semantics

Agent C — CLIENT PLAYOUT:
- T2 stop/empty race
- FIFO terminal semantics
- destructor enumeration

Agent D — STRUCTURE / DOCUMENT HYGIENE:
- removal-list correction
- static text / AST consistency
- duplicate/orphan cleanup

Agent F:
- NEW independent instance
- must NOT participate in drafting
- receives only completed rev-9 Part A + persisted PO rev-9 decision +
  read-only source/evidence
- adversarially reviews the completed design

==================================================
BLOCKER B-1
E4 MEDIA-CLOCK EPOCH CREATION
==================================================

Accept Agent F's finding.

Replace the rev-8 E4 definition:

"E4 — pacer restart after cancel/stall"

with:

E4 — EVERY PACER TASK START OTHER THAN E1

Normative meaning:

E1:
the connection's FIRST pacer task start.

E4:
EVERY subsequent pacer task start, regardless of why the previous pacer
ended, including:

- normal GenerationEnd drain
- ordinary queue drain / pacer exit
- cancel
- stall
- send-error cleanup
- barge-in cleanup
- any later legitimate pacer recreation

At EVERY E4:

epoch_ordinal += 1
media_epoch = monotonic_now()
frame_index = 0
sent_in_epoch = 0

and the current clean steady segment begins inside the new epoch.

There is no state in which:

media_epoch is re-anchored
but
sent_in_epoch / epoch_ordinal are inherited from the previous pacer task.

A normal sequence:

response 1
-> pacer drains
-> pacer exits
-> response 2
-> _ensure_pacer creates new pacer task

MUST therefore create E4 before response-2's first send.

Keep E2 and E3 unchanged.

Require Agent F to re-prove:

wire_excess(t) <= 0

for E1, E2, E3 and corrected E4.

==================================================
MAJOR M-1
T2 CLIENT WINDOW — FIFO ALREADY EMPTY AT TTS STOP
==================================================

Accept Agent F's race finding.

Do NOT introduce an arbitrary 500 ms timer.

Use a deterministic FIFO-state rule.

For keep_listening=False / T2 handling, when the client processes the TTS
stop for the active TTS playout session:

Atomically snapshot, for the SAME pcm_fifo_instance_id:

- FIFO size
- pcm_fifo_partial_underfill_events
- pcm_fifo_partial_zero_pad_samples
- pcm_fifo_drained_to_empty_events
- pcm_fifo_dropped_samples
- all other scoped client acceptance counters

Then apply exactly ONE of two T2 branches.

--------------------------------------------------
T2-A — FIFO ALREADY EMPTY AT STOP
--------------------------------------------------

IF:

fifo_size_at_stop == 0

THEN:

end the active TTS playout measurement window IMMEDIATELY at the
stop-processing snapshot.

Label:

T2_EMPTY_AT_STOP

No future:

pcm_fifo_drained_to_empty_events

edge is required.

A later session's push/pull MUST NOT be allowed to close or alter this
already-closed window.

The scoped deltas are computed from:

window-start snapshot
to
T2_EMPTY_AT_STOP snapshot

for the same pcm_fifo_instance_id only.

--------------------------------------------------
T2-B — FIFO NON-EMPTY AT STOP
--------------------------------------------------

IF:

fifo_size_at_stop > 0

THEN:

record:

t2_stop_fifo_instance_id
t2_stop_drained_edge_baseline =
    pcm_fifo_drained_to_empty_events at stop

Keep the window open until the FIRST edge satisfying:

same pcm_fifo_instance_id

AND

pcm_fifo_drained_to_empty_events
>
t2_stop_drained_edge_baseline

The end snapshot occurs AFTER all counters caused by that draining pull
have been updated.

Label:

T2_DRAIN_AFTER_STOP

A drain edge belonging to a later TTS session MUST NOT close this window.

If a new TTS start occurs before T2-B closes:

retain the existing T4 supersession rule:

- if the old session is already drained/cleared, close correctly;
- if old queued audio remains, client half = INVALID.

Session identity and FIFO instance identity must both match.

This completely replaces the ambiguous "first new drain edge after stop"
wording.

==================================================
MINOR mi-1
A.16 ARITHMETIC
==================================================

Correct the slack-5 transcription.

For:

20.0023 ms

the rate is approximately:

49.994 fps

or:

49.99 fps

when shown to two decimals.

Do NOT state 49.97 fps for 20.0023 ms.

This correction is numerical hygiene only and does not affect the gate.

==================================================
MINOR mi-2
WAKE-OVERSHOOT CANONICAL EVIDENCE
==================================================

The rev-8 pinned per-pair estimator remains normative:

delta =
gap - 20 - T(later frame)

when matching T exists,

otherwise:

gap - 20 - run_mean_T

Rev-9 SHALL use the independently reproducible values from that pinned
estimator as the canonical evidence:

mean delta:

r1e_mock = 1.3858 ms
r1d_real = 3.3237 ms
r1e_real = 2.4710 ms

median delta:

r1e_mock = 1.0270 ms
r1d_real = 1.0845 ms
r1e_real = 1.2100 ms

fraction delta > 2 ms:

r1e_mock = 7.5 %
r1d_real = 22.4 %
r1e_real = 14.9 %

Use these consistently in A.1 / A.5 / A.16.

This rev-9 correction supersedes the earlier approximate
r1d = 3.298 ms figure where the pinned estimator is being quoted.

The load-bearing conclusion remains unchanged:

all observed mean deltas are well below

PACING_SLACK_MS = 5.0

Wake overshoot remains DIAGNOSTIC ONLY.

Do NOT reopen the 15 ms floor.

==================================================
MINOR mi-3
REMOVAL LIST LINE ACCURACY
==================================================

Correct the A.3 "all dl_q uses" enumeration.

The exact direct dl_q occurrences are the AST-verified direct occurrences.

Do NOT list:

turns.py:533
turns.py:555
turns.py:559

as direct dl_q uses when they access the local alias q.

They remain covered by the separate:

diag queue fields / rewritten queue-access logic

entry.

Do not alter the actual removal scope.

This is documentation line-accuracy only.

==================================================
MINOR mi-4
DOCUMENT HYGIENE
==================================================

Remove the duplicated consecutive A.12 sentence:

"If no session start is observable for the run..."

Keep exactly one authoritative copy.

Remove / renumber the orphaned A.3 marker:

"4. legacy_drop_oldest_calls remains useful..."

so the surrounding normative structure is syntactically coherent.

Run a final heading / numbering / duplicate-paragraph audit after merge.

==================================================
MINOR mi-5
AudioCodec.__del__ EMERGENCY CLEAR
==================================================

The T1–T4 normal telemetry terminal-event list must not falsely claim that
AudioCodec.__del__ is covered by those normal paths.

Add explicit abnormal-shutdown semantics:

AudioCodec.__del__ is an EMERGENCY DESTRUCTION path.

It is NOT a clean T1/T2/T3/T4 certification terminal.

If __del__ occurs while an R-1f TTS playout measurement window is active:

CLIENT_TELEMETRY_INVALID = 1

and the client half of that acceptance run is INVALID.

It MUST NOT silently clear the FIFO and allow the run to claim clean
client telemetry.

If __del__ occurs only after the measurement window has already closed:

it has no effect on that completed window.

Do not require destructor-time I/O or logging.

This is an integrity classification rule, not a new normal shutdown path.

==================================================
REV-9 REGRESSION REQUIREMENTS
==================================================

The following rev-8 results must remain unchanged:

- sentinel correct implementation PASS
- rogue second holder FAIL
- normal SEALED_DRAINING backlog drain legal
- post_terminal_sends_total = 0
- all 8 SEND_FORBIDDEN transitions before await
- byte-cap RESERVED_WAIT closure
- byte-cap SEND_AWAIT INVALID closure
- byte-cap no-head closure
- early/bursting sender detected
- bad 49.0 fps segment detected by extrema
- all-good multiple segments pass
- AST getattr fixture FAIL
- docstring-only legacy tokens PASS
- FIFO 200/480 = +280 partial zero-pad
- FIFO instance rebuild cannot create negative scoped delta
- T=10 ms slow-send guard passes
- all accounting closures remain zero on their specified paths
- 15 ms / 20 ms / positive-rate constants unchanged

==================================================
MANDATORY REV-9 AGENT F ATTACKS
==================================================

Fresh Agent F must execute at least:

1. First connection pacer start:
   classified E1.

2. Normal response-1 drain -> pacer exits -> response-2 pacer start:
   response-2 start is E4;
   epoch_ordinal increments;
   sent_in_epoch resets to 0;
   no false wire excess.

3. Cancel -> pacer recreation:
   new start is E4.

4. Stall -> pacer recreation:
   new start is E4.

5. Re-prove wire_excess <= 0 for E1/E2/E3/E4.

6. TTS stop arrives when FIFO already empty:
   window closes immediately as T2_EMPTY_AT_STOP;
   no later drain edge required.

7. TTS stop arrives with FIFO non-empty:
   window remains open;
   closes on same-instance drain edge;
   end snapshot includes the final pull's partial-zero-pad counters.

8. Old T2-B window followed by new TTS session before old drain:
   later session's drain edge MUST NOT close the old window;
   existing T4 rule must decide clean close vs INVALID.

9. FIFO instance changes during T2 wait:
   cross-instance closure is rejected / CLIENT_TELEMETRY_INVALID.

10. __del__ during active measurement window:
    client half INVALID;
    no clean certification.

11. __del__ after already-closed window:
    prior result unchanged.

12. Verify 20.0023 ms arithmetic.

13. Recompute the pinned delta estimator and confirm the rev-9 canonical
    evidence values/tolerance.

14. Verify the corrected direct dl_q line inventory.

15. Verify duplicate A.12 sentence and orphan A.3 numbering are removed.

16. Re-run the rev-8 sentinel / AST regression attacks.

17. Re-run byte-cap three-case closure tests.

18. Re-run multi-segment rate extrema attacks.

19. Confirm all three accounting closures remain zero on every previously
    passing path.

20. Confirm:

    MEDIA_FRAME_MS = 20.0
    MIN_SEND_START_INTERVAL_MS = 15.0
    PACING_SLACK_MS = 5.0

    unchanged.

21. Confirm no implementation source changed,
    no runtime config changed,
    no container rebuilt/restarted,
    protected stacks untouched.

==================================================
REV-9 REVIEW GATE
==================================================

Lead rewrites Part A as rev-9.

Then dispatch a NEW independent Agent F.

Required final output:

DESIGN_REVIEW_BLOCKERS =
DESIGN_REVIEW_MAJORS =
DESIGN_REVIEW_MINORS =
DESIGN_REVIEW = PASS / REVISE

STOP AFTER THE REVIEW.

If:

DESIGN_REVIEW_BLOCKERS != 0

STOP.

If:

DESIGN_REVIEW_BLOCKERS = 0

STILL STOP.

DO NOT IMPLEMENT AUTOMATICALLY.

Return the completed rev-9 design and independent review first.

Implementation requires a separate explicit product-owner authorization.

---

End of persisted product-owner correction text.
