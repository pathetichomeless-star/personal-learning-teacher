# modules/adapters

Ownership boundary: integration with the **external** systems.

- XiaoZhi Admin adapter (calls the pinned legacy manager-api; no fork/vendoring — see `admin0/admin-adapter-contract.md`)
- English-workbench adapter (read-only progress/lesson calls; the workbench stays the authoritative course/progress engine)

Rules: thin translation only; credentials injected at runtime (never committed); fail-closed on upstream unavailability.
