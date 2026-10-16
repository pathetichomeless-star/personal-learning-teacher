# Agent F — B6 备份/恢复与条件部署独立审查

日期：2026-10-10，Asia/Shanghai。
性质：**完全只读**。本审查未 SSH、未接触 NAS、未改任何仓库文件（仅新增本报告）、未 commit、未执行任何 stop/start/deploy。所有判定仅基于仓库内既有文档与证据；缺证据处一律标注“缺证据”。

审查输入（均在本仓库读取）：
- `B6_PRODUCTION_BACKUP_RESTORE_FINAL.md`
- `B6_MAINTENANCE_WRITE_QUIESCE_PLAN.md`
- `docs/engineering/product-v1/b6-production-backup/`（AGENT_A/B/C/D、备份清单、离线结果、生产状态）
- `docs/engineering/product-v1/PRODUCT-V1-DEPLOYMENT.md`
- `docs/engineering/product-v1/admin-auth-p0/RELEASE_SAFETY.md` 及 `admin-auth-p0/codex-evidence/nas_readonly.json`
- `docs/engineering/deploy-log.md`（条目 #93）
- `docs/engineering/product-v1/admin-v4/RECOVERY_CHECKPOINT_20261010.md`

---

## 一、B6 真实状态提取

**总体状态：BLOCKED**（`B6_PRODUCTION_BACKUP_RESTORE_FINAL.md:5`）。有效部分归档已保留，但完整一致性备份与精确恢复**未完成**，不得据此申请 ADMIN P0 生产部署。

### 1. 已完成的归档（有效部分）
- 生产基线：容器 `xiaozhi-product-v1-sidecar`，完整 ID `295eb64dc48c…b4c4bd`；镜像 `sha256:038d2f6c7a8945…b826611`，linux/arm64，13 层（`B6_PRODUCTION_BACKUP_RESTORE_FINAL.md:13-14`）。
- 归档物：完整生产镜像 + 原始容器 inspect + 原始镜像 inspect，均 AES-256-GCM 认证加密（`…FINAL.md:23-27`）。
- 目录：`/home/<nas-login>/.xiaozhi-b6-backups/b6-20261009T190033Z`，密钥独立目录 `…/.xiaozhi-b6-keys/…`（同 NAS、同账号，仅逻辑分离）（`…FINAL.md:23-25`）。

### 2. 已通过的校验
| 校验 | 结果 | 依据 |
|---|---|---|
| 镜像明文 tar 大小/摘要 | 179633664 bytes；SHA-256 `62d00b6b…2ceb01` | `…FINAL.md:32`；`AGENT_C_RESTORE.md:56` |
| 密文 SHA-256 | `b9af26b8…bd9e926` | `…FINAL.md:33` |
| NAS SHA256SUMS | 4/4 通过（3 密文 + MANIFEST） | `…FINAL.md:34`；`AGENT_D_QA.md:23` |
| 全归档认证/明文摘要/长度 | 3/3 通过 | `…FINAL.md:35` |
| 篡改 tag 拒绝（负向） | 3/3 通过 | `…FINAL.md:36`；`AGENT_D_QA.md:24` |
| config digest/架构/层 | 038d 镜像 linux/arm64，13/13 一致 | `…FINAL.md:37`；`AGENT_C_RESTORE.md:57-58` |
| OCI blob 内容摘要 | 28/28 一致 | `…FINAL.md:38`；`AGENT_C_RESTORE.md:59` |
| 归档自身权限 | 0700/0600、无额外 named/default ACL | `…FINAL.md:25`；`AGENT_D_QA.md:37` |

独立离线核验脚本 `b6_offline_verify.py` 由 Agent C 独立执行，结论 **OFFLINE_INTEGRITY_PASS_ONLY**（`AGENT_C_RESTORE.md:52-62`）。这只证明**加密镜像归档的完整性与身份**，不等于 Docker 加载成功、也不等于完整恢复。

### 3. 当前 BLOCKED 的门槛与原因
| BLOCKED 项 | 原因 |
|---|---|
| 独立 Docker 实际 load | 未执行；尚无 NAS 独立镜像存储/独立 daemon（`…FINAL.md:39,51`；`AGENT_C_RESTORE.md:22`） |
| 配置/Secrets/完整 data 归档 | 未归档；加密 inspect 不能替代（`…FINAL.md:41`） |
| 全量内容 + numeric UID/GID/ACL/xattr 恢复校验 | data 10001:10001、文件 10001:0、NAS `ug.*` xattr，需授权管理员权限（`…FINAL.md:50`；`AGENT_A_INVENTORY.md:52`） |
| 隔离精确恢复 | 未启动恢复容器/测试卷/网络（`…FINAL.md:51`） |
| PolicyStore active/history/audit 恢复一致 | 仅活体库存证据，无恢复件可比（`…FINAL.md:47`） |
| 一致性快照 | 生产卷 ext4，无已验证快照流程；执行账号无非交互 sudo（`…FINAL.md:45`；`AGENT_A_INVENTORY.md:78-83`） |
| 写入方闭合 | `<legacy-platform>` 对 `/volume1/docker` 存在**祖先路径 RW 挂载**（`…FINAL.md:53`；`AGENT_A_INVENTORY.md:100-110`） |

**关于 <legacy-platform>（设计阻塞关键）**：`AGENT_A_INVENTORY.md:104-110` 记录 `<legacy-platform>`（镜像 `<platform-image>:v4.2.3-821`，完整 ID `419b486e…5df77d48`）以 root 身份对 `/volume1/docker` 整目录 RW 挂载，覆盖生产 data 与 Secrets；其职责/访问用途未确认，可能承担 NAS 远程管理，**不能直接停止**。该写入面未闭合前维护施工为 NO_GO（`B6_MAINTENANCE_WRITE_QUIESCE_PLAN.md:18,123`；`AGENT_D_MAINTENANCE_PLAN_QA.md:5`）。

---

## 二、四门禁判定表

产品负责人规定的条件性部署门禁（须全部满足才允许更新小智 NAS 容器）。

| # | 门禁 | 判定 | 依据（文件:行 或 缺失证据） |
|---|---|---|---|
| ① | V4 P0 真实功能完成 | **部分满足（有本地验收证据，但为自证、非独立确认）** | `admin-v4/RECOVERY_CHECKPOINT_20261010.md:21`（合计 311 绿）、`:34`（端到端 E2E 70/70）、`:42`（五格式真实解析）。均为本地 127.0.0.1:8119 验收环境自报，**缺独立审计确认** |
| ② | 独立审计无 Blocker/Major | **未满足（缺证据）** | 仓库内**未发现针对真实 V4 实现（非原型）的独立审计报告**；`admin-v4/` 仅有 RECOVERY_CHECKPOINT 一份；`prototypes/admin-dual-mode-v4/XIAOZHI_ADMIN_V4_QA.md` 为原型 QA，非本轮 V4 实现审计。**缺证据 → 不满足部署门槛** |
| ③ | ARM64 候选测试通过 | **未满足** | 全仓库未发现 V4 ARM64 候选镜像/构建记录（详见第四节）。`prototypes/admin-dual-mode-v4/XIAOZHI_ADMIN_V4_CONTRACT_FINAL.md:374` 明确“部署（NAS 替换）不在本轮”；`XIAOZHI_FILE_IMPORT_P0_PLAN.md:32` 目标平台为 ARM64/RK3588，但依赖未验证 |
| ④ | B6 完整一致性备份 + 独立恢复 + 精确回滚均成功 | **未满足（B6 BLOCKED）** | `B6_PRODUCTION_BACKUP_RESTORE_FINAL.md:5`（BLOCKED）、`:39,41,51,65`（load/Secrets/隔离恢复/PolicyStore 全 BLOCKED）；`AGENT_D_QA.md:3`（PARTIAL，拒绝 B6 PASS）；`AGENT_D_MAINTENANCE_PLAN_QA.md:5`（NO_GO） |

**结论：四条门禁无一“完全满足”，门禁②③④未满足，门禁①仅为本地自证。整体不满足部署条件。**

---

## 三、B6 闭环待办与产品负责人授权点

按 `B6_MAINTENANCE_WRITE_QUIESCE_PLAN.md` 维护方案，闭环 B6 需要以下步骤；每步标出所需授权点（当前均**未获授权**）。

| 步骤 | 内容 | 需要的产品负责人授权点 | 依据 |
|---|---|---|---|
| S1 写入方闭合 | 关闭全部对生产目录的写入面：容器内语音/后台写、`<legacy-platform>` 祖先 RW 挂载、root/主机定时任务、SSH/同步备份任务 | 授权确认 <legacy-platform> 责任人/用途与替代访问通道 → 允许停容器或写入隔离；授权查明/冻结主机 writer | `…PLAN.md:9,12,18`；`AGENT_A_INVENTORY.md:106-112` |
| S2 零连接确认 | 停机前连续 3 次（间隔 5s）`ws_connections=0` 且 `qwen_connected=0`；负责人确认当前不在练习 | 负责人当场确认不在练习 + 维护窗口起止时间 | `…PLAN.md:26-27` |
| S3 优雅停写 | 对**原完整容器 ID** 执行 `docker stop --timeout=-1`，不设自动 SIGKILL，不用 pause/强杀/recreate | 授权停止该容器（含三端口 28310/28311/28312 共享中断）+ 备用控制台 | `…PLAN.md:31,53,100` |
| S4 停止后基线 | 确认 Running=false、PID=0；清点完整生产目录（内容 + 可恢复元数据） | 授权（隐含于窗口授权）；元数据读取需授权管理员身份 | `…PLAN.md:32-34` |
| S5 完整归档 | 认证加密归档 `/volume1/docker/xiaozhi-product-v1/` 全量（data、PolicyStore 全量、Secrets、compose/.env/config、镜像外依赖）；GNU tar pax + numeric owner + ACL + 全部 xattr | 授权 NAS 管理员执行元数据读取/恢复；授权新私有备份根与磁盘预留 | `…PLAN.md:59-73` |
| S6 完整认证回读 | 全量 GCM 认证与清单校验、fsync；认证前不向 Docker/tar 交付明文 | （技术前置，授权窗口内执行） | `…PLAN.md:71` |
| S7 启动原容器 | `docker start <原完整容器 ID>`；不 build/pull/recreate，不改规格；核验三端口/health/PolicyStore 实际加载/Secrets 只读/配置指纹 | 授权启动原容器；接受启动重置非持久化会话/统计 | `…PLAN.md:53,55`；`AGENT_D_MAINTENANCE_PLAN_QA.md:22` |
| S8 独立加载 | 在独立 daemon/image store/socket（或隔离 VM）加载归档，禁止复用生产引擎 | 授权安装/启用独立运行时或管理员提供独立 daemon/VM | `…PLAN.md:79`；`AGENT_C_MAINTENANCE_FEASIBILITY.md:19-22` |
| S9 隔离恢复 | 独立数据路径/容器名/卷/网络；优先 `network none`；`QWEN_MODE=mock` + loopback Mock；证明无生产/LAN/云端路由 | 授权并验证隔离环境；记录安全偏差 | `…PLAN.md:81`；`AGENT_C_RESTORE.md:34-35` |
| S10 读回校验 | 逐文件内容 + numeric UID/GID + ACL + xattr 名称/值 + mode/mtime + 链接；PolicyStore 在精确镜像内加载核对 active/history/audit，拒绝 v1 默认回退 | （技术前置） | `…PLAN.md:83`；`AGENT_C_RESTORE.md:32,37` |
| S11 回滚演练 | 保留维护后新增写入再评估兼容性；禁止直接覆盖 data；回滚锚点为原完整容器 ID/038d 镜像 | 授权回滚演练及后续写入保全方案 | `…PLAN.md:129`；`AGENT_D_MAINTENANCE_PLAN_QA.md:36-38` |
| S12 独立 QA | 独立复核归档、隔离证据、加载状态、元数据比对 | 授权独立 QA | `…PLAN.md:132` |

**维护执行前必须另获**（`…PLAN.md:134`）：明确起止时间、允许停止/启动的完整容器清单、全部 writer 的关闭/恢复方案、管理员执行方式、故障处置联系人、非持久化状态影响接受、独立恢复测试环境安排。“愿意安排窗口”不等于动作已批准。

---

## 四、ARM64 候选镜像核证

**结论：未发现任何针对 V4 的 ARM64 候选镜像或构建流程 → 门禁③未满足。**

核证证据（全仓库只读检索）：
1. **无 V4 Dockerfile / compose**：`deploy/` 下 Dockerfile 仅有 `product-sidecar`、`mvp-sidecar`、`sidecar`（另有 `gateway/Dockerfile`、旧 `rtl-lab/Dockerfile`），**无 v4 专属构建文件**（Glob `**/Dockerfile*`）。
2. **V4“验收环境”不是容器**：`deploy/v4-acceptance/start_v4_acceptance.py:1-18` 是 **Mac 本地 Python 启动器**，绑定 `127.0.0.1:8119`（admin 面）与本地 mock `8123`，明确“只启动 ADMIN V4 控制面（aiohttp），不启动音频面/WS/OTA”“不影响 NAS 任何容器”。它不产出镜像、不涉及 ARM64。
3. **无 buildx / platform=linux/arm64 / V4 镜像哈希**：检索 `arm64|buildx|platform=linux|v4.*image|镜像候选` 等模式，未命中任何 V4 镜像构建记录或摘要；命中的 arm64 记录均为**生产 038d 镜像**（`AGENT_A_INVENTORY.md:10`、`AGENT_C_RESTORE.md:57` 等）或离线校验内容，与 V4 候选无关。
4. **文档明确 V4 未部署/未构建**：`prototypes/admin-dual-mode-v4/XIAOZHI_ADMIN_V4_CONTRACT_FINAL.md:374`“部署（NAS 替换）**不在本轮**”；`XIAOZHI_ADMIN_V4_SPEC_CLOSURE.md:42,199` 记录解析器 ARM64 依赖（lxml wheel）**尚未实现/未验证**；`XIAOZHI_FILE_IMPORT_P0_PLAN.md:32` 目标平台 NAS RK3588/ARM64 仅为选型约束。
5. **历史候选镜像非 V4**：仓库内出现的候选摘要（`4d26ae4a…`、`7152e3eb…`、`93af2dac…`）均属 **ADMIN P0** 候选（`ADMIN_P0_HUMAN_UI_ACCEPTANCE.md:23`；`TRAE_ADMIN_P0_V2_FINAL_REVIEW.md:80`），非 V4。

因此，门禁③“ARM64 候选测试通过”**不具备前置对象（无候选可测）**，判定未满足。

---

## 五、回滚依据一致性核验

**待核验结论**：B6 文档声明旧 `RELEASE_SAFETY.md` 的 `34ea8277…` 回滚指令在精确回滚场景失效，仅“原完整容器 ID 的 `start`”可用。

**核验结果：该结论在文档间自洽。**

1. 旧回滚指令原文（`RELEASE_SAFETY.md:13`）：`docker tag …:XIAOZHI-VOICE-V1-HUMAN-ACCEPTED …:latest && docker compose up -d --force-recreate`（回到镜像 `34ea8277cb57`），来源为 deploy-log #93 rollback A（`deploy-log.md:176`）。
2. 该指令的语义是 **recreate 容器 + 替换镜像（038d→34ea8277）**，属“降级式回滚”，会改变容器与镜像身份，不使用原容器 ID。
3. B6 立场（`B6_PRODUCTION_BACKUP_RESTORE_FINAL.md:76`）：在 B6 当前精确回滚场景下该历史回滚**失效**，不执行；**仅恢复原容器服务应使用原完整容器 ID 的 `start`，不得 recreate 或替换镜像**。
4. 维护方案一致：`B6_MAINTENANCE_WRITE_QUIESCE_PLAN.md:53`“服务恢复只启动**同一个已停止容器 ID**；不使用 compose up/build/pull/recreate”。
5. 独立代理一致：`AGENT_C_RESTORE.md:49`、`AGENT_D_QA.md:70`、`AGENT_D_MAINTENANCE_PLAN_QA.md:38`、`AGENT_C_MAINTENANCE_FEASIBILITY.md:42` 均判定历史 `34ea8277…` 不是当前 ADMIN-V2 精确回滚目标，锚点应为完整 `038d…` ID。
6. 佐证数据一致：`nas_readonly.json:116-120`（`34ea8277` 存在，tag `XIAOZHI-VOICE-V1-HUMAN-ACCEPTED`）与 `:227`（`freeze/pre-adminv2/running_image_id.txt` 记录旧运行镜像为 `34ea8277`）；`:230`（`freeze/pre-adminauth-p0` 不存在）。即 `34ea8277` 是 **ADMIN-VISUAL-V2 发布前**的旧镜像，回滚到它 = 丢弃当前 038d 发布，与“精确回滚到维护前同一镜像/容器”目标不同。

**补充：另一处历史回滚亦不可用于精确恢复**——`PRODUCT-V1-DEPLOYMENT.md:80` 的整阶段回滚 `docker compose down && rm -rf /volume1/docker/xiaozhi-product-v1` 是**破坏性删除**，明确不能用于精确恢复场景。

**差异澄清（不构成矛盾）**：`RELEASE_SAFETY.md` 的回滚面向其自身场景（部署 admin-auth 修复后回退到修复前镜像），B2 的 B6 精确回滚面向“维护停写后恢复原服务/原数据”。两者场景不同；B6 文档正确地指出**历史 34ea8277 指令不能被当作 B6 精确回滚**，且任何维护恢复都不得 recreate/换镜像。文档间无相互冲突，B6 结论自洽且被 C/D 独立确认。

---

## 六、总体判定

| 判定项 | 结果 |
|---|---|
| 门禁① V4 P0 真实功能完成 | 部分满足（本地自证，缺独立确认） |
| 门禁② 独立审计无 Blocker/Major | **未满足（缺证据）** |
| 门禁③ ARM64 候选测试通过 | **未满足（无候选）** |
| 门禁④ B6 备份/独立恢复/精确回滚 | **未满足（B6 BLOCKED）** |
| **总体** | **未满足全部门禁 → 必须 `BLOCKED_NOT_DEPLOYED`，保留旧系统** |

同时满足硬性停止条件：<legacy-platform>（未授权服务）写入面未闭合、B6 无法闭环、无独立恢复、无 ARM64 候选、无安全回滚证明。按门禁规则，**必须停止生产部署、保留旧系统**（`B6_PRODUCTION_BACKUP_RESTORE_FINAL.md:5,86`；`B6_MAINTENANCE_WRITE_QUIESCE_PLAN.md:18,135`）。

### 若未来满足全部条件，精确操作顺序建议（仅建议，不执行）
1. 重新核实真实生产镜像、挂载、写入方、SSH 管理通道、活动会话；任一偏离已审核基线则停止。
2. 取得产品负责人对维护窗口（起止时间）与全部动作的明确批准（清单见第三节 S1–S12）。
3. 闭合全部写入方（含 <legacy-platform>、root/主机任务），确认零语音连接与零活动会话。
4. `docker stop --timeout=-1 <原完整容器 ID>`；确认 Running=false、PID=0、无自动重拉。
5. 建立停止后全量内容/元数据基线；认证加密归档全量生产目录（含 Secrets、PolicyStore 全量、compose/.env/config、镜像外依赖）。
6. 全量 GCM 认证 + 清单校验 + fsync（认证前不得交付明文）。
7. `docker start <原完整容器 ID>`，核验三端口/health/PolicyStore 实际加载/Secrets 只读/配置指纹。
8. 独立 daemon/image store 加载归档 → 隔离 `network none` 恢复（`QWEN_MODE=mock` + loopback Mock）→ 逐项元数据与 PolicyStore（active/history/audit）读回校验，拒绝 v1 默认回退。
9. 独立 QA 复核；回滚演练保留维护后新增写入并评估兼容性。
10. 上述全部通过后**另行**取得产品部署授权（B6 通过本身不构成 ADMIN P0 部署授权，`…FINAL.md:86`）。V4 还需先补齐门禁①②③（独立审计 + ARM64 候选构建与验证）。

---

**审查者边界声明**：本报告为独立只读审查；未执行任何 NAS/生产操作，未改仓库文件（除本报告），未 commit。缺证据项已如实标注。