#!/usr/bin/env python
"""RED-I round-3: probe NEW repair code paths for response/log leakage.

Exercises (against a LOCAL mock gateway on 127.0.0.1:29312):
  * policy section type-confusion (was 500)         -> expect 400 policy_invalid, no value echo
  * deep nesting (was RecursionError 500)           -> expect 400 policy_invalid
  * boundary-violation on a secret-shaped memory value -> expect 400, no value echo
  * PersistError (read-only data dir)               -> expect 500 persist_failed, no path echo
Then reports which sentinel strings appear in any response body (they must not).

Never prints a real secret. The sentinel here is a synthetic fake string we control.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, "<project-root>")
from modules.memory.store import MemoryStore  # noqa: E402

BASE = "http://127.0.0.1:29312"
TOKEN_FILE = "/tmp/adv/red_i3/token"
DATA = "/tmp/adv/red_i3/data"
SENTINEL = "sk-TESTFAKESECRET0123456789ABCDEF"   # synthetic, not a real credential
SENTINEL2 = "ghp_TESTFAKETOKEN0123456789abcdef"  # synthetic

TOK = open(TOKEN_FILE).read().strip()
AUTH = {"Authorization": "Bearer " + TOK}
hits = []


def call(method, path, body=None, raw=None, headers=None, timeout=15):
    h = dict(AUTH)
    data = None
    if raw is not None:
        data = raw if isinstance(raw, bytes) else raw.encode()
    elif body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return -1, repr(e)


def check(label, status, body, expectations):
    leak = [s for s in (SENTINEL, SENTINEL2, "/tmp/adv", "/app/data", "data/memory.json",
                        "Traceback", 'File "') if s in body]
    print("  [%s] %-42s -> %s" % (status, label, body[:180]))
    if leak:
        hits.append((label, leak, body[:200]))
    ok = status in expectations
    print("        expected %s -> %s" % (expectations, "OK" if ok else "MISMATCH"))


print("=== new-path probes ===")
st, b = call("POST", "/admin/policy/preview", body={"policy": {"persona": "x"}})
check("policy section type-confusion", st, b, (400,))

deep = {"policy": {"persona": {}}, "confirm": True}
cur = deep["policy"]["persona"]
for _ in range(4000):
    cur["n"] = {}
    cur = cur["n"]
st, b = call("POST", "/admin/policy/apply", body=deep)
check("deep nesting apply", st, b, (400,))

# secret-shaped memory value via admin edit (need an existing item first)
ms = MemoryStore(DATA + "/memory.json")
it = ms.save("profile_fact", "favourite_colour", "blue")
print("  seeded memory item id:", it.id)
st, b = call("POST", "/admin/memory/edit", body={"id": it.id, "value": SENTINEL})
check("memory boundary (secret-shaped value)", st, b, (400,))

# PersistError: make the data dir read-only, then attempt a durable write
os.chmod(DATA, 0o500)
try:
    st, b = call("POST", "/admin/knowledge/dataset/create", body={"name": "red_i3_ds"})
    check("PersistError (read-only data dir)", st, b, (400, 500, 503))
finally:
    os.chmod(DATA, 0o700)
time.sleep(0.3)

print()
print("=== sentinel/path echo in any response body? ===")
if hits:
    for label, leak, body in hits:
        print("LEAK", label, leak, "::", body)
else:
    print("NONE — no sentinel, path, or traceback in any response body")

print()
print("=== store .lock files ===")
for name in sorted(os.listdir(DATA)):
    p = os.path.join(DATA, name)
    stt = os.stat(p)
    print("  %-24s mode=%s size=%s empty=%s" % (
        name, oct(stt.st_mode & 0o777), stt.st_size, stt.st_size == 0))
