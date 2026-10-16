# V1_ENGINE_LICENSE_AUDIT_V2

date=2026-10-09T00:00:00Z (branch avatar-vision-v06-mac-native)
scope=V1.0 整改重审: 数字人引擎许可四档对照（个人开发 / 内部测试 / 公开发行 / 商业使用）, 取代 V1_LIVE2D_LICENSE_EVALUATION 的"一刀切否决"结论
policy_input=产品负责人指示: 不得因"未来商业许可不确定性"认定当前开发不能使用; 必须按使用档位区分判定

## METHODOLOGY (证据等级标注约定)

- **[A-官方原文]** 直接抓取的官方条款/官方仓库 LICENSE 文件原文
- **[B-官方页面]** 官方网页正文（WebFetch 抓取成功）
- **[C-官方矩阵]** 官方文档表格/支持矩阵页
- **[D-二手转引]** 第三方对官方条款的逐条转引（未能回抓一手原文）
- **[E-社区共识/推断]** 无一手数据，由公开实践推断
- 未能核实的点均如实标注，无臆造。

## AUDIT_DATE = 2026-10-09

---

# 1. Live2D Cubism (Web SDK 路线: Cubism Core + Framework, QML WebView 内嵌)

## 1.1 许可结构 [A/B]

三层结构，本轮全部核对：

| 组件 | 许可 | 来源 |
|---|---|---|
| Cubism Core (live2dcubismcore.min.js) | Live2D Proprietary Software License | https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html |
| Cubism Web Framework (源码) | Live2D Open Software License（年收≥1000 万日元的事业者须另行取得 Release License） | 官方仓库 https://github.com/Live2D/CubismWebFramework/blob/main/LICENSE.md [A-官方原文，本轮逐字抓取] |
| 官方样例模型 (Hiyori/Haru/Mao/Mark/Natori/Ren/Rice/Wanko) | Free Material License + 逐模型 Terms of Use | 官方 https://github.com/Live2D/CubismWebSamples/blob/main/LICENSE.md 及 https://www.live2d.com/eula/live2d-sample-model-terms_en.html (v1.7, 2026-01-29) [A/B] |

官方 Framework LICENSE.md 原文关键句 [A-官方原文]:

> "*All business* users must obtain a Cubism SDK Release License. 'Business' means an entity with the annual gross revenue more than ten million (10,000,000) JPY for the most recent fiscal year."

官方 SDK 发布页关键句 [B]:

> "License agreement required for business entities publishing a content using Live2D SDK. Individuals and Small-Scale Enterprises are exempted from the license and payment (except Expandable Application)."
> "**License only required upon releasing** your content. **Not during trial or development.**"

官方帮助中心（无需签约的情形）[B]:

> "・尚处于 Live2D Cubism SDK 试用和开发阶段。"
> "・年销售额低于 1000 万日元的'小型企业'或'普通用户'公开作品时。"
- https://help.live2d.com/en/?p=2558

规模定义 [B]（https://help.live2d.com/en/sdk/sdk_007/）:

> "Small-Scale Enterprises: enterprises with the Latest Sales of less than 10 million yen"
> "Middle-Scale Enterprises: ... 10 million yen or more and less than 100 million yen"
> "Large-Scale Enterprises: ... 100 million yen or more"

## 1.2 Core 再分发与 WebView 内嵌

- 官方 SDK 分发包内 `Core/RedistributableFiles.txt` 列明 `live2dcubismcore.js / .min.js / .d.ts` 为"允许按 Proprietary License 条款再分发的文件"；协议第 5.1 条（转引）："The Customer may copy and distribute the Redistributable Code." [D-二手转引，来源为社区逐条引用 SDK 包内文件：http://hime.xdrv.cn/guide/develop/model-license.html ；未能本轮回抓一手 SDK 包，待集成时以随包 LICENSE 原文最终确认]
- 官方明确 **Core 不放入 GitHub**："根据 Live2D 专有软件许可协议，不在 GitHub 上发布 Cubism Core。" [C-官方矩阵] https://docs.live2d.com/zh-CHS/cubism-sdk-manual/cubism-sdk-for-web/
  → 推论 [E]: Core 不得提交进 Git 仓库/单独上传 CDN，只能以"应用内嵌分发"形式随成品发布（官方 SDK 的设计用途即如此）。
- WebView 桌面内嵌: 官方支持矩阵只承诺浏览器（Web SDK: Chrome/Firefox/Safari/Edge）[C-官方矩阵] https://docs.live2d.com/en/cubism-sdk-manual/platform/ (更新 2026-09-29)。QtWebEngine(Chromium) 属非官方环境；Electron+Live2D 桌面壳是大量公开实践 [E-社区共识]。旧评估"WebView 内嵌按 Native 分发类判定"的框架正确，但**仅当发生分发/出版时**该判定才有意义——开发与内部测试阶段不触发任何出版义务。
- **本轮未找到专门针对"QtWebEngine 内嵌"的官方 FAQ 条目**——如实记录：该组合无官方明文背书，属"官方许可模型可容纳的常见实践"，证据等级 [E]。

## 1.3 Expandable Applications（唯一对个人/小规模也生效的特别通道）[B]

官方定义 [B]（https://www.live2d.com/en/sdk/license/expandable/）:

> "'Expandable Application' means any work having significant expandability among services or content utilizing SDK products. In particular, it includes the Derivative Work which uses and generates any indefinite numbers of models by adding or combining files or data (e.g. avatar)"

触发条件（对本项目）: 只有当应用可加载**不特定数量**的模型（换装/多化身/开放模型加载）时才落入。**固定单一自绘模型的 AI 对话产品不落入** [B-官方流程图明确要求先判断是否 Expandable，非 Expandable 走普通 plan]。

Expandable 通道的义务（官方价目）[B]:
- General User / Small-Scale（<1000 万日元）: 免初始费与年费，但 **Revenue Share $1.90USD[¥300]/次 或 20% 取高 + 季度销售报告**（注意: 旧评估写 $1.95，官方现行价目为 $1.90）
- Middle-Scale: initial ¥50,000 + 年费 ¥240,000/平台 + 5%; Large: ¥300,000 + ¥1,200,000/平台 + 5%
- 发行前须逐个通过 Live2D 审查并签特别 Publication License
- 规模变化须 2 个月内通知，追溯补费

## 1.4 样例模型关键条款（官方 v1.7, 2026-01-29）[B]

- Hiyori Momose（及 Miara）: "**No changes of any kind to the design of this character are permitted.**"（零改模）
- Shizuku: 禁改名称与设定; Nito: 保持头身比; Mark: 保持卡通属性
- 强制版权声明（长版/短版按平台能力）: "This content uses sample data owned and copyrighted by Live2D Inc. ..."
- 联动角色（如 Natori）: "may neither use ... for commercial purposes nor alter nor distribute them"
- Miku/Unity-chan 等外部授权角色按第三方条款

## 1.5 四档对照: Live2D Cubism

| 档位 | 允许? | 条件 | 证据 |
|---|---|---|---|
| 个人开发（下载 SDK、写代码、本机跑） | **明确允许，免费，无需任何许可合同** | 同意 Proprietary + Open 两个协议（下载即视为同意） | [B] 官方: "Not during trial or development" |
| 内部测试（仓库内、不发二进制、不上线） | **明确允许** | 同上；若把 Core 提交进 Git 即违反再分发管理惯例（见硬条件） | [B] 同上 |
| 公开发行 | **个人/小规模（<1000 万日元年收）豁免签约与付费** | 固定单一模型 + 非 Expandable → 普通方案免费; 须满足样例模型条款（声明/零改模）或使用自制模型; 发行前一个月完成流程确认 | [B] 官方发行页+FAQ p2558 |
| 商业使用 | **有条件** | 年收 <1000 万日元且非 Expandable → 仍免费; 年收 ≥1000 万日元 → 签 Publication License 付费（Middle ¥5 万 initial + ¥24 万/年/平台 + 5% RS 起）; 若做可加载多模型的化身 → 任何规模均需逐个过审 + $1.90/次或 20% 取高 + 季度报告 | [B] 官方价目 |

**结论: 当前整改（个人开发 + 内部测试）阶段，Live2D Cubism 是官方明文免费且无需许可合同的用途。**

## 1.6 雷区

1. Core/模型二进制不得提交 Git（官方不发布 Core 到 GitHub，属于许可管理要求; 再分发白名单以随包 RedistributableFiles.txt 为准）
2. 年收越线（1000 万日元）→ 义务即刻触发，须 2 个月内通知并补签 [B]
3. 一旦做成"可换模型"形态 → Expandable 审查通道，不可逆地进入 Revenue Share 体系 [B]
4. 样例模型 Hiyori 零改模 + 强制声明; 想要自有形象须自制模型（Cubism Editor PRO 付费）或购买模型（逐个核许可）[B]
5. Editor 本身另算: PRO 版按月订阅，与 SDK 许可无关 [C]

---

# 2. Open-LLM-VTuber（主仓库 + 前端复用）

## 2.1 主仓库 Open-LLM-VTuber [A-官方原文]

LICENSE（逐字抓取自 https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/blob/main/LICENSE）:

> "MIT License / Copyright (c) 2025 Yi-Ting Chiu"
> 末行: "This project is licensed under the MIT License, except for the Live2D sample models, which are governed by LICENSE-Live2D.md."

其 LICENSE-Live2D.md 是 **Live2D 官方样例模型条款的全文转载**（Hiyori 零改模、强制版权声明、联动角色禁商用等，与本文 1.4 相同）[A-官方原文，逐字抓取]。即: 主仓代码 MIT，模型资产沿用 Live2D 官方条款——**与本文第 1 节义务完全一致，不因 MIT 而豁免**。

## 2.2 前端 Open-LLM-VTuber-Web [A-官方原文]（关键新发现）

LICENSE（逐字抓取自 https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web/blob/main/LICENSE）——**不是标准开源许可，是自定义 "Open-LLM-VTuber License 1.0"（Apache 2.0 + Additional Conditions）**，GitHub 识别为 NOASSERTION：

免费用途（无需商业许可）:
> "Non-commercial Uses: Any non-commercial activity including, but not limited to, personal projects, educational purposes, academic research, and non-profit initiatives."
> "VTuber Streaming and Content Creation: ... provided revenue primarily derives from content creation and not from direct sale, distribution, or subscription to the software itself."

需单独商业许可的用途:
> "Monetized Access or Hosting Services"（SaaS/订阅/按次付费/付费下载安装）
> "Commercial Redistribution or Rebranding"（收费的再打包/换牌）
> "Commercial Embedding or Integration: Incorporating this software, wholly or partially, into any commercial software, hardware, or physical product that is sold, licensed, or otherwise distributed for a fee."

## 2.3 四档对照: Open-LLM-VTuber（代码部分）

| 档位 | 主仓 (MIT) | 前端 Web (自定义) | 证据 |
|---|---|---|---|
| 个人开发 | 允许 | 允许（"personal projects" 明文） | [A] |
| 内部测试 | 允许 | 允许（非商业） | [A] |
| 公开发行（免费分发、非收费） | 允许 | 允许，但落在自定义许可的灰色边缘（"non-commercial activity" 覆盖，非 VTuber 直播变现场景需按 non-commercial 解释） | [A] + [E-解释空间] |
| 商业使用（嵌入收费产品） | 允许（MIT 不限制） | **不允许，必须向 Open LLM Vtuber 购买商业许可**（"Commercial Embedding" 条款直接命中本项目形态） | [A] |

## 2.4 雷区

1. **前端是未来的硬阻断**: 若 V2.0 商业化且复用其前端渲染层，自定义条款要求整条前端渲染链换掉或购买商业许可。MIT 的主仓救不了前端。
2. 其捆绑的 Live2D 样例模型（Hiyori 等）义务与 Live2D 官方条款相同（声明、零改模）。
3. 复用运行层（音频→参数驱动逻辑）本身 MIT 没问题; 问题集中在 Web 前端壳。

---

# 3. Inochi2D（原生路线）

## 3.1 许可覆盖范围 [A-官方原文]

| 组件 | 许可 | 来源 |
|---|---|---|
| inochi2d 库（D 语言 SDK） | BSD 2-Clause（"Copyright (c) 2020-2026, Inochi2D Project / Kitsunebi Games"） | 逐字抓取 https://github.com/Inochi2D/inochi2d/blob/main/LICENSE [A] |
| inochi-session（VTuber 应用，参考实现） | BSD 2-Clause | GitHub 仓库 license 元数据 [A] |
| inox2d（Rust 重实现） | BSD 2-Clause（"Copyright (c) 2022 Speykious and Inochi2D Project"） | 逐字抓取 [A] |
| example-models（模型文件） | **无 LICENSE 字段、仓库根目录无 LICENSE 文件** | GitHub API 查询结果 [A] |
| Inochi Creator / Session 应用本体 | BSD-2-Clause | GitHub [A] |

**关键: 引擎 BSD-2-Clause ≠ 模型文件可用。** 官方示例模型仓库没有明确许可标注——逐模型核对义务依然存在（与 Live2D 层结构相同）。官方文档 FAQ 建议自制模型（Inochi Creator 制作）。[C] https://docs.inochi2d.com/

## 3.2 运行时成熟度（如实评估）

- 参考实现是 **D 语言**库，官方集成方式: D 原生 / C FFI (inochi2d-c, 需 LDC2+dub 自建或取预编译) / WebAssembly (需 patched druntime, "currently this requires a patched druntime source tree") / 官方绑定仅 Unity 与 Godot(GDExtension) [B] README https://github.com/Inochi2D/inochi2d
- **Python: 无成熟绑定**。仅 "Python via ctypes/FFI" 的机制可行性描述 [D-DeepWiki 转述 README]，无 PyPI 发布包、无官方 Python 绑定工程。与 PySide6 客户端集成 = 自维护 ctypes 绑定 + 动态库构建链，工作量为自建项目级别。[E-推断]
- 渲染管线: 参考实现 **要求 OpenGL 3.1 上下文**（README/README.ja 明文）[B]。macOS 提供 OpenGL 4.1（Apple 已弃用但可用）→ QOpenGLWidget/自建 GL 上下文技术上可行 [E-推断，基于 Apple 公开平台能力]。WASM 路线同样需要 patched 工具链，成熟度低 [B]。
- inox2d (Rust): 纯解析器方向，"In Development"（官方定语），不能作为生产运行时 [C-官方描述]。
- 社区规模: inochi2d ~1.7k stars，生态以 Inochi Session（VTuber 直播）为主，无 Qt/桌面应用嵌入的公开案例 [E-社区共识]。

## 3.3 四档对照: Inochi2D

| 档位 | 允许? | 条件 | 证据 |
|---|---|---|---|
| 个人开发 | 允许（BSD-2 无限制） | 保留版权声明 | [A] |
| 内部测试 | 允许 | 同上 | [A] |
| 公开发行 | 允许 | BSD-2 二进制再分发条款（声明保留）; 模型文件逐个核 | [A] |
| 商业使用 | 允许 | BSD-2 允许商用，零版税; 模型文件逐个核 | [A] |

## 3.4 雷区

1. 许可全绿，但**工程成本是三条路线最高**: 无 Python 绑定、需自建 D/C FFI 工具链、渲染需自管 OpenGL 上下文、WASM 链不成熟。
2. 模型资产层无许可标注 → 与 Live2D 同样的"逐模型核对"义务, 且可用模型生态远小于 Live2D（Inochi Creator 生态起步中）[E]。
3. macOS OpenGL 弃用风险: Apple 长期不维护 OpenGL，Inochi2D 参考实现锁死 GL 3.1 → 未来演进靠其 renderer 抽象（"bring your own renderer"）[B/E]。

---

# 4. Mac 客户端集成依赖与性能预期

| 维度 | a. Cubism Web 经 QtWebEngine | b. Inochi2D 原生 | c. Open-LLM-VTuber 复用 |
|---|---|---|---|
| 运行时文件 | live2dcubismcore.min.js (WASM, 须从官方 SDK 包解出) + Framework 源码 + pixi-live2d-display(MIT) 或直接 Framework + 模型 .moc3/.model3.json | inochi2d 动态库(dylib, dub 自建 C FFI) 或 WASM; 模型 .inp/.inx | Python 主程序(pip 依赖链) + Open-LLM-VTuber-Web 前端构建物 + Node/前端资产 |
| Web 引擎 | 需要 QtWebEngine/WebKit (PySide6 自带, Chromium 内核) | 不需要 | 需要（前端即 Web 技术，通常 Electron 或浏览器） |
| GPU/渲染 | WebGL (官方支持 Safari/Chrome/Edge; QtWebEngine=Chromium 等价 [E]) | OpenGL 3.1 上下文（macOS 可用但已弃用） | WebGL（同 a） |
| 内存 | 无官方公开数据; Chromium 内核 WebView 进程常量开销通常为数百 MB 级 [E-社区共识，不编精确数] | 官方系统要求: "At least 1 GB of RAM for bigger models", CPU x86-64 SSE4+/Aarch64 NEON [B-官方 README] | 无公开基准数据 |
| CPU/延迟 | 无官方公开数据; 本项目 V0.6 已实测 fallback rig 音频振幅→参数链路 barge-in ≈0ms（自有基准，与引擎无关的接口层同构） | 无公开数据 | 无公开数据 |
| 附加依赖 | pixi-live2d-display (MIT, @jannchie 维护分支 2026-08 仍活跃) [A] | LDC2 + dub 构建链（引入 D 工具链依赖） | Python ≥3.10、音频管线（其自带 ASR/TTS 桥接，可能与本项目 gateway 冲突需裁剪）[E] |

官方一手数据仅 Inochi2D 有系统要求表；Cubism 与 Open-LLM-VTuber **无公开性能基准**，如实标注。

---

# 5. 与既有评估的差异 (V1_LIVE2D_LICENSE_EVALUATION)

## 5.1 成立的结论（本轮重申）

1. 双协议结构、Core 永远专有 —— 成立 [A/B 重证]
2. 小规模豁免是**动态义务**（随年收变化，2 个月通知义务）—— 成立且本轮补足官方出处 [B]
3. Expandable Application 对个人/小规模也生效（换装/多化身类产品不可控）—— 成立 [B]
4. 样例模型资产层义务（声明/零改模/禁改设定）—— 成立，官方 v1.7 重证 [B]
5. "MIT 不漂白任何许可"（对 pixi-live2d-display 而言）—— 成立，且在 Open-LLM-VTuber 主仓同样应验（MIT 代码 + 非开源条款的模型转载 + 自定义许可的前端）
6. 技术债判断（WebView 内嵌专有 Core 调试面大）—— 属工程判断，本轮不推翻

## 5.2 过度保守的结论（本轮修正）

1. **"V1.0 不采用"混淆了档位**。官方明文许可义务仅在"发行/出版"时触发（"License only required upon releasing... Not during trial or development"）。既有评估把**公开发行与商业化的未来义务**当作了**当前开发与内部测试的阻断**——这正是产品负责人指出的问题。当前整改档位（个人开发+内部测试，不部署、不合并 main）下，Live2D 路线与自研 rig 的许可负担**完全相同：都是零**。
2. 对"年收越 1000 万日元触发付费"的表述夸大了不确定性：这是**明确的、可预期的**单一阈值（官方价目公开），与"不确定性"是两回事；越线前有充足预警（义务随营收渐进触发，且需 2 个月通知窗口）。
3. "AI/Chatbot 属性天然落入 Expandable"表述过强：官方判定路径是先问"是否可加载不特定数量模型"，**固定单一模型的 AI 界面按普通 plan 走**（个人/小规模仍豁免）。Expandable 风险只在产品主动选择"可换模型"形态时触发。
4. 旧评估未区分"Core 再分发"的两层含义: 单独上传 Core 到仓库/CDN（不被官方允许，官方不把 Core 放 GitHub）vs 随应用内嵌分发（SDK 设计用途，Redistributable Files 白名单明文覆盖）。后者不是雷区。
5. 旧评估未审计替代路线的许可: Open-LLM-VTuber-Web 的自定义商业条款（商业嵌入需买许可）实际上比 Live2D 出版许可**更直接阻断**本项目未来商业化——旧评估将其列在替代路径里而无许可风险标注。

---

# 6. 总结论

## 6.1 当前整改档位（个人开发 + 内部测试，不部署、不合并 main）合法性

三条路线**当前档位均合法**:

| 路线 | 个人开发 | 内部测试 | 公开发行 | 商业使用 |
|---|---|---|---|---|
| Live2D Cubism (Web + WebView) | 免费允许 | 免费允许 | 个人/小规模豁免签约付费（固定单模型时） | 条件触发（年收 1000 万日元阈值 / Expandable 审查） |
| Inochi2D (BSD-2) | 允许 | 允许 | 允许 | 允许（零版税） |
| Open-LLM-VTuber 代码 (MIT) | 允许 | 允许 | 允许 | 允许 |
| Open-LLM-VTuber-Web 前端 (自定义) | 允许 | 允许 | 边缘（non-commercial 解释） | **需购买商业许可** |

## 6.2 推荐路线

**当前整改（V1.0）：采用 Live2D Cubism Web SDK + QML WebView 内嵌，官方样例模型（Hiyori）或自制模型做开发与内部测试。** 理由：
- 官方明文当前档位免费且无合同义务；
- 渲染质量/生态/工具链成熟度最高（官方 TypeScript Framework、WebGL、pixi 包装层 MIT 可选）；
- Inochi2D 许可全绿但工程成本最高（无 Python 绑定、D 工具链、GL3.1 弃用风险），Open-LLM-VTuber 复用受前端自定义许可拖累且与现有 gateway 架构冲突面大。

**V2.0/商业化决策点（提前立牌）**：若产品确定要"可换装/多模型化身"→ 触发 Expandable 审查 + Revenue Share，届时重新评估（届时 Inochi2D 的零版税优势才真正生效）；若保持固定形象且年收 <1000 万日元 → Live2D 路线继续免费。

## 6.3 必须遵守的硬条件（当前整改立即生效）

1. **不得把 live2dcubismcore.min.js / .moc3 等模型二进制提交进 Git**。通过本地下载脚本（用户手动从官方 SDK 包放置）或 LFS + 仓库私有安排处理; 集成时以随包 LICENSE 原文与 RedistributableFiles.txt 为最终依据 [B/D]
2. 不从第三方 CDN 加载 Cubism 2.1 老运行时（官方已停止分发，许可与技术双重不可靠）[B/旧评估重证]
3. 使用官方样例模型（Hiyori）时: 零改模 + 界面/应用信息处保留强制版权声明; 不使用联动角色（禁商用）[B-官方 v1.7]
4. 禁止在开发过程中就把产品做成"可加载不特定数量模型"的形态（防被动进入 Expandable 通道）[B-官方定义]
5. Open-LLM-VTuber 的任何复用只允许主仓 (MIT) 代码级参考，前端渲染层不复用（自定义许可 + 商业化阻断）[A]
6. Inochi2D 仅作为 V2 备选记录，当前不引入 D 工具链依赖 [E-工程判断]

## 6.4 未能核实一手来源的事项（如实登记）

- Live2D Proprietary Software License Agreement 逐条原文（Redistributable Code 5.1 条、Web/Native Application 定义）: live2d.com eula 页为 JS 渲染、Wayback 本轮不可达，仅有社区逐条转引 [D]。集成时以 SDK 包内随附协议 PDF/HTML 为最终依据。
- "QtWebEngine 内嵌"专项官方 FAQ: 未找到官方条目，属可容纳的常见实践 [E]。
- Cubism / Open-LLM-VTuber 性能基准: 无官方公开数据。
- Inochi2D example-models 仓库逐模型许可: 仓库无 LICENSE 文件，逐模型标注情况未逐个核对（当前不采用，不影响结论）。

## SOURCES (本轮全部实际访问核对, 2026-10-09)

- https://www.live2d.com/en/sdk/license/ (SDK Release License 总览) [B]
- https://www.live2d.com/en/sdk/license/expandable/ (Expandable Applications + 价目) [B]
- https://help.live2d.com/en/sdk/sdk_007/ (企业规模定义) [B]
- https://help.live2d.com/en/?p=2558 (何时无需签约 FAQ) [B]
- https://github.com/Live2D/CubismWebFramework/blob/main/LICENSE.md (官方 Framework LICENSE 原文) [A]
- https://github.com/Live2D/CubismWebSamples/blob/main/LICENSE.md (官方 Samples LICENSE 原文, 含样例模型清单) [A]
- https://www.live2d.com/eula/live2d-sample-model-terms_en.html (样例模型条款 v1.7, 2026-01-29) [B]
- https://docs.live2d.com/en/cubism-sdk-manual/platform/ (平台支持矩阵, 更新 2026-09-29) [C]
- https://docs.live2d.com/zh-CHS/cubism-sdk-manual/cubism-sdk-for-web/ (Core 不在 GitHub 发布) [C]
- https://www.live2d.com/en/sdk/about/ (各 SDK 平台/渲染器表) [C]
- https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/blob/main/LICENSE (MIT 原文) [A]
- https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/blob/main/LICENSE-Live2D.md (样例条款转载) [A]
- https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web/blob/main/LICENSE (Open-LLM-VTuber License 1.0 原文) [A]
- https://github.com/Inochi2D/inochi2d (README + LICENSE BSD-2-Clause 原文) [A/B]
- https://github.com/Inochi2D/inox2d (LICENSE 原文 BSD-2-Clause) [A]
- https://github.com/Inochi2D/inochi-session (license 元数据 BSD-2-Clause) [A]
- https://docs.inochi2d.com/ (官方文档/FAQ) [C]
- https://github.com/Jannchie/pixi-live2d-display (MIT, 2026-08 活跃) [A]
- http://hime.xdrv.cn/guide/develop/model-license.html (RedistributableFiles.txt 转引) [D]

## NON_GOALS

- 不下载/集成任何 SDK、模型或工具链。
- 不修改除本文档外的任何文件; 不 git commit。
- 商业化 (V2.0) 的正式许可谈判/签约不在本轮范围; 本文仅标注触发条件与决策点。
