"""ADMIN-1 views: exactly six read-only endpoints, plus the static UI shell.

Every payload is built by an **allowlist constructor** — never by serializing an internal
object and deleting fields.  Raw transcripts, raw session/response ids, secret values, secret
paths, capture paths and unbounded arrays cannot appear because they are never copied in.
"""

import logging

from aiohttp import web

from .. import diag
from ..counters import counters
from . import version as version_mod
from .registry import sessions

log = logging.getLogger("rtl.admin.views")

UI_FILES = {"/": "index.html", "/index.html": "index.html",
            "/app.js": "app.js", "/styles.css": "styles.css"}

FLUSH_KEYS = (
    "flushed_bargein_frames", "flushed_abort_frames", "flushed_close_frames",
    "flushed_listen_start_frames", "flushed_upstream_closed_frames",
    "flushed_pacer_stall_frames", "flushed_byte_cap_failure_frames",
    "flushed_send_error_frames",
)

# Bounded, non-sensitive aggregate metrics (see docs/architecture/api-boundaries.md).
METRIC_KEYS = (
    # connectivity
    "ws_connections", "qwen_connected", "qwen_sessions", "qwen_connect_errors",
    # responses / turns
    "responses_completed", "responses_cancelled", "turns", "barge_ins",
    "upstream_errors", "aborts",
    # audio frames (aggregate counts only)
    "audio_in_opus_frames", "audio_out_opus_frames", "audio_in_pcm_bytes",
    "qwen_audio_delta_bytes",
    # pacer aggregates
    "pacer_starts", "pacer_rebases", "pacer_fatal_stalls", "pacer_short_interval_count",
    "slow_send_guard_violations", "steady_pacer_segments_qualifying_total",
    "active_pacer_tasks", "active_pacer_tasks_max",
    "pacer_min_inter_send_ms_observed", "pacer_rebase_max_lateness_ms",
    "steady_segment_rate_fps_min", "steady_segment_rate_fps_max",
    "steady_segment_mean_inter_send_ms_min", "steady_segment_mean_inter_send_ms_max",
    "wire_rate_excess_frames_max", "pacer_wake_overshoot_mean_ms_observed",
    # closure / integrity counters
    "byte_cap_failures", "cap_transitions_total", "send_outcome_unknown_frames",
    "post_terminal_sends_total", "send_failed_frames", "encode_failed_frames",
    "guard_dropped_pcm_bytes", "safety_truncated_pcm_bytes",
    "residue_discarded_pcm_bytes", "still_buffered_pcm_bytes",
    "still_stored_frames", "in_flight_frames", "audio_store_current_frames",
    # barge-in aggregate counters
    "barge_in_sequences_total", "barge_in_sequence_incomplete",
    # latency aggregates
    "last_speech_stop_to_first_audio_ms", "last_abort_stop_ms",
)


def _rid(request):
    return request.get("request_id", "")


def _num(value):
    return 0 if value is None else value


def _closures(snap):
    """The three R-1f closure residuals (0 when the run is clean)."""
    source = _num(snap.get("source_pcm_bytes")) - (
        _num(snap.get("admitted_pcm_bytes")) + _num(snap.get("guard_dropped_pcm_bytes"))
        + _num(snap.get("safety_truncated_pcm_bytes")))
    framer = _num(snap.get("admitted_pcm_bytes")) - (
        960 * _num(snap.get("encoded_full_frames"))
        + 960 * _num(snap.get("encode_failed_frames"))
        + _num(snap.get("synthetic_tail_source_bytes"))
        + _num(snap.get("synthetic_tail_encode_failed_source_bytes"))
        + _num(snap.get("residue_discarded_pcm_bytes"))
        + _num(snap.get("still_buffered_pcm_bytes")))
    disposition = (_num(snap.get("encoded_full_frames")) + _num(snap.get("synthetic_tail_frames"))) - (
        _num(snap.get("sent_confirmed_frames"))
        + sum(_num(snap.get(k)) for k in FLUSH_KEYS)
        + _num(snap.get("send_failed_frames")) + _num(snap.get("send_outcome_unknown_frames"))
        + _num(snap.get("still_stored_frames")) + _num(snap.get("in_flight_frames")))
    return {"source_residual_bytes": source,
            "framer_residual_bytes": framer,
            "disposition_residual_frames": disposition}


# ---- the six endpoints -----------------------------------------------------

async def health(request):
    snap = counters.snapshot()
    info = request.app["admin_gateway_info"]() or {}
    store = request.app.get("admin_token_store")
    stores = request.app.get("admin_stores")
    admin_cfg = request.app["admin_config"]
    reasons = []
    if info.get("mode") == "real" and not info.get("ready", False):
        reasons.append("qwen_not_ready")
    if store is not None and not store.configured:
        reasons.append("admin_auth_not_configured")
    return web.json_response({
        "status": "degraded" if reasons else "ok",
        "degraded_reasons": reasons,
        "uptime_s": snap.get("uptime_s"),
        "gateway_version": version_mod.GATEWAY_VERSION,
        "qwen_mode": info.get("mode"),
        "qwen_ready": bool(info.get("ready", False)),
        "qwen_model": info.get("model"),
        "qwen_voice": info.get("voice"),
        "qwen_connected": snap.get("qwen_connected"),
        "qwen_sessions": snap.get("qwen_sessions"),
        "ws_connections": snap.get("ws_connections"),
        "active_sessions": sessions.count(),
        "responses": {
            "completed": snap.get("responses_completed"),
            "cancelled": snap.get("responses_cancelled"),
            "turns": snap.get("turns"),
        },
        "admin": {
            "enabled": admin_cfg.enabled,
            "bind": admin_cfg.bind,
            "port": admin_cfg.port,
            "auth_configured": bool(store.configured) if store is not None else False,
            "listener": "running",
        },
        # V4 wiring visibility (requirement: admin face ↔ running service): the
        # bundles are the SAME on-disk stores the runtime uses; booleans only,
        # no paths, no secrets.  ``None`` = the bundle is not mounted at all.
        "stores": (stores.describe()
                   if stores is not None and hasattr(stores, "describe") else None),
        "build": {
            "git_commit": version_mod.build_facts().get("git_commit"),
            "build_time": version_mod.build_facts().get("build_time"),
        },
        "request_id": _rid(request),
    })


async def version_view(request):
    facts = version_mod.build_facts()
    facts["request_id"] = _rid(request)
    return web.json_response(facts)


async def sessions_view(request):
    rows = sessions.snapshot()
    return web.json_response({
        "available": True,
        "count": len(rows),
        "sessions": rows,
        "note": None if rows else "no_active_sessions",
        "request_id": _rid(request),
    })


async def metrics_view(request):
    snap = counters.snapshot()
    metrics = {k: snap.get(k) for k in METRIC_KEYS}
    metrics["uptime_s"] = snap.get("uptime_s")
    return web.json_response({
        "available": True,
        "window": "process_lifetime",
        "metrics": metrics,
        "closures": _closures(snap),
        "request_id": _rid(request),
    })


async def telemetry_view(request):
    # No authoritative server-side client-telemetry aggregator exists yet: stay honest.
    return web.json_response({
        "available": False,
        "reason": "server_side_aggregator_unavailable",
        "request_id": _rid(request),
    })


async def diag_summary_view(request):
    snap = diag.SNAPSHOT_PROVIDER() or {}
    enabled = bool(snap.get("enabled", False))
    if not enabled:
        return web.json_response({
            "available": True,
            "enabled": False,
            "reason": "diagnostics_disabled",
            "capture": {"enabled": False},
            "request_id": _rid(request),
        })
    cap_raw = diag.capture_info() or {}
    per_conn = snap.get("per_conn") or {}
    segments = snap.get("steady_segments") or []
    intervals = snap.get("send_intervals_ms")
    c = counters.snapshot()
    return web.json_response({
        "available": True,
        "enabled": True,
        "uptime_s": snap.get("uptime_s"),
        "journal_entries": snap.get("journal_entries"),
        "assertions_total": snap.get("assertions_total"),
        "assertions": dict(snap.get("assertions") or {}),
        "generation_count": snap.get("generation_count"),
        "connection_count": len(snap.get("connections") or {}),
        "live_pacer_count": len(per_conn.get("live_pacers") or []),
        "invalidated_generation_count": len(per_conn.get("invalidated_gens") or []),
        "conns_closed": per_conn.get("conns_closed"),
        "active_generation": per_conn.get("active_gen") is not None,
        "tts_active": per_conn.get("tts_gen") is not None,
        "send_interval_ms": (
            {"p50": intervals.get("p50"), "p95": intervals.get("p95"),
             "min": intervals.get("min"), "max": intervals.get("max"), "n": intervals.get("n")}
            if isinstance(intervals, dict) else None),
        "steady_segments": {
            "count": len(segments),
            "frames_max": c.get("steady_segment_frames_max"),
            "rate_fps_min": c.get("steady_segment_rate_fps_min"),
            "rate_fps_max": c.get("steady_segment_rate_fps_max"),
            "mean_inter_send_ms_min": c.get("steady_segment_mean_inter_send_ms_min"),
            "mean_inter_send_ms_max": c.get("steady_segment_mean_inter_send_ms_max"),
        },
        "closures": _closures(c),
        # capture: enabled flag + byte counts only (never the capture directory)
        "capture": {
            "enabled": bool(cap_raw.get("enabled", False)),
            "bytes": {name: cap_raw.get(name, 0) for name in
                      ("qwen_pcm24.raw", "sent_opus.bin", "sent_opus.jsonl")},
        },
        "resettable": False,          # ADMIN-1 exposes no reset (locked scope)
        "request_id": _rid(request),
    })


# ---- static UI shell (allowlist; no listing, no user-controlled paths) -----

async def ui_shell(request):
    name = request.path
    if name == "/favicon.ico":
        return web.Response(status=204)
    filename = UI_FILES.get(name)
    if not filename:
        return web.json_response({"error": "not_found", "request_id": _rid(request)}, status=404)
    path = request.app["admin_ui_dir"] / filename
    if not path.is_file():
        log.warning("admin UI file missing: %s", filename)
        return web.json_response(
            {"error": "ui_unavailable", "detail": "static UI file not found",
             "request_id": _rid(request)}, status=503)
    ctype = {"index.html": "text/html; charset=utf-8",
             "app.js": "application/javascript; charset=utf-8",
             "styles.css": "text/css; charset=utf-8"}[filename]
    return web.FileResponse(path, headers={"Content-Type": ctype,
                                           "Cache-Control": "no-store"})


# ---- V4 dual-mode UI (static shell; the API it calls is `/admin/*`) --------

V4_UI_FILES = {"/v4": "index.html", "/v4/": "index.html",
               "/v4/index.html": "index.html", "/v4/app.js": "app.js",
               "/v4/app-pro.js": "app-pro.js", "/v4/styles.css": "styles.css"}


async def v4_shell(request):
    """Serve the V4 dual-mode static shell from ``admin_config.ui_v4_dir``.

    Like the ADMIN-1 shell this is public by construction (no operational data);
    every call it makes to ``/admin/*`` still needs the bearer token.
    """
    filename = V4_UI_FILES.get(request.path)
    if not filename:
        return web.json_response({"error": "not_found", "request_id": _rid(request)},
                                 status=404)
    base = request.app["admin_v4_ui_dir"]
    path = base / filename
    if not path.is_file():
        log.warning("admin V4 UI file missing: %s", filename)
        return web.json_response(
            {"error": "ui_unavailable", "detail": "static UI file not found",
             "request_id": _rid(request)}, status=503)
    ctype = {"html": "text/html; charset=utf-8",
             "js": "application/javascript; charset=utf-8",
             "css": "text/css; charset=utf-8"}.get(path.suffix.lstrip("."), "text/plain")
    return web.FileResponse(path, headers={"Content-Type": ctype,
                                           "Cache-Control": "no-store"})