import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

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
    part = int(parse_qs(urlparse(url_or_bvid).query).get("p", ["1"])[0])
    if not 1 <= part <= len(pages):
        raise ValueError("视频分P不存在")
    selected = pages[part - 1]
    return {
        "bvid": bvid,
        "title": data.get("title") or bvid,
        "owner": (data.get("owner") or {}).get("name"),
        "duration": selected.get("duration"),
        "cid": selected["cid"],
        "part": part,
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
            "speaker": "说话人_未区分",
            "speaker_confidence": "low",
        }
        for item in body
        if str(item.get("content", "")).strip()
    ]


def _download_audio_via_browser(video_url: str, tmp_dir: str) -> Path:
    """
    Browser fallback for Bilibili anti-bot HTTP 412.

    Strategy:
    1. Open the public video page in real Chromium.
    2. Prefer window.__playinfo__ DASH audio.
    3. If playinfo is unavailable, capture real media requests emitted by the
       Bilibili player and select an audio/media URL.
    4. Download only into the ephemeral runner temp directory.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "浏览器兜底需要 Playwright：pip install playwright && "
            "python -m playwright install chromium"
        ) from exc

    output = Path(tmp_dir) / "browser_audio.m4s"
    captured_media: List[Dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            user_agent=UA,
            locale="zh-CN",
            viewport={"width": 1365, "height": 768},
            extra_http_headers={
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
                "Referer": "https://www.bilibili.com/",
            },
        )
        page = context.new_page()

        def remember_response(response) -> None:
            try:
                url = response.url
                headers = response.headers
                ctype = (headers.get("content-type") or "").lower()
                lower = url.lower()
                looks_media = (
                    response.request.resource_type == "media"
                    or "audio/" in ctype
                    or "video/" in ctype
                    or ".m4s" in lower
                    or ".mp4" in lower
                    or ".flv" in lower
                )
                if looks_media:
                    captured_media.append(
                        {
                            "url": url,
                            "content_type": ctype,
                            "resource_type": response.request.resource_type,
                        }
                    )
            except Exception:
                pass

        page.on("response", remember_response)
        page.goto(video_url, wait_until="domcontentloaded", timeout=90_000)

        # Ask the player to start so Chromium emits actual media requests.
        try:
            page.evaluate(
                """() => {
                    const v = document.querySelector('video');
                    if (v) {
                        v.muted = true;
                        const p = v.play();
                        if (p && p.catch) p.catch(() => {});
                    }
                }"""
            )
        except Exception:
            pass

        # Give the page time to populate embedded playinfo and/or send media.
        page.wait_for_timeout(8_000)

        play_info = page.evaluate(
            "() => window.__playinfo__ ? JSON.parse(JSON.stringify(window.__playinfo__)) : null"
        )

        audio_url = None
        if play_info:
            data = play_info.get("data") or {}
            dash = data.get("dash") or {}
            audio_list = dash.get("audio") or []

            if audio_list:
                best = max(
                    audio_list,
                    key=lambda item: int(item.get("bandwidth") or 0),
                )
                audio_url = (
                    best.get("baseUrl")
                    or best.get("base_url")
                    or ((best.get("backupUrl") or best.get("backup_url") or [None])[0])
                )

            # Legacy playback can expose durl instead of DASH.
            if not audio_url:
                durl = data.get("durl") or []
                if durl:
                    audio_url = durl[0].get("url")

        # Third fallback: use the browser's real player requests. Prefer URLs
        # whose response MIME explicitly says audio, then generic m4s/media.
        if not audio_url and captured_media:
            def media_score(item: Dict[str, Any]) -> int:
                url = item["url"].lower()
                ctype = item["content_type"]
                score = 0
                if "audio/" in ctype:
                    score += 100
                if "audio" in url:
                    score += 40
                if ".m4s" in url:
                    score += 20
                if item["resource_type"] == "media":
                    score += 10
                if "video/" in ctype:
                    score -= 10
                return score

            captured_media.sort(key=media_score, reverse=True)
            audio_url = captured_media[0]["url"]

        if not audio_url:
            debug = {
                "page_title": page.title(),
                "page_url": page.url,
                "captured_media_count": len(captured_media),
                "captured_media_sample": captured_media[:20],
                "has_playinfo": bool(play_info),
            }
            browser.close()
            raise RuntimeError(
                "浏览器已打开 B站页面，但没有取得可用音频/媒体 URL；"
                + json.dumps(debug, ensure_ascii=False)
            )

        cookies = context.cookies()
        cookie_header = "; ".join(
            f"{item['name']}={item['value']}" for item in cookies
        )
        browser.close()

    headers = {
        "User-Agent": UA,
        "Referer": video_url,
        "Origin": "https://www.bilibili.com",
    }
    if cookie_header:
        headers["Cookie"] = cookie_header

    with requests.get(
        audio_url,
        headers=headers,
        stream=True,
        timeout=(20, 120),
    ) as resp:
        resp.raise_for_status()
        with output.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    if not output.exists() or output.stat().st_size < 1024:
        raise RuntimeError("浏览器获取到媒体地址，但临时音频下载为空")

    return output


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
        audio_path: Optional[Path] = None
        try:
            subprocess.run(cmd, check=True)
            audio_files = list(Path(tmp).glob("audio.*"))
            if audio_files:
                audio_path = audio_files[0]
        except subprocess.CalledProcessError:
            # Bilibili frequently returns HTTP 412 to non-browser cloud
            # requests. Fall back to a real Chromium page and its embedded
            # playback state.
            audio_path = _download_audio_via_browser(video_url, tmp)

        if audio_path is None:
            audio_path = _download_audio_via_browser(video_url, tmp)

        model = WhisperModel(model_size, device="auto", compute_type="int8")
        segments, _ = model.transcribe(
            str(audio_path),
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
                    "speaker": "说话人_未区分",
                    "speaker_confidence": "low",
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
