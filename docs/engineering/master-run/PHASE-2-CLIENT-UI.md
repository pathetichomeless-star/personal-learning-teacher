# PHASE 2 — CLIENT-UI-1 (conversation transcript UI)

Implemented: 2026-10-07 · Scope: learner-facing conversation text in the py-xiaozhi client
(`client/`), driven by mechanically observed provider events. No UI change touches audio.

## 1. Read-only audit first (as required — no invented event types)

| question | mechanical answer (file:line) |
|---|---|
| Qwen input-transcription events | `conversation.item.input_audio_transcription.delta` and `.completed` — mapped in `gateway/app/turns.py:75-87` (`_transcript_args`) |
| Qwen output-transcription events | `response.audio_transcript.delta` / `.done` — same mapper (`turns.py:88-90`) |
| gateway event handling | `Connection._on_qwen_event` (`turns.py:521-527`) fed the four events to diagnostics |
| current client text hook | `client/src/plugins/ui_presenter.py:107-109` → `set_chat_text()` for inbound `tts`/`stt` messages; viewport contract `client/src/ui/shared/viewport.py:26` |
| existing chat UI | GUI `MainModel.ttsText` + `qml/panels/ChatPanel.qml` (single text block); TUI `chat_text`; CLI chat line |
| partial vs final | both available per role (delta = partial, `.completed`/`.done` = final) ✓ |
| interruption events | `_on_response_end` → `status == "cancelled"` → `counters.responses_cancelled` (`turns.py:878`) |

## 2. Implementation (additive only)

**Gateway** (audio path untouched — only additive forwarding):
- `protocol.py`: new `build_transcript(role, delta, text, final, interrupted, turn)` message type.
- `turns.py`: `_send_transcript()` (bounded send, never raises, **not gated on RTL_DIAG**),
  forwarding of the four events mapped to `user`/`assistant`, a per-connection turn key
  (`_ui_turn`, incremented on `response.created`), and an honest interrupted notice on
  cancellation via the sync-safe `_ui_notify_interrupted()` (fire-and-forget; no control-flow
  change in `_count_response_done`).

**Client** (shared core + per-frontend rendering):
- `src/ui/shared/transcript.py` (new): `TranscriptStore` — pure Python, bounded (200 bubbles),
  states STREAMING/FINAL/INTERRUPTED, duplicate + stale-turn protection, idempotent finals,
  local-abort fallback, `snapshot()`/`text_lines()`, **no persistence, no audio/protocol imports**.
- `src/plugins/ui_presenter.py`: routes the `transcript` message into the store and hands the
  bubbles to the viewport (`set_transcript`), plus `mark_transcript_interrupted()` /
  `reset_transcript()` hooks.
- `src/ui/shared/viewport.py`: default `set_transcript()` renders the last 12 turns into the
  existing chat display → every frontend (TUI/CLI) shows the conversation with no extra work.
- GUI: `MainModel.transcriptItems` (+ `transcriptChanged`) and `ChatPanel.qml` now renders
  role-styled bubbles with the streaming/interrupted markers and `positionViewAtEnd()` auto-scroll
  (empty state "等待对话...").
- No permanent transcript persistence by default; the current conversation display is **not** Memory.

## 3. Tests (all green)

| suite | result |
|---|---|
| `client/tests/test_client_ui_transcript.py` | **37/37 PASS** (Chinese/English text, punctuation, streaming→final, partial→completed replacement, barge-in interrupted honesty, no-stream interruption, local abort, duplicate/stale/malformed protection, bounds, reconnect reset, render helper, 50-partial single-bubble, no-audio-coupling + no-persistence guards, presenter routing, QML bindings) |
| `gateway/tests/client_ui1_integration.py` | **16/16 PASS** — the R-1f mock harness with an upstream that also emits the four transcript events; the gateway's real WS send path is recorded and **replayed through the client's own TranscriptStore** (two correct bubbles; barge-in yields an `interrupted` final notice with no fabricated text; R-1f closures stay 0) |
| `gateway/tests/r1f_tests.py` | unchanged vs baseline (180 checks / 179 PASS / 1 pre-existing environmental OpusError) |
| `gateway/tests/admin1_tests.py` | **80/80 PASS** |

## 4. Safety properties

- UI delivery is event-driven (one call per transcript message); **no per-frame UI work**, no
  polling of `/diag` or `/diag-summary`, no blocking of capture/AEC/Opus/WS/pacer/FIFO/barge-in
  (the store is pure-Python and the gateway send is a bounded, error-swallowing `send_str`).
- Interrupted assistant turns are represented honestly: the bubble keeps only the text actually
  received and is marked INTERRUPTED; no playback position is fabricated.

## 5. Honest limitations

- The QML bubble panel was validated statically (bindings/states/auto-scroll asserted in the test
  suite) and by code review; a live GUI rendering pass is part of the human acceptance (Phase 13)
  because this environment cannot run a Qt GUI headlessly.
- The client's own dev venv was not re-created during this phase (`uv sync` will be needed before
  a human run) — operational note, not a defect.

**PHASE 2 = PASS → continue to Phase 3 (Qwen `session.update` capability spike).**