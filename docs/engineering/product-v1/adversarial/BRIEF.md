# ADVERSARIAL VALIDATION — SHARED BRIEF (read this first)

Run: `PRODUCT V1 ADVERSARIAL VALIDATION RUN` (directive attached by the product owner).
Repo: `<project-root>` (branch `main`, no remote). Target: **Product V1** as currently
deployed in the isolated test sidecar.

## Mission

Try to BREAK the product. Happy-path re-runs are worthless here. Attack architecture
boundaries, auth, admin writes, policy, Memory, Knowledge, the Workbench read-only
boundary, session isolation, concurrency, reconnect, transcript state, versioning/rollback,
destructive confirmations, malformed input, privacy, secret handling, prompt/context
boundaries and degraded dependencies.

## ABSOLUTE HARD LOCKS (violating any of these is itself a BLOCKER finding)

1. **No real-Qwen session.** `REAL_QWEN_TOTAL_USED = 4/4`, `REMAINING = 0`.
   - NEVER run `gateway/tests/{spike_session_update,spike_vocab_matrix,mvp_real_smoke,r1f_real_probe}.py`.
   - NEVER connect a WS client that starts listening / sends uplink audio to the **NAS** test
     sidecar: it runs `QWEN_MODE=real` and would open a paid upstream session.
2. **All functional attacks run LOCAL, mock-only.** Start a local gateway instance with
   `QWEN_MODE=mock` (see "Local instance recipe") or use in-process aiohttp test clients.
   Prefer the in-process pattern: `gateway/tests/admin2_tests.py` / `behavior1_tests.py`.
3. **Never touch**: primary `xiaozhi-rtl-bridge` (8110/8111), the production Workbench
   (`english-learning-workbench-web` :18100 — no writes, and prefer a local stub so you do not
   touch it at all), the legacy `xiaozhi-full-*` stack, the accepted MVP sidecar
   (28210-28212), real learner data.
4. **Never change** provider / model / voice / VAD / 20 ms frame / 15 ms guard / 5 ms slack /
   Opus / FIFO / generation ownership / barge-in semantics. No frozen-file edits
   (`gateway/app/{turns,audio,qwen,ws,protocol,counters}.py`).
5. **No secrets in any artifact.** Never print, copy or commit tokens, API keys or
   `/app/secrets/*`. Reference them only as "the admin token".

## YOUR WRITE SCOPE (red-team agents are read-only on product source)

You may create/modify ONLY:
- your own test files under `gateway/tests/adversarial/<your-agent-id>/`
- your own report at `docs/engineering/product-v1/adversarial/reports/<your-agent-id>-round<N>.md`

You MUST NOT modify any product/implementation file (`modules/**`, `gateway/app/**`,
`admin/**`). If you find a defect, DO NOT fix it — record it; the remediation lead fixes it.

## Local instance recipe (mock, isolated)

```bash
cd <project-root>/gateway
DYLD_LIBRARY_PATH=/tmp/opus131/lib \
PUBLIC_WS_URL=ws://127.0.0.1:<WS>/xiaozhi/v1/ WS_PORT=<WS> HTTP_PORT=<HTTP> FRAME_MS=20 \
QWEN_MODE=mock QWEN_MODEL=qwen3.8-omni-flash-realtime QWEN_VOICE=Tina \
MEMORY_FILE=/tmp/adv/<id>/memory.json KNOWLEDGE_FILE=/tmp/adv/<id>/knowledge.json \
POLICY_FILE=/tmp/adv/<id>/policy.json WORKBENCH_BASE_URL=<local stub or empty> \
ADMIN_ENABLED=1 ADMIN_BIND=127.0.0.1 ADMIN_PORT=<ADMIN> \
ADMIN_API_TOKEN_FILE=/tmp/adv/<id>/token ADMIN_UI_DIR=<project-root>/admin \
.venv/bin/python -m app.main
```

Use ONLY the port range assigned to you. Run it in the background, and stop it when done.
For a mock upstream, reuse `gateway/tests/mock_qwen_server.py` (`--port <MOCK> --scenario …`)
and set `QWEN_WS_URL=ws://127.0.0.1:<MOCK>`. Note: mock mode defaults to
`ws://127.0.0.1:9977`, so also pass `QWEN_WS_URL` if you change the port.

Test command shape: `${REPO}/gateway/.venv/bin/python` with
`DYLD_LIBRARY_PATH=/tmp/opus131/lib` (the venv python is used for gateway suites).

Known environment quirk (NOT a product defect, do not report as one): this Mac's *dev*
libopus intermittently raises `OpusError(bitrate)` on the first `OpusEnc24()` construction;
`R1F_REGRESSION` is therefore 179/180 here and it reproduces at the pristine baseline.

## Reporting format (every finding)

ID · agent · round · severity (BLOCKER/MAJOR/MINOR/INFO) · surface · precondition ·
reproduction (exact commands/inputs) · expected · actual · root cause (if known) · status.

Severity guide:
- BLOCKER: auth bypass, cross-user leak, secret disclosure, unauthorized Workbench write,
  primary realtime touched, irreversible data loss, audio frozen-invariant violation,
  real-Qwen budget violation.
- MAJOR: persistent state corruption, rollback failure, deleted Knowledge still retrieved,
  policy bypass, cross-session contamination, destructive action without confirmation,
  reliably stale/incorrect progress presentation.
- MINOR: non-security, non-integrity UX/diagnostic defects. INFO: observations.

Also state explicitly, for your surface, the metric you were asked to prove (e.g.
`AUTH_BYPASS = 0`), and how you tried to falsify it.

## Report-back contract

Return to the orchestrator: your agent id, the metric verdict, a numbered findings list
(severity + one-line description + exact repro), and the path of your report file.
Be concise. If you found nothing on a surface, say so explicitly and describe what you
tried (negative results with coverage evidence are valuable).
