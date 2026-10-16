# V0 安全实现核验（READ-ONLY 审计，对照 VISION_SECURITY_REVIEW.md）

- 核验对象：commit `64e543a`（分支 `avatar-vision-v0`，基线 `d5644f1`）
- 审计方式：只读代码审计 + 实测运行三套测试；本报告为唯一写入产物
- 日期：2026-10-09（UTC）
- 前置文档：VISION_SECURITY_REVIEW.md（R1–R10 预实现需求审计）

---

```
V0_SECURITY_VERIFICATION
date=2026-10-09 (UTC)
commit=64e543a
R_COVERAGE=
  R1  SATISFIED(原型层)   camera default OFF: vision_v0.html:35(video hidden)/41(capture disabled);
                          显式点击: :79-91 getUserMedia 由点击触发, catch→"授权拒绝…语音不受影响";
                          STOP 释放: :93-98 track.stop()+srcObject=null;
                          GAP(遗留,非V0切片): 客户端 take_photo 语音触发与 VLCamera 直连旁路的停用
                          未在本切片内（V0 为 mock 原型+网关守卫，客户端集成延后，须在 V1 前关闭）
  R2  SATISFIED          magic 嗅探: vision_v0_logic.js:12 / qwen.py:699-702 (FFD8FF);
                          尺寸: :15 (190KB) / qwen.py:704-706 (raw≤190KB) / :716-719 (b64≤256KB);
                          EXIF 剥离: vision_v0.html:100-115 canvas 重编码 + 长边≤1280px(compressPlan,
                          vision_v0_logic.js:21-28); 全部守卫在发送前判定，超限不产生任何网络字节
  R3  SATISFIED          双层限速: 前端 vision_v0_logic.js:35-50 (≥5s 间隔 + ≤6/60s)；
                          网关 qwen.py:710-714 (interval≥5.0s) / :715-717 (≤6/min)；
                          无连拍/无流式/无定时自动采集（grep 无 setInterval 采集路径）
  R4  SATISFIED          会话隔离: vision_v0_logic.js:53-68 createIsolation（跨会话 add 返回 false，
                          rotate 清空旧缓冲）; 网关侧图像仅走本连接私有 _ws（qwen.py:695,717），
                          无可伪造的 session 参数; 未触碰 MEMORY/KNOWLEDGE/POLICY 文件
  R5  SATISFIED          零落盘/零图像日志: diff 中 qwen.py 新增行 grep log|print|open|write|imwrite
                          = 0 命中; mock /__log 仅记录 {t, mode, bytes}（vision_mock_server.py:83-84，
                          注释"仅记录大小，不记录图像内容"）
  R6  SATISFIED          图像即逝: vision 原型 grep localStorage|sessionStorage|cookie = 0 命中；
                          网关 b64 为 send_image 局部变量，发送后无缓存/无重试队列
  R7  PARTIAL            无自动重试 SATISFIED（send_image 单发、无重试环，qwen.py:697-720）；
                          GAP(轻微): 网关仅本地 _vision_rejected 计数（qwen.py:303），
                          vision_captures_total 等全局 counters 未接线（counters.py 零 diff）——
                          V0 mock 阶段可接受，接真实模型前须补
  R8  SATISFIED          avatar_v0.html/avatar_v0_logic.js: grep fetch|WebSocket|XMLHttpRequest|
                          getUserMedia 仅命中 1 处注释文字; 渲染为纯 Canvas 2D; 音频为本地
                          OscillatorNode（avatar_v0.html:61-74），零设备采集零网络
  R9  SATISFIED          降级路径: vision_v0.html:125-128,145-148（一次性降级文案，语音不受影响）;
                          网关拒绝返回 (False, reason) 元组不抛异常（qwen.py:697-720）;
                          avatar 打断清零: mouth.hardClose（avatar_v0_logic.js:52）/ newTurn 防串(:59-61)
  R10 SATISFIED          无新端点/端口: send_image 复用既有 WS 连接 _send_json(self._ws)（qwen.py:717），
                          gateway/app 仅 qwen.py 一个文件变更; mock 服务绑定 127.0.0.1:18766
                          （vision_mock_server.py:114）
SEND_IMAGE_REVIEW=
  守卫顺序（qwen.py:697-720）: not_connected → JPEG magic(FFD8FF) → raw≤190KB →
  ordering(_audio_seen) → interval≥5s → per-minute≤6 → b64≤256KB → send_json+记窗口。
  与规范顺序一致（magic→size→ordering→interval→per-minute→b64）。
  绕过分析:
  - _audio_seen 仅在 send_audio（qwen.py:687）置位，send_image 是图像唯一入口，
    无旁路调用; 图像先于音频被拒（V4 测试）。
  - 状态全部为实例属性（qwen.py:299-303 __init__），非类属性，实例间不泄漏（V8 测试:
    client B 不受 client A 音频历史影响）。
  - 重连复位位于连接成功路径（qwen.py:463-465，紧跟 _connected=True），新会话重新
    强制 ordering（V9 测试）。
  - 拒绝路径: 所有 early-return 发生在任何 _send_json 之前，仅动 _vision_rejected
    计数器; 音频缓冲/_audio_seen/_vision_window 均不被触碰（V1b/V7 测试: 拒绝后音频
    上行正常）。b64 超限拒绝发生在 window.append 之前，不污染限速状态（失败尝试不占
    限额——不产生字节故无计费风险）。
  - 已知设计假设: _audio_seen 按 WS 连接生命周期而非 per-commit 复位; 与文档语义
    （"首图前至少一次音频 append"）一致，V0 可接受。
FREEZE_AUDIT=
  git diff d5644f1..64e543a -- gateway/ tools/ → 仅 3 个文件:
  gateway/app/qwen.py (+54, 纯增量)、gateway/tests/vision_v0_tests.py (新增)、
  tools/vision_mock_server.py (新增)。
  gateway/app/audio.py / turns.py / ws.py / counters.py / diag.py / admin/ 均零 diff;
  仓库无独立 vad/pacing 模块文件（audio 路径文件全量核对为零变更）。
  原型层不含任何音频回放链路（avatar 使用独立本地 OscillatorNode）。
PRIVACY_AVATAR=
  - 图像字节零落盘零日志: qwen.py 新增行无 log/print/open/write; 前端无持久化 API;
    mock /__log 只含 size。
  - avatar 零网络零设备: grep 证实无 fetch/WebSocket/getUserMedia（唯一命中为注释）;
    纯本地 Canvas 2D + 本地振荡器。
TESTS=vision_v0 13/13 PASS; avatar_logic 16/16 PASS; vision_logic 17/17 PASS
  (命令: cd gateway && DYLD_LIBRARY_PATH=/tmp/opus131/lib .venv/bin/python
   tests/vision_v0_tests.py; node prototypes/tests/{avatar,vision}_logic_tests.mjs)
VERDICT=PASS
```

## 结论

**PASS**。实现与 VISION_SECURITY_REVIEW.md 的 V0 硬条件逐条对应：图像五件套
（嗅探/上限/限速/隔离/即逝）在前后端双层落实；send_image 守卫顺序正确、拒绝路径
不污染音频与限速状态、重连复位在连接路径上；冻结审计确认音频/VAD/pacing 面
零 diff；隐私面（零落盘/零图像日志/size-only mock）与 avatar 隔离（零网络零设备）
均经 grep 与测试双重证实。

### 遗留项（不阻塞 V0，进入真实模型/V1 前必须关闭）
1. **R1 遗留**：客户端 `take_photo` 语音触发与 `VLCamera`（直连智谱 API）旁路尚未
   停用——客户端集成不在本切片内，接真实链路前必须关闭，否则数据生命周期图不成立。
2. **R7 轻微缺口**：网关仅本地 `_vision_rejected` 计数，`vision_captures_total` /
   `vision_bytes_total` / `vision_rejects_total{reason}` 未接入全局 counters（/health
   不可见）；接真实模型前补齐。
3. **传输路线注记**：当前网关图像走 WS JSON 帧（b64≤256KB），未受 64KB 全局 JSON 帽
   约束是因为未经过 protocol.py 的消息入口（直接 _send_json）；若未来图像消息改经
   统一入口，须按预审计 R2 走 binary 帧或单设帽。
