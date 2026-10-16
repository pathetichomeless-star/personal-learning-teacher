"""P2-B2 TEACHER VOICE BRIDGE — a NON-INTRUSIVE seam that lets a teacher-scoped
WebSocket connection reuse the FROZEN realtime voice engine.

Why this file exists
--------------------
CHECKPOINT_1 只读勘察（Agent A VOICE_SEAM_REPORT）证明：`turns.Connection` 以
**构造参数**接收 config，且对 config 的依赖只有 5 个字段
（`config.qwen` + BehaviorLink 的 MEMORY_FILE / WORKBENCH_BASE_URL /
KNOWLEDGE_FILE / POLICY_FILE，全部 `getattr(..., "")`）。
因此可以对每个连接传入一份 **config 拷贝**（替换 `.qwen` 为按老师构造的
QwenConfig、改写存储路径），而**不必修改任何冻结文件**。

本模块只新增：
  * 一条 flag 门控的新 WS 路由；
  * 该路由前的**服务端鉴权**与**老师解析（fail-closed）**；
  * 逐连接 config 的构造。

绝对不触碰（冻结，逐字节不变）：
  gateway/app/{qwen,turns,audio,protocol,ws}.py，以及 behavior.py 的渲染逻辑。

安全立场（Agent D FREEZE_SECURITY_REPORT）
------------------------------------------
* 公开 WS 面（/xiaozhi/v1/）当前**无鉴权**，客户端自报的 teacher_id 只能当作
  **请求**、绝不能当作身份。本路由因此在解析任何老师之前，先要求服务端部署
  令牌（`X-Teacher-Token`，与 `TEACHER_VOICE_TOKEN_FILE` 恒时比较）——没有它，
  客户端无法任选老师。
* 老师作用域**一律服务端判定**（存在 / 未删除 / 已启用 / 非冻结 / 交流方式为实时），
  任何不匹配 fail-closed；未通过能力门禁的实时模型**如实拒绝**，绝不静默降级到
  另一位老师。
* 每个老师连接使用**独立存储路径**（未配置数据目录时则**不挂载任何共享存储**），
  私有记忆 / 策略 / 教材不会在老师之间泄漏。

凭据隔离（P2-B2-R1 — C1 修复）
------------------------------
* 老师连接的 `QwenConfig` **只携带该老师自选服务商的自有凭据**（经密封凭据库
  `CredentialStore.read_secret` 读取），并在构造时**显式清空** `api_key` /
  `workspace_id` / `region`——全局链路（Tina）的 API Key、workspace 与 Secret
  File 在老师路径上**没有任何读取点**，因此"继承"在结构上不可能发生。
* 实时接口地址由**该老师的服务商记录**（`provider.base_url`）派生，绝不复用全局
  链路的 workspace 主机。
* 以下情形一律 **fail-closed**（拒绝建立连接，绝不静默降级）：模型未过门禁 /
  **模型未启用（P2-B2-R3-0：`model.enabled`，服务端在此接入层强制）** /
  模型或服务商为冻结 / 服务商协议无法被实时引擎驱动（非 `dashscope`+`builtin`）
  / 服务商凭据缺失 / 服务商地址不可用 / 解析出的凭据与全局链路凭据相同。
* 仍保留一条 belt-and-braces 断言：若老师凭据与全局凭据相同，直接拒绝。

诚实范围：默认部署下**没有任何获授权的原生实时模型**（唯一 `realtime_safe` 是
冻结 Tina，且门禁拒绝 frozen）。真实老师会以 `realtime_not_configured` /
`capability_mismatch:realtime_not_safe` 诚实 fail-closed；本 seam 用隔离 mock 上游
验证。**老师真实端点形态尚未经真人验证**。REAL_MULTI_TEACHER_HUMAN_TEST = PENDING。
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
from types import SimpleNamespace

from aiohttp import WSMsgType, web

from . import teacher_context          # P2-B2-R2 non-frozen context projection

log = logging.getLogger("rtl.teacher_voice")

TEACHER_WS_PATH = "/xiaozhi/v1/teacher/"
TEACHER_LIST_PATH = "/xiaozhi/v1/teacher/list"
HEADER_TEACHER_TOKEN = "X-Teacher-Token"
DEFAULT_TOKEN_FILE = "/app/secrets/teacher_voice_token"

# 冻结 Tina 的 teacher_id（modules/teacher/store.py::DEFAULT_TEACHER_ID）。
DEFAULT_TEACHER_ID = "tina"
REALTIME_VOICE_MODE = "realtime"

# --- credential isolation (P2-B2-R1) ----------------------------------------
# The frozen realtime engine authenticates with ``Authorization: Bearer
# <QwenConfig.api_key>``.  A non-frozen teacher must therefore be given ITS OWN
# provider credential — never the global (Tina) one — and its endpoint must be
# derived from the provider record it was authorized against.
FROZEN_PROVIDER_ID = "prov_frozen_tina"      # modules.model.registry
REALTIME_PROTOCOL = "dashscope"              # the only protocol the engine speaks
REALTIME_ADAPTER = "builtin"                 # its registered adapter


class TeacherVoiceUnavailable(RuntimeError):
    """A teacher connection could not be authorized/resolved (never invented)."""

    def __init__(self, code, detail=""):
        super().__init__("%s%s" % (code, (": %s" % detail) if detail else ""))
        self.code = str(code)
        self.detail = str(detail)


# --- test-only seam: allow tests to substitute a fake Connection class ---------
_connection_factory = None


def _get_connection_cls():
    if _connection_factory is not None:
        return _connection_factory
    from .turns import Connection          # 延迟导入：无 libopus 环境亦可导入本模块
    return Connection


# ---------------------------------------------------------------------------
# option / config helpers
# ---------------------------------------------------------------------------

def _opts(config):
    """Read the P2-B2 options off a gateway config object (getattr + defaults)."""
    return SimpleNamespace(
        TEACHER_FILE=str(getattr(config, "TEACHER_FILE", "") or ""),
        MODEL_REGISTRY_FILE=str(getattr(config, "MODEL_REGISTRY_FILE", "") or ""),
        MODEL_CREDENTIALS_FILE=str(getattr(config, "MODEL_CREDENTIALS_FILE", "") or ""),
        MODEL_CREDENTIALS_KEY_FILE=str(getattr(config, "MODEL_CREDENTIALS_KEY_FILE", "") or ""),
        TEACHER_VOICE_DATA_DIR=str(getattr(config, "TEACHER_VOICE_DATA_DIR", "") or ""),
        TEACHER_VOICE_TOKEN_FILE=str(
            getattr(config, "TEACHER_VOICE_TOKEN_FILE", "") or DEFAULT_TOKEN_FILE),
        # P2-B2-R2 teaching context: the global (admin) knowledge base is the
        # ONLY source a teacher's authorised material is projected from, and the
        # teaching store + the server-side student label gate the classroom
        # record (both default OFF -> R1 behaviour is unchanged).
        KNOWLEDGE_FILE=str(getattr(config, "KNOWLEDGE_FILE", "") or ""),
        TEACHING_FILE=str(getattr(config, "TEACHING_FILE", "") or ""),
        TEACHER_VOICE_STUDENT_ID=str(
            getattr(config, "TEACHER_VOICE_STUDENT_ID", "") or ""),
        qwen=config.qwen,
        origin=config,           # 保留原始 config 供 clone 用
    )


def _clone_config(cfg):
    """A shallow, independent copy of the gateway config object.

    Never mutate the shared global config (that would change Tina's link too).
    """
    try:
        return SimpleNamespace(**vars(cfg))
    except TypeError:
        import copy
        return copy.copy(cfg)


def _read_token(path):
    try:
        with open(str(path or ""), "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _resolve_token(opts):
    """Token material: env override first (tests), else the configured file."""
    env = os.environ.get("TEACHER_VOICE_TOKEN", "").strip()
    if env:
        return env
    return _read_token(getattr(opts, "TEACHER_VOICE_TOKEN_FILE", ""))


# ---------------------------------------------------------------------------
# per-connection config construction  (the seam itself)
# ---------------------------------------------------------------------------

def build_teacher_qwen(base_qwen, *, model, voice, mode, api_key="",
                       workspace_id="", region="", real_ws_url=""):
    """A NEW QwenConfig for ONE teacher — credential-isolated by construction.

    ``base_qwen`` (the frozen global config) is copied for *behaviour* settings
    only; its **credential material is never read**.  ``api_key`` /
    ``workspace_id`` / ``region`` / ``ws_url`` are always (re)assigned here, so a
    ``real`` teacher connection cannot inherit Tina's API key, workspace or the
    global Secret File.  Missing credential material fails CLOSED.
    """
    import copy as _copy
    q = _copy.copy(base_qwen)
    # Credential isolation FIRST — drop whatever the global/frozen link carried
    # before anything else touches this object (no read path, no transient carry).
    q.api_key = ""
    q.workspace_id = ""
    q.region = ""
    if model:
        q.model = str(model)
    if voice:
        q.voice = str(voice)
    q.mode = str(mode or "mock")
    if q.mode == "real":
        if not str(api_key or "").strip():
            raise TeacherVoiceUnavailable(
                "credential_missing", "老师实时模型缺少自有服务商凭据")
        if not str(real_ws_url or "").strip():
            raise TeacherVoiceUnavailable(
                "realtime_endpoint_not_configured", "老师服务商未提供可用的实时接口地址")
        q.api_key = str(api_key)
        q.ws_url = str(real_ws_url)
        q.workspace_id = str(workspace_id or "")
        q.region = str(region or "")
    else:
        # mock carries no credential material at all (no Authorization header).
        q.ws_url = getattr(base_qwen, "ws_url", "") or "ws://127.0.0.1:9977"
    return q


def provider_realtime_binding(base_url, model_key):
    """``(ws_url, workspace_id, region)`` derived **only** from the provider record.

    The frozen engine's ``real`` mode speaks ``wss://<host>/api-ws/v1/realtime``
    with a Bearer key, and its ``ready`` gate additionally requires a non-empty
    workspace and ``region == "cn-beijing"``.  Every one of those values is taken
    from the **teacher's own provider** ``base_url`` (or left empty) — nothing is
    ever taken from the global/Tina link.

    Returns ``("", "", "")`` when the provider record cannot supply a usable,
    engine-compatible binding; the caller then fails CLOSED.
    """
    from urllib.parse import quote, urlsplit
    from .qwen import REAL_PATH
    try:
        u = urlsplit(str(base_url or "").strip())
        host = (u.hostname or "").lower()
        port = (":%d" % u.port) if u.port else ""
    except ValueError:            # malformed URL / non-numeric port
        return "", "", ""
    if u.scheme not in ("http", "https", "ws", "wss") or not host:
        return "", "", ""
    key = quote(str(model_key or "").strip(), safe="")
    if not key:
        return "", "", ""
    ws_url = "%s://%s%s%s?model=%s" % (
        "ws" if u.scheme in ("http", "ws") else "wss", host, port, REAL_PATH, key)
    # Same host shape the frozen link uses: ``<workspace>.<region>.maas.aliyuncs.com``
    # (suffix must match exactly — a trailing label is never accepted).
    suffix = ".maas.aliyuncs.com"
    if host.endswith(suffix):
        prefix = host[:-len(suffix)]
        if prefix.count(".") == 1:
            workspace, region = prefix.split(".")
            if workspace and region:
                return ws_url, workspace, region
    return ws_url, "", ""


def build_teacher_config(base_config, *, qwen_cfg, teacher_id, data_dir="",
                         policy_file="", knowledge_file="", memory_file=""):
    """A per-connection gateway config for one teacher.

    * ``.qwen`` is replaced (per-teacher model/voice).
    * ``WORKBENCH_BASE_URL`` is CLEARED: it is the global product link, and
      inheriting it would leak the global workbench into a teacher session
      (BehaviorLink reads it at ``behavior.py:88``).  A teacher connection only
      ever carries its own scoped context.
    * the three storage paths come from the teacher's OWN projected context
      (P2-B2-R2).  They are EMPTY whenever ``data_dir`` is unset or a projection
      could not be verified — which means the BehaviorLink loads NO store at all,
      the strongest isolation default (no cross-teacher memory/policy/material).
    """
    from .teacher_context import safe_component
    cfg = _clone_config(base_config)
    cfg.qwen = qwen_cfg
    cfg.WORKBENCH_BASE_URL = ""
    if data_dir and safe_component(teacher_id):
        cfg.MEMORY_FILE = str(memory_file or "")
        cfg.POLICY_FILE = str(policy_file or "")
        cfg.KNOWLEDGE_FILE = str(knowledge_file or "")
    else:
        cfg.MEMORY_FILE = ""
        cfg.POLICY_FILE = ""
        cfg.KNOWLEDGE_FILE = ""
    return cfg


# ---------------------------------------------------------------------------
# authorization (server-side, before any teacher is resolved)
# ---------------------------------------------------------------------------

def authorize(request, expected_token):
    """Constant-time deployment-token check.  Returns (ok, code)."""
    if not str(expected_token or "").strip():
        return False, "teacher_voice_not_configured"
    provided = request.headers.get(HEADER_TEACHER_TOKEN, "")
    if not provided or not hmac.compare_digest(
            provided.encode("utf-8"), str(expected_token).encode("utf-8")):
        return False, "invalid_token"
    return True, ""


# ---------------------------------------------------------------------------
# teacher resolution (server-side, fail-closed)
# ---------------------------------------------------------------------------

def resolve_teacher(store, teacher_id):
    """Load + validate a teacher record.  Raises TeacherVoiceUnavailable."""
    tid = str(teacher_id or "").strip()
    if not tid:
        raise TeacherVoiceUnavailable("teacher_id_required")
    rec = store.get_teacher(tid)
    if rec is None or rec.get("deleted"):
        raise TeacherVoiceUnavailable("teacher_not_found")
    if not rec.get("enabled"):
        raise TeacherVoiceUnavailable("teacher_disabled")
    if rec.get("frozen"):
        # the frozen default teacher IS the production realtime link; this round
        # must not take it over (and must not reconfigure it)
        raise TeacherVoiceUnavailable("frozen_realtime_only")
    voice = rec.get("voice") or {}
    if str(voice.get("mode") or "text") != REALTIME_VOICE_MODE:
        raise TeacherVoiceUnavailable("voice_mode_text")
    return rec


def _registry(opts):
    path = getattr(opts, "MODEL_REGISTRY_FILE", "")
    if not path:
        return None
    try:
        from modules.model.registry import ModelRegistry
        return ModelRegistry(path).load().ensure_seeded()
    except Exception as e:  # noqa: BLE001
        log.warning("teacher voice: registry load failed: %r", e)
        return None


def _credentials(opts):
    path = getattr(opts, "MODEL_CREDENTIALS_FILE", "")
    if not path:
        return None
    try:
        from modules.model.credentials import CredentialStore
        return CredentialStore(path, key_path=getattr(opts, "MODEL_CREDENTIALS_KEY_FILE", "")).load()
    except Exception as e:  # noqa: BLE001
        log.warning("teacher voice: credential store load failed: %r", e)
        return None


def default_resolver(opts, teacher):
    """Resolve a teacher's REAL realtime binding through the shared gate.

    Guarantees (P2-B2-R1 · C1):

    * the model must pass the server-side gate (non-frozen, verified,
      ``realtime_safe`` for the ``oral_realtime`` scene);
    * the model must be operator-**enabled** (P2-B2-R3-0) — a disabled model is
      refused before any credential / endpoint work, i.e. before a real Qwen
      connection can exist;
    * the provider must be one the frozen realtime engine can actually drive
      (``dashscope`` / registered ``builtin`` adapter) and must NOT be the frozen
      Tina provider;
    * the credential is the **provider's own**, read from the sealed credential
      store — the global (Tina) API key / workspace / Secret File are never read;
    * the endpoint + workspace + region are derived **only** from that provider's
      ``base_url``;
    * every missing / incompatible condition fails CLOSED (never a silent
      downgrade to another teacher or to the global link).
    """
    model = teacher.get("model") or {}
    mid = str(model.get("realtime_model_id") or "")
    if not mid:
        raise TeacherVoiceUnavailable("realtime_model_not_configured")
    reg, creds = _registry(opts), _credentials(opts)
    if reg is None or creds is None:
        raise TeacherVoiceUnavailable(
            "realtime_not_configured",
            "网关未配置模型注册表 / 凭据，无法校验老师的实时语音模型")
    rec = reg.get_model(mid)
    if rec is None:
        raise TeacherVoiceUnavailable("model_missing", mid)
    if rec.get("frozen"):
        raise TeacherVoiceUnavailable("frozen_model")
    # P2-B2-R3-0: the model must be ENABLED by an operator.
    #
    # ``enable_gate`` (modules/model/gating.py) checks existence / frozen /
    # adapter / evidence / credential / scene capability — but NOT the operator's
    # ``enabled`` switch, so a model an operator explicitly disabled could still
    # be driven here.  The check is done in THIS (non-frozen) access layer rather
    # than inside the shared gate, to keep the admin enable/set-default flows
    # unaffected and the blast radius minimal.
    #
    # ``enabled`` missing is treated as DISABLED (fail closed): ``create_model``
    # starts every model disabled and ``mark_frozen`` forces it off, so an absent
    # key can only mean a hand-edited / corrupt record.
    #
    # Positioned right after ``frozen`` and ahead of every credential / endpoint /
    # socket step, so a disabled model is refused before any real Qwen connection
    # is created, and NEVER falls back to Tina or another model.
    if not bool(rec.get("enabled")):
        raise TeacherVoiceUnavailable("model_disabled", mid)
    from modules.model.gating import enable_gate
    ok, code, detail = enable_gate(reg, creds, mid, scene="oral_realtime",
                                   action="teaching")
    if not ok:
        raise TeacherVoiceUnavailable(code or "model_unusable", detail or "")
    prov = reg.get_provider(rec["provider_id"])
    if prov is None:
        raise TeacherVoiceUnavailable("provider_missing")
    if prov.get("frozen") or str(prov.get("id") or "") == FROZEN_PROVIDER_ID:
        raise TeacherVoiceUnavailable("frozen_provider")
    proto = str(prov.get("protocol") or "")
    if proto != REALTIME_PROTOCOL or reg.adapter_of(proto) != REALTIME_ADAPTER:
        raise TeacherVoiceUnavailable(
            "provider_incompatible",
            "服务商协议 %r 无法被实时语音引擎驱动" % (proto or "?"))

    # --- the teacher's OWN credential (never the global/frozen one) ----------
    ref = creds.current_ref(prov["id"])
    if not ref:
        raise TeacherVoiceUnavailable("credential_missing")
    try:
        secret = str(creds.read_secret(ref) or "").strip()
    except Exception:  # noqa: BLE001  (unusable credential -> fail closed)
        secret = ""
    if not secret:
        raise TeacherVoiceUnavailable("credential_missing", "服务商凭据不可用")

    # --- the teacher's OWN endpoint / workspace (never the global one) -------
    ws_url, workspace, region = provider_realtime_binding(
        prov.get("base_url"), rec.get("model_key"))
    if not ws_url or not workspace or region != "cn-beijing":
        raise TeacherVoiceUnavailable(
            "realtime_endpoint_not_configured",
            "该服务商地址无法提供引擎所需的实时接口 / workspace / region")

    voice = (teacher.get("voice") or {})
    q = build_teacher_qwen(
        opts.qwen, model=rec.get("model_key"), voice=voice.get("voice_id") or "",
        mode="real", api_key=secret, workspace_id=workspace, region=region,
        real_ws_url=ws_url)
    # Belt-and-braces: a teacher credential must never equal the global one.
    base_key = str(getattr(opts.qwen, "api_key", "") or "")
    if base_key and q.api_key == base_key:
        raise TeacherVoiceUnavailable(
            "credential_isolation_violation",
            "老师凭据与全局链路凭据相同，拒绝建立连接")
    return q


# ---------------------------------------------------------------------------
# WS handler + route mount
# ---------------------------------------------------------------------------

#: strong references for teardowns that outlive a cancelled handler task
_TEARDOWN_TASKS = set()


async def _teardown(conn, observer):
    """Release the connection, then close the classroom record.

    The record is closed with NO outcome, so the store's evidence gate derives
    everything: a transcript-only class yields no pronunciation / learning claim.
    """
    try:
        await conn.close()
    except Exception as e:  # noqa: BLE001
        log.warning("teacher voice: connection close failed: %r", e)
    if observer is None:
        return
    try:
        log.info("teacher voice record closed: %s", await observer.finish())
    except Exception as e:  # noqa: BLE001
        log.warning("teacher voice: record close failed: %r", e)


async def _run_teardown(conn, observer):
    """Run the teardown so that a cancelling client can NOT skip it.

    aiohttp cancels the handler task when the client goes away, and that
    cancellation is delivered at the first ``await`` in the ``finally`` block —
    which used to abort the drain and leave an orphan ``active`` classroom
    record while silently dropping every real turn.  The teardown therefore runs
    in its own task; ``shield`` keeps it alive if the handler is cancelled.
    """
    task = asyncio.ensure_future(_teardown(conn, observer))
    _TEARDOWN_TASKS.add(task)
    task.add_done_callback(_TEARDOWN_TASKS.discard)
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        # the canceller wins the race, but the shielded task still completes
        log.info("teacher voice: teardown continues in the background")
        raise


def make_handler(config, store, token, resolver=None):
    """Build the teacher WS handler (reuses turns.Connection unchanged)."""
    opts = _opts(config)
    resolve = resolver or default_resolver

    async def handler(request):
        ok, code = authorize(request, token)
        if not ok:
            log.warning("teacher voice refused: %s", code)
            return web.json_response({"error": code}, status=401)
        try:
            teacher = resolve_teacher(store, request.query.get("teacher_id"))
            qwen_cfg = resolve(opts, teacher)
        except TeacherVoiceUnavailable as e:
            log.warning("teacher voice refused: %s", e.code)
            return web.json_response({"error": e.code, "detail": e.detail}, status=409)
        except Exception as e:  # noqa: BLE001
            log.warning("teacher voice resolve error: %r", e)
            return web.json_response({"error": "internal_error"}, status=500)

        # ---- P2-B2-R2: THIS teacher's own teaching context -------------------
        # policy / material are projected from the teacher record the server just
        # resolved; nothing is ever taken from the client, and every failure
        # leaves the corresponding path empty (fail-closed, honestly reported).
        ctx = teacher_context.project_teacher_context(
            teacher=teacher,
            data_dir=getattr(opts, "TEACHER_VOICE_DATA_DIR", ""),
            knowledge_source=getattr(opts, "KNOWLEDGE_FILE", ""))
        log.info("teacher voice context teacher=%s policy=%s/%s knowledge=%s/%s "
                 "datasets=%d chunks=%d memory=%s",
                 teacher.get("teacher_id"), ctx["policy"]["state"],
                 ctx["policy"]["reason"], ctx["knowledge"]["state"],
                 ctx["knowledge"]["reason"], ctx["knowledge"]["datasets"],
                 ctx["knowledge"]["chunks"], ctx["memory"]["reason"])

        teacher_cfg = build_teacher_config(
            config, qwen_cfg=qwen_cfg, teacher_id=teacher["teacher_id"],
            data_dir=getattr(opts, "TEACHER_VOICE_DATA_DIR", ""),
            policy_file=ctx["policy"]["path"],
            knowledge_file=ctx["knowledge"]["path"],
            memory_file=ctx["memory"]["path"])

        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        Connection = _get_connection_cls()
        conn = Connection(ws, teacher_cfg)

        # The classroom record is opened only once the connection really exists,
        # so a failed handshake can never leave an orphan "active" session behind.
        observer = None
        record_reason = teacher_context.RECORD_REASON_NOT_CONFIGURED
        try:
            observer, record_reason = teacher_context.open_teaching_record(
                store=_teaching_store(opts),
                student_id=getattr(opts, "TEACHER_VOICE_STUDENT_ID", ""),
                teacher=teacher, binding=_record_binding(opts, teacher),
                dataset_ids=ctx["knowledge"]["dataset_ids"],
                policy=ctx["policy"].get("built") or {},
                course_id=str(((teacher.get("knowledge") or {})
                               .get("default_course")) or ""))
        except Exception as e:  # noqa: BLE001  (never blocks the session)
            log.warning("teacher voice: classroom record skipped: %r", e)
        log.info("teacher voice record teacher=%s decision=%s",
                 teacher.get("teacher_id"), record_reason)
        if observer is not None and not observer.attach(conn):
            # the tap could not be installed -> close the record instead of
            # leaving an active session that can never receive a real turn
            try:
                await observer.finish()
            except Exception as e:  # noqa: BLE001
                log.warning("teacher voice: orphan record close failed: %r", e)
            observer = None
        try:
            try:
                from .admin.registry import sessions as admin_sessions
                admin_sessions.register(conn)
            except Exception as e:  # noqa: BLE001  (observer only)
                log.debug("teacher voice: admin register skipped: %r", e)
            # inside the try: a failing handshake must still release the record
            await conn.on_connect()
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await conn.handle_text(msg.data)
                elif msg.type == WSMsgType.BINARY:
                    conn.handle_binary(msg.data)
                elif msg.type == WSMsgType.ERROR:
                    log.warning("teacher WS error: %s", ws.exception())
                    break
        except Exception as e:  # noqa: BLE001
            log.warning("teacher WS handler error: %s", e)
        finally:
            try:
                from .admin.registry import sessions as admin_sessions
                admin_sessions.discard(conn)
            except Exception:  # noqa: BLE001
                pass
            await _run_teardown(conn, observer)
        return ws

    return handler


def _teacher_store(opts):
    path = getattr(opts, "TEACHER_FILE", "")
    if not path:
        return None
    try:
        from modules.teacher.store import TeacherStore
        return TeacherStore(path).load().ensure_seeded()
    except Exception as e:  # noqa: BLE001
        log.warning("teacher voice: teacher store load failed: %r", e)
        return None


def _teaching_store(opts):
    """The P2-A classroom-record store (P2-B2-R2).  Absent -> record OFF."""
    path = getattr(opts, "TEACHING_FILE", "")
    if not path:
        return None
    try:
        from modules.teaching.store import TeachingSessionStore
        store = TeachingSessionStore(path).load()
        return store if getattr(store, "available", False) else None
    except Exception as e:  # noqa: BLE001
        log.warning("teacher voice: teaching store load failed: %r", e)
        return None


def _record_binding(opts, teacher):
    """Identity metadata for the classroom record (a READ-ONLY registry lookup).

    The model was already authorised by the resolver before this runs; this only
    records WHICH model the session used.  Never fabricates a binding.
    """
    mid = str(((teacher.get("model") or {}).get("realtime_model_id")) or "")
    if not mid:
        return None
    reg = _registry(opts)
    if reg is None:
        return None
    try:
        rec = reg.get_model(mid)
    except Exception as e:  # noqa: BLE001
        log.warning("teacher voice: model lookup failed: %r", e)
        return None
    if not isinstance(rec, dict):
        return None
    return {"model_id": mid, "model_key": str(rec.get("model_key") or ""),
            "provider_id": str(rec.get("provider_id") or "")}


def make_list_handler(store, token):
    """P2-B2-R3-2C: `GET /xiaozhi/v1/teacher/list` for the GUI teacher picker.

    Same constant-time deployment-token auth as the WS route; returns ONLY the
    teachers a normal user may pick — enabled, non-deleted, non-frozen, realtime
    mode — and ONLY display fields (teacher_id / display_name / voice_id /
    language).  Never returns tokens, knowledge dataset ids, student labels or
    internal flags.  No audit entry: reading a list leaks nothing.
    """

    async def list_handler(request):
        ok, code = authorize(request, token)
        if not ok:
            # 401 for BOTH missing and wrong tokens: no oracle for enumeration
            log.warning("teacher list refused: %s", code)
            return web.json_response({"error": code}, status=401)
        rows = []
        try:
            for rec in store.list_teachers():
                if rec.get("deleted") or not rec.get("enabled") or rec.get("frozen"):
                    continue
                voice = rec.get("voice") or {}
                if str(voice.get("mode") or "text") != REALTIME_VOICE_MODE:
                    continue
                rows.append({
                    "teacher_id": str(rec.get("teacher_id") or ""),
                    "display_name": str(rec.get("name") or ""),
                    "voice_id": str(voice.get("voice_id") or ""),
                    "language": str(voice.get("language") or ""),
                })
        except Exception as e:  # noqa: BLE001
            log.warning("teacher list failed: %r", e)
            return web.json_response({"error": "internal_error"}, status=500)
        rows.sort(key=lambda r: (r["display_name"], r["teacher_id"]))
        return web.json_response({"teachers": rows})

    return list_handler


def mount(app, config, *, resolver=None):
    """Additive route mount.  Fail-closed: no token / no teacher store -> no route.

    Returns True only when the route was actually mounted.
    """
    if str(getattr(config, "TEACHER_VOICE_WS", "0")).strip().lower() not in (
            "1", "true", "yes", "on"):
        return False
    opts = _opts(config)
    token = _resolve_token(opts)
    if not token:
        log.error("TEACHER_VOICE_WS=1 but no token configured "
                  "(TEACHER_VOICE_TOKEN_FILE / TEACHER_VOICE_TOKEN); "
                  "teacher WS route NOT mounted")
        return False
    store = _teacher_store(opts)
    if store is None or not getattr(store, "available", False):
        log.error("TEACHER_VOICE_WS=1 but teacher store unavailable; "
                  "teacher WS route NOT mounted")
        return False
    handler = make_handler(config, store, token, resolver=resolver)
    app.router.add_get(TEACHER_WS_PATH, handler)
    app.router.add_get(TEACHER_LIST_PATH, make_list_handler(store, token))
    log.info("teacher voice WS mounted at %s (+ GET %s for the GUI teacher "
             "picker; per-connection teacher binding)",
             TEACHER_WS_PATH, TEACHER_LIST_PATH)
    return True
