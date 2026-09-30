from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .transcript_quality import verified_wanghan


def fmt_time(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def write_transcripts(out_dir: Path, rows: List[Dict[str, Any]], *, source: str,
                      date: str, bvid: str, precision: bool) -> None:
    with (out_dir / "transcript.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps({**row, "source": source}, ensure_ascii=False) + "\n")
    lines = [f"# {date} 直播完整证据时间轴", "", f"- BVID: {bvid}", f"- 来源: {source}", "",
             "> 自动转写证据草稿，原文保留。身份验证与文本质量分别审计，需人工校对。", ""]
    for row in rows:
        interval = f"{fmt_time(row['start_seconds'])}-{fmt_time(row['end_seconds'])}"
        if row.get("kind", "speech") == "speech" and row.get("text"):
            label = str(row.get("speaker", "说话人_未区分"))
            audit = (f"身份:{row.get('speaker_confidence', 'low')} / "
                     f"ASR:{row.get('asr_confidence', 'unscored')} / "
                     f"审计:{row.get('hallucination_status', 'unscored')}")
            lines.append(f"**[{interval}] {label} [{audit}]**  {row['text']}")
        elif precision and row.get("kind") == "music":
            lines.append(f"**[{interval}] 背景音乐/歌唱**")
    (out_dir / "transcript.md").write_text("\n\n".join(lines) + "\n", encoding="utf-8")
    if precision:
        selected = verified_wanghan(rows)
        lines = [f"# {date} 王焓验证通过转写", "", f"- BVID: {bvid}",
                 f"- 片段数: {len(selected)}", "",
                 "> 仅保留 speech、王焓验声通过、ASR质量通过、幻觉审计 clear 的片段。"
                 "自动质量门槛不保证逐字准确；原文未润色，仍需听音校对。", ""]
        if not selected:
            lines.append("本次没有片段同时通过全部门槛。详见 quality_report.json 的参考与质量状态。")
        for row in selected:
            lines.append(f"**[{fmt_time(row['start_seconds'])}-{fmt_time(row['end_seconds'])}]**  {row['text']}")
        (out_dir / "wanghan_verified_transcript.md").write_text(
            "\n\n".join(lines) + "\n", encoding="utf-8")


def quality_status(quality: Dict[str, Any], speaker: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "pipeline_version": "precision_v2_1",
        "quality_status": "needs_human_text_review" if speaker.get("reference_usable")
            else "reference_required",
        "speaker_distribution": speaker.get("distribution", {}),
        "asr_quality": quality.get("asr_quality", {}),
        "hallucination_distribution": quality.get("hallucination_audit", {}).get("distribution", {}),
        "verified_transcript": quality.get("verified_transcript", {}),
        "voiceprint_persisted": False,
    }

