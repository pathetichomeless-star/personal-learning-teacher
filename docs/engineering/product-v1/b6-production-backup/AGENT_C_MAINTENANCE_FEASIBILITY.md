# Agent C：维护方案与恢复环境可行性（仅方案）

本次仅做只读分析；未停止、启动或重建任何生产/测试容器，未更改权限或运行时。既有 B6 结论仍为 BLOCKED。

## 新增只读证据

在 NAS 内对既有镜像归档完成完整 GCM 认证后，流式读取 layer tar，仅输出布尔检查结果，无明文落盘：

- 归档 layer 中存在 `/app/app/qwen.py`、`/app/modules/policy/persona.py`、`/app/tests/mvp_mock_qwen.py`、`/usr/bin/tar`。
- 加密保存的实际运行规格中，`QWEN_VOICE == Tina`、`FRAME_MS == 20`。
- 归档 Qwen 源码含 Tina 默认声线与 Mock 入口；Policy 源码含默认策略及 fail-soft 指示。
- 另从归档实际 `main.py` 做 AST 检查，确认 `_run` 的信号元组包含 `SIGTERM`、注册回调 `stop.set`、等待 `stop.wait()`、调用 `stop_admin_listener` 与 `runner.cleanup`；加密镜像规格的 StopSignal 缺省或与 SIGTERM 相容。这是静态支持证据，未实际发送信号，不保证退出耗时。
- 实际源码 AST 确认隔离替换变量名 `QWEN_MODE`、`QWEN_WS_URL`、`WORKBENCH_BASE_URL`，以及原始 Secret 引用变量 `QWEN_SECRET_FILE`。

上述仅为归档源码/捕获配置证据，未执行镜像代码，也未完整重放 overlay whiteout，不能替代恢复实例行为测试。tar 二进制存在不等于其 ACL/xattr 功能已验证。

## 恢复环境建议

1. **现有 NAS Docker，独立测试容器/目录，network none：有条件可行。** 复用已有完整生产镜像，无拉取。通过仅 loopback 的 Mock Qwen/Workbench 与容器内探针验证恢复内容、认证和语音装配；不给测试容器生产挂载、网络、Docker socket 或主机端口。此方案可以完成应用恢复测试，不能证明镜像在独立 image store 中加载。
2. **NAS 新增独立 rootless runtime：须额外批准部署与预检。** 当前缺少已验证的 rootlesskit、UID/GID 映射辅助工具、subuid/subgid 配置和 user namespace 可用性。必须有独立 daemon/socket/data-root/containerd 状态及可验证隔离。rootless 身份映射不能直接保证原主机 numeric UID/GID，更不能保证 NAS `ug.*` xattr 可恢复；该方案只解决独立镜像加载，元信息仍需 NAS 管理员验证。
3. **NAS 管理员提供独立测试 daemon/VM：优先。** 使用现有可执行文件及保存镜像，独立 image store、socket、运行状态目录，不复用生产 containerd 状态。无桥接、无主机端口、禁止改动生产 iptables/路由；先证明与生产 daemon 的身份/目录完全独立。创建该环境及所需 host root 权限需额外授权，不自行配置 sudo、绕过权限或启用 privileged helper。
4. **获批的 arm64 本地隔离运行时：备选。** 当前本地无 Docker CLI。安装运行时、将密文归档迁出 NAS、分开转交密钥都需明确批准；不能根据本轮 NAS 内授权自行实施。离线验证需禁止镜像自动拉取。

## 完整元信息备份/恢复前置要求

由获授权的 NAS 管理员使用主机已验证 GNU tar 完成源目录读取、numeric ownership 归档及隔离目标恢复；不调整生产 data/Secrets 权限。优先避免通过容器 helper 处理源目录，以免 NAS 属性权限受默认 capabilities 限制。

- 必须包含完整 data、Secrets、实际 Compose/env、外部配置及其恢复依赖，包含隐藏文件、锁文件、旧策略副本等。完整性范围由冻结目录清单确认，不能只挑三个 JSON。
- 捕获文件类型、numeric UID/GID、mode、所有 ACL 项、**所有可读取 xattr 的名称和值**、软/硬链接关系和可保存时间戳。xattr 值与 Secrets 内容同样加密，不进入报告。
- 已观察到 `ug.archive_bit`、`ug.archive_version`、`user.ug.flags`。GNU tar 需要验证 `--acls --xattrs --xattrs-include='*' --numeric-owner` 等支持；仅默认 `user.*` 范围会遗漏 `ug.*`。恢复需验证 `--same-owner --same-permissions --acls --xattrs --xattrs-include='*'` 等行为及目标文件系统支持。
- 在批准的全新测试目录先证明 NAS `ug.*`、ACL 与所有权可精确回写。root 容器的默认 capabilities 不等于拥有全部 NAS xattr 权限；某些命名空间/厂商属性仍可能拒绝，禁止通过 privileged 或额外 host capabilities 自行绕过。无法还原必须明确 BLOCKED，不能静默忽略警告。
- inode/ctime 通常不可保留，列为已解释差异；mtime、支持的 atime/精度、硬链接、ACL/xattr 不能未经验证宣称一致。

## 一次停机取一致性归档的建议边界

仅在负责人明确批准维护窗口、停止权限、元信息操作权限及最大可接受中断后执行。以下不是可执行停止脚本：

1. 维护前完成独立恢复环境和元信息预检、空间/加密/密钥/归档工具预检；固定实际完整镜像、容器 ID、启动命令、全部环境/挂载引用与 Tina/音频配置私有指纹。查明所有可能修改该目录的写入者，窗口内禁止并发管理修改。
2. 停止前即时读取语音连接/Qwen 状态；同时由负责人确认当前不在练习。仅空闲观察不构成停止授权；若基线变化或仍有连接，退出维护流程。
3. 温和停止**既有容器**并确认进程退出后，才开始读取完整可变备份源。计划设置 `--timeout=-1`，避免有限 stop timeout 自动升级为 SIGKILL；若不能正常退出，立即报告并按负责人预先确定的超时方案处理，不自行强杀。本文件不提供或执行停止脚本。
4. 在没有其他写入者的静止区间中完成元信息/文件清单与流式认证加密归档，fsync；记录一致性区间而非虚构快照瞬时点。只有相关所有写入者静止，才能称为一致性归档。
5. 归档完成后启动**同一个既有容器**，因此保留完整生产镜像 `sha256:038d2f6c7a8945ff8ceadffdf100dc306123d51aa8b0ad2c4c48ed073b826611`、原启动规格和原数据挂载；不使用 build、pull、compose up/recreate、候选 ADMIN P0 或旧 `34ea8277...` 替代品。维护前发现生产完整 ID 已变则重新冻结并请求确认。
6. 只读检查三端口、healthy、生产镜像/容器身份、Tina/音频配置指纹、PolicyStore 实际加载版本/历史/审计；不连接真实 Qwen 来验证。服务恢复即结束停机区间，之后独立测试从加密归档恢复，不延长生产中断等待全部演练结束。
7. 若归档步骤失败，保留失败材料；优先按已批准恢复方案启动原既有容器，不覆盖生产数据。若生产启动失败，不自行切换镜像、恢复旧数据或修改 Secrets，进入负责人预先批准的故障处理边界。

Tina 不变的判据是同镜像、同配置/Secrets 字节与环境、同音频参数、同挂载关系；测试实例只对云端依赖作明确安全替换。恢复演练不会证明真实 Qwen 声音效果，不能以调用付费云端补测。

## 结论

停机一致性归档和 NAS 管理员元信息能力是当前主要缺口；独立 image store 仍需额外环境能力。批准停机本身不会自动解决独立加载与 `ug.*` 属性恢复。两个前置缺口应在维护窗口前明确解决，避免停机后才发现无法交付 B6 PASS。
