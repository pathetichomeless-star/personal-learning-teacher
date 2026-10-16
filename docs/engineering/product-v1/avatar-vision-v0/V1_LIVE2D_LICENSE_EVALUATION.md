# V1_LIVE2D_LICENSE_EVALUATION

date=2026-10-09T00:00:00Z (branch avatar-vision-v06-mac-native)
scope=V1.0 动漫风英语教师形象: Live2D 引擎选项的许可评估 (PySide6/QML Mac 客户端, QML WebView 内嵌), 以及合规替代路径确认

## SOURCES (官方)

- Cubism SDK 发行许可总览 (Publication License Agreement): https://www.live2d.com/en/sdk/license/
- 企业规模定义 (小规模企业 = 最近年销售额 < 1000 万日元): https://help.live2d.com/en/sdk/sdk_007/ 及 https://help.live2d.com/zh-CHS/sdk/sdk_007/
- Expandable Applications (可扩展性 APP, 逐个审查 + Revenue Share): https://www.live2d.com/en/sdk/license/expandable/
- AI/Chatbot 界面属于官方许可分类之一 (license 页专设 "AI / Chatbot" 判断流程图): https://www.live2d.com/en/sdk/license/
- SDK 下载需同意 Live2D Proprietary Software License Agreement + Live2D Open Software License Agreement: https://help.live2d.com/zh-CHS?p=2557
- 官方样例模型使用条款 (Hiyori/Haru 等原案角色): https://www.live2d.com/eula/live2d-sample-model-terms_en.html 及 https://docs.google.com/document/d/e/2PACX-1vTz65pfSReDw6NTheqxQzfqSj_tgQn1D35PHCQE3EgLKiR80-TFtjvk6WPRL-0g-TMfjJMEgf-7sfvp/pub
- 无偿提供素材使用许可契约书 (Free Material License Agreement): https://www.live2d.com/eula/live2d-free-material-license-agreement_en.html
- pixi-live2d-display (guansss 原作, MIT): https://github.com/guansss/pixi-live2d-display
- @jannchie/pixi-live2d-display (PixiJS v8 维护分支): https://github.com/Jannchie/pixi-live2d-display
- 前序决策: AVATAR_ENGINE_RECOMMENDATION.md (V0.6, 同目录; three-vrm 引擎 MIT 已核实为 V2 路径)

## CUBISM_LICENSE (Live2D Proprietary Software License Agreement 要点)

- **双协议结构**: 下载 SDK 即需同意 ① Proprietary Software License Agreement (覆盖 Cubism Core, 专有闭源) ② Open Software License Agreement (覆盖 Framework 源码部分)。Core 永远是专有组件, 不存在"MIT 化"。
- **免费门槛**: SDK 本身免费下载、免费开发试用; 只有"出版 (公开/分发/销售)"时才触发 Publication License Agreement (发行许可)。
- **豁免条件**: General User (个人/学生/团体) 与 Small-Scale Enterprise (最近年销售额 < 1000 万日元) **出版时豁免签约与付费** (Expandable Application 除外)。中规模 (≥1000 万 < 1 亿日元) / 大规模 (≥1 亿日元) 企业出版需签约付费 (Initial fee ¥5 万~¥30 万 + 年费 ¥24 万~¥120 万/平台 + Revenue Share 5%)。
- **年度审查义务**: 小规模豁免资格以"最近销售收入"为判定基准, 且随每年销售额动态变化——Live2D 自身条款要求使用者持续自查规模, 越线即须立即切换到付费方案 (Editor EULA 2.1.2.4 明确该切换义务); 实质经营管理者为其他企业时按母公司规模判定。即: 免费不是一次性豁免, 而是**随营收增长的持续合规义务**。
- **再分发/内嵌**: 允许把 SDK (含 Core) 编译内嵌进应用分发——这正是 SDK 的正常用途 (Steam 上的 Desktop Waifu 等即 Cubism SDK for Web 内嵌桌面壳的实例)。禁止: 单独抽取 Core 再分发、修改/反编译、未授权公开 SDK 代码。
- **WebView 内嵌 (本项目关键问题)**: 许可协议区分 Web Application (不落盘、经浏览器提供) 与 Native Application (安装到终端设备)。**QML WebView 加载本地打包 HTML+Cubism Web SDK 属于后者 (Native Application, distributed)**——技术上被许可 (Web SDK 支持 Safari/WebKit, QML WebView 可运行), 但要按 Native 分布应用的许可计划 (Plan D/E/G) 判定, 不能按"网页"豁免逻辑套用。
- **AI/Chatbot 特别审查**: 官方许可页将 "AI / Chatbot 界面" 列为独立判定类别, 并设 **Expandable Application** 概念——凡"可加载/生成不特定数量模型的衍生作品 (典型: 虚拟化身)"**无论用户规模 (含个人与小规模企业) 都必须逐个通过 Live2D 审查 + 签订特别发行许可 + Revenue Share ($1.95/次或 20% 取高, 季度销售报告)**。固定单一模型则不落入此类别, 但 AI 对话产品属性使审查边界存在解释空间。

## MODEL_ASSETS (官方样例模型条款)

- 三类: Live2D 原案角色 / 联动角色 / 外部授权角色, 条款各不相同。Hiyori Momose、Haru、Shizuku 等属**原案角色**, 受 Free Material License Agreement + 样例数据利用条件双重约束。
- 原案角色允许: General User / Small-Scale Enterprise (年销售额 < 1000 万日元) 商用+非商用自由使用 (Miku、Unity-chan 等外部授权角色除外)。
- 附加硬性义务:
  - **版权声明强制**: 须在内容显著位置标注 "This content uses sample data owned and copyrighted by Live2D Inc." (长短两版按平台能力选用); 商用时须标注 "Permission for commercial use of this character has been obtained from Live2D Inc."
  - **Hiyori Momose: 禁止任何形式的设计改动** (零改模); Shizuku 禁改名称与设定。
  - 禁止: 情色/暴力/猎奇/政治宗教内容、显著改变角色体型平衡、与其他公司软件制作的模型混售。
  - Live2D 保留"出版"认定的最终解释权。
- 引擎 MIT ≠ 资产可用: 模型资产许可是独立于 SDK 的另一层, 逐模型核对。

## PIXI_WRAPPER (pixi-live2d-display 状态)

- 许可: 原作 guansss/pixi-live2d-display 为 **MIT**; 活跃维护分支 @jannchie/pixi-live2d-display (PixiJS v8) 亦 MIT。
- **它包的是什么**: 仅是 PixiJS 渲染层的便捷封装; 运行必须加载 **Cubism Core** (Cubism 4: live2dcubismcore.min.js, 须从官方 SDK 解出, 下载即受 Proprietary License 约束; Cubism 2.1: live2d.min.js 已于 2019-09-04 停止官方分发, 只能走第三方 CDN——生产环境不可靠且有许可瑕疵)。
- 结论: **MIT 不漂白任何许可**——Core 仍是专有组件, Publication License 全部义务原样落在使用方。插件的 MIT 只覆盖它自己那部分胶水代码。
- 兼容性: PixiJS 8.x + WebGL + ES6, 支持 Cubism 2.1/3/4 全系模型, 音频 lipsync (speak()/麦克风/手动值)、眨眼/呼吸/物理开关齐全, 在 WebView (WebKit) 内可运行——技术可行无障碍, 瓶颈纯在许可层。

## VERDICT_V1 = fallback-2d-rig

**判定: Live2D 路径对本项目"有条件合法但高摩擦", V1.0 不采用; 采用 QML Canvas 参数驱动 2D 分层形象 (Live2D 式 rig, 零专有依赖) 作为 V1.0 路径。**

逐条理由:

1. **许可对"个人/小规模"确有豁免, 但义务是动态的**: 当前小规模可免费出版, 然而英语教学产品一旦商业化且年销售额越过 1000 万日元, 即触发 Publication License (Initial + 年费 + 5% Revenue Share)。免费地位需**逐年自查**, 属持续性合规负担而非一次性豁免。
2. **AI/Chatbot 属性是官方重点审查类别**: 本产品正是"AI 对话 + 形象界面"。若未来支持换装/加载多模型 (化身可扩展性), 直接落入 Expandable Application——**所有规模用户 (含个人) 都须逐个过审 + Revenue Share + 季度销售报告**。产品演进方向与该高风险类别天然重叠, 不可控。
3. **资产层附加枷锁**: 官方免费样例 (Hiyori/Haru) 强制版权声明、商用声明, Hiyori 零改模; 想要"动漫英语教师"的差异化形象则需外包/购买模型, 每个模型许可再核一遍。资产供给被锁死在 Live2D 生态内。
4. **技术债**: WebView 方案本质是把专有 Core 塞进 Native 壳, 调试面大 (WebGL in QML WebEngine), 且 Core 不可审计、不可修改。
5. **合规替代路径已验证**: V0.6 AVATAR_ENGINE_RECOMMENDATION 方案 4 (Canvas/CSS + WebAudio AnalyserNode) 已跑通三态机 + 口型驱动 + barge-in ≈0ms; V1.0 将其升级为 **QML Canvas 参数驱动 2D 分层形象**——保持「音频振幅 → 口型/表情参数」接口不变, 渲染层做成 Live2D 式多图层 rig (呼吸/眨眼/头偏/口型), 形象绘制 100% 自有, 零专有依赖、零许可义务、零外部资产许可核对。
6. **V2 保留升级路径**: three-vrm (引擎 MIT, pixiv 维护) 已核实; 届时仅需按 VRM 资产逐模型核对许可 (优先 VRoid Studio 自制或明确允许商用的模型), 接口层与 2D rig 完全同构, 切换成本可控。

## NON_GOALS

- 不在本轮下载/集成任何 Live2D SDK 或模型文件。
- 不改变 V0.6 已上线的 admin 侧 avatar 实现。
- 不触碰 Tina 形象与其链路。
- 本文件为唯一产出 (只读调研 + 本文档)。
