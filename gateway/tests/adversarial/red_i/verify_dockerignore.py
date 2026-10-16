#!/usr/bin/env python
"""RED-I round-3: verify the sidecar build context excludes the real-Qwen drivers.

docker/podman are not available on this host, so we emulate Docker's .dockerignore
matching for the exact staging layout used by deploy/product-sidecar/Dockerfile
(the NAS staging dir mirrors: <context>/{app,config,modules,tests,admin-ui} where
tests == the repo's gateway/tests).  Docker matches a pattern against the context-
relative path; our patterns are literal relative paths, so membership == match.

Evidence: for each forbidden path, is it excluded?  And sanity-check that an
expected-kept file is NOT excluded.
"""
from __future__ import annotations

import fnmatch
from pathlib import Path

REPO = Path("<project-root>")
DOCKERIGNORE = REPO / "deploy" / "product-sidecar" / ".dockerignore"

patterns = [ln.strip() for ln in DOCKERIGNORE.read_text().splitlines()]
patterns = [p for p in patterns if p and not p.startswith("#")]
print("patterns:", patterns)


def excluded(relpath: str) -> bool:
    for p in patterns:
        # docker treats a leading-slash and trailing-slash as anchored/prefix; our
        # patterns are plain relative paths -> exact file match or dir prefix.
        if fnmatch.fnmatch(relpath, p) or relpath == p or relpath.startswith(p.rstrip("/") + "/"):
            return True
    return False


# staging-relative forbidden paths (the real-Qwen spend drivers)
forbidden = [
    "tests/spike_session_update.py",
    "tests/spike_vocab_matrix.py",
    "tests/mvp_real_smoke.py",
    "tests/r1f_real_probe.py",
    "tests/r1c_probe.py",
]
# must never enter the context either
also_forbidden = ["secrets/product_v1_admin_token", "secrets/qwen-realtime.env",
                  "data/memory.json"]
# expected KEPT (mock infra + normal app)
kept = ["tests/mock_qwen_server.py", "app/main.py", "modules/memory/store.py",
        "config/config.json", "probe_product_v1.py"]

print("\n-- forbidden (must be excluded) --")
ok = True
for f in forbidden + also_forbidden:
    ex = excluded(f)
    ok &= ex
    print("  %-42s excluded=%s %s" % (f, ex, "OK" if ex else "*** NOT EXCLUDED ***"))

print("\n-- expected kept (must NOT be excluded) --")
for f in kept:
    ex = excluded(f)
    ok &= (not ex)
    print("  %-42s excluded=%s %s" % (f, ex, "OK" if not ex else "*** WRONGLY EXCLUDED ***"))

print("\nRESULT:", "PASS" if ok else "FAIL")
