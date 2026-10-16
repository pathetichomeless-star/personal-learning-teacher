"""Provider / Model / Scene / Binding / Evidence registry (contract §2, §5).

Server-authoritative by construction: the verification level an enable decision
sees comes **only** from ``_data["evidence"]`` in this file, never from a request
body.  A model is `adapter_present` because its protocol has a registered
adapter; it becomes `verified` only when :meth:`set_evidence` is called by a real
test run.  Nothing here can be set by the UI.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid

from modules.model._jsonstore import (BaseJsonStore, CapExceeded, ConfirmRequired,
                                      StoreUnavailable)
from modules.model.endpoint_policy import validate_endpoint

MAX_NAME = 60
MAX_KEY = 120
MAX_URL = 300
MAX_PROVIDERS = 50
MAX_MODELS = 200

CAPABILITIES = ("text_llm", "realtime_audio", "asr", "tts", "vad", "vision",
                "tool_calling", "streaming", "barge_in")

EVIDENCE_LEVELS = ("id_only", "adapter_present", "realtime_handshake",
                   "verified", "realtime_safe")
_EVIDENCE_ORDER = {v: i for i, v in enumerate(EVIDENCE_LEVELS)}

# protocol -> adapter availability.  ``builtin``/``partial`` are *registered*
# adapters (a `partial` one covers text only); ``planned``/``none`` are not, so a
# model on those protocols can never be verified by a test.
PROTOCOLS = {
    "dashscope": {
        "label": "DashScope 原生（阿里云百炼）", "adapter": "builtin",
        "caps": ["text_llm", "realtime_audio", "asr", "tts", "streaming",
                 "barge_in", "tool_calling"]},
    "openai_compatible": {
        "label": "OpenAI 兼容（文本 / 工具）", "adapter": "partial",
        "caps": ["text_llm", "streaming", "tool_calling"]},
    # P2-B1: 语音管线的语音面（ASR / TTS）。  它只覆盖「音频进 / 音频出」的请求-响应，
    # 不声称实时双向音频、不声称打断，也不声称 Opus 线路。
    "openai_audio_compatible": {
        "label": "OpenAI 兼容语音（语音识别 / 语音合成）", "adapter": "partial",
        "caps": ["asr", "tts", "streaming"]},
    "ollama": {
        "label": "Ollama / 自建本地推理", "adapter": "planned",
        "caps": ["text_llm", "streaming"]},
    "custom_unknown": {
        "label": "未知 / 私有协议", "adapter": "none", "caps": []},
}

REGISTERED_ADAPTERS = ("builtin", "partial")

PROTOCOL_LABELS = {k: v["label"] for k, v in PROTOCOLS.items()}

# Built-in provider templates: **quick-fill hints only** — never a fixed vendor
# list, never seeded as instances.  The model centre landing page must stay empty
# for a fresh install (contract / spec §1).
PROVIDER_TEMPLATES = (
    {"id": "dashscope", "name": "DashScope 原生（阿里云百炼）",
     "vendor": "Alibaba Cloud", "protocol": "dashscope",
     "default_base_url": "https://dashscope.aliyuncs.com",
     "capabilities": ["text_llm", "realtime_audio", "asr", "tts", "streaming",
                      "barge_in", "tool_calling"],
     "note": "可快捷填充；不是唯一可选名单"},
    {"id": "openai_compatible", "name": "OpenAI 兼容（文本 / 工具）",
     "vendor": "Generic", "protocol": "openai_compatible",
     "default_base_url": "https://api.openai.com",
     "capabilities": ["text_llm", "streaming", "tool_calling"],
     "note": "仅覆盖文本请求-响应；不保证实时双向音频 / Opus / 打断"},
    {"id": "openai_audio_compatible", "name": "OpenAI 兼容语音（ASR / TTS）",
     "vendor": "Generic", "protocol": "openai_audio_compatible",
     "default_base_url": "https://api.openai.com",
     "capabilities": ["asr", "tts", "streaming"],
     "note": "只覆盖「音频进 / 音频出」的请求-响应；不保证实时双向音频、Opus 或打断"},
    {"id": "ollama", "name": "Ollama / 自建本地推理", "vendor": "Local",
     "protocol": "ollama", "default_base_url": "http://localhost:11434",
     "capabilities": ["text_llm", "streaming"],
     "note": "适配器规划中（未注册），当前不可验证/启用"},
    {"id": "custom_unknown", "name": "未知 / 私有协议", "vendor": "Custom",
     "protocol": "custom_unknown", "default_base_url": "",
     "capabilities": [],
     "note": "必须先实现并注册适配器，不得虚构可用性"},
)
# The existing, frozen Tina realtime link is materialised as these read-only ids.
FROZEN_PROVIDER_ID = "prov_frozen_tina"
FROZEN_MODEL_ID = "mdl_frozen_tina"
FROZEN_LABEL = "Tina 实时语音（既有冻结链路 · 只读）"
FROZEN_CAPS = ("realtime_audio", "asr", "tts", "streaming", "barge_in",
               "tool_calling")

SCENE_DEFS = {
    "text_chat": {"name": "文本聊天（书面辅导 / 写作 / 语法）",
                  "need": ["text_llm", "streaming"]},
    "oral_realtime": {"name": "英语口语（实时语音对话）",
                      "need": ["realtime_audio", "streaming", "barge_in"]},
    "vision_learning": {"name": "视觉学习（看图学英语）",
                        "need": ["vision", "text_llm"]},
    # P2-B1: 组合式语音管线的两个语音面。  只要求各自的最小能力，不冒充实时语音。
    "voice_asr": {"name": "语音识别（把学生的话转成文字）", "need": ["asr"]},
    "voice_tts": {"name": "语音合成（把老师的回复读出来）", "need": ["tts"]},
}


class ModelRegistryError(ValueError):
    """Base class for registry refusals."""


class NotFound(ModelRegistryError):
    pass


class Duplicate(ModelRegistryError):
    pass


class FrozenModel(ModelRegistryError):
    """The model is part of the frozen Tina link and must not be changed."""


class EvidenceMissing(ModelRegistryError):
    """No *real* verification evidence: the gate refuses (contract §2.2 step 4)."""


class CredentialMissing(ModelRegistryError):
    """The provider has no usable credential (contract §2.2 step 5)."""


class ModelRegistry(BaseJsonStore):
    SCHEMA_VERSION = 1
    ROOT_KEYS = ("providers", "models", "scenes", "bindings", "evidence")

    # ---- seed ------------------------------------------------------------

    def ensure_seeded(self):
        with self._lock:
            self._ensure_loaded()
            defs = self._data["scenes"].get("defs")
            if not isinstance(defs, dict) or not defs:
                self._data["scenes"]["defs"] = {
                    k: {"name": v["name"], "need": list(v["need"])}
                    for k, v in SCENE_DEFS.items()}
                self._data["scenes"].setdefault("defaults", {})
                try:
                    self._persist()
                except StoreUnavailable:
                    pass
        return self

    # ---- helpers ---------------------------------------------------------

    @staticmethod
    def _clean(value, what, cap, required=False):
        s = str(value or "").strip()
        if required and not s:
            raise ModelRegistryError("%s required" % what)
        return s[:cap]

    @staticmethod
    def protocol_info(protocol):
        return PROTOCOLS.get(str(protocol or ""), PROTOCOLS["custom_unknown"])

    def adapter_of(self, protocol) -> str:
        return self.protocol_info(protocol)["adapter"]

    def model(self, model_id):
        return self._data["models"].get(str(model_id or ""))

    def provider(self, provider_id):
        return self._data["providers"].get(str(provider_id or ""))

    def evidence_level(self, model_id) -> str:
        rec = self._data["evidence"].get(str(model_id or ""))
        if isinstance(rec, dict) and rec.get("level") in _EVIDENCE_ORDER:
            return rec["level"]
        model = self.model(model_id)
        if model is None:
            return "id_only"
        # no stored evidence yet: derive the *floor* from the adapter only
        return "adapter_present" if self.adapter_of(model.get("protocol")) \
            in REGISTERED_ADAPTERS else "id_only"

    def is_frozen(self, model_id) -> bool:
        model = self.model(model_id)
        return bool(model and model.get("frozen"))

    # ---- providers -------------------------------------------------------

    def list_providers(self):
        with self._lock:
            self._ensure_loaded()
            rows = [dict(v) for v in self._data["providers"].values()]
            rows.sort(key=lambda r: (r.get("created_at") or 0, r["id"]))
            return rows

    def create_provider(self, *, name, protocol, base_url, capabilities=None,
                        allow_local=False, template_id=None, resolver=None):
        name = self._clean(name, "name", MAX_NAME, True)
        protocol = str(protocol or "")
        if protocol not in PROTOCOLS:
            raise ModelRegistryError("unknown protocol")
        url = validate_endpoint(base_url, allow_local=bool(allow_local),
                                resolver=resolver)
        caps = [c for c in (capabilities or []) if c in CAPABILITIES]
        with self._lock.exclusive():
            self.reload_if_changed()
            if len(self._data["providers"]) >= MAX_PROVIDERS:
                raise CapExceeded("provider cap reached (%d)" % MAX_PROVIDERS)
            for p in self._data["providers"].values():
                if p["name"] == name:
                    raise Duplicate("duplicate_provider")
            now = time.time()
            pid = "prov_" + uuid.uuid4().hex[:12]
            rec = {"id": pid, "name": name, "protocol": protocol,
                   "base_url": url, "allow_local": bool(allow_local),
                   "capabilities": caps, "enabled": True,
                   "template_id": template_id,
                   "frozen": False, "created_at": now, "updated_at": now}
            self._data["providers"][pid] = rec
            self._persist()
            return dict(rec)

    def update_provider(self, provider_id, *, name=None, protocol=None,
                        base_url=None, capabilities=None, allow_local=None,
                        resolver=None):
        with self._lock.exclusive():
            self.reload_if_changed()
            rec = self._data["providers"].get(str(provider_id or ""))
            if rec is None:
                raise NotFound("unknown provider")
            if rec.get("frozen"):
                raise FrozenModel("provider is frozen")
            if name is not None:
                rec["name"] = self._clean(name, "name", MAX_NAME, True)
            if protocol is not None:
                if protocol not in PROTOCOLS:
                    raise ModelRegistryError("unknown protocol")
                rec["protocol"] = protocol
            if base_url is not None:
                local = bool(rec.get("allow_local")) if allow_local is None \
                    else bool(allow_local)
                rec["base_url"] = validate_endpoint(base_url, allow_local=local,
                                                    resolver=resolver)
            if allow_local is not None:
                rec["allow_local"] = bool(allow_local)
            if capabilities is not None:
                rec["capabilities"] = [c for c in capabilities if c in CAPABILITIES]
            rec["updated_at"] = time.time()
            self._persist()
            return dict(rec)

    def delete_provider(self, provider_id, *, confirm=None):
        with self._lock.exclusive():
            self.reload_if_changed()
            rec = self._data["providers"].get(str(provider_id or ""))
            if rec is None:
                raise NotFound("unknown provider")
            if confirm != rec["id"]:
                raise ConfirmRequired("confirm must equal the provider id")
            if rec.get("frozen"):
                raise FrozenModel("provider is frozen")
            users = [m["id"] for m in self._data["models"].values()
                     if m.get("provider_id") == rec["id"]]
            if users:
                raise ModelRegistryError("provider_in_use")
            del self._data["providers"][rec["id"]]
            self._persist()
            return {"deleted": rec["id"]}

    # ---- models ----------------------------------------------------------

    def list_models(self, *, provider_id=None, scene=None, enabled=None):
        with self._lock:
            self._ensure_loaded()
            rows = []
            for m in self._data["models"].values():
                if provider_id is not None and m.get("provider_id") != str(provider_id):
                    continue
                if enabled is not None and bool(m.get("enabled")) != bool(enabled):
                    continue
                if scene is not None and str(scene) not in (m.get("scenes") or []):
                    continue
                out = dict(m)
                out["evidence_level"] = self.evidence_level(m["id"])
                out["adapter"] = self.adapter_of(m.get("protocol"))
                rows.append(out)
            rows.sort(key=lambda r: (r.get("created_at") or 0, r["id"]))
            return rows

    def get_model(self, model_id):
        with self._lock:
            self._ensure_loaded()
            m = self.model(model_id)
            if m is None:
                return None
            out = dict(m)
            out["evidence_level"] = self.evidence_level(m["id"])
            out["adapter"] = self.adapter_of(m.get("protocol"))
            return out

    def create_model(self, *, provider_id, model_key, display_name=None,
                     capabilities=None, protocol=None):
        key = self._clean(model_key, "model_key", MAX_KEY, True)
        with self._lock.exclusive():
            self.reload_if_changed()
            prov = self._data["providers"].get(str(provider_id or ""))
            if prov is None:
                raise NotFound("unknown_provider")
            if len(self._data["models"]) >= MAX_MODELS:
                raise CapExceeded("model cap reached (%d)" % MAX_MODELS)
            proto = str(protocol or prov.get("protocol") or "")
            for m in self._data["models"].values():
                if m["provider_id"] == prov["id"] and m["model_key"] == key:
                    raise Duplicate("duplicate_model")
            now = time.time()
            mid = "mdl_" + uuid.uuid4().hex[:12]
            rec = {"id": mid, "provider_id": prov["id"], "model_key": key,
                   "display_name": self._clean(display_name, "display_name",
                                               MAX_NAME) or key,
                   "protocol": proto,
                   "capabilities": [c for c in (capabilities or []) if c in CAPABILITIES],
                   "scenes": [], "enabled": False, "frozen": False,
                   "created_at": now, "updated_at": now}
            self._data["models"][mid] = rec
            self._persist()
            out = dict(rec)
            out["evidence_level"] = self.evidence_level(mid)
            out["adapter"] = self.adapter_of(proto)
            return out

    def update_model(self, model_id, *, model_key=None, display_name=None,
                     capabilities=None):
        with self._lock.exclusive():
            self.reload_if_changed()
            rec = self._data["models"].get(str(model_id or ""))
            if rec is None:
                raise NotFound("unknown model")
            if rec.get("frozen"):
                raise FrozenModel("model is frozen")
            if model_key is not None:
                rec["model_key"] = self._clean(model_key, "model_key", MAX_KEY, True)
            if display_name is not None:
                rec["display_name"] = self._clean(display_name, "display_name", MAX_NAME)
            if capabilities is not None:
                rec["capabilities"] = [c for c in capabilities if c in CAPABILITIES]
            rec["updated_at"] = time.time()
            self._persist()
            return dict(rec)

    def delete_model(self, model_id, *, confirm=None):
        with self._lock.exclusive():
            self.reload_if_changed()
            rec = self._data["models"].get(str(model_id or ""))
            if rec is None:
                raise NotFound("unknown model")
            if rec.get("frozen"):
                raise FrozenModel("model is frozen")
            if confirm != rec["id"]:
                raise ConfirmRequired("confirm must equal the model id")
            del self._data["models"][rec["id"]]
            self._data["evidence"].pop(rec["id"], None)
            for scene, ids in list(self._data["bindings"].items()):
                self._data["bindings"][scene] = [i for i in ids if i != rec["id"]]
            for scene, mid in list(self._data["scenes"].get("defaults", {}).items()):
                if mid == rec["id"]:
                    self._data["scenes"]["defaults"].pop(scene, None)
            self._persist()
            return {"deleted": rec["id"]}

    # ---- enable / scenes -------------------------------------------------

    def set_enabled(self, model_id, enabled: bool):
        with self._lock.exclusive():
            self.reload_if_changed()
            rec = self._data["models"].get(str(model_id or ""))
            if rec is None:
                raise NotFound("unknown model")
            if rec.get("frozen"):
                raise FrozenModel("model is frozen")
            rec["enabled"] = bool(enabled)
            rec["updated_at"] = time.time()
            self._persist()
            return dict(rec)

    def scene_defs(self):
        with self._lock:
            self._ensure_loaded()
            defs = self._data["scenes"].get("defs") or {}
            return {k: {"name": v.get("name"), "need": list(v.get("need") or [])}
                    for k, v in defs.items()}

    def bindings(self, scene=None):
        with self._lock:
            self._ensure_loaded()
            if scene is None:
                return {k: list(v) for k, v in self._data["bindings"].items()}
            return list(self._data["bindings"].get(str(scene), []))

    def bind_scene(self, model_id, scene, *, replace=False):
        scene = str(scene or "")
        with self._lock.exclusive():
            self.reload_if_changed()
            rec = self._data["models"].get(str(model_id or ""))
            if rec is None:
                raise NotFound("unknown model")
            if rec.get("frozen"):
                raise FrozenModel("model is frozen")
            defs = self._data["scenes"].get("defs") or {}
            if scene not in defs:
                raise NotFound("unknown scene")
            if not replace and scene in rec.get("scenes", []):
                raise Duplicate("scene_already_bound")
            ids = self._data["bindings"].setdefault(scene, [])
            if rec["id"] not in ids:
                ids.append(rec["id"])
            if scene not in rec["scenes"]:
                rec["scenes"].append(scene)
            rec["updated_at"] = time.time()
            self._persist()
            return {"model_id": rec["id"], "scene": scene, "bindings": list(ids)}

    def unbind_scene(self, model_id, scene):
        with self._lock.exclusive():
            self.reload_if_changed()
            rec = self._data["models"].get(str(model_id or ""))
            if rec is None:
                raise NotFound("unknown model")
            if rec.get("frozen"):
                raise FrozenModel("model is frozen")
            ids = self._data["bindings"].get(str(scene), [])
            self._data["bindings"][str(scene)] = [i for i in ids if i != rec["id"]]
            rec["scenes"] = [s for s in rec.get("scenes", []) if s != str(scene)]
            rec["updated_at"] = time.time()
            self._persist()
            return {"model_id": rec["id"], "scene": str(scene)}

    def set_default(self, scene, model_id):
        with self._lock.exclusive():
            self.reload_if_changed()
            rec = self._data["models"].get(str(model_id or ""))
            if rec is None:
                raise NotFound("unknown model")
            if rec.get("frozen"):
                raise FrozenModel("model is frozen")
            self._data["scenes"].setdefault("defaults", {})[str(scene)] = rec["id"]
            self._persist()
            return {"scene": str(scene), "model_id": rec["id"]}

    def default_for(self, scene):
        with self._lock:
            self._ensure_loaded()
            return (self._data["scenes"].get("defaults") or {}).get(str(scene))

    # ---- evidence (server authority) -------------------------------------

    def set_evidence(self, model_id, level, *, source="test", detail=None):
        """Write the real verification level.  Only a genuine test run may call this.

        The stored level is a **high-water mark** (contract §5.1 ladder): a later
        successful *re-test* records its run but never silently lowers an already
        achieved level — a promotion to ``realtime_safe`` must not be revoked by a
        plain ``verified`` test run.
        """
        if level not in _EVIDENCE_ORDER:
            raise ModelRegistryError("unknown evidence level")
        with self._lock.exclusive():
            self.reload_if_changed()
            rec = self._data["models"].get(str(model_id or ""))
            if rec is None:
                raise NotFound("unknown model")
            prev = self._data["evidence"].get(rec["id"]) or {}
            runs = list(prev.get("runs") or [])
            runs.append({"level": level, "source": str(source),
                         "at": time.time(), "detail": detail})
            keep = prev.get("level")
            if keep in _EVIDENCE_ORDER and _EVIDENCE_ORDER[keep] > _EVIDENCE_ORDER[level]:
                # high-water mark: the run is recorded, the level is not demoted
                self._data["evidence"][rec["id"]] = {
                    "level": keep, "source": prev.get("source") or str(source),
                    "at": prev.get("at") or time.time(), "runs": runs[-20:]}
            else:
                self._data["evidence"][rec["id"]] = {
                    "level": level, "source": str(source), "at": time.time(),
                    "runs": runs[-20:]}
            self._persist()
            return dict(self._data["evidence"][rec["id"]])

    def promote_realtime_safe(self, model_id, *, operator="admin", confirm=False):
        """Explicit, authorized promotion (contract §2.3).  Never automatic."""
        if confirm is not True:
            raise ConfirmRequired("confirm: true is required")
        cur = self.evidence_level(model_id)
        if _EVIDENCE_ORDER.get(cur, 0) < _EVIDENCE_ORDER["verified"]:
            raise ModelRegistryError("evidence_missing")
        return self.set_evidence(model_id, "realtime_safe",
                                 source="authorized_promotion:%s" % operator)

    def mark_frozen(self, model_id, frozen=True):
        with self._lock.exclusive():
            self.reload_if_changed()
            rec = self._data["models"].get(str(model_id or ""))
            if rec is None:
                raise NotFound("unknown model")
            rec["frozen"] = bool(frozen)
            rec["enabled"] = False if frozen else rec.get("enabled")
            rec["updated_at"] = time.time()
            self._persist()
            return dict(rec)

    # ---- frozen Tina link (auto-detected, read-only) ----------------------

    def get_provider(self, provider_id):
        with self._lock:
            self._ensure_loaded()
            rec = self._data["providers"].get(str(provider_id or ""))
            return dict(rec) if rec else None

    def ensure_frozen_link(self, snapshot):
        """Materialise the *existing* frozen Tina realtime link as read-only rows.

        This only mirrors what the runtime already uses (contract §5.3).  It never
        touches user-created providers/models and can never enable or disable the
        real link — the mirror is display-only, marked ``frozen:true``.
        """
        snap = dict(snapshot or {})
        model_key = str(snap.get("model") or "").strip()
        if not model_key:
            return None
        digest = hashlib.sha256(
            json.dumps(snap, ensure_ascii=False, sort_keys=True,
                       default=str).encode("utf-8")).hexdigest()[:16]
        with self._lock.exclusive():
            self.reload_if_changed()
            now = time.time()
            prov = self._data["providers"].get(FROZEN_PROVIDER_ID)
            if prov is None:
                prov = {"id": FROZEN_PROVIDER_ID,
                        "name": "DashScope 原生（冻结 Tina 链路）",
                        "protocol": "dashscope",
                        "base_url": "https://dashscope.aliyuncs.com",
                        "allow_local": False, "capabilities": list(FROZEN_CAPS),
                        "enabled": True, "template_id": "dashscope",
                        "frozen": True, "origin": "detected_frozen_link",
                        "created_at": now, "updated_at": now}
                self._data["providers"][FROZEN_PROVIDER_ID] = prov
            rec = self._data["models"].get(FROZEN_MODEL_ID)
            if rec is None:
                rec = {"id": FROZEN_MODEL_ID, "provider_id": FROZEN_PROVIDER_ID,
                       "model_key": model_key, "display_name": FROZEN_LABEL,
                       "protocol": "dashscope", "capabilities": list(FROZEN_CAPS),
                       "scenes": ["oral_realtime"], "enabled": True,
                       "frozen": True, "origin": "detected_frozen_link",
                       "voice": str(snap.get("voice") or ""),
                       "snapshot": snap, "snapshot_hash": digest,
                       "created_at": now, "updated_at": now}
                self._data["models"][FROZEN_MODEL_ID] = rec
            else:
                rec.update({"model_key": model_key, "enabled": True,
                            "frozen": True,
                            "voice": str(snap.get("voice") or ""),
                            "snapshot": snap, "snapshot_hash": digest,
                            "updated_at": now})
            prev = self._data["evidence"].get(FROZEN_MODEL_ID) or {}
            self._data["evidence"][FROZEN_MODEL_ID] = {
                "level": "realtime_safe", "source": "detected_frozen_link",
                "at": now, "runs": list(prev.get("runs") or [])[-20:]}
            ids = self._data["bindings"].setdefault("oral_realtime", [])
            if FROZEN_MODEL_ID not in ids:
                ids.insert(0, FROZEN_MODEL_ID)
            self._data["scenes"].setdefault("defaults", {})["oral_realtime"] = \
                FROZEN_MODEL_ID
            self._persist()
            out = dict(rec)
            out["evidence_level"] = "realtime_safe"
            out["adapter"] = "builtin"
            return out

    def frozen_snapshot_hash(self):
        with self._lock:
            self._ensure_loaded()
            rec = self._data["models"].get(FROZEN_MODEL_ID) or {}
            return rec.get("snapshot_hash")


def frozen_link_snapshot(*, mode="", model="", voice="", host="", frame_ms=None,
                         reconnect_max=None, region="", extra=None):
    """Build the read-only snapshot of the existing realtime configuration."""
    snap = {"mode": str(mode or ""), "model": str(model or ""),
            "voice": str(voice or ""), "host": str(host or ""),
            "region": str(region or ""), "frame_ms": frame_ms,
            "reconnect_max": reconnect_max,
            "vad": "server-side (Qwen realtime)", "opus_frame_ms": frame_ms,
            "barge_in": True}
    if extra:
        snap.update(dict(extra))
    return snap
