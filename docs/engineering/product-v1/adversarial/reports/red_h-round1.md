# RED_H — Round 1 Report: Admin UI / Input Safety

Agent: **AGENT RED-H** · Round 1 · Surface: unified Chinese-first admin console
(`admin/index.html`, `admin/app.js`, `admin/styles.css`) + the `gateway/app/admin/api.py`
contract it consumes.

Mode: fully **in-process** (`aiohttp` `TestClient`), `QWEN_MODE=mock` never needed (no WS
client, no audio, no upstream). No primary / Workbench / production / NAS touched. No
secret printed (the only token is an in-test fixed literal; it is never persisted or
echoed). Product source unchanged (`git status`: only untracked test/report dirs).

Test artifact: `gateway/tests/adversarial/red_h/red_h_admin_tests.py`
Run: `DYLD_LIBRARY_PATH=/tmp/opus131/lib gateway/.venv/bin/python gateway/tests/adversarial/red_h/red_h_admin_tests.py`
Result: **56 checks, 50 PASS, 6 FAIL** (6 FAIL = 4 distinct findings below; H24 folded into RED-H-02).

---

## Metric verdicts

| Metric | Verdict | Basis |
|---|---|---|
| `NO_ACTIVE_CONTENT_FROM_DATA` | **PASS** | Exhaustive sink scan (H1–H6) + round-trip (H7–H14): every DOM write is `textContent`/`createElement`/`appendChild`; no `innerHTML/outerHTML/insertAdjacentHTML/document.write/eval/new Function/srcdoc/on*=`, no `href/src/style/formaction/xlink` sink. The single `setTimeout` is a function ref (H4). All GETs return `application/json` and store-controlled markup comes back as inert data, byte-for-byte. |
| `NO_PARTIAL_MUTATION_ON_FAILURE` | **FAIL** | H30/H31 (RED-H-01): when the atomic flush fails, the API still returns **200** with `readback_ok:true` while the durable file is unchanged/absent — in-memory state is mutated, durable state is not, and the failure is invisible. (Confirmed-negative sub-results: validation/confirm/unknown-id failures mutate nothing — H21/H22/H37/H38/H39; disk writes are single `os.replace`, no torn file.) |
| `DOUBLE_SUBMIT_SAFE` | **PASS** | H33–H36: 2nd submit of document/dataset/memory delete returns 400/404 (no double-apply); 2nd category-clear removes 0 (idempotent). |

---

## Findings

### RED-H-01 · MAJOR · memory + knowledge write path
**Failed persist is reported as success (`200` + `readback_ok:true`).** Same class as the
sibling policy finding (a), reproduced on my surface.

- **Surface:** `POST /admin/memory/edit`, `POST /admin/knowledge/dataset/create` (and by
  construction every memory/knowledge write: `delete`, `clear-category`, `dataset/*`,
  `document/*`).
- **Precondition:** the store's atomic flush cannot complete (target dir unwritable / disk
  full / path released). Reproduced here by `chmod 0o500` on the store directory.
- **Reproduction:** `H30`, `H31` in the test file. Seed a memory item, `chmod` its dir to
  `0o500`, then `POST /admin/memory/edit {"id": <real>, "value": "v1"}`.
- **Expected:** a durable-write failure must not be reported as success — 5xx (or 200 with
  `readback_ok:false`); `readback_ok` must reflect what is actually persisted.
- **Actual:** `200 {"readback_ok": true}` while the on-disk file is unchanged
  (`disk_changed=False`); for knowledge the store file is never created (`file_exists=False`)
  yet the response is `200 {"readback_ok": true}`. The UI then renders “读回一致：是”.
- **Root cause:** `MemoryStore._flush()` / `KnowledgeStore._flush()` are *fail-soft*
  (`except Exception: return False`) and the mutators ignore the return value; the readback
  in `api.py` re-reads the **in-memory** object via `.inspect()`/`.get_dataset()`, so it
  confirms memory, not durability.
- **Impact:** invisible write loss — after a restart the mutation is gone although the
  operator/UI saw success. Data-loss integrity defect.
- **Status:** OPEN (remediation owns the fix).

### RED-H-02 · MINOR · knowledge write path (API robustness)
**Type-confused `top_k` yields HTTP 500 instead of 400.** Same class as the sibling policy
finding (b).

- **Surface:** `POST /admin/knowledge/search`.
- **Reproduction:** `H23` — `POST /admin/knowledge/search {"query":"x","top_k":"abc"}` →
  `500 {"error":"internal_error"}`. Server log: `admin api error in knowledge_search:
  ValueError("invalid literal for int() ... 'abc'")`.
- **Expected:** `400` (invalid argument), never an internal error.
- **Actual:** `500 internal_error`.
- **Root cause:** `KnowledgeStore.search` does `int(top_k or default)` with no type guard;
  the `ValueError` is not a `KnowledgeError`, so `_guard` maps it to the generic 500 branch.
- **Secondary (H24, INFO):** `top_k: {}` is *falsy* so it is silently replaced by the
  default (`200, count 0`) — wrong-typed `top_k` is therefore handled inconsistently
  (`"abc"` → 500; `{}` → silently defaulted; a truthy non-numeric like `[1]` → 500).
- **Status:** OPEN.

### RED-H-03 · MINOR · knowledge write path
**Non-string `dataset/create.name` is silently stringified and persisted.**

- **Reproduction:** `H25` — `POST /admin/knowledge/dataset/create {"name": {"a": 1}}` →
  `200`, dataset persisted with `"name": "{'a': 1}"`.
- **Expected:** `4xx` on a non-string name (type contract).
- **Actual:** `200`; `KnowledgeStore._valid_name` applies `str(name or "").strip()` before
  validating, so a dict/list is coerced to its Python repr and stored.
- **Impact:** misleading stored dataset names; inconsistent with the API's own
  `isinstance(..., str)` guards used on rename/document fields.
- **Status:** OPEN.

### RED-H-04 · MINOR · memory + knowledge persistence
**`.tmp` file leaks when the atomic `os.replace` fails.** Same class as the sibling policy
finding (c).

- **Surface:** `MemoryStore._flush` / `KnowledgeStore._flush` (`tmp` written, `os.replace`
  raises, `except` swallows the error and leaves the file).
- **Precondition:** the store path is a directory (or any condition that makes `os.replace`
  fail after the tmp write). Reproduced: point the store path at an existing directory.
- **Reproduction:** `H32` — `MemoryStore(<dir>)`, `save(...)` →
  `OSError [Errno 21] Is a directory: .../memory.json.1bd65ccd.tmp -> .../memory.json`;
  a `*.tmp` file remains in the store directory.
- **Expected:** no leftover temp file on a failed replace.
- **Actual:** leftover `memory.json.<hex>.tmp` (contains the full store payload; mode 0600).
- **Status:** OPEN.

### RED-H-05 · MINOR · admin UI coverage ("no common operation requires raw JSON")
**Some policy fields and read views have no UI affordance.**

- **Tests:** `H48` (every `POST` write route has a UI affordance — **PASS**) and `H49`
  (≥6 destructive actions gated by `window.confirm` — **PASS**). So no *write* operation
  requires an external tool.
- **Gap (observed in `admin/app.js:287-302` vs `modules/policy/persona.py:51-83`):**
  `teaching.vocab_policy_header` (present in `DEFAULT_POLICY`) and the `activities` /
  `scenarios` / `limits` sections are absent from `POLICY_FIELDS`; changing them requires
  hand-editing the in-UI **advanced raw-JSON textarea**.
- **Read endpoints with no UI surface:** `/admin/audit`, `/admin/policy/audit`,
  `/admin/memory/item/{id}`, `/admin/knowledge/document/{id}`,
  `/admin/knowledge/document/{id}/chunks`.
- **Also:** a memory item's `confidence` is editable by the API but the UI only prompts for
  `value` (no affordance to edit confidence).
- **Status:** INFO→MINOR (UX/diagnostic parity; no security impact).

---

## Active-content sink enumeration (evidence for the PASS)

Every place `app.js` writes to the DOM/attribute, and whether the value is **data** or a
**literal** (all literals are compile-time constants in the file; no store/user/operator
data flows to an active sink):

| Line(s) | Sink | Value source | Active? |
|---|---|---|---|
| 24 | `e.className = cls` | literal class strings | no |
| 25 | `e.textContent = String(text)` | **data**, text-only | no |
| 44,62,99,100,131 | `.textContent = ...` | **data**, text-only | no |
| 79 | `pre.textContent = JSON.stringify(obj)` | **data**, text-only | no |
| 132,140,146…(all) | `container.appendChild(el(...))` | built via `el` (textContent) | no |
| 90 | `input.value = ""` | literal | no |
| 338 | `input.id = "pf_" + f[0] + "_" + f[1]` | `POLICY_FIELDS` **literal** | no |
| 339 | `input.value = policy[...][...]` | data into a **form value** (not HTML) | no |
| 346 | `o.value = v` | literal `["zh","en"]` | no |
| 358,359,439,588-596 | `.id`/`.placeholder` | literal | no |
| 395 | `setTimeout(function(){render(...)}, 400)` | **function ref** (no string) | no |
| 446-448 | `encodeURIComponent(...)` into fetch URL | data, URL-encoded | no |

No `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval`, `new Function`,
`srcdoc`, `createContextualFragment`, `DOMParser`, `<script|iframe|object|embed>`, `on*=`
handler, or `href/src/style/formaction/xlink` sink exists anywhere in `admin/` (H1–H3, H6).
All data-display GETs return `application/json; charset=utf-8`, so a browser opening an
endpoint renders text, not HTML (H8, H14).

## Data round-trip evidence (H7–H14)

Stored and read back through every displaying GET, byte-exact (post `_norm_text`
normalization where the store normalizes): dataset `name` =
`<script>alert('ds')</script>`; document `title` = `<img src=x onerror=alert(1)>"'\\`;
`source_uri` = `javascript:alert(1)//uri"><svg/onload=alert(2)>`; document text with
`</script><script>`, `&`, `<b>`; memory value `<script>alert('mem')</script>`; memory value
with emoji+ZWJ, combining mark, zero-width, Arabic, Hebrew and an embedded NUL — all returned
verbatim as inert JSON strings.

## Robustness evidence (H17–H22, H28, H33–H42)

- Malformed JSON → 400; non-object JSON → 400 (H17/H18).
- Duplicate JSON keys → last-wins, still a clean coded 4xx (no 500) (H19).
- Unknown/extra fields (incl. `__proto__`) ignored; item still updates (H20).
- Wrong-type `value` (list) / non-numeric `confidence` → 400 (H21/H22).
- Body > 64 KiB → 413 before parsing (H28). NUL in document text normalized, no 500 (H29).
- Destructive cancellation is clean: memory delete w/o confirm, category clear with wrong
  confirm, dataset delete with wrong confirm → 400 and **no mutation** (H37–H39).
- Double-submit safe (H33–H36).
- Stateless across a client refresh: a preview elsewhere does not change the active version
  (H40/H41); confirm tokens are data-derived (`confirm_token == dataset id`), i.e. no
  server-issued one-time state to go stale (H42).
- Missing assets degrade honestly: `/`,`/index.html`,`/app.js`,`/styles.css` in an empty UI
  dir → `503 {"error":"ui_unavailable"}` with no filesystem path/traceback; unknown path →
  404 with no disclosure; `/favicon.ico` → 204 (H43–H45). Real shell serves correct
  content types (H46/H47).

## Negative results / coverage (things tried that found nothing)

Weird path ids (`%2e%2e%2f..%2fetc%2fpasswd`, `%00%01%02`, 500-char, RTL+NUL) → clean
400/404 with no path/trace leak (H15/H16). No XSS/active-content execution path exists. No
authentication or secret-leak issue was found on this surface (out of scope; owned by the
auth agent). No partial mutation on validation/confirmation failures. No stateful behaviour
across requests.

## What remains / caveats

- RED-H-01..04 require the fixes owned by the remediation lead; not modified here (read-only
  on product source, per BRIEF).
- The `.tmp` leak (RED-H-04) needs the destination path to be a directory to trigger
  deterministically; the broader class (any `os.replace` failure) is what the sibling
  policy finding (c) describes.
