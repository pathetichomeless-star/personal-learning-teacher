# R-1f REV-8 PRODUCT-OWNER DESIGN CORRECTION (persisted artefact)

Persisted by the team-lead on 2026-10-06 for review traceability (same practice as
`r1f-rev7-po-decision.md`). This file is a verbatim copy of the product-owner correction text
received for R-1f rev-8. It is the authoritative input for the rev-8 revision; where it differs
from any interim draft or kit, this text governs. The rev-7 core architecture (15 ms floor) is
FINAL and not reopened.

---

R-1f REV-8 PRODUCT-OWNER DESIGN CORRECTION
MULTI-AGENT DESIGN REVIEW ONLY

Rev-7 Agent F review is ACCEPTED.

Current verdict:

DESIGN_REVIEW_BLOCKERS = 3
DESIGN_REVIEW_MAJORS   = 3
DESIGN_REVIEW_MINORS   = 10
DESIGN_REVIEW          = REVISE

Continue DESIGN REVISION ONLY.

DO NOT implement code.
DO NOT modify runtime config.
DO NOT rebuild/restart containers.
DO NOT touch english-learning-workbench or protected stacks.

The rev-7 core architecture remains accepted:

MEDIA_FRAME_MS = 20.0
MIN_SEND_START_INTERVAL_MS = 15.0
PACING_SLACK_MS = 5.0

Do NOT reopen the 15 ms decision.

The rev-7 evidence already established:

- compliant 15 ms deadline pacer passes the positive-rate design
- legacy ~47.4 fps pacer fails
- B1 full-backlog seal-time residue rule is sound
- slow-send / fatal-stall state machine is directionally sound
- PcmFifo partial-underfill observability is sound

Rev-8 is a LOCAL CORRECTION ROUND.

==================================================
ROLE SEPARATION
==================================================

Use the same strict architecture:

Lead:
- only writer
- merges and records all decisions explicitly

Agent A:
- pacer / wire-rate / rate observables

Agent B:
- terminal semantics / byte-cap / accounting

Agent C:
- client telemetry / FIFO session window

Agent D:
- sentinel / AST / mechanical verification

Agent F:
- NEW independent reviewer
- must not participate in drafting

==================================================
BLOCKER B1
SINGLE-STORE SENTINEL TEST
==================================================

Accept Agent F's finding.

The rev-7 asyncio.Queue/gc procedure is withdrawn.

Rev-8 SHALL PIN THE DIRECT ENCODED-FRAME STORE TYPE:

future_audio_store = collections.deque

The deque itself is the ONE AND ONLY mutable container that directly
holds encoded downlink StoreItem / Opus packet objects.

Do NOT use asyncio.Queue as future_audio_store.

Waiting/wakeup may use:

asyncio.Event
or
asyncio.Condition

but such synchronization primitives MUST NOT hold encoded audio frames.

No wrapper object may contain another encoded-frame deque/queue internally
unless future_audio_store itself IS that canonical deque.

--------------------------------------------------
REV-8 SENTINEL HARNESS
--------------------------------------------------

This is a separate NON-ACCEPTANCE construction harness.

RTL_DIAG = unset is allowed for this harness only.

It does NOT certify the shipping acceptance configuration.

Test procedure:

1. Instantiate Connection.

2. Monkeypatch / harness-control pacer startup so that the pacer DOES NOT
   consume from future_audio_store during inventory.

   Do NOT replace store.get().
   Do NOT introduce a consumer wrapper.

   The hold point is before any popleft()/dequeue operation.

3. Encoder returns one identity-unique:

   SENTINEL_ENCODED_PACKET

4. Drive exactly one complete downlink frame.

5. Verify:

   future_audio_store is collections.deque

   len(future_audio_store) == 1

   future_audio_store[0] is SENTINEL_ENCODED_PACKET
   or the StoreItem payload field is identity-equal to that sentinel,
   depending on the final StoreItem representation.

6. Root inventory MUST be seeded from:

   list(vars(conn).values())

   NOT from the conn.__dict__ object itself.

7. Explicit exempt roots:

   ws
   diag
   config
   uplink_q
   dl_buf

   Prune their subtrees by identity.

8. The canonical encoded-frame holder is future_audio_store.

   Search all other non-exempt Connection-owned mutable containers for the
   sentinel identity.

   Required:

   exactly one holder exists
   and it is future_audio_store.

9. Do NOT count coroutine locals or transport internals.

10. The test must not depend on asyncio.Queue iteration semantics,
    asyncio.Queue._queue internals, or Python-version-specific
    gc.get_referents(dict) behaviour.

This replaces rev-7 A.3 Steps 0–4 where incompatible.

==================================================
BLOCKER B2
POST-TERMINAL SEND SEMANTICS
==================================================

Accept Agent F's finding.

Do NOT make normal seal wait until quiescence to become sealed merely to
satisfy the old counter.

Normal seal / controlled STORE_CAP seal MUST continue to allow all already
accepted playable frames to drain.

Therefore redefine the invariant domain.

Introduce the explicit state concept:

SEND_FORBIDDEN

A generation enters SEND_FORBIDDEN on FLUSH-TYPE terminal transitions:

BARGEIN
ABORT
CLOSE
LISTEN_START
UPSTREAM_CLOSED
SEND_ERROR
PACER_STALL
BYTE_CAP_FAILURE

A generation does NOT enter SEND_FORBIDDEN merely because it becomes:

SEALED_DRAINING

by normal completion or controlled STORE_CAP completion.

Normal seal and STORE_CAP seal may therefore:

- reject all future source audio
- tombstone/guard late upstream events
- drain already accepted playable audio
- consume GenerationEnd
- emit one TTS stop

without violating the send invariant.

Keep the field name required by the prior PO decision:

post_terminal_sends_total

but redefine it normatively as:

increment exactly when send_bytes is entered for a frame whose owning
generation has already entered SEND_FORBIDDEN.

Do NOT increment it for legal SEALED_DRAINING backlog drain.

Required:

post_terminal_sends_total = 0

for all normal acceptance runs.

Update all wording that currently defines it as:

"is_locally_terminal at send_start_at"

because that predicate is too broad.

Also define:

generation.send_forbidden = bool

and make the transition explicit before any await on every flush-type path.

==================================================
BLOCKER B3
BYTE-CAP IN-FLIGHT HEAD
==================================================

Accept Agent F's finding.

BYTE_CAP_FAILURE must participate in the same in-flight lifecycle rules as
the other flush-type terminal reasons.

When AUDIO_STORE_BYTE_CAP_REACHED fires:

1. Mark the generation SEND_FORBIDDEN before the first await.

2. Cancel the pacer with:

   reason = BYTE_CAP_FAILURE

3. If the pacer head is in RESERVED_WAIT:

   it is KNOWN UNSENT

   flushed_byte_cap_failure_frames += 1

4. If the pacer head is in SEND_AWAIT:

   send_outcome_unknown_frames += 1

   run = INVALID

5. Flush all remaining QUEUED accepted frames to:

   flushed_byte_cap_failure_frames

6. The triggering oversized encoded packet is also dispositioned exactly
   once into:

   flushed_byte_cap_failure_frames

   and is never stored.

7. Residue:

   residue_discarded_byte_cap_failure_bytes

8. cancel_upstream_once()

9. exactly one TTS stop

10. byte_cap_failures += 1

11. normal acceptance FAILS

12. quiescence requires:

    queued_audio_frames = 0
    in_flight_frames = 0
    still_stored_frames = 0
    still_buffered_pcm_bytes = 0

Add BYTE_CAP_FAILURE to the A.4.C RESERVED_WAIT known-unsent reason set.

Add a mandatory byte-cap attack with BOTH cases:

A. head in RESERVED_WAIT
B. head in SEND_AWAIT

and verify the complete disposition equation in each case.

==================================================
MAJOR M1
WIRE-RATE EXCESS METRIC
==================================================

Accept Agent F's mathematical finding.

Do NOT loosen the product gate merely to 2.

Keep:

wire_rate_excess_frames_max <= 1

but redefine the metric against the actual MEDIA CLOCK EPOCH rather than
the first observed send.

For each media-clock epoch:

epoch_t = media_epoch

permitted(t) =
    max(0, 1 + floor((t - epoch_t) / MEDIA_FRAME_MS))

sent_in_epoch(t) =
    number of confirmed audio send starts belonging to that epoch
    up to time t

wire_excess(t) =
    sent_in_epoch(t) - permitted(t)

wire_rate_excess_frames_max =
    maximum wire_excess(t) across all epochs in the scoped run

Because each send is constrained by its own deadline in that SAME epoch,
a compliant pacer may not get ahead of this media clock.

Epoch boundary:

- initial pacer start creates a new epoch
- A.6 Case-A rebase creates a new epoch
- slow-send rebase creates a new epoch
- pacer restart creates a new epoch

The first-send overshoot from a previous epoch MUST NOT be carried into a
new epoch's allowance.

Cross-epoch / cross-generation bursts remain independently protected by:

pacer_min_inter_send_ms_observed >= 14.999

and the connection-wide previous_audio_send_start_at floor.

Require Agent F to prove the <=1 bound from this new definition.

==================================================
MAJOR M2
PER-SEGMENT RATE OBSERVABILITY
==================================================

The rev-7 rule:

EVERY qualifying clean segment must pass

is retained.

Replace ambiguous scalar acceptance with explicit run extrema.

For each qualifying segment record:

segment_rate_fps
segment_mean_inter_send_ms
segment_frames
segment_id

Expose:

steady_segment_rate_fps_min
steady_segment_rate_fps_max

steady_segment_mean_inter_send_ms_min
steady_segment_mean_inter_send_ms_max

steady_pacer_segments_qualifying_total
steady_segment_frames_max

Acceptance requires:

steady_pacer_segments_qualifying_total >= 1

steady_segment_rate_fps_min >= 49.5
steady_segment_rate_fps_max <= 50.5

steady_segment_mean_inter_send_ms_min >= 19.80
steady_segment_mean_inter_send_ms_max <= 20.20

Raw per-segment records remain available in /diag.

The old singular names:

steady_pacer_rate_fps
pacer_mean_inter_send_ms_observed

may remain only as per-segment diagnostic fields or compatibility aliases.

They MUST NOT be the sole acceptance observables.

==================================================
MAJOR M3
MECHANICAL AST SCAN
==================================================

Replace the semantic AST wording with an exact executable rule.

Before scanning:

strip / ignore module, class and function docstring Expr(Constant(str))
nodes.

Then reject ANY executable AST occurrence of the legacy symbol set in:

Name.id
Attribute.attr
keyword.arg
Constant(str)

Legacy symbol/string set includes at least:

dl_q
SENTINEL
_stop_pending
_enqueue_frame
_enqueue_sentinel
_drop_one_non_sentinel
_put_drop_oldest
DL_QUEUE_MAX
qwen_closed

This intentionally catches:

getattr(config, "DL_QUEUE_MAX", 256)

because "DL_QUEUE_MAX" is an executable string Constant.

Do NOT use the semantic phrase:

"qwen_closed used as a flush/residue reason"

The test is mechanical:

no executable string Constant equal to "qwen_closed" remains in the
R-1f downlink module.

If logging still needs the wording, use the normative string:

UPSTREAM_CLOSED

or a different non-accounting human label that is not the legacy token.

==================================================
REV-7 MINORS
==================================================

Apply ALL confirmed minors.

m1:
Replace the unreproducible delta text.

Use the reproducible median range:

approximately 1.03 / 1.07 / 1.21 ms

or a clearly labelled rounded range.

Do not write 0.98 unless an estimator that produces it is explicitly
defined.

m2:
Choose ONE normative wake-overshoot estimator.

Use the per-pair estimator:

delta =
gap - 20 - T(later frame)

when T exists,
else gap - 20 - run_mean_T

Canonical means:

mock ≈ 1.386 ms
r1d ≈ 3.298 ms
r1e ≈ 2.472 ms

Use these consistently in A.1/A.5/A.16.

Wake overshoot remains diagnostic only.

m3:
Delete:

"a compliant pacer has no sustained deficit by construction"

Replace with:

clean steady segments are required to hold approximately 50 fps;
phase resets/rebases may lower aggregate wall-clock rate and are counted,
bounded and excluded from the clean-segment rate calculation.

m4:
State clearly:

the raw r1d evidence has only 70 frames and is too short to itself satisfy
the >=250-frame qualification.

Claims about >=250-frame r1d segments come only from documented
resampling/repetition experiments.

m5:
Record the deliberate telemetry architecture explicitly:

BRIDGE /health:
bridge counters/gauges only

CLIENT acceptance telemetry:
client FIFO/drop/zero-fill counters

The client fields:

pcm_fifo_partial_underfill_events
pcm_fifo_partial_zero_pad_samples

are part of the R-1f ACCEPTANCE TELEMETRY CONTRACT,
not literal fields inside the bridge's HTTP /health payload.

This is an explicit PO clarification of the earlier shorthand
"Part A /health contract".

m6:
Counters are NOT assumed monotone across FIFO object replacement.

Each TTS FIFO has:

pcm_fifo_instance_id

The playout window records:

start_fifo_instance_id
start counter snapshots

For T3 reload/teardown:

snapshot the OLD FIFO counters first,
end the window,
then rebuild/replace the FIFO.

A scoped delta may never span two FIFO instance ids.

If the FIFO instance changes without a properly recorded T3 terminal event:

CLIENT_TELEMETRY_INVALID = 1
run client half = INVALID.

m7:
Add an exact T2 observable inside PcmFifo.pull:

pcm_fifo_drained_to_empty_events

Increment once when:

size_before > 0
AND
size_after == 0

as the pull completes.

No I/O/logging.

For a post-tts-stop T2 close:

the window ends on the first new
pcm_fifo_drained_to_empty_events edge for that FIFO instance.

The end snapshot occurs AFTER all counters from that pull are updated,
including partial zero-pad samples.

m8:
Use one wording for the post-send T>250 fatal stall:

the slow send has already completed and is SENT;
there is NO SEND_AWAIT or RESERVED_WAIT head belonging to that completed
attempt;
only remaining QUEUED frames are flushed through the PACER_STALL path.

Do not state two variants.

m9:
The "R2 after R1" condition is UNREACHABLE BY CONSTRUCTION.

Keep an optional defensive assertion only as:

if observed => accounting_fault_events += 1

but clearly label it an invariant-violation tripwire, not a normal branch.

m10:
State explicitly:

the single-store sentinel construction test is a separate,
non-acceptance harness run with RTL_DIAG unset.

The real long-response certification run remains:

RTL_DIAG = 1
client telemetry = ON

The sentinel harness can prove structure but cannot certify realtime
shipping behaviour.

==================================================
ADDITIONAL REV-7 REVIEW OBSERVATION
SLOW-SEND GUARD ASSERTION
==================================================

Close the reviewer's uncounted row-24 observability gap.

Add:

slow_send_guard_violations

For each slow successful send with:

5 < T <= 250 ms

record:

slow_guard_deadline =
completion_time + MIN_SEND_START_INTERVAL_MS

On the next audio send start, if:

send_start_at < slow_guard_deadline - SPACING_EPSILON_MS

then:

slow_send_guard_violations += 1

Acceptance requires:

slow_send_guard_violations = 0

The deterministic T=10 ms test must verify:

completion = start + 10
guard = completion + 15
next media deadline = completion + 20
next send >= completion + 20
slow_send_guard_violations = 0

==================================================
REV-8 ASSERTION REQUIREMENTS
==================================================

Normal clean long-response acceptance must now include:

steady_pacer_segments_qualifying_total >= 1

steady_segment_rate_fps_min >= 49.5
steady_segment_rate_fps_max <= 50.5

steady_segment_mean_inter_send_ms_min >= 19.80
steady_segment_mean_inter_send_ms_max <= 20.20

pacer_min_inter_send_ms_observed >= 14.999

wire_rate_excess_frames_max <= 1

active_pacer_tasks_max <= 1

slow_send_guard_violations = 0

post_terminal_sends_total = 0
where post_terminal means SEND_FORBIDDEN, not SEALED_DRAINING.

Client gate unchanged in intent:

incoming_queue_dropped_packets = 0
pcm_fifo_dropped_samples = 0
tts_playout_whole_block_zero_fill_count = 0
tts_playout_partial_zero_pad_samples = 0

==================================================
MANDATORY REV-8 ATTACKS
==================================================

Fresh Agent F must attack at least:

1. Canonical deque sentinel store:
   correct implementation passes the sentinel test.

2. Add a deliberate second deque containing the same sentinel:
   sentinel test MUST fail.

3. Normal seal with queued backlog:
   SEALED_DRAINING is allowed to send;
   post_terminal_sends_total remains 0.

4. Barge-in/abort/close/listen_start/upstream-close/send-error/fatal-stall:
   SEND_FORBIDDEN is set before any later send;
   post_terminal_sends_total remains 0.

5. Byte-cap with head in RESERVED_WAIT:
   head -> flushed_byte_cap_failure_frames exactly once.

6. Byte-cap with head in SEND_AWAIT:
   outcome_unknown += 1;
   run INVALID;
   closure residual 0.

7. Byte-cap with no in-flight head:
   triggering packet + queued store + residue all close exactly once.

8. Wire-rate metric:
   first-frame overshoot >20 ms followed by legal 15 ms recovery must NOT
   falsely produce excess >1 under the media_epoch-based definition.

9. An actually early/bursting sender MUST violate wire_rate_excess <=1
   and/or min interval gate.

10. Two or more qualifying steady segments:
    one deliberately set to 49.0 fps;
    extrema make acceptance FAIL.

11. Two or more qualifying good segments:
    all extrema pass.

12. AST fixture containing:
    getattr(config, "DL_QUEUE_MAX", 256)
    MUST fail the legacy scan.

13. AST fixture with legacy token only in a docstring/comment:
    MUST NOT fail after docstring stripping.

14. FIFO 200/480:
    partial-underfill +280
    drained_to_empty edge increments exactly once.

15. FIFO rebuild during active window:
    old instance snapshot closes before replacement;
    no negative delta;
    cross-instance window is rejected.

16. T=10 ms slow send:
    guard observable verifies no early next send.

17. All three accounting closures zero for:
    normal completion
    full-backlog seal
    barge-in
    send-error
    fatal-stall
    byte-cap RESERVED_WAIT
    byte-cap SEND_AWAIT-labelled-invalid path

18. Confirm 15 ms / 20 ms / positive-rate gates unchanged.

19. Confirm no source/config/container implementation changes occurred.

==================================================
REVIEW GATE
==================================================

Lead rewrites Part A as rev-8.

Then dispatch a NEW independent Agent F.

Required final output:

DESIGN_REVIEW_BLOCKERS =
DESIGN_REVIEW_MAJORS =
DESIGN_REVIEW_MINORS =
DESIGN_REVIEW = PASS / REVISE

STOP after review.

Even if:

DESIGN_REVIEW_BLOCKERS = 0

DO NOT IMPLEMENT.

Report first.

Implementation still requires a separate explicit product-owner
authorization.

---

End of persisted product-owner correction text.
