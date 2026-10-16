GATEWAY_PROTOCOL_DESIGN — avatar-vision-v0
date=<2026-10-09 UTC>
author=<v05-gw-protocol (read-only design agent; this file is the only artifact written)>
scope=<client → gateway → Qwen image transport for V0.5, on branch avatar-vision-v0 @ HEAD>

EVIDENCE BASE (prior rounds, cited throughout)
- VISION_PROTOCOL_REPORT.md (docs/engineering/product-v1/avatar-vision-v0/): official
  `input_image_buffer.append` event (base64 JPEG, ≤256KB post-encode, raw ≤190KB recommended),
  commit coupling with `input_audio_buffer.commit`, audio-append-first ordering — all doc-verified
  verbatim from Aliyun Model Studio docs.
- gateway/app/qwen.py: `send_image()` already implemented with 5 guards (JPEG magic, raw ≤190KB
  [qwen.py:699,711], base64 ≤256KB [qwen.py:700,727], audio-first ordering [qwen.py:715-717],
  ≥5s interval + ≤6/min [qwen.py:697-698,718-725]). Tests: gateway/tests/vision_v0_tests.py 13/13.
- gateway/app/protocol.py:6 `MAX_JSON_BYTES = 65536` — the client WS text frame caps at 64KB,
  so a ~300KB base64 image CANNOT ride the WS JSON plane. This is the hard constraint that
  forces an HTTP-side transport.
- gateway/app/turns.py is the frozen client-WS dispatcher (audio/VAD/turns). NOT touched.
- Admin bearer token must NOT be reused for image auth; the OTA "test-token" (http.py:38) is a
  known-weak value and must NOT be reused either.

---

## TRANSPORT_CHOICE

**Additive `POST /xiaozhi/vision/` on the existing 8111 HTTP listener (gateway/app/http.py).**

Why HTTP on 8111, not the WS plane:
1. The WS JSON frame cap is 64KB (protocol.py:6); a 190KB raw JPEG encodes to ~253KB base64 —
   4× over the cap. Enlarging the WS cap would put a new 256KB allocation into every client
   frame parse (DoS surface on the frozen audio path). HTTP gives us per-request bodies with a
   route-local size cap and zero impact on turns.py.
2. The 8111 listener already serves device-facing endpoints (`/health` main.py:69,
   `/xiaozhi/ota/` main.py:70-71) — the route is registered in `create_app()` (main.py:67-77)
   with one additive line; turns.py dispatch (turns.py:494 `handle_text`) is untouched.
3. The Qwen image event is a per-session push, not a turn-control message: it belongs next to
   `send_append`/`send_cancel` in QwenClient (qwen.py:683-733), called from the HTTP handler —
   the same layering as admin routes calling into stores, never into the audio hot path.

**Session resolution (how the HTTP handler finds the live QwenClient):**
- `Connection` owns exactly one `QwenClient` (turns.py:266-267); live connections are already
  weakly registered in the ADMIN-1 registry (`admin/registry.py:28-78`, keyed by
  `conn_ordinal`, `session_id` at turns.py:432).
- V0 policy: the request MAY carry `"session_id"`. If absent: resolve when **exactly one** live
  connection exists with `qwen.connected == True` (single-device V0 deployment; ambiguity →
  409 `ambiguous_session`). If provided and not found / not qwen-connected → 404
  `unknown_session`. This uses a read-only weakref walk over `admin.sessions` (additive accessor,
  e.g. `registry.live_connections()`); the registry's observer-only invariant is preserved
  (no mutation of gateway state, registry.py:1-8).

---

## ENDPOINT_SPEC

### Route registration (mirrors main.py:69-76 pattern)
```python
# gateway/app/main.py, inside create_app(config):
app.router.add_post("/xiaozhi/vision/", partial(http.vision, config=config))
```
Handler lives in gateway/app/http.py (where `/health` and `/xiaozhi/ota/` already live).

### Auth — NEW dedicated token, mirroring admin/auth.py
- Secret: a NEW file `/app/secrets/vision_token` (sibling of admin's
  `admin/config.py:18 DEFAULT_TOKEN_FILE = "/app/secrets/admin_api_token"`; optional
  `VISION_TOKEN` env fallback). Loaded by a `TokenStore` clone of `admin/auth.py:21-84`
  (file-mtime reload, never logged, `hmac.compare_digest` at auth.py:84 — constant time).
- Header: `X-Vision-Token: <token>`. Constant-time compare, byte-equal.
- Fail closed: if the listener serves `/xiaozhi/vision/` but no token is configured → 401
  `auth_not_configured` (same posture as admin auth_middleware, auth.py:121-139).
- 401 body is IDENTICAL for missing / invalid / unconfigured (no oracle), including
  `X-Request-Id` (mirrors auth.py:97-118).
- Explicitly NOT: the admin bearer token (separate secret, separate blast radius), NOT the
  OTA `test-token` (public in http.py:38).
- Reuse note: implement as a small `vision_auth` module importing the existing `TokenStore`
  class (it is header-agnostic; only `_bearer()` is admin-specific) — one new `_header(request)`
  for `X-Vision-Token`. No change to admin code.

### Request
```
POST /xiaozhi/vision/            HTTP/1.1, 8111
X-Vision-Token: <token>
Content-Type: application/json

{"image_b64": "<base64 JPEG>", "session_id": "<optional XiaoZhi WS session_id>"}
```
- `image_b64` required; `session_id` optional (see TRANSPORT_CHOICE).
- Body cap enforced BEFORE base64 decode: reject any body where the raw request bytes exceed
  260KB (max legal payload = 256KB b64 + JSON envelope slack) → 413 `payload_too_large`.
  This is the route-local analog of protocol.py's WS cap; aiohttp default 1MB body limit is
  never reached because we check first.

### Handler pipeline (http.vision, strict order)
1. Auth (401 paths above).
2. Body read + size cap (413).
3. JSON parse — malformed → 400 `bad_json`.
4. `image_b64` present and str → else 400 `missing_image_b64` / `bad_image_b64_type`.
5. base64 decode (strict) → bytes → else 400 `bad_base64`.
6. Delegate to the target connection's `qwen.send_image(jpeg_bytes)` — ALL official guards
   (magic bytes, raw/b64 caps, ordering, rate) are re-enforced there; the HTTP layer adds NO
   duplicate limit logic beyond the body cap. Map the `(ok, reason)` pair per the table below.
7. Every call wrapped so that rejections NEVER touch the audio path (already the send_image
   contract, qwen.py:704; V7 test vision_v0_tests.py:163-170).

### Response shapes
Accepted — `200`:
```json
{"accepted": true, "session_id": "<sid>", "note": "commits_with_next_audio_commit"}
```
Rejected — status maps from `send_image` reason (exact strings from qwen.py:706-729):
| reason                 | status | client action                          |
|------------------------|--------|----------------------------------------|
| `not_connected`        | 503    | retry after reconnect; gateway tells device via WS if it has an out-of-band channel (V0: just retry on next speech) |
| `not_jpeg`             | 415    | re-encode as JPEG (client-side)        |
| `too_large_raw`        | 413    | downscale/recompress below 190KB raw   |
| `too_large_b64`        | 413    | (defensive; unreachable via raw cap)   |
| `ordering_audio_first` | 409    | speak first, then retry the image (see VAD_RACE_ANALYSIS) |
| `rate_interval`        | 429    | wait ≥5s since last accepted image     |
| `rate_per_minute`      | 429    | wait until the 60s window drains       |
| `ambiguous_session`    | 409    | include `session_id` in the request    |
| `unknown_session`      | 404    | stale session_id; re-resolve           |

Rejected body (uniform):
```json
{"accepted": false, "reason": "<reason>", "session_id": "<sid-or-null>"}
```
No token value, no payload bytes, no stack trace ever appears in a response or log line
(vision payloads are user imagery — treat like credentials).

---

## VAD_RACE_ANALYSIS

Commit semantics (official, VISION_PROTOCOL_REPORT.md:24): "若客户端已发送过
input_image_buffer.append 事件，input_audio_buffer.commit 事件将同时提交图像缓冲区。"
The gateway runs `server_vad` (qwen.py:675-679), so the SERVER issues the commit at end of
user speech. Consequences:

1. **User sends image, stays silent.** No VAD commit fires → the image sits in the upstream
   image buffer indefinitely (official semantics: the buffer waits for the next commit). No
   response is generated from the image alone. This is correct-and-desired: "show, don't tell"
   without a spoken request produces nothing. The HTTP response already sets expectations via
   the `note` field (`commits_with_next_audio_commit`). Client guidance text on the device:
   "说点什么，小智就会看到它" — the image answers the NEXT utterance.
2. **Speech mid-turn (the "让小智看看" case).** The user says "让小智看看" while the image POST
   lands: both the audio of that utterance and the image are in the buffer when server VAD
   commits at end-of-utterance → the image joins the CURRENT turn's commit. The model sees
   image + speech together. This is exactly the desired behavior and requires NO gateway-side
   commit logic — VAD timing does it for free.
3. **Ordering guarantee (gateway-side).** `send_image` is only accepted after ≥1
   `input_audio_buffer.append` on the LIVE Qwen connection (qwen.py:715-717, `_audio_seen` set
   in `send_append` qwen.py:687; reset per fresh session qwen.py:463). This is the doc-verified
   official constraint (VISION_PROTOCOL_REPORT.md:48), already test-locked (V4/V8/V9).
   Failure mode: device POSTs an image on a brand-new session before speaking → HTTP 409
   `ordering_audio_first`. Client retry guidance: **retry-after-next-speech** — the device
   SHOULD re-POST the same image after the user has spoken (any utterance → audio appends flow
   continuously → `_audio_seen` becomes True). Do NOT queue-and-auto-retry inside the gateway:
   a silent queue would resurrect a stale image into a later unrelated turn.
4. **Rate limit interaction.** The 1/s official recommendation is enforced as ≥5s + ≤6/min
   (qwen.py:697-698) — V0 is single-shot user-initiated ("看一眼"), so a human cannot hit it;
   the limits exist to make a buggy client harmless. 429 responses carry the reason; no queue.

---

## TURN_BINDING

No new event names. The committed image+audio becomes one user item
(`conversation.item.created`), and the assistant answer arrives as the NORMAL downlink the
gateway already handles end-to-end: `response.created` → `response.audio.delta` → pacer →
Opus → WS to the device, with `response.audio_transcript.*` for UI (turns.py:77-97 mapping).
Binding is therefore implicit and total: the image belongs to the turn whose
`input_audio_buffer.commit` swept it up, on the SAME Qwen session (one QwenClient per XiaoZhi
connection, qwen.py:284; session id captured at qwen.py:475-487). The client does not need to
correlate the HTTP 202/200 with the response — it correlates by hearing it, as with any other
turn. V0 does NOT add a `vision_result` client event; if V1 wants explicit acks, that is a new
design round. Diagnostic hook only: `counters.vision_images_accepted/rejected` (additive),
so `/health` can show the image path is alive without touching the WS protocol.

---

## CANCEL_TIMEOUT_CLOSE

- **`response.cancel` (barge-in / `abort` → turns.py:591-611):** response.cancel cancels the
  RESPONSE in flight; per official docs it does not commit or clear input buffers. A buffered
  (not-yet-committed) image therefore SURVIVES an abort and will join the next commit.
  Assessment: acceptable-and-likely-desired for V0 ("我打断了，但你刚才给我看的图还在").
- **`input_audio_buffer.clear`:** UNCERTAIN — docs name no `input_image_buffer.clear` and do
  not state that the audio clear wipes the image buffer (VISION_PROTOCOL_REPORT.md:59-60).
  V0 policy: the gateway never sends buffer-clear on the image path, so this branch is
  unreachable in our topology; document as UNCERTAIN, verify in a real session before any
  feature that relies on clearing.
- **Session close / WS disconnect / Qwen reconnect:** the image buffer is per-session
  upstream state; `session.finish` + WS teardown (qwen.py:741-743, 755-780) discards it, and a
  reconnect opens a FRESH session where `_audio_seen=False` (qwen.py:463) — ordering is
  re-enforced from scratch (V9). A POST racing a close returns 503 `not_connected`.
  A POST that accepted (200) immediately before close: image was already handed upstream;
  the turn it would have joined is lost with the session — client retries after the new
  session has audio. This half-open window is inherent to the async commit model; documented,
  not engineered away.
- **Timeout:** none added. The HTTP handler awaits `send_image()` which is a single
  `ws.send_str` on a live connection (qwen.py:636-640) — sub-ms; a handler-level timeout would
  only mask a dead socket, and 503 covers that.

---

## MOCK_TEST_HOOKS

Wire frames the mock upstream (deploy/product-sidecar/probe_product_v1.py — currently NO image
events, report appendix line 84) and the tests must assert:

1. **Mock upstream additions (upstream side):** on `input_image_buffer.append` → record it;
   on the NEXT `input_audio_buffer.commit` (or synthesized commit after silence, controllable
   via the existing `/control/*` endpoints, tests/mvp_mock_qwen.py:169-172) → emit the standard
   committed/`response.created`/`response.audio.delta`/`response.done` sequence so the test
   proves image+audio committed together. Optionally emit a doc-shaped error frame for
   negative-path rehearsal (ordering violation simulated by resetting mock state).
2. **Gateway HTTP surface (device side):**
   - H1  200 happy path: auth'd POST → 200 `{"accepted":true,...}`; exactly ONE upstream frame
         `{"type":"input_image_buffer.append","image":<b64>}` whose decoded bytes equal the POST
         (mirrors V5's wire check, vision_v0_tests.py:130-135).
   - H2  ordering: POST before any audio on the session → 409 `ordering_audio_first`, ZERO
         upstream image frames (V4 analog at the HTTP layer).
   - H3  auth: missing header → 401; wrong header → 401 (identical body); admin token ≠
         vision token (positive proof they are separate secrets).
   - H4  size: 260KB+ body → 413 `payload_too_large`; non-JPEG payload → 415 `not_jpeg`.
   - H5  rate: two POSTs <5s apart → second 429 `rate_interval` (fake clock as in V6).
   - H6  commit coupling: after H1, drive mock silence/VAD-commit → assert the mock's commit
         handler saw the image buffered BEFORE the commit frame arrived on the upstream WS
         (the core "让小智看看" assertion), and the assistant audio/text response reached the
         device WS unchanged.
   - H7  session resolution: two live connections without `session_id` → 409
         `ambiguous_session`; stale `session_id` → 404 `unknown_session`.
   - H8  degradation: any 4xx above leaves the audio path byte-identical (V7 analog: audio
         continues to flow on the device WS after the rejected POST).
3. **Existing suite stays green:** vision_v0_tests.py (13/13) guards QwenClient directly and
   must keep passing untouched; the new HTTP tests are additive (new file, e.g.
   `gateway/tests/vision_http_tests.py`), reusing the stub-WS + fake-clock harness pattern.

---

## VERDICT

FEASIBLE with a small, additive surface: one POST route on the 8111 plane (main.py:67-77
pattern, handler in http.py), one new dedicated token file + `X-Vision-Token` header
(constant-time, mirroring admin/auth.py — NOT the admin token, NOT the OTA test-token), zero
changes to turns.py / protocol.py / the WS frame cap. All official constraints are already
enforced in `QwenClient.send_image` (qwen.py:702-733, 13/13 tests); the HTTP layer only adds
auth, body-cap, and session resolution via the read-only ADMIN-1 registry. The VAD race is
resolved by official semantics itself: image waits for the next commit (silence case) or joins
the current turn's commit (speech case) — both desired; the only client obligation is
retry-after-next-speech on 409 `ordering_audio_first`. Remaining UNCERTAIN (real-session
verification before production): image-buffer clear semantics on
`input_audio_buffer.clear`, and the half-open accept-then-close window — both documented
above, neither blocking V0. Recommend proceeding to implementation with the H1-H8 hooks as the
acceptance set.
