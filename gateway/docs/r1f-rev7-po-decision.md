# R-1f REV-7 PRODUCT-OWNER DECISION (persisted artefact)

Persisted by the team-lead on 2026-10-06 for review traceability (the rev-6 reviewer's disclosed
limitation — "the directive is unavailable to me as a separate artefact" — is fixed by this file).
This file is a verbatim copy of the product-owner decision text received for R-1f rev-7.
It is the authoritative input for the rev-7 revision; where it differs from any interim draft,
this text governs.

---

R-1f REV-7 PRODUCT-OWNER DECISION
MULTI-AGENT DESIGN REVIEW ONLY

Proceed with DESIGN REVISION ONLY.

Do NOT implement code.
Do NOT modify runtime config.
Do NOT rebuild/restart containers.
Do NOT touch english-learning-workbench or any protected stack.

==================================================
MULTI-AGENT ROLE SEPARATION
==================================================

Use multiple agents with strict role separation.

Lead:
- ONLY writer to rtl-lab/
- owns revision control, evidence reconciliation and final merge
- must not silently override reviewer findings

Agent A — PACER / CLOCK
READ-ONLY analysis first.
Own:
- 15 ms anti-burst floor
- absolute 20 ms media clock
- slow-send guard
- positive-rate gate
- fatal-stall interaction

Agent B — ACCOUNTING / GENERATION
READ-ONLY analysis first.
Own:
- full-backlog normal-seal edge
- source/framer/frame closures
- residue disposition
- GenerationEnd
- terminal paths

Agent C — CLIENT PLAYOUT
READ-ONLY analysis first.
Own:
- PcmFifo partial starvation observability
- zero-fill telemetry
- TTS playout-session window
- Q1/Q2/client gate semantics

Agent D — STRUCTURE / STATIC TEST
READ-ONLY analysis first.
Own:
- exactly-one encoded downlink store
- removal of legacy dl_q/SENTINEL/drop-oldest paths
- mechanically decidable construction/static test
- single-pacer invariant

Agent F:
- NEW independent instance
- must NOT participate in Part A drafting
- receives only completed rev-7 Part A + read-only evidence/source
- performs adversarial final design review

Lead is the only writer.

==================================================
PRODUCT-OWNER DECISION FOR REV-6 B2
==================================================

Choose option (a).

Normative constants:

MEDIA_FRAME_MS = 20.0
MIN_SEND_START_INTERVAL_MS = 15.0
PACING_SLACK_MS = 5.0

This decision is FINAL for R-1f rev-7.

Do NOT use:

- 18.0 ms
- a 15–18 ms runtime range
- environment-dependent selection
- an acceptance-only E[j] < 2 ms precondition

Rationale:

The existing evidence shows that the 18 ms floor conflicts with the
mandatory positive-rate gate on the real r1d/r1e scheduling envelopes.

The same resampled evidence shows the 15 ms / 5 ms-slack design at
approximately:

r1d ≈ 49.97 fps
r1e ≈ 50.00 fps

Therefore the design uses 15 ms.

15 ms is ONLY the anti-burst safety floor.

The media cadence remains:

20 ms / frame
50 fps target

Absolute media deadlines remain authoritative.

Required gates:

49.5 <= steady_pacer_rate_fps <= 50.5

19.80 <= pacer_mean_inter_send_ms_observed <= 20.20

pacer_min_inter_send_ms_observed >= 14.999

wire_rate_excess_frames_max <= 1

Remove every normative/advisory statement saying:

- 18 ms is the R-1f floor
- widen to 15–16 later if acceptance fails
- acceptance validity depends on E[j] < 2 ms

Wake-overshoot remains diagnostic evidence only.

==================================================
B1 — NORMAL SEAL AT FULL BACKLOG
==================================================

Close the seal-time residue hole.

At normal response seal:

IF:

unsent_backlog_frames < MAX_FUTURE_FRAMES

THEN normal residue processing applies:

0 < N < 960
-> attempt one synthetic tail

BUT IF:

unsent_backlog_frames == MAX_FUTURE_FRAMES
AND
0 < len(dl_buf) < 960

THEN:

1. DO NOT create a synthetic tail frame.
2. DO NOT admit a 1501st frame.
3. Transition exactly once to:

   AUDIO_STORE_CAP_REACHED
   CONTROLLED_TAIL_TRUNCATION

   unless the generation already entered this state.

4. residue_discarded_store_cap_bytes += len(dl_buf)
5. clear dl_buf
6. synthetic_tail_frames does NOT increment
7. synthetic_tail_source_bytes does NOT increment
8. seal the generation
9. enqueue exactly one GenerationEnd
10. allow the already accepted 1500-frame backlog to drain normally

This is NOT safety_truncated_pcm_bytes because these residue bytes were
already admitted.

Add mandatory Test B-prime:

Scenario:

unsent_backlog_frames = 1500
normal response seal occurs
dl_buf contains N where 0 < N < 960

Required:

unsent_backlog_peak_frames <= 1500
residue_discarded_store_cap_bytes += N exactly once
synthetic_tail_frames unchanged
cap_transitions_max_per_generation <= 1
still_buffered_pcm_bytes = 0 at quiescence

source closure residual = 0
framer closure residual = 0
frame disposition residual = 0

==================================================
M1 — SLOW SEND PATH
==================================================

Make slow-success behaviour explicit, implementable and bounded.

Connection state:

send_guard_until = None

For successful send:

T = send_completion_time - send_start_at

IF:

T <= SLOW_SEND_THRESHOLD_MS

normal absolute-deadline scheduling continues.

IF:

5 ms < T <= MAX_REBASE_LATENESS_MS

THEN:

slow_send_events += 1

send_guard_until =
    send_completion_time + MIN_SEND_START_INTERVAL_MS

Break the current clean steady segment.

Rebase the next frame deadline explicitly:

next_deadline =
    send_completion_time + MEDIA_FRAME_MS

The next send must satisfy BOTH:

next_deadline
and
send_guard_until

No catch-up occurs.

Count this phase reset in:

pacer_rebases += 1

IF:

T > MAX_REBASE_LATENESS_MS

THEN the send that just completed is dispositioned normally as SENT,
but the generation immediately enters:

PACER_FATAL_STALL

Then:

- invalidate generation
- flush remaining QUEUED / RESERVED_WAIT frames to
  flushed_pacer_stall_frames
- dispose residue to residue_discarded_pacer_stall_bytes
- cancel upstream once if active
- emit exactly one TTS stop
- pacer_fatal_stalls += 1
- normal acceptance FAILS

A multi-second successful send must never silently rebase and continue.

For failed or SEND_AWAIT-cancelled sends:

keep existing send_failed / outcome_unknown rules

and set:

send_guard_until =
    observation_time + MIN_SEND_START_INTERVAL_MS

==================================================
NO VACUOUS RATE PASS
==================================================

For a normal long-response acceptance run:

at least ONE qualifying clean steady segment with:

steady_segment_frames >= 250

is mandatory.

If no qualifying clean segment exists:

PACING_RATE_EVIDENCE = INSUFFICIENT
NORMAL_LONG_RESPONSE_ACCEPTANCE = FAIL

The positive-rate gate must never PASS vacuously.

==================================================
M2 — CLIENT PARTIAL STARVATION OBSERVABILITY
==================================================

Move the partial-underfill counter to the location where zero padding
actually occurs.

Inside:

PcmFifo.pull(n)

IF:

size == 0

retain the whole-empty behaviour that ultimately produces:

whole_block_zero_fill_count

IF:

0 < available_samples < n

THEN:

filled = available_samples
missing = n - filled

increment:

pcm_fifo_partial_underfill_events += 1
pcm_fifo_partial_zero_pad_samples += missing

Count this exactly where the missing tail is zero-filled inside
PcmFifo.pull.

Do NOT infer it later from callback output length because the callback
already receives a full-length zero-padded array.

The TTS-playout-scoped metric becomes:

tts_playout_partial_zero_pad_samples

=
delta of pcm_fifo_partial_zero_pad_samples during the active client
TTS playout-session window.

Clean long-response acceptance requires:

tts_playout_whole_block_zero_fill_count = 0
tts_playout_partial_zero_pad_samples = 0

Add deterministic client test:

FIFO contains 200 samples
PcmFifo.pull(480)

Required:

returned block length = 480
pcm_fifo_partial_underfill_events += 1
pcm_fifo_partial_zero_pad_samples += 280

and the scoped starvation acceptance gate FAILS.

==================================================
M3 — MECHANICALLY DECIDABLE SINGLE-STORE TEST
==================================================

Replace the vague construction predicate with a deterministic sentinel test.

Drive one synthetic response while the pacer is deliberately held before
consuming the encoded frame.

Configure the test encoder to return one unique sentinel packet:

SENTINEL_ENCODED_PACKET

Then inspect Connection state using an explicit root inventory.

Allowed/exempt roots:

ws
diag
config
uplink_q
dl_buf

Required:

1. future_audio_store exists.

2. SENTINEL_ENCODED_PACKET is present exactly once in:

   future_audio_store

3. Outside the explicitly exempt roots above,
   no other Connection-owned mutable container contains the sentinel packet.

4. Connection/class has no:

   dl_q
   SENTINEL
   _stop_pending
   _enqueue_frame
   _enqueue_sentinel
   _drop_one_non_sentinel
   _put_drop_oldest

5. R-1f downlink source contains no executable reference to the removed
   legacy audio-queue path.

6. audio_out_dropped has no R-1f mutation site.

7. dl_buf contains PCM residue only and satisfies:

   0 <= len(dl_buf) < 960

8. uplink_q remains explicitly outside this test.

This is the mechanically decidable proof of exactly one encoded
downlink store.

==================================================
APPLY ALL 10 CONFIRMED REV-6 MINORS
==================================================

Apply all rev-6 MINOR findings.

At minimum:

1. Canonical frame name:

queued_audio_frames

Use it everywhere.

2. Add:

post_terminal_sends_total

Replace the row-11 journal-only assertion with:

post_terminal_sends_total = 0

No acceptance assertion may rely only on journal text.

3. Barge-in ownership:

BIT1 / pacer cancellation owns resolution of the RESERVED_WAIT head frame.

BIT2 / store flush owns only the remaining QUEUED frames.

Therefore the RESERVED_WAIT head can never be counted twice.

4. Explicitly enumerate:

audio_out_dropped mutation sites

and every current _flush_downlink call site

in the removal/rewrite plan.

Explicitly map legacy:

qwen_closed

to normative reason:

UPSTREAM_CLOSED

5. Add:

active_pacer_tasks
active_pacer_tasks_max

Required:

active_pacer_tasks_max <= 1

6. Define the R-1f real acceptance configuration explicitly:

RTL_DIAG = 1
client gated telemetry = ON
acoustic capture = ON when required
same bridge/client build under test

No acceptance result from a materially different runtime configuration
may certify the shipping build.

7. Client terminology:

The client has a TTS playout SESSION correlated by TTS start/stop.

Do NOT call it the Qwen response generation on the client side.

The client does not carry response_id in the audio path.

8. keep_listening=False:

The playout measurement window must continue through the actual queued
audio drain/clear terminal event.

Do not end the measurement window prematurely merely because a stop
handler returned without clearing the queue.

9. Clean A.2 sampling wording:

Residue disposal itself is NOT a backlog mutation.

AUDIO_STORE_CAP_REACHED is exactly once PER GENERATION.

10. Remove stale historical wording such as:

"Rev 4 requires..."

from current normative Part A.

11. Wake-overshoot diagnostic:

Define its measurement domain clearly.
It remains DIAGNOSTIC ONLY.
Do NOT use E[j] as a shipping acceptance precondition now that the
normative anti-burst floor is 15 ms.

12. Clarify framer assertion wording:

still_buffered_pcm_bytes is a closure TERM.

At generation quiescence:

still_buffered_pcm_bytes = 0

It is not itself "the closure residual".

==================================================
COUNTER / ASSERTION UPDATES
==================================================

Part A /health contract must include at least the new fields:

pcm_fifo_partial_underfill_events
pcm_fifo_partial_zero_pad_samples

post_terminal_sends_total

active_pacer_tasks
active_pacer_tasks_max

slow_send_events

Pacer acceptance:

49.5 <= steady_pacer_rate_fps <= 50.5

19.80 <= pacer_mean_inter_send_ms_observed <= 20.20

pacer_min_inter_send_ms_observed >= 14.999

wire_rate_excess_frames_max <= 1

active_pacer_tasks_max <= 1

Client clean-long-response acceptance:

incoming_queue_dropped_packets = 0
pcm_fifo_dropped_samples = 0
tts_playout_whole_block_zero_fill_count = 0
tts_playout_partial_zero_pad_samples = 0

Terminal invariant:

post_terminal_sends_total = 0

==================================================
REV-7 REVIEW GATE
==================================================

Lead rewrites Part A as rev-7.

No implementation.

Then dispatch a NEW, independent Agent F.

Agent F must NOT read the Part A drafting discussion.

It may read:

- completed rev-7 Part A
- relevant bridge/client source
- raw evidence
- required product-owner decision text if persisted as an artefact

It must attack at least:

1. 15 ms floor + real r1d/r1e resampled envelopes:
   positive-rate gate passes.

2. Legacy 47.4 fps pacer:
   positive-rate gate fails.

3. Normal seal:
   backlog = 1500
   residue = every representative value in 1..959
   no frame 1501
   every byte closes.

4. Slow send:
   T = 10 ms
   explicit completion+15 guard
   visible rebase
   no burst.

5. Very slow successful send:
   T > 250 ms
   PACER_FATAL_STALL.

6. No qualifying >=250-frame clean segment:
   normal long-response acceptance FAILS.

7. PcmFifo partial fill:
   200 / 480
   exactly 280 zero-padded samples counted.

8. Client starvation with zero Q1/Q2 drops:
   starvation gate still FAILS.

9. Sentinel construction test:
   mechanically proves exactly one encoded downlink store.

10. RESERVED_WAIT barge-in:
    head frame counted exactly once.

11. post_terminal_sends_total remains 0.

12. active_pacer_tasks_max <= 1.

13. All three accounting closures are zero for:

    normal completion
    full-backlog normal seal
    barge-in
    send-error
    fatal-stall
    byte-cap failure

14. No R-1f audio_out_dropped mutation remains.

15. Confirm:

    NO source implementation changed
    NO runtime config changed
    NO container rebuilt/restarted
    protected stacks unchanged

Required final output:

DESIGN_REVIEW_BLOCKERS =
DESIGN_REVIEW_MAJORS =
DESIGN_REVIEW_MINORS =
DESIGN_REVIEW = PASS / REVISE

If:

DESIGN_REVIEW_BLOCKERS != 0

STOP.

Do not implement anything.

If:

DESIGN_REVIEW_BLOCKERS = 0

still STOP and report.

Do NOT begin implementation automatically.

Implementation requires a separate explicit product-owner authorisation.

---

End of persisted product-owner decision text.
