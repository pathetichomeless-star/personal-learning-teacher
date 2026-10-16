# R-1f rev-7 — INDEPENDENT ADVERSARIAL DESIGN REVIEW (Agent F, fresh instance)

> Persisted by the team-lead on 2026-10-06, verbatim from the reviewer's final report, with the
> reviewer's errata of the same session applied (2 cross-reference slips only: §1 M8 ends "See MAJOR
> M1"; §4 F8's observability item is labelled an additional, uncounted minor observation). Numbers
> and verdict unchanged. Lead audit: see Part B of `r1f-design-review.md`.

Scope: r1f-design-review.md (rev 7), r1f-rev7-po-decision.md, rtl-lab/app/*, config/config.json,
py-xiaozhi/src/* (read-only), rtl-lab/evidence/*. Read-only: no file created/modified, no docker
command (docker is not even on PATH in my shell), no network. All numbers below recomputed by me with
<user-home>/.workbuddy/binaries/python/versions/3.13.12/bin/python3 (stdout only).

## 1. RECOMPUTED NUMBERS (method + results)

M1. Median inter-send gap from the sent-Opus journals (t_send, same `pacer_task_id`):
21.0939 / 21.1627 / 21.3062 ms (r1e_mock / r1d_real / r1e_real) ⇒ **47.407 / 47.253 / 46.935 fps**
(design A.16: 21.0939/21.1627/21.3062 ⇒ 47.41/47.25/46.93 — reproduced).

M2. `T = t_send − t_intent` from `send_intents` (n = 200 / 70 / 200 of 8000-max deques):
p50 **0.0600 / 0.0645 / 0.0835 ms**; p95 lower-rank 0.0950/0.1360/0.1780; p95 nearest-rank
0.0950/0.1450/0.1780; p95 linear 0.0951/0.1410/0.1783; max **0.124 / 0.198 / 0.214 ms**
(design: 0.060/0.0645/0.0835, 0.095/0.136/0.178, max 0.124/0.198/0.214 — reproduced).

M3. Opus packet bytes: mean **61.47 / 55.87 / 58.76**; p50 62/60/61; p95(lower) 67/72/73; max
**87 / 79 / 108**; min 49/21/3 (design: 61.5/55.9/58.8, p50 60–61, p95 73, max 79–108 real / 87 mock
— reproduced).

M4. δ envelope. Method (A.16's): consecutive `t_send` pairs with same `pacer_task_id` and gap<200 ms;
`δ = gap − 20 − T(later frame)` when that frame has a `t_intent`, else `gap − 20 − mean(T)`.
n = 362 / 67 / 477; mean **1.3857 / 3.2980 / 2.4716**; median 1.027 / 1.071 / 1.214;
fraction > 2 ms 7.5 % / 22.4 % / 14.9 %.
Mean-gap estimator (mean steady gap − 20 − mean T): **1.3857 / 3.3244 / 2.4710** — this reproduces
A.5's 1.386/3.324/2.484, not A.16's stated per-pair estimator (r1d 3.298 ≠ 3.324). See m2.

M5. 15 ms vs 18 ms resample simulation (my own method, stated so it is reproducible):
send-time recursion `s_n = max(d_n, s_{n−1}+F) + δ_n`, `d_n = epoch + 20n`, hence
`L_n = max(0, L_{n−1} − (20−F)) + δ_n` and `interval_n = s_n − s_{n−1} = 20 + L_n − L_{n−1}`;
δ resampled from each journal's M4 envelope (a) in journal order, (b) bootstrap with replacement
(500 trials), (c) 8000-frame bootstrap. rate = 1000/mean(interval).
- **F = 15 ms (slack 5)**: journal order **49.992 / 49.638 / 49.998 fps**; bootstrap median
  49.993 / 49.739 / 49.993; 8000-frame 50.000 / 49.995 / 50.000.
  ⇒ **reproduces the PO claim r1d ≈ 49.97 / r1e ≈ 50.00** (r1d spans 49.64–50.00 by method).
- **F = 18 ms (slack 2)**: journal order **49.992 / 46.459 / 48.793 fps**; bootstrap median
  49.991 / 46.717 / 48.751; 8000-frame 50.000 / 46.789 / 48.979.
  ⇒ **an 18 ms floor fails the gate on the r1d and r1e envelopes** (46.46–46.79 and 48.75–48.98, both
  < 49.5); the mock envelope still passes (its E[δ]=1.39 < 2). This is exactly the PO's rationale.
  Under the §0.7.3 item-2 locality rule it fails even harder: r1d produced *no* qualifying ≥250-frame
  segment at all (INSUFFICIENT⇒FAIL) and r1e's qualifying segments reach 49.25 < 49.5.
- Analytic cross-check of the gate's satisfiability at F=15: within a *clean* segment no rebase occurs,
  so every pre-send lateness ≤ 40 ms, hence L ≤ 45 ms; segment mean ∈
  [20 − 45/(k−1), 20 + 45/(k−1)] = **[19.819, 20.181] ms** for k ≥ 250 ⇒ segment rate
  ∈ **[49.55, 50.46] fps ⊂ both gates**. So §0.7.3 item 2 cannot false-fail a clean segment.
  (Lower bound 19.819 is only 0.019 ms from the gate — thin, but sound because a segment begins at
  L≈0 after a rebase/pacer start, giving mean ≥ 20.)

M6. Arithmetic spot-checks: 524288/1500 = 349.53 B/frame; 524288/1275 = 411.2 ⇒ frame 412;
349.53/108 = 3.236×; Q1 64×20 ms = 1.28 s; Q2 240000 samples @24 kHz = 10.0 s; absorptive 11.28 s =
564 frames; measured deficit 50−47.41/47.25/46.93 = 2.59/2.75/3.07 ⇒ 1/3.07…1/2.59 = 326…386 ms
(design 2.6–3.1 fps ⇒ 323–385 ms — reproduced).

M7. CL-1 executed against the **real** `PcmFifo` (imported, not reimplemented): FIFO holding 200
samples, `pull(480)` ⇒ returned length **480**, FIFO size → 0, `dropped` = 0. CL-2: empty FIFO
`pull(480)` ⇒ **None**. Missing tail = **280** samples. The callback cannot infer underfill from the
return length (always n when size>0) — the design's premise is verified.

M8. wire-rate excess. Derivation for the design's own metric: with `excess_n = (n+1) − (1+floor((s_n−s_0)/20))`
and no rebase, `s_n − s_0 = 20n + L_n − δ_0` ⇒ `excess_n = −floor((L_n − δ_0)/20)`, i.e.
**excess ≤ ceil(δ_0/20)**, where δ_0 is the *first* frame's overshoot. Since the r1d envelope
contains δ up to 27.8 ms and slack 5 lets the pacer fully catch up (L→0), **excess = 2 is reachable**,
not ≤ 1. My simulation of the specified pacer (15 ms floor, floor-bound recovery, Case-A rebase model)
gave per-run `wire_rate_excess_max` median **1**, max **2** over 200×1500-frame resampled runs for
r1d_real and r1e_real. See MAJOR M1.

## 2. CONFORMANCE AUDIT (§0.7.1 row-by-row vs Part A; and §0.7.3)

| §0.7.1 row | Verdict |
|---|---|
| B2 decision (15.0/5.0, no 18.0, no 15–18 range, no E[j] precondition, gates, diagnostic-only overshoot) | **CONFORMANT** (A.5:579–587; A.1:209–210; A.13:1049–1054; A.15 rows 1–3; A.16:1254–1255). No *normative* 18.0 remains; the surviving 18.0 strings are historical closure maps (§0.4:58, §0.5:100/107, §0.6:110/116/118) and A.16's explicitly-labelled HISTORICAL row — acceptable, see m5-adjacent note. |
| B1 normal seal at full backlog | **CONFORMANT** (A.2 route R2:252–262 implements PO items 1–10 verbatim incl. "exactly once", no tail, no 1501st, drain normally; A.9:809 both branches; A.15 row 5; mandatory Test B′ with N∈{1,200,500,959}). |
| M1 slow-send path | **CONFORMANT** (A.5:613–627: slow_send_events, guard=completion+15, next_deadline=completion+20, break segment, pacer_rebases, no catch-up; T>250 ⇒ SENT then PACER_FATAL_STALL via A.6 Case B; failed/SEND_AWAIT-cancelled ⇒ guard=observation+15). |
| No vacuous rate pass | **CONFORMANT** (A.5:653–658; A.13:1054; A.15 row 2). |
| M2 client partial starvation | **CONFORMANT** (A.12 §"Normative PcmFifo.pull counting":924–945; scoped metric = window delta:994–999; CL-1/2/3:1033–1037). |
| M3 single-store sentinel test | **CONTENT conformant to PO #1–#8, PROCEDURE NOT DECIDABLE** — see BLOCKER B1. |
| MINORS 1–12 | **CONFORMANT** (queued_audio_frames:303/517; post_terminal_sends_total:1116/1218 — but false, B2; BIT1/BIT2 head ownership:851; mutation + `_flush_downlink` site enumeration + qwen_closed→UPSTREAM_CLOSED:305–359; active_pacer_tasks/_max:678–681; acceptance config:1061; TTS-playout-session terminology:900; keep_listening=False window:981–984; A.2 sampling wording:234; stale "Rev 4 requires" removed:301; overshoot diagnostic domain:685/1172; framer TERM-vs-residual:459). |
| COUNTER/ASSERTION updates | **MOSTLY CONFORMANT, one literal deviation**: `pcm_fifo_partial_underfill_events` / `pcm_fifo_partial_zero_pad_samples` are placed in A.14's **client** telemetry block and explicitly **excluded** from the bridge `/health` payload (A.14:1188), while the PO lists them under "Part A /health contract must include at least the new fields". Functional intent met; literal deviation ⇒ m5. |

§0.7.3: item 1 consistent with A.4.C PASS set (A.4.C:569) and row 22; item 3 consistent with A.12 T4
(A.12:987–990); item 4 consistent with A.12:1004; item 5 consistent with A.5:783/671. **Item 2 is
*not* matched by any observable definition** — see MAJOR M2 below. Item 2 does not otherwise contradict
§0.7.1 (verified analytically in M5).

## 3. MANDATED ATTACKS (all 15)

1. **15 ms floor + r1d/r1e resampled envelopes ⇒ positive-rate gate passes — PASS.** M5: F=15 gives
   r1d 49.64–50.00 fps, r1e/mock 50.00; every clean ≥250-frame segment is bounded into [49.55, 50.46]
   by the lateness≤40 ⇒ L≤45 argument, i.e. inside `[49.5,50.5]`/`[19.80,20.20]`. The PO's 49.97/50.00
   is reproduced (r1d is method-sensitive: 49.64 journal-order, 49.74 boot-median, 50.00 boot-long).
2. **Legacy 47.4 fps pacer ⇒ gate fails — PASS.** The journalised pacer's clean segments are 21.09–21.31 ms
   ⇒ 46.93–47.41 fps < 49.5 ⇒ FAIL. Same for an 18 ms floor (M5: 46.46 / 48.79 fps). Also, a run too
   short for a 250-frame segment is INSUFFICIENT ⇒ FAIL — no vacuous escape.
3. **Normal seal, backlog 1500, residue = every representative value 1..959; no frame 1501; every byte closes — PASS.**
   A.2 R2 is N-agnostic: no synthetic tail, no 1501st, `residue_discarded_store_cap_bytes += N`,
   `dl_buf.clear()`, one GenerationEnd, 1500 accepted frames drain. Source: N already in
   `admitted_pcm_bytes`, now in `residue_discarded_pcm_bytes ⊂ residue_discarded_pcm_bytes` term of
   A.4.B; framer residual 0; disposition: no frame formed ⇒ residual 0. Verified for all N∈[1,959]
   (no value-dependent branch). `unsent_backlog_peak_frames` cannot exceed 1500 (no admission).
4. **Slow send T = 10 ms ⇒ explicit completion+15 guard, visible rebase, no burst — PASS.** start s,
   completion s+10; guard s+25; next_deadline s+30; `normal_floor` s+15 ⇒ next send at s+30
   (interval 30 ms). `pacer_rebases += 1`, segment broken (A.5:613–623, A.15 row 24). No interval
   < 20 ms, let alone < 15 ms.
5. **Very slow successful send T > 250 ms ⇒ PACER_FATAL_STALL, no silent rebase — PASS.** A.5:625–626:
   frame SENT first, then exactly one PACER_FATAL_STALL running A.6 Case-B steps 1–8; `pacer_fatal_stalls += 1`;
   NORMAL_LONG_RESPONSE_ACCEPTANCE = FAIL.
6. **No qualifying ≥250-frame clean segment ⇒ acceptance FAILS — PASS.** A.5:653–658 sets
   `PACING_RATE_EVIDENCE = INSUFFICIENT`; A.13:1054 gates `steady_pacer_segments_qualifying_total >= 1`;
   row 2 repeats the clause. Verified no alternative pass path exists.
7. **PcmFifo partial fill 200/480 ⇒ exactly 280 zero-padded samples — PASS (executed).** M7 against the
   real class; `missing > 0 ⟺ 0 < size < n` because the `size==0` early return guarantees size>0 and
   `filled = min(n, size)`.
8. **Client starvation with zero Q1/Q2 drops ⇒ starvation gate still FAILS — PASS.** CL-3: with
   `incoming_queue_dropped_packets = 0` and `pcm_fifo_dropped_samples = 0`, a 200/480 pull yields
   `tts_playout_partial_zero_pad_samples = 280 ≠ 0` ⇒ row 18 FAILS while row 17 passes. Q1/Q2 can only
   detect overrun (A.13:1063) — the scoped zero-pad metric is the real falsifier.
9. **Sentinel construction test mechanically proves exactly one encoded downlink store — FAIL. See BLOCKER B1.**
10. **RESERVED_WAIT barge-in ⇒ head counted exactly once — PASS.** A.10:851 (BIT1 owns the popped head →
    `flushed_bargein_frames`, BIT2 owns only still-QUEUED); A.4.C:522 makes a RESERVED_WAIT cancellation
    under barge-in known-unsent (never outcome-unknown). A double count could only appear as an A.15
    row-8 residual, which the split prevents.
11. **post_terminal_sends_total remains 0 — FAIL on the normal path. See BLOCKER B2.** (It does hold on
    the stall/barge-in/close/send-error paths, where the transition also flushes the head+store.)
12. **active_pacer_tasks_max ≤ 1 — PASS.** Increment is synchronous inside `_ensure_pacer`
    (turns.py:503–506, no await, verified) at the same instant as `create_task`; decrement only in the
    pacer `finally` (turns.py:600–601) or the cancel clear (627–628, 643–644); `done()` ⇒ finally ran,
    so the two paths cannot double-decrement; a successor can only increment after the predecessor
    decremented (same task). Definition and gate are anchored on named fields (A.5:678–681, A.15 row 23).
13. **All three closures zero for the six paths — PARTIAL: 5/6 PASS, byte-cap FAILS. See BLOCKER B3.**
    normal completion ✓ (drain → sent_confirmed; N=0); full-backlog normal seal ✓ (R2; drain);
    barge-in ✓ (head→BIT1, store→BIT2, residue→bargein); send-error ✓ (A.4.C:526 flushes *remaining
    QUEUED/RESERVED_WAIT* → `flushed_send_error_frames`, residue → send_error); fatal stall ✓ (pre-send
    Case B step 2: RESERVED_WAIT→pacer_stall, SEND_AWAIT→outcome_unknown; §2 variant has no head);
    **byte-cap ✗** (no rule for the in-flight head).
14. **No R-1f `audio_out_dropped` mutation remains — PASS.** Full grep of rtl-lab/app: exactly two
    mutations, turns.py:521 (in `_drop_one_non_sentinel`) and turns.py:552 (in `_put_drop_oldest`) —
    both functions are in the REMOVE list (A.3:315–318, 325–326); counters.py:26/56 are
    definition/read-only alias. No third site exists.
15. **No source/config/container change — PASS for files, ATTESTATION-ONLY for containers.**
    Independently verified: every file under rtl-lab/app, rtl-lab/config, rtl-lab/tests is older than
    the two rev-7 markdowns (latest source mtime 2026-10-06 13:33; design doc 21:41; PO doc 21:28);
    py-xiaozhi/src files are 2026-10-05; no new/generated file under those trees; `rtl-lab-backups/`
    contains only the rev-6 backup (21:28) plus pre-R-1c tarballs. sha256[:16] of the sources under
    review: turns.py 4ee903fe9fd8dc93, audio.py c2218a2c3fda5200, counters.py 7e2132d7a68195b5,
    diag.py b969c39f55321d48, qwen.py 7568521304aa458b, ws.py 1322a7599985ad39, http.py
    63d26c203af9e4b1, main.py 8fe46a30dbe08402, config.json a7c1ff3ea8d0e661. Every line reference
    in the document resolves against these contents. **Containers/protected stacks: NOT verifiable
    from here (no docker on PATH; read-only mandate) — lead attestation stands unverified.**

## 4. FREE ATTACKS (rev-7-specific)

F1. §0.7.3 item 1 (cap-run PASS eligibility) — sound and non-loopable: `safety_truncated_pcm_bytes > 0`
    independently catches R1 even when R1's own residue is 0; R2 always has N>0. No loophole found.
    A.4.C's labelled-test exemption (A.4.C:573) is correctly narrowed by §0.7.3 item 1.
F2. §0.7.3 item 2 — the rule is stated but its observable is not (M2 below).
F3. §0.7.3 item 3/4 — consistent with A.12; item 4 correctly makes the whole-block term non-evaluable
    under parallel music (music-only pull returns non-None, suppressing the whole-block count) — the
    "must declare it" escape hatch is a run-level declaration, not a mechanical predicate (minor, not listed).
F4. 15 ms floor ∩ M1 guard ∩ positive-rate gates ∩ A.16: no contradiction found in the floor/guard
    arithmetic (M4 above); the one real inconsistency is the wire-excess "by construction" claim (B3/M1).
F5. A.3 sentinel decidability: exempt-root pruning is a scoped blind spot but is mitigated by hold point
    H (no dequeue, so no coroutine-local copy) — acceptable. The real defects are B1.
F6. A.12 T1–T4 vs source: T1 = audio_codec.py:420–426 invoked from session.py:117–139 — note the
    *keep_listening=True* path only; T2 = session.py:117–119 early return leaves the FIFO to drain —
    matches the source; T3 = audio_codec.py:547 (close) and 263–265 (pipeline rebuild) — matches.
    Defects: T2's sampling instant has no named observable (m7); "counters are monotone" is false
    across T3 (m6).
F7. B′ edges: cap already fired via R1 ⇒ `len(dl_buf)==0` ⇒ R2 precondition false (A.2:250/256) ✓;
    N=0 ⇒ no tail in both branches ✓; duplicate end ⇒ A.4.B:483 idempotent no-op, and A.2's impossible
    "R2 after R1" paragraph (A.2:264) contradicts R2.3 (m9).
F8. Assertions with no named observable: A.15 row 24's "armed send_guard_until = completion+15"
    (an **additional, uncounted minor observation of the same class as m7** — becomes m11 if
    enumerated; the verdict is unchanged either way); row 5's "increases by exactly N once" is
    test-local and fine; row 12's sentinel test is B1; row 2's per-segment semantics is M2.
F9. New: A.11's byte-cap path also does not state a pacer cancel, so the only two readings are
    (i) cancel ⇒ head unbucketed (B3) or (ii) no cancel ⇒ head sent post-terminal (B2). Either way the
    design fails a mandated invariant.
F10. New: `capture` of the sentinel test under RTL_DIAG unset (A.3:369) vs A.13's normative
    `RTL_DIAG = 1` acceptance configuration — the design never declares the sentinel test a separate
    non-acceptance harness run (m10).

## 5. FINDINGS

### BLOCKERS

**B1 — [A.3 Step 1 vs Step 3/Step 4.1–4.3] The M3 sentinel test is not decidable as written; a correct
single-store implementation can FAIL it.** Anchor: Step 1 (line 373) "substitute the store's `get()`
with a wrapper … (this is the hold point H)"; Step 3 (385–387) "breadth-first from `vars(conn)`,
following `gc.get_referents(o)` … **Do not descend into** (i) the origin `vars(conn)` dict itself";
Step 4.1 (390) "`future_audio_store` … and `future_audio_store ∈ hits`"; Step 4.3 (392)
"`sum(1 for x in future_audio_store if x is SENTINEL_ENCODED_PACKET) == 1`".
Falsification (reproduced): Step 1 presupposes the store exposes `get()`, i.e. an `asyncio.Queue`-like
object (the legacy `dl_q`). For `asyncio.Queue` (verified on 3.9.6, 3.12.13, 3.13.12):
`gc.get_referents(q)` = [int, deque, deque, int, Event, deque, type] — it does **not** contain the
sentinel, so `HIT(q)` is false and **assertion 1 fails**; the backing `q._queue` deque *is* a
`MUTABLE_CONTAINER` that directly holds the sentinel, so it is a second element of `hits` and
**assertion 2 (`hits == {future_audio_store}`) fails**; and `asyncio.Queue` is not iterable, so
**assertion 3 raises `TypeError: 'Queue' object is not iterable`**. No object simultaneously (a)
directly holds the sentinel and (b) exposes `get()`, except a bespoke deque-subclass store — a
precondition the document never states. Additionally, Step 3 is self-contradictory ("BFS from
`vars(conn)` following get_referents" vs "do not descend into the origin dict"), and on the
interpreter I was directed to use (CPython 3.13.12) `gc.get_referents(vars(obj)) == []` for an
ordinary instance (a *copy* of the dict returns the values), so a literal BFS seeds on nothing and
assertion 1 fails there too (this last leg does not reproduce on 3.12.13 / 3.11.15 / 3.9.6 — the
shipping image is python:3.12-slim — so it is an interpreter-fragility note, not the basis).
Because the PO designates this test as *the* mechanically decidable proof of the single store (PO M3),
its undecidability is BLOCKER-level.
Minimal fix: seed the walk from `vars(conn).values()` and exclude the origin dict from `hits`; define
`future_audio_store` as the object that *directly* holds encoded frames and pin its type (a
`collections.deque` or an explicit store class), then either drop `asyncio.Queue` from
`MUTABLE_CONTAINER` or canonicalise `asyncio.Queue` → its `_queue` and define assertions 2/3 on the
canonical container only.

**B2 — [A.4.A:416 + A.4.C:549 + A.2 R2.9:262 + A.9:812 + A.14:1116 + A.15 row 11] The mandated
terminal invariant `post_terminal_sends_total = 0` is falsified by the design's own normal-seal path.**
Anchor: A.4.A "A generation is **locally terminal** as soon as any of the following completes: **normal
seal** (A.9), cap seal (A.9), …"; A.4.C "A send is **post-terminal for the frame's OWNING generation**
if that generation is already locally terminal … at the instant `send_bytes` is invoked … Expected
value is **structurally 0**: every terminal transition resolves the `RESERVED_WAIT` head (BIT 1 …) and
the `QUEUED` frames (BIT 2 …) before the pacer can reach `send_bytes` again"; A.2 R2 step 9 / A.9
step 4 "the already accepted 1500-frame backlog drains normally".
Falsification: on a normal seal the generation *is* locally terminal (A.9 step 2, before the drain),
yet its accepted backlog is then sent (A.9 step 4). Every one of those drained frames satisfies
`frame.owning_generation.is_locally_terminal` at `send_start_at`, so the counter increments — up to
1500 on Test B′ and ≥ 1 on any response whose backlog exceeds `in_flight_frames` (i.e. every normal
response). The "structurally 0" argument cites BIT 1/BIT 2, which belong to the barge-in path (A.10)
and do not run on a normal seal; sealing does not flush. The PO states "Terminal invariant:
post_terminal_sends_total = 0"; under rev 7's own definitions that invariant cannot hold.
Minimal fix (either): (a) make the normal/cap seal take effect as *locally terminal* only at
generation quiescence (after the GenerationEnd is consumed), keeping "sealed" as the separate state
that tombstones late upstream terminals and late deltas; or (b) redefine
`post_terminal_sends_total` as "sends attempted after a flush-type terminal transition (barge-in,
abort, close, listen_start, upstream-close, send error, fatal stall, byte cap)" and state explicitly
that the sealed generation's own accepted-backlog drain is exempt.

**B3 — [A.11:878–886 + A.4.C:522 + A.4.B:481] The byte-cap path leaves the in-flight `RESERVED_WAIT` /
`SEND_AWAIT` head frame with no disposition rule, so the third closure cannot be shown to be 0 for
that path (mandated attack 13).** Anchor: A.11 "Required behaviour when it fires: … flush the accepted
store to `flushed_byte_cap_failure_frames`; discard the residue to
`residue_discarded_byte_cap_failure_bytes` …"; A.4.C "`RESERVED_WAIT` + {barge-in, abort, close,
listen_start, upstream-close, fatal-stall} ⇒ … reason-scoped flush counter" (BYTE_CAP_FAILURE absent);
A.4.B "For every reason there is a frame counter `flushed_<reason>_frames`".
Falsification: the byte-cap decision is evaluated after encoding, i.e. inside `_on_audio_delta`, while
the pacer normally holds a popped, not-yet-sent head. A.11 enumerates only the *store* flush. The
enumerated known-unsent reason set excludes BYTE_CAP_FAILURE, so the head is neither routed to
`flushed_byte_cap_failure_frames` (not enumerated) nor to `send_outcome_unknown_frames` (that requires
`SEND_AWAIT`). The disposition equation therefore has an unassigned term on the byte-cap path — the
same class of defect that was classified BLOCKER in rev 5 (A.3:79 "has no disposition bucket"). If
instead the pacer is *not* cancelled, the head is sent after the generation was invalidated
(post-terminal), violating B2's invariant. The design states neither.
Minimal fix: add BYTE_CAP_FAILURE to A.4.C's known-unsent reason set (RESERVED_WAIT head →
`flushed_byte_cap_failure_frames`; SEND_AWAIT head → `send_outcome_unknown_frames` + INVALID) and add
"cancel the pacer with reason BYTE_CAP_FAILURE" to A.11's behaviour list.

### MAJORS

**M1 — [A.5:683 + A.15 row 3] `wire_rate_excess_frames_max <= 1` is asserted "by construction", but the
argument is invalid and the metric can reach 2.** Anchor: A.5 "Because every send is ≥ its own absolute
deadline, `wire_rate_excess_frames_max <= 1` holds by construction for any floor slack (the +1
tolerance absorbs only the initial-credit frame)".
Falsification: being ≥ one's own deadline does not bound the anchor-relative count; the design's own
15 ms floor recovery produces runs of consecutive 15 ms intervals. With `excess_n =
−floor((L_n − δ_0)/20)` (no rebase, M8), excess = `ceil(δ_0/20)`, so a first-frame overshoot δ_0 ∈
[20,40) with full catch-up yields **2**. My simulation of the specified pacer returned per-run
`wire_rate_excess_max` = 2 in the tails for r1d_real and r1e_real (median 1), while slack=0 (20 ms
floor) would give ≤ 1. The PO gate is `<= 1`, so this can fail a compliant run.
Minimal fix: state the derived bound (it is `ceil(δ_first/20)` plus the recovery term) and set/justify
the tolerance accordingly, or reset the wire anchor at each pacer start (and define the anchor's
behaviour across pacer restarts, which is currently ambiguous).

**M2 — [§0.7.3 item 2:185 + A.5:640–649 + A.14:1171 + A.15 row 2:1209] The rate-gate locality rule has
no matching observable: `steady_pacer_rate_fps` / `pacer_mean_inter_send_ms_observed` are per-segment
quantities asserted as scalars.** Anchor: A.5 defines the two fields by a formula over *a* clean
segment; §0.7.3 item 2 says the gate "is evaluated over **every** qualifying clean steady segment … a
run with any qualifying segment outside the gates is FAIL"; A.14's "MAX / MIN OBSERVATIONS (aggregation
rules are normative)" lists both fields with **no** aggregation rule (unlike
`cancel_max_per_generation` etc., which say "max over generations"); A.15 row 2 compares the fields to
the gates as scalars.
Falsification: with ≥ 2 qualifying segments the named field has no defined value, so the acceptance
row is not evaluable from the named observable. This is the same defect class the document itself
fixed for the `*_per_generation` fields (A.14:1178–1181).
Minimal fix: report per-segment values plus explicit extrema
(`steady_segment_rate_fps_min/max`, `steady_segment_mean_inter_send_ms_min/max`) and reference those in
row 2.

**M3 — [A.3 assertion 5:396–398] The mandated static single-store test is not fully mechanically
decidable and is incomplete.** Anchor: "no … node whose identifier is in `{…, DL_QUEUE_MAX}` and no
string constant equal to `"qwen_closed"` used as a flush/residue reason. Comments and docstrings are
excluded by the AST (string constants are matched by value)."
Falsification: (a) "used as a flush/residue reason" is a semantic property an AST cannot decide — a
mechanical implementation degenerates to "no such string anywhere", which is stricter than the
normative text (A.3:347 allows it as a log label); (b) the string-constant clause covers only
`"qwen_closed"`, so the surviving legacy reference `getattr(config, "DL_QUEUE_MAX", 256)`
(turns.py:77) is a string `Constant`, not a `Name`/`Attribute`/`keyword`, and escapes the scan,
although PO #5 requires "no executable reference to the removed legacy audio-queue path".
Minimal fix: state the scan as "no occurrence of any member of the identifier set as a `Name`,
`Attribute`, `keyword`, **or string `Constant`**", and drop the undecidable "used as a reason"
qualifier (or replace it with "no `qwen_closed` string constant anywhere in the module").

### MINORS

m1. **A.1:208** "`δ` ≈ **0.98–1.3 ms**" — the lower bound is not reproducible: median δ = 1.027 /
1.071 / 1.214 by A.16's own method, and A.16:1251 states 1.03/1.09/1.23. No stated estimator yields
0.98. Fix: quote the reproducible range (≈1.03–1.25) or name the estimator that yields 0.98.
m2. **A.5:210 vs A.16:1250** — A.5 reports δ means 1.386/3.324/2.484 as "independently recomputed,
A.16", but A.16's stated per-pair estimator gives 1.386/3.298/2.472; the reported 3.324 reproduces only
the "mean steady gap − 20 − mean T" estimator. Fix: state which estimator is normative.
m3. **A.1:219** "a compliant rev-7 pacer has no sustained deficit by construction (deadline clock)" —
A.6 Case A re-phases the epoch for lateness 40–250 ms, which *forgoes* recovery of up to 40 ms per
rebase, so the aggregate rate is below 50 fps (the doc itself acknowledged ~0.5 % in §0.5). Fix:
weaken to "bounded, counted, and excluded from the clean-segment mean".
m4. **A.16:1255** "every envelope yields ≥ 1 qualifying clean ≥ 250-frame segment" — true only under
resampling; the raw r1d journal has 70 frames / 67 steady gaps, so a run on that evidence is
INSUFFICIENT by A.5's own no-vacuous clause. (r1e_mock 363 / r1e_real 479 do contain one.) Fix: state
"under resampling/repetition; the raw r1d sample is too short to qualify".
m5. **§0.7.1:160 vs A.14:1188** — the PO puts `pcm_fifo_partial_underfill_events` /
`pcm_fifo_partial_zero_pad_samples` under the "Part A /health contract"; A.14 explicitly excludes them
from the bridge `/health` payload (client sub-block). No functional gap, but it is a literal deviation;
fix: record the deliberate deviation in §0.7.1 (as was done for the other merge decisions).
m6. **A.12:998** "The counters are monotone; a single int read is atomic" — false across T3: the FIFO
is *rebuilt* (audio_codec.py:263–265 via `_configure_pipeline`/`reload_devices`), which resets the
instance counters, so the window delta becomes negative. Fix: define the scoped delta per FIFO
instance and end the window before/at a rebuild, or make the counters process-global.
m7. **A.12:981–984, 1002** — the T2 window end must be sampled "after the pull that emptied the FIFO",
but no observable (edge flag / timestamp / counter) is named that pins that instant; the design
simultaneously forbids I/O inside `pull`. Fix: name an observable, e.g. a monotone
`pcm_fifo_empty_pulls` counter or a `fifo_emptied_ts`, and sample on it.
m8. **A.5:625 / A.6:743** — the §2 fatal-stall text says "the step-2 head-frame clause applying to
QUEUED / RESERVED_WAIT only — there is no SEND_AWAIT head", while A.6 step 2 for the same trigger says
"For the §2 trigger there is no in-flight head frame". Fix: one wording.
m9. **A.2:264** — the "If R2 is ever observed for a generation that already entered the state via R1 …
`accounting_fault_events += 1`" paragraph describes a state that R2.3 (A.2:250/256) proves impossible
(`len(dl_buf) == 0`). Harmless as a tripwire, but it contradicts the invariant two paragraphs above.
Fix: label it explicitly as unreachable-by-construction.
m10. **A.3:369 vs A.13:1061** — the sentinel scenario normatively requires `RTL_DIAG` **unset**, while
the acceptance configuration normatively requires `RTL_DIAG = 1`; the design never declares the
sentinel test a separate (non-acceptance) harness run. Fix: state it explicitly in A.3 Step 0.

(Also noted, not counted: the removal list enumerates `_stop_pending` only at turns.py:84 and 297 while
it is also used at 541, 549, 573 and 612 — all inside removed or rewritten functions, so the plan is
complete; only the enumeration is line-incomplete.)

## 6. INDEPENDENTLY VERIFIED AS CORRECT

- Every A.16 numeric row recomputed from raw journals/diag bundles (median gaps, implied fps, T p50/p95
  in all three conventions, Opus packet stats, δ stats, 349.53 B/frame, frame 412, 3.236×, Q1/Q2/
  absorptive capacity, 323–385 ms).
- The 15 ms/5 ms claim (r1d ≈ 49.64–50.00, r1e ≈ 50.00 fps) and the 18 ms counter-claim (r1d 46.46–46.79,
  r1e_real 48.75–48.98 fps) — reproduced with my own recursion + resampling, method stated above.
- The clean-segment rate bound [49.55, 50.46] fps ⇒ §0.7.3 item 2 cannot false-fail a clean segment.
- CL-1 and CL-2 executed against the real `PcmFifo` (480/480/280/None).
- B1/R2 byte and frame closure reasoning for all N ∈ 1..959; "no 1501st frame"; each byte in exactly
  one bucket; peak ≤ 1500.
- M1 guard/rebase arithmetic for T = 10 ms; the `T > 250` SENT-then-PACER_FATAL_STALL ordering.
- The whole REMOVE/REWRITE list line-by-line against the current source: `dl_q` (turns.py:77 and all
  13 use sites), `DL_QUEUE_MAX` (config.json:6; main.py:24/53/75-76), `SENTINEL` (20), `_stop_pending`
  (84/297), `_enqueue_frame` (492), `_enqueue_sentinel` (498), `_drop_one_non_sentinel` (508),
  `_put_drop_oldest` (531), `audio_out_dropped` (counters.py:26/56; mutations 521/552),
  `_ensure_pacer` (503), `_cancel_pacer` (625), `_flush_downlink` (610) and its five call sites
  (111/233/245/336/651), `qwen_closed` (649/651/653), `send_cancel` sites (249-255, 340-349),
  `_on_qwen_closed` (648-659 incl. `upstream_errors` at 658).
- All client anchors: audio_buffer.py (pull 54-74, size==0 57-58, zeros 59, loop 61-73, push drop-oldest
  43-52), audio_codec.py (26/68-70, 192-239, 218-227, 226-229, 227, 239, 263-265, 272-297, 373-403, 382-384,
  395-398, 400, 420-426, 547), session.py (94-99, 117-119, 134-137), plugins/audio.py (141-150, 168, 174),
  protocol_manager.py (24, 42-44, 162-178 + the accurate over-cap wording), constants.py:93-94,
  stream_manager.py:64-72, audio_device.py:125-127, audio_converter.py:150-167.
- `turns.py:394-397` (`_make_frame` returns the raw packet when `diag.ENABLED` is false) — the A.3
  Step 0 premise; `diag.py:32`, `diag.py:351-355`, `diag.py:149/347/362`.
- Attack 15 file witnesses (mtimes + sha256 above).

## 7. VERDICT

DESIGN_REVIEW_BLOCKERS = 3
DESIGN_REVIEW_MAJORS = 3
DESIGN_REVIEW_MINORS = 10
DESIGN_REVIEW = REVISE

`PASS` is not available: `DESIGN_REVIEW_BLOCKERS != 0` (B1 M3 sentinel-test undecidability; B2
`post_terminal_sends_total = 0` falsified on the normal-seal path; B3 byte-cap in-flight frame with no
disposition bucket). All three are small, localised fixes to Part A; none requires abandoning the 15 ms
floor, the B1 seal rule, the M1 state machine, M2 or M3's intent — but Part A must be revised and the
design re-reviewed before implementation. No implementation was performed; the implementation gate
remains closed.
