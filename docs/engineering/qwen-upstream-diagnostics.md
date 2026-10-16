# QWEN UPSTREAM DIAGNOSTICS (observability-only) — `gateway/app/qwen.py`

Status: implemented under explicit narrow authorization (2026-10-08). Scope:
**diagnostics only** — no handshake payload, `session.update` payload, model,
provider, voice, VAD, audio format, timeout, reconnect policy, generation
ownership, barge-in or timing constant was changed.

## 1. Why

The human-acceptance Scenario 1 failure (2026-10-08 11:53) was traced to the
Qwen upstream session layer: `session.created` was received, `session.updated`
never was, an unidentified frame with no `type` arrived, and the upstream
closed every session after ~2000 ms (5/5 retries, then reconnect budget
exhausted) — with input transcription events = 0. The exact upstream rejection
reason was **not recoverable** because the frozen R-1f logging policy:

* only classified `type == "error"` frames (a type-less error envelope fell
  through as `event ignored: None`);
* discarded websocket close codes/reasons entirely;
* carried no per-connection handshake timeline.

This module adds exactly those three observability gaps — nothing else.

## 2. What is now logged (bounded + redacted)

| area | log line | fields |
|---|---|---|
| unidentified frame (no `type`) | `qwen unidentified upstream event …` | `conn`, `top_keys` (≤12 names, ≤40 ch), `shape` (`empty`/`error`/`other`), `error_present`, `error_type`, `error_code`, `status`, `message` |
| upstream error event | `qwen upstream error event …` | `conn`, `error_code`, `error_type`, `status`, `message` (counter behaviour unchanged) |
| benign cancel-grace error | `qwen benign cancel error ignored: <code> conn=…` | code + `conn` |
| websocket close | `qwen ws close …` | `conn`, `via` (`close`/`closed`/`error`), `close_code`, `close_reason`, `lifetime_ms`, `created`, `updated`, `update_sent`, `created_ms`, `updated_ms` |
| unexpected close (existing line, extended) | `qwen connection closed unexpectedly; scheduling reconnect (budget left N, conn=…, close_code=…)` | — |
| handshake timeline | `qwen connected … conn=…` / `qwen handshake incomplete conn=… elapsed_ms=…` | per-connection correlation id `qc<N>` |

Exception to the rule: the type-less frame is **still forwarded** to the
dispatcher after the diagnostic line (dispatch behaviour unchanged).

## 3. Redaction rules (applied BEFORE any text reaches the log)

1. Pattern table (hardened after independent review I1–I3):
   * URLs (`ws://`/`wss://…`) → `[url]`; `bearer <token>` → `bearer [redacted]`;
   * `sk-…` keys (≥2 chars after the prefix) → `[key]`; the prefix match is
     case-insensitive (`SK-`/`Sk-` variants included);
   * dash/underscore tokens ≥32 ch → `[token]`; base64-ish runs ≥24 ch →
     `[token]`; hex runs ≥32 ch → `[token]`;
   * `ws-…`-shaped ids (≥6 ch) → `[id]`;
   * bare alnum **12+ ch containing at least one digit** (any case) → `[id]`
     (digit-free English words are left intact; 24+ ch runs may already be
     labelled `[token]` by the base64-ish rule — label-only difference, both
     masked).
   * Anchoring uses Unicode-aware lookbehinds — **not `\b`** — so a credential
     written with **no separator directly after CJK/word text** is still
     masked (review I1 repro: `密钥sk-abc123def` → `密钥[key]`).
2. **Control characters (C0/C1 incl. NUL/ESC/BEL) are stripped to spaces**
   before matching (review I3), then the text is single-lined,
   whitespace-collapsed and capped (message ≤180, reason ≤120, token fields
   ≤80). Non-scalar values (dict/list/bytes) are **omitted**.
3. Raw upstream frames are never logged; keys are logged as names only. The
   helpers are **exception-safe**: a redaction error yields
   `[redaction-failed]` rather than raw text. Masking is shape-based
   best-effort by design — pattern non-matches pass through, so the test
   suite pins the adversarial shapes explicitly (C15 CJK-adjacency,
   C16 mixed-case ids, C17 control characters — added after the independent
   review found the initial `\b`-anchored patterns bypassable).

Never logged (per authorization): API key, bearer token, workspace id, full
websocket URL, raw audio / PCM / Opus payload, transcripts, full instructions.

## 4. What did NOT change (freeze checks)

* handshake / `session.update` payload — pinned by test `G5`;
* `SESSION_CREATED_TIMEOUT 5.0` / `CANCEL_GRACE_S 3.0` / defaults — pinned by `G6`;
* forwarding map — errors and malformed frames are still NOT forwarded;
  normal and type-less frames are still forwarded (`C02/C03c/C04c/C06/C07`);
* counters — malformed `+1`, error `+1`, benign-grace `0`, type-less `0`
  (`C03b/C07/G3/G4`); reconnect / budget logic untouched;
* audio / pacing / generation / barge-in code paths untouched (diff audit).

## 5. Tests

`gateway/tests/qwen_diag_tests.py` — synthetic only (stub websocket /
`aiohttp.WSMessage`; **no network, no Qwen session**): 14 numbered cases
(C01…C14: normal handshake, structured errors, missing-`type` error, nested
error, unexpected fields, malformed frame, normal/abnormal close, 2 s
premature close, empty reason, fake key / workspace / payload redaction) plus
guard checks (G1…G9 incl. a global secret scan over every captured record).

```
cd gateway
DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python tests/qwen_diag_tests.py
# QWEN_DIAG_TESTS: 35 checks, 35 PASS, 0 FAIL
```

Regression evidence for this round: R1F_REGRESSION 179/180 (1 documented
macOS dev-libopus `OpusError` env sentinel; the intermittent 2-fail variant is
also baseline-proven), CLIENT_UI_INTEGRATION 19/19, BEHAVIOR1_TESTS 111/111,
PRODUCT_V1_INTEGRATION 33/33, RED_F_ROUND1 123/123, RED_F_ROUND2 20/20,
RED_F_ROUND3 27/27, ADMIN_SECURITY_TESTS 29/29, QWEN_DIAG_TESTS 35/35.
(Evidence dir, local: `docs/engineering/product-v1/adversarial/evidence/qwen-diag/`.)

## 6. Rollback

* Code: `git revert` of the diagnostics commit (single file `qwen.py` +
  test file + this doc). The file hash before the change:
  `qwen.py 2727bc628c4dce9b881780ea51c8f63ec262f36ce2b3349dd05730a1f993ab1d`.
* Sidecar: image tag `xiaozhi-product-v1-sidecar:pre-diag` (the closure-round
  image) kept on the NAS for one-command rollback.

## 7. Interpretation notes for the controlled retest

When the product owner runs the authorized retest, the first failed session
will now emit (bounded + redacted):

* `qwen unidentified upstream event conn=qcN top_keys=… error_code=… message=…`
  → the upstream's actual refusal reason if it ships in the type-less envelope;
* `qwen ws close conn=qcN via=… close_code=… close_reason=… lifetime_ms=…`
  → exact close semantics (e.g. `1005`/`1008`/`1000`) and whether
  `session.updated` was ever seen.

No automated real-Qwen session is created by this change; the retest remains
product-owner-initiated only.
