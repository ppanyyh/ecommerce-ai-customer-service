# DESIGN.md — 电商客服AI助手 作品集PPT

## 画布与母版
- 画布 1280×720，页面 padding：上下20、左右60。
- A 标题块：0–120px（标题36px bold，左对齐）。
- B 内容区：120–660px（540px 可用）。
- C 页脚条：660–720px：左「电商客服AI助手 · 个人作品集」14px #94A3B8，右页码「NN / 07」14px #94A3B8。
- 封面（P1）允许自定义全屏版式，省略 A/C 区。

## 色彩池（4 hex）
- 主色 BLUE #2563EB（Demo主色）；辅色 LIGHT #EFF4FF（卡片底/浅蓝）；文本 TEXT #1A2333；中性 MUTED #64748B。
- 功能色仅P6图表：通过 #2563EB / 部分通过 #F59E0B / 不通过 #EF4444。
- 渐变方案：封面背景 linear-gradient(135deg,#1D4ED8 0%,#3B82F6 55%,#60A5FA 100%)；卡片头部可用同角度主色渐变。
- 面积分配：常规页主色≤10%（标题条+锚点数字），辅色(浅蓝卡底)≤30%，强调色(封面整页蓝)仅P1；P6图表页辅色约25%。

## 字体
- 全篇：标题 'Microsoft YaHei' bold；正文 'Microsoft YaHei' regular（西文 Segoe UI）。
- 阶梯：封面主标64 / 页面标题36 / 卡片小标题20 bold / 正文16–17 / 截图注13 / 页脚14。
- 锚点数字：56–72 bold（P6「80%→100%」、P7交付物数字）。

## 配图清单（全部为真实项目材料，material来源，已核对）
| 文件 | 内容 | 尺寸 | 用途 |
|---|---|---|---|
| assets/flowchart.png | 业务流程图(2560×3360, 竖版) | 已核对 | P3 L1主视觉 |
| assets/proto_blank.png | Axure空白会话(1912×914) | 已核对 | P5 |
| assets/proto_product.png | Axure商品问答(1912×914) | 已核对 | P5 |
| assets/proto_order.png | Axure退款进度查询(1912×914) | 已核对 | P5 |
| assets/proto_uncovered.png | Axure资料未覆盖(1912×914) | 已核对 | P5 |
| assets/proto_risk.png | Axure风险转人工(1912×914) | 已核对 | P5 |
- 不使用 ImageGen：作品集要求真实项目截图，装饰性图片禁用（用户显式指令优先）。

## 页面映射表
| # | 文件 | 类型 | 角色 | 版式 | 主视觉 | 色彩 | 关键约束 |
|---|---|---|---|---|---|---|---|
| 01 | 01.slide | cover | hero | 全屏蓝渐变+左下大标题 | 渐变色块 | 主色100% | 白字，含角色/工具/数据声明 |
| 02 | 02.slide | content | supporting | 左痛点右目标 | 无图，锚点=编号列表 | 主色≤10% | 4痛点+目标/非目标+3角色 |
| 03 | 03.slide | content | supporting | 左流程图右说明 | flowchart.png h≈500 | 主色≤10% | 流程图文字可读(h500,w381) |
| 04 | 04.slide | content | supporting | 上8功能块下3规则卡 | 无图 | 浅蓝卡底30% | 3规则卡横排 |
| 05 | 05.slide | content | hero | 3+2截图网格 | 5张截图 | 主色≤8% | 每图带13px注 |
| 06 | 06.slide | content | hero | 左图表右问题/修复 | barChart h≈360 | 图表3色 | 100%边界声明必须 |
| 07 | 07.slide | content | supporting | 左交付物右复盘/规划 | 无图，锚点=交付数字 | 主色≤10% | 交付物7项 |
