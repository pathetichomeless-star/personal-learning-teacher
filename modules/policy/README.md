# modules/policy

Ownership boundary: **persona / language / teaching policy (PERSONA-POLICY V1)** — one
authoritative, versioned, validated policy object; **not** another LLM.

`persona.py` holds:

* `DEFAULT_POLICY` — the closed-schema default (persona / language / teaching /
  activities / scenarios / limits); every prompt line the tutor session receives is
  composed from it by the `render_*` helpers (single source of prompt text);
* `validate_policy` / `diff_keys` — closed keys, bounded strings, enum values;
* `PolicyStore` — one JSON file (atomic 600 writes, `threading.RLock`, bounded history 20,
  sanitized audit 200) with `preview` / `apply` / `rollback` / `versions` / `audit` /
  `reload_if_changed`; missing or corrupted storage fails soft to the defaults (v1);
* `render_policy_overview` — static preview used by the admin UI.

Precedence (fixed): hard rule > explicit current user request > saved learner preference >
current activity > auto/default.  Hot apply reuses the proven instructions-only
`session.update` path and only at a safe boundary; model/voice/VAD/audio formats are never
touched.  See `docs/engineering/product-v1/PERSONA-POLICY-V1.md`.