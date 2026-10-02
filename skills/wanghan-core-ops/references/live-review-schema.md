# 输出与数据结构参考

## 推荐时间轴字段

| 字段 | 说明 |
|---|---|
| session_id | 抖音场次标识 |
| video_time | B站录像时间，例如 01:23:45 |
| live_time | 抖音实际时间（若可校准） |
| visual_variant | 银白 / 黑发 / 玫红 / 其他 |
| content_type | opening / chatting / singing / medical_topic / call / pk / game / story / ceremony / conversion / transition |
| kind | speech / marker / chat / enter / like / follow / gift / fanclub / share / audience_stats |
| content | 王焓话语、节点名称、弹幕或事件描述 |
| audience | 当前在线 |
| exposure | 曝光（若有） |
| entries | 窗口内进房 |
| chats | 窗口内弹幕 |
| likes | 窗口内点赞 |
| follows | 窗口内关注 |
| shares | 窗口内分享 |
| gifts | 窗口内礼物/价值（写清口径） |
| fanclub | 粉丝团变化 |
| interpretation | 运营判断 |
| confidence | high / medium / low |

## 节点表模板

| 节点 | 王焓内容 | 进人 | 留人 | 互动 | 转粉 | 付费 | 运营判断 | 下一次动作 |
|---|---|---:|---:|---:|---:|---:|---|---|
| 开灯 | ... | ... | ... | ... | ... | ... | ... | ... |
| 首唱 | ... | ... | ... | ... | ... | ... | ... | ... |

## 五层漏斗

1. 进人：曝光、进入、进入率、进房速度。
2. 留人：30秒、1分钟、平均停留、当前在线、峰值在线。
3. 互动：弹幕、点赞、分享、互动用户数。
4. 转粉：关注、粉丝团、场后粉丝增量。
5. 付费：礼物、付费人数、付费率、人均付费。

## 节点质量置信度（不等于证据来源等级）

- High：连续数据 + 清晰录像时间点 + 多项指标同步；
- Medium：时间点较清晰，但只有部分指标或较粗采样；
- Low：只有单点截图、主观感受或无法校准的时间。

## 因果措辞

优先使用：
- 同步出现；
- 紧随其后；
- 与...相关；
- 可能是影响因素；
- 需要A/B测试验证。

避免：
- “一定导致”；
- “证明了发色提升”；
- “因为这个环节所以流水上涨”。

## 长期保存

优先保存：
- session metadata；
- events.sqlite3 / JSONL；
- timeline.csv；
- transcript.jsonl / md；
- B站 URL / BV；
- 场次后台导出；
- 视觉版本标签；
- 最终复盘报告。

默认不长期保存：
- 完整 MP4；
- 无必要的原始音频；
- 观众敏感个人资料；
- Cookie、密码、App Secret、长期 token。


原始数据、自动识别与分析结论须分开。所有候选数值列缺字段时填NA和原因，不填0；行中exposure/entries应标人数或次数，speaker_confidence、alignment_error_seconds与source_id分列。High只表示节点匹配较可靠，不表示因果已证实。精确新人留存需要可用观看队列或平台原生口径，在线曲线不能替代。
