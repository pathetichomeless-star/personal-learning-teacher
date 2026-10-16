#!/usr/bin/env python3
"""R-1c Phase 8 analysis (pure stdlib + opuslib; no numpy in the container).

A = raw Qwen PCM24 s16le mono, exactly as reassembled before Opus encoding
B = the exact Opus packets handed to the XiaoZhi wire
C = PCM24 decoded from exactly those packets

FRAME IDENTITY (R-1e ITEM 3)
----------------------------
Frames are keyed by the triple ``(response_id, generation_id, frame_seq)``.
``frame_seq`` ALONE is NEVER an identity: the bridge resets ``frame_seq`` to 0
on every ``response.created`` (app/turns.py ``_make_frame`` increments
``self.diag.frame_seq``, and ``on_response_created`` sets it back to 0), so the
same ``frame_seq`` value occurs once per generation. The output states the
identity scheme explicitly in ``frame_identity``.

DROP BOUNDARIES (R-1e ITEM 3)
------------------------------
A "contiguous dropped region" is a maximal run of source frames that were
present in the source capture (A) but have NO packet in the sent list (B).
Because drop-oldest removes the OLDEST queued frames, such regions are expected
to sit at the FRONT of a generation when the queue saturates.

Usage:
  python r1c_audio_analysis.py                       # analyse $RTL_DIAG_DIR
  python r1c_audio_analysis.py --diag-dir /tmp/x     # explicit capture dir
  python r1c_audio_analysis.py --self-test-inject    # ITEM 4 self-test
"""

import array
import json
import math
import os
import shutil
import struct
import sys
import tempfile

import opuslib

D = os.environ.get("RTL_DIAG_DIR", "/tmp/rtl-diag")
SR = 24000
N = 480                      # samples per 20 ms frame
FRAME_MS = 20.0

# ---- R-1e ITEM 3: EXPLICIT, UNCHANGED thresholds ---------------------------
# TH_DISC is the PRE-EXISTING audibility proxy carried over from the original
# analyzer (8000/32768 = 24.41% of full scale). It is NOT weakened.
TH_DISC = 8000               # ~24.41% FS -> objective discontinuity marker
FS = 32768.0

# REAL_DROP_DISCONTINUITY: purely a DATA-COMPLETENESS statement -- real source
# frames existed and were never transmitted. Threshold: >= 1 missing source
# frame (i.e. >= 20 ms). It says nothing about audibility.
TH_REAL_DROP_FRAMES = 1
TH_REAL_DROP_MS = FRAME_MS

# OBJECTIVE_CLICK_OR_STEP_RISK: an objective sample-domain jump across a drop
# boundary at or above TH_DISC. Judged on the MAXIMUM jump (strictest).
TH_CLICK_STEP = TH_DISC

SILK_MS = {0: 10, 1: 20, 2: 40, 3: 60}
HYB_MS = {12: 10, 13: 20}
CELT_MS = {16: 2.5, 17: 5, 18: 10, 19: 20}

FRAME_IDENTITY = "(response_id, generation_id, frame_seq)"
PERCEPTION_DISCLAIMER = (
    "REAL_DROP_DISCONTINUITY is a DATA-COMPLETENESS fact (source frames were "
    "never transmitted). OBJECTIVE_CLICK_OR_STEP_RISK is an OBJECTIVE "
    "sample-domain jump measurement against a stated threshold "
    "(%d int16 = %.2f%% of full scale). NEITHER is the human 'electrical / "
    "static' perception: that is a subjective, device- and codec-dependent "
    "auditory judgement which this offline analysis does NOT and CANNOT "
    "establish." % (TH_DISC, 100.0 * TH_DISC / FS)
)


def toc_info(b):
    """RFC 6716 §3.1 TOC byte -> (mode, bandwidth, frame_ms, frames, code)."""
    if not b:
        return None
    toc = b[0]
    cfg, nf, code = toc >> 3, (toc >> 2) & 1, toc & 3
    if cfg < 12:                                   # 0..11  SILK NB/MB/WB
        return ("SILK", ["NB", "MB", "WB"][cfg // 4], SILK_MS[cfg % 4], nf + 1, code)
    if cfg < 16:                                   # 12..15 HYBRID SWB/FB
        return ("HYBRID", "SWB" if cfg < 14 else "FB",
                HYB_MS[12 + (cfg % 2)], nf + 1, code)
    i = cfg - 16                                   # 16..31 CELT NB/WB/SWB/FB
    return ("CELT", ["NB", "WB", "SWB", "FB"][i // 4],
            CELT_MS[16 + (i % 4)], nf + 1, code)


def arr(b):
    a = array.array("h")
    a.frombytes(b)
    return a


def stats(a, name):
    n = len(a)
    if not n:
        return {"name": name, "samples": 0}
    peak = 0
    ssum = 0
    clip = 0
    zero = 0
    for v in a:
        av = -v if v < 0 else v
        if av > peak:
            peak = av
        if av >= 32767:
            clip += 1
        if v == 0:
            zero += 1
        ssum += v
    rms = math.sqrt(sum(float(v) * v for v in a) / n)
    return {
        "name": name, "samples": n, "duration_s": round(n / SR, 3),
        "peak_int16": peak,
        "peak_dbfs": round(20 * math.log10(max(peak, 1) / 32768.0), 2),
        "clipping_samples": clip, "clipping_ratio": round(clip / n, 8),
        "dc_mean": round(ssum / n, 3),
        "rms": round(rms, 1),
        "rms_dbfs": round(20 * math.log10(max(rms, 1) / 32768.0), 2),
        "zero_samples": zero, "zero_ratio": round(zero / n, 6),
    }


def pct(v, q):
    """Percentile of a list of numbers (q in [0,1]); None for an empty list."""
    if not v:
        return None
    s = sorted(v)
    if len(s) == 1:
        return float(s[0])
    k = q * (len(s) - 1)
    lo = int(math.floor(k))
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return float(s[lo] + (s[hi] - s[lo]) * frac)


def dist(v, name):
    """min / median / p95 / max distribution, with n and total."""
    if not v:
        return {"name": name, "n": 0, "min": None, "median": None,
                "p95": None, "max": None, "total": None}
    return {"name": name, "n": len(v), "min": min(v),
            "median": pct(v, 0.5), "p95": pct(v, 0.95), "max": max(v),
            "total": sum(v)}


# ---------------------------------------------------------------------------
# capture loading
# ---------------------------------------------------------------------------

def load_capture(d):
    """Load A (source PCM), the packet list B and the per-packet metadata."""
    A = arr(open("%s/qwen_pcm24.raw" % d, "rb").read())
    n_src = len(A) // N

    blob = open("%s/sent_opus.bin" % d, "rb").read()
    pkts, off = [], 0
    while off + 4 <= len(blob):
        ln = struct.unpack(">I", blob[off:off + 4])[0]
        off += 4
        pkts.append(blob[off:off + ln])
        off += ln
    meta = [json.loads(l) for l in open("%s/sent_opus.jsonl" % d) if l.strip()]
    if len(meta) != len(pkts):
        # Never silently mis-pair metadata with packets.
        raise SystemExit("capture corrupt: %d jsonl rows vs %d packets"
                         % (len(meta), len(pkts)))
    return A, pkts, meta, n_src


def source_offsets(gen_order, per_gen, n_src):
    """Generation-aware source offsets (R-1d mapping, kept intact).

    NOTE (honest limitation, unchanged): the jsonl only proves a LOWER bound on
    a generation's frames_encoded. The last generation of a capture that
    completed normally is anchored to the END of the source; earlier ones fall
    back to the cumulative lower bound. `mapping_mode` in the output says which
    rule was used so the result can never be over-trusted.
    """
    offset, mapping_mode = {}, "single_gen"
    if len(gen_order) == 1:
        offset[gen_order[0]] = 0
    elif gen_order:
        mapping_mode = "gen_aware_tail_anchored"
        offset[gen_order[0]] = 0
        last = gen_order[-1]
        rows = len(per_gen[last])
        last_contig = sorted(per_gen[last]) == list(range(1, rows + 1))
        if last_contig and n_src - rows >= 0:
            offset[last] = n_src - rows
        else:
            mapping_mode = "gen_aware_lower_bound"
            offset[last] = sum(max(per_gen[g]) for g in gen_order[:-1])
        for g in gen_order[1:-1]:
            prevs = gen_order[:gen_order.index(g)]
            offset[g] = min(sum(max(per_gen[p]) for p in prevs), offset[last])
    return offset, mapping_mode


# ---------------------------------------------------------------------------
# R-1e ITEM 3: drop-region analysis
# ---------------------------------------------------------------------------

def contiguous_runs(sorted_vals):
    """[1,2,3,7,8,12] -> [(1,3),(7,8),(12,12)] as inclusive (lo, hi) runs."""
    runs = []
    for v in sorted_vals:
        if runs and v == runs[-1][1] + 1:
            runs[-1][1] = v
        else:
            runs.append([v, v])
    return [tuple(r) for r in runs]


def analyze_drops(A, n_src, pkts, meta, src, decoded_first, decoded_last):
    """Every contiguous dropped region, with full boundary detail.

    `decoded_first[i]` / `decoded_last[i]` are the first and last decoded
    sample of the i-th decoded frame (each exactly N samples).
    """
    # Identity-keyed view of what was actually transmitted.
    delivered = {}                       # src_index -> identity triple
    for i, m in enumerate(meta):
        delivered.setdefault(src[i], (m.get("resp_id"), m.get("gen"),
                                      m.get("frame_seq")))
    delivered_sorted = sorted(delivered)
    missing = [i for i in range(n_src) if i not in delivered]
    runs = contiguous_runs(missing)

    # position of each delivered src index in send order (for the decoded step)
    send_pos = {}
    for pos, s in enumerate(src):
        send_pos.setdefault(s, pos)

    regions = []
    for lo, hi in runs:
        frames_dropped = hi - lo + 1
        before = lo - 1
        after = hi + 1
        src_before = A[before * N + (N - 1)] if before >= 0 else None
        src_after = A[after * N] if after < n_src else None
        step = (abs(src_after - src_before)
                if (src_before is not None and src_after is not None) else None)
        # decoded / playback domain: last sample before, first sample after
        dec_step = None
        dec_before = dec_after = None
        if before in send_pos and after in send_pos:
            dec_before = decoded_last[send_pos[before]]
            dec_after = decoded_first[send_pos[after]]
            dec_step = abs(dec_after - dec_before)
        regions.append({
            "source_frame_lo": lo,
            "source_frame_hi": hi,
            "frames_dropped": frames_dropped,
            "ms_missing": round(frames_dropped * FRAME_MS, 3),
            "identity_before": list(delivered[before]) if before in delivered else None,
            "identity_after": list(delivered[after]) if after in delivered else None,
            "source_sample_before_gap": src_before,
            "source_sample_after_gap": src_after,
            "source_step_int16": step,
            "source_step_pct_fs": (round(100.0 * step / FS, 4)
                                   if step is not None else None),
            "decoded_sample_before_gap": dec_before,
            "decoded_sample_after_gap": dec_after,
            "decoded_step_int16": dec_step,
            "decoded_step_pct_fs": (round(100.0 * dec_step / FS, 4)
                                    if dec_step is not None else None),
            "at_capture_start": before < 0,
            "at_capture_end": after >= n_src,
        })

    steps = [r["source_step_int16"] for r in regions
             if r["source_step_int16"] is not None]
    dec_steps = [r["decoded_step_int16"] for r in regions
                 if r["decoded_step_int16"] is not None]
    mss = [r["ms_missing"] for r in regions]
    fds = [r["frames_dropped"] for r in regions]

    # ---- the two required verdicts, with the threshold stated inline ------
    real_drop = [r for r in regions
                 if r["frames_dropped"] >= TH_REAL_DROP_FRAMES
                 and r["ms_missing"] >= TH_REAL_DROP_MS]
    real_drop_yes = len(real_drop) > 0
    max_step = max(steps) if steps else None
    click_yes = bool(steps) and max_step >= TH_CLICK_STEP
    max_dec = max(dec_steps) if dec_steps else None

    return {
        "frame_identity": FRAME_IDENTITY,
        "identity_never_frame_seq_alone": True,
        "source_frames_total": n_src,
        "source_frames_delivered": len(delivered_sorted),
        "source_frames_missing": len(missing),
        "drop_region_count": len(regions),
        "drop_regions": regions,
        "drop_step_distribution": dist(steps, "source_step_int16"),
        "drop_decoded_step_distribution": dist(dec_steps, "decoded_step_int16"),
        "drop_ms_distribution": dist(mss, "ms_missing"),
        "drop_frames_distribution": dist(fds, "frames_dropped"),
        "REAL_DROP_DISCONTINUITY": "YES" if real_drop_yes else "NO",
        "REAL_DROP_DISCONTINUITY_threshold": (
            ">= %d missing source frame(s) (>= %g ms) in at least one "
            "contiguous region" % (TH_REAL_DROP_FRAMES, TH_REAL_DROP_MS)),
        "REAL_DROP_DISCONTINUITY_regions": len(real_drop),
        "OBJECTIVE_CLICK_OR_STEP_RISK": "YES" if click_yes else "NO",
        "OBJECTIVE_CLICK_OR_STEP_RISK_threshold": (
            "max source-domain step across any drop boundary >= %d int16 "
            "(%.2f%% of full scale); judged on MAXIMUM (strictest)"
            % (TH_CLICK_STEP, 100.0 * TH_CLICK_STEP / FS)),
        "objective_max_source_step_int16": max_step,
        "objective_max_decoded_step_int16": max_dec,
        "objective_max_source_step_pct_fs": (round(100.0 * max_step / FS, 4)
                                             if max_step is not None else None),
        "perception_disclaimer": PERCEPTION_DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# main analysis
# ---------------------------------------------------------------------------

def analyze(d):
    A, pkts, meta, n_src = load_capture(d)

    dec = opuslib.Decoder(SR, 1)
    outs, derr = [], 0
    for p in pkts:
        try:
            outs.append(arr(dec.decode(p, N)))
        except Exception:  # noqa: BLE001
            derr += 1
            outs.append(array.array("h", [0] * N))
    C = array.array("h")
    for o in outs:
        C.extend(o)
    decoded_first = [o[0] for o in outs]
    decoded_last = [o[-1] for o in outs]

    tocs = {}
    for p in pkts:
        t = toc_info(p)
        if t:
            k = "mode=%s bw=%s frame_ms=%s frames=%s code=%s" % t
            tocs[k] = tocs.get(k, 0) + 1

    # ---- frame_seq report, keyed by generation --------------------------
    gens = {}
    for m in meta:
        gens.setdefault(m["gen"], []).append(m["frame_seq"])
    seq_rep = {}
    for g, s in gens.items():
        rng = set(range(min(s), max(s) + 1))
        miss = sorted(rng - set(s))
        seq_rep[str(g)] = {
            "n": len(s), "min": min(s), "max": max(s),
            "strictly_increasing": all(s[i] < s[i + 1] for i in range(len(s) - 1)),
            "duplicates": len(s) - len(set(s)),
            "missing_count": len(miss), "missing_sample": miss[:12],
        }

    ts = [m["t_send"] for m in meta if m.get("t_send")]
    d_ms = [round((ts[i] - ts[i - 1]) * 1000.0, 3) for i in range(1, len(ts))]

    # ---- R-1d: generation-aware frame_seq -> source-chunk mapping --------
    gen_order, per_gen = [], {}
    for m in meta:
        g = m.get("gen")
        if g not in per_gen:
            per_gen[g] = []
            gen_order.append(g)
        per_gen[g].append(m["frame_seq"])
    offset, mapping_mode = source_offsets(gen_order, per_gen, n_src)
    src = [offset[m.get("gen")] + m["frame_seq"] - 1 for m in meta]
    mapped_max = (max(src) + 1) if src else 0
    gen_map = {
        str(g): {"n_sent": len(per_gen[g]), "min_frame_seq": min(per_gen[g]),
                 "max_frame_seq": max(per_gen[g]), "source_offset": offset[g],
                 "resp_ids": sorted({m["resp_id"] for m in meta
                                     if m.get("gen") == g})}
        for g in gen_order
    }
    mapping_exact = (mapped_max == n_src)

    # ---- R-1e ITEM 3: drop boundaries + full region report ---------------
    drops = analyze_drops(A, n_src, pkts, meta, src, decoded_first, decoded_last)

    # delivered-stream boundary discontinuity (adjacent vs across a drop)
    adj, gap, gap_span = [], [], []
    for k in range(1, len(outs)):
        jump = abs(outs[k][0] - outs[k - 1][-1])
        if src[k] == src[k - 1] + 1:
            adj.append(jump)
        else:
            gap.append(jump)
            gap_span.append(src[k] - src[k - 1])

    def agg(v):
        if not v:
            return {"n": 0}
        return {"n": len(v), "mean": round(sum(v) / len(v), 1),
                "max": max(v), "min": min(v),
                "over_%d" % TH_DISC: sum(1 for x in v if x > TH_DISC),
                "over_ratio": round(sum(1 for x in v if x > TH_DISC) / len(v), 4)}

    return {
        "capture_dir": d,
        "frame_identity": FRAME_IDENTITY,
        "identity_never_frame_seq_alone": True,
        "A_qwen_raw_pcm24": stats(A, "A"),
        "C_decoded_from_sent_opus": stats(C, "C"),
        "source_frames": n_src,
        "delivered_frames": len(outs),
        "undelivered_frames": n_src - len(outs),
        "loss_ratio": round(1 - len(outs) / n_src, 4) if n_src else None,
        "packets_sent": len(pkts),
        "packet_bytes_min_max_mean": [
            min((len(p) for p in pkts), default=0),
            max((len(p) for p in pkts), default=0),
            round(sum(len(p) for p in pkts) / len(pkts), 1) if pkts else 0],
        "effective_downlink_kbit_s": round(
            (sum(len(p) for p in pkts) * 8 / 1000.0) / (len(pkts) * 0.02), 3) if pkts else 0,
        "opus_decode_errors": derr,
        "toc_distribution": tocs,
        "frame_seq_report": seq_rep,
        "gen_aware_mapping": True,
        "generation_mapping_mode": mapping_mode,
        "generation_mapping": gen_map,
        "source_index_coverage": {
            "mapped_source_frames": mapped_max, "source_frames": n_src,
            "exact": mapping_exact},
        "send_intervals_ms": {
            "n": len(d_ms),
            "min": min(d_ms) if d_ms else None,
            "p50": sorted(d_ms)[len(d_ms) // 2] if d_ms else None,
            "max": max(d_ms) if d_ms else None,
            "count_lt_15ms": sum(1 for x in d_ms if x < 15),
        },
        "boundary_adjacent_frames": agg(adj),
        "boundary_across_drop": agg(gap),
        "drop_gap_frame_span": {
            "n": len(gap_span),
            "median": sorted(gap_span)[len(gap_span) // 2] if gap_span else None,
            "max": max(gap_span) if gap_span else None,
            "mean": round(sum(gap_span) / len(gap_span), 2) if gap_span else None,
        },
        "drop_analysis": drops,
    }


# ---------------------------------------------------------------------------
# R-1e ITEM 4: injected-drop detection self-test
# ---------------------------------------------------------------------------

def inject_drop(src_dir, dst_dir, first, count):
    """Remove `count` packets starting at send-order index `first`.

    Writes a doctored copy of the capture: `qwen_pcm24.raw` is copied VERBATIM
    (the source is the ground truth and must not change), while `sent_opus.bin`
    and `sent_opus.jsonl` are both shortened at the same positions so they stay
    index-aligned. Returns metadata describing exactly what was removed.
    """
    os.makedirs(dst_dir, exist_ok=True)
    shutil.copyfile(os.path.join(src_dir, "qwen_pcm24.raw"),
                    os.path.join(dst_dir, "qwen_pcm24.raw"))

    blob = open(os.path.join(src_dir, "sent_opus.bin"), "rb").read()
    rows = [json.loads(l) for l in
            open(os.path.join(src_dir, "sent_opus.jsonl")) if l.strip()]

    # locate packet boundaries
    offs, off = [], 0
    while off + 4 <= len(blob):
        ln = struct.unpack(">I", blob[off:off + 4])[0]
        off += 4
        offs.append((off, ln))
        off += ln
    n = len(offs)
    first = max(0, min(int(first), n - 1))
    count = max(1, min(int(count), n - first))

    keep = [i for i in range(n) if not (first <= i < first + count)]
    with open(os.path.join(dst_dir, "sent_opus.bin"), "wb") as f:
        for i in keep:
            o, ln = offs[i]
            p = blob[o:o + ln]
            f.write(struct.pack(">I", ln))
            f.write(p)
    with open(os.path.join(dst_dir, "sent_opus.jsonl"), "w") as f:
        for i in keep:
            f.write(json.dumps(rows[i]) + "\n")

    removed = [rows[i] for i in range(first, first + count)]
    return {"packets_total": n, "removed_send_order_index_range": [first,
                                                                  first + count - 1],
            "removed_count": count,
            "removed_identities": [[r.get("resp_id"), r.get("gen"),
                                    r.get("frame_seq")] for r in removed],
            "removed_frame_seq_min": min(r.get("frame_seq") for r in removed),
            "removed_frame_seq_max": max(r.get("frame_seq") for r in removed)}


def expected_from_source(src_dir, first, count):
    """Ground truth computed DIRECTLY from the source PCM, independently of
    the analyzer's drop logic: the removed packets' source frames are simply
    absent from the sent list, so the gap spans exactly those frame indices."""
    A = arr(open(os.path.join(src_dir, "qwen_pcm24.raw"), "rb").read())
    n_src = len(A) // N
    rows = [json.loads(l) for l in
            open(os.path.join(src_dir, "sent_opus.jsonl")) if l.strip()]
    gen_order, per_gen = [], {}
    for m in rows:
        g = m.get("gen")
        if g not in per_gen:
            per_gen[g] = []
            gen_order.append(g)
        per_gen[g].append(m["frame_seq"])
    off, _mode = source_offsets(gen_order, per_gen, n_src)
    src_idx = [off[m.get("gen")] + m["frame_seq"] - 1 for m in rows]
    lo = src_idx[first]
    hi = src_idx[first + count - 1]
    before, after = lo - 1, hi + 1
    sb = A[before * N + (N - 1)] if before >= 0 else None
    sa = A[after * N] if after < n_src else None
    return {
        "expected_source_frame_lo": lo,
        "expected_source_frame_hi": hi,
        "expected_frames_dropped": count,
        "expected_ms_missing": count * FRAME_MS,
        "expected_source_sample_before_gap": sb,
        "expected_source_sample_after_gap": sa,
        "expected_source_step_int16": (abs(sa - sb)
                                        if sb is not None and sa is not None
                                        else None),
    }


def self_test_inject(src_dir, first, count, workdir=None):
    """Inject a known contiguous gap and prove the analyzer reports it."""
    tmp = workdir or tempfile.mkdtemp(prefix="r1e_inject_")
    dst = os.path.join(tmp, "capture")
    inj = inject_drop(src_dir, dst, first, count)
    exp = expected_from_source(src_dir, first, count)
    res = analyze(dst)

    regs = res["drop_analysis"]["drop_regions"]
    # The injected block must appear as EXACTLY ONE contiguous region.
    match = [r for r in regs
             if r["source_frame_lo"] == exp["expected_source_frame_lo"]
             and r["source_frame_hi"] == exp["expected_source_frame_hi"]]
    r0 = match[0] if len(match) == 1 else None

    checks = {
        "exactly_one_matching_region": len(match) == 1,
        "frames_dropped_matches": (r0 is not None
                                   and r0["frames_dropped"]
                                   == exp["expected_frames_dropped"]),
        "ms_missing_matches": (r0 is not None
                               and abs(r0["ms_missing"]
                                       - exp["expected_ms_missing"]) < 1e-6),
        "source_frame_lo_matches": (r0 is not None
                                    and r0["source_frame_lo"]
                                    == exp["expected_source_frame_lo"]),
        "source_frame_hi_matches": (r0 is not None
                                    and r0["source_frame_hi"]
                                    == exp["expected_source_frame_hi"]),
        "source_step_matches": (r0 is not None
                                and r0["source_step_int16"]
                                == exp["expected_source_step_int16"]),
        "sample_before_matches": (r0 is not None
                                  and r0["source_sample_before_gap"]
                                  == exp["expected_source_sample_before_gap"]),
        "sample_after_matches": (r0 is not None
                                 and r0["source_sample_after_gap"]
                                 == exp["expected_source_sample_after_gap"]),
        "detected_as_real_drop": res["drop_analysis"]["REAL_DROP_DISCONTINUITY"] == "YES",
    }
    ok = all(checks.values())
    return {
        "INJECTED_DROP_DETECTION": "PASS" if ok else "FAIL",
        "method": (
            "Copied the capture verbatim, then removed a KNOWN contiguous block "
            "of %d packets at send-order indices [%d, %d] from BOTH "
            "sent_opus.bin and sent_opus.jsonl (same positions, so the two "
            "stay index-aligned). qwen_pcm24.raw was copied UNCHANGED, so the "
            "source remains the ground truth and the removed frames are now "
            "present in A but absent from B -- exactly the shape a real "
            "queue drop produces. Ground truth is computed independently from "
            "the raw source PCM, then compared field-by-field with the "
            "analyzer's own drop report." % (count, first, first + count - 1)),
        "source_capture_dir": src_dir,
        "doctored_capture_dir": dst,
        "workdir": tmp,
        "injection": inj,
        "ground_truth": exp,
        "checks": checks,
        "analyzer_reported_region": r0,
        "analyzer_drop_region_count": res["drop_analysis"]["drop_region_count"],
        "analyzer_REAL_DROP_DISCONTINUITY":
            res["drop_analysis"]["REAL_DROP_DISCONTINUITY"],
        "analyzer_OBJECTIVE_CLICK_OR_STEP_RISK":
            res["drop_analysis"]["OBJECTIVE_CLICK_OR_STEP_RISK"],
        "analyzer_drop_step_distribution":
            res["drop_analysis"]["drop_step_distribution"],
        "analyzer_drop_ms_distribution":
            res["drop_analysis"]["drop_ms_distribution"],
        # honesty: the decoded-domain step is NOT predicted a priori, because
        # the Opus decoder carries state across the removed packets. It is
        # reported as measured, and is deliberately NOT part of the PASS test.
        "decoded_step_is_measured_not_predicted": True,
    }


def main():
    ap_kwargs = dict(description=__doc__)
    import argparse
    ap = argparse.ArgumentParser(**ap_kwargs)
    ap.add_argument("--diag-dir", default=D)
    ap.add_argument("--self-test-inject", action="store_true")
    ap.add_argument("--inject-first", type=int, default=40)
    ap.add_argument("--inject-count", type=int, default=25)
    ap.add_argument("--workdir", default=None)
    args = ap.parse_args()

    if args.self_test_inject:
        out = self_test_inject(args.diag_dir, args.inject_first,
                               args.inject_count, args.workdir)
        print(json.dumps(out, indent=1))
        return 0 if out["INJECTED_DROP_DETECTION"] == "PASS" else 1
    print(json.dumps(analyze(args.diag_dir), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())