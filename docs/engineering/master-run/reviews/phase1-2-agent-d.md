# Catch-Up Review — Phases 1–2 · AGENT D (privacy / security / transcript exposure)

Reviewer: AGENT D (read-only) · Date: 2026-10-07 · Repo `<project-root>` @ `5ed3132` (`main`, local-only)
Scope: prove Phases 1–2 leaked **no** private data anywhere new (transcript forwarding, admin surface, sidecar
token, repo shareability, client privacy). Independent probes only — none of the Lead's suites were trusted.
Verdict: **PHASE12_D = PASS** for the privacy/security scope. One material **functional** defect found on the
forwarding path is recorded in §6 (out of privacy scope; not a leak).

## 1. Transcript exposure — no new exposure found

- **Admin endpoints.** `gateway/app/admin/app.py:44-51` route table = six GET API routes + 5 static; no
  `add_post/put/delete/patch`. `diag_summary_view` (`views.py:172-223`) is an **allowlist constructor**: it
  copies only scalar aggregates and never `transcripts` / `journal_tail` / `send_intent` / `send_timeline`.
  Live probe against the running sidecar (token used in-container, never printed):
  `/admin/diag`, `/admin/reset`, `/admin/diag/reset`, `/admin/routing`, `/admin/transcripts`, `/admin/routes`,
  `/diag`, `/diag/reset` → **all 404**; `/admin/diag-summary`, `/admin/sessions`, `/admin/health` → 200 with
  `has_transcript_kw=False`. `grep gateway/app/admin` finds no reference that copies transcript data.
- **Logging by the forwarding path.** `turns.py:344-357` `_send_transcript()` contains **no** `log.*` call;
  the only log lines around it (`turns.py:544-560`) emit `etype` / response-id / `extra` (extra is `None` for
  transcript events). Own mock flow (macOS, `opuslib` stubbed; the four real Qwen transcript events fed to a
  real `Connection`): 5 transcript payloads produced, **0** log lines containing the secret sentences
  (`我的护照号…G12345678`, `BLUE-RABBIT-77`) and 0 partial leaks. `diag.ENABLED=False` → `_transcripts` deques
  stay empty (gated at `diag.py:223`).
- **Client persistence.** `client/src/ui/shared/transcript.py` has no `open(`/`json.dump`/`pickle`/`sqlite`/
  `write(`; `MainModel` holds an in-memory `QVariantList`. Session-only by construction.
- **Repo artefacts.** `git ls-files` scan for transcript-bearing data: none (only source + synthetic fixtures).

## 2. Route integrity (CLIENT-UI-1 additive)

- The client never emits a `transcript` message: `grep '"type"\s*:\s*"transcript"' client/src` → none. So the
  client cannot send these messages back.
- The gateway never trusts client-supplied transcript fields: `handle_text` (`turns.py:417-431`) dispatches only
  `hello`/`listen`/`abort` and ignores every other type. Inbound handlers read only `version`, `state`, `mode`,
  `text` (length-only log at `turns.py:491-492`), `reason` — no `transcript`/`delta` field is ever consumed.
  (The `obj.get("delta"/"text"/"transcript")` reads in `_transcript_args` are on the **upstream Qwen** object.)

## 3. Sidecar token hygiene — verified on the NAS

- `/volume1/docker/xiaozhi-product-sidecar/secrets/admin_api_token`: `mode=600 uid=10001 gid=10001`; SSH user
  (`uid=1000`) → `test -r` = **no**, `open` = **no** (unreadable).
- In-container probe re-run: anonymous/invalid `[401×6]`, valid `[200×6]`, `AUTH_MATRIX = PASS`,
  `token appears in responses: 0`. Container logs: `grep -cE '[0-9a-f]{64}'` = **0** (token is a 64-hex value,
  confirmed via `len=64 / is_hex64=True` without printing it); the 28 case-insensitive "bearer" hits are only the
  words `bearer auth` / `reason=missing_bearer`. No `ADMIN_API_TOKEN=` literal anywhere.
- `deploy/sidecar/*`: no secret value — the compose only **references a mounted path**
  (`./secrets/admin_api_token:/app/secrets/admin_api_token:ro`); Dockerfile/probe check out clean.
- Container untouched: `xiaozhi-product-sidecar Up (healthy)`; no restart performed.

## 4. Repo shareability — `git ls-files` (944 files) secret scan → expected 0

| target | real value found |
| --- | --- |
| Qwen API key | 0 (`sk-…` hits are the substring in `vosk-model-…`, len 19) |
| admin token | 0 (2 633×64-hex hits are sha256 digests / `uv.lock` hashes / doc summaries) |
| MySQL / Redis passwords | 0 (`MYSQL_ROOT/REDIS_PASSWORD` only as `change_me_*` in `.env.example`; `mysql://` = host-only URL) |
| SSH material | 0 (no keys/`known_hosts`/`.netrc` tracked) |
| private KB / memory | 0 (only `.gitignore` / doc mentions of the patterns) |
| Workbench user data | 0 (doc mentions only) |
| real learner audio / transcripts | 0 (tracked audio = 407 synthetic `client/assets/sounds/*.wav` + 3 approved `gateway/tests/assets/u*.pcm16k.raw`; no `.jsonl`/`.sqlite`) |

`docs/reference/config.yaml` holds only upstream **placeholders** + a shared QWeather demo key (`sk-` scan clean).
New docs `docs/architecture/HARDWARE-TARGETS.md`, `AVATAR-LAYER.md`, `docs/engineering/master-run/**` contain no
secret/transcript/capture data (only `token occurrences … 0` style prose).

## 5. Client privacy

`grep client/src` for `/diag`, `/admin`, `8112`, `ADMIN_`, `/health` → **no matches**. The GUI/TUI render the
bubbles from the in-memory store only; nothing is written to disk. (The store's `reset_transcript()` /
`mark_transcript_interrupted()` wiring gap is AGENT B's finding — see `phase1-2-agent-b.md`.)

## 6. NEW material defect (functional, **not** a privacy leak) — forwarding is dead on the wire

`protocol.build_transcript()` returns a **dict** (`protocol.py:61-69`), but `_send_transcript()` passes it to
`ws.send_str(msg)` (`turns.py:352-355`). aiohttp 3.14.4 `WebSocketResponse.send_str` is a coroutine that raises
`TypeError("data argument must be str (<class 'dict'>")` for a dict (reproduced against a real aiohttp server).
The raise is swallowed by `except Exception: pass`, so **no transcript message ever leaves the gateway**; the
client bubbles can never populate. `build_hello`/`build_tts` return `json.dumps(...)` — `build_transcript` is the
inconsistent one. The Lead's `client_ui1_integration.py` does **not** catch this: it records messages inside a
wrapper *before* delegating to the (silently failing) original. This strengthens the privacy conclusion (nothing
is forwarded) but falsifies the Phase-2 "gateway forwarding" claim. Fix: `json.dumps` the dict in
`build_transcript` (or in `_send_transcript`). Reported here for the Lead; owned by the correctness track.

## Notes

- Pre-existing (not Phases 1–2): the audio-plane `/diag` (port 8111) still exposes `snapshot()["transcripts"]`
  **only when `RTL_DIAG=1`**. The admin app neither mounts nor proxies it (404), and the sidecar runs with
  `RTL_DIAG` unset, so this surface is inert here.
- Read-only review; no NAS container was restarted; the only file written is this report.

**PHASE12_D = PASS**
