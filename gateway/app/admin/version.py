"""ADMIN-1 version/build facts (mechanically known values only).

``image_digest`` is deliberately **not** wired in this build: the authorization for ADMIN-1
requires reporting it as unavailable rather than inventing it, shelling out per request or
reading the Docker socket.  ``git_commit``/``build_time`` are only reported when they were
injected into the runtime environment by the (future) build pipeline.
"""

import os

GATEWAY_VERSION = "r1f-rev9+admin1"
SCHEMA_VERSION = "a14"                      # the R-1f A.14 counter contract


def build_facts(env=None):
    e = os.environ if env is None else env
    return {
        "version": GATEWAY_VERSION,
        "git_commit": (str(e.get("GATEWAY_GIT_COMMIT", "")).strip() or None),
        "build_time": (str(e.get("GATEWAY_BUILD_TIME", "")).strip() or None),
        "schema_version": SCHEMA_VERSION,
        "image_digest": None,
        "image_digest_source": "unavailable",
        "config_version": None,
        "config_version_source": "unavailable",
    }