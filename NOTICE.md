# NOTICE

This repository is the source tree for **个人学习老师 / Personal Learning Teacher** —
an AI English-learning & classroom assistant built on the “小智 AI 学生课堂” codebase.

## License

Our own code (including this repository’s `gateway/`, `modules/`, `tools/`, admin
surface and the classroom application under `client/`) is licensed under the
**MIT License** — see `LICENSE`.

The **py-xiaozhi fork** under `client/` is MIT, Copyright (c) 2025 Junsen,
upstream `https://github.com/huangjunsen0406/py-xiaozhi`. The upstream MIT licence
text is retained verbatim at `client/LICENSE` (do not edit it).

## Third-party components

See `THIRD_PARTY_LICENSES.md` for the full, mechanically verified attribution list
and the obligations that apply to each component.

## Notes on this release tree

- 本仓库为公开的 integration 发布树；部分能力（真实语音链路、模型接入等）依赖本地配置与授权，默认关闭。
- This repository intentionally **excludes**: native binary libraries (`client/libs/**`),
  textbook/content material, proprietary runtime assets not licensed for redistribution
  (e.g. Live2D vendor assets), and internal operation scripts.
- 参见 `PROVENANCE.md` 了解本发布树的生成基线与脱敏政策。
