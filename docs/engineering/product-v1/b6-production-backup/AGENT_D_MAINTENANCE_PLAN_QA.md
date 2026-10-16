# Agent D — 维护窗口方案独立安全审查

范围：仅审查后续方案。本轮未执行 stop、pause、restart、start、部署或其他生产变更。

**当前结论：维护施工 NO_GO，方案可继续准备。** 停止共享生产容器可以消除该容器内的写入，但不能单独证明所有生产数据写入者已关闭。A 新发现 `<legacy-platform>` 有整个 `/volume1/docker` 的 RW bind；身份/职责及其他主机写入者尚未排除。没有权限停止其他业务服务，不能将本方案视为现有施工授权。

## 必须满足的施工门槛

1. 产品负责人明确批准具体维护窗口、停止原生产容器和恢复原容器。维护同时影响语音28310、HTTP/OTA28311、管理后台28312，不能承诺只中断管理后台。
2. 执行前重新读取完整容器 ID、镜像、挂载、配置/Secrets 引用、RestartPolicy、StopSignal及当前连接。ws_connections=0、qwen_connected=0、负责人确认不在使用，全部成立才可发送停止请求；qwen_sessions/turns等累计值不属于“活跃为零”条件。
3. 完成所有写入者登记并取得关闭证据，包括 RW ancestor bind、同路径/卷的其他容器、主机进程、NAS 文件任务和外部文件共享访问。`<legacy-platform>` 未解释前中止；FD 扫描瞬时未发现写句柄或重复摘要相同都不能单独证明没有未来写入。不得自行暂停或停止其他服务。
4. 记录明确的备份与恢复执行身份。data mode700、Secrets文件mode600、不同 GID 和 NAS `ug.*` xattr 要求实际读取及恢复权限；不能假定 cap_drop=ALL 的 root helper 能读/恢复全部属性。能力不足则中止。
5. 安全备份路径、独立密钥管理、磁盘空间、加密工具、tar/ACL/xattr 能力、恢复测试隔离、失败恢复责任人及在线通知方式均已准备并验证。不得临时将原始 env、Secret 或 key 写入普通日志/报告。

## 无强杀停止与原容器恢复

- 优先使用已验证本机 Docker 支持的 `docker stop --timeout=-1 <原完整容器ID>`，并确认 StopSignal 为 SIGTERM（或默认SIGTERM）。先通过本机 help/API 能力检查；不照搬未知版本参数。
- 停止请求必须异步监督，轮询原完整 ID 的实际状态。无论客户端等待多久，都不切换为 SIGKILL、有限 timeout 的 `docker stop`、`docker rm` 或 force-recreate。
- 单独 `docker kill --signal=TERM` 不是已验证的等价替代；必须先证明 daemon 的手动停止/重启策略行为，不能让 unless-stopped 自动拉起破坏静止窗口。方案默认不采用此路径。
- “客户端等待超时”不等于容器已停止。仍 running/stopping 时不得备份为一致；停止请求可能仍在 daemon 内等待。此时中止备份并升级处理，禁止盲目重发 start 或声称服务已恢复。无强杀前提下无法保证任意故障均在固定时长内恢复，维护窗口风险说明必须写明。
- 仅在 Running=false、未 Restarting、其他 writer门槛仍成立后建立停机后基线。基线要包含优雅退出最终写入；停机前实时摘要只用于说明两者差异。
- 备份成功或失败都须进入受控恢复分支：对确认已停止的**同一原容器 ID**执行 `docker start <原完整容器ID>`，保留原镜像与参数。不 build、不 pull、不 recreate、不改restartpolicy、不改Secrets或data。
- 启动失败不是触发强制重建或历史镜像回滚的授权；保全状态、通知负责人、停止继续施工。

## 一致性归档与恢复验收

- 完整清单覆盖全部 data、Secrets、Compose及覆盖文件、env、镜像外配置/依赖；包括隐藏文件、嵌套目录、lock、历史备份、符号链接/硬链接与额外数据。对 symlink 指向的必要外部依赖单独清点，避免仅保存链接而遗漏内容。
- 保存并验证 numeric UID/GID、mode、ACL、全部可读取 xattr名称及值摘要、mtime/纳秒精度、链接关系。不能统一 chown 为10001:10001；当前文件存在10001:0。读取失败、tar warning、unsupported xattr、恢复权限不足均使该项失败。
- inode、ctime跨恢复通常变化，不能声明完全保留；报告区分可恢复元数据与观察信息。原目录 access time 可能受取证影响，不能当成逻辑数据一致性证据。
- 全量加密归档完成且 SHA/GCM 认证通过后，才允许解包或 Docker 加载。GCM认证完成之前不得把流式明文交给 tar/Docker。
- 重启原容器后立即核对同一镜像/容器、三端口、健康、语音装配配置及Tina配置、实际加载的active/history/audit与停机后基线。只读健康/配置检查，不新建真实付费 Qwen 会话；不改变原始Secrets或运行配置。启动可能改变lock文件等运行元信息，须单独解释。
- 完整隔离恢复必须使用独立daemon/数据目录/端口/网络；证明无真实Qwen及生产网络路由后才启动，使用Mock云端。真实Secrets恢复权限测试不能导致实例使用真实Token访问云端。
- 数据内容、PolicyStore字节及运行加载状态、静态资源与当前生产认证行为必须验证，不能用healthy或HTTP200替代。后续恢复中的版本1默认回退必须视为失败。
- 全部恢复及独立QA通过之前，B6仍为BLOCKED。B6通过也不授予候选ADMIN P0镜像部署权限。

## 部署失败时的数据处理

实际部署及回滚均需另行授权。应保全维护基线之后的新memory/knowledge/policy/audit等写入，再评估旧镜像兼容性；不能覆盖新数据为旧快照，也不能假定只换回镜像即可安全使用新格式。当前精确回滚镜像只认完整 `sha256:038d2f6c7a8945ff8ceadffdf100dc306123d51aa8b0ad2c4c48ed073b826611`；历史 `34ea8277…` 不是替代。

本文件是后续方案门槛审查，不是执行记录或B6通过证据。

## 方案草稿复核

D 已独立完整阅读工作区根目录 `B6_MAINTENANCE_WRITE_QUIESCE_PLAN.md` 与 `B6_PRODUCTION_BACKUP_RESTORE_FINAL.md`。

草稿正确区分提案与执行授权，明确B6仍BLOCKED、<legacy-platform>和未知主机writer未闭合就NO_GO、停机影响三端口、累计Qwen指标不等于活跃连接、无限优雅等待无强杀、只启动同一原容器、认证后解析、元数据精确核验、拒绝PolicyStore默认回退及后续写入保护；未发现把部分归档伪称完整恢复或把维护提案当施工授权的问题。

两项闭环补充建议已发送Lead：

1. 完整目录归档且“不解引用链接”之外，显式核查运行引用、symlink目标、子挂载及其他镜像外依赖是否均受清单覆盖。必要外部依赖未归档时NO_GO，不能仅保存链接后声称完整。
2. 隔离演练显式固定 `QWEN_MODE=mock` 与 loopback Mock endpoint，并在测试spec中记录这些必要偏差；不得直接拿原生产real环境启动。真实Secrets只用于单独内容/权限/只读挂载验证，不应进入发送凭据的Mock客户端路径。

此前data小目录量级不能代表整个生产根；A 后续实际测量为144文件、58326937 bytes（约55.6MiB），维护时长仍是未经实测的预算，执行前必须重新计量并验证吞吐。

审查意见：**可提交负责人审阅此提案；当前仍不得施工、不得判定B6 PASS、不得申请候选镜像生产部署。** 本次只读审阅未操作NAS生产服务。
