"""RED-D worker: unsynchronised MemoryStore writer (gateway/admin two-writer topology).

Usage: python _memory_mp_worker.py <memory_path> <n> <tag> <go_file>
Waits for the barrier, then saves <n> distinct profile_fact items.
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

from modules.memory.store import MemoryStore  # noqa: E402


def main():
    path, n, tag, go = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
    if go:
        deadline = time.time() + 20
        while not os.path.exists(go) and time.time() < deadline:
            time.sleep(0.0005)
    ms = MemoryStore(path).load()
    ok = 0
    for i in range(n):
        try:
            ms.save("profile_fact", "k_%s_%d" % (tag, i), "v_%s_%d" % (tag, i))
            ok += 1
        except Exception:  # noqa: BLE001
            pass
    print(json.dumps({"tag": tag, "ok": ok}))


if __name__ == "__main__":
    main()
