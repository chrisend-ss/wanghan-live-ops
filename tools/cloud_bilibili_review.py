import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.bilibili import extract_bvid
from app.bilibili_browser import transcribe_page_media


def fmt_time(seconds: float) -> str:
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="GitHub Actions cloud Bilibili transcription for WangHan reviews."
    )
    parser.add_argument("--request", required=True, help="Path to request JSON")
    args = parser.parse_args()

    request_path = Path(args.request)
    request = json.loads(request_path.read_text(encoding="utf-8"))

    url = str(request["url"]).strip()
    date = str(request.get("date") or "unknown-date").strip()
    model = str(request.get("model") or "small").strip()
    allow_audio = bool(request.get("audio_fallback", True))
    label = str(request.get("label") or "王焓直播录屏").strip()

    bvid = extract_bvid(url)
    out_dir = Path("reviews") / f"{date}_{bvid}"
    out_dir.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(timezone.utc).isoformat()
    status: Dict[str, Any] = {
        "status": "running",
        "date": date,
        "bvid": bvid,
        "url": url,
        "label": label,
        "request_file": str(request_path),
        "started_at": started_at,
        "storage_mode": "cloud-temporary-media",
        "media_committed": False,
    }
    write_json(out_dir / "status.json", status)

    for stale_name in ("ERROR.md", "metadata.json", "transcript.jsonl", "transcript.md"):
        stale = out_dir / stale_name
        if stale.exists():
            stale.unlink()

    try:
        result = transcribe_page_media(
            url=url,
            model_size=model,
            language="zh",
        )
        info = result["info"]
        segments = result["segments"]

        metadata = {
            "date": date,
            "label": label,
            "bvid": info["bvid"],
            "url": url,
            "title": info.get("title"),
            "owner": info.get("owner"),
            "duration_seconds": info.get("duration"),
            "cid": info.get("cid"),
            "source": result["source"],
            "segment_count": len(segments),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "storage_mode": "text-only-after-cloud-processing",
            "notes": [
                "Full video/audio is not committed to GitHub.",
                "If public subtitles are unavailable, audio is downloaded only inside the ephemeral GitHub runner.",
                "Automatic speech recognition may contain mistakes; preserve it as raw evidence until reviewed.",
            ],
        }
        write_json(out_dir / "metadata.json", metadata)

        with (out_dir / "transcript.jsonl").open("w", encoding="utf-8") as f:
            for seg in segments:
                row = {
                    "start_seconds": float(seg["start_seconds"]),
                    "end_seconds": float(seg["end_seconds"]),
                    "speaker": str(seg.get("speaker", "王焓")),
                    "text": str(seg["text"]),
                    "source": result["source"],
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

        lines = [
            f"# {date} 王焓直播录屏转写",
            "",
            f"- BVID: \`{info['bvid']}\`",
            f"- 标题: {info.get('title') or ''}",
            f"- 来源: {result['source']}",
            f"- 时长: {info.get('duration') or ''} 秒",
            f"- 片段数: {len(segments)}",
            "",
            "> 自动转写属于原始证据草稿。唱歌、多人声音、背景音和识别错误需要后续校对，不应直接当作王焓固定口头禅。",
            "",
        ]
        for seg in segments:
            start = fmt_time(float(seg["start_seconds"]))
            end = fmt_time(float(seg["end_seconds"]))
            text = str(seg["text"]).strip()
            if text:
                lines.append(f"**[{start}–{end}] 王焓**  {text}")

        (out_dir / "transcript.md").write_text(
            "\n\n".join(lines) + "\n",
            encoding="utf-8",
        )

        status.update(
            {
                "status": "completed",
                "source": result["source"],
                "segment_count": len(segments),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "needs_audio_fallback": result.get("needs_audio_fallback", False),
            }
        )
        write_json(out_dir / "status.json", status)
        print(f"Completed {bvid}: {len(segments)} segments via {result['source']}")
        return 0

    except Exception as exc:
        status.update(
            {
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        write_json(out_dir / "status.json", status)
        (out_dir / "ERROR.md").write_text(
            "# B站云端处理失败\n\n"
            f"- BVID: \`{bvid}\`\n"
            f"- URL: {url}\n"
            f"- 错误类型: \`{type(exc).__name__}\`\n"
            f"- 错误: {exc}\n\n"
            "## Traceback\n\n"
            "\`\`\`text\n"
            + traceback.format_exc()
            + "\n\`\`\`\n",
            encoding="utf-8",
        )
        print(traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
