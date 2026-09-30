# B站录像源模式（低本地占用）

王焓直播录像不再默认长期保存在运营电脑。

## 工作方式

```text
直播时
抖音事件 → WangHan Live Ops → SQLite（很小）

下播后
B站录屏链接
   ↓
优先读取公开视频字幕
   ↓
王焓说话时间轴 → SQLite
   ↓
与直播事件 / 手动内容节点合并
   ↓
timeline.csv
```

如果公开视频没有字幕，可选择音频兜底：

```text
B站视频
  ↓
临时压缩音频
  ↓
Whisper 分段识别
  ↓
写入文字
  ↓
临时音频自动删除
```

因此**不会长期保存 screen.mp4 或完整音频**。

## 导入

```bash
python tools/import_bilibili.py \
  --session 20260930-210000-xxxxxx \
  --url "https://www.bilibili.com/video/BVxxxxxxxx/"
```

无字幕时才使用：

```bash
pip install -r requirements-transcribe.txt

python tools/import_bilibili.py \
  --session 20260930-210000-xxxxxx \
  --url "https://www.bilibili.com/video/BVxxxxxxxx/" \
  --audio-fallback
```

音频兜底还需要系统安装 FFmpeg。音频只存在于系统临时目录，程序退出后会清理。

## 最终本地长期保存内容

- SQLite：直播事件、时间节点、字幕/转写
- CSV：合并时间轴（按需导出）
- 不保存完整 B 站视频
- 不保存完整直播录屏
- 不保存长期音频
