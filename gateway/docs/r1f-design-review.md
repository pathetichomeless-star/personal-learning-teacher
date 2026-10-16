# R-1f Design — Normative Specification (rev 9) + Agent F review slot

Gate: **implementation BLOCKED until `DESIGN_REVIEW_BLOCKERS == 0`**
Revision: **rev 9** — the FINAL LOCAL CORRECTION ROUND applying the accepted rev-8 Agent-F review via the **product-owner rev-9 correction** ("R-1f REV-9 PRODUCT-OWNER FINAL LOCAL DESIGN CORRECTION", persisted verbatim at `rtl-lab/r1f-rev9-po-decision.md`; application map §0.9), merged from three read-only domain revision kits (Agents A/C/D) plus a read-only accounting regression pass (Agent B). The rev-8 architecture is LOCKED and not reopened (constants; deque store; SEND_FORBIDDEN/SEALED_DRAINING; byte-cap 12-step; media-epoch wire definition; ≤ 1 gate; per-segment extrema; mechanical AST rule; FIFO partial counters; slow-send machine). Where the PO text differs from any draft or kit, the PO text governs.
Author of Part 0 + Part A: team-lead (from the PO correction + the three domain kits). Part B: a **fresh, independent** Agent F (rev 9 review).
Nothing in this document has been implemented. No code was written; no config was modified; no container was rebuilt or restarted.

Inputs:

- Product-owner rev-9 correction "R-1f REV-9 PRODUCT-OWNER FINAL LOCAL DESIGN CORRECTION" (authoritative; persisted: `rtl-lab/r1f-rev9-po-decision.md`; application map §0.9). Accepts the rev-8 Agent-F review and mandates the final local corrections; the rev-8 architecture is LOCKED.
- Product-owner rev-8 correction "R-1f REV-8 PRODUCT-OWNER DESIGN CORRECTION" (authoritative; persisted: `rtl-lab/r1f-rev8-po-decision.md`; application map §0.8, partially superseded by §0.9). Accepted the rev-7 Agent-F review; the rev-7 core constants are FINAL.
- Product-owner rev-7 decision "R-1f REV-7 PRODUCT-OWNER DECISION" (authoritative; persisted: `rtl-lab/r1f-rev7-po-decision.md`; application map §0.7, partially superseded by §0.8). On the former B2 it supersedes the earlier directive's §1 floor value (option (a): `MIN_SEND_START_INTERVAL_MS = 15.0`).
- Product-owner revision directive "R-1f DESIGN REVISION rev-4", sections 1–25 + mandated re-review attacks §26 (authoritative where not superseded by the rev-7/rev-8 decisions; application map §0.6).
- Product-owner rev-3 revision directive, sections 1–16 (authoritative, applied verbatim in semantics).
- Product-owner rev-1 corrections 1–3 + over-cap policy decision.
- Rev-2 Agent F review: `rtl-lab/r1f-agent-f-review.md` (findings accepted).
- Rev-3 Agent F review: `rtl-lab/r1f-agent-f-review-rev3.md` (findings accepted; closure map §0.3).
- Rev-4 Agent F review: `rtl-lab/r1f-agent-f-review-rev4.md` (findings accepted after lead audit; closure map §0.4).
- Rev-5 Agent F review: `rtl-lab/r1f-agent-f-review-rev5.md` (findings accepted after lead audit: B1 superseded by directive §4; B2 carried into rev 6 — §0.5/§0.6).
- Rev-6 Agent F review: `rtl-lab/r1f-agent-f-review-rev6.md` (findings accepted; closure map §0.7.2).
- Rev-7 Agent F review: `rtl-lab/r1f-agent-f-review-rev7.md` (ACCEPTED by the product owner; closure map §0.8.2).
- Rev-8 Agent F review: `rtl-lab/r1f-agent-f-review-rev8.md` (ACCEPTED by the product owner; closure map §0.9).
- Domain revision kits (rev 9, read-only, merged by the lead): Agents A (pacer/epoch), C (client playout), D (structure/document hygiene); plus a read-only accounting regression pass by Agent B post-merge.
- Bridge source under review: `rtl-lab/app/turns.py`, `rtl-lab/app/audio.py`, `rtl-lab/app/counters.py`, `rtl-lab/app/diag.py`, `rtl-lab/config/config.json`.
- Client source (read-only): `py-xiaozhi/src/core/protocol_manager.py`, `py-xiaozhi/src/audio_codecs/audio_codec.py`, `py-xiaozhi/src/audio_codecs/audio_buffer.py`, `py-xiaozhi/src/audio_codecs/stream_manager.py`, `py-xiaozhi/src/audio_processing/aec_engine.py`, `py-xiaozhi/src/bootstrap/session.py`, `py-xiaozhi/src/plugins/audio.py`.
- Evidence: `rtl-lab/evidence/r1d|r1e_real_sent_opus.jsonl`, `r1e_mock_sent_opus.jsonl`.
- Agent B audit: `rtl-lab/r1f-agent-b-playout-audit.md`.

---

## Part 0 — Provenance and revision record

### 0.1 Standing retractions (from rev 1)

| # | Retracted | Replacement |
|---|---|---|
| C1 | "the buzz mechanism has been identified"; "digital silence injected every 20–50 ms" | `PACER_UNDERRUN_ZERO_FILL = STRONG_CANDIDATE`; `DROP_INDUCED_AUDIO_DISCONTINUITY = SECONDARY_CANDIDATE`; `STATIC_AUDIO_ROOT_CAUSE = UNPROVEN` |
| C2 | "Qwen's already-encoded Opus" | Qwen downlink is **PCM24**. Bridge assembles exact 20 ms PCM frames, encodes each to Opus **once**, stores the packet, then paces |
| C3 | "~14 % faster than realtime" proved by the 580 ms residual | `CLIENT_BACKLOG_OBSERVED = YES`; `CLIENT_FEED_RATE_FROM_THIS_SAMPLE = UNPROVEN` |

### 0.2 Rev-2 → rev-3 closure map

| rev-2 finding | Closed by rev-3 section |
|---|---|
| B-1 cap predicate counted cumulative frames (capped total response duration) | A.2 — occupancy-only cap with canonical `unsent_backlog_frames` definition and cap-crossing byte rule |
| B-2 frame closure false (send exception / cancel mid-send / encode failure unbucketed); byte closure self-referential | A.4 — three independent domains (source byte, framer byte, encoded frame disposition) |
| B-3 `MIN_SEND_INTERVAL_MS = 16 < 20` permitted 62.5 fps catch-up | A.5 — 16 ms rule deleted; 20 ms floor; connection-wide `connection_last_audio_send_at` |
| B-4 assertion set not backed by counters | A.14 counter contract + A.15 assertion table (every assertion names one field) |
| B-5 rebase unbounded and unquantified | A.6 — `WALL_CLOCK_PHASE_RESET` (≤250 ms) and `PACER_FATAL_STALL` (>250 ms) |
| M-1 legacy queue not enumerated; drop counter cannot prove single-stage | A.3 — explicit removal list + static/construction test |
| M-2 sentinel/end-of-response stage missing | A.9 — `GenerationEnd(gen_id, reason)` marker |
| M-3 generation boundaries undefined | A.7 — generation ≡ upstream `response_id`, with tombstone map |
| M-4 client metrics incomplete | A.12 — single normative client instrumentation spec |
| M-5 "bridge cannot relocate backlog" unestablished | A.5 + A.13 — connection-wide floor, wire-excess counter, client gate conditions |
| M-6 byte backstop justified against the mean; precedence undefined | A.11 — 2 MiB emergency ceiling, separate event/classification, frame cap authoritative |
| rev-2 minors m-1…m-8 | A.4.B (residue domain), A.14 (gauges split out), A.5 (epoch init), A.9 (marker excluded from counters), A.16 (period derivation, bitrate label), A.11 (byte domain), A.12 (designation) |

### 0.3 Rev-3 → rev-4 closure map

| rev-3 finding | Closed by rev-4 |
|---|---|
| **F-1** 20 ms floor reproduces the deficit (charged from completion; no slower-direction assertion) | A.5 — floor is re-anchored to the **send-attempt start**, given 2 ms slack (`MIN_SEND_INTERVAL_MS = 18.0`), explicitly designated a guard that must never pace; **positive rate assertion** added (`pacer_mean_inter_send_ms_observed <= 20.5`, row 7b) alongside the existing fast-side gates |
| **F-2** disposition domain missing `listen_start` / upstream-close flush buckets; stall/byte-cap flush without a reason; failed synthetic-tail encode invisible | A.4.B + A.4.C — one 9-reason vocabulary shared by both domains; `flushed_listen_start_frames`, `flushed_upstream_closed_frames`, `flushed_byte_cap_frames`, `flushed_send_error_frames` added; `synthetic_tail_encode_failures` + `tail_encode_failed_pcm_bytes` added and placed in the PASS set (A.15 #18) |
| **F-3** residue admitted before a cap/stall transition has no exit bucket | A.2 + A.4.B + A.6 + A.11 — every transition discards the current `dl_buf` residue with a reason-scoped counter (`residue_discarded_cap/stall/byte_cap/send_error_bytes`); A.4.B equation extended; explicit "not `safety_truncated`" rule (no double-count) |
| **F-4** `in_flight_frames` undefined for "popped, awaiting its send slot" | A.4.C — `in_flight_frames` defined with two sub-states (`PRE_SEND_WAIT`, `SENDING`); cancellation during the wait = **known-unsent** → reason-scoped flush bucket; only cancellation inside the transport call is outcome-unknown; test-B peak uniquely 1500 canonical backlog |
| M-1 `catch_up_frames_over_50fps` not provable | A.5 — **half-open** window `(t−1000 ms, t]`, **max over sends** convention stated; "accumulated" wording deleted |
| M-2 four `*_per_generation` fields lack aggregation domain | A.14 — each defined as **max over generations of that generation's count**; connection-level stop attribution rule added (A.9) |
| M-3 2 MiB ceiling cannot bind (tautology) | A.11 — ceiling lowered to **300 KiB (307200 B)**; bindable before the frame cap under encoder misconfiguration (≥ ~205 B/frame sustained ⇒ fires ≈ frame 241 at 1275 B/frame), unreachable at 1.9× margin for the configured encoder; **simulated misconfiguration test** required so the branch is exercised |
| M-4 exception containment has no observable | A.4 header + A.14 — per-branch containment in the event dispatcher; `qwen_dispatch_errors` counter; nonzero ⇒ run INVALID; a local defect can no longer masquerade as an upstream close |
| M-5 orphan / bad-base64 rules vs deliberate id-less tolerance | A.4.A — ordered attribution-then-decode rule; id-less deltas map to the live generation (`idless_delta_events` reported, non-invalidating); bad-base64 invalidation scoped to live-generation deltas (`bad_base64_ignored_events` otherwise) |
| M-6 synthetic-tail encode failure invisible | A.4.B — `synthetic_tail_encode_failures` + `tail_encode_failed_pcm_bytes` (see F-2 row) |
| M-7 single-store proof not implementable; removal list incomplete | A.3 — concrete construction-test predicate; `SENTINEL`, `_stop_pending`, `counters.audio_out_dropped`, all `dl_q` uses, both `send_cancel` sites added to the removal/rewrite list; `dl_buf` sub-frame invariant stated |
| M-8 barge-in step bits never defined | A.10 — steps S1–S4 enumerated; per-step failure counters; `barge_in_sequence_incomplete` as their derived predicate; S5 tracked by A.8 counters |
| m-1…m-10 | A.6 (`lateness_n` formula), A.14 (connection-wide min; `unsent_backlog_peak_frames`), A.5 (`None` initial floor), A.5/A.4.C (floor update mandated in the `CancelledError` handler; atomic single-pacer rule), A.4.B (1-byte residue + duplicate-end listed), A.14/A.2 (`unsent_backlog_peak_frames`), A.14 (all maxima as max-over-generations), A.9 (count emissions), A.14 (`qwen_audio_delta_bytes` retired as an alias of `admitted_pcm_bytes`; bad-base64 scope; half-open window wording) |
| Over-claims: A.1 "removes the deficit"; A.13 starvation-blind gate | A.1 — wording now "designed to restore the 50 fps media rate; static/buzz root cause remains UNPROVEN"; A.13 — starvation side added (`client_midstream_underrun_events`, row 17b) and the bridge-side positive rate assertion named as the primary anti-starvation guarantee |

### 0.4 Rev-4 → rev-5 closure map (rev-4 review, audited by the lead)

Rev-4 review returned **1 BLOCKER / 7 MAJORS / 9 MINORS (`REVISE`)** (`rtl-lab/r1f-agent-f-review-rev4.md`). Lead audit: every item confirmed against sources/evidence; **one extension added (M-A-ext)**, found by independently resampling the raw jitter distributions (legacy `δ` means 1.387 / 3.324 / 2.490 ms; a 2 ms slack is insufficient for the two real envelopes ⇒ 46.6 / 48.9 fps simulated; 5 ms slack restores 49.97–50.00 fps).

| rev-4 finding | Closed by rev-5 |
|---|---|
| **B1** frame that triggers the frame cap (and the packet that triggers the byte cap) has no disposition bucket | A.2 — the admission decision moves to **frame-completion, before encoding**; the refused candidate is **never encoded**; all bytes then in `dl_buf` (the candidate + residue, up to the full buffer content) are discarded as `residue_discarded_cap_bytes`. A.11 — the byte-cap decision happens **after encoding** (size unknowable earlier); the triggering packet is discarded as `flushed_byte_cap_frames` and counted in `encoded_full_frames`. Both paths now close A.4.B and A.4.C with residual 0 |
| **M-A** floor rationale falsified (floor binds at measured rates) | A.5 — rationale rewritten: the floor *does* bind after multi-ms wakes (measured `δ > 2 ms` on 7.5 / 22.4 / 15.1 % of steady gaps); it is a bounded phase-recovery mechanism (lateness decays, mean stays 20.000) and can never pace because of the absolute-deadline invariant |
| **M-A-ext (audit)** drift condition: mean wake overshoot must be **below** the slack, else lateness creeps and the rate sags | A.5 — slack raised to 5 ms (`MIN_SEND_INTERVAL_MS = 15.0`), drift condition stated normatively (`E[wake overshoot] < slack`, with ≥1 ms margin), new observable `pacer_wake_overshoot_mean_ms_observed` asserted in row 7b; recovery depth bounded by the 40 ms rebase trigger ⇒ `wire_rate_excess <= 1` preserved under any slack (absolute-deadline invariant) |
| **M-B** row 7b has no minimum-run constraint (short compliant runs can false-fail) | A.5/A.14/A.15 — the mean-rate field and row 7b apply to active runs with `frames_in_run >= 250` (5 s); shorter runs are reported for information only |
| **M-C** post-cap upstream terminal could create a second `GenerationEnd` | A.9 — a sealed/tombstoned generation is terminal locally: a late upstream terminal is accounted via the tombstone and **must not** enqueue a marker, emit a stop, or process a tail |
| **M-D** single-store predicate undecidable (`uplink_q` holds complete 640-byte frames) and removal list holes | A.3 — predicate scoped to the **downlink playback path** (`uplink_q` explicitly exempt); list completed: `main.py:24,53,75-76` (`DL_QUEUE_MAX`), `turns.py:297` (`_stop_pending` reset) |
| **M-E** stall path leaves the in-flight `PRE_SEND_WAIT` head frame unbucketed | A.6 — case B step 2 now resolves the in-flight head frame (PRE_SEND_WAIT → `flushed_pacer_stall_frames`; SENDING → `send_outcome_unknown_frames` + INVALID) |
| **M-F** rate metrics do not pin the timestamp basis (completion-based reading false-fails row 7) | A.5/A.14 — all inter-send metrics are defined on `t_attempt` (the attempt-start timestamp, the same basis the floor is charged from) |
| **M-G** tombstone insertion rule not normative; a replaced generation can misclassify as `UNKNOWN_RID` | A.4.A — normative rule: every `response_id` is inserted into the ever-created map **at creation** and retained for the connection lifetime; `UNKNOWN_RID` = never created |
| min-1 A.16 r1d p95 convention | A.16 — noted (nearest-rank convention) |
| min-2 row 9 structurally 0 (sends never early) | A.15 — row 9 reworded: reported sanity gauge, structurally 0 by construction (kept as a regression tripwire) |
| min-3 `pacer_floor_bind_count` tie undefined | A.5 — tie rule: equality counts as the deadline term |
| min-4 cancellation-boundary sub-µs exception | A.10/A.4.C — scope wording: delivered *while the pacer is suspended in the pre-send wait* |
| min-5 close-during-send INVALID scope undeclared | A.13 — declared: a close/abort landing inside the transport call yields `send_outcome_unknown_frames` and an INVALID run; tests exercising it are labelled |
| min-6 client playback start instant undefined | A.12 — defined (first PCM block written for the response) |
| min-7 refused admission sampled as admission | A.14 — sampling rule: only actual admissions and `in_flight` entries are sampled; a refused admission mutates nothing |
| min-8 id-less delta vs ended-but-uncleared current | A.4.A — `ENDED_CURRENT` target class (guard-dropped, `idless_delta_events`, non-invalidating) |
| min-9 byte-cap check point unspecified | A.11 — post-encode check point stated explicitly |

### 0.5 Rev-5 → rev-6 change list (interim plan — **superseded by the product-owner directive; see §0.6**; retained for audit history)

Rev-5 review returned **2 BLOCKERS / 2 MAJORS / 11 MINORS (`REVISE`)** (`rtl-lab/r1f-agent-f-review-rev5.md`). Lead audit: both blockers confirmed with independent reproduction (analytic argument + resampling simulation); MA-2's stale-text findings acknowledged; 16 of the 18 §0.4 rows verified genuinely closed (rev-4's B1 included). (Note: the directive applied as rev 6 supersedes this interim plan where they differ — in particular it deletes `catch_up_frames_over_50fps` outright, keeps `MIN_SEND_START_INTERVAL_MS = 18.0`, and replaces the byte ceiling with 512 KiB.)

| rev-5 finding | Planned rev-6 change |
|---|---|
| **B1** `catch_up_frames_over_50fps = 0` unsatisfiable under jitter (51-send windows occur on ~half of sends; floor-bound recovery guarantees it) | A.5/A.14/A.15 — the **anchored** `wire_rate_excess_frames_max <= 1` becomes the sole fast-side gate (it is provably ≤ 1 via the absolute-deadline invariant). `catch_up_frames_over_50fps` is **redefined** as `max(0, sent_in_window − 51)` (half-open window, uniform ±1 measurement tolerance) and demoted to **reported** evidence; A.5's "exactly 50 in every window" claim restated as "50 ± 1"; consequence-5 wording updated |
| **B2** sealed ⇒ locally-terminal set covers 2 of 8 terminal transitions; stall/send_error leave the generation `LIVE` (undead playback) | One predicate (A.4.A + A.9): a generation is **locally terminal** on any of {normal seal, cap seal, barge-in, abort, close, listen_start, upstream_closed, send_error, fatal stall}; once locally terminal it leaves the `LIVE` class (late deltas ⇒ `STALE` ⇒ `guard_dropped_pcm_bytes`), its store is closed, and later upstream terminals are absorbed by the tombstone (no marker/stop/tail). Every terminal transition explicitly "marks locally terminal + clears `current_resp_id` if it points at this generation" (A.6 case B step 7, A.4.C send-error bullet, A.10 S1 description). New reported counter `post_terminal_delta_events`; new A.15 row 19 (stall-test exit: zero post-stall sends with the old `resp_id`; `in_flight_frames == 0`; residual 0; markers/stops = 1) |
| **MA-1** overshoot observable lacks a minimum-run constraint; false-fails on compliant runs | A.5/A.14/A.15 — `pacer_wake_overshoot_mean_ms_observed` domain: runs with `frames_in_run >= 1000` (20 s; gate `<= 4.5`, margin to slack 5.0 argued, false-fail negligible at that n for the measured envelopes); runs 250–999 reported for information; field added to A.13's required-fields list |
| **MA-2** stale constants: A.13 "18 ms", A.1 "2 ms slack", Part A heading "(rev 4)" | Replace with 15 ms / 5 ms / "(rev 6)"; fix the "what rev 4 removes" / "compliant rev-4 pacer" wordings |
| mi-1..mi-11 | A.16: state the percentile convention correctly (nearest-rank 0.145; linear 0.141; lower-rank 0.136) and define "steady gaps" + the T-subtraction method used for δ means (state method ⇒ reproducible); A.3: invariant-2 restatement (cap instant: only the refused candidate + residue, discarded as a unit) and predicate-(a) "encoded units" vs "960-byte PCM frame" wording; A.2: pin the incremental-append reading for cap-crossing byte attribution (extra complete frames beyond the candidate ⇒ `safety_truncated`); A.4.C: quiescence gains "and no `dl_buf` residue"; A.12: playback-start correlation mechanism (tag first sample / timestamp consuming callback; fallback = first FIFO push with the FIFO offset noted); A.5: condition "can never pace" on the drift condition; A.16: fix the client drain-clock description (480 samples @ 24 kHz; FIFO 240000 @ 24 kHz); A.1/A.5: acknowledge the ~0.5 % rebase-induced deficit (rebase-spanning intervals excluded from the mean; wire-level sag bounded and counted); A.3: make the `dl_q` use-site enumeration line-accurate |

### 0.6 Product-owner revision directive ("R-1f DESIGN REVISION rev-4") — applied as rev 6 (historical; superseded in part by §0.7 — in particular the §1 floor value 18.0 is superseded by the rev-7 decision: `MIN_SEND_START_INTERVAL_MS = 15.0`)

Numbering reconciliation: this document's lineage is rev 3 → interim rev 4 → interim rev 5 (both independently reviewed) → **rev 6 (this revision)**. The directive text labels itself "rev-4"; its normative content governs this revision verbatim in semantics. Where the directive and the interim drafts differ, the directive governs. Carried from the interim drafts only where compatible: rev-5 blocker **B2** (unified local-terminal predicate, directive-silent) and the settled rev-3 closures.

| Directive § | Applied in | Normative content (applied) |
|---|---|---|
| 1 Pacer clock | A.5 | `MEDIA_FRAME_MS = 20.0`; `MIN_SEND_START_INTERVAL_MS = 18.0` (hard anti-burst safety floor only — NOT the media clock); `CATCH_UP_BURST = DISABLED`; absolute deadlines authoritative; floor charged from the previous send **START** (`previous_audio_send_start_at`), never completion; `send_start_at` taken immediately before `send_bytes`; overshoot recovered by a following interval below 20 ms but never below 18 ms |
| 2 Slow/failed send | A.5 | `send_call_duration_ms`; `SLOW_SEND_THRESHOLD_MS = 5.0`; slow success ⇒ `slow_send_events += 1`, no catch-up, next deadline rebased from completion, next send ≥ completion + 18 ms; failure/unknown after transport entry ⇒ `send_guard_until = observation + 18 ms` respected by any subsequent generation |
| 3 Positive rate gate | A.5, A.14, A.15 | Clean steady segments (≥ 250 confirmed frames, no rebase/stall/failure/unknown) ⇒ `steady_pacer_rate_fps ∈ [49.5, 50.5]` and `pacer_mean_inter_send_ms_observed ∈ [19.80, 20.20]`; anti-burst kept separately (`min ≥ 17.999`, `wire_rate_excess ≤ 1`); 18 ms must never be described as the target cadence |
| 4 Remove catch_up | A.5, A.14, A.15 | `catch_up_frames_over_50fps` deleted entirely; not replaced by any inclusive/exclusive-window metric |
| 5 Frame lifecycle | A.4.C | `QUEUED / RESERVED_WAIT / SEND_AWAIT / SENT / FLUSHED_<reason> / SEND_FAILED / SEND_OUTCOME_UNKNOWN`; `in_flight_frames` includes both `RESERVED_WAIT` and `SEND_AWAIT`; popping does not reduce `unsent_backlog_frames` |
| 6 Pre-send-wait cancellation | A.4.C, A.6, A.10 | `RESERVED_WAIT` cancellation ⇒ known-unsent ⇒ reason-scoped `flushed_<reason>_frames`; only cancellation after entering `SEND_AWAIT` ⇒ `send_outcome_unknown_frames` |
| 7 Reason vocabulary | A.4.B | One reason set {BARGEIN, ABORT, CLOSE, LISTEN_START, UPSTREAM_CLOSED, PACER_STALL, BYTE_CAP_FAILURE, SEND_ERROR}; `flushed_<reason>_frames` + `residue_discarded_<reason>_bytes` for each; no flush and no `dl_buf.clear()` without one reason |
| 8 Store-cap residue | A.2 | `residue_discarded_store_cap_bytes`; residue may remain buffered; when incoming bytes would complete another frame while backlog == 1500 ⇒ fire exactly once, move the already-admitted residue to the store-cap bucket, clear `dl_buf`, classify all not-yet-admitted bytes of the triggering delta (and every later delta) as `safety_truncated_pcm_bytes`; accepted playable frames drain normally; no reclassification of admitted residue |
| 9 Source/framer closures | A.4.A, A.4.B | Source closure unchanged; framer closure = `960*encoded_full_frames + 960*encode_failed_frames + synthetic_tail_source_bytes + synthetic_tail_encode_failed_source_bytes + residue_discarded_pcm_bytes + still_buffered_pcm_bytes`; `residue_discarded_pcm_bytes` = Σ reason counters + store-cap bucket |
| 10 Synthetic tail failure | A.4.B | Success: `synthetic_tail_frames/source_bytes/zero_pad_bytes`; failure: `synthetic_tail_encode_failures` + `synthetic_tail_encode_failed_source_bytes` + `synthetic_tail_encode_failed_zero_pad_bytes`; no playable frame; PASS requires 0 failures; not safety truncation |
| 11 Send-error termination | A.4.C | `send_failed_frames += 1`; invalidate; store → `flushed_send_error_frames`; residue → `residue_discarded_send_error_bytes`; cancel upstream once; one TTS stop; run non-PASS |
| 12 Disposition closure | A.4.C | Full closure equation with the eight reason buckets + store-cap excluded (no frame bucket); quiescence gauges 0 |
| 13 Byte ceiling | A.11 | `MAX_FUTURE_AUDIO_BYTES = 524288` (512 KiB); ≈ 349.5 B/frame at 1500; observed max 108 B ⇒ 3.24× margin; fires before the frame cap under pathological inflation; testable with an oversized mock packet fixture; `flushed_byte_cap_failure_frames` / `residue_discarded_byte_cap_failure_bytes`; `byte_cap_failures += 1`; acceptance FAILS |
| 14 Id-less audio events | A.4.A | Exactly one live non-terminal current ⇒ map + `idless_delta_mapped_bytes` (in source closure); zero or more than one ⇒ `orphan_pcm_bytes` + INVALID; bad base64 scoped: `bad_base64_live_events` (invalidates) vs `bad_base64_stale_or_unmapped_events` (diagnostic) |
| 15 Dispatch containment | A.4 | Per-branch containment; `qwen_dispatch_errors_total` + `qwen_dispatch_errors_by_type`; never reclassified as connect error / upstream disconnect / ordinary `qwen_closed`; any > 0 ⇒ INVALID |
| 16 Aggregation + TTS ownership | A.9, A.14 | Four `*_max_per_generation` fields = MAXIMUM over generations (not sums); raw per-generation values in `/diag`; `tts_owner_generation_id` set at emission, stop counted only when emitted, attributed to the owner even if tombstoned, then set to null |
| 17 Quiescence | A.4.C | No queued frame, no `RESERVED_WAIT`/`SEND_AWAIT`, no `dl_buf` residue, local TTS lifecycle ended, `GenerationEnd` consumed or immediate local termination completed; upstream terminal NOT required; tombstone only classifies late events; gauges sampled atomically |
| 18 Single store | A.3 | Completed removal list; construction test with the six points (incl. `dl_buf`/`uplink_q` exemptions and the static source test); `GenerationEnd` replaces sentinel semantics; `audio_out_dropped` retired (deprecated; never increments under R-1f) |
| 19 Barge-in bits | A.10 | BIT0..BIT3 mask `0b1111`; per-step SUCCEEDED/NOT_APPLICABLE/FAILED; failure counters `barge_in_{invalidate,pacer_cancel,store_flush,tts_stop}_failures`; upstream cancel separate |
| 20 Client starvation gate | A.12, A.13 | Playout-active window (first decoded PCM into Q2 → that generation's TTS stop/flush); `tts_playout_whole_block_zero_fill_count`, `tts_playout_partial_zero_pad_samples`; clean long-response acceptance ⇒ drops 0 AND both zero-fill metrics 0; report peaks; no static/buzz claim before the human listening gate |
| 21 Backlog observability | A.2, A.14 | `unsent_backlog_current_frames`, `unsent_backlog_peak_frames`; assert `unsent_backlog_peak_frames <= 1500`; store gauge not used alone |
| 22 Initial conditions | A.5 | `previous_audio_send_start_at = None`, `send_guard_until = None`; first frame not delayed; exactly one pacer per connection; ownership reserved atomically before any await; all `current_resp_id`-gated cancel sites rewritten to `cancel_upstream_once()` |
| 23 Residue clear sites | A.2, A.4.B, A.6, A.11 | Every clear path listed; 1-byte drop removed (any `0 < N < 960` ⇒ synthetic-tail rule); duplicate end resolves to the correct generation/tombstone (idempotent no-op or named accounting path) |
| 24 qwen_audio_delta_bytes | A.4.A, A.14 | Retained only as legacy diagnostic; marked `LEGACY / NOT USED FOR CLOSURE`; documented post-guard update point; no acceptance assertion uses it |
| 25 Updated assertions | A.15 | Rows A–I applied; `catch_up_frames_over_50fps` assertion deleted |
| (carried) rev-5 B2 | A.7, A.9, A.4.A/E | Unified **local-terminal predicate**: a generation is locally terminal on {normal seal, cap seal, barge-in, abort, close, listen_start, upstream_closed, send_error, fatal stall}; once locally terminal it leaves the `LIVE` class (late deltas ⇒ `STALE` ⇒ `guard_dropped_pcm_bytes`); later upstream terminals absorbed by the tombstone; `post_terminal_delta_events` reported |

Method note: every numeric claim below is taken from the product-owner text, re-derived here from raw evidence, or quoted with an explicit `file:line` anchor.

### 0.7 Rev-6 → rev-7 change map (product-owner decision + lead merge decisions)

The rev-7 revision applies the product-owner decision (**"R-1f REV-7 PRODUCT-OWNER DECISION"**, persisted verbatim at `rtl-lab/r1f-rev7-po-decision.md` — authoritative) merged from four read-only domain revision kits (Agents A/B/C/D, 2026-10-06). Where the PO text differs from any kit or interim draft, the PO text governs. §0.7.3 records the lead's merge decisions explicitly (nothing silent) for adversarial review.

#### 0.7.1 PO decision applied

| PO item | Applied in | Normative content (applied) |
|---|---|---|
| B2 decision (option a, FINAL) | A.1, A.5, A.13, A.14, A.15, A.16 | `MIN_SEND_START_INTERVAL_MS = 15.0`; `PACING_SLACK_MS = 5.0`; no 18.0 ms anywhere, no 15–18 ms range, no environment-dependent selection, no `E[j] < 2 ms` precondition; gates `[49.5, 50.5]` fps / `[19.80, 20.20]` ms / `>= 14.999` / `wire_rate_excess_frames_max <= 1`; wake overshoot diagnostic only |
| B1 normal seal at full backlog | A.2 (route R2), A.4.B, A.9, A.15 | seal-time store-cap disposal: no synthetic tail, no 1501st frame, residue → `residue_discarded_store_cap_bytes`, `AUDIO_STORE_CAP_REACHED` once per generation, accepted backlog drains; mandatory Test B′ (N ∈ {1, 200, 500, 959}) |
| M1 slow-send path | A.5, A.6, A.14, A.15 | slow success: `slow_send_events += 1`; `send_guard_until = completion + 15`; `next_deadline = completion + 20`; `pacer_rebases += 1`; `T > 250 ms` ⇒ `PACER_FATAL_STALL` (send dispositioned SENT first, then the A.6 Case-B exit list; acceptance FAILS) |
| No vacuous rate pass | A.5, A.13, A.15 | ≥ 1 qualifying clean steady segment (`steady_segment_frames >= 250`) mandatory; else `PACING_RATE_EVIDENCE = INSUFFICIENT` and `NORMAL_LONG_RESPONSE_ACCEPTANCE = FAIL` |
| M2 client partial starvation | A.12, A.13, A.14 (client sub-block), A.15 | `pcm_fifo_partial_underfill_events` / `pcm_fifo_partial_zero_pad_samples` counted inside `PcmFifo.pull`; scoped metric = window delta; deterministic test CL-1 (200/480 ⇒ len 480 / +1 event / +280 samples ⇒ gate FAILS) |
| M3 single-store sentinel test | A.3, A.15 row 12 | executable root-walk sentinel test (`SENTINEL_ENCODED_PACKET`; exempt roots {ws, diag, config, uplink_q, dl_buf}); 8 mechanically checkable assertions |
| MINORS 1–12 | distributed (see §0.7.2) | `queued_audio_frames` canonical; `post_terminal_sends_total`; BIT1/BIT2 head ownership; mutation/flush-site enumeration + `qwen_closed` → `UPSTREAM_CLOSED`; `active_pacer_tasks`/`_max <= 1`; acceptance configuration; client TTS-playout-session terminology; `keep_listening=False` window; A.2 sampling wording; stale-wording removal; wake-overshoot diagnostic domain; framer TERM-vs-residual wording |
| COUNTER/ASSERTION updates | A.14 + client sub-block, A.15 | new fields: `pcm_fifo_partial_underfill_events`, `pcm_fifo_partial_zero_pad_samples`, `post_terminal_sends_total`, `active_pacer_tasks`, `active_pacer_tasks_max` (+ `slow_send_events` kept); client clean-long-response set; terminal invariant `post_terminal_sends_total = 0` |

#### 0.7.2 Rev-6 review findings closed

| Rev-6 finding | Closed by |
|---|---|
| **B1** seal-time residue hole (full-backlog normal seal) | A.2 route R2 (complete seal decision table); A.9 step 1 both branches; A.4.B tail qualification + clear-site list; mandatory Test B′; A.15 row 5 |
| **B2** 18 ms floor vs rate gate (PO decision required) | A.1; A.5 (15.0/5.0, gates); A.13; A.14–A.16; decision persisted at `r1f-rev7-po-decision.md` |
| **M1** slow-send guard unrepresentable / unbounded / vacuous-pass | A.5 §2 state machine (guard = completion + 15; rebase = completion + 20); A.6 division-of-labour table + Case-B unified exit; no-vacuous clause; A.15 rows 2/24 |
| **M2** partial starvation invisible at callback | A.12 (counters inside `PcmFifo.pull`); retired callback-level partial counter; tests CL-1/CL-2/CL-3; A.15 row 18 |
| **M3** six-point construction test undecidable | A.3 (replaced wholesale by the executable sentinel test); A.15 row 12 |
| m1 naming (`queued_frames` vs `queued_audio_frames`) | A.2/A.4.C/A.14 — one canonical name |
| m2 row-11 journal-only assertion | A.4.C post-terminal definition; A.14 counter; A.15 row 11 `post_terminal_sends_total = 0` |
| m3 barge-in bit ownership | A.10 |
| m4 removal-list omissions | A.3 (mutation sites `turns.py:521, 552`; `_flush_downlink` callers 111/233/245/336/651; `qwen_closed` → `UPSTREAM_CLOSED` at 649/651/653; non-widening constraint) |
| m5 single-pacer has no field/row | A.5 (`active_pacer_tasks`/`_max` definitions); A.14; A.15 row 23 |
| m6 acceptance configuration unpinned | A.13 (normative configuration statement) |
| m7 client window/terminology | A.12 (TTS playout session; T1–T4 window ends) |
| m8 A.2 sampling wording | A.2 (residue disposal ≠ backlog mutation; once per generation) |
| m9 doc hygiene | A.2/A.3/A.4/A.4.A/A.7/A.8/A.9/A.10 headings; A.16 Q1 wording; A.5/A.16 wake-overshoot domain |
| m10 framer TERM vs residual | A.4.C term-vs-residual note; A.15 row 7 |

#### 0.7.3 Lead merge decisions (explicit; for adversarial review)

1. **Cap-run PASS eligibility (Agent B kit R1).** Adopted option (a): `residue_discarded_store_cap_bytes = 0` joins the A.4.C normal-completion PASS set (and A.15 row 22). Any run with a fired STORE_CAP transition (route R1 or R2) is a labelled `CONTROLLED_TAIL_TRUNCATION` run and cannot claim clean normal completion; the mandatory Test B/B′ runs remain labelled path-exercising runs (under the labelled-test exemption already provided in A.4.C). Rationale: without this term a full-backlog seal could satisfy every PASS clause while having truncated the tail — a policy gap the PO text does not address; recorded here rather than silently resolved.
2. **Rate-gate locality (Agent A kit R-6).** The positive-rate gate is evaluated over every qualifying clean steady segment observed in the run; any qualifying segment outside `[49.5, 50.5]` / `[19.80, 20.20]` is FAIL. `steady_segment_frames_max` and `steady_pacer_segments_qualifying_total` are reported for audit.
3. **Client window supersession (Agent C kit R5).** On supersession (T4: a new tts start before the prior window's terminal event), the prior window may close at the new start only if its TTS FIFO was already drained or cleared; if queued audio from the prior session remains, the run's client half is INVALID (overlap uncountable).
4. **Music-parallel mode (Agent C kit R3).** Certifying long-response runs use the default TTS music-pause policy (no music during the TTS session); with parallel music active the whole-block term is not evaluable and the run must declare it.
5. Notes adopted into normative text (no separate ruling): `SLOW_SEND_THRESHOLD_MS` and `PACING_SLACK_MS` are distinct constants whose 5.0 equality is coincidental (A.5); `send_guard_until` is an absolute deadline compared by value, never consumed (A.5); `pacer_wake_overshoot_mean_ms_observed` diagnostic domain (A.5/A.16).

### 0.8 Rev-7 → rev-8 change map (product-owner correction + lead merge decisions)

The rev-8 revision is a LOCAL CORRECTION ROUND applying the accepted rev-7 Agent-F review (3 BLOCKERS / 3 MAJORS / 10 MINORS + 1 uncounted observation) per the product-owner correction (persisted verbatim at `rtl-lab/r1f-rev8-po-decision.md` — authoritative), merged from four read-only domain revision kits (Agents A/B/C/D). The rev-7 core architecture (`MEDIA_FRAME_MS = 20.0`, `MIN_SEND_START_INTERVAL_MS = 15.0`, `PACING_SLACK_MS = 5.0`) is FINAL and not reopened. §0.8.3 records the lead's merge decisions explicitly (nothing silent) for adversarial review.

#### 0.8.1 PO correction applied

| PO item | Applied in | Normative content (applied) |
|---|---|---|
| B1 single-store sentinel | A.3, A.15 row 12 | `future_audio_store = collections.deque` pinned (direct representation: the deque's elements ARE the encoded packet objects); `asyncio.Queue` withdrawn as the store; `asyncio.Event`/`asyncio.Condition` allowed for wakeup but must not hold frames; new NON-ACCEPTANCE sentinel harness (pacer-startup hold via `_ensure_pacer` no-op, seeds `list(vars(conn).values())`, exempt roots {ws, diag, config, uplink_q, dl_buf} pruned by identity, descent-prune for type/function/module/code objects, runtime-nonce sentinel); no dependence on `asyncio.Queue` semantics, `Queue._queue`, or version-specific `gc.get_referents(dict)` behaviour |
| B2 post-terminal semantics | A.4.A, A.4.C, A.7, A.9, A.10, A.14, A.15 | two-tier partition: **SEALED_DRAINING** (normal seal / controlled cap seal; may drain legally) vs **SEND_FORBIDDEN** (the 8 flush-type transitions; `generation.send_forbidden = true` synchronously before any await); `post_terminal_sends_total` redefined (SEND_FORBIDDEN domain only; never for SEALED_DRAINING drain); tombstone/STALE semantics unchanged for both tiers |
| B3 byte-cap in-flight head | A.4.C, A.11, A.15 | BYTE_CAP_FAILURE added to the A.4.C known-unsent reason set; A.11 rewritten as the PO's 12-step sequence; triggering packet dispositioned exactly once (source bytes admitted at frame formation; the cap governs storage only); mandatory dual-case test (head RESERVED_WAIT / SEND_AWAIT) plus the no-head case |
| M1 wire-rate excess | A.5, A.13, A.15 | media-clock-epoch definition (E1 pacer start / E2 A.6 Case-A rebase / E3 slow-send rebase / E4 pacer restart create epochs); `permitted(t) = max(0, 1 + floor((t − epoch_t)/MEDIA_FRAME_MS))`; `wire_excess = sent_in_epoch − permitted`; gate `<= 1` KEPT (theorem `<= 0`, to be proven by Agent F from the definition); the rev-7 first-send anchor and `WIRE_RUN_ANCHOR_GAP_MS` are DELETED |
| M2 per-segment observability | A.5, A.13, A.14, A.15 | per-segment raw records in /diag (`segment_id`, first/last send start, frames, rate, mean, epoch); run extrema `steady_segment_rate_fps_min/max`, `steady_segment_mean_inter_send_ms_min/max`; old singular names demoted to per-segment diagnostics/aliases, never sole acceptance observables |
| M3 mechanical AST scan | A.3, A.15 | docstring `Expr(Constant(str))` stripping; reject `Name.id` / `Attribute.attr` / `keyword.arg` / `Constant(str)` occurrences of the 9-token legacy set (exact equality); scope = all `rtl-lab/app/**/*.py`; `getattr(config, "DL_QUEUE_MAX", 256)` caught; the semantic "used as a reason" phrase withdrawn |
| slow-send guard assertion | A.5, A.13, A.14, A.15 | `slow_send_guard_violations` (a next audio send start earlier than `slow_guard_deadline − SPACING_EPSILON_MS`); acceptance `= 0`; T = 10 ms deterministic test extended |
| m1–m10 | distributed | δ median 1.03/1.07/1.21 ms (never 0.98) and per-pair estimator means ≈ 1.386/3.298/2.472 ms (HISTORICAL rev-8 figures; superseded by the rev-9 canonical values, §0.9); "no sustained deficit by construction" deleted; raw r1d = 70 frames note (resampling-only); telemetry architecture sentence (bridge `/health` vs client acceptance telemetry); `pcm_fifo_instance_id` + T3 ordering + `CLIENT_TELEMETRY_INVALID`; `pcm_fifo_drained_to_empty_events` T2 edge; single m8 wording; m9 tripwire labelling; m10 harness declaration |

#### 0.8.2 Rev-7 review findings closed

| Rev-7 finding | Closed by |
|---|---|
| **B1** sentinel test not decidable | A.3 (canonical deque, direct representation, new harness, descent prune — the kit's F-D1/F-D2 findings recorded) |
| **B2** post-terminal falsified on normal seal | A.4.A/A.4.C (SEND_FORBIDDEN / SEALED_DRAINING partition + redefinition) |
| **B3** byte-cap head unbucketed | A.4.C/A.11 (known-unsent + 12-step sequence) |
| **M1** wire-excess bound invalid | A.5 (media-epoch definition; theorem ≤ 0) |
| **M2** locality rule without observable | A.5/A.13/A.14/A.15 (extrema fields) |
| **M3** AST scan incomplete/undecidable | A.3 (mechanical rule; 4 channels; docstring strip) |
| m1–m9 | A.1/A.2/A.5/A.6/A.9/A.11/A.12/A.14/A.16 (see §0.8.1) |
| m10 | A.3 declaration |
| uncounted row-24 observation | A.5/A.13/A.14/A.15 (`slow_send_guard_violations`) |

#### 0.8.3 Lead merge decisions (explicit; for adversarial review)

1. **Head-ownership representation (Agent D R-D1 × Agent B).** With the direct-deque store (bare packet objects), the popped head's owning generation is tracked by the pacer in a Connection scalar recorded at pop time (`head_owning_generation_id`); per-frame bookkeeping lives in Connection scalar fields and the A.4.C counters, not in wrapper objects inside the store. A.4.C's head-resolution wording is aligned accordingly.
2. **Two flush-type transitions interleaving (Agent B R3).** `send_forbidden` sets are idempotent; FLUSH DISPOSITION is owned by the FIRST transition to complete its flush step (store/head emptied once; the second sees empty state and contributes 0 frames); `byte_cap_failures` increments whenever `AUDIO_STORE_BYTE_CAP_REACHED` fires (event-independent of flush ownership); the trigger packet always goes to `flushed_byte_cap_failure_frames` exactly once; ≤ 1 TTS stop per generation preserved by the existing latch.
3. **The pacer pre-send `send_forbidden` check is normative (Agent B R4).** The pacer's synchronous pre-send stretch checks `send_forbidden` and resolves a forbidden head as known-unsent — attack 4 is provable, not merely plausible.
4. **Byte-cap covers BOTH encode sites (Agent B R5).** The delta-loop encode and the seal-time tail encode; a seal-time firing creates no tail frame and routes the tail's N already-admitted bytes to `residue_discarded_byte_cap_failure_bytes` (closure-B residue term).
5. **Queue-empty waits do not evaluate lateness (Agent A risk 6).** One sentence added to A.6: the lateness evaluation happens at the next send decision; a > 250 ms queue-empty idle gap followed by a new frame in a live pacer enters A.6 Case B (unchanged rev-7 behaviour, now stated).
6. **`steady_segment_frames_max` is taken over QUALIFYING segments only (Agent A risk 7)** — reconciled with `steady_pacer_segments_qualifying_total`.
7. **δ estimator contract pinned (Agent A risk 4).** A.16 states the normative per-pair estimator INCLUDING the `send_intent` matching rule; the PO's ≈ figures are quoted as reviewer/resampling values. Notes adopted into normative text: `max(0, ·)` retained as written (vacuous in-domain; anti-simplification note); the extrema rows short-circuit on the qualifying-count clause; the old singular rate names are aliases and never sole acceptance observables.

### 0.9 Rev-8 → rev-9 change map (final local correction; product-owner decision + lead merge decisions)

The rev-9 revision is the FINAL LOCAL CORRECTION ROUND, applying the accepted rev-8 Agent-F review (1 BLOCKER / 1 MAJOR / 5 MINORS) per the product-owner correction (persisted verbatim at `rtl-lab/r1f-rev9-po-decision.md` — authoritative), merged from three read-only domain revision kits (Agents A/C/D) plus a read-only accounting regression pass (Agent B). The rev-8 architecture is LOCKED and not reopened (constants; deque store; SEND_FORBIDDEN/SEALED_DRAINING; byte-cap 12-step; media-epoch wire definition; ≤ 1 gate; per-segment extrema; mechanical AST rule; FIFO partial counters; slow-send machine). §0.9.2 records the lead's merge decisions explicitly (nothing silent) for adversarial review.

#### 0.9.1 PO correction applied

| PO item | Applied in | Normative content (applied) |
|---|---|---|
| B-1 E4 epoch creation | A.5 | E4 = EVERY pacer task start other than E1, regardless of why the previous pacer ended (normal GenerationEnd drain; ordinary queue drain/exit; cancel; stall; send-error cleanup; barge-in cleanup; any later legitimate recreation); at every E4: `epoch_ordinal += 1`, `media_epoch = monotonic_now()`, `frame_index = 0`, `sent_in_epoch = 0`; no state re-anchors `media_epoch` while inheriting `sent_in_epoch`/`epoch_ordinal`; the initialization block and the normal-pacing block are declared the SAME rule; E2/E3 unchanged; Agent F required to re-prove `wire_excess ≤ 0` for E1–E4 |
| M-1 T2 two-branch rule | A.12, A.14, A.15 | atomic lock-held stop snapshot (same `pcm_fifo_instance_id`: size + all scoped counters); **T2-A** (`fifo_size_at_stop == 0` ⇒ immediate close, label `T2_EMPTY_AT_STOP`, no future edge required; a later session's push/pull cannot close/alter the closed window); **T2-B** (`size > 0` ⇒ record `t2_stop_fifo_instance_id` + `t2_stop_drained_edge_baseline`; window open until the FIRST edge with same instance AND `drained_events > baseline`; end snapshot after that pull's counters; label `T2_DRAIN_AFTER_STOP`; a later session's edge must not close it; T4 governs if a new start precedes closure); completely replaces the rev-8 "first new edge after stop" wording; no arbitrary timer |
| mi-1 | A.16 | 20.0023 ms ⟹ 49.994 fps (49.99 at two decimals); the 49.97 transcription slip corrected |
| mi-2 | A.1, A.16 | canonical evidence values of the pinned per-pair estimator: mean 1.3858/3.3237/2.4710 ms; median 1.0270/1.0845/1.2100 ms; frac > 2 ms 7.5/22.4/14.9 %; supersedes the approximate r1d 3.298 figure; conclusion unchanged (all ≪ 5 ms); diagnostic only |
| mi-3 | A.3 | "all dl_q uses" row corrected to the AST-verified direct occurrences (533/555/559 removed — alias `q` accesses; covered by the diag-queue-fields rewrite row); removal scope unchanged |
| mi-4 | A.3, A.12 | duplicated A.12 sentence removed (one authoritative copy); orphaned "4." marker in A.3 replaced by an unnumbered bold-lead paragraph (with the stale "(3)" cross-ref corrected to "Step 4 assertion 6"); final heading/numbering/duplicate audit run post-merge |
| mi-5 | A.12, A.15 | `AudioCodec.__del__` = EMERGENCY DESTRUCTION path, NOT a T1–T4 certification terminal; during an active window ⇒ `CLIENT_TELEMETRY_INVALID = 1` + client half INVALID; after close ⇒ no effect; no destructor I/O; integrity classification only |

#### 0.9.2 Lead merge decisions (explicit; for adversarial review)

1. **Initialization-block identity (Agent A §1.3).** The directive-§22 initialization block and the normal-pacing epoch line are declared to be the SAME rule as the E1/E4 epoch creation ("this IS the E1/E4 epoch creation — same rule stated twice"), so a double increment of `epoch_ordinal` at task start is excluded by construction; `epoch_ordinal >= pacer_starts` always (E2/E3 also increment), with equality only if no rebase ever fired.
2. **Pacer-exit segment termination (Agent A §1.4/§1.5).** A pacer task EXIT terminates the current clean steady segment even if no new task starts; the successor segment opens inside the E4 epoch of the next task (condition (e) "no pacer restart/stop" covers it; now stated).
3. **Lock-held T2 snapshots (Agent C R3).** The T2 stop snapshot and the T2-B end snapshot are lock-held atomic reads of the TTS FIFO scalars (same `threading.Lock` as push/pull) — the branch decision needs size and drained_events mutually consistent, and the T2-B end snapshot must include the draining pull's (I2)/(I3) counters. Not I/O; does not run in the realtime callback; window-START snapshots keep the GIL-atomic rule.
4. **T2-B + intervening clear (Agent C R1 FIRST-of clause).** A `clear_audio_queue()` applied while a T2-B window is open terminates it via the T1/T3 mechanics with the pre-clear snapshot; the pending T2-B baseline is discarded (clear() produces no drained edge). No path leaves a T2-B window waiting forever.
5. **Attribution under the edge/start race (Agent C R1; rev-9 erratum m-4).** An edge is attributed to the window's owning session iff no later tts start has been observed at the moment of edge observation; client-observed processing order is the only observable order (declared bounded race). RACE DIRECTION (normative, erratum m-4): because the FIFO counters are monotone per instance and the scoped delta is end − start, next-session pollution can only ADD to the old window's delta — it can produce a spurious FAIL / CLIENT_TELEMETRY_INVALID, and it can NEVER turn a real underfill into a false PASS. The bounded race is therefore fail-safe, and implementations MUST NOT attempt to eliminate it with blocking I/O in the realtime callback (the A.12 lock-held stop/end snapshots are the only permitted synchronisation).
6. **Historical figures annotation.** §0.8.1's m1–m10 row retains the rev-8-era approximate figures as history; the rev-9 canonical values (PO mi-2) govern A.1/A.5/A.16.

---

## Part A — Normative specification (rev 9)

### A.1 Root-cause state and wording

```
PACER_UNDERRUN_ZERO_FILL         = STRONG_CANDIDATE
DROP_INDUCED_AUDIO_DISCONTINUITY = SECONDARY_CANDIDATE
STATIC_AUDIO_ROOT_CAUSE          = UNPROVEN
```

Rev 7 does **not** claim to solve static/buzz. The pacer changes are specified to **restore the 50 fps media rate** (with the two-sided positive-rate gate, A.5/A.15) and to bound *memory*; whether that restores perceived voice quality remains unproven until instrumented client listening.

Clock mechanism of the measured deficit (this is what the rev-7 fix, A.5, removes):

- The legacy pacer sleeps a fixed 20 ms *after* each send (`turns.py:591`), so its realised period is `20 + T + δ` with no phase anchoring.
- Charging a send floor from the observed send *completion* time makes the floor itself binding for any `T > 0`, so even a deadline-driven pacer would settle at `20 + T + δ` (F-1). The directive's fix charges the floor from the send **start** and keeps the absolute deadline authoritative.
- Measured values: `T` p50 **0.060 ms** (mock) / **0.0645 ms** (r1d) / **0.0835 ms** (r1e), max 0.214 ms (`send_intents` in the three diag bundles); `δ` median = **1.0270 / 1.0845 / 1.2100 ms** (r1e_mock / r1d_real / r1e_real; rev-9 canonical values of the normative per-pair estimator, A.16 / PO mi-2 — two-decimal form 1.03 / 1.08 / 1.21; these supersede the rev-8 rounded 1.03 / 1.07 / 1.21; no estimator in this design produces 0.98) (median inter-send gap 21.0939/21.1627/21.3062 ms for the requested 20 ms sleep; journals `r1e_mock/r1d_real/r1e_real_sent_opus.jsonl`). Implied **47.4 / 47.3 / 46.9 fps**.
- Normative fix (A.5, rev-7 PO decision B2): the media clock (absolute deadlines) paces; `MIN_SEND_START_INTERVAL_MS = 15.0` is a hard anti-burst safety floor charged from the send-start; `PACING_SLACK_MS = 5.0` (= `MEDIA_FRAME_MS − MIN_SEND_START_INTERVAL_MS`) is the per-frame recovery depth. A slow successful send (`send_call_duration_ms > SLOW_SEND_THRESHOLD_MS = 5.0`) takes the explicit §2 guard-and-rebase (`send_guard_until = completion + 15`; `next_deadline = completion + 20`); a very slow successful send (`T > MAX_REBASE_LATENESS_MS = 250`) enters `PACER_FATAL_STALL` and the run FAILS. Failed / `SEND_AWAIT`-cancelled sends take `send_guard_until = observation_time + 15`. The positive-rate gate (per-segment extrema, rev-8 M2: `steady_segment_rate_fps_min/max ∈ [49.5, 50.5]`, `steady_segment_mean_inter_send_ms_min/max ∈ [19.80, 20.20]`) fails any pacer that reproduces the deficit; it must never PASS vacuously (A.5, no-vacuous clause). `MIN_SEND_START_INTERVAL_MS` is 15.0 and only 15.0; 18.0 is not the R-1f floor and no 15–18 ms runtime range exists.
- Floor slack (rev 7): the 15 ms floor leaves 5 ms of slack. The Lindley stability condition for the deadline backlog `L_n = max(0, L_{n-1} − PACING_SLACK_MS) + δ_n` is `E[δ] < PACING_SLACK_MS`; the measured mean wake overshoot δ under the NORMATIVE per-pair estimator (A.16, rev-8 m2: `δ = gap − MEDIA_FRAME_MS − T(later frame)` when that frame's `send_intent` exists, else `gap − MEDIA_FRAME_MS − run_mean_T`) is **1.3858 / 3.3237 / 2.4710 ms** (mock / r1d / r1e; rev-9 canonical values, PO mi-2 — these supersede the earlier approximate r1d = 3.298 ms figure wherever the pinned estimator is quoted; independently recomputed and reproduced to ≤ 0.03 ms, A.16) — all three are below 5 ms, so the absolute-deadline clock holds 50 fps and the floor is a pure anti-burst guard, not the rate-setting term. Wake overshoot is DIAGNOSTIC EVIDENCE ONLY: it is reported (`pacer_wake_overshoot_mean_ms_observed`) and is NOT an acceptance precondition. There is no `E[j] < 2 ms` validity clause anywhere in rev 7. The rate gate is the designed detector, and it is non-vacuous by construction: if a clean acceptance run produces no qualifying clean steady segment with `steady_segment_frames >= 250`, the run is `PACING_RATE_EVIDENCE = INSUFFICIENT` and `NORMAL_LONG_RESPONSE_ACCEPTANCE = FAIL` (never a pass on absent evidence).

Missing-block estimate, corrected:

| Basis | Deficit | Implied one-frame-missing period |
|---|---|---|
| Measured pacer deficit (send clock, A.16) | 2.6–3.1 frames/s | **1/3.1 s ≈ 323 ms to 1/2.6 s ≈ 385 ms** |
| Earlier aggregate frame-rate estimates (45.9–47.9 fps) | 2.1–4.1 frames/s | 244–476 ms — retained **only** if explicitly labelled as derived from those aggregate estimates |

The canonical figure from here on is the measured 2.6–3.1 frames/s ⇒ **≈323–385 ms**, on the stated assumption that the deficit is uniformly distributed across delivery opportunities. This estimate describes the **legacy** pacer (and any implementation that reproduces it); clean steady segments are required to hold approximately 50 fps (A.15 row 2); phase resets/rebases may lower aggregate wall-clock rate and are counted (`pacer_rebases`), bounded (`MAX_REBASE_LATENESS_MS = 250`) and excluded from the clean-segment rate calculation.

### A.2 Store cap domain (directive §8/§21; rev-7 B1)

`MAX_FUTURE_FRAMES` applies **only to unsent backlog occupancy**. It is **not** cumulative frames generated per response, not total response duration, and not total frames accepted by a generation.

Canonical definition (frame states defined in A.4.C):

```
unsent_backlog_frames = queued_audio_frames + in_flight_frames
    # queued_audio_frames is the CANONICAL component name (A.4.C); never write `queued_frames`
    # in_flight_frames includes BOTH sub-states: RESERVED_WAIT and SEND_AWAIT (directive §5)
MAX_FUTURE_FRAMES = 1500
```

Canonical observables (directive §21): `unsent_backlog_current_frames` (gauge, = `queued_audio_frames + in_flight_frames`) and `unsent_backlog_peak_frames` (max over the run, sampled **only** at actual admission events and at `in_flight` entries). A transition-truncated arrival is **not** a backlog mutation — none of its bytes are admitted — so it is not sampled and cannot raise the peak; residue disposal is likewise not a backlog mutation. `AUDIO_STORE_CAP_REACHED` fires **at most once PER GENERATION** (equivalently `cap_transitions_max_per_generation <= 1`). Assertion reads `unsent_backlog_peak_frames`; `audio_store_peak_frames` is the store-only gauge with `audio_store_peak_frames <= unsent_backlog_peak_frames` — it is **not** used alone.

Admission rule — a new complete frame may be admitted **only** when `unsent_backlog_frames + 1 <= MAX_FUTURE_FRAMES`.

**STORE_CAP transition (directive §8).** `CONTROLLED_TAIL_TRUNCATION` does **not** flush already accepted playable frames, so it is not one of the normal frame-flush reasons (A.4.B) — but it may discard already-admitted partial PCM residue. There are exactly **two trigger routes**; the event `AUDIO_STORE_CAP_REACHED` fires **at most once per generation** (whichever route occurs first).

**Route R1 — delta-triggered** (the only route that can fire while the response is still live):

1. While `unsent_backlog_frames == MAX_FUTURE_FRAMES`, an admitted partial frame in `dl_buf` **may remain buffered** until enough new source bytes arrive to complete another frame.
2. The decision is evaluated **per incoming delta, before any of that delta's bytes are admitted**: if `len(dl_buf) + len(delta_bytes) >= 960` while `unsent_backlog_frames` is still 1500:
   a. fire `AUDIO_STORE_CAP_REACHED` **exactly once** (`cap_transitions_total += 1`);
   b. move the already-admitted `dl_buf` residue into `residue_discarded_store_cap_bytes`;
   c. clear `dl_buf`;
   d. classify **all** bytes of the triggering delta (none admitted) as `safety_truncated_pcm_bytes`;
   e. every later audio delta for that generation is also `safety_truncated_pcm_bytes`;
   f. already accepted playable frames remain and drain normally.
3. **Post-condition (invariant):** after R1, `len(dl_buf) == 0` for the remainder of the generation, because none of the later deltas' bytes are admitted. Therefore R2 cannot fire for that generation and no byte can be disposed twice.

**Route R2 — seal-time at full backlog** (normal response seal only; the rev-6 B1 hole). Precondition: `unsent_backlog_frames == MAX_FUTURE_FRAMES` **and** `0 < len(dl_buf) < 960` at the first seal of the generation:

1. do **not** create a synthetic tail frame;
2. do **not** admit a 1501st frame;
3. fire `AUDIO_STORE_CAP_REACHED` exactly once (`cap_transitions_total += 1`) — **unless** the generation already entered the state via R1 (in which case `len(dl_buf) == 0` by R1.3 and R2's precondition is false, so R2 cannot fire);
4. `residue_discarded_store_cap_bytes += len(dl_buf)`;
5. `dl_buf.clear()`;
6. `synthetic_tail_frames` does **not** increment;
7. `synthetic_tail_source_bytes` does **not** increment;
8. seal the generation (A.9) and enqueue **exactly one** `GenerationEnd`;
9. the already accepted 1500-frame backlog drains normally.

The R2 residue bytes were **already admitted**, so they are **NOT** `safety_truncated_pcm_bytes`. If R2 is ever observed for a generation that already entered the state via R1, that is an **invariant-violation tripwire** (`accounting_fault_events += 1`): R2-after-R1 is **UNREACHABLE BY CONSTRUCTION** (R1.3 gives `len(dl_buf) == 0`, so R2's precondition is false — rev-8 m9); this is a defensive assertion, **not** a normal branch, and no test may exercise it as one. The residue is still disposed **exactly once** through `residue_discarded_store_cap_bytes` (those are *different* bytes — the R1 bytes were already cleared), and the transition event is **not** re-fired.

- Do **not** reclassify already-admitted residue as `safety_truncated_pcm_bytes` — that would double-count the source-byte domain. At quiescence after either route: `len(dl_buf) == 0`, `still_buffered_pcm_bytes == 0`, `still_stored_frames == 0`, `in_flight_frames == 0`.
- Because the frame that "would have completed" at the boundary is never formed or admitted, the `dl_buf` invariant `0 <= len(dl_buf) < 960` (A.3) holds at every instant, on **both** routes.
- A response may therefore be 60 s, 5 minutes, etc. without truncation provided the unsent backlog never exceeds 1500 frames.

**Seal decision at normal response seal (complete and total).** On the first seal of a generation (a duplicate end is the A.4.B idempotent/no-op case), let `N = len(dl_buf)` at that instant:

| `unsent_backlog_frames` | `N` | behaviour |
|---|---|---|
| `< 1500` | `0` | normal seal; **no** synthetic tail |
| `< 1500` | `0 < N < 960` | normal seal; **one** synthetic tail frame (A.4.B) — admitted, since `backlog + 1 <= 1500` |
| `== 1500` | `0` | normal seal; **no** tail and **no** cap event (nothing would have been refused) |
| `== 1500` | `0 < N < 960` | **route R2** (store-cap disposal); **no** tail |

No other case exists (`unsent_backlog_frames > MAX_FUTURE_FRAMES` is impossible).

Required tests:

| Test | Scenario | Expected |
|---|---|---|
| A | 60 s response, backlog peak = 3 | `safety_truncated_pcm_bytes = 0`; no cap transition |
| B | stalled pacer, backlog at 1500, `dl_buf` holding 500 admitted bytes; a triggering delta arrives whose bytes (plus the 500) would complete a frame | cap fires **exactly once** (`cap_transitions_max_per_generation == 1`); canonical peak `unsent_backlog_peak_frames == 1500`; `residue_discarded_store_cap_bytes == 500` (disposed exactly once — no byte in two counters); ALL triggering-delta bytes and every later delta ⇒ `safety_truncated_pcm_bytes`; `dl_buf == 0` after the transition; accepted frames drain; A.4.B and A.4.C closures residual 0 |
| **B′** (mandatory) | **full-backlog normal seal:** stalled pacer, `unsent_backlog_frames = 1500`, `dl_buf` holds `N` with `0 < N < 960`, then `response.audio.done` / `response.done` arrives (no further delta) | route R2: `unsent_backlog_peak_frames <= 1500` (**no frame 1501**); `residue_discarded_store_cap_bytes` increases by **exactly N once** (no byte of N in `safety_truncated_pcm_bytes`); `synthetic_tail_frames` unchanged; `synthetic_tail_source_bytes` unchanged; `safety_truncated_pcm_bytes = 0`; `cap_transitions_max_per_generation <= 1`; `end_markers_max_per_generation == 1`; `tts_stop_emissions_max_per_generation == 1`; at quiescence (**sampled after the already-accepted backlog drains, not at the seal instant**) `still_buffered_pcm_bytes = 0`, `in_flight_frames = 0`, `still_stored_frames = 0`; A.4.A source residual 0, A.4.B framer residual 0, A.4.C disposition residual 0. Run representative `N ∈ {1, 200, 500, 959}` |

### A.3 Downlink pipeline and single-stage store (rev-8 B1/M3/m10; rev-7 MINORS 1/4/5/9/10)

```
Qwen `response.audio.delta` (base64 PCM24, mono s16le, 24 kHz)
  -> source byte accounting boundary                     (A.4.A)
  -> 20 ms framing (960-byte complete frames)            (A.4.B)
  -> encode once to Opus (one packet per complete frame)
  -> generation-aware future-audio store                 <-- the ONLY audio holding structure
  -> pacer (absolute monotonic media clock + conn. floor) (A.5)
  -> websocket `send_bytes`
```

**Provenance.** The rev-7 product-owner decision (persisted: `rtl-lab/r1f-rev7-po-decision.md`, §M3 and MINORS 1/4/5/9/10) requires an explicit REMOVAL/REWRITE list, a mechanically decidable single-store sentinel test, and the single-pacer exclusivity invariant. (This replaces the superseded "Rev 4 requires…" wording — rev-6 m9.)

**Canonical naming (rev-7 MINOR 1).** The queued part of the backlog is `queued_audio_frames` (canonical spelling; A.4.C). `unsent_backlog_frames = queued_audio_frames + in_flight_frames` (A.2). A.3 uses no other spelling of this quantity; `future_audio_store` is the container, not the counter.

**REMOVAL/REWRITE list (complete; every line re-verified against the current source).**

```
REMOVE entirely:
  self.dl_q                    turns.py:77            (definition)
  DL_QUEUE_MAX                 config/config.json:6
  DL_QUEUE_MAX (all sites)     main.py:24 (DEFAULTS), main.py:53 (load_config),
                               main.py:75-76 (startup log)
  SENTINEL                     turns.py:20            (module-level definition)
  _stop_pending                turns.py:84 (definition), turns.py:297 (reset in response.created)
  _enqueue_frame               turns.py:492
  _enqueue_sentinel            turns.py:498
  _drop_one_non_sentinel       turns.py:508
  _put_drop_oldest             turns.py:531
  counters.audio_out_dropped   counters.py:26 (definition), counters.py:56 (/health alias)
  all dl_q uses                turns.py:321, 322 (diag qsize/maxsize), 337 (diag step qsize),
                               513, 528 (inside _drop_one_non_sentinel),
                               532 (inside _put_drop_oldest: the alias binding `q = self.dl_q`),
                               568, 571, 575 (pacer loop), 616 (inside _flush_downlink),
                               633 (diag step in _cancel_pacer)
  audio_out_dropped mutations  turns.py:521 (inside _drop_one_non_sentinel),
                               552 (inside _put_drop_oldest)
  legacy reason literal        "qwen_closed" at turns.py:649, 651, 653  (see mapping below)

REWRITE (may be kept by name only):
  _ensure_pacer                turns.py:503  -> operate on the single store; enforce A.5 single-pacer rule
  _cancel_pacer                turns.py:625  -> accept and thread a flush reason (A.4.C, A.10)
  _flush_downlink              turns.py:610  -> reason-scoped store+residue flush (A.4.B)
  both send_cancel sites       turns.py:249-255, 340-349 -> cancel_upstream_once(gen, reason) (A.8)
  diag queue fields            turns.py:321, 322, 337, 533, 555, 559 -> store/backlog fields
```

**Legacy reason → normative reason (rev-7 MINOR 4).** The only legacy reason literal that is not already in the A.4.B vocabulary is `"qwen_closed"`:

```
  "qwen_closed"  ->  UPSTREAM_CLOSED
    turns.py:649   diag.mark_invalidated(self.diag.active_gen, "qwen_closed")
    turns.py:651   self._flush_downlink("qwen_closed")
    turns.py:653   self._stop_tts("qwen_closed")
    (entry point _on_qwen_closed turns.py:648; upstream close origin in qwen.py, incl. the
     ordinary-close path referenced by A.4)
```
No occurrence of `"qwen_closed"` may remain as a flush/residue *reason* in R-1f; the normative 8-reason set `{BARGEIN, ABORT, CLOSE, LISTEN_START, UPSTREAM_CLOSED, PACER_STALL, BYTE_CAP_FAILURE, SEND_ERROR}` (A.4.B) is the only accepted source. `qwen_closed` may survive only as a log message / diag label, never as an accounting key.

Renaming must NOT widen `_on_qwen_closed`'s trigger entries (`turns.py:648-659`). A.4 requires that a local dispatch/accounting exception never be reclassified as an ordinary upstream close; therefore the dispatch path must not route into the UPSTREAM_CLOSED flush, and `qwen_dispatch_errors_total` remains the classifier. `counters.upstream_errors += 1` (`turns.py:658`) is a corroborating signal only.

**Every current `_flush_downlink` call site (rev-7 MINOR 4), mapped to its normative reason:**

```
  turns.py:111   close          -> CLOSE
  turns.py:233   listen_start   -> LISTEN_START
  turns.py:245   abort          -> ABORT
  turns.py:336   barge_in       -> BARGEIN
  turns.py:651   qwen_closed    -> UPSTREAM_CLOSED   (definition of _flush_downlink is turns.py:610)
```

Normative (directive §18; rev-8 PO B1):

1. There must be **exactly one** container capable of holding one or more encoded Opus downlink frames between the encoder and `send_bytes`: `future_audio_store`. (`GenerationEnd` replaces the legacy sentinel semantics.)
2. `dl_buf` is **explicitly exempt**: it stores raw PCM residue, not encoded Opus frames. Invariant `0 <= len(dl_buf) < 960` at every instant. `uplink_q` is **explicitly exempt** (microphone uplink; out of the downlink playback path).

**Canonical store type (rev-8 PO B1).** `future_audio_store` SHALL be a `collections.deque`. It is the ONE AND ONLY mutable container that directly holds encoded downlink Opus packet objects between the encoder and `send_bytes`. Normative representation: the deque's elements ARE the encoded packet objects themselves (direct representation; no per-frame wrapper object in the store). Per-frame lifecycle bookkeeping (generation, in-flight state) lives in Connection scalar fields and the A.4.C counters, not in wrapper objects inside the store. Rationale (recorded): a wrapper/StoreItem representation is undecidable on CPython 3.13.12 — `gc.get_referents` does not traverse instance-`__dict__` values, so a second wrapper deque could hide the sentinel from the identity walk. `asyncio.Queue` SHALL NOT be used as `future_audio_store` (the rev-7 procedure is withdrawn; root cause: `gc.get_referents(queue)` does not contain the enqueued item). Wake-up MAY use `asyncio.Event` or `asyncio.Condition`; such primitives MUST NOT hold encoded audio frames. No wrapper object may contain another encoded-frame deque/queue internally unless `future_audio_store` itself IS that canonical deque. The pipeline diagram's "generation-aware future-audio store" box is realized by exactly this deque; the "exactly one container" norm (point 1) is unchanged.

**m10 declaration (rev-8 PO m10).** The single-store sentinel construction test is a SEPARATE, NON-ACCEPTANCE harness run with `RTL_DIAG` unset. This is the only construction in which `RTL_DIAG` unset is permitted. The real long-response certification run remains `RTL_DIAG = 1`, client telemetry = ON. The sentinel harness proves structure only; it cannot certify realtime shipping behaviour.

**Mechanically decidable single-store sentinel harness (rev-8 PO B1; replaces the rev-7 Steps 0–4 in full).**

*Step 0 — harness configuration (non-acceptance; m10).*
- Instantiate one R-1f `Connection` with a stub websocket (`send_bytes` records; `send_str` no-op). `RTL_DIAG` unset (m10); with diag disabled `_make_frame` returns the raw packet (`turns.py:394-397`).
- Encoder fixture: `enc24.encode` returns `SENTINEL_ENCODED_PACKET = b"\x00SENTINEL<" + <runtime nonce> + b">"` — one identity-unique `bytes` instance per harness run, built with a RUNTIME nonce. A literal is forbidden: value-equal bytes literals in one module dedupe to one object (verified), so only a runtime nonce guarantees no accidental identity collision.

*Step 1 — hold point: pacer startup control (replaces the store-wrapper gate; rev-8 PO point 2).*
- Before driving any delta, monkeypatch/harness-control pacer startup: substitute `turns.Connection._ensure_pacer` with a no-op. `_ensure_pacer` is the sole pacer-startup site (`turns.py:503-506`; synchronous, no await), so with the patch no pacer task is created and no `popleft()`/dequeue operation can occur. Do NOT replace any store accessor; do NOT introduce a consumer wrapper.
- The hold point is structurally BEFORE any `popleft()`; nothing has been dequeued and no coroutine local holds a frame.

*Step 2 — drive one synthetic response.*
- Feed `response.created` → exactly enough `response.audio.delta` events for one complete frame → release the encode path. Do NOT send `response.done` before the inventory walk.

*Step 3 — root-inventory walk (explicit, decidable, Connection-scoped).*
- Seeds: `list(vars(conn).values())`. NOT the `conn.__dict__` object itself (rev-8 PO point 6; on CPython 3.13.12 `gc.get_referents(vars(obj)) == []`, so dict-object seeding seeds nothing).
- `EXEMPT_ROOTS` (pruned by object identity, whole subtrees): `conn.ws`, `conn.diag`, `conn.config`, `conn.uplink_q`, `conn.dl_buf` (rev-8 PO point 7).
- Descent prune (mechanical, required for decidability): do NOT descend into — (i) exempt roots; (ii) `conn` itself; (iii) any type object, function, bound method, module, or code object. Rationale (verified): function objects traverse their `__globals__`, pulling module-level dicts into the walk and fabricating false holders; this prune implements PO points 8–9 ("Connection-owned", "no coroutine locals or transport internals") mechanically.
- `MUTABLE_CONTAINER(o) := isinstance(o, (list, dict, set, frozenset, bytearray, collections.deque))`. `asyncio.Queue` is deliberately absent: it is not a legal store, and its elements are not yielded by `gc.get_referents` anyway. Coroutine/generator frame `f_locals` are not `MUTABLE_CONTAINER` and are not counted.
- Reachability `R`: breadth-first from the seeds following `gc.get_referents(o)` for each visited `o`, subject to the prune rules.
- `HIT(C) := C ∈ R ∧ MUTABLE_CONTAINER(C) ∧ ∃ r ∈ gc.get_referents(C) : r is SENTINEL_ENCODED_PACKET`.
- `hits := { C : HIT(C) }`, compared by object identity.
- Version robustness: HIT detection relies only on deque/list/set element traversal (verified: deque/list/set traverse their elements on 3.13.12; dict traversal is version-variable and is NOT relied upon — the direct store representation means the store HIT needs only deque traversal). The test uses no `asyncio.Queue` iteration semantics, no `Queue._queue` internals, and no version-specific `gc.get_referents(dict)` behaviour (rev-8 PO point 10).

*Step 4 — required assertions (each mechanically checkable; PO 10-point mapping in brackets).*
1. `type(conn.future_audio_store) is collections.deque`. *(PO 5)*
2. `len(conn.future_audio_store) == 1`. *(PO 5)*
3. `conn.future_audio_store[0] is SENTINEL_ENCODED_PACKET` (direct representation; normative choice — no StoreItem-payload alternative). *(PO 5)*
4. `conn.pacer_task is None` (pacer never started; hold point valid; nothing dequeued). *(PO 2, 9)*
5. The walk was seeded from `list(vars(conn).values())` and NOT from the `conn.__dict__` object itself (harness-structural; the seeding expression is part of the executable harness text). *(PO 6)*
6. `hits == {id(conn.future_audio_store)}` — exactly one holder exists and it is `future_audio_store`. *(PO 8)*
7. Exempt roots `ws, diag, config, uplink_q, dl_buf` are pruned by identity; their subtrees are not in `hits`. Verified by the harness's synthetic self-test at bring-up (a sentinel placed inside an exempt subtree is not counted), never against the live Connection. *(PO 7)*
8. The walk visits no coroutine locals and no transport internals (the descent prune of step 3 plus assertion 4). *(PO 9)*
9. The harness source contains no `asyncio.Queue` API use and no dependence on `Queue._queue`, `Queue` iteration, or `gc.get_referents(dict)` element behaviour. *(PO 10)*
10. Symbol absence on instance and class (carried from rev-7, unchanged): none of `{dl_q, SENTINEL, _stop_pending, _enqueue_frame, _enqueue_sentinel, _drop_one_non_sentinel, _put_drop_oldest}` appears in `vars(conn)` or in `[c.__dict__ for c in type(conn).__mro__]`; additionally `not hasattr(turns_module, "SENTINEL")`. *(PO 4)*

Pass/fail of every point follows from this document plus the source. Rev-8 mandatory attacks 1 and 2 target exactly this harness (1: a correct deque implementation passes; 2: a deliberate second deque holding the same sentinel MUST fail assertion 6).

**Mechanical AST scan (rev-8 PO M3; replaces the rev-7 assertion-5 scan wording in full).**
- Scope: every `.py` file under `rtl-lab/app/` (this includes `turns.py` and `main.py` — the latter holds `DL_QUEUE_MAX` as a `keyword.arg` at `main.py:53` and a string Constant at `main.py:24`, both already on the removal list). `config/config.json` is not Python; its `DL_QUEUE_MAX` remains covered by the removal list plus a plain-text absence check.
- Pre-processing: strip/ignore the module, class and function docstring `Expr(Constant(str))` nodes. Comments never appear in the AST.
- Rule (mechanical, exact): after stripping, REJECT (test FAILS) on ANY occurrence of a member of the legacy symbol/string set
  `{dl_q, SENTINEL, _stop_pending, _enqueue_frame, _enqueue_sentinel, _drop_one_non_sentinel, _put_drop_oldest, DL_QUEUE_MAX, qwen_closed}`
  in any of: `Name.id`, `Attribute.attr`, `keyword.arg`, `Constant(str)` (string constants matched by exact value). Matching is EXACT identifier/value equality, never substring.
- The rule intentionally catches `getattr(config, "DL_QUEUE_MAX", 256)` because `"DL_QUEUE_MAX"` is an executable string Constant (verified against the fixture: FAIL; and against `turns.py` as-is: line 77 flagged on this channel).
- The semantic phrase "qwen_closed used as a flush/residue reason" is withdrawn. The test is: no executable string Constant equal to `"qwen_closed"` remains in the R-1f modules (verified: today flagged at `turns.py:649/651/653`). If logging still needs the wording, use the normative string `UPSTREAM_CLOSED` or a different non-accounting human label that is not the legacy token.
- Documented survivors under exact-equality matching (NOT violations, stated to prevent reviewer confusion): the identifier `_on_qwen_closed` (the A.4 entry point kept by the removal list's non-widening constraint), `SENTINEL_ENCODED_PACKET`, `diag.on_sentinel`-style names containing "sentinel" in different spellings, and `future_audio_store`.
- Verification status: executed against `app/turns.py` AS-IS ⇒ FAIL with the exact per-symbol counts (dl_q ×12 as `Attribute.attr` at 77,321,322,337,513,528,532,568,571,575,616,633; SENTINEL ×6 as `Name.id`; `_stop_pending` ×7; `_enqueue_frame` ×2; `_enqueue_sentinel` ×1; `_drop_one_non_sentinel` ×1; `_put_drop_oldest` ×2; `DL_QUEUE_MAX` ×1 as string Constant at line 77; `qwen_closed` ×3 as string Constants at 649/651/653); docstring/comment-only fixture ⇒ PASS (attack 13); `getattr` fixture ⇒ FAIL (attack 12); planned-R-1f-names fixture (`SENTINEL_ENCODED_PACKET`, `future_audio_store`, `on_sentinel`, `_on_qwen_closed`, `UPSTREAM_CLOSED`) ⇒ PASS, zero false positives.
- Reconciliation with the removal/rewrite list: unchanged and line-accurate; the mapping `"qwen_closed" -> UPSTREAM_CLOSED` and the non-widening constraint on `_on_qwen_closed`'s trigger entries (`turns.py:648-659`) stay in force. The scan now additionally proves `main.py`'s keyword/constant occurrences (removal-list rows) are gone.

**`audio_out_dropped` mutation check (carried rev-7 assertion 6; rev-9 erratum m-5).** An AST scan over the R-1f app package finds no runtime mutation of `counters.audio_out_dropped`. Mechanical rule (exact): the counter-definition assignment `self.audio_out_dropped = 0` (`counters.py:26`) is EXEMPT; there must be no `AugAssign` targeting `counters.audio_out_dropped` and no non-definition `Assign` targeting it. The counter is read-only in `/health` (`counters.py:56`). Verified this round: the only two runtime mutation sites (`turns.py:521, 552`) sit inside functions the removal list deletes.
**Regression counter.** `legacy_drop_oldest_calls` remains useful as a regression counter but is **not accepted as proof** that a second queue does not exist (the sentinel walk — Step 4 assertion 6 — is that proof).

Encoder configuration in force (unchanged): `opuslib.Encoder(24000, 1, APPLICATION_VOIP)`, `bitrate = 24000` (`rtl-lab/app/audio.py:25-29`); one packet per 20 ms frame, 480 samples.

### A.4 Three-stage accounting (directive §9/§12/§15; provenance §0.3–§0.5)

No single self-referential closure. Three independent domains.

Counter integrity (directive §15): every `_on_qwen_event` branch must be **locally exception-contained**. An exception must not leave a frame or a byte unclassified, must not desynchronise the domains, and must not escape the dispatcher. Observables: `qwen_dispatch_errors_total` (cumulative) and `qwen_dispatch_errors_by_type`. A local dispatch/accounting exception **MUST NOT** be reclassified as `qwen_connect_error`, an upstream disconnect, or an ordinary `qwen_closed` (`qwen.py:296` path) — the containment wrapper absorbs it, counts it, and lets the cleanup path run in the normal controlled, reason-accounted way. **Any `qwen_dispatch_errors_total > 0` makes the acceptance run INVALID** (A.15). `barge_in_sequence_incomplete` (A.10) remains the visible consequence of a containment failure on the barge-in path.

#### A.4.A — Source byte domain (directive §14; unified local-terminal predicate)

**Local-terminal predicate (normative; rev-8 B2: two-tier partition).** A generation is **locally terminal** as soon as any of the following completes: normal seal (A.9), cap seal (A.9), or invalidation by barge-in, abort, close, listen_start, upstream-close, send error (A.4.C), fatal stall (A.6), or byte-cap failure (A.11). "Locally terminal" is the UMBRELLA predicate; it partitions into exactly two normative tiers:

- **SEALED_DRAINING** — entered by NORMAL seal completion or CONTROLLED STORE_CAP completion (A.2 R1 / R2). A SEALED_DRAINING generation MAY continue to send its already-accepted playable frames: it may reject all future source audio, tombstone/guard late upstream events, drain accepted playable audio, consume GenerationEnd, and emit one TTS stop, **without violating the send invariant**. Entering SEALED_DRAINING MUST NOT set `send_forbidden`.
- **SEND_FORBIDDEN** — entered by a FLUSH-TYPE terminal transition. The exact reason set (identical to the A.4.B one-normative-reason-set): {BARGEIN, ABORT, CLOSE, LISTEN_START, UPSTREAM_CLOSED, SEND_ERROR, PACER_STALL, BYTE_CAP_FAILURE}. On every flush-type path the transition sets `generation.send_forbidden = true` **synchronously, before any await** on that path (transition sites enumerated in A.4.C).

**Late-delta / tombstone semantics are UNCHANGED for BOTH tiers** (carried rev-5 B2): after a generation is locally terminal — in either tier — late deltas classify `STALE` (⇒ `guard_dropped_pcm_bytes`), `post_terminal_delta_events` is reported, and a late upstream terminal is absorbed by the tombstone (no marker/stop/tail — A.9). Once locally terminal the generation is removed from the `LIVE` class, its store is closed to it, and every terminal transition explicitly clears `current_resp_id` if it points at that generation.

Attribution and decode are **ordered**:

1. **Resolve the attribution target first, without decoding.** Normative map rule: every `response_id` observed in `response.created` is inserted into the ever-created map **at creation time** and retained for the connection's lifetime; "tombstoned" is a separate terminal flag on that entry. `UNKNOWN_RID` therefore means *never created on this connection*.
   - `rid` present and equal to the single live, non-terminal current response ⇒ `LIVE`;
   - `rid` present, known in the ever-created map, not live ⇒ `STALE`;
   - `rid` present but never created on this connection ⇒ `UNKNOWN_RID`;
   - `rid` absent and **exactly one** live, non-terminal current response exists ⇒ map the delta to that generation (`LIVE`) and `idless_delta_mapped_bytes += decoded_length` (participates normally in the source closure);
   - `rid` absent with zero live generations (or, defensively, more than one possible live generation) ⇒ `UNMAPPED`.
2. **Then decode** (always), and classify by target:
   - decode **fails**:
     - target `LIVE` ⇒ `bad_base64_live_events += 1` ⇒ run **INVALID** (the live generation's byte closure is unknowable);
     - all other targets ⇒ `bad_base64_stale_or_unmapped_events += 1` — diagnostic only; it does **not** invalidate the current live generation's zero-loss result (stated explicitly per directive §14).
   - decode **succeeds**, N bytes:
     - `LIVE` ⇒ `source_pcm_bytes += N`; downstream classification per A.2: `admitted_pcm_bytes` or `safety_truncated_pcm_bytes`;
     - `STALE` ⇒ `source_pcm_bytes += N`; `guard_dropped_pcm_bytes += N`;
     - `UNMAPPED` / `UNKNOWN_RID` ⇒ `orphan_pcm_bytes += N` (NOT counted in `source_pcm_bytes`); run **INVALID**.

Required closure at generation quiescence:

```
source_pcm_bytes = admitted_pcm_bytes + guard_dropped_pcm_bytes + safety_truncated_pcm_bytes
```

`orphan_pcm_bytes` is outside this equation by construction. Any acceptance run with `orphan_pcm_bytes > 0` or `bad_base64_live_events > 0` is **INVALID**.

`qwen_audio_delta_bytes` (`turns.py:372-373`, `counters.py:19,48`) is retained **only as a legacy diagnostic field** (directive §24): marked `LEGACY / NOT USED FOR CLOSURE`; its differing post-guard update point must be documented in the implementation; **no acceptance assertion may use it**.

#### A.4.B — Framer / encoder byte domain (directive §7/§9/§10)

At generation quiescence:

```
admitted_pcm_bytes
  = 960 * encoded_full_frames
  + 960 * encode_failed_frames
  + synthetic_tail_source_bytes
  + synthetic_tail_encode_failed_source_bytes
  + residue_discarded_pcm_bytes
  + still_buffered_pcm_bytes
```

**Term vs residual (minor 12).** `still_buffered_pcm_bytes` is a closure **TERM** (the last term of the right-hand side above), **not** the framer residual. At generation quiescence `still_buffered_pcm_bytes = 0` (A.4.C quiescence), which makes the term vanish; the framer **residual** is (LHS − RHS) and must be 0.

where

```
residue_discarded_pcm_bytes
  = residue_discarded_bargein_bytes
  + residue_discarded_abort_bytes
  + residue_discarded_close_bytes
  + residue_discarded_listen_start_bytes
  + residue_discarded_upstream_closed_bytes
  + residue_discarded_pacer_stall_bytes
  + residue_discarded_byte_cap_failure_bytes
  + residue_discarded_send_error_bytes
  + residue_discarded_store_cap_bytes      # the A.2 STORE_CAP special case (not a frame-flush reason)
```

- **Seal-time store-cap residue (A.2 route R2).** The bytes disposed at seal are already inside `admitted_pcm_bytes`; they enter the single `residue_discarded_store_cap_bytes` term (already a member of the `residue_discarded_pcm_bytes` sum above) and are **never** reclassified as `safety_truncated_pcm_bytes`. **No new residue counter is introduced by B1.**

Rules:

- An encode failure of a complete 960-byte source frame consumes it: `encode_failed_frames += 1`.
- **One normative reason set (directive §7):** {BARGEIN, ABORT, CLOSE, LISTEN_START, UPSTREAM_CLOSED, PACER_STALL, BYTE_CAP_FAILURE, SEND_ERROR}. For every reason there is a frame counter `flushed_<reason>_frames` (A.4.C) and a partial-PCM residue counter `residue_discarded_<reason>_bytes`. STORE_CAP is special (directive §8): it has **no** frame-flush counter (accepted playable frames drain normally) but owns `residue_discarded_store_cap_bytes`.
- **No store flush and no `dl_buf.clear()` may execute without one reason.** Required clear sites to cover in the implementation change set: `turns.py:429, 438, 442, 611` plus the cap/stall/byte-cap/send-error transitions and the **A.2 route R2 seal-time residue disposal**.
- Duplicate end (second end event, `turns.py:441-442`, directive §23): it must **not** blindly clear active residue; it resolves to the correct generation/tombstone — an **idempotent no-op** when the first end completed cleanly (residue already 0), or a **named accounting path** otherwise. A non-empty residue at that point means the first end left accounting open: `accounting_fault_events += 1` and the residue is routed through its correct reason-scoped counter (never a blind clear).
- At normal response completion (first seal): residue `0 < N < 960` follows the synthetic-tail rule **only when `unsent_backlog_frames < MAX_FUTURE_FRAMES`** — **including `N == 1`** (the legacy `len >= 2` shortcut at `turns.py:424` is a required change). At `unsent_backlog_frames == MAX_FUTURE_FRAMES` the seal-time store-cap route (A.2 route R2) applies instead: **no** synthetic tail frame, `residue_discarded_store_cap_bytes += N`, `dl_buf` cleared, `synthetic_tail_frames`/`synthetic_tail_source_bytes` unchanged. `N == 0` emits **no** synthetic tail frame in either case.

Synthetic tail (directive §10):

```
on success:
synthetic_tail_frames                       += 1
synthetic_tail_source_bytes                 += N
synthetic_tail_zero_pad_bytes               += 960 - N

on encode failure:
synthetic_tail_encode_failures              += 1
synthetic_tail_encode_failed_source_bytes   += N
synthetic_tail_encode_failed_zero_pad_bytes += 960 - N
```

On failure no playable frame is created; the N bytes enter **neither** `synthetic_tail_source_bytes` **nor** any disposition bucket. Normal-completion PASS requires `synthetic_tail_encode_failures = 0` — a lost tail cannot hide behind a PASS. This is **not** safety truncation and not Qwen-generated full-frame audio.

#### A.4.C — Encoded frame disposition domain (directive §5/§6/§11/§12/§17)

Frame lifecycle (directive §5) — every encoded audio frame has exactly one state:

```
QUEUED -> RESERVED_WAIT -> SEND_AWAIT -> SENT
   \-> FLUSHED_<reason>          (from QUEUED or RESERVED_WAIT on a reason)
   \-> SEND_FAILED               (definite send exception inside SEND_AWAIT)
   \-> SEND_OUTCOME_UNKNOWN      (cancellation after entering SEND_AWAIT)
```

- `QUEUED`: inside the single future-audio store.
- `RESERVED_WAIT`: removed from the store by the pacer, waiting for its scheduled send slot.
- `SEND_AWAIT`: the `send_bytes` call has been entered and has not returned.
- `SENT`: `send_bytes` returned successfully.
- `in_flight_frames` includes **both** `RESERVED_WAIT` and `SEND_AWAIT`; therefore `unsent_backlog_frames = queued_audio_frames + in_flight_frames` (A.2) — **popping a frame does not reduce backlog; only a final disposition does.** `queued_audio_frames` is the canonical component name (never `queued_frames`); `queued_audio_frames` is the frame count inside the single `future_audio_store` (it equals the `audio_store_current_frames` gauge).
- Non-audio markers (A.9) are excluded from all frame counters.

Cancellation (directive §6; mandatory distinction):

- `RESERVED_WAIT` + {barge-in, abort, close, listen_start, upstream-close, fatal-stall, **byte-cap-failure**} ⇒ the frame is **KNOWN UNSENT**: it must **not** be classified as outcome-unknown; it resolves immediately into the matching reason-scoped flush counter (`flushed_bargein_frames`, `flushed_abort_frames`, `flushed_close_frames`, `flushed_listen_start_frames`, `flushed_upstream_closed_frames`, `flushed_pacer_stall_frames`, `flushed_byte_cap_failure_frames`).
- Only a cancellation delivered **after entering `SEND_AWAIT`** may create `send_outcome_unknown_frames += 1` (retaining its INVALID consequence for zero-loss acceptance).
- Witness wording: if the `CancelledError` surfaces from the pre-send wait (the pacer suspended in `RESERVED_WAIT`), known-unsent applies; a cancellation in the synchronous stretch after the wait returns surfaces inside the transport await and is outcome-unknown by this rule.

Send-error termination (directive §11): a `SEND_AWAIT` frame failing with a definite send exception ⇒ `send_failed_frames += 1`; then controlled local termination: invalidate the generation (local-terminal predicate, A.4.A — including clearing `current_resp_id` if it points at it), flush remaining `QUEUED`/`RESERVED_WAIT` frames to `flushed_send_error_frames`, discard residue to `residue_discarded_send_error_bytes`, cancel upstream once if still active (A.8), exactly one TTS stop; the run is non-PASS (real transport loss).

Frame-cap boundary: neither STORE_CAP route (A.2 R1 delta-triggered, R2 seal-time) ever forms the would-be frame, so it appears in **no** term of this closure; its bytes are accounted in A.4.B via `residue_discarded_store_cap_bytes`. The byte-cap boundary packet **is** encoded and is discarded into `flushed_byte_cap_failure_frames` (A.11) — counted once in `encoded_full_frames` and once in that bucket. The closure equation below is unchanged by R2.

Closure at generation quiescence (directive §12):

```
encoded_full_frames + synthetic_tail_frames
  = sent_confirmed_frames
  + flushed_bargein_frames
  + flushed_abort_frames
  + flushed_close_frames
  + flushed_listen_start_frames
  + flushed_upstream_closed_frames
  + flushed_pacer_stall_frames
  + flushed_byte_cap_failure_frames
  + flushed_send_error_frames
  + send_failed_frames
  + send_outcome_unknown_frames
  + still_stored_frames
  + in_flight_frames
```

**Post-terminal send invariant (rev-8 B2; supersedes the rev-7 "is_locally_terminal at send_start_at" definition, which was too broad).** A send is **post-terminal for the frame's OWNING generation** iff, at the instant `send_bytes` is entered with that frame, the owning generation has already entered **SEND_FORBIDDEN** (A.4.A) — NOT merely SEALED_DRAINING. Observable: `post_terminal_sends_total` (cumulative; A.14) — `+= 1` exactly when `send_bytes` is entered for a frame whose owning generation has `send_forbidden == true` at send-entry. It is **never** incremented for legal SEALED_DRAINING backlog drain. Attribution is by owning generation: a frame of a NEW generation sent while an OLD generation is SEND_FORBIDDEN does not count. Expected value: `post_terminal_sends_total = 0` for all normal acceptance runs — structurally, because the pacer checks the owning generation's `send_forbidden` flag in its synchronous pre-send stretch (before entering `send_bytes`) and resolves a forbidden head as known-unsent (normative pacer behaviour, §0.8.3 item 3); the counter is retained as the invariant tripwire.

`generation.send_forbidden = bool` (new per-generation state, A.7). It is set `true` **synchronously, before any await**, at exactly these transition sites, and is never cleared for the generation's lifetime (subsequent sets are idempotent no-ops):
1. BARGE-IN — as part of BIT 0 (A.10), before the `response.cancel` await (`turns.py:340-349` region);
2. ABORT — before `await self._cancel_pacer()` (`turns.py:239-247` region);
3. CLOSE — before the awaited pacer cancel in `close()` (`turns.py:103-115` region);
4. LISTEN_START — before `await self._cancel_pacer()` (`turns.py:227-233` region);
5. UPSTREAM_CLOSED — first step of `_on_qwen_closed` (`turns.py:648-659` region);
6. SEND_ERROR — synchronously in the send-exception handler, before the termination sequence's first await;
7. PACER_STALL — in the pacer's synchronous stall-detection stretch, before the A.6 Case-B exit list's first await (both the pre-send lateness trigger and the §2 T>250 trigger; for §2 the completed send already started before the set, so it is not post-terminal);
8. BYTE_CAP_FAILURE — synchronously at the `AUDIO_STORE_BYTE_CAP_REACHED` trigger point (after the oversized packet is encoded, before the first await of the byte-cap handling sequence; A.11).

`SEND_FORBIDDEN` is orthogonal to the connection-wide `send_guard_until` (time-based, binds any next send) — `send_forbidden` is per-generation (identity-based); a NEW generation may send while an OLD one is SEND_FORBIDDEN (subject to `send_guard_until`), and such sends do not increment `post_terminal_sends_total`.

**Byte-cap in-flight head rules (rev-8 B3).** When the pacer is cancelled with `reason = BYTE_CAP_FAILURE`: a head in `RESERVED_WAIT` is known-unsent and enters `flushed_byte_cap_failure_frames` exactly once; a head in `SEND_AWAIT` (cancellation surfaces inside the transport await) is `send_outcome_unknown_frames += 1` and the run is INVALID; a cancellation delivered in the synchronous stretch after the pre-send wait returns is outcome-unknown by the existing witness rule. If the pacer is idle (no popped head), no head disposition arises. Additionally, the pacer's synchronous pre-send `send_forbidden` check guarantees no frame of a SEND_FORBIDDEN generation ever enters `send_bytes`; a head that would have been sent after the flag was set resolves known-unsent into the owning transition's reason bucket.

**Head-ownership representation (rev-8, §0.8.3 item 1).** With the direct-deque store (A.3: the deque's elements ARE the encoded packet objects), the popped head's owning generation is tracked by the pacer in a Connection scalar recorded at pop time (`head_owning_generation_id`); per-frame bookkeeping lives in Connection scalar fields and the counters below, not in wrapper objects inside the store.

**Interleaved flush-type transitions (rev-8, §0.8.3 item 2).** `send_forbidden` sets are idempotent (a bool); FLUSH DISPOSITION is owned by the FIRST transition to complete its flush step (store/head are emptied once; the second transition's flush sees empty state and contributes 0 frames — no double count, residual stays 0). `byte_cap_failures` increments whenever `AUDIO_STORE_BYTE_CAP_REACHED` fires (event-independent of flush ownership); the trigger packet, never stored, always goes to `flushed_byte_cap_failure_frames` exactly once. ≤ 1 TTS stop per generation is preserved by the existing latch (A.9).

**Quiescence (directive §17):** a generation is locally QUIESCENT when (1) no queued encoded frame of it remains, (2) no `RESERVED_WAIT`/`SEND_AWAIT` frame of it remains, (3) no `dl_buf` residue, (4) its local TTS lifecycle has ended, and (5) its `GenerationEnd` has been consumed **or** an immediate local termination path has completed. Upstream terminal arrival is **not** required; a tombstone remains only to classify late upstream events. All closure gauges are sampled atomically at this point.

```
still_stored_frames = 0
in_flight_frames    = 0
```

Normal-completion PASS additionally requires:

```
encode_failed_frames           = 0
send_failed_frames             = 0
send_outcome_unknown_frames    = 0
guard_dropped_pcm_bytes        = 0
safety_truncated_pcm_bytes     = 0
synthetic_tail_encode_failures = 0
qwen_dispatch_errors_total     = 0
accounting_fault_events        = 0
residue_discarded_store_cap_bytes = 0    # a fired STORE_CAP transition (R1/R2) is a labelled
                                         # CONTROLLED_TAIL_TRUNCATION run (§0.7.3), not a clean completion
```

except where the specific test intentionally exercises one of those paths (and the run is then labelled with the path it exercises).

### A.5 Pacer (directive §1/§2/§3/§4/§22; rev-7 PO decision B2 + M1; rev-8 M1/M2/slow-guard)

**Design rule:** the absolute media deadline is authoritative for the long-run rate. `MIN_SEND_START_INTERVAL_MS` is ONLY a hard anti-burst safety floor — it is NOT the media clock. `CATCH_UP_BURST = DISABLED`.

```
MEDIA_FRAME_MS             = 20.0    # media cadence; 50 fps target
MIN_SEND_START_INTERVAL_MS = 15.0    # FINAL (PO B2); hard anti-burst safety floor; NOT the media clock
PACING_SLACK_MS            = 5.0     # = MEDIA_FRAME_MS - MIN_SEND_START_INTERVAL_MS; per-frame recovery depth
SLOW_SEND_THRESHOLD_MS     = 5.0     # a successful send with T > this is a "slow success"
MAX_REBASE_LATENESS_MS     = 250     # single bound for BOTH the A.6 lateness rebase and the §2 slow-send rebase
```

`MIN_SEND_START_INTERVAL_MS = 15.0` is FINAL for R-1f rev-7. There is **no** 18.0 ms value, **no** 15–18 ms runtime range, and **no** environment-dependent selection. 18 ms must never be described as the R-1f floor. The media cadence remains 20 ms / 50 fps and the absolute deadlines remain authoritative. The floor is charged from the send **START** (`previous_audio_send_start_at`), never from the completion.

**Normal pacing (directive §1).** For a clean active run:

```
epoch_ordinal += 1; media_epoch = monotonic_now(); frame_index = 0;
sent_in_epoch = 0; pacer_starts += 1

for frame n:
  deadline_n    = media_epoch + n * MEDIA_FRAME_MS
  normal_floor  = previous_audio_send_start_at + MIN_SEND_START_INTERVAL_MS   (if a previous
                  audio send exists; else -infinity)
  not_before    = max(deadline_n, normal_floor, send_guard_until or -infinity)
  wait until monotonic_now() >= not_before      # re-check after the wait returns; if early, wait again
  send_start_at = monotonic_now()               # recorded immediately before entering send_bytes
  state         = SEND_AWAIT
  perform exactly ONE send attempt
  on success:   previous_audio_send_start_at = send_start_at   # NEVER the send-completion time
                T = completion_time - send_start_at            # §2; see below
  n := n + 1                                     # the absolute deadline sequence continues
```

Ordinary scheduler overshoot is recovered naturally by a following interval slightly below 20 ms, but never below 15 ms. Recovery depth is bounded by `PACING_SLACK_MS = 5 ms` per frame. Example: deadlines 0, 20, 40, …; if a send starts at 21 ms because of 1 ms wake jitter, the next deadline is still 40 ms — its next interval may therefore be ≈ 19 ms, which removes accumulated drift without a burst.

**Slow / failed / unknown send safety (directive §2; M1).** Normal pacing is based on send START time; slow, failed or outcome-unknown sends get a conservative guard. Measure `T = send_completion_time − send_start_at` against `SLOW_SEND_THRESHOLD_MS = 5.0`. Connection state `send_guard_until = None` at connection init.

- **T <= SLOW_SEND_THRESHOLD_MS:** normal absolute-deadline scheduling continues; no guard is armed.
- **SLOW_SEND_THRESHOLD_MS < T <= MAX_REBASE_LATENESS_MS (slow success):**
  ```
  slow_send_events += 1
  send_guard_until = send_completion_time + MIN_SEND_START_INTERVAL_MS      # completion + 15
  slow_guard_deadline = send_completion_time + MIN_SEND_START_INTERVAL_MS   # == the send_guard_until value
  # rev-8 observable (PO slow-guard): on the NEXT confirmed audio send start (the first after
  # this completion, connection-wide, across generations), if
  #     send_start_at < slow_guard_deadline - SPACING_EPSILON_MS
  # then slow_send_guard_violations += 1. Each armed guard is checked against exactly one
  # next audio send start (guards consumed in completion order). Acceptance: = 0.
  break the current clean steady segment                                    # segment terminator
  rebase the next media deadline explicitly:
      next_deadline = send_completion_time + MEDIA_FRAME_MS                 # completion + 20
  the next send must satisfy BOTH next_deadline AND send_guard_until
  no catch-up occurs
  pacer_rebases += 1                                                        # slow-send phase reset
  ```
  Because the media epoch is re-phased so that `deadline_{n+1} == send_completion_time + 20`, `previous_audio_send_start_at` is NOT changed by this rebase (it remains the last send START); the binding term for the next send is the re-based `deadline_{n+1}` together with `send_guard_until`. The guard term is what makes the "≥ completion + 15" rule implementable from the specified state; without it a literal implementation could start as early as `prev_start + 15 = completion + 5` for `T = 10`.
- **T > MAX_REBASE_LATENESS_MS (very slow success):** the send that just completed is dispositioned normally as **SENT** (`sent_confirmed_frames += 1`), but the generation **immediately** enters `PACER_FATAL_STALL` and runs the A.6 Case-B exit list verbatim. Per A.6 step 2 — the AUTHORITATIVE single wording (rev-8 m8): the slow send has already completed and is SENT; there is **no SEND_AWAIT or RESERVED_WAIT head belonging to that completed attempt**; only remaining QUEUED frames are flushed through the PACER_STALL path (`flushed_pacer_stall_frames`), the residue goes to `residue_discarded_pacer_stall_bytes`, upstream is cancelled once if active, exactly one TTS stop is emitted, `pacer_fatal_stalls += 1`, and `NORMAL_LONG_RESPONSE_ACCEPTANCE = FAIL`.
  A multi-second successful send must never silently rebase and continue.
- **Failure, or cancellation after transport entry:** keep the existing `send_failed_frames` / `send_outcome_unknown_frames` rules (A.4.C) and set `send_guard_until = observation_time + MIN_SEND_START_INTERVAL_MS`; any subsequent generation must respect `send_guard_until`.

**Division of labour between the two rebase mechanisms (A.6 vs §2).**

| Mechanism | Trigger (evaluated where) | Bound | Effect | Counter |
|---|---|---|---|---|
| A.6 Case A lateness rebase | `lateness_n = max(0, now − deadline_n)` at the **pre-send wait decision** (before the send) | `40 < lateness_n <= MAX_REBASE_LATENESS_MS` | wall-clock phase reset; head frame preserved and sent | `pacer_rebases += 1` |
| §2 slow-send rebase | `T = completion − start` after a **successful send** | `SLOW_SEND_THRESHOLD_MS < T <= MAX_REBASE_LATENESS_MS` | explicit `next_deadline = completion + 20` and `send_guard_until = completion + 15`; no catch-up | `pacer_rebases += 1` |
| A.6 Case B fatal stall (pre-send) | `lateness_n > MAX_REBASE_LATENESS_MS` | — | `PACER_FATAL_STALL` (steps 1–8) | `pacer_fatal_stalls += 1` |
| §2 fatal stall (post-send) | `T > MAX_REBASE_LATENESS_MS` | — | completed send = SENT, then `PACER_FATAL_STALL` (steps 1–8) | `pacer_fatal_stalls += 1` |

`MAX_REBASE_LATENESS_MS = 250` is the bound for BOTH rebase mechanisms; the §2 path can no longer escape A.6's bound (rev-6 M1 defect). **Both rebases increment the same counter `pacer_rebases`.** Both terminate the current clean steady segment and both exclude their spanning interval from `pacer_mean_inter_send_ms_observed` (numerator AND denominator).

**Positive rate gate (directive §3; rev-8 PO M2 per-segment extrema form) and no-vacuous clause.**
Spacing-only assertions are insufficient.

**Clean contiguous pacing segment.** A maximal run of consecutive confirmed successful audio
sends, all within ONE media-clock epoch, with (a) no rebase (A.6 Case A or §2 slow-send),
(b) no fatal stall, (c) no send failure, (d) no unknown send outcome, (e) no pacer
restart/stop. A generation boundary inside one epoch does NOT terminate a segment (the pacer,
epoch and deadline sequence continue); a rebase or restart always does. Segments never span
epoch boundaries. The frame that triggers an E3 slow-send rebase belongs (by send start) to
the closing segment and is its last frame. Under rev-9 corrected E4 a normal pacer exit after
GenerationEnd drain is also such a terminator; the successor segment opens inside the E4 epoch
of the next pacer task.

**segment_id naming convention.** `c{conn_ordinal}-p{pacer_task_id}-e{epoch_ordinal}-s{segment_ordinal_in_epoch}`
where `epoch_ordinal` counts epoch creations on the connection (1-based) and
`segment_ordinal_in_epoch` counts segments opened inside that epoch (1-based). Ids are unique,
time-ordered, and encode the epoch, so no frame can be attributed to two segments.

For every **qualifying** segment (`steady_segment_frames >= 250` and (a)–(e) clean) record one
raw record in /diag (`steady_segments` journal; raw records are normative diagnostic output):

```
segment_id, steady_segment_first_send_start, steady_segment_last_send_start,
steady_segment_frames, segment_rate_fps, segment_mean_inter_send_ms, epoch_ordinal,
qualifying = true
```

```
segment_rate_fps           = (steady_segment_frames - 1) * 1000
                             / (steady_segment_last_send_start_ms - steady_segment_first_send_start_ms)
segment_mean_inter_send_ms = (steady_segment_last_send_start_ms - steady_segment_first_send_start_ms)
                             / (steady_segment_frames - 1)
```

**Run extrema (aggregation normative; computed over QUALIFYING segments only):**

```
steady_segment_rate_fps_min  / steady_segment_rate_fps_max
steady_segment_mean_inter_send_ms_min / steady_segment_mean_inter_send_ms_max
steady_pacer_segments_qualifying_total    # count of qualifying segments
steady_segment_frames_max                 # max steady_segment_frames over qualifying segments
```

If `steady_pacer_segments_qualifying_total = 0`, the four extrema are UNDEFINED (reported
null); the run is then governed by the no-vacuous clause alone (below) and the extrema rows
are NOT evaluable and must not be compared to constants.

**Acceptance:**

```
steady_pacer_segments_qualifying_total >= 1                      # no vacuous rate pass
steady_segment_rate_fps_min            >= 49.5
steady_segment_rate_fps_max            <= 50.5
steady_segment_mean_inter_send_ms_min  >= 19.80
steady_segment_mean_inter_send_ms_max  <= 20.20
```

The gate is evaluated over EVERY qualifying clean steady segment via its extrema; a run with
any qualifying segment outside the gates is FAIL. A 47.4 fps pacer MUST fail. Anti-burst
checks are kept separately: `pacer_min_inter_send_ms_observed >= 14.999`,
`wire_rate_excess_frames_max <= 1` (media-epoch definition, above). **Neither 15 ms nor 18 ms
is the target cadence — the target cadence remains 20 ms / 50 fps.**

**Compatibility aliases (PO M2).** The rev-7 singular names `steady_pacer_rate_fps` and
`pacer_mean_inter_send_ms_observed` may remain ONLY as per-segment diagnostic fields inside
the raw segment record (identical to `segment_rate_fps` / `segment_mean_inter_send_ms`) or as
compatibility aliases in /health, and MUST NOT be the sole acceptance observables. A.13, A.14
and A.15 reference the extrema fields only.

**No vacuous rate pass (rev-7, retained).** For a normal long-response acceptance run, at
least ONE qualifying clean steady segment with `steady_segment_frames >= 250` is mandatory.
If none exists: `PACING_RATE_EVIDENCE = INSUFFICIENT`, `NORMAL_LONG_RESPONSE_ACCEPTANCE = FAIL`.
The positive-rate gate must never PASS vacuously.

**Deleted metric (directive §4).** `catch_up_frames_over_50fps` is **deleted** — it must not be replaced by any inclusive/exclusive-window metric. The rate behaviour is tested jointly by: the absolute deadlines, the 15 ms hard safety floor, `wire_rate_excess_frames_max` (media-epoch definition), and the per-segment extrema `steady_segment_rate_fps_min/max` and `steady_segment_mean_inter_send_ms_min/max`.

**Connection state and initialization (directive §22).**

```
previous_audio_send_start_at     = None    # no constraint until the first audio send: the first ever
                                           # audio frame is NOT delayed by a prior-send floor
send_guard_until                 = None    # armed on slow success, and on failed/unknown sends;
                                           # an absolute monotonic deadline compared by value, never
                                           # consumed or cleared (a past value simply never binds)
active_pacer_tasks               = 0       # gauge: live pacer tasks owned by this connection (see below)
at every pacer task start (this IS the E1/E4 epoch creation — same rule stated twice,
rev-9 B-1 alignment):
    epoch_ordinal += 1; media_epoch = monotonic_now(); frame_index = 0;
    sent_in_epoch = 0; pacer_starts += 1
```

There must be **exactly one pacer task per connection**; pacer ownership is reserved atomically **before any await** (single-pacer exclusivity; the floor read–check–wait sequence is executed by the single owner pacer only). Every pacer task start other than E1 is an E4 epoch creation (rev-9 B-1): it begins at `frame_index = 0`, `sent_in_epoch = 0`, `epoch_ordinal += 1`, phase = now: it can only be late, never early — it cannot create a catch-up burst. A pacer task EXIT terminates the current clean steady segment even if no new pacer task starts; the next pacer task start opens the next epoch.

**`active_pacer_tasks` / `active_pacer_tasks_max` (rev-7 MINOR 5), verified against the current source.**
- `active_pacer_tasks` (gauge) = number of pacer tasks currently owned by the connection. **Increment** exactly at the atomic ownership reservation, i.e. at the same synchronous instant as `self.pacer_task = asyncio.create_task(self._pacer(self._pacer_pid))` (`turns.py:506`, inside `_ensure_pacer`, `turns.py:503-506`, which contains no `await`). **Decrement** exactly when ownership is released: the pacer's own `finally: if asyncio.current_task() is self.pacer_task: self.pacer_task = None` (`turns.py:600-601`), or the cancel path clearing the slot (`turns.py:627-628` and `turns.py:643-644`).
- `active_pacer_tasks_max` (max observation) = max over the run of `active_pacer_tasks`. **Required: `active_pacer_tasks_max <= 1`.**
- The log-only `MULTIPLE_PACER_VIOLATION` detector (`diag.py:351-355`; `live_pacers` set `diag.py:149,347,362`) is **not** an assertion basis (A.14); this new counter is.

**Guarantees that must be stated and asserted:** scheduled (media-clock) spacing is exactly 20 ms; the observed inter-send interval is never below `MIN_SEND_START_INTERVAL_MS − SPACING_EPSILON_MS = 14.999 ms`; a new response cannot inject an immediate extra frame sooner than `previous_audio_send_start_at + 15 ms` nor before its own deadline; rebases and generation boundaries cannot create catch-up bursts or accumulate +2/+3-frame excursions. `wire_rate_excess_frames_max <= 1` is a THEOREM under the rev-9 media-epoch definition (E1, E2, E3, and E4 = every pacer task start other than E1; see Wire-rate excess above): each send is ≥ its own in-epoch deadline, which yields `wire_excess(t) <= 0` at every evaluation point; the ≤ 1 gate is the PO-mandated acceptance bound, to be proven by Agent F from the definition — not asserted "by construction".

**Additional observables (reported).** `pacer_floor_bind_count` (guard activity; equality of the two terms counts as the deadline term). `pacer_wake_overshoot_mean_ms_observed` — **DIAGNOSTIC ONLY** (rev-7 MINOR 11; no E[j] acceptance precondition and no E[j] < 2 ms clause). Measurement domain: over one active pacer task, take consecutive send starts with the same `pacer_task_id` and `gap < 200 ms`; `δ = gap − MEDIA_FRAME_MS − T(later frame)`, where `T` is the later frame's `t_send − t_intent` when that `send_intent` record exists, else the run's mean `T`; exclude intervals spanning a rebase (A.6 or §2); the field is the max over active runs with `run_frames >= 1000` of the mean δ. It is evidence about slack, not a gate.

**Wire-rate excess (rev-8, PO M1 — MEDIA-CLOCK EPOCH definition).**

A **media-clock epoch** is created by exactly four events:

- **E1** — pacer task start: the connection's FIRST pacer task start;
- **E2** — A.6 Case-A lateness rebase (pre-send decision);
- **E3** — §2 slow-send rebase (post-send, 5 < T <= 250 ms);
- **E4** — EVERY pacer task start OTHER THAN E1 (rev-9 B-1), regardless of why the
  previous pacer ended: normal GenerationEnd drain; ordinary queue drain / pacer
  exit; cancel; stall; send-error cleanup; barge-in cleanup; any later legitimate
  pacer recreation.

At every E4:

```
epoch_ordinal += 1
media_epoch   = monotonic_now()
frame_index   = 0
sent_in_epoch = 0
```

and the current clean steady segment begins inside the new epoch. There is NO state
in which `media_epoch` is re-anchored but `sent_in_epoch` / `epoch_ordinal` are
inherited from the previous pacer task. A normal sequence — response 1 → pacer
drains → pacer exits → response 2 → `_ensure_pacer` creates a new pacer task
(`turns.py:503-506`) — MUST therefore create E4 before response-2's first send.
E2 and E3 are unchanged from rev 8.

At every epoch creation:

```
epoch_ordinal += 1                                  # per connection, 1-based
media_epoch := the absolute deadline of the NEXT frame to be sent in this epoch:
    E1/E4:  media_epoch = monotonic_now()           # frame_index := 0; sent_in_epoch := 0;
                                                    # deadline_0 = media_epoch
    E2:     media_epoch = monotonic_now()           # preserved head becomes frame 0; deadline_0 = now
    E3:     media_epoch = send_completion_time + MEDIA_FRAME_MS
                # frame_index := 0; deadline_0 = completion + 20; the armed guard
                # (completion + 15) is strictly below the deadline, so the deadline binds
sent_in_epoch := 0
the current clean steady segment is TERMINATED at the boundary (segments never span epochs)
```

For an epoch with anchor `epoch_t`, at any instant `t >= epoch_t`:

```
permitted(t)       = max(0, 1 + floor((t - epoch_t) / MEDIA_FRAME_MS))
sent_in_epoch(t)   = number of confirmed audio send starts BELONGING TO THIS EPOCH up to t
                     (a send belongs to the epoch that was active at its send_start_at)
wire_excess(t)     = sent_in_epoch(t) - permitted(t)
wire_rate_excess_frames_max = max over all epochs, over that epoch's send starts, of wire_excess
```

Evaluation points are the send starts: `sent_in_epoch` is a step function and `permitted` is
non-decreasing, so the maximum over send starts is the maximum over all t.

**Theorem (bound TO BE PROVEN by Agent F from this definition, for E1, E2, E3 AND corrected E4 — not accepted "by construction").**
Within one epoch every send with in-epoch index `j` (0-based) starts at
`s_j >= deadline_j = epoch_t + j*MEDIA_FRAME_MS` (A.5 normal pacing; both rebase mechanisms
re-anchor before the next send; a fresh pacer task (E1/E4) cannot send before its own
`deadline_0 = media_epoch = its start time`). If `k` sends have occurred by `t`, then `s_{k-1} <= t`, hence
`20*(k-1) <= t - epoch_t`, hence `k <= 1 + floor((t - epoch_t)/20) = permitted(t)`. Therefore
`wire_excess(t) <= 0` at every evaluation point, and `wire_rate_excess_frames_max <= 0 <= 1`.
**Gate KEPT unchanged: `wire_rate_excess_frames_max <= 1` (PO M1 — NOT loosened to 2).** The
single frame between the proven bound (<= 0) and the gate is PO-mandated measurement headroom,
not an allowance to outrun the clock. (`max(0, ·)` is vacuous in-domain — any in-epoch
evaluation point has `t >= epoch_t` so `permitted >= 1 > 0`; it is retained exactly as the PO
wrote it and must not be "simplified" into a behaviour change.)

**Epoch-boundary carry-over rule (PO M1).** The first-send overshoot of a PREVIOUS epoch must
not be carried into a new epoch's allowance. Because `sent_in_epoch` resets to 0 and
`permitted` re-anchors at every E1–E4 event, no overshoot credit or debt crosses a boundary.
The rev-7 anchor-based definition (anchor = first audio send of the active run, reset only by
a 1000 ms idle gap) is DELETED, including `WIRE_RUN_ANCHOR_GAP_MS`: it yields
`wire_excess = ceil(delta_first/20)`, i.e. 2 for a compliant pacer whose first frame
overshoots by 20–40 ms with full catch-up (rev-7 Agent F M1/M8 falsification; reproduced).

**Cross-epoch / cross-generation burst protection is INDEPENDENT and unchanged:**
`pacer_min_inter_send_ms_observed >= 14.999` and the connection-wide
`previous_audio_send_start_at` floor (A.15 row 1). A burst straddling an epoch boundary is
invisible to `wire_excess` by design and is caught by row 1. Target: `wire_excess(t) <= 0`;
gate: `wire_rate_excess_frames_max <= 1`. Sends are never earlier than their deadlines, so
this metric only catches *fast* violations; the slow direction is covered by the §3 gate.

Interval metrics (timestamp basis = `send_start_at`; a completion-based reading is non-normative): `pacer_min_inter_send_ms_observed` is **connection-wide** (minimum over consecutive successful sends across all generations, restarts and rebases). `pacer_mean_inter_send_ms_observed` is evaluated over the §3 clean segments. Intervals spanning a `WALL_CLOCK_PHASE_RESET` (A.6 Case A), a §2 slow-send rebase, or a pacer restart are excluded from numerator AND denominator (those delays are bounded separately). `SPACING_EPSILON_MS = 0.001` absorbs float noise only; any interval below `MIN_SEND_START_INTERVAL_MS − SPACING_EPSILON_MS` increments `pacer_short_interval_count`.

Lead, defined for frame `n`:

```
lead_frames(n) = max(0, (deadline_n - send_start_at_n) / MEDIA_FRAME_MS)
pacer_lead_frames_max = max over frames        # structurally 0 under this design; reported
```

### A.6 Rebase and event-loop stall (rev-7 M1: unified fatal-stall exit)

A rebase **never discards stored media frames**. It only resets wall-clock phase.

```
LATE_REBASE_THRESHOLD_MS = 40
MAX_REBASE_LATENESS_MS   = 250
```

`lateness` is defined (m-1): for the frame at the head of the send slot,

```
lateness_n = max(0, monotonic_now() - deadline_n)      # evaluated at the pre-send wait decision point
```

Queue-empty waits do not evaluate lateness: the evaluation happens at the next send decision (rev-8, §0.8.3 item 5). A > `MAX_REBASE_LATENESS_MS` queue-empty idle gap followed by a new frame in a live pacer therefore enters Case B below (unchanged behaviour, now stated).

**Case A — `LATE_REBASE_THRESHOLD_MS < lateness_n <= MAX_REBASE_LATENESS_MS`:**

- preserve every queued frame
- preserve the current head frame
- set the current frame's new deadline to now (equivalently, shift `media_epoch` so that `deadline_n == now`)
- do **not** reset source/frame identity
- do **not** discard media
- `pacer_rebases += 1`
- update `pacer_rebase_max_lateness_ms`
- the connection-wide `MIN_SEND_START_INTERVAL_MS = 15.0` floor still applies
- intervals spanning this phase reset are excluded from `pacer_mean_inter_send_ms_observed` (A.5); the delay is bounded here instead
- Case A is the **lateness**-triggered rebase (evaluated at the pre-send wait decision, before the send). The §2 slow-send rebase (evaluated after a successful send from `T = completion − start`) is the second mechanism; it shares the same bound `MAX_REBASE_LATENESS_MS = 250` and also increments `pacer_rebases`. The two are distinct triggers on distinct quantities (`lateness_n` vs `T`); a send never satisfies both in the same frame (Case A fires before the send, §2 fires after a send that already started).

Therefore rebase means `WALL_CLOCK_PHASE_RESET`, not `MEDIA_FRAME_LOSS`.

**Case B — `lateness_n > MAX_REBASE_LATENESS_MS` (pre-send), or `T > MAX_REBASE_LATENESS_MS` (slow successful send, §2):**

Do **not** silently rebase after an arbitrarily large stall. This step list is the SINGLE authoritative `PACER_FATAL_STALL` exit for BOTH triggers (A.6 lateness and §2 `T`); the §2 path differs only in that the frame that triggered it was already dispositioned as SENT before this list runs (so there is no in-flight head). Trigger `PACER_FATAL_STALL`, then:

1. invalidate the active generation — **mark it locally terminal** (local-terminal predicate, A.4.A) and clear `current_resp_id` if it points at this generation
2. resolve the **in-flight head frame** and flush all queued unsent frames to `flushed_pacer_stall_frames` (directive §6): a head frame in `RESERVED_WAIT` is known-unsent and enters the same bucket; a head frame in `SEND_AWAIT` is `send_outcome_unknown_frames` and the run is INVALID (A.4.C). After this step `in_flight_frames == 0`. For the §2 trigger (rev-8 m8, authoritative wording): the slow send has already completed and is SENT; there is NO `SEND_AWAIT` or `RESERVED_WAIT` head belonging to that completed attempt; only remaining QUEUED frames are flushed through the PACER_STALL path, and the just-completed slow send is already in `sent_confirmed_frames`.
3. **discard the current `dl_buf` residue `R` (0 ≤ R < 960 B): `residue_discarded_pacer_stall_bytes += R`; `dl_buf.clear()`** — the bytes are already in `admitted_pcm_bytes`, so they must **not** be re-classified as `safety_truncated_pcm_bytes`. After this step the residue is 0.
4. flush any un-consumed `GenerationEnd` marker of that generation (marker excluded from frame counters, A.9)
5. cancel upstream once if still active (A.8)
6. emit exactly one TTS stop
7. mark the generation locally terminal (idempotent) and return to a clean state — no late delta may re-enter it (A.4.A)
8. `pacer_fatal_stalls += 1`

No frame may be silently discarded. `audio_rebase_discarded_frames` is an explicit invariant counter and must remain `0`.

A simulated 10-second event-loop stall must therefore produce a visible, bounded `PACER_FATAL_STALL` outcome, not a bare clock rebase. The same is required of a very slow successful send with `T > 250 ms` (PO M1): it must enter `PACER_FATAL_STALL`, never silently rebase and continue.

### A.7 Generation definition

The canonical generation is **not** `diag.active_gen`.

```
generation_id  ≡  one upstream Qwen response_id      (one-to-one)
```

- Generation begins at `response.created(response_id)` (`turns.py:293-300`).
- Generation identity remains the **same** across local invalidation, barge-in, abort, and the safety-cap transition, until the response is upstream-terminal or locally finalized/tombstoned.
- A new `response.created` with a new `response_id` creates the next generation.
- Maintain a `response_id → generation` mapping plus a tombstone, long enough to classify late deltas and terminal events.
- An id-less end event is applied to the live generation (existing deliberate tolerance, `turns.py:410-418`); the tombstone map backs A.4.A's `STALE` classification for late deltas.
- A generation is **locally terminal** exactly when the local-terminal predicate of A.4.A fires (normal seal, cap seal, or invalidation by barge-in, abort, close, listen_start, upstream-close, send error, fatal stall). Local terminality removes it from the `LIVE` class; the tombstone then absorbs any later upstream event (no marker/stop/tail — A.9). Note `response.audio.done` does not by itself clear `current_resp_id` (`turns.py:452-453`); the explicit clears are part of the terminal transitions themselves (A.4.A/A.6/A.4.C/A.10).
- The one-shot cancel latch (A.8) is stored **on this response generation**.

Therefore one upstream response cannot receive two cancels merely because `diag.active_gen` changed.

### A.8 One-shot cancel

`cancel_upstream_once(gen, reason)` — before **any** await:

```
if gen.cancel_requested:
    return ALREADY_REQUESTED

if gen.upstream_terminal:
    record cancel_skipped_upstream_already_done
    return ALREADY_TERMINAL

gen.cancel_requested = true
gen.cancel_attempts  += 1
gen.cancel_reason     = reason
```

Only then may `response.cancel` be awaited. Required: `cancel_max_per_generation <= 1`, where the field is defined as **max over generations of that generation's `cancel_attempts`**.

- An exception raised by the awaited `response.cancel` increments `cancel_send_errors` (reported; the latch is one-shot regardless, and the local stop sequence must not depend on the upstream cancel — A.10).
- Both existing `current_resp_id`-gated cancel sites (`turns.py:249-255`, `:340-349`) are rewritten to call `cancel_upstream_once(gen, reason)`; neither may consult `diag.active_gen`.

### A.9 Generation-end marker

The single future store must support a non-audio marker:

```
GenerationEnd(gen_id, reason)
```

or an equivalent explicit sealed-generation state. The marker does **not** count toward `MAX_FUTURE_FRAMES`, `audio_store_current_frames`, or `audio_store_current_bytes`.

Normal completed response:

1. process the final residual `N = len(dl_buf)` at the first seal:
   - `unsent_backlog_frames < MAX_FUTURE_FRAMES`: `N == 0` → no synthetic tail; `0 < N < 960` → **exactly one** synthetic tail frame (encode-failure path per A.4.B);
   - `unsent_backlog_frames == MAX_FUTURE_FRAMES`: `N == 0` → no synthetic tail, no cap event; `0 < N < 960` → the **A.2 route R2** applies: **no** synthetic tail frame, **no** 1501st frame, `AUDIO_STORE_CAP_REACHED` fires exactly once for this generation (unless already entered via R1), `residue_discarded_store_cap_bytes += N`, `dl_buf.clear()`, `synthetic_tail_frames`/`synthetic_tail_source_bytes` unchanged.
2. seal the generation — the generation enters **SEALED_DRAINING** (A.4.A); it does **NOT** enter SEND_FORBIDDEN and `send_forbidden` remains false
3. enqueue **exactly one** `GenerationEnd` after its final playable frame — in **both** branches (R2 neither adds, removes nor duplicates the marker)
4. the pacer drains all prior audio (in the R2 branch: the already accepted 1500-frame backlog) — legal SEALED_DRAINING drain; `post_terminal_sends_total` is NOT incremented (rev-8 B2)
5. the pacer consumes the `GenerationEnd`
6. emit exactly one TTS stop
7. mark the generation quiescent / transition appropriately

`CONTROLLED_TAIL_TRUNCATION`: when the occupancy cap fires — route R1 (delta-triggered) or route R2 (seal-time) — no future audio is accepted; the residue was discarded at the transition (A.2 R1 / R2), so there is **no** synthetic tail for this generation. After all already-accepted playable frames, the generation is consumed/ended with **exactly one** `GenerationEnd`. **Already-entered case:** if the generation already entered the state via R1, then by R1.3 `len(dl_buf) == 0` at seal, so the seal is a normal seal with `N == 0`, R2 does not fire, no second transition event and no second residue disposal occur, and the single `GenerationEnd` is unchanged. At that seal the generation becomes SEALED_DRAINING (not SEND_FORBIDDEN); the already-accepted backlog drains legally.

**Locally terminal generations are sealed against late events (directive §16; carried B2).** Once a generation is locally terminal (either tier — SEALED_DRAINING or SEND_FORBIDDEN) — normal seal, cap seal, or any invalidation per the A.4.A predicate — a later upstream terminal event for the same `response_id` is processed **only** through the tombstone accounting (counters/log): it must **not** enqueue a second `GenerationEnd`, emit a second TTS stop, process a synthetic tail, re-open the store, or restart a pacer. `end_markers_max_per_generation <= 1` and `tts_stop_emissions_max_per_generation <= 1` therefore hold by construction on every path.

Barge-in / abort: the immediate local stop overrides tail-drain. Flush the remaining old-generation audio **and** its end marker, emit the TTS stop immediately, and do **not** later emit a second stop (a generation that has already emitted a stop must suppress the marker-driven stop).

Counter semantics (directive §16):

```
end_markers_max_per_generation        <= 1
tts_stop_emissions_max_per_generation <= 1
```

- Both fields are the **MAXIMUM over all generations observed in the scoped run** — they are **not** sums. Per-generation raw values remain in `/diag`.
- `tts_owner_generation_id` is set when TTS start is **actually emitted**. A TTS-stop counter increments only when a stop is **actually emitted**, never when `_stop_tts()` is merely called (a call while `tts_active` is already False is a no-op, `turns.py:480-481`).
- The stop is attributed to `tts_owner_generation_id` **even if that generation has already become a tombstone**; after emission `tts_owner_generation_id = null`.

### A.10 Barge-in invariant

Preserved: **invalidate before the first await**. Each step is **exception-contained** so a failure cannot abort the remaining steps.

Mandatory local step bits (one sequence record per barge-in; directive §19):

```
BIT 0 = GENERATION_INVALIDATED            (local state write + local-terminal mark + send_forbidden = true
                                          (SEND_FORBIDDEN, A.4.A) + current_resp_id clear; all synchronous,
                                          before any await)
BIT 1 = PACER_CANCELLED_OR_NOT_APPLICABLE reason=barge_in;  SUCCEEDED | NOT_APPLICABLE(no_live_pacer) | FAILED
BIT 2 = STORE_FLUSHED_OR_EMPTY            reason=barge_in;  SUCCEEDED | FAILED
BIT 3 = TTS_STOP_EMITTED_OR_NOT_ACTIVE    SUCCEEDED | NOT_APPLICABLE(tts already inactive) | FAILED
```

- Required mask: `0b1111`. Each step result is one of SUCCEEDED / NOT_APPLICABLE / FAILED; FAILED on any mandatory bit increments **`barge_in_sequence_incomplete`** (derived predicate; each step counts at most once per barge-in). `barge_in_sequences_total += 1` per barge-in.
- Cumulative failure counters: `barge_in_invalidate_failures`, `barge_in_pacer_cancel_failures`, `barge_in_store_flush_failures`, `barge_in_tts_stop_failures`.
- Upstream `response.cancel` is **NOT** part of the mandatory local completion mask; it is governed separately by the one-shot cancel contract (A.8: `cancel_attempts`, `cancel_send_errors`, `cancel_skipped_*`).
- Boundary note: a `CancelledError` delivered while the pacer is suspended in `RESERVED_WAIT` resolves the popped frame as known-unsent (`flushed_bargein_frames`); a cancellation in the synchronous stretch after the wait returns surfaces inside the transport await and is outcome-unknown by the A.4.C rule. Barge-ins land in the suspended-wait window in practice, so `send_outcome_unknown_frames == 0` is the expected reading for barge-in runs. Because BIT 0 sets `send_forbidden` before BIT 1's cancel await, the head can never enter `send_bytes` after the barge-in decision.
- **Ownership of the `RESERVED_WAIT` head (minor 3).** BIT 1 (`PACER_CANCELLED_OR_NOT_APPLICABLE`) owns resolution of the single `RESERVED_WAIT` head frame — the frame the pacer has already popped from the store — into `flushed_bargein_frames` (known-unsent per A.4.C). BIT 2 (`STORE_FLUSHED_OR_EMPTY`) owns **only** the remaining `QUEUED` frames still inside the store. Because the head has already left the store, BIT 2 must not see it and must not re-classify it, so the head is counted **exactly once**. If BIT 2 could still reach the head (e.g. a store keeping a reserved slot), the double count would surface as an A.15 row-8 residual; the split above is normative. Cross-reference: A.4.C cancellation bullets and A.6 case-B step 2 (same split on the fatal-stall path).

Required: `barge_in_sequence_incomplete = 0` (reported against `barge_in_sequences_total`).

### A.11 Byte emergency ceiling (directive §13)

The interim ceilings (2 MiB in rev 3; 300 KiB in the interim rev-4/5 drafts) are superseded by the directive:

```
MAX_FUTURE_AUDIO_BYTES = 512 KiB = 524288 bytes
```

Justification algebra (directive §13):

- `524288 / 1500 ≈ 349.5 B/frame` allowance at full occupancy — far above the observed normal packet distribution (observed max 108 B ⇒ **3.24× margin**), so this is **not** normal congestion policy.
- It is low enough that pathological packet inflation can trigger it **before 1500 frames**: e.g. a ≤ 1275 B/frame stream (the Opus 20 ms arithmetic bound at the 510 kbit/s protocol ceiling) fires it at about frame ⌈524288 / 1275⌉ ≈ 412.
- It is therefore testable with an intentionally oversized mock packet fixture (Test C) — not a dead branch.

Check point: the decision is evaluated **after encoding** (the packet size is unknowable earlier). The **triggering packet itself is discarded into `flushed_byte_cap_failure_frames`** — counted once in `encoded_full_frames` and once in that bucket — and is never stored.

Event and classification:

```
AUDIO_STORE_BYTE_CAP_REACHED
RESOURCE_SAFETY_FAILURE
```

Required behaviour when `AUDIO_STORE_BYTE_CAP_REACHED` fires (rev-8 B3; each step's ordering is normative):
1. Mark the generation `send_forbidden = true` (SEND_FORBIDDEN tier, A.4.A) **before the first await** of this sequence.
2. Cancel the pacer with `reason = BYTE_CAP_FAILURE` (A.4.C byte-cap head rules apply: `RESERVED_WAIT` ⇒ known-unsent; `SEND_AWAIT` ⇒ outcome-unknown + run INVALID).
3. Head in `RESERVED_WAIT` ⇒ KNOWN UNSENT ⇒ `flushed_byte_cap_failure_frames += 1`.
4. Head in `SEND_AWAIT` ⇒ `send_outcome_unknown_frames += 1`; run = INVALID.
5. Flush all remaining QUEUED accepted frames to `flushed_byte_cap_failure_frames`.
6. The triggering oversized encoded packet is dispositioned **exactly once** into `flushed_byte_cap_failure_frames` and is **never stored**. Reconciliation with the "counted once in `encoded_full_frames`" rule: the packet IS counted once in `encoded_full_frames` (it was encoded), and its 960 source bytes ARE in `admitted_pcm_bytes` (admitted at frame-formation — `dl_buf` consumption, `turns.py:378-379` — before the cap check; the cap governs only whether the encoded packet may be stored). No double count in either closure.
7. Residue: `residue_discarded_byte_cap_failure_bytes += len(dl_buf)`; `dl_buf.clear()` (never re-classified as `safety_truncated`).
8. `cancel_upstream_once()` (A.8).
9. Exactly one TTS stop.
10. `byte_cap_failures += 1`.
11. Normal acceptance FAILS (run labelled `RESOURCE_SAFETY_FAILURE`; the SEND_AWAIT-head case is additionally INVALID).
12. Quiescence requires `queued_audio_frames = 0`, `in_flight_frames = 0`, `still_stored_frames = 0`, `still_buffered_pcm_bytes = 0`.

The byte-cap check covers BOTH encode sites (the delta-loop encode and the seal-time tail encode — §0.8.3 item 4). If it fires on the seal-time tail encode: no tail frame is created, `synthetic_tail_frames`/`synthetic_tail_source_bytes` are unchanged, and the tail's N bytes go to `residue_discarded_byte_cap_failure_bytes` (they were already admitted — the frame-formation rule of step 6 does not apply because no frame was formed; they enter the residue term of closure B).

Required test (exercises the branch):

| Test | Scenario | Expected |
|---|---|---|
| C | mock encoder fixture emitting oversized packets (> 349.5 B/frame sustained, e.g. ~1 KiB/packet, stalled pacer) | `AUDIO_STORE_BYTE_CAP_REACHED` fires before the 1500-frame cap, at ≈ ⌈524288 / packet_size⌉ frames; classification `RESOURCE_SAFETY_FAILURE`; store → `flushed_byte_cap_failure_frames`; residue → `residue_discarded_byte_cap_failure_bytes`; exactly one TTS stop; `byte_cap_failures = 1`; closures residual 0; run cannot PASS |

The frame cap remains the normal backlog policy.

### A.12 Client observability — single normative specification (rev-7 M2; rev-8 m5/m6/m7)

This section is the **single normative client instrumentation specification**. It supersedes earlier Agent-B field lists while adopting all required Agent-B observables. Default **OFF**. **No logging or I/O in the realtime callback and none inside `PcmFifo.pull`**; callback-side and FIFO-side fields are integer counter updates only and are reported asynchronously outside the callback.

**Terminology (normative).** The client has a **TTS playout session**, correlated by the server `tts` message pair `{"type":"tts","state":"start"}` / `{"type":"tts","state":"stop"}` (`session.py:94-99`; `plugins/audio.py:141-150`). It is **not** the Qwen response generation: the client never sees `response_id`/`resp_id` in the audio path — `AudioCodec.write_audio(opus_data: bytes)` receives bytes only (`audio_codec.py:373-403`, called from `plugins/audio.py:174`; `on_incoming_audio(self, data: bytes)` at `plugins/audio.py:168`). All client-side scoped metrics below use **session** wording; the phrase "that generation's TTS stop/flush" is retired.

Q1 (inbound Opus queue — `protocol_manager.py:24,42-44,162-178`):

```
incoming_queue_current
incoming_queue_peak
incoming_queue_dropped_packets   # +1 per over-cap packet the queue rejects
```

Over-cap policy (accurate wording): enqueue tries `put_nowait`; on `QueueFull` it removes **one** oldest packet silently (`protocol_manager.py:170-176`); only if the queue is **still** full does it log `入站音频队列仍满，丢弃当前帧` and drop the incoming frame (`protocol_manager.py:177-178`). `incoming_queue_dropped_packets` counts every rejected incoming packet.

Q2 (decoded PCM FIFO — `audio_codec.py:26,68-70`; `audio_buffer.py:22-83`):

```
pcm_fifo_current_samples
pcm_fifo_peak_samples
pcm_fifo_dropped_samples              # push() over-cap drop-oldest (audio_buffer.py:43-52); silent (no log)
pcm_fifo_partial_underfill_events     # counted INSIDE PcmFifo.pull (audio_buffer.py:54-74)
pcm_fifo_partial_zero_pad_samples     # counted INSIDE PcmFifo.pull (audio_buffer.py:54-74)
pcm_fifo_drained_to_empty_events      # NEW rev-8 (m7) — counted INSIDE PcmFifo.pull; exact predicate below
```

**The `pcm_fifo_*` fields (specifically the two `pcm_fifo_partial_*` counters) are properties of the TTS FIFO instance `self._tts_fifo`** (the instance constructed at `audio_codec.py:68-70`/`263-265`). The music FIFO `self._music_fifo` is **not** part of the client gate contract; an optional diagnostic pair `music_fifo_partial_underfill_events` / `music_fifo_partial_zero_pad_samples` may be reported but must never be folded into `pcm_fifo_partial_zero_pad_samples`, or music underfill would pollute the TTS starvation falsifier.

**FIFO instance identity (rev-8, m6).** Every `PcmFifo` construction assigns a fresh, monotonically increasing `pcm_fifo_instance_id` (constructor `audio_buffer.py:22`; construction sites: TTS FIFO `audio_codec.py:68-70`, music FIFO `audio_codec.py:71-73`, both rebuilt at `audio_codec.py:263-268` inside `_configure_pipeline`). The TTS FIFO instance the counters belong to is identified by this id. All `pcm_fifo_*` counters are **per-instance monotone**; monotonicity is NOT assumed across FIFO object replacement (rev-8 m6). The music FIFO (`self._music_fifo`) carries its own instance ids and is not part of the client gate contract.

**Normative `PcmFifo.pull` counting (M2 fix).** The missing tail is zero-filled **inside** `PcmFifo.pull`, and the counter is placed exactly there:

```
def pull(self, n):
    with self._lock:
        if self._size == 0:
            return None                       # (I1) whole-empty branch — UNCHANGED; feeds the callback's
                                              #      outdata.fill(0.0) → whole_block_zero_fill_count
        size_before = self._size              # (I3) NEW rev-8 — captured before consumption
        out = np.zeros(n, dtype=np.float32)   # audio_buffer.py:59 — full-length, tail zeroed
        filled = 0
        ... existing consume loop (audio_buffer.py:61-73) ...
        missing = n - filled                  # (I2) partial counting, immediately before `return out`
        if missing > 0:                       #     ⟺ 0 < available_samples < n
            self.pcm_fifo_partial_underfill_events += 1
            self.pcm_fifo_partial_zero_pad_samples += missing
        if size_before > 0 and self._size == 0:          # (I3) NEW rev-8 drained edge (m7)
            self.pcm_fifo_drained_to_empty_events += 1
        return out
```

- **(I1)** unchanged (`audio_buffer.py:57-58`); the `None` early-return produces **no** drained edge (it is not a "drain" — nothing was consumed) and is still the only producer of `whole_block_zero_fill_count` via `_pull_mixed` (`audio_codec.py:272-297`) → `outdata.fill(0.0)` (`audio_codec.py:227`).
- **(I2)** unchanged from rev-7: predicate `missing > 0` ⟺ `0 < available < n`.
- **(I3, rev-8 m7):** `pcm_fifo_drained_to_empty_events += 1` exactly once when `size_before > 0` AND `size_after == 0` as the pull completes. Insertion point: **after** the (I2) partial counters of the same pull, immediately before `return out`. Per-pull semantics: at most +1 edge per pull. No I/O, no logging, no timestamp read inside the lock — counter increment only.
- **The edge predicate excludes:** (i) the `size == 0` early return (returns `None`, no counter moves); (ii) partial pulls with leftover (`size_after > 0`); (iii) `push()` (can never empty the FIFO) and `clear()` (`audio_buffer.py:76-83` bypasses `pull` entirely — **`clear()` does NOT produce a drained edge**; a barge-in clear closes the window via T1, not T2).
- **Ordering guarantee (m7):** because (I3) is evaluated after (I2) in the same pull, the end snapshot taken on the first drained edge necessarily includes that pull's partial zero-pad samples.
- **RETIRED:** the callback-level `partial_zero_pad_samples` (`audio_codec.py:192-239` anchor) is **replaced** by `pcm_fifo_partial_zero_pad_samples`. It is not kept under any alias; retaining it would double-count `tts_playout_partial_zero_pad_samples`. The callback's short-return branch (`audio_codec.py:226-229`) is a *resampler-buffer* residue condition (`drain_output_buffer`, `audio_converter.py:150-167`), not FIFO underfill, and feeds no counter.

Decoder (`audio_codec.py:373-403`):

```
decode_errors
toc_null_count                       # audio_codec.py:382-384
decoded_short_frame_count            # audio_codec.py:395-398
```

Playback / PortAudio (`audio_codec.py:192-239`):

```
whole_block_zero_fill_count          # callback all-empty branch only (audio_codec.py:218-227)
output_callback_interval_min
output_callback_interval_max
output_callback_interval_p95
portaudio_output_underflow_count     # classify; do not throttle away
portaudio_output_overflow_count
```

(The exception path `audio_codec.py:239` also fills zeros; it must be counted separately as a callback error and must **not** increment `whole_block_zero_fill_count`.)

**TTS-playout-session-scoped starvation metrics (feeds A.13).** The window is correlated by the client TTS session, not by a generation:

```
playout_window.start := the first TTS-FIFO push of the session
                        (audio_codec.py:400 `self._tts_fifo.push(audio_float32)`) that occurs
                        at or after the session's tts start message

playout_window.end   := the FIRST of:
    (T1) the TTS FIFO is cleared by `clear_audio_queue()` (audio_codec.py:420-426), applied
         while the session is active — the keep_listening=True path (session.py:134-139);
         snapshot the OLD FIFO counters BEFORE the clear takes effect;
    (T2) post-tts-stop natural drain (keep_listening=False path, session.py:117-119 returns
         BEFORE clear_audio_queue). REV-9 (PO M-1) TWO-BRANCH RULE — this completely
         replaces the rev-8 "first new pcm_fifo_drained_to_empty_events edge after the
         tts stop" wording. When the client processes the tts stop for the active TTS
         playout session, it takes an ATOMIC STOP SNAPSHOT of the TTS FIFO, for the SAME
         pcm_fifo_instance_id: fifo size (fifo_size_at_stop),
         pcm_fifo_partial_underfill_events, pcm_fifo_partial_zero_pad_samples,
         pcm_fifo_drained_to_empty_events, pcm_fifo_dropped_samples, and all other scoped
         client acceptance counters (at minimum: whole_block_zero_fill_count, the output
         callback interval extrema/p95, portaudio under/overflow counts, callback error
         count, decode_errors/toc_null_count/decoded_short_frame_count, Q1 counters,
         clear_audio_queue_samples_at_stop). The snapshot is a lock-held read (see
         Sampling rule) so the branch decision is atomic w.r.t. push/pull. Exactly ONE
         branch then applies:
         (T2-A — FIFO ALREADY EMPTY AT STOP) IF fifo_size_at_stop == 0: end the active
              TTS playout measurement window IMMEDIATELY at the stop-processing snapshot.
              Label: T2_EMPTY_AT_STOP. No future pcm_fifo_drained_to_empty_events edge is
              required. A later session's push/pull MUST NOT be allowed to close or alter
              this already-closed window. The scoped deltas are computed from the
              window-start snapshot to the T2_EMPTY_AT_STOP snapshot, for the same
              pcm_fifo_instance_id only.
         (T2-B — FIFO NON-EMPTY AT STOP) IF fifo_size_at_stop > 0: record
              t2_stop_fifo_instance_id and t2_stop_drained_edge_baseline =
              pcm_fifo_drained_to_empty_events at stop, and keep the window open until
              the FIRST edge satisfying: same pcm_fifo_instance_id AND
              pcm_fifo_drained_to_empty_events > t2_stop_drained_edge_baseline. The end
              snapshot occurs AFTER all counters caused by that draining pull have been
              updated. Label: T2_DRAIN_AFTER_STOP. A drain edge belonging to a later TTS
              session MUST NOT close this window. Attribution rule: an edge is attributed
              to the window's owning session iff no later tts start has been observed at
              the moment of edge observation; session identity and FIFO instance identity
              must both match. If a new tts start occurs before T2-B closes, the existing
              T4 supersession rule governs: old session already drained/cleared ⇒ close
              correctly (label T4); old queued audio remains ⇒ client half = INVALID.
              RACE DIRECTION (erratum m-4): the counters are monotone per instance, so
              next-session pollution can only inflate the old window's delta — a spurious
              FAIL / CLIENT_TELEMETRY_INVALID — and can never turn a real underfill into a
              false PASS. This bounded race MUST NOT be "fixed" with blocking I/O in the
              realtime callback.
         T2-B remains subject to the FIRST-of ordering of this list: a
         clear_audio_queue() applied while a T2-B window is open terminates it via the
         T1/T3 mechanics (snapshot OLD counters BEFORE the clear) — clear() produces no
         drained edge (audio_buffer.py:76-83), so the pending T2-B baseline is discarded
         and the window never waits for an edge that cannot fire.
    (T3) FIFO teardown/rebuild while a MEASUREMENT WINDOW is open (session active
         OR a T2/T4 wait is pending) — rev-8 m6 ORDERING IS NORMATIVE:
         FIRST snapshot the OLD FIFO counters, THEN end the window, THEN rebuild/replace
         the FIFO. Applies to `close()` (audio_codec.py:537-571, which clears via
         clear_audio_queue at 547) and to `_configure_pipeline` rebuilds
         (audio_codec.py:263-265, reached from `initialize` and `reload_devices`:515).
         A scoped delta may NEVER span two FIFO instance ids.
    (T4) supersession: a new tts start arrives before T1/T2/T3. The prior window closes
         at the new start ONLY IF its TTS FIFO was already drained or cleared; if queued
         audio from the prior session remains, the run's client half is INVALID
         (overlap uncountable) — §0.7.3 item 3. No overlap, no double count.

The window MUST NOT end merely because the tts-stop handler returned.
If the FIFO instance changes without a properly recorded T3 terminal event:
CLIENT_TELEMETRY_INVALID = 1 and the run's client half is INVALID (rev-8 m6).

Window metadata (rev-8; rev-9 M-1): start_fifo_instance_id and end_fifo_instance_id are
recorded at window start/end, together with the terminal-event label
(T1 | T2_EMPTY_AT_STOP | T2_DRAIN_AFTER_STOP | T3 | T4). On every T2-terminal window,
end_fifo_instance_id MUST equal t2_stop_fifo_instance_id (the instance captured in the
stop snapshot). A valid scoped delta requires start_fifo_instance_id ==
end_fifo_instance_id == t2_stop_fifo_instance_id; otherwise the window is
cross-instance and rejected (CLIENT_TELEMETRY_INVALID = 1).

Abnormal shutdown — AudioCodec.__del__ (rev-9 mi-5). The (T1)–(T4) list above is
exhaustive for NORMAL certification terminals; AudioCodec.__del__
(audio_codec.py:573-611) is NOT covered by those paths and is NOT a clean
T1/T2/T3/T4 certification terminal: it is an EMERGENCY DESTRUCTION path. If __del__
occurs while an R-1f TTS playout measurement window is active: CLIENT_TELEMETRY_INVALID
= 1 and the client half of that acceptance run is INVALID. It MUST NOT silently clear
the FIFO and allow the run to claim clean client telemetry — note __del__ does call
_tts_fifo.clear() (audio_codec.py:587) and clear() produces no drained edge
(audio_buffer.py:76-83), so absent this rule an emergency destruction would be
indistinguishable from a clean T1 close. If __del__ occurs only after the measurement
window has already closed, it has no effect on that completed window. No
destructor-time I/O or logging is required (mechanism note: the invalidity may be
recorded by an in-memory flag read by the run collector after the fact). This is an
integrity classification rule, not a new normal shutdown path.

tts_playout_whole_block_zero_fill_count := delta of whole_block_zero_fill_count over the window
tts_playout_partial_zero_pad_samples     := delta of pcm_fifo_partial_zero_pad_samples over the window

Sampling rule: snapshot the raw counters at window start and again immediately after the
window-end event; the scoped value is end − start. Counters are monotone **per FIFO
instance** (rev-8 m6); they are NOT monotone across FIFO replacement, which is exactly why
T3 mandates snapshot-old → end-window → rebuild and why a delta must never span two
instance ids. A single int read is atomic under the GIL, so a snapshot needs no lock;
instance-id reads use the same rule.

REV-9 (M-1) exception: the T2 STOP SNAPSHOT and the T2-B END SNAPSHOT are lock-held
atomic reads of the TTS FIFO scalars (a read-only accessor acquiring the same
threading.Lock as push/pull, audio_buffer.py:27). Rationale: the branch decision needs
fifo_size_at_stop and pcm_fifo_drained_to_empty_events to be mutually consistent, and
the T2-B end snapshot must include the draining pull's (I2)/(I3) counters; under the
lock, observing drained_events > baseline guarantees that pull's partial counters are
already visible (same critical section). This is not I/O and does not run in the
realtime callback; the stop handler (event-loop thread) may block at most for the
remainder of one pull's critical section. Window-START snapshots keep the GIL-atomic
read rule unchanged.
```

**Music-parallel mode (§0.7.3 item 4).** Certifying long-response runs use the default TTS music-pause policy (no music during the TTS session); with parallel music active, `_pull_mixed` returns non-`None` while music plays and the whole-block term is not evaluable — the run must declare it.

If no session start is observable for the run (client joined mid-stream), the client half of the acceptance is **unavailable** and the relocation claim must be restricted to the bridge side, stated as such.

These are what can falsify `PACER_UNDERRUN_ZERO_FILL`. Do **not** claim static/buzz solved before the human listening gate.

Resampler (`audio_converter.py`):

```
resampler_input_samples
resampler_output_samples
```

AEC (`aec_engine.py:210`):

```
aec_far_dropped
```

Stop / flush (`audio_codec.py:420-426`; the `keep_listening=False` early-return path is `session.py:117-119`, the clearing path is `session.py:134-137`):

```
clear_audio_queue_samples_at_stop
```

Q1 and Q2 capacities are **not** changed in R-1f. Agent B's `_TTS_FIFO_MAX_S 10.0 → 0.20` recommendation remains deferred.

**Required deterministic client tests (rev-7 M2).**

| Test | Scenario | Expected |
|---|---|---|
| **CL-1** | TTS FIFO holds exactly 200 samples; call `PcmFifo.pull(480)` | returned block length = **480**; `pcm_fifo_partial_underfill_events` **+= 1**; `pcm_fifo_partial_zero_pad_samples` **+= 280**; `pcm_fifo_drained_to_empty_events` **+= 1 exactly once** (size_before=200>0, size_after=0; rev-8 attack 14); scoped starvation gate (A.15 row 18) **FAILS** because `tts_playout_partial_zero_pad_samples = 280 ≠ 0` |
| **CL-2** | FIFO empty; call `PcmFifo.pull(480)` | returns `None`; **no counter moves — including no drained edge** (size==0 early return precedes all counting); `whole_block_zero_fill_count` path is the only producer for this case |
| **CL-3** | FIFO holds 200, pull(480) *inside* an active session window; Q1/Q2 drops both 0 | `incoming_queue_dropped_packets = 0`, `pcm_fifo_dropped_samples = 0`, yet `tts_playout_partial_zero_pad_samples = 280` ⇒ row 17 satisfied while row 18 fails ⇒ the drop-only gate is provably insufficient; additionally the window closes via T2: as T2_DRAIN_AFTER_STOP with the end snapshot including the +280 if the stop precedes the drained edge, or as T2_EMPTY_AT_STOP if the stop is processed after that edge (FIFO already empty at stop) |
| **CL-4 (NEW, rev-8)** | partial-with-leftover pull: FIFO holds 700, `pull(480)` | returns 480; size_after = 220 > 0 ⇒ **no drained edge**; `pcm_fifo_partial_*` unchanged; subsequent `pull(480)` consumes 220 + pads 260 ⇒ partial +1/+260 AND drained edge +1 (one edge total across the two pulls) |

### A.13 Bridge → client relocation + starvation gate (directive §20)

The media-clock pacer (absolute deadlines) plus the connection-wide `MIN_SEND_START_INTERVAL_MS = 15.0` guard (A.5) apply across **all** generations, pacer starts, and rebases. Response boundaries can neither inject extra packets (guard) nor burst (clock).

Required bridge fields: `steady_segment_rate_fps_min`/`steady_segment_rate_fps_max`, `steady_segment_mean_inter_send_ms_min`/`steady_segment_mean_inter_send_ms_max`, `steady_pacer_segments_qualifying_total`, `steady_segment_frames_max`, `pacer_min_inter_send_ms_observed`, `pacer_short_interval_count`, `wire_rate_excess_frames_max`, `slow_send_events`, `slow_send_guard_violations`, `active_pacer_tasks_max` (`steady_pacer_rate_fps` / `pacer_mean_inter_send_ms_observed` are compatibility aliases only — PO M2).
Required client gate fields: `incoming_queue_peak`, `incoming_queue_dropped_packets`, `pcm_fifo_peak_samples`, `pcm_fifo_dropped_samples`, `pcm_fifo_partial_underfill_events`; plus the TTS-playout-session-scoped starvation metrics (A.12): `tts_playout_whole_block_zero_fill_count`, `tts_playout_partial_zero_pad_samples`.

A clean long-response acceptance run requires **all** of:

```
steady_pacer_segments_qualifying_total   >= 1     # no vacuous rate pass (A.5)
steady_segment_rate_fps_min              >= 49.5
steady_segment_rate_fps_max              <= 50.5
steady_segment_mean_inter_send_ms_min    >= 19.80
steady_segment_mean_inter_send_ms_max    <= 20.20
pacer_min_inter_send_ms_observed         >= 14.999
wire_rate_excess_frames_max              <= 1     # media-epoch definition (A.5, PO M1)
active_pacer_tasks_max                   <= 1
slow_send_guard_violations               = 0      # rev-8 slow-send guard (A.5 §2)
incoming_queue_dropped_packets           = 0
pcm_fifo_dropped_samples                 = 0
tts_playout_whole_block_zero_fill_count  = 0
tts_playout_partial_zero_pad_samples     = 0
```

If `steady_pacer_segments_qualifying_total = 0` the run is `PACING_RATE_EVIDENCE = INSUFFICIENT` and `NORMAL_LONG_RESPONSE_ACCEPTANCE = FAIL`; the four extrema rows are then undefined and not evaluated.

**Real acceptance configuration (rev-7 MINOR 6, normative).** A clean long-response acceptance run is executed with: `RTL_DIAG = 1` (bridge instrumentation enabled, `diag.py:32`; the bridge `/health` fields and `/diag` journals are required to evaluate the gates); client gated telemetry = ON (A.12; the client instrumentation is default OFF, so a run used to certify the client gate must state that it was enabled); acoustic capture = ON when the run requires it; and the SAME bridge/client build under test. No acceptance result from a materially different runtime configuration may certify the shipping build. The run record must name the configuration (build ids, `RTL_DIAG`, client-telemetry state, capture state). The rate/interval gate is evaluated on the bridge-side `/health` fields of that configuration, and the no-vacuous clause (A.5) requires at least one qualifying clean steady segment with `steady_segment_frames >= 250` in that run; if none exists the run is `PACING_RATE_EVIDENCE = INSUFFICIENT` and `NORMAL_LONG_RESPONSE_ACCEPTANCE = FAIL`. Consequence: the `tts_playout_*` gate has no meaning on a run with client telemetry OFF.

Scope statement (fixes the rev-3 over-claim): the drop counters (Q1/Q2) can only detect **overrun**; a slow bridge starves the client without any client drop counter moving. The tts-playout-session-scoped zero-fill metrics are what can falsify `PACER_UNDERRUN_ZERO_FILL`. Without an instrumented client run (A.12 default OFF), the client half is unavailable and the relocation claim must be restricted to the bridge side, stated as such. Do **not** claim static/buzz solved before the human listening gate.

Declared scope: a connection close / abort that lands inside a transport call yields `send_outcome_unknown_frames` and an INVALID run per A.4.C. Runs that intentionally exercise close-during-send are labelled with that path and excluded from the normal-completion PASS set; every other run must show `send_outcome_unknown_frames = 0`.

### A.14 Counter contract (`/health`)

**CUMULATIVE COUNTERS**

```
source_pcm_bytes
admitted_pcm_bytes
guard_dropped_pcm_bytes
safety_truncated_pcm_bytes
orphan_pcm_bytes
idless_delta_mapped_bytes               # directive §14 (mapped into the single live non-terminal response)
bad_base64_live_events                  # run-invalidating (directive §14)
bad_base64_stale_or_unmapped_events     # diagnostic only
post_terminal_delta_events              # carried B2: late deltas classified STALE after local terminality
qwen_dispatch_errors_total              # directive §15; run-invalidating
qwen_dispatch_errors_by_type
accounting_fault_events                 # invariant-violation tripwire (rev-8 m9): includes the
                                        # UNREACHABLE-BY-CONSTRUCTION R2-after-R1 observation (A.2)

encoded_full_frames
encode_failed_frames
synthetic_tail_frames
synthetic_tail_source_bytes
synthetic_tail_zero_pad_bytes
synthetic_tail_encode_failures
synthetic_tail_encode_failed_source_bytes
synthetic_tail_encode_failed_zero_pad_bytes

residue_discarded_pcm_bytes
residue_discarded_bargein_bytes
residue_discarded_abort_bytes
residue_discarded_close_bytes
residue_discarded_listen_start_bytes
residue_discarded_upstream_closed_bytes
residue_discarded_pacer_stall_bytes
residue_discarded_byte_cap_failure_bytes
residue_discarded_send_error_bytes
residue_discarded_store_cap_bytes

sent_confirmed_frames
flushed_bargein_frames
flushed_abort_frames
flushed_close_frames
flushed_listen_start_frames
flushed_upstream_closed_frames
flushed_pacer_stall_frames
flushed_byte_cap_failure_frames
flushed_send_error_frames
send_failed_frames
send_outcome_unknown_frames
post_terminal_sends_total               # terminal invariant (rev-8 B2): += 1 iff send_bytes entered while
                                        # the owning generation is SEND_FORBIDDEN (NOT SEALED_DRAINING); expected 0

pacer_starts
pacer_rebases                           # A.6 Case-A lateness rebases AND §2 slow-send rebases
pacer_fatal_stalls                      # A.6 Case-B lateness stalls AND §2 T>250 stalls
pacer_short_interval_count
pacer_floor_bind_count
slow_send_events                        # §2: count of slow SUCCESSES (5 < T <= 250)
slow_send_guard_violations              # rev-8: a next audio send start earlier than
                                        # slow_guard_deadline - SPACING_EPSILON_MS (A.5 §2); expected 0
audio_rebase_discarded_frames

legacy_drop_oldest_calls                # regression only (A.3 "Regression counter.") — NOT proof against a second store
barge_in_sequence_incomplete            # derived (A.10)
barge_in_sequences_total
barge_in_invalidate_failures
barge_in_pacer_cancel_failures
barge_in_store_flush_failures
barge_in_tts_stop_failures
cancel_attempts
cancel_send_errors
byte_cap_failures
cap_transitions_total

qwen_audio_delta_bytes                  # LEGACY / NOT USED FOR CLOSURE (directive §24)
audio_out_dropped                       # DEPRECATED: no R-1f mutation site (A.3 "audio_out_dropped mutation check"); read-only in /health
```

**STATES (not counters)**

```
previous_audio_send_start_at            # None until the first audio send (directive §22)
send_guard_until                        # None; armed on slow success (= completion+15) and on failed/unknown (= observation_time+15) (§2)
tts_owner_generation_id                 # set at TTS-start emission; null after the stop emission (directive §16)
media_epoch / epoch_ordinal / sent_in_epoch  # media-clock epoch state (A.5, rev-8 PO M1); journaled to
                                        # /diag at epoch creation and at each send start; not a /health counter
```

**GAUGES** (sampled atomically at generation quiescence — quiescence definition in A.4.C)

```
audio_store_current_frames
audio_store_current_bytes
unsent_backlog_current_frames           # canonical = queued + in_flight (A.2)
in_flight_frames
still_stored_frames
still_buffered_pcm_bytes
active_pacer_tasks                      # live pacer tasks owned by the connection; sampled at /health read and at ownership change
```

**MAX / MIN OBSERVATIONS** (aggregation rules are normative)

```
audio_store_peak_frames                 # store gauge only; <= unsent_backlog_peak_frames
unsent_backlog_peak_frames              # canonical cap observable (A.2)
audio_store_peak_bytes
pacer_lead_frames_max                   # structurally 0 under this design (reported tripwire)
pacer_min_inter_send_ms_observed        # connection-wide; measured on send_start_at
pacer_mean_inter_send_ms_observed       # ALIAS (PO M2): per-segment diagnostic field / compat alias of
                                        # segment_mean_inter_send_ms; NOT a sole acceptance observable
steady_pacer_rate_fps                   # ALIAS (PO M2): per-segment diagnostic field / compat alias of
                                        # segment_rate_fps; NOT a sole acceptance observable
steady_segment_rate_fps_min             # min segment_rate_fps over qualifying clean steady segments
steady_segment_rate_fps_max             # max segment_rate_fps over qualifying clean steady segments
steady_segment_mean_inter_send_ms_min   # min over qualifying segments; gate >= 19.80
steady_segment_mean_inter_send_ms_max   # max over qualifying segments; gate <= 20.20
pacer_wake_overshoot_mean_ms_observed   # DIAGNOSTIC ONLY: max over runs (frames>=1000) of mean delta, exclusion of rebase spans; no acceptance precondition (A.5)
active_pacer_tasks_max                  # max over the run of active_pacer_tasks; gate <= 1
steady_segment_frames_max               # max steady_segment_frames over QUALIFYING segments (rev-8 reconciliation)
steady_pacer_segments_qualifying_total  # count of qualifying segments (frames >= 250, clean) (no-vacuous clause)
# Raw per-segment records (segment_id, first/last send start, frames, segment_rate_fps,
# segment_mean_inter_send_ms, epoch_ordinal, qualifying) are normative /diag output (A.5).
pacer_rebase_max_lateness_ms
wire_rate_excess_frames_max
cancel_max_per_generation               # max over generations of that generation's cancel_attempts
cap_transitions_max_per_generation      # max over generations
end_markers_max_per_generation          # max over generations
tts_stop_emissions_max_per_generation   # max over generations; counts emissions (A.9)
```

Every required assertion names the exact observable field that makes it evaluable (A.15). No assertion compares a constant to itself. **No assertion depends on journal text** — in particular the former row-11 "wire/send-timeline check" is replaced by the observable `post_terminal_sends_total = 0`. `catch_up_frames_over_50fps` does not exist.

**CLIENT-SIDE TELEMETRY CONTRACT (client-gated; co-captured with the bridge `/health` snapshot of the same run).**

These fields are not carried in the bridge `/health` payload. They are the client-side telemetry that the R-1f acceptance capture must record from the same run as the bridge `/health` snapshot. Definitions live in A.12; the names are normative.

```
incoming_queue_current / _peak / _dropped_packets
pcm_fifo_current_samples / _peak_samples / _dropped_samples
pcm_fifo_partial_underfill_events
pcm_fifo_partial_zero_pad_samples
pcm_fifo_drained_to_empty_events          # NEW rev-8 (m7); per FIFO instance
pcm_fifo_instance_id                      # NEW rev-8 (m6); identity of the FIFO instance the counters belong to
playout_window.start_fifo_instance_id     # NEW rev-8 window metadata
playout_window.end_fifo_instance_id       # NEW rev-8 window metadata
playout_window.terminal_event             # NEW rev-9 (M-1): T1 | T2_EMPTY_AT_STOP | T2_DRAIN_AFTER_STOP | T3 | T4
t2_stop_fifo_instance_id                  # NEW rev-9 (M-1): FIFO instance id captured by the T2 stop snapshot
t2_stop_fifo_size_at_stop                 # NEW rev-9 (M-1): fifo_size_at_stop (branch discriminator; recorded evidence)
t2_stop_drained_edge_baseline             # NEW rev-9 (M-1): pcm_fifo_drained_to_empty_events at stop (T2-B only; None for T2-A)
whole_block_zero_fill_count
tts_playout_whole_block_zero_fill_count
tts_playout_partial_zero_pad_samples
clear_audio_queue_samples_at_stop
decode_errors / toc_null_count / decoded_short_frame_count
```

**Telemetry architecture (rev-8, explicit PO clarification of the earlier shorthand "Part A /health contract"):** BRIDGE `/health` carries bridge counters/gauges only; CLIENT acceptance telemetry is the client FIFO/drop/zero-fill counters above. The client fields `pcm_fifo_partial_underfill_events` / `pcm_fifo_partial_zero_pad_samples` are part of the **R-1f ACCEPTANCE TELEMETRY CONTRACT**, not literal fields inside the bridge's HTTP `/health` payload.

Client clean-long-response acceptance requires: `incoming_queue_dropped_packets = 0`; `pcm_fifo_dropped_samples = 0`; `tts_playout_whole_block_zero_fill_count = 0`; `tts_playout_partial_zero_pad_samples = 0`.

### A.15 Assertion table

| # | Acceptance assertion | Observable field(s) | Spec |
|---|---|---|---|
| 1 | Pacer spacing (anti-burst; directive §25.B) | `pacer_short_interval_count = 0`; `pacer_min_inter_send_ms_observed >= 14.999` (`MIN_SEND_START_INTERVAL_MS = 15.0`, `SPACING_EPSILON_MS = 0.001`; on `send_start_at`) | A.5 |
| 2 | Positive rate, per-segment extrema + no vacuous pass (directive §25.A; rev-8 PO M2) | `steady_pacer_segments_qualifying_total >= 1`; `steady_segment_rate_fps_min >= 49.5` AND `steady_segment_rate_fps_max <= 50.5`; `steady_segment_mean_inter_send_ms_min >= 19.80` AND `steady_segment_mean_inter_send_ms_max <= 20.20` (extrema over qualifying clean steady segments: >= 250 confirmed frames, one epoch, no rebase/stall/failure/unknown); a 47.4 fps pacer fails; if `steady_pacer_segments_qualifying_total = 0` then `PACING_RATE_EVIDENCE = INSUFFICIENT` and `NORMAL_LONG_RESPONSE_ACCEPTANCE = FAIL` (never a vacuous PASS; extrema then undefined and not compared); `pacer_floor_bind_count`, `slow_send_events`, `steady_segment_frames_max` reported; raw per-segment records in /diag | A.5 |
| 3 | Wire-rate excess (fast side; media-epoch definition, rev-8 PO M1) | `wire_rate_excess_frames_max <= 1` (max over media-clock epochs of `sent_in_epoch − permitted`; epoch = pacer start / A.6 Case-A rebase / §2 slow-send rebase / pacer restart; theorem `wire_excess <= 0`, to be proven by Agent F from the A.5 definition); cross-epoch bursts caught by row 1 | A.5 |
| 4 | Store occupancy cap (directive §25.C) | `unsent_backlog_peak_frames <= 1500` (canonical; `audio_store_peak_frames` reported) | A.2 |
| 5 | Cap fires exactly once per generation (delta-triggered AND seal-time) | `cap_transitions_max_per_generation <= 1`; test B (delta-triggered) checks; **test B′ (full-backlog normal seal)** checks: `unsent_backlog_peak_frames <= 1500`, `residue_discarded_store_cap_bytes` increases by exactly N once, `synthetic_tail_frames`/`synthetic_tail_source_bytes` unchanged, source/framer/disposition residuals 0 | A.2 |
| 6 | Source byte closure (directive §25 — §9/§14) | `source_pcm_bytes = admitted + guard_dropped + safety_truncated` (residual 0); `orphan_pcm_bytes = 0`; `bad_base64_live_events = 0`; `idless_delta_mapped_bytes`, `bad_base64_stale_or_unmapped_events`, `post_terminal_delta_events` reported | A.4.A |
| 7 | Framer byte closure (directive §9/§10) | residual of `admitted_pcm_bytes = 960*encoded_full_frames + 960*encode_failed_frames + synthetic_tail_source_bytes + synthetic_tail_encode_failed_source_bytes + residue_discarded_pcm_bytes + still_buffered_pcm_bytes` is 0. `still_buffered_pcm_bytes` is a closure **TERM** (a field of the RHS); at generation quiescence `still_buffered_pcm_bytes = 0`. `still_buffered_pcm_bytes` is **not** itself "the closure residual" | A.4.B |
| 8 | Encoded frame disposition closure (directive §12) | `encoded_full_frames + synthetic_tail_frames` = `sent_confirmed_frames` + the eight `flushed_*_frames` buckets + `send_failed_frames` + `send_outcome_unknown_frames` + `still_stored_frames` + `in_flight_frames` (residual 0; gauges 0 at quiescence) | A.4.C |
| 9 | Zero-loss run validity | `send_outcome_unknown_frames = 0` (else **INVALID**); `send_failed_frames` = real transport loss | A.4.C |
| 10 | Rebase safety (both mechanisms) | `pacer_rebase_max_lateness_ms <= 250`; `audio_rebase_discarded_frames = 0`; `pacer_rebases` counts BOTH A.6 Case-A lateness rebases and §2 slow-send rebases; `pacer_rebases`, `pacer_starts` reported | A.6, A.5 |
| 11 | Bounded stall + no undead playback (carried B2; rev-6 m2; rev-8 B2 semantics) | 10 s-stall test: `pacer_fatal_stalls` bounded; `in_flight_frames == 0`; closures residual 0; `end_markers_max_per_generation == 1`; `tts_stop_emissions_max_per_generation == 1`; **`post_terminal_sends_total = 0` (post-terminal = SEND_FORBIDDEN at send-entry, NOT SEALED_DRAINING — rev-8 B2)**; `post_terminal_delta_events` reported | A.6, A.9, A.4.A, A.4.C |
| 12 | Single encoded store / legacy queue removed (directive §18; rev-7 §M3; rev-8 B1/M3/m10) | separate NON-ACCEPTANCE sentinel harness (`RTL_DIAG` unset; m10): `future_audio_store` is `collections.deque` (direct representation, exactly one holder — `hits == {id(future_audio_store)}` under the PO walk with seeds `list(vars(conn).values())`, exempt roots {ws, diag, config, uplink_q, dl_buf} pruned by identity, descent-pruned for class/function/module/code objects); sentinel `len==1`, identity-equal at `store[0]`; hold point = pacer-startup control (`_ensure_pacer` no-op), `pacer_task is None`; no dependence on asyncio.Queue semantics or `gc.get_referents(dict)` behaviour; mechanical AST scan over all `rtl-lab/app/**/*.py` after docstring stripping: no `Name.id`/`Attribute.attr`/`keyword.arg`/`Constant(str)` occurrence of the 9-token legacy set {dl_q, SENTINEL, _stop_pending, _enqueue_frame, _enqueue_sentinel, _drop_one_non_sentinel, _put_drop_oldest, DL_QUEUE_MAX, qwen_closed} (exact equality; catches `getattr(config, "DL_QUEUE_MAX", 256)`); plain-text `DL_QUEUE_MAX` absent from `config/config.json`; no `audio_out_dropped` mutation site; `0 <= len(dl_buf) < 960`; `uplink_q` exempt; `legacy_drop_oldest_calls = 0` (regression only). Mandatory attacks 1, 2, 12, 13 | A.3 |
| 13 | Cancel once | `cancel_max_per_generation <= 1` (max over generations); `cancel_send_errors` reported | A.7, A.8 |
| 14 | Barge-in completeness (directive §19) | `barge_in_sequence_incomplete = 0` derived from `barge_in_{invalidate,pacer_cancel,store_flush,tts_stop}_failures`; mask `0b1111`; reported against `barge_in_sequences_total` | A.10 |
| 15 | Generation end (directive §16) | `end_markers_max_per_generation <= 1`; `tts_stop_emissions_max_per_generation <= 1` (both MAX over generations; stops count emissions) | A.9 |
| 16 | Byte ceiling is a live emergency guard (directive §13) | acceptance: `byte_cap_failures = 0`; branch exercise (test C, oversized mock fixture) fires `AUDIO_STORE_BYTE_CAP_REACHED` before the frame cap; run = `RESOURCE_SAFETY_FAILURE` | A.11 |
| 17 | Client relocation, drop side (directive §25.D) | `incoming_queue_dropped_packets = 0`; `pcm_fifo_dropped_samples = 0`; `incoming_queue_peak`, `pcm_fifo_peak_samples` reported | A.13 |
| 18 | Client starvation (directive §25.E; rev-7 M2; rev-8 m7; rev-9 M-1) | `tts_playout_whole_block_zero_fill_count = 0`; `tts_playout_partial_zero_pad_samples = 0`; source of the second term = window delta of `pcm_fifo_partial_zero_pad_samples`, counted inside `PcmFifo.pull` (`audio_buffer.py:54-74`); **T2 window end is the rev-9 two-branch rule**: at the tts-stop processing point (`session.py:117-119`, keep_listening=False) a lock-held stop snapshot is taken; `fifo_size_at_stop == 0` ⇒ window closes immediately, label `T2_EMPTY_AT_STOP`, no later edge required; `fifo_size_at_stop > 0` ⇒ window stays open until the FIRST edge with same `pcm_fifo_instance_id` AND `pcm_fifo_drained_to_empty_events > t2_stop_drained_edge_baseline`, label `T2_DRAIN_AFTER_STOP`, end snapshot taken after that pull's partial counters ((I3)-after-(I2) ordering); a drain edge belonging to a later TTS session MUST NOT close the window; tests CL-1 and CL-4 are mandatory; a valid window requires `start_fifo_instance_id == end_fifo_instance_id == t2_stop_fifo_instance_id`, else `CLIENT_TELEMETRY_INVALID = 1`; `AudioCodec.__del__` during an active window ⇒ `CLIENT_TELEMETRY_INVALID = 1` (rev-9 mi-5) | A.12, A.13 |
| 19 | Local dispatch integrity (directive §25.F) | `qwen_dispatch_errors_total = 0` | A.4 |
| 20 | Synthetic tail (directive §25.G) | `synthetic_tail_encode_failures = 0` | A.4.B |
| 21 | Per-generation maxima (directive §25.H) | `cap_transitions_max_per_generation <= 1`; `cancel_max_per_generation <= 1`; `end_markers_max_per_generation <= 1`; `tts_stop_emissions_max_per_generation <= 1` | A.2, A.8, A.9 |
| 22 | Normal-completion PASS set | `encode_failed_frames = 0`, `send_failed_frames = 0`, `send_outcome_unknown_frames = 0`, `guard_dropped_pcm_bytes = 0`, `safety_truncated_pcm_bytes = 0`, `synthetic_tail_encode_failures = 0`, `qwen_dispatch_errors_total = 0`, `accounting_fault_events = 0`, `residue_discarded_store_cap_bytes = 0` (a fired STORE_CAP transition R1/R2 is a labelled CONTROLLED_TAIL_TRUNCATION run — §0.7.3) | A.4, A.2 |

`barge_in_sequence_incomplete = 0` (directive §25.I) is row 14. `catch_up_frames_over_50fps` does not exist (directive §25 — deleted).

`post_terminal_sends_total = 0` is the **terminal invariant** (A.4.C); it is not confined to the stall path.

Additional rows (appended to the table above):

| # | Acceptance assertion | Observable field(s) | Spec |
|---|---|---|---|
| 23 | Single pacer task (rev-7 MINOR 5) | `active_pacer_tasks_max <= 1` | A.5 |
| 24 | Slow-send boundedness + guard observable (rev-7 PO M1; rev-8 slow-guard) | `slow_send_events` reported; every slow success (5 < T <= 250) armed `slow_guard_deadline = send_completion_time + 15` (state field: `send_guard_until`) and rebased `next_deadline = completion + 20` (no interval below 14.999 ms after a slow send); **`slow_send_guard_violations = 0`** (a next audio send start earlier than `slow_guard_deadline - SPACING_EPSILON_MS` increments it); every T > 250 ms success drove exactly one `PACER_FATAL_STALL` (no silent rebase); `pacer_fatal_stalls`, `pacer_rebases` reported | A.5, A.6 |
| 25 | Byte-cap in-flight head, BOTH mandatory cases (rev-8 B3) | **Case C-A** (head `RESERVED_WAIT`, forced by holding the pacer in its pre-send wait): `flushed_byte_cap_failure_frames = 1 (head) + queued + 1 (trigger packet)` exactly once; `send_outcome_unknown_frames = 0`; all A.4.B/A.4.C closures residual 0; run `RESOURCE_SAFETY_FAILURE`. **Case C-B** (head `SEND_AWAIT`, forced by stalling the transport inside `send_bytes`): `send_outcome_unknown_frames = 1`; run additionally **INVALID**; `flushed_byte_cap_failure_frames = queued + 1 (trigger packet)`; closures residual 0. **Case C-C** (no in-flight head, pacer idle): `flushed_byte_cap_failure_frames = queued + 1 (trigger packet)`; closures residual 0. All cases: `byte_cap_failures = 1`; `residue_discarded_byte_cap_failure_bytes = len(dl_buf)`; exactly one TTS stop; `queued_audio_frames = in_flight_frames = still_stored_frames = still_buffered_pcm_bytes = 0` at quiescence | A.11, A.4.C |
| 26 | FIFO instance integrity (rev-8 m6; rev-9 M-1/mi-5) | every recorded playout window has `start_fifo_instance_id == end_fifo_instance_id` (== `t2_stop_fifo_instance_id` on T2-terminal windows); any FIFO instance change during an active window is covered by a properly recorded T3 terminal event (snapshot-old → end-window → rebuild); a change without one ⇒ `CLIENT_TELEMETRY_INVALID = 1`, run client half INVALID — this includes an instance change while a T2-B window is pending: cross-instance drain edges are rejected as closure candidates; `AudioCodec.__del__` is NOT a T1–T4 terminal: `__del__` while a window is active ⇒ `CLIENT_TELEMETRY_INVALID = 1` and client half INVALID; `__del__` after the window closed has no effect on the completed window; attacks 8, 9, 10, 11 mandatory | A.12 |

### A.16 Evidence base and measurement notes

| Item | Value | Source |
|---|---|---|
| Pacer median inter-send gap | 21.0939 / 21.1627 / 21.3062 ms | `r1e_mock` / `r1d_real` / `r1e_real` sent-Opus journals |
| Pacer implied rate | 47.41 / 47.25 / 46.93 fps | derived |
| Measured deficit vs 50 fps | 2.6 / 2.8 / 3.1 frames/s | derived |
| Send duration `T = t_send − t_intent` p50 / p95 / max | 0.060 / 0.095 / 0.124 ms (mock); 0.0645 / 0.136 / 0.198 (r1d); 0.0835 / 0.178 / 0.214 (r1e). p95 convention is stated once and used consistently: **lower-rank** `int(0.95(n−1))` (r1d slice 0.116/0.132/0.136/0.145/0.158 ⇒ lower-rank 0.136; linear interpolation 0.141; nearest-rank 0.145) | `send_intents` in the three diag bundles |
| Wake overshoot `δ` definition | NORMATIVE estimator (rev-8 m2; used consistently in A.1/A.5/A.16): steady gaps := consecutive `t_send` pairs with the same `pacer_task_id` and `gap < 200 ms`; `δ = gap − 20 − T(later frame)` where that frame's `t_intent` exists (matched by `(resp_id, frame_seq, pacer_task_id)`), else `gap − 20 − mean(T)` over that bundle's intents. rev-9 (PO mi-2): the canonical values below are NORMATIVE; independent recomputation from the raw journals reproduces them to ≤ 0.004 ms when the fallback run-mean T is expressed in ms (well inside the ≤ 0.03 ms reproducibility bound) | derived |
| Wake overshoot `δ` (DIAGNOSTIC ONLY): median | = **1.0270 / 1.0845 / 1.2100 ms** (r1e_mock / r1d_real / r1e_real; rev-9 canonical, PO mi-2) | derived |
| Wake overshoot `δ` (DIAGNOSTIC ONLY): mean | = **1.3858 / 3.3237 / 2.4710 ms** (per-pair estimator; rev-9 canonical, PO mi-2 — supersedes the approximate r1d 3.298 figure) | derived |
| `δ > 2 ms` fraction of steady gaps (DIAGNOSTIC ONLY) | = **7.5 / 22.4 / 14.9 %** (rev-9 canonical, PO mi-2; the qualitative claim — all means far below PACING_SLACK_MS = 5.0 — is the load-bearing part and is unchanged) | derived |
| Simulated pacer mean rate — slack 2 ms (`MIN_SEND_START_INTERVAL_MS = 18.0`) — **HISTORICAL** (superseded rev-6 design point; retained as evidence that the 18 ms floor fails the gate) | 20.0000 / 21.4830 / 20.4587 ms ⟹ 50.00 / 46.55 / 48.88 fps on the raw resampled envelopes ⇒ the 18 ms slack is not viable (A.1/A.5) | resampling simulation (lead audit, M-A-ext) |
| Simulated pacer mean rate — slack 5 ms (`MIN_SEND_START_INTERVAL_MS = 15.0`) — **R-1f rev-7/8/9 DESIGN POINT** (PO B2) | 20.0000 / 20.0023 / 20.0003 ms ⟹ 50.00 / **49.99** / 50.00 fps on the resampled envelopes (20.0023 ms ⟹ 49.994 fps; PO mi-1 correction of the rev-8 49.97 transcription slip) — PO / rev-7 reviewer resampling figures (lead audit M-A-ext; Agent F M5 re-simulation) | resampling simulation (lead audit, M-A-ext) + Agent F M5 + rev-7 Agent A recompute |
| Real Opus packet mean size | 55.9 B (r1d), 58.8 B (r1e); 61.5 B (mock) | journals |
| Real Opus packet p50 / p95 / max | 60–61 B / **72 B (r1d_real) and 73 B (r1e_real), lower-rank p95 `int(0.95(n−1))` stated per bundle** / 79–108 B (real); max 87 B (mock) | journals |
| Bridge→client **Opus media rate** (mean packet ÷ 20 ms) | 2.79–3.07 kB/s ≈ 22.4–24.6 kbit/s | derived (configured bitrate 24 kbit/s) |
| Byte ceiling (directive §13, 512 KiB) | 524288 / 1500 ≈ 349.5 B/frame vs observed max 108 B ⇒ 3.24× margin; a 1275 B/frame stream fires it at ≈ frame 412, before the 1500-frame cap | derived |
| Legacy bridge store in force | 256 frames = 5.12 s, silent drop-oldest | `config/config.json:6`, `turns.py:508-559` |
| Client Q1 | 64 packets = 1.28 s; over-cap policy drops **one** oldest packet silently (`protocol_manager.py:170-176`); only if the queue is still full does it log a warning and discard the incoming frame (`protocol_manager.py:177-178`) | `protocol_manager.py:24,42-44,162-178` |
| Client Q2 | 240000 samples = 10.0 s @ 24 kHz; `push()` over-cap drop-oldest is silent (no log in `audio_buffer.py:43-52`); each FIFO carries a `pcm_fifo_instance_id` assigned at construction (rev-8 m6); rebuild at `audio_codec.py:263-265` replaces the instance | `audio_codec.py:26,68-70`; `audio_buffer.py:22-83` |
| Client drain clock | exactly 50 chunks/s (`_mix_chunk = 480 samples @ 24 kHz`) | `audio_codec.py:74`, `stream_manager.py:64-72`, `audio_device.py:125-127`, `constants.py:93-94` |
| Client absorptive capacity | 564 frames ≈ 11.28 s | derived |
| Raw r1d evidence length (rev-8 m4) | **70 frames / 67 steady gaps across 3 short responses — too short to itself satisfy the >= 250-frame qualification**; claims about >= 250-frame r1d segments come only from documented resampling/repetition experiments; a run on the raw r1d evidence alone is `INSUFFICIENT` by the no-vacuous clause | journals |

Note on the media-rate row: this is the bridge→client Opus *media* rate (mean packet size ÷ 20 ms), not a wall-clock journal span rate, and not the raw Qwen PCM24 downlink rate (48 kB/s).

---

## Part B — Agent F re-review (rev 9)

**Previous rounds (recorded).** Rev 4: 1/7/9 `REVISE` (audited; §0.4). Rev 5: 2/2/11 `REVISE` (audited; §0.5). Rev 6: 2/3/10 `REVISE` (audited; §0.7.2). Rev 7: 3/3/10 `REVISE` (audited; §0.8.2; ACCEPTED). Rev 8: 1/1/5 `REVISE` (audited; report `rtl-lab/r1f-agent-f-review-rev8.md`; closure map §0.9) — **ACCEPTED by the product owner**, whose rev-9 correction mandates the final local fixes; the rev-8 architecture survived independent attack (the wire-rate theorem was proven ≤ 0 from the epoch definition, the sentinel harness and AST rule held, and 18/19 mandated attacks passed).

**Round rev 9 (COMPLETE — reviewed and audited; DESIGN REVIEW = PASS).** Fresh, independent Agent F report: `rtl-lab/r1f-agent-f-review-rev9.md` (no errata). **Lead audit: every finding independently re-checked and confirmed** — all 5 minors are documentation-precision items; none affects a gate, a closure, or an attack outcome. Agent B's independent accounting regression pass returned REGRESSION_PASS (7/7 items); its one minor doc defect (dangling A.14 citations orphaned by the mi-4 edit) was fixed by the lead before the Agent F review.

Confirmed outcomes:

- **Conformance:** §0.9.1 audited row-by-row — B-1/M-1/mi-1..mi-5 all CONFORMS (the mi-3 removal-list edit verified source-exact; mi-2's canonical δ values reproduced within tolerance; the direct-representation and lock-held T2 snapshot decisions proven necessary). §0.9.2 items 1–6 all traceable into Part A; nothing silent.
- **21/21 mandated attacks executed — all PASS.** Highlights: the multi-response scenario (response-1 drain → exit → response-2 start) now correctly fires E4 with `epoch_ordinal` increment and `sent_in_epoch` reset — the rev-8 false-FAIL (≈500) is eliminated; cancel/stall recreations are E4; **the wire_excess ≤ 0 theorem re-proven in full for E1/E2/E3/corrected-E4** (base cases per event type; induction unchanged; tight — excess 0 attained); T2_EMPTY_AT_STOP and T2_DRAIN_AFTER_STOP both close correctly with the (I2)→(I3) ordering guarantee; cross-session/instance-change/`__del__` cases all fail-safe; 20.0023 ms ⇒ 49.994/49.99; the pinned δ estimator reproduces to ≤ 0.0032 ms; the corrected dl_q inventory is AST-source-exact; byte-cap C-A/C-B/C-C closure residuals algebraically re-derived as 0; no-change confirmed at filesystem + content level (attestation-only: docker, out-of-allowlist stacks).
- **MINORS (5, documentation-precision only):** m-1 A.12 T3 wording vs row 26 tension (one sentence); m-2 A.2 orphaned "3./4./5." list continuation (the mi-4 audit's one miss); m-3 Opus p95 per-bundle precision (72/73 B); m-4 §0.9.2 item 5 should state the fail-safe direction of the edge/start race explicitly; m-5 the `audio_out_dropped` AST rule needs an explicit exemption for the counters.py:26 definition Assign.
- **Agent F's transparency note:** the A.16 resampling rows are structurally unverifiable from the allowlisted artefacts (simulation code not persisted) — classified attestation-only/PO-quoted, not gate-load-bearing (the gate is measured per-segment extrema at implementation time).

```
DESIGN_REVIEW_BLOCKERS = 0
DESIGN_REVIEW_MAJORS   = 0
DESIGN_REVIEW_MINORS   = 5
DESIGN_REVIEW          = PASS
```

**Status: STOPPED after review, exactly as directed by the PO review gate (STOP even at BLOCKERS = 0).** No implementation has been performed at any point in the R-1f design-review programme. `DESIGN_REVIEW = PASS` means the design is approved for implementation — which still requires a separate explicit product-owner authorisation. The 5 minors are one-sentence documentation-precision fixes, queued for the implementation round's doc pass (they gate nothing).
