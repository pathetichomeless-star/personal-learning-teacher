# RED_H — Round 3 Report: Independent Cross-Check of the Repairs

Agent: **AGENT RED-H** (admin-UI / input-safety) · Round 3 · cross-checker for fixes in
`e3c9b6c` and `b854778`.

Mode: fully **in-process** (`aiohttp` TestClient), no real Qwen, no network, no
primary/Workbench/production/NAS touched. Read-only on product source (only my test dir +
this report written). No secret printed.

Test artifact: `gateway/tests/adversarial/red_h/red_h_round3_crosscheck.py`
Run: `DYLD_LIBRARY_PATH=/tmp/opus131/lib gateway/.venv/bin/python gateway/tests/adversarial/red_h/red_h_round3_crosscheck.py`
Result: **106 checks, 101 PASS, 5 FAIL** (5 FAIL = 5 NEW residual MINOR findings; no MAJOR,
no regression of the fixed MAJORs).
Sanity: the remediation's own `gateway/tests/adversarial_repair_tests.py` = **79/79 PASS**
(so the residuals below are gaps it does not cover, not failures of its guards).

`admin/` was **not modified** by either commit (verified via `git show --stat`), so the
round-1 UI sink analysis is re-asserted, not re-derived.

---

## Cross-check verdicts

| Fix | Verdict | Basis |
|---|---|---|
| Persist honesty (all 3 stores raise `PersistError`; API → `500 persist_failed`; read-back through a **new** store instance; `readback_ok:true` only when durable) | **CONFIRMED** | Forced flush failure on **all 12 write routes** (policy apply/rollback; memory edit/delete/clear-category; knowledge dataset create/rename/enable/delete; document add/delete/rebuild): every one → coded `500 persist_failed`, none returns `200` with a misleading body; a **fresh** reader still sees the pre-write durable state (no phantom); on the success path `readback_ok:true` agrees with a fresh reader; a retry after the failure clears succeeds and is durable (R3-7..R3-17). |
| New validation rules (non-string name/top_k → 400; lone surrogates; control chars; policy newlines in any section; invisible-only fields; capped `errors`) | **CONFIRMED, with residuals (weakened in 3 spots)** | All the named rules hold (R3-22..R3-29, R3-28x, R3-24/25/26/27). Residuals: the `errors` cap applies only on the apply path, not on **preview** (RED-H-R3-01); `top_k=true` slips the int guard (RED-H-R3-02); `description` / `tags[]` / `source_uri` wrong-type values are silently coerced (RED-H-R3-03/04/05). |
| Input safety on the new paths | **CONFIRMED** | long Unicode/RTL/emoji/ZWJ/combining/zero-width accepted and round-trip inert (intended ≤cap length capping); malformed ids in path params → clean 4xx with no path/trace leak; duplicate JSON keys last-wins; unknown/`__proto__` fields ignored; >64 KiB body → 413; validation errors never echo a submitted **value** (R3-31..R3-44). |
| UI contract | **CONFIRMED (unchanged)** | No `innerHTML/outerHTML/insertAdjacentHTML/document.write/eval/new Function/srcdoc/on*=/data-driven href|src|style`; DOM writes are `textContent` only; `showError` renders via `textContent`; every POST write route still has a UI affordance; a 400 body is honest JSON with no traceback/path/`readback_ok` (R3-1..R3-6, R3-44). |

Round-1 findings status: **RED-H-01 fixed** (persist honesty), **RED-H-02 fixed**
(`top_k="abc"` now 400), **RED-H-04 fixed** (verified: a failed `os.replace` leaves **no**
`.tmp` — `glob('*.tmp') == []`), **RED-H-03 fixed for `name`** but residual on the sibling
fields (RED-H-R3-03/04/05).

---

## Metric verdicts (re-proved on the current revision)

| Metric | Verdict |
|---|---|
| `NO_ACTIVE_CONTENT_FROM_DATA` | **PASS** |
| `NO_PARTIAL_MUTATION_ON_FAILURE` | **PASS** (the round-1 FAIL is now closed: forced flush failure → honest 500, no phantom, durable state unchanged, retry sane) |
| `DOUBLE_SUBMIT_SAFE` | **PASS** |

---

## NEW findings

### RED-H-R3-01 · MINOR · policy read path (API robustness)
**`POST /admin/policy/preview` returns an UNCAPPED `errors` list**, while the apply/error
path caps at 50.
- Repro: `POST /admin/policy/preview {"policy": {"k000":1, ... 300 unknown sections ...}}`
  → response `errors` length **300**. The same payload to `/admin/policy/apply` → `400` with
  `errors` length 50 (`api.py:91` `list(e.errors)[:50]`).
- Expected: a bounded error list on both paths (the fix's stated intent).
- Actual: `policy_preview` returns `store.preview(candidate)` verbatim; `validate_policy`
  emits one error per operator-supplied key, so a ≤64 KiB body yields a multi-hundred-entry
  list (~3–6× response amplification). Server→browser only; no DOM sink (the UI renders it
  through `textContent`). No submitted **value** is echoed (R3-31).
- Root cause: the cap lives in the exception mapping, not in `Preview`'s return.
- Status: OPEN.

### RED-H-R3-02 · MINOR · knowledge search (API robustness)
**`top_k: true` is accepted** (`bool` is a subclass of `int`, so the `isinstance(top_k, int)`
guard passes; `int(True)=1`). Repro: R3-23b → `200`.
- Expected: `400` for a non-integer `top_k` per the stated contract.
- Actual: `200`. Low impact (result count only), but the guard is not type-exact.
- Status: OPEN.

### RED-H-R3-03 · MINOR · knowledge dataset create (input validation)
**Non-string `description` is silently stringified** (residual of round-1 RED-H-03, on a
sibling field). R3-45: `POST /admin/knowledge/dataset/create {"name":"x","description":{"a":1}}`
→ `200`, persisted `"description": "{'a': 1}"`.
- Expected: `4xx` (the API already type-guards `name`).
- Root cause: `KnowledgeStore._valid_text_field` applies `str(value or "")` before validating.

### RED-H-R3-04 · MINOR · knowledge dataset create (input validation)
**Non-string `tags[]` element is silently stringified.** R3-46:
`{"name":"x","tags":[{"a":1}]}` → `200`, tag becomes `"{'a': 1}"`. Same root cause as R3-03.

### RED-H-R3-05 · MINOR · knowledge document add (input validation)
**Non-string `source_uri` is silently stringified.** R3-47:
`POST /admin/knowledge/document/add {"...","source_uri":{"a":1}}` → `200`,
`source.uri` = `"{'a': 1}"`. Same root cause as R3-03.

(All three are `MINOR`: no security/integrity break; they accept malformed types instead of
rejecting, and the coerced strings still round-trip as inert data.)

## INFO observations (not defects)

- **INFO-1:** `KnowledgeStore.add_document` validates `source_uri`/`added_by` **after** the
  duplicate-content and cap checks, so a request that is simultaneously duplicate-content and
  carries an invalid `source_uri` answers `409 duplicate_content` rather than `400 malformed`.
  Ordering only; no security impact.
- **INFO-2:** `api.py:344` `memory_delete` durable check is
  `_disk_memory_item(store, item_id) is None`, so a *read-back exception* (the helper catches
  and returns `None`) would read as success. Not reachable in practice — `MemoryStore.delete`
  raises `PersistError` first unless the flush already succeeded — but it is the one
  fail-open durable check (every other durable check is `disk is not None and …`, i.e.
  fail-closed). Worth hardening for defence in depth.
- **INFO-3:** `api.py:522` `knowledge_document_delete` still returns an *in-memory*-derived
  `readback_ok` (`store.get_document(doc_id) is None`), unlike the other handlers that now
  return `True` after `_durable`. It is reached only after `_durable` passed, so it is not
  misleading — a style inconsistency only.

## Coverage / negative results (what I tried that found nothing)

- 12× write routes under a forced read-only store dir → all honest-coded, no fake 200, no
  phantom, fresh readers agree, retry sane.
- Success-path `readback_ok` cross-verified against independent fresh readers
  (`MemoryStore`/`KnowledgeStore`/`PolicyStore`) — agreement in every case.
- Double-submit of all destructive routes — 2nd is 400/404 or removes 0.
- Surrogates in name/description/tags/title/text/source_uri → 400; control chars in dataset
  name and memory values → 400; policy newlines rejected in persona/language/teaching/
  canonical_spelling_rules/speed_levels/activities/limits; invisible-only names rejected.
- Long Unicode/RTL/emoji/ZWJ/combining/zero-width metadata accepted and inert (with the
  documented `MAX_NAME_LEN` capping); weird path ids clean; duplicate keys, unknown fields,
  413, honest error bodies.
- UI sinks unchanged and text-only.
