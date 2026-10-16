"""RED-D worker: deliberately-unsynchronised policy writer for the cross-process test.

Usage: python _policy_mp_worker.py <policy_path> <n> <tag> <go_file>
Waits for <go_file> to appear (start barrier), then applies <n> distinct policies.
Prints a JSON summary. Loopback/filesystem only; no Qwen, no product writes.
"""
import json
import os
import sys
import time
from pathlib import Path


def _find_repo(start):
    for p in (start, *start.parents):
        if (p / "modules").is_dir():
            return p
    return None


_REPO = _find_repo(Path(__file__).resolve())
if _REPO is not None and str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from modules.policy.persona import PolicyStore  # noqa: E402


def main():
    path, n, tag, go = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
    if go:
        deadline = time.time() + 20
        while not os.path.exists(go) and time.time() < deadline:
            time.sleep(0.0005)
    ps = PolicyStore(path).load()
    ok = 0
    versions = []
    for i in range(n):
        try:
            out = ps.apply({"persona": {"tone": "%s-%d" % (tag, i)}}, actor=tag)
            versions.append(out["version"])
            ok += 1
        except Exception as e:  # noqa: BLE001
            versions.append("E:%s" % type(e).__name__)
    print(json.dumps({"tag": tag, "ok": ok, "versions": versions}))


if __name__ == "__main__":
    main()
