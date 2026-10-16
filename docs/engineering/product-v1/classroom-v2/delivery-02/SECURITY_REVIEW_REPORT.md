# CLASSROOM V2 · DELIVERY GATE 02 — 安全复核报告

- **独立安全复核：NOT_COMPLETED（429 额度中断，见 INDEPENDENT_QA_REPORT.md §1）→ 安全门禁维持全部关闭**
- 生成时间：2026-10-12 23:50 (UTC+8)
- 本报告性质：登记总控侧**事实性自查证据**（可复算哈希与字面扫描），**不构成安全签收**。

## 1. 门禁状态（未解除事项）

| 门禁 | 状态 |
|---|---|
| 正式学生白名单服务（/cls/knowledge/* 真实服务端路由） | **维持不开放**（契约与测试就绪，但未部署、未联真实服务） |
| 最终课程发布 API | **维持不开放**（发布页为本地 Mock 门禁态） |
| NAS 连接/修改 | **无**（本轮零 NAS 操作） |
| Tina 生产凭据使用 | **无**（客户端老师链路为 Mock/演练态） |
| 真实付费 AI 模型请求 | **无**（零付费调用；语音演练为纯本地 Mock） |

## 2. 总控侧事实性证据（可复算）

1. **包内凭据扫描**（`Contents/Resources`、`Contents/Frameworks/src` 文本资源，模式：`sk-*`/`api_key=`/`TEACHER_VOICE_TOKEN`/`ADMIN_TOKEN`/`Bearer`/`secret=`）：**0 命中**。
2. **包内非环回 URL 扫描**（QML/JSON/plist/txt）：仅命中良性文档/命名空间串（`json-schema.org`（$schema 声明）、`w3.org`、`qt.io`、`m3.material.io`、`philrathe.com`/`angularjs.org`（随包第三方 JS 库内注释））。**无任何指向生产网关、NAS、阿里云 MaaS 的地址**。
3. **可执行二进制 strings URL 粗筛**：`https?://` 且非环回 **0 命中**。
4. **学生 .app 不读正式配置**：`classroom_env.py` fail-closed 设计——检测到正式客户端目录即退出码 3 拒绝启动（开发方 FIX01 改动；独立复核待办）。
5. **无子进程能力**：开发方 boundary_check D02（AST 级）PASS；独立 QA 须自写 AST 扫描复核，不得引用。
6. **冻结/保护面**（总控 23:40 亲自复算）：冻结六文件 git diff 空 + 哈希==基线；数字人 5 文件==基线；HEAD/暂存区未动（boundary_check 13/13）。

## 3. 待独立安全复核清单（通过前门禁不解锁）

1. 最小权限学生子应用模型：.app 进程权限面、可写目录范围（应仅限独立演示目录）。
2. IPC/本地服务面：环回监听地址与端口、是否可被同机其他用户访问。
3. 会话密钥：演示令牌的生成、落盘权限（600）、生命周期与失效路径。
4. 路由白名单：学生端可达路由枚举（应仅老师列表/静态资源/Mock），与 `/admin/*` 的隔离证明。
5. 资源隔离：与正式客户端配置（`~/Library/Application Support/py-xiaozhi/`）、NAS 生产数据的读写隔离实测。
6. 包内 PYZ 逐模块反查（确认无隐藏管理端代码路径）。

**判定：SECURITY_REVIEW = NOT_COMPLETED / GATE CLOSED。**
