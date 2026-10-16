# B6 Agent A — 生产只读取证

结论：生产基线确认；完整一致性数据备份 **BLOCKED**。本 Agent 未暂停、重启或修改生产，未创建数据副本或快照，未输出秘密内容。取证时间：2026-10-10 02:58–03:02 Asia/Shanghai。

## 实际运行基线

- NAS：192.0.2.1；SSH 别名 `xiaozhi-nas`。
- 容器：`xiaozhi-product-v1-sidecar`；完整 ID：`295eb64dc48c364de65cc4a5d163a60ec9aa1d936cf2909fafe53e2937b4c4bd`。
- 当前完整镜像：`sha256:038d2f6c7a8945ff8ceadffdf100dc306123d51aa8b0ad2c4c48ed073b826611`。
- 镜像平台：linux/arm64；大小 174556624 bytes；RootFS diff-ID 层数 13；RepoDigests 为空。该完整 ID 才是本轮精确回滚目标。
- 状态 running / Running=true / Paused=false / Restarting=false；StartedAt `2026-10-09T06:36:55.857693136Z`；主进程 PID 555596。03:01:47复查 RestartCount=0、Health.Status=healthy。
- 工作目录 `/app`；运行用户 `10001`；命令 `python -m app.main`；无 Entrypoint。
- 网络 `xiaozhi-product-v1_default`；端口 28310→8110、28311→8111、28312→8112，全部 TCP。
- RestartPolicy `unless-stopped`；Privileged=false；CapDrop=ALL；SecurityOpt=`no-new-privileges:true`；根文件系统可写；json-file 日志配置未设置额外选项。
- `docker diff` 仅显示 `/app` 改变及挂载点 `/app/data`、`/app/secrets` 添加，无额外持久化数据位置证据。

## Compose 与生效配置

运行标签明确指定唯一 Compose：`/volume1/docker/xiaozhi-product-v1/docker-compose.yml`；项目工作目录 `/volume1/docker/xiaozhi-product-v1`；无覆盖文件标签。Compose 版本 5.1.3；config-hash `e7c6ba1c6f09da1a98385bdcb0babc854ee0765dacb8d52a0bad7b19d2780f1a`。

`docker compose -f ... config --format json` 只读解析成功；服务名 `xiaozhi-product-v1-sidecar`，生效端口/挂载/网络/安全选项与 inspect 一致。Compose 使用 build，未固定 image 字段，故精确恢复必须使用保存的完整镜像 ID，不能直接重新 build 代替。

| 主机源 | 容器目标 | 生效访问 |
|---|---|---|
| `/volume1/docker/xiaozhi-product-v1/data` | `/app/data` | rw, rprivate |
| `/volume1/docker/xiaozhi-product-v1/secrets` | `/app/secrets` | ro, rprivate |

文件引用：`POLICY_FILE=/app/data/policy.json`、`KNOWLEDGE_FILE=/app/data/knowledge.json`、`MEMORY_FILE=/app/data/memory.json`、`ADMIN_API_TOKEN_FILE=/app/secrets/product_v1_admin_token`、`QWEN_SECRET_FILE=/app/secrets/qwen-realtime.env`、`ADMIN_UI_DIR=/app/admin-ui`。ADMIN_ENABLED=1，ADMIN_BIND=0.0.0.0，ADMIN_PORT=8112，WS_PORT=8110，HTTP_PORT=8111，FRAME_MS=20。

Compose 根目录还存在 `.env`、若干 `.env.pre-*.bak`、`config/config.json` 及 freeze 下历史文件。只枚举文件元信息，未输出内容。有效 `.env`、Compose、config 文件均 uid1000/gid10 mode0644；这只说明访问权限，未断言其内容无秘密。

运行环境变量名称：ADMIN_API_TOKEN_FILE、ADMIN_BIND、ADMIN_ENABLED、ADMIN_PORT、ADMIN_UI_DIR、FRAME_MS、GPG_KEY、HTTP_PORT、KNOWLEDGE_FILE、LANG、MEMORY_FILE、PATH、POLICY_FILE、PUBLIC_WS_URL、PYTHONUNBUFFERED、PYTHON_SHA256、PYTHON_VERSION、QWEN_MODE、QWEN_MODEL、QWEN_SECRET_FILE、QWEN_VOICE、TZ、WORKBENCH_BASE_URL、WS_PORT。值不进入普通报告；完整运行规格需加密保存。

## 完整 data 与 Secrets 文件元信息

| 路径（相对生产根） | numeric UID:GID | mode | bytes |
|---|---|---|---:|
| data/ | 10001:10001 | 0700 | — |
| data/knowledge.json | 10001:0 | 0600 | 67 |
| data/knowledge.json.lock | 10001:0 | 0600 | 0 |
| data/memory.json | 10001:0 | 0600 | 67 |
| data/memory.json.lock | 10001:0 | 0600 | 0 |
| data/policy.json | 10001:0 | 0600 | 111759 |
| data/policy.json.lock | 10001:0 | 0600 | 0 |
| data/policy.json.pre-sa02.bak | 10001:0 | 0600 | 105448 |
| secrets/ | 1000:10 | 0755 | — |
| secrets/product_v1_admin_token | 10001:10001 | 0600 | 64 |
| secrets/qwen-realtime.env | 10001:10001 | 0600 | 384 |

`getfacl -p -n` 显示 data 根与 secrets 根/两个秘密文件均为基础 owner/group/other ACL，无额外 named-user/group 项。data 子文件由既有容器内只读 Python 枚举；SSH 用户1000:10无法直接遍历0700数据根。未以此绕过一致性要求复制数据。

data 和 secrets 根的 xattr 名称均含 `ug.archive_bit`、`user.ug.flags`、`ug.archive_version`；其文件均含 `ug.archive_bit`。恢复需处理这些 NAS 扩展属性、ACL 与 numeric ownership，不能只验证文件字节或 chmod。尚未验证普通权限是否能完整恢复 NAS `ug.*` 属性。

## PolicyStore 活体观察（不是备份证明）

- policy.json 可解析，schema_version=1。
- active 为 dict，键 actor/policy/updated_at/version，active.version=20；history=list，19 条；audit=list，19 条。
- 原文件 SHA-256：`1e99fd29465e152a4f80a5baac034888639fbb2a5f4607117e52b3ab794fbd9e`。
- active canonical JSON SHA-256：`7fb7ccfeed833e507e6a45c652df50d97ad805b0b242a40288415094d7cee8a0`。
- history canonical JSON SHA-256：`fa0122288a97321e79896fe8ccca1aeb8139eb72ff95d0e8e82c6ee7823fe1ef`。
- audit canonical JSON SHA-256：`0e3832c716eb2a830488cafc53170fc988308e8c1d44f45bf69417012d8bd9bb`。
- knowledge.json SHA-256：`3b9c15b5bb68d949d4714dd356af83deafdcdbcba8ee1346d5bf374e18a70f2f`。
- memory.json SHA-256：`8c62b5e965850a1fce9c268fd301278f126b0fa456a49418bf66bfd86b045cb1`。
- policy.json.pre-sa02.bak SHA-256：`06958532b66b5fd085f7836723b0ebd9cb207ef1ae3a362313b64f6ce0ea5773`。

以上在生产继续运行时读取，仅用作调查。不能证明多个文件同一逻辑时刻，更不能代替完整一致性归档或恢复比对。

canonical JSON算法为 `json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')` 后SHA-256。使用ensure_ascii=True的独立调查会得到不同canonical hash；精确文件一致性仍应优先比对原始文件SHA-256，并统一canonical算法。

## 在线状态

只读请求容器本机 `http://127.0.0.1:8110/health`：status=ok，ws_connections=0，qwen_connected=0，turns=26，uptime_s≈44586；容器 `/proc/net/tcp` 中8110/8111/8112均 LISTEN，未见这些端口的 ESTABLISHED 连接。此状态仅对观察时刻有效，零连接不授予停止服务权限。未发起 WebSocket 或 Qwen 请求。

2026-10-10 03:01:47 Asia/Shanghai复查：同一容器ID、镜像及StartedAt，RestartCount=0，healthy；status=ok、ws_connections=0、qwen_connected=0、qwen_sessions=3、turns=26、uptime_s=44691.29。qwen_sessions=3为已有累计值，本 Agent未新增真实Qwen请求。

## 一致性快照障碍

- `findmnt -T /volume1`：`/dev/mapper/ug_8F0970_1765336960_pool1-volume1`，ext4，rw/nosuid/nodev/noatime/nobarrier/quota。
- df：可用284999704576 bytes（约265GiB），使用率91%。
- btrfs 工具存在，但该卷 ext4；`btrfs subvolume show` 未能访问/证明数据子卷；不存在已验证可用的 Btrfs 快照路径。
- PATH 中未找到 lvs/lvdisplay/dmsetup/fsfreeze、restic/borg/zfs。底层 mapper 名称不足以证明有可用、一致的 LVM 快照。
- `sudo -n -l` 返回1，需要密码；未获得额外权限。
- rsync、tar、getfacl、getfattr 已有；普通复制不能提供跨文件生产一致性。尚无已经验证的应用级在线一致性快照机制。

因此严格停止 live data/Secrets/可变配置归档及完整恢复依赖工作；需要负责人另行批准维护窗口内停止写入/服务，或提供能够验证应用一致性的非中断机制及权限。不得以重复哈希不变、原子替换单文件、空闲连接或既有 freeze 副本代替本轮一致性证明。

## 私有备份目录建议

`/volume1/docker` 为 root:root mode0777，无 sticky bit；即使子目录0700，其父目录仍有路径替换风险。建议使用已经验证的 `/home/<nas-login>`（uid1000/gid10 mode0700）下独立0700备份根；其父 `/home` 为root:root mode0755。解密材料另放独立私有目录并由备份 Agent 管理。该 home 位于同一 NAS ext4 存储上，目录分离不等于异地灾备。

本 Agent 仅提供库存及障碍证据；不对备份完成、恢复或 B6 PASS 作声明。

## 维护窗口方案续查（仅计划授权，未执行）

以下仅为只读调查与本地文档补充，不授予或执行停写、stop、pause、restart、部署或其他容器变更。

### 写入者覆盖范围

遍历全部运行及停止容器的实际 Mounts，检查生产 data/secrets 本身、子路径及其祖先路径。命中两个运行容器：

| 容器 | 覆盖源/目标 | 权限与身份 |
|---|---|---|
| xiaozhi-product-v1-sidecar | data→/app/data；secrets→/app/secrets | data rw，secrets ro；用户10001 |
| <legacy-platform> | `/volume1/docker`→`/volume1/docker` | rw；默认root；覆盖生产data与secrets |

<legacy-platform>完整ID `419b486eb3e822aefc8bfc43e19d665465c27f3176b92e6cd89674eb12fb7e37`；镜像 `<platform-image>:v4.2.3-821`，完整镜像ID `sha256:d49ff0cd148688f34cb6bfa1f47d1814af19564abfee8ecd1665df7197d77d48`；Privileged=false、network=host、无host PID模式，入口可执行文件 `/bin/bash`。相关挂载还包含 `/volume1/docker/store`→`/data/store` rw；没有发现docker.sock挂载。仅记录可执行文件及挂载，不输出进程参数、env或配置内容。

该nblink镜像及进程名称提示它可能承担远程管理/连接用途，此为推断、尚未确认。停用可能影响管理通道；若方案涉及此容器，必须先确认责任人、取得额外批准，并验证独立本地恢复通道，不能盲目stop。

<legacy-platform>内现有进程名称为bash、<legacy-platform>（2个）、ownbsvman、sh、NodeBabyLinkSer，均UID0。容器内只读/proc FD调查：7个可访问进程、0个拒绝、0个生产路径FD命中。**没有打开的FD只是瞬时观察，不能证明后续不会打开路径写入。** 该root进程可通过祖先rw挂载触达生产目录，必须确认用途及维护期间的停写/隔离机制；未获批准不得擅自停止它。

主机/proc FD调查仅可访问1个进程，390个拒绝访问或已消失；无生产路径命中但不完整，不能据此排除主机writer。当前SSH用户 `crontab -l` 返回1、无可读任务。只读检查 `/etc/crontab`、`/etc/cron.d`、可读hourly/daily任务，无直接 `xiaozhi-product-v1` 或docker字符串引用；系统timer名称主要为sysstat/logrotate/apt/anacron/tmpfiles/dpkg/e2scrub/fstrim/ntpsec。root私有cron、NAS自身调度与间接调用脚本未全面验证；不输出任何原始任务行。这些仍属维护前需关闭的证明缺口。

### 实际生产代码的写入及锁结构

对运行容器内源文件做只读AST分析，不以候选ADMIN P0代码替代当前生产行为：

- `/app/app/admin/api.py`：Policy apply/rollback；Memory edit/delete/forget_category；Knowledge create_dataset/rename_dataset/set_dataset_enabled/delete_dataset/add_document/delete_document/rebuild_chunks。
- `/app/app/behavior.py:_memory_side_effects`：语音会话可调用save_preference、forget、note_weak_word。因此只有管理后台停用不足以关闭所有data写入。
- 三个Store使用 `modules/_store_lock.py` 的按路径in-process RLock，以及writer端 `<store>.lock` 的 `fcntl.flock(LOCK_EX|LOCK_NB)`，等待有界。锁不可用的其他异常会退化为仅in-process锁；锁是advisory，不能约束不遵守协议的外部进程，也不是整个目录的统一事务锁。
- 三个Store写文件采用tmp→os.replace；实际生产模块中未发现fsync调用。单文件atomic replace不能证明跨文件或断电持久性；不得靠持有几个锁或docker pause自行宣布一致。
- `/app/app/main.py:_run` 为SIGTERM/SIGINT注册事件处理，收到信号后清理admin listener与WS/HTTP runners。没有已验证的在线全局写闸。

关键实际源文件SHA-256：`_store_lock.py=c92cebb10a52b734436d9680fc60e13a61fd4bb3c088b37b2f7aeef499ae882f`，`main.py=40a423799d0e3cf17d43558a5081c3c6777db758740306d347c32751887185c6`。以上只证明当前代码结构，尚未执行维护停写或恢复测试。

### 补充运行规格及计划门禁

生产Memory=402653184（384MiB），MemorySwap=805306368（768MiB），MemoryReservation=0；CpuShares/NanoCpus/CpuQuota/CpuPeriod均0，CpusetCpus为空，PidsLimit未设置。RestartPolicy=unless-stopped、MaximumRetryCount=0；AutoRemove=false。未显式设置StopSignal、StopTimeout、Init、Tmpfs、GroupAdd、DNS或Ulimits，ExtraHosts为空；PidMode为空。精确恢复应从加密inspect完整复原，避免遗漏限制或使用daemon隐式默认值替代已保存规格。

待负责人批准维护窗口后，方案应先确认全部writer已受控，再优雅stop同一个共享生产容器，不使用docker pause充当flush。检查进程完全退出、未触发非预期SIGKILL，并同步已完成写入；若无法证明其他writer（尤其<legacy-platform>祖先rw挂载及主机调度）不会写，则不得开始一致性归档。任何强制kill、额外容器停机或挂载变更均需明确授权。

实时门禁应要求 `ws_connections=0` 且 `qwen_connected=0`，并取得用户当下无练习及维护窗口确认；`qwen_sessions=3`、`turns=26`是累计计数，不要求它们清零，也不能用它们代替活动连接数。零连接不自动授予停机权限。归档后重新启动生产也必须是后续明确批准的维护方案的一部分，本次未执行。

### 只读容量估算

2026-10-10 03:07:41 Asia/Shanghai：生产根可stat文件137个、逻辑字节58109596，唯一walk权限错误为data根；data另由既有生产容器只读stat确认7文件、217341 bytes。合计144文件、58326937 bytes（约55.6MiB），均未发现符号链接；目录元信息、ACL/xattr及归档开销不计入该总字节数。它不是一致性归档或读取吞吐基准。

分组：root files 15/40319 bytes；tests 68/1989374；modules 16/166125；admin-ui 5/57790；freeze 9/55609159；secrets 2/448；app 21/246082；config 1/299；data 7/217341。实际必要配置+data较小，freeze约53MiB；镜像174556624 bytes另计。不能仅凭这些容量承诺精确维护时长，须留归档、加密、全量校验、权限/xattr核验及恢复生产的裕量。
