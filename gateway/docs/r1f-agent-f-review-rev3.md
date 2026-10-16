# R-1f Agent F re-review (rev 3)

Independent, adversarial. Inputs: `rtl-lab/r1f-design-review.md` (Part 0 + Part A rev 3), the read-only bridge/client sources, and the raw journals. No earlier review was read.

## Attack results

### 1. 60 s response — NOT-VERIFIED (not for the stated reason)
The **cap predicate itself is clean**: A.2's canonical `unsent_backlog_frames = queued + in_flight` and the occupancy-only test `unsent_backlog_frames + 1 <= 1500` do not accumulate per generation; A.9's `GenerationEnd` is explicitly excluded from the cap and from `audio_store_current_*` (A.9). So a 60 s response (3000 frames at 50 fps) with a backlog peak of 3 fires no transition and yields `safety_truncated_pcm_bytes = 0`. Test A as written passes.

What fails is the premise "peak ≈ 3". A.5's floor is `not_before = max(deadline_n, connection_last_audio_send_at + 20.0)` with `connection_last_audio_send_at := observed send-completion time` (A.5). Since a send is never instantaneous, the floor **always** binds: `s_{n-1} + T + 20 >= deadline_n + T > deadline_n` for any `T > 0`. Measured `T = t_send - t_intent` is p50 0.060 ms (mock), 0.065 ms (r1d), 0.084 ms (r1e), max 0.214 ms (`r1e_*_diag.json` → `send_intents`), and the wait primitive adds its own overshoot δ ≈ 0.98 ms (median inter-send gap 21.094 ms − T 0.06 ms for a requested 20 ms `asyncio.sleep`, `r1e_mock_sent_opus.jsonl`; same for 21.167/21.306 in r1d/r1e). Because the floor is charged from the previous *completion*, every frame's period is `20 + T + δ ≈ 21.1 ms` → **≈47.4 fps**, i.e. exactly the deficit A.1 claims to remove (2.6–3.1 frames/s, A.16). The ledger is cumulative: backlog grows ~2.6–3.1 frames/s, so a 5-minute response ends ~800–930 frames deep (no cap, but only ~40 % of the cap budget left) and a ~10-minute one caps out. Nothing in A.2/A.9 re-introduces cumulativity; A.5's floor does.

### 2. 1501-frame burst — VERIFIED (cap), subject to the in-flight definition
Stalled pacer, admission per A.2: frames 1..1500 admitted (`backlog + 1 <= 1500`), the 1501st refused → latch → `CONTROLLED_TAIL_TRUNCATION`; A.9 makes the refusal permanent for the generation ("no future audio is accepted"), so a later drain cannot re-open admission, and a missing latch would be caught by `cap_transitions_max_per_generation`. Expected reads: `cap_transitions_max_per_generation = 1`; `safety_truncated_pcm_bytes =` (bytes of the delta that would have completed frame 1501, after the last admissible frame) + all bytes of every later audio delta; no second transition reachable.
Caveat: `audio_store_peak_frames` is **not** uniquely determined by the spec — it is the *store* gauge, while the cap is checked on `queued + in_flight`. If the stalled pacer holds one popped frame, the store peaks at **1499**, not 1500 (see F-4). The bytes already sitting in `dl_buf` (< 960) when the cap fires are also unaddressed (see F-3).

### 3. Accounting escape — FAILED (three holes found)
Exit points tested against A.4.A/B/C:

| Exit point (source) | Bucket in A.4 | Result |
|---|---|---|
| stale-rid / no-current-response guard, `turns.py:356-359` | `guard_dropped_pcm_bytes` | OK — but A.4.A requires decoding *before* the guard, i.e. reordering vs `turns.py:367` (see M-5) |
| bad base64, `turns.py:366-371` | `bad_base64_events` (invalidates) | OK for a live generation; invalidates for a stale one (M-5) |
| encode failure, `turns.py:381-385` | `encode_failed_frames` | OK (`960 * encode_failed_frames` in A.4.B; excluded from both sides of A.4.C) |
| send exception, `turns.py:582-587` | `send_failed_frames` | OK for the frame lost; the **remaining store has no flush reason** on pacer exit (no `flushed_send_error_frames`); the run is INVALID, so residual≠0 cannot be *evaluated* at quiescence |
| cancel during `send_bytes`, `turns.py:582` + `:634` | `send_outcome_unknown_frames` (INVALID) | OK |
| cancel during the **pacing wait** (frame popped, not yet sent) | **none** | **HOLE — F-4** |
| `dl_buf.clear()` `turns.py:611` (close/listen_start/abort/barge_in/qwen_closed) | residue reasons | bytes OK (5 reasons, A.4.B) — but **frames flushed by `listen_start` (`:233`) and `qwen_closed` (`:651`) have no bucket in A.4.C** — **HOLE, F-2** |
| `dl_buf.clear()` `turns.py:438` / `:442` (response end / duplicate end) | tail rule only covers `0<N<960` at *normal* completion | 1-byte residue dropped by current code (`if len(dl_buf) >= 2`, `:424`); duplicate-end clear unclassified (m-7) |
| response-end residue `0<N<960` / `N==0` | synthetic tail / nothing | OK, no double count (`admitted` counted it once, `synthetic_tail_source_bytes` counts it once) |
| synthetic-tail *encode* failure, `turns.py:435` | none | **HOLE** — the padded tail is silently lost; `encode_failed_frames` is not incremented (that rule is for 960-byte source frames) and A.4.C never sees the frame, so A.15 #18 can PASS (M-6) |
| cap-transition residue (accepted before the cap, still in `dl_buf`) | none | **HOLE — F-3** |
| fatal-stall flush (A.6 case B) | `flushed_pacer_stall_frames` for frames; residue none | violates A.4.B's "No `dl_buf.clear()` may occur without reason-scoped residue accounting" — **F-2/F-3** |
| exception escaping `_on_qwen_event` (`turns.py:264-310`, no containment) | none | propagates to `qwen.py:296` → treated as unexpected upstream close → `_on_qwen_closed` → flush reason `qwen_closed` (no frame bucket) + `qwen_connect_errors` + reconnect (M-4) |

A.4.C's equation is therefore **false for two reasons named inside the design itself** (`listen_start`, upstream close, `A.3`/`A.14` enumerate both) and undefined for a third (pre-send cancellation). A.4.C also omits the byte-cap flush reason that A.11 requires.

### 4. Unknown send outcome — VERIFIED in model, one required code change
A.4.C models an abandoned `send_bytes` as `send_outcome_unknown_frames` and A.15 #6 makes any such run INVALID; correct, since the bytes may or may not be on the wire. The A.5 floor after an unknown attempt is safe: the abandonment is observed when `CancelledError` surfaces from `await self.ws.send_bytes(pkt)` (`turns.py:582`) or from the failure handler, i.e. at or after any transport write, so `last := observation` cannot be beaten by the next send (which must wait `+20 ms`). Gap: the current cancellation path (`turns.py:592-594`, `except CancelledError: raise`) performs **no** post-processing and the `finally` (`:599-608`) never touches any floor state — the design must mandate the floor update inside that handler, otherwise the next pacer reads a stale floor and may send < 20 ms after an abandoned write (m-4). Also undefined: a frame cancelled during the *pre-send* wait has a *known* outcome (nothing on the wire) yet no bucket (F-4).

### 5. Sub-20 ms sends — VERIFIED for the spacing floor; FAILED for the rate/`catch_up` definitions
No pacer start, generation boundary, rebase, stall recovery, synthetic tail or first frame of a response can beat the floor: every send is gated by the connection-wide `max(deadline_n, connection_last_audio_send_at + 20.0)` and the epoch init is explicitly subject to it (A.5). Rebase case A shifts `media_epoch` so `deadline_n = now`, leaving `deadline_{n+1} = now + 20` — no catch-up (A.6). Fatal-stall recovery and a first frame after a 10 s stall are ≥ 20 ms late anyway. The floor-update rule on failure/abandonment is conservative and safe (attack 4). Epoch initialisation is unspecified only in that `connection_last_audio_send_at`'s initial value is not stated (m-3).

But the floor is also the *pace-setter*, and that is the defect: with `MIN_SEND_INTERVAL_MS = MEDIA_FRAME_MS = 20.0` there is **no slack**, so any positive send duration (T ≥ 0.04 ms measured) or late wake (δ ≈ 0.98 ms measured for `asyncio.sleep(0.02)`) is converted by the floor into a permanent period inflation: `s_n = s_{n-1} + 20 + T + δ`. The two stated goals — "no two sends closer than 20 ms" and "50 frames/s on the media clock" — are simultaneously satisfiable only at exactly 20.000 ms with zero jitter and zero send time. This is why every spacing assertion passes while the pacer runs at 47.4 fps (F-1).

`wire_rate_excess_frames_max`: the run anchor (`anchor_t` = first send after ≥1000 ms of silence; `permitted(t) = 1 + floor((t-anchor_t)/20)`) cannot be gamed *because the floor exists* — with a 20 ms minimum, `excess(t) <= 0` always, so the `<= 1` tolerance only absorbs the initial-credit frame. It is airtight but weak: it can only detect too-fast, never too-slow. Two caveats: the anchor definition does not say what happens to a run in which the pacer restarts mid-generation with a fresh epoch (`media_epoch = now; n = 0`), which silently discards accrued phase (a deficit, so it never shows up as excess) and is not counted in `pacer_rebases`; and the metric is meaningless for a slow pacer.

`catch_up_frames_over_50fps`: **not provable as written**. A.5 says "sliding 1 s look-back window: `sent_in_window - 50`, accumulated as `max(0, …)`" but never fixes the window boundary or whether it is a max or a running sum. With an inclusive window `[t-1000, t]`, a *perfectly compliant* 50 fps pacer has 51 sends in every window → `51 - 50 = 1` at every send, so `catch_up_frames_over_50fps = 0` (A.15 #8) is unsatisfiable under the accumulating reading and equal to 1 under the max reading. Only the half-open window `(t-1000 ms, t]` yields 50 → 0 (M-1).

### 6. 10 s stall — VERIFIED in outline, one unclassified residue
`lateness = now - deadline_n ≈ 10 s > 250 ms` → A.6 case B: invalidate the generation, flush queued frames to `flushed_pacer_stall_frames`, `cancel_upstream_once` (A.8), exactly one TTS stop, clean state, `pacer_fatal_stalls += 1`. Bounded and visible, not a bare rebase. Connection floor afterwards is trivially satisfied (the stall is longer than 20 ms). `audio_rebase_discarded_frames` stays 0.
Not closed: the partial residue in `dl_buf` (0 < N < 960) at stall time has no bucket, and A.4.B's invariant forbids clearing `dl_buf` without reason-scoped accounting while A.6/A.11 name no residue reason → the "no frame silently discarded" claim holds for frames but not for the buffered bytes (F-2/F-3). `lateness` itself is never defined in A.6 (m-1).

### 7. One store — NOT-VERIFIED
Rev 3 does require removal (A.3 enumerates `self.dl_q` `turns.py:77`, `DL_QUEUE_MAX` `config/config.json:6`, `_enqueue_frame` `:492`, `_enqueue_sentinel` `:498`, `_drop_one_non_sentinel` `:508`, `_put_drop_oldest` `:531`, legacy drains `:321-322,337,568-578,616-621,633`) and keeps `_ensure_pacer` conditionally. That is necessary but not sufficient:
- the removal list is **incomplete**: `SENTINEL` (`turns.py:20`), `_stop_pending` (`:84`), `counters.audio_out_dropped` (`counters.py:26,56`) and the `dl_q.qsize()/maxsize` diag fields (`:321-322,337,533,555,559`) are still live state that can only exist if a second structure exists;
- the required "static/construction test" is **not implementable as written** — "fails if the R-1f connection builds a second audio queue" names no predicate, and `Connection` legitimately owns `uplink_q` (`turns.py:86`) and `dl_buf` (`:78`, an audio byte buffer);
- "exactly one audio holding structure" is not distinguished from `dl_buf` (which does hold admitted audio), so a test written from this text can pass while `dl_buf` and the store both exist. (M-7)

### 8. GenerationEnd — VERIFIED conditionally; counters not defined
Exactly one stop per path is achievable: normal completion (`seal` → one marker → one stop), cap truncation (A.9: consume/end with exactly one marker), barge-in/abort/fatal stall/close (immediate stop; the flushed marker's stop is suppressed by "a generation that has already emitted a stop must suppress the marker-driven stop"). A second *emission* is prevented by the existing latch `if not self.tts_active: return` (`turns.py:480-481`) plus the per-generation sealing; a second *call* is possible and benign, so the counter must count emissions, not calls (m-9).
Not evaluable as written: `end_markers_per_generation` / `tts_stops_per_generation` are listed as MAX/MIN observations with no stated aggregation domain (per-generation max vs sum over generations) and no attribution rule for a *connection-level* stop such as `close()` (`turns.py:113`) when the owning generation has already been tombstoned. With a 3-generation run each stopping once, the max reading gives 1 (PASS) and the sum reading gives 3 (FAIL). (M-2, m-9)

### 9. Cancel once — VERIFIED conditionally
A.8's latch is tested and set before any await, and A.7 stores it on the generation ≡ `response_id`, so the `diag.active_gen`-based double-cancel of rev 2 is gone. Walked: barge-in→abort (barge-in clears `current_resp_id`, `turns.py:346`, so abort resolves no live generation → no second cancel); cap→abort (latch already requested → ALREADY_REQUESTED); abort→barge-in (same); `close()` during a pending cancel (latch set first; the awaiting `response.cancel` completes or raises once); upstream terminal arriving between the latch and the await (one cancel sent to an already-terminal response; not a double cancel); a late `response.done` for a tombstoned generation (A.7 tombstone; `_on_response_end` never cancels — `turns.py:403-453` has no `send_cancel`). Condition: A.8 requires the generation to be resolved *by response id*; the current call sites gate on `self.current_resp_id` (`turns.py:249-255`, `:340-349`) and A.3's removal list does not enumerate those two sites as parts of the rewrite (m-5).

### 10. Evaluability of A.15 — NOT-VERIFIED in five places
Checked every row against A.14's kind and the domain:

| # | Status |
|---|---|
| 1 | OK (`audio_store_peak_frames` max-gauge) — but it is the store gauge, not the canonical backlog (m-6) |
| 2 | ambiguous domain (max vs sum) → M-2 |
| 3,4 | OK (all four fields exist; `still_buffered_pcm_bytes` is a quiescence-sampled gauge) |
| 5 | **not evaluable** — A.4.C's equation omits `listen_start`/upstream-close flush buckets and the pre-send-cancellation state → F-2/F-4 |
| 6 | OK |
| 7 | OK, provided `pacer_min_inter_send_ms_observed` is connection-wide (m-2) |
| 8 | `wire_rate_excess_frames_max <= 1` OK; `catch_up_frames_over_50fps = 0` not provable → M-1 |
| 9 | OK but vacuous as a rate check: a 47.4 fps pacer has `lead = 0` → F-1 |
| 10 | OK |
| 11 | OK |
| 12 | **not evaluable** — the static test is unspecified → M-7 |
| 13 | ambiguous domain → M-2 |
| 14 | **not evaluable** — A.10 names "defined expected step bits per barge-in" but no bit set or per-step counter exists in A.10/A.14 → M-8 |
| 15 | ambiguous domain + no attribution for connection-level stops → M-2/m-9 |
| 16 | structurally tautological (`byte_cap_failures = 0` cannot fail) → M-3 |
| 17 | evaluable, but the client measurement window/aggregation is undefined and the gate cannot see starvation → M-6 |
| 18 | OK |

`still_stored_frames` is a gauge and is readable at quiescence; its sampling instant is undefined only for a tombstoned generation whose upstream terminal never arrives (m-8). `cap_transitions_max_per_generation` is per-generation only if read as the max over generations; as written it could be read globally (M-2).

## DESIGN_REVIEW_BLOCKERS

4

**F-1 — A.5's send floor is the pace-setter, so the design reproduces the measured rate deficit it exists to remove, and no assertion can detect it.**
Evidence: A.5 updates `connection_last_audio_send_at` from the *observed send-completion* time, so `not_before_n = max(deadline_n, s_{n-1} + T + 20)`. Since `T > 0`, the floor always binds and `s_n = s_{n-1} + 20 + T + δ` — a permanent, cumulative period inflation. Measured `T = t_send - t_intent` p50 0.060/0.065/0.084 ms (`r1e_mock/r1d_real/r1e_real` `send_intents`) and δ ≈ 0.98 ms (median inter-send gap 21.094/21.167/21.306 ms for a requested 20 ms `asyncio.sleep`; `evidence/r1e_mock_sent_opus.jsonl`, `r1e_real_sent_opus.jsonl`, `r1d_real_sent_opus.jsonl`) → ≈47.4 fps, the same 2.6–3.1 frames/s deficit A.1 claims to remove; `turns.py:591` is the same mechanism. No A.15 field bounds the slow direction: #9 (`lead >= 0`), #8 (`excess <= 0`, `catch_up = 0`) and #7 (spacing) all pass at 47.4 fps, so the gate cannot distinguish "fixed" from "unchanged".
Required remedy: make the absolute deadline authoritative by giving the floor slack below the media period (e.g. `MIN_SEND_INTERVAL_MS <= MEDIA_FRAME_MS - max(T + wake_jitter)` ≈ 18–19 ms, already within the 1-frame tolerance granted by `wire_rate_excess_frames_max <= 1`), or implement the wait with explicit overshoot compensation; and add a positive rate assertion (`pacer_mean_inter_send_ms_observed <= 20.0 + eps`, and/or `sent_frames / (t_last - t_first) >= 49.5`).
Exit criterion: a compliant implementation provably sends at ~20.000 ms mean with zero cumulative drift, and the new assertion fails on a 47.4 fps pacer.

**F-2 — A.4.C's disposition domain is missing the flush reasons that A.4.B/A.3/A.14 already enumerate, so the frame closure cannot balance for `listen_start`, upstream close, fatal stall or the byte cap; and A.4.B's "no `dl_buf.clear()` without reason-scoped residue accounting" is unsatisfiable.**
Evidence: A.4.B/A.14 define five residue reasons (`bargein`, `abort`, `close`, `listen_start`, `upstream_closed`); A.4.C defines only four frame flush buckets (`bargein`, `abort`, `close`, `pacer_stall`) — `_flush_downlink("listen_start")` (`turns.py:233`) and `"qwen_closed"` (`turns.py:651`) discard queued frames with no bucket. A.6 case B and A.11 flush the store (and eventually `dl_buf`) but no residue reason exists for stall/byte-cap, while A.4.B forbids any unaccounted clear at `turns.py:611`. Additional unclassified frame loss: a failed synthetic-tail encode (`turns.py:435`) never reaches `encode_failed_frames` (that rule is scoped to 960-byte source frames) or any disposition bucket, so a lost tail can co-exist with a PASS under A.15 #18.
Required remedy: one reason vocabulary shared by all three domains (add `flushed_listen_start_frames`, `flushed_upstream_closed_frames`, `flushed_send_error_frames`, plus `residue_discarded_{cap,stall,byte_cap,send_error}_bytes` or a single `flushed_unplayed_frames{reason}` map), and a required change list covering every clear site (`turns.py:429,438,442,611`).
Exit criterion: for each of the eight flush reasons there is exactly one byte bucket and one frame bucket, and A.4.B's invariant holds at every `dl_buf.clear()` site.

**F-3 — The residue accepted into `dl_buf` before the cap/stall transition has no exit bucket: it is neither playable nor truncatable nor discardable, so those bytes escape classification and A.15 #4 can still read residual = 0.**
Evidence: A.2 rules 2–5 and A.9's "no future audio is accepted" stop admission at the cap but only forbid *newly accepted* partial residue; A.4.B's residue list has no cap/stall reason; counting the residue as `safety_truncated_pcm_bytes` would double-count it (its bytes are already in `admitted_pcm_bytes`, breaking A.4.A's closure). So the bytes either sit in `still_buffered_pcm_bytes` while the run passes #4 with media never played, or are cleared by an unrelated later flush (`residue_discarded_listen_start_bytes`) and misattributed. Same hole at A.6 case B and A.11.
Required remedy: define the cap/stall/cap-byte transition to flush the existing `dl_buf` residue into a reason-scoped counter (`residue_discarded_cap_bytes` etc.) and require the residue bytes not be counted as admitted until a complete frame is stored (or explicitly reclassify them from `admitted` to `safety_truncated` in the same step).
Exit criterion: a cap-truncated or stall-flushed generation has `still_buffered_pcm_bytes = 0` at quiescence, every source byte in exactly one of A.4.A's three classes, and every byte in exactly one A.4.B bucket.

**F-4 — `in_flight_frames`/`unsent_backlog_frames` are undefined for the state "popped from the single store, awaiting its send slot" — the normal barge-in instant — so the frame closure cannot balance on barge-in, or every barge-in run is declared INVALID.**
Evidence: the pacer's only long-lived await is the wait before `send_bytes` (`turns.py:582`; with A.5 the frame is popped, then `await until not_before`). A.4.C's only abandonment bucket is "pacer cancelled during `send_bytes`"; a frame cancelled during the pre-send wait has a *known* outcome (nothing on the wire) and lands in no bucket unless `in_flight_frames` is defined to include it. If the implementer instead routes it to `send_outcome_unknown_frames`, A.15 #6 makes every barge-in run INVALID, contradicting A.10's expected complete barge-in. The same definition also decides A.2's test-B peak (1499 vs 1500 store frames) and whether a whole class of frames escapes the cap domain.
Required remedy: define `in_flight_frames` = every frame removed from the single store and not yet assigned a disposition (including the pre-send wait), require all cancellation paths to resolve it into the reason-scoped flush bucket before quiescence, and state explicitly that a frame cancelled before the transport call is known-unsent, not outcome-unknown.
Exit criterion: A.4.C balances for a barge-in that lands during the pacing wait, with `send_outcome_unknown_frames = 0`, and A.2 test B's peak is uniquely determined.

## DESIGN_REVIEW_MAJORS

8

**M-1 — `catch_up_frames_over_50fps = 0` is not provable as defined (window convention and max-vs-sum unspecified).**
A.5: "sliding 1 s look-back window: `sent_in_window - 50`, accumulated as `max(0, …)`". With an inclusive window `[t-1000 ms, t]`, a compliant 50 fps pacer has 51 sends in the window → the term is 1 at every send (unsatisfiable as a sum, 1 as a max); only the half-open window `(t-1000 ms, t]` yields 50 → 0. Remedy: pin the window to half-open and state max-vs-sum. Exit: a simulated compliant pacer yields exactly 0.

**M-2 — Four "per_generation" fields have no aggregation domain, so assertions #2/#13/#15 flip with the reading.**
`cap_transitions_max_per_generation`, `cancel_max_per_generation`, `end_markers_per_generation`, `tts_stops_per_generation` are listed under MAX/MIN OBSERVATIONS (A.14) without saying "max over generations in the run" vs "sum". A 3-generation run with one marker each: max = 1 (PASS), sum = 3 (FAIL). Remedy: define each as the max over generations of that generation's count, and add the attribution rule for connection-level stops (`close()`, `turns.py:113`) against a tombstoned generation. Exit: each assertion has exactly one reading.

**M-3 — A.11's 2 MiB byte ceiling cannot bind before the 1500-frame cap, so rev 3 reinstates the "non-binding" characterisation it explicitly withdrew, and A.15 #16 is tautological.**
With the frame cap authoritative and packets bounded by 1275 B (Opus 20 ms at the 510 kbit/s ceiling; the encoder is pinned to `bitrate = 24000`, `audio.py:28`, ≈ 60 B), 1500 × 1275 = 1,912,500 B < 2,097,152 B, so `AUDIO_STORE_BYTE_CAP_REACHED` is unreachable, `byte_cap_failures` is structurally 0, and the required behaviour (byte_cap flush, exactly one stop) is untestable. Remedy: lower the byte ceiling below 1500 × the configured max packet so it can bind, or state plainly that it is a non-binding backstop for a pathological encoder and delete the dead branch and assertion.

**M-4 — A.4's exception-containment requirement has no observable, and a containment failure is recorded as an upstream failure.**
`_on_qwen_event` (`turns.py:264-310`) has no containment; an exception propagates to the reader (`qwen.py:296`), which treats it as an unexpected close (`qwen.py:298-321`) → `_on_qwen_closed` (`turns.py:648`) → flush reason `qwen_closed`, `qwen_connect_errors += 1`, reconnect. A local accounting bug is thus reported as an upstream fault, and only the barge-in path has a named consequence (`barge_in_sequence_incomplete`). Remedy: per-branch containment inside `_on_qwen_event`, a `qwen_dispatch_errors{event_type}` counter, and a rule that any nonzero value invalidates the run.

**M-5 — A.4.A's orphan/bad-base64 rules conflict with the bridge's deliberate tolerance of id-less events and can make runs un-invalidatable in practice.**
`_on_response_end` explicitly applies an id-less end event to the current response (`turns.py:410-418`), while an id-less `response.audio.delta` returns `rid = None` from `_resp_id` (`turns.py:31-38,356`); under A.4.A those bytes are "not mappable to a known response/generation" → `orphan_pcm_bytes > 0` → run INVALID though a current response exists. Because A.4.A mandates decoding before the guards (`turns.py:356-359` precede the decode at `:367`), a bad-base64 delta for a *stale* response also increments `bad_base64_events` and invalidates the run. Remedy: specify the mapping rule (id-less delta → current response, or a dedicated `idless_delta_bytes` bucket) and scope bad-base64 invalidation to deltas belonging to a live generation.

**M-6 — The synthetic-tail encode failure is invisible.**
`turns.py:435` catches the exception and logs; the padded tail frame is lost, `synthetic_tail_frames` never increments, and `encode_failed_frames` is scoped by A.4.B to 960-byte source frames, so nothing on either side of A.4.B/A.4.C records the loss and A.15 #18 can still PASS. Remedy: add `synthetic_tail_encode_failures` (counted in the normal-completion PASS set) and require the residue bytes to be reclassified as truncated/zero-padded on failure.

**M-7 — A.3's single-store proof is not implementable and its removal list is incomplete.**
The "static/construction test" has no predicate: `Connection` legitimately owns `uplink_q` (`turns.py:86`) and `dl_buf` (`turns.py:78`, which holds admitted audio), so "a second audio queue" is undefined. Unlisted live legacy state: `SENTINEL` (`turns.py:20`), `_stop_pending` (`:84`), `counters.audio_out_dropped` (`counters.py:26,56`), `dl_q.qsize()/maxsize` uses (`turns.py:321-322,337,533,555,559`). Remedy: define the predicate as a unit test that instantiates `Connection` and asserts exactly one object holding ≥1 encoded audio frame between encode and `send_bytes` plus the absence of `dl_q`, and complete the removal list. Exit: the test's pass/fail follows from the document alone.

**M-8 — A.10's barge-in step bits are never defined.**
"with defined expected step bits per barge-in" appears in A.10, but no bit set, step enumeration or per-step counter exists in A.10 or A.14, so `barge_in_sequence_incomplete = 0` (A.15 #14) is not evaluable and cannot be implemented. Remedy: enumerate the mandatory local steps (cancel local pacer, flush store, TTS stop, invalidate generation) with per-step SUCCEEDED / NOT_APPLICABLE / FAILED counters and make `barge_in_sequence_incomplete` their derived predicate.

Also over-claiming: A.1's "removes the measured rate deficit" (unachieved under A.5 — F-1) and A.13's relocation gate, which requires only client *drop* counters (`incoming_queue_dropped_packets`, `pcm_fifo_dropped_samples`, A.15 #17) while the measured deficit makes the client *starve*; the client's zero-fill observables (`whole_block_zero_fill_count`, `partial_zero_pad_samples`, A.12) are collected but not required as evidence, so a 47.4 fps run with an underrun-buzzing client passes unchanged. Remedy: require the client underrun/zero-fill fields per response as reported evidence, or state explicitly that A.13 does not cover starvation.

## DESIGN_REVIEW_MINORS

10

- m-1 — A.6 uses `lateness` in both case headers but never defines it (presumably `now - deadline_n`); A.15 #10 depends on it. State the formula.
- m-2 — `pacer_min_inter_send_ms_observed` (A.5/A.13) must be defined **connection-wide** across generations, pacer restarts and rebases; as written it could be read per pacer and would miss a cross-boundary violation.
- m-3 — A.5 does not state the initial value of `connection_last_audio_send_at` (the first audio send of the process must not be delayed).
- m-4 — A.5 requires a floor update on a failed/abandoned attempt, but the current cancellation path (`turns.py:592-594`) re-raises before any post-processing and the `finally` (`:599-608`) never updates floor state; mandate the update inside that handler.
- m-5 — A.5/A.8 do not require single-pacer exclusivity or an atomic read-then-reserve of the floor; `_ensure_pacer` (`turns.py:503-506`) with an await inside the pacer's `finally` (`:603`) admits a brief two-pacer window (harmless today because the old pacer has left its loop, but the invariant must be stated). A.3's rewrite list also omits the two `current_resp_id`-gated `send_cancel` sites (`:249-255`, `:340-349`).
- m-6 — `audio_store_peak_frames` is a proxy: the canonical `unsent_backlog_frames` (A.2) has no observable, so a failure to count in-flight frames is invisible to A.15 #1.
- m-7 — A.4.B requires padding for any `0 < N < 960`, but the current code drops a 1-byte residue (`if len(self.dl_buf) >= 2`, `turns.py:424`) and clears without accounting on a duplicate end (`:442`); list these as required changes.
- m-8 — A.14's gauges are "sampled atomically at generation quiescence", but no sampling instant is defined for a tombstoned generation whose upstream terminal never arrives.
- m-9 — TTS-stop/marker counters must count **emissions**: the latch `if not self.tts_active: return` (`turns.py:480-481`) makes duplicate calls no-ops, so a call-counting counter fails A.15 #15 on benign duplicates.
- m-10 — A.4.A moves source-byte counting to the decoded boundary while `counters.qwen_audio_delta_bytes` remains post-guard (`turns.py:372`); state whether the `/health` field is retained or renamed so two contradictory byte counters cannot coexist. Also scope `bad_base64_events`'s invalidation (run vs generation) and fix the typo-level imprecision that `catch_up_frames_over_50fps` is described as "accumulated" and as a "max" in the same sentence.

## VERDICT

DESIGN_REVIEW_BLOCKERS = 4
DESIGN_REVIEW_MAJORS   = 8
DESIGN_REVIEW_MINORS   = 10
DESIGN_REVIEW          = REVISE



