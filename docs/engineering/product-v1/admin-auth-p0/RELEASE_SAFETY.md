# RELEASE_SAFETY — admin-auth P0 修复发布安全评估

date: 2026-10-09
scope: 判定 admin-auth 修复是否可在**不破坏 PO 英语练习所用实时语音（28310）**的前提下部署。只读审计，NAS 上未做任何变更。

```
RELEASE_SAFETY
date=2026-10-09
COLOCATION=<同一容器同一进程：xiaozhi-product-v1-sidecar（295eb64dc48c，镜像 038d2f6c7a89，tag admin-visual-v2-release / latest），单进程 `python -m app.main`，端口映射 8110→28310(语音WS) 8111→28311(OTA/health) 8112→28312(admin)。docker inspect 实测 + 启动日志同一进程依次 listen 8110/8111/8112 ⇒ 任一容器 recreate = 三端口同时中断，admin 修复必须通过整容器 recreate 落地>
CURRENT_WS=<0>（docker exec /health on 8110：ws_connections=0, qwen_connected=0, turns=0, uptime≈29550s，容器 Up 8h healthy）
RESTART_IMPACT=<应用监听 <1s：StartedAt 06:36:55.857Z → 日志 "listening ws on 0.0.0.0:8110" 06:36:56.729Z（0.87s）。HEALTHCHECK interval=30s/start-period=10s ⇒ recreate→healthy 在首个探针窗口（≈10–30s，与 deploy-log #93 A3 记录的 recreate→healthy 流程一致）。drop 风险：ws=0 时零活跃客户端被断；若 PO 正在练习，recreate 会即时断开其 WS（客户端可重连，但练习会话中断）>
DEPLOY_RECOMMENDATION=<选 (a) ws=0 时共享容器 recreate，附双重前置条件：① recreate 前一刻实测 ws_connections=0（>0 则中止改约窗口）；② PO 明确确认当前不在练习（任务规则：练习期间禁止自动重启）。执行序：ws=0 复查 → PO 确认 → docker compose up -d --force-recreate → healthy → unauth 401 → admin 200 验证 → /health ws=0。备选 (b) 与 PO 约定维护窗口，仅在 (a) 前置条件无法满足时使用。全程不触碰模型/Tina/策略，与 #93 冻结面一致>
ROLLBACK=<deploy-log #93 已验证路径：docker tag xiaozhi-product-v1-sidecar:XIAOZHI-VOICE-V1-HUMAN-ACCEPTED xiaozhi-product-v1-xiaozhi-product-v1-sidecar:latest && docker compose up -d --force-recreate（回到镜像 34ea8277cb57；数据/策略/审计保留）。两镜像 tag 均在 NAS 实测存在（038d2f6c7a89 / 34ea8277cb57）>
BACKUP_LIST=<仿 freeze/pre-adminv2 模式，发布前建 freeze/pre-adminauth-p0/：① docker-compose.yml（/volume1/docker/xiaozhi-product-v1/）② .env ③ policy_v20.json ④ running_image_id.txt=038d2f6c7a89 ⑤ secrets/（product_v1_admin_token、qwen-realtime.env）只读副本 ⑥ config/config.json。现有参照：freeze/pre-adminv2/{docker-compose.yml,policy_v20.json,running_image_id.txt} 与既有 *.pre-*.bak 序列>
```

## 证据明细

1. **共置（colocation）** — `docker inspect xiaozhi-product-v1-sidecar`：HostConfig.PortBindings = `{"8110/tcp":[{"HostPort":"28310"}],"8111/tcp":[{"HostPort":"28311"}],"8112/tcp":[{"HostPort":"28312"}]}`；Cmd=`["python","-m","app.main"]`（Entrypoint null）。启动日志同一 PID 依次输出 `listening ws on 0.0.0.0:8110` → `listening http on 0.0.0.1:8111` → `rtl.admin.auth admin token material updated`（8112 侧）。结论：语音 WS、OTA、admin 同容器同进程，任何 admin-auth 部署 = 容器 recreate = 28310 WS 必然短暂中断。
2. **当前语音状态** — 容器内 `/health`（127.0.0.1:8110）：`ws_connections: 0`、`turns: 0`、`qwen_connected: 0`，uptime ≈ 29550s。此刻 recreate **不会断开任何活跃客户端**。
3. **重启影响窗口** — 实测启动日志：容器 StartedAt `2026-10-09T06:36:55.857Z`，`listening ws on 0.0.0.0:8110` 于 `06:36:56.729Z`（≈0.87s）。Dockerfile HEALTHCHECK `--interval=30s --start-period=10s`；deploy-log #93（2026-10-09，ADMIN-VISUAL-V2 发布）A3 记录流程 `ws=0 确认 → up -d --force-recreate → healthy → unauth 401 → 10/10 端点 200`，即 recreate→healthy 为秒级~半分钟窗口；"≈15s" 为该窗口的工程近似（日志未记精确秒数，本文以实测 0.87s 监听 + 首探针 healthy 为准）。
4. **部署选项** — (a) 共享容器 recreate @ ws=0：代价 ≈10–30s 无人连接窗口，ws=0 时不掉任何客户端；PO 若恰在此刻发起练习，其客户端会经历一次重连。(b) 与 PO 约定维护窗口：仅在 PO 正在练习/即将练习时采用。**推荐 (a)，条件：ws=0 实测通过 + PO 口头确认**；两者任一不满足则转 (b)。
5. **回滚** — deploy-log #93 原文 rollback A：`docker tag xiaozhi-product-v1-sidecar:XIAOZHI-VOICE-V1-HUMAN-ACCEPTED xiaozhi-product-v1-xiaozhi-product-v1-sidecar:latest && up -d --force-recreate`（数据/策略审计保留）。NAS 实测镜像表：`...:admin-visual-v2-release = 038d2f6c7a89`、`...:XIAOZHI-VOICE-V1-HUMAN-ACCEPTED = 34ea8277cb57`，回滚路径可直接执行。
6. **备份（发布前）** — 按 #93 A2 freeze/pre-adminv2 模式落盘（见上方 BACKUP_LIST），关键点是把运行镜像 ID 038d2f6c7a89 写入 running_image_id.txt，保证回滚锚点可查。

## 结论

admin-auth 修复**可以安全部署**：admin 与语音共置使 recreate 不可避免，但当前 ws=0，且应用冷启动监听 <1s、healthy 在首探针窗口内；按 (a) 方案在 ws=0 + PO 确认双条件下执行，回滚路径已验证存在。唯一不可接受的是在 PO 练习期间自动重启。
