> 融合后兼容参考：执行规则以fusion-workflow.md及core-data-analysis.md为准；旧speaker/confidence标签不能确认本人身份或ASR质量。

# 王焓直播运营技术栈参考

## 主仓库

`chrisend-ss/wanghan-live-ops`

## B站精准转写 V2

仓库现已包含：

- `app/precision_audio.py`：speech / music / noise 分段、精准 ASR、speaker clustering；
- `app/bilibili_browser.py`：B站媒体获取与 precision mode；
- `tools/cloud_bilibili_review.py`：生成 speaker/kind/confidence 结构化结果；
- `requirements-transcribe.txt`：精准模式依赖。

核心技术：

- `inaSpeechSegmenter`：把说话与音乐/歌唱/噪声先分开；其设计上会把 singing 标为 music，非常适合避免把歌曲歌词混进主播口播。
- `faster-whisper`：中文 ASR，高精度模式使用更强模型和保守解码。
- `SpeechBrain ECAPA-TDNN`：说话人 embedding。
- `scikit-learn AgglomerativeClustering`：同场录屏内多人说话人聚类。

默认不长期保存完整音频、视频或持久声纹档案。

## 实时事件采集参考

`ape-byte/DouyinBarrageGrab` 可作为弹幕、点赞、关注、礼物、进入直播间、统计、粉丝团、分享等事件的上游来源。只通过 adapter 接入统一 schema。

## 录屏参考

`ihmily/DouyinLiveRecorder` 可用于必须自动录制的场景；有 B站公开录屏时优先不重复长期保存。

## 粉丝趋势

`veyvin/douyin_fans_tracker` 可作为周/月级粉丝趋势参考，不能单独证明某一分钟或某个视觉变量造成涨粉。

## 推荐架构

B站/录屏/实时事件/后台导出
→ 音频精准分层（speech/music/noise）
→ speaker clustering
→ ASR + 时间码
→ adapter + 统一事件 schema
→ timeline
→ 进人 / 留人 / 互动 / 转粉 / 付费分析
→ 下一场动作
