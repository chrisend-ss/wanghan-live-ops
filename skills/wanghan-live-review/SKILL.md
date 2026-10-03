---
name: wanghan-live-review
description: 王焓直播复盘与核心运营融合入口：接收B站URL/BV、已登录Chrome后台、转写、CSV/Excel或方案，统一内容可信度审查、时间校准、五层漏斗、八模块判断与下一轮实验；默认不写主播话术。
---

# 王焓直播复盘

本技能是“新分支核心运营思路”的兼容入口，内置完整融合方法。调用本技能即可完成可信复盘与核心运营分析，无需再调用另一个技能或重复提交资料。

执行前读 [融合协议](references/fusion-workflow.md)。该协议优先于旧V2标签和历史报告的推断。用户是运营，王焓是主播，交付服务运营决策。

## 按输入推进

- B站URL/BV：按 [数据入口](references/source-acquisition.md) 核对分P/CID与覆盖，先查可复用结果；按 [内置复盘方法](references/live-review-method.md) 审查说话、音乐、噪声、说话人身份与ASR质量。无需先下载完整视频。
- 已登录Chrome抖音后台或机构版：核对账号/场次，实际只读采集汇总、分钟趋势、流量来源与转化；单位、窗口、人群逐项验证。浏览器工具未连接时不假称已读取。
- 已有转写/表格/节点：审查后复用，与后台用至少两个独立锚点对齐；未核验原话不纳入本人语料。
- 仅后台或截图：按真实粒度分析，不编造录像节点或精确留存。
- 仅视觉、活动、选题或切片方案：做对应模块实验设计；未运行标待验证。
- 多场：先建立各场卡片，口径和来源可比后再比较。

## 同一份报告

按 [统一分析与实验模板](references/core-data-analysis.md) 输出模块/运营功能、四项可信度、节点表、进房→留人→互动→转粉/关系→付费漏斗、变量、核心指标、验证方法、结论标准和下一步。默认八模块顺序见融合协议；策略判断必须建立在数据上，未取得数据只写假设。

指标定义读 [measurement.md](references/measurement.md)，时间轴与事件字段读 [live-review-schema.md](references/live-review-schema.md)，运营审查读 [operations-department.md](references/operations-department.md)。历史 [output-schema.md](references/output-schema.md) 的confidence只作兼容字段，不能代替独立的身份、ASR和对齐可信度。

两个技能同时被@时，共用同一场次、转写、节点、数据和实验台账，只执行一次、只输出一份报告。默认低存储，保存必要文字与数据；不长期留完整音视频或声纹，不保存认证信息。实际工具和任务状态逐次核验；包更新不意味着重新转写已完成或流量效果已提升。
