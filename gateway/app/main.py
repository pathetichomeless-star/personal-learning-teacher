"""Entrypoint: aiohttp app served on two ports (WS 8110 / HTTP 8111)."""

import asyncio
import json
import logging
import os
import signal
from functools import partial
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web

from . import http, ws
from .admin import load_admin_config, start_admin_listener, stop_admin_listener
from .qwen import QwenConfig

log = logging.getLogger("rtl.main")

DEFAULTS = {
    "PUBLIC_WS_URL": "ws://192.0.2.1:8110/xiaozhi/v1/",
    "WS_PORT": 8110,
    "HTTP_PORT": 8111,
    "FRAME_MS": 20,
    "QWEN_MODE": "mock",
    "QWEN_WS_URL": "",
    "QWEN_WORKSPACE_ID": "",
    "QWEN_MODEL": "qwen3.8-omni-flash-realtime",
    "QWEN_VOICE": "Tina",
    "QWEN_SECRET_FILE": "/app/secrets/qwen-realtime.env",
    "QWEN_RECONNECT_MAX": 5,
    "QWEN_RECONNECT_BASE_MS": 500,
    "QWEN_STABLE_RESET_S": 30,
    # BEHAVIOR-1 / MEMORY-1 / WORKBENCH-1 / KNOWLEDGE-1 / POLICY-1 (empty =
    # disabled: pure R-1f behaviour)
    "MEMORY_FILE": "",
    "WORKBENCH_BASE_URL": "",
    "KNOWLEDGE_FILE": "",
    "POLICY_FILE": "",
    # ADMIN V4 (model management + knowledge import).  Empty = store absent
    # (that surface simply is not mounted).
    "MODEL_REGISTRY_FILE": "",
    "MODEL_CREDENTIALS_FILE": "",
    "MODEL_CREDENTIALS_KEY_FILE": "",
    "KNOWLEDGE_IMPORT_FILE": "",
    "KNOWLEDGE_IMPORT_SCRATCH": "",
    # P1 multi-teacher: independent teacher-profile store.  Empty = surface absent.
    "TEACHER_FILE": "",
    # P2-A teaching sessions: real text-teaching sessions + classroom records.
    # Empty = the teaching surface simply is not mounted (no behavior change).
    "TEACHING_FILE": "",
    # P2-B1 voice channels: audio-transport lifecycle of a voice classroom.
    # Empty = the voice surface is not mounted (no behavior change).
    "VOICE_FILE": "",
    # P2-B2 teacher voice bridge: a flag-gated, ADDITIVE WS route that binds a
    # teacher to a per-connection copy of the frozen realtime config.  Default 0
    # -> the route is not mounted and the frozen /xiaozhi/v1/ path is untouched.
    "TEACHER_VOICE_WS": "0",
    "TEACHER_VOICE_DATA_DIR": "",
    "TEACHER_VOICE_TOKEN_FILE": "/app/secrets/teacher_voice_token",
    # P2-B2-R2 classroom records: a SERVER-side student label for the voice
    # classroom.  Empty (default) -> NO classroom record is written, because an
    # unattributed record must never be invented and the client may not declare
    # one.  Setting it also requires TEACHING_FILE.
    "TEACHER_VOICE_STUDENT_ID": "",
    "MODEL_TEST_AUTHORIZED": "0",
    # Explicit, product-owner-authorized promotion to ``realtime_safe``
    # (contract §2.3 step 3).  Default 0: the promotion route fails closed.
    "MODEL_PROMOTE_AUTHORIZED": "0",
    # P2-B2-R3-2C: the realtime HANDSHAKE probe (the honest evidence channel for
    # dashscope models) has its OWN authorization flag, default off.  A probe
    # writes at most the ``realtime_handshake`` ladder level — never
    # verified/realtime_safe — and dials the provider's own endpoint with the
    # provider's own sealed credential.
    "MODEL_REALTIME_PROBE_AUTHORIZED": "0",
}


def load_config():
    values = dict(DEFAULTS)
    cfg_path = Path(__file__).resolve().parent.parent / "config" / "config.json"
    try:
        if cfg_path.is_file():
            values.update(json.loads(cfg_path.read_text("utf-8")))
    except Exception as e:  # noqa: BLE001
        log.warning("config.json load failed (%s); using defaults", e)
    for key in DEFAULTS:
        if key in os.environ:
            values[key] = os.environ[key]
    return SimpleNamespace(
        PUBLIC_WS_URL=str(values["PUBLIC_WS_URL"]),
        WS_PORT=int(values["WS_PORT"]),
        HTTP_PORT=int(values["HTTP_PORT"]),
        FRAME_MS=int(values["FRAME_MS"]),
        MEMORY_FILE=str(values.get("MEMORY_FILE") or ""),
        WORKBENCH_BASE_URL=str(values.get("WORKBENCH_BASE_URL") or ""),
        KNOWLEDGE_FILE=str(values.get("KNOWLEDGE_FILE") or ""),
        POLICY_FILE=str(values.get("POLICY_FILE") or ""),
        MODEL_REGISTRY_FILE=str(values.get("MODEL_REGISTRY_FILE") or ""),
        MODEL_CREDENTIALS_FILE=str(values.get("MODEL_CREDENTIALS_FILE") or ""),
        MODEL_CREDENTIALS_KEY_FILE=str(values.get("MODEL_CREDENTIALS_KEY_FILE") or ""),
        KNOWLEDGE_IMPORT_FILE=str(values.get("KNOWLEDGE_IMPORT_FILE") or ""),
        KNOWLEDGE_IMPORT_SCRATCH=str(values.get("KNOWLEDGE_IMPORT_SCRATCH") or ""),
        TEACHER_FILE=str(values.get("TEACHER_FILE") or ""),
        TEACHING_FILE=str(values.get("TEACHING_FILE") or ""),
        VOICE_FILE=str(values.get("VOICE_FILE") or ""),
        TEACHER_VOICE_WS=str(values.get("TEACHER_VOICE_WS") or "0"),
        TEACHER_VOICE_DATA_DIR=str(values.get("TEACHER_VOICE_DATA_DIR") or ""),
        TEACHER_VOICE_TOKEN_FILE=str(values.get("TEACHER_VOICE_TOKEN_FILE")
                                     or "/app/secrets/teacher_voice_token"),
        TEACHER_VOICE_STUDENT_ID=str(values.get("TEACHER_VOICE_STUDENT_ID") or ""),
        MODEL_TEST_AUTHORIZED=str(values.get("MODEL_TEST_AUTHORIZED") or "0"),
        MODEL_PROMOTE_AUTHORIZED=str(values.get("MODEL_PROMOTE_AUTHORIZED") or "0"),
        MODEL_REALTIME_PROBE_AUTHORIZED=str(
            values.get("MODEL_REALTIME_PROBE_AUTHORIZED") or "0"),
        qwen=QwenConfig.from_values(values),
    )


def create_app(config):
    app = web.Application()
    app.router.add_get("/health", http.health)
    app.router.add_post("/xiaozhi/ota/", partial(http.ota, config=config))
    # VISION V0.5: 客户端图像提交（专用 vision token，非 admin token）
    app.router.add_post("/xiaozhi/vision/", partial(http.make_vision_handler(config)))
    app.router.add_get("/xiaozhi/ota/", partial(http.ota, config=config))
    app.router.add_get("/xiaozhi/v1/", partial(ws.ws_handler, config=config))
    # R-1c diagnostics (read-only; 404-free but inert when RTL_DIAG is unset)
    app.router.add_get("/diag", http.diag_view)
    app.router.add_post("/diag/reset", http.diag_reset)
    app.router.add_get("/diag/capture", http.diag_capture)
    # P2-B2: additive, flag-gated teacher voice WS route.  Flag off (default) ->
    # not mounted; the frozen /xiaozhi/v1/ route above is unchanged either way.
    from . import teacher_voice
    teacher_voice.mount(app, config)
    return app


async def _run():
    config = load_config()
    q = config.qwen
    log.info("config: PUBLIC_WS_URL=%s WS_PORT=%d HTTP_PORT=%d FRAME_MS=%d",
             config.PUBLIC_WS_URL, config.WS_PORT,
             config.HTTP_PORT, config.FRAME_MS)
    if q.is_real:
        if q.ready:
            log.info("qwen mode=real host=%s model=%s voice=%s",
                     q.host, q.model, q.voice)
        else:
            log.error("qwen mode=real NOT READY: %s "
                      "(qwen_connected=false, no crash)", q.not_ready_reason)
    else:
        log.info("qwen mode=mock host=%s model=%s voice=%s",
                 q.host, q.model, q.voice)

    runners = []
    for name, port in (("ws", config.WS_PORT), ("http", config.HTTP_PORT)):
        runner = web.AppRunner(create_app(config))
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", port).start()
        runners.append(runner)
        log.info("listening %s on 0.0.0.0:%d", name, port)

    # ADMIN-1/ADMIN-2 control plane: a THIRD, separate listener that only starts when
    # ADMIN_ENABLED=1.  With the default (0) nothing changes for the current runtime.
    admin_cfg = load_admin_config()
    stores = None
    if admin_cfg.enabled:
        from .admin.stores import AdminStores
        from modules.model.registry import frozen_link_snapshot
        # read-only snapshot of the EXISTING (frozen) realtime link — detection
        # only; nothing here changes the audio path.
        frozen_snap = frozen_link_snapshot(
            mode=q.mode, model=q.model, voice=q.voice,
            host=getattr(q, "host", ""), frame_ms=config.FRAME_MS,
            reconnect_max=getattr(q, "reconnect_max", None))
        stores = AdminStores(
            policy_file=config.POLICY_FILE,
            memory_file=config.MEMORY_FILE,
            knowledge_file=config.KNOWLEDGE_FILE,
            workbench_url=config.WORKBENCH_BASE_URL,
            model_registry_file=config.MODEL_REGISTRY_FILE,
            model_credentials_file=config.MODEL_CREDENTIALS_FILE,
            model_credentials_key_file=config.MODEL_CREDENTIALS_KEY_FILE,
            knowledge_import_file=config.KNOWLEDGE_IMPORT_FILE,
            knowledge_import_scratch=config.KNOWLEDGE_IMPORT_SCRATCH,
            teacher_file=config.TEACHER_FILE,
            teaching_file=config.TEACHING_FILE,
            voice_file=config.VOICE_FILE,
            realtime_snapshot=frozen_snap,
            test_authorized=str(config.MODEL_TEST_AUTHORIZED).strip() in ("1", "true", "yes"),
            promote_authorized=str(config.MODEL_PROMOTE_AUTHORIZED).strip() in ("1", "true", "yes"),
            realtime_probe_authorized=str(
                config.MODEL_REALTIME_PROBE_AUTHORIZED).strip() in ("1", "true", "yes"))
    admin_runners = await start_admin_listener(
        admin_config=admin_cfg,
        gateway_info=lambda: {"mode": "real" if q.is_real else "mock",
                              "ready": bool(q.ready),
                              "model": q.model, "voice": q.voice},
        stores=stores,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    await stop.wait()
    log.info("shutdown requested; cleaning up runners")
    await stop_admin_listener(admin_runners)
    for runner in runners:
        await runner.cleanup()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()