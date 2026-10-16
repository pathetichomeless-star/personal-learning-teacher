# V06_FINAL_REVIEW — d31d05e 提交独立评审（V0.6 stage A/B/C）

- 日期：2026-10-09 / 审查对象：commit `d31d05e`（AVATAR-VISION V0.6 stage A/B/C），HEAD=`da2c86a`（docs-only，无代码增量）
- 编制：v06-mac-ui（只读评审；本文为唯一写入物）
- 结论先行：**APPROVE（附 2 条诚实备注）**——回归 68/68 全绿、冻结链零触碰、安全语义符合 V05 QA 口径；备注①commit 信息"qwen.py additive only"表述不精确（实为 1 行行为修改，已论证安全）；②product_v1 需 `DYLD_LIBRARY_PATH` 指向 client/libs/libopus 才能在本机运行（环境项，非代码缺陷）。

---

## 1. DIFF_BOUNDARY（diff 边界确认，`git show d31d05e --stat` 实测）

9 文件，+306/-3：

| 文件 | 变更 | 边界判定 |
|---|---|---|
| `client/src/vision/__init__.py` | +9（配置键常量，ENABLED 默认 False） | 纯加法 |
| `client/src/vision/compress.py` | +48（validate/plan/compress，cv2 延迟 import，≤190KB 阶梯，重编码去 EXIF） | 纯加法 |
| `client/src/vision/controller.py` | +79（VisionController：频率守卫 + urllib POST + X-Vision-Token + 会话绑定，零 PySide6 import） | 纯加法 |
| `client/src/vision/tests/test_vision_module.py` | +129（13 checks） | 纯加法 |
| `client/src/avatar/states.py` | +27（5 状态机 + generation 绑定） | 纯加法 |
| `gateway/app/http.py` | -3/+2（F2 token 路径简化） | 视觉端点内修改，见 §3 |
| `gateway/app/qwen.py` | +1（F1 `_teardown` 内 `_ACTIVE_INSTANCES.discard(self)`，qwen.py:796） | **1 行行为修改**，见 §2 |
| `gateway/tests/vision_v0_tests.py` | +8（V10 回归用例） | 测试 |
| `tools/vision_mock_server.py` | +3（F3 token 缺失 fail-closed） | 工具 |

**冻结链核验（客户端音频面，零触碰 ✓）**：diff 中不存在 `client/src/audio_codecs/`（7 文件）、`client/src/audio_processing/`、`client/src/plugins/audio.py`、`websocket_protocol.py` 的 `send_audio`(:256-277)/`_on_incoming_audio`(:221-224)、`bootstrap/session.py`、`core/` 任何一行——V05-R10/E9 冻结审计口径下自动通过。gateway 侧 `turns.py`/`protocol.py`/VAD 亦零改动（`git show d31d05e --stat` 证）。

**嘴型同步路线核验**：`avatar/states.py` 注释与实现均为协议包络方案（Option B），audio_codec.py RMS 探针**未实现**，与 `V06_AUDIO_SYNC_BLOCKER_ANALYSIS.md` 的 BLOCKED/PO 门控结论一致——诚实未伪装。

## 2. F1 影响分析（qwen.py 唯一非加法行）

- 改动：`_teardown()`（qwen.py:789-804）第一段新增 `_ACTIVE_INSTANCES.discard(self)`。
- 关闭前行为：连接关闭后实例滞留模块级注册表（qwen.py:815 `_ACTIVE_INSTANCES = set()`），仅靠 `submit_vision_image`（:820-830）的 `getattr(inst, "_connected", False) and inst._ws is not None` 过滤跳过——功能正确但引用泄漏（长运行进程集合无界增长 + 延迟 GC）。
- 关闭后行为：teardown 即注销；`submit_vision_image` 对已关闭实例返回 `not_connected` 语义不变。teardown 只发生在连接关闭路径，音频收发路径（append/send 循环）零触碰。
- 判定：**安全**。但 commit 信息"the frozen audio path zero-diff (qwen.py additive only)"表述不精确——qwen.py 是 1 行行为修改（虽不影响音频），评审记录以本节为准。

## 3. F2/F3 语义核验

- **F2**（http.py:57-58）：旧表达式 `str(getattr(config,"workspace_id","") or "") or "/app/secrets/vision_token"` 存在缺陷——workspace_id 非空时 token_path 被置为 **workspace_id 字符串本身**（目录而非文件）→ 读 token 必然 OSError → fail-closed（旧代码同样 401）。新代码 = `VISION_TOKEN_FILE` 环境变量或固定 `/app/secrets/vision_token`，行为更可预测。部署注意：**依赖 workspace_id 派生路径的部署（如曾有）需改用 VISION_TOKEN_FILE 环境变量**；失败方向为 fail-closed，安全。
- **鉴权面复核**（http.py:63-97）：`X-Vision-Token` 恒时比较（`hmac.compare_digest`，:68-71）；expected 为空即 401（:68 `if not expected or ...`，fail-closed）；处理函数不读取任何 Admin Bearer/Admin 头——E1-a"admin token 冒充"分支由代码路径排除（除非两密钥文件内容相同，属部署错误）。体长 320KB 上限（:73-75）→ JSON → base64 validate → qwen 五重守卫（190KB raw/256KB b64/5s/6per-min/ordering，qwen.py:695-703）。
- **F3**（vision_mock_server.py:93-95）：mock 在缺 token 文件时 401，与真实端点 fail-closed 语义对齐，消除"mock 比真实宽"的测试盲区。

## 4. REGRESSION（回归实测，本机运行）

| 套件 | 命令（venv） | 结果 |
|---|---|---|
| gateway vision_v0 | `gateway/.venv/bin/python gateway/tests/vision_v0_tests.py` | **14/14 PASS**（含新 V10 teardown 注销） |
| v05_e2e | `gateway/.venv/bin/python gateway/tests/v05_e2e_tests.py` | **8/8 PASS**（E1a/E1b 401、E2 413、E4 全链、E5 409、E6 429、E7 音频无恙、E8 415） |
| product_v1 集成 | `DYLD_LIBRARY_PATH=client/libs/libopus/mac/arm64 gateway/.venv/bin/python gateway/tests/product_v1_integration.py` | **33/33 PASS**（H1-H15 含冻结音频行为） |
| client 视觉/头像模块 | `client/.venv/bin/python client/src/vision/tests/test_vision_module.py` | **13/13 PASS**（validate/compress/默认关闭/频率守卫/E2E 200+401/avatar 5 状态+代际+打断归零） |

合计 **68/68 全绿**。环境备注：两个 venv 均无系统 libopus，product_v1 需 `DYLD_LIBRARY_PATH` 指向 `client/libs/libopus/mac/arm64`（repo 内自带 dylib）——建议在测试 README/CI 记录此先决条件。

## 5. QA_MAPPING（对 V05_SECURITY_QA_TEST_DESIGN / VISION_V0_TEST_PLAN）

- **E1-a/b、E2、E4、E5、E6、E7、E8** → v05_e2e 8/8 ✓；**V1-V10** → vision_v0 14/14 ✓；客户端守卫镜像 → 模块 13/13 ✓。
- **未覆盖（诚实清单）**：①手工验收项——macOS TCC 摄像头授权分支、识别后绿灯熄灭确认、"嘴-音同步感"主观验收（包络 HONEST_LOSS 近似口径）——属 UI 切片验收，本提交无 UI 无法执行；②QML 装配（VisionPanel/AvatarCanvas/插件注册/设置开关）**不在 d31d05e 内**——commit 明示 "QML assembly + plugin registration: next slice"，装配方案见 `V06_MAC_UI_ASSEMBLY.md`（4 触点 + 5 新文件 + DEFAULT_OFF 证明）。

## 6. VERDICT

**APPROVE（d31d05e 可作为 V0.6 逻辑层基线）**：边界干净（客户端 5 文件纯加法 + 网关 2 处小改均安全）、冻结链零触碰、68/68 回归全绿、fail-closed 语义三处一致（http.py 空 token / mock 缺 token / controller 默认 disabled）。两条挂账：①commit 信息"qwen.py additive only"应更正为"1 行 teardown 注销修改（安全，见 §2）"；②下一切片为 Mac UI 装配（V06_MAC_UI_ASSEMBLY.md）+ 手工验收项，验收通过前 V0.6 不宜宣称交付。
