"""TEACHER_CONTEXT_SEAM_TESTS — P2-B2-R2 isolated verification of the non-frozen
teaching-context projection (gateway/app/teacher_context.py + teacher_voice.py).

Scope (isolated only — NO real model, NO paid call, NO NAS, NO frozen edit):
  T1  teacher A gets ONLY material A, and it is really retrievable
  T2  teacher B gets ONLY material B, and it is really retrievable
  T3  A cannot reach B's material or private memory
  T4  B cannot reach A's material or private memory
  T5  an unauthorised / disabled dataset is refused (never substituted)
  T6  no material -> honest general teaching (never the whole library)
  T7  switching teachers does not carry the previous context over
  T8  reconnecting loads the right teacher again
  T9  with no trustworthy student identity, private memory is DISABLED
  T10 only real evidence is written; no pronunciation verdict is invented
  T11 the R1 credential isolation is not regressed
  T12 the frozen Tina link is untouched
  T14 with the new features off, behaviour is unchanged

The frozen engine is never imported here: a fake connection supplies the
``qwen.on_event`` attribute the observer wraps.
"""

import asyncio
import hashlib
import json
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

from app import teacher_context as tc                             # noqa: E402
from app import teacher_voice as tv                               # noqa: E402
from modules.intent.behavior import BehaviorState, render_instructions  # noqa: E402
from modules.knowledge.store import KnowledgeStore                # noqa: E402
from modules.policy.persona import PolicyStore                    # noqa: E402
from modules.teacher.store import TeacherStore                    # noqa: E402
from modules.teaching.store import TeachingSessionStore           # noqa: E402

RESULTS = []

PROBE_A = "photosynthesis chlorophyll"
PROBE_B = "quadratic discriminant"
TEXT_A = ("Photosynthesis is the process by which plants convert sunlight into "
          "chemical energy using chlorophyll inside the chloroplast.")
TEXT_B = ("A quadratic equation has a discriminant whose sign decides how many "
          "real roots the parabola crosses.")


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % detail)[:220] if not cond else ""))


def _sha_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ---------------------------------------------------------------------------
# fixtures (isolated; real product stores on temporary files)
# ---------------------------------------------------------------------------

def _make_kb(tmp):
    path = os.path.join(tmp, "kb.json")
    kb = KnowledgeStore(path).load()
    ds_a = kb.create_dataset(name="英语口语")["id"]
    kb.add_document(ds_a, "英语-第1课", TEXT_A)
    ds_b = kb.create_dataset(name="数学")["id"]
    kb.add_document(ds_b, "数学-二次方程", TEXT_B)
    ds_off = kb.create_dataset(name="已停用教材")["id"]
    kb.add_document(ds_off, "停用", "withheld material zeta marker")
    kb.set_dataset_enabled(ds_off, False)
    ds_unused = kb.create_dataset(name="无人授权")["id"]
    kb.add_document(ds_unused, "无人授权", "orphan material omega marker")
    kb.load()
    return path, {"a": ds_a, "b": ds_b, "off": ds_off, "unused": ds_unused}


def _make_registry(tmp):
    """A real (isolated) model registry so the classroom record has a binding."""
    from modules.model.registry import ModelRegistry
    path = os.path.join(tmp, "registry.json")
    reg = ModelRegistry(path).load().ensure_seeded()
    prov = reg.create_provider(name="老师A服务商", protocol="dashscope",
                               base_url="https://wsa.cn-beijing.maas.aliyuncs.com")
    mdl = reg.create_model(provider_id=prov["id"], model_key="qwen-realtime-a",
                           capabilities=["realtime_audio", "streaming", "barge_in"])
    reg.set_evidence(mdl["id"], "realtime_safe", source="test")
    # R3-0: the resolver now enforces the operator `enabled` switch; a fixture
    # that leaves the model disabled would rely on the missing gate.
    reg.set_enabled(mdl["id"], True)
    return path, mdl["id"], prov["id"]


def _make_teachers(tmp, ds, rt_model_id="mdl_a"):
    path = os.path.join(tmp, "teachers.json")
    store = TeacherStore(path).load().ensure_seeded()          # seeds frozen tina
    a = store.create_teacher(name="老师A", subject="english", language="en",
                             teaching_style="patient",
                             voice={"mode": "realtime", "voice_id": "VoiceA"},
                             model={"realtime_model_id": rt_model_id},
                             knowledge={"dataset_ids": [ds["a"], ds["off"]]})
    b = store.create_teacher(name="老师B", subject="math", language="zh",
                             teaching_style="strict",
                             voice={"mode": "realtime", "voice_id": "VoiceB"},
                             model={"realtime_model_id": "mdl_b"},
                             knowledge={"dataset_ids": [ds["b"]]})
    c = store.create_teacher(name="老师C", subject="general", language="bi",
                             teaching_style="encouraging",
                             voice={"mode": "realtime", "voice_id": "VoiceC"},
                             model={"realtime_model_id": "mdl_c"})
    return store, {"A": a, "B": b, "C": c}


class FakeQwen:
    def __init__(self):
        self.seen = []

    async def on_event(self, obj):
        self.seen.append(obj)


class FakeConn:
    def __init__(self):
        self.qwen = FakeQwen()


def _hits(path, probe, dataset_id):
    st = KnowledgeStore(path).load()
    return st.search(probe, dataset_id=dataset_id, min_score=1)


async def main():
    tmp = tempfile.mkdtemp(prefix="p2b2-ctx-")
    data = os.path.join(tmp, "data")
    kb_path, ds = _make_kb(tmp)
    kb_sha0 = _sha_file(kb_path)          # the source library must stay untouched
    reg_path, rt_model_id, rt_provider_id = _make_registry(tmp)
    store, T = _make_teachers(tmp, ds, rt_model_id)

    # ================= T1 / T2 : own material, really retrievable ============
    ctx_a = tc.project_teacher_context(teacher=T["A"], data_dir=data,
                                       knowledge_source=kb_path)
    ctx_b = tc.project_teacher_context(teacher=T["B"], data_dir=data,
                                       knowledge_source=kb_path)
    check("T1a A's material projection is verified and mounted",
          ctx_a["knowledge"]["state"] == "ok" and ctx_a["knowledge"]["path"],
          json.dumps(ctx_a["knowledge"])[:200])
    check("T1b A's projection contains ONLY A's authorised dataset",
          ctx_a["knowledge"]["dataset_ids"] == [ds["a"]],
          str(ctx_a["knowledge"]["dataset_ids"]))
    check("T1c A's material is really retrievable from the mounted file",
          bool(_hits(ctx_a["knowledge"]["path"], PROBE_A[:40], ds["a"])))
    check("T2a B's material projection is verified and mounted",
          ctx_b["knowledge"]["state"] == "ok" and ctx_b["knowledge"]["path"])
    check("T2b B's projection contains ONLY B's authorised dataset",
          ctx_b["knowledge"]["dataset_ids"] == [ds["b"]])
    check("T2c B's material is really retrievable from the mounted file",
          bool(_hits(ctx_b["knowledge"]["path"], PROBE_B[:40], ds["b"])))

    # ================= T3 / T4 : no cross-teacher material ==================
    check("T3a A's mounted file cannot reach B's dataset id",
          not _hits(ctx_a["knowledge"]["path"], PROBE_B[:40], ds["b"]))
    check("T3b A's mounted file has no B chunk at all",
          not _hits(ctx_a["knowledge"]["path"], "discriminant parabola", ds["a"]))
    check("T4a B's mounted file cannot reach A's dataset id",
          not _hits(ctx_b["knowledge"]["path"], PROBE_A[:40], ds["a"]))
    check("T4b B's mounted file has no A chunk at all",
          not _hits(ctx_b["knowledge"]["path"], "chlorophyll chloroplast", ds["b"]))
    check("T3c A/B mounted files are different files with different bytes",
          ctx_a["knowledge"]["path"] != ctx_b["knowledge"]["path"]
          and _sha_file(ctx_a["knowledge"]["path"])
          != _sha_file(ctx_b["knowledge"]["path"]))
    check("T3d private memory is not readable on this path (no store mounted)",
          ctx_a["memory"]["path"] == "" and ctx_b["memory"]["path"] == ""
          and ctx_a["memory"]["state"] == "disabled")

    # ================= T5 : unauthorised / disabled material refused ========
    check("T5a an authorised-but-DISABLED dataset is excluded (never substituted)",
          ds["off"] not in ctx_a["knowledge"]["dataset_ids"])
    check("T5b a dataset nobody authorised never appears anywhere",
          ds["unused"] not in (ctx_a["knowledge"]["dataset_ids"]
                               + ctx_b["knowledge"]["dataset_ids"]))
    ctx_c = tc.project_teacher_context(teacher=T["C"], data_dir=data,
                                       knowledge_source=kb_path)
    check("T5c a teacher with no authorisation gets an EMPTY reason, not the library",
          ctx_c["knowledge"]["state"] == "disabled"
          and ctx_c["knowledge"]["reason"] == tc.KB_REASON_NO_AUTH
          and ctx_c["knowledge"]["path"] == "")
    bogus = dict(T["B"])
    bogus["knowledge"] = {"dataset_ids": ["ds_does_not_exist"]}
    ctx_bogus = tc.project_teacher_context(teacher=bogus, data_dir=data,
                                           knowledge_source=kb_path)
    check("T5d an unknown dataset id is refused, never resolved loosely",
          ctx_bogus["knowledge"]["state"] == "disabled")
    ctx_nosrc = tc.project_teacher_context(
        teacher=T["A"], data_dir=data, knowledge_source=os.path.join(tmp, "nope.json"))
    check("T5e an unreadable source never falls back to anything else",
          ctx_nosrc["knowledge"]["state"] == "disabled"
          and ctx_nosrc["knowledge"]["reason"] == tc.KB_REASON_SOURCE_MISSING)
    escaped = []
    for bad in ("../evil", "a/b", "a\\b", ".", "..", "", "x\x00y", "a\nb", "c:d"):
        fake = dict(T["A"])
        fake["teacher_id"] = bad
        got = tc.project_teacher_context(teacher=fake, data_dir=data,
                                         knowledge_source=kb_path)
        escaped.append((bad, got["policy"]["path"], got["knowledge"]["path"]))
    check("T5f a hostile teacher_id can never escape the data dir",
          all(p == "" and k == "" for _b, p, k in escaped)
          and all(tc.safe_component(b) == "" for b in
                  ("../evil", "a/b", "a\\b", ".", "..", "", "x\x00y", "a\nb", "c:d")))
    check("T5g safe_component still accepts a normal generated id",
          tc.safe_component("tch_0a1b2c3d4e5f") == "tch_0a1b2c3d4e5f")

    # ================= T6 : honest general teaching =========================
    check("T6a no material -> knowledge disabled with an honest reason",
          ctx_c["knowledge"]["state"] == "disabled"
          and ctx_c["knowledge"]["reason"] in (tc.KB_REASON_NO_AUTH,
                                               tc.KB_REASON_EMPTY))
    check("T6b the teacher's own POLICY still applies without material",
          ctx_c["policy"]["state"] == "ok"
          and "persona.personality" in ctx_c["policy"]["fields"])
    check("T6c an invalid language (bi) is not written as language.default",
          "language.default" not in ctx_c["policy"]["fields"])

    # ================= policy injection is real, not decorative =============
    pol_a = PolicyStore(ctx_a["policy"]["path"]).load().active()["policy"]
    rendered_a = render_instructions(BehaviorState(), None, policy=pol_a)
    check("T1d A's rendered instructions really contain A's own teaching rule",
          "耐心的引导者" in rendered_a and "老师A" in rendered_a)
    check("T1e A's rendered instructions never contain B's teaching rule",
          "严格的纠错者" not in rendered_a and "老师B" not in rendered_a)
    pol_b = PolicyStore(ctx_b["policy"]["path"]).load().active()["policy"]
    rendered_b = render_instructions(BehaviorState(), None, policy=pol_b)
    check("T2d B's rendered instructions really contain B's own teaching rule",
          "严格的纠错者" in rendered_b and "老师B" in rendered_b)
    check("T2e B's rendered instructions never contain A's teaching rule",
          "耐心的引导者" not in rendered_b)
    check("T2f the projected role/language line is rendered too",
          "教学科目：数学" in rendered_b or "数学" in rendered_b)

    # ================= T7 : switching does not carry context over ===========
    # build the two connection configs exactly the way the handler does
    base = _base_config(kb_path)
    c_a = tv.build_teacher_config(base, qwen_cfg="QA", teacher_id=T["A"]["teacher_id"],
                                  data_dir=data,
                                  policy_file=ctx_a["policy"]["path"],
                                  knowledge_file=ctx_a["knowledge"]["path"],
                                  memory_file=ctx_a["memory"]["path"])
    c_b = tv.build_teacher_config(base, qwen_cfg="QB", teacher_id=T["B"]["teacher_id"],
                                  data_dir=data,
                                  policy_file=ctx_b["policy"]["path"],
                                  knowledge_file=ctx_b["knowledge"]["path"],
                                  memory_file=ctx_b["memory"]["path"])
    check("T7a the two connections point at different policy/material files",
          c_a.POLICY_FILE != c_b.POLICY_FILE
          and c_a.KNOWLEDGE_FILE != c_b.KNOWLEDGE_FILE)
    check("T7b neither connection inherits the global stores",
          c_a.MEMORY_FILE == "" and c_a.WORKBENCH_BASE_URL == ""
          and c_a.KNOWLEDGE_FILE != base.KNOWLEDGE_FILE)
    check("T7c the second connection's material is B's, not A's",
          _hits(c_b.KNOWLEDGE_FILE, PROBE_B[:40], ds["b"])
          and not _hits(c_b.KNOWLEDGE_FILE, "chlorophyll", ds["b"]))
    check("T7d the global config object was never mutated",
          base.KNOWLEDGE_FILE == kb_path and base.POLICY_FILE == ""
          and base.WORKBENCH_BASE_URL == "")

    # ================= T8 : reconnect resolves the right teacher ============
    again = tc.project_teacher_context(teacher=T["A"], data_dir=data,
                                       knowledge_source=kb_path)
    check("T8a re-projecting the same teacher is stable and idempotent",
          again["knowledge"]["path"] == ctx_a["knowledge"]["path"]
          and again["policy"]["path"] == ctx_a["policy"]["path"]
          and _sha_file(again["knowledge"]["path"])
          == _sha_file(ctx_a["knowledge"]["path"]))
    check("T8b a different teacher on reconnect gets a different context",
          again["knowledge"]["path"] != ctx_b["knowledge"]["path"])
    pol_before = _sha_file(ctx_a["policy"]["path"])
    tc.project_teacher_context(teacher=T["A"], data_dir=data, knowledge_source=kb_path)
    check("T8c re-projecting is BYTE-idempotent (no churn, no rewrite)",
          _sha_file(ctx_a["policy"]["path"]) == pol_before)
    d_mode = os.stat(os.path.dirname(ctx_a["policy"]["path"])).st_mode & 0o777
    f_mode = os.stat(ctx_a["policy"]["path"]).st_mode & 0o777
    check("T8d projections are not world-readable (dir 700 / file 600)",
          d_mode == 0o700 and f_mode == 0o600, "dir=%o file=%o" % (d_mode, f_mode))
    # a directory widened externally must be re-tightened even when the content
    # itself is unchanged (the idempotent early-return path)
    pdir = os.path.dirname(ctx_a["policy"]["path"])
    os.chmod(pdir, 0o755)
    tc.project_teacher_context(teacher=T["A"], data_dir=data, knowledge_source=kb_path)
    check("T8e a widened directory is re-tightened on the no-change path",
          os.stat(pdir).st_mode & 0o777 == 0o700)

    # ================= T13 : end-to-end through the real WS route ==========
    # The projection is only useful if the LIVE handler actually mounts it, so
    # drive the route with the frozen engine stubbed out.
    class _Conn:
        built = []

        def __init__(self, ws, config):
            self.ws = ws
            self.config = config
            self.qwen = FakeQwen()
            _Conn.built.append(self)

        async def on_connect(self):
            pass

        async def handle_text(self, raw):
            pass

        def handle_binary(self, data):
            pass

        async def close(self):
            pass

    def _stub_resolver(opts, teacher):
        return tv.build_teacher_qwen(opts.qwen, model="mock-" + teacher["teacher_id"],
                                     voice=(teacher.get("voice") or {}).get("voice_id") or "",
                                     mode="mock")

    from aiohttp import web, test_utils
    import aiohttp

    token = "ctx-token"
    live_cfg = _base_config(kb_path)
    live_cfg.TEACHER_VOICE_DATA_DIR = data
    live_cfg.TEACHER_FILE = os.path.join(tmp, "teachers.json")
    live_cfg.TEACHING_FILE = os.path.join(tmp, "teaching_live.json")
    live_cfg.TEACHER_VOICE_STUDENT_ID = "kiosk-live"
    live_cfg.MODEL_REGISTRY_FILE = reg_path
    tv._connection_factory = _Conn
    app = web.Application()
    app.router.add_get(tv.TEACHER_WS_PATH,
                       tv.make_handler(live_cfg, store, token, resolver=_stub_resolver))
    server = test_utils.TestServer(app)
    await server.start_server()
    url = server.make_url(tv.TEACHER_WS_PATH)
    try:
        async with aiohttp.ClientSession() as sess:
            _Conn.built = []
            async with sess.ws_connect(
                    str(url) + "?teacher_id=" + T["A"]["teacher_id"],
                    headers={tv.HEADER_TEACHER_TOKEN: token}) as ws:
                await asyncio.sleep(0.05)
            check("T13a the live route built exactly one teacher connection",
                  len(_Conn.built) == 1)
            # fixture honesty (R3-0): this suite drives the route with a stub
            # resolver, so nothing else here would notice a DISABLED model — yet
            # the real resolver refuses one.  Pin the fixture to a resolvable
            # model so the e2e can never silently drift off the real contract.
            from modules.model.registry import ModelRegistry as _MR
            _live_rec = _MR(reg_path).load().get_model(rt_model_id)
            check("T13a2 the e2e model is operator-enabled (as the real resolver requires)",
                  bool(_live_rec) and bool(_live_rec.get("enabled")))
            if _Conn.built:
                got = _Conn.built[0].config
                check("T13b the live connection mounts A's OWN policy projection",
                      got.POLICY_FILE == ctx_a["policy"]["path"]
                      and got.POLICY_FILE != "")
                check("T13c the live connection mounts A's OWN material projection",
                      got.KNOWLEDGE_FILE == ctx_a["knowledge"]["path"]
                      and got.KNOWLEDGE_FILE != "")
                check("T13d the live connection mounts NO shared memory / workbench",
                      got.MEMORY_FILE == "" and got.WORKBENCH_BASE_URL == "")
                check("T13e the live connection carries no global store path",
                      got.KNOWLEDGE_FILE != kb_path and got.POLICY_FILE != "")
                check("T13f the mounted material really holds material A only",
                      bool(_hits(got.KNOWLEDGE_FILE, PROBE_A[:40], ds["a"]))
                      and not _hits(got.KNOWLEDGE_FILE, PROBE_B[:40], ds["a"]))
                live_sessions = list(TeachingSessionStore(
                    live_cfg.TEACHING_FILE).load().list_sessions())
                check("T13g a real class record was opened for the configured kiosk",
                      os.path.isfile(live_cfg.TEACHING_FILE)
                      and len(live_sessions) == 1
                      and live_sessions[0]["modality"] == "voice"
                      and live_sessions[0]["model_id"] == rt_model_id
                      and live_sessions[0]["provider_id"] == rt_provider_id
                      and live_sessions[0]["teacher_id"] == T["A"]["teacher_id"])
                check("T13j the record is attributed to the SERVER-side kiosk label",
                      bool(live_sessions)
                      and live_sessions[0]["student_id"] == "kiosk-live")
                # a clean client disconnect must still close the record
                status = "?"
                for _ in range(40):
                    got_now = TeachingSessionStore(live_cfg.TEACHING_FILE).load() \
                        .get_session(live_sessions[0]["session_id"])
                    status = (got_now or {}).get("status")
                    if status == "ended":
                        break
                    await asyncio.sleep(0.05)
                check("T13k a normal client disconnect closes the classroom record",
                      status == "ended", "status=%s" % status)
            _Conn.built = []
            async with sess.ws_connect(
                    str(url) + "?teacher_id=" + T["B"]["teacher_id"],
                    headers={tv.HEADER_TEACHER_TOKEN: token}) as ws:
                await asyncio.sleep(0.05)
            if _Conn.built:
                got_b = _Conn.built[0].config
                check("T13h switching teacher switches the mounted context",
                      got_b.KNOWLEDGE_FILE == ctx_b["knowledge"]["path"]
                      and got_b.POLICY_FILE == ctx_b["policy"]["path"])
                check("T13i the previous material is not reused for B",
                      not _hits(got_b.KNOWLEDGE_FILE, "chlorophyll", ds["b"]))
    finally:
        await server.close()
        tv._connection_factory = None

    # ------------- P1 regression: teardown must survive CANCELLATION --------
    # aiohttp cancels the handler task when the client vanishes; delivering that
    # cancellation at the first await of the teardown used to abort the drain and
    # leave an orphan `active` record.  This drives the real teardown helper.
    ran = {"close": 0, "finish": 0}

    class _CancellableConn:
        async def close(self):
            await asyncio.sleep(0)
            ran["close"] += 1

    class _SlowObserver:
        async def finish(self):
            await asyncio.sleep(0.25)          # stands in for the drain
            ran["finish"] += 1
            return {"written": 0}

    teardown = asyncio.ensure_future(
        tv._run_teardown(_CancellableConn(), _SlowObserver()))
    await asyncio.sleep(0.05)
    teardown.cancel()
    try:
        await teardown
    except asyncio.CancelledError:
        pass
    await asyncio.sleep(0.5)                   # the shielded teardown finishes
    check("T13l a CANCELLED handler still runs the whole teardown (P1 guard)",
          ran["close"] == 1 and ran["finish"] == 1, "ran=%s" % ran)

    # ================= T9 : no identity -> memory fail-closed ===============
    check("T9a memory is disabled with the honest identity reason",
          tc.memory_decision() == ("", tc.MEMORY_REASON_DISABLED))
    check("T9b no connection ever mounts a memory file",
          c_a.MEMORY_FILE == "" and c_b.MEMORY_FILE == ""
          and ctx_c["memory"]["path"] == "")
    check("T9c a client-declared student id cannot reach private memory",
          "student_id" not in json.dumps(ctx_a["memory"]))

    # ================= T10 : only real evidence is recorded =================
    tpath = os.path.join(tmp, "teaching.json")
    tstore = TeachingSessionStore(tpath).load()
    obs, reason = tc.open_teaching_record(
        store=tstore, student_id="", teacher=T["A"], binding=None,
        dataset_ids=ctx_a["knowledge"]["dataset_ids"])
    check("T10a no server-side identity -> NO classroom record is invented",
          obs is None and reason == tc.RECORD_REASON_NO_IDENTITY)
    obs2, reason2 = tc.open_teaching_record(
        store=None, student_id="kiosk-1", teacher=T["A"], binding=None,
        dataset_ids=[])
    check("T10b no teaching store -> NO classroom record",
          obs2 is None and reason2 == tc.RECORD_REASON_NOT_CONFIGURED)
    obs3, reason3 = tc.open_teaching_record(
        store=tstore, student_id="kiosk-1", teacher=T["A"], binding=None,
        dataset_ids=[])
    check("T10c no verified model binding -> NO classroom record",
          obs3 is None and reason3 == tc.RECORD_REASON_NO_BINDING)

    obs4, reason4 = tc.open_teaching_record(
        store=tstore, student_id="kiosk-1", teacher=T["A"],
        binding={"model_id": "mdl_a", "model_key": "qwen-realtime-a",
                 "provider_id": "prov_x"},
        dataset_ids=ctx_a["knowledge"]["dataset_ids"],
        policy=ctx_a["policy"]["built"])
    check("T10d a fully configured class DOES open a record",
          obs4 is not None and reason4 == tc.RECORD_REASON_OK)
    conn = FakeConn()
    check("T10e the observer attaches to the (instance-level) event hook",
          obs4.attach(conn) is True)
    # a cumulative preview is NOT evidence
    await conn.qwen.on_event({"type": "conversation.item.input_audio_transcription.delta",
                              "delta": "photosyn"})
    check("T10f a transcript PREVIEW is never recorded as a learner turn",
          obs4.stats["observed"] == 0 and conn.qwen.seen)
    await conn.qwen.on_event({"type": "conversation.item.input_audio_transcription.completed",
                              "transcript": "What does photosynthesis mean?"})
    await conn.qwen.on_event({"type": "response.audio_transcript.done",
                              "transcript": "Photosynthesis is how plants make food."})
    await conn.qwen.on_event({"type": "response.done", "response": {"status": "completed"}})
    check("T10g only the two TERMINAL transcript events are observed",
          obs4.stats["observed"] == 2)
    stats = await obs4.finish()
    sess = tstore.get_session(obs4.session_id)
    check("T10h the real turns were written to the classroom record",
          stats["written"] == 2 and len(sess["turns"]) == 2
          and [t["role"] for t in sess["turns"]] == ["student", "teacher"])
    check("T10i realtime audio is NOT treated as pronunciation evidence",
          sess["outcome"]["pronunciation"]["status"] == "unassessed"
          and "pronunciation" in sess["outcome"]["unassessed"])
    check("T10j the session ended without any invented learning claim",
          sess["status"] == "ended" and sess["outcome"]["notes"] == ""
          and sess["outcome"]["knowledge_points"] == []
          and sess["outcome"]["weak_points"] == []
          and sess["outcome"]["rejected_items"] == [])
    check("T10k the recorded evidence comes from the session turns only",
          sess["outcome"]["evidence"]["source"] == "session_turns"
          and sess["outcome"]["evidence"]["audio_turns"] == 0)

    # an outcome claiming audio pronunciation with no audio must be refused
    ts2 = TeachingSessionStore(os.path.join(tmp, "teaching2.json")).load()
    obs5, _r = tc.open_teaching_record(
        store=ts2, student_id="kiosk-2", teacher=T["A"],
        binding={"model_id": "mdl_a", "model_key": "k", "provider_id": "p"},
        dataset_ids=[], policy={})
    c5 = FakeConn()
    obs5.attach(c5)
    await c5.qwen.on_event({"type": "conversation.item.input_audio_transcription.completed",
                            "transcript": "hello"})
    await obs5.drain()
    ts2.end_session(obs5.session_id, outcome={"pronunciation": ["th 音清晰"]})
    rec5 = ts2.get_session(obs5.session_id)
    check("T10l an audio claim without audio evidence is REJECTED by the store",
          rec5["outcome"]["pronunciation"]["status"] == "unassessed")

    # a record whose tap cannot be installed must not stay active forever
    class _NoQwen:
        pass

    ts3 = TeachingSessionStore(os.path.join(tmp, "teaching3.json")).load()
    obs6, r6 = tc.open_teaching_record(
        store=ts3, student_id="kiosk-3", teacher=T["A"],
        binding={"model_id": "mdl_a", "model_key": "k", "provider_id": "p"},
        dataset_ids=[], policy={})
    check("T10m a connection without an event hook refuses the tap calmly",
          obs6 is not None and obs6.attach(_NoQwen()) is False
          and obs6.attach(SimpleNamespace(qwen=SimpleNamespace(on_event="x"))) is False)
    await obs6.finish()
    check("T10n the un-attached record is still closed (no orphan active class)",
          ts3.get_session(obs6.session_id)["status"] == "ended"
          and obs6.stats["written"] == 0)
    ts4 = TeachingSessionStore(os.path.join(tmp, "teaching4.json")).load()
    obs7, _r7 = tc.open_teaching_record(
        store=ts4, student_id="kiosk-4", teacher=T["A"],
        binding={"model_id": "mdl_a", "model_key": "k", "provider_id": "p"},
        dataset_ids=[], policy={})
    c7 = FakeConn()
    obs7.attach(c7)
    await c7.qwen.on_event({"type": "conversation.item.input_audio_transcription.completed",
                            "transcript": "x" * 50_000})
    await c7.qwen.on_event({"type": "response.audio_transcript.done",
                            "transcript": "short reply"})
    await obs7.finish()
    rec7 = ts4.get_session(obs7.session_id)
    check("T10p an over-long transcript cannot drop the rest of the class",
          obs7.stats["truncated"] == 1 and obs7.stats["written"] == 2
          and len(rec7["turns"]) == 2
          and len(rec7["turns"][0]["text"]) == tc.TeachingRecordObserver.MAX_TURN_CHARS
          and rec7["turns"][1]["text"] == "short reply")

    check("T10o the observer survives malformed events without raising",
          (tc.realtime_transcript(None) is None
           and tc.realtime_transcript("nope") is None
           and tc.realtime_transcript({}) is None
           and tc.realtime_transcript(
               {"type": "conversation.item.input_audio_transcription.completed",
                "transcript": "   "}) is None
           and (obs6.observe(None) or obs6.observe("x") or True)))

    # ================= T11 : R1 credential isolation not regressed ==========
    bq = tv.build_teacher_qwen(_q(api_key="TINA-KEY"), model="m", voice="v",
                               mode="real", api_key="K-A", workspace_id="wsa",
                               region="cn-beijing",
                               real_ws_url="wss://wsa.cn-beijing.maas.aliyuncs.com/x?model=m")
    check("T11a a real teacher config still carries its OWN credential only",
          bq.api_key == "K-A" and bq.workspace_id == "wsa")
    try:
        tv.build_teacher_qwen(_q(api_key="TINA-KEY"), model="m", voice="v", mode="real")
        missing = False
    except tv.TeacherVoiceUnavailable as e:
        missing = e.code == "credential_missing"
    check("T11b real mode without its own credential still fails closed", missing)
    check("T11c the builder still clears any inherited credential material",
          tv.build_teacher_qwen(_q(api_key="TINA-KEY", workspace_id="tina-ws"),
                                model="m", voice="v", mode="mock").api_key == "")
    check("T11d the projection layer never reads a credential",
          "api_key" not in json.dumps(ctx_a) and "TINA-KEY" not in json.dumps(ctx_a))

    # ================= T12 : frozen Tina untouched ==========================
    try:
        tv.resolve_teacher(store, "tina")
        frozen_blocked = False
    except tv.TeacherVoiceUnavailable as e:
        frozen_blocked = e.code == "frozen_realtime_only"
    check("T12a the frozen teacher is still refused by the seam", frozen_blocked)
    tina_before = store.get_teacher("tina")
    tc.project_teacher_context(teacher=T["A"], data_dir=data, knowledge_source=kb_path)
    check("T12b projecting another teacher never touches frozen Tina's record",
          store.get_teacher("tina") == tina_before)
    check("T12c frozen Tina still carries no knowledge authorisation of its own",
          (tina_before.get("knowledge") or {}).get("dataset_ids") == [])
    check("T12d the projected files live only under the per-teacher data dir",
          os.path.dirname(ctx_a["policy"]["path"]) == os.path.dirname(
              ctx_a["knowledge"]["path"])
          and ctx_a["policy"]["path"].startswith(data + os.sep)
          and ctx_a["policy"]["path"] != ctx_b["policy"]["path"]
          and os.path.basename(os.path.dirname(ctx_a["policy"]["path"]))
          == T["A"]["teacher_id"])

    # ================= T14 : features off -> behaviour unchanged ============
    off = tc.project_teacher_context(teacher=T["A"], data_dir="",
                                     knowledge_source=kb_path)
    check("T14a with no data dir nothing at all is projected or mounted",
          off["policy"]["path"] == "" and off["knowledge"]["path"] == ""
          and off["memory"]["path"] == "" and off["policy"]["state"] == "disabled")
    c_off = tv.build_teacher_config(_base_config(kb_path), qwen_cfg="Q",
                                    teacher_id=T["A"]["teacher_id"], data_dir="")
    check("T14b the connection then loads no store (R1 behaviour) and no workbench",
          c_off.POLICY_FILE == "" and c_off.KNOWLEDGE_FILE == ""
          and c_off.MEMORY_FILE == "" and c_off.WORKBENCH_BASE_URL == "")
    check("T14c the global knowledge base itself was never modified by projection",
          _sha_file(kb_path) == kb_sha0
          and json.loads(open(kb_path, "r", encoding="utf-8").read())["version"] == 1)
    from modules.knowledge.store import SCHEMA_VERSION as KB_SV
    from modules.policy.persona import SCHEMA_VERSION as POL_SV
    kb_doc = json.loads(open(ctx_a["knowledge"]["path"], "r", encoding="utf-8").read())
    pol_doc = json.loads(open(ctx_a["policy"]["path"], "r", encoding="utf-8").read())
    check("T14d both projections carry the READER's schema version, not a local one",
          kb_doc["version"] == KB_SV and pol_doc["schema_version"] == POL_SV)
    check("T14e the projected material is a strict subset of the source library",
          set(kb_doc["chunks"]) <= set(json.loads(
              open(kb_path, "r", encoding="utf-8").read())["chunks"]))
    bare = _base_config(kb_path)
    del bare.TEACHING_FILE
    del bare.TEACHER_VOICE_STUDENT_ID
    del bare.KNOWLEDGE_FILE
    opts_bare = tv._opts(bare)
    check("T14f every R2 knob defaults to OFF when simply absent from config",
          opts_bare.TEACHING_FILE == "" and opts_bare.TEACHER_VOICE_STUDENT_ID == ""
          and opts_bare.KNOWLEDGE_FILE == "" and opts_bare.TEACHER_VOICE_DATA_DIR == "")
    rec_off, why_off = tc.open_teaching_record(
        store=None, student_id="", teacher=T["A"], binding=None, dataset_ids=[])
    check("T14g with the features off no record and no material is ever produced",
          rec_off is None and why_off == tc.RECORD_REASON_NOT_CONFIGURED)

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print("\n%s  %d/%d" % ("ALL PASS" if passed == total else "FAILURES", passed, total))
    return 0 if passed == total else 1


def _q(api_key="", workspace_id="", region=""):
    from types import SimpleNamespace
    return SimpleNamespace(mode="mock", ws_url="ws://127.0.0.1:9977", model="g",
                           voice="Tina", api_key=api_key, workspace_id=workspace_id,
                           region=region, reconnect_max=5, reconnect_base_ms=500,
                           stable_reset_s=30)


def _base_config(kb_path):
    from types import SimpleNamespace
    cfg = SimpleNamespace(
        TEACHER_FILE="", MODEL_REGISTRY_FILE="", MODEL_CREDENTIALS_FILE="",
        MODEL_CREDENTIALS_KEY_FILE="", TEACHER_VOICE_DATA_DIR="",
        TEACHER_VOICE_TOKEN_FILE="", TEACHER_VOICE_WS="0",
        KNOWLEDGE_FILE=kb_path, POLICY_FILE="", MEMORY_FILE="",
        TEACHING_FILE="", TEACHER_VOICE_STUDENT_ID="",
        WORKBENCH_BASE_URL="", FRAME_MS=20, PUBLIC_WS_URL="ws://x")
    cfg.qwen = _q()
    return cfg


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
