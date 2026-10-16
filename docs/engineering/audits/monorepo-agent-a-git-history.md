# MONOREPO MIGRATION — AGENT A: GIT / HISTORY AUDIT (READ ONLY)

- Date: 2026-10-07
- Auditor: Agent A (independent, read-only)
- Repository root: `<project-root>` (root repo, branch `main`)
- Source repo under audit: `<project-root>/py-xiaozhi` (local shallow clone, pending retirement)
- Bundle under audit: `admin0-backups/py-xiaozhi-pre-monorepo.bundle`
- Constraint honoured: no file, git state, container or config was modified. The only file written is this report.

---

## 1. Pre-migration py-xiaozhi state

Commands:

```
git -C py-xiaozhi rev-parse HEAD
git -C py-xiaozhi tag -l
git -C py-xiaozhi status --porcelain | wc -l
git -C py-xiaozhi rev-parse --is-shallow-repository
```

Output:

```
fed48362c65b92a9fb8464aa51ebff4488979d2c
r1f-client-accepted
v2.1.2
       0
true
```

Findings:
- `HEAD` = `fed48362c65b92a9fb8464aa51ebff4488979d2c` — MATCHES the required accepted commit.
- Tag `r1f-client-accepted` exists in the source repo.
- Worktree clean: `status --porcelain | wc -l` = `0`.
- Source repo is a shallow clone (`is-shallow-repository` = `true`) — see section 7.

---

## 2. Git bundle validity

Commands:

```
stat -f 'mode=%Sp size=%z bytes name=%N' admin0-backups/py-xiaozhi-pre-monorepo.bundle
ls -la admin0-backups/py-xiaozhi-pre-monorepo.bundle
git -C py-xiaozhi bundle verify <project-root>/admin0-backups/py-xiaozhi-pre-monorepo.bundle
git bundle list-heads <project-root>/admin0-backups/py-xiaozhi-pre-monorepo.bundle
```

Output:

```
mode=-rw------- size=61062573 bytes name=admin0-backups/py-xiaozhi-pre-monorepo.bundle
-rw-------@ 1 ming  staff  61062573 10月  7 12:31 admin0-backups/py-xiaozhi-pre-monorepo.bundle

<project-root>/admin0-backups/py-xiaozhi-pre-monorepo.bundle is okay
The bundle contains these 2 refs:
fed48362c65b92a9fb8464aa51ebff4488979d2c refs/heads/main
b12fd407c0775b8d076ad303b5426edbd2b9d348 refs/tags/r1f-client-accepted
The bundle records a complete history.
The bundle uses this hash algorithm: sha1

fed48362c65b92a9fb8464aa51ebff4488979d2c refs/heads/main
b12fd407c0775b8d076ad303b5426edbd2b9d348 refs/tags/r1f-client-accepted
```

Findings:
- Bundle verifies OK against the source repo (`... is okay`).
- File mode `-rw-------` (owner-only, 0600) — appropriate for a private migration backup.
- Size: 61,062,573 bytes (~58 MiB).
- Contains exactly 2 refs: `refs/heads/main` → `fed4836…` and `refs/tags/r1f-client-accepted` → tag object `b12fd407…`.
- Verifier reports "The bundle records a complete history" (i.e. all ancestry captured by the bundle is self-contained; `v2.1.2` was intentionally not included in the bundle ref set).
- Hash algorithm: sha1.
- Note: the tag object recorded in the bundle (`b12fd407c0775b8d076ad303b5426edbd2b9d348`) is byte-identical to the source repo's tag object for `r1f-client-accepted` — the bundle is a faithful capture of the source at freeze time.

---

## 3. Subtree import preserved the locally available history

Commands:

```
git log --graph --oneline -8
git rev-list --parents -n 1 HEAD
git log --format='%H %P %s'
git merge-base --is-ancestor fed48362c65b92a9fb8464aa51ebff4488979d2c HEAD
git merge-base --is-ancestor 9bfc807d368cccac71af8d9f7042ab6b5af92030 HEAD
```

Output:

```
* 6ffabc4 docs: organize approved documentation (admin0, admin1, engineering, reference) + tools
* b379cec modules: scaffold ownership boundaries (adapters, intent, memory, knowledge)
* 1abc74b deploy: import sanitized legacy-stack deployment source
* 561bd80 gateway: accepted R-1f baseline import (source-only, no runtime modification)
*   3e22a4d client: import py-xiaozhi source with locally available history
|\
| * fed4836 feat(client): freeze accepted R-1f rev-9 playout telemetry instrumentation
| * 9bfc807 chore: release v2.1.2
* 303d0d3 admin0: monorepo foundation — share boundary, attribution, approved documentation

6ffabc4bd6075181700730316ccf3855c6a89208 b379cecacd8413961e4ce1b6ebb60319502471b0
```

Import commit (merge) parents:

```
3e22a4de0c3f7a3393526a7092c545ed9fb0528f 303d0d343ac98d20dd7c6dc8eebea476c3ac8a09 fed48362c65b92a9fb8464aa51ebff4488979d2c
```

Ancestry:

```
fed4836 IS ancestor of HEAD
9bfc807 IS ancestor of HEAD
```

Findings:
- `3e22a4d` is a merge commit whose parents are `303d0d3…` (the monorepo initial commit) and `fed4836…` — the import commit's second parent IS `fed48362c65b92a9fb8464aa51ebff4488979d2c`. ✔
- `fed48362c65b92a9fb8464aa51ebff4488979d2c` is reachable from `HEAD` (`merge-base --is-ancestor` succeeded). ✔
- SHA unchanged vs source: source `git -C py-xiaozhi rev-parse HEAD` = `fed48362c65b92a9fb8464aa51ebff4488979d2c`, identical to the commit reachable in the root repo (`git log` shows the same 40-char SHA). No rewriting of the accepted commit. ✔

Additional provenance check (tree fidelity):

```
git rev-parse HEAD:client                                      -> 425589fbae0e5e7f34d4a4b3718d1be3bb56e6d9
git rev-parse fed48362c65b92a9fb8464aa51ebff4488979d2c^{tree}   -> 425589fbae0e5e7f34d4a4b3718d1be3bb56e6d9
git diff --stat HEAD:client fed4836…                           -> (empty)
```

- The imported `client/` subtree tree-SHA equals the source `fed4836` root tree-SHA exactly (`425589fb…`), and `git diff` between them is empty. The client content was imported losslessly as a subtree.

---

## 4. No squash / rebase / reset / history rewrite

Commands:

```
git log --graph --oneline -8
git -C py-xiaozhi reflog | head -20
git rev-list --parents -n 1 3e22a4d
git cat-file -t 9bfc807d368cccac71af8d9f7042ab6b5af92030
```

Output:

```
*   3e22a4d client: import py-xiaozhi source with locally available history
|\
| * fed4836 feat(client): freeze accepted R-1f rev-9 playout telemetry instrumentation
| * 9bfc807 chore: release v2.1.2
* 303d0d3 admin0: monorepo foundation — share boundary, attribution, approved documentation

fed4836 HEAD@{0}: commit: feat(client): freeze accepted R-1f rev-9 playout telemetry instrumentation
9bfc807 HEAD@{1}: clone: from https://github.com/huangjunsen0406/py-xiaozhi.git

9bfc807d368cccac71af8d9f7042ab6b5af92030 (type: commit)
```

Root repo reflog:

```
6ffabc4 HEAD@{0}: commit: docs: organize approved documentation (admin0, admin1, engineering, reference) + tools
b379cec HEAD@{1}: commit: modules: scaffold ownership boundaries (adapters, intent, memory, knowledge)
1abc74b HEAD@{2}: commit: deploy: import sanitized legacy-stack deployment source
561bd80 HEAD@{3}: commit: gateway: accepted R-1f baseline import (source-only, no runtime modification)
3e22a4d HEAD@{4}: commit (merge): client: import py-xiaozhi source with locally available history
303d0d3 HEAD@{5}: commit (initial): admin0: monorepo foundation — share boundary, attribution, approved documentation
```

Findings:
- The import is a genuine two-parent **merge** (`3e22a4d`), not a squashed or cherry-picked single commit. The root reflog explicitly labels it `HEAD@{4}: commit (merge)`. ✔
- Source reflog shows only two entries: the original `clone` and the accepted `commit` — NO `reset`, `rebase`, `checkout`-rewrite, or `reflog` anomalies. ✔
- The upstream/source commit `9bfc807d368cccac71af8d9f7042ab6b5af92030` is present in the root repo (type `commit`) and reachable from `HEAD`. ✔

---

## 5. No nested `client/.git` or other nested repositories

Commands:

```
find client -name .git | wc -l
find client gateway modules deploy tools docs -name .git
find . -mindepth 2 -name .git
find . -mindepth 2 -name .gitmodules
ls -la .gitmodules
find client gateway modules deploy tools docs -name '.git*'
```

Output:

```
       0
(no output)
./py-xiaozhi/.git
ls: .gitmodules: No such file or directory
client/.gitignore
client/.github
client/documents/.gitignore
```

Findings:
- `find client -name .git | wc -l` = `0`. ✔
- No nested `.git` (directory or file stub) anywhere in the imported trees `client gateway modules deploy tools docs`. ✔
- The only nested `.git` in the whole working tree is `./py-xiaozhi/.git` — the source repo itself, which is present only until retirement and is not part of the imported trees.
- No `.gitmodules` anywhere (no submodule configuration).
- The `.git*` matches inside `client/` are ordinary tracked content (`.gitignore` files and a `.github` directory), NOT git stubs/worktrees/submodules.

---

## 6. Root tag correctness

Commands:

```
git tag -l
git rev-list -n1 r1f-client-accepted
git for-each-ref refs/tags --format='%(refname) %(objecttype) %(objectname) %(*objectname)'
git rev-parse refs/tags/r1f-client-accepted
git rev-parse refs/tags/r1f-client-accepted^{}
git rev-parse refs/tags/v2.1.2
git rev-parse refs/tags/v2.1.2^{}
git tag -n99 -l
```

Output:

```
r1f-client-accepted
v2.1.2

fed48362c65b92a9fb8464aa51ebff4488979d2c

refs/tags/r1f-client-accepted tag 8313e16838d8959e5a479fae1f83ed3a6600753a fed48362c65b92a9fb8464aa51ebff4488979d2c
refs/tags/v2.1.2 tag b817215a9967cb996a8d782c5b5dbc7d2e68a9c1 9bfc807d368cccac71af8d9f7042ab6b5af92030

8313e16838d8959e5a479fae1f83ed3a6600753a   (tag object, root repo)
fed48362c65b92a9fb8464aa51ebff4488979d2c   (peeled -> commit)
b817215a9967cb996a8d782c5b5dbc7d2e68a9c1   (tag object, root repo)
9bfc807d368cccac71af8d9f7042ab6b5af92030   (peeled -> commit)

r1f-client-accepted R-1f accepted client source (imported into the monorepo; commit unchanged)
v2.1.2          v2.1.2
```

Findings:
- `git rev-list -n1 r1f-client-accepted` = `fed48362c65b92a9fb8464aa51ebff4488979d2c`. ✔ (points at the accepted commit)
- `r1f-client-accepted` is an **annotated** tag; tag object SHA (root repo) = `8313e16838d8959e5a479fae1f83ed3a6600753a`, peeled → `fed4836…`.
- `v2.1.2` is annotated; tag object SHA = `b817215a9967cb996a8d782c5b5dbc7d2e68a9c1`, peeled → `9bfc807…`.

---

## 7. Shallow boundary handling (disclosure)

Commands:

```
git rev-parse --is-shallow-repository
git -C py-xiaozhi rev-parse --is-shallow-repository
cat .git/shallow
cat py-xiaozhi/.git/shallow
git rev-list --parents -n 1 9bfc807d368cccac71af8d9f7042ab6b5af92030
```

Output:

```
true
true
9bfc807d368cccac71af8d9f7042ab6b5af92030
9bfc807d368cccac71af8d9f7042ab6b5af92030
9bfc807d368cccac71af8d9f7042ab6b5af92030      (no parents listed -> boundary commit)
```

Findings (stated plainly):
- BOTH repos are shallow repositories.
- `.git/shallow` in the root repo and in `py-xiaozhi` list exactly one boundary commit: `9bfc807d368cccac71af8d9f7042ab6b5af92030`.
- `9bfc807` has **no parent recorded** (`git rev-list --parents` returned only its own SHA). This is the expected consequence of a shallow clone — it is a **documented boundary, not a defect**.
- The source was a shallow clone (`clone: from https://github.com/huangjunsen0406/py-xiaozhi.git` in the reflog), so only the locally available history existed to import. The migration preserved **exactly** the locally available history: 2 source commits (`fed4836`, `9bfc807`) carried into the monorepo unchanged; nothing before the shallow boundary was fabricated or dropped, and the upstream `v2.1.2` release commit `9bfc807` is the deepest available commit in both repos.

---

## 8. Tags imported automatically

Commands:

```
git tag -l
git for-each-ref refs/tags --format='%(refname) %(objecttype) %(objectname) %(*objectname)'
git -C py-xiaozhi for-each-ref refs/tags --format='%(refname) %(objecttype) %(objectname) %(*objectname)'
git -C py-xiaozhi tag -n99 -l
```

Root repo tags:

```
refs/tags/r1f-client-accepted tag 8313e16838d8959e5a479fae1f83ed3a6600753a fed48362c65b92a9fb8464aa51ebff4488979d2c
refs/tags/v2.1.2             tag b817215a9967cb996a8d782c5b5dbc7d2e68a9c1 9bfc807d368cccac71af8d9f7042ab6b5af92030
```

Source repo tags:

```
refs/tags/r1f-client-accepted tag b12fd407c0775b8d076ad303b5426edbd2b9d348 fed48362c65b92a9fb8464aa51ebff4488979d2c
refs/tags/v2.1.2             tag b817215a9967cb996a8d782c5b5dbc7d2e68a9c1 9bfc807d368cccac71af8d9f7042ab6b5af92030
```

Findings:
- `v2.1.2` DID come along into the monorepo.
- `v2.1.2` points at the SAME commit in both repos: peeled = `9bfc807d368cccac71af8d9f7042ab6b5af92030`. Its tag object SHA is also identical in both repos (`b817215a…`), i.e. imported verbatim.
- **Disclosure:** `r1f-client-accepted` peels to the SAME commit (`fed4836…`) in both repos, but its annotated **tag object SHA differs** because the tag was re-created in the monorepo:
  - source : `b12fd407c0775b8d076ad303b5426edbd2b9d348` — message `R-1f accepted client source (ADMIN-0 Phase B freeze) — commit fed4836`
  - root   : `8313e16838d8959e5a479fae1f83ed3a6600753a` — message `R-1f accepted client source (imported into the monorepo; commit unchanged)`
  - This is expected behaviour when an annotated tag is re-tagged: the tag object's metadata/message changed, but the **target commit SHA is byte-identical**. This is NOT a commit history rewrite and does not affect any acceptance criterion.

---

## 9. Root repo facts

Commands:

```
git -C <project-root> branch --show-current
git -C <project-root> remote -v
git -C <project-root> rev-parse HEAD
git log --format='%H %P %s'
git rev-list --all --count      # root
git -C py-xiaozhi rev-list --all --count
```

Output:

```
main
(no output — no remotes configured)
6ffabc4bd6075181700730316ccf3855c6a89208

6ffabc4bd6075181700730316ccf3855c6a89208 b379cecacd8413961e4ce1b6ebb60319502471b0 docs: organize approved documentation (admin0, admin1, engineering, reference) + tools
b379cecacd8413961e4ce1b6ebb60319502471b0 1abc74bef5d0888248e89831ba9b276eda9ca5c5 modules: scaffold ownership boundaries (adapters, intent, memory, knowledge)
1abc74bef5d0888248e89831ba9b276eda9ca5c5 561bd8085dcf75fc38f584ee792bc69cbde65c76 deploy: import sanitized legacy-stack deployment source
561bd8085dcf75fc38f584ee792bc69cbde65c76 3e22a4de0c3f7a3393526a7092c545ed9fb0528f gateway: accepted R-1f baseline import (source-only, no runtime modification)
3e22a4de0c3f7a3393526a7092c545ed9fb0528f 303d0d343ac98d20dd7c6dc8eebea476c3ac8a09 fed48362c65b92a9fb8464aa51ebff4488979d2c client: import py-xiaozhi source with locally available history
303d0d343ac98d20dd7c6dc8eebea476c3ac8a09  admin0: monorepo foundation — share boundary, attribution, approved documentation
fed48362c65b92a9fb8464aa51ebff4488979d2c 9bfc807d368cccac71af8d9f7042ab6b5af92030 feat(client): freeze accepted R-1f rev-9 playout telemetry instrumentation
9bfc807d368cccac71af8d9f7042ab6b5af92030  chore: release v2.1.2

root reachable commits: 8
source reachable commits: 2
```

Findings:
- Branch: `main`. ✔
- `git remote -v`: EMPTY — no remotes configured (local-only monorepo, as intended). ✔
- `HEAD` = `6ffabc4bd6075181700730316ccf3855c6a89208` (valid; `rev-parse --verify` would succeed).
- Commit chain (SHAs, parents): 6 root-only commits forming linear history `303d0d3 → 3e22a4d → 561bd80 → 1abc74b → b379cec → 6ffabc4`, plus the merged client history `9bfc807 → fed4836` grafted in at `3e22a4d`. Total reachable = 8 (= 6 root-side + 2 imported), consistent with the source's 2 commits.
- Root working tree is clean (`git status --porcelain | wc -l` = `0`) at the time of this audit, before this report file was created.

---

## Overall summary

| # | Check | Result |
|---|-------|--------|
| 1 | py-xiaozhi HEAD = `fed4836…`, tag exists, clean | PASS |
| 2 | Bundle verifies OK, lists 2 refs, complete history, 0600, ~58 MiB | PASS |
| 3 | Import is a merge with parent `fed4836…`; SHA unchanged; subtree tree-SHA identical | PASS |
| 4 | No squash/rebase/reset; merge has 2 parents; `9bfc807` present | PASS |
| 5 | No `client/.git`; no nested `.git`/`.git` file stubs; no `.gitmodules` | PASS |
| 6 | `rev-list -n1 r1f-client-accepted` = `fed4836…`; annotated tag object recorded | PASS |
| 7 | Shallow boundary `9bfc807` documented (not a defect) | PASS (disclosed) |
| 8 | `v2.1.2` imported, points at same commit; `r1f-client-accepted` re-tagged (same commit) | PASS (disclosed) |
| 9 | Branch `main`, no remotes, valid HEAD, 8 reachable commits | PASS |

Disclosures (no defects):
- Source was a shallow clone; only locally available history (2 commits) was imported. Boundary commit `9bfc807d368cccac71af8d9f7042ab6b5af92030` has no parent — expected.
- `r1f-client-accepted` annotated tag object SHA changed (`b12fd407…` → `8313e168…`) because the tag was re-created with a new message; the target commit `fed4836…` is byte-identical.

No defect meeting the FAIL criteria (unreachable accepted commit / rewritten SHA / nested `.git` / squashed import / invalid bundle) was found.

A_GIT_HISTORY = PASS