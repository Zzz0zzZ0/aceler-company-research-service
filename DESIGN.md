---
name: "Aceler 背调看板"
description: "以事实、证据和判断为中心的公司背调审阅工作台"
colors:
  ground: "#fafafb"
  surface: "#fff"
  ink: "#16161b"
  muted: "#626368"
  quiet: "#6f7178"
  line: "#e6e8ed"
  line-strong: "#cdd2dc"
  cobalt: "#104eec"
  cobalt-soft: "#eef3ff"
  cobalt-deep: "#0c42cb"
  selection: "#cbd8ff"
  selection-ink: "#071d5e"
  queue-hover: "#f7f9fd"
  bar-track: "#e4e7ed"
  tag-neutral: "#eef0f4"
  tag-neutral-ink: "#4f5158"
  cobalt-muted: "#244fa6"
  coral: "#e36965"
  coral-soft: "#fff2f1"
  coral-deep: "#b33e3a"
  success: "#177245"
  success-soft: "#edf8f2"
  amber: "#a46100"
  amber-soft: "#fff7e7"
typography:
  display:
    fontFamily: '"Avenir Next","PingFang SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif'
    fontSize: "clamp(26px, 3vw, 38px)"
    fontWeight: 700
    lineHeight: 1.16
    letterSpacing: "-0.038em"
  headline:
    fontFamily: '"Avenir Next","PingFang SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif'
    fontSize: "24px"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "-0.04em"
  title:
    fontFamily: '"Avenir Next","PingFang SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif'
    fontSize: "19px"
    fontWeight: 700
    lineHeight: 1.55
    letterSpacing: "-0.02em"
  body:
    fontFamily: '"Avenir Next","PingFang SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif'
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: '"Avenir Next","PingFang SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif'
    fontSize: "12px"
    fontWeight: 600
    lineHeight: 1.55
  mono:
    fontFamily: '"SFMono-Regular",Consolas,"Liberation Mono",monospace'
    fontSize: "17px"
    fontWeight: 750
    lineHeight: 1
spacing:
  header-height: "64px"
  mobile-header-min: "112px"
  content-gutter: "24px"
  queue-gutter: "22px"
  section-gap: "28px"
  row-padding: "13px 22px"
  detail-top: "30px"
  detail-bottom: "48px"
  drawer-width: "400px"
rounded:
  flat: "0"
  control: "5px"
  marker: "2px"
  status-dot: "50%"
  status-pill: "999px"
components:
  run-strip:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.flat}"
    padding: "0 24px"
    height: "64px"
  primary-action:
    backgroundColor: "{colors.cobalt}"
    textColor: "{colors.surface}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "8px 15px"
    height: "38px"
  search-input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "8px 10px 8px 36px"
    height: "40px"
  queue-row-selected:
    backgroundColor: "{colors.cobalt-soft}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.flat}"
    padding: "13px 22px"
  status-tag:
    backgroundColor: "{colors.success-soft}"
    textColor: "{colors.success}"
    typography: "{typography.label}"
    rounded: "{rounded.status-pill}"
    padding: "1px 7px"
    height: "22px"
  report-module:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.flat}"
    padding: "26px 0 28px"
  match-metric:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.flat}"
    padding: "26px 0 28px"
  research-drawer:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.flat}"
    padding: "24px"
    width: "400px"
    height: "calc(100vh - 64px)"
---

# Design System: Aceler 背调看板

## Overview

**Creative North Star: "事实核验编辑台"**

这是一个面向背调操作人员的数字事实核验编辑台：把现代调查新闻编辑台的秩序感与研究简报的证据意识，收束为一张清晰的工作界面。近白画布、近黑正文、单一钴蓝动作通道与发丝分隔线，保持密集信息仍可快速扫描；颜色只在选择、状态和异常处承担语义。

界面以结果审阅为先：顶栏负责运行上下文，左侧公司队列用于扫描和定位，右侧正文让公司定位、角色判断、匹配度、采购方向及来源在同一视野对齐；新建背调作为按需打开的右侧抽屉，保持可达却不抢占阅读宽度。深度主要来自色调分层和结构线，主体没有阴影、纹理、渐变或玻璃质感。

**Key Characteristics:**

- 事实与判断在同一审阅流中分层呈现
- 紧凑顶栏 + 左队列/右正文的并排审阅
- 钴蓝承担选择与主动作，珊瑚仅提示失败/异常
- 发丝线、低圆角、平面主体；抽屉用轻投影表达覆盖关系
- 匹配度与证据置信度始终保持为两个独立指标

## Colors

这是一套冷静的近白、中性墨色与单一高识别度钴蓝组成的审阅调色板；珊瑚、成功绿和琥珀只在状态语义需要时出现。

### Primary

- **审阅钴蓝**：用于选中公司、主要动作、链接、匹配度和进度条；它是界面中唯一持续出现的强调通道。
- **钴蓝选区底**：用于公司队列的选中行和中等级别标签，让状态有背景但不抢正文。
- **深钴蓝悬停态**：只用于主要动作的悬停反馈。
- **选择高亮**：浏览器文本选择使用更浅的蓝色洗底和深蓝文字。

### Semantic Status

- **珊瑚异常**：失败状态与错误提示使用珊瑚及其浅底，保持少量、明确的异常信号。
- **成功绿**：有效状态和高优先级标签使用成功绿及其浅底。
- **琥珀警示**：低优先级采购方向使用琥珀及其浅底。
- **状态文字变体**：中等级别、失败文字和中性标签各自使用对应的深色文字，以维持小字号对比度。

### Neutral

- **近白画布**：页面背景保持无纹理、无渐变的连续平面。
- **表面白**：队列、正文模块和抽屉使用白色表面，与画布形成极轻的层次。
- **编辑墨色**：公司名、正文和关键标签使用高对比近黑。
- **中性灰**：用于次级说明、字段名、运行标签和辅助信息。
- **安静灰**：用于加载状态、输入提示和更弱的辅助文字。
- **发丝灰**：用于分隔线、行边界和底部辅助栏；更强分隔灰只用于标题下沿和抽屉边缘。
- **队列悬停灰**：行悬停时的微弱底色，不改变文字层级。
- **条形轨道灰**：匹配度拆解条的未填充轨道。

**The Single Channel Rule.** 一次只让钴蓝承担选择、链接、进度和主要动作；珊瑚、成功绿和琥珀只表达各自状态，不把它们混作装饰色。

## Typography

**Display Font:** Avenir Next（fallback 为 PingFang SC、Noto Sans CJK SC、Microsoft YaHei 和 sans-serif）
**Body Font:** Avenir Next（同一中文 fallback 链）
**Label/Mono Font:** SFMono-Regular、Consolas、Liberation Mono（用于数字与状态数值）

**Character:** 无衬线字形保持现代、清楚和紧凑；中文正文以稳定的行高承载长段证据，数字切换为等宽字形并启用 tabular figures，让分数、统计和条形数值形成可比的垂直节奏。

### Hierarchy

- **Display**（700，`clamp(26px, 3vw, 38px)`，1.16，字距 `-0.038em`）：当前公司名称，作为详情页的审阅锚点。
- **Headline**（700，24px，1，字距 `-0.04em`）：顶栏中的 Aceler 产品名。
- **Title**（700，19px，继承正文行高）：公司队列标题；模块标题使用 17px、1.3 行高和轻微负字距。
- **Body**（400，14px，1.55）：公司定位、角色依据、采购方向和来源说明；长文本保持自然换行。
- **Label**（600，12px，1.55）：运行批次、统计标签、字段名、状态和辅助元数据。
- **Mono**（750，17px，1）：运行统计和分数；匹配度主数值放大到 36px但仍沿用等宽字形。

**The Two-Register Rule.** 解释性内容留在无衬线正文层；分数、数量和状态数值使用等宽层，始终让匹配度与证据置信度可分别读取。

## Layout

桌面工作区采用并排审阅：固定 64px 顶栏下，左侧公司队列从 330px 起约占 31%，右侧详情填满剩余宽度。顶栏用三列网格放置品牌、运行批次/统计条和“新建背调”主动作；运行数字保持单行并按基线对齐。队列由标题、筛选工具和可滚动行列表组成，详情以 30px 顶部留白和 `clamp(24px, 3.4vw, 54px)` 的水平内边距展开。

详情标题以公司名和两项独立指标开场；主要模块在宽屏下使用两列网格，列间距随视口从 26px 到 58px；每个模块以轻分隔线收尾。来源与输入记录位于底部原生折叠栏，不把辅助信息抬成新的卡片墙。常用间距围绕 8px、12px、18px、24px 和 28px 递进，队列标题和行保留更宽的 22px 内边距以便扫描。

在 1080px 以下，队列扩展到约 38%，详情模块改为单列；在 760px 以下，顶栏变为至少 112px 的粘性上下文条，队列和详情自然堆叠，队列最多占 56vh；抽屉覆盖全宽。480px 以下收紧到 16px 横向内边距并隐藏产品副标题，但保留运行选择和主动作。

## Elevation & Depth

主体遵循平面优先：画布、队列和详情通过近白/白色调差与 1px 结构线分层，不使用卡片阴影。主要动作保留很轻的环境投影以增强可点击性；右侧抽屉使用向左扩散的投影和半透明遮罩明确覆盖关系。抽屉和遮罩的位移/透明度过渡为 180ms，并在减少动态偏好下压缩到即时反馈。

### Shadow Vocabulary

- **主动作环境投影**（`0 4px 12px rgb(16 78 236 / 18%)`）：仅用于顶栏主要动作，避免把所有控件抬离画布。
- **抽屉覆盖投影**（`-18px 0 48px rgb(21 29 49 / 14%)`）：只在抽屉打开时表达它覆盖详情正文。
- **遮罩层**（`rgb(13 20 37 / 22%)`）：降低背景干扰，但不制造玻璃材质。

**The Flat Rest Rule.** 静止的结果审阅界面保持平面；深度只服务于主动作的可点击性和抽屉的覆盖状态。

## Shapes

控件采用克制的 5px 小圆角：运行选择器、搜索/表单输入、主要动作和关闭按钮共享同一控制轮廓。内容模块和行容器不使用完整圆角卡片，结构由 1px 发丝线组织；模块标题前的蓝色标记仅有 2px 圆角。状态圆点为 7px 圆形，状态标签使用胶囊轮廓；选中行以 3px 左侧蓝线和浅蓝底共同表达，而不是只靠颜色。

所有键盘可操作控件共享 3px 可见焦点描边并留出 2px 偏移；输入、选择器和按钮保持至少 38–40px 的可操作高度。抽屉打开时焦点进入公司名字段，Esc 可关闭，减少动态偏好会禁用平滑滚动和位移动画。

## Components

### Buttons

按钮是克制而明确的工作台动作，不承担装饰性品牌展示。

- **Shape:** 5px 控件圆角；顶栏主要按钮最小高度 38px，抽屉内提交按钮最小高度 44px。
- **Primary:** 钴蓝底、白色文字、8px 15px 内边距、750 字重；图标与文字间距 8px。
- **Hover / Focus:** 悬停切换到深钴蓝；键盘焦点使用全局可见焦点描边，禁用/在途状态降低不透明度并显示等待光标。
- **Secondary / Ghost:** 关闭抽屉使用白底、发丝边框的 38px 方形图标按钮；它不与主动作争夺视觉重量。

### Chips (if used)

状态标签是语义标记，不是导航控件。

- **Style:** 22px 最小高度、1px 7px 内边距、999px 胶囊轮廓和 11px/750 标签字形；有效/高优先级为成功底，中等级别为浅蓝底，低优先级为琥珀底，失败为珊瑚底。
- **State:** 未确认或未知值回落到中性灰标签；匹配度与证据置信度各自拥有标签，不合并为一个状态。

### Cards / Containers

详情区域使用连续的平面报告模块，而非圆角卡片网格。

- **Corner Style:** 模块不设圆角；内部结构使用 1px 底部分隔线。
- **Background:** 模块继承白色表面，和近白画布形成低对比层次。
- **Shadow Strategy:** 默认无阴影，遵循 Elevation & Depth 的 Flat Rest Rule。
- **Border:** 只有分隔线和模块标题左侧 3px 蓝色标记；不围成厚重边框。
- **Internal Padding:** 模块使用 26px 顶部、28px 底部留白；标题与内容之间约 13px。

### Inputs / Fields

输入字段保持实用、平整，并与队列筛选共享同一控制语言。

- **Style:** 白色底、1px 强分隔灰边框、5px 圆角、40px 最小高度；搜索框为图标左置并保留 36px 左内边距。
- **Focus:** 3px 可见蓝色焦点描边并偏移 2px，不依赖阴影表达焦点。
- **Error / Disabled:** 失败说明使用珊瑚文字；提交在途时按钮禁用并显示等待状态，字段本身不伪装成可编辑结果。

### Navigation

顶栏是运行上下文条，不是营销导航。

- **Style:** 64px 高、底部 1px 发丝线、品牌/批次/统计/主动作单行排列；统计数字用等宽字形。
- **Default / Hover / Active:** 运行选择器为白底 5px 控件；有效与失败统计各自使用状态色；“新建背调”保持唯一高权重动作。
- **Mobile:** 760px 以下变为至少 112px 的粘性条，运行选择器占据下一行并隐藏“公司”统计，480px 以下隐藏“背调看板”副标题。

### Company Queue Row

公司行是高扫描密度的审阅入口：名称、匹配度、行业/角色关系和有效/失败状态在两行内对齐。

- 默认是白色平面、13px 22px 内边距和底部分隔线；悬停使用极浅底色。
- 选中行使用浅蓝底、左侧 3px 钴蓝线和 `aria-pressed` 语义；状态同时显示形状圆点与文字。
- 搜索和状态筛选只改变队列内容，不重新计算评分或把证据置信度折叠进匹配度。

### Match Metric

匹配度模块是报告中的测量区，不是单一结论卡。

- 主分数以 36px 等宽字形显示，旁边保留等级文字；证据置信度和准入门槛作为独立标签。
- 组件拆解使用 3px 高蓝色填充条和中性轨道，数值与标签沿同一行对齐。
- 评分读取已有验证结果；界面只呈现，不在前端推导或修改。

### Research Drawer

“新建背调”是按需出现的辅助工作面，不占据关闭时的正文宽度。

- 从右侧覆盖，桌面宽度最多 400px，顶部避开 64px 状态栏；移动端覆盖全宽。
- 顶部为标题、说明和 38px 关闭按钮；正文 24px 内边距，表单按 18px 间距堆叠。
- 只保留真实的公司名、官网和 LinkedIn 字段；打开时背景进入 inert，焦点进入公司名，Esc/遮罩点击可关闭。

## Do's and Don'ts

### Do

- **Do** 把公司定位、角色判断、匹配度、采购方向和来源放在同一条详情审阅流里，并保持模块之间的轻分隔。
- **Do** 使用近白画布、白色表面、近黑正文和单一钴蓝动作通道，让高密度信息保持可扫描。
- **Do** 让匹配度与证据置信度各自占据明确位置，分别读取，不合并为一个综合图表。
- **Do** 用文本加圆点/标签表达有效与失败，确保状态不依赖颜色单独传达。
- **Do** 保留键盘焦点、Esc 关闭抽屉、焦点进入公司名以及减少动态偏好等已实现的可访问行为。

### Don't

- **Don't** 添加纸张纹理、印章、复古边框、渐变、玻璃效果或营销式 hero；这个系统属于数字事实核验编辑台。
- **Don't** 把结果审阅堆成圆角卡片墙或统计卡海洋；优先使用连续模块、发丝线和空间节奏。
- **Don't** 用珊瑚、成功绿或琥珀做常规装饰，也不要让多个高饱和色同时争夺主动作。
- **Don't** 合并匹配度和证据置信度，不替前端重新推导评分，也不在界面虚构审批、上传、导出或团队协作能力。
- **Don't** 让新建背调抽屉遮蔽默认审阅路径；它应当可达、可关闭，并只展示现有三个真实输入字段。
