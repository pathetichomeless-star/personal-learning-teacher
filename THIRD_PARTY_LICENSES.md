# THIRD-PARTY LICENSES AND ATTRIBUTION

Scope: components that this repository contains, bundles, or consumes at runtime, with the
licence name and the obligations **as mechanically read from the licence texts** during the
ADMIN-1/ADMIN-0 audit (2026-10-07) and updated at the PLT release integration (2026-10-16).
This file is factual attribution only — it is not legal advice, and it does not choose a
licence for anyone else's code.

> **OUR OWN CODE — MIT.** Our own code (this repository's `gateway/`, `modules/`, `tools/`,
> admin surface, and the classroom application code under `client/src/classroom/` and related
> files) is licensed under the **MIT License** — see [LICENSE](LICENSE). The previous
> “PENDING PRODUCT OWNER” status is resolved as of this release.

## 1. Bundled / forked in this repository

### py-xiaozhi (desktop client) — **MIT**
- Local path: `client/` (monorepo import; canonical source in this repo; upstream `https://github.com/huangjunsen0406/py-xiaozhi`)
- Evidence: local `client/LICENSE` (MIT, "Copyright (c) 2025 Junsen") and `pyproject.toml` licence field.
- Obligation: retain the copyright notice and the permission notice in all copies or substantial
  portions. → the upstream `LICENSE` file is **kept verbatim** at `client/LICENSE`; do not edit it.
- Upstream documentation site sources are included under `client/documents/`.

### Speech recognition models — **Apache-2.0**
- Local paths: `client/models/en/**`, `client/models/zh/**` (sherpa-onnx ONNX models + tokens).
- Evidence: per-model `README.md` (licence field) + upstream source (ModelScope, pkufool).
- Obligation: retain notices; models are redistributed here as part of the fork's runtime assets.

## 2. Dependencies (NOT vendored — consumed as pinned/published artefacts)

### PySide6 / Qt — **LGPLv3 (or commercial)**
- Used by the desktop client at runtime. This repository distributes **source only**.
- If you redistribute a **built binary** (e.g. the macOS `.app`), you must satisfy LGPLv3:
  include the licence texts and enable replacement of the dynamically linked libraries.
- Obligation recorded 2026-10-16 (previously missing); see `docs/` for build notes.

### sherpa-onnx — **Apache-2.0** (Python/CLI dependency; consumed, not vendored)

### xinnan-tech/xiaozhi-esp32-server (legacy server + embedded manager-api) — **MIT**
- Used as container images only; not copied into this repository.

### word-master — **Apache-2.0** (runs as an independent local image; not part of this repository)

### English-learning-workbench — **NOT INCLUDED — explicit exclusion**
- Its content is MIT + explicit exclusion clause; **LAN use only**; the `/ielts/` path must not be
  published. The application body has **no licence file** → never redistributed here.

### libopus / webrtc_apm — **excluded from this release**
- Native binaries under `client/libs/**` are **not distributed** with this release tree
  (licence texts not closed out); see README “not included”.

### Live2D Cubism — **not included**
- Proprietary runtime assets (vendor files) are **not distributed** in this repository;
  obtaining and using them is subject to Live2D's own licence terms.

### Python runtime dependencies
- Principal packages referenced by `client/requirements.txt` / gateway requirements:
  aiohttp (Apache-2.0), websockets (BSD), numpy (BSD), cryptography (Apache-2.0/BSD),
  opuslib (BSD), pynput (LGPLv3), pyperclip (BSD), mutagen (GPL-2.0 — runtime library only,
  not vendored or modified), pendulum (MIT), psutil (BSD). Full list: see requirements files.

## 3. Runtime images we only operate (not redistributed)
`mysql`, `redis`, `nginx`, `python` images and a private NAS platform image
(`<platform-image>`). These are pulled and run as published images; their own licence metadata
governs. They are **not** redistributed by this project.

## 4. Documentation / reference material
- The upstream XiaoZhi sample configuration previously carried under `docs/reference/` is
  **not included** in this release (reference-only artefact; excluded during sanitisation).

## 5. Rules for future dependencies
1. Any new dependency (library, image, dataset, model) must be recorded in this file **in the same
   commit** that introduces it, with: name, version/pin, licence, upstream URL, where it is used,
   obligations.
2. Never modify an upstream licence file.
3. Never vendor the English-workbench content.
4. Our own licence is **MIT** (see `LICENSE`); keep this file and `NOTICE.md` in sync with it.
