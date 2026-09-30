import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Referer": "https://www.bilibili.com/",
}


def extract_bvid(url_or_bvid: str) -> str:
    text = url_or_bvid.strip()
    if re.fullmatch(r"BV[0-9A-Za-z]+", text):
        return text
    match = re.search(r"/video/(BV[0-9A-Za-z]+)", text)
    if not match:
        match = re.search(r"(BV[0-9A-Za-z]+)", text)
    if not match:
        raise ValueError("未识别到 Bilibili BV 号")
    return match.group(1)


def _get_json(url: str, params: Optional[dict] = None) -> dict:
    resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and data.get("code", 0) != 0:
        raise RuntimeError(f"Bilibili API error: {data.get('message')}")
    return data


def get_video_info(url_or_bvid: str) -> Dict[str, Any]:
    bvid = extract_bvid(url_or_bvid)
    payload = _get_json(
        "https://api.bilibili.com/x/web-interface/view",
        {"bvid": bvid},
    )
    data = payload["data"]
    pages = data.get("pages") or []
    if not pages:
        raise RuntimeError("视频没有可读取的分P信息")
    return {
        "bvid": bvid,
        "title": data.get("title") or bvid,
        "owner": (data.get("owner") or {}).get("name"),
        "duration": data.get("duration"),
        "cid": pages[0]["cid"],
        "pages": pages,
    }


def get_public_subtitles(bvid: str, cid: int) -> List[Dict[str, Any]]:
    payload = _get_json(
        "https://api.bilibili.com/x/player/v2",
        {"bvid": bvid, "cid": cid},
    )
    subtitles = ((payload.get("data") or {}).get("subtitle") or {}).get("subtitles") or []
    if not subtitles:
        return []

    candidates = sorted(
        subtitles,
        key=lambda s: (
            0 if "zh" in str(s.get("lan", "")).lower() else 1,
            0 if "ai" not in str(s.get("lan_doc", "")).lower() else 1,
        ),
    )

    url = candidates[0].get("subtitle_url")
    if not url:
        return []
    if url.startswith("//"):
        url = "https:" + url
    body = _get_json(url).get("body") or []

    return [
        {
            "start_seconds": float(item.get("from", 0)),
            "end_seconds": float(item.get("to", item.get("from", 0))),
            "text": str(item.get("content", "")).strip(),
            "speaker": "王焓",
        }
        for item in body
        if str(item.get("content", "")).strip()
    ]


def transcribe_temp_audio(
    video_url: str,
    model_size: str = "small",
    language: str = "zh",
) -> List[Dict[str, Any]]:
    """
    字幕不可用时的可选兜底。
    只在系统临时目录保存压缩音频，识别结束后 TemporaryDirectory 自动删除。
    需要：ffmpeg、yt-dlp，以及可选的 faster-whisper。
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "视频没有公开字幕。若要自动识别音频，请先安装可选依赖："
            "pip install faster-whisper"
        ) from exc

    with tempfile.TemporaryDirectory(prefix="wanghan_bili_") as tmp:
        output_template = str(Path(tmp) / "audio.%(ext)s")
        cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--no-playlist",
            "-f",
            "bestaudio/best",
            "-x",
            "--audio-format",
            "m4a",
            "--audio-quality",
            "7",
            "-o",
            output_template,
            video_url,
        ]
        subprocess.run(cmd, check=True)

        audio_files = list(Path(tmp).glob("audio.*"))
        if not audio_files:
            raise RuntimeError("没有生成临时音频")

        model = WhisperModel(model_size, device="auto", compute_type="int8")
        segments, _ = model.transcribe(
            str(audio_files[0]),
            language=language,
            vad_filter=True,
        )

        result: List[Dict[str, Any]] = []
        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue
            result.append(
                {
                    "start_seconds": float(seg.start),
                    "end_seconds": float(seg.end),
                    "text": text,
                    "speaker": "王焓",
                }
            )
        return result


def import_bilibili(
    url: str,
    allow_temp_audio: bool = False,
    whisper_model: str = "small",
) -> Dict[str, Any]:
    """
    Prefer lightweight Bilibili metadata/subtitles, but never let the public
    metadata API be a single point of failure. Bilibili may return HTTP 412 to
    cloud IPs. In that case, fall through to yt-dlp, which can often recover
    media from the webpage's embedded window.__playinfo__.
    """
    bvid = extract_bvid(url)
    info: Dict[str, Any] = {
        "bvid": bvid,
        "title": bvid,
        "owner": None,
        "duration": None,
        "cid": None,
        "pages": [],
    }
    segments: List[Dict[str, Any]] = []
    source = "none"
    metadata_error: Optional[str] = None

    try:
        info = get_video_info(url)
        segments = get_public_subtitles(info["bvid"], info["cid"])
        if segments:
            source = "bilibili_subtitle"
    except Exception as exc:
        # HTTP 412 and other metadata failures are expected on some cloud IPs.
        # Preserve the error for diagnostics but continue to the media fallback.
        metadata_error = f"{type(exc).__name__}: {exc}"

    if not segments and allow_temp_audio:
        segments = transcribe_temp_audio(
            video_url=url,
            model_size=whisper_model,
        )
        source = "bilibili_temp_audio_whisper"

    return {
        "info": info,
        "segments": segments,
        "source": source,
        "needs_audio_fallback": not bool(segments),
        "metadata_error": metadata_error,
    }
