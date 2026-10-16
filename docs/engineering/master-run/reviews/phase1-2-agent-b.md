# Catch-Up Review — Phases 1–2 · AGENT B (CLIENT-UI-1 transcript contract + interruption)

Reviewer: AGENT B (read-only) · Date: 2026-10-07 · Repo `<project-root>` @ `5ed3132` (`main`)
Scope: verify (not redo) the CLIENT-UI-1 transcript contract — gateway forwarding + client store + GUI.
Verdict: **PHASE12_B = FAIL** (original) → **PASS after fixes** — see §9 post-fix re-review.

## 1. Gateway side — verified (as designed)

| claim | observed |
|---|---|
| `build_transcript` additive message | `gateway/app/protocol.py:52-69` — `{type,role,delta,text,final,interrupted,turn}` |
| four real Qwen events mapped | `gateway/app/turns.py:75-92` `_transcript_args`: input `.delta/.completed`→`user`, `response.audio_transcript.delta/.done`→`assistant` |
| forwarding independent of `RTL_DIAG` | `turns.py:547-554` diag gated on `diag.ENABLED`; `turns.py:556-560` unconditional, `await` per transcript message |
| `_send_transcript` bounded + error-swallowing | `turns.py:344-357` `asyncio.wait_for(ws.send_str, 2.0)`, bare `except: pass` |
| `_ui_turn` incremented on `response.created` | `turns.py:590` (init `turns.py:188`) |
| interrupted notice fire-and-forget from sync `_count_response_done` | `turns.py:911-918`; `_ui_notify_interrupted` `ensure_future` (`334-342`) keeps the helper synchronous — no control-flow change |

## 2. Client store + routing — verified

- `client/src/ui/shared/transcript.py`: pure stdlib (no imports), states STREAMING/FINAL/INTERRUPTED,
  `_newest_turn` stale guard (`53-54`), idempotent final (`73-74, 83-84`), bounded `MAX_MESSAGES=200` (`125-126`),
  `reset()` (`101-106`), no persistence / no audio-protocol imports.
- Routing `client/src/plugins/ui_presenter.py:139-142`; fallback `client/src/ui/shared/viewport.py:26-39`.
- GUI `MainModel.transcriptItems` (`main_model.py:72-80`); `ChatPanel.qml` bubbles + `positionViewAtEnd()` (`30-31, 34-61`).

## 3. Suites (run, both green)

- `python3 client/tests/test_client_ui_transcript.py` → **37/37 PASS**
- `gateway/.venv/bin/python gateway/tests/client_ui1_integration.py` → **16/16 PASS** (real WS sends replayed through the client store)

## 4. Adversarial cases (own, inline — no files written)

| case | observed |
|---|---|
| delta AFTER a same-turn final | **appends to the FINAL bubble** (`"final answer"` → `"final answer LATE"`); state stays FINAL |
| final for an OLDER turn (4 < newest 5) | ignored (stale) ✓ |
| interrupted notice for an already-FINAL turn | **flips FINAL → INTERRUPTED** (can materialise via §5 collision) |
| repeated final / malformed / foreign | no-op ✓ |

## 5. BLOCKER — reconnect does not clear the transcript (rule falsified)

`reset_transcript()` / `mark_transcript_interrupted()` (`ui_presenter.py:121-130`) have **no callers**
(grep over `client/src`: definitions only). The store is owner-scoped to the long-lived `UIPlugin` presenter,
and reconnect (`bootstrap/session.py:175-198` disconnect + `connect_protocol`) opens a **new WS → new gateway
`Connection`**, so the gateway `_ui_turn` restarts at 0 (`turns.py:188`) while the client keeps old turns.

Inline simulation (old session turns 1–4, then post-reconnect turn 1–2):
```
old-session bubbles: 8   newest assistant turn: 4
post-reconnect turn1 delta applied? False     # silently dropped as stale
post-reconnect user turn1 applied? False
post-reconnect interrupted(turn2) applied? False
```
⇒ after any reconnect the first N new assistant/user turns (N = previous session's turn count) are
**silently dropped**, which is exactly the "reconnecting must clear without leaking state" rule failing.
(The store primitive `reset()` is correct — it is simply never invoked.)

## 6. Secondary findings

- `MainModel.__init__` (`main_model.py:22-31`) never initialises `_transcript_items`, but the getter
  (`73-74`) reads it → QML `model: mainModel.transcriptItems` raises on first panel load until a transcript
  message arrives (empty view + binding error, not a crash).
- Transcript send `await`s on the Qwen reader task (bounded 2 s): the "never blocks the audio path" claim holds
  only because of the bound/swallow, not by decoupling — acceptable but worth noting.

## 7. Confirmed non-issues

- UI path is event-driven: no per-frame work, no polling, no `/diag` access (grep `client/src` → none).
- Client transcript is in-memory only: no `open(`/`json.dump`/`sqlite`/`write(` in the store; `MainModel` holds a QVariantList, no file I/O.

## 8. Verdict

Gateway forwarding, the store contract, and both mandated suites are correct; single-session honesty rules
(no fabricated interruption text, no final-duplication, stale protection, idempotent final) hold.
The enumerated **reconnect rule is falsified end-to-end** (unwired reset → stale-turn silent drop, plus a
reachable FINAL→INTERRUPTED flip), and the GUI model has an uninitialised attribute. → **FAIL**.

**PHASE12_B = FAIL** (original, superseded)

## 9. Post-fix re-review (2026-10-07, read-only)

Fixes verified mechanically (code read + suites + own adversarial re-runs).

| fix | file | verified |
|---|---|---|
| 1. `hello` (new session) resets the transcript | `client/src/plugins/ui_presenter.py:136-139` | `show_protocol_message({"type":"hello"})` → store cleared; new session turn 1 then accepted (fake-viewport run) |
| 2. `MainModel._transcript_items` initialised | `client/src/ui/gui/models/main_model.py:23` | `self._transcript_items = []` now set in `__init__` |
| 3. late delta after FINAL ignored | `transcript.py:60-61` | `apply(delta, same turn)` after a FINAL → returns `None`; text unchanged |
| 4. interrupted never re-marks a FINAL turn | `transcript.py:166-167` | `apply(interrupted)` on an already-FINAL turn → `None`, state stays FINAL, text not fabricated |
| 5. `build_transcript` returns a JSON string + defensive serialise | `gateway/app/protocol.py:60-68` (`json.dumps`, `ensure_ascii=False`), `turns.py:356-357` | only caller `_send_transcript` (`turns.py:353`) handles both str/dict — no dict-to-`send_str` path remains |

Suites re-run: `test_client_ui_transcript.py` → **43/43 PASS**; `client_ui1_integration.py` → **19/19 PASS**.

Re-attempted falsifications (all now **fail to falsify** = fixed):
- late delta after FINAL → ignored (was appended);
- final for an older turn → ignored (unchanged, was already correct);
- interrupted notice for an already-FINAL turn → no-op, no fabrication (was flipping FINAL→INTERRUPTED);
- reconnect sequence (old turns 1–4, then reset) → cleared, new turn 1 applies (was silently dropped);
- duplicate final / malformed / bounds → no-op ✓ (unchanged).

Residual minor notes (non-blocking): `_transcript_items` is assigned *before* `super().__init__()` (harmless for a
non-Qt attribute, style nit); `_apply_interrupted` still appends to an empty INTERRUPTED bubble if real deltas
arrive for that same turn afterwards (honest text only, state unchanged) — not a stated rule.

**PHASE12_B = PASS**