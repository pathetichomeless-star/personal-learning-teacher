"""RED_H ROUND 3 — independent cross-check of the persist-honesty + validation fixes.

Read-only on product source.  Fully in-process (aiohttp TestClient); no real Qwen,
no network, no primary/Workbench/production.

Scope: cross-check the fixes landed in e3c9b6c / b854778 through the ADMIN-2 API and
the admin UI contract.  NOT a rubber-stamp: every write route is attacked under a
forced persist failure, the new validation rules are attacked from the operator seat,
and every metric from rounds 1/2 is re-proved on the current revision.

Run:  DYLD_LIBRARY_PATH=/tmp/opus131/lib gateway/.venv/bin/python \
        gateway/tests/adversarial/red_h/red_h_round3_crosscheck.py
"""

import asyncio
import json
import os
import re
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[2]                          # gateway/
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from aiohttp.test_utils import TestClient, TestServer        # noqa: E402

from app.admin import load_admin_config                      # noqa: E402
from app.admin.app import admin_route_table, create_admin_app  # noqa: E402
from app.admin.auth import TokenStore                        # noqa: E402
from app.admin.stores import AdminStores                     # noqa: E402
from modules.knowledge.store import KnowledgeStore           # noqa: E402
from modules.memory.store import MemoryStore                 # noqa: E402
from modules.policy.persona import PolicyStore               # noqa: E402

FIX_TOKEN = "REDH_R3_TOKEN_DO_NOT_LEAK_1357"
UI_DIR = _ROOT.parent / "admin"
AUTH = {"Authorization": "Bearer " + FIX_TOKEN}
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  [%s]" % (detail,)) if (detail and not cond) else ""))


def _token(tmpdir):
    p = Path(tmpdir) / "tok"
    p.write_text(FIX_TOKEN + "\n")
    os.chmod(p, 0o600)
    return str(p)


def _app(tmpdir, stores, ui_dir=UI_DIR):
    cfg = load_admin_config(env={
        "ADMIN_ENABLED": "1", "ADMIN_BIND": "127.0.0.1", "ADMIN_PORT": "9412",
        "ADMIN_API_TOKEN_FILE": _token(tmpdir), "ADMIN_UI_DIR": str(ui_dir)})
    ts = TokenStore(cfg.token_file, cfg.token_env)
    ts.reload()
    return create_admin_app(admin_config=cfg, token_store=ts,
                            gateway_info=lambda: {"mode": "mock", "ready": True},
                            stores=stores)


async def with_client(fn, tmpdir, *, stores, ui_dir=UI_DIR):
    app = _app(tmpdir, stores, ui_dir)
    async with TestClient(TestServer(app)) as client:
        await fn(client, stores, tmpdir)


def _mkstores(tmpdir, name="s", *, workbench_url=""):
    sub = Path(tmpdir) / name
    sub.mkdir(parents=True, exist_ok=True)
    return AdminStores(policy_file=str(sub / "policy.json"),
                       memory_file=str(sub / "memory.json"),
                       knowledge_file=str(sub / "knowledge.json"),
                       workbench_url=workbench_url), sub


# ===========================================================================
# A. UI static re-verification (admin/ was NOT touched by the fixes)
# ===========================================================================

DANGEROUS = ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write",
             "eval(", "new Function", "srcdoc", "createContextualFragment",
             "DOMParser", "dangerouslySet", "javascript:", ".href", ".src",
             "formaction", "xlink:href", "setAttribute"]
ON_ATTR = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)


def t_ui_static():
    js = (UI_DIR / "app.js").read_text("utf-8")
    html = (UI_DIR / "index.html").read_text("utf-8")
    css = (UI_DIR / "styles.css").read_text("utf-8")
    blob = js + html + css
    hits = {t: blob.count(t) for t in DANGEROUS if t in blob}
    check("R3-1 no active-content sink token in admin assets (unchanged)",
          hits == {}, hits)
    check("R3-2 no inline on* handlers in index.html",
          not ON_ATTR.search(html), ON_ATTR.findall(html))
    writes = set(re.findall(r"\.(textContent|innerText|innerHTML|outerHTML)\s*=", js))
    check("R3-3 DOM text writes are textContent only", writes == {"textContent"},
          sorted(writes))
    attrs = set(re.findall(r"\.([A-Za-z]+)\s*=(?!=)", js))
    check("R3-4 no data-driven href/src/style/on* attribute assignment",
          attrs <= {"className", "textContent", "value", "id", "placeholder",
                    "selected", "onclick", "body"}, sorted(attrs))
    check("R3-5 showError renders via textContent (honest, no HTML)",
          'box.textContent = parts.join' in js and "innerHTML" not in js)
    # every POST write route still has a UI affordance
    table = admin_route_table(stores=AdminStores())
    write_routes = {p for m, p in table if m == "POST"}
    ui_writes = set(re.findall(r'api\("(/admin/[^"]+)"', js))
    check("R3-6 every POST write route has a UI affordance",
          write_routes - ui_writes == set(), sorted(write_routes - ui_writes))


# ===========================================================================
# B. Persist-honesty sweep: EVERY write route under a forced flush failure
# ===========================================================================

# (label, path, body, must-not-return-200-with-readback-true)
def _write_attempts(ids):
    return [
        ("memory edit", "/admin/memory/edit",
         {"id": ids["mem"], "value": "v1"}),
        ("memory delete", "/admin/memory/delete",
         {"id": ids["mem"], "confirm": True}),
        ("memory clear-category", "/admin/memory/clear-category",
         {"entity": "habit", "confirm": "habit"}),
        ("knowledge dataset create", "/admin/knowledge/dataset/create",
         {"name": "kb_new"}),
        ("knowledge dataset rename", "/admin/knowledge/dataset/rename",
         {"id": ids["ds"], "name": "renamed"}),
        ("knowledge dataset enable", "/admin/knowledge/dataset/enable",
         {"id": ids["ds"], "enabled": False}),
        ("knowledge dataset delete", "/admin/knowledge/dataset/delete",
         {"id": ids["ds"], "confirm": ids["ds"]}),
        ("knowledge document add", "/admin/knowledge/document/add",
         {"dataset_id": ids["ds"], "title": "t2", "text": "second body here"}),
        ("knowledge document delete", "/admin/knowledge/document/delete",
         {"id": ids["doc"], "confirm": True}),
        ("knowledge document rebuild", "/admin/knowledge/document/rebuild",
         {"id": ids["doc"]}),
        ("policy apply", "/admin/policy/apply",
         {"policy": {"persona": {"name": "新名"}}, "confirm": True}),
        ("policy rollback", "/admin/policy/rollback",
         {"version": 1, "confirm": True}),
    ]


async def t_persist_sweep(tmpdir):
    stores, sub = _mkstores(tmpdir, "ro")
    mem_path = str(sub / "memory.json")
    kb_path = str(sub / "knowledge.json")
    pol_path = str(sub / "policy.json")

    # seed while writable so deletes/renames have a target and v1 is in history
    stores.memory.save("profile_fact", "seed", "v0")
    stores.memory.save("habit", "h", "short answers")
    ds = stores.knowledge.create_dataset("seedds")
    doc = stores.knowledge.add_document(ds["id"], "seeddoc", "hello world seed body")
    stores.policy.apply({"persona": {"name": "小美"}})          # v2, puts v1 in history
    assert PolicyStore(pol_path).load().active()["version"] == 2
    seed_mem_id = [i for i in stores.memory.list_items()
                   if i["key"] == "seed"][0]["id"]
    ids = {"mem": seed_mem_id, "ds": ds["id"], "doc": doc["id"]}

    os.chmod(sub, 0o500)                                        # persist now fails
    try:
        async def body(client, stores, _):
            for label, path, payload in _write_attempts(ids):
                r = await client.post(path, headers=AUTH, json=payload)
                j = None
                try:
                    j = await r.json()
                except Exception:
                    pass
                err = (j or {}).get("error")
                honest = r.status in (400, 404, 409, 500)
                no_fake = not (r.status == 200 and (j or {}).get("readback_ok") is True)
                check("R3-7 %s under failed persist -> honest failure (no fake 200)" % label,
                      honest and no_fake, (r.status, err))
                if r.status == 500:
                    check("R3-7b %s 500 is persist_failed (coded)" % label,
                          err == "persist_failed", err)

            # no phantom: a FRESH reader must see the pre-write durable state
            fresh_mem = MemoryStore(mem_path).load()
            check("R3-8 memory: fresh reader still sees the seeded value",
                  (fresh_mem.inspect(seed_mem_id) or {}).get("value") == "v0",
                  fresh_mem.inspect(seed_mem_id))
            check("R3-9 memory: habit category not cleared on disk",
                  any(i["key"] == "h" for i in fresh_mem.list_items()))
            fresh_kb = KnowledgeStore(kb_path).load()
            check("R3-10 knowledge: dataset survives on disk",
                  fresh_kb.get_dataset(ds["id"]) is not None)
            check("R3-11 knowledge: document survives on disk",
                  fresh_kb.get_document(doc["id"]) is not None)
            check("R3-12 policy: version unchanged on disk after failed apply+rollback",
                  PolicyStore(pol_path).load().active()["version"] == 2,
                  PolicyStore(pol_path).load().active()["version"])
        await with_client(body, tmpdir, stores=stores)
    finally:
        os.chmod(sub, 0o700)

    # sanity: once writable again (simulating a transient failure clearing), a retry works
    async def retry(client, stores, _):
        r = await client.post("/admin/memory/edit", headers=AUTH,
                              json={"id": seed_mem_id, "value": "v_retry"})
        j = await r.json()
        check("R3-13 retry after the failure clears succeeds and is durable",
              r.status == 200 and j.get("readback_ok") is True
              and (MemoryStore(mem_path).load().inspect(seed_mem_id) or {})
              .get("value") == "v_retry",
              (r.status, j.get("readback_ok")))
    await with_client(retry, tmpdir, stores=stores)


# ===========================================================================
# C. readback_ok vs durable agreement on the SUCCESS path (fresh reader)
# ===========================================================================

async def t_readback_success(tmpdir):
    stores, sub = _mkstores(tmpdir, "ok")

    async def body(client, stores, _):
        # knowledge create: readback_ok true implies a fresh reader sees it
        r = await (await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                                     json={"name": "okds"})).json()
        fresh = KnowledgeStore(str(sub / "knowledge.json")).load()
        check("R3-14 knowledge create readback_ok agrees with a fresh reader",
              r["readback_ok"] is True and fresh.get_dataset(r["dataset"]["id"])
              is not None)

        doc = (await (await client.post(
            "/admin/knowledge/document/add", headers=AUTH,
            json={"dataset_id": r["dataset"]["id"], "title": "t",
                  "text": "hello durable body"})).json())["document"]
        fresh = KnowledgeStore(str(sub / "knowledge.json")).load()
        check("R3-15 document add readback_ok agrees with a fresh reader",
              fresh.get_document(doc["id"]) is not None)

        # memory: edit then a fresh reader sees the value
        stores.memory.save("profile_fact", "k", "v0")
        items = (await (await client.get("/admin/memory/items", headers=AUTH)).json())
        mid = [i for i in items["items"] if i["key"] == "k"][0]["id"]
        e = await (await client.post("/admin/memory/edit", headers=AUTH,
                                     json={"id": mid, "value": "v1"})).json()
        fresh = MemoryStore(str(sub / "memory.json")).load()
        check("R3-16 memory edit readback_ok agrees with a fresh reader",
              e["readback_ok"] is True
              and (fresh.inspect(mid) or {}).get("value") == "v1")

        # policy apply then a fresh reader sees the new version
        p = await (await client.post("/admin/policy/apply", headers=AUTH,
                                     json={"policy": {"persona": {"name": "新"}},
                                           "confirm": True})).json()
        fresh = PolicyStore(str(sub / "policy.json")).load().active()
        check("R3-17 policy apply readback_ok agrees with a fresh reader",
              p["readback_ok"] is True and fresh["version"] == p["applied"]["version"])

    await with_client(body, tmpdir, stores=stores)


# ===========================================================================
# D. Double-submit on the new path
# ===========================================================================

async def t_double_submit(tmpdir):
    stores, _ = _mkstores(tmpdir, "dbl")

    async def body(client, stores, _):
        ds = (await (await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                                       json={"name": "d"})).json())["dataset"]
        doc = (await (await client.post(
            "/admin/knowledge/document/add", headers=AUTH,
            json={"dataset_id": ds["id"], "title": "t", "text": "hello world x"})).json()
        )["document"]
        d1 = await client.post("/admin/knowledge/document/delete", headers=AUTH,
                               json={"id": doc["id"], "confirm": True})
        d2 = await client.post("/admin/knowledge/document/delete", headers=AUTH,
                               json={"id": doc["id"], "confirm": True})
        check("R3-18 document delete double-submit: 2nd no double-apply",
              d1.status == 200 and d2.status in (400, 404), (d1.status, d2.status))

        s1 = await client.post("/admin/knowledge/dataset/delete", headers=AUTH,
                               json={"id": ds["id"], "confirm": ds["id"]})
        s2 = await client.post("/admin/knowledge/dataset/delete", headers=AUTH,
                               json={"id": ds["id"], "confirm": ds["id"]})
        check("R3-19 dataset delete double-submit: 2nd no double-apply",
              s1.status == 200 and s2.status in (400, 404), (s1.status, s2.status))

        stores.memory.save("profile_fact", "d", "v")
        items = (await (await client.get("/admin/memory/items", headers=AUTH)).json())
        mid = [i for i in items["items"] if i["key"] == "d"][0]["id"]
        m1 = await client.post("/admin/memory/delete", headers=AUTH,
                               json={"id": mid, "confirm": True})
        m2 = await client.post("/admin/memory/delete", headers=AUTH,
                               json={"id": mid, "confirm": True})
        check("R3-20 memory delete double-submit: 2nd -> 404, no double-apply",
              m1.status == 200 and m2.status == 404, (m1.status, m2.status))

        stores.memory.save("habit", "h", "short")
        c1 = await (await client.post("/admin/memory/clear-category", headers=AUTH,
                                      json={"entity": "habit", "confirm": "habit"})).json()
        c2 = await (await client.post("/admin/memory/clear-category", headers=AUTH,
                                      json={"entity": "habit", "confirm": "habit"})).json()
        check("R3-21 category clear double-submit idempotent",
              c1["removed"] == 1 and c2["removed"] == 0,
              (c1["removed"], c2["removed"]))

    await with_client(body, tmpdir, stores=stores)


# ===========================================================================
# E. New validation rules — attacked from the operator seat
# ===========================================================================

def _mk_policy(base=None, **over):
    p = json.loads(json.dumps(base or {}))
    return p


async def t_validation(tmpdir):
    stores, _ = _mkstores(tmpdir, "val")

    async def body(client, stores, _):
        # --- non-string name / top_k ---
        for bad in ({"a": 1}, ["x"], 123, None, True):
            r = await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                                  json={"name": bad})
            check("R3-22 dataset name %r -> 400" % (bad,), r.status == 400, r.status)
        ds = (await (await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                                       json={"name": "ok"})).json())["dataset"]
        for bad in ("abc", {}, [1], 1.5):
            r = await client.post("/admin/knowledge/search", headers=AUTH,
                                  json={"query": "x", "top_k": bad})
            check("R3-23 top_k %r -> 400" % (bad,), r.status == 400, r.status)
        r = await client.post("/admin/knowledge/search", headers=AUTH,
                              json={"query": "x", "top_k": True})
        check("R3-23b top_k=true is rejected (bool is not an int)",
              r.status == 400, (r.status, (await r.text())[:80]))

        # --- residual type confusion on the OTHER dataset fields (name was fixed,
        #     description / tags[] / source_uri were not type-guarded at the API) ---
        r = await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                              json={"name": "x", "description": {"a": 1}})
        check("R3-45 dataset description non-string (dict) -> 4xx reject",
              r.status == 400, (r.status, (await r.text())[:90]))
        r = await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                              json={"name": "x", "tags": [{"a": 1}]})
        check("R3-46 dataset tags element non-string (dict) -> 4xx reject",
              r.status == 400, (r.status, (await r.text())[:90]))
        r = await client.post("/admin/knowledge/document/add", headers=AUTH,
                              json={"dataset_id": ds["id"], "title": "ok",
                                    "text": "ok body", "source_uri": {"a": 1}})
        check("R3-47 document source_uri non-string (dict) -> 4xx reject",
              r.status == 400, (r.status, (await r.text())[:90]))

        # --- lone surrogates in every ingestion field ---
        for label, payload in (
                ("name", {"name": "a\ud800b"}),
                ("description", {"name": "x", "description": "d\ud800"}),
                ("tags", {"name": "x", "tags": ["t\ud800"]})):
            r = await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                                  json=payload)
            check("R3-24 lone surrogate in %s -> 4xx (not 500)" % label,
                  r.status == 400, r.status)
        for i, (label, payload) in enumerate([
            ("title", {"dataset_id": ds["id"], "title": "t\ud800", "text": "body 0"}),
            ("text", {"dataset_id": ds["id"], "title": "ok", "text": "b\ud800dy 1"}),
            ("source_uri", {"dataset_id": ds["id"], "title": "ok",
                            "text": "body u2", "source_uri": "u\ud800"})]):
            r = await client.post("/admin/knowledge/document/add", headers=AUTH,
                                  json=payload)
            check("R3-25 lone surrogate in %s -> 4xx (not 500)" % label,
                  r.status == 400, (r.status, (await r.text())[:90]))

        # --- control characters ---
        r = await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                              json={"name": "a\nb"})
        check("R3-26 newline in dataset name -> 400", r.status == 400, r.status)
        stores.memory.save("profile_fact", "cf", "v0")
        mid = [i for i in stores.memory.list_items() if i["key"] == "cf"][0]["id"]
        for bad in ("a\nb", "a\x00b", "a\tb", "a\x7fb"):
            r = await client.post("/admin/memory/edit", headers=AUTH,
                                  json={"id": mid, "value": bad})
            check("R3-27 control char %r in memory value -> 400" % bad,
                  r.status == 400, r.status)

        # --- policy: newlines in ANY section ---
        cases = {
            "persona.name": {"persona": {"name": "A\nB"}},
            "language.chinese_default_policy": {"language": {"chinese_default_policy": "A\nB"}},
            "teaching.correction_style": {"teaching": {"correction_style": "A\nB"}},
            "teaching.canonical_spelling_rules[0]":
                {"teaching": {"canonical_spelling_rules": ["A\nB"]}},
            "teaching.speed_levels.slow":
                {"teaching": {"speed_levels": {"slow": "A\nB", "normal": "n", "fast": "f"}}},
            "activities.PRACTICE_CONVERSATION":
                {"activities": {"PRACTICE_CONVERSATION": "A\nB"}},
            "limits.closing_followup": {"limits": {"closing_followup": "A\nB"}},
        }
        for label, pol in cases.items():
            pv = await (await client.post("/admin/policy/preview", headers=AUTH,
                                          json={"policy": pol})).json()
            check("R3-28 newline in policy %s rejected by preview" % label,
                  pv.get("valid") is False and pv.get("errors"),
                  pv.get("valid"))
            ap = await client.post("/admin/policy/apply", headers=AUTH,
                                   json={"policy": pol, "confirm": True})
            check("R3-28b newline in policy %s -> 400 apply" % label,
                  ap.status == 400, ap.status)

        # --- invisible-only fields ---
        for invis in ("\u200b\u200c\u200d", "\u00ad", "\ufeff"):
            pv = await (await client.post("/admin/policy/preview", headers=AUTH,
                                          json={"policy": {"persona": {"name": invis}}})
                        ).json()
            check("R3-29 invisible-only name %r rejected" % invis,
                  pv.get("valid") is False, pv.get("valid"))

        # --- errors cap + no value echo ---
        big = {"policy": {("k%03d" % i): 1 for i in range(300)}}
        pv = await (await client.post("/admin/policy/preview", headers=AUTH,
                                      json=big)).json()
        check("R3-30 preview errors list is capped at 50",
              len(pv.get("errors") or []) <= 50, len(pv.get("errors") or []))
        ap = await client.post("/admin/policy/apply", headers=AUTH,
                               json=dict(big, confirm=True))
        aj = await ap.json()
        check("R3-30b apply errors list is capped at 50",
              ap.status == 400 and len(aj.get("errors") or []) <= 50,
              len(aj.get("errors") or []))

        marker = "SECRET_VALUE_" + "Z" * 40
        ap = await client.post("/admin/policy/apply", headers=AUTH,
                               json={"policy": {"persona": {"name": marker}},
                                     "confirm": True})
        aj = await ap.json()
        check("R3-31 validation errors never echo a submitted VALUE",
              marker not in json.dumps(aj), json.dumps(aj)[:200])

    await with_client(body, tmpdir, stores=stores)


# ===========================================================================
# F. Input-safety re-check on the new paths + round-trip inert data
# ===========================================================================

XSS_TITLE = "<img src=x onerror=alert(1)>\"'\\"
XSS_DS = "<script>alert('ds')</script>"
XSS_URI = "javascript:alert(1)//uri\"><svg/onload=alert(2)>"
XSS_TEXT = "line1 </script><script>alert(3)</script> & <b>b</b>\n\nsecond para \u202eRTL"
WEIRD = ("emoji \U0001f469\u200d\U0001f4bb ZWJ, combining e\u0301, zero\u200bwidth, "
         "arabic \u0645\u0631\u062d\u0628\u0627, hebrew \u05e9\u05dc\u05d5\u05dd")  # 66 chars > cap
WEIRD_SHORT = "e\u0301 \U0001f469\u200d\U0001f4bb \u200b \u0645\u0631 \u05e9\u05dc"   # <60, same classes


async def t_input_safety(tmpdir):
    stores, _ = _mkstores(tmpdir, "inp")

    async def body(client, stores, _):
        # round-trip inert data with script-like + weird unicode metadat
        ds = (await (await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                                       json={"name": XSS_DS})).json())["dataset"]
        doc = (await (await client.post(
            "/admin/knowledge/document/add", headers=AUTH,
            json={"dataset_id": ds["id"], "title": XSS_TITLE, "text": XSS_TEXT,
                  "source_uri": XSS_URI})).json())["document"]
        got = (await (await client.get(
            "/admin/knowledge/dataset/%s/documents" % ds["id"], headers=AUTH)).json()
        )["documents"][0]
        check("R3-32 doc title (img-onerror) round-trips exact inert bytes",
              got["title"] == XSS_TITLE, got["title"])
        check("R3-33 source_uri (javascript:+svg) round-trips exact inert bytes",
              got["source"]["uri"] == XSS_URI, got["source"].get("uri"))
        r = await client.get("/admin/knowledge/datasets", headers=AUTH)
        check("R3-34 datasets GET is application/json",
              "application/json" in r.headers.get("Content-Type", ""),
              r.headers.get("Content-Type"))

        # weird-unicode + emoji/ZWJ/combining/RTL/zero-width in every new field
        ds2 = await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                                json={"name": WEIRD, "description": WEIRD,
                                      "tags": [WEIRD]})
        check("R3-35 unicode/RTL/emoji/ZWJ/combining/ZW only -> accepted",
              ds2.status == 200, (ds2.status, (await ds2.text())[:120]))
        d2 = await ds2.json()
        check("R3-35b a >cap unicode name is capped to MAX_NAME_LEN (60)",
              len(d2["dataset"]["name"]) == 60
              and d2["dataset"]["name"] == WEIRD[:60], len(d2["dataset"]["name"]))
        ds3 = await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                                json={"name": WEIRD_SHORT})
        check("R3-35c a sub-cap unicode name round-trips byte-exact",
              (await ds3.json())["dataset"]["name"] == WEIRD_SHORT,
              (await ds3.json()).get("dataset", {}).get("name"))

        stores.memory.save("profile_fact", "w", "v0")
        mid = [i for i in stores.memory.list_items() if i["key"] == "w"][0]["id"]
        e = await client.post("/admin/memory/edit", headers=AUTH,
                              json={"id": mid, "value": WEIRD})
        ej = await e.json()
        check("R3-36 memory weird-unicode value round-trips inert",
              e.status == 200 and ej["item"]["value"] == WEIRD,
              (e.status, ej.get("item", {}).get("value")))

        # malformed ids in path params -> clean 4xx, no leak
        for pid in ("%2e%2e%2f%2e%2e%2fetc%2fpasswd", "x" * 400, "%00%01%02",
                    "\u202e\u0000"):
            rr = await client.get("/admin/memory/item/" + pid, headers=AUTH)
            txt = await rr.text()
            check("R3-37 weird memory path id -> clean 4xx, no path leak (%r)" % pid[:20],
                  rr.status in (400, 404) and "/Users/" not in txt
                  and "/etc/" not in txt and "Traceback" not in txt, rr.status)
        rr = await client.get("/admin/knowledge/document/" + "%2e%2e%2fpasswd",
                              headers=AUTH)
        txt = await rr.text()
        check("R3-38 weird doc path id -> clean 4xx, no path leak",
              rr.status in (400, 404) and "/etc/" not in txt, rr.status)

        # duplicate JSON keys / unknown fields
        r = await client.post("/admin/memory/edit", headers=AUTH,
                              data='{"id": "%s", "id": "mem_bogus", "value": "z"}'
                              % mid)
        check("R3-39 duplicate JSON keys last-wins, no 500",
              r.status in (400, 404), r.status)
        r = await client.post("/admin/memory/edit", headers=AUTH,
                              json={"id": mid, "value": "v9", "role": "admin",
                                    "__proto__": {"x": 1}})
        check("R3-40 unknown/extra fields ignored", r.status == 200, r.status)

        # malformed JSON / non-object / oversized body
        r = await client.post("/admin/memory/edit", headers=AUTH, data="{not json")
        check("R3-41 malformed JSON -> 400",
              r.status == 400 and (await r.json()).get("error") == "invalid_json",
              r.status)
        r = await client.post("/admin/memory/edit", headers=AUTH, data="[1,2,3]")
        check("R3-42 non-object JSON -> 400", r.status == 400, r.status)
        h = dict(AUTH); h["Content-Type"] = "application/json"
        r = await client.post("/admin/knowledge/document/add", headers=h,
                              data=json.dumps({"dataset_id": ds["id"], "title": "big",
                                               "text": "a" * 70000}))
        check("R3-43 >64KiB body -> 413", r.status == 413, r.status)

        # a 500/400 body must be honest JSON, no traceback/path/'success'
        r = await client.post("/admin/knowledge/dataset/create", headers=AUTH,
                              json={"name": {"a": 1}})
        txt = await r.text()
        check("R3-44 a 400 body is JSON with no traceback/path/'success'",
              r.status == 400 and "application/json" in r.headers.get("Content-Type", "")
              and "Traceback" not in txt and "/Users/" not in txt
              and "readback_ok" not in txt, txt[:120])

    await with_client(body, tmpdir, stores=stores)


# ===========================================================================

async def amain():
    tmp = tempfile.mkdtemp(prefix="redh-r3-")
    t_ui_static()
    await t_persist_sweep(tmp)
    await t_readback_success(tmp)
    await t_double_submit(tmp)
    await t_validation(tmp)
    await t_input_safety(tmp)

    total = len(RESULTS)
    failed = [r for r in RESULTS if not r[1]]
    print("=" * 74)
    print("RED_H_R3_CROSSCHECK: %d checks, %d PASS, %d FAIL"
          % (total, total - len(failed), len(failed)))
    for name, _, detail in failed:
        print("  FINDING/FAIL: %s %s" % (name, detail))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
