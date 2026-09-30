# Precision V2.1

V2.1 用同场参考逐段验声，输出王焓 / 非王焓 / 不确定。全场自由 speaker clustering 和 dominant-first 主播猜测已移除。
speaker_confidence 描述身份判定，asr_confidence / asr_quality_score 描述文本质量，两者独立。

## 请求

```json
{
  "date": "2026-09-29",
  "url": "https://www.bilibili.com/video/BV1xNas6ZEpB/",
  "model": "large-v3",
  "precision_mode": true,
  "output_suffix": "precise_v2_1",
  "wanghan_reference_ranges": [],
  "wanghan_reference_confirmed": false,
  "speaker_verify_threshold": 0.72,
  "speaker_reject_threshold": 0.45,
  "asr_pass_threshold": 0.72
}
```

至少两段已听音确认的、不重叠的 3–12 秒王焓独白参考，才可设置 confirmed=true。
代码检查至少 90% speech 覆盖和所有参考子窗口之间 cosine >= 0.60。
不一致时整批身份为 uncertain，不自动选择某一声纹簇充当王焓。
同一待验证片段的所有子窗口须达到 verify 门槛才标王焓；全部低于 reject 才标非王焓；其余不确定。
低于 1.5 秒或 speech 覆盖不足 85% 的片段不验声。没有参考不猜主播。

默认阈值尚未经同场人工标签校准，cosine 不等于身份概率；非王焓仅表示不匹配王焓参考，不能推断嘉宾名字。
参考一致性无法验证其真实身份，也不是完整重叠说话检测器。

## ASR 与幻觉

保留 raw text 和模型指标，独立审计 avg_logprob、no_speech_prob、compression_ratio、单字、字速、长音频稀疏文本。
无 avg_logprob/no_speech_prob 时质量不通过；缺少 compression_ratio 会在审计覆盖中注明。
字幕志愿者/校对、分发版权、特定订阅栏目模式可直接拒绝，不靠三条固定整句字符串匹配。
通用重复使用 Unicode 规范化、跨至少 60 秒的三次长文本重复、12 字 n-gram 模板覆盖与文本周期循环。
重复本身标 review，结合模型或字速异常则 rejected。短句如“来宝宝跑车”的自然重复可保持 clear。
待复核重复内容保留原文与证据，但暂不进入自动验证版。

这些规则只能排除可检测异常，不能识别所有错字、合理句型幻觉或漏识别语音；通过不代表逐字正确。

## 产物

`transcript.jsonl` 保留所有返回的 speech，以及 music/noise 时间轴；低质量文字不静默丢弃。
每个 speech 带 speaker_verification、speaker_verification_pass、speaker_similarity、speaker_confidence、
asr_quality_score、asr_confidence、asr_quality_pass、hallucination_status、审计原因。
speaker_cluster 为 null，仅作为旧消费者兼容字段。

`wanghan_verified_transcript.md` 仅输出 speech、王焓验证通过、ASR质量通过、幻觉 clear 的片段，不润色。
quality_report 包含三分类数量/时长、参考状态、ASR通过数、幻觉审计条目、验证版数量/秒数。
status.completed 表示执行完成；quality_status=reference_required 表示身份验收尚未完成；
needs_human_text_review 表示参考可用、自动流程完成，引用仍须人工听音校对。

媒体仅在临时目录，ASR 小片段用完即删除；个人 embedding 仅在内存，通用模型缓存不存个人声纹。
Git/artifact 仅包含 .md/.json/.jsonl；禁止媒体和向量文件。

## 验证

```bash
python -m unittest discover -s tests -v
python tools/audit_precision_transcript.py --input reviews/2026-09-29_BV1xNas6ZEpB_precise_v2/transcript.jsonl --output reviews/2026-09-29_BV1xNas6ZEpB_asr_audit_v21
python tools/cloud_bilibili_review.py --request review_requests/2026-09-29_BV1xNas6ZEpB_precise_v2_1.json
```

audit 工具只重审旧文本，原有身份标注在新结果中失效，不能当成 full audio rerun。
维护技能入口在 `skills/wanghan-live-review/SKILL.md`。
