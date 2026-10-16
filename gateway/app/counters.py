"""Process-global counters exposed via the /health endpoint.

R-1f rev-9 counter contract (design A.14):
- legacy XiaoZhi-facing counters (kept verbatim for compatibility);
- cumulative R-1f counters (`inc`);
- gauges (`set_gauge`, sampled at quiescence / on change);
- / health states (`set_state`);
- max/min observations (`observe_max` / `observe_min`);
- aliases (`set_gauge` on the alias names).
"""

import time

# ---- A.14 CUMULATIVE COUNTERS ---------------------------------------------

CUMULATIVE = (
    # A.4.A source byte domain
    "source_pcm_bytes", "admitted_pcm_bytes", "guard_dropped_pcm_bytes",
    "safety_truncated_pcm_bytes", "orphan_pcm_bytes", "idless_delta_mapped_bytes",
    "bad_base64_live_events", "bad_base64_stale_or_unmapped_events",
    "post_terminal_delta_events", "qwen_dispatch_errors_total",
    "accounting_fault_events",
    # A.4.B framer / encoder byte domain
    "encoded_full_frames", "encode_failed_frames", "synthetic_tail_frames",
    "synthetic_tail_source_bytes", "synthetic_tail_zero_pad_bytes",
    "synthetic_tail_encode_failures", "synthetic_tail_encode_failed_source_bytes",
    "synthetic_tail_encode_failed_zero_pad_bytes",
    "residue_discarded_bargein_bytes", "residue_discarded_abort_bytes",
    "residue_discarded_close_bytes", "residue_discarded_listen_start_bytes",
    "residue_discarded_upstream_closed_bytes", "residue_discarded_pacer_stall_bytes",
    "residue_discarded_byte_cap_failure_bytes", "residue_discarded_send_error_bytes",
    "residue_discarded_store_cap_bytes",
    # A.4.C encoded frame disposition domain
    "sent_confirmed_frames", "flushed_bargein_frames", "flushed_abort_frames",
    "flushed_close_frames", "flushed_listen_start_frames",
    "flushed_upstream_closed_frames", "flushed_pacer_stall_frames",
    "flushed_byte_cap_failure_frames", "flushed_send_error_frames",
    "send_failed_frames", "send_outcome_unknown_frames", "post_terminal_sends_total",
    # A.5/A.6 pacer
    "pacer_starts", "pacer_rebases", "pacer_fatal_stalls", "pacer_short_interval_count",
    "pacer_floor_bind_count", "slow_send_events", "slow_send_guard_violations",
    "audio_rebase_discarded_frames",
    # regression / A.9 / A.10 / A.11
    "legacy_drop_oldest_calls", "barge_in_sequence_incomplete",
    "barge_in_sequences_total", "barge_in_invalidate_failures",
    "barge_in_pacer_cancel_failures", "barge_in_store_flush_failures",
    "barge_in_tts_stop_failures", "cancel_attempts", "cancel_send_errors",
    "byte_cap_failures", "cap_transitions_total",
    "steady_pacer_segments_qualifying_total",
    # legacy diagnostic (marked LEGACY; no closure may use it)
    "qwen_audio_delta_bytes",
)

# Sum of these nine terms == residue_discarded_pcm_bytes (computed in snapshot).
RESIDUE_TERMS = (
    "residue_discarded_bargein_bytes", "residue_discarded_abort_bytes",
    "residue_discarded_close_bytes", "residue_discarded_listen_start_bytes",
    "residue_discarded_upstream_closed_bytes", "residue_discarded_pacer_stall_bytes",
    "residue_discarded_byte_cap_failure_bytes", "residue_discarded_send_error_bytes",
    "residue_discarded_store_cap_bytes",
)

# ---- A.14 GAUGES (sampled at generation quiescence / on ownership change) --
GAUGES = (
    "audio_store_current_frames", "audio_store_current_bytes",
    "unsent_backlog_current_frames", "in_flight_frames", "still_stored_frames",
    "still_buffered_pcm_bytes", "active_pacer_tasks",
)

# ---- A.14 STATES -----------------------------------------------------------
STATES = (
    "previous_audio_send_start_at", "send_guard_until", "tts_owner_generation_id",
)

# ---- A.14 MAX / MIN OBSERVATIONS ------------------------------------------
MAX_OBS = (
    "audio_store_peak_frames", "unsent_backlog_peak_frames", "audio_store_peak_bytes",
    "pacer_lead_frames_max", "pacer_wake_overshoot_mean_ms_observed",
    "active_pacer_tasks_max", "steady_segment_frames_max",
    "steady_segment_rate_fps_max", "steady_segment_mean_inter_send_ms_max",
    "pacer_rebase_max_lateness_ms", "wire_rate_excess_frames_max",
    "cancel_max_per_generation", "cap_transitions_max_per_generation",
    "end_markers_max_per_generation", "tts_stop_emissions_max_per_generation",
)

MIN_OBS = (
    "pacer_min_inter_send_ms_observed",
    "steady_segment_rate_fps_min", "steady_segment_mean_inter_send_ms_min",
)

# Compatibility aliases (A.5 PO M2) — never sole acceptance observables.
ALIASES = ("steady_pacer_rate_fps", "pacer_mean_inter_send_ms_observed")


class Counters:
    def __init__(self):
        self._start = time.monotonic()
        self._c = {k: 0 for k in CUMULATIVE}
        self._g = {k: None for k in GAUGES}
        self._s = {k: None for k in STATES}
        self._mx = {k: None for k in MAX_OBS}
        self._mn = {k: None for k in MIN_OBS}
        self._al = {k: None for k in ALIASES}
        self.qwen_dispatch_errors_by_type = {}
        # existing XiaoZhi-facing counters (legacy; unchanged names)
        self.ws_connections = 0
        self.aborts = 0
        self.last_abort_stop_ms = None
        # Qwen realtime counters
        self.qwen_connected = 0
        self.qwen_sessions = 0
        self.qwen_connect_errors = 0
        self.audio_in_opus_frames = 0
        self.audio_in_pcm_bytes = 0
        self.audio_out_opus_frames = 0
        self.responses_completed = 0
        self.responses_cancelled = 0
        self.barge_ins = 0
        self.upstream_errors = 0
        self.last_speech_stop_to_first_audio_ms = None
        # DEPRECATED: no R-1f mutation site (A.3 m-5 exemption); read-only below.
        self.audio_out_dropped = 0
        self.uplink_dropped = 0

    # ---- R-1f accessors (validated) ---------------------------------------

    def inc(self, name, n=1):
        cur = self._c.get(name)
        if cur is None:
            raise KeyError("unknown cumulative counter: %r" % name)
        self._c[name] = cur + n

    def get(self, name):
        if name in self._c:
            return self._c[name]
        if name in self._mx:
            return self._mx[name]
        if name in self._mn:
            return self._mn[name]
        if name in self._g:
            return self._g[name]
        if name in self._s:
            return self._s[name]
        return None

    def observe_max(self, name, v):
        if name not in self._mx:
            raise KeyError("unknown max observation: %r" % name)
        cur = self._mx[name]
        if cur is None or v > cur:
            self._mx[name] = v

    def observe_min(self, name, v):
        if name not in self._mn:
            raise KeyError("unknown min observation: %r" % name)
        cur = self._mn[name]
        if cur is None or v < cur:
            self._mn[name] = v

    def set_gauge(self, name, v):
        if name in self._g:
            self._g[name] = v
            return
        if name in self._al:
            self._al[name] = v
            return
        raise KeyError("unknown gauge/alias: %r" % name)

    def set_state(self, name, v):
        if name not in self._s:
            raise KeyError("unknown state field: %r" % name)
        self._s[name] = v

    def inc_dispatch_error(self, etype):
        self.inc("qwen_dispatch_errors_total")
        key = str(etype)
        self.qwen_dispatch_errors_by_type[key] = (
            self.qwen_dispatch_errors_by_type.get(key, 0) + 1)

    def uptime_s(self):
        return round(time.monotonic() - self._start, 3)

    # ---- snapshot ----------------------------------------------------------

    def snapshot(self):
        out = {
            "status": "ok",
            "uptime_s": self.uptime_s(),
            "ws_connections": self.ws_connections,
            # turns / frames_in / frames_out are kept as aliases
            "turns": self.responses_completed + self.responses_cancelled,
            "frames_in": self.audio_in_opus_frames,
            "frames_out": self.audio_out_opus_frames,
            "aborts": self.aborts,
            "last_abort_stop_ms": self.last_abort_stop_ms,
            "qwen_connected": self.qwen_connected,
            "qwen_sessions": self.qwen_sessions,
            "qwen_connect_errors": self.qwen_connect_errors,
            "audio_in_opus_frames": self.audio_in_opus_frames,
            "audio_in_pcm_bytes": self.audio_in_pcm_bytes,
            "qwen_audio_delta_bytes": self._c["qwen_audio_delta_bytes"],
            "audio_out_opus_frames": self.audio_out_opus_frames,
            "responses_completed": self.responses_completed,
            "responses_cancelled": self.responses_cancelled,
            "barge_ins": self.barge_ins,
            "upstream_errors": self.upstream_errors,
            "last_speech_stop_to_first_audio_ms":
                self.last_speech_stop_to_first_audio_ms,
            "audio_out_dropped": self.audio_out_dropped,
            "uplink_dropped": self.uplink_dropped,
        }
        out.update(self._c)
        out.update(self._g)
        out.update(self._s)
        out.update(self._mx)
        out.update(self._mn)
        out.update(self._al)
        out["residue_discarded_pcm_bytes"] = sum(
            self._c[k] for k in RESIDUE_TERMS)
        out["qwen_dispatch_errors_by_type"] = dict(self.qwen_dispatch_errors_by_type)
        return out


counters = Counters()