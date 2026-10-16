# R-1f Agent F re-review (rev 4)

Fresh, independent, adversarial. Reviewed artifact: `rtl-lab/r1f-design-review.md` (Part 0 + Part A rev 4).
Evidence: read-only sources (`rtl-lab/app/*.py`, `rtl-lab/config/config.json`, `py-xiaozhi/src/**`) and the raw
journals/diag bundles under `rtl-lab/evidence/`. No earlier *rev-4* review exists; `r1f-agent-f-review-rev3.md`
was read only to recover the F-1..F-4 / M-1..M-8 / m-1..m-10 statements for the closure audit.
Not read: `r1f-agent-f-review.md` (rev-2).

Nothing was written except this report. No code/config/container was touched. All numeric recomputation was done
with heredoc Python against the raw evidence (statistics re-derived independently, not copied from A.16).

ASCII-safe punctuation is used in code/paths/identifiers throughout.

---

## 1. Recomputed numbers (independent, from raw evidence)

Percentiles: linear interpolation on the sorted sample unless noted. Times: `t_send`/`t_intent` are Unix-monotonic
seconds in the journals and diag bundles.

### (a) `T = t_send - t_intent` (send duration), from `send_intents` in the three diag bundles

| bundle | n | p50 (ms) | p95 (ms) | p95 nearest-rank (ms) | max (ms) | mean (ms) |
|---|---|---|---|---|---|---|
| `r1e_mock_diag.json` | 200 | 0.0600 | 0.0951 | 0.0950 | 0.1240 | 0.0636 |
| `r1d_real_diag.json` | 70 | 0.0645 | **0.1410** | 0.1395 | 0.1980 | 0.0768 |
| `r1e_real_diag.json` | 200 | 0.0835 | 0.1783 | 0.1780 | 0.2140 | 0.0923 |

A.16 prints `0.0645 / 0.136 / 0.198` for r1d; `0.136` is the *lower* convention at index `int(0.95*69)=65`
(the sorted tail is `..., 0.132, 0.136, 0.145, ...`). Linear interpolation gives 0.1410. Delta is 5 us; see MINOR m-a.

### (b) Same-`pacer_task_id` consecutive `t_send` gaps (journals) and implied rate

| journal | rows | pacers | gaps n | p50 (ms) | p95 (ms) | min (ms) | max (ms) | implied fps (1000/p50) |
|---|---|---|---|---|---|---|---|---|
| `r1e_mock_sent_opus.jsonl` | 363 | 1 | 362 | 21.0939 | 22.3177 | 20.3929 | 83.0900 | **47.41** |
| `r1d_real_sent_opus.jsonl` | 70 | 3 | 67 | 21.1627 | 36.6202 | 20.3417 | 47.9337 | **47.25** |
| `r1e_real_sent_opus.jsonl` | 479 | 2 | 477 | 21.3062 | 32.1029 | 20.3604 | 80.4597 | **46.93** |

A.16's 21.0939 / 21.1627 / 21.3062 and 47.41 / 47.25 / 46.93 reproduce exactly.

### (c) Opus packet size (journals)

| journal | mean (B) | p50 (B) | p95 (B) | max (B) | min (B) |
|---|---|---|---|---|---|
| mock | 61.47 | 62 | 67 | 87 | 49 |
| r1d | 55.87 | 60 | 72.5 | 79 | 21 |
| r1e | 58.76 | 61 | 73 | **108** | 3 |

A.16's `55.9 / 58.8 / 61.5 B` means, `60-61 / 73 / 79-108` p50/p95/max and `max 87` (mock) all reproduce.

### (d) Wake overshoot `delta = gap - 20 - T` (median), and its full distribution

Median (using the bundle's own T p50): **1.034 / 1.098 / 1.223 ms** (mock / r1d / r1e) - matches A.16's
`1.03 / 1.10 / 1.22`. Independently, using `delta_i = gap_i - 20` (T <= 0.214 ms, negligible):

| journal | delta p50 | delta p90 | delta p95 | delta max | **fraction of intervals with delta > 2 ms** |
|---|---|---|---|---|---|
| mock | 1.094 | 1.815 | 2.318 | 63.090 | **8.0 %** |
| r1d | 1.163 | 9.437 | 16.620 | 27.934 | **23.9 %** |
| r1e | 1.306 | 2.509 | 12.103 | 60.460 | **16.1 %** |

This last column is material: A.5 asserts the 2 ms slack means "the floor never binds" in normal operation. It
binds on 8-24 % of frames in the measured evidence (see MAJOR M-A).

### Simulation of the A.5 pseudocode (deadline clock + 18 ms floor charged from the attempt start)

3000 frames, `T ~ U(0,0.14) ms`, jitter models over `delta`; excess uses the A.5 formula
`permitted(t) = 1 + floor((t - anchor_t)/20)` (same-run anchor), catch-up uses the half-open `(t-1 s, t]` window:

| jitter model | mean interval (ms) | fps | min gap (ms) | floor binds (frames) | `wire_rate_excess_frames_max` | `catch_up_frames_over_50fps` |
|---|---|---|---|---|---|---|
| `delta ~ N(1.0, 0.4)` | **20.0000** | 50.00 | 18.19 | 19 | 1 | 0 |
| `delta ~ N(1.1, 0.3)` | **19.9999** | 50.00 | 18.58 | 6 | 1 | 0 |
| 8 % late wake `U(2,6) ms` | **20.0000** | 50.00 | 18.00 | 690 | 1 | 0 |
| 4 % late wake `U(3,15) ms` | **19.9999** | 50.00 | 18.00 | 929 | 1 | 0 |
| 1 % stall `U(20,60) ms` | 20.2848 | 49.30 | 18.00 | 350 | 1 | 0 |

Single late-wake spike, then the gaps that follow (frame 30 spiked, frames around it shown):

| spike | `floor_binds` | gaps after the spike (ms) | max excess over the run | catch-up |
|---|---|---|---|---|
| 2.5 ms | 1 | 21.37, 19.16, 19.73, 19.87, 19.86, 19.79 | 1 | 0 |
| 5 ms | 4 | 23.87, 19.16, 19.39, 19.26, 19.13, 18.97, 19.93 | 1 | 0 |
| 10 ms | 10 | 28.87, 19.16, 19.39, 19.26, 19.13, 18.92, 18.85, 19.16, 19.43, 19.11 | 1 | 0 |
| 35 ms | 37 | 53.87, then ~19.1 ms for ~20 frames | 1 | 0 |

Result: the deadline clock pins the mean at **20.0000 ms (50.00 fps)** and the guard never injects excess beyond the
`<= 1` tolerance, so F-1 is closed functionally - but the *mechanism description* in A.5 ("it delays one interval ...
the deadline clock re-asserts on the following frame") is false: the floor paces for ~L/2 frames at 18.9-19.4 ms
(MAJOR M-A).

### Gate discrimination (does anything actually detect 47.4 fps?)

| pacer | mean interval | `pacer_mean_inter_send_ms_observed` vs 20.5 (row 7b) | spacing row 7 | `wire_rate_excess_frames_max` vs 1 (row 8) | `catch_up_frames_over_50fps` vs 0 (row 8) |
|---|---|---|---|---|---|
| legacy 21.1 ms (47.4 fps) | 21.100 | **FAIL** (21.10 > 20.5) | PASS | 0 (PASS) | **0 (PASS)** |
| real r1e_mock runs | 21.449 (max over runs) | **FAIL** | PASS | 0 | 0 |
| real r1d runs (17/23/30 frames) | 22.87 / 21.82 / **24.90** | **FAIL** | PASS | 0 | 0 |
| real r1e runs (192/287) | 23.62 / 21.86 | **FAIL** | PASS | 0 | 0 |
| compliant rev-4 pacer | 20.0000 | PASS | PASS | 1 (PASS) | 0 (PASS) |
| floor-dominated pathological pacer at 18 ms (`delta ~ N(1.1,0.3)`) | 19.0935 (52.37 fps) | **PASS** (19.09 <= 20.5) | PASS | **136 -> FAIL** | 0 |

Both directions are covered: the fast-side excess metric catches an 18 ms floor-dominated pacer (excess 136), and
row 7b catches the 47.4 fps deficit that rows 7/8/9 cannot see. This is the design's central correction and it
holds.

### Byte-ceiling arithmetic (A.11)

| claim | recomputed | verdict |
|---|---|---|
| `307200 / 1500 = 204.8 B/frame` at full occupancy | 204.8 | correct |
| margin vs observed max 108 B (r1e) | 204.8 / 108 = **1.896x** | "1.9x" correct |
| 1275 B/frame stream fires the ceiling at ~frame 241 | 240x1275 = 306000 <= 307200; 241x1275 = 307275 > 307200 | fires at the **241st** frame, before the 1500-frame cap |
| frame cap binds first for the configured encoder | 1500x108 = 162000 < 307200 | correct |
| can a 24 kbit/s VBR encoder sustain > 204.8 B/frame | 204.8 B/20 ms = **81.9 kbit/s = 3.4x the 24 kbit/s target**; observed max = 108 B = 43.2 kbit/s | no - unreachable for the configured encoder |
| earlier 2 MiB claim | 1500x1275 = 1912500 < 2097152 | rev-3's dead-branch criticism was correct; rev-4's 300 KiB fixes it |

### `pacer_mean_inter_send_ms_observed` false-fail simulation (compliant rev-4 pacer)

`max over active runs of (t_last - t_first)/(frames_in_run - 1)`, 4000 draws, run length drawn from {2,3,5,10,40}:

| scenario | FAIL rate (mean > 20.5) | p50 | p95 | max |
|---|---|---|---|---|
| no hiccup | **2.9 %** (n=2 runs: **11.3 %**) | 20.000 | 20.352 | 21.356 |
| 5 % hiccup 8-20 ms | **9.6 %** (n=2: 19.5 %, n=3: 10.1 %, n=5: 9.3 %) | 20.004 | 21.857 | 41.152 |

### Other verified figures

- Client capacity: `_INCOMING_AUDIO_QUEUE_SIZE = 64` (`protocol_manager.py:23`), `_TTS_FIFO_MAX_S = 10.0`
  (`audio_codec.py:26`), drop-oldest at `protocol_manager.py:162-178` and `audio_buffer.py:43-52`.
  64 + 500 = 564 frames = 11.28 s - A.16 correct.
- Generation timing in all three bundles is strictly sequential (`response.created` always after the previous
  `response.done`), so the A.4.A `UNKNOWN_RID` path is not exercised by the evidence (see MAJOR M-H).
- Every `response.audio.delta` in the diag journals carries a non-null `resp_id` (mock 44/44, r1d 12/12, r1e 7/7
  in `journal_tail`); the id-less tolerance path is defensive only.
- `delta_bytes / 960` is exact in the real bundles (r1e gen1: 890880/960 = 928 = `frames_encoded`), so real runs
  end with zero `dl_buf` residue; the residue paths are only exercised by tests.

---

## 2. Attack results

### Attack 1 - F-1 fix effectiveness: VALIDATED (with a falsified rationale)

- Positive: with the floor charged from the **send attempt** and the deadline clock authoritative, the simulated
  mean is **20.0000 ms (50.00 fps)** under all four jitter models, excess never exceeds the `<= 1` tolerance, and
  catch-up stays 0 even after 35 ms spikes. Lateness decays (2 ms/frame while the guard binds) and never
  accumulates. Row 7b fails the measured 47.4 fps pacer (21.1 > 20.5) - the assertion is a real detector.
- Reverse attack (18 vs 20): lowering `MIN_SEND_INTERVAL_MS` to 18 does weaken the *burst* guard: the pathological
  floor-dominated pacer runs at 52.4 fps. But `wire_rate_excess` still fires (excess 136 >> 1), so the weakening is
  covered by the fast-side gate; and the client's Q1 (64 packets, 1.28 s) is not at risk from a transient 19 ms
  cadence. Net: the 18 ms floor does not open an undetectable fast path.
- Falsified claim: A.5 "during normal operation the floor never binds ... it delays one interval to >= 18 ms and the
  deadline clock re-asserts on the following frame". Measured `delta > 2 ms` on 8.0 % / 23.9 % / 16.1 % of intervals;
  simulation shows the guard binds for ~L/2 frames. The conclusion survives; the stated mechanism does not
  (MAJOR M-A).

### Attack 2 - Capacity domain and canonical observable: VERIFIED

`unsent_backlog_frames = queued + in_flight` changes only on admission (`+1`); pop (`queued-1, in_flight+1`) is
net zero, and sent/flush/cancel/rebase/stall only decrease it. Sampling at "every admission event and every
in_flight entry" therefore covers every increase; the peak is admission-determined and test B's peak is uniquely
**1500** (store gauge 1499 when one frame is in `PRE_SEND_WAIT`, exactly as A.2 states). A 60 s / 3000-frame
response with backlog ~3 is not truncated because the cap is occupancy-only. Two nits: a *refused* admission must
not be sampled (else the peak could read 1501) - MINOR m-g - and test B's own frame closure does not balance
(BLOCKER B1).

### Attack 3 - Three-domain closure completeness: ONE UNBUCKETED OBJECT CLASS FOUND

Walked every exit of every byte and frame, including the combination scenarios listed in the brief:

| combination | frames | bytes | residue | verdict |
|---|---|---|---|---|
| cap while `listen_start` flushes | cap has no frame bucket; frames continue to drain, `listen_start` takes what remains -> `flushed_listen_start_frames` | `safety_truncated_pcm_bytes` (post-cap) | `residue_discarded_cap_bytes` then 0 | OK |
| stall with a frame in `SENDING` | frame completes -> `sent_confirmed_frames` | normal | normal | OK |
| stall with the frame in `PRE_SEND_WAIT` | A.6 step 2 says "queued unsent frames" only | - | - | **M-E** |
| close with a frame in `PRE_SEND_WAIT` | `_cancel_pacer(reason=close)` -> `flushed_close_frames` | - | - | OK |
| close with a frame in `SENDING` | `send_outcome_unknown_frames` -> INVALID | - | - | OK (conservative; MINOR m-e) |
| barge-in after a rebase | `flushed_bargein_frames` | - | - | OK |
| late end for a tombstoned generation | ignored by the leak guard (`turns.py:419-422`) | - | - | OK |
| id-less delta into the cap transition | `safety_truncated_pcm_bytes` | - | - | OK |
| orphan rid / unattributed | `orphan_pcm_bytes` (outside A.4.A's equation); INVALID | - | - | OK |
| duplicate end with non-empty residue | `accounting_fault_events` -> INVALID | - | - | OK |
| **the frame that trips the cap (occupancy and byte cap)** | **NO BUCKET** | bytes land in two classes under either reading | rule 3's `R < 960` is violated under the pre-check reading | **BLOCKER B1** |
| cap + later upstream `response.done` | possibly a second `GenerationEnd` | - | - | **M-C** |

Residue-vocabulary reconciliation: the 9 residue reasons cover all five `_flush_downlink` callers
(`turns.py:111,233,245,336,651`) plus the four new transitions, and the 8 frame flush reasons map one-to-one
(`pacer_stall` frames vs `stall` residue; `cap` residue only, correctly, because accepted frames keep draining).
The four `dl_buf.clear()` sites map as: `:429` consumed into the tail (no discard counter), `:438` becomes
`N == 0` only (m-7 fix), `:442` -> `accounting_fault_events`, `:611` -> reason-scoped. That part is closed.

### Attack 4 - Cancellation race: VERIFIED (self-consistent)

PRE_SEND_WAIT vs SENDING is a local state variable set between the wait's return and the transport call, so the
handler can always tell where the `CancelledError` surfaced. A cancel that lands in the sub-microsecond window
between the wait's return and the first suspension inside `send_bytes` is thrown at the transport entry and is
therefore classified outcome-unknown -> INVALID. That is conservative and consistent with A.4.C's definition
(the boundary is "where the error surfaces", not "when the cancel was requested"). A barge-in landing during the
*pacing wait* - the overwhelmingly likely case, since the pacer is suspended in the wait ~99.7 % of the time
(20 ms wait vs ~0.07 ms send) - necessarily balances with `send_outcome_unknown_frames == 0`. No defect; MINOR m-d
asks for the boundary to be stated in one sentence.

### Attack 5 - Rate-metric anti-gaming: NO GAMING WINDOW FOUND; FALSE-FAIL RISK FOUND

- `catch_up_frames_over_50fps` at 47.4 fps with the half-open window = **0** (computed on all three journals and
  analytically: a 1 s window holds ~47.4 sends, so `max(0, sent-50) = 0`). Row 8 is fast-side-only by construction,
  which is why row 7b is needed. Correct division of labour.
- Can `pacer_mean_inter_send_ms_observed` be gamed to hide 47.4 fps? No, verified by simulation: excluding
  rebase-spanning intervals removes ~1 of ~37 intervals for a 21.1 ms pacer, leaving the mean at ~21.1 (> 20.5).
  Rebasing more often is not reachable (case A requires `lateness > 40 ms`), and if all intervals span a phase
  reset the run has `frames_in_run - 1` usable intervals -> the run is dropped from the max, which can only hide a
  *slow* pacer over a *short* run (< 1 s), where the deficit is bounded by < 1 frame. Accepted.
- Run/anchor definitions vs pacer restart: `WIRE_RUN_ANCHOR_GAP_MS = 1000` splits runs, but a pacer restart after a
  < 1 s inter-response silence does **not** split the run and its phase reset is *not* a `WALL_CLOCK_PHASE_RESET`
  (A.5: "reported as `pacer_starts`"), so the restart gap is folded into the run mean. Measured false-FAIL rates for
  a *compliant* pacer: 2.9 % overall / 11.3 % for 2-frame runs (no hiccups), 9.6 % / 19.5 % with 8-20 ms hiccups
  (MAJOR M-B).

### Attack 6 - A.15 evaluability (rows 1..18 incl. 7b/17b): EVALUABLE

Every row's named field exists in A.14 (or A.12 for the client rows): checked row by row.
1 `unsent_backlog_peak_frames`+`audio_store_peak_frames`; 2 `cap_transitions_max_per_generation`;
3 all seven source-domain fields; 4 all seven framer-domain fields incl. the `still_buffered_pcm_bytes` gauge;
5 the 13-term disposition set; 6/7/7b/8/9/10/11 their named fields; 12 construction test + `legacy_drop_oldest_calls`;
13 `cancel_max_per_generation`; 14 the derived predicate + three per-step counters; 15 both max-over-generations
fields; 16 `byte_cap_failures`; 17/17b the client fields; 18 the eight PASS fields.
Aggregation domain is unique wherever it matters (rows 1, 2, 13, 15; A.14 states "max over generations").
No constant-to-constant comparison: row 16's acceptance form (`byte_cap_failures = 0`) is structurally zero for the
configured encoder, but the required test C exercises the branch with a stub encoder, so the assertion is live - this
is the honest resolution of rev-3's M-3. Row 7's `17.999` = `18.0 - 0.001` is a derived constant, acceptable.
Caveats: row 9 (`pacer_lead_frames_max <= 1`) is structurally 0 (the wait guarantees `t_attempt >= deadline_n`), so it
is a cross-check, not a rate guard (MINOR m-b); row 12's predicate (a) is still not decidable from the document
alone (MAJOR M-D); row 5 cannot balance at the cap (BLOCKER B1).

### Attack 7 - Byte-ceiling arithmetic: VERIFIED

Recomputed in section 1: 204.8 B/frame, 1.896x margin, 241-frame trigger, frame-cap-first for the configured
encoder, and 3.4x-target bitrate needed for VBR to sustain the ceiling - so the "unreachable for the configured
encoder; reachable only under encoder misconfiguration" positioning is honest, and test C makes it measurable.
The branch is live, not tautological. One structural consequence worth recording: the byte budget is only knowable
*after* encoding, which is exactly what makes BLOCKER B1 unavoidable without an added rule.

### Attack 8 - A.4.A attribution vs the real protocol: MOSTLY CORRECT, ONE NON-NORMATIVE RULE

- `_resp_id` (`turns.py:31-38`) reads top-level `response_id` else `response.id`. In the evidence every
  `response.audio.delta` carries a real id (44/44, 12/12, 7/7 in the journals), so the id-less tolerance is
  defensive, as documented (`turns.py:410-418` tolerates id-less *ends*).
- Ordering: A.4.A's "resolve, then decode" is a real reorder vs `turns.py:356-359` (guards) before `:367` (decode);
  the design states it explicitly and scopes bad-base64 invalidation to live generations. Closed.
- The tripartition needs state that does not exist today (`turns.py` has only `current_resp_id` and a single
  `_ended_resp_id`): a created-ids set plus a tombstone. A.7 mandates "a `response_id -> generation` mapping plus a
  tombstone" but does not make **when** a generation enters the tombstone, or how long it stays, normative.
  Consequence: a generation that was created and then stopped being live *without* an upstream terminal (barge-in
  clears `current_resp_id` at `turns.py:346`, or a new `response.created` overwrites `turns.py:295`) has its later
  deltas classified `UNKNOWN_RID` -> `orphan_pcm_bytes` -> run INVALID, i.e. a normal barge-in turn becomes
  unassessable (MAJOR M-H).
- Ledger self-consistency: `source = admitted + guard_dropped + safety_truncated` with `orphan` outside holds under
  the stated classification; the STALE branch (`source += N`, `guard_dropped += N`) and the LIVE branch
  (`source += N`, then admitted/truncated) are disjoint, so no double count.

### Attack 9 - GenerationEnd / stop suppression: ONE MARKER-COUNT HOLE

Exactly one stop per path is achievable: normal completion (seal -> one marker -> one stop), cap (one marker, no
synthetic tail), barge-in/abort (flush marker, immediate stop, later stop suppressed by the `tts_active` latch at
`turns.py:480-481`), stall (A.6 step 4 + step 6), close (attributed to `tts_gen`). The emission-vs-call rule makes
`tts_stops_per_generation` robust to benign duplicate calls. Connections-level close attribution is unique
(A.9: attributed to the generation owning the active TTS start; not counted if none is active).
Hole: `end_markers_per_generation <= 1` can read 2. After the cap, A.9 says the generation "is consumed/ended with
exactly one `GenerationEnd`", but A.7 says the generation identity persists across the cap transition (it is not
listed as a local finalization), so the later upstream `response.done` runs A.9's normal-completion steps 2-3 and
enqueues a second marker. This is reachable in the mandated test B, where the upstream response completes while the
pacer is stalled (MAJOR M-C).

### Attack 10 - A.3 single-store construction test: PARTIAL (MAJOR)

- (b) and (c) are mechanically decidable: the legacy names are enumerated and a class-namespace scan can assert
  their absence.
- (a) "exactly one attribute set that can hold complete audio frames exists and is the designated store object" is
  still not decidable from the document: `Connection` legitimately owns `uplink_q` (`turns.py:86`), which holds
  complete 640-byte 16 kHz uplink PCM frames, and there is no enumeration rule for "attribute sets that can hold
  complete audio frames". A literal reading of (a) fails on a *correct* implementation.
- `dl_buf` sub-frame invariant (`len(dl_buf) < 960` after each delta step) is compatible with cap/stall residue
  discard only if the framer refrains from cutting when capacity is absent - which is precisely the unresolved point
  of BLOCKER B1; today's code cuts first (`turns.py:377-386`), so the invariant and the cap transition interact.
- Removal-list completeness (grepped): A.3 names `dl_q` `turns.py:77`, `DL_QUEUE_MAX` `config/config.json:6`,
  `SENTINEL` `:20`, `_stop_pending` `:84`, the four helpers, `counters.audio_out_dropped` `counters.py:26,56`, and
  `dl_q` uses. Still missing live references: **`DL_QUEUE_MAX` in `main.py:24` (DEFAULTS), `main.py:53` (config
  threading), `main.py:75-76` (log)**; and the use sites `SENTINEL` (`turns.py:500,519,548,572,620`),
  `_stop_pending` (`:297,541,549,568,573,612`), `audio_out_dropped` (`turns.py:521,552`), `dl_q` (`:513,528,532`);
  the list's `turns.py:555,559` are not `dl_q` uses (they use the local alias `q` from `:532`), so the line-level
  bookkeeping is imprecise in both directions.

### Free attack - new inconsistencies introduced by rev-4's rewrites

- A.2 residue discard vs A.4.B equation: consistent (cap residue stays inside `admitted_pcm_bytes` and appears as the
  `residue_discarded_pcm_bytes` term; it is explicitly *not* `safety_truncated`).
- A.5 metric definition vs A.13 gate: consistent; A.13's `pacer_mean_inter_send_ms_observed <= 20.5` is row 7b.
- A.11 ceiling vs A.14 field names: consistent (`byte_cap_failures`, `audio_store_current_bytes`/`peak_bytes`).
- A.14 gauge list vs A.4.C quiescence: `still_buffered_pcm_bytes` is 0 at quiescence on every path (tail consumes,
  cap/stall/byte-cap/send-error discard, the five flush reasons clear), so A.4.B's `still_buffered_pcm_bytes` term is
  consistent.
- A.12 client starvation observable: `client_midstream_underrun_events` needs a defined "playback start instant" for
  the 500 ms priming exclusion; otherwise the window boundary is implementation-defined (MINOR m-f).
- Timestamp ambiguity: neither `pacer_min_inter_send_ms_observed` nor `pacer_mean_inter_send_ms_observed` says whether
  the timestamp is the send *attempt* (A.5's floor instant) or the send *completion* (the existing journal's
  `t_send`, `turns.py:588`). A completion-based measurement can read `18 - T` (~17.79-17.9 ms) and fail row 7 on a
  compliant pacer (MAJOR M-F).
- Id-less delta arriving after an end while `current_resp_id` is still set (the `response.audio.done` path does not
  clear it, `turns.py:452-453`): A.4.A would classify it LIVE and admit bytes into `dl_buf`, after which the
  duplicate-end assertion `len(dl_buf) == 0` fires -> `accounting_fault_events` -> INVALID (MINOR m-h).
- Upstream close concurrent with an in-flight send: `close`/`qwen_closed` cancel the pacer inside `send_bytes` ->
  `send_outcome_unknown_frames` -> INVALID, so no relocation claim is evaluable for that run (MINOR m-e).

---

## 3. Closure audit of the 14 §0.3 rows (24 original findings)

Verdicts are based on my own reading of the rev-4 text plus source/evidence verification, not on the "closed" claim.

| §0.3 row | original finding (abbrev.) | verdict | rev-4 section + evidence |
|---|---|---|---|
| F-1 | 20 ms floor reproduces the deficit; no slower-direction assertion | **CLOSED** | A.5 (attempt-charged floor, 18 ms slack, row 7b). Simulated mean 20.0000 ms; 47.4 fps fails row 7b (21.10 > 20.5); 18 ms floor-dominated pacer caught by excess=136. Rationale text is wrong (M-A), mechanism is right. |
| F-2 | disposition domain missing listen_start / upstream-close flush, stall/byte-cap residue, failed synthetic-tail encode | **CLOSED** | A.4.B/C (9-reason residue vocabulary, `flushed_{listen_start,upstream_closed,byte_cap,send_error}_frames`, `synthetic_tail_encode_failures`, `tail_encode_failed_pcm_bytes` in the PASS set). Verified against `_flush_downlink` callers `turns.py:111,233,245,336,651` and encode failure `turns.py:430-436`. |
| F-3 | residue admitted before cap/stall has no exit bucket | **CLOSED** | A.2 rule 3, A.6 step 3, A.11, `residue_discarded_{cap,stall,byte_cap,send_error}_bytes`, explicit "not safety_truncated" rule; A.4.B equation extended. All four `dl_buf.clear()` sites mapped. (The adjacent *frame*-level hole is new -> B1.) |
| F-4 | `in_flight_frames` undefined for "popped, awaiting its slot" | **CLOSED** | A.4.C two sub-states (PRE_SEND_WAIT/SENDING), known-unsent for wait cancellation -> reason-scoped flush, only transport-internal cancellation is unknown; test B peak uniquely 1500 (store gauge 1499). Boundary is implementable because the state variable is set between the wait's return and the transport call. |
| M-1 | `catch_up_frames_over_50fps` window/max unspecified | **CLOSED** | A.5 half-open `(t-1000 ms, t]`, max-over-sends, "accumulated" deleted. Recomputed: 0 for both a compliant and the 47.4 fps pacer. |
| M-2 | four `*_per_generation` fields lack an aggregation domain | **CLOSED** | A.14 "max over generations of that generation's count" for all four; A.9 adds the connection-level stop attribution rule. |
| M-3 | 2 MiB ceiling cannot bind (tautology) | **CLOSED** | A.11 lowered to 307200 B; arithmetic verified (241 frames at 1275 B/frame < 1500); test C mandated with a stub encoder. Honest positioning (unreachable for the configured encoder). |
| M-4 | exception containment has no observable | **CLOSED** | A.4 header (per-branch containment) + `qwen_dispatch_errors`, nonzero => INVALID; A.10 per-step containment and the S1-S4 counters. (A mid-delta containment failure can leave a generation that never quiesces, but the run is INVALID, so assertions are not the arbiter - MINOR-class.) |
| M-5 | orphan / bad-base64 rules conflict with deliberate id-less tolerance | **CLOSED** | A.4.A ordered attribution-then-decode; id-less delta with a live generation => LIVE + `idless_delta_events` (non-invalidating); bad-base64 invalidation scoped to live-generation deltas. Matches `turns.py:356-359,365-371,410-418`. |
| M-6 | synthetic-tail encode failure invisible | **CLOSED** | A.4.B `synthetic_tail_encode_failures` + `tail_encode_failed_pcm_bytes`, and the failure counter is in the normal-completion PASS set (A.15 #18); `turns.py:430-436` is the site. |
| M-7 | single-store proof not implementable; removal list incomplete | **PARTIAL -> MAJOR (not a blocker)** | A.3 adds (a)(b)(c) + a longer list; (b)/(c) are decidable, but (a) is still not decidable from the document (uplink_q holds complete uplink PCM frames; no enumeration rule), and the list still misses `main.py:24,53,75-76` plus the use sites of SENTINEL/_stop_pending/audio_out_dropped/dl_q. Residual defect (a second store could escape detection) is a verification gap, not a reachable runtime media defect, and (b)+(c) cover every *known* legacy structure - hence MAJOR, not BLOCKER. |
| M-8 | barge-in step bits never defined | **CLOSED** | A.10 S1-S4 with per-step outcomes, three failure counters, `barge_in_sequence_incomplete` derived, S5 explicitly out of scope and tracked by A.8. |
| m-1 | `lateness` never defined | **CLOSED** | A.6 `lateness_n = max(0, now - deadline_n)` at the pre-send decision point. |
| m-2 | `pacer_min_inter_send_ms_observed` must be connection-wide | **CLOSED** | A.5/A.13 state connection-wide across generations, restarts, rebases. |
| m-3 | initial value of the floor unstated | **CLOSED** | A.5 `initial value None (no constraint; m-3)`. |
| m-4 | floor update on failure/abandonment | **CLOSED** | A.5 mandates `connection_last_audio_send_at := monotonic_now()` inside the `CancelledError` handler (today `turns.py:592-594` does nothing). |
| m-5 | single-pacer exclusivity; two `send_cancel` sites missing from the rewrite list | **CLOSED** | A.5 single-pacer + atomic reserve; A.3 rewrite list includes `turns.py:249-255` and `:340-349` -> `cancel_upstream_once`. |
| m-6 | canonical backlog has no observable | **CLOSED** | A.2/A.14 `unsent_backlog_peak_frames` + `audio_store_peak_frames <= unsent_backlog_peak_frames`. |
| m-7 | 1-byte residue dropped; duplicate-end clear unclassified | **CLOSED** | A.4.B (tail for any `0 < N < 960` incl. `N == 1`, the `len >= 2` shortcut at `turns.py:424` is a required change) + duplicate-end must assert 0 else `accounting_fault_events` (`turns.py:441-442`). |
| m-8 | no quiescence instant for a tombstoned generation | **CLOSED** | A.4.C quiescence definition (no store entry, no in-flight, stop emitted or suppressed; tombstones sample locally). |
| m-9 | stop/marker counters must count emissions | **CLOSED** | A.9 "counts emissions, not calls" + the `turns.py:480-481` no-op rule + `tts_gen` attribution. |
| m-10 | two contradictory byte counters; bad-base64 scope; "accumulated" wording | **CLOSED** | A.4.A retires `qwen_audio_delta_bytes` as an alias of `admitted_pcm_bytes`; invalidation scoped; wording fixed (`turns.py:372-373`, `counters.py:19,48`). |
| over-claim 1 | A.1 "removes the deficit" | **CLOSED** | A.1 reworded: "designed to restore the 50 fps media rate"; `STATIC_AUDIO_ROOT_CAUSE = UNPROVEN`. |
| over-claim 2 | A.13 starvation-blind gate | **CLOSED** | A.13 adds `client_midstream_underrun_events` (A.12 defines it, 500 ms priming allowance excluded) + row 17b + an explicit scope restriction when no instrumented client run exists. |

Summary: 23 CLOSED, 1 PARTIAL (M-7 -> MAJOR). No closure row leaves a *reachable runtime* defect unclosed.
The BLOCKER below is a **new** hole that rev-4 left (and partly created) in the same area as F-3/F-4.

---

## 4. BLOCKERS

### B1 - The frame that trips a store cap (occupancy cap and byte cap) has no disposition bucket; under either reading of A.2, one of the two closure equations breaks, and for the byte cap no reading is consistent.

Evidence:
- A.2: "If **admitting a newly completed frame** would make `unsent_backlog_frames + 1 > MAX_FUTURE_FRAMES`, transition
  that generation exactly once ..." -> at the transition a **complete frame exists**; A.2 rule 2 ("accept only enough
  bytes to complete/store that frame") and rule 5 ("must leave no **newly accepted** partial residue") both speak about
  a frame that is completed.
- A.3 pipeline: `20 ms framing -> encode once to Opus (one packet per complete frame) -> store`. This is the order the
  current code implements (`turns.py:377-386`: `del dl_buf[:960]` then `enc24.encode(...)`, then `_enqueue_frame`).
- A.4.C terminal buckets: `sent_confirmed_frames | flushed_{bargein,abort,close,listen_start,upstream_closed,
  pacer_stall,byte_cap,send_error}_frames | send_failed_frames | send_outcome_unknown_frames`, plus the non-terminal
  gauges `still_stored_frames`, `in_flight_frames`. None covers "encoded, complete, refused because the store is full".
- A.11 has the same shape for bytes: the ceiling can only be evaluated **after** encoding (the packet size is unknown
  before `enc24.encode`, `audio.py:25-29`), and A.11 only says to "flush the remaining **accepted** store".

Counterexample path (the mandated test B): short burst, stalled pacer. Frames 1..1500 are encoded+stored.
Frame 1501 is cut from `dl_buf` and encoded, then refused admission. Then
`encoded_full_frames = 1501`, `sent_confirmed_frames = 0`, all `flushed_* = 0` (the accepted store is *not* flushed at
the cap - A.9 lets it drain), `still_stored_frames = 1500`, `in_flight_frames = 0`, `synthetic_tail_frames = 0`.
A.4.C requires residual 0: `1501 + 0 - (0 + 0 + 0 + 1500 + 0) = 1 != 0` -> **A.15 #5 fails in the test that must
prove the cap works.** If instead the implementer reclassifies frame 1501's bytes as `safety_truncated_pcm_bytes`
(A.2 rule 4), then A.4.B (`admitted_pcm_bytes = 960*encoded_full_frames + ...`) breaks because those bytes are in
`encoded_full_frames` but not in `admitted_pcm_bytes`. If the implementer pre-checks capacity *before* cutting
(reading rule 2 as a pre-check), then at the transition `dl_buf` holds >= 960 bytes of a complete frame and rule 3's
`0 <= R < 960 B` is violated, and those bytes would be simultaneously `residue_discarded_cap_bytes` (inside
`admitted`) and `safety_truncated` (outside `admitted`) - a double classification. So all three readings break
something. For the **byte** cap (test C) the pre-check reading is *impossible in principle* with the doc's own
arithmetic (a 1275 B conservative pre-check would fire at 241 frames for the configured 60 B encoder, destroying
normal operation), so the byte-cap path has **no** consistent reading at all.

Reachable? Yes - in required tests B and C, and in production whenever a slow/stalled pacer meets a long response.

Minimal fix (normative sentence, one of two):
1. Add a non-terminal terminal-bucket pair: `cap_refused_frames` and `byte_cap_refused_frames` (or one
   `refused_at_cap_frames` plus a reason tag), counted on the A.4.C LHS **and** RHS, and state that the tripping frame
   is encoded-then-refused (its bytes remain in `admitted_pcm_bytes`, so its 960 source bytes stay inside A.4.B's
   `960*encoded_full_frames` term, no `safety_truncated` reclassification); or
2. State that capacity is checked **before** framing (frame cap) and that any `dl_buf` remainder at the transition -
   including a >= 960-byte complete-frame remainder - is discarded by reason (cap/byte_cap), relaxing A.2 rule 3's
   bound to `0 <= R < 960 + FRAME_BYTES` and adding the corresponding A.4.A/A.4.B reclassification rule; and for the
   byte cap, add the post-encode refusal bucket as in option 1 (the only consistent choice there).

Exit criterion (verifiable): with the implementation written exactly to the amended text, test B and test C both
report residual 0 for A.4.C's equation and 0 for A.4.B's equation, with `encoded_full_frames` equal to
`1500 + refused_count` (test B) / `240 + refused_count` (test C) and `refused_count` reading exactly 1 and 0
respectively.

---

## 5. MAJORs

M-A. A.5's guard rationale is falsified by the evidence (functional outcome unaffected).
A.5: "measured wake overshoot delta ~ 1.03/1.10/1.22 ms plus send duration T <= 0.214 ms is < 2 ms, so during normal
operation the floor **never binds**"; and "when it does bind (a > 2 ms late wake), it delays **one interval** to >= 18 ms
and the deadline clock re-asserts on the following frame". Measured: delta > 2 ms on **8.0 % / 23.9 % / 16.1 %** of
intervals (mock / r1d / r1e, journals); simulation shows the guard binds for ~L/2 consecutive frames (a 10 ms spike ->
~10 frames of 18.85-19.43 ms cadence; 35 ms -> ~20 frames). The mean stays 20.0000 ms and excess stays <= 1, so the
design is safe; but `pacer_floor_bind_count` must be expected to be large, and an implementer who tunes the 2 ms slack
on the "never binds" premise will mis-size it. Fix: replace the rationale with "the guard is expected to bind
whenever delta > 2 ms and then acts as the phase-recovery pace-setter for ~L/2 frames; the deadline clock bounds the
total recovery so the run mean stays at 20.000 ms and `wire_rate_excess_frames_max <= 1`".
Exit: text consistent with the measured delta distribution; `pacer_floor_bind_count` reported and expected nonzero.

M-B. Row 7b is not robust for short runs (no priming exclusion, no minimum run length).
`pacer_mean_inter_send_ms_observed` = max over `WIRE_RUN_ANCHOR_GAP_MS`-delimited runs of
`(t_last - t_first)/(frames_in_run - 1)`; the only exclusion is a rebase-spanning interval. A pacer restart after a
< 1 s inter-response silence keeps the run alive and adds the restart gap (`pacer_starts`, A.5) to the numerator, and a
2-frame run is a single noisy interval. Computed false-FAIL rates for a *compliant* rev-4 pacer (mean 20.0000 ms):
2.9 % overall and 11.3 % for 2-frame runs with no hiccups; 9.6 % / 19.5 % with 8-20 ms hiccups. Free-tier acceptance
would flake on short utterances. Fix: exclude the first interval of each run (priming) or require
`frames_in_run >= 5`, or aggregate over the connection (e.g. a global trimmed mean plus a per-run `<= 21.5` cap).
Exit: the metric provably returns <= 20.5 for a compliant pacer over 10^4 simulated short-run sessions including
5 % hiccups, and still fails the measured 21.1 ms legacy pattern on all three journals.

M-C. Cap + later upstream end can produce two `GenerationEnd` markers -> A.15 #15 can read 2.
A.9 (cap): "the generation is consumed/ended with exactly one `GenerationEnd`"; A.9 (normal completion) steps 2-3
("seal the generation; enqueue exactly one `GenerationEnd`") are not conditioned on the generation already being
cap-finalized, while A.7 says the generation identity *persists across the safety-cap transition* (it is not listed as
a local finalization, only "upstream-terminal or locally finalized/tombstoned" ends it). In the mandated test B the
upstream response completes while the pacer is stalled, so `response.done` (`turns.py:444-451`) reaches the
normal-completion path and a second marker is enqueued. Fix: one sentence - "a generation that has already been
sealed (cap, stall, send-error, barge-in, abort, close, listen_start, upstream-close) must not enqueue a second
`GenerationEnd`; its later upstream terminal event is absorbed without a marker and without a stop".
Exit: test B reports `end_markers_per_generation == 1` and `tts_stops_per_generation == 1`.

M-D. A.3's construction-test predicate (a) is still not decidable from the document, and the removal list still
misses live references (re-derivation of rev-3 M-7).
(a) "exactly one attribute set that can hold complete audio frames exists and is the designated store object": no
enumeration rule; `uplink_q` (`turns.py:86`) holds complete 640-byte uplink PCM frames, so a literal test fails on a
correct implementation. Missing live references: `DL_QUEUE_MAX` at `main.py:24` (DEFAULTS), `main.py:53`
(`SimpleNamespace`), `main.py:75-76` (log) - removing it only from `config/config.json:6` leaves the constant and its
plumbing alive; plus the use sites `SENTINEL` (`turns.py:500,519,548,572,620`), `_stop_pending`
(`:297,541,549,568,573,612`), `audio_out_dropped` (`:521,552`), `dl_q` (`:513,528,532`); and the list's
`turns.py:555,559` are not `dl_q` uses (local `q` from `:532`).
Why not a blocker: the residual is "a second store could escape detection" - a verification gap, not a reachable
runtime media defect - and (b)+(c) already catch every known legacy structure; rev-3 rated the same finding MAJOR.
Fix: define (a) as "the set of instance attributes whose declared type is the generation-scoped store type is exactly
{`store`}" (a type-based, enumerable predicate), and complete the list with `main.py:24,53,75-76` and the use sites.
Exit: a unit test written from the document alone passes on the rev-4 implementation and fails when any of
`dl_q`/`SENTINEL`/`_stop_pending`/`audio_out_dropped`/`DL_QUEUE_MAX` is reintroduced at any of the listed lines.

M-E. A.6 case B flushes only "queued unsent frames"; the in-flight `PRE_SEND_WAIT` head frame has no named
resolution.
`lateness_n` is evaluated "for the frame at the head of the send slot ... at the pre-send wait decision point" (A.6),
so at the fatal-stall instant the head frame is by construction in `PRE_SEND_WAIT` (i.e. `in_flight_frames == 1`),
yet step 2 says "flush all **queued unsent** frames to `flushed_pacer_stall_frames`". Literal implementation leaves
`in_flight_frames == 1` at quiescence, violating A.4.C's quiescence clause (`in_flight_frames = 0`, A.15 #5) and
A.6's own "No frame may be silently discarded". Reachable in the mandated 10 s-stall test. Why not a blocker: the
required vocabulary already exists (`flushed_pacer_stall_frames` + the A.4.C pre-send-wait known-unsent rule), and
A.4.C's quiescence requirement forces the implementer to resolve it; the text is imprecise, not inconsistent.
Fix: change step 2 to "flush all store-resident unsent frames **and resolve the in-flight head frame** (known-unsent
if its `CancelledError` surfaces from the pre-send wait -> `flushed_pacer_stall_frames`; `send_outcome_unknown_frames`
if from inside the transport call)".
Exit: the 10 s-stall test reports `in_flight_frames == 0`, residual 0 for A.4.C, and `send_outcome_unknown_frames == 0`.

M-F. The spacing metrics do not pin the timestamp they are measured on.
A.5 asserts "the observed inter-send interval is never below `18.0 - 0.001 = 17.999 ms`", and A.15 #7/#7b read
`pacer_min_inter_send_ms_observed` / `pacer_mean_inter_send_ms_observed`, but neither says whether the timestamp is
the send **attempt** (A.5's floor instant, `connection_last_audio_send_at`) or the send **completion** (the field the
existing journals record, `turns.py:588`). With the floor charged from the attempt, completion-based gaps can read
`18 - T` (~17.79-17.9 ms with the measured T) -> a compliant pacer fails #7. Fix: state that all spacing metrics are
computed on the send-attempt instant (and, if a completion-based journal is retained, that it is diagnostic only).
Exit: on synthetic compliant runs with T up to 0.3 ms, #7 and #7b pass; on the 21.1 ms legacy pattern, #7b fails.

M-G. `UNKNOWN_RID` can turn a normal superseded generation into an INVALID run.
A.4.A classifies "rid present but never created on this connection" as `UNKNOWN_RID` -> `orphan_pcm_bytes` -> run
INVALID, and the STALE class requires the rid to be "present in the connection's tombstone map". A.7 mandates such a
map but never makes the insertion rule normative ("long enough to classify late deltas" is not a rule). A generation
that stops being live *without* an upstream terminal - barge-in clears `current_resp_id` (`turns.py:346`), a new
`response.created` overwrites it (`turns.py:295`), or the cap fires - may therefore be absent from the map, and its
later deltas invalidate the run. Evidence: all three bundles show strictly sequential turns, so this is not observed;
it is reachable in principle on a barge-in with an upstream terminal still in flight. Fix: state that any generation
ceasing to be live (ended, invalidated, barge-in, abort, cap, stall, superseded by a new `response.created`) is
inserted into the tombstone map atomically at that instant and retained for the connection lifetime.
Exit: a scripted run in which a new `response.created` precedes the previous generation's terminal event, followed by
deltas for the superseded rid, reports residual 0 for A.4.A with `orphan_pcm_bytes == 0` and
`guard_dropped_pcm_bytes > 0`.

---

## 6. MINORs

- m-a. A.16's r1d `T` p95 is 0.136 ms (lower-quantile convention at index 65); linear interpolation on the same
  sample gives 0.141 ms (0.1395 nearest-rank). Every other A.16 row matches my recomputation. State the percentile
  convention once.
- m-b. A.15 #9 (`pacer_lead_frames_max <= 1`) is structurally 0 because the wait guarantees
  `t_attempt >= not_before >= deadline_n`; keep it as a cross-check but stop presenting it as a pacing assertion.
- m-c. `pacer_floor_bind_count` is undefined on a tie (`not_before == deadline_n`): say whether a tie counts as a
  floor bind (it should not).
- m-d. A.4.C's "a barge-in landing during the pacing wait must therefore balance with
  `send_outcome_unknown_frames == 0`" is true in practice but not in the sub-microsecond window between the wait's
  return and the first suspension inside `send_bytes`; one sentence fixing the boundary as "where the `CancelledError`
  surfaces" removes the ambiguity.
- m-e. A connection close concurrent with an in-flight send yields `send_outcome_unknown_frames` -> INVALID, so the
  relocation claim is unevaluable for that run; state this explicitly (it is the conservative choice).
- m-f. A.12's `client_midstream_underrun_events` needs a normative "playback start instant" for the 500 ms priming
  exclusion, otherwise the window is implementation-defined.
- m-g. A.2's "sampled at every admission event" should state that a *refused* admission is not sampled, else the peak
  could read 1501 and fail A.15 #1.
- m-h. An id-less delta arriving after an end but while `current_resp_id` is still set (the `response.audio.done` path
  at `turns.py:452-453` does not clear it) is classified LIVE, admitted, and then trips the duplicate-end
  `len(dl_buf) == 0` assertion -> `accounting_fault_events` -> INVALID. Scope A.4.A's LIVE rule to "live **and not
  ended**".
- m-i. A.11 does not state the byte-cap check point (necessarily post-encode); documenting it also documents why B1
  needs the refusal bucket.

---

## 7. Independently verified as correct

- The measured deficit: same-pacer gap p50 21.0939 / 21.1627 / 21.3062 ms -> 47.41 / 47.25 / 46.93 fps; deficit
  2.6 / 2.75 / 3.07 frames/s; `T` p50 0.060 / 0.0645 / 0.0835 ms, max 0.124 / 0.198 / 0.214 ms; median delta
  1.034 / 1.098 / 1.223 ms; packet mean 61.47 / 55.87 / 58.76 B, max 87 / 79 / 108 B. A.16 reproduces (except the
  r1d p95 convention, m-a).
- The A.5 fix works: simulated mean **20.0000 ms / 50.00 fps** under five jitter models; excess never exceeds the
  `<= 1` tolerance; catch-up 0 even after 35 ms spikes; the measured 47.4 fps pattern fails row 7b; an 18 ms
  floor-dominated pacer is caught by `wire_rate_excess_frames_max = 136`.
- `catch_up_frames_over_50fps` with the half-open window is 0 for both a compliant pacer and the 47.4 fps pacer - the
  metric is fast-side-only by construction, exactly as A.13 states; the slow side is covered by row 7b.
- Capacity domain: the backlog changes only at admission, so the A.2 sampling rule covers every increase; test B's
  peak is uniquely 1500 (store gauge 1499); a 60 s response is not truncated.
- Byte arithmetic: 307200/1500 = 204.8 B; 204.8/108 = 1.896x; 240x1275 = 306000 <= 307200 < 307275 = 241x1275;
  1500x108 = 162000 < 307200; a 24 kbit/s VBR encoder cannot sustain 81.9 kbit/s. A.11 is live and testable.
- Residue vocabulary: the 9 reasons cover all five `_flush_downlink` callers (`turns.py:111,233,245,336,651`) plus the
  four new transitions; the 8 frame flush reasons map one-to-one; the four `dl_buf.clear()` sites (`:429,:438,:442,:611`)
  map to tail-consumed / `N == 0` only / `accounting_fault_events` / reason-scoped. F-2/F-3 are genuinely closed at
  the residue level.
- Source anchors in the design are accurate: `turns.py:20` (SENTINEL), `:77-78` (dl_q/dl_buf), `:84` (`_stop_pending`),
  `:249-255`/`:340-349` (the two `send_cancel` sites), `:356-359` + `:367` (guard before decode), `:372-373`
  (`qwen_audio_delta_bytes`), `:377-386` (framing/encode loop), `:410-418` (id-less end tolerance), `:424` (`len >= 2`),
  `:429/:438/:442` (residue clears), `:435` (tail encode failure), `:480-481` (tts no-op latch), `:492/:498/:503/:508/:531`
  (helpers), `:591` (legacy sleep), `:592-594` (bare re-raise), `:599-608` (finally), `:610-611` (`_flush_downlink`),
  `:625` (`_cancel_pacer`), `:648-651` (`_on_qwen_closed`).
- Client figures: `_INCOMING_AUDIO_QUEUE_SIZE = 64`, `_TTS_FIFO_MAX_S = 10.0`, drop-oldest in both queues,
  564 frames = 11.28 s, 50 chunks/s drain.
- A.14/A.15 field coverage: every one of rows 1..18 (incl. 7b, 17b) names fields that exist, with unique aggregation
  domains for the four `*_per_generation` fields.
- m-1..m-10 and both over-claims: reworded/defined as claimed, verified against source lines and the evidence.

---

## 8. Verdict

DESIGN_REVIEW_BLOCKERS = 1
DESIGN_REVIEW_MAJORS   = 7
DESIGN_REVIEW_MINORS   = 9
DESIGN_REVIEW          = REVISE

Gate note: B1 makes A.15 #5 (frame closure) unsatisfiable in the two mandated cap tests and has no consistent
reading for the byte cap, so implementation remains blocked. Every other finding is either non-reachable in a
required test (major/minor) or a documentation/evaluability defect that does not by itself gate the gate.
