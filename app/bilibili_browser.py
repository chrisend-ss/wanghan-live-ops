from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests

from .bilibili import extract_bvid

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/154.0.0.0 Safari/537.36"
)

PAGE_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
}


def _raw_decode_assignment(html: str, variable: str) -> Optional[dict]:
    patterns = [
        f"window.{variable}",
        f"window['{variable}']",
        f'window["{variable}"]',
    ]
    start = -1
    marker = ""
    for candidate in patterns:
        start = html.find(candidate)
        if start >= 0:
            marker = candidate
            break
    if start < 0:
        return None

    eq = html.find("=", start + len(marker))
    if eq < 0:
        return None

    payload = html[eq + 1 :].lstrip()
    try:
        value, _ = json.JSONDecoder().raw_decode(payload)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None


def _metadata_from_initial(initial: Optional[dict], bvid: str) -> Dict[str, Any]:
    initial = initial or {}
    video = initial.get("videoData") or initial.get("videoInfo") or {}
    pages = video.get("pages") or []
    cid = video.get("cid")
    if not cid and pages:
        cid = pages[0].get("cid")

    owner = (
        (initial.get("upData") or {}).get("name")
        or video.get("owner", {}).get("name")
        or video.get("upName")
    )

    return {
        "bvid": video.get("bvid") or bvid,
        "title": video.get("title") or bvid,
        "owner": owner,
        "duration": video.get("duration"),
        "cid": cid,
        "pages": pages,
    }


def _extract_media_candidates(playinfo: dict) -> List[Tuple[str, str, int]]:
    data = playinfo.get("data") if isinstance(playinfo.get("data"), dict) else playinfo
    if not isinstance(data, dict):
        return []

    candidates: List[Tuple[str, str, int]] = []
    dash = data.get("dash") or {}

    audios = list(dash.get("audio") or [])
    dolby = dash.get("dolby") or {}
    if isinstance(dolby, dict):
        audios.extend(dolby.get("audio") or [])

    for item in audios:
        if not isinstance(item, dict):
            continue
        bandwidth = int(item.get("bandwidth") or 0)
        urls = []
        for key in ("baseUrl", "base_url"):
            if item.get(key):
                urls.append(item[key])
        urls.extend(item.get("backupUrl") or item.get("backup_url") or [])
        for media_url in urls:
            if media_url:
                candidates.append((str(media_url), "audio", bandwidth))

    # Some logged-out/low-quality responses use a combined stream.
    for durl in data.get("durl") or []:
        if not isinstance(durl, dict):
            continue
        if durl.get("url"):
            candidates.append((str(durl["url"]), "combined", int(durl.get("size") or 0)))
        for backup in durl.get("backup_url") or []:
            candidates.append((str(backup), "combined", 0))

    # Prefer highest-bandwidth dedicated audio first.
    candidates.sort(key=lambda x: (0 if x[1] == "audio" else 1, -x[2]))
    return candidates


def _page_state_via_requests(url: str) -> Tuple[dict, dict, List[dict], str]:
    response = requests.get(url, headers=PAGE_HEADERS, timeout=30)
    response.raise_for_status()
    html = response.text
    initial = _raw_decode_assignment(html, "__INITIAL_STATE__") or {}
    playinfo = _raw_decode_assignment(html, "__playinfo__") or {}
    return initial, playinfo, [], "http_page"


def _page_state_via_browser(url: str) -> Tuple[dict, dict, List[dict], str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is required for browser fallback") from exc

    captured: List[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent=UA,
            locale="zh-CN",
            viewport={"width": 1440, "height": 900},
            extra_http_headers={
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
            },
        )
        page = context.new_page()

        def on_response(response):
            url_text = response.url
            if "playurl" not in url_text:
                return
            try:
                if "application/json" in (response.headers.get("content-type") or ""):
                    body = response.json()
                    if isinstance(body, dict):
                        captured.append(body)
            except Exception:
                pass

        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(8000)

        initial = page.evaluate("() => window.__INITIAL_STATE__ || null") or {}
        playinfo = page.evaluate("() => window.__playinfo__ || null") or {}

        if not initial or not playinfo:
            html = page.content()
            initial = initial or _raw_decode_assignment(html, "__INITIAL_STATE__") or {}
            playinfo = playinfo or _raw_decode_assignment(html, "__playinfo__") or {}

        # If the page loaded a playurl response after hydration, use it when page-level playinfo is absent.
        if not playinfo:
            for body in captured:
                data = body.get("data")
                if isinstance(data, dict) and (data.get("dash") or data.get("durl")):
                    playinfo = {"data": data}
                    break

        cookies = context.cookies()
        browser.close()
        return initial, playinfo, cookies, "chromium_page"


def get_page_media(url: str) -> Dict[str, Any]:
    bvid = extract_bvid(url)
    errors: List[str] = []

    try:
        initial, playinfo, cookies, method = _page_state_via_requests(url)
        candidates = _extract_media_candidates(playinfo)
        if candidates:
            return {
                "info": _metadata_from_initial(initial, bvid),
                "playinfo": playinfo,
                "cookies": cookies,
                "method": method,
                "candidates": candidates,
            }
        errors.append("HTTP page loaded but contained no usable playinfo media.")
    except Exception as exc:
        errors.append(f"HTTP page fallback failed: {type(exc).__name__}: {exc}")

    try:
        initial, playinfo, cookies, method = _page_state_via_browser(url)
        candidates = _extract_media_candidates(playinfo)
        if not candidates:
            raise RuntimeError("Browser page contained no usable playinfo media.")
        return {
            "info": _metadata_from_initial(initial, bvid),
            "playinfo": playinfo,
            "cookies": cookies,
            "method": method,
            "candidates": candidates,
        }
    except Exception as exc:
        errors.append(f"Browser fallback failed: {type(exc).__name__}: {exc}")

    raise RuntimeError(" | ".join(errors))


def _download_candidate(
    candidate_url: str,
    destination: Path,
    page_url: str,
    cookies: List[dict],
) -> None:
    if candidate_url.startswith("//"):
        candidate_url = "https:" + candidate_url

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": UA,
            "Referer": page_url,
            "Origin": "https://www.bilibili.com",
        }
    )
    for cookie in cookies:
        name = cookie.get("name")
        value = cookie.get("value")
        domain = cookie.get("domain")
        if name and value:
            session.cookies.set(name, value, domain=domain or ".bilibili.com")

    with session.get(candidate_url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with destination.open("wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)


def _ensure_audio_decodable(media_path: Path, tmp: Path) -> Path:
    converted = tmp / "audio_for_whisper.m4a"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(media_path),
        "-vn",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        str(converted),
    ]
    subprocess.run(
        cmd,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return converted


def transcribe_page_media(
    url: str,
    model_size: str = "small",
    language: str = "zh",
) -> Dict[str, Any]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper is required") from exc

    media = get_page_media(url)

    with tempfile.TemporaryDirectory(prefix="wanghan_bili_page_") as tmp_dir:
        tmp = Path(tmp_dir)
        last_error: Optional[Exception] = None
        source_path: Optional[Path] = None
        source_kind = ""

        for index, (candidate_url, kind, _) in enumerate(media["candidates"][:8]):
            try:
                suffix = ".m4s" if kind == "audio" else ".mp4"
                candidate_path = tmp / f"source_{index}{suffix}"
                _download_candidate(
                    candidate_url,
                    candidate_path,
                    url,
                    media["cookies"],
                )
                if candidate_path.stat().st_size < 1024:
                    raise RuntimeError("Downloaded media is unexpectedly small")
                source_path = candidate_path
                source_kind = kind
                break
            except Exception as exc:
                last_error = exc

        if source_path is None:
            raise RuntimeError(f"All page media candidates failed: {last_error}")

        try:
            audio_path = _ensure_audio_decodable(source_path, tmp)
        except Exception:
            audio_path = source_path

        model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
            cpu_threads=4,
        )
        segments_iter, detected = model.transcribe(
            str(audio_path),
            language=language,
            vad_filter=True,
            beam_size=3,
        )

        segments: List[Dict[str, Any]] = []
        for seg in segments_iter:
            text = seg.text.strip()
            if not text:
                continue
            segments.append(
                {
                    "start_seconds": float(seg.start),
                    "end_seconds": float(seg.end),
                    "text": text,
                    "speaker": "王焓",
                }
            )

        return {
            "info": media["info"],
            "segments": segments,
            "source": f"bilibili_{media['method']}_{source_kind}_whisper",
            "needs_audio_fallback": False,
            "detected_language": getattr(detected, "language", language),
        }
