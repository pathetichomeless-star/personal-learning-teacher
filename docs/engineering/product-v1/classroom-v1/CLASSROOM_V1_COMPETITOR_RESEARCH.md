# CLASSROOM V1 — Competitor Research: Public UI & Interaction Patterns for an English-Learning Student Classroom

小智学生课堂 V1 · 竞品公开界面与交互机制研究

## 一、研究方法与来源

- 仅使用公开、可核查资料。标注 **[官方]** 者为产品方帮助中心 / 官方博客 / 官方产品页；标注 **[二手]** 者为第三方实测评测、行业博客或学术论文。
- 本文只描述**交互模式与版式规律**，不复制任何受版权保护的界面、图像或角色设计。
- 结论中的比值与占比，除注明外均来自公开资料**文字描述**，非像素级测量；凡无可靠来源者一律写"未验证"，不臆造。

## 二、各竞品逐条

### 1) Duolingo Max（Video Call with Lily / Explain My Answer / Roleplay）
1. **内容 vs 角色占比**：通话（Video Call）以"角色主导"——Lily 的视频画面即主体，学习内容不与之并排；课程内容的呈现转移到通话前后的学习路径与"复盘"环节。[官方]
2. **头像屏幕占比**：公开资料未给出具体百分比（未验证）。
3. **字幕 / 课件切换**：采用"先沉浸对话、后文字复盘"——挂断后提供完整 transcript，并可查看 Lily 每句翻译。[官方]
4. **小屏降级**：Max 仅支持 iOS/Android，官方明确"网页端不可用"，因此无桌面版形态可供参考。[官方]
5. **进入教师/课程**：从学习小径或"练习基地"进入视频通话；Roleplay 作为"支线任务"，点击路径上的角色进入。[官方]
6. **学习状态**：[二手] 通话界面右上角有 XP 计数，达目标后 Lily 收尾；官方未详述通话中的进度 UI（部分未验证）。

### 2) Speak（口语练习）
1. **内容 vs 角色占比**：Immersive Roleplay 以"3D 风格动画角色 + 场景"为主视觉，提示 / 纠错 / 翻译以**流内浮层**叠加在对话之上，而非另开区域。[官方]
2. **头像屏幕占比**：属"场景主角"级别；具体占比未验证。
3. **字幕 / 课件切换**：逐句实时转写（脉冲麦克风环 + 事后自动纠错）；纠错以独立组件呈现并支持 Retry 回退到该轮；翻译可逐句点开，或设置"总是显示"，在 agent 输出结束后流式出现。[官方]
4. **小屏降级**：产品以移动端核心为单栏体验（桌面布局未验证）。
5. **进入教师/课程**：Home 的"语音气泡路径"→点气泡弹出课程卡选择课型；或从 Speak Tutor 标签生成 / 进入自定义课；课程结构为 Learn → Practice → Apply 循环。[官方]
6. **学习状态**：气泡路径本身即状态（蓝色脉冲 = 下一课；填色 = 已完成；勾号 = 全部完成）；个人页展示说话句数、时长、词汇熟练度与 Speak Level。[官方]+[二手]

### 3) Khanmigo（内容驱动辅导）
1. **内容 vs 角色占比**：左侧为**活动导航栏**（Tutor Me、Refresh、Write 等），中央为交互 / 作答区；辅导对话以**右下角图标**唤起的可开合窗口存在，不常驻占版。[二手·学术论文]+[官方]
2. **头像屏幕占比**：无角色头像，Khanmigo 以文字 / 图标形象出现，并可用能量点解锁"帽子"外观。[官方]
3. **字幕 / 课件切换**：语音→文字（点麦克风，出现蓝点与声波，随后显示识别文本）；文字→语音（朗读回复）。[官方]
4. **小屏降级**：移动浏览器功能与桌面一致；但移动 App 为**精简版**（无聊天框、无教师 / 家长工具）；[二手] 反映小屏上"苏格拉底式长对话"偏拥挤。[官方]+[二手]
5. **进入教师/课程**：内容页右下角图标点击开窗；右上角下拉菜单区分 Learner activities / Parent tools / Teacher tools / My documents；教师看 Teacher Dashboard 右侧快捷工具。[官方]
6. **学习状态**：Learner Home 内含 Activities、Chat History；家长 / 教师可查看对话记录。[官方]

### 4) Buddy.ai
1. **内容 vs 角色占比**：机器人角色 Buddy 是固定教学主体，课件以**闪卡、3D 物件、动画、视频片段、声音**形式出现。[官方]
2. **头像屏幕占比**：未验证。
3. **字幕 / 课件切换**：官方流程为 **Presentation → Practice**（先用闪卡 / 3D / 动画 / 声音引入新词，再以语音练习与对话游戏巩固），"呈现词义"与"开口练习"交替。[官方]
4. **小屏降级**：本质为面向低龄（约 3–12 岁）的手机 App。[官方]+[二手]
5. **进入教师/课程**：打开即进入角色引导的课程流，无独立"选老师"环节。[官方]
6. **学习状态**：[二手] 家长仪表盘展示学会词汇、使用频率与粗略流利度。

### 5) HeyGen（数字人讲解版式）
1. **内容 vs 角色占比**：提供四种版式——① 全屏头像；② 左右分屏（头像 + 内容）；③ 画中画 PiP（头像缩到角落、内容占主）；④ 下三分之一 talking-head。[二手]
2. **头像屏幕占比**：分屏时头像区约 **40%**、内容约 60%。[二手]（非官方 API 明示，标注**待核**）；官方 API 支持 16:9 / 9:16 / 1:1 输出比例。[官方]
3. **头像取景**：可选特写 / 半身 / 圆形，位置可选左 / 中 / 右。[二手]
4. **小屏降级**：官方能力面向视频输出比例而非响应式 UI（UI 降级未验证）。
5. **进入教师/课程**：不适用（创作工具）。
6. **学习状态**：不适用。

## 三、提炼出的课堂信息架构

**核心共识**：① "讲解者"与"课件"要么**分区并存**（HeyGen 分屏 ~40/60、Khanmigo 左导航 + 中画布），要么**轮流主导**（Duolingo 通话 = 角色全屏、复盘 = 文字；Buddy 呈现↔练习交替）；② 语音产品普遍采用**实时转写 + 流内纠错 / 翻译浮层**（Speak、Khanmigo、Duolingo transcript）；③ 学习状态普遍放在**持久顶栏或路径节点**（Duolingo XP 计数、Speak 脉冲气泡、Khanmigo Learner Home）。

**推荐三栏（宽屏 ≥1440px）**
- **左栏｜教师头像**：固定宽约 22%–28%。借鉴 HeyGen "讲解者占少数、内容占多数"的取舍，并把头像压得更窄以给课件留空间；头像用半身 / 胸像，以口型 / 呼吸微动区分"安静态"与"说话态"。
- **中栏｜课件**：自适应主区（≥44%），承载闪卡、例句、习题、3D 物件。这是"内容驱动"（Khanmigo 中画布）与"练习交替"（Buddy Presentation→Practice）的落点。
- **右栏｜交互 / 字幕**：约 24%–30%。上半区为实时逐句字幕（可逐句翻译 / 重听），下半区为答题与纠错卡（Retry），对齐 Speak 的"流内纠错 + 复盘组件"。

**三级响应式降级阶梯**
- **宽档（≥1440px）**：三栏全显。
- **中档（1024–1440px）**：右栏收为可开合抽屉，字幕改为中栏底部**字幕条覆盖层**；左栏头像缩为**画中画圆形 / 竖条**（HeyGen PiP 模式）。
- **紧凑档（<1024px）**：单栏聚焦——课件为主，头像降为**下三分之一 talking-head 条**（HeyGen bottom-third），字幕固定为底部单行，答题转为**底部弹层**；坚持"一屏一件事"。

## 四、对本项目「小智学生课堂 V1」的可操作结论

1. **双模并存**：授课 / 讲解阶段用三栏同屏；口语对练阶段可临时放大头像（借鉴 Duolingo 通话），结束后切入"复盘栏"（转录 + 纠错 + 逐句翻译）。
2. **状态可见性**：顶栏常驻"当前单元 + 本课进度 + 连续 / 能量"三类状态，呼应 Speak 脉冲气泡与 Duolingo XP 计数。
3. **进入路径**：沿用"路径节点 → 课程卡 → 进入课堂"（Speak 气泡弹卡），课堂内再提供显式的"切换课程 / 切换教师"入口。
4. **语音反馈**：实时转写 + 流内纠错卡 + 可开关的逐句翻译（Speak 模式），降低低注意力与小屏负担。
5. **降级优先顺序**：先牺牲**头像面积**，再牺牲**右栏（并入抽屉）**，最后才让**课件全屏**——保证"课件永远在场"。

**依赖未验证项**：各产品的头像精确屏幕占比、Duolingo 通话进行中的完整进度 UI，均无官方数值，建议后续以自测截图补证。

## 五、来源清单

**官方来源 [官方]**
- [Duolingo Help Center — What is Duolingo Max?](https://www.duolingo.com/help/what-is-duolingo-max)（[中文版](https://www.duolingo.cn/help/what-is-duolingo-max)）
- [Duolingo Blog — Introducing Duolingo Max（Video Call 与 Roleplay，含挂断后 transcript）](https://blog.duolingo.com/duolingo-max/)
- [Speak Help Center — Free Talk: Immersive Roleplay](https://help.speak.com/en/articles/13182402-free-talk-immersive-roleplay)
- [Speak Help Center — Explore Your New Home Screen](https://help.speak.com/en/articles/11430473-explore-your-new-home-screen)
- [Speak Help Center — What are Tutor Lessons?](https://help.speak.com/en/articles/11966855-what-are-tutor-lessons)
- [Speak 官方站 — Learn / Practice / Apply](https://www.speak.com/)
- [Khan Academy Help Center — Where can I access Khanmigo?](https://support.khanacademy.org/hc/en-us/articles/13982530363533)
- [Khan Academy Help Center — How to Use Speech-to-Text with Khanmigo](https://support.khanacademy.org/hc/en-us/articles/37785606729101)
- [Khan Academy Help Center — Does Khanmigo have a read-aloud / TTS feature?](https://support.khanacademy.org/hc/en-us/articles/23772334788365)
- [Khanmigo for learners（官方博客）](https://blog.khanacademy.org/collegeapps/)
- [Buddy.ai — education 页面（Presentation → Practice 流程）](https://old.buddy.ai/en/education)
- [HeyGen Videos API（输出比例 16:9 / 9:16 / 1:1）](https://raw.githubusercontent.com/api-evangelist/heygen/refs/heads/main/openapi/heygen-videos-api-openapi.yml)

**二手来源 [二手]**
- [duoplanet — Duolingo Video Call（XP 计数、tap-to-speak、transcript）](https://duoplanet.com/duolingo-video-call/)
- [ERIC 学术论文 — An Evaluation of Khanmigo (EJ1435677)：左导航 + 中画布](https://files.eric.ed.gov/fulltext/EJ1435677.pdf)
- [agent-finder.co — Buddy.ai Review 2026](https://agent-finder.co/reviews/buddy-ai)
- [ai-biz-tools.com — HeyGen 上手（分屏头像约 40% / 内容 60%）](https://ai-biz-tools.com/blog/heygen-setup/)
- [fazcomia.aphmedia — HeyGen 版式（全屏 / 分屏 / PiP / bottom-third）](https://fazcomia.aphmedia.com.br/heygen-avatares-ia-producao/)
- [vidmetoo — HeyGen Review（取景与左 / 中 / 右位置）](https://www.vidmetoo.com/heygen-review/)
- [aibesthub.org — Khanmigo 小屏体验偏拥挤](https://www.aibesthub.org/app/khanmigo)
- [Speak Blog — Winter 2025 Release（Speak Level 进度量化）](https://www.speak.com/blog/winter-2025)
- [aipilotsg.com — Speak App Review（单元课型流转）](https://aipilotsg.com/blogs/news/speak-app-review-does-ai-speaking-practice-actually-work)
