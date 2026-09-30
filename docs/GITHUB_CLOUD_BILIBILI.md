# GitHub 云端 B站转写

目标：解决运营电脑不想长期保存录屏、ChatGPT 当前环境又不能直接解码 B站媒体的问题。

## 流程

```text
review_requests/*.json
        ↓ push
GitHub Actions 临时 Runner
        ↓
先尝试 B站公开字幕
        ↓ 没字幕
yt-dlp 临时下载音频
        ↓
faster-whisper 中文转写
        ↓
reviews/<date>_<BV>/
        ├─ metadata.json
        ├─ status.json
        ├─ transcript.jsonl
        └─ transcript.md
        ↓
Runner 销毁 → 临时音频自动消失
```

仓库不会提交完整视频或音频。

## 请求文件

示例：

```json
{
  "date": "2026-09-29",
  "url": "https://www.bilibili.com/video/BVxxxxxxxx/",
  "label": "王焓直播录屏",
  "audio_fallback": true,
  "model": "small"
}
```

把文件写到 `review_requests/` 后，Actions 会自动处理。

## 结果可信度

- `bilibili_subtitle`：来自公开视频字幕；
- `bilibili_temp_audio_whisper`：GitHub Runner 临时音频 + Whisper 自动转写；
- 自动转写必须保留时间码，并在成为“王焓真实口语样本”前进行校对；
- 唱歌歌词、背景人声和连麦对象可能被识别进转写，后续复盘需要区分。
