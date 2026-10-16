"""TEACHER_VOICE_SEAM_TESTS — P2-B2 isolated verification of the non-intrusive
teacher-voice seam (gateway/app/teacher_voice.py).

Scope (isolated only — NO real model, NO paid call, NO NAS):
  * flag OFF  -> the teacher route is NOT mounted (frozen behaviour unchanged)
  * fail-closed mount (no token / no teacher store)
  * server-side authorization (deployment token, constant-time) BEFORE any teacher
  * teacher resolution fail-closed (unknown / disabled / frozen / text-mode)
  * per-connection config: teacher model/voice injected, base QwenConfig NOT mutated
  * cross-teacher isolation: two teachers -> distinct model/voice, no shared stores
  * default resolver refuses honestly (`realtime_not_configured`) with no registry
  * [R1] credential isolation: a teacher connection carries ONLY its own provider
    credential — the global (Tina) api_key / workspace is never read, never
    inherited, never re-emitted; missing / incompatible provider material fails
    CLOSED (`credential_missing`, `provider_incompatible`,
    `realtime_endpoint_not_configured`, `credential_isolation_violation`).
  * [R3-0] the operator `enabled` switch on the model is enforced server-side
    BEFORE any credential / endpoint step: a disabled model (or a record with no
    `enabled` key) is refused with `model_disabled` — never a silent fallback to
    Tina or to another model.  Frozen still wins over disabled.

The frozen engine (turns.Connection / qwen.QwenClient) is substituted by a fake
factory so this test needs no Qwen upstream, no network and no libopus at runtime.

Standalone:  python tests/teacher_voice_seam_tests.py   (from gateway/, venv)
"""

import asyncio
import os
import sys
import tempfile
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
_GATEWAY = os.path.dirname(_HERE)
_REPO = os.path.dirname(_GATEWAY)
for p in (_GATEWAY, _REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

import aiohttp                                                      # noqa: E402
from aiohttp import web, test_utils                                 # noqa: E402

from app import teacher_voice as tv                                 # noqa: E402
from modules.teacher.store import TeacherStore                      # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % detail)[:200] if not cond else ""))


def _base_qwen(model="qwen-global", voice="Tina", mode="mock", api_key="",
               workspace_id="ws1", region="cn-beijing"):
    return SimpleNamespace(mode=mode, ws_url="ws://127.0.0.1:9977",
                           model=model, voice=voice, api_key=api_key,
                           workspace_id=workspace_id, region=region,
                           reconnect_max=5, reconnect_base_ms=500,
                           stable_reset_s=30)


def _base_config(**over):
    cfg = SimpleNamespace(
        TEACHER_FILE="", MODEL_REGISTRY_FILE="", MODEL_CREDENTIALS_FILE="",
        MODEL_CREDENTIALS_KEY_FILE="", TEACHER_VOICE_DATA_DIR="",
        TEACHER_VOICE_TOKEN_FILE="", TEACHER_VOICE_WS="0",
        FRAME_MS=20, PUBLIC_WS_URL="ws://x",
        MEMORY_FILE="/global/memory.json", POLICY_FILE="/global/policy.json",
        KNOWLEDGE_FILE="/global/kb.json", WORKBENCH_BASE_URL="")
    cfg.qwen = _base_qwen()
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


class FakeConnection:
    built = []

    def __init__(self, ws, config):
        self.ws = ws
        self.config = config
        FakeConnection.built.append(self)

    async def on_connect(self):
        pass

    async def handle_text(self, raw):
        pass

    def handle_binary(self, data):
        pass

    async def close(self):
        pass


def _mk_teacher_store(tmp):
    path = os.path.join(tmp, "teachers.json")
    store = TeacherStore(path).load().ensure_seeded()          # seeds frozen tina
    store.create_teacher(name="老师A", subject="english", language="en",
                         teaching_style="patient",
                         voice={"mode": "realtime", "voice_id": "VoiceA"},
                         model={"realtime_model_id": "mdl_a"})
    store.create_teacher(name="老师B", subject="math", language="zh",
                         teaching_style="strict",
                         voice={"mode": "realtime", "voice_id": "VoiceB"},
                         model={"realtime_model_id": "mdl_b"})
    return store


def _stub_resolver(opts, teacher):
    """Test resolver: build an isolated (mock) Qwen config per teacher."""
    return tv.build_teacher_qwen(opts.qwen, model="mock-" + teacher["teacher_id"],
                                 voice=(teacher.get("voice") or {}).get("voice_id") or "",
                                 mode="mock")


async def main():
    tmp = tempfile.mkdtemp(prefix="p2b2-seam-")
    os.environ.pop("TEACHER_VOICE_TOKEN", None)
    FakeConnection.built = []
    tv._connection_factory = FakeConnection

    # ---------- pure-function / authorization ----------
    check("T3a authorize: missing header -> invalid_token",
          tv.authorize(SimpleNamespace(headers={}), "tok") == (False, "invalid_token"))
    check("T3b authorize: wrong token -> invalid_token",
          tv.authorize(SimpleNamespace(headers={tv.HEADER_TEACHER_TOKEN: "bad"}), "tok")
          == (False, "invalid_token"))
    check("T3c authorize: correct token -> ok",
          tv.authorize(SimpleNamespace(headers={tv.HEADER_TEACHER_TOKEN: "tok"}), "tok")
          == (True, ""))
    check("T3d authorize: no configured token -> not_configured",
          tv.authorize(SimpleNamespace(headers={tv.HEADER_TEACHER_TOKEN: "x"}), "")
          == (False, "teacher_voice_not_configured"))

    # ---------- per-connection config construction ----------
    base = _base_config()
    base_qwen_id = id(base.qwen)
    tq = tv.build_teacher_qwen(base.qwen, model="m-A", voice="VoiceA", mode="mock")
    check("T5a build_teacher_qwen returns a NEW object", tq is not base.qwen)
    check("T5b base QwenConfig NOT mutated (model/voice)",
          base.qwen.model == "qwen-global" and base.qwen.voice == "Tina")
    check("T5c teacher qwen carries the teacher model/voice",
          tq.model == "m-A" and tq.voice == "VoiceA" and id(base.qwen) == base_qwen_id)
    # R1: a real teacher config is built ONLY from explicitly supplied provider
    # material — the global config's credentials are never consulted.
    tq_real = tv.build_teacher_qwen(
        base.qwen, model="m-R", voice="vR", mode="real", api_key="K-R",
        workspace_id="ws-r", region="cn-beijing",
        real_ws_url="wss://ws-r.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model=m-R")
    check("T5d mode=real uses the SUPPLIED endpoint (not the global workspace)",
          tq_real.ws_url.startswith("wss://ws-r.cn-beijing.maas.aliyuncs.com/")
          and "model=m-R" in tq_real.ws_url
          and tq_real.api_key == "K-R" and tq_real.workspace_id == "ws-r")

    cfg_a = tv.build_teacher_config(base, qwen_cfg=tq, teacher_id="tch_A",
                                    data_dir=os.path.join(tmp, "data"))
    cfg_b = tv.build_teacher_config(base, qwen_cfg=tq, teacher_id="tch_B",
                                    data_dir=os.path.join(tmp, "data"))
    check("T6a unscoped config mounts NO store (paths are projection-supplied)",
          cfg_a.MEMORY_FILE == "" and cfg_a.POLICY_FILE == ""
          and cfg_a.KNOWLEDGE_FILE == "")
    check("T6b base config NOT mutated (MEMORY_FILE/qwen)",
          base.MEMORY_FILE == "/global/memory.json" and base.qwen.voice == "Tina")
    cfg_nodir = tv.build_teacher_config(base, qwen_cfg=tq, teacher_id="tch_A",
                                        data_dir="")
    check("T6c no data dir -> NO shared stores (empty paths)",
          cfg_nodir.MEMORY_FILE == "" and cfg_nodir.POLICY_FILE == ""
          and cfg_nodir.KNOWLEDGE_FILE == "")
    cfg_scoped = tv.build_teacher_config(
        base, qwen_cfg=tq, teacher_id="tch_A", data_dir=os.path.join(tmp, "data"),
        policy_file="/p/tch_A/policy.json", knowledge_file="/p/tch_A/kb.json")
    check("T6d only the VERIFIED projection paths are ever mounted",
          cfg_scoped.POLICY_FILE == "/p/tch_A/policy.json"
          and cfg_scoped.KNOWLEDGE_FILE == "/p/tch_A/kb.json"
          and cfg_scoped.MEMORY_FILE == "")
    check("T6e the global workbench link is NOT inherited by a teacher conn",
          cfg_scoped.WORKBENCH_BASE_URL == ""
          and base.WORKBENCH_BASE_URL == "")
    cfg_wb = tv.build_teacher_config(
        _base_config(WORKBENCH_BASE_URL="https://workbench.global"),
        qwen_cfg=tq, teacher_id="tch_A", data_dir=os.path.join(tmp, "data"))
    check("T6f a configured global workbench is still cleared for teachers",
          cfg_wb.WORKBENCH_BASE_URL == "")

    # ---------- teacher resolution ----------
    store = _mk_teacher_store(tmp)

    def _raises_code(fn, code):
        try:
            fn()
            return False
        except tv.TeacherVoiceUnavailable as e:
            return e.code == code

    def _raises(fn, code):
        try:
            fn()
            return False
        except tv.TeacherVoiceUnavailable as e:
            return e.code == code
    check("T4a unknown teacher -> teacher_not_found",
          _raises(lambda: tv.resolve_teacher(store, "nope"), "teacher_not_found"))
    check("T4b blank teacher -> teacher_id_required",
          _raises(lambda: tv.resolve_teacher(store, ""), "teacher_id_required"))
    check("T4c frozen tina -> frozen_realtime_only",
          _raises(lambda: tv.resolve_teacher(store, "tina"), "frozen_realtime_only"))
    tid_a = [r["teacher_id"] for r in store.list_teachers() if r.get("name") == "老师A"][0]
    store.update_teacher(tid_a, voice={"mode": "text", "voice_id": ""})
    check("T4d text-mode teacher -> voice_mode_text",
          _raises(lambda: tv.resolve_teacher(store, tid_a), "voice_mode_text"))
    store.update_teacher(tid_a, voice={"mode": "realtime", "voice_id": "VoiceA"})
    store.set_enabled(tid_a, False)
    check("T4e disabled teacher -> teacher_disabled",
          _raises(lambda: tv.resolve_teacher(store, tid_a), "teacher_disabled"))
    store.set_enabled(tid_a, True)
    check("T4f valid realtime teacher -> resolved",
          tv.resolve_teacher(store, tid_a)["teacher_id"] == tid_a)

    # ---------- R1: credential isolation (build layer) ----------
    base_key = _base_qwen(api_key="TINA-KEY", workspace_id="tina-ws",
                          region="cn-beijing")
    check("T10a real mode without own credential -> credential_missing",
          _raises_code(lambda: tv.build_teacher_qwen(base_key, model="m", voice="v",
                                                     mode="real"),
                       "credential_missing"))
    check("T10b real mode without own endpoint -> realtime_endpoint_not_configured",
          _raises_code(lambda: tv.build_teacher_qwen(base_key, model="m", voice="v",
                                                     mode="real", api_key="K-A"),
                       "realtime_endpoint_not_configured"))
    qa = tv.build_teacher_qwen(
        base_key, model="m-A", voice="vA", mode="real", api_key="K-A",
        workspace_id="wsa", region="cn-beijing",
        real_ws_url="wss://wsa.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model=m-A")
    check("T10c teacher qwen carries its OWN credential",
          qa.api_key == "K-A" and qa.workspace_id == "wsa")
    check("T10d teacher qwen does NOT inherit the global credential",
          qa.api_key != base_key.api_key and qa.workspace_id != base_key.workspace_id)
    check("T10e global (Tina) credential untouched by the teacher build",
          base_key.api_key == "TINA-KEY" and base_key.workspace_id == "tina-ws")
    qb = tv.build_teacher_qwen(
        base_key, model="m-B", voice="vB", mode="real", api_key="K-B",
        workspace_id="wsb", region="cn-beijing",
        real_ws_url="wss://wsb.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model=m-B")
    check("T10f teacher A/B credentials are isolated",
          qa.api_key == "K-A" and qb.api_key == "K-B" and qa.api_key != qb.api_key)
    qm = tv.build_teacher_qwen(base_key, model="m", voice="v", mode="mock")
    check("T10g mock teacher carries NO credential material",
          qm.api_key == "" and qm.workspace_id == "" and qm.region == "")

    # provider-scoped endpoint derivation
    b1 = tv.provider_realtime_binding("https://wsa.cn-beijing.maas.aliyuncs.com", "m-A")
    check("T10h binding derived from the provider base_url only",
          b1 == ("wss://wsa.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model=m-A",
                 "wsa", "cn-beijing"))
    b2 = tv.provider_realtime_binding("https://dashscope.aliyuncs.com", "m-A")
    check("T10i host without a workspace -> caller must fail closed",
          b2[0].startswith("wss://dashscope.aliyuncs.com/") and b2[1] == ""
          and b2[2] == "")
    check("T10j unusable base_url -> empty binding",
          tv.provider_realtime_binding("", "m-A") == ("", "", "")
          and tv.provider_realtime_binding("ftp://x", "m-A") == ("", "", ""))
    check("T10k look-alike host / bad port -> refused (no workspace leaked in)",
          tv.provider_realtime_binding("https://a.b.maas.aliyuncs.com.evil.com",
                                       "m-A")[1] == ""
          and tv.provider_realtime_binding("https://host:abc", "m-A") == ("", "", "")
          and tv.provider_realtime_binding("https://evil.maas.aliyuncs.com",
                                           "m-A")[1] == "")

    # ---------- R1: credential isolation (resolver layer) ----------
    from modules.model.credentials import CredentialStore
    from modules.model.registry import ModelRegistry

    reg_path = os.path.join(tmp, "r1_registry.json")
    cred_path = os.path.join(tmp, "r1_credentials.json")
    key_path = os.path.join(tmp, "r1_credentials.key")
    reg = ModelRegistry(reg_path).load().ensure_seeded()
    creds = CredentialStore(cred_path, key_path=key_path).load()

    def _rt_provider(name, protocol, base_url, key, model_key, enabled=True):
        p = reg.create_provider(name=name, protocol=protocol, base_url=base_url)
        m = reg.create_model(provider_id=p["id"], model_key=model_key,
                             capabilities=["realtime_audio", "streaming", "barge_in"])
        reg.set_evidence(m["id"], "realtime_safe", source="test")
        if enabled:
            # R3-0: a model must be operator-enabled to be resolvable; a fixture
            # that skips this would silently rely on the missing gate.
            reg.set_enabled(m["id"], True)
        if key:
            creds.put(p["id"], key)
        return p, m

    p_ok, m_ok = _rt_provider("老师A服务商", "dashscope",
                              "https://wsa.cn-beijing.maas.aliyuncs.com",
                              "K-A-secret", "qwen-realtime-a")
    p_bad, m_bad = _rt_provider("老师B服务商", "openai_compatible",
                                "https://api.openai.com", "K-B-secret", "gpt-b")
    p_pub, m_pub = _rt_provider("公有服务商", "dashscope",
                                "https://dashscope.aliyuncs.com",
                                "K-P-secret", "qwen-realtime-pub")
    p_nocred, m_nocred = _rt_provider("无凭据服务商", "dashscope",
                                      "https://wsc.cn-beijing.maas.aliyuncs.com",
                                      "", "qwen-realtime-c")

    rc = _base_config(MODEL_REGISTRY_FILE=reg_path,
                      MODEL_CREDENTIALS_FILE=cred_path,
                      MODEL_CREDENTIALS_KEY_FILE=key_path)
    rc.qwen = _base_qwen(api_key="TINA-KEY", workspace_id="tina-ws",
                         region="cn-beijing")
    opts_r = tv._opts(rc)

    rq = tv.default_resolver(opts_r, {"model": {"realtime_model_id": m_ok["id"]},
                                      "voice": {"voice_id": "VoiceA"}})
    check("T11a resolver injects the PROVIDER credential, not the global one",
          rq.api_key == "K-A-secret" and rq.workspace_id == "wsa"
          and rq.region == "cn-beijing" and rq.model == "qwen-realtime-a"
          and rq.voice == "VoiceA")
    check("T11b resolved endpoint is the provider's own host (no global workspace)",
          rq.ws_url.startswith("wss://wsa.cn-beijing.maas.aliyuncs.com/")
          and "tina-ws" not in rq.ws_url)
    check("T11c global (Tina) credential still untouched after resolve",
          rc.qwen.api_key == "TINA-KEY" and rc.qwen.workspace_id == "tina-ws")
    dumped = "%r" % (vars(rq),)
    check("T11d resolved config never carries the global credential",
          "TINA-KEY" not in dumped and "tina-ws" not in dumped)
    check("T11e provider protocol the engine cannot drive -> provider_incompatible",
          _raises(lambda: tv.default_resolver(
              opts_r, {"model": {"realtime_model_id": m_bad["id"]}}),
              "provider_incompatible"))
    check("T11f provider host without workspace -> realtime_endpoint_not_configured",
          _raises(lambda: tv.default_resolver(
              opts_r, {"model": {"realtime_model_id": m_pub["id"]}}),
              "realtime_endpoint_not_configured"))
    check("T11g provider without credential -> credential_missing",
          _raises(lambda: tv.default_resolver(
              opts_r, {"model": {"realtime_model_id": m_nocred["id"]}}),
              "credential_missing"))
    creds.put(p_ok["id"], "TINA-KEY")            # same value as the global key
    check("T11h provider credential equal to the global one -> refused",
          _raises(lambda: tv.default_resolver(
              opts_r, {"model": {"realtime_model_id": m_ok["id"]}}),
              "credential_isolation_violation"))
    creds.put(p_ok["id"], "K-A-secret-2")        # rotate back to a distinct key
    check("T11i rotation keeps isolation (new distinct key still accepted)",
          tv.default_resolver(opts_r, {"model": {"realtime_model_id": m_ok["id"]}}
                              ).api_key == "K-A-secret-2")

    # ---------- R3-0: the operator `enabled` gate on the resolver ----------
    # The admin `enable_gate` never looks at `model.enabled`, so without this
    # check an operator-disabled model could still be driven on this route.
    import json as _json

    def _refusal(fn):
        """Return (code, detail, resolved) — `resolved` is the returned config.

        A refusal must yield a code AND no resolved config; a code with a config
        would mean a silent downgrade, which the contract forbids.
        """
        try:
            got = fn()
        except tv.TeacherVoiceUnavailable as e:
            return e.code, e.detail or "", None
        return None, None, got

    opt = lambda mid: {"model": {"realtime_model_id": mid}}        # noqa: E731

    # (a) disabled + no credential   -> must report the DISABLED code
    p_dis, m_dis = _rt_provider("停用服务商", "dashscope",
                                "https://wsd.cn-beijing.maas.aliyuncs.com",
                                "", "qwen-realtime-d", enabled=False)
    # (b) disabled but otherwise fully valid down to the endpoint -> same code
    p_dis2, m_dis2 = _rt_provider("停用公有服务商", "dashscope",
                                  "https://dashscope.aliyuncs.com",
                                  "K-D2-secret", "qwen-realtime-d2", enabled=False)

    code_a, _, got_a = _refusal(lambda: tv.default_resolver(opts_r, opt(m_dis["id"])))
    check("T11j operator-disabled model -> model_disabled (and nothing resolved)",
          code_a == "model_disabled" and got_a is None)

    # Falsifiable ordering proof 1: only toggling `enabled` moves the code.
    reg.set_enabled(m_dis["id"], True)
    code_on, _, _ = _refusal(lambda: tv.default_resolver(opts_r, opt(m_dis["id"])))
    reg.set_enabled(m_dis["id"], False)
    code_off, _, _ = _refusal(lambda: tv.default_resolver(opts_r, opt(m_dis["id"])))
    check("T11k refusal precedes the credential gate "
          "(enabled -> credential_missing, disabled -> model_disabled)",
          code_on == "credential_missing" and code_off == "model_disabled",
          "%s / %s" % (code_on, code_off))

    # Falsifiable ordering proof 2: the model would pass gate + provider +
    # protocol + credential and fail only at the LAST (endpoint) step.
    reg.set_enabled(m_dis2["id"], True)
    code_ep, _, _ = _refusal(lambda: tv.default_resolver(opts_r, opt(m_dis2["id"])))
    reg.set_enabled(m_dis2["id"], False)
    code_ep2, _, _ = _refusal(lambda: tv.default_resolver(opts_r, opt(m_dis2["id"])))
    check("T11l refusal precedes the endpoint gate "
          "(enabled -> realtime_endpoint_not_configured, disabled -> model_disabled)",
          code_ep == "realtime_endpoint_not_configured"
          and code_ep2 == "model_disabled", "%s / %s" % (code_ep, code_ep2))

    # (c) an absent `enabled` key (hand-edited / corrupt record) -> fail closed
    _raw = _json.loads(open(reg_path, encoding="utf-8").read())
    _saved = _raw["models"][m_ok["id"]].pop("enabled", None)
    with open(reg_path, "w", encoding="utf-8") as _fh:
        _fh.write(_json.dumps(_raw, ensure_ascii=False))
    code_abs, _, _ = _refusal(lambda: tv.default_resolver(opts_r, opt(m_ok["id"])))
    reg.set_enabled(m_ok["id"], True)            # also rewrites the key
    check("T11m record without an `enabled` key -> model_disabled (fail closed)",
          code_abs == "model_disabled", "saved=%r" % (_saved,))

    # (d) the frozen refusal is NOT masked by the new check (frozen comes first)
    reg.mark_frozen(m_ok["id"], True)
    code_fz, _, _ = _refusal(lambda: tv.default_resolver(opts_r, opt(m_ok["id"])))
    check("T11n frozen model still -> frozen_model (frozen is checked first)",
          code_fz == "frozen_model")
    reg.mark_frozen(m_ok["id"], False)
    reg.set_enabled(m_ok["id"], True)

    # (e) re-enabling restores a real resolve with the PROVIDER's own credential:
    #     no silent fallback to Tina, and the global link stays untouched.
    got_re = tv.default_resolver(opts_r, opt(m_ok["id"]))
    check("T11o re-enabled model resolves again with its own credential (no fallback)",
          got_re.api_key == "K-A-secret-2" and "TINA-KEY" not in "%r" % (vars(got_re),)
          and rc.qwen.api_key == "TINA-KEY" and rc.qwen.workspace_id == "tina-ws")


    # ---------- default resolver honesty (no registry) ----------
    check("T8 default resolver fails closed with no registry",
          _raises(lambda: tv.default_resolver(tv._opts(_base_config()),
                                              {"model": {"realtime_model_id": "mdl_a"}}),
                  "realtime_not_configured"))

    # ---------- mount fail-closed ----------
    teachers_path = os.path.join(tmp, "teachers.json")
    app0 = web.Application()
    check("T1a flag OFF -> route NOT mounted",
          tv.mount(app0, _base_config(TEACHER_VOICE_WS="0",
                                      TEACHER_FILE=teachers_path)) is False
          and len(app0.router.routes()) == 0)
    app1 = web.Application()
    check("T1b flag ON but no token -> mount refused (fail closed)",
          tv.mount(app1, _base_config(TEACHER_VOICE_WS="1",
                                      TEACHER_FILE=teachers_path,
                                      TEACHER_VOICE_TOKEN_FILE="")) is False
          and len(app1.router.routes()) == 0)
    tok_path = os.path.join(tmp, "tv_token")
    app1b = web.Application()
    check("T1c flag ON + token file absent -> mount refused",
          tv.mount(app1b, _base_config(TEACHER_VOICE_WS="1",
                                       TEACHER_FILE=teachers_path,
                                       TEACHER_VOICE_TOKEN_FILE=tok_path)) is False
          and len(app1b.router.routes()) == 0)
    with open(tok_path, "w", encoding="utf-8") as f:
        f.write("deploy-token-xyz\n")
    app2 = web.Application()
    ok2 = tv.mount(app2, _base_config(TEACHER_VOICE_WS="1",
                                      TEACHER_FILE=teachers_path,
                                      TEACHER_VOICE_TOKEN_FILE=tok_path))
    check("T2 flag ON + real token file -> route mounted",
          ok2 and any(r.resource.canonical == tv.TEACHER_WS_PATH
                      for r in app2.router.routes()))

    # ---------- end-to-end handler over a real WS (frozen engine stubbed) ----------
    app = web.Application()
    cfg = _base_config(TEACHER_VOICE_WS="1",
                       TEACHER_FILE=os.path.join(tmp, "teachers.json"),
                       TEACHER_VOICE_TOKEN_FILE=tok_path)
    app.router.add_get(tv.TEACHER_WS_PATH,
                       tv.make_handler(cfg, store, "deploy-token-xyz",
                                       resolver=_stub_resolver))
    server = test_utils.TestServer(app)
    await server.start_server()
    url = server.make_url(tv.TEACHER_WS_PATH)
    try:
        async with aiohttp.ClientSession() as sess:
            # (1) no token -> 401, no connection built
            FakeConnection.built = []
            got401 = False
            try:
                async with sess.ws_connect(url) as _ws:
                    pass
            except aiohttp.WSServerHandshakeError as e:
                got401 = (e.status == 401)
            check("T9a no token -> 401 and NO teacher connection built",
                  got401 and len(FakeConnection.built) == 0)

            # (2) token but unknown teacher -> 409
            got409 = False
            try:
                async with sess.ws_connect(str(url) + "?teacher_id=nope",
                                           headers={tv.HEADER_TEACHER_TOKEN: "deploy-token-xyz"}) as _ws:
                    pass
            except aiohttp.WSServerHandshakeError as e:
                got409 = (e.status == 409)
            check("T9b unknown teacher -> 409 refused", got409)

            # (3) token + frozen tina -> 409
            got_frozen = False
            try:
                async with sess.ws_connect(str(url) + "?teacher_id=tina",
                                           headers={tv.HEADER_TEACHER_TOKEN: "deploy-token-xyz"}) as _ws:
                    pass
            except aiohttp.WSServerHandshakeError as e:
                got_frozen = (e.status == 409)
            check("T9c frozen tina refused (never reconfigured)", got_frozen)

            # (4) teacher A -> connection built with teacher-scoped config
            qa = str(url) + "?teacher_id=" + tid_a
            FakeConnection.built = []
            async with sess.ws_connect(qa, headers={tv.HEADER_TEACHER_TOKEN: "deploy-token-xyz"}) as ws:
                await ws.send_str('{"type":"hello","version":1}')
                await asyncio.sleep(0.05)
            check("T9d teacher A connection built", len(FakeConnection.built) == 1)
            if FakeConnection.built:
                ca = FakeConnection.built[0].config
                check("T9e teacher A qwen.model/voice injected",
                      ca.qwen.model == "mock-" + tid_a and ca.qwen.voice == "VoiceA")
                check("T9f base (global/Tina) qwen UNCHANGED after teacher conn",
                      cfg.qwen.model == "qwen-global" and cfg.qwen.voice == "Tina")
                check("T9g teacher A carries no global store and no global workbench",
                      ca.MEMORY_FILE == "" and ca.POLICY_FILE == ""
                      and ca.WORKBENCH_BASE_URL == "")

        # server stopped accepting checks above; make a second connection for B
        async with aiohttp.ClientSession() as sess:
            tid_b = [r["teacher_id"] for r in store.list_teachers()
                     if r.get("name") == "老师B"][0]
            FakeConnection.built = []
            async with sess.ws_connect(str(url) + "?teacher_id=" + tid_b,
                                       headers={tv.HEADER_TEACHER_TOKEN: "deploy-token-xyz"}) as ws:
                await asyncio.sleep(0.05)
            check("T9h teacher B connection built", len(FakeConnection.built) == 1)
            if FakeConnection.built:
                cb = FakeConnection.built[0].config
                check("T9i teacher A/B configs are isolated (model+voice differ)",
                      cb.qwen.model == "mock-" + tid_b and cb.qwen.voice == "VoiceB")
    finally:
        await server.close()
        tv._connection_factory = None

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print("\n%s  %d/%d" % ("ALL PASS" if passed == total else "FAILURES", passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
