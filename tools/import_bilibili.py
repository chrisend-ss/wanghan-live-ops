import argparse

from app.bilibili import import_bilibili
from app.storage import storage


def main() -> None:
    parser = argparse.ArgumentParser(
        description="从 Bilibili 录像提取王焓说话文字，不长期保存视频。"
    )
    parser.add_argument("--url", required=True, help="Bilibili 视频 URL 或 BV 号")
    parser.add_argument("--session", required=True, help="本地直播场次 ID")
    parser.add_argument(
        "--audio-fallback",
        action="store_true",
        help="无公开字幕时临时下载压缩音频并 Whisper 识别；完成后自动删除",
    )
    parser.add_argument("--model", default="small", help="faster-whisper 模型")
    args = parser.parse_args()

    result = import_bilibili(
        args.url,
        allow_temp_audio=args.audio_fallback,
        whisper_model=args.model,
    )
    info = result["info"]
    storage.attach_bilibili(
        args.session,
        args.url,
        info["bvid"],
        info["title"],
    )

    segments = result["segments"]
    if segments:
        count = storage.replace_transcript(
            args.session,
            segments,
            source=result["source"],
        )
        print(f"已保存 {count} 条说话/字幕片段")
        print(f"来源：{result['source']}")
    else:
        print("该视频当前没有可读取的公开字幕。")
        print("可加 --audio-fallback，仅临时下载音频识别，完成后自动删除。")

    print(f"视频：{info['title']}")
    print(f"BV：{info['bvid']}")


if __name__ == "__main__":
    main()
