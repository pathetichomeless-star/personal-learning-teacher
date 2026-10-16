# CLASSROOM V1 — RELEASE FIX 02 独立复验报告

- 复验性质：**独立只读审计 + 独立测试**（不修改产品代码，未接真实语音，未接真实模型，无 NAS 操作）
- 复验对象：提交 `3754e502701713ee420e19b5badee5c421a77f88`（CLASSROOM-V1-FIX-02）及其重建 `.app`
- 施工报告：`docs/engineering/product-v1/classroom-v1/release-fix02/CLASSROOM_V1_RELEASE_FIX02_REPORT.md`
- 复验环境：macOS，客户端运行时 `client/.venv`（Python 3.10.20 / PySide6 6.10.1），真实 cocoa 渲染
- 复验时间：2026-10-12

---

## 0. 结论块（交付）

```
BASELINE              = 存在偏差：任务书基准 3754e50 不是当前检出 HEAD
                        （实际 HEAD=c298a4f=p2b2-teacher-voice；3754e50 为其
                          子提交，位于分支/工作树 workbuddy/p2b2-teacher-voice-f0edf42f）
CHANGE_SCOPE          = FIX02 提交仅改 1 个产品文件 client/src/classroom/qml/CourseArea.qml
                        ＋ 14 个 docs/evidence 文档/截图；无其它产品代码
IPA_560               = PASS（布局框恰齐平 530.0/0.0；实际字形 ink 右缘 518.5，余 11.5px）
IPA_620               = PASS（word 350.1 / ipa 380.6 ≤ 视口 590）
LONG_WORD_AND_IPA     = PASS（4 词 × 7 档 = 56 项：布局框最大越界 0.0px；
                        字形 ink 最大越界 −2.0px（即全部在裁剪区内）；文本 0 篡改、0 省略）
WIDE_LAYOUT           = PASS（≥860 档 word 与 IPA 同行，宽屏无错误断行）
OLD_PROBE_FAILURES    = 已逐项核实：qa_probe 34/35（FAIL=探针选择器命中“例句”非“单词”，非产品缺陷）；
                        qa_experience 25/26（FAIL 与 pre-FIX02 完全相同 → 既有基线限制，非 FIX02 回归）
APP_VERSION_MATCH     = PASS（主可执行 SHA-256=146e47a3… 与报告一致；包内 CourseArea.qml=bd3eed7…
                        = FIX02 源码；与 .pre-fix02=08171ef… 明确区分）
APP_LAUNCH            = PASS（LaunchServices open 以应用身份启动、0 个 Terminal 进程；
                        env -i 清洁环境独立启动 CLASSROOM_READY size=narrow 620×620）
ISOLATION             = PASS（指向正式目录 → 退出码 3 + 中文 fail-closed 文案）
REGRESSION            = PASS（开发方 46/46、40/40 未复核采信；本轮独立复核 FIX02 未引入 FIX01 项回归：
                        560/620/860/1000/1360 控件 0 越界、860 结束学习可达、1000 输入框 388px、教学语言、全屏 均 PASS）
REAL_MODEL_REQUESTS   = ZERO
TINA_FROZEN           = UNCHANGED
DIGITAL_HUMAN_FILES   = UNTOUCHED
NAS_CHANGED           = NO
P0_P1_P2_REMAINING    = 无（P0=0；P1 与 P2-1..P2-4 已于 FIX01 关闭且本轮复核仍关闭；
                        最后一个 P2=LONG_WORD_IPA_RENDER 由 FIX02 关闭并通过独立复验）
INDEPENDENT_QA        = COMPLETED
READY_FOR_HUMAN_ACCEPTANCE = YES（含 1 项流程提示，见 §5，不构成验收阻断）
HUMAN_GUI_TEST        = PENDING
```

---

## 1. 基线审计

### 1.1 实际 HEAD 与提交范围（发现偏差）

| 项 | 实测 |
|---|---|
| 当前 HEAD | `c298a4fdd93c37aef8667a6a6e5f428c0a4e9f49`（branch `p2b2-teacher-voice`） |
| 任务书基准 | `3754e502701713ee420e19b5badee5c421a77f88` |
| 拓扑关系 | `3754e50` 的父提交 = `c298a4f`（即 FIX02 是当前 HEAD 的**子提交**） |
| 归属 | `3754e50` 位于分支 `workbuddy/p2b2-teacher-voice-f0edf42f`，工作树 `<user-home>/WorkBuddy/Worktrees/小智/p2b2-teacher-voice-f0edf42f`（HEAD=3754e50） |
| 主检出工作树源码 | `client/src/classroom/qml/CourseArea.qml` = `08171ef…`（**pre-FIX02**，即父版本） |

**判断**：任务书所给基准 `3754e50` 与当前检出 HEAD `c298a4f` **不一致**。FIX02 的实际载体是
`workbuddy/p2b2-teacher-voice-f0edf42f` 分支工作树 + 重建 `.app`；主检出（`p2b2-teacher-voice`）
工作树**尚未含 FIX02 源码**。本轮即以此提交对象与 `.app` 为被测对象，并做交叉一致性核验。

### 1.2 提交范围（c298a4f → 3754e50）

```
M client/src/classroom/qml/CourseArea.qml                     (+31 −6)
A docs/engineering/product-v1/classroom-v1/release-fix02/…（报告 1 + 脚本 2 + 截图 12）
```

- **产品代码仅修改 `CourseArea.qml`**：单 `Text`（word+"  "+phonetic，无 width/wrapMode/elide）
  → 可换行 `Flow` + 两个自适应 `Text`（`width=Math.min(implicitWidth, flow.width)`、
  `wrapMode=Text.WrapAnywhere`）。改动静确认与施工报告一致。
- 其余 14 项均为文档/证据（未入库的 `client/dist/**`、`build2/**` 属构建产物，`.gitignore` 覆盖）。

### 1.3 工作树与未跟踪文件

- 工作树**修改文件仅数字人/头像相关**（`probe_avatar_qml_offscreen.py`、`avatar_page.js`、
  `manager.py`、`AvatarLive2D.qml`、`V1_MAC_GUI_ACCEPTANCE.md`）——均为既有未提交改动，FIX02 未触及。
- 未跟踪文件：FIX01 独立 QA 报告、数字人 `runtime_server.py`、P2B2/R3_2C 文档、`qa-independent/` 证据等，
  均为**既有**产物，非 FIX02 新增，不属产品代码。

### 1.4 冻结 / 保护面（SHA-256 实测比对）

| 对象 | 实测 | 结论 |
|---|---|---|
| Tina 冻结六文件 | turns `e18a0d08…` / qwen `13d4800d…` / audio `c2218a2c…` / protocol `944e2d5a…` / ws `dde9d427…` / behavior `6d705960…` | **UNCHANGED**（逐一匹配基线） |
| 数字人未提交文件 | `f3cb7ea3/1243b98d/bd2de04b/32c1c16a/8ac51456` | **UNTOUCHED**（与报告一致） |
| 正式配置 `…/py-xiaozhi/config/config.json` | `301f5244…` | **UNCHANGED** |
| 课件数据 `client/src/classroom/data/courses.json` | `1b8c01ac…`；`git diff` 为空 | **未篡改** |
| NAS | 零操作 | **NO** |

---

## 2. 独立音标复验（核心）

### 2.1 方法（正确坐标系，双口径）

独立探针（QA 侧新建，只用 `client/.venv`，不改产品代码）以**真实裁剪容器**
`ScrollView{clip:true}` 的 scene 矩形为唯一横向坐标系，对每个词汇 `Text` 记录三口径：

1. **文本自然宽度** `nat` = `QFontMetricsF.horizontalAdvance(text)`
2. **实际布局宽度** `lay` = `item.width()`（+ 场景 `x/y/right/height`，行数 = `height/lineHeight`）
3. **最终可见字形区域** = 窗口抓图的**像素级 ink 右缘**（在 item 框内扫描非白像素）

并对 4 词 × 7 档（560/620/640/860/1000/1360/全屏）= **56 项**逐一判定：
`right ≤ clip.right`（几何）且 `ink_right ≤ clip.right`（像素）且文本未篡改/未省略。
同时以 **pre-FIX02 主检出**（同探针，仅换 client 目录）做反向对照。

### 2.2 结果（FIX02 = 全部通过）

| 指标 | 数值 |
|---|---|
| 布局框最大越界（56 项） | **0.0 px**（`internationalization` IPA@560，恰齐平） |
| 字形 ink 最大越界（56 项） | **−2.0 px**（距裁剪右缘最近者仍在内侧 2px） |
| 文本篡改 / 省略 / 缺失 | **0 / 0 / 0** |

关键样例（裁剪右缘：560→530、620→590、640→610、860→830、1000→970、1360→988、全屏→1098）：

| 档 | word `reservation` 右缘 | IPA `/ˌrezəˈveɪʃn/` 右缘 | 结论 |
|---|---|---|---|
| 560 | 350.1 | 380.6 | PASS（两行，均在内） |
| 620 | 350.1 | 380.6 | PASS |
| 640 | 358.1 | 388.6 | PASS |
| 860 | 358.1 | 618.7（与 word **同行**） | PASS |
| 1000 | 464.1 | 724.7（同行） | PASS |
| 1360 | 514.1 | 774.7（同行） | PASS |
| 全屏 | 514.1 | 774.7（同行） | PASS |

合成长词（**未写入产品课件**）：

- `internationalization@560`：word 自然宽 365、IPA 自然宽 403.3 > 可用宽 392 → 按
  `WrapAnywhere` 折为 **2 行**（贪心复算行数一致）；IPA **布局框右缘 530.0（恰齐平裁剪右缘，越界 0.0）**，
  但**实际字形 ink 右缘仅 518.5（距裁剪右缘尚有 11.5px）**。
- `congratulations / photosynthesis` 在 7 档全部单行、无越界；IPA 闭合斜杠 `/` 全部保留。

### 2.3 反向对照（证明探针灵敏度与修复真实性）

同探针作用于 **pre-FIX02** 主检出：

| 档 | 合并文本自然宽 | 文本右缘 | 裁剪右缘 | 越界 |
|---|---|---|---|---|
| 560 | 481.3 | 619.3 | 530.0 | **+89.3px** |
| 620 | 481.3 | 619.3 | 590.0 | **+29.3px** |

- pre-FIX02：布局框最大越界 **+402.9px**、字形 ink 最大越界 **+30.5px**（**真实裁剪**），
  17 项布局越界 / 15 项字形越界。
- 与《CLASSROOM_V1_RELEASE_FIX01_INDEPENDENT_QA》所记 560 −89.3 / 620 −29.3 **完全吻合**（符号仅表方向）。
- ⇒ 同一探针在 FIX02 全绿、在 pre-FIX02 检出真实裁剪：**修复真实有效，探针非“恒通过”**。

### 2.4 关于报告 §3.2「`internationalization@560` 最小余量 −31.8px」与「全部不越界」之矛盾（任务点名）

**结论：该 −31.8px 不可复现，属报告数字陈旧/口径标注错误；其实质不构成越界。**

复算数据（正确坐标系）：

| 口径 | `internationalization@560` word | IPA |
|---|---|---|
| 自然宽 nat | 365.0 | 403.3 |
| 布局宽 lay | 365.0 | 392.0（WrapAnywhere 2 行） |
| 布局框右缘/越界 | 503.0 / **−27.0** | 530.0 / **0.0（恰齐平）** |
| 字形 ink 右缘/越界 | 500.5 / **−29.5** | 518.5 / **−11.5** |

- 施工报告**自带证据** `evidence/logs/fix02_evidence.json` 亦记录该例最小 overhang = **0.0**（非 −31.8）。
- 报告 §3.1 表格（word 右缘 345.3）与其证据 json（350.1）**亦不一致** → 该表格来自更早一次运行。
- 报告把**带符号的越界量（负=在视口内）**直接称作「余量」，造成“负余量却称不越界”的字面矛盾；
  实为**符号/命名口径问题**，并非产品越界。
- **判定：不越界、不裁剪（PASS）。** 报告 §3.2 的 −31.8px 应在交付记录中订正；不影响验收结论。

---

## 3. 测试结果差异核实（旧探针）

在 FIX02 工作树客户端上实跑两个旧探针：

| 探针 | 实测 | 未通过项 | 性质判定 |
|---|---|---|---|
| `qa_probe.py` | **34/35** | 「620 reservation+IPA **自然宽度**不超过课件视口宽度」：natural=471.6 > viewport=452 | **探针选择器口径问题**：该探针以 `find_text_contains("reservation")` 取**最宽**文本，FIX02 下命中的是**例句** `"I have a reservation under the name Li."`（非单词「reservation」）。同一探针的「文本右缘≤视口」项 **PASS**（`clipped_px=0.0`，右缘 590=视口右缘）。例句本就应 `WordWrap`，非产品缺陷。 |
| `qa_experience.py` | **25/26** | 「UI：语音不可用原因文案在位」（期望含「未接入真实实时语音」，实际为「语音对话（不可用）」） | **既有基线限制、非 FIX02 回归**：在 **pre-FIX02 主检出**上实跑，结果**同为 25/26、同一未通过项**。 |

- 未对历史证据作任何修改；未把非全绿写成全绿。
- 两处未通过均**不涉及**本次 FIX02 的改动面（`CourseArea.qml` 词汇行）。

---

## 4. 新 `.app` 验证

| 项 | 实测 | 结论 |
|---|---|---|
| 主可执行 `Contents/MacOS/xiaozhi-classroom` SHA-256 | `146e47a3e3b8390ba5f4bc4aa2d9f6002c56b7f1dcaed7a8812c8de93476fe5f` | **= 报告一致** |
| 包内 `Resources/src/classroom/qml/CourseArea.qml` SHA-256 | `bd3eed7…`（= FIX02 源码逐字节一致） | **含 FIX02** |
| `.pre-fix02` 旧包内同文件 SHA-256 | `08171ef…`（= pre-FIX02） | **明确区分，未误用旧包** |
| 独立启动（LaunchServices `open`） | 进程以应用身份启动（pid 实测运行）、菜单栏显示「小智 AI 学生课堂」 | **PASS** |
| 是否出现终端 | 启动前后 `Terminal` 进程数 **0 → 0** | **无终端** |
| 开发环境依赖 | 包内自带 `PySide6`/Qt Frameworks；**无** `pyvenv.cfg`/venv 痕迹 | **无开发环境依赖** |
| 隔离 fail-closed | 指向正式目录启动 → **退出码 3** + 中文拒启文案 | **PASS** |
| 清洁环境独立启动 | `env -i HOME=… XIAOZHI_CLASSROOM_DIR=<iso> --size narrow` → `CLASSROOM_READY size=narrow width=620 height=620` | **PASS** |
| 离线课件 | 隔离目录启动正常，随包本地演示课件可用 | **PASS** |
| 自动联网 / 真实模型 | 隔离目录无演示配置 → 零外呼；未接真实模型 | **0 次真实模型请求** |

> 注：报告称的「包整体清单 SHA-256 `d328a466…`」未给定可复现清单口径，未独立复算；
> 以更强的绑定标识（主可执行 SHA + 包内 `CourseArea.qml` SHA）完成版本一致性判定。

---

## 5. 复验结论与遗留

- 独立复验确认 **FIX02 已关闭最后的 P2 缺陷 `LONG_WORD_IPA_RENDER`**：窄窗「单词+IPA」在
  560/620/640/860/1000/1360/全屏 全档**完整显示、无缺字、无越界、含闭合斜杠**，宽屏排版未破坏，
  中文释义/例句在位、翻页与滚动正常。
- **P0/P1/P2 全部关闭**（P1 与 P2-1..P2-4 于 FIX01 关闭，本轮复核其独立 QA 项在 FIX02 下**仍全部通过**）
  ⇒ **READY_FOR_HUMAN_ACCEPTANCE = YES**。

**流程提示（非验收阻断，供产品负责人知悉）**：
1. FIX02（`3754e50`）位于分支 `workbuddy/p2b2-teacher-voice-f0edf42f`，**尚未合并**至 `p2b2-teacher-voice`；
   主检出源码仍为 pre-FIX02。面向普通用户的交付物是 `.app`（已含 FIX02），可直接人工验收；
   但**源码记录在发布前应合并且主检出源码同步**，以免后续基于主检出重打包时回退到 pre-FIX02。
2. 施工报告 §3.2 的「−31.8px」与其 §3.1 表格数字为**陈旧/口径标注错误**，建议在交付记录中订正
   （不影响功能与验收）。

**未做/待办**：真实人机 GUI 验收（`HUMAN_GUI_TEST = PENDING`）；真实实时语音与真实模型接入不在本轮范围。

---

## 6. 证据索引（本机路径）

| 类别 | 路径 |
|---|---|
| 独立探针（几何+像素，双口径） | `/tmp/fix02_review/indep_probe3.py` |
| FIX02 逐项结果（56 项） | `/tmp/fix02_review/indep_v3/rows_fix02.json` |
| pre-FIX02 逐项结果（反向对照） | `/tmp/fix02_review/indep_v3/rows_prefix.json` |
| 像素级字形测量明细 | `/tmp/fix02_review/focused_ink.py`（输出见运行日志） |
| 旧探针实跑日志 | `/tmp/fix02_review/qa_probe_run.log`、`/tmp/fix02_review/qa_exp_run.log` |
| `.app` 启动/隔离证据 | `/tmp/fix02_review/app_run.out`、`app_refuse.out`、`newapp_onscreen3.png` |
| 官方 FIX02 证据（只读引用，未改动） | `…/classroom-v1/release-fix02/evidence/**` |

（本报告由独立复验方生成，不修改任何产品代码、不提交、不打标签。）
