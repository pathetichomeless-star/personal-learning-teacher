# Catch-Up Review — Phases 1–2 · AGENT C (R-1f / audio non-regression)

Reviewer: AGENT C (read-only) · Date: 2026-10-07 · Repo `<project-root>` @ `5ed3132` (`main`)
Scope: prove the Phase-1 admin plane + Phase-2 transcript forwarding did **not** regress the realtime audio path.
Verdict: **PHASE12_C = PASS** (no audio-path regression found).

Pristine baseline used: `/tmp/admin1-baseline/gateway` (git archive of `ecb8209`) + `docs/admin0/baseline-manifest.sha256`.

## 1. Frozen surface (manifest `rtl-lab/*` → `gateway/*`)

Compared every `rtl-lab/app/*` + `rtl-lab/config/config.json` manifest hash against today's `gateway/…`:

```
IDENTICAL rtl-lab/app/__init__.py      -> gateway/app/__init__.py
IDENTICAL rtl-lab/app/audio.py         -> gateway/app/audio.py
IDENTICAL rtl-lab/app/counters.py      -> gateway/app/counters.py
IDENTICAL rtl-lab/app/diag.py          -> gateway/app/diag.py
IDENTICAL rtl-lab/app/http.py          -> gateway/app/http.py
CHANGED   rtl-lab/app/main.py          -> gateway/app/main.py
CHANGED   rtl-lab/app/protocol.py      -> gateway/app/protocol.py
IDENTICAL rtl-lab/app/qwen.py          -> gateway/app/qwen.py
CHANGED   rtl-lab/app/turns.py         -> gateway/app/turns.py
CHANGED   rtl-lab/app/ws.py            -> gateway/app/ws.py
IDENTICAL rtl-lab/config/config.json   -> gateway/config/config.json
```

Exactly the four expected files changed: `main.py`, `ws.py`, `turns.py`, `protocol.py`. `audio.py` (Opus
factories + 20 ms/480-sample framing constants), `qwen.py` (provider/model/voice), `counters.py`, `diag.py`,
`http.py` and `config.json` are **byte-identical** to baseline.

Pacing constants are byte-identical to baseline (`turns.py:32-34`):

```
MEDIA_FRAME_MS = 20.0
MIN_SEND_START_INTERVAL_MS = 15.0
PACING_SLACK_MS = 5.0
```

**`turns.py` diff is purely additive** (`diff -u`): (a) two new instance attrs `_ui_turn` / `_ui_tasks`;
(b) new sync `_ui_notify_interrupted()` (fire-and-forget) and async `_send_transcript()`; (c) an
`await self._send_transcript(...)` in `_on_qwen_event` after the existing `diag.on_transcript`; (d)
`self._ui_turn += 1` in `_on_response_created`; (e) `self._ui_notify_interrupted()` in
`_count_response_done` on `cancelled`. **No hunk touches the pacer (`_pacer`, lines 1412–1631), the send
loop, barge-in bits, epochs, genesis framing, Opus paths or accounting.** **`protocol.py` diff** is a pure
addition of `build_transcript()` (+ trailing-newline normalisation of the prior function). `main.py` adds the
ADMIN_ENABLED-gated admin listener start/stop; `ws.py` adds registry `register`/`discard` lifecycle calls.

## 2. Suites (run locally, `DYLD_LIBRARY_PATH=/tmp/opus131/lib gateway/.venv/bin/python`)

```
gateway/tests/r1f_tests.py            -> R1F_BRIDGE_TESTS: 180 checks, 179 PASS, 1 FAIL
                                         FAILED: B test_sentinel_harness EXCEPTION OpusError()   (pre-existing environmental)
gateway/tests/admin1_load.py          -> ADMIN1_LOAD: 29/29 PASS
                                         pacer_rebases=0 ; fps [49.9953,49.9953] ; closures residual 0
gateway/tests/client_ui1_integration.py -> CLIENT_UI1_INTEGRATION: 16/16 PASS
                                         "R-1f closures stay 0 with transcript forwarding"
```

`gateway/tests/r1f_tests.py` sha256 is identical to the pristine baseline
(`c02e13b83dbac1c9fcff59591bc0e70c0177f1332bfffcca3b44e53f1a7eebd6`, same as the manifest). The single opus
failure reproduces identically on the baseline — environmental, not a regression. `admin1_load.py` and
`client_ui1_integration.py` are the new Phase-1/2 test files (absent from `ecb8209`).

## 3. No cross-task interaction with the audio path

- **Pacer isolation.** The pacer runs in its own task: `pacer_task = asyncio.create_task(self._pacer(pid))`
  (`turns.py:1303`); it is fed only from the store (`_store_pop`). Transcript forwarding lives in
  `_on_qwen_event` (`turns.py:536`), which is awaited from the Qwen reader task only
  (`qwen.py:286 → 375 await self.on_event(obj)`) — a different task from the pacer. A slow transcript send
  blocks only later Qwen events, never pacing.
- **Bounded forwarding.** `_send_transcript` wraps the send in `await asyncio.wait_for(self.ws.send_str(msg),
  2.0)` and swallows all exceptions — bounded, non-fatal.
- **Fire-and-forget notice.** `_ui_notify_interrupted()` uses `asyncio.ensure_future(...)` and returns
  immediately; it is invoked from the synchronous `_count_response_done`. It never blocks a caller.
- **Audio / Opus untouched.** `audio.py` has no app callbacks; it is byte-identical, and no
  `_send_transcript` / `build_transcript` / registry reference appears in `audio.py` or on the Opus path.
- **Registry is lifecycle-only.** `admin_sessions.register/discard` are called solely from `ws.py`
  connect/close (weak refs, no locks); row reads happen on the separate admin HTTP listener and mutate no
  gateway state.

## 4. Methodology (trimmed commands)

```
shasum -a 256 /tmp/admin1-baseline/gateway/app/<f> gateway/app/<f>            # per-file equality
while read hash path; ... gateway/${path#rtl-lab/} ... < baseline-manifest.sha256  # manifest cross-check
diff -u /tmp/admin1-baseline/gateway/app/{turns,protocol,main,ws}.py gateway/app/<same>  # additive-diff proof
sed -n '32,34p' /tmp/admin1-baseline/gateway/app/turns.py ; sed -n '32,34p' gateway/app/turns.py
DYLD_LIBRARY_PATH=/tmp/opus131/lib gateway/.venv/bin/python gateway/tests/{r1f_tests,admin1_load,client_ui1_integration}.py
```

Read-only; the only file written is this review. No NAS access.

**PHASE12_C = PASS**

## Re-check after findings-scoped fixes (2026-10-07, HEAD `5ed3132`, working-tree fixes uncommitted)

Two defects were fixed by the Lead; both touch only the additive CLIENT-UI-1 surface.

**1. `gateway/app/protocol.py`** — `diff -u` vs `/tmp/admin1-baseline/gateway/app/protocol.py`: a single hunk
(1 `@@`), 20 added content lines — all of `build_transcript`, which now `return json.dumps({...},
ensure_ascii=False)` (was a raw dict). `import json` was already present in both. `build_hello` (baseline
lines 31–43) and `build_tts` (46–50) are **byte-identical**; `parse_json`/`new_session_id` untouched; the
only other delta is the pre-existing trailing-newline normalisation of `build_tts`'s return line.

**2. `gateway/app/turns.py`** — `diff -u` vs pristine baseline adds `import json` and, inside
`_send_transcript` only, a two-line defensive guard:

```
            if not isinstance(msg, str):        # defensive: never send a dict to send_str
                msg = json.dumps(msg, ensure_ascii=False)
```

All other CLIENT-UI-1 hunks are unchanged since my review (attrs, `_ui_notify_interrupted`, forwarding call,
turn-key increment, interrupted notice). No pacer/`_pacer` (1412–1631)/send-loop/accounting/barge-in/Opus
section was touched. Locked constants still `MEDIA_FRAME_MS = 20.0`, `MIN_SEND_START_INTERVAL_MS = 15.0`,
`PACING_SLACK_MS = 5.0` (now `turns.py:33-35`, shifted by the new import).

**Suites re-run:**
```
gateway/tests/r1f_tests.py              -> R1F_BRIDGE_TESTS: 180 checks, 179 PASS, 1 FAIL (B OpusError, environmental)
                                           (r1f_tests.py sha256 still == baseline c02e13b8…)
gateway/tests/client_ui1_integration.py -> CLIENT_UI1_INTEGRATION: 19/19 PASS
                                           (adds "wire payloads are JSON strings of type=transcript")
```

No audio/regression impact. **PHASE12_C = PASS**