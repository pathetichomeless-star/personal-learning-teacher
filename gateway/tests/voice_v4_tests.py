"""VOICE_V4_TESTS — P2-B1 multi-teacher voice-teaching infrastructure suite.

Runs standalone:  python tests/voice_v4_tests.py   (from gateway/, venv)

Everything here is a **real backend linkage** test: the admin app is exercised over
HTTP (aiohttp TestClient) and every voice exchange performs **real HTTP calls** to a
reproducible local mock speech service (a second aiohttp server implementing
``/v1/chat/completions``, ``/v1/audio/transcriptions`` and ``/v1/audio/speech``).
No paid provider is contacted, nothing is fabricated, and the audio that flows
through the pipeline is an **isolated test source** (deterministic bytes generated
by the test) — so a pass proves the interface and the state machine work, never
that real speech quality or real barge-in has been accepted.

Coverage (the eight required checks of the P2-B1 order):

  V1 a new teacher gets its own, independent voice configuration
  V2 starting is refused when model / adapter capability does not match
  V3 switching teachers never bleeds the previous teacher's config
  V4 channel create / close / timeout / error cleanup
  V5 correct teacher + student attribution of voice class records
  V6 no audio evidence -> no pronunciation verdict is ever produced
  V7 the text classroom is not regressed
  V8 the frozen Tina configuration is untouched
"""

import asyncio
import base64
import json
import os
import socket
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from aiohttp import web                                        # noqa: E402
from aiohttp.test_utils import TestClient, TestServer          # noqa: E402

from app.admin.app import admin_route_table, create_admin_app  # noqa: E402
from app.admin.auth import TokenStore                          # noqa: E402
from app.admin.config import load_admin_config                 # noqa: E402
from app.admin.password_auth import PasswordStore, SessionStore  # noqa: E402
from app.admin.stores import AdminStores                       # noqa: E402
from modules.model.gating import enable_gate                   # noqa: E402
from modules.teaching.store import TeachingSessionStore        # noqa: E402
from modules.voice import TEST_PIPELINE_ID, get_adapter, list_adapters  # noqa: E402
from modules.voice.capability import (CapabilityInvalid,       # noqa: E402
                                      validate as validate_capability)
from modules.voice.session import VoiceChannelStore            # noqa: E402

FIX_TOKEN = "VOICE_V4_BEARER_TOKEN_DO_NOT_LEAK_24680"
AUTH = {"Authorization": "Bearer " + FIX_TOKEN}
SECRET = "sk-voice-secret-never-leak-13579"
RESULTS = []

FAKE_IP = lambda host: ["93.184.216.34"]                        # noqa: E731

# a deterministic, explicitly non-human "isolated test audio source": 0.25s of
# 16 kHz mono PCM16 silence plus a recognisable header run.  It is real *bytes*
# (so the audio path is real) but it is not a human voice — and the tests never
# treat it as one.
TEST_PCM = (b"\x01\x02" * 8) + (b"\x00" * (16000 // 4 * 2))


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % (detail,)) if (detail and not cond) else ""))


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---------------------------------------------------------------------------
# reproducible local speech / text upstream (a real HTTP server)
# ---------------------------------------------------------------------------

class MockSpeechUpstream:
    """Deterministic OpenAI-compatible upstream: chat + ASR + TTS.

    Its replies carry ``marker`` so a test can prove WHICH upstream was called.
    ``fail_asr`` makes the ASR endpoint return 500, which is how the error /
    cleanup path is exercised without inventing a transcript.
    """

    def __init__(self, marker):
        self.marker = marker
        self.port = _free_port()
        self.seen = []              # (system, last_user) for chat calls
        self.asr_calls = 0
        self.tts_calls = 0
        self.fail_asr = False
        self._runner = None

    @property
    def base_url(self):
        return "http://127.0.0.1:%d" % self.port

    async def start(self):
        async def models(request):
            return web.json_response({"object": "list", "data": [
                {"id": "mock", "object": "model", "owned_by": "test"}]})

        async def chat(request):
            try:
                body = await request.json()
            except Exception:  # noqa: BLE001
                body = {}
            msgs = body.get("messages") or []
            system, last_user = "", ""
            for m in msgs:
                if (m or {}).get("role") == "system":
                    system += str((m or {}).get("content") or "")
                if (m or {}).get("role") == "user":
                    last_user = str((m or {}).get("content") or "")
            self.seen.append((system, last_user))
            reply = ("[%s] 收到问题：%s ｜系统提示长度=%d"
                     % (self.marker, last_user[:60], len(system)))
            return web.json_response({
                "object": "chat.completion", "model": str(body.get("model") or "mock"),
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": reply}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

        async def asr(request):
            self.asr_calls += 1
            if self.fail_asr:
                return web.json_response({"error": "asr_down"}, status=500)
            try:
                body = await request.json()
            except Exception:  # noqa: BLE001
                body = {}
            ia = body.get("input_audio") or {}
            nbytes = len(str(ia.get("data") or "")) * 3 // 4
            return web.json_response({
                "text": "[%s] 测试音频转写(%d字节)" % (self.marker, nbytes)})

        async def tts(request):
            self.tts_calls += 1
            try:
                body = await request.json()
            except Exception:  # noqa: BLE001
                body = {}
            pcm = b"\x00" * (int(body.get("sample_rate") or 24000) // 4 * 2)
            return web.json_response({"audio": base64.b64encode(pcm).decode(),
                                      "format": "pcm16"})

        app = web.Application()
        app.router.add_get("/v1/models", models)
        app.router.add_post("/v1/chat/completions", chat)
        app.router.add_post("/v1/audio/transcriptions", asr)
        app.router.add_post("/v1/audio/speech", tts)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, "127.0.0.1", self.port).start()
        return self

    async def stop(self):
        if self._runner is not None:
            await self._runner.cleanup()


# ---------------------------------------------------------------------------
# admin app harness
# ---------------------------------------------------------------------------

def _cfg(tmp):
    p = os.path.join(tmp, "tok")
    with open(p, "w") as fh:
        fh.write(FIX_TOKEN + "\n")
    os.chmod(p, 0o600)
    return load_admin_config(env={
        "ADMIN_ENABLED": "1", "ADMIN_BIND": "127.0.0.1", "ADMIN_PORT": "18162",
        "ADMIN_API_TOKEN_FILE": p, "ADMIN_API_TOKEN": "",
        "ADMIN_USERS_FILE": os.path.join(tmp, "users.json"),
        "ADMIN_SESSIONS_FILE": os.path.join(tmp, "sessions.json")})


def _stores(tmp, sub="stores"):
    d = os.path.join(tmp, sub)
    os.makedirs(d, exist_ok=True)
    return AdminStores(
        policy_file=os.path.join(d, "policy.json"),
        memory_file=os.path.join(d, "memory.json"),
        knowledge_file=os.path.join(d, "knowledge.json"),
        workbench_url="",
        model_registry_file=os.path.join(d, "registry.json"),
        model_credentials_file=os.path.join(d, "creds.json"),
        model_credentials_key_file=os.path.join(d, "creds.key"),
        knowledge_import_file=os.path.join(d, "imports.json"),
        knowledge_import_scratch=os.path.join(d, "scratch"),
        teacher_file=os.path.join(d, "teachers.json"),
        teaching_file=os.path.join(d, "teaching.json"),
        voice_file=os.path.join(d, "voices.json"),
        realtime_snapshot={"mode": "real", "model": "qwen3.8-omni-flash-realtime",
                           "voice": "Tina", "host": "dashscope.aliyuncs.com",
                           "frame_ms": 20},
        test_authorized=False)


def _app(tmp, stores):
    c = _cfg(tmp)
    ts = TokenStore(c.token_file, c.token_env)
    ts.reload()
    app = create_admin_app(
        admin_config=c, token_store=ts,
        gateway_info=lambda: {"mode": "real", "ready": True},
        stores=stores,
        password_store=PasswordStore(c.users_file),
        session_store=SessionStore(c.sessions_file))
    app["model_endpoint_resolver"] = FAKE_IP
    return app


def _seed_provider(stores, *, name, base_url, protocol, caps):
    return stores.model_registry.create_provider(
        name=name, protocol=protocol, base_url=base_url, allow_local=True,
        capabilities=caps, resolver=FAKE_IP)


def _seed_model(stores, prov, *, key, caps, scenes=()):
    reg = stores.model_registry
    m = reg.create_model(provider_id=prov["id"], model_key=key, capabilities=caps)
    reg.set_evidence(m["id"], "verified", source="test")
    reg.set_enabled(m["id"], True)
    for sc in scenes:
        reg.bind_scene(m["id"], sc)
    return m


def _seed_speech(stores, *, marker_url, secret):
    """Register the audio provider + ASR/TTS models bound to their voice scenes."""
    prov = _seed_provider(stores, name="本地语音服务-%s" % marker_url[-5:],
                          base_url=marker_url, protocol="openai_audio_compatible",
                          caps=["asr", "tts", "streaming"])
    asr = _seed_model(stores, prov, key="mock-asr", caps=["asr", "streaming"],
                      scenes=["voice_asr"])
    tts = _seed_model(stores, prov, key="mock-tts", caps=["tts", "streaming"],
                      scenes=["voice_tts"])
    stores.model_credentials.put(prov["id"], secret)
    return prov, asr, tts


def _audio_b64(data=TEST_PCM):
    return base64.b64encode(data).decode()


async def amain():
    tmp = tempfile.mkdtemp(prefix="voice-v4-")
    up_one = await MockSpeechUpstream("UPSTREAM-ONE").start()
    up_two = await MockSpeechUpstream("UPSTREAM-TWO").start()
    try:
        await _run(tmp, up_one, up_two)
    finally:
        await up_one.stop()
        await up_two.stop()


async def _run(tmp, up_one, up_two):
    stores = _stores(tmp)
    app = _app(tmp, stores)
    table = admin_route_table(stores=stores)
    voice_routes = {p for m, p in table if "/admin/voice/" in p}
    mounted = {r.resource.canonical for r in app.router.routes()}
    check("V0 all voice routes mounted",
          all(p in mounted for p in voice_routes), str(sorted(voice_routes)))

    # ---- capability honesty (no false claim can be registered) -------------
    try:
        validate_capability({"kind": "native_realtime",
                             "input_audio": {"containers": ["opus"], "streaming": True},
                             "output_audio": {"containers": ["opus"], "streaming": True},
                             "barge_in": True, "full_duplex": False,
                             "transcript": True})
        native_rejected = False
    except CapabilityInvalid:
        native_rejected = True
    check("Vcap-a native_realtime with full_duplex=false is rejected",
          native_rejected)
    try:
        validate_capability({"kind": "native_realtime",
                             "input_audio": {"containers": ["opus"], "streaming": True},
                             "output_audio": {"containers": ["opus"], "streaming": True}})
        undeclared_rejected = False
    except CapabilityInvalid:
        undeclared_rejected = True
    check("Vcap-b native_realtime refusing to declare duplex/barge-in is rejected",
          undeclared_rejected)
    try:
        validate_capability({"kind": "pipeline_asr_llm_tts", "stages": ["asr", "llm"],
                             "input_audio": {"containers": ["pcm16"]},
                             "output_audio": {"containers": ["pcm16"]}})
        stages_rejected = False
    except CapabilityInvalid:
        stages_rejected = True
    check("Vcap-c an incomplete pipeline (missing tts stage) is rejected",
          stages_rejected)
    try:
        validate_capability({"kind": "pipeline_asr_llm_tts", "stages": ["asr", "llm", "tts"],
                             "input_audio": {"containers": []},
                             "output_audio": {"containers": []}})
        text_only_rejected = False
    except CapabilityInvalid:
        text_only_rejected = True
    check("Vcap-d a text-only description cannot pass as a voice adapter",
          text_only_rejected)
    avail = [a for a in list_adapters() if a["available"]]
    check("Vcap-e exactly one adapter is runnable, and it is a labelled test pipeline",
          len(avail) == 1 and avail[0]["id"] == TEST_PIPELINE_ID
          and avail[0]["is_test"] is True and avail[0]["mode"] == "simulation",
          str([(a["id"], a["available"]) for a in list_adapters()]))

    # ---- seed models --------------------------------------------------------
    prov_t1, model_t1 = (None, None)
    prov_t1 = _seed_provider(stores, name="本地文字服务-1", base_url=up_one.base_url,
                             protocol="openai_compatible",
                             caps=["text_llm", "streaming"])
    model_t1 = _seed_model(stores, prov_t1, key="mock-text-one",
                           caps=["text_llm", "streaming"])
    stores.model_credentials.put(prov_t1["id"], SECRET)
    prov_t2 = _seed_provider(stores, name="本地文字服务-2", base_url=up_two.base_url,
                             protocol="openai_compatible",
                             caps=["text_llm", "streaming"])
    model_t2 = _seed_model(stores, prov_t2, key="mock-text-two",
                           caps=["text_llm", "streaming"])
    stores.model_credentials.put(prov_t2["id"], SECRET)
    _prov_s1, asr1, tts1 = _seed_speech(stores, marker_url=up_one.base_url, secret=SECRET)
    _prov_s2, asr2, tts2 = _seed_speech(stores, marker_url=up_two.base_url, secret=SECRET)

    # a plain text model must NOT satisfy a speech scene
    ok_asr, code_asr, _ = enable_gate(stores.model_registry,
                                      stores.model_credentials, model_t1["id"],
                                      scene="voice_asr", action="voice")
    check("Vcap-f a plain text-chat model fails the voice_asr gate",
          ok_asr is False and code_asr == "capability_mismatch", str(code_asr))

    kb = stores.knowledge
    ds_a = kb.create_dataset("语音课件库A")
    kb.add_document(ds_a["id"], "Voice Lesson A",
                    "uniquetokenVA 是本节课的重点词汇。" * 5)

    async with TestClient(TestServer(app)) as cl:
        async def get(p):
            r = await cl.get(p, headers=AUTH)
            return r.status, await r.json()

        async def post(p, body):
            r = await cl.post(p, headers=AUTH, json=body)
            return r.status, await r.json()

        async def put(p, body):
            r = await cl.put(p, headers=AUTH, json=body)
            return r.status, await r.json()

        # ---- V1 per-teacher, independent voice configuration ----------------
        st, ov = await get("/admin/voice/overview")
        check("V1a voice overview is available and honest",
              st == 200 and ov["available"] is True, str(ov)[:160])
        st, ad = await get("/admin/voice/adapters")
        check("V1b adapter surface declares capability and availability honestly",
              st == 200 and any(a["id"] == TEST_PIPELINE_ID and a["available"]
                                and a["is_test"] for a in ad["adapters"])
              and any(not a["available"] and a["requirement"]
                      for a in ad["adapters"]), str(ad)[:220])

        st, ca = await post("/admin/teacher/teachers", {
            "name": "语音王老师", "subject": "english", "language": "zh",
            "teaching_style": "strict",
            "voice": {"mode": "realtime", "adapter_id": TEST_PIPELINE_ID,
                      "voice_id": "voice-a", "accent": "american", "language": "en",
                      "speed": 1.1,
                      "interaction": {"barge_in": True, "allow_transcript": True,
                                      "max_turn_seconds": 60}},
            "model": {"text_model_id": model_t1["id"], "asr_model_id": asr1["id"],
                      "tts_model_id": tts1["id"]},
            "knowledge": {"dataset_ids": [ds_a["id"]]}})
        tid_a = ca["teacher"]["teacher_id"]
        check("V1c teacher A created with its own voice configuration",
              st == 200 and ca["teacher"]["voice"]["adapter_id"] == TEST_PIPELINE_ID
              and ca["teacher"]["voice"]["voice_id"] == "voice-a"
              and ca["teacher"]["voice"]["speed"] == 1.1, str(ca.get("teacher")))

        st, cb = await post("/admin/teacher/teachers", {
            "name": "语音赵老师", "subject": "math", "language": "zh",
            "teaching_style": "encouraging",
            "voice": {"mode": "realtime", "adapter_id": TEST_PIPELINE_ID,
                      "voice_id": "voice-b", "accent": "british", "language": "en"},
            "model": {"text_model_id": model_t2["id"], "asr_model_id": asr2["id"],
                      "tts_model_id": tts2["id"]}})
        tid_b = cb["teacher"]["teacher_id"]
        st, ga = await get("/admin/teacher/teachers/%s" % tid_a)
        st2, gb = await get("/admin/teacher/teachers/%s" % tid_b)
        check("V1d two teachers keep separate voice configs (no overwrite)",
              ga["teacher"]["voice"]["voice_id"] == "voice-a"
              and gb["teacher"]["voice"]["voice_id"] == "voice-b"
              and ga["teacher"]["voice"]["accent"] == "american"
              and gb["teacher"]["voice"]["accent"] == "british",
              str([ga["teacher"]["voice"], gb["teacher"]["voice"]]))
        st, _ = await put("/admin/teacher/teachers/%s" % tid_b,
                          {"voice": {"mode": "realtime", "adapter_id": TEST_PIPELINE_ID,
                                     "voice_id": "voice-b2", "accent": "neutral",
                                     "language": "en"}})
        _, ga2 = await get("/admin/teacher/teachers/%s" % tid_a)
        check("V1e editing teacher B never touches teacher A's voice config",
              st == 200 and ga2["teacher"]["voice"]["voice_id"] == "voice-a"
              and ga2["teacher"]["voice"]["accent"] == "american",
              str(ga2["teacher"]["voice"]))
        # voice config is an object independent of model / persona / knowledge
        st, _ = await put("/admin/teacher/teachers/%s" % tid_a,
                          {"teaching_style": "patient",
                           "model": {"text_model_id": model_t1["id"],
                                     "asr_model_id": asr1["id"],
                                     "tts_model_id": tts1["id"]}})
        _, ga3 = await get("/admin/teacher/teachers/%s" % tid_a)
        check("V1f voice config is independent of persona and model bindings",
              st == 200 and ga3["teacher"]["voice"]["voice_id"] == "voice-a"
              and ga3["teacher"]["voice"]["speed"] == 1.1
              and ga3["teacher"]["knowledge"]["dataset_ids"] == [ds_a["id"]],
              str(ga3["teacher"]["voice"]))
        st, r = await put("/admin/teacher/teachers/%s" % tid_a,
                          {"voice": {"mode": "realtime", "adapter_id": TEST_PIPELINE_ID,
                                     "speed": 9.9}})
        check("V1g out-of-range speed is refused", st == 400, str(r)[:140])
        st, co = await post("/admin/teacher/teachers", {
            "name": "未知适配器老师",
            "voice": {"mode": "realtime", "adapter_id": "voice_does_not_exist"}})
        st2, r = await post("/admin/voice/sessions",
                            {"teacher_id": co["teacher"]["teacher_id"]})
        check("V1h unknown adapter is refused honestly",
              st2 == 400 and r.get("error") == "voice_adapter_unknown", str(r)[:180])

        # ---- V2 refusals on capability / model mismatch ---------------------
        st, cslot = await post("/admin/teacher/teachers", {
            "name": "未接入适配器老师",
            "voice": {"mode": "realtime", "adapter_id": "voice_native_realtime_slot"},
            "model": {"text_model_id": model_t1["id"]}})
        tid_slot = cslot["teacher"]["teacher_id"]
        st, r = await post("/admin/voice/sessions", {"teacher_id": tid_slot})
        check("V2a starting is refused when the adapter is not implemented",
              st == 400 and r.get("error") == "voice_adapter_unavailable"
              and "未接入" in (r.get("detail") or ""), str(r)[:220])
        st, ctext = await post("/admin/teacher/teachers",
                               {"name": "文字模式老师", "voice": {"mode": "text"},
                                "model": {"text_model_id": model_t1["id"]}})
        st, r = await post("/admin/voice/sessions",
                           {"teacher_id": ctext["teacher"]["teacher_id"]})
        check("V2b a text-mode teacher cannot start a voice class",
              st == 400 and r.get("error") == "voice_mode_text", str(r)[:180])
        st, cnoad = await post("/admin/teacher/teachers",
                               {"name": "未选适配器老师", "voice": {"mode": "realtime"},
                                "model": {"text_model_id": model_t1["id"]}})
        st, r = await post("/admin/voice/sessions",
                           {"teacher_id": cnoad["teacher"]["teacher_id"]})
        check("V2c starting is refused when no voice adapter is configured",
              st == 400 and r.get("error") == "voice_adapter_not_configured",
              str(r)[:180])

        # unset the ASR binding -> the pipeline cannot be assembled
        st, _ = await put("/admin/teacher/teachers/%s" % tid_a,
                          {"model": {"text_model_id": model_t1["id"],
                                     "asr_model_id": "", "tts_model_id": tts1["id"]}})
        st, r = await post("/admin/voice/sessions", {"teacher_id": tid_a})
        check("V2d starting is refused when a pipeline model role is missing",
              st == 400 and r.get("error") == "voice_model_missing"
              and r.get("missing_role") == "asr" and r.get("detail"), str(r)[:240])
        # an ASR model with NO verification evidence
        m_unv = stores.model_registry.create_model(
            provider_id=_prov_s1["id"], model_key="unverified-asr",
            capabilities=["asr"])
        stores.model_registry.set_enabled(m_unv["id"], True)
        st, _ = await put("/admin/teacher/teachers/%s" % tid_a,
                          {"model": {"text_model_id": model_t1["id"],
                                     "asr_model_id": m_unv["id"],
                                     "tts_model_id": tts1["id"]}})
        st, r = await post("/admin/voice/sessions", {"teacher_id": tid_a})
        check("V2e starting is refused when a pipeline model lacks verification",
              st == 400 and r.get("error") == "evidence_missing", str(r)[:220])
        # a *text* model cannot serve the ASR role
        st, _ = await put("/admin/teacher/teachers/%s" % tid_a,
                          {"model": {"text_model_id": model_t1["id"],
                                     "asr_model_id": model_t1["id"],
                                     "tts_model_id": tts1["id"]}})
        st, r = await post("/admin/voice/sessions", {"teacher_id": tid_a})
        check("V2e2 a text-chat model is refused for the speech-recognition role",
              st == 400 and r.get("error") == "capability_mismatch", str(r)[:220])
        st, _ = await put("/admin/teacher/teachers/%s" % tid_a,
                          {"model": {"text_model_id": model_t1["id"],
                                     "asr_model_id": asr1["id"],
                                     "tts_model_id": tts1["id"]}})
        # the class may require a feature the adapter does not have
        st, r = await post("/admin/voice/sessions",
                           {"teacher_id": tid_a, "features": ["barge_in"]})
        check("V2f a required feature the adapter lacks is refused (never faked)",
              st == 400 and r.get("error") == "adapter_capability_unsupported",
              str(r)[:220])
        st, lst = await get("/admin/voice/channels")
        check("V2g no channel was created by any refusal", st == 200
              and all(c["teacher_id"] not in (tid_slot, tid_a)
                      for c in lst["channels"]), str(lst["count"]))

        # ---- V3 start a real voice class, switch teachers -------------------
        st, s1 = await post("/admin/voice/sessions",
                            {"teacher_id": tid_a, "student_id": "stu_v1",
                             "idle_timeout": 30})
        ch_a = s1.get("channel") or {}
        sess_a = s1.get("session") or {}
        check("V3a voice class started with the teacher's own adapter + config",
              st == 200 and ch_a.get("status") == "ready"
              and ch_a.get("adapter_id") == TEST_PIPELINE_ID
              and ch_a.get("adapter_is_test") is True
              and (ch_a.get("voice") or {}).get("voice_id") == "voice-a"
              and sess_a.get("modality") == "voice", str(s1)[:300])
        check("V3b the transcript capability is reported from the adapter declaration",
              s1["speech"]["transcript_supported"] is True
              and s1["speech"]["barge_in_supported"] is False
              and s1["speech"]["full_duplex"] is False
              and s1["speech"]["mode"] == "simulation", str(s1.get("speech"))[:260])
        check("V3c the teacher's unsupported preference is disclosed, not pretended",
              "barge_in" in (s1["speech"].get("unsupported_requested") or []),
              str(s1["speech"].get("unsupported_requested")))

        st, s2 = await post("/admin/voice/sessions",
                            {"teacher_id": tid_b, "student_id": "stu_v1",
                             "idle_timeout": 30})
        ch_b = s2.get("channel") or {}
        sess_b = s2.get("session") or {}
        check("V3d switching teachers closes the previous channel (release)",
              st == 200 and s2["replaced_channels"]
              and s2["replaced_channels"][0]["channel_id"] == ch_a["channel_id"]
              and s2["replaced_channels"][0]["close_reason"] == "teacher_switch",
              json.dumps(s2.get("replaced_channels"))[:220])
        _, ch_a_after = await get("/admin/voice/channels/%s" % ch_a["channel_id"])
        check("V3e the previous channel is closed, not merely marked",
              ch_a_after["channel"]["status"] == "ended"
              and ch_a_after["channel"]["is_open"] is False,
              str(ch_a_after["channel"])[:180])
        _, sess_a_after = await get("/admin/teaching/sessions/%s"
                                    % sess_a["session_id"])
        check("V3f the previous teacher's class record was closed",
              sess_a_after["session"]["status"] == "ended")

        _, gb_now = await get("/admin/teacher/teachers/%s" % tid_b)
        b_voice_id = (gb_now["teacher"]["voice"] or {}).get("voice_id")
        check("V3g the new class carries the NEW teacher's config only",
              (ch_b.get("voice") or {}).get("voice_id") == b_voice_id
              and b_voice_id != "voice-a"
              and sess_b.get("teacher_id") == tid_b
              and sess_b.get("model_id") == model_t2["id"]
              and (ch_b.get("voice") or {}).get("accent") == "neutral",
              str([ch_b.get("voice"), sess_b.get("model_id")]))

        # teacher B speaks: the system prompt must be B's, never A's
        st, m_b = await post("/admin/voice/channels/%s/audio" % ch_b["channel_id"],
                             {"audio_b64": _audio_b64(),
                              "format": "pcm16", "sample_rate": 16000})
        sys_b = up_two.seen[-1][0] if up_two.seen else ""
        sys_a_last = up_one.seen[-1][0] if up_one.seen else ""
        check("V3h the reply came from teacher B's own upstream",
              st == 200 and "UPSTREAM-TWO" in (m_b.get("reply") or ""), str(m_b)[:220])
        check("V3i teacher A's instruction did not leak into teacher B's class",
              "互动伙伴" in sys_b and "纠错者" not in sys_b and "严格" not in sys_b,
              (sys_b[:120], sys_a_last[:60]))
        check("V3j synthetic audio is reported honestly (never a real-voice claim)",
              m_b["audio_out"]["attempted"] is True and m_b["audio_out"]["ok"] is True
              and ch_b.get("adapter_is_test") is True,
              str(m_b.get("audio_out"))[:180])

        # ---- V4 lifecycle: timeout + error cleanup --------------------------
        st, s3 = await post("/admin/voice/sessions",
                            {"teacher_id": tid_a, "student_id": "stu_v2",
                             "idle_timeout": 10})
        ch_c = s3["channel"]
        sess_c = s3["session"]
        # the sweep is deterministic: the caller may inject `now`
        st, sw = await post("/admin/voice/sweep",
                            {"now": (ch_c["last_activity_at"] or 0) + 11})
        check("V4a an idle channel is reaped as a timeout",
              st == 200 and any(c["channel_id"] == ch_c["channel_id"]
                                and c["status"] == "timeout" for c in sw["channels"]),
              json.dumps(sw)[:220])
        check("V4b the timed-out class record was closed too",
              sess_c["session_id"] in sw["sessions_closed"], str(sw["sessions_closed"]))
        _, ch_c_after = await get("/admin/voice/channels/%s" % ch_c["channel_id"])
        check("V4c the reaped channel reports why it was cleaned up",
              ch_c_after["channel"]["close_reason"] == "idle_timeout"
              and ch_c_after["channel"]["error_code"] == "idle_timeout",
              str(ch_c_after["channel"])[:200])

        # an upstream failure must be reported, never replaced by invented output
        st, s4 = await post("/admin/voice/sessions",
                            {"teacher_id": tid_a, "student_id": "stu_v3",
                             "idle_timeout": 60})
        ch_d = s4["channel"]
        up_one.fail_asr = True
        st, r = await post("/admin/voice/channels/%s/audio" % ch_d["channel_id"],
                           {"audio_b64": _audio_b64(), "format": "pcm16",
                            "sample_rate": 16000})
        up_one.fail_asr = False
        check("V4d a failed speech call is an error, never a fabricated transcript",
              st == 502 and r.get("error") == "upstream_http_500"
              and not r.get("transcript"), str(r)[:200])
        _, ch_d_after = await get("/admin/voice/channels/%s" % ch_d["channel_id"])
        check("V4e the channel moved to the error state with a coded reason",
              ch_d_after["channel"]["status"] == "error"
              and ch_d_after["channel"]["error_code"] == "upstream_http_500",
              str(ch_d_after["channel"])[:200])
        st, r = await post("/admin/voice/channels/%s/audio" % ch_d["channel_id"],
                           {"audio_b64": _audio_b64()})
        check("V4f a dead channel refuses further audio", st == 400
              and r.get("error") == "channel_closed", str(r)[:160])
        st, r = await post("/admin/voice/channels/%s/interrupt" % ch_d["channel_id"], {})
        check("V4g a closed channel cannot be interrupted", st == 404
              or r.get("error") in ("channel_closed", "channel_not_found"),
              str(r)[:160])

        # ---- V5 attribution + audio evidence --------------------------------
        check("V5a the transcript came back from the real ASR upstream call",
              "UPSTREAM-TWO" in (m_b.get("transcript") or "")
              and up_two.asr_calls >= 1, str(m_b)[:200])
        check("V5a2 the reply audio came back from the real TTS upstream call",
              up_two.tts_calls >= 1 and (m_b.get("audio_out") or {}).get("audio_bytes", 0) > 0,
              json.dumps(m_b.get("audio_out"))[:180])
        _, sess_b_full = await get("/admin/teaching/sessions/%s" % sess_b["session_id"])
        turns = sess_b_full["session"]["turns"]
        speech = [t for t in turns if t.get("kind") == "speech"]
        check("V5b a speech turn carries real audio metadata (never audio bytes)",
              speech and speech[0]["audio"]["bytes"] == len(TEST_PCM)
              and "data" not in speech[0]["audio"]
              and speech[0]["audio"]["source"] == "isolated_test_source",
              json.dumps(speech[:1])[:220])
        check("V5c the record attributes the class to the right teacher + student",
              sess_b_full["session"]["teacher_id"] == tid_b
              and sess_b_full["session"]["student_id"] == "stu_v1"
              and sess_b_full["session"]["modality"] == "voice")
        st, vs = await get("/admin/voice/sessions?student_id=stu_v1")
        check("V5d the voice history is scoped by student",
              st == 200 and vs["sessions"]
              and all(x["student_id"] == "stu_v1" for x in vs["sessions"])
              and all(x["modality"] == "voice" for x in vs["sessions"]),
              str(vs["count"]))
        st, vs2 = await get("/admin/voice/sessions?student_id=stu_v2")
        check("V5e another student's voice history is not visible",
              all(x["session_id"] != sess_b["session_id"] for x in vs2["sessions"]))
        st, tch = await get("/admin/voice/sessions?teacher_id=%s" % tid_b)
        check("V5f the voice history is scoped by teacher",
              all(x["teacher_id"] == tid_b for x in tch["sessions"]))
        st, m_b2 = await post("/admin/voice/channels/%s/audio" % ch_b["channel_id"],
                              {"text": "uniquetokenVA 是什么？"})
        check("V5g a text turn inside a voice class carries no audio evidence",
              st == 200 and not (m_b2.get("audio_in")), str(m_b2)[:200])
        st, irq = await post("/admin/voice/channels/%s/interrupt" % ch_b["channel_id"], {})
        check("V5h barge-in on a non-supporting adapter reports honestly",
              st == 200 and irq.get("supported") is False
              and irq.get("reason") == "adapter_no_barge_in"
              and irq["channel"]["status"] in ("ready", "streaming"), str(irq)[:220])
        st, irq_dead = await post("/admin/voice/channels/%s/interrupt"
                                  % ch_c["channel_id"], {})
        check("V5i a cleaned-up channel cannot be interrupted",
              st == 400 and irq_dead.get("error") == "channel_closed",
              str(irq_dead)[:160])

        # ---- V6 no audio evidence -> no pronunciation verdict ---------------
        # (a) a class whose turns are all TEXT: an audio/pronunciation claim must go
        st, s_t = await post("/admin/voice/sessions",
                             {"teacher_id": tid_a, "student_id": "stu_v6"})
        ch_t = s_t["channel"]
        await post("/admin/voice/channels/%s/audio" % ch_t["channel_id"],
                   {"text": "uniquetokenVA 是什么意思？"})
        st, e_t = await post("/admin/voice/channels/%s/close" % ch_t["channel_id"], {
            "outcome": {"knowledge_points": ["uniquetokenVA 词汇"],
                        "weak_points": ["发音不标准", "第三人称单数 -s"],
                        "review_items": ["朗读 Voice Lesson A"],
                        "notes": "发音进步明显",
                        "pronunciation": {"score": 88.5, "issues": ["θ 音不准"]}},
            "memory_items": [{"entity": "profile_fact", "key": "goal",
                              "value": "跟语音王老师练口语"}]})
        oc = (e_t.get("session") or {}).get("outcome") or {}
        check("V6a with no audio evidence the pronunciation claim is refused",
              st == 200 and oc.get("pronunciation", {}).get("status") == "unassessed"
              and oc["pronunciation"].get("reason") == "no_audio_evidence",
              json.dumps(oc.get("pronunciation"))[:220])
        check("V6b no fabricated pronunciation score is ever stored",
              oc.get("pronunciation", {}).get("score") is None,
              str(oc.get("pronunciation")))
        check("V6c audio-claiming items are rejected with an explicit reason",
              any(x["reason"] == "no_audio_evidence" for x in oc.get("rejected_items", []))
              and "发音不标准" not in oc.get("weak_points", [])
              and all("朗读" not in x for x in oc.get("review_items", []))
              and "发音" not in (oc.get("notes") or ""),
              json.dumps(oc.get("rejected_items"))[:260])
        check("V6d non-audio items are still recorded (the class is not thrown away)",
              oc.get("knowledge_points") == ["uniquetokenVA 词汇"]
              and oc.get("weak_points") == ["第三人称单数 -s"], json.dumps(oc)[:260])
        check("V6e the class is labelled simulated (no real teaching claim)",
              oc.get("simulated") is True and bool(oc.get("simulation_note")))
        check("V6f the outcome cites the evidence it really has",
              (oc.get("evidence") or {}).get("kinds") == ["text_dialogue"]
              and (oc.get("evidence") or {}).get("audio_turns") == 0,
              json.dumps(oc.get("evidence")))

        # (b) a class WITH audio evidence: the item is kept, but the adapter does not
        #     provide scoring — so a score must still not appear out of nowhere
        st, e_b = await post("/admin/voice/channels/%s/close" % ch_b["channel_id"],
                             {"outcome": {"weak_points": ["发音不标准"],
                                          "pronunciation": {"score": 91.0}}})
        ocb = (e_b.get("session") or {}).get("outcome") or {}
        check("V6g with real audio evidence the pronunciation item is kept",
              st == 200 and ocb.get("weak_points") == ["发音不标准"]
              and not ocb.get("rejected_items"),
              json.dumps(ocb)[:260])
        check("V6h a score is still not invented when the adapter does not score",
              ocb["pronunciation"]["status"] == "unassessed"
              and ocb["pronunciation"]["reason"] == "adapter_no_assessment"
              and ocb["pronunciation"]["score"] is None,
              json.dumps(ocb.get("pronunciation"))[:220])
        check("V6i the audio evidence is cited, with counts and no audio bytes",
              "audio_speech" in (ocb.get("evidence") or {}).get("kinds", [])
              and (ocb.get("evidence") or {}).get("audio_turns", 0) >= 1,
              json.dumps(ocb.get("evidence")))
        st, irq_closed = await post("/admin/voice/channels/%s/interrupt"
                                    % ch_b["channel_id"], {})
        check("V6j a closed class cannot be interrupted",
              st == 400 and irq_closed.get("error") == "channel_closed",
              str(irq_closed)[:160])

        # a class with NO evidence at all must not invent learning results
        st, s5 = await post("/admin/voice/sessions",
                            {"teacher_id": tid_a, "student_id": "stu_v4"})
        ch_e = s5["channel"]
        st, e_e = await post("/admin/voice/channels/%s/close" % ch_e["channel_id"],
                             {"outcome": {"weak_points": ["发音需要加强"],
                                          "knowledge_points": ["问候语"]}})
        oc_e = (e_e.get("session") or {}).get("outcome") or {}
        check("V6k a class with no evidence stores no learning claims",
              st == 200 and oc_e.get("knowledge_points") == []
              and oc_e.get("weak_points") == []
              and all(x["reason"] == "no_evidence" for x in oc_e.get("rejected_items", []))
              and set(["knowledge_points", "weak_points", "review_items",
                       "pronunciation"]) <= set(oc_e.get("unassessed") or []),
              json.dumps(oc_e)[:300])

        # ---- V7 the text classroom is not regressed -------------------------
        st, ct = await post("/admin/teacher/teachers", {
            "name": "文字李老师", "teaching_style": "patient",
            "voice": {"mode": "text"},
            "model": {"text_model_id": model_t1["id"]},
            "knowledge": {"dataset_ids": [ds_a["id"]]}})
        tid_t = ct["teacher"]["teacher_id"]
        st, ts1 = await post("/admin/teaching/sessions",
                             {"teacher_id": tid_t, "student_id": "stu_v5"})
        tsid = (ts1.get("session") or {}).get("session_id")
        check("V7a the text classroom still starts",
              st == 200 and ts1["session"]["modality"] == "text"
              and ts1["session"]["model_id"] == model_t1["id"], str(ts1)[:220])
        st, tm = await post("/admin/teaching/sessions/%s/messages" % tsid,
                            {"text": "uniquetokenVA 是什么意思？"})
        check("V7b the text classroom still calls a real model and returns sources",
              st == 200 and "UPSTREAM-ONE" in (tm.get("reply") or "")
              and any(s["dataset_id"] == ds_a["id"] for s in (tm.get("sources") or [])),
              str(tm)[:220])
        st, te = await post("/admin/teaching/sessions/%s/end" % tsid, {
            "outcome": {"weak_points": ["发音不标准"], "knowledge_points": ["问候语"]}})
        toc = (te.get("session") or {}).get("outcome") or {}
        check("V7c the text classroom applies the same audio-evidence gate",
              st == 200 and toc.get("knowledge_points") == ["问候语"]
              and toc.get("weak_points") == []
              and toc.get("pronunciation", {}).get("status") == "unassessed",
              json.dumps(toc)[:260])
        check("V7d teaching routes are still mounted alongside the voice surface",
              all(p in mounted for p in ("/admin/teaching/overview",
                                         "/admin/teaching/sessions")))

        # ---- V8 frozen Tina untouched --------------------------------------
        st, tina = await get("/admin/teacher/teachers/tina")
        tr = tina["teacher"]
        check("V8a frozen Tina teacher record unchanged",
              tr["frozen"] is True and tr["voice"]["mode"] == "realtime"
              and tr["voice"]["voice_id"] == "Tina"
              and tr["model"]["realtime_model_id"] == "mdl_frozen_tina"
              and tr["model"]["text_model_id"] == "", str(tr.get("voice")))
        st, r = await post("/admin/voice/sessions", {"teacher_id": "tina"})
        check("V8b the frozen production voice link is not taken over",
              st == 400 and r.get("error") == "frozen_realtime_only", str(r)[:180])
        st, r = await put("/admin/teacher/teachers/tina",
                          {"voice": {"mode": "realtime", "adapter_id": TEST_PIPELINE_ID}})
        check("V8c frozen Tina voice is still not writable", st == 400, str(r)[:140])
        froz = stores.model_registry.get_model("mdl_frozen_tina")
        check("V8d the frozen realtime model is untouched",
              bool(froz) and froz.get("frozen") is True and froz.get("enabled") is True
              and froz.get("model_key") == "qwen3.8-omni-flash-realtime",
              json.dumps({k: froz.get(k) for k in ("frozen", "enabled", "model_key")}))
        st, ad2 = await get("/admin/voice/adapters")
        check("V8e no registered adapter claims the frozen production link",
              all("frozen" not in a["id"] and "tina" not in a["id"].lower()
                  for a in ad2["adapters"]), str([a["id"] for a in ad2["adapters"]]))

        # ---- bearer still enforced -------------------------------------------
        check("V9 bearer is still enforced on the voice surface",
              (await cl.get("/admin/voice/overview")).status == 401)

        # ---- restart: voice channels + records survive ----------------------
        stores2 = _stores(tmp)
        app2 = _app(tmp, stores2)
        async with TestClient(TestServer(app2)) as cl2:
            r = await cl2.get("/admin/voice/channels/%s" % ch_b["channel_id"],
                              headers=AUTH)
            b = await r.json()
            check("V10a a closed voice channel survives a restart",
                  r.status == 200 and b["channel"]["status"] == "ended"
                  and b["channel"]["close_reason"] in ("user_closed", "idle_timeout"),
                  str(b)[:200])
            r = await cl2.get("/admin/teaching/sessions/%s" % sess_b["session_id"],
                              headers=AUTH)
            b2 = await r.json()
            check("V10b the voice class learning result survives a restart",
                  r.status == 200
                  and (b2["session"].get("outcome") or {}).get("pronunciation", {})
                  .get("status") == "unassessed"
                  and b2["session"]["modality"] == "voice", str(b2)[:220])
            check("V10c the voice store reloaded from disk is available",
                  stores2.voice is not None and stores2.voice.available)

    # ---- summary -----------------------------------------------------------
    ok = sum(1 for _, c, _ in RESULTS if c)
    print("\n%d/%d checks passed" % (ok, len(RESULTS)))
    if ok != len(RESULTS):
        print("FAILURES:")
        for n, c, d in RESULTS:
            if not c:
                print("  -", n, ("[%s]" % d) if d else "")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(amain())
