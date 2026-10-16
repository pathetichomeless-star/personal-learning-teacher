# Catch-Up Review — Phases 1–2 · AGENT E (final, fresh, read-only)

Reviewer: AGENT E (no prior context) · Date: 2026-10-07 · Repo `<project-root>` @ `5ed3132` (`main`, local-only, + uncommitted catch-up fixes)
Scope: independently judge whether Phases 1–2 are safe to accept and whether the catch-up findings are truly closed.
Verdict: **PHASE12_E = FAIL** — one catch-up finding (B / reconnect transcript reset) is **not truly closed**.

## 1. Uncommitted surface (own `git status`/`diff`)

Tracked, modified — exactly the expected phase surface:
`client/src/plugins/ui_presenter.py`, `client/src/ui/gui/models/main_model.py`,
`client/src/ui/shared/transcript.py`, `client/tests/test_client_ui_transcript.py`,
`gateway/app/protocol.py`, `gateway/app/turns.py`, `gateway/tests/client_ui1_integration.py` (+77/−2).
Untracked: `docs/architecture/{HARDWARE-TARGETS,AVATAR-LAYER}.md`, `docs/engineering/master-run/reviews/`.
Nothing outside the phase surface changed.

R-1f frozen surface vs `docs/admin0/baseline-manifest.sha256` (`rtl-lab/app/*` → `gateway/app/*`), own `shasum -a 256`:

| file | baseline hash | current | verdict |
|---|---|---|---|
| audio.py | c2218a2c… | c2218a2c… | IDENTICAL |
| counters.py | b435ecaf… | b435ecaf… | IDENTICAL |
| diag.py | 8cc31768… | 8cc31768… | IDENTICAL |
| http.py | 63d26c20… | 63d26c20… | IDENTICAL |
| qwen.py | 75685213… | 75685213… | IDENTICAL |
| config/config.json | 670c1c9d… | 670c1c9d… | IDENTICAL |
| main.py | e19ee609… | 639305f0… | CHANGED (ADMIN-1 listener) — expected |
| ws.py | 1322a759… | dde9d427… | CHANGED (ADMIN-1 registry) — expected |
| turns.py | 06a41cf9… | 123cc223… | CHANGED (CLIENT-UI-1) — expected |
| protocol.py | 35b5fa7b… | 944e2d5a… | CHANGED (build_transcript) — expected |

Exactly the four expected files (`main.py`, `ws.py`, `turns.py`, `protocol.py`) differ. Pacing constants unchanged
(`turns.py` `MEDIA_FRAME_MS=20.0`, `MIN_SEND_START_INTERVAL_MS=15.0`, `PACING_SLACK_MS=5.0`). Own `diff -u` vs the
pre-monorepo original: the `turns.py` delta is **purely additive** (import json; `_ui_turn`/`_ui_tasks`; `_ui_notify_interrupted`;
`_send_transcript`; one forwarding `await`; `_ui_turn += 1`; interrupted notice) — no pacer/send-loop/barge-in/epoch/Opus hunk.

## 2. The D defect is really closed — verified by own probe

`build_transcript` (`protocol.py:52-69`) returns `json.dumps({...}, ensure_ascii=False)`; `_send_transcript`
(`turns.py:345-360`) adds `if not isinstance(msg, str): msg = json.dumps(msg, …)` before `ws.send_str`.
Own minimal probe (stub ws + `Connection._send_transcript`, bypassing `__init__`):
`build_transcript` type = **str**; three sends reached `send_str` as **str**, each `json.loads` round-trips with
`type=="transcript"`; forcing `build_transcript` to return a dict still results in a **str** on the wire.
⇒ A real client would now actually receive the transcript messages. **D's finding is closed.**

## 3. B findings — store closed, but the reconnect fix is NOT wired end-to-end

Independently re-ran all four falsifications; all **fail to falsify** at the store level: duplicate final (identical
and marker-only) → `None`; late delta after FINAL → `None`; interrupted-on-FINAL → `None`, state stays FINAL;
interrupted during STREAMING keeps received text; older-turn stale → `None`. Client store + GUI fixes are correct.

**However — the reconnect-reset fix is dead code on the real client path.** The Lead added, in
`ui_presenter.show_protocol_message`, `if msg_type == "hello": self.reset_transcript()`. But the real dispatch
(`client/src/protocols/websocket_protocol.py:213-218`) **intercepts `hello` before** the generic path:
```
if msg_type == "hello":  await self._handle_server_hello(data)
else:                    self._on_incoming_json(data)   # -> presenter.show_protocol_message
```
`_handle_server_hello` (`:349-372`) only sets `hello_received` and calls `_on_audio_channel_opened`; it never
forwards to `on_incoming_json`/`notify_incoming_json`. No other caller of `reset_transcript()` exists (grep: only
this one site), and no subscriber to `AUDIO_CHANNEL_OPENED`/`PROTOCOL_CONNECTED` resets the store; `UIPlugin` does
**not** override `on_protocol_connected`. Own probe (presenter + fake viewport, real dispatch shape): reconnect
after turns 1–4 → new-session turn 1 **silently dropped as stale** (bubbles stay 4); only when `hello` is delivered
directly to the presenter does reset fire and turn 1 apply.

⇒ B's original blocker ("reconnect does not clear the transcript → first N new turns silently dropped") is **still
falsifiable end-to-end**; B's post-fix re-pass verified only a direct `show_protocol_message({"type":"hello"})`
call, not delivery. Correct hook would be `UIPlugin.on_protocol_connected` (invoked on every `connect_protocol()`,
including reconnect). **Not a safety/audio/security issue — a client-UI correctness gap on reconnect.**

## 4. Suites (own runs, all as expected)

- `python3 client/tests/test_client_ui_transcript.py` → **43/43 PASS**
- `DYLD_LIBRARY_PATH=/tmp/opus131/lib gateway/.venv/bin/python gateway/tests/client_ui1_integration.py` → **19/19 PASS**
- `gateway/tests/r1f_tests.py` → **180 checks, 179 PASS, 1 FAIL** (baseline-identical; `B test_sentinel_harness EXCEPTION OpusError()` environmental)
- `gateway/tests/admin1_tests.py` → **80/80 PASS**

## 5. Phase-1 deployment reality (NAS, read-only, no restart)

- `xiaozhi-product-sidecar`: `running` / `healthy`, `RestartCount=0`, ports `28110→8110, 28111→8111, 28112→8112`.
- token `/volume1/docker/xiaozhi-product-sidecar/secrets/admin_api_token`: `-rw------- 10001 10001` (mode **600**, uid/gid **10001**), shell `test -r` → **NO** (unreadable).
- Primary lab `xiaozhi-rtl-bridge`: `StartedAt=2026-10-06T18:41:10.230297191Z`, `Restarts=0` — **matches expected**.
- Workbench `english-learning-workbench-web` `2026-10-04T01:56:08…`; legacy (`xiaozhi-full-*`, `xiaozhi-esp32-server`) StartedAt unchanged, all Restarts=0.

## 6. New decision documents — consistent with accepted architecture

`HARDWARE-TARGETS.md`: one shared core, "**Do not maintain two independent product codebases**", target-specific code
confined to `targets/**`/`ui/**`/`deploy/**`, gateway + ADMIN control plane "target-independent and must not be
forked", restructuring out of scope. `AVATAR-LAYER.md`: avatar = **PRESENTATION LAYER**, must not replace Qwen
**Audio↔Audio** / intent / memory / knowledge / **Workbench authority** / gateway; consumes CLIENT-UI-1 transcript +
turn key + tts/interrupted signals; no audio-path coupling, no new source of truth, target-specific rendering only.
Both are internally consistent with the accepted architecture and map cleanly onto the code that exists.

## 7. Residual risk not accepted before Phase 3

The reconnect transcript-reset wiring gap (§3): after a client reconnect (network drop, or the explicit
disconnect+reconnect path in `_on_protocol_reconnect_request`), the gateway restarts `_ui_turn` at 0 while the client
store keeps the previous session's turns, so the new session's early transcript turns are dropped until the turn
count exceeds the old session's. Fix: reset the transcript on `UIPlugin.on_protocol_connected` (or forward `hello`
to the presenter), and cover it with a test that exercises the real dispatch shape, not a direct presenter call.
Everything else (§§1,2,4,5,6) is accept-ready.

**PHASE12_E = FAIL**

## Independent verdicts

- **PHASE12_A = PASS** (sidecar/auth/runtime independently reproduced; agrees with A).
- **PHASE12_B = FAIL** (store fixes correct, but the reconnect finding B claimed closed is not wired on the real path).
- **PHASE12_C = PASS** (own hash/manifest + additive-diff checks reproduce C's conclusion).
- **PHASE12_D = PASS** (own wire probe confirms the dict→`send_str` defect is closed).

Read-only review; the only file written is this report.

---

# Post-fix re-review (2026-10-07, read-only) — E's reconnect finding

Re-verified after the Lead moved the reset onto the real lifecycle hook.

## 1. The fix is on the path that actually runs

- `client/src/plugins/ui.py:67-76` — `UIPlugin` now implements
  `async def on_protocol_connected(self, protocol)` → `self._presenter.reset_transcript()` then
  `await super().on_protocol_connected(protocol)`.
- `client/src/plugins/manager.py:217-227` — `notify_protocol_connected()` iterates `self._active_plugins()` and
  `await p.on_protocol_connected(protocol)` (guarded by try/except per plugin).
- Real trigger: `ConversationSession.connect_protocol()` (`bootstrap/session.py:167-174`) calls
  `self.plugins.notify_protocol_connected(self.protocol.protocol)` **after every successful `protocol.connect()`** —
  the initial connect and the reconnect paths (network re-connect, and the explicit disconnect+reconnect in
  `_on_protocol_reconnect_request`). `connect_protocol()` early-returns when the channel is already open
  (`if self.protocol.is_audio_channel_opened(): return True`), so a live session is **not** wiped mid-conversation.
- The presenter `hello` branch (`ui_presenter.py:136-140`) is kept but now explicitly documented as a
  **"Defensive fallback only"** that the live protocol layer never reaches (the `hello` intercept remains at
  `websocket_protocol.py:213-218`).

## 2. Safety on the audio path

The hook is a lifecycle callback (invoked once per connect by the plugin manager), **not** a per-message handler, and
runs on the connect coroutine — it cannot sit on the 20 ms send path. The dispatcher wraps it in try/except. On an
empty store `reset_transcript()` → `store.reset()` → `None` → no `set_transcript` / no viewport redraw (verified).
Even a raise would be logged and swallowed by the manager and could not reach the audio plane.

## 3. Suites (own runs)

- `python3 client/tests/test_client_ui_transcript.py` → **48/48 PASS** (up from 43; adds the wiring/hook check +
  reset-then-new-turn-1 behavioural case).
- `DYLD_LIBRARY_PATH=/tmp/opus131/lib gateway/.venv/bin/python gateway/tests/client_ui1_integration.py` → **19/19 PASS**.

## 4. Original falsification re-attempted — now genuinely closed

Own probe against the **real `UIPlugin`**: build a previous session (assistant turns 1–4 → 4 bubbles), then call the
exact method the manager calls (`await p.on_protocol_connected(None)` — i.e. a reconnect), then feed the new
session's turn-1 delta:

```
before reconnect bubbles: 4
after hook reset bubbles: 0
new-session turn1 accepted? True  [{'role':'assistant','text':'new session','state':'STREAMING','turn':1}]
hook safe on empty store: OK
```

⇒ The reconnect path is now closed without needing a live socket: reset fires on the real connect hook, and the new
session's lower-numbered turns are no longer mistaken for stale events. My prior blocker is resolved.

## 5. No other change to the audio path

`git diff --stat`: the previously reviewed gateway surface is unchanged (`protocol.py` 4, `turns.py` 3,
`client_ui1_integration.py` 34) — only client files grew (`plugins/ui.py` +11, `ui_presenter.py` +5,
`test_client_ui_transcript.py` +50). Prior-session `shasum -a 256` re-check: `audio.py`/`counters.py`/`diag.py`/
`http.py`/`qwen.py`/`config.json` remain **byte-identical** to `docs/admin0/baseline-manifest.sha256`.

## Updated verdicts (supersede the FAIL above)

- **PHASE12_A = PASS**
- **PHASE12_B = PASS** — the reconnect finding is now wired on the real lifecycle hook and behaviourally verified.
- **PHASE12_C = PASS**
- **PHASE12_D = PASS**
- **PHASE12_E = PASS** — no residual blocker before Phase 3.