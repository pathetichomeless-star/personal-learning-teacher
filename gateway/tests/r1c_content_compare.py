#!/usr/bin/env python3
"""R-1c CASE-D adjudicator: is "response N+1" a *content repetition* of the
invalidated "response N", as opposed to a transport replay of N's audio?

Pure stdlib. No network, no cloud, no side effects.

Background
----------
In the R-1b human test the user spoke over the assistant, the old audio stopped
immediately, Qwen answered the interruption -- and then the OLD response
"later resumed playing". Every bridge-side transport explanation has been
disproven under deterministic mock instrumentation (deploy-log #69: 0 stale
frames, 0 post-invalidation sends, clean flush). The residual hypothesis is
CASE D: the *content* of response N was regenerated/continued by a later
response (N+1), which is perceptually indistinguishable from stale audio but is
text repetition, not transport replay.

This script computes an objective TEXT-OVERLAP metric over transcripts so that,
once the gated transcript-capture hook is in place, CASE D can be concluded or
refuted from data rather than from listening.

The canonical comparison is:

    response_N.output_transcript  (assistant text of the cancelled response)
        vs
    response_N+1.output_transcript (assistant text of the next response)

NOT against the input transcript (that is the user's own speech / ASR text and
is trivially related). See FALSE_CONCLUSION_TRAPS in the design report.

Verdicts: NONE / LOW / MATERIAL. `MATERIAL` is the only level that, together
with transport prerequisites (a) and (b), supports CASE D.

Usage
-----
    python r1c_content_compare.py --selftest
    python r1c_content_compare.py --ref-file resp_N.txt --new-file resp_N1.txt \
        [--input-file user_N.txt] [--anchors park,picnic,football,family,lake,weekend]
"""

import argparse
import json
import re
import sys
from collections import Counter

# --------------------------------------------------------------------------
# Lexicons
# --------------------------------------------------------------------------

# Function words: articles, pronouns, prepositions, auxiliaries, conjunctions,
# negations, contractions, discourse markers. Removing these prevents the
# metric from scoring "I / you / the / to" as overlap.
STOP = {
    "a", "an", "the", "and", "or", "but", "nor", "so", "yet", "for",
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us",
    "them", "my", "your", "his", "its", "our", "their", "mine", "yours",
    "this", "that", "these", "those", "there", "here",
    "is", "am", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "doing", "done",
    "have", "has", "had", "having",
    "will", "would", "shall", "should", "can", "could", "may", "might",
    "must", "ought", "to", "of", "in", "on", "at", "by", "with", "from",
    "into", "onto", "about", "as", "than", "if", "because", "while", "when",
    "where", "which", "who", "whom", "whose", "what", "why", "how",
    "not", "no", "nor", "dont", "didnt", "doesnt", "isnt", "arent", "wasnt",
    "werent", "cant", "cannot", "couldnt", "wont", "wouldnt", "shouldnt",
    "ill", "im", "ive", "id", "youre", "youve", "youll", "hes", "shes",
    "its", "were", "weve", "theyre", "theyve", "thats", "theres", "lets",
    "s", "t", "re", "ve", "ll", "d", "m",
}

# High-frequency conversational *content* words (verbs / fillers / generic
# nouns). They carry almost no topical signal and are exactly what a legitimate
# short topic-change answer shares with any previous turn ("sure, let's talk
# about something else"). Excluded from the DISTINCTIVE set so that boilerplate
# is never mistaken for repetition.
COMMON = {
    "like", "want", "wanted", "would", "know", "knew", "think", "thought",
    "talk", "talking", "speak", "tell", "telling", "say", "saying", "said",
    "well", "good", "great", "nice", "really", "very", "too", "also",
    "something", "anything", "nothing", "everything", "thing", "things",
    "else", "again", "still", "right", "sure", "okay", "ok", "yes", "yeah",
    "nope", "maybe", "perhaps", "please", "thanks", "thank", "hello", "hi",
    "hey", "let", "discuss", "prefer", "need", "help", "look", "see", "seen",
    "go", "going", "went", "gone", "get", "got", "getting", "come", "came",
    "coming", "make", "made", "making", "take", "took", "taking", "give",
    "gave", "put", "use", "using", "used", "just", "more", "most", "much",
    "many", "one", "two", "three", "first", "next", "last", "new", "old",
    "way", "kind", "sort", "lot", "bit", "stuff", "time", "times", "today",
    "now", "then", "start", "started", "stop", "stopped", "hold", "wait",
    "sound", "sounds", "sounded", "hear", "heard", "listen", "listening",
    "english", "practice", "question", "answer", "sentence", "word", "words",
    "talk", "change", "learn", "learning", "study", "studying",
    "enjoy", "enjoyed", "enjoying", "mind", "care", "mean", "guess",
    "suppose", "imagine", "remember", "forget", "believe", "feel", "feeling",
    "seem", "looking", "favorite", "favourite", "hobby", "hobbies",
}

# Scenario anchors: distinctive, topic-specific words from the R-1c fixture
# (the park/picnic story). A correct topic-change answer has no reason to use
# these; their reuse is strong evidence that N+1 is still replaying N's content.
DEFAULT_ANCHORS = [
    "park", "picnic", "football", "family", "lake", "weekend", "weekends",
    "children", "child", "kids", "hours", "hour", "afternoon", "saturday",
    "sunday", "played", "playing", "relax", "outside",
]


def normalize(text):
    """Lowercase, drop apostrophes, keep [a-z0-9 ] -> token list.

    Contractions are split into their raw parts ("let's" -> "lets" after the
    apostrophe is removed) so they match our lexicon; punctuation never
    attaches to a token.
    """
    if not text:
        return []
    t = text.lower().replace("\u2019", "'").replace("\u2018", "'")
    t = re.sub(r"[^a-z0-9\s']", " ", t)
    t = t.replace("'", "")
    return [w for w in t.split() if w]


def content_tokens(toks):
    return [w for w in toks if w not in STOP]


def distinctive_tokens(toks):
    return [w for w in toks if w not in STOP and w not in COMMON]


def _counter(a):
    return Counter(a)


def containment(a, b):
    """Fraction of b's tokens (multiset) that also occur in a.

    Denominator = |b| so this measures "how much of the NEW text is OLD
    content" -- the quantity of interest for repetition. Guarded elsewhere by a
    minimum-|b| requirement because small b inflates this ratio.
    """
    if not b:
        return 0.0
    ca, cb = _counter(a), _counter(b)
    inter = sum(min(ca[k], v) for k, v in cb.items())
    return inter / float(len(b))


def jaccard(a, b):
    """Multiset Jaccard |a n b| / |a u b|."""
    if not a and not b:
        return 0.0
    ca, cb = _counter(a), _counter(b)
    inter = sum(min(ca[k], v) for k, v in cb.items())
    union = sum(max(ca[k], cb.get(k, 0)) for k in set(ca) | set(cb))
    return inter / float(union) if union else 0.0


def lcs_run(a, b):
    """Longest common CONTIGUOUS token subsequence (token-level LCS substring).

    Returns (length, run_tokens). O(len(a)*len(b)) DP, stdlib only.
    """
    if not a or not b:
        return 0, []
    prev = [0] * (len(b) + 1)
    best = 0
    best_end_b = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
                    best_end_b = j
        prev = cur
    run = b[best_end_b - best:best_end_b] if best else []
    return best, run


def anchor_hits(text_tokens, anchors):
    """Anchor words present in `text_tokens`, plural-insensitive (simple -s).

    Deduplicated by stem so {"weekend","weekends"} counts once. Returns the
    canonical anchor spellings found in the text.
    """
    tset = {_stem(w) for w in text_tokens}
    seen = {}
    for a in anchors:
        s = _stem(a)
        if s in tset and s not in seen:
            seen[s] = a
    return sorted(seen.values())


def _stem(w):
    return w[:-1] if (len(w) > 3 and w.endswith("s")) else w


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------

# Thresholds. Justified in the design report; validated in --selftest.
T = {
    "lcs_all_material": 4,       # verbatim run >= 4 tokens (+ >=1 distinctive)
    "lcs_all_low": 3,
    "contain_dist_material": 0.40,
    "contain_dist_low": 0.20,
    "jaccard_dist_material": 0.25,
    "min_dist_tokens_for_ratio": 3,   # guards short-answer ratio inflation
    "anchor_material": 3,             # >=3 distinct anchors reused
    "anchor_two_material_min_dist": 4,  # 2 anchors + >=4 distinctive tokens
    "anchor_low": 1,
}


def classify(ref_text, new_text, anchors=None, verbose=False):
    """Return a dict with the raw metrics and a NONE/LOW/MATERIAL verdict."""
    anchors = list(anchors if anchors is not None else DEFAULT_ANCHORS)
    ref_all = normalize(ref_text)
    new_all = normalize(new_text)
    ref_c, new_c = content_tokens(ref_all), content_tokens(new_all)
    ref_d, new_d = distinctive_tokens(ref_all), distinctive_tokens(new_all)

    lcs_len, lcs_toks = lcs_run(ref_all, new_all)
    lcs_dist = [w for w in lcs_toks if w in set(ref_d) | set(new_d)]
    a_hits = anchor_hits(new_all, anchors)          # anchors in the NEW text
    ref_stems = {_stem(w) for w in ref_all}
    a_hits = [a for a in a_hits if _stem(a) in ref_stems]  # also present in ref

    contain_d = containment(ref_d, new_d)
    jac_d = jaccard(ref_d, new_d)
    contain_c = containment(ref_c, new_c)
    jac_c = jaccard(ref_c, new_c)

    n_d = len(new_d)
    reasons = []
    verdict = "NONE"

    def material(r):
        reasons.append(r)

    # (V) verbatim run: >=4 contiguous tokens AND at least one distinctive token
    # inside the run (kills templated function-word stems like
    # "what would you like to talk about").
    if lcs_len >= T["lcs_all_material"] and len(lcs_dist) >= 1:
        material("V1 verbatim_run=%d tokens (%s)" % (lcs_len, " ".join(lcs_toks)))
    if n_d >= T["min_dist_tokens_for_ratio"] and contain_d >= T["contain_dist_material"]:
        material("V2 distinctive_containment=%.3f (n_dist=%d)" % (contain_d, n_d))
    if n_d >= T["min_dist_tokens_for_ratio"] and jac_d >= T["jaccard_dist_material"]:
        material("V3 distinctive_jaccard=%.3f (n_dist=%d)" % (jac_d, n_d))
    # (T) topic anchors reused
    if len(a_hits) >= T["anchor_material"]:
        material("T1 anchors_reused=%d %s" % (len(a_hits), a_hits))
    if (len(a_hits) == 2 and n_d >= T["anchor_two_material_min_dist"]):
        material("T2 two_anchors=%s + n_dist=%d" % (a_hits, n_d))

    if reasons:
        verdict = "MATERIAL"
    else:
        low = []
        if lcs_len == T["lcs_all_low"]:
            low.append("L1 verbatim_run=3")
        if n_d >= T["min_dist_tokens_for_ratio"] and contain_d >= T["contain_dist_low"]:
            low.append("L2 distinctive_containment=%.3f" % contain_d)
        if len(a_hits) >= T["anchor_low"]:
            low.append("L3 anchors_reused=%d %s" % (len(a_hits), a_hits))
        if low:
            verdict = "LOW"
            reasons = low

    out = {
        "verdict": verdict,
        "reasons": reasons,
        "metrics": {
            "n_tokens_ref": len(ref_all), "n_tokens_new": len(new_all),
            "n_dist_ref": len(ref_d), "n_dist_new": n_d,
            "lcs_tokens_all": lcs_len, "lcs_run": " ".join(lcs_toks),
            "lcs_run_distinctive_hits": len(lcs_dist),
            "containment_distinctive": round(contain_d, 4),
            "jaccard_distinctive": round(jac_d, 4),
            "containment_content": round(contain_c, 4),
            "jaccard_content": round(jac_c, 4),
            "anchors_reused": a_hits,
            "distinctive_new": sorted(set(new_d)),
        },
    }
    if verbose:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    return out


# --------------------------------------------------------------------------
# Self-test / validation on synthetic pairs
# --------------------------------------------------------------------------

SELFTEST_CASES = [
    ("identical",
     "You had a lovely weekend with your family at the park. You had a picnic near the lake, and the children played football.",
     "You had a lovely weekend with your family at the park. You had a picnic near the lake, and the children played football.",
     "MATERIAL"),
    ("verbatim_repeat_truncated",
     "You had a lovely weekend with your family at the park. You had a picnic near the lake, and the children played football for almost two hours.",
     "You had a lovely weekend with your family at the park. You had a picnic near the lake.",
     "MATERIAL"),
    ("narrative_continuation",
     "You had a lovely weekend with your family at the park. You had a picnic near the lake.",
     "Your family must have had a great time by the lake, and playing football for two hours sounds tiring.",
     "MATERIAL"),
    ("correct_topic_change",
     "You had a lovely weekend with your family at the park. You had a picnic near the lake, and the children played football for almost two hours.",
     "Sure, let's talk about something else. What would you like to talk about instead?",
     "NONE"),
    ("templated_stem_boilerplate",
     "That sounds like a lot of fun. What did you enjoy most about your weekend?",
     "What did you enjoy most about the trip?",
     "NONE"),
    ("one_anchor_ack",
     "You had a lovely weekend with your family at the park. You had a picnic near the lake.",
     "Okay, we can leave the park topic for now. What would you like to talk about?",
     "LOW"),
    ("topic_word_only_unrelated",
     "You had a lovely weekend with your family at the park. You had a picnic near the lake.",
     "I love weekends because I can relax at home.",
     "LOW"),
    ("unrelated",
     "You had a lovely weekend with your family at the park. You had a picnic near the lake.",
     "Sure. Do you prefer reading books or watching movies in your free time?",
     "NONE"),
    ("short_two_anchor",
     "You had a lovely weekend with your family at the park. You had a picnic near the lake.",
     "That picnic by the lake sounds nice.",
     "LOW"),
    ("two_anchors_long",
     "You had a lovely weekend with your family at the park. You had a picnic near the lake.",
     "I hope your family enjoyed the picnic by the lake and the long drive home afterwards.",
     "MATERIAL"),
]


def selftest():
    print("=" * 78)
    print("R-1c content-compare self-test (synthetic pairs)")
    print("=" * 78)
    ok = True
    for name, ref, new, expect in SELFTEST_CASES:
        r = classify(ref, new)
        got = r["verdict"]
        flag = "ok " if got == expect else "FAIL"
        if got != expect:
            ok = False
        m = r["metrics"]
        print("%-4s %-28s -> %-8s (expect %-8s) lcs=%-2d run='%s' "
              "cont_d=%.2f jac_d=%.2f anchors=%d n_dist=%d"
              % (flag, name, got, expect, m["lcs_tokens_all"], m["lcs_run"],
                 m["containment_distinctive"], m["jaccard_distinctive"],
                 len(m["anchors_reused"]), m["n_dist_new"]))
        if got != expect:
            print("      reasons=%s" % (r["reasons"],))
    print("-" * 78)
    print("SELFTEST_RESULT =", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="R-1c CASE-D content comparator")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--ref-file")
    ap.add_argument("--new-file")
    ap.add_argument("--input-file", help="optional user input transcript (N)")
    ap.add_argument("--anchors", help="comma-separated anchor override")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest or not (args.ref_file and args.new_file):
        return selftest()

    with open(args.ref_file, "r", encoding="utf-8") as f:
        ref = f.read()
    with open(args.new_file, "r", encoding="utf-8") as f:
        new = f.read()
    anchors = (args.anchors.split(",") if args.anchors else None)
    res = classify(ref, new, anchors=anchors)
    if args.input_file:
        with open(args.input_file, "r", encoding="utf-8") as f:
            inp = f.read()
        # Secondary, NON-decisive: does the answer echo the USER's story words?
        res["input_echo"] = classify(inp, new, anchors=anchors)["metrics"]
    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print("VERDICT = %s" % res["verdict"])
        print("reasons = %s" % res["reasons"])
        print(json.dumps(res["metrics"], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
