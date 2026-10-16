# AGENT E — Security / Privacy / Rollback Review (READ-ONLY)

- Reviewed commit: `52facaa24b5b8c97f805e019e66b087faf9ac46b` (HEAD, main)
- Date: 2026-10-08 (Asia/Shanghai)
- Scope: admin plane auth, privacy, destructive confirmations, filesystem modes, rollback
- Verdict line at the end.

## Method

Files read: `gateway/app/admin/{auth,service,config,api,stores,views,registry,app}.py`,
`gateway/app/main.py` (wiring), `gateway/tests/admin_security_tests.py`,
`gateway/tests/admin1_tests.py`, `docs/engineering/product-v1/{ADMIN-2.md,BASELINE.md}`,
`admin/app.js`, `.gitignore`, `modules/{policy/persona,memory/store,knowledge/store}.py`.

Commands (verbatim results):
- `DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python tests/admin_security_tests.py` →
  `ADMIN_SECURITY_TESTS: 29 checks, 29 PASS, 0 FAIL`
- `git ls-files | grep -Ei "secret|\.env|token|credential"` → only
  `client/models/{en,zh}/tokens.txt` (tokenizer vocab),
  `deploy/legacy-xiaozhi/.env.example`, `docs/admin0/secret-hygiene-plan.md`,
  `tools/configure-secrets.sh`. No `admin_api_token` tracked.
- `shasum -a 256 admin0-backups/product-v1-pre-run.bundle` →
  `fec3096d72592a0c310c4ad76d2f75b60699a6f01d094906ba353e86e91433b1` (matches BASELINE).
- `git rev-parse product-v1-pre-run^{commit}` → `2fd8d4f8bedffaad8e6973f294b8ac7ed1a365d8`
  (= START_COMMIT); tag object `e8af29d` → commit `2fd8d4f` (consistent with BASELINE).
- repo-wide grep `sk-[A-Za-z0-9_-]{20,}|AKIA…|-----BEGIN …PRIVATE` → no matches.

Independent probe (reading route table + suite) not run as a separate driver (budget lock);
evidence taken from the suite and code inspection.

## Findings

### BLOCKER — none

### MAJOR — none

### MINOR — none

### INFO

1. **Auth is uniform and fail-closed.** `auth_middleware` guards every `/admin/*` path
   (`auth.py:125`), uses `hmac.compare_digest` (`auth.py:84`), prefers the token file then env
   (`auth.py:39-56`), and returns an identical 401 body for anonymous vs invalid tokens
   (`auth.py:111-118`; suite S1c). Missing token store / unconfigured token both 401
   (`auth.py:129-133`). `start_admin_listener` refuses to start when enabled without a token
   (`service.py:24-28`; S9). `ADMIN_ENABLED` defaults `"0"` (`config.py:55`; S9/S8).
2. **No secret leak vectors found.** Token value is never logged (only `source`+`configured`
   label, `auth.py:62-66`); handled by allowlist payload builders (`views.py:1-6`); errors are
   coded/sanitized (`api.py:53-97`); `PolicyInvalid.errors` carry only field-path labels, never
   values (`persona.py:155-275`). Suite S4/S4b/S4c/S4d pass (token/values/paths/transcripts
   absent from bodies and logs). No `/admin/diag/reset` route (`api.py` route table; S2b/S2d);
   `resettable: False` (`views.py:223`).
3. **No write bypass.** Every non-GET route is under `/admin/*` (`api.py:588-657`); the only
   non-`/admin` routes are static-shell GETs (`app.py:47-51`), served without auth by design and
   carrying no operational data (S1b: anonymous POST → 401 on all write routes; S2c workbench
   GET-only). `admin/app.js` uses relative `fetch` only, token in `sessionStorage`
   (`app.js:85-115`), no external URLs; bind default `127.0.0.1` (`config.py:16`).
4. **Destructive writes require explicit confirmation.** `policy_apply`/`policy_rollback`
   `_confirm` (`api.py:177,197`); `memory_delete` `_confirm` (`api.py:265`);
   `memory_clear_category` requires `confirm == entity` (`api.py:285-288`);
   `knowledge_dataset_delete` requires `confirm == ds_id` (`api.py:373-376`);
   `knowledge_document_delete` `_confirm` (`api.py:431`). Suite S3e/S3f pass.
5. **Filesystem modes.** All three stores use tmp-file → `os.chmod(0o600)` → `os.replace`
   atomically: `persona.py:447-458`, `knowledge/store.py:285-298`, `memory/store.py:204-216`
   (S6 confirms 0o600). The admin token file's own mode is operator-managed (not chmod'd by
   code; default `/app/secrets/admin_api_token`); no commitment of token occurred.
6. **Rollback intact.** Tag `product-v1-pre-run` and bundle present with matching recorded
   sha256; phase commits are ordinary commits on `main` (revertible). Stores are fail-soft
   (`stores.py:85-93`; `memory/store.py` load fail-soft, `persona.py` versioned history +
   rollback). Policy exposes version/rollback semantics; memory/knowledge expose delete/clear
   without version history (not meaningful there).

## Conclusion

No BLOCKER or MAJOR. Auth, privacy, confirmations, file modes and rollback all verified against
code and the 29/29 security suite.

AGENT_E = PASS