from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse


TARGET_HOST = "union.bytedance.com"

# These are discovery aliases, not promises about the institution backend schema.
# Every standardized value keeps its source path so mappings can be audited.
METRIC_ALIASES: Dict[str, Tuple[str, ...]] = {
    "exposure_uv": (
        "exposure_uv", "expose_uv", "show_uv", "impression_uv", "expo_uv",
    ),
    "viewer_uv": (
        "viewer_uv", "watch_uv", "view_uv", "live_watch_uv", "audience_uv",
    ),
    "viewer_pv": (
        "viewer_pv", "watch_pv", "view_pv", "live_watch_pv",
    ),
    "enter_uv": (
        "enter_uv", "room_enter_uv", "live_enter_uv",
    ),
    "entry_rate": (
        "entry_rate", "enter_rate", "room_enter_rate",
    ),
    "max_online": (
        "max_online", "peak_online", "max_user_count", "max_audience",
    ),
    "avg_online": (
        "avg_online", "average_online", "avg_user_count", "avg_audience",
    ),
    "avg_watch_seconds": (
        "avg_watch_seconds", "avg_watch_duration", "average_watch_duration",
        "avg_stay_time", "average_stay_time",
    ),
    "new_followers": (
        "new_followers", "new_follower", "follow_uv", "new_fans", "fans_inc",
    ),
    "unfollows": (
        "unfollows", "unfollow", "unfollow_uv", "fans_dec",
    ),
    "fanclub_joins": (
        "fanclub_joins", "fanclub_join", "join_fanclub", "club_join_uv",
    ),
    "comments": (
        "comments", "comment_cnt", "comment_count", "chat_cnt",
    ),
    "likes": (
        "likes", "like_cnt", "like_count",
    ),
    "pay_users": (
        "pay_users", "pay_uv", "payer_uv", "gift_user_uv",
    ),
    "gift_value": (
        "gift_value", "gift_amount", "income", "revenue", "gmv",
    ),
}


@dataclass
class PageIdentity:
    page_url: str
    anchor_id: Optional[str]
    room_id: Optional[str]
    app_id: Optional[str]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_page_identity(url: str) -> PageIdentity:
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    def one(key: str) -> Optional[str]:
        values = q.get(key)
        return values[0] if values else None

    return PageIdentity(
        page_url=url,
        anchor_id=one("anchorID"),
        room_id=one("roomID"),
        app_id=one("appId"),
    )


def iter_scalars(value: Any, path: str = "$") -> Iterable[Tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            yield from iter_scalars(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_scalars(child, f"{path}[{index}]")
    else:
        yield path, value


def _path_leaf(path: str) -> str:
    leaf = re.split(r"\.|\[", path)[-1]
    return leaf.rstrip("]")


def discover_metrics(payloads: List[Dict[str, Any]]) -> Dict[str, Any]:
    alias_to_metric: Dict[str, str] = {}
    for metric, aliases in METRIC_ALIASES.items():
        for alias in aliases:
            alias_to_metric[alias.lower()] = metric

    candidates: Dict[str, List[Dict[str, Any]]] = {}
    for item in payloads:
        body = item.get("body")
        if not isinstance(body, (dict, list)):
            continue
        for path, value in iter_scalars(body):
            leaf = _path_leaf(path).lower()
            metric = alias_to_metric.get(leaf)
            if not metric:
                continue
            if not isinstance(value, (int, float, str)) or isinstance(value, bool):
                continue
            candidates.setdefault(metric, []).append(
                {
                    "value": value,
                    "source_url": item.get("url"),
                    "source_path": path,
                }
            )

    standardized: Dict[str, Any] = {}
    for metric, hits in candidates.items():
        # Keep all hits for auditability; first value is only a provisional mapping.
        standardized[metric] = {
            "value": hits[0]["value"],
            "confidence": "provisional",
            "source_url": hits[0]["source_url"],
            "source_path": hits[0]["source_path"],
            "alternatives": hits[1:],
        }
    return standardized


def redact_url(url: str) -> str:
    parsed = urlparse(url)
    # Query strings may contain tokens/signatures. Store endpoint path only.
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def _looks_like_json(content_type: str) -> bool:
    ct = content_type.lower()
    return "json" in ct or "javascript" in ct


def collect(
    page_url: str,
    output_dir: Path,
    cdp_url: Optional[str],
    profile_dir: Optional[Path],
    settle_seconds: int,
) -> Dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is required. Install requirements-institution.txt first."
        ) from exc

    identity = parse_page_identity(page_url)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    room_part = identity.room_id or "unknown-room"
    run_dir = output_dir / f"{stamp}_{room_part}"
    run_dir.mkdir(parents=True, exist_ok=True)

    captured: List[Dict[str, Any]] = []
    response_errors: List[Dict[str, str]] = []

    with sync_playwright() as p:
        browser = None
        context = None
        attached = False

        if cdp_url:
            browser = p.chromium.connect_over_cdp(cdp_url)
            attached = True
            contexts = browser.contexts
            if not contexts:
                raise RuntimeError("CDP browser has no usable context")
            context = contexts[0]
        else:
            profile = profile_dir or Path("data/douyin-institution-profile")
            profile.mkdir(parents=True, exist_ok=True)
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                viewport={"width": 1440, "height": 1000},
            )

        page = None
        for candidate in context.pages:
            if TARGET_HOST in candidate.url and "liveRecordDetail" in candidate.url:
                page = candidate
                break
        if page is None:
            page = context.new_page()

        def on_response(response):
            try:
                parsed = urlparse(response.url)
                host = parsed.netloc.lower()
                if not (host == TARGET_HOST or host.endswith(".bytedance.com")):
                    return
                content_type = response.headers.get("content-type") or ""
                if not _looks_like_json(content_type):
                    return
                body = response.json()
                if not isinstance(body, (dict, list)):
                    return
                captured.append(
                    {
                        "captured_at": utc_now(),
                        "status": response.status,
                        "method": response.request.method,
                        "url": redact_url(response.url),
                        "body": body,
                    }
                )
            except Exception as exc:
                response_errors.append(
                    {
                        "url": redact_url(response.url),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        page.on("response", on_response)

        if page.url != page_url:
            page.goto(page_url, wait_until="domcontentloaded", timeout=90000)
        else:
            page.reload(wait_until="domcontentloaded", timeout=90000)

        # Give the SPA time to load secondary cards/tabs.
        deadline = time.time() + max(5, settle_seconds)
        while time.time() < deadline:
            page.wait_for_timeout(1000)

        final_url = page.url
        title = page.title()

        # DOM text is useful for mapping labels, but never save input values/cookies.
        body_text = page.locator("body").inner_text(timeout=15000)
        (run_dir / "page_text.txt").write_text(body_text, encoding="utf-8")

        with (run_dir / "responses.jsonl").open("w", encoding="utf-8") as f:
            for item in captured:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        standardized = discover_metrics(captured)
        summary = {
            "schema_version": 1,
            "captured_at": utc_now(),
            "source": "douyin_institution_live_record_detail",
            "page": {
                "requested_url": page_url,
                "final_url": final_url,
                "title": title,
                "anchor_id": identity.anchor_id,
                "room_id": identity.room_id,
                "app_id": identity.app_id,
            },
            "capture": {
                "response_count": len(captured),
                "response_error_count": len(response_errors),
                "mode": "cdp_attach" if attached else "persistent_profile",
            },
            "metrics": standardized,
            "response_errors": response_errors,
            "notes": [
                "Metric mappings are provisional until verified against visible institution labels.",
                "Stored response URLs exclude query strings to avoid persisting tokens/signatures.",
                "Browser cookies, passwords and request headers are not written to output files.",
                "Raw output is local under data/ and is gitignored by default.",
            ],
        }
        (run_dir / "standardized.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if not attached:
            context.close()
        elif browser:
            # Disconnect only; do not close the user's browser.
            browser.close()

    return {
        "run_dir": str(run_dir),
        "room_id": identity.room_id,
        "responses": len(captured),
        "metrics": list(standardized.keys()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect aggregate metrics from an authorized Douyin institution live detail page."
    )
    parser.add_argument("--url", required=True, help="Authorized liveRecordDetail URL")
    parser.add_argument(
        "--output-dir",
        default="data/institution",
        help="Local gitignored output directory",
    )
    parser.add_argument(
        "--cdp-url",
        default=None,
        help="Attach to an already-running Chromium debug endpoint, e.g. http://127.0.0.1:9222",
    )
    parser.add_argument(
        "--profile-dir",
        default="data/douyin-institution-profile",
        help="Persistent Playwright profile used when CDP attach is unavailable",
    )
    parser.add_argument(
        "--settle-seconds",
        type=int,
        default=15,
        help="Seconds to wait for SPA data calls after page load",
    )
    args = parser.parse_args()

    result = collect(
        page_url=args.url,
        output_dir=Path(args.output_dir),
        cdp_url=args.cdp_url,
        profile_dir=Path(args.profile_dir) if args.profile_dir else None,
        settle_seconds=args.settle_seconds,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
