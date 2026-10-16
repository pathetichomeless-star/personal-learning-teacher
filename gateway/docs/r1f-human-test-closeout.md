# R-1f HUMAN VOICE TEST — CLOSEOUT (Lead)

> **【链结项文件 · 2026-10-13】** TASK_ID = R1F-AUDIO-REGRESSION：本文件=真机语音测试结项记录（Lead，2026-10-07）。
> 链权威入口=`gateway/docs/r1f-implementation-report.md`；rev3–rev9 轮次件与 PO 决策原件例外保留，正文不合并。

Date: 2026-10-07 · Run window: 11:17–11:34 CST (armed 11:16:46, side container removed 11:45+)

Environment: NAS side instance `xiaozhi-r1f-humantest` = shipped build `:r1f-final` =

`sha256:1b341ddb…ccd3`, `RTL_DIAG=1` + `RTL_DIAG_CAPTURE=1`, real Qwen (model/voice unchanged),

secrets read-only; Mac py-xiaozhi client with `RTL_CLIENT_TELEMETRY=1`; real playback on the user's

Mac (Event Tap hotkeys in the user's own terminal).



## 1. HUMAN OBSERVATIONS (recorded verbatim — NOT converted to PASS/no-static)



```

VOICE_CONVERSATION_USABLE = YES

SPEECH_RECOGNITION       = USABLE

BARGE_IN                 = USABLE

STATIC_OR_BUZZ           = YES

STATIC_SEVERITY          = SLIGHT

STATIC_PATTERN           = INTERMITTENT

GENERAL_AUDIO_QUALITY    = USABLE

```

`STATIC_OR_BUZZ = YES / SLIGHT / INTERMITTENT` is recorded as a REAL observed residual symptom.

It is **not** reinterpreted as "no static" and **not** claimed solved.



## 2. MACHINE GATE SUMMARY



### 2a. Bridge (transport layer) — ALL GATES PASS

```

closures: source = 0 · framer = 0 · disposition = 0        (baseline→final /health deltas)

qualifying clean segments = 7  (frames 255/252/254/260/504/640/288)

  fps_min 49.986988 / fps_max 49.998119   (gate [49.5, 50.5])      PASS

  mean_min 20.000752 / mean_max 20.005206 ms (gate [19.80, 20.20]) PASS

pacer_min_inter_send_ms_observed = 15.060   (>= 14.999)            PASS

wire_rate_excess_frames_max = 0  (<= 1) · active_pacer_tasks_max = 1 (<= 1)  PASS

slow_send_guard_violations = 0 · post_terminal_sends_total = 0     PASS

qwen_dispatch_errors_total = 0 · accounting_fault_events = 0       PASS

byte_cap_failures = 0 · cap_transitions_total = 0                  PASS

encode_failed_frames = 0 · send_failed_frames = 0 · send_outcome_unknown_frames = 0  PASS

guard_dropped_pcm_bytes = 0 · safety_truncated_pcm_bytes = 0       PASS

end_markers / tts_stop / cancel maxima per generation <= 1 (1 / 1 / 0)  PASS

barge_in_sequences_total = 5 · barge_in_sequence_incomplete = 0    PASS

pacer_rebases = 3 (bounded) · pacer_fatal_stalls = 0 · pacer_short_interval_count = 0  PASS

turns = 20 · qwen_sessions = 1 · sent_confirmed_frames = 3713 = capture frames 3713   consistent

```

Per-generation: 20 generations, every framed generation 100 % delivered

(e.g. 100/100, 280/280, 244/244, 252/252) with one marker and one stop each; zero-frame

upstream-cancelled generations present (gen3 etc.) as expected.



### 2b. Client (A.12/A.15 row 17–18) — row 17 PASS, row 18 **NOT CLEAN**

```

18/18 playout windows valid, terminal_event = T1 (keep_listening/realtime path)

incoming_queue_dropped_packets = 0        (row 17)                PASS

pcm_fifo_dropped_samples       = 0        (row 17)                PASS

tts_playout_partial_zero_pad_samples = 0  (row 18, pacer-starvation falsifier)  PASS

tts_playout_whole_block_zero_fill_count = 1..4 per window (sum 42) (row 18)     **FAIL (!= 0)**

CLIENT_TELEMETRY_INVALID = 0 · no __del__-during-active-window marker            PASS

```

Mechanical context (facts, not reinterpretation): per window the FIFO reached empty

(drained edges 1–128) with `partial_zero_pad = 0` — i.e. the client consumed at ≈ the delivery

rate and produced only `whole_block` (all-empty) callback blocks, 20–80 ms per session; the T1

clear at tts-stop discarded 0–2400 samples (0–100 ms) of already-received audio. The row-18

gate is **reported as failed**, not weakened, and the design's gate text is unchanged.



### 2c. Human gate vs declared criteria

Declared PASS required `STATIC_OR_BUZZ = NO` → **human gate = NOT_CLEAN**.

`R1F_HUMAN_VOICE_TEST = PASS_FOR_TRANSPORT_LAYER / NOT_CLEAN_ON_AUDIO_RESIDUAL`

(bridge machine gates PASS; client whole-block term non-zero; static observed by the human).



## 3. ATTRIBUTION CANDIDATES FOR THE RESIDUAL SYMPTOM (HYPOTHESES — NOT PROVEN)



1. **Client tail emptiness**: 20–80 ms of all-empty callback output at every session end

   (the row-18 whole-block counts) → tiny silence gaps at turn boundaries.

2. **T1 clear truncation**: 20–100 ms of already-received audio discarded at tts-stop in

   realtime mode (`clear_audio_queue`) → mid-waveform cut at turn ends (possible click).

3. **FIFO operating near-empty** (1–128 drain edges per window) → high sensitivity to any

   delivery jitter; absorbs little.

4. Client/OS playout layers (CoreAudio buffering, resampler) remain `NOT_EXCLUDED`.

The bridge transport layer is clean on every gate, so the residual is **not** attributed to the

rev-9 pacing/accounting work by this evidence. `STATIC_AUDIO_ROOT_CAUSE = UNPROVEN` (unchanged).



## 4. DOCUMENTED OBSERVATION (no new label created)



`/diag` `assertions = {"MULTIPLE_PACER_VIOLATION": 17}` — this is the **legacy log-only detector**

(A.14: explicitly not an assertion basis). Pattern: `live = [3, 4], [3, 5], [3, 6], [3, 7] …`

(one pacer pid persisting in the detector's set on the earlier connection `3c666708-…`, so each

later pacer start logs). The authoritative gate `active_pacer_tasks_max = 1` PASSED, no two pacers

ever drained the store (per-generation sent/queued sums exact; closures 0; capture frames = sent

frames), and the final connection reports `live_pacers = []`. Classification: diagnostic-set

bookkeeping noise — informational, deferred to the admin/diagnostic-hygiene backlog (no label

created; the PO authorised only AUDIO-NOISE-1).



## 5. DEFERRED LABEL (as instructed)



```

AUDIO-NOISE-1 = DEFERRED / NON-BLOCKING FOR ADMIN DEVELOPMENT

STATIC_AUDIO_ROOT_CAUSE = UNPROVEN

```

No fix attempted in this phase (per instruction). No 6h/24h/72h/168h soak started.



## 6. ENVIRONMENT CLOSEOUT



| check | result |

|---|---|

| Mac config restored from `config-backups/config_backup_r1f_humantest_20261007_111645.json` | done |

| restored SHA256 | `02b8dffbf9277b39b8da4f329efdd8bad874cc2a82122f2edfc7797c7068a93b` = recorded original ✓ (OTA 8102 / WS 8100 / AEC true) |

| temporary side container `xiaozhi-r1f-humantest` | stopped & removed (only this container; 0 matches remain) |

| main realtime lab container | image `1b341ddb…ccd3`, StartedAt `2026-10-06T18:41:10Z` unchanged, Restarts 0, healthy, `/diag = {"enabled": false}` |

| protected stacks (9) | Running=true, Restarts=0, StartedAt byte-identical to the R-1f baseline (no unintended restart/drift) |

| soak | none started; no long-running test/soak processes on the NAS (0) |

| client process | not running (clean exit before collection) |



## 7. EVIDENCE INDEX (all under `rtl-lab/evidence/`)



`r1f_ht_baseline_health.json`, `r1f_ht_baseline_diag.json` (pre-run), `r1f_ht_final_health.json`,

`r1f_ht_final_diag.json`, `r1f_ht_capture_info.json`, `r1f_ht_container.log` (99 KB),

`r1f_ht_qwen_pcm24.raw` (3 797 760 B ≈ 79 s of Qwen source audio), `r1f_ht_sent_opus.bin` +

`r1f_ht_sent_opus.jsonl` (3 713 frames with `t_send`), `r1f_ht_client_telemetry.jsonl` (18 windows),

`r1f_ht_client_stdout.log`. Machine summary reproducible from these files (script logic in §2).