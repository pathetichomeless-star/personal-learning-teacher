# CLASSROOM V2 — 界面设计规范与 QML 落地规格（Phase 1 · **REV1A → REV1B**）

- 交付：Agent A（画布与 UI/UX 总设计）／总控整理
- 画布成果：`docs/engineering/product-v1/classroom-v2/design/canvas/classroom_v2_design_canvas.html`（**REV1B · 可在浏览器直接查看**；REV1 归档为同目录 `classroom_v2_design_canvas_REV1.html`）
- 本文件 = **设计系统 + 布局规范 + 组件规范 + QML 落地映射**，是 Phase 2 QML 施工的唯一视觉依据
- 覆盖：学生课堂 · 我的书库 · 导入教材 · 解析进度 · 教材校对 · 发布课程 · AI 老师 · 语音状态 · 数字人 · 窄屏布局 · 六类状态 + 网络四态
- **修订记录**：REV1A（产品负责人裁决 `VISUAL_DIRECTION=APPROVED_WITH_FIXES` / `MAIN_UI_CONSTRUCTION_GATE=PENDING_REV1A`）→ **REV1B**（R3–R6/R8–R12 通过；**R1/R2/R7 最小补正**已并入 §4.5/§4.6/§4.9/§9）；两份差异清单原件已删除（PROJECT-DOC-MERGE-01 批准；结论并入本修订记录，恢复=项目外备份 `<offsite-backup>/merge01-20261013/docs/engineering/product-v1/classroom-v2/`）

> **两条硬规则（强制，覆盖全文）**
> 1. **设计样例 ≠ 真实状态。** 画布中的人物、音色、字幕、连接/语音状态**以及溯源字段（页码/抽取器索引/章节/置信度）**均为**视觉占位**（已用紫色虚线 + 「设计样例」chip 标注）。
>    正式 UI 这些字段**必须**来自真实数据源；**严禁**以硬编码假数据替代「老师在线 / 正在讲解 / 正在聆听」等真实连接状态。无数据时显示「状态未知」，不得沿用样例值。
>    **溯源字段无可靠依据时显示「页码待确认 / 章节归属待确认 / 不可评估」，不得用推断数字冒充精确来源**（REV1B R7）。
> 2. **能力必须如实标注。** 导入页支持格式**以 `GET /admin/knowledge/parsers` 真实返回为准**；**文字型 EPUB 已实现（D2，开发交付，独立 QA 待完成）**；
>    书页图片 **OCR 尚未实现（D3，延后至 P1）**，在能力就绪前**一律显示「暂不支持」**——不得宣称 EPUB 或 OCR「不支持」。

> 设计优先级（产品负责人明确）：**操作效率 > 内容可读性 > 交互清晰度 > 视觉装饰**。
> 风格方向：现代 AI 教学产品（深海蓝 / 深紫 / 智能蓝光 / 柔和渐变 / 适度玻璃 / 克制动效），**非传统后台管理系统**。

---

## 0. 设计原则（5 条，作为评审基准）

1. **课件是主视觉中心**：任何断点下，课件区必须是面积最大的区域；数字人/侧栏不得挤压课件。
2. **AI 感来自"真实状态"而非装饰**：状态提示只在真实事件发生时出现；**禁止**假字幕、假思考过程、假波形、假连接状态。
3. **诚实标注**：本地演示 / 本地模拟(Mock) / 真实在线 三态必须在界面可见；课程来源（本地演示样本 vs 用户教材）必须可见。
4. **一步可达**：高频操作（选课 / 换老师 / 开始-暂停 / 语音 / 文字 / 结束）不进入深层设置；**不出现重复按钮**（如两个"下一页"）。
5. **无障碍内建**：正文对比度 ≥ 4.5:1、大字 ≥ 3:1；状态**不以颜色单独传达**；提供"减少动效"开关。

---

## 1. 设计令牌 → QML 映射

### 1.1 现有 `client/src/classroom/qml/theme/ClassroomTheme.qml`（**只新增，不改旧值**）

现有属性（`bg/surface/border/primary/spacingXs..Xl/fontXs..Hero` 等 20 个）**保持名称与取值不变**，避免 FIX01/FIX02 回归。V2 在其后追加：

```qml
// ---- V2 新增：深色轨道 ----
readonly property color bgDark:          "#0B1020"
readonly property color surfaceDark:      "#121A2E"
readonly property color surfaceAltDark:   "#18223A"
readonly property color borderDark:       "#26314E"
readonly property color borderStrongDark: "#35446A"
readonly property color textDark:         "#EAF0FF"
readonly property color text2Dark:        "#A8B6D6"
readonly property color placeholderDark:  "#6C7BA0"
readonly property color primaryDark:      "#5B8CFF"
readonly property color primaryDeepDark:  "#3E6FE0"
readonly property color accentDark:       "#8B7BFF"

// ---- V2 新增：品牌色 / 语义色（浅色轨道）----
readonly property color accent:        "#6D5EF8"
readonly property color primaryDeep:   "#1E3FBF"
readonly property color primaryGlow:   "#4EA8FF"
readonly property color success:       "#17A673"
readonly property color warn:          "#D98317"
readonly property color danger:        "#E5484D"
readonly property color info:          "#3D7EFF"
readonly property color focusRing:     Qt.rgba(47/255, 107/255, 255/255, 0.35)

readonly property Gradient brandGradient: Gradient {
    GradientStop { position: 0.0; color: "#2F6BFF" }
    GradientStop { position: 1.0; color: "#6D5EF8" }
}

// ---- V2 新增：8 网格间距（旧 spacing* 不动）----
readonly property int gapXxs: 4
readonly property int gapXs:  8
readonly property int gapSm:  12
readonly property int gapMd:  16
readonly property int gapLg:  24
readonly property int gapXl:  32
readonly property int gap2xl: 48

// ---- V2 新增：圆角 / 动效 ----
readonly property int radiusXl:   22
readonly property int radiusPill: 999
readonly property int durInstant: 100
readonly property int durFast:    150
readonly property int durBase:    220
readonly property int durSlow:    320

// ---- V2 新增：主题开关与无障碍 ----
property bool darkMode: false
property bool animationsEnabled: true      // 「减少动效」开关
```

### 1.2 色值对照（浅色 / 深色）

| 语义 | 浅色 | 深色 |
|---|---|---|
| 画布 bg | `#F2F5FC` | `#0B1020` |
| 卡片 surface | `#FFFFFF` | `#121A2E` |
| 次级块 surfaceAlt | `#EEF2FB` | `#18223A` |
| 描边 border | `#DCE3F2` | `#26314E` |
| 主文字 text | `#16203A` | `#EAF0FF` |
| 次文字 text2 | `#5A6B8C` | `#A8B6D6` |
| 主品牌 primary | `#2F6BFF` | `#5B8CFF` |
| 次强调 accent | `#6D5EF8` | `#8B7BFF` |
| 成功/警告/危险 | `#17A673` / `#D98317` / `#E5484D` | `#35C48B` / `#F0A93B` / `#FF6B6B` |

**铁律**：渐变只用于主 CTA / 进度填充 / 成功卡 / Logo（面积 ≤ 单屏 8%）；发光只用于焦点环 / 活动项 / speaking 头像；玻璃只用于 chrome（顶栏/抽屉/浮层），**文字一律落在实底之上**。深色**不用阴影**堆叠，改用 1px 边框 + 顶部内高光。

### 1.3 字体（沿用现有 + 新增 Display）

`PingFang SC`（Windows 落 `Microsoft YaHei UI`）；等宽 `SF Mono`（音标/版本号）。
Caption 12 · BodySm 13 · Body 15 · Title 19 · Headline 26 · **Display 32（新增）** · Hero 40。
行高：正文 1.5 / 标题 1.3 / Display·Hero 1.2。单页字号 ≤ 4 种。

---

## 2. 布局规范（断点与三栏）

### 2.1 断点兼容策略（**工程硬约束**）

现有测试断言 `classroomWindowMode ∈ {narrow, compact, medium, wide}`（`test_classroom_release_fix01.py`、`ui_layout_probe.py`）。
→ **保留这 4 个字符串**；`ClassroomWindow.qml` **新增** `readonly property int bpTier`（0–5）承载细分档，新页面按 `bpTier` 决策。

**REV1A 断点命名统一（指令 ⑤）** —— 唯一权威表；画布标注、QML 常量、测试断言三处**必须**与此表逐字一致：

| bpTier | **唯一名称** | 宽度区间 | `classroomWindowMode` | 画布标注写法 | QML 常量名 |
|---|---|---|---|---|---|
| 0 | **narrow** | 560–619 | `narrow` | `tier0 narrow 560–619` | `BP_NARROW` |
| 1 | **compact** | **620–859** | `compact` | `tier1 compact 620–859` | `BP_COMPACT` |
| 2 | **medium** | 860–999 | `medium` | `tier2 medium 860–999` | `BP_MEDIUM` |
| 3 | **wide** | 1000–1359 | `wide` | `tier3 wide 1000–1359` | `BP_WIDE_3` |
| 4 | **wide** | 1360–1599 | `wide` | `tier4 wide 1360–1599` | `BP_WIDE_4` |
| 5 | **wide** | ≥1600 | `wide` | `tier5 wide ≥1600` | `BP_WIDE_5` |

> ⚠️ **REV1 错误已更正**：REV1 画布把 620px 标为「narrow」，与本节表格（620–859 = **compact / tier1**）矛盾；
> §4.8 也曾写作「窄屏（tier0 / 620）」。**620px 恒为 tier1 compact**，narrow 仅指 560–619。
> 画布 CSS 类名同步由 `.screen.small` 更正为 `.screen.compact`。

| bpTier | 名称 | 左（AI 老师） | 中（课件，**永远最大**） | 右（字幕/词汇/笔记） | 内容页导航 |
|---|---|---|---|---|---|
| 0 | narrow | 顶栏内 40px 圆头像 | flex，min 320 | 底部 Sheet | 顶部「更多」 |
| 1 | compact | 96px 图标竖条 | flex | 右抽屉 `min(360, w-80)` | 顶部分段控件 |
| 2 | medium | 200px（可折至 96） | flex | 右抽屉 | 顶部分段控件 |
| 3 | wide | 208px | flex ≥ 420 | **288px 常驻** | 左侧导航 240px |
| 4 | wide | 260px（现默认） | flex | **340px** | 左侧导航 240px |
| 5 | wide | 280px | flex，内容最大宽 1080 居中 | 360px | 左侧导航 260px |
| — | 全屏 | 同 tier5 | 同 tier5 | 同 tier5 | 顶栏 62→56、底栏 auto-hide |

**QML 派生规则（唯一实现，禁止各处自算）**：

```qml
readonly property int bpTier:
    width >= 1600 ? 5 : width >= 1360 ? 4 : width >= 1000 ? 3 :
    width >=  860 ? 2 : width >=  620 ? 1 : 0
readonly property string classroomWindowMode:      // 必须保持 4 值枚举，勿增勿改
    bpTier <= 0 ? "narrow" : bpTier === 1 ? "compact" : bpTier === 2 ? "medium" : "wide"
```

**降级顺序**：① 缩小/隐藏头像 → ② 右栏转抽屉 → ③ 课件全屏。**任何档位课件 ≥ 320px 且为最大面积区。**
面板间距：tier0/1 = 0（贴边）· tier2/3 = 12 · tier4/5 = 16。窗口 `minimumWidth 560 / minimumHeight 480` 不变。

### 2.2 主界面信息架构（三栏）

- **左 · AI 老师与语音互动区**：形象卡（数字人/静态降级）、老师名、教学语言与音色、状态徽章（在线/聆听/讲解/思考/等待/出错）、「更换老师」「隐藏数字人」。
- **中 · 课程 / 课件 / 练习区**：课程与课时标题、进度（n/N）、课件五型（cover/vocab/sentence/practice/summary）、操作行（朗读 / 跟读 / 下一页）。
- **右 · 实时字幕 / 重点词汇 / 课堂笔记**：三标签可切换；可折叠为抽屉。
- **底栏操作台**：麦克风、文字输入、「结束学习」。**不设重复的"下一页/重复讲解"。**

---

## 3. 组件清单与 QML 映射

| 组件 | QML 落点 | 决策 | 规格 |
|---|---|---|---|
| AppShell（顶栏+主体+底栏） | `ClassroomWindow.qml` | **EXTEND** | 顶栏 62（全屏 56）、底栏 76（可 auto-hide） |
| TopBar 视图分段控件 | `ClassroomWindow.qml` | BUILD | 高 30；选中 `#E6EEFF` 底 + primary 文字 |
| StatusPill | 新增 `components/StatusPill.qml` | BUILD | 高 22–24；色点 8px + 文字 12 |
| TeacherPanel / TeacherAvatar | 现有 `.qml` | **REUSE / EXTEND** | 新增 `state: idle\|thinking\|speaking` 呼吸（1200ms，仅 speaking） |
| CourseArea（五型课件 + FIX02 换行） | 现有 `CourseArea.qml` | **REUSE + EXTEND** | 保留 WrapAnywhere；练习选项补 ✓/✗ 图标（可访问性） |
| InteractionPanel（字幕/词汇/笔记） | 现有 `InteractionPanel.qml` | **REUSE** | 不动 `ALLOWED_TABS` |
| BottomBar（麦克风/输入/结束） | `ClassroomWindow.qml` | EXTEND | 麦克风 52px 圆形渐变；输入框 flex |
| PrimaryButton / Secondary / Ghost / IconButton | 新增 `components/` | BUILD | 高 36 / 36 / 36 / 32×32 |
| Drawer / Modal | 新增 `components/` | BUILD | 抽屉 `min(360,w-80)`；弹窗 `min(560,w-40)`，**严格限制在窗口内** |
| SkeletonBlock / EmptyState / ErrorState / OfflineBanner / DisabledWrap | 新增 `components/states/` | BUILD | 六态原语（见 §5） |
| LibraryGrid / BookCard | 新增 `pages/LibraryPage.qml` | BUILD | 列数 `floor((content-2*gap)/(200+gap))`，卡 200×267，封面 3:4 |
| ImportDropZone / FileQueueList | 新增 `pages/ImportPage.qml` | BUILD | 拖放区高 200 虚线；队列行 56；**格式清单来自 `GET /admin/knowledge/parsers`，禁止硬编码** |
| FormatCapabilityList（REV1A 新增） | 新增 `components/FormatCapabilityList.qml` | BUILD | 渲染 `{ext, available, reason}`；`available=false` 灰显 + 原因 + **不可选中** |
| StepTimeline / ChapterTreePreview | 新增 `pages/ParseProgressPage.qml` | BUILD | 圆点 24；状态：待办/进行中(脉冲)/完成(✓)/失败(✗)；**A/B 两段各自独立时间线** |
| SplitReader / DiffHighlight / IssueList | 新增 `pages/ProofreadPage.qml` | BUILD | ≥860 双栏；<860 上下堆叠；IssueList 分**关键 / 非关键**两档；**本页无发布动作**（只有校对操作 + 「进入发布流程」导航） |
| **ProvenanceBlock（REV1A 新增 · REV1B R7 收紧 · PHASE2 修正③）** | 新增 `components/ProvenanceBlock.qml` | BUILD | 来源文件名 + **原文件哈希 `source_file_sha256`（无值→「原文件哈希待确认」）** + **知识库内容哈希 `content_hash`（分栏）** + `doc_id` + 页码映射依据 + 抽取器索引 + 章节映射依据 + **置信度** + 锚点粒度；精度不可保证时显示 `页码待确认 / 章节归属待确认 / 不可评估`（**禁止推断数字**）；**两个哈希不得互相顶替**；**发布构建中不得使用设计样例值** |
| **RiskNotice（REV1A 新增）** | 新增 `components/RiskNotice.qml` | BUILD | **一般性**版面风险提醒（固定文案）；**不接受**"已检测"类文案，除非后端返回真实信号 |
| **GateBanner（REV1A 新增 · REV1B R1 收紧）** | 新增 `components/GateBanner.qml` | BUILD | 三态 `blocked / warning / passed`；blocked 时必须输出**具体原因列表**；**关键项无「接受即豁免」入口**，仅非关键缺失可逐项记录（原因/范围/历史） |
| **SampleBadge（REV1A 新增）** | 新增 `components/SampleBadge.qml` | BUILD | **仅设计/演示构建可用**；发布构建中必须编译期禁用（见 §5.3） |
| **NetworkStateGroup（REV1A 新增）** | 复用 `components/states/` | BUILD | 未连接 / 连接中 / 失败可重试 / 离线（§5.2） |
| PublishWizard / MetaForm / CoverUploader | 新增 `pages/PublishPage.qml` | BUILD | 4 步向导；**发布按钮受 GateBanner 门禁控制**（关键待确认项 = 0 且来源 `source_doc_id@revision` 有效才启用）；覆盖既有课程需二次确认 |
| TeacherPicker（学生侧） | 新增 `pages/TeacherPicker.qml` | BUILD | 只显示老师名/形象/音色，**不显示 id/token/url** |

**文件所有权**（详见 `CLASSROOM_V2_AGENT_PLAN.md`）：`client/src/classroom/qml/**` 归 **Agent B**；画布规范由 Agent A 提供；数据契约由 Agent I/E 提供。

---

## 4. 页面规格（逐页）

### 4.1 学生课堂（主界面）
- 三栏按 §2.2；tier0 用顶部老师条（40px 圆头像 + 名）+ 右栏折叠为底部 Sheet。
- 老师区必须表达：是否在线 / 正在听 / 正在讲解 / 当前音色。
- 课件区为主视觉；操作行不重复；未开始学习时状态恒为「待开始」，且**不产生讲解**（沿用 FIX01 门禁）。

### 4.2 我的书库
- 工具栏：搜索框 280 + 视图切换（网格/列表）+「导入教材」主按钮。
- 卡片：封面 3:4 + 标题（2 行省略）+ 元信息（章节/页数/最近使用）+ 状态徽章（未解析 / 解析中 / 已校对 / 已发布 / 待校对）。
- **空状态**：图标 + 「书架还空着」+「导入第一本教材」；**明确说明演示样本不代表正式教材**。

### 4.3 导入教材（**链路 A**：导入教材 → 提交知识库）
- 三步：选择文件 → 解析选项 → 确认提交。
- **支持格式以接口真实返回为准（指令 ③）**：页面加载时调用 `GET /admin/knowledge/parsers`；
  `available=true` 才可选中，`available=false` 灰显并展示 `reason`；**未出现在返回列表中的格式一律视为不支持**。
  **禁止硬编码格式清单**。EPUB **D2 已完成**（文字型，41 项安全测试通过）→ 接口会返回 `available=true`，界面据此显示为可用；
  **但界面不得假设**——若接口未返回或返回 false，仍须显示「暂不支持」。书页图片 / 扫描件 OCR 排在 **P1**，P0 必须显示「暂不支持」。
- 队列行显示：图标 + 文件名 + 大小 + 进度 + **解析路径徽标**（`本机环回解析` / `暂不支持` / `需上传云端并另行授权`）。
  **REV1 措辞更正**：不得再写「本机解析」——解析由**本机环回网关**（绑 `127.0.0.1`）执行，教材内容不出本机（D1）。
- **上云前必须二次确认 + 隐私说明**；云能力默认关闭。
- **本页终点是"提交知识库"，不是"可以上课"**（见 §4.9）。

### 4.4 解析进度（**A 段与 B 段必须显式分段**）
- **A 段 · 导入知识库**（对接既有后端，已实现）：上传 → 文本抽取 → 生成预览（TTL 30 min）→ 提交知识库（commit，服务端回读校验）。
- **B 段 · 生成课程草稿**（V2 新增）：结构锚点识别 → 语义切分 course/lesson/slide → 词条/音标/例句抽取 → 就绪待校对。
- 两段各自独立进度条与状态；**A 段失败不使 B 段草稿失效，反之亦然**。
- **诚实标注**：原文提取与课程草稿生成**必须视觉可分**；无真实生成能力时标注「**本地规则草稿**」或「**人工待确认**」，**不得伪装为 AI 已生成**。
- 断线转网络态（见 §5.2）；可后台继续。

### 4.5 教材校对（**链路 B 中途**）
- ≥860 双栏：左「原页预览」+ **真实数据链标注**，右「结构化校对」（420px）。
- **R1（REV1B）· 本页无发布动作**：校对页**不出现**「发布可学习课程」按钮，只有两类控件——
  ①**校对操作**（重新解析 / 确认本页校对）；②**「进入发布流程」导航**（门禁不通过时该导航进入禁用态并给出具体原因）。
  发布动作一律在 §4.6 的独立发布页完成。
- **原书预览 / 来源 / 页码 / 章节映射必须有真实数据链支撑（指令 ⑦）**：预览上方强制显示来源块，至少含
  来源文件名 + **两个独立哈希**（**原文件哈希 `source_file_sha256`**（无值显示「原文件哈希待确认」）、**知识库内容哈希 `content_hash`/`source_doc_hash`**（分栏、分别标注，**不得互相顶替**））、知识库 `doc_id`、页码映射依据（抽取器页序 / 0-based 页索引）、章节映射依据与**置信度**、锚点粒度。
  **无法保证精度时（如页内字符级锚点不可用）必须显式标记「待确认」，不得给出看似精确却无依据的页码/章节。**
- **R7（REV1B）· 画布中的溯源字段全部是设计样例**：`design/canvas/` 中出现的 PDF 页码、抽取器索引、章节映射、置信度
  **一律带「设计样例」标注**（`.mchip`），不得被误读为真实数据。
  **正式数据链不具备可靠页码映射时，界面必须显示「页码待确认」（章节同理「章节归属待确认」、置信度「不可评估」），
  不得用推断数字（如"约第 28 页"）冒充精确来源。** 画板 E 已提供「样例值 / 待确认态」双向对照。
- 差异高亮：新增(+) / 修改(~) / 缺失(!) —— **均带图标 + 下划线，不只靠色**。
- 「需人工确认」清单按严重度排序，分「关键 / 非关键」两档；点击定位高亮 1.2s。
- **版面风险提醒必须是一般性文案（指令 ⑧）**：固定文案「当教材为多栏排版时，抽取顺序可能与阅读顺序不一致，请重点核对」。
  **当前不具备自动栏检测能力 → 不得声称"已检测到多栏"**；仅当后端返回真实检测信号时才允许显示针对性提示。
- **本页终点是「校对完成」（proofreading → ready）+ 导航到独立发布流程，不是「已发布」**。

### 4.6 发布可学习课程（**链路 B 终点**，与「提交知识库」完全分离）
- 4 步向导：元信息 → 封面（可选，不伪造）→ 章节与课时编排（拖拽排序）→ 范围/确认。
- 来源字段只读展示（**知识库 `doc_id` + 内容哈希 `content_hash` + 原文件哈希 `source_file_sha256` + 教材文件名 + 章节范围**）——**发布产物必须绑定该 `source_doc_id` + `source_doc_hash`（发布时冻结），以及课程自身的 `revision`（幂等键）**（R2）。
  > 注 ①：`KnowledgeStore` 文档**当前不含 `revision` 字段**（身份 = `id` + `content_hash`），故来源绑定以**存在性 + 内容哈希一致**实现；不虚构"知识库 revision"。
  > 注 ②（修正③）：`source_file_sha256`（原文件字节哈希）⊥ `content_hash`（抽取文本哈希），**二者分栏显示、不可互换**；无真实原文件哈希时显示「**原文件哈希待确认**」，**严禁用 `content_hash` 冒充**（唯一实现入口 `course_schema.file_hash_display`）。
- **发布门禁（指令 ①，硬约束）**：仅当**关键待确认项 = 0** 时发布按钮才启用。
  存在未解决关键项时：
  - 主按钮进入**禁用态**（`opacity .4`）**并给出具体原因**（如「有 2 项关键待确认项未解决」）；
  - 提供次操作：「返回校对」与「导出仅含已确认部分的草稿（**不发布**）」；
  - **不允许**跳过校对直接发布，**不允许**静默放行。
- **R1（REV1B）· 关键项无豁免分支**：**关键未解决项不得通过简单勾选豁免**，必须回到校对页逐项解决。
  门禁公式不含「接受即通过」；门禁由**服务端**强制（§8.3）。
- **可接受的非关键缺失**：允许带缺失发布，但必须**逐项记录**——**原因**（为何可接受）/ **范围**（影响哪些课时、页）/ **历史**（谁在何时判定，可追溯），
  且课程内对应位置**持续显示**「已知缺失」标记，**不得**用一句勾选替代记录。
- **R2（REV1B）· 来源依赖**：发布前置校验 `source_doc_id` **存在**、文档 `status=="ready"`、且回读 `content_hash == source_doc_hash`；
  **来源丢失 / 失效 → 禁止发起新发布**（已发布课程保持可读，不自动下架）。
- 覆盖既有课程需**二次确认**；发布成功卡用渐变 + 「去上课」CTA。
- **幂等**：同一 `course_id + revision` 重复发布**不产生副本**。

### 4.7 AI 老师 / 语音状态 / 数字人
- 老师选择：卡片式（形象 + 名 + 教学语言/音色），**学生界面不出现 teacher_id / Token / WebSocket URL / API Key**。
- 语音状态徽章四态：麦克风未授权 / 已授权待启动 / 正在聆听 / 正在回应；**三模式标注**（本地演示 / 本地模拟(Mock) / 真实在线）。
- 数字人：不可用时降级为静态卡片并显示原因；**隐藏后课件区自动扩大**；异常不得导致课程/文字/语音崩溃。
- **禁止假口型**：无真实音频输入时口型必须为 0，并明示「未同步」。

### 4.8 窄屏（tier0 narrow 560–619 / tier1 compact 620–859）
- **命名更正**：REV1 曾写作「窄屏（tier0 / 620）」——**620px 属 tier1 compact**，narrow 仅 560–619（见 §2.1）。
- tier0：顶部老师条（40px 圆头像 + 名 + 状态）；右栏折叠为**底部 Sheet**；课件全宽。
- tier1：**96px 图标竖条**；右栏折叠为**右抽屉**；课件全宽。
- 两档均：**长英文单词与 IPA 必须调用 FIX02 的 `WrapAnywhere` 自适应机制**（画板已演示 `internationalization` 场景）。

### 4.9 双链路契约概要（**导入知识库 ≠ 发布可学习课程**）

> 完整契约见 `CLASSROOM_V2_AGENT_PLAN.md` §8。此处为设计侧约束。

| | **链路 A · 提交知识库** | **链路 B · 发布可学习课程** |
|---|---|---|
| 端点 | `POST /admin/knowledge/import` → `…/{job_id}/commit` | V2 新增（课程草稿 / 校对 / 发布） |
| 产物 | 知识库文档：`doc_id` + 分块 + 内容哈希（**可检索原文**） | 课程 schema v1：信封 `schema`/`version` + 课程 `course_id`/`revision`/`source`/`source_doc_id`/`source_doc_hash`/`source_file_sha256`/`slides`（**可上课**） |
| 状态机 | uploaded → parsed → preview_ready → committed ／ cancelled ／ expired ／ failed | draft → proofreading → ready → published（**＋ blocked 门禁态**） |
| 失败恢复 | cancel / retry；`job_expired`(410)；`duplicate_content`(409, 带 `existing_doc_id`) | 重新生成草稿 / 回滚上一已发布版本 / 保留未发布草稿 |
| 幂等 | `Idempotency-Key` | `course_id + revision` |
| **依赖关系** | 独立 | **强依赖 A 的 `source_doc_id` + `source_doc_hash`**（文档存在且内容哈希一致）；来源失效 → 禁止新发布 |

**设计侧四条硬约束**：
1. **A 成功 ≠ B 可发布**：知识库已提交只解锁「生成课程草稿」，不产生「开始学习」入口。
2. **门禁不可绕过**：B 的 `published` 前置条件 = 关键待确认项为 0（§4.6）；**关键项不得勾选豁免**，且**校对页无发布按钮**（只有进入发布流程的导航）。
3. **失败不互相吞掉**：A 失败不使 B 草稿失效；B 校对失败不清空 A 的知识库文档。
4. **书库卡片必须同时显示两套状态**（如「知识库：已提交」+「课程：草稿」），不得只显示一套而误导。
5. **来源依赖是新的阻断位**：`source_doc_id` 悬空 / `content_hash` 漂移时，**仅禁止新发布**，不删除已发布课程（保证学生端可读）。

---

## 5. 六类状态规范（硬约束）

| 状态 | 视觉 | 文案/交互 | 覆盖点 |
|---|---|---|---|
| **正常** | 标准令牌 | — | 全组件 |
| **加载** | 骨架屏（尺寸=真实内容、同圆角）；**≤300ms 不显示**；长任务=顶部 3px 渐变进度条 | 显示「第 n/N 步 · 预估 xx 秒」 | 书库、课件、字幕、解析、导入队列、发布 |
| **空数据** | 图标 96 + 主文案 + 副文案 + **单个** CTA | 「书架还空着」→「导入第一本教材」 | 书库、字幕/词汇/笔记、章节树、0 词条 |
| **离线** | 顶部 OfflineBanner（warn 底 + 云断图标） | 网络操作禁用并说明；恢复后 200ms 淡出 | 全 app、书库、导入、发布、语音 |
| **错误** | **内联错误卡（不整页崩）**：图标 + 主因 + 次因 + 「重试」 | 保留其余可用；单文件失败=行内红字可移除重试 | 课件加载、书库、导入、解析、发布、老师列表 |
| **禁用** | opacity .4 + 光标 default + **必须** ToolTip 说明原因 | 复用现有 `enabled:` 逻辑 | 开始学习、下一页、语音、发布 |

### 5.2 网络四态（REV1A 新增 · 与「离线」区分）

V2 客户端**首次具备网络能力**（对接本机环回网关）。四态**必须**与系统级「离线」区分，不得混用：

| 态 | 含义 | 视觉 | 文案/交互 |
|---|---|---|---|
| **未连接** | 本机环回网关未就绪 | 中性灰 + 🔌 | 「本地服务未启动」+「重试」；**本地阅读不受影响** |
| **连接中** | 正在建立 | 脉冲/骨架 | 超过 3s 追加「仍在连接…」+ 取消 |
| **失败可重试** | 请求失败 | warn 内联卡 | 明确主因 + 「重试」；**不整页崩** |
| **离线** | 系统无网络 | OfflineBanner | 「离线，可继续阅读本地教材」；网络动作禁用并说明 |

**共同约束**：① 有明确原因文案；② 有重试入口；③ **不阻塞本地已发布课程的阅读**；④ 不得以「离线」掩盖「本地服务未启动」。

### 5.3 设计样例与真实状态的分界（REV1A 强制）

| 字段 | 真实数据源 | 无数据时的正确表现 |
|---|---|---|
| 老师姓名 / 学科 / 教学语言 / 音色 | `GET /xiaozhi/v1/teacher/list` | 「未选择老师」 |
| 连接状态（老师在线 / 未连接） | 真实 WebSocket 会话状态 | **「状态未知」**（不得沿用样例值） |
| 语音状态（聆听 / 讲解 / 待启动） | 真实音频会话事件 | 「未启动」 |
| 实时字幕 | 真实字幕事件流 | **空状态**（不得预填示例句） |
| 数字人口型 | 真实 TTS 音频（无音频时恒 0） | 口型 0 + 「未同步」 |
| 教材文件名 / 页数 / 章节数 | 知识库文档与课程元数据 | 空状态 |
| **页码 / 抽取器索引 / 章节映射 / 置信度** | 真实解析产物的溯源元数据（须可校验） | **「页码待确认」「章节归属待确认」「不可评估」**——不得用推断数字冒充（REV1B R7） |
| 课程与课件正文 | 用户教材解析产物 | 演示样本须显式标注 `local-demo` |
| 待确认项数量 / 校对进度 | 真实校对状态 | 不得写死 |
| 发布门禁状态 / 来源 `doc_id`·`content_hash` 有效性 | 服务端门禁与来源依赖校验 | 未校验 → 不得显示「可发布」；来源失效 → 显示阻断原因 |

> **QA 验收用例（强制）**：**断开全部后端**，逐一核验上述字段**不出现**画布示例值（如「老师在线」「正在讲解」）。

---

## 6. 动效与无障碍

- 时长：100（hover）/150（按压、chip、标签）/220（面板展开、页切换）/320（抽屉、向导）。
- 缓动：`easeStandard cubic-bezier(.2,0,0,1)`、`easeEmphasized cubic-bezier(.05,.7,.1,1)`、`easeExit cubic-bezier(.3,0,1,1)`。
- 规则：标签切换**不做位移**（避免布局跳动）；speaking 头像呼吸 scale 1.0→1.03 / 1200ms；thinking 三点脉冲；**禁止无意义 confetti**。
- `animationsEnabled` 关闭时所有过渡降为 0ms。
- 焦点环统一 `focusRing`；键盘可达所有交互控件；`Accessible.name` 覆盖图标按钮。

---

## 7. 与数据契约的衔接（见 `CLASSROOM_V2_AGENT_PLAN.md` §3.6/§3.7.1/§3.8）

- **两层结构（PHASE2 冻结）**：文档级（信封）只含 `schema`/`version`/`label`/`notice`/`courses[]`；**`source` 只在课程级**，文档级出现 `source` = 违规。
- `source` 枚举 `local-demo | admin-knowledge | user-textbook` → **书库/课堂需展示来源徽标**（`user-textbook` = 我的教材；`local-demo` = 本地演示样本）。
- **来源绑定**：`local-demo` 三绑定字段（`source_doc_id`/`source_doc_hash`/`source_file_sha256`）强制 `null`（**不得伪造**）；正式来源必须有真实绑定。
- **哈希分栏（修正③）**：`source_file_sha256`（原文件字节哈希）与 `content_hash`（抽取文本哈希）**分栏显示、不可互换**；无值时显示「**原文件哈希待确认**」。
- `version` 缺失/未知 → 走**错误态**（不静默）。
- 未知 `slide.type` → 渲染「未知内容类型」占位（**不得空白页**）。
- `practice.answer` 缺失/非法 → 「**答案待人工确认**」，不计分、不判错。

---

## 8. 产品负责人审定结果（REV1A · 已裁定）

| # | 事项 | 裁定 |
|---|---|---|
| 1 | 视觉方向 | **APPROVED_WITH_FIXES**（REV1A 已修：深色标题对比度、断点命名、设计样例标注） |
| 2 | 三栏宽度 260 / flex / 340 | **APPROVED_AT_1360**（即 tier4） |
| 3 | 「我的书库」默认首页 | **YES** |
| 4 | 单 AppShell 内视图切换 | **YES** |
| 5 | 备课链路连网方式 | **D1 = MAC_LOOPBACK_ISOLATED**（本机环回、独立验收环境；安全方案见 §9） |
| — | EPUB 范围 | **D2 = EPUB_TEXT_ONLY_IN_P0** |
| — | OCR 范围 | **D3 = OCR_DEFERRED_TO_P1** |

**REV1B 复审（最新）**：R3–R6、R8–R12 **设计层通过**；**R1 / R2 / R7 需最小补正**（本文件 §4.5 / §4.6 / §4.9 已完成）。
Agent G 方案 **有条件批准**（S1–S5 已裁定，见 `security/`）；Agent H 方案 **有条件批准**（H1–H5 已裁定，见 `deploy/`）；
D2 EPUB **接受开发交付，独立 QA 待完成**（见 `CLASSROOM_V2_PARSER_CAPABILITY_REPORT.md`）。

**残余门禁（PHASE 2 LIMITED START · 最新）**：`MAIN_UI_CONSTRUCTION_GATE = PENDING_REV1B → 补正完成 → **APPROVED_FOR_NON_SENSITIVE_P2**`。
R1/R2/R7 补正**已被产品负责人接受**（逐条记录原见 `CLASSROOM_V2_REV1B_DIFF.md`，该原件已删除，恢复=项目外备份）；**四项契约修正已完成**（文件所有权 / 冻结唯一 Course Schema / 哈希语义 / 打包最小化，见 `CLASSROOM_V2_PHASE2_CONTRACT_FIX_01.md`）。
**允许**非敏感 UI、解析适配、课程草稿、文字/Mock 语音、记忆、数字人适配及测试进入 Phase 2；**禁止**在独立安全复核前实现/开放/启用**链路 B 最终发布服务端路由**。
大规模主 UI 施工按文件所有权矩阵分派（B 独占 QML；`classroom_model.py` 由 TC 串行协调；I 不与 B 并发改 QML）。

---

## 9. D1 安全架构与部署约束（REV1A 新增 · REV1B 修订 · 设计侧）

> 完整方案由 Agent G / H 分别交付：`docs/engineering/product-v1/classroom-v2/security/`、
> `docs/engineering/product-v1/classroom-v2/deploy/`。此处仅为设计侧必须体现的约束。

**严禁（设计期即须遵守，不得出现任何"后续再补"的例外）**：
1. 在学生 `.app`、QML、前端资源或日志中**保存 / 硬编码 / 暴露管理员 Bearer Token**；
2. 把**管理员权限**直接交给普通学生客户端；
3. 使用 **Tina 生产密钥 / 正式网关数据目录 / NAS 服务**；
4. **开放局域网或公网**导入端点。

**设计要求**：
- 客户端**只**访问 `127.0.0.1` 上的本机环回网关；界面**不出现**任何 Token / URL / JSON 字段（沿用 FIX01 既有约定）。
- 鉴权采用**最小权限**原则（一次性/会话级授权，非长期管理员凭据）；具体机制由 G 方案裁定后再落 QML。
- 敏感凭据**不得**进入前端资源、不得进入日志、不得由用户手工填写。
- Finder 双击的生命周期（启动/健康探测/端口/崩溃恢复/退出清理）由 H 方案裁定；**普通用户不得手动开终端或填技术参数**。

**REV1B 追加约束（产品负责人裁定，设计侧同步）**：
- **默认拒绝 + 仅 `127.0.0.1`**；**不接受未经明确定义的 `Origin: null` 作为可信依据**。
- 会话密钥传递**优先匿名继承 fd / `socketpair`**，**严禁**通过同一用户其他进程可连接的 socket 无条件发放会话密钥。
- 学生端**不开放**管理型导出、批量删除、存储维护；不内置不必要管理员功能与凭据。
- **不得**把本机单用户会话令牌当成学生身份。
- 子进程**直接绑定 `port 0`**，通过受保护 IPC 上报真实端口/就绪信息；**不得**父进程预占端口后再让子进程竞争绑定。

**门禁**：**在 D1 安全方案获批前，不得把现有 `/admin/knowledge/import` 的管理员 Token 接到学生客户端。**

---

## 10. 附录：后端验证修订（v1.1 · 实测驱动）

> 依据 `CLASSROOM_V2_PARSER_CAPABILITY_REPORT.md`（P0 只读实测）。**不改变本文件已定的页面结构与视觉基线**，
> 仅补齐设计与契约边界。

### 10.1 书库/导入/解析/校对/发布 5 页 = **UI 对接既有 HTTP API**

后端导入管线已完整实现并挂载（10 条路由）。设计上须**按 API 语义映射界面**，不得自造状态名：

| 界面元素 | 对接语义 | 依据 |
|---|---|---|
| 上传（拖拽/选择） | `POST /admin/knowledge/import`（multipart，单文件 ≤ 20 MB，支持 `Idempotency-Key` 防重复） | 超限 → `body_too_large`(413) |
| 支持格式提示 | `GET /admin/knowledge/parsers` 动态读取（**禁止硬编码**） | 能力表含 `available`/`reason` |
| 解析进度/预览 | `GET /admin/knowledge/import/{job_id}`（预览 TTL **30 min**，过期 → `job_expired`(410)） | 8 态机 |
| 「确认提交知识库」按钮 | `POST .../{job_id}/commit`，**必须带确认** | 缺确认 → `confirm_required`(400) |
| 重复教材 | `duplicate_content`(409) **携带 `existing_doc_id`** → 界面应提供「查看已存在的那份」而非只报错 | — |
| 提交成功 | 仅在 `readback_ok=true` 时提示成功 | 服务端回读磁盘后才报 applied |

> **注意**：本表整表属于**链路 A（提交知识库）**。链路 B（发布可学习课程）不在既有 API 内，见 §4.9。

### 10.2 网络四态（已并入 §5.2）

四态定义与约束见 **§5.2**；本节保留为索引，不再重复。

### 10.3 解析相关错误码的**中文可操作文案**（不得空白页）

| 错误码 | 界面文案（建议） |
|---|---|
| `scanned_pdf_no_text` | 「这份 PDF 是扫描件，没有可复制的文字。扫描件识别尚未开放，请换用可复制文字的版本。」 |
| `unsupported_content_type` | 「暂不支持这种格式。」+ **动态列出** `GET /admin/knowledge/parsers` 返回的可用扩展名（**不得写死**） |
| `parser_unavailable` | 「本机解析组件暂不可用（<原因>）。可稍后重试。」（**不得**让学生看到技术堆栈） |
| `epub_malformed`（D2 新增） | 「这本 EPUB 文件已损坏或格式异常，无法读取。「+ 不展示内部细节」 |
| `job_expired`(410) | 「解析结果已过期，请重新上传该文件。」 |
| `duplicate_content`(409) | 「这本教材之前已经导入过。」+「查看已有记录」按钮（用 `existing_doc_id` 定位） |

### 10.4 版面风险提示（**一般性文案，不得声称自动检测**）

多栏排版的**静默错序**风险已实证复现（见 `CLASSROOM_V2_PARSER_CAPABILITY_REPORT.md` §4.2）。
校对页须显示**一般性**风险提醒：

> 「当教材为**多栏排版**时，文字抽取顺序可能与阅读顺序不一致，词条边界可能不准确，请重点核对。」

**硬约束（REV1A 指令 ⑧）**：
- 当前**不具备**自动栏检测能力 → **禁止**出现「检测到疑似多栏排版」「第 N 页为双栏」等**声称已检测**的措辞。
- 仅当后端**返回真实检测信号**时，才允许切换为针对性提示；在此之前一律使用上述固定文案。
- 无论是否有提示，人工校对步骤**不可跳过**（与发布门禁 §4.6 联动）。

