---
name: wanghan-live-review
description: Review WangHan livestream recordings and evidence timelines with Precision V2.1 speech separation, reference speaker verification, independent ASR quality gates, and low-storage cloud processing.
---

# 王焓直播复盘

用户是运营，王焓是主播。原话与分析概括分开；转写原文不润色、不补句。
背景音乐/歌唱保留为节目节点，排除于王焓口语语料。内容与后台数据的相关性不能当因果。

## Precision V2.1

使用 `chrisend-ss/wanghan-live-ops` 的 `review_requests/*.json` 请求和云端 Runner。
读取 `status.json`、`quality_report.json` 后再判断能否复用。旧版 completed 不代表 V2.1 质量通过。

1. 从 B站页面媒体接口取得音轨，Runner 临时转换为 16kHz 单声道。
2. inaSpeechSegmenter 分离 speech、music/singing、noise。只有 speech 进入 faster-whisper。
3. 用 large-v3、beam search、`condition_on_previous_text=false`；保留原文、avg_logprob、no_speech_prob、compression_ratio。
4. 对 ASR 独立评分与幻觉审计：字幕/分发模式、跨时间固定重复、近似模板、文本循环、异常字速和模型指标。
   重复本身标 review；与模型/文本异常共现或命中固定字幕类型时标 rejected。
   clear/review/rejected 保存在完整证据中。review/rejected 不进入验证版语料。
5. 直接以同场王焓干净参考逐段验声，不使用全场自由聚类，也不根据时长/首次出现猜主播。
   每段长语音拆为子窗口，结果一致才分类；短句、混音、边界结果保留 uncertain。
6. 仅 `speech + speaker_verification=wanghan + speaker_verification_pass=true + asr_quality_pass=true + hallucination_status=clear`
   写入 `wanghan_verified_transcript.md`。该文件仍是自动证据草稿，引用原话前听音校对。

## 参考门槛

请求包含 `wanghan_reference_ranges` 和 `wanghan_reference_confirmed: true`。
确认必须有真实听音/视频证据，不能从旧聚类标签或 ASR 文字倒推身份。
至少两段不重叠、每段 3–12 秒的同场王焓独白；参考中不能夹入嘉宾、歌唱或背景人声。
代码检查 speech 覆盖率与参考一致性；声纹一致不能证明参考的身份一定是王焓。
没有已确认干净参考时仍可做 ASR/幻觉审计，但全部身份保持 uncertain，质量状态为 reference_required。
用户仅确认当前一段至少 5 秒参考时，可以显式启用 allow_single_reference；报告注明单段证据有限，使用更严格门槛。
用户指出参考有背景伴奏时，启用 speaker_remove_background_music，参考与待验证窗口均先做内存中的人声/伴奏分离。
该处理失败不得静默退回原音；人声分离不能移除所有歌曲人声或其他说话人，仍需身份/文本复核。
历史 BV1xNas6ZEpB 的 47:03–47:55、49:12–49:50 已被审计指出混有多人，不能复用为干净参考。

默认门槛：speaker verify 0.72、reject 0.45、ASR pass 0.72，均是待标注数据校准的启发式门槛。
相似度不是身份准确率，ASR 质量分不是文本正确率。speaker_confidence 与 asr_confidence 各自独立。

## 结果与复盘

读取 `reviews/<date>_<BV>_precise_v2_1/`：

- `status.json`：执行状态 + quality_status，completed 仅表示计算完成。
- `quality_report.json`：三分类数量/时长、参考是否可用、ASR门槛、幻觉审计条目、验证版数量。
- `transcript.jsonl` / `transcript.md`：完整原始证据及审计字段。
- `wanghan_verified_transcript.md`：自动门槛通过的王焓片段，可能为空。
- `audio_zones.jsonl`：说话、音乐、噪声节点。

`run_mode=legacy_text_audit` 只是旧文字重审，不是重新下载/识别/验声。
Workflow artifact 可用于恢复文字结果；产物提交失败与转写失败分别报告。

以共同锚点校准直播事件时间轴，再分析进人、留人、互动、转粉、付费。
报告核心结论、可信度与缺口、关键节点及可执行动作。低置信度/待复核内容不能总结王焓固定口头禅。
后台指标写清口径，整场汇总不能伪装分钟级曲线；视觉换皮实验需控制其他变量。

## 低存储

媒体和语音片段仅在临时 Runner；声纹向量只在本次内存中，结束即释放。
通用模型权重缓存不含个人声纹。Git 与 artifact 只提交文字/JSON/JSONL，禁止音视频、向量文件或媒体目录。
具体请求和字段见仓库 `docs/PRECISION_V21.md`。
