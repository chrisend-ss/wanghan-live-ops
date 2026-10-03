import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from urllib.parse import parse_qs, urlsplit

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
    output_suffix = str(request.get("output_suffix") or "").strip()
    precision_mode = bool(request.get("precision_mode", False))
    hotwords = str(
        request.get("hotwords")
        or "王焓 焓太医 听潮阁 中医 连麦 PK 粉丝团 灯牌 音浪 开灯"
    ).strip()
    wanghan_reference_ranges = request.get("wanghan_reference_ranges") or []

    bvid = extract_bvid(url)
    part = int(parse_qs(urlsplit(url).query).get("p", ["1"])[0])
    if part < 1:
        raise ValueError("分P必须是正整数")
    folder_name = f"{date}_{bvid}" + (f"_p{part}" if part != 1 else "") + (f"_{output_suffix}" if output_suffix else "")
    out_dir = Path("reviews") / folder_name
    out_dir.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(timezone.utc).isoformat()
    status: Dict[str, Any] = {
        "status": "running",
        "date": date,
        "bvid": bvid,
        "part": part,
        "url": url,
        "label": label,
        "request_file": str(request_path),
        "started_at": started_at,
        "storage_mode": "cloud-temporary-media",
        "media_committed": False,
        "precision_mode": precision_mode,
    }
    write_json(out_dir / "status.json", status)

    for stale_name in (
        "ERROR.md",
        "metadata.json",
        "transcript.jsonl",
        "transcript.md",
        "quality_report.json",
        "audio_zones.jsonl",
    ):
        stale = out_dir / stale_name
        if stale.exists():
            stale.unlink()

    try:
        result = transcribe_page_media(
            url=url,
            model_size=model,
            language="zh",
            precision_mode=precision_mode,
            hotwords=hotwords,
            wanghan_reference_ranges=wanghan_reference_ranges,
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
            "part": info.get("part", part),
            "source": result["source"],
            "segment_count": len(segments),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "storage_mode": "text-only-after-cloud-processing",
            "precision_mode": precision_mode,
            "speaker_summary": result.get("speaker_summary"),
            "quality": result.get("quality"),
            "notes": [
                "Full video/audio is not committed to GitHub.",
                "If public subtitles are unavailable, audio is downloaded only inside the ephemeral GitHub runner.",
                "Automatic speech recognition may contain mistakes; preserve it as raw evidence until reviewed.",
                (
                    "Precision mode separates speech from music/singing before ASR and "
                    "clusters speakers; speaker labels still carry confidence and are not ground truth."
                    if precision_mode
                    else "Legacy mode does not reliably separate speakers from background audio."
                ),
            ],
        }
        write_json(out_dir / "metadata.json", metadata)

        with (out_dir / "transcript.jsonl").open("w", encoding="utf-8") as f:
            for seg in segments:
                row = {
                    "start_seconds": float(seg["start_seconds"]),
                    "end_seconds": float(seg["end_seconds"]),
                    "kind": str(seg.get("kind", "speech")),
                    "speaker": str(seg.get("speaker", "说话人_未区分")),
                    "speaker_confidence": str(seg.get("speaker_confidence", "low")),
                    "speaker_cluster": seg.get("speaker_cluster"),
                    "text": str(seg.get("text", "")),
                    "avg_logprob": seg.get("avg_logprob"),
                    "no_speech_prob": seg.get("no_speech_prob"),
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
            (
                "> 精准模式会先把语音与音乐/歌唱分开，再做多人说话人聚类。"
                "标为王焓的片段仍应结合 speaker_confidence 复核。"
                if precision_mode
                else "> 自动转写属于原始证据草稿。唱歌、多人声音、背景音和识别错误需要后续校对。"
            ),
            "",
        ]
        for seg in segments:
            start = fmt_time(float(seg["start_seconds"]))
            end = fmt_time(float(seg["end_seconds"]))
            kind = str(seg.get("kind", "speech"))
            speaker = str(seg.get("speaker", "说话人_未区分"))
            confidence = str(seg.get("speaker_confidence", "low"))
            text = str(seg.get("text", "")).strip()

            if kind == "speech" and text:
                lines.append(
                    f"**[{start}–{end}] {speaker} [{confidence}]**  {text}"
                )
            elif precision_mode and kind == "music":
                lines.append(f"**[{start}–{end}] 背景音乐/歌唱**")

        (out_dir / "transcript.md").write_text(
            "\n\n".join(lines) + "\n",
            encoding="utf-8",
        )

        if precision_mode:
            write_json(
                out_dir / "quality_report.json",
                {
                    "precision_mode": True,
                    "source": result["source"],
                    "speaker_summary": result.get("speaker_summary") or {},
                    "quality": result.get("quality") or {},
                    "wanghan_reference_ranges": wanghan_reference_ranges,
                    "hotwords": hotwords,
                },
            )
            with (out_dir / "audio_zones.jsonl").open("w", encoding="utf-8") as f:
                for zone in result.get("zones") or []:
                    f.write(json.dumps(zone, ensure_ascii=False) + "\n")

        status.update(
            {
                "status": "completed",
                "source": result["source"],
                "segment_count": len(segments),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "needs_audio_fallback": result.get("needs_audio_fallback", False),
                "precision_mode": precision_mode,
                "speaker_summary": result.get("speaker_summary"),
                "quality": result.get("quality"),
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
