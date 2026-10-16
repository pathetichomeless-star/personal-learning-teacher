# R-1f IMPLEMENTATION — CONSOLIDATED FINAL REPORT (Lead)

> **【链权威入口 · 2026-10-13】** TASK_ID = R1F-AUDIO-REGRESSION（已结项历史任务）。本文件=终态实施报告（consolidated final，
> rev-9 DESIGN_REVIEW=PASS）；同目录 `r1f-human-test-closeout.md`=真机语音测试结项。rev3–rev9 审查件、rev7–9 PO 决策原件、
> `r1f-agent-b-playout-audit.md` 等共 15 份按「独立审计证据/PO 决策原件」例外保留、正文不合并（收敛登记见 `docs/PROJECT_WORKLOG.md`）。
> 后续 Agent 默认读本文件与 closeout 即懂 R-1F 全历史。

Date: 2026-10-07 (Asia/Shanghai) · Authority: the R-1f implementation authorization

(rev-9 rev-9 DESIGN_REVIEW = PASS, 0 blockers / 0 majors / 5 minors).

Deliverable state: **shipped lab build = `:r1f-final` = `sha256:1b341ddb…ccd3`**, healthy.



---



## 1. IMPLEMENTATION VERDICT



**The rev-9 design was implemented faithfully inside the locked boundaries; all Phase-2/3

deterministic and runtime gates are green; the Phase-4 real-Qwen smoke reconciles exactly; the

independent 5-lane audit and two fresh Agent-F rounds were closed.**

`R1F_IMPLEMENTATION_REVIEW = PASS` (fresh Agent F, 0 blockers / 0 majors / 1 non-blocking record

minor, fixed). The autonomous loop stopped here, as mandated: human acceptance is NOT started

automatically, and `STATIC_AUDIO_ROOT_CAUSE = UNPROVEN` remains in force.



## 2. EXACT CHANGED FILES (before → after; full hashes in the manifest)



Bridge (`rtl-lab/`):

| file | before | after |

|---|---|---|

| app/turns.py | `4ee903fe…48d9` | `06a41cf9…ad7a` |

| app/counters.py | `7e2132d7…b032` | `b435ecaf…a622` |

| app/diag.py | `b969c39f…ce79` | `8cc31768…6ba0` |

| app/main.py | `8fe46a30…6b20` | `e19ee609…8f14` |

| config/config.json | `a7c1ff3e…8b61` | `670c1c9d…83c3` |

| docker-compose.yml | `4be36c81…a186` | `7859b8c4…9ba4` |



Client (`py-xiaozhi/src/`):

| file | before | after |

|---|---|---|

| audio_codecs/audio_buffer.py | `dfbd22dc…af40` | `b489a282…49cc` |

| audio_codecs/audio_codec.py | `08f50218…18de` | `e4014df6…fb85` |

| audio_codecs/audio_converter.py | `db620b28…8994` | `314d6a72…623d` |

| audio_codecs/rtl_client_telemetry.py | (new) | `b0229681…a944` |

| bootstrap/session.py | `18bcb809…ed13` | `8e216718…de4e` |

| core/protocol_manager.py | `d0c69d92…669f` | `d46d3e3c…6da0` |

| audio_processing/aec_engine.py | `3c3f0185…7532` | `60e726c8…14fd` |



Documentation / tests / evidence (all new or edited, hashes in the manifest):

`rtl-lab/r1f-design-review.md` (5 approved errata only), `rtl-lab/tests/{r1f_tests.py,

r1f_client_tests.py, r1f_runtime.py, r1f_real_probe.py}`, `rtl-lab/tests/assets/u{1,2,3}.pcm16k.raw`,

`rtl-lab/evidence/*` (7 artefacts), `rtl-lab-backups/r1f_baseline_20261007_010101/*`.

**Unchanged (hash-identical to baseline):** `app/http.py, app/ws.py, app/qwen.py, app/audio.py,

app/protocol.py, Dockerfile`.



## 3. SOURCE DIFF SUMMARY



- **turns.py — full rev-9 rewrite.** Single `collections.deque` downlink store holding raw encoded

  packets (+ GenerationEnd markers, meta records without packet references); generation map with

  SEALED_DRAINING/SEND_FORBIDDEN tiers, tombstone absorption and stale classification; one-shot cancel

  latch per generation; deadline-driven single pacer with E1–E4 media-clock epochs, 15 ms start-floor,

  slow-send guard (`completion+15`, `next_deadline=completion+20`), fatal-stall exit for lateness/T>250,

  post-wait lateness evaluation; per-segment extrema with no-vacuous clause; the three accounting

  closures (source/framer/disposition); store-cap routes R1/R1-mid-delta/R2; byte-cap 12-step lifecycle;

  four-bit barge-in sequence; reason-scoped flushes and residues; quiescence gauges.

- **counters.py — A.14 contract.** 60 cumulative counters, 7 gauges, 3 states, 16 max / 3 min

  observations, 2 aliases; derived `residue_discarded_pcm_bytes`; legacy `/health` keys preserved (114 keys).

- **diag.py — rev-9 observables.** Epochs, per-send epoch bookkeeping, raw steady-segment records,

  store/head/seal/cap/byte-cap/quiescence hooks, per-generation evidence fields, connection-registry

  eviction; R-1c probe-compatible fields retained.

- **main.py / config / compose — legacy downlink queue surface removed** (DL_QUEUE_MAX, drop-oldest).

- **Client.** PcmFifo instance identity + (I1)/(I2)/(I3) counters + lock-held snapshot; new

  `rtl_client_telemetry.py` playout-window tracker (T1 / T2_EMPTY_AT_STOP / T2_DRAIN_AFTER_STOP / T3 / T4,

  `__del__` emergency INVALID with deferred marker export, JSONL export with normative A.14 names);

  audio_codec T1/T3 hook points, decode/callback counters, all-empty-only zero-fill counting, deferred

  (loop-side) callback logging; session T2 stop hook; Q1 counters incl. teardown losses; `aec_far_dropped`.



## 4. TEST TOTALS (final shipped build)



| suite | scope | result |

|---|---|---|

| `r1f_tests.py` (bridge, in-image, RTL_DIAG unset) | A–S + CST groups (AST/sentinel/closures/R1/R2/mid-delta/byte-cap×3/one-shot/SEND_FORBIDDEN×8/dup-end/stalls/epochs/E4/segments/constants) | **187/187 PASS** |

| `r1f_client_tests.py` (macOS client interpreter) | T–Z (CL-1..4, T2-A/B, T4 race, cross-instance, `__del__`, zero-fill semantics, naming) | **38/38 PASS** |

| `r1f_runtime.py` (mock/synthetic, in-image) | 7 scenarios: clean_long, backlog_stress (cap), turns_50, rapid_barge, duplicate_stale, upstream_reconnect, client_teardown | **93/93 PASS** |

| `r1f_real_probe.py` (real Qwen, bounded) | phase 1 / phase 2 / final same-build phase 2 | all sub-turns true, closures 0 |



**Failed tests encountered (all fixed, none silenced):**

1. `AttributeError: module 'app.diag' has no attribute 'on_generation_seal'` (module-level diag calls) —

   55 failures in run 1; fixed (cycle 1).

2. Pacer never started from the delta path — P1*/G8/G13/I2.SEND_ERROR/I2.PACER_STALL/N*/O*/Q2/Q3

   (25 checks); fixed (cycle 1).

3. Mock-runtime vacuity (fake upstream 404 → no audio): 10 failures; fixed (cycle 2).

4. `upstream_reconnect` min-sent expectation (mid-response upstream close legally flushes unsent

   frames): 1 failure; fixed (cycle 3).

5. Five-lane audit: **1 BLOCKER + 3 MAJORS** — multi-frame deltas could admit beyond the 1500 frame cap

   (Lane 3); failed/unknown-send guard never armed (Lane 1); client `whole_block_zero_fill_count`

   over-counted the resampler short return and `__del__` INVALID was unobservable (Lane 4). Fixed

   (cycle 4) with new tests F21a-j, M6a-c, Z4-Z9.

6. Cycle-5 regression: the new `_gen_sync` again used a module-level `diag.<hook>` call (5 checks);

   fixed + a new mechanical AST guard (A6) so this class cannot pass again.



## 5. AUTONOMOUS FIX CYCLES (5 of max 5; no root cause >2 attempts)



| cycle | classification | fix | re-run |

|---|---|---|---|

| 1 | IMPLEMENTATION_DEFECT ×2 | `_ensure_pacer()` in the store-push path; `self.diag.*` | 173/173 |

| 2 | TEST_DEFECT | fake upstream served `/` + route; non-vacuity gates | runtime green |

| 3 | TEST_DEFECT | reconnect threshold + reason-scoped flush gate | 93/93 |

| 4 | IMPLEMENTATION_DEFECT ×5 | mid-delta cap guard; guard arming; flush attribution/tier; zero-fill semantics; `__del__` observability; deferred callback logging; Q1 teardown; unique gen ids; diag eviction; normative names | 186/186, 93/93, 38/38 |

| 5 | RECORD/DISPOSITION | manifest re-pin + declared build delta; per-generation evidence sync; harness rid scoping; AST guard A6 | **187/187, 93/93, 38/38** |



No acceptance gate, constant or rev-9 element was modified at any point (semantic diff of the Phase-0

errata contains zero gate/constant tokens).



## 6. FIVE-LANE FINDINGS (independent, read-only) AND DISPOSITION



- Lane 1 (pacer/clock): MAJOR — failed/unknown-send guard not armed → **fixed + tested**; MINORs

  (per-gen flush off-by-one → fixed; phase-1 mid-drain reading → annotated + verified post-drain).

- Lane 2 (barge-in/state): no blocker/major; MINORs — bystander generation tiering → **fixed**; head

  flush /diag evidence → **fixed**; `max(0,·)` clamp and named-bucket notes → accepted (documented);

  cross-connection gen-id collisions → **fixed** (process-unique ids).

- Lane 3 (accounting/queues): **BLOCKER** — in-batch admission guard used a stale backlog → **fixed**

  with the single-pass admit loop + `_store_cap_transition_mid_delta` + F21 tests; MAJOR (tripwire

  mis-routing) → resolved by the same fix; MINORs — R2-after-R1 re-fire branch (unreachable, accepted),

  tail byte-cap coverage → F21/G12/G17 closures verified, /diag attribution → fixed.

- Lane 4 (client audio): MAJORs — zero-fill over-count → **fixed + Z5/Z6/Z7**; `__del__` unobservable →

  **fixed + Z1c/Z4**; MINORs — polling approximation (accepted, inflate-only per erratum m-4), Q1

  teardown losses → **fixed**, naming drift → **fixed**, T1 delta artefact → **fixed**, callback logging

  → **fixed (deferred to the loop thread)**.

- Lane 5 (fault recovery): no blocker/major; MINORs — diag registry growth → **fixed**, gen-id

  namespace → **fixed**, deferred `_on_qwen_closed` interleave (not observed, accepted), missing

  success-path assertions → M6 added.



## 7. FINAL AGENT F (fresh independent instances)



- Round 1: `REVISE` — 1 MAJOR (record stale vs shipped build), 6 MINORS (per-gen evidence scalars,

  barge-in on the shipped build, unwritten suite log, harness noise, un-backed NAS claims, doc line ref).

- Round 2 (fresh instance): `REVISE` — 1 MAJOR (capture/manifest NAS identity disagreement — both

  record-level; the smoke had run on the cycle-4 image), 1 MINOR (hash suffix typo). Both corrected;

  the cycle-4 → cycle-5 delta declared explicitly.

- Round 3 (record confirmation): **`PASS` — 0 blockers / 0 majors / 1 MINOR** (one wording collision in

  the residual-boundaries bullet; fixed). Agent F independently recomputed the closures and the

  manifest hashes and confirmed the delta declaration is diagnostics-only.



## 8. ACCEPTANCE COUNTERS / GATES (final real-Qwen smoke; runtime values in parentheses)



```

MEDIA_FRAME_MS = 20.0 · MIN_SEND_START_INTERVAL_MS = 15.0 · PACING_SLACK_MS = 5.0   PASS

steady_pacer_segments_qualifying_total = 2 (>=1)                                  PASS

steady_segment_rate_fps_min/max = 49.998 / 49.999  (49.9957 / 49.9992) [49.5,50.5] PASS

steady_segment_mean_inter_send_ms_min/max = 20.00036 / 20.00073 (20.0003/20.0017) PASS

pacer_min_inter_send_ms_observed = 15.13 (15.11–18.55)  >= 14.999                  PASS

wire_rate_excess_frames_max = 0.0  <= 1                                            PASS

active_pacer_tasks_max = 1  <= 1                                                   PASS

slow_send_guard_violations = 0 · pacer_short_interval_count = 0                     PASS

post_terminal_sends_total = 0                                                      PASS

qwen_dispatch_errors_total = 0 · accounting_fault_events = 0                        PASS

encode_failed_frames = 0 · send_failed_frames = 0 · send_outcome_unknown_frames = 0 PASS

guard_dropped_pcm_bytes = 0 · safety_truncated_pcm_bytes = 0                        PASS

synthetic_tail_encode_failures = 0 · residue_discarded_store_cap_bytes = 0          PASS

byte_cap_failures = 0 · cap_transitions_total = 0                                   PASS

end_markers_max ≤ 1 · tts_stop_emissions_max ≤ 1 · cancel_max_per_generation ≤ 1    PASS

orphan_pcm_bytes = 0 · bad_base64_live_events = 0 · post_terminal_delta_events = 0   PASS

active_pacer_tasks_max ≤ 1 · audio_rebase_discarded_frames = 0                      PASS

```

Client gates (deterministic): CL-1 200/480 → +1 underfill / +280 zero-pad / +1 edge; CL-2 empty pull

moves nothing; CL-4 partial-with-leftover; T2-A/T2-B/T4/T3/T1 windows correct; cross-instance

rejected; `__del__` during an active window → `CLIENT_TELEMETRY_INVALID = 1`; the

`tts_playout_*` starvation falsifier provably fires when starved (CL-1/CL-3). A real-client run with

telemetry ON is required to certify the client half on real audio (human stage).



## 9. ACCOUNTING CLOSURE RESULTS



| run | source | framer | disposition |

|---|---|---|---|

| real phase 1 (build A) | 0 | 0 | 0 at quiescence (242 mid-drain reading reconciled in `r1f_real_phase1_postdrain_verify.txt`) |

| real phase 2 (build A) | 0 | 0 | 0 (`2261760 = 960·1820`, `1820 = 1226 sent + 594 flushed`) |

| real final (cycle-4 build) | 0 | 0 | 0 (`2356 = 1762 sent + 594 flushed`; per-gen 784/676/896 = 2356) |

| mock runtime (all 7 scenarios) | — | — | 0 in every scenario (incl. cap-saturated backlog_stress) |



## 10. REAL-QWEN SMOKE RESULTS (bounded; 4 paid sessions, well under ~15 min of audio; no soak)



- **Diagnostic session 1** (no response; probe lacked an always-on silence stream → server VAD never

  fired `speech_stopped`; input transcription only). Fixed; recorded in `r1f_paid_usage_justification.txt`.

- **Phase 1 (build A):** short answer ✓ → long-answer prompt ✓ → spoken barge-in during playback ✓

  (stop observed; `barge_in_sequences_total=2`, `barge_in_sequence_incomplete=0`,

  `send_outcome_unknown_frames=0`) → recovery turn ✓.

- **Phase 2 (build A + evidence fixes):** client abort mid-playback (stop in ~7 ms; `cancel_attempts=1`)

  ✓ → next turn ✓ → client WS reconnect ✓ → final turn ✓; closures 0/0/0.

- **Final same-build run (cycle-4 build, declared delta to cycle-5):** abort ✓ / turn ✓ / reconnect ✓;

  closures 0/0/0; 2 qualifying segments 49.998–49.999 fps; all negative gates zero.

- No credential/key/provider/endpoint change; credentials never printed; side instance removed after the run.



## 11. REMAINING MINORS (accepted, documented)



1. The shipped build's spoken-barge-in real evidence rests on the mock `rapid_barge` scenario; the real

   spoken barge-in ran on build A (cycle-4/5 edits do not touch that control flow). The human run will

   exercise it on the shipped build.

2. The shipped build's same-build real run is the pending human voice test (declared build delta:

   diagnostics-only).

3. `R2-after-R1` defensive branch still increments `cap_transitions` if ever reached (unreachable by

   construction; tripwire retained).

4. T2-B closure is poll-approximated (≤20 ms latency); inflate-only per erratum m-4.

5. `_release_head` clamps with `max(0,·)` (silently absorbs a would-be double disposition).

6. `_duplicate_end_residue_check` routes a sealed generation's stray residue to the UPSTREAM_CLOSED

   bucket (named, not blind).

7. `A.15` row 18's `session.py:117-119` line reference predates the client edits (hook now at 128-139);

   the contract was not edited beyond the five approved errata.

8. Per-generation `/diag` scalars are now synced, but `delta_events/delta_bytes` remain the primary

   per-gen byte evidence.



## 12. ROLLBACK PROCEDURE



1. **Source:** restore `rtl-lab-backups/r1f_baseline_20261007_010101/rtl-lab_pre_r1f_impl.tar.gz` over

   `rtl-lab/` and `py-xiaozhi_src_pre_r1f_impl.tar.gz` over `py-xiaozhi/src/`.

2. **NAS:** `docker image tag xiaozhi-realtime-lab-xiaozhi-rtl-bridge:pre-r1f xiaozhi-realtime-lab-xiaozhi-rtl-bridge:latest && cd /volume1/docker/xiaozhi-realtime-lab && docker compose up -d`

   (or restore the baseline tarball into the lab dir and `docker compose up -d --build`).

   Rollback tags: `:pre-r1f` (bfb4261730b7), `:pre-r1e`, `:pre-r1d`, `:pre-r1c-rev`, `:pre-r1c`.

3. **Client runtime config:** untouched by R-1f (no OTA/WS/AEC change); the client source rollback is

   the tarball in step 1.

4. **Evidence:** all raw logs/JSONs under `rtl-lab/evidence/`; hashes and the full change/fix record in

   `rtl-lab-backups/r1f_baseline_20261007_010101/CHANGED-FILE-MANIFEST.md`.



## 13. PROTECTED-STACK VERIFICATION (final)



`rtl-lab/evidence/r1f_nas_state_capture.txt`: all nine protected containers (english-learning-workbench-web,

-sync, <legacy-platform>, word-master, xiaozhi-esp32-server, xiaozhi-full-db, -redis, -server, -web) `Running=true`,

`Restarts=0`, `StartedAt` byte-identical to the R-1f baseline. Lab bridge healthy, Restarts 0, image

`1b341ddb…ccd3` (`:r1f-final`); `/diag` inert (`{"enabled": false}`); secret file `-rw------- 10001:10001

384 B`, mtime unchanged; no side instance left running; no credential leak (logs scanned throughout).



## 14. HUMAN TESTING



**Human voice testing is not started automatically and would be the next authorized stage.** It is the

only stage that can move `STATIC_AUDIO_ROOT_CAUSE` off `UNPROVEN`, and it must run on the shipped build

(`1b341ddb…ccd3`) with `RTL_DIAG = 1` on the bridge and client telemetry ON, with the Mac client's OTA

repointed (and restored afterwards) per the established procedure.



---



## FINAL STATUS BLOCK



```

R1F_DESIGN = PASS

R1F_IMPLEMENTATION = PASS

AUTONOMOUS_FIX_CYCLES = 5

STATIC_TESTS = PASS

UNIT_TESTS = PASS

MOCK_TESTS = PASS

INTEGRATION_TESTS = PASS

REAL_QWEN_SMOKE = PASS

FIVE_LANE_AUDIT = PASS (1 blocker + 3 majors found and fixed; minors dispositioned)

IMPLEMENTATION_BLOCKERS = 0

IMPLEMENTATION_MAJORS = 0

IMPLEMENTATION_MINORS = 8

R1F_IMPLEMENTATION_AUTOMATED_ACCEPTANCE = PASS

READY_FOR_HUMAN_VOICE_TEST = YES

STATIC_AUDIO_ROOT_CAUSE = UNPROVEN

```



STOP — human acceptance and the 6h/24h/72h/168h soaks are NOT started automatically.