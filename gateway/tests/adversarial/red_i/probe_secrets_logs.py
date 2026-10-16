#!/usr/bin/env python
"""RED-I probe: error-response & log hygiene against a LOCAL mock gateway.

Read-only on product source. Hits only the local admin API (127.0.0.1:29312),
triggering malformed / oversized / unknown-id / wrong-type inputs and checking
every response + (separately) the gateway log for disclosure of:
  token value, secret file paths, tracebacks, store internals, real transcripts.

Never prints a secret value. Run:
  gateway/.venv/bin/python gateway/tests/adversarial/red_i/probe_secrets_logs.py
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:29312"
TOKEN_FILE = "/tmp/adv/red_i/token"

# patterns that MUST NOT appear in any admin response body
FORBIDDEN = [
    ("token_value", None),  # filled at runtime
    ("secret_path", re.compile(r"/app/secrets|qwen-realtime\.env|admin_token|/tmp/adv/red_i/token")),
    ("traceback", re.compile(r"Traceback \(most recent call last\)|\bFile \"")),
    ("internal_module", re.compile(r"site-packages|gateway/app|modules/(memory|knowledge)|<user-home>")),
    ("exc_type", re.compile(r"\b(KeyError|TypeError|ValueError|AttributeError|IndexError|OpError)\b")),
    ("env_leak", re.compile(r"QWEN_REALTIME_API_KEY|QWEN_SECRET_FILE|ADMIN_API_TOKEN")),
]

def token() -> str:
    with open(TOKEN_FILE, "r", encoding="utf-8") as fh:
        return fh.read().strip()

def call(method, path, body=None, headers=None, raw_body=None, chunked=False):
    url = BASE + path
    data = None
    hdrs = dict(headers or {})
    if raw_body is not None:
        data = raw_body if isinstance(raw_body, bytes) else raw_body.encode()
    elif body is not None:
        data = json.dumps(body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return -1, repr(e)

def scan(label, status, body, tok, findings):
    hits = []
    if tok and tok in body:
        hits.append("token_value")
    for name, rx in FORBIDDEN:
        if name == "token_value":
            continue
        if rx.search(body):
            hits.append(name)
    if hits:
        findings.append((label, status, hits, body[:400]))

def main():
    tok = token()
    findings = []
    results = []

    def rec(label, status, body):
        results.append((label, status, body[:200]))
        scan(label, status, body, tok, findings)

    # ---- auth surface ----
    rec("anon GET /admin/health", *call("GET", "/admin/health"))
    rec("invalid token /admin/health",
        *call("GET", "/admin/health", headers={"Authorization": "Bearer not-a-valid-token"}))
    rec("malformed auth /admin/health",
        *call("GET", "/admin/health", headers={"Authorization": "abc"}))
    AUTH = {"Authorization": "Bearer " + tok}

    admin1_gets = ["/admin/health", "/admin/version", "/admin/sessions",
                   "/admin/metrics", "/admin/telemetry", "/admin/diag-summary"]
    admin2_gets = ["/admin/policy/active", "/admin/policy/versions", "/admin/policy/audit",
                   "/admin/memory/items", "/admin/memory/search?q=zzz",
                   "/admin/memory/item/nope", "/admin/memory/diagnostics",
                   "/admin/knowledge/datasets", "/admin/knowledge/diagnostics",
                   "/admin/knowledge/dataset/does-not-exist/preview",
                   "/admin/knowledge/dataset/does-not-exist/documents",
                   "/admin/knowledge/document/does-not-exist",
                   "/admin/knowledge/document/does-not-exist/chunks",
                   "/admin/workbench/status", "/admin/workbench/current",
                   "/admin/workbench/progress", "/admin/workbench/reviews",
                   "/admin/behavior/active", "/admin/behavior/routing", "/admin/audit"]
    for p in admin1_gets + admin2_gets:
        rec("valid GET %s" % p, *call("GET", p, headers=AUTH))

    # ---- malformed / boundary inputs (POST) ----
    posts = ["/admin/policy/preview", "/admin/policy/apply", "/admin/policy/rollback",
             "/admin/memory/edit", "/admin/memory/delete", "/admin/memory/clear-category",
             "/admin/knowledge/dataset/create", "/admin/knowledge/dataset/rename",
             "/admin/knowledge/dataset/enable", "/admin/knowledge/dataset/delete",
             "/admin/knowledge/document/add", "/admin/knowledge/document/delete",
             "/admin/knowledge/document/rebuild", "/admin/knowledge/search"]
    for p in posts:
        rec("malformed-json POST %s" % p,
            *call("POST", p, raw_body=b"{ not json ,,,",
                  headers={**AUTH, "Content-Type": "application/json"}))
        rec("non-dict-json POST %s" % p,
            *call("POST", p, raw_body=b"[1,2,3]",
                  headers={**AUTH, "Content-Type": "application/json"}))
        rec("empty-body POST %s" % p,
            *call("POST", p, raw_body=b"", headers={**AUTH}))
        rec("wrong-types POST %s" % p,
            *call("POST", p, body={"id": ["x"], "name": {"y": 1}, "entity": 3,
                                   "dataset_id": 1, "doc_id": None, "query": [1],
                                   "content": {"a": 1}, "confirm": "yes"},
                  headers=AUTH))
        # oversized (> 64 KiB Content-Length)
        big = {"blob": "A" * (70 * 1024)}
        rec("oversized POST %s" % p, *call("POST", p, body=big, headers=AUTH))

    # chunked oversized (no content-length) via generator to bypass the CL check
    def gen():
        chunk = b'{"blob":"' + b"A" * 8192 + b'"}'
        for _ in range(40):
            yield chunk
    for p in ["/admin/knowledge/search", "/admin/policy/apply"]:
        try:
            req = urllib.request.Request(BASE + p, data=gen(), method="POST",
                                         headers={**AUTH, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                rec("chunked-oversized POST %s" % p, resp.status, resp.read().decode("utf-8", "replace")[:200])
        except urllib.error.HTTPError as e:
            rec("chunked-oversized POST %s" % p, e.code, e.read().decode("utf-8", "replace")[:200])
        except Exception as e:  # noqa: BLE001
            rec("chunked-oversized POST %s" % p, -1, repr(e))

    # ---- unknown route / traversal-ish ----
    for p in ["/admin/env", "/admin/config", "/admin/../etc/passwd",
              "/admin/%2e%2e/etc/passwd", "/admin/health/../../secret"]:
        rec("probe %s" % p, *call("GET", p, headers=AUTH))

    # ---- report ----
    print("=== STATUS SUMMARY (label -> status) ===")
    from collections import Counter
    c = Counter(s for _, s, _ in results)
    print("status counts:", dict(sorted(c.items())))
    print("non-2xx responses (excluding intended 401/4xx probes):")
    for label, status, body in results:
        if status >= 500 or status < 0:
            print("  [%s] %s :: %s" % (status, label, body))
    print()
    print("=== DISCLOSURE SCAN ===")
    if findings:
        for label, status, hits, body in findings:
            print("LEAK CANDIDATE [%s] %s -> %s" % (status, label, hits))
            print("   body:", body)
    else:
        print("NO FORBIDDEN PATTERN IN ANY RESPONSE BODY")
    print()
    print("token present in any response body:", any("token_value" in h for _, _, h, _ in findings))
    return 0

if __name__ == "__main__":
    sys.exit(main())
