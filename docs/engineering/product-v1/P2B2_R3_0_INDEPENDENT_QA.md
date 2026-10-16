# P2-B2-R3-0 独立 QA 记录

**复核对象**：最终 HEAD `7fdd68d`（docs-only）；**唯一代码提交 `3b13c4c`**（父提交 `4669b59`）。
`git diff --stat 3b13c4c 7fdd68d -- gateway/` 为空 ⇒ HEAD 的代码与 `3b13c4c` 逐字节相同。

**方式**：独立 QA 智能体（**未参与本轮施工**），仓库只读，自写探针脚本仅写入 `/tmp`，
全部使用 Mock 上游与隔离夹具，无网络、无密钥、无付费、无 NAS。
**范围**：`gateway/app/teacher_voice.py`（本轮唯一改动的产品代码）、`gateway/app/teacher_context.py`、
`gateway/app/main.py`、`gateway/tests/teacher_voice_seam_tests.py`、`gateway/tests/teacher_context_seam_tests.py`、
`modules/model/gating.py`、`modules/model/registry.py` 只读参考。

---

## 一、QA 复核的产物（sha256，**已提交版本**）

```
ed3be714a5e9c7f6f3307ad28dc05adf27a77b521eff6acc7946ceb3ba84cf68  gateway/app/teacher_voice.py
bae0db6fe6ac12b859e7ef309a89430a855beceece214ef1fe024fae8c811b42  gateway/tests/teacher_voice_seam_tests.py
b5de961dbefbd4c35143a110729f871ea908d864d8561c6a5a3b429e532058be  gateway/tests/teacher_context_seam_tests.py
13d679c4d9532de223d6f939efe96ad70140854db3b3c8d0e723e0d06c9801a6  gateway/app/teacher_context.py
cc2f65d373f6a0049ca8f96cd4be82b13db0bf469b5f9f3cdfc0953ef61ecfae  gateway/app/main.py
3d3cae0ebcf054f80a93e33421e52e16242af5f498627ee9c03ceaad4ccda247  modules/model/gating.py
794f50772ce1e8c70f2fd7441585ad0f46a29798f87fa30fe4bb0b695c9b2ef2  modules/model/registry.py
```

> 与 R2 的差别（R2 教训的整改）：R2 的 QA 记录钉的是**未提交工作树**哈希，导致"QA 复核了什么"与"提交了什么"
> 之间缺少可追溯链路（见交付记录 §5.3）。本轮 QA **只钉已提交产物**，且下列哈希均由 QA 亲自计算。

---

## 二、QA 结论

```
VERDICT: QA_PASS_WITH_NOTES
```

**0 个 P0 / 0 个 P1 / 0 个 P2 / 6 项 P3。**

QA 明确声明：它在最终 HEAD 上**亲自运行了全部 25 个 gateway 套件 + 2 个 client 套件**（未采信施工方数字），
因此满足"若最终 HEAD 的完整测试没有经过独立复核，不得声明最终 QA PASS"的前置条件。

---

## 三、逐项判定（QA 原文摘要）

| # | 项 | 判定 | 证据（QA 给出的） |
|---|---|---|---|
| 1 | `model.enabled` 门禁 | **PASS** | `gating.py:26-55` 确不读 `enabled`；`teacher_voice.py:384-385` 位于 `frozen`(366) 之后、credential(403)/endpoint(414) 之前；QA 自写探针 16/16（enabled / disabled / 缺键 / 顺序翻转 / 无回退） |
| 2 | 拒绝先于真实连接 | **PASS** | HEAD 行号：resolver@493 < context@505 < config@516 < `ws.prepare`@524 < `Connection`@526 < record@533 |
| 3 | frozen 模型 / provider 拒绝保留 | **PASS** | 探针 3a → `frozen_model`；3b → `frozen_provider`；两者均不返回 config |
| 4 | R1 凭据隔离未回退 | **PASS** | 探针 4a–4e 全过；套件 T11a–T11i 在 60/60 内全绿 |
| 5 | R2 上下文注入未回退 | **PASS** | QA 自写探针 10/10；`teacher_context.py` 本轮逐字节未改；套件 83/83 |
| 6 | 课堂记录 teardown | **PASS（有注）** | T13k（正常断开）通过；**T13l 确非恒真** —— 构造"去掉 `asyncio.shield`"的 /tmp 模块副本后，观察到 `close=1 finish=0 → FAIL` |
| 7 | 默认关闭时 Tina 路径不变 | **PASS** | QA 自写探针 8/8；默认 `create_app` 不含 teacher 路由，`/xiaozhi/v1/` 仍在 |
| 8 | 数字人文件未触碰 | **PASS** | 本轮两提交对该组文件命中 **0**；工作树仍为 `M` / `??` 状态 |
| 9 | 冻结六文件逐字节一致 | **PASS** | 六个 sha256 与交付记录 §三完全一致；`4669b59..7fdd68d` 对六文件 diff 为空 |
| 10 | NAS 零改动 | **PASS（受限）** | 提交内容无 NAS / 部署痕迹；**QA 无法访问 NAS**，只能作此限度证明 |
| 11 | FINAL_HEAD 全量测试 | **PASS** | 22 套件 **1179/1179**；client **48+25 = 73/73**；3 个失败套件在父提交纯净 worktree 复现（见第五节） |
| 12 | 文档数字对账 | **PASS（有注）** | 67 陈旧 ✓、81 未提交 ✓、82 已提交 ✓、54→60 ✓、3/5 哈希不符 ✓；但发现交付记录 §5.5 自身有 1 处哈希笔误（P3），已勘误 |
| 13 | 自我证伪 | **PASS** | 破坏上下文探针 → 5e/5g FAIL；删除门禁的 /tmp 模块副本 → disabled 与缺键**均解析出配置**（证明检查是承重的） |

---

## 四、QA 发现（6 项 P3，全部为文档/环境级）

| 编号 | 级别 | 发现 | 施工方处置 |
|---|---|---|---|
| **Q3-1** | P3 | 交付记录 §5.5 把 `gateway/app/teacher_context.py` 的哈希误写为 `dd04a6aa…`（实为 `teacher_context_seam_tests.py` 在**父提交**的哈希）；正确值 `13d679c4…` | **已勘误**：§5.5 表格改为 `13d679c4…`，并补勘误说明。施工方复核确认 QA 正确（`shasum` 实测与 `git show 4669b59:` 均为 `13d679c4…`） |
| **Q3-2** | P3 | 交付记录 §2.2 引用的 handler 行号（471/483/494/502/504/511）是**父提交**行号，HEAD 实为 493/505/516/524/526/533 | **已修正**：§2.2 并列给出两套行号并注明差值 22 = 本轮新增行数 |
| **Q3-3** | P3 | 交付记录前向引用了当时尚不存在的 `P2B2_R3_0_INDEPENDENT_QA.md` | **已消解**：该文件即本文档，随后以同一检查点提交落地 |
| **Q3-4** | P3 | 主工作树 `r1f_tests` 176/179 比纯净基线 177/179 少 1 项；根因为被 `.gitignore` 忽略的 `gateway/app/.DS_Store`（Finder 生成，2026-10-09） | **登记未执行**：删除本地被忽略文件属本轮授权范围外的环境卫生；已在交付记录 §六.9 登记，删除即可恢复 177/179 |
| **Q3-5** | P3 | 既往基线债：`admin1_tests` 81/83（`/xiaozhi/vision/` 多出第 7 条路由 + `api_model.py` 含 `urllib`）、`client_ui1_integration` aiohttp 重置 —— 二者在父提交 worktree 同样复现 | **登记**：非本轮引入，归 vision / admin-model 线路收敛 |
| **Q3-6** | P3 | 工作树含 URL 编码名的未跟踪文件（`%E5%B0%8F…_V2.md` / `…_V2.zip`） | **登记**：非本轮产物，待归属 |

---

## 五、QA 独立实测的测试计数（最终 HEAD）

命令前缀：`cd REPO/gateway && PYTHONPATH= DYLD_LIBRARY_PATH=REPO/client/libs/libopus/mac/arm64 <xiaozhi-p2b2-python> tests/<suite>.py`；
客户端使用 `client/.venv`（Python 3.10.20）。

| 套件 | QA 实测 | 套件 | QA 实测 |
|---|---|---|---|
| `teacher_voice_seam_tests` | **60/60** | `persona_policy_tests` | 62/62 |
| `teacher_context_seam_tests` | **83/83** | `admin2_tests` | 69/69 |
| `model_v4_tests` | 72/72 | `product_v1_integration` | 33/33 |
| `teacher_v4_tests` | 46/46 | `product_boundary_tests` | 23/23 |
| `teaching_v4_tests` | 36/36 | `admin_ui_tests` | 23/23 |
| `teaching_assessment_v4_tests` | 28/28 | `memory1_tests` | 19/19 |
| `voice_v4_tests` | 74/74 | `mvp_integration` | 28/28 |
| `admin_v4_api_tests` | 107/107 | `behavior1_tests` | 111/111 |
| `import_v4_tests` | 39/39 | `vocab_accuracy_tests` | 79/79 |
| `admin_security_tests` | 29/29 | `memory_v1_tests` | 61/61 |
| `knowledge1_tests` | 72/72 | `workbench1_tests` | 25/25 |

合计 **22 套件 / 1179 项 / 0 失败**；客户端 `test_client_ui_transcript` 48/48、`test_gui_transcript_live` 25/25 = **73/73**。
QA 的实测值与施工方交付记录 §4.1 **完全一致**（这是独立复核，不是转抄）。

失败套件与环境性证明（QA 在 `/tmp` 纯净 worktree 复现）：

| 套件 | 最终 HEAD（主工作树） | `4669b59` 纯净 worktree | 判定 |
|---|---|---|---|
| `admin1_tests` | 81/83（vision 路由 + `api_model urllib`） | **81/83（同 2 项）** | 基线/环境，非本轮 |
| `r1f_tests` | 176/179（含 `.DS_Store` 的 `A1b`） | **177/179（仅剩 2 项 OpusError）** | 差值 = 本机 `.DS_Store`；`OpusError` 两处皆有 = dev libopus 环境 |
| `client_ui1_integration` | `aiohttp ClientConnectionResetError` | **同类异常** | 环境，非本轮 |

**逐提交复跑（QA 独立完成，用于数字对账）**：`teacher_context_seam_tests` / `teacher_voice_seam_tests`
在 `64a7d68` / `f7c9736` / `4669b59` 均为 **82/82 与 54/54**；在 `3b13c4c` 为 **83/83 与 60/60**。

---

## 六、卖方主张的独立裁定

**经 QA 核实为真**：`enable_gate` 不读 `enabled`；新门禁位置正确且缺键 fail-closed；拒绝早于凭据门禁与端点门禁；
无静默回退且全局 Tina 凭据逐值不变；`67/67` 在任何已提交修订上不可复现（R2 三提交均 82）；
`82/82` 为 R2 已提交值、`54` 为 `teacher_voice_seam_tests` 的 R2 值（现 60）；
**"R2 独立 QA 钉的 5 个哈希中 3 个与已提交产物不符"成立**（`teacher_context.py` `16ca10e7`≠`13d679c4`、
`teacher_voice.py` `1fba38f2`≠`94f17ed1`、`teacher_context_seam_tests.py` `8ac25d64`≠`dd04a6aa`；
`main.py` 与 `teacher_voice_seam_tests.py` 相符）；T13l 非恒真。**未发现卖方实质主张为假**。

**QA 判定为 UNCERTAIN（施工方接受该修正）**："`81/81` 属于 R2 QA 窗口内一个未提交工作树修订" ——
该未提交修订**已不可复现**，属合理推断而非直接观测。施工方已在交付记录 §5.3 补"诚实标注"段落，
明确其为推断及其两条支持证据。

**QA 明确无法核实**：NAS 零改动（无法访问 NAS，仅能证明提交内容不含 NAS 痕迹）；
真实音频 / 真实模型密钥 / 真实 Qwen 实时端点（本轮正确标注为 PENDING）。

---

## 七、QA 的合规声明

REPO 全程只读；仅在 `/tmp` 下新建 4 个探针脚本与 4 个临时 worktree（`4669b59` / `64a7d68` / `f7c9736` / `3b13c4c`，
均已 `git worktree remove --force` 清除）；未触碰冻结六文件、未访问 NAS、无网络/密钥/付费调用；
复核后 `git status --porcelain` 计数与开始时一致（均为既有数字人线路改动）。

---

## 八、QA 提出的"真人验收前须解决事项"与施工方处置

| # | QA 事项 | 处置 |
|---|---|---|
| 1 | 修 §5.5 错哈希 | **已完成**（Q3-1） |
| 2 | 清理主工作树 `.DS_Store` | **登记未执行**（Q3-4，属授权范围外；待产品负责人决定） |
| 3 | 落地 `P2B2_R3_0_INDEPENDENT_QA.md` | **已完成**（即本文档） |
| 4 | 运维前置：管理后台**显式启用**该老师的实时模型；指定非冻结 `realtime_safe` 真实模型；提供该服务商**自有**凭据；确认端点可达且不影响生产 Tina | 移交产品负责人（交付记录 §八 D2–D5） |
| 5 | 决策：是否把 `enabled` 纳入共享 `enable_gate` | 移交产品负责人（交付记录 §八 D6） |
| 6 | 补"真实 aiohttp 客户端消失 → handler 取消"的端到端用例 | **登记**（交付记录 §六.8）；现有 T13l 为 helper 级鉴别测试，已被证明非恒真 |
