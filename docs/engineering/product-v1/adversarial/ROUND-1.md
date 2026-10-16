# ROUND 1 — BROAD ADVERSARIAL DISCOVERY

Run: PRODUCT V1 ADVERSARIAL VALIDATION RUN. Revision under attack: `387ffcc`
(the Product V1 completion-run closure). Round 1 is discovery only; no product
source was modified during it.

Execution model: ten independent red-team agents (RED-A…RED-J), **read-only on
product source**, each with its own namespace
(`gateway/tests/adversarial/red_<x>/`) and its own raw report
(`reports/red_<x>-round1.md`). The Lead was the only writer, and only after the
round closed. All functional attacks ran against LOCAL `QWEN_MODE=mock`
instances or in-process aiohttp test clients; the NAS sidecar was never dialled
for a session, the production Workbench was replaced by a recording stub, and
no real-Qwen session was opened (budget stays 4/4, remaining 0).

## Start condition (verified before the round)

| condition | value |
|---|---|
| PRODUCT_V1_READY_FOR_SINGLE_HUMAN_ACCEPTANCE | YES |
| BLOCKERS / MAJORS open | 0 / 0 |
| worktree | CLEAN |
| isolated Product V1 test sidecar | deployed + healthy |

## Verdicts and metrics

| agent | surface | metric verdicts | findings |
|---|---|---|---|
| RED-A | auth / authorization | `AUTH_BYPASS = 0` (holds), `UNAUTHORIZED_WRITES = 0` (holds) | 4 INFO |
| RED-B | memory / privacy / isolation | `CROSS_USER_LEAKS = 0`, `RAW_TRANSCRIPT_STORAGE = 0`, `MEMORY_PROGRESS_DUPLICATION = 0` (hold); secret + partition defects found | **4 MAJOR**, 3 MINOR, 1 INFO |
| RED-C | knowledge / retrieval / poisoning | `DELETED_DOC_RETRIEVAL = 0`, `DISABLED_DATASET_RETRIEVAL = 0`, `CONTEXT_BOUND_VIOLATION = 0` (hold); framing defects found | **2 MAJOR**, 1 MINOR, 3 INFO |
| RED-D | persona / policy / admin mutation | `LOCKED_FIELD_MUTATIONS = 0`, `ROLLBACK_FAILURES = 0`, `DESTRUCTIVE_CONFIRMATION_BYPASS = 0` (hold); `UNVERIFIED_WRITES` **falsified** | **1 MAJOR**, 4 MINOR, 2 INFO |
| RED-E | workbench boundary | `WORKBENCH_WRITES = 0` (holds, stub request log: GET-only; 16/16 write verbs → 405) | 1 MINOR |
| RED-F | realtime / session state | `OLD_AUDIO_RESUME = 0`, `SESSION_STATE_LEAK = 0`, `GENERATION_OWNERSHIP_FAULT = 0`, `AUDIO_ARCHITECTURE_CHANGED = NO` (hold); `LATE_FINAL_MUTATION` **falsified** | **1 MAJOR**, 2 MINOR, 1 INFO |
| RED-G | concurrency / races | `CROSS_SESSION_CONTAMINATION = 0`, `STORE_CORRUPTION = 0` (hold); `LOST_UPDATE` **falsified (4)** | **5 MAJOR**, 1 MINOR |
| RED-H | admin UI / input safety | `NO_ACTIVE_CONTENT_FROM_DATA = PASS`, `DOUBLE_SUBMIT_SAFE = PASS`; `NO_PARTIAL_MUTATION_ON_FAILURE` **FAIL** | **1 MAJOR**, 3 MINOR, 1 INFO |
| RED-I | secrets / logs / fs / deployment | `SECRET_LEAKS = 0` (product surfaces), `REAL_LEARNER_DATA_COMMITTED = 0`, `PUBLIC_EXPOSURE = 0` (hold) | **1 MAJOR** (non-product artifact), 3 MINOR, 3 INFO |
| RED-J | semantic / teaching boundary | `ACTIVITY_RESUME_FAILURE = 0` (holds); `PRECEDENCE_VIOLATIONS`, `HARD_RULE_WEAKENING`, `FAKE_PROGRESS_FROM_DATA` **falsified** | **3 MAJOR**, 2 MINOR, 1 INFO |

Round-1 totals: **18 MAJOR**, 0 BLOCKER, 20 MINOR, 13 INFO.

## What the round proved is already solid (negative results with coverage)

- **Auth**: ~40 header forms, the full truncation/prefix/suffix/case matrix, duplicate
  and comma-joined headers, CRLF injection / obs-fold / header smuggling, path and
  percent-encoding tricks, method confusion, route enumeration (~22 backdoor probes),
  a no-oracle check on 401 bodies, token-reload semantics (unchanged source keeps the
  token, empty/missing fails closed) — all fail closed. Every successful write yields
  exactly one audit entry; every failed write leaves state and audit untouched
  (validate-before-mutate). The admin surface is absent from the audio app.
- **Workbench**: zero write shapes anywhere in product code; the recording stub saw
  GET-only traffic across adapter ops, conversation turns, prefetch and all four admin
  routes; "mark lesson 12 as passed"-style utterances produced no intent, no memory op
  and no fetch; degraded/500/malformed/giant/redirect-loop/reset were bounded and
  honest; provenance matched the stub exactly and expiry re-fetched.
- **Locked fields**: 19 provider/model/voice/VAD/frame/guard/slack/Opus/FIFO/
  generation/barge-in/audio vectors rejected outright (honest rejection, not
  stored-then-ignored).
- **XSS/injection sinks**: every DOM write in `admin/app.js` goes through
  `textContent`/`createElement`; no `innerHTML`/`eval`/`Function`/`srcdoc`/`on*`/
  data-driven `href|src|style` sink; store-controlled markup round-trips as inert JSON.
- **Realtime**: barge-in at first/middle/last chunk, double barge-in, cancel at every
  phase, duplicate/stale/unknown response ids, `audio.done` after `done`, malformed and
  out-of-order upstream events, 6 MiB deltas, abrupt closure at every phase, listen
  start during a response, reconnect storms with budget exhaustion, rapid activity
  switching — closures balanced, gauges zeroed, `post_terminal_sends_total = 0`, no old
  audio ever resumed, no cross-session state.
- **Frozen architecture**: 20/15/5 ms, the 1500/524288/250 caps, VAD/model/voice
  constants and the single-store sentinel all re-asserted by the reporters.

## Persisted raw artifacts

`reports/red_a-round1.md` … `reports/red_j-round1.md`, plus each agent's executable
suite under `gateway/tests/adversarial/red_<x>/`.
