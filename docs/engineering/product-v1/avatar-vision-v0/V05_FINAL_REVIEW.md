# V05_FINAL_REVIEW

date=2026-10-09 (UTC)
head=98a1c83 (avatar-vision-v0, baseline d5644f1)
reviewer=v05-final-review (read-only; only write = this file)

## BOUNDARY (freeze audit evidence)

`git diff d5644f1..98a1c83 --numstat`:

- `gateway/app/audio.py`, `gateway/app/turns.py`: **absent from diff → ZERO diff** (audio/VAD/turns path frozen ✓)
- `client/`: **absent from diff → ZERO diff** (real Mac client untouched this round ✓)
- `gateway/app/qwen.py`: **+80/−1** (brief said +52/−0; actual delta includes the prior-round V0 guards
  `_audio_seen`/`_vision_*` state + `send_image` five-guard chain, plus the V0.5 tail. The −1 is the
  EOF-newline fix at the file tail. All additive; fully accounted.)
- `gateway/app/http.py`: +62/−2 (−2 = docstring line replaced + EOF newline; rest is the additive
  `make_vision_handler` tail)
- `gateway/app/main.py`: +2/−0 (one additive route line + comment)
- New files: `tools/mock_client_gateway.py` (180), `prototypes/mock_client_preview.html` (250),
  `gateway/tests/v05_e2e_tests.py` (192), plus design docs and V0-era artifacts.

Working tree clean at HEAD=98a1c83b0d5e81e08698c7e0bd5e681df27641ee (only untracked `backups/`).

## ENDPOINT_SECURITY (auth/guards/status-mapping evidence)

Auth (gateway/app/http.py:56-64):
- Header `X-Vision-Token` compared against secrets/vision_token file via `hmac.compare_digest` ✓
- Fail-closed: `if not expected or not compare_digest(...)` → 401 when token file missing/empty ✓
- **Admin token NEVER accepted**: handler reads only `X-Vision-Token` vs the vision token file; no
  admin/auth import, no Bearer fallback. Design-mandated secret separation holds ✓
- Token value never logged or echoed: no log statements on the path; 401 body = `{"accepted": false,
  "reason": "invalid_token"}` (identical for missing/invalid — no oracle) ✓
- Route purely additive: `main.py:72` one `add_post("/xiaozhi/vision/", ...)`;
  turns.py/audio.py zero diff confirmed above ✓

Guards:
- HTTP layer: 320KB content_length cap before decode; strict JSON; `image_b64` type check;
  `b64decode(..., validate=True)` → 400s
- Qwen side (qwen.py:713-741): JPEG magic `ffd8ff`, raw ≤190KB, audio-first ordering,
  ≥5s interval, ≤6/min window, b64 ≤256KB; rejections never touch the audio path
  (E7 proves audio continues after a vision rejection)
- Status map (http.py:92-95): not_jpeg→415, too_large_raw/b64→413, rate_*→429,
  ordering_audio_first→409, not_connected→503, unknown→422 ✓ (E2/E5/E6/E8 assert each)

Registry (qwen.py:466, 812-828): `_ACTIVE_INSTANCES.add(self)` on the connect path (in the same
block that sets `_connected=True`); `submit_vision_image` scans the set and only forwards to an
instance with `_connected=True and _ws is not None`, else 503 `not_connected` ✓

Mock (tools/mock_client_gateway.py + prototypes/mock_client_preview.html):
- Binds 127.0.0.1 only (WS :18768, static :18769) ✓; static handler resolves + prefix-checks paths
- WS hello token gate before any mock.vision event; audio_append_sim must precede vision_image ✓
- All events namespaced `mock.*` ✓
- Preview page renders every dynamic string via `textContent` (messages, guard reasons, states);
  images only as `data:` URIs from canvas; **zero innerHTML usage** — no API-controlled string
  reaches innerHTML ✓

## TESTS

Fresh run (this review, against committed HEAD):
`cd gateway && DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python tests/v05_e2e_tests.py`
→ **8 checks, 8 PASS, 0 FAIL** (E1a/E1b 401s, E5 409 ordering, E8 415 not_jpeg, E2 413,
E4 full-chain 200 with byte-exact `input_image_buffer.append` round-trip, E6 429 after exactly 6
accepts under faked monotonic clock, E7 audio-path untouched). Assertions are real (status codes,
reason strings, byte round-trip) — no fabricated stats.

## DESIGN_CONFORMANCE (vs GATEWAY_PROTOCOL_DESIGN.md)

Docs verified present: MAC_CLIENT_AUDIT.md, GATEWAY_PROTOCOL_DESIGN.md,
AVATAR_AUDIO_SYNC_DESIGN.md, V05_SECURITY_QA_TEST_DESIGN.md ✓

Matches: route `POST /xiaozhi/vision/` on the 8111 plane (design ENDPOINT_SPEC:52-59); dedicated
X-Vision-Token ≠ admin bearer ≠ OTA test-token (design:61-75); body cap before decode;
handler pipeline order auth→cap→json→b64→delegate; rejection status table for all implemented
reason strings (design:108-118); fail-closed 401; no-audio-first → 409 semantics.

Deviations (doc/impl gaps, none security-defeating):
1. `session_id` resolution NOT implemented (design:39-48, 83, 118 wanted admin-registry walk +
   409 `ambiguous_session` / 404 `unknown_session`); implementation uses a module-level
   `_ACTIVE_INSTANCES` set instead. Acceptable for the single-device V0 deployment, but the
   design doc should be annotated.
2. Body cap 320KB vs design's 260KB (design:87). Both sit above the 256KB legal max and below
   aiohttp's 1MB default; loosening only admits slightly more pre-decode. LOW.
3. 200 body is `{"accepted": true}` — lacks design's `session_id`/`note` fields. Cosmetic.
4. Auth is an inline file-read rather than the specified TokenStore clone (no mtime cache,
   no X-Request-Id in 401). Functionally equivalent constant-time + fail-closed posture. LOW.

## FINDINGS

1. **LOW — registry never pruned on close** (gateway/app/qwen.py:706-710): `_register_active` /
   `_unregister_active` are defined but never called; `close()`/`_teardown()` (qwen.py:765-805)
   never discards from `_ACTIVE_INSTANCES`. Closed instances are retained for the process lifetime
   (reference leak). Functionally safe — `submit_vision_image` and `send_image` both check
   `_connected`, and `_teardown()` sets it False — but the fix is one line: discard in `_teardown`.
   Also removes the dead-code pair or wires it up.
2. **LOW — confusing token-path default** (gateway/app/http.py:55-56):
   `str(getattr(config, "workspace_id", "") or "") or "/app/secrets/vision_token"` — the app config
   has no `workspace_id` attribute, so this always falls back to the constant, but if a qwen-style
   config were ever passed, token_path would become a workspace-ID string → open fails → fail-closed
   401 for everyone. Simplify to `os.environ.get("VISION_TOKEN_FILE", "/app/secrets/vision_token")`.
3. **LOW (mock-only) — empty-token bypass in mock** (tools/mock_client_gateway.py:72,120): unlike
   the real handler, the mock lacks the `not expected` pre-check; with the token file missing,
   `compare_digest(b"", b"")` / `"" != ""` comparisons pass. Mitigated: 127.0.0.1 bind only and the
   token file is auto-created at startup. The real gateway has the guard (E1a covers it).
4. **INFO — coverage gaps**: E6 monkeypatches `qwen.time.monotonic`; `fresh_client` injects
   instances directly into `_ACTIVE_INSTANCES`, so the add-on-connect path (qwen.py:466) and real
   close-path cleanup are not exercised end-to-end. Chunked requests without Content-Length bypass
   the 320KB pre-check (aiohttp's 1MB default still bounds the body; decode remains bounded).

No auth bypass, no freeze violation, no API-controlled string into innerHTML, no fabricated
statistics.

## VERDICT

**PASS**

Approved as-is for the V0.5 mock-boundary scope. Recommended follow-ups (non-blocking, next slice):
prune registry in `_teardown` (F1), simplify token-path default (F2), annotate
GATEWAY_PROTOCOL_DESIGN with the session_id/body-cap deviations (D1/D2), add the `not expected`
pre-check to the mock for hygiene (F3).
