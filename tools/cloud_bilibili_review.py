import argparse
import json
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
from app.review_output import quality_status, write_transcripts


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
    label = str(request.get("label") or "王焓直播录屏").strip()
    output_suffix = str(request.get("output_suffix") or "").strip()
    precision_mode = bool(request.get("precision_mode", False))
    hotwords = str(
        request.get("hotwords")
        or "王焓 焓太医 听潮阁 中医 连麦 PK 粉丝团 灯牌 音浪 开灯"
    ).strip()
    wanghan_reference_ranges = request.get("wanghan_reference_ranges") or []
    reference_confirmed = request.get("wanghan_reference_confirmed") is True

    bvid = extract_bvid(url)
    folder_name = f"{date}_{bvid}" + (f"_{output_suffix}" if output_suffix else "")
    out_dir = Path("reviews") / folder_name
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
        "precision_mode": precision_mode,
        "pipeline_version": "precision_v2_1" if precision_mode else "legacy",
        "voiceprint_persisted": False,
    }
    write_json(out_dir / "status.json", status)

    for stale_name in (
        "ERROR.md",
        "metadata.json",
        "transcript.jsonl",
        "transcript.md",
        "quality_report.json",
        "audio_zones.jsonl",
        "wanghan_verified_transcript.md",
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
            reference_confirmed=reference_confirmed,
            speaker_verify_threshold=float(request.get("speaker_verify_threshold", 0.72)),
            speaker_reject_threshold=float(request.get("speaker_reject_threshold", 0.45)),
            asr_pass_threshold=float(request.get("asr_pass_threshold", 0.72)),
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
            "precision_mode": precision_mode,
            "speaker_summary": result.get("speaker_summary"),
            "quality": result.get("quality"),
            "notes": [
                "Full video/audio is not committed to GitHub.",
                "If public subtitles are unavailable, audio is downloaded only inside the ephemeral GitHub runner.",
                "Automatic speech recognition may contain mistakes; preserve it as raw evidence until reviewed.",
                (
                    "Precision mode separates speech from music/singing before ASR and "
                    "verifies WangHan against confirmed same-recording references; "
                    "speaker confidence and ASR quality are independent gates."
                    if precision_mode
                    else "Legacy mode does not reliably separate speakers from background audio."
                ),
            ],
        }
        write_json(out_dir / "metadata.json", metadata)

        write_transcripts(out_dir, segments, source=result["source"], date=date,
                          bvid=bvid, precision=precision_mode)

        if precision_mode:
            write_json(
                out_dir / "quality_report.json",
                {
                    "precision_mode": True,
                    "pipeline_version": "precision_v2_1",
                    "source": result["source"],
                    "speaker_summary": result.get("speaker_summary") or {},
                    "speaker_verification": result.get("speaker_summary") or {},
                    "quality": result.get("quality") or {},
                    "wanghan_reference_ranges": wanghan_reference_ranges,
                    "wanghan_reference_confirmed": reference_confirmed,
                    "voiceprint_persisted": False,
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
                "quality": {key: value for key, value in (result.get("quality") or {}).items()
                            if key != "hallucination_audit"},
            }
        )
        if precision_mode:
            status.update(quality_status(result.get("quality") or {},
                                         result.get("speaker_summary") or {}))
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
            f"- BVID: `{bvid}`\n"
            f"- URL: {url}\n"
            f"- 错误类型: `{type(exc).__name__}`\n"
            f"- 错误: {exc}\n\n"
            "## Traceback\n\n"
            "```text\n"
            + traceback.format_exc()
            + "\n```\n",
            encoding="utf-8",
        )
        print(traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

