# B6 Agent B — Secure Backup

执行者：Lead，独立于 A/C/D 的取证、恢复验证和 QA 工作流。
结论：**PARTIAL**；完整一致性备份 **BLOCKED**。

## 已执行

- 重新读取运行容器后，以完整不可变镜像 ID 执行 `docker image save`，未使用可变 tag。
- 当前镜像：`sha256:038d2f6c7a8945ff8ceadffdf100dc306123d51aa8b0ad2c4c48ed073b826611`。
- NAS 归档目录：`/home/<nas-login>/.xiaozhi-b6-backups/b6-20261009T190033Z`。
- 独立密钥目录：`/home/<nas-login>/.xiaozhi-b6-keys/b6-20261009T190033Z`。本报告只记录位置，不含解密材料。
- 归档和密钥目录均 0700，文件均 0600；父目录是用户私有 home，上级 `/home` 为 root 所有 0755。
- `/volume1/docker` 为无 sticky bit 的 0777 共享父目录，因此未用于安全归档。
- 每个归档使用独立随机 256-bit 密钥、96-bit nonce 和 AES-256-GCM 认证加密；格式版本头与 nonce 作为 AAD。
- 完整镜像保存时直接流式加密，无明文 tar 落盘。
- 原始容器 inspect 与镜像 inspect 仅写入加密归档，包含恢复所需的有效运行参数；未打印原始 env 或秘密。
- 对每个归档完成整流解密认证、明文 SHA-256 回读比较，建立密文 SHA-256 清单，文件与目录执行 fsync。
- 工具脚本、脱敏清单保存在本证据目录。密文及密钥均留在 NAS，未上传或传输至外部。

实际结果见 `BACKUP_MANIFEST.json`。NAS `SHA256SUMS` 覆盖 3 个密文归档和清单本身；D 独立复算，不依赖 B 的 PASS。

## 未执行及原因

`findmnt` 确认生产持久化路径所在卷为 ext4；Btrfs 查询明确失败，无已验证可用的一致性快照流程。当前普通用户无非交互 sudo，常见 LVM/冻结工具缺失。不能从这些结果推断 NAS 永远不支持快照，只能判定本轮尚无可安全执行、已验证的机制。

依据产品负责人边界，停止完整 data、完整 Secrets、实际 Compose/env 和配置依赖的归档以及后续恢复步骤。未将在线目录的普通复制或重复哈希宣称为一致性备份；未调用 pause/stop/restart/recreate/fsfreeze/sync 或修改生产文件。

运行规格的加密 JSON 不能替代完整 Secrets 与原始 Compose/env。镜像归档完整性也不能替代独立 image load。镜像包含的配置/静态资源不代表所有外部恢复依赖均已覆盖。

## 安全和恢复限制

- 分目录管理密钥已落实；密钥和归档仍位于同一 NAS、同一用户账号，不具备异机密钥托管或整机灾难恢复能力。
- 解密时必须先完成**整个**归档的 GCM 认证，再向 Docker/tar 等解析器提供明文；不得在 tag 校验前导入或执行内容。
- 本次没有数据一致性时间点，不得将归档生成时间当作 PolicyStore/数据快照时间。
- 不存在可由本次部分备份单独完成的精确全量回滚流程。完整回滚必须补齐一致性数据/Secrets/配置备份和独立恢复验证。
