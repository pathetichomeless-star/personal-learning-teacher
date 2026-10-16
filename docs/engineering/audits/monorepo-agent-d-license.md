# MONOREPO MIGRATION — AGENT D: LICENSE / ATTRIBUTION AUDIT (raw report)

- Date: 2026-10-07 (Asia/Shanghai)
- Mode: **READ-ONLY**. 未修改任何被审计文件；本文件是本次审计唯一写入的产物。
- Repo: `<project-root>` (root git repo, branch `main`)
- 证据来源：本地文件读取 + `git ls-files`；本仓库内 **无** 需要 WebFetch 的上游许可文本
  （外部组件均由仓库内文件或 ADMIN-1 已记录的 NAS/上游读取结果覆盖），因此本次 **未使用任何 UPSTREAM-NOT-LOCAL 新证据**。
- 私有值：未打印任何密钥值。

结论：**D_LICENSE = PASS**（详见文末判据）。

---

## 1. py-xiaozhi MIT 归属是否保留

| 检查项 | 结果 | 证据 |
|---|---|---|
| `client/LICENSE` 存在 | ✅ | `git ls-files` → `client/LICENSE` |
| 为逐字 MIT 文本 | ✅ | `client/LICENSE:1` `MIT License`；`:3` `Copyright (c) 2025 Junsen`；`:5-21` 标准 MIT 正文 |
| 与 `py-xiaozhi/LICENSE` 字节相等 | ✅ | `cmp client/LICENSE py-xiaozhi/LICENSE` → IDENTICAL；sha256 均为 `49ddd0fdc520a6e936b6c618dbcc66055d31b746ddd1972337f2a6e96135ba4d` |
| `client/pyproject.toml` 许可元数据仍在 | ✅ | `client/pyproject.toml:7` `license = { text = "MIT" }`；`:8` `authors = [{ name = "Junsen", ... }]`；`:102-103` Homepage/Repository = `https://github.com/huangjunsen0406/py-xiaozhi` |

两级副本（`client/` 为 git 跟踪的 fork；`py-xiaozhi/` 为未跟踪的本地 canonical 源）许可文本完全一致，归属无损失。

## 2. xiaozhi-esp32-server 保持外部 / 固定，未 vendored

- 路径级证据（`git ls-files | grep -iE 'xiaozhi-esp32-api|manager-api|manager-web|AdminApplication|server_latest|xiaozhi-esp32|esp32-server|web_latest'`）→ **无任何匹配**（exit=1）。
- 内容级证据（全仓 grep `server_latest|web_latest|manager-api|xiaozhi-esp32|AdminApplication|ghcr`）命中的文件仅为：
  - **仅镜像引用**：`deploy/legacy-xiaozhi/docker-compose.yml:10`、`docker-compose_all.yml:12,33`、`compose_all.template.yml:12,33` 均引用
    `ghcr.nju.edu.cn/xinnan-tech/xiaozhi-esp32-server:server_latest` 与 `:web_latest`；`.env.example` 仅含占位变量名；
  - **上游文档/生态提及**：`client/README*.md`、`client/documents/docs/**`；
  - **审计/说明文档**：`docs/**`、`THIRD_PARTY_LICENSES.md`、`NOTICE.md`、`docs/reference/config.yaml`。
- `git ls-files | grep -iE '\.jar$|\.java$|spring'` → **无匹配**（无 `xiaozhi-esp32-api.jar`、无 Java/Spring 源码）。
- `AdminApplication` 仅出现在 `docs/admin1/ADMIN-1-audit-report.md`、`docs/admin1/raw-cd-admin-capabilities-db.md`（纯文本描述）。

**结论**：仓库内仅存在镜像引用与文档提及，**无 server / manager-api / manager-web 源码**，符合"外部固定镜像、不 vendored"。

## 3. word-master Apache-2.0 归属

- `THIRD_PARTY_LICENSES.md:32-35` §2 记录：`word-master — **Apache-2.0**`；`Evidence: NAS LICENSE (Apache License 2.0, "Copyright 2024 Word Master Contributors"; no NOTICE file upstream)`；`Obligation if redistributed: include a copy of the licence and state any modified files.`
  → 满足 Apache-2.0 的 **保留许可副本** 与 **声明修改（statement of changes）** 义务的表述。
- 该读取与 `docs/admin1/raw-gi-gaps-sourcetruth-licenses.md:154`（`LICENSE:1-3` 头；`:186` `Copyright 2024 Word Master Contributors`；`package.json` name `word-master@1.1.0`）一致，无 NOTICE 上游。
- 未 vendored：`git ls-files | grep -i 'word-master'` → **无匹配**；内容 grep `word-master|Word Master` 仅命中 `docs/**`、`THIRD_PARTY_LICENSES.md`、`NOTICE.md`、`gateway/docs/**` 等文档。**无 word-master 代码/资源入库。**

## 4. English-workbench 未 vendored + 受限内容规则

- 路径级：`git ls-files | grep -iE 'ielts|workbench|elw_state|COPYRIGHT\.md|README-DEPLOY'` → 仅 `docs/admin1/raw-ef-realtime-workbench.md`（文档）。
  `git ls-files | grep -i 'ielts'` → 无匹配；`workbench` 作为路径仅上述 1 个文档。
- `COPYRIGHT.md`、`README-DEPLOY`、`elw_state` 在跟踪文件中 **无任何路径匹配**（仅 `.gitignore` 含 `**/elw_state*.json` 排除规则，属反向证据=不入库）。
- 受限内容规则已在 `THIRD_PARTY_LICENSES.md:37-44` §2 明确陈述：
  - 教科书/音频/图片等第三方内容 **未获任何授权**（文本 "textbook/audio/image third-party content is **not** granted any rights"）；
  - `README-DEPLOY.txt` 限制为 **仅局域网（LAN）使用** 并 **禁止发布 `/ielts/`**；
  - 结论条款：**绝不 vendored workbench 内容**，至多一个走 LAN 的瘦适配器；应用主体无许可文件 → 在澄清前不得再分发。
- 交叉文档一致：`docs/admin1/raw-gi-gaps-sourcetruth-licenses.md:156-163`、`docs/admin0/license-attribution-plan.md:11,42` 表述一致。

## 5. `THIRD_PARTY_LICENSES.md` 内部一致性

- 所列许可名称与本次独立核验一致：py-xiaozhi = MIT（✅ 见 §1）；xiaozhi-esp32-server = MIT（镜像引用，见 §2）；word-master = Apache-2.0（✅ 见 §3）；workbench = MIT 内容 + 排除条款 / 应用主体无许可（✅ 见 §4）。
- 与 `NOTICE.md` 无矛盾：两文件列出同一组件集合与同一许可结论（含 fork=MIT、外部依赖、PENDING）。
- 运行时镜像段落 `THIRD_PARTY_LICENSES.md:46-49` §3，标题即 "Runtime images we only operate"，正文明确 "They are **not redistributed by this project**" → 满足"run-only, not redistributed"的显式声明。
- 后续依赖规则（`:56-61` §5）要求新依赖同 commit 记录、禁改上游许可、禁 vendored workbench、我方许可由 PO 决定。

## 6. `NOTICE.md` 内部一致性 + 根许可缺失 / PENDING

- `NOTICE.md` 同时包含三块：① 我方代码（`rtl-lab/`、`admin0/`、`admin1/`、`tools/`、`modules/`）标注
  **`LICENSE DECISION = PENDING PRODUCT OWNER`**（`:6-9`）；② 捆绑的 py-xiaozhi fork = MIT `Copyright (c) 2025 Junsen`，`py-xiaozhi/LICENSE` 逐字保留（`:11-14`）；③ 未 vendored 的外部依赖清单（server/manager-api=MIT 镜像、word-master=Apache-2.0、workbench=LAN-only、运行时镜像）（`:16-20`）。
- 无根许可：`ls LICENSE` → `No such file or directory`（失败）；`git ls-files | grep -i '^LICENSE'` → **空**（exit=1）。
- 全仓跟踪的许可类文件名（`git ls-files | grep -iE '(^|/)(licen[cs]e|copying|notice)(\.|$|/)'`）→ 仅 `NOTICE.md`、`client/LICENSE`。
  → **未为我方代码新增任何许可文本**；`LICENSE DECISION` 仍为 `PENDING_PRODUCT_OWNER`。

## 7. imported client 树无冲突许可

- `git ls-files client | grep -iE 'licen[cs]e|copying|notice|copyright'` → 仅 `client/LICENSE`（唯一 MIT）。**无 GPL/COPYING/NOTICE 等额外许可副本**。
- 全仓 `GPL|GNU General Public` 内容 grep → 仅 2 个文件：
  - `client/scripts/bundle_ffmpeg.sh:174-204`：ffmpeg 打包脚本注明选用 **LGPL** 构建（"fewer GPL obligations for MIT app"）——这是**构建脚本注释**，非许可文件、非 vendored 内容；
  - `docs/admin0/license-attribution-plan.md:13`：引用 mysql 镜像的上游许可元数据（GPL-2.0 / BSD）。
  → 均不构成与 MIT fork 冲突的许可文件。

---

## 观察项（非阻断，不改变 PASS 判定）

1. **路径标注精度**：`NOTICE.md:11` 与 `THIRD_PARTY_LICENSES.md:15` 将捆绑 fork 标为 `py-xiaozhi/`，而 **git 跟踪的 fork 实为 `client/`**
   （`py-xiaozhi/` 未跟踪，经 `.git/info/exclude:1` 排除，且自身是嵌套 git 仓库）。两处 `LICENSE` 字节相同，**归属无损失**；
   建议后续统一为 `client/` 以免混淆，但当前不构成不一致性缺陷。
2. `THIRD_PARTY_LICENSES.md:52` 引用 `ref/config.yaml`，仓库内实际跟踪路径为 `docs/reference/config.yaml`（同一参考样本，迁移后路径不同）。非许可问题。
3. `THIRD_PARTY_LICENSES.md:26` 对 server 标注证据为 `UPSTREAM-NOT-LOCAL`；`docs/admin1/raw-gi-gaps-sourcetruth-licenses.md:151` 记录了抓取到上游 MIT 文本（"Copyright (c) 2025 xinnan-tech"）。两者一致（本仓库无本地源码副本）。

## 判据核对（FAIL 仅限：真实归属丢失 / vendored 受限内容 / 归属文档自相矛盾 / 为我方代码新增许可文件）

| FAIL 条件 | 是否触发 |
|---|---|
| 真实归属丢失 | 否（MIT 逐字、字节相等，pyproject 元数据在） |
| vendored 受限内容（server/workbench/word-master 代码或内容） | 否（均无路径级入库，仅文档/镜像引用） |
| 归属文档自相矛盾 | 否（THIRD_PARTY 与 NOTICE 一致；仅路径标注精度观察项） |
| 为我方代码新增许可文件 | 否（根无 LICENSE，跟踪许可类文件仅 NOTICE.md + client/LICENSE） |

---

## 结论

**D_LICENSE = PASS**

无归属丢失、无 vendored 受限内容、无归属文档矛盾、未为我方代码新增许可文本；`LICENSE DECISION` 保持 `PENDING_PRODUCT_OWNER`。