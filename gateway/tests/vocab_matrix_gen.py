"""Generate the VOCAB matrix turn table for the single real-Qwen session.

Produces, for every matrix turn, the EXACT `instructions` each phase would send:

* phase "pre_audit" — rendered by the OLD module (`git show HEAD:modules/intent/
  behavior.py`, i.e. before the vocabulary audit fixes) — the instruction block
  the product would have sent at the time of the human failure;
* phase "post_fix" — rendered by the CURRENT working-tree module (VOCABULARY
  ACCURACY POLICY + fixed routing).

Usage (from gateway/, venv):  python tests/vocab_matrix_gen.py /tmp/vocab_turns.json
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_GATEWAY = os.path.dirname(_HERE)
_REPO = os.path.dirname(_GATEWAY)
for p in (_GATEWAY, _REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

# matrix: id, question, accepted canonical answers
MATRIX = [
    ("m01", "街道用英语怎么说？", ["street"]),
    ("m02", "酒店用英语怎么说？", ["hotel"]),
    ("m03", "房间怎么说？", ["room"]),
    ("m04", "桌子用英语怎么说？", ["table"]),
    ("m05", "窗户用英语怎么说？", ["window"]),
    ("m06", "机场用英语怎么说？", ["airport"]),
    ("m07", "离开用英语怎么说？", ["leave"]),
    ("m08", "居住用英语怎么说？", ["live"]),
    ("m09", "到达用英语怎么说？", ["arrive"]),
    ("m10", "预订用英语怎么说？", ["book", "reserve", "booking", "reservation"]),
    ("m11", "船用英语怎么说？", ["ship"]),
    ("m12", "羊用英语怎么说？", ["sheep"]),
    ("m13", "住宿用英语怎么说？", ["accommodation", "lodging"]),
    ("m14", "前台用英语怎么说？", ["reception", "front desk", "front desk"]),
    ("m15", "行李用英语怎么说？", ["luggage", "baggage"]),
    ("m16", "street 怎么拼？", ["street"]),
    ("m17", "hotel 怎么拼？", ["hotel"]),
    ("m18", "accommodation 怎么拼？", ["accommodation"]),
    ("m19", "街道是什么？", ["street"]),
    ("m20", "英文里的街道怎么说？", ["street"]),
    ("m21", "街道的英文是什么？", ["street"]),
    ("m22", "street 是什么意思？", ["street"]),
    ("m23", "accommodation 是什么意思？", ["accommodation"]),
    ("m24", "在酒店预订房间用英语怎么说？",
     ["book", "reserve", "booking", "reservation"]),
    ("m25", "hotel 是什么意思？", ["hotel"]),
]

# baseline (pre-audit) subset — the classes the human complained about
BASELINE_IDS = ["m01", "m11", "m12", "m13", "m16", "m19", "m25", "m07"]

SPELLING_IDS = {"m16", "m17", "m18"}


def load_old_module():
    src = subprocess.run(
        ["git", "show", "HEAD:modules/intent/behavior.py"],
        cwd=_REPO, capture_output=True, text=True, check=True).stdout
    tmp = tempfile.NamedTemporaryFile("w", suffix="_old_behavior.py",
                                      delete=False)
    tmp.write(src)
    tmp.close()
    spec = importlib.util.spec_from_file_location("old_behavior", tmp.name)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["old_behavior"] = mod          # dataclasses need the registration
    spec.loader.exec_module(mod)
    return mod, tmp.name


def render(mod, question):
    st = mod.BehaviorState()
    d = mod.route(question, st)
    return mod.render_instructions(st, d), d.temporary


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/vocab_turns.json"
    old, tmp_name = load_old_module()
    from modules.intent import behavior as new

    turns = []
    for mid, question, accepted in MATRIX:
        old_ins, old_temp = render(old, question)
        new_ins, new_temp = render(new, question)
        base = {"id": mid, "question": question, "accepted": accepted,
                "spelling": mid in SPELLING_IDS}
        if mid in BASELINE_IDS:
            t = dict(base)
            t.update({"phase": "pre_audit", "instruction": old_ins,
                      "route_temp": old_temp, "instruction_len": len(old_ins)})
            turns.append(t)
        t = dict(base)
        t.update({"phase": "post_fix", "instruction": new_ins,
                  "route_temp": new_temp, "instruction_len": len(new_ins)})
        turns.append(t)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"turns": turns}, f, ensure_ascii=False, indent=1)
    os.unlink(tmp_name)
    print("turns=%d (pre_audit=%d, post_fix=%d) -> %s" % (
        len(turns), len(BASELINE_IDS), len(MATRIX), out_path))
    print("%-4s %-10s %-30s %-14s %s" % ("id", "phase", "question", "old_route",
                                         "new_route"))
    seen = {}
    for t in turns:
        if t["phase"] == "post_fix":
            old_t = seen.get(t["id"], "?")
            print("%-4s %-10s %-30s %-14s %s" % (
                t["id"], "both", t["question"][:28], old_t, t["route_temp"]))
        else:
            seen[t["id"]] = t["route_temp"]


if __name__ == "__main__":
    main()