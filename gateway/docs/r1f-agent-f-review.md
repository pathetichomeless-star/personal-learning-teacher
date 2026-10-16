# R-1f Agent F re-review (rev 2)

Reviewer: Agent F (fresh, independent). Inputs: Part 0 + Part A of `rtl-lab/r1f-design-review.md` (rev 2, normative), the read-only sources listed in the brief, and the raw sent-Opus journals. Nothing was implemented, and no file other than this one was modified.

All `A.x` references are to `rtl-lab/r1f-design-review.md`; all code references are `file:line`.

---

## Verification results

### 1. Pacer (A.3)

**(a) Long-run send rate.** Rule 1 (never send earlier than `deadline_n − MAX_PACER_LEAD_MS`) is an *earliest-send-time* constraint: with `MEDIA_FRAME_MS = 20` and `MAX_PACER_LEAD_MS = 20`, the earliest send for frame `n+1` is `deadline_{n+1} − 20 = deadline_n`, i.e. exactly 20 ms after the earliest send of frame `n`. If the pacer waits for that instant, the asymptotic rate is exactly 50 fps. **But the design never says the pacer waits.** Rule 3 (A.3:114) says only "send **only one** frame and continue with `n := n + 1`", and rule 6 (A.3:117) floors the spacing at `MIN_SEND_INTERVAL_MS = 16`. Under the literal reading (send, then sleep until the 16 ms floor is satisfied), `t_n ≥ max(t_{n−1} + 16, deadline_n − 20)` and the 16 ms chain binds until the lead bound catches up, giving **62.5 fps** while `lateness_n ∈ (−20, 40]`. Simulation of `t_n = max(t_{n−1}+16, deadline_n−20)` from a fresh epoch: sends at 0, 16, 32, 48, 64, 80, then 20 ms spacing — **6 frames in the first 80 ms (75 fps instantaneous), i.e. +2 frames (40 ms) of excess over the client's 50 fps**, retained thereafter. With `MIN_SEND_INTERVAL_MS = 20` the same schedule is exactly 20 ms from the first frame (no excess). So (a) holds only under an interpretation the document does not state, and (b) is false as written.

**Worst case before a rebase.** Rebase fires at `lateness > 40` (A.3:115). Simulated catch-up with the 16 ms floor and `lateness = 40`: 15 sends at 16 ms (40, 56, 72, … 264 ms), then 20 ms — **+3 frames (60 ms) of excess in 240 ms**. Per rebase, the immediate 16 ms transient yields **+2 frames (40 ms)** before the lead bound saturates.

**Is `CATCH_UP_BURST = DISABLED` consistent with a 16 ms floor?** **No.** A 16 ms floor is a standing permit to emit at 62.5 fps, i.e. a (small, bounded) catch-up capability — the opposite of "DISABLED", and a direct contradiction of rule 5 ("must never attempt to recover accumulated lateness by flooding the client", A.3:116). To make the constant true, `MIN_SEND_INTERVAL_MS` must be ≥ `MEDIA_FRAME_MS` (20).

**Are the three required assertions measurable from a counter?** **No, for all three** (A.3:121-125, A.13:296-299):

- `MAX_MEASURED_PACER_LEAD_FRAMES <= 1`: A.7 (A.7:228-245) contains no lead counter. `pacer_behind_frames` is the opposite sign (behind, not ahead) and is a gauge, not a max.
- `MIN_SEND_INTERVAL_MS >= 16`: `MIN_SEND_INTERVAL_MS` is a **constant**, not a measurement, so this "runtime assertion" is vacuous. The meaningful assertion (`min_observed_inter_send_ms >= 16`) needs a counter that does not exist in A.7.
- `CATCH_UP_BURST_COUNT = 0`: no counter in A.7, and "burst" is never defined (one-frame-per-iteration vs sub-`MEDIA_FRAME_MS` spacing vs >50 fps rate).

None of the three is named in A.7. See **B-4**.

### 2. Rebase consequence (A.3 rule 4)

The brief's premise ("rebasing discards up to 40 ms of media time") is not what A.3:115-116 says: 40 ms is the *trigger threshold*, so the lateness abandoned at a rebase is **> 40 ms and unbounded** (a blocked event loop of 10 s produces a rebase with 10 s of abandoned schedule). Two further things are undefined:

- **Frame disposition at rebase.** A.3 rule 4 resets `media_epoch` and `n := 0` but never says whether frames already in the store are retained (delivered late) or discarded as "overdue". Reading 1 (retain): no frames are lost, but the design's claim (A.1:61) that the pacer "remove[s] the deficit at the *rate* level" is converted into unbounded, permanent added delivery latency — and the client's 50 fps drain (stream_manager.py:69-71, blocksize 960 @ 48 kHz) will underrun for the whole stall. Reading 2 (discard): frames are committed to **neither** closure in A.4.3, so both identities lose frames.
- **Magnitude accounting.** `pacer_rebases` (A.7:241) is an event *count*. No counter carries the discarded lateness/frames; `pacer_behind_frames` (A.7:242) is unnamed as a gauge or a max and cannot substitute. The design itself calls a rebase "a *loss* of media time" (A.3:116) while providing no loss accounting.

**Is A.7's counter contract sufficient to detect it?** **No.** Required additionally: (i) a hard bound on lateness tolerated at a rebase (beyond which the generation is torn down and its frames flushed to a counted bucket instead of silently rebased); (ii) an explicit statement that store frames survive a rebase; (iii) `pacer_rebase_max_lateness_ms` plus a frame-closure bucket for any frames discarded at rebase. See **B-5**.

### 3. Store replacement (A.2)

**Achievable?** Yes — the pipeline is realisable — but A.2 does not enumerate what must change, and "unreachable from normal R-1f audio delivery" (A.2:81) is weaker than "removed". The complete set of symbols that touch the current single queue is: `self.dl_q` (turns.py:77); `_enqueue_frame` (turns.py:492) called at turns.py:392 and turns.py:434; `_enqueue_sentinel` (turns.py:498) called at turns.py:439; `_ensure_pacer` (turns.py:503); `_drop_one_non_sentinel` (turns.py:508); `_put_drop_oldest` (turns.py:531); and the `dl_q` reads at turns.py:321-322, 337, 568-578, 616-621, 633. These are **all** the paths that reach `_put_drop_oldest` (verified: only turns.py:495 and turns.py:500 call it). `config.json:6` `DL_QUEUE_MAX = 256` must also stop being read.

**Verifiable?** `LEGACY_DROP_OLDEST_CALLS = 0` is verifiable as a counter, but it **does not prove single-stage**: `_drop_one_non_sentinel` is only reached when `q.full()` (turns.py:534), so a second queue left in series that never fills yields 0 while still existing — and if it is left upstream of the pacer it *is* the `store → legacy queue → pacer` chain that A.2:79 forbids. There is also an uncounted drop path inside `_put_drop_oldest`'s `QueueFull` fallback (turns.py:547-555) which increments `audio_out_dropped` without going through `_drop_one_non_sentinel`; a counter attached only to the latter would miss it. Required: name the deleted symbols, delete `dl_q`/`DL_QUEUE_MAX` outright, and back single-stage with a construction-time/code-level check, not with a drop counter. See **M-1**.

**Two queues in series?** Yes, this is still reachable as written (store added in front of `_enqueue_frame`, `dl_q` retained). See **M-1**.

**Additional pipeline gap:** A.2's stage list (A.2:67-74) contains no end-of-response marker. Today the `SENTINEL` (turns.py:20, enqueued at turns.py:439, consumed at turns.py:572-578, and used by `_stop_pending`) is what lets the pacer drain, call `_stop_tts("pacer_finally")` and move to LISTENING (turns.py:599-608). The new store's termination and TTS-stop semantics are therefore undefined. See **M-2**.

### 4. Closure completeness (A.4.2, A.4.3)

Every path by which bytes/frames currently leave the pipeline, tested against the two identities:

| # | Path | What leaves | In closure? |
|---|---|---|---|
| 1 | `dl_buf.extend(raw)` turns.py:373; framing loop 377-386 | accepted bytes; complete frames | yes (accepted / encoded_full_frames) |
| 2 | **encode failure** — `del` at turns.py:379, `continue` at turns.py:385 | one complete 960-byte frame, silently | **NO — no bucket** |
| 3 | response-end residue: pad+encode turns.py:424-436 (`if len(dl_buf) >= 2`) | one synthetic tail frame | yes (A.4.4) |
| 4 | response-end residue **`len(dl_buf) < 2`** → clear turns.py:438; and `rid == _ended_resp_id` → clear turns.py:442 | 0-1 byte, never framed | **NO — invisible to both** (sub-frame) |
| 5 | `_flush_downlink` `dl_buf.clear()` turns.py:611 (close:111, listen_start:233, abort:245, barge_in:336, qwen_closed:651) | sub-frame residue in `dl_buf` | **NO — invisible to both** |
| 6 | `_flush_downlink` draining `dl_q` turns.py:613-618 | whole queued frames | yes via `flushed_frames` (reason-scoped) |
| 7 | **pacer send exception** turns.py:581-587 | one frame, already dequeued | **NO — no bucket** |
| 8 | **pacer cancelled during `send_bytes`** turns.py:582, 592-594 (reached from `_cancel_pacer` turns.py:634 on *every* barge-in/abort/close/listen_start) | one frame, already dequeued | **NO — no bucket** |
| 9 | cap rejection A.4.1 | bytes only | bytes yes; no frame involved |
| 10 | stale-rid guard turns.py:356-359, bad base64 turns.py:368-371 | whole deltas | outside "generated" (counters are incremented at turns.py:372) — must be stated as outside the generation, not silently unaccounted |
| 11 | `_on_qwen_event` has no exception containment (turns.py:264-310) | anything mid-dispatch | **NO — counters can desync** |

**Do the identities hold?** A.4.3's identity has exactly three RHS terms (`sent` + `flushed` + `still_stored`) and A.7 names exactly three reason-scoped flush counters (A.7:235-237). Paths 2, 7 and 8 therefore make **`frame closure residual = 0` false as specified** — and path 8 is not exotic: one barge-in while the pacer is awaiting `send_bytes` loses exactly one uncounted frame. Paths 4 and 5 lose media invisibly to *both* identities (they are bytes-but-never-frames, so the byte closure balances and the frame closure never sees them).

**Is the byte closure meaningful?** No, it is self-referential: `generated_pcm_bytes` and `accepted_pcm_bytes` would both be computed at turns.py:372-373, the same statement pair that counts `qwen_audio_delta_bytes`. An identity whose LHS and RHS are produced by the same code cannot detect a loss before that point. It needs an independent source (e.g. the base64-decoded length summed at the event boundary *before* the guards of turns.py:356-359, with the guard-dropped bytes in their own counted bucket).

**Cap domain — the decisive reading.** A.4.1 (A.4.1:131-136) says "*When the **1500th complete 960-byte frame** is formed*, mark `AUDIO_STORE_CAP_REACHED`" — that predicate counts **cumulative frames accepted per generation**, not store occupancy. This contradicts:

- A.2:71, which defines the stage as a **"generation-aware future-audio store"** (occupancy);
- A.4.5:172, which derives `MAX_FUTURE_AUDIO_MS = 30000 ms` — under A.4.1's predicate that is **max response audio duration**, not max backlog;
- A.2:82 ("The 30 s store is **not** client prebuffer") and the product-owner decision that the cap applies to **unsent backlog**, not total response duration.

Consequences under A.4.1's wording: any reply longer than 30 s is silently truncated from 30 s onward (counted only in `safety_truncated_pcm_bytes`), and the cap would essentially never bind in the normal case (the pacer drains at 50 fps, so occupancy at the 1500th formed frame is a few frames — `MAX_FUTURE_FRAMES` stops being a memory bound in the sense A.8 claims). Also, "`dl_buf` must be **empty** after the cap transition" (A.4.1:135) discards the in-flight partial residue of that delta; whether those bytes are added to `safety_truncated_pcm_bytes` is not stated, so the byte closure can fail at exactly the cap transition. See **B-1**.

### 5. Cancel latch (A.5)

**Sufficient for `cancels_per_generation <= 1`?** Yes *in principle*: the pre-await check-and-set (A.5:189-193) contains no `await`, so on a single-threaded event loop it is atomic against the barge-in/abort/cap interleavings that broke the current guard at turns.py:340-349 and turns.py:249-257. The existing paths that send an upstream cancel are exactly: barge-in (turns.py:342), abort (turns.py:251), and the new cap path. `close()` (turns.py:103-144) and `_on_qwen_closed` (turns.py:648-659) do **not** send `response.cancel` (they call `qwen.close()` / clean up locally), so they add no cancels.

**But the assertion is not verifiable.** (i) **Generation boundaries are undefined**: A.5 never says what a generation *is*, when it starts/ends, or which field is its identity. `self.diag.active_gen` is bumped by `mark_invalidated` (turns.py:332, 242, 229, 649), and a fresh generation carries a fresh latch, so two cancels can be emitted for one upstream response across a barge-in that creates a new generation — the latch does not prevent that. (ii) **`cancel_attempts` in A.7 is cumulative** (A.7:244), so no per-generation maximum can be derived from it; a monotone counter cannot exhibit a max-per-generation. `cancel_upstream_once` also has a *second*, post-latch gate ("already terminal → do not send", A.5:204) whose ordering relative to the latch is not stated for the case where the terminal check precedes the latch. See **M-3**.

### 6. Barge-in invariant (A.6)

**"Invalidate before the first await" — achievable?** Yes for the barge-in entry: `_on_qwen_event` performs only synchronous diag work before `await self._on_speech_started()` (turns.py:288), and inside `_on_speech_started` the invalidation at turns.py:332 precedes the first await at turns.py:334. So the ordering itself is already satisfied in the current structure; the requirement is a preservation requirement, not a change.

**Can A.7 back `BARGE_IN_SEQUENCE_INCOMPLETE = 0`?** **No.** A.7 (A.7:228-245) contains no such counter and no definition of the sequence's expected steps. A.6:222 itself notes the sequence is "only probabilistically true until containment is added" because `_on_qwen_event` has no exception containment (turns.py:264-310); A.7 adds no containment counter either. As a result A.13:302 is unverifiable. See **B-4** and **M-2** (the sentinel gap changes the sequence itself).

### 7. Client relocation (A.2 item 5, A.12)

**Is it impossible for the bridge to move backlog into Q1/Q2?** **No.** Given the 16 ms floor (see item 1/2), each pacer start or rebase delivers up to **+2 frames (40 ms)** and each sub-threshold catch-up up to **+3 frames (60 ms)** of excess over the client's 50 fps drain. These do not accumulate within one episode (the lead bound re-saturates at 20 ms), but the episode count is unbounded: `_ensure_pacer` (turns.py:503-506) starts a fresh pacer per response, and A.3 permits a rebase whenever lateness > 40 ms. So the maximum client-side contribution from the bridge is **not bounded by the design**; the bound the lead rule provides is on *lead within one epoch*, not on the integral of delivered frames. Q1 holds 64 packets = 1.28 s (`protocol_manager.py:24,42-44`) and Q2 holds 10.0 s (`audio_codec.py:26,68-70`; `audio_buffer.py:43-52`), so a repeated-episode excursion can fill Q1 and trigger silent drop-oldest at `protocol_manager.py:162-178`. A.2:82's "must continue to receive approximately realtime-paced audio only" is therefore an over-claim on the bridge side. See **M-5**.

**Does A.12 cover every metric needed to falsify the remaining hypotheses?** **No.** Present: Q1 depth/peak/dropped; Q2 depth/peak/dropped; whole-block zero-fill; partial zero-pad; callback cadence; decode errors; resampler counts; `clear_audio_queue` depth. Missing, each of which Agent B's audit (`r1f-agent-b-playout-audit.md` §B-8, §B-10, §C-14, §E-22) identifies as the only observable for a live hypothesis:

- `toc_null` — `audio_codec.py:382-384` returns without decoding on TOC parse failure (silent frame drop, no log, no counter);
- `dec_short` — decoded length vs `frame_size` (`audio_codec.py:395-398`) is never compared;
- PortAudio `output_underflow` / `output_overflow` **classification** — `audio_codec.py:207-212` only does `if status:` with a 2 s throttle, so underrun and overrun are indistinguishable;
- AEC `_far_dropped` — `aec_engine.py:210`, only DEBUG at close, and relevant because the AEC far/near delay assumption is a static 100 ms while the client FIFO depth varies.

Without these, `DECODE_LAYER` and `CLIENT_OR_OS_PLAYOUT_LAYER` remain unfalsifiable, which is exactly the gap A.12 exists to close. See **M-4**.

**Contradiction with Agent B?** A.12:292 explicitly defers Agent B's `_TTS_FIFO_MAX_S 10.0 → 0.20` recommendation, which is a legitimate choice *because* A.12 adds the `dropped`/depth observability that the smaller cap was meant to provide — no contradiction, provided A.12 is actually implemented (it is a prerequisite, not a gate assertion). Two parallel instrumentation designs now exist (A.12 vs Agent B §GATED_INSTRUMENTATION_DESIGN) with no stated designation; A.12 should either adopt Agent B's field list verbatim or state which supersedes which. See **m-8**.

### 8. Over-claim check (A.8)

No statement in Part A claims static/buzz is solved: A.1:49-51 keeps `STATIC_AUDIO_ROOT_CAUSE = UNPROVEN`, A.8:251-253 repeats the hedge, A.2:83 makes client telemetry a prerequisite, and A.12:292 defers the client cap change. **One over-claim exists**, and it concerns the pacer rather than static/buzz: A.1:61 ("the deficit the rev-2 pacer (A.3) is specified to remove at the *rate* level") is offered as a design-intent claim, but A.13:296-299 presents the three pacer assertions as *the* runtime certification of it. As shown in items 1, 2 and 7, those assertions cannot detect a 62.5 fps reading, cannot quantify a rebase, and are not backed by counters. Wording that could be read as "the pacer fix is validated" should be removed until the assertions are real. No other over-claim found.

### 9. Byte backstop (A.4.5)

`MAX_FUTURE_AUDIO_BYTES / MAX_FUTURE_FRAMES = 163840 / 1500 = 109.2267 B` allowed per frame. Measured (journals, recomputed): r1d mean 55.9 B / **max 79 B** / p50 60 / p95 73 (n=70); r1e mean 58.8 B / **max 108 B** / p50 61 / p95 73 (n=479); mock mean 61.5 / max 87 (n=363). A.14's mean-based headroom (109.2 / 58.8 = **1.86×**) is arithmetically correct but is the **wrong statistic**: "non-binding" requires the *per-frame maximum* to stay below the allowance. Against the observed worst case it is 109.2267 / 108 = **1.012**, i.e. a **1.1 % margin**, and even that holds only for these 479 frames of one response: 1500 × 108 = 162 000 ≤ 163 840 is true, but a per-frame size of 109.3 B (Opus VBR overshoot on a transient; the encoder is `bitrate = 24000`, audio.py:27-28) would trip the byte cap before the frame cap.

**Precedence:** not defined. A.4.1's cap rule is purely frame-based ("the 1500th complete frame"), A.4.5 calls the byte limit a "backstop", and A.13 asserts nothing about it. If the byte cap fires first, A.4.1's frame rule never fires, `MAX_FUTURE_FRAMES` stops being authoritative in the sense A.10:261 claims, and whether the truncated bytes are counted in `safety_truncated_pcm_bytes` is unstated. See **M-6**.

---

## DESIGN_REVIEW_BLOCKERS

**5**

### B-1 — The frame cap is defined on cumulative formed frames, which contradicts the store and the product-owner decision

*Claim.* A.4.1's predicate ("when the 1500th complete 960-byte frame is formed") counts cumulative accepted frames per generation, not store occupancy; that makes `MAX_FUTURE_FRAMES` a 30 s cap on **total response duration**, silently truncating every longer reply.

*Evidence.* `r1f-design-review.md:132` vs `:71` ("generation-aware future-audio store"), `:172` (`MAX_FUTURE_AUDIO_MS = 30000` derived from the cap), `:82` ("not client prebuffer"), `:135` ("`dl_buf` must be empty after the cap transition", which discards the in-flight residue of that delta without saying whether it enters `safety_truncated_pcm_bytes`). Product-owner statement: cap applies to unsent backlog, not total response duration. Today's framing loop consumes complete frames immediately (`turns.py:377-386`), so at the 1500th formed frame the store occupancy is a few frames while 30 s of response have been accepted.

*Remedy.* Define the cap on **store occupancy**: reject a new complete frame when `unsent_backlog_frames + 1 > MAX_FUTURE_FRAMES`, and restate A.4.1/A.4.5/A.10 accordingly (`MAX_FUTURE_AUDIO_MS` is then max backlog, not max duration). State explicitly that residue bytes of the rejected delta are added to `safety_truncated_pcm_bytes`, so A.4.2 holds across the transition. Add an assertion that `audio_store_peak_frames <= MAX_FUTURE_FRAMES` and that a response longer than 30 s does **not** truncate while the backlog stays under the cap.

*Exit criterion.* A.4.1 contains a single unambiguous occupancy predicate that a 60 s reply with a 3-frame backlog satisfies without any `safety_truncated_pcm_bytes` increment, and a 3 s reply from a stalled pacer does increment it.

### B-2 — The frame closure (A.4.3) is false: three frame-loss paths have no bucket, and the byte closure is self-referential

*Claim.* `encoded_full_frames + synthetic_tail_frames = sent_frames + flushed_frames + still_stored_frames` (A.4.3:149-153) cannot hold: frames leave the pipeline through paths that are none of `sent`, `flushed` (three reason-scoped counters only) or `still_stored`.

*Evidence.* (i) pacer send exception, frame already dequeued: `turns.py:581-587`; (ii) pacer cancelled during `send_bytes`, frame already dequeued: `turns.py:582` + `_cancel_pacer` `turns.py:634`, reached from `turns.py:334` (barge-in), `244` (abort), `108` (close), `230` (listen_start); (iii) encode failure, frame deleted at `turns.py:379` and skipped at `turns.py:385`; (iv) sub-frame residue cleared at `turns.py:438`, `442`, `611` — never becomes a frame, so it is invisible to the frame closure while the byte closure balances; (v) `_on_qwen_event` has no exception containment (`turns.py:264-310`). A.4.2's `generated_pcm_bytes` and `accepted_pcm_bytes` would both be counted at `turns.py:372-373`, the same point as `qwen_audio_delta_bytes` (`counters.py:19`), so the identity is self-referential and cannot detect a loss before that statement.

*Remedy.* Add explicit buckets and name them in A.7/A.13: `audio_send_failed_frames`, `audio_send_cancelled_frames`, `audio_encode_failed_frames`, `audio_residue_discarded_bytes`, `audio_guard_dropped_pcm_bytes`; make `flushed_frames` = barge-in + abort + close + send-failure + cancel-mid-send. Source `generated_pcm_bytes` independently, at the base64-decoded event boundary **before** the guards at `turns.py:356-359`, and count the guard-dropped bytes separately. Define the snapshot instant for the residual (generation quiescence).

*Exit criterion.* A.4.3 enumerates every removal point with a counter, the residual is evaluable from A.7 at a defined instant, and a forced `send_bytes` exception leaves residual = 0.

### B-3 — The rate bound is self-contradictory: `MIN_SEND_INTERVAL_MS = 16` < `MEDIA_FRAME_MS = 20` with `CATCH_UP_BURST = DISABLED`

*Claim.* Rules 3 + 6 admit two incompatible readings (50 fps vs 62.5 fps) and the "no catch-up burst" / "never flood the client" statements are false under the literal reading.

*Evidence.* A.3:98 (`MIN_SEND_INTERVAL_MS = 16`), A.3:94-95 (`MEDIA_FRAME_MS = 20`), A.3:99 (`CATCH_UP_BURST = DISABLED`), A.3:114 (rule 3 has no wait; "continue with `n := n + 1`"), A.3:116-117 (rule 5 "never ... flooding", rule 6 floor 16). Simulation of `t_n = max(t_{n−1} + 16, deadline_n − 20)` from a fresh epoch: 0, 16, 32, 48, 64, 80, then 20 ms → **75 fps instantaneous, +2 frames over the client's 50 fps**; with a 40 ms lateness catch-up, 15 sends at 16 ms (= 62.5 fps) before the lead bound saturates. Client drain is exactly 50 chunks/s (`stream_manager.py:64-72`).

*Remedy.* Set `MIN_SEND_INTERVAL_MS = MEDIA_FRAME_MS` (20) — or delete the constant — and state the pacer's wait explicitly: "sleep until `max(deadline_n − MAX_PACER_LEAD_MS, t_{n−1} + MEDIA_FRAME_MS)` before sending frame `n`". Under that rule the asymptotic and instantaneous rates are both ≤ 50 fps and `CATCH_UP_BURST = DISABLED` is true.

*Exit criterion.* A single stated wait expression from which ≤50 fps follows for every schedule, including immediately after a rebase and immediately after a pacer start, with `MIN_SEND_INTERVAL_MS >= MEDIA_FRAME_MS`.

### B-4 — A.13's assertion set is not backed by A.7's counter contract

*Claim.* Five of A.13's eight assertions have no counter in A.7, so the gate cannot be evaluated.

*Evidence.* A.13:296-305 vs A.7:228-245.
- `MAX_MEASURED_PACER_LEAD_FRAMES <= 1` (A.3:122): no lead counter; `pacer_behind_frames` (A.7:242) is the opposite sign.
- `MIN_SEND_INTERVAL_MS >= 16` (A.3:123): `MIN_SEND_INTERVAL_MS` is a constant; the assertion is vacuous, and no measured-interval counter exists.
- `CATCH_UP_BURST_COUNT = 0` (A.3:124): no counter and no definition of "burst".
- `cancels_per_generation <= 1` (A.5:201): only the cumulative `cancel_attempts` (A.7:244) exists.
- `BARGE_IN_SEQUENCE_INCOMPLETE = 0` (A.6:219): no counter.
- `frame closure residual = 0` (A.4.3): `audio_still_stored_frames` is listed among "cumulative counters" (A.7:226) although it must be a gauge sampled atomically with the cumulative terms.

*Remedy.* Extend A.7 with the missing fields (`pacer_lead_frames_max`, `pacer_min_interval_ms_observed`, `catch_up_frames_over_50fps`, `barge_in_sequence_incomplete`, `cancel_max_per_generation`, `audio_send_failed_frames`, `audio_send_cancelled_frames`, `audio_encode_failed_frames`, `pacer_rebase_max_lateness_ms`), label which are gauges/maxima vs cumulatives, and give each A.13 assertion exactly one counter.

*Exit criterion.* Every A.13 line names the A.7 field it is computed from, and no A.13 line asserts a constant against itself.

### B-5 — A.3 rule 4 (rebase) is unbounded, unquantified, and does not state frame disposition

*Claim.* The rebase is the design's only recovery action and is described as a "loss of media time", yet neither the amount discarded nor the fate of stored frames is defined or counted.

*Evidence.* A.3:115-116 (`if lateness_n > LATE_REBASE_THRESHOLD_MS: rebase ... n := 0`; "Rebase is the only recovery action, and it is a *loss* of media time, not a burst"). The trigger is 40 ms, so the discarded lateness is >40 ms and unbounded (any event-loop stall). A.7:241 supplies only `pacer_rebases` (a count). A.4.3 has no rebase bucket, so neither closure can see discarded frames; if instead frames are retained and delivered late, the deficit becomes unbounded added latency with no counter.

*Remedy.* State that store frames survive a rebase (delivered late), bound the lateness tolerated (beyond the bound, tear down the generation and flush its frames into a counted bucket), and add `pacer_rebase_max_lateness_ms` plus `audio_rebase_discarded_frames`, with the latter included in A.4.3.

*Exit criterion.* A.3 rule 4 defines frame disposition, a maximum discarded lateness, and the counter pair; a simulated 10 s loop stall produces a bounded, visible outcome rather than a bare `pacer_rebases += 1`.

---

## DESIGN_REVIEW_MAJORS

**6**

### M-1 — A.2 does not enumerate the removals; `LEGACY_DROP_OLDEST_CALLS = 0` cannot prove single-stage

*Evidence.* A.2:78-81 ("REPLACES ... not retained as a second stage"; "must be unreachable from normal R-1f audio delivery"). Symbols still present and reachable: `turns.py:77, 492, 498, 503, 508, 531`; `dl_q` reads at `turns.py:321-322, 337, 568-578, 616-621, 633`; `config.json:6`. Only `turns.py:495` and `turns.py:500` reach `_put_drop_oldest`, and `_drop_one_non_sentinel` is reached only when `q.full()` (`turns.py:534`) — so a never-full second queue yields 0 calls while still existing. `_put_drop_oldest`'s `QueueFull` fallback (`turns.py:547-555`) drops an audio frame without calling `_drop_one_non_sentinel`.

*Remedy.* List the deleted symbols and `DL_QUEUE_MAX`; require `_pacer` to read the store and no other queue; back single-stage with a construction-time assertion or a code-level test rather than with a drop counter; ensure the drop counter covers the `QueueFull` fallback too.

*Exit criterion.* A.2 names each removed symbol and states a check that fails if any second queue holds audio.

### M-2 — The end-of-response/sentinel stage is missing from the new pipeline, leaving pacer termination and TTS-stop undefined

*Evidence.* A.2:67-74 lists store → pacer → send only. `SENTINEL` (`turns.py:20`), `_enqueue_sentinel` (`turns.py:498`), the sentinel branches in `_pacer` (`turns.py:568-578`) and `_stop_pending` are what trigger `_stop_tts("pacer_finally")` and the transition to LISTENING (`turns.py:599-605`). A.6's barge-in sequence also depends on the stop path.

*Remedy.* Specify the generation-end marker in the new store (or its equivalent), and state how `_stop_tts` and the LISTENING transition are triggered when the store drains.

*Exit criterion.* A.2 contains the termination signal and its handler; A.6's sequence names the same steps.

### M-3 — Generation boundaries are undefined, so `cancels_per_generation <= 1` is not verifiable

*Evidence.* A.5:181-184 defines per-generation fields but never defines a generation. `self.diag.active_gen` is bumped at `turns.py:332, 242, 229, 649`; the latch is per-object, so a new generation after a barge-in can emit a second cancel for the same upstream response. A.7:244 supplies only the cumulative `cancel_attempts`.

*Remedy.* Define generation := one upstream response (bounded by `response.created` at `turns.py:293-300` and the terminal event at `turns.py:444-451`), and add `cancel_max_per_generation`.

*Exit criterion.* A generation's start/end and identity field are stated, and the assertion is computable per generation.

### M-4 — A.12 omits client-side silent-loss metrics required to falsify the remaining hypotheses

*Evidence.* A.12:271-290 lists depth/peak/dropped and zero-fill counts but not: `toc_null` (`audio_codec.py:382-384` returns silently), `dec_short` (`audio_codec.py:395-398` never compares decoded length to `frame_size`), PortAudio `output_underflow`/`output_overflow` classification (`audio_codec.py:207-212`, `if status:` with a 2 s throttle), AEC `_far_dropped` (`aec_engine.py:210`). These are the exact fields Agent B identified as the only observables for the decode-layer and CoreAudio hypotheses (`r1f-agent-b-playout-audit.md` §B-8, §B-10, §C-14, §E-22).

*Remedy.* Add the four metrics to A.12's list and state that Agent B's field set is adopted (or superseded field-by-field).

*Exit criterion.* Every hypothesis named in A.1/A.8 has at least one observable in A.12 that can distinguish it.

### M-5 — The claim that the bridge cannot move backlog into Q1/Q2 is not established

*Evidence.* Items 1/2/7: +2 frames per pacer start or rebase, +3 frames per sub-threshold catch-up, unbounded episode count (`_ensure_pacer` starts a pacer per response, `turns.py:503-506`). Q1 = 64 packets = 1.28 s (`protocol_manager.py:24,42-44`), Q2 = 10.0 s (`audio_codec.py:26,68-70`), client drop-oldest is silent (`protocol_manager.py:162-178`, `audio_buffer.py:43-52`). A.2:82 claims the client receives "approximately realtime-paced audio only".

*Remedy.* After B-3, state and assert the bound on the **integral** of sent frames vs consumed frames (e.g. `sent_frames_total − 50 × elapsed_s <= 1` in steady state, reset per generation), and make Q1/Q2 depth a gate-relevant observable (currently A.12 is default-OFF and not an assertion).

*Exit criterion.* A bounded, asserted excess over 50 fps whose maximum is quantified in ms and checked by a counter.

### M-6 — The byte backstop is justified with the wrong statistic and has no defined precedence

*Evidence.* A.4.5:173 calls 163 840 "non-binding"; A.14:317 justifies it as 163 840/1500 = 109.2 B vs measured **mean** 58.8 B = 1.86×. Observed **max** packet is 108 B (r1e, n=479; r1d max 79, mock max 87, recomputed from the journals), so the true margin is 109.227/108 = 1.012 (1.1 %). A.4.1's cap predicate is frame-only; A.10:261 calls the frame cap authoritative; A.13 asserts nothing about bytes.

*Remedy.* Replace the mean-based headroom with the max/p99.9 packet size, define precedence explicitly (frame cap wins; the byte cap may only ever fire as an emergency tear-down), and state which counter records a byte-cap truncation.

*Exit criterion.* The non-binding claim is proven against the worst observed frame size (or the byte cap is given precedence and a counter), with one sentence naming the winner.

---

## DESIGN_REVIEW_MINORS

**8**

### m-1 — Response-end residue of 0-1 bytes is dropped without accounting
*Evidence.* `turns.py:424` gates padding on `len(self.dl_buf) >= 2`; `turns.py:438` clears below that; `turns.py:442` clears when `rid == self._ended_resp_id`. A.4.4:156-166 describes padding for "a partial residue" without a lower bound.
*Remedy.* Pad any residue `0 < N < FRAME_BYTES`; state whether an `N == 0` case emits a tail frame at all.
*Exit criterion.* A.4.4 states the residue domain and the `N == 0` behaviour.

### m-2 — `audio_still_stored_frames` is labelled cumulative but must be a gauge
*Evidence.* A.7:226 ("Cumulative counters that must be exposed at minimum"), `:238`; A.4.3:153 uses it as a stock in the residual.
*Remedy.* Split A.7 into cumulative counters and gauges/maxima; sample the gauges atomically at generation quiescence.
*Exit criterion.* Each A.4.3 term is labelled as flow or stock with a defined read instant.

### m-3 — Pacer epoch initialization is undefined
*Evidence.* A.3:106 (`deadline_n = media_epoch + n * MEDIA_FRAME_MS`) never defines `media_epoch` or `n` at pacer open; `_ensure_pacer` (`turns.py:503-506`) starts a task per response with no epoch notion.
*Remedy.* State that `media_epoch` is set at pacer open (and at each rebase) to `now_monotonic()` with `n = 0`.
*Exit criterion.* The first deadline after each pacer start is defined.

### m-4 — `audio_flushed_*_frames` semantics vs `diag.on_flush` item counting
*Evidence.* `turns.py:619-621` counts items and sentinels from `dl_q`; A.7:235-237 names frames per reason.
*Remedy.* State that sentinels are excluded from the flush frame counters.
*Exit criterion.* The counter definition names its unit.

### m-5 — A.1's missing-block period is not derived from the measured deficit
*Evidence.* A.1:25 claims the derived period is ≈244-476 ms, computed from the table's 47.9/45.9 fps rows (A.1:58-59); A.1:61 states the *measured* deficit is 2.6-3.1 fps, which implies 50/3.1 ≈ 16.1 frames ≈ 323 ms to 50/2.6 ≈ 19.2 frames ≈ 385 ms.
*Remedy.* Re-derive the range from the measured deficit or mark the wider range as covering the table's assumed rates.
*Exit criterion.* One consistent derivation chain from the measurement to the period.

### m-6 — "Effective downlink bitrate" wording
*Evidence.* A.14:316 gives 2.79-3.07 kB/s ≈ 22.4-24.6 kbit/s, which is the per-frame media rate (mean packet / 20 ms: 55.9/0.02 = 2.795 kB/s; 58.8/0.02 = 2.94 kB/s), not a wall-clock rate (the journals' span rates are 1.66 kB/s). The Qwen PCM24 downlink is 48 kB/s raw.
*Remedy.* Label it "bridge→client Opus media rate (mean packet / 20 ms)".
*Exit criterion.* The label matches the derivation.

### m-7 — The domain of `MAX_FUTURE_AUDIO_BYTES` is unspecified
*Evidence.* A.4.5:173 lists it beside a frame cap that A.4.1 applies per generation; a store-byte cap and a generation-byte cap behave differently.
*Remedy.* State that it is a store byte cap, or fold it into M-6's precedence rule.
*Exit criterion.* Domain stated once.

### m-8 — Two instrumentation designs coexist (A.12 vs Agent B §GATED_INSTRUMENTATION_DESIGN) with no designation
*Evidence.* A.12:267-292 defines a list and explicitly supersedes only Agent B's `_TTS_FIFO_MAX_S` change; Agent B's gate env vars, field list and ~83-line plan are not referenced.
*Remedy.* Designate A.12 as normative and either adopt Agent B's field list or enumerate which of its fields are dropped.
*Exit criterion.* One normative field list, cross-referenced.

---

## VERDICT

```
DESIGN_REVIEW_BLOCKERS = 5
DESIGN_REVIEW_MAJORS   = 6
DESIGN_REVIEW_MINORS   = 8
DESIGN_REVIEW          = REVISE
```
