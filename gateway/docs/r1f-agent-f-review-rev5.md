# R-1f Agent F re-review (rev 5)

Fresh, independent, adversarial. Reviewed artifact: `rtl-lab/r1f-design-review.md` (Part 0 + Part A rev 5).
Role: Agent F (rev-5). Not the author. No earlier-revision review of *this* round exists; `r1f-agent-f-review-rev4.md`
was read only to recover the B1 / M-A..M-G / min-1..min-9 statements for the closure audit. Not read:
`r1f-agent-f-review-rev3.md`, `r1f-agent-f-review.md` (rev 2).

Nothing was written except this report. No code/config/container was touched. All numeric recomputation and all
simulation were done with heredoc Python (`<user-home>/.workbuddy/binaries/python/versions/3.13.12/bin/python3`)
against the raw evidence; no package was installed.

Evidence actually used: `evidence/r1e_mock_diag.json`, `r1d_real_diag.json`, `r1e_real_diag.json`
(`send_intents`), `r1e_mock_sent_opus.jsonl`, `r1d_real_sent_opus.jsonl`, `r1e_real_sent_opus.jsonl`; sources
`app/turns.py`, `app/audio.py`, `app/counters.py`, `app/diag.py`, `app/main.py`, `app/http.py`, `config/config.json`;
client `src/core/protocol_manager.py`, `src/audio_codecs/{audio_codec,audio_buffer,stream_manager}.py`,
`src/audio_processing/aec_engine.py`.

---

## 1. Recomputed numbers (independent, from raw evidence)

### (a) `T = t_send - t_intent` (ms), `send_intents`

| bundle | n | p50 | p95 (linear) | p95 (nearest-rank) | p95 (lower-rank, `int(0.95(n-1))`) | max | mean |
|---|---|---|---|---|---|---|---|
| `r1e_mock_diag.json` | 200 | 0.0600 | 0.0951 | 0.0950 | 0.0960 | 0.1240 | 0.0636 |
| `r1d_real_diag.json` | 70 | 0.0645 | **0.1410** | **0.1450** | **0.1360** | 0.1980 | 0.0768 |
| `r1e_real_diag.json` | 200 | 0.0835 | 0.1783 | 0.1780 | 0.1840 | 0.2140 | 0.0923 |

A.16 prints `0.060 / 0.095 / 0.124`, `0.0645 / 0.136 / 0.198`, `0.0835 / 0.178 / 0.214`. The r1d `0.136` is the
lower-rank value at index 65 (`sorted[63:68] = 0.116, 0.132, 0.136, 0.145, 0.158`). **A.16's parenthetical is wrong**:
it calls `0.141` the "nearest-rank" value, but `0.141` is the *linear-interpolation* value and nearest-rank is `0.145`
(see MINOR mi-2).

### (b) Same-`pacer_task_id` consecutive `t_send` gaps (journals)

| journal | rows | pacers | gaps n | p50 (ms) | p95 (ms) | min (ms) | max (ms) | fps = 1000/p50 |
|---|---|---|---|---|---|---|---|---|
| `r1e_mock_sent_opus.jsonl` | 363 | 1 | 362 | 21.0939 | 22.3177 | 20.3929 | 83.0900 | **47.41** |
| `r1d_real_sent_opus.jsonl` | 70 | 3 | 67 | 21.1627 | 36.6202 | 20.3417 | 47.9337 | **47.25** |
| `r1e_real_sent_opus.jsonl` | 479 | 2 | 477 | 21.3062 | 32.1029 | 20.3604 | 80.4597 | **46.94** |

A.16's `21.0939 / 21.1627 / 21.3062` and `47.41 / 47.25 / 46.93` reproduce exactly. (Frame_seq resets per
`response.created` — `diag.py:187` — so r1d's 70 rows span fs 1..30 across 3 generations; frame_seq is **not** a
connection-unique key: see mi-3.)

### (c) Opus packet size (journals)

| journal | mean (B) | p50 | p95 | max | min |
|---|---|---|---|---|---|
| mock | 61.47 | 62 | 67 | 87 | 49 |
| r1d | 55.87 | 60 | 72.5 | 79 | 21 |
| r1e | 58.76 | 61 | 73 | **108** | 3 |

A.16's `55.9 / 58.8 / 61.5 B`, `60-61 / 73 / 79-108` and mock `max 87` reproduce.

### (d) Wake overshoot `delta = gap - 20 - T`

Three Methods (T is only available for the last 200 `send_intents` in the mock/r1e bundles — `diag.py:535` keeps
`[-200:]` — so the "joined" method is only valid where the fs ranges overlap):

| method | mock | r1d | r1e |
|---|---|---|---|
| mean, `gap - 20 - mean(T)` | **1.3857** | **3.3086** | **2.4710** |
| mean, `gap - 20` (T ignored) | 1.4494 | 3.4012 | 2.5632 |
| mean, per-frame joined `gap - 20 - T(later)` (valid subset) | 1.2003 (n=200, quiet tail) | 3.2980 (n=67) | 1.8755 (n=239) |
| fraction `> 2 ms`, `gap - 20 - mean(T)` | 7.5 % | 20.9 % | 15.1 % |
| fraction `> 2 ms`, `gap - 20` | 8.0 % | 23.9 % | 16.1 % |
| fraction `> 5 ms`, `gap - 20` | 1.9 % | 14.9 % | 8.2 % |

A.16 claims means `1.387 / 3.324 / 2.490` and `delta>2ms` fractions `7.5 / 22.4 / 15.1 %`. My most consistent single
method gives `1.386 / 3.31 / 2.47` and `7.5 / 20.9 / 15.1 %`; the joined method gives `22.4 %` for r1d but a lower
mean. **The qualitative claim is confirmed and is the load-bearing one**: `E[delta] ~ 3.3 ms` (r1d) and `~ 2.5 ms`
(r1e) both exceed the rev-4 2 ms slack, and `E[delta] < 5 ms` in all three (margin 1.6 / 1.7 / 2.5 ms). The exact
3-dp means are not reproducible by any method stated in the document ("steady gaps" is undefined) — MINOR mi-3.

### (e) Pacer resampling simulation (my own, deadline clock + connection floor + A.6 rebase)

Model: `deadline_n = epoch + 20n`; `not_before = max(deadline_n, t_{n-1}+MIN)`; `t_n = not_before + j_n` with `j_n`
resampled (with replacement) from the measured per-interval overshoot envelope; `40 ms < lateness <= 250 ms`
re-phases the epoch (`WALL_CLOCK_PHASE_RESET`); `lateness > 250 ms` is a fatal stall. 30 000 frames, mean over the
run; anchor excess uses `permitted(t) = 1 + floor((t-anchor)/20)`; catch-up uses the half-open sliding window
`(t-1000 ms, t]`.

| envelope | MIN=18 (slack 2, rev-4) | MIN=15 (slack 5, rev-5) | MIN=19.5 (slack 0.5) |
|---|---|---|---|
| mock | 20.0005 ms (49.99 fps) | 20.1182 ms (49.71 fps) | 20.9157 ms (47.81 fps) |
| r1d | **21.4700 ms (46.58 fps)** | 20.0961 ms (49.76 fps) | 22.9617 ms (43.55 fps) |
| r1e | **20.6055 ms (48.53 fps)** | 20.1403 ms (49.65 fps) | 22.0692 ms (45.31 fps) |

Design claims (A.16): slack 2 → `20.0000 / 21.4830 / 20.4587`; slack 5 → `20.0000 / 20.0023 / 20.0003`.
The **slack-2 numbers reproduce** (`21.47 vs 21.48`; `20.61 vs 20.46`) → M-A-ext's core claim (2 ms slack sags on
the two real envelopes, 5 ms restores the rate) is **confirmed**. The slack-5 numbers do **not** reproduce unless the
mandated A.6 rebase is deleted: with the rebase present the rate is ~`20.10-20.15 ms` (49.6-49.8 fps, still under
row 7b's 20.5 gate). Hand-checked sanity: the sim returns exactly `20.0000` for every envelope with MIN=15 and no
rebase, matching the lead's model. See MINOR mi-10.

### (f) Invariant / gate checks from the same simulation (MIN=15, rebase on)

| check | mock | r1d | r1e |
|---|---|---|---|
| min inter-send interval (ms) | 15.363 | 15.342 | 15.360 |
| `min(t_attempt - deadline)` (>= 0 expected) | 0.393 | 0.342 | 0.360 |
| `wire_rate_excess_frames_max` | **1** | **1** | **1** |
| `catch_up_frames_over_50fps` (max over sends, half-open) | **2** | **3** | **3** |
| `pacer_floor_bind_count` regime | frequent | frequent | frequent |
| rebases / 30 000 frames | 82 | 62 | 89 |

**The absolute-deadline invariant holds** (`t_attempt - deadline >= 0` always; `wire_rate_excess <= 1` for MIN in
{15, 18}; 0 for MIN=19.5) — confirmed for clock-dominant, floor-bound recovery, and rebase re-phasing. But
**`catch_up_frames_over_50fps` is NOT 0 for a compliant pacer** — see BLOCKER B1.

Even a benign synthetic envelope `delta ~ N(1.0, 0.4)` (floor essentially never binds) yields `catch_up = 1`: the
mechanism is analytic — with the half-open window `(t-1000, t]`, frame `n-50` is inside the window iff
`delta_{n-50} > delta_n`, which happens with probability ~0.5 per send. The design's claim "a compliant 50 fps pacer
has exactly 50 sends in every such window" holds only for a perfectly periodic pacer.

### (g) Row 7b robustness (false-fail rates, resampled envelopes)

`pacer_mean_inter_send_ms_observed` with `frames_in_run >= 250` (M-B fix): 4 000 simulated 250-frame compliant runs
with 5 % 6-18 ms hiccups → **0.00 %** exceed 20.5 (p50 20.0005, p95 20.0415, max 20.1216). **M-B is genuinely fixed.**

`pacer_wake_overshoot_mean_ms_observed` (the M-A-ext field, **no** minimum-run constraint):

| run length | mock | r1d | r1e |
|---|---|---|---|
| 250 (long) | 0.0 % | **6.3 %** | 0.0 % |
| 30 | 0.5 % | 27.4 % | 9.2 % |
| 10 | 2.8 % | 31.7 % | 13.3 % |
| 5 | 2.5 % | 34.7 % | 18.6 % |
| 3 | 2.5 % | 28.3 % | 19.0 % |
| 2 | 2.5 % | 27.9 % | 14.7 % |
| mixed session (runs 2,3,4,6,250) | 10.1 % | **77.4 %** | **52.6 %** |

(P shown is `P(mean overshoot > 4.0)`; the gate is `<= 4.0`.) See MAJOR MA-1.

### (h) Byte-ceiling arithmetic (A.11) — recomputed

`307200/1500 = 204.8 B/frame`; `204.8/108 = 1.896x`; `240*1275 = 306000 <= 307200 < 307275 = 241*1275` (fires at
the 241st frame, before the 1500-frame cap); `1500*108 = 162000 < 307200`. Correct.

---

## 2. Attack results

### Attack 1 — B1 implementation ambiguity: reading-dependent counter attribution, closures still hold

Walked both cap paths.

*Frame cap (A.2, pre-encode refusal).* Bytes are appended to `dl_buf`, a frame completes, and the admission check
runs **before** `enc24.encode`. When refused, the candidate is never encoded, so it appears in no A.4.C term; its
960 source bytes plus the sub-frame residue are discarded as `residue_discarded_cap_bytes += len(dl_buf)` and appear
in A.4.B. Numeric check (test B): `admitted = 1500*960 + 960`, `encoded_full_frames = 1500`,
`residue_discarded_cap = 960` → A.4.B balances (`1501*960 = 1500*960 + 960`); A.4.C balances
(`1500 = still_stored 1500`). **Residual 0.** A.2 rule 2 ("do not append blindly; accept only enough bytes to
complete/store that frame") vs the B1 sentence ("all bytes then in `dl_buf` … the whole remaining buffer content")
leaves the *attribution* non-unique when one delta brings several complete frames: under "append whole delta" the
extra frames' bytes become `residue_discarded_cap_bytes` (inside `admitted_pcm_bytes`); under "append frame by
frame" they become `safety_truncated_pcm_bytes` (rule 4). Both close both equations, but a given byte lands in
different counters depending on the implementation → MINOR mi-5, **not a blocker**.

*Byte cap (A.11, post-encode).* Packet size is unknowable before encode, so the decision is post-encode; the
triggering packet is discarded into `flushed_byte_cap_frames`, counted once in `encoded_full_frames` and once in
that bucket; the remaining store → `flushed_byte_cap_frames`; `dl_buf` residue → `residue_discarded_byte_cap_bytes`.
Test C numeric check: `encoded_full = 241 = flushed_byte_cap 241`, residue term separate → A.4.B and A.4.C residual
0. **B1's two mandated paths are closed.**

*Interaction with A.2 rule 2 / A.4.A.* The refused candidate's bytes are in `admitted_pcm_bytes` (A.2 rule 3), which
is consistent with A.4.A's LIVE branch ("admitted or safety_truncated"). No double classification found in the
cap-while-delta-in-flight combination: the discarded `dl_buf` bytes (already `admitted`) and the *later* delta bytes
(`safety_truncated`) are disjoint by construction. No new double count / leak bucket found beyond the ambiguity
above.

*One residual text conflict.* A.3 invariant 2 states `len(dl_buf) < 960` "after each delta-processing step" **and**
"residue never constitutes a complete frame", but A.2/B1 explicitly place the complete refused candidate (960 B) in
`dl_buf` at the transition instant. The first clause is saved by "after each step" (the step ends with
`dl_buf == 0`); the second clause is literally false at the cap → MINOR mi-4.

### Attack 2 — Drift condition, rebase, restart, stall: invariant holds, but the catch-up gate is broken

*Absolute-deadline invariant.* Verified in simulation for clock-dominant, floor-bound recovery (MIN=15 and 18),
rebase re-phasing (62-89 rebases per 30 000 frames), and a 200 ms stall: `t_attempt >= deadline_n` always
(`min(t-deadline) = 0.34-0.39 ms`), and `wire_rate_excess_frames_max = 1` for every slack tested. The +1 tolerance
absorbs only the initial-credit frame, exactly as A.5 claims. **This part of M-A-ext is confirmed.**

*Drift condition.* Confirmed: with `E[j] > slack` the floor binds persistently and lateness creeps
(`L_n = L_{n-1} - slack + j_n`), the rate sags toward `MIN + E[j]` (MIN=18, E=3.3 → 21.47; MIN=19.5 → 22.96), and
with `E[j] < slack` the clock dominates and the mean is 20.00. The threshold behaviour is real.

*Recovery / catch-up.* The rebase (A.6) caps lateness at 40 ms, so non-rebase recovery is short; but **floor-bound
recovery sends frames at `MIN + j` (< 20 ms)**, so any 1000 ms sliding window can hold 51-53 sends. The design's
`catch_up_frames_over_50fps = 0` assertion is therefore unsatisfiable → BLOCKER B1.

*Rebase-induced deficit.* With the mandated rebase present, the mean over the measured envelopes is
20.10-20.15 ms (49.6-49.8 fps), not the 20.000-20.002 the design prints; each rebase re-anchors the phase and
throws away up to 40 ms. A.5/A.1's "restores the 50 fps media rate" and "mean stays 20.000 ms" are therefore
overstated by ~0.5 % (still inside row 7b). MINOR mi-10.

### Attack 3 — Row 7b evaluability / robustness: the new field has no minimum-run constraint

`pacer_wake_overshoot_mean_ms_observed` is defined "max over active runs of the mean of
`max(0, t_attempt_n − not_before_n)` over non-rebase intervals" (A.5) with **no `frames_in_run >= 250` qualifier**,
while its sibling `pacer_mean_inter_send_ms_observed` *does* carry the qualifier (A.5/A.14). A.15 row 7b then gates
`<= 4.0 ms`. Consequences: (i) the sampling domains of the two fields in the same assertion differ; (ii) the gate
false-fails on short runs (table (g)): r1d 27-35 % for realistic short utterances, 77 % for a mixed session, and
even 6.3 % for a 250-frame run (the r1d envelope is heavy-tailed, so the 250-sample mean itself has ~0.4 ms sd).
`pacer_wake_overshoot_mean_ms_observed` is also absent from A.12/A.13 `Required bridge fields` — only row 7b names
it, so it is a gate-only observable. MAJOR MA-1.

### Attack 4 — A.4.C lifecycle (ten transitions): all frames/bytes bucketed

| path | frame | bytes/residue | verdict |
|---|---|---|---|
| `cap` | candidate never encoded (no term needed) | `residue_discarded_cap_bytes += len(dl_buf)` | OK |
| `byte_cap` | triggering packet + remaining store → `flushed_byte_cap_frames` | `residue_discarded_byte_cap_bytes` | OK; trigger packet is never in-flight, so no `send_failed` ambiguity |
| `pacer_stall` | head `PRE_SEND_WAIT` → `flushed_pacer_stall_frames`; head `SENDING` → `send_outcome_unknown_frames` (INVALID); queued → `flushed_pacer_stall_frames` | `residue_discarded_stall_bytes` | OK (M-E fix present) |
| `send_error` | failed frame → `send_failed_frames`; store → `flushed_send_error_frames` | `residue_discarded_send_error_bytes` | OK |
| `barge_in` / `abort` / `close` / `listen_start` / `upstream_closed` | in-flight (pre-send wait) → `flushed_<reason>_frames`; store → same | `residue_discarded_<reason>_bytes` | OK |
| `dup_end` | none (no frame) | asserts `len(dl_buf)==0` else `accounting_fault_events` | OK |
| cap instant with an already-popped in-flight frame | frame unaffected, drains; counted in the 1500 backlog | — | OK |
| `listen_start` landing in `SENDING` | → `send_outcome_unknown_frames` → INVALID (A.4.C general rule). Note A.13/min-5 declares only close/abort | — | OK / MINOR scope note |

No unbucketed frame or byte found. One definitional gap: **A.4.C's quiescence definition does not require `dl_buf`
empty**, so `still_buffered_pcm_bytes` may be nonzero at quiescence (all paths clear it in practice) — MINOR mi-6.

### Attack 5 — A.4.A mapping vs the real protocol

`_resp_id` (`turns.py:31-38`) reads top-level `response_id` else `response.id` — matches the design's map. `_ended_resp_id`
is set at `turns.py:440`; `response.audio.done` does **not** clear `current_resp_id` (`turns.py:452-453`), only
`response.done` does (`turns.py:451`) — this is exactly the min-8/m-h situation and `ENDED_CURRENT` covers it. Id-less
delta after a cap: `current_resp_id` is still set and not ended → `LIVE`, `idless_delta_events += 1`, bytes →
`safety_truncated_pcm_bytes` per A.2 rule 4 — consistent (A.7 keeps identity across the cap). `orphan_pcm_bytes` stays
outside the A.4.A equation. **The classification is self-consistent for cap/ended/stale/unattributed.** The one real
gap is the *non-cap* invalidation case → BLOCKER B2 (Attack 8).

### Attack 6 — A.15 rows 1..18 (incl. 7b, 17b): fields exist, domains unique, basis pinned

Every named field exists in A.14 (or A.12 for rows 17/17b/#18-client). Aggregation domains are unique for the four
`*_per_generation` fields. Row 9 is correctly reworded as a structural-0 tripwire (min-2). Row 16's acceptance form
(`byte_cap_failures = 0`) is structurally 0 for the configured encoder but is made live by the mandated stub-encoder
test C — honest. No constant-to-constant comparison. `t_attempt` basis: rows 7/7b and A.14's `pacer_min_...` are
pinned; `pacer_wake_overshoot_mean_ms_observed` is pinned by its definition. Caveats: row 8's
`catch_up_frames_over_50fps = 0` is unsatisfiable (B1); row 12's predicate (a) decidability (mi-4); row 4's
`synthetic_tail_zero_pad_bytes` is not asserted but is reported.

### Attack 7 — A.3 construction test: decidable except for the dl_buf claim

(b) and (c) are mechanically decidable. (a) is now scoped to the downlink playback path with `uplink_q` explicitly
exempt (`turns.py:86` holds 640 B uplink frames) → the rev-4 M-D objection is answered. Residual tension: predicate
(a) speaks of "complete **encoded** audio units" while A.3 invariant 1 counts "a 960-byte **PCM** frame or its Opus
packet"; and invariant 2's "residue never constitutes a complete frame" conflicts with the cap's complete refused
candidate (mi-4). Not fatal to decidability.

### Attack 8 — A.9 sealed rule vs the other late-event forms: NOT fully covered → BLOCKER B2

A.9 defines the locally-terminal state narrowly: "Once a generation is sealed — **normal completion or cap
truncation** — …". The other seven terminal transitions (stall, send_error, barge-in, abort, close, listen_start,
upstream-close) are **not** declared sealing. Combined with A.4.A (which classifies by `current_resp_id` /
`_ended_resp_id` only — it has no invalidation term) and with A.6/A.4.C never clearing `current_resp_id`, a
generation that was invalidated by a fatal stall or a send error remains "live" to A.4.A: late in-flight
`response.audio.delta`s are classified `LIVE`, admitted (the store was flushed to backlog 0), encoded, stored, and
`_ensure_pacer` restarts a pacer — i.e. **the killed generation resumes playback with stale audio**. A late
`response.done`/`audio.done` for such a generation also reaches the normal-completion path and re-opens the store
(seal + `GenerationEnd` + tail processing), which is exactly what the sealed rule exists to prevent (A.9/A.6 step 7
"return to a clean state" does not cover it). Reachable in the mandated 10 s-stall test (upstream in-flight deltas
after the stall; the cancel is one-shot and asynchronous). See BLOCKER B2.
`barge_in`/`abort`/`close`/`listen_start`/`upstream_closed` are incidentally protected because the legacy code
clears `current_resp_id` (`turns.py:346, 255, 116, 234, 656`) — but the design's A.10 does not enumerate that clear
step, so the protection rests on an unstated legacy detail, not on the spec.

### Attack 9 — A.12 client observables

Field names map to the sources: `_INCOMING_AUDIO_QUEUE_SIZE = 64` (`protocol_manager.py:24`), bounded queue
(`:42-44`), drop-oldest (`:162-178`); `_TTS_FIFO_MAX_S = 10.0` (`audio_codec.py:26`), FIFO (`:68-70`),
`PcmFifo` push/pull/clear (`audio_buffer.py:34-83`); output callback (`audio_codec.py:192-239`);
`clear_audio_queue` (`:420-426`); `aec_engine.py:210` is `self._far_dropped += 1`. The
`client_midstream_underrun_events` "playback start instant" is defined as "the first decoded PCM block … submitted
to the output device", but the code's write point is `self._tts_fifo.push(audio_float32)` at `audio_codec.py:400`
(a FIFO push, *not* device submission; the device submission is `_output_callback:218-231`), and `write_audio` is
not response-aware. The definition is *conceptually* the right one, but the correlation mechanism is unspecified —
MINOR mi-7. `portaudio_output_underflow_count` / `whole_block_zero_fill_count` / `partial_zero_pad_samples` are
implementable from `status` (`:207-212`) and the zero-fill branch (`:226-229`). A.16's "client drain clock = 50
chunks/s (**960 @ 48 kHz**)" is mis-described: `_mix_chunk = OUTPUT_SAMPLE_RATE*0.02 = 480 @ 24 kHz` (`:74`) and the
FIFO is 240 000 samples = 10 s @ 24 kHz, not 48 kHz — MINOR mi-9.

### Attack 10 — Row 17b / row 16 scenarios

Row 17b requires an instrumented client run (A.12 default OFF); row 16 requires stub encoder test C. Both are
executable and non-dead: test C exercises `AUDIO_STORE_BYTE_CAP_REACHED` at frame 241 before the 1500-frame cap with
the stated flush mapping. The two rows are the only places the client half and the byte-cap branch are exercised,
and each has a named field. No dead branch found (row 9's structural 0 is acknowledged, not hidden).

### Free attack — rev-5 self-inconsistencies

* Stale constants/version after the slack change: `r1f-design-review.md:114` (A.1) still says "given **2 ms slack**";
  `:720` (A.13) says "the connection-wide **18 ms** guard (A.5)" while A.5 sets `MIN_SEND_INTERVAL_MS = 15.0` and
  A.15 row 7 asserts `>= 14.999`; `:97` heads Part A "(**rev 4**)" while the header declares rev 5; `:109`, `:123`
  still speak of "what rev 4 removes" / "a compliant rev-4 pacer". The A.13 "18 ms" is not cosmetic: an implementer
  following A.13 gets slack 2, reproduces exactly the sag M-A-ext was added to fix, and fails row 7b → MAJOR MA-2.
* §0.4 vs Part A, 18 rows spot-checked: rows B1, M-A, M-A-ext, M-C, M-D, M-E, M-F, M-G, min-2..min-9 are consistent
  in substance. Two mismatches: (i) §0.4's M-B row says "the mean-rate field **and row 7b** apply to active runs
  with `frames_in_run >= 250`", but row 7b's overshoot clause has no such qualifier (A.5) — the closure claim
  overstates the fix (supports MA-1); (ii) §0.4's M-A row asserts "lateness decays, mean stays 20.000" as the
  rewrite, but A.5's own drift condition makes that conditional on `E[j] < slack` (supports mi-8).
* A.16 `delta`-mean/percentile numbers: exact method not stated, values not reproducible to 3 dp (mi-3); the
  "nearest-rank" parenthetical is mislabelled (mi-2).

---

## 3. Closure audit of the 18 §0.4 rows

Verdicts are from my own reading of Part A plus source / evidence / simulation verification, not from the "closed"
claims. "Reach." = does the row's residual defect remain reachable?

| # | §0.4 row | verdict | reach. | target section + evidence |
|---|---|---|---|---|
| 1 | **B1** frame/byte cap trigger has no bucket | **CLOSED** | no | A.2 (pre-encode refusal; whole-`dl_buf` discard) + A.11 (post-encode trigger packet → `flushed_byte_cap_frames`). Re-derived both mandated tests: A.4.B and A.4.C residual 0. Residual ambiguity in counter attribution only (mi-5). |
| 2 | M-A floor rationale falsified | **CLOSED** | no | A.5 rationale rewritten (floor binds on multi-ms wakes; bounded recovery). Confirmed by measurement (`delta>2ms` on 7.5/20.9-23.9/15.1-16.1 %) and simulation. Caveat: "can never pace" is unconditional but only holds when `E[j] < slack` (mi-8). |
| 3 | M-A-ext drift condition | **CLOSED** | no | A.5 states `E[wake overshoot] < slack` + `pacer_wake_overshoot_mean_ms_observed` in row 7b. `E[j]` = 3.31/2.47 ms < 5 ms reproduced; threshold behaviour reproduced (MIN=18 sags to 21.47 ms; MIN=15 → 20.10-20.15 ms). But the gate built on the new field false-fails → new MAJOR MA-1. |
| 4 | M-B row 7b short-run false-fail | **CLOSED** | no | A.5/A.14/A.15 `frames_in_run >= 250`. Simulation: 250-frame compliant runs with 5 % hiccups → 0.00 % exceed 20.5 (max 20.12). |
| 5 | **M-C** post-cap second `GenerationEnd` | **PARTIAL** | **yes** | A.9 sealed = "normal completion or cap truncation" only. The cap case is fixed, but stall/send_error are not sealing: their late `LIVE` deltas are admitted and restart the pacer, and their late terminals re-open the store (A.4.A has no invalidation term; A.6/A.4.C do not clear `current_resp_id`). Reachable in the mandated stall test → **BLOCKER B2**. |
| 6 | M-D predicate (a) + removal list | **CLOSED** | no | A.3(a) scoped to the downlink playback path with `uplink_q` exempt; list now includes `main.py:24,53,75-76` and `turns.py:297`. Grep of the whole repo confirms those are the remaining live `DL_QUEUE_MAX` / `_stop_pending` sites. Residual: the "all `dl_q` uses" line still lists `turns.py:555,559` (which use the local alias `q` from `:532`) and omits `:513,528,532` — harmless (those functions are removed) → MINOR mi-11. |
| 7 | M-E stall case leaves `PRE_SEND_WAIT` head unbucketed | **CLOSED** | no | A.6 case B step 2 resolves the in-flight head (`PRE_SEND_WAIT` → `flushed_pacer_stall_frames`; `SENDING` → `send_outcome_unknown_frames` + INVALID). |
| 8 | M-F timestamp basis | **CLOSED** | no | A.5 `timestamp basis := t_attempt`; A.14 `pacer_min_inter_send_ms_observed … measured on t_attempt`; A.15 row 7 "on `t_attempt`"; the overshoot metric is defined on `t_attempt - not_before`. |
| 9 | M-G tombstone insertion rule | **CLOSED** | no | A.4.A rule 1: every `response_id` inserted into the ever-created map at creation, retained for the connection lifetime; `UNKNOWN_RID` = never created. |
| 10 | min-1 A.16 r1d p95 convention | **PARTIAL** | no | A.16 notes the convention, but the note is wrong: it calls `0.141` "nearest-rank" (nearest-rank = `0.145`; `0.141` = linear interpolation; the printed `0.136` = lower-rank on `n-1`) → MINOR mi-2. No reachable defect. |
| 11 | min-2 row 9 structurally 0 | **CLOSED** | no | A.15 #9 reworded as a regression tripwire; confirmed structurally 0 (`t_attempt >= deadline`). |
| 12 | min-3 floor-bind tie rule | **CLOSED** | no | A.5: "equality counts as the deadline term". |
| 13 | min-4 cancellation-boundary scope | **CLOSED** | no | A.4.C + A.10 boundary note ("delivered while the pacer is suspended in the pre-send wait"). |
| 14 | min-5 close-during-send INVALID scope | **CLOSED** | no | A.13 declared scope; runs labelled. (Only close/abort named, but A.4.C's general rule covers the other reasons — attack 4 table.) |
| 15 | min-6 client playback start instant | **CLOSED** | no | A.12 defines it (first decoded PCM block of the response submitted to the output device). Mechanism unspecified → MINOR mi-7. |
| 16 | min-7 refused admission not sampled | **CLOSED** | no | A.2: "a refused admission mutates nothing and is not sampled". |
| 17 | min-8 ENDED_CURRENT | **CLOSED** | no | A.4.A: `rid` absent and `_ended_resp_id == current_resp_id` → `ENDED_CURRENT`, guard-dropped, non-invalidating. Consistent with `turns.py:440-442,452-453`. |
| 18 | min-9 byte-cap check point | **CLOSED** | no | A.11: post-encode check point stated explicitly; B1's frame-cap point is pre-encode. |

Summary: 16 CLOSED, 1 PARTIAL-with-residual (**M-C → BLOCKER**), 1 PARTIAL-documentation (min-1, MINOR).
Rev-4 B1 is genuinely closed; rev-4 M-B, M-D, M-E, M-F, M-G and eight of nine rev-4 minors are closed.

---

## 4. BLOCKERS

### B1 — `catch_up_frames_over_50fps = 0` (A.15 row 8; A.5) is unsatisfiable for any compliant pacer that ever recovers from jitter; the fast-side gate (and A.13's relocation gate) cannot pass.

Evidence:
- A.5: "`catch_up_frames_over_50fps` … evaluated at every send with the **half-open** look-back window
  `(t_now − 1000 ms, t_now]`; term `= max(0, sent_in_window − 50)` … A compliant 50 fps pacer has exactly 50 sends in
  every such window ⇒ the counter is 0." A.15 row 8 asserts `catch_up_frames_over_50fps = 0`; A.13 requires it for
  the relocation claim.
- Analytic counter-example: with `t_k = 20k + delta_k`, frame `n-50` lies inside `(t_n − 1000, t_n]` iff
  `delta_{n-50} > delta_n` — probability ≈ 0.5 per send for any non-degenerate `delta`. So the count is 51 (term 1)
  on roughly half of all sends even for a clock-dominant pacer.
- Simulation (heredoc, resampled envelopes, A.6 rebase included): `max(sent_in_window − 50)` = **1** for the benign
  synthetic envelope `delta ~ N(1.0, 0.4)`, and **2 / 3 / 3** for the mock / r1d / r1e measured envelopes. MIN=18
  behaves the same (2-3).
- The failure direction is inverted: `catch_up` is 0 only when the pacer is *slow* (MIN=19.5: mean 20.9-23.0 ms,
  `catch_up = 0`) and nonzero exactly when the pacer does its mandated floor-bound recovery
  (`MIN + j` ≈ 15-16.5 ms). The design's own A.5 rationale ("the guard binds after multi-ms wakes and recovers")
  guarantees a nonzero reading.

Reachability: every run with a steady segment longer than 1 s and any jitter, i.e. every normal R-1f acceptance run.

Minimal fix (normative sentence, one of two — preferably both):
1. Give `catch_up_frames_over_50fps` the same measurement tolerance as `wire_rate_excess`
   (`<= 1`, i.e. `max(0, sent_in_window − 51)`), and restate A.5's "exactly 50 in every window" claim as "50 ± 1";
   or
2. Redefine it on the connection-wide anchor basis exactly like `wire_rate_excess`
   (`permitted(t) = 1 + floor((t − anchor_t)/20)`) and delete the sliding window; then the metric is the same object
   as row 8's first clause and the second clause becomes redundant.

Exit criterion (verifiable): a compliant pacer driven by the three measured jitter envelopes reports
`catch_up_frames_over_50fps` within the chosen tolerance over a 30 000-frame run, while a 21.1 ms legacy pattern
still fails row 7b; and the assertion is reproducible by a simulator written from the document alone.

### B2 — A.9's "sealed ⇒ locally terminal" set covers only 2 of the 8 terminal transitions; after a fatal stall or a send error the generation is neither sealed nor excluded from A.4.A's `LIVE` class, so late upstream events re-open the store and late deltas resume playback of a killed generation.

Evidence:
- A.9: "Once a generation is sealed — **normal completion or cap truncation** — a later upstream terminal event for
  the same `response_id` is processed only through the tombstone accounting … must not enqueue a second
  `GenerationEnd`, emit a second TTS stop, process a synthetic tail, or re-open the store." `stall`, `send_error`,
  `barge_in`, `abort`, `close`, `listen_start`, `upstream_closed` are **not** in the sealing set.
- A.4.A classifies purely by `current_resp_id` / `_ended_resp_id` (`LIVE` = "`rid` equal to the live generation
  (`current_resp_id`, **not ended**)"). It has no invalidation term.
- A.6 case B (stall) and A.4.C (send error) invalidate and flush the generation but **do not clear
  `current_resp_id`** (A.6 steps 1-8; A.4.C bullet "Send exception"); A.6 step 7's "return to a clean state" is not
  normative. A.7 keeps the generation identity across invalidation.
- Consequence chain, reachable in the mandated 10 s-stall test (upstream in-flight deltas after the stall; the
  one-shot cancel is asynchronous): a late `response.audio.delta` for the stalled generation is classified `LIVE` →
  admitted (the store was just flushed to backlog 0) → encoded → stored → `_ensure_pacer` starts a new pacer →
  stale audio is delivered for a generation the bridge declared dead. A late `response.done`/`audio.done` for such a
  generation additionally reaches A.9's normal-completion steps (seal → `GenerationEnd` → tail processing →
  stop), re-opening the store, which is the exact behaviour M-C was raised for.
- The other five transitions are only incidentally protected: the legacy code clears `current_resp_id` at
  `turns.py:346` (barge-in), `:255` (abort), `:116` (close), `:234` (listen_start), `:656` (qwen close) — but A.10's
  S1-S4/S5 enumeration does not include that clear, and A.8's rewrite of the two cancel sites explicitly forbids
  consulting `diag.active_gen`, so the protection is not specified.

Reachability: the mandated stall test (B/A.6 test), and any production stall/send error with in-flight deltas.

Minimal fix (normative): define one local-terminal predicate used by both A.9 and A.4.A — "a generation is
**locally terminal** as soon as it is sealed (normal completion, cap truncation) **or** invalidated
(barge-in, abort, close, listen_start, upstream-close, send error, fatal stall); once locally terminal it is removed
from the `LIVE` class (late deltas → `STALE`/`guard_dropped_pcm_bytes`), the store is closed to it, and any later
upstream terminal is absorbed by the tombstone with no marker, no stop, no tail." Add the corresponding field
(e.g. `locally_terminal_generations`) to A.14 and assert `late_deltas_after_terminal_frames = 0` (or
`guard_dropped_pcm_bytes > 0, orphan = 0`) in A.15.

Exit criterion (verifiable): the 10 s-stall run reports `in_flight_frames == 0`, A.4.C residual 0,
`end_markers_per_generation == 1`, `tts_stops_per_generation == 1`, and **zero** frames from the invalidated
generation sent after the stall instant (`send_timeline` shows no post-stall send with the old `resp_id`).

---

## 5. MAJORS

### MA-1 — `pacer_wake_overshoot_mean_ms_observed` (row 7b's drift clause) has no minimum-run constraint and false-fails on compliant runs.

A.5 defines it as "max over active runs of the mean of `max(0, t_attempt_n − not_before_n)` over non-rebase
intervals" with **no `frames_in_run >= 250`** (its sibling `pacer_mean_inter_send_ms_observed` has it — A.5/A.14),
and A.15 row 7b gates `<= 4.0`. §0.4's M-B row nonetheless claims row 7b carries the `>= 250` constraint. Measured
false-fail rates (compliance = the design's own envelopes, drift condition satisfied): table (g) — r1d 6.3 % at 250
frames, 27-35 % for 30/5/3/2-frame runs, 77.4 % for a mixed session; r1e 52.6 % mixed; mock 10.1 % mixed. The
field is also absent from A.13's `Required bridge fields`.
Fix: apply the same `frames_in_run >= 250` qualifier to the overshoot field (or aggregate it connection-wide as a
trimmed mean), state the sampling domain once for both fields, and either raise the gate to `<= 5.0` with the
margin argued against the measured envelope or state the margin derivation explicitly.
Exit: over 4 000 simulated sessions that include short utterances, a compliant pacer reports 0 false-fails on row
7b, while a `E[j] >= slack` pacer still fails it.

### MA-2 — A.13 states an "18 ms guard", contradicting A.5/A.15 (15.0 ms); the rev-5 slack change was not propagated.

`r1f-design-review.md:720` (A.13, normative "Required bridge fields" section): "the media-clock pacer (absolute
deadlines) plus the connection-wide **18 ms guard** (A.5)". A.5 sets `MIN_SEND_INTERVAL_MS = 15.0` (slack 5 ms) and
A.15 row 7 asserts `>= 14.999`. Related stale text: A.1 `:114` "given **2 ms slack**"; Part A heading `:97`
"(rev 4)"; `:109`/`:123` "rev 4 removes" / "compliant rev-4 pacer". An implementer who follows A.13 gets slack 2,
which per M-A-ext itself reproduces the 21.47 ms / 46.6 fps sag for r1d and fails row 7b.
Fix: replace "18 ms" with "15 ms" in A.13; change A.1's "2 ms slack" to "5 ms"; retitle Part A "(rev 5)".
Exit: no normative section states a floor/slack value other than 15.0 / 5.0.

---

## 6. MINORS

- **mi-1** Stale revision/parameter text: `:97` Part A heading "(rev 4)"; `:109` "what rev 4 removes"; `:123`
  "compliant rev-4 pacer"; `:114` "2 ms slack". (MA-2 covers the normative one.)
- **mi-2** A.16 mislabels the r1d `T` p95 convention: nearest-rank = `0.145 ms`; `0.141 ms` is linear
  interpolation; the printed `0.136 ms` is the lower-rank value at index `int(0.95(n-1)) = 65`. min-1 is therefore
  only partially closed. State the convention once (as rev-4 asked) and use it consistently.
- **mi-3** A.16's `delta` means `1.387 / 3.324 / 2.490 ms` are not reproducible to 3 dp by any method stated in the
  document; my values are `1.386 / 3.31 / 2.47-2.56` depending on whether/how `T` is subtracted. Define "steady
  gaps" and the `T`-subtraction rule. (The load-bearing inequality `E[delta] ≷ slack` is unaffected.)
- **mi-4** A.3 invariant 2 ("`len(dl_buf) < 960` after each step; residue never constitutes a complete frame")
  conflicts with A.2/B1 (the complete refused candidate sits in `dl_buf` at the cap instant); invariant 1's
  "960-byte PCM frame **or** its Opus packet" also conflicts with predicate (a)'s "complete **encoded** audio units".
  Restate invariant 2 as "… < 960 after each step, and at the cap transition `dl_buf` holds only the refused
  candidate plus its sub-frame residue, which is discarded as a unit".
- **mi-5** A.2's cap-crossing byte attribution is not unique: under "append whole delta" the extra complete frames
  become `residue_discarded_cap_bytes`; under rule 2's "append only enough to complete one frame" they become
  `safety_truncated_pcm_bytes`. Both close both equations, but the counter values are implementation-selected. Pin
  one reading (A.2 rule 2's incremental append) and reword the B1 sentence accordingly.
- **mi-6** A.4.C's quiescence definition (no store entry, no in-flight frame, stop emitted/suppressed) does not
  require `dl_buf` empty, yet A.14 samples `still_buffered_pcm_bytes` "at generation quiescence" and A.4.B carries it
  as a term. Add "and no `dl_buf` residue" to the quiescence condition (all paths already satisfy it).
- **mi-7** A.12's "playback start instant = first decoded PCM block of that response submitted to the output
  device" is not directly observable at the code's write point (`audio_codec.py:400` is a FIFO push; device
  submission is `_output_callback:218-231`, which is not response-aware). Specify the correlation (tag the first
  sample of a response and timestamp the callback that consumes it, or define the instant as the first
  `write_audio` for the response and accept the FIFO offset explicitly).
- **mi-8** A.5's "it can never pace the stream" (and §0.4's M-A "lateness decays, mean stays 20.000") is
  unconditional but only true when `E[j] < slack`; with `E[j] >= slack` the floor *does* pace (sag to
  `MIN + E[j]`, verified: 21.47 / 22.96 ms). Condition the sentence on the drift condition.
- **mi-9** A.16's "client drain clock: exactly 50 chunks/s (960 @ 48 kHz)" mis-describes the client:
  `_mix_chunk = OUTPUT_SAMPLE_RATE*0.02 = 480 @ 24 kHz` (`audio_codec.py:74`), and the FIFO figure
  `240 000 samples = 10.0 s` implies a 24 kHz protocol rate, not 48 kHz. (The 50 chunks/s and the 564-frame
  capacity are right.)
- **mi-10** The slack-5 simulated means `20.0000 / 20.0023 / 20.0003` (A.16, §0.4) are only reproducible with the
  A.6 rebase deleted; with the mandated rebase the means are `20.10-20.15 ms` (49.6-49.8 fps) — a real ~0.5 %
  rebase-induced deficit that A.1's "restores the 50 fps media rate" and A.5's "mean stays 20.000 ms" ignore
  (still inside row 7b's 20.5). Either state the rebase deficit or exclude it explicitly.
- **mi-11** A.3's "all `dl_q` uses" line still lists `turns.py:555,559` (which use the local alias `q` from `:532`)
  and omits `:513, 528, 532`. Harmless (all those bodies are in the REMOVE list) but the enumeration is still
  line-imprecise, which is the rev-4 M-D complaint left standing.

---

## 7. Independently verified as correct

- Deficit reproduction: same-pacer gap p50 `21.0939 / 21.1627 / 21.3062 ms` → `47.41 / 47.25 / 46.94 fps`;
  `T` p50 `0.060 / 0.0645 / 0.0835 ms`, max `0.124 / 0.198 / 0.214 ms`; delta median
  `1.034 / 1.098 / 1.223 ms` (`gap_p50 - 20 - T_p50`); packet mean `61.47 / 55.87 / 58.76 B`, p50 `62/60/61`,
  p95 `67/72.5/73`, max `87/79/108`. A.16's headline rows reproduce (the r1d p95 parenthetical excepted, mi-2).
- A.5/M-A-ext mechanism: deadline clock pinned at `20.0000 ms` when `E[j] < slack`; sag to `MIN + E[j]` when
  `E[j] > slack`; with the measured envelopes, MIN=18 sags r1d/r1e to `21.47 / 20.61 ms` while MIN=15 holds
  `20.10-20.14 ms`. The `E[j] < 5 ms` drift condition is satisfied by all three envelopes with 1.6-2.5 ms margin.
- Absolute-deadline invariant: `t_attempt >= deadline_n` in every regime (clock, floor-bound recovery, rebase,
  200 ms stall); `wire_rate_excess_frames_max = 1` for MIN in {15,18} and 0 for MIN=19.5 — the fast-side bound is
  real and the +1 tolerance is correct.
- M-B: `frames_in_run >= 250` eliminates the short-run false-fail on `pacer_mean_inter_send_ms_observed`
  (0.00 % over 4 000 simulated 250-frame runs with 5 % hiccups; max 20.12 < 20.5).
- B1: both cap paths close A.4.B and A.4.C with residual 0 (test B `1501*960 = 1500*960 + 960`; test C
  `241 = 241`); the refused candidate is never encoded (no A.4.C term needed) and the byte-cap trigger packet is
  never in-flight (no `send_failed` aliasing).
- A.4.C lifecycle: all ten transitions map every frame to exactly one terminal bucket and every removed byte to
  exactly one residue reason; the frame-cap instant leaves an in-flight frame untouched.
- A.4.A: `_resp_id` (`turns.py:31-38`), `_ended_resp_id` (`:440`), the `response.audio.done` non-clear
  (`:452-453`) and the `response.done` clear (`:451`) all support the LIVE/STALE/ENDED_CURRENT/UNKNOWN/UNATTRIBUTED
  triage; `orphan_pcm_bytes` stays outside the source equation; no double count between the LIVE and STALE branches.
- M-D: the removal list's newly added sites are the real remaining live references — repo-wide grep confirms
  `DL_QUEUE_MAX` at `main.py:24,53,75-76`, `config/config.json:6`, `turns.py:77`; `SENTINEL` `turns.py:20,500,519,
  548,572,620`; `_stop_pending` `:84,297,541,549,568,573,612`; `audio_out_dropped` `counters.py:26,56` +
  `turns.py:521,552`; `/health` alias at `counters.py:56` via `http.py:14`.
- Byte-ceiling arithmetic: `204.8 B/frame`, `1.896x` margin vs 108 B, 241-frame trigger before the 1500-frame cap,
  `1500*108 < 307200` → live branch, test C makes it execrable.
- A.15 field coverage: every field named in rows 1..18 (incl. 7b, 17b) exists in A.14/A.12; the four
  `*_per_generation` fields have unique "max over generations" domains; row 9 is honestly re-worded; row 16 is made
  live by test C.
- Client figures: `_INCOMING_AUDIO_QUEUE_SIZE = 64`, `_TTS_FIFO_MAX_S = 10.0`, drop-oldest in both queues,
  `564 frames = 11.28 s`, 50 chunks/s (modulo mi-9's unit description).
- Source anchors used by the design are accurate: `turns.py:20,77,84,86,111,116,233-234,245,249-255,255,297,321-322,
  337,340-349,346,356-359,367,372-373,377-386,410-418,424,429,435,438,442,451-453,480-481,492,498,503,508,531,
  591,592-594,610-611,625,651,656`; `audio.py:25-29`; `counters.py:26,56`; `main.py:24,53,74-76`;
  `config/config.json:6`; `diag.py:40,187,535`; client `protocol_manager.py:24,42-44,162-178`,
  `audio_codec.py:26,68-70,74,192-239,373-403,400,420-426`, `audio_buffer.py:34-83`, `aec_engine.py:210`.

---

## 8. Verdict

DESIGN_REVIEW_BLOCKERS = 2
DESIGN_REVIEW_MAJORS   = 2
DESIGN_REVIEW_MINORS   = 11
DESIGN_REVIEW          = REVISE

Gate note. Rev-4's blocker (B1: the cap-triggering frame/byte had no disposition bucket) is **closed** — both the
pre-encode frame-cap refusal and the post-encode byte-cap flush now close A.4.B and A.4.C with residual 0, verified
by re-deriving tests B and C. Six of the eight rev-4 majors (M-A, M-A-ext, M-B, M-D, M-E, M-F, M-G) and eight of
nine rev-4 minors are closed. Two blockers remain:

* **B1 (new)** `catch_up_frames_over_50fps = 0` (A.15 row 8, A.13) is unsatisfiable for a compliant pacer: the
  half-open sliding window reads 51 on ~half of all sends and 52-53 on the design's own measured envelopes, because
  the mandated floor-bound recovery sends at `MIN + j < 20 ms`. The fast-side acceptance gate — and therefore the
  bridge half of the relocation claim — cannot pass. This is deterministic, not a flake.
* **B2 (M-C PARTIAL, residual reachable)** A.9's "sealed ⇒ locally terminal" set covers only normal completion and
  cap truncation. After a fatal stall or a send error the generation is neither sealed nor removed from A.4.A's
  `LIVE` class, so late in-flight deltas are admitted and restart the pacer (stale audio from a killed generation)
  and late terminals re-open the store. Reachable in the mandated 10 s-stall test.

The two majors (MA-1: the new drift-condition observable has no minimum-run constraint and false-fails on compliant
runs; MA-2: A.13 still states an 18 ms guard against A.5's 15.0 ms) and the eleven minors are carried to the
implementation backlog at the lead's discretion and do not by themselves gate. Implementation should proceed only
after B1 and B2 are amended normatively and re-reviewed.
