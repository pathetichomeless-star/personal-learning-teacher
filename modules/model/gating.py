"""Server-side enable gate (contract §2.2 — the hard rules).

``enable`` / ``set-default`` / ``bind-scene`` MUST call this.  The decision is
made **only** from server-stored state:

1. the model exists;
2. it is not part of the frozen Tina link;
3. its protocol has a **registered** adapter (``builtin`` / ``partial``);
4. its **real** evidence level is at least ``verified`` (from the registry's
   evidence log — a request body or UI simulation is never consulted);
5. the provider has a usable credential;
6. the scene's required capabilities are a subset of the model's;
7. ``oral_realtime`` additionally requires ``realtime_safe``.

Returns ``(ok, code, detail)``; the caller maps ``code`` to the HTTP error in the
contract's error table and leaves state untouched on refusal.
"""

from __future__ import annotations

from modules.model.registry import REGISTERED_ADAPTERS, EVIDENCE_LEVELS

_ORDER = {v: i for i, v in enumerate(EVIDENCE_LEVELS)}


def enable_gate(registry, credentials, model_id, *, scene=None, action="enable"):
    model = registry.get_model(model_id)
    if model is None:
        return (False, "not_found", None)
    if model.get("frozen"):
        return (False, "frozen_model", None)

    adapter = registry.adapter_of(model.get("protocol"))
    if adapter not in REGISTERED_ADAPTERS:
        return (False, "capability_mismatch", "adapter_not_registered")

    level = registry.evidence_level(model_id)
    if _ORDER.get(level, 0) < _ORDER["verified"]:
        return (False, "evidence_missing", level)

    prov = registry.provider(model.get("provider_id"))
    if prov is None:
        return (False, "not_found", "provider")
    if credentials is None or not credentials.is_configured(prov["id"]):
        return (False, "credential_missing", None)

    if scene:
        need = (registry.scene_defs().get(str(scene)) or {}).get("need") or []
        caps = set(model.get("capabilities") or [])
        missing = [c for c in need if c not in caps]
        if missing:
            return (False, "capability_mismatch", "missing:" + ",".join(missing))
        if str(scene) == "oral_realtime" and level != "realtime_safe":
            return (False, "capability_mismatch", "realtime_not_safe")
    return (True, None, None)
