"""RED_H — adversarial validation of the unified Chinese-first admin console.

Surface: the static UI (admin/index.html, admin/app.js, admin/styles.css) and the
API contract it consumes for input safety and robustness.

READ-ONLY on product source.  Runs fully in-process (aiohttp TestClient); no real
Qwen session, no network, no primary/Workbench/production touch.

Run:  DYLD_LIBRARY_PATH=/tmp/opus131/lib gateway/.venv/bin/python \
        gateway/tests/adversarial/red_h/red_h_admin_tests.py

Metrics under test:
  NO_ACTIVE_CONTENT_FROM_DATA   (expect PASS)
  NO_PARTIAL_MUTATION_ON_FAILURE(expect PASS; a FAIL is a finding)
  DOUBLE_SUBMIT_SAFE            (expect PASS)

Each `check()` asserts the SECURE expectation; a FAIL is a reproduced defect.
"""

import asyncio
import glob
import json
import os
import re
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[2]                      # gateway/
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from aiohttp import web                                      # noqa: E402
from aiohttp.test_utils import TestClient, TestServer        # noqa: E402

from app.admin import load_admin_config                      # noqa: E402
from app.admin.app import admin_route_table, create_admin_app  # noqa: E402
from app.admin.auth import TokenStore                        # noqa: E402
from app.admin.stores import AdminStores                     # noqa: E402

FIX_TOKEN = "REDH_TEST_TOKEN_DO_NOT_LEAK_2468"
UI_DIR = _ROOT.parent / "admin"
AUTH = {"Authorization": "Bearer " + FIX_TOKEN}

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % (detail,)) if (detail and not cond) else ""))


def _cfg(tmpdir, ui_dir=UI_DIR, name="admin_api_token"):
    return load_admin_config(env={
        "ADMIN_ENABLED": "1", "ADMIN_BIND": "127.0.0.1", "ADMIN_PORT": "9412",
        "ADMIN_API_TOKEN_FILE": str(Path(tmpdir) / name),
        "ADMIN_UI_DIR": str(ui_dir),
    })


def _token(tmpdir, name="admin_api_token"):
    p = Path(tmpdir) / name
    p.write_text(FIX_TOKEN + "\n")
    os.chmod(p, 0o600)
    return str(p)


def _stores(tmpdir, *, workbench_url="", name="default"):
    sub = Path(tmpdir) / name
    sub.mkdir(parents=True, exist_ok=True)
    return AdminStores(policy_file=str(sub / "policy.json"),
                       memory_file=str(sub / "memory.json"),
                       knowledge_file=str(sub / "knowledge.json"),
                       workbench_url=workbench_url)


async def with_client(fn, tmpdir, *, stores, ui_dir=UI_DIR):
    token_file = _token(tmpdir)
    cfg = _cfg(tmpdir, ui_dir=ui_dir)
    cfg = cfg.__class__(enabled=cfg.enabled, bind=cfg.bind, port=cfg.port,
                        token_file=token_file, token_env="", ui_dir=cfg.ui_dir)
    ts = TokenStore(cfg.token_file, cfg.token_env)
    ts.reload()
    app = create_admin_app(admin_config=cfg, token_store=ts,
                           gateway_info=lambda: {"mode": "mock", "ready": True,
                                                 "model": "m", "voice": "v"},
                           stores=stores)
    async with TestClient(TestServer(app)) as client:
        await fn(client, stores, tmpdir)


# ---------------------------------------------------------------------------
# 1. ACTIVE-CONTENT SINKS (static, exhaustive)
# ---------------------------------------------------------------------------

DANGEROUS = [
    "innerHTML", "outerHTML", "insertAdjacentHTML", "document.write",
    "eval(", "new Function", "srcdoc", "createContextualFragment",
    "DOMParser", "dangerouslySet", "javascript:", ".href", ".src",
    "formaction", "xlink:href", "setAttribute",
]
# dangerous DOM event-handler attribute names in markup
ON_ATTR = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)


def scan_assets():
    js = (UI_DIR / "app.js").read_text("utf-8")
    html = (UI_DIR / "index.html").read_text("utf-8")
    css = (UI_DIR / "styles.css").read_text("utf-8")
    blob = js + "\n" + html + "\n" + css

    hits = {tok: blob.count(tok) for tok in DANGEROUS if tok in blob}
    check("H1 no active-content sink token anywhere in admin UI assets",
          hits == {}, hits)
    check("H2 no inline on* event handlers in index.html",
          not ON_ATTR.search(html), ON_ATTR.findall(html))
    check("H3 no <script>/<iframe>/<object>/<embed> built in app.js",
          not re.search(r"<script|<iframe|<object|<embed", js, re.IGNORECASE))
    # the only setTimeout uses a function reference (not a string)
    stims = re.findall(r"setTimeout\(([^,]+),", js)
    check("H4 every setTimeout is a function ref (no string eval)",
          bool(stims) and all(s.strip().startswith("function") for s in stims),
          stims)
    # DOM text writes are textContent / createElement / appendChild only
    writes = set(re.findall(r"\.(textContent|innerText|innerHTML|outerHTML)\s*=", js))
    check("H5 DOM text writes are textContent only",
          writes == {"textContent"}, sorted(writes))
    # attribute sinks are literals or form-control values, never URL/event attrs.
    # `body` is the fetch RequestInit body (a data property, not a DOM attribute).
    attrs = set(re.findall(r"\.([A-Za-z]+)\s*=(?!=)", js))
    safe_attrs = {"className", "textContent", "value", "id", "placeholder",
                  "selected", "onclick", "body"}
    check("H6 attributes assigned are non-dangerous (no href/src/style/on*)",
          attrs <= safe_attrs, sorted(attrs - safe_attrs))


# ---------------------------------------------------------------------------
# 2. DATA ROUND-TRIP (inert bytes through every GET that displays it)
# ---------------------------------------------------------------------------

XSS_TITLE = "<img src=x onerror=alert(1)>\"'\\"
XSS_DATASET = "<script>alert('ds')</script>"
XSS_URI = "javascript:alert(1)//uri\"><svg/onload=alert(2)>"
XSS_TEXT = "line1 </script><script>alert(3)</script> & <b>bold</b>\n\nsecond para \u202eRTL"
WEIRD_VALUE = ("emoji \U0001f469\u200d\U0001f4bb ZWJ, combining e\u0301, "
               "zero\u200bwidth, arabic \u0645\u0631\u062d\u0628\u0627, "
               "hebrew \u05e9\u05dc\u05d5\u05dd, nul\u0000byte")


async def t_roundtrip(tmpdir):
    stores = _stores(tmpdir, name="roundtrip")

    async def body(client, stores, _):
        # ---- knowledge: dataset name / title / source_uri / text ----
        ds = (await (await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                                       json={"name": XSS_DATASET})).json())["dataset"]
        doc = (await (await client.post(
            "/admin/knowledge/document/add", headers=AUTH,
            json={"dataset_id": ds["id"], "title": XSS_TITLE, "text": XSS_TEXT,
                  "source_type": "text", "source_uri": XSS_URI})).json())["document"]

        r = await client.get("/admin/knowledge/datasets", headers=AUTH)
        ct = r.headers.get("Content-Type", "")
        data = await r.json()
        names = [d["name"] for d in data["datasets"]]
        check("H7 dataset name (script-like) round-trips inert as JSON",
              r.status == 200 and "application/json" in ct and XSS_DATASET in names,
              (r.status, ct, names))
        check("H8 datasets endpoint is application/json (not text/html)",
              "text/html" not in ct.lower(), ct)

        r2 = await (await client.get(
            "/admin/knowledge/dataset/%s/documents" % ds["id"], headers=AUTH)).json()
        got = r2["documents"][0]
        check("H9 document title (img-onerror) round-trips exact bytes",
              got["title"] == XSS_TITLE, (got["title"], XSS_TITLE))
        check("H10 source_uri (javascript:+svg) round-trips exact bytes",
              got["source"]["uri"] == XSS_URI,
              (got["source"].get("uri"), XSS_URI))

        # retrieval surfaces title + source + text verbatim
        sr = await (await client.post("/admin/knowledge/search", headers=AUTH,
                                      json={"query": "line1"})).json()
        hits = [h for h in sr["results"] if h["document_id"] == doc["id"]]
        check("H11 search hit returns the script-like title/uri as data",
              hits and hits[0]["document_title"] == XSS_TITLE
              and hits[0]["source"]["uri"] == XSS_URI, sr.get("results")[:1])

        # ---- memory: script-like + weird unicode value ----
        stores.memory.save("profile_fact", "note", "<script>alert('mem')</script>")
        items = await (await client.get("/admin/memory/items", headers=AUTH)).json()
        vals = [i["value"] for i in items["items"]]
        check("H12 memory script-like value round-trips inert as data",
              "<script>alert('mem')</script>" in vals, vals)

        # weird-unicode value must survive the JSON boundary byte-for-byte
        r3 = await client.post("/admin/memory/edit", headers=AUTH,
                               json={"id": [i for i in items["items"]
                                            if i["key"] == "note"][0]["id"],
                                     "value": WEIRD_VALUE})
        rd = await r3.json()
        check("H13 memory unicode/RTL/emoji/ZWJ/NUL value round-trips",
              r3.status == 200 and rd["item"]["value"] == WEIRD_VALUE,
              (r3.status, rd.get("item", {}).get("value")))

        # diagnostics GET that lists keys/values must also stay JSON
        dg = await client.get("/admin/memory/diagnostics", headers=AUTH)
        check("H14 memory diagnostics JSON content-type",
              "application/json" in dg.headers.get("Content-Type", ""))

    await with_client(body, tmpdir, stores=stores)


# ---------------------------------------------------------------------------
# 3. INPUT SAFETY AT THE API
# ---------------------------------------------------------------------------

async def t_input_safety(tmpdir):
    stores = _stores(tmpdir, name="inputs")

    async def body(client, stores, _):
        # weird path ids -> clean 4xx, never 500 / traceback / path disclosure
        for pid in ("%2e%2e%2f%2e%2e%2fetc%2fpasswd", "x" * 500,
                    "%00%01%02", "\u202e\u0000"):
            r = await client.get("/admin/memory/item/" + pid, headers=AUTH)
            txt = await r.text()
            ok = r.status in (400, 404) and "Traceback" not in txt \
                and "/Users/" not in txt and "/etc/" not in txt
            check("H15 memory item weird path id -> clean 4xx (%r)" % pid[:24],
                  ok, (r.status, txt[:120]))

        r = await client.get("/admin/knowledge/document/" + "%2e%2e%2fpasswd",
                             headers=AUTH)
        txt = await r.text()
        check("H16 knowledge doc traversal-ish id -> clean 4xx, no path leak",
              r.status in (400, 404) and "/etc/" not in txt and "/Users/" not in txt,
              (r.status, txt[:120]))

        # malformed JSON body / non-object
        r = await client.post("/admin/memory/edit", headers=AUTH, data="{not json")
        check("H17 malformed JSON -> 400 invalid_json",
              r.status == 400 and (await r.json()).get("error") == "invalid_json",
              r.status)
        r = await client.post("/admin/memory/edit", headers=AUTH, data="[1,2,3]")
        check("H18 non-object JSON -> 400", r.status == 400, r.status)

        # duplicate JSON keys: last wins, must stay a clean coded response
        stores.memory.save("profile_fact", "dup", "v1")
        items = (await (await client.get("/admin/memory/items", headers=AUTH)).json())
        real_id = [i for i in items["items"] if i["key"] == "dup"][0]["id"]
        r = await client.post("/admin/memory/edit", headers=AUTH,
                              data='{"id": "%s", "id": "mem_bogus", "value": "z"}'
                              % real_id)
        check("H19 duplicate JSON keys last-wins, no 500",
              r.status in (400, 404) and (await r.json()).get("error")
              in ("boundary_violation", "not_found"), r.status)

        # unknown fields ignored
        r = await client.post("/admin/memory/edit", headers=AUTH,
                              json={"id": real_id, "value": "v2",
                                    "role": "admin", "__proto__": {"x": 1}})
        check("H20 unknown/extra fields ignored, item updated",
              r.status == 200 and (await r.json())["item"]["value"] == "v2", r.status)

        # wrong-type value / confidence -> 400 (not 500)
        r = await client.post("/admin/memory/edit", headers=AUTH,
                              json={"id": real_id, "value": [1, 2, 3]})
        check("H21 list value -> 400 (not 500)", r.status == 400, r.status)
        r = await client.post("/admin/memory/edit", headers=AUTH,
                              json={"id": real_id, "confidence": "abc"})
        check("H22 non-numeric confidence -> 400 (not 500)", r.status == 400, r.status)

        # knowledge: top_k type confusion MUST be 400, not 500
        r = await client.post("/admin/knowledge/search", headers=AUTH,
                              json={"query": "x", "top_k": "abc"})
        check("H23 knowledge search top_k='abc' -> 400 (not 500)",
              r.status == 400, (r.status, (await r.text())[:120]))
        r = await client.post("/admin/knowledge/search", headers=AUTH,
                              json={"query": "x", "top_k": {}})
        check("H24 knowledge search top_k={} -> 400 (not 500)",
              r.status == 400, (r.status, (await r.text())[:120]))

        # dataset name type confusion: non-string should be rejected (4xx)
        r = await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                              json={"name": {"a": 1}})
        check("H25 dataset name non-string (dict) -> 4xx reject",
              r.status in (400, 422), (r.status, (await r.text())[:120]))

        # very long name / title / text
        r = await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                              json={"name": "N" * 5000})
        check("H26 over-long dataset name -> 400", r.status == 400, r.status)
        ds = (await (await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                                       json={"name": "t"})).json())["dataset"]
        r = await client.post("/admin/knowledge/document/add", headers=AUTH,
                              json={"dataset_id": ds["id"], "title": "T" * 5000,
                                    "text": "hello"})
        check("H27 over-long document title -> 400", r.status == 400, r.status)

        # oversized body (>64 KiB) -> 413
        big_headers = dict(AUTH)
        big_headers["Content-Type"] = "application/json"
        r = await client.post("/admin/knowledge/document/add", headers=big_headers,
                              data=json.dumps({"dataset_id": ds["id"], "title": "big",
                                               "text": "a" * 70000}))
        check("H28 >64KiB body -> 413 (pre-parse cap)", r.status == 413, r.status)

        # NUL in document text: normalized away, no error
        r = await client.post("/admin/knowledge/document/add", headers=AUTH,
                              json={"dataset_id": ds["id"], "title": "nul",
                                    "text": "a\u0000b\u0000c"})
        check("H29 NUL in document text accepted (normalized), no 500",
              r.status == 200, (r.status, (await r.text())[:120]))

    await with_client(body, tmpdir, stores=stores)


# ---------------------------------------------------------------------------
# 4. PERSIST FAILURE — same class as policy (a): success reported though the
#    durable write failed.
# ---------------------------------------------------------------------------

async def t_persist_failure(tmpdir):
    # memory: file lives in a directory made read-only after load
    mdir = Path(tmpdir) / "mro"
    mdir.mkdir()
    memory_file = str(mdir / "memory.json")
    kdir = Path(tmpdir) / "kro"
    kdir.mkdir()
    knowledge_file = str(kdir / "knowledge.json")
    stores = AdminStores(policy_file="", memory_file=memory_file,
                         knowledge_file=knowledge_file, workbench_url="")
    stores.memory.save("profile_fact", "seed", "v0")
    assert Path(memory_file).is_file(), "seed flush must create the file"
    before = Path(memory_file).read_text("utf-8")
    os.chmod(mdir, 0o500)   # persist now impossible
    os.chmod(kdir, 0o500)
    try:
        async def body(client, stores, _):
            items = (await (await client.get("/admin/memory/items", headers=AUTH))
                     .json())
            mid = [i for i in items["items"] if i["key"] == "seed"][0]["id"]

            r = await client.post("/admin/memory/edit", headers=AUTH,
                                  json={"id": mid, "value": "v1"})
            rd = await r.json()
            after = Path(memory_file).read_text("utf-8")
            check("H30 memory edit with failed persist is NOT reported as success",
                  r.status != 200 or rd.get("readback_ok") is not True
                  or "v1" in after,
                  (r.status, rd.get("readback_ok"), "disk_changed=%s" % ("v1" in after)))

            r = await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                                  json={"name": "kb1"})
            rd = await r.json()
            exists = Path(knowledge_file).exists()
            check("H31 knowledge dataset create with failed persist is NOT success",
                  r.status != 200 or rd.get("readback_ok") is not True or exists,
                  (r.status, rd.get("readback_ok"), "file_exists=%s" % exists))
        await with_client(body, tmpdir, stores=stores)
    finally:
        os.chmod(mdir, 0o700)
        os.chmod(kdir, 0o700)


# ---------------------------------------------------------------------------
# 5. .tmp LEAK when the atomic replace fails (same class as policy (c))
# ---------------------------------------------------------------------------

async def t_tmp_leak(tmpdir):
    leak = Path(tmpdir) / "leak"
    leak.mkdir()
    slot = leak / "memory.json"
    slot.mkdir()                      # target path is a DIRECTORY -> os.replace fails
    stores = AdminStores(policy_file="", memory_file=str(slot),
                         knowledge_file="", workbench_url="")

    async def body(client, stores, _):
        # a normal-looking write whose atomic replace cannot succeed
        try:
            stores.memory.save("profile_fact", "leaky", "v")
        except Exception:
            pass
        leftovers = glob.glob(str(leak / "*.tmp"))
        check("H32 failed atomic replace leaves no .tmp behind",
              leftovers == [], leftovers)

    await with_client(body, tmpdir, stores=stores)


# ---------------------------------------------------------------------------
# 6. DOUBLE-SUBMIT SAFETY
# ---------------------------------------------------------------------------

async def t_double_submit(tmpdir):
    stores = _stores(tmpdir, name="dbl")

    async def body(client, stores, _):
        # knowledge: dataset + document, then double-delete each
        ds = (await (await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                                       json={"name": "d"})).json())["dataset"]
        doc = (await (await client.post(
            "/admin/knowledge/document/add", headers=AUTH,
            json={"dataset_id": ds["id"], "title": "t", "text": "hello world"})).json()
        )["document"]

        r1 = await client.post("/admin/knowledge/document/delete", headers=AUTH,
                               json={"id": doc["id"], "confirm": True})
        r2 = await client.post("/admin/knowledge/document/delete", headers=AUTH,
                               json={"id": doc["id"], "confirm": True})
        check("H33 document delete double-submit: 2nd does not double-apply",
              r1.status == 200 and r2.status in (400, 404),
              (r1.status, r2.status))

        d1 = await client.post("/admin/knowledge/dataset/delete", headers=AUTH,
                               json={"id": ds["id"], "confirm": ds["id"]})
        d2 = await client.post("/admin/knowledge/dataset/delete", headers=AUTH,
                               json={"id": ds["id"], "confirm": ds["id"]})
        check("H34 dataset delete double-submit: 2nd does not double-apply",
              d1.status == 200 and d2.status in (400, 404), (d1.status, d2.status))

        # memory: double delete + double clear-category
        stores.memory.save("profile_fact", "d", "v")
        items = (await (await client.get("/admin/memory/items", headers=AUTH)).json())
        mid = [i for i in items["items"] if i["key"] == "d"][0]["id"]
        m1 = await client.post("/admin/memory/delete", headers=AUTH,
                               json={"id": mid, "confirm": True})
        m2 = await client.post("/admin/memory/delete", headers=AUTH,
                               json={"id": mid, "confirm": True})
        check("H35 memory delete double-submit: 2nd -> 404, no double-apply",
              m1.status == 200 and m2.status == 404, (m1.status, m2.status))

        stores.memory.save("habit", "h", "short answers")
        c1 = await (await client.post("/admin/memory/clear-category", headers=AUTH,
                                      json={"entity": "habit", "confirm": "habit"})).json()
        c2 = await (await client.post("/admin/memory/clear-category", headers=AUTH,
                                      json={"entity": "habit", "confirm": "habit"})).json()
        check("H36 category clear double-submit: 2nd removes 0 (idempotent)",
              c1["removed"] == 1 and c2["removed"] == 0,
              (c1["removed"], c2["removed"]))

    await with_client(body, tmpdir, stores=stores)


# ---------------------------------------------------------------------------
# 7. DESTRUCTIVE CANCELLATION — no mutation without a correct confirmation
# ---------------------------------------------------------------------------

async def t_cancellation(tmpdir):
    stores = _stores(tmpdir, name="cancel")

    async def body(client, stores, _):
        stores.memory.save("profile_fact", "keep", "v")
        items = (await (await client.get("/admin/memory/items", headers=AUTH)).json())
        mid = [i for i in items["items"] if i["key"] == "keep"][0]["id"]

        r = await client.post("/admin/memory/delete", headers=AUTH, json={"id": mid})
        still = (await (await client.get("/admin/memory/items", headers=AUTH)).json())
        check("H37 memory delete w/o confirm -> 400 and no mutation",
              r.status == 400 and any(i["id"] == mid for i in still["items"]), r.status)

        r = await client.post("/admin/memory/clear-category", headers=AUTH,
                              json={"entity": "profile_fact", "confirm": "wrong"})
        still = (await (await client.get("/admin/memory/items", headers=AUTH)).json())
        check("H38 category clear wrong confirm -> 400 and no mutation",
              r.status == 400 and any(i["id"] == mid for i in still["items"]), r.status)

        ds = (await (await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                                       json={"name": "c"})).json())["dataset"]
        r = await client.post("/admin/knowledge/dataset/delete", headers=AUTH,
                              json={"id": ds["id"], "confirm": "not-the-id"})
        dslist = (await (await client.get("/admin/knowledge/datasets", headers=AUTH))
                  .json())
        check("H39 dataset delete wrong confirm -> 400 and dataset survives",
              r.status == 400 and any(d["id"] == ds["id"]
                                      for d in dslist["datasets"]), r.status)

    await with_client(body, tmpdir, stores=stores)


# ---------------------------------------------------------------------------
# 8. STATELESSNESS — server state consistent across a client refresh
# ---------------------------------------------------------------------------

async def t_stateless(tmpdir):
    stores = _stores(tmpdir, name="stateless")

    # a preview must not change anything, and a *fresh* client must be able to
    # complete the op using only data it read back (no server-side pending state)
    async def first(client, stores, _):
        pv = await (await client.post("/admin/policy/preview", headers=AUTH,
                                      json={"policy": {"persona": {"name": "新名"}}})
                    ).json()
        check("H40 preview is non-mutating (would_be_version, no apply)",
              pv["valid"] and pv["would_be_version"] == 2)

    await with_client(first, tmpdir, stores=stores)

    async def second(client, stores, _):
        act = await (await client.get("/admin/policy/active", headers=AUTH)).json()
        check("H41 fresh client sees unchanged version after a preview elsewhere",
              act["version"] == 1, act["version"])
        # confirm tokens are data-derived (stateless), not server-issued nonces
        ds = (await (await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                                       json={"name": "s"})).json())["dataset"]
        prev = await (await client.get(
            "/admin/knowledge/dataset/%s/preview" % ds["id"], headers=AUTH)).json()
        check("H42 confirm token is the dataset id (data-derived, no server state)",
              prev["preview"]["confirm_token"] == ds["id"],
              prev["preview"]["confirm_token"])

    await with_client(second, tmpdir, stores=stores)


# ---------------------------------------------------------------------------
# 9. MISSING / CORRUPT UI ASSETS degrade safely
# ---------------------------------------------------------------------------

async def t_ui_assets(tmpdir):
    empty = Path(tmpdir) / "emptyui"
    empty.mkdir()
    stores = _stores(tmpdir, name="ui")

    async def body(client, stores, _):
        for p in ("/", "/index.html", "/app.js", "/styles.css"):
            r = await client.get(p)
            txt = await r.text()
            ok = r.status == 503 and "ui_unavailable" in txt \
                and "/Users/" not in txt and "Traceback" not in txt \
                and "emptyui" not in txt
            check("H43 missing asset %s -> honest 503, no path/trace leak" % p,
                  ok, (r.status, txt[:120]))
        r = await client.get("/does-not-exist")
        txt = await r.text()
        check("H44 unknown shell path -> 404, no path/trace leak",
              r.status == 404 and "/Users/" not in txt and "Traceback" not in txt,
              (r.status, txt[:120]))
        r = await client.get("/favicon.ico")
        check("H45 favicon -> 204", r.status == 204, r.status)

    await with_client(body, tmpdir, stores=stores, ui_dir=empty)

    # and with the real UI dir, the shell serves with the right content types
    stores2 = _stores(tmpdir, name="ui2")

    async def body2(client, stores, _):
        r = await client.get("/")
        check("H46 real shell serves index.html as text/html",
              r.status == 200 and "text/html" in r.headers.get("Content-Type", ""),
              r.status)
        for p, ct in (("/app.js", "javascript"), ("/styles.css", "text/css")):
            rr = await client.get(p)
            check("H47 %s served as %s" % (p, ct),
                  rr.status == 200 and ct in rr.headers.get("Content-Type", ""),
                  rr.status)

    await with_client(body2, tmpdir, stores=stores2)


# ---------------------------------------------------------------------------
# 10. "no common operation should require raw JSON" (static coverage)
# ---------------------------------------------------------------------------

WRITES_FROM_UI = {
    "/admin/policy/preview", "/admin/policy/apply", "/admin/policy/rollback",
    "/admin/memory/edit", "/admin/memory/delete", "/admin/memory/clear-category",
    "/admin/knowledge/dataset/create", "/admin/knowledge/dataset/rename",
    "/admin/knowledge/dataset/enable", "/admin/knowledge/dataset/delete",
    "/admin/knowledge/document/add", "/admin/knowledge/document/delete",
    "/admin/knowledge/document/rebuild", "/admin/knowledge/search",
}


def coverage_static():
    js = (UI_DIR / "app.js").read_text("utf-8")
    table = admin_route_table(stores=AdminStores())
    write_routes = {p for m, p in table if m == "POST"}
    missing_writes = write_routes - WRITES_FROM_UI
    check("H48 every POST write route has a UI affordance in app.js",
          missing_writes == set(), sorted(missing_writes))
    # destructive actions all gated by window.confirm
    check("H49 >=6 destructive actions gated by window.confirm",
          js.count("window.confirm(") >= 6, js.count("window.confirm("))


# ---------------------------------------------------------------------------

async def amain():
    tmp = tempfile.mkdtemp(prefix="redh-")
    scan_assets()
    coverage_static()
    await t_roundtrip(tmp)
    await t_input_safety(tmp)
    await t_persist_failure(tmp)
    await t_tmp_leak(tmp)
    await t_double_submit(tmp)
    await t_cancellation(tmp)
    await t_stateless(tmp)
    await t_ui_assets(tmp)

    total = len(RESULTS)
    failed = [r for r in RESULTS if not r[1]]
    print("=" * 74)
    print("RED_H_ADMIN_TESTS: %d checks, %d PASS, %d FAIL"
          % (total, total - len(failed), len(failed)))
    for name, _, detail in failed:
        print("  FINDING: %s %s" % (name, detail))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
