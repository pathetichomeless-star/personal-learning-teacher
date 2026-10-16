# RED-F (Realtime / Session State) — Adversarial Validation, Round 1

- **Agent**: RED-F (Realtime / Session State Machine)
- **Round**: 1
- **Surface**: `gateway/app/turns.py` (generation / pacer / single-store FSM,
  `handle_text`/`handle_binary`, barge-in, abort, close, `_on_qwen_event`),
  `gateway/app/ws.py`, `gateway/app/protocol.py`, `gateway/app/counters.py`,
  `gateway/app/audio.py`, and the real `QwenClient` reconnect path in
  `gateway/app/qwen.py`.
- **Method**: protocol simulation only. Deterministic events are driven straight
  into a real `turns.Connection` (real Opus codecs, stub websocket + stub qwen);
  an integration harness runs a LOCAL gateway instance (in-process aiohttp
  `TestServer`, loopback, `QWEN_MODE=mock`) whose real `QwenClient` speaks to a
  hostile mock upstream on `127.0.0.1:9277`, driven by a real WebSocket client.
- **Evidence script**: `gateway/tests/adversarial/red_f/red_f_round1.py`
  (+ hostile upstream `gateway/tests/adversarial/red_f/adv_mock_qwen_server.py`).
- **Result**: **123 checks, 121 PASS, 2 FAIL in ~33 s** (the 2 FAILs are the same
  finding, reproduced deterministically and end-to-end).

Reproduce:

```
cd <project-root>/gateway
DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python \
    tests/adversarial/red_f/red_f_round1.py
```

## Metric verdicts (asked to falsify)

```
OLD_AUDIO_RESUME = 0              [CONFIRMED]   (12 checks)
LATE_FINAL_MUTATION = 0           [FALSIFIED]   (2 checks -> finding R-F-1)
SESSION_STATE_LEAK = 0            [CONFIRMED]   (14 checks)
GENERATION_OWNERSHIP_FAULT = 0    [CONFIRMED]   (7 checks; see R-F-2 observation)
AUDIO_ARCHITECTURE_CHANGED = NO   [CONFIRMED]   (7 checks)
```

## Hard-lock compliance

- **No real Qwen.** The forbidden drivers were never run. All upstream traffic
  went to the local mock (`QWEN_MODE=mock`, `QWEN_WS_URL=ws://127.0.0.1:9277/...`).
  The NAS sidecar was never contacted; the Workbench was never contacted; no
  primary/legacy/MVP port was touched (only loopback + an in-process app).
- **Read-only on product source.** No file under `gateway/app/**`, `modules/**`
  or `admin/**` was modified (asserted by `ARCH5`: `git diff --stat` over those
  paths is empty; frozen-file sha256 recorded in the run log).
- **No secrets.** No token/key/`/app/secrets` value is read, printed or stored.
  The only bearer used is a throwaway local test constant for `/admin/metrics`.
- **Environment quirk (NOT a defect).** The known macOS dev-libopus
  intermittent `OpusError(bitrate)` on `OpusEnc24()` construction is worked
  around inside the test harness by a bounded construction retry (runtime
  monkey-patch of the codec factory in the test process only). Reported per the
  BRIEF as environmental, not a product fault.

## Findings

### R-F-1 · RED-F · round1 · **MAJOR** · surface: CLIENT-UI-1 transcript forwarding (`gateway/app/turns.py::_on_qwen_event` L576-581 → `_send_transcript` L356-371)
**A LATE assistant transcript FINAL for a superseded response is re-attributed
to the newest assistant turn.**

- **Precondition**: two responses in one connection. `r1` completes (or is
  cancelled); `r2` is created (`response.created` → `_ui_turn += 1`, L613). A
  `response.audio_transcript.done` for `r1` then arrives late.
- **Reproduction (deterministic, `red_f_round1.py` A5.1/A5.2)**:
  `created r1 → delta r1 → response.done r1 → created r2 →` feed
  `{"type":"response.audio_transcript.done","response_id":"<r1>","transcript":"late-final-text"}`.
  The client receives:
  `{"type":"transcript","role":"assistant","delta":null,"text":"late-final-text","final":true,"interrupted":false,"turn":2}`.
- **Reproduction (end-to-end, `red_f_round1.py` B3.2**, mock scenario
  `late_done_after_new`): same message observed on the real gateway websocket,
  plus a second stale mutation — `r1`'s late `response.done status=cancelled`
  after `r2` **completed** fires `_ui_notify_interrupted()` and the client gets
  an `interrupted:true, turn:2` final even though turn 2's own audio finished.
- **Expected** (`LATE_FINAL_MUTATION = 0`): a terminal/transcript event for a
  response that is not the current, live generation must not be stamped onto the
  current turn (it should be dropped, or attributed to `r1`'s own turn key).
- **Actual**: the late FINAL is emitted with the **current** `_ui_turn` (`2`),
  i.e. the finished/cancelled old response mutates the new turn's transcript
  state (`final`/`interrupted`) on the client.
- **Root cause**: `_on_qwen_event` forwards every transcript event via
  `_send_transcript(..., turn=None)`, which stamps `self._ui_turn`. The
  transcript path computes `_rid` from the event but **never checks** whether
  `_rid` is the current/live generation; `_ui_turn` only advances on
  `response.created`. There is no generation-ownership gate on the text plane.
- **Impact**: stale/incorrect transcript presentation to the learner (an old
  reply's text and an "interrupted" flag appear on the newest turn). No audio,
  security or integrity-counter impact — closures stay clean and
  `GENERATION_OWNERSHIP_FAULT` remains 0 on the audio plane.
- **Status**: OPEN (read-only scope; not fixed here). Remediation lead: scope
  transcript forwarding to the owning live generation (or at least stamp the
  event's `_rid` turn key, and suppress stale terminals).

### R-F-2 · RED-F · round1 · **MINOR** · surface: generation adoption on overlapping `response.created` (`turns.py::_on_response_created` L608-620)
**A second `response.created` while the first response streams does not
terminate the superseded generation; its already-queued audio still plays.**

- **Precondition**: `r1` has queued (not yet sent) audio frames; a second
  `response.created` (`r2`) arrives before `r1`'s terminal.
- **Reproduction (`red_f_round1.py` A2.11-A2.14)**: with the pacer stalled,
  admit 6 frames for `r1`, then `created r2`, then a further `r1` delta, then
  `response.done r2`; start the pacer and drain. Observed: `r1`'s 6 buffered
  frames are transmitted after `r2` became current (`gen1.sent == 6`).
- **Expected**: a new response should supersede the previous one (the old
  generation should be terminated/invalidated so its buffered audio does not
  continue into the new turn).
- **Actual**: `_on_response_created` unconditionally adopts `r2` as current but
  leaves `r1` untouched (`not gen1.send_forbidden and not gen1.sealed`); `r1`'s
  subsequent deltas are correctly dropped as STALE, but its already-queued frames
  are still drained and sent, so two responses' audio are concatenated.
- **Root cause**: no "single active response" enforcement on `response.created`;
  the previous generation is only terminated when its own terminal event arrives.
- **Impact**: with a well-behaved (serialising) upstream this cannot happen;
  adversarially it yields concatenated playback of two responses. All closure
  counters balance and ownership pointers (`_current_gen`/`current_resp_id`)
  remain correct, so no metric is violated — reported for hardening.
- **Status**: OPEN (observation; read-only scope).

### R-F-3 · RED-F · round1 · **MINOR** · surface: Qwen event dispatch (`turns.py::_on_qwen_event` L560-567)
**A non-string `delta` raises out of the diagnostic prelude and is swallowed at
the transport layer, uncounted.**

- **Precondition**: an upstream `response.audio.delta` whose `delta` is not a
  string (e.g. an integer).
- **Reproduction (`red_f_round1.py` A6.3)**: feed
  `{"type":"response.audio.delta","response_id":"r1","delta":12345}` —
  `_extra = {"delta_b64_len": len(obj.get("delta") or "")}` raises
  `TypeError: object of type 'int' has no len()` **before** the contained
  dispatch block.
- **Expected**: the malformed field is absorbed by the documented
  `bad_base64_live_events` / `bad_base64_stale_or_unmapped_events` buckets.
- **Actual**: the exception escapes `_on_qwen_event`. In production it is caught
  by `QwenClient._handle_text` and logged, so the connection survives
  (`red_f_round1.py` B7/B9 confirm the loop stays intact), but the event is
  neither counted as `bad_base64_*` nor as `qwen_dispatch_errors_total`.
- **Root cause**: the diagnostic `_extra` computation runs outside the
  exception-contained dispatch `try`.
- **Impact**: an adversarial upstream can emit events that are silently
  unaccounted in the integrity counters (no crash, no state corruption).
- **Status**: OPEN (read-only scope).

### R-F-4 · RED-F · round1 · **INFO** · surface: diagnostics `SEND_INTENT_UNRESOLVED` (`diag` surface, log-only)
On abrupt client close / abort while the pacer is in `SEND_AWAIT`, the diag
send-intent announced by `on_send_intent()` is left unresolved
(`DIAG_ASSERT SEND_INTENT_UNRESOLVED {"unresolved":2,"unresolved_invalidated_gen":0,...}`).
This is consistent with the frame being dispositioned as
`send_outcome_unknown_frames` (A7.2 asserts exactly 1) — the send outcome is
genuinely unknown, so the diag flag is self-consistent. Log-only; no control-flow
or closure impact. Noted for observability hygiene only.

## Coverage that found nothing (negative results)

Everything below was attempted and did **not** break the invariants. Names match
the checks in `red_f_round1.py`.

**Speech-event storms (A1)** — `started-started`, `stopped-without-started`,
`stopped-twice`, `started-during-response`, `started ×3 storm`: exactly one
barge-in each; no double-invalidate; old-generation deltas after barge-in land
only in `guard_dropped_pcm_bytes` (`admitted == 0`) → **OLD_AUDIO_RESUME = 0**.

**Overlapping / duplicate responses (A2)** — duplicate `response.done` ×3, and
`response.audio.done` after `response.done`: one marker, one TTS stop, no
`accounting_fault_events`, no `post_terminal_sends`, closures clean.
`response.done` for an unknown `ghost_rid` mid-stream: current generation
untouched, counted once. Duplicate `response.created` for the same rid: map
replaced, closures clean. Overlap scenario closures clean (see R-F-2 for the
audio-continuation observation).

**Cancel at every phase (A3)** — cancel before any audio, after the last delta,
and mid-stream: sealed cleanly, TTS never wrongly started, cancelled counted
once, late deltas STALE, closures clean.

**Barge-in at every phase (A4)** — barge-in during the first chunk, the middle,
and the final chunk of a response (1 / 5 / 12 preset frames): generation
invalidated `BARGEIN`, store flushed exactly (`flushed_bargein_frames` == preset),
store empty afterwards. Double barge-in then new response then another barge-in:
exactly two barge sequences, `r2` invalidated on its own barge.

**Late events (A5)** — late audio after cancel → `guard_dropped` only, 0 admitted,
0 sent (OLD_AUDIO_RESUME = 0). Late `response.done status=cancelled` for the
cancelled `r1` after `r2` started: `r2` stays current, not invalidated. (Late
transcript FINAL is the R-F-1 failure.)

**Malformed / out-of-order (A6)** — unknown event types ignored with no dispatch
error; `response.created` with a list, `response.done` with a string, null
`response_id`/null `delta`, invalid base64, truncated JSON, >64 KiB inbound JSON,
binary-where-text, and a 6 MiB single delta (bounded by the byte cap): all
contained; closures clean; `unsent_backlog_peak_frames ≤ 1500`.

**Session reset / pacer timing (A7)** — abort during `SEND_AWAIT`
(`send_outcome_unknown_frames == 1`, `in_flight == 0`); close during `SEND_AWAIT`
(residue gauges zero, closures clean); `listen start` during a response
(invalidated `LISTEN_START`, flushed); abort with no generation; upstream close
during a response (`UPSTREAM_CLOSED`, gauges zeroed, closures clean); abort
during seal-drain; rapid activity switching (4 turns × listen-start): closures
clean, quiescent.

**Cross-session isolation (A8)** — two connections keep independent stores;
a foreign rid fed to the other connection is UNKNOWN (orphan) and cannot create
frames; `close()` clears generation pointers and leaves no store/residue bytes →
**SESSION_STATE_LEAK = 0**.

**Integration through a real local gateway + hostile upstream (Part B)** —
`normal`, `bargein`, `late_done_after_new`, `close_mid`, `close_after_created`,
`close_immediate`, `interrupt_then_close`, `storm` (reconnect budget = 3,
exhausted), `overlap_responses`, `malformed_stream`, `duplicate_done`,
`audio_done_after_done`, `wrong_types`, `null_ids`, `binary_frame`,
`done_unknown_rid`, and a client-side abrupt close mid-response. Observed:
hello/tts handshake works; upstream close triggers a real `QwenClient` reconnect;
reconnect storm is budget-bounded and the gateway stays up; `/health` gauges
(`still_stored_frames`, `in_flight_frames`, `still_buffered_pcm_bytes`) return to
0 after every close; `/diag` reachable; `/admin/metrics` closures **delta == 0**
across the whole Part B run; `post_terminal_sends_total == 0` and
`still_buffered_pcm_bytes == 0` at the admin endpoint.

**Frozen architecture (`AUDIO_ARCHITECTURE_CHANGED = NO`)** — media frame 20 ms /
send-start guard 15 ms / pacing slack 5 ms / 1500-frame & 524288-byte caps /
250 ms rebase intact; no legacy AST tokens in `app/*.py`; provider/model/voice
and `server_vad 0.5 / silence_duration_ms 800` / `pcm16` / Opus unchanged; the
single-store sentinel walk finds **exactly one** mutable holder of an encoded
frame (`future_audio_store`); `git diff` over product source is empty.

## Artifacts written

- `gateway/tests/adversarial/red_f/adv_mock_qwen_server.py` (26 hostile upstream scenarios)
- `gateway/tests/adversarial/red_f/red_f_round1.py` (the suite)
- `docs/engineering/product-v1/adversarial/reports/red_f-round1.md` (this report)

No local instance is left running (all servers were in-process and torn down;
ports 9277 / 9210 verified free).
