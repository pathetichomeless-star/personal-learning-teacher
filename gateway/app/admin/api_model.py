"""ADMIN V4 model-management API (contract §2, §3).

Additive over the ADMIN-2 control plane; mounted only when the model stores are
wired.  Every decision that could enable something is taken by
:func:`modules.model.gating.enable_gate` from **server-stored state** — a request
body's ``verify``/``verified``/``capabilities`` claims are never consulted.

Any response, log or audit entry produced here is sanitized: no plaintext secret
ever appears (only ``fingerprint`` + opaque ``credential_ref``), and no store
value leaks through an error body.
"""

from __future__ import annotations

import asyncio
import functools
import logging

from .api import (_ApiError, _audit, _body, _confirm, _durable, _err, _ok,  # noqa: F401
                  _need_avail)

log = logging.getLogger("rtl.admin.api.model")

from modules._store_lock import StoreLockTimeout                       # noqa: E402
from modules.model.credentials import (CredentialError,                # noqa: E402
                                       CredentialInUse, CredentialStore)
from modules.model.endpoint_policy import EndpointRejected             # noqa: E402
from modules.model.gating import enable_gate                           # noqa: E402
from modules.model.probe import NotAuthorized, probe_protocol, probe_verified  # noqa: E402
from modules.model.registry import (PROTOCOLS, PROTOCOL_LABELS,        # noqa: E402
                                    PROVIDER_TEMPLATES, REGISTERED_ADAPTERS,
                                    Duplicate, EvidenceMissing,
                                    CredentialMissing, FrozenModel,
                                    ModelRegistry, ModelRegistryError,
                                    NotFound, CapExceeded, StoreUnavailable)
from modules.model._jsonstore import PersistError, ConfirmRequired     # noqa: E402

from .realtime_probe import realtime_capability_probe                  # noqa: E402

# ---- error mapping --------------------------------------------------------

_KNOWN_CODES = {
    "provider_in_use": 409, "model_in_use": 409, "scene_in_use": 409,
    "scene_already_bound": 409, "duplicate_provider": 409,
    "duplicate_model": 409, "unknown protocol": 400, "unknown_provider": 404,
    "unknown model": 404, "unknown scene": 404, "invalid_json": 400,
    "evidence_missing": 400,
}


def _map(exc):
    """Translate a store exception to a coded :class:`_ApiError` (or None)."""
    if isinstance(exc, _ApiError):
        return exc
    if isinstance(exc, StoreLockTimeout):
        return _ApiError(503, "store_busy")
    if isinstance(exc, StoreUnavailable):
        return _ApiError(503, "store_unavailable", getattr(exc, "reason", None))
    if isinstance(exc, PersistError):
        return _ApiError(500, "persist_failed")
    if isinstance(exc, ConfirmRequired):
        return _ApiError(400, "confirm_required", str(exc))
    if isinstance(exc, CapExceeded):
        return _ApiError(409, "cap_exceeded", str(exc))
    if isinstance(exc, FrozenModel):
        return _ApiError(400, "frozen_model", str(exc))
    if isinstance(exc, NotFound):
        return _ApiError(404, "not_found", str(exc))
    if isinstance(exc, EvidenceMissing):
        return _ApiError(400, "evidence_missing", str(exc))
    if isinstance(exc, CredentialMissing):
        return _ApiError(400, "credential_missing", str(exc))
    if isinstance(exc, CredentialInUse):
        return _ApiError(409, "credential_in_use", str(exc))
    if isinstance(exc, EndpointRejected):
        return _ApiError(400, "endpoint_not_allowed", exc.reason)
    if isinstance(exc, Duplicate):
        msg = str(exc)
        return _ApiError(409, msg if msg in _KNOWN_CODES else "duplicate", msg)
    if isinstance(exc, CredentialError):
        return _ApiError(400, "invalid_json", str(exc))
    if isinstance(exc, ModelRegistryError):
        msg = str(exc)
        return _ApiError(_KNOWN_CODES.get(msg, 400),
                         msg if msg in _KNOWN_CODES else "invalid_json", msg)
    return None


def _mguard(fn):
    """Uniform coded/sanitized error mapping for the model surface."""
    @functools.wraps(fn)
    async def wrapper(request):
        try:
            return await fn(request)
        except Exception as e:  # noqa: BLE001
            mapped = _map(e)
            if mapped is None:
                log.warning("model api error in %s: %r", fn.__name__, e)
                return _err(request, 500, "internal_error")
            return _err(request, mapped.status, mapped.code, mapped.detail)
    return wrapper


def _gate_fail(code, detail):
    http = 404 if code == "not_found" else (400 if code in (
        "frozen_model", "capability_mismatch", "evidence_missing",
        "credential_missing") else 400)
    return _ApiError(http, code or "capability_mismatch", detail)


# ---- store access ---------------------------------------------------------

def _st(request, name):
    stores = request.app["admin_stores"]
    s = getattr(stores, name, None)
    if s is None:
        raise _ApiError(503, "%s_not_configured" % name)
    return s


def _reg(request):
    return _need_avail(_st(request, "model_registry"))


def _creds(request):
    return _need_avail(_st(request, "model_credentials"))


def _resolver(request):
    return request.app.get("model_endpoint_resolver")


def _probe_opener(request):
    return request.app.get("model_probe_opener")


def _disk_registry(store):
    try:
        return ModelRegistry(store.path).load()
    except Exception as e:  # noqa: BLE001
        log.warning("model registry disk read-back failed: %r", e)
        return None


def _disk_creds(store):
    try:
        return CredentialStore(store.path, key_path=store.key_path).load()
    except Exception as e:  # noqa: BLE001
        log.warning("credential store disk read-back failed: %r", e)
        return None


def _need_str(body, name, *, cap=200):
    v = body.get(name)
    if not isinstance(v, str) or not v.strip():
        raise _ApiError(400, "invalid_json", detail="%s string required" % name)
    return v.strip()[:cap]


# ---- providers ------------------------------------------------------------

def _provider_view(reg, rec):
    out = dict(rec)
    out["adapter"] = reg.adapter_of(rec.get("protocol"))
    out["protocol_label"] = PROTOCOL_LABELS.get(rec.get("protocol"),
                                                rec.get("protocol"))
    return out


@_mguard
async def provider_templates(request):
    return _ok(request, {"available": True, "templates": [dict(t) for t in PROVIDER_TEMPLATES]})


@_mguard
async def providers_list(request):
    reg = _reg(request)
    rows = [_provider_view(reg, r) for r in reg.list_providers()]
    return _ok(request, {"available": True, "count": len(rows), "providers": rows,
                         "protocols": {k: {"label": v["label"], "adapter": v["adapter"],
                                           "registered": v["adapter"] in REGISTERED_ADAPTERS}
                                       for k, v in PROTOCOLS.items()}})


@_mguard
async def provider_create(request):
    reg = _reg(request)
    body = await _body(request)
    rec = reg.create_provider(
        name=_need_str(body, "name", cap=60),
        protocol=_need_str(body, "protocol", cap=40),
        base_url=_need_str(body, "base_url", cap=300),
        capabilities=body.get("capabilities"),
        allow_local=bool(body.get("allow_local")),
        template_id=(str(body["template_id"])[:60] if isinstance(
            body.get("template_id"), str) else None),
        resolver=_resolver(request))
    disk = _disk_registry(reg)
    _audit(request, "model_provider_create", subject=rec["id"])
    _durable(request, bool(disk) and disk.provider(rec["id"]) is not None)
    return _ok(request, {"available": True, "provider": _provider_view(reg, rec),
                         "readback_ok": True})


@_mguard
async def provider_get(request):
    reg = _reg(request)
    rec = reg.get_provider(request.match_info["provider_id"])
    if rec is None:
        raise _ApiError(404, "not_found")
    return _ok(request, {"available": True, "provider": _provider_view(reg, rec)})


@_mguard
async def provider_update(request):
    reg = _reg(request)
    body = await _body(request)
    pid = request.match_info["provider_id"]
    rec = reg.update_provider(pid, name=body.get("name"), protocol=body.get("protocol"),
                              base_url=body.get("base_url"),
                              capabilities=body.get("capabilities"),
                              allow_local=body.get("allow_local"),
                              resolver=_resolver(request))
    disk = _disk_registry(reg)
    _audit(request, "model_provider_update", subject=pid,
           changed=[k for k in ("name", "protocol", "base_url", "capabilities",
                                "allow_local") if k in body])
    _durable(request, bool(disk) and disk.provider(pid) is not None
             and disk.provider(pid).get("updated_at") == rec["updated_at"])
    return _ok(request, {"available": True, "provider": _provider_view(reg, rec),
                         "readback_ok": True})


@_mguard
async def provider_delete(request):
    reg = _reg(request)
    body = await _body(request)
    pid = request.match_info["provider_id"]
    if str(body.get("confirm") or "") != pid:
        raise _ApiError(400, "confirm_required",
                        detail="confirm must equal the provider id")
    out = reg.delete_provider(pid, confirm=pid)
    disk = _disk_registry(reg)
    _audit(request, "model_provider_delete", subject=pid)
    _durable(request, bool(disk) and disk.provider(pid) is None)
    return _ok(request, {"available": True, "deleted": out, "readback_ok": True})


# ---- models ---------------------------------------------------------------

@_mguard
async def models_list(request):
    reg = _reg(request)
    provider_id = request.query.get("provider_id") or None
    scene = request.query.get("scene") or None
    enabled_raw = request.query.get("enabled")
    enabled = None if enabled_raw is None else str(enabled_raw).lower() in ("1", "true", "yes")
    rows = reg.list_models(provider_id=provider_id, scene=scene, enabled=enabled)
    return _ok(request, {"available": True, "count": len(rows), "models": rows,
                         "scene_defs": reg.scene_defs(),
                         "bindings": reg.bindings(),
                         "defaults": {s: reg.default_for(s) for s in reg.scene_defs()}})


@_mguard
async def model_create(request):
    reg = _reg(request)
    body = await _body(request)
    rec = reg.create_model(provider_id=_need_str(body, "provider_id", cap=64),
                           model_key=_need_str(body, "model_key", cap=120),
                           display_name=body.get("display_name"),
                           capabilities=body.get("capabilities"),
                           protocol=body.get("protocol"))
    disk = _disk_registry(reg)
    _audit(request, "model_create", subject=rec["id"])
    _durable(request, bool(disk) and disk.get_model(rec["id"]) is not None)
    return _ok(request, {"available": True, "model": rec, "readback_ok": True})


@_mguard
async def model_get(request):
    reg = _reg(request)
    rec = reg.get_model(request.match_info["model_id"])
    if rec is None:
        raise _ApiError(404, "not_found")
    return _ok(request, {"available": True, "model": rec,
                         "provider": reg.get_provider(rec["provider_id"])})


@_mguard
async def model_update(request):
    reg = _reg(request)
    body = await _body(request)
    mid = request.match_info["model_id"]
    rec = reg.update_model(mid, model_key=body.get("model_key"),
                           display_name=body.get("display_name"),
                           capabilities=body.get("capabilities"))
    disk = _disk_registry(reg)
    _audit(request, "model_update", subject=mid,
           changed=[k for k in ("model_key", "display_name", "capabilities") if k in body])
    out = reg.get_model(mid)
    _durable(request, bool(disk) and disk.get_model(mid) is not None)
    return _ok(request, {"available": True, "model": out, "readback_ok": True})


@_mguard
async def model_delete(request):
    reg = _reg(request)
    body = await _body(request)
    mid = request.match_info["model_id"]
    if str(body.get("confirm") or "") != mid:
        raise _ApiError(400, "confirm_required",
                        detail="confirm must equal the model id")
    out = reg.delete_model(mid, confirm=mid)
    disk = _disk_registry(reg)
    _audit(request, "model_delete", subject=mid)
    _durable(request, bool(disk) and disk.get_model(mid) is None)
    return _ok(request, {"available": True, "deleted": out, "readback_ok": True})


@_mguard
async def model_enable(request):
    reg, creds = _reg(request), _creds(request)
    mid = request.match_info["model_id"]
    ok, code, detail = enable_gate(reg, creds, mid, scene=None, action="enable")
    if not ok:
        raise _gate_fail(code, detail)
    reg.set_enabled(mid, True)
    disk = _disk_registry(reg)
    _audit(request, "model_enable", subject=mid)
    _durable(request, bool(disk) and (disk.get_model(mid) or {}).get("enabled") is True)
    return _ok(request, {"available": True, "model": reg.get_model(mid),
                         "readback_ok": True})


@_mguard
async def model_disable(request):
    reg = _reg(request)
    mid = request.match_info["model_id"]
    reg.set_enabled(mid, False)
    disk = _disk_registry(reg)
    _audit(request, "model_disable", subject=mid)
    _durable(request, bool(disk) and (disk.get_model(mid) or {}).get("enabled") is False)
    return _ok(request, {"available": True, "model": reg.get_model(mid),
                         "readback_ok": True})


def _test_authorized(request):
    return str(request.app.get("model_test_authorized") or "").strip().lower() in (
        "1", "true", "yes")


def _promote_authorized(request):
    return str(request.app.get("model_promote_authorized") or "").strip().lower() in (
        "1", "true", "yes")


def _realtime_probe_authorized(request):
    # P2-B2-R3-2C: the realtime-handshake probe has its OWN authorization flag
    # (default off) — separate from the metadata-test flag and from promotion.
    return str(request.app.get("model_realtime_probe_authorized") or "").strip().lower() in (
        "1", "true", "yes")


@_mguard
async def model_test(request):
    reg, creds = _reg(request), _creds(request)
    mid = request.match_info["model_id"]
    model = reg.get_model(mid)
    if model is None:
        raise _ApiError(404, "not_found")
    if model.get("frozen"):
        raise _ApiError(400, "frozen_model")
    body = await _body(request)
    mode = str(body.get("mode") or "protocol")
    if mode not in ("protocol", "verified", "realtime_handshake"):
        raise _ApiError(400, "invalid_json",
                        detail="mode must be protocol|verified|realtime_handshake")
    adapter = reg.adapter_of(model.get("protocol"))
    if mode == "protocol":
        out = probe_protocol(model.get("protocol"), adapter)
        _audit(request, "model_test_protocol", subject=mid)
        return _ok(request, {"available": True, "result": out, "wrote_evidence": False})
    if mode == "realtime_handshake":
        # P2-B2-R3-2C: the honest evidence channel for dashscope realtime
        # models.  Own authorization flag + explicit confirm; dials the
        # provider's OWN endpoint with the provider's OWN sealed credential
        # (never the global/Tina key — there is no read path to it here);
        # writes at most the honest `realtime_handshake` ladder level (never
        # verified/realtime_safe — the audio stage is a later, separately
        # authorized gate).  Probing works on a disabled model on purpose:
        # evidence is a PRECONDITION of enable, not its consequence.
        if not _realtime_probe_authorized(request) or \
                body.get("confirm_realtime") is not True:
            raise _ApiError(403, "realtime_probe_not_authorized",
                            detail="实时握手验证需产品负责人独立授权（当前环境未开启）")
        prov = reg.get_provider(model["provider_id"])
        if prov is None:
            raise _ApiError(404, "not_found")
        if prov.get("frozen") or str(prov.get("id") or "") == "prov_frozen_tina":
            raise _ApiError(400, "frozen_provider")
        from app.teacher_voice import provider_realtime_binding
        ws_url, _workspace, region = provider_realtime_binding(
            prov.get("base_url"), model.get("model_key"))
        if not ws_url or not _workspace or region != "cn-beijing":
            raise _ApiError(400, "realtime_binding_unavailable",
                            detail="该服务商地址无法派生实时验证端点"
                                   "（需业务空间绑定的 https 地址）")
        ref = creds.current_ref(prov["id"])
        if not ref:
            raise _ApiError(400, "credential_missing")
        secret = creds.read_secret(ref)
        probe_fn = request.app.get("model_realtime_probe_fn") \
            or realtime_capability_probe
        out = await probe_fn(
            ws_url, secret, model=model.get("model_key"), voice="")
        wrote = bool(out.get("handshake") and out.get("session_compat"))
        if wrote:
            reg.set_evidence(mid, "realtime_handshake", source="realtime_probe",
                             detail={"handshake": True, "session_compat": True,
                                     "audio": "not_tested",
                                     "latency_ms": out.get("latency_ms")})
        _audit(request, "model_realtime_handshake", subject=mid,
               changed=[("realtime_handshake" if wrote else
                         ("no_handshake" if out.get("network")
                          else "offline"))])
        return _ok(request, {"available": True, "result": out,
                             "wrote_evidence": wrote,
                             "evidence_level": reg.evidence_level(mid)})
    # real (potential-charge) verification: gated, and never a generation call
    if not _test_authorized(request) or body.get("confirm_verified") is not True:
        raise _ApiError(403, "test_not_authorized",
                        detail="真实验证需产品负责人独立授权")
    prov = reg.get_provider(model["provider_id"])
    if prov is None:
        raise _ApiError(404, "not_found")
    ref = creds.current_ref(prov["id"])
    if not ref:
        raise _ApiError(400, "credential_missing")
    secret = creds.read_secret(ref)
    # The probe is synchronous (urllib): run it off the event loop so the admin
    # app — and any same-loop service — stays responsive during the up-to-5s check.
    out = await asyncio.to_thread(
        probe_verified, prov, secret, authorized=True,
        opener=_probe_opener(request), resolver=_resolver(request))
    if out.get("verified"):
        reg.set_evidence(mid, "verified", source="real_test",
                         detail={"protocol": model.get("protocol")})
    _audit(request, "model_test_verified", subject=mid,
           changed=["verified" if out.get("verified") else "not_verified"])
    return _ok(request, {"available": True, "result": out,
                         "wrote_evidence": bool(out.get("verified")),
                         "evidence_level": reg.evidence_level(mid)})


@_mguard
async def model_promote_realtime(request):
    """Explicit promotion to ``realtime_safe`` (contract §2.3 step 3).

    The path is never automatic: the protocol must have a registered adapter,
    the stored evidence must already be ``verified`` (real test), the request
    must carry ``confirm: true``, and the environment must hold the SEPARATE
    product-owner authorization (``MODEL_PROMOTE_AUTHORIZED``, default off).
    """
    reg = _reg(request)
    mid = request.match_info["model_id"]
    model = reg.get_model(mid)
    if model is None:
        raise _ApiError(404, "not_found")
    if model.get("frozen"):
        raise _ApiError(400, "frozen_model")
    body = await _body(request)
    _confirm(body)
    if not _promote_authorized(request):
        raise _ApiError(403, "promote_not_authorized",
                        detail="realtime_safe 提升需产品负责人独立授权")
    if reg.adapter_of(model.get("protocol")) not in REGISTERED_ADAPTERS:
        raise _ApiError(400, "capability_mismatch", detail="adapter_not_registered")
    out = reg.promote_realtime_safe(mid, operator="admin", confirm=True)
    disk = _disk_registry(reg)
    _audit(request, "model_promote_realtime", subject=mid, changed=["realtime_safe"])
    _durable(request, bool(disk) and disk.evidence_level(mid) == "realtime_safe")
    return _ok(request, {"available": True, "model": reg.get_model(mid),
                         "evidence": out, "evidence_level": reg.evidence_level(mid),
                         "readback_ok": True})


@_mguard
async def model_bind_scene(request):
    reg, creds = _reg(request), _creds(request)
    mid = request.match_info["model_id"]
    body = await _body(request)
    scene = _need_str(body, "scene", cap=60)
    ok, code, detail = enable_gate(reg, creds, mid, scene=scene, action="bind-scene")
    if not ok:
        raise _gate_fail(code, detail)
    out = reg.bind_scene(mid, scene, replace=bool(body.get("replace")))
    disk = _disk_registry(reg)
    _audit(request, "model_bind_scene", subject=mid, changed=["scene=%s" % scene])
    _durable(request, bool(disk) and mid in disk.bindings(scene))
    return _ok(request, {"available": True, "binding": out, "readback_ok": True})


@_mguard
async def model_set_default(request):
    reg, creds = _reg(request), _creds(request)
    mid = request.match_info["model_id"]
    body = await _body(request)
    _confirm(body)
    scene = _need_str(body, "scene", cap=60)
    ok, code, detail = enable_gate(reg, creds, mid, scene=scene, action="set-default")
    if not ok:
        raise _gate_fail(code, detail)
    out = reg.set_default(scene, mid)
    disk = _disk_registry(reg)
    _audit(request, "model_set_default", subject=mid, changed=["scene=%s" % scene])
    _durable(request, bool(disk) and disk.default_for(scene) == mid)
    return _ok(request, {"available": True, "default": out, "readback_ok": True})


# ---- credentials ----------------------------------------------------------

@_mguard
async def credentials_list(request):
    creds = _creds(request)
    rows = creds.list(provider_id=request.query.get("provider_id") or None)
    return _ok(request, {"available": True, "count": len(rows), "credentials": rows,
                         "note": "仅返回 fingerprint 与 credential_ref；永不返回明文"})


@_mguard
async def credential_create(request):
    reg, creds = _reg(request), _creds(request)
    body = await _body(request)
    pid = _need_str(body, "provider_id", cap=64)
    if reg.get_provider(pid) is None:
        raise _ApiError(404, "not_found", detail="unknown provider")
    secret = body.get("secret")
    if not isinstance(secret, str) or not secret.strip():
        raise _ApiError(400, "invalid_json", detail="secret string required")
    label = body.get("label")
    pub = creds.put(pid, secret,
                    label=(str(label)[:60] if isinstance(label, str) else None))
    disk = _disk_creds(creds)
    _audit(request, "credential_write", subject=pub["id"], changed=["configured"])
    _durable(request, bool(disk) and disk.is_configured(pid))
    return _ok(request, {"available": True, "credential": pub, "readback_ok": True})


@_mguard
async def credential_get(request):
    creds = _creds(request)
    rec = creds.get(request.match_info["cred_id"])
    if rec is None:
        raise _ApiError(404, "not_found")
    return _ok(request, {"available": True, "credential": rec})


@_mguard
async def credential_rotate(request):
    creds = _creds(request)
    body = await _body(request)
    _confirm(body)
    secret = body.get("secret")
    if not isinstance(secret, str) or not secret.strip():
        raise _ApiError(400, "invalid_json", detail="secret string required")
    cid = request.match_info["cred_id"]
    pub = creds.rotate(cid, secret, confirm=True)
    disk = _disk_creds(creds)
    _audit(request, "credential_rotate", subject=cid, changed=["v%d" % pub["current_v"]])
    _durable(request, bool(disk) and (disk.get(cid) or {}).get("current_v") == pub["current_v"])
    return _ok(request, {"available": True, "credential": pub, "readback_ok": True})


@_mguard
async def credential_delete(request):
    reg, creds = _reg(request), _creds(request)
    body = await _body(request)
    _confirm(body)
    cid = request.match_info["cred_id"]
    rec = creds.get(cid)
    if rec is None:
        raise _ApiError(404, "not_found")
    pid = rec["provider_id"]
    in_use = any(m.get("provider_id") == pid and m.get("enabled")
                 for m in reg.list_models())
    out = creds.delete(cid, confirm=True, in_use=in_use)
    disk = _disk_creds(creds)
    _audit(request, "credential_delete", subject=cid)
    _durable(request, bool(disk) and disk.get(cid) is None)
    return _ok(request, {"available": True, "deleted": out, "readback_ok": True})


# ---- scenes ---------------------------------------------------------------

@_mguard
async def scenes_list(request):
    reg = _reg(request)
    defs = reg.scene_defs()
    rows = []
    for sid, meta in defs.items():
        rows.append({"id": sid, "name": meta.get("name"),
                     "need": list(meta.get("need") or []),
                     "bindings": reg.bindings(sid),
                     "default": reg.default_for(sid)})
    return _ok(request, {"available": True, "count": len(rows), "scenes": rows})


@_mguard
async def scene_bind(request):
    reg, creds = _reg(request), _creds(request)
    scene = request.match_info["scene"]
    body = await _body(request)
    mid = _need_str(body, "model_id", cap=64)
    ok, code, detail = enable_gate(reg, creds, mid, scene=scene, action="bind-scene")
    if not ok:
        raise _gate_fail(code, detail)
    out = reg.bind_scene(mid, scene, replace=bool(body.get("replace")))
    disk = _disk_registry(reg)
    _audit(request, "scene_bind", subject=mid, changed=["scene=%s" % scene])
    _durable(request, bool(disk) and mid in disk.bindings(scene))
    return _ok(request, {"available": True, "binding": out, "readback_ok": True})


@_mguard
async def scene_unbind(request):
    reg = _reg(request)
    scene = request.match_info["scene"]
    body = await _body(request)
    mid = _need_str(body, "model_id", cap=64)
    out = reg.unbind_scene(mid, scene)
    disk = _disk_registry(reg)
    _audit(request, "scene_unbind", subject=mid, changed=["scene=%s" % scene])
    _durable(request, bool(disk) and mid not in disk.bindings(scene))
    return _ok(request, {"available": True, "unbound": out, "readback_ok": True})


# ---- route table ----------------------------------------------------------

def api_route_table_model():
    return [
        ("GET", "/admin/model/provider-templates"),
        ("GET", "/admin/model/providers"),
        ("POST", "/admin/model/providers"),
        ("GET", "/admin/model/providers/{provider_id}"),
        ("PUT", "/admin/model/providers/{provider_id}"),
        ("DELETE", "/admin/model/providers/{provider_id}"),
        ("GET", "/admin/model/models"),
        ("POST", "/admin/model/models"),
        ("GET", "/admin/model/models/{model_id}"),
        ("PUT", "/admin/model/models/{model_id}"),
        ("DELETE", "/admin/model/models/{model_id}"),
        ("POST", "/admin/model/models/{model_id}/enable"),
        ("POST", "/admin/model/models/{model_id}/disable"),
        ("POST", "/admin/model/models/{model_id}/test"),
        ("POST", "/admin/model/models/{model_id}/promote-realtime"),
        ("POST", "/admin/model/models/{model_id}/bind-scene"),
        ("POST", "/admin/model/models/{model_id}/set-default"),
        ("GET", "/admin/model/credentials"),
        ("POST", "/admin/model/credentials"),
        ("GET", "/admin/model/credentials/{cred_id}"),
        ("POST", "/admin/model/credentials/{cred_id}/rotate"),
        ("DELETE", "/admin/model/credentials/{cred_id}"),
        ("GET", "/admin/model/scenes"),
        ("POST", "/admin/model/scenes/{scene}/bind"),
        ("POST", "/admin/model/scenes/{scene}/unbind"),
    ]


def mount_model(app):
    routes = [
        ("get", "/admin/model/provider-templates", provider_templates),
        ("get", "/admin/model/providers", providers_list),
        ("post", "/admin/model/providers", provider_create),
        ("get", "/admin/model/providers/{provider_id}", provider_get),
        ("put", "/admin/model/providers/{provider_id}", provider_update),
        ("delete", "/admin/model/providers/{provider_id}", provider_delete),
        ("get", "/admin/model/models", models_list),
        ("post", "/admin/model/models", model_create),
        ("get", "/admin/model/models/{model_id}", model_get),
        ("put", "/admin/model/models/{model_id}", model_update),
        ("delete", "/admin/model/models/{model_id}", model_delete),
        ("post", "/admin/model/models/{model_id}/enable", model_enable),
        ("post", "/admin/model/models/{model_id}/disable", model_disable),
        ("post", "/admin/model/models/{model_id}/test", model_test),
        ("post", "/admin/model/models/{model_id}/promote-realtime", model_promote_realtime),
        ("post", "/admin/model/models/{model_id}/bind-scene", model_bind_scene),
        ("post", "/admin/model/models/{model_id}/set-default", model_set_default),
        ("get", "/admin/model/credentials", credentials_list),
        ("post", "/admin/model/credentials", credential_create),
        ("get", "/admin/model/credentials/{cred_id}", credential_get),
        ("post", "/admin/model/credentials/{cred_id}/rotate", credential_rotate),
        ("delete", "/admin/model/credentials/{cred_id}", credential_delete),
        ("get", "/admin/model/scenes", scenes_list),
        ("post", "/admin/model/scenes/{scene}/bind", scene_bind),
        ("post", "/admin/model/scenes/{scene}/unbind", scene_unbind),
    ]
    for method, path, handler in routes:
        app.router.add_route(method.upper(), path, handler)
