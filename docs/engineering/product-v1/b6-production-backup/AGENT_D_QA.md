# Agent D — Independent Recovery QA

核验时间：2026-10-10 03:02（Asia/Shanghai）。结论：**PARTIAL / B6 BLOCKED，不同意 B6 PASS，不具备申请生产部署的恢复准备条件。**

本审核由 D 直接 SSH 读取 NAS、独立解密验证归档及逐层计算摘要；没有引用 Lead 的 PASS，没有启动恢复容器，没有修改生产配置、Secrets 或 data。

## 1. 独立生产取证

- 容器：`xiaozhi-product-v1-sidecar`，完整 ID `295eb64dc48c364de65cc4a5d163a60ec9aa1d936cf2909fafe53e2937b4c4bd`。
- 镜像：`sha256:038d2f6c7a8945ff8ceadffdf100dc306123d51aa8b0ad2c4c48ed073b826611`，运行中，RestartCount=0，StartedAt=`2026-10-09T06:36:55.857693136Z`。
- `/app/data` 为生产 data 的读写 bind；`/app/secrets` 为生产 secrets 的只读 bind。
- `/volume1` 实际为 **ext4**，块设备 `/dev/mapper/ug_8F0970_1765336960_pool1-volume1`。`lvs`、`dmsetup` 未在当前 PATH 发现，`sudo -n true` 返回 1；不能由此排除管理员另有存储快照能力，但当前执行身份无法验证或使用它。
- `btrfs subvolume show` 对 data 无法访问；底层 ext4 已独立确认。SSH 用户不能直接读取 mode700 的 data；在现有生产容器内仅执行只读 Python 统计。
- 观察到 data 7 个文件、1 个目录、0 个符号链接；文件共 7 个 xattr 名称。这是实时清点，**不是一致性快照**。
- `/health` 8110、8111：ws_connections=0、qwen_connected=0、turns=26。本审核未发起语音/云端会话。

## 2. 实际归档独立校验

备份：`/home/<nas-login>/.xiaozhi-b6-backups/b6-20261009T190033Z`。解密材料位于同一 SSH 用户私有 home 下的独立密钥目录；没有输出密钥、明文 env 或 raw inspect。

| 检查 | D 独立结果 |
|---|---|
| `sha256sum -c SHA256SUMS` | rc=0，4/4（3 密文归档及 MANIFEST） |
| AES-256-GCM 完整认证 | 3/3 通过，32-byte 独立 key；认证 header 与完整 ciphertext |
| 明文/密文 SHA-256 与长度 | 3/3 均与 NAS manifest 相符 |
| 镜像 tar 的 config digest | 与上述完整生产镜像 ID 相同 |
| 架构与操作系统 | linux/arm64 |
| 镜像层 | 13/13 tar layer SHA-256 与 config rootfs.diff_ids 相同，且与 captured image inspect 相同 |
| 实际 Docker 独立加载 | **NOT_PERFORMED**；逐层校验不能替代独立 daemon 加载 |

镜像明文 tar SHA-256：`62d00b6b7ad32b6a77fc5b0dac51d8485c2b84fc6b90f750deba45c5da2ceb01`。

镜像密文 SHA-256：`b9af26b8af9a11db46e2e27ccd172b41513fd330573dc653c53740dc5bd9e926`。

D 另行阅读并重跑 C 的 `b6_offline_verify.py`（NAS-only stdin，不落盘脚本或明文）：再次通过全部校验，3/3 篡改 tag 被拒绝、28/28 OCI 内容寻址 blob 摘要通过；MANIFEST SHA-256=`37afd3bd8cb636ce302bc5d63b4b82d4a65938990c4198e66da1ee51b0a54994`。这是对 D 自行编写的前述核验的补充，不是实际镜像加载。

归档根、run 目录、密钥根及密钥 run 目录均为 UID1000:GID10、mode700、非符号链接；5 个备份文件与3 个密钥文件均为 UID1000:GID10、mode600。对上述12个对象独立执行 `getfacl -cpn`：均成功，没有 named/default ACL 条目，other::---。各对象存在1个 xattr 名称，未打印其值。

审核 `b6_secure_backup.py`：umask077、独占创建、不落盘明文、随机 nonce、GCM header AAD、finalize tag、全量解密认证并复核摘要，符合本次部分归档目的。密钥与归档仍位于同一 NAS/同一账户；目录分离不能抵御整机丢失或该账户泄露。未授权异地转移，因此未执行。

## 3. 数据与 PolicyStore：恢复证据缺失

本次归档明确**未包含**完整 data、完整 Secrets、Compose/env 原文件及镜像外配置/构建依赖。runtime inspect 虽保存运行参数，不等于保存上述文件。当前不能证明跨文件一致性；依据用户边界，没有普通复制后宣称一致，没有自行暂停写入。

实时只读 PolicyStore 观察：active version=20，history=19，audit=19。

| 实时观察对象 | SHA-256 |
|---|---|
| `policy.json` 原始字节 | `1e99fd29465e152a4f80a5baac034888639fbb2a5f4607117e52b3ab794fbd9e` |
| active canonical JSON | `5cbc37d04b1e108ea9a8373585b7f7c5652d91f3bfd2750a65305e80534e3b1d` |
| history canonical JSON | `e1d0e0ce8b511e8755454abe37610f4a501d4aa5491c45ee97dc691bbcb4e6b4` |
| audit canonical JSON | `0e3832c716eb2a830488cafc53170fc988308e8c1d44f45bf69417012d8bd9bb` |

Canonical 摘要采用 Python `json.dumps(value, sort_keys=True, separators=(',', ':'))` 默认 ensure_ascii=True 后 UTF-8 编码。这些摘要没有对应恢复件，**不能作为 PolicyStore 恢复成功证据**。

权限差异必须保留：data 目录10001:10001 mode700；policy/memory/knowledge 文件10001:0 mode600；Secrets 目录1000:10 mode755；两个已知 Secrets 文件10001:10001 mode600。统一 chown10001:10001 会改变原始文件 GID。ACL/xattr 必须归档、恢复、逐项核对；当前尚无此验证。

本地 `modules/policy/persona.py:452-483` 在文件缺失、格式或 schema 不合格时可能使用 v1 默认值；本地 HEAD 为 `d177582e1e4ec4737ca0ef8ec68966ce7fb7798d`，不是用户给定 `f57b8cde741821928b0d90c03e5f8628a77ee146`，故本地代码仅用于提示检查项，不能替代生产镜像运行验证。未来必须同时比对恢复字节、active/history/audit 与该精确镜像实际加载后的状态，主动拒绝 v1 静默回退。

## 4. 隔离与生产影响

未启动恢复容器，未连接 Mock 或真实 Qwen。当前隔离恢复网络、独立数据卷及端口没有建立或验证，所以恢复运行结果为 BLOCKED，不能写成“隔离演练 PASS”。

未来启动前必须证明：完全独立 Docker daemon/网络、无生产 bind/服务网络、无外网路由、Mock endpoint 仅在隔离网络可达；仅设置 QWEN_MODE=mock 不足以证明网络隔离。保留真实 Secrets 的权限验证与 Mock 运行装配须分开核对，测试不得使用真实 Token 访问云端。

D 在归档核验后再次比对 live/captured inspect：容器完整 ID、镜像 ID、StartedAt、RestartCount 均相同，仍运行。没有执行生产 stop/pause/restart/recreate。上述证据证明身份及生命周期未变化，不能无限扩大为所有延迟指标完全无影响。

## 5. 回滚安全审查与后续门槛

旧 `admin-auth-p0/RELEASE_SAFETY.md` 推荐历史 `34ea8277…` tag 回滚及不完整备份清单，**不适用于 B6 当前 ADMIN-V2 精确回滚**。未来回滚只能以本次实际生产完整 `038d…` ID 为锚点，并重新核验回滚前当前环境。

当前只有镜像与运行规格部分归档，无法形成“已演练、可独立执行”的完整灾难恢复流程。后续必须先取得一致性快照能力，或单独取得维护窗口内停止生产写入的明确授权；当前授权不能执行停止、重建或配置修改。

具备完整归档后的流程应依次执行：完整校验 → 全量 GCM 认证 → 在安全私有恢复位置恢复数据/Secrets及 numeric UID/GID、ACL、xattr → 独立 daemon 加载精确镜像 → 核对完整 ID/层/架构 → 生成无 build、禁止拉取替代镜像的恢复运行规格 → 隔离 Mock 测试 active/history/audit、静态资源/认证、语音配置 → 独立 QA → 再申请部署授权及维护窗口。

不得在 GCM `finalize` 认证成功之前将流式明文交给 `docker load` 或 tar 解包。未来批准实际回滚前，应将候选运行后新增 memory/knowledge/policy/audit 等写入单独保全并评估兼容性；不能直接覆盖为快照时刻数据，也不能仅靠保留新 data 就假定旧程序兼容。

| B6 完成条件 | D 判定 |
|---|---|
| 当前镜像备份及独立加载 | PARTIAL：归档/摘要通过，加载未执行 |
| 配置、Secrets、完整 data 安全备份 | BLOCKED |
| 全备完整性、原数据权限恢复 | BLOCKED；仅部分归档安全权限通过 |
| 隔离精确恢复 | BLOCKED |
| PolicyStore 历史与审计恢复 | BLOCKED |
| 独立 QA | 已执行；结论不通过 B6 门槛 |
| 生产未重启/中断 | 生命周期核验通过；没有执行中断操作 |
| 证据不包含秘密值 | D 工具输出与报告仅元数据/摘要，未输出秘密值 |

最终：**B6 BLOCKED；保留有效部分归档，不得据此申请生产部署。**
