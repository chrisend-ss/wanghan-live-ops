"""Read-only Bilibili intake and explicit Douyin capture normalization.

No browser profiles, cookies, media downloads, backend requests or cloud jobs.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

BV = re.compile(r"BV[0-9A-Za-z]{10}")
METRIC_KEYS = {
    "exposure", "entries", "online", "watchers", "comments", "follow",
    "fanclub", "gift_revenue", "newcomer_eligible60", "newcomer_retained60",
    "official_entry_rate", "official_newcomer60_rate",
}
KINDS = {"window_increment", "cumulative", "instant", "cohort", "official_rate"}


def recording_identity(value: str) -> dict:
    value = value.strip()
    if BV.fullmatch(value):
        bvid, part = value, 1
    else:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
            "bilibili.com", "www.bilibili.com", "m.bilibili.com"
        } or parsed.username or parsed.password:
            raise ValueError("需要完整B站视频链接或BV号；短链接请先在浏览器解析")
        match = re.fullmatch(r"/video/(BV[0-9A-Za-z]{10})/?", parsed.path)
        if not match:
            raise ValueError("未识别到B站视频路径")
        bvid = match.group(1)
        parts = parse_qs(parsed.query).get("p", ["1"])
        if len(parts) != 1 or not re.fullmatch(r"[1-9][0-9]*", parts[0]):
            raise ValueError("分P必须是一个正整数")
        part = int(parts[0])
    return {"bvid": bvid, "part": part,
            "url": f"https://www.bilibili.com/video/{bvid}/" +
                   (f"?p={part}" if part != 1 else "")}


def public_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0",
                                   "Referer": "https://www.bilibili.com/"})
    with urlopen(request, timeout=20) as response:
        result = json.load(response)
    if not isinstance(result, dict) or result.get("code", 0) != 0:
        raise ValueError("B站返回非成功JSON")
    return result


def probe_bilibili(value: str, browser_metadata: dict | None = None) -> dict:
    identity = recording_identity(value)
    result = {**identity, "checked_at": datetime.now(timezone.utc).isoformat(),
              "status": "metadata_pending", "subtitle_status": "not_checked",
              "identity_status": "unverified", "alignment_status": "not_aligned"}
    try:
        if browser_metadata is not None:
            if browser_metadata.get("bvid") != identity["bvid"]:
                raise ValueError("浏览器元数据BV不匹配")
            data = browser_metadata
        else:
            data = public_json("https://api.bilibili.com/x/web-interface/view?" +
                               urlencode({"bvid": identity["bvid"]}))["data"]
        pages = data.get("pages") or []
        if identity["part"] > len(pages):
            raise ValueError("所选分P不存在")
        page = pages[identity["part"] - 1]
        result.update(status="metadata_available", cid=page["cid"],
                      title=data.get("title"), part_title=page.get("part"),
                      duration_seconds=page.get("duration"),
                      publication_timestamp=data.get("pubdate", data.get("publicationTimestamp")),
                      metadata_source="browser_observed" if browser_metadata is not None else "anonymous_api",
                      live_date=None)
    except Exception as exc:
        result.update(status="metadata_unavailable", error_type=type(exc).__name__)
        return result
    if browser_metadata is not None:
        # This input is metadata only; it does not establish a subtitle track.
        return result
    try:
        player = public_json("https://api.bilibili.com/x/player/v2?" +
                             urlencode({"bvid": identity["bvid"], "cid": result["cid"]}))
        tracks = ((player.get("data") or {}).get("subtitle") or {}).get("subtitles") or []
        # Signed subtitle URLs are deliberately not persisted.
        result["subtitle_tracks"] = [{"id": t.get("id"), "language": t.get("lan"),
                                      "label": t.get("lan_doc")} for t in tracks]
        result["subtitle_status"] = "available" if tracks else "not_available_anonymously"
    except Exception as exc:
        result.update(subtitle_status="request_failed", subtitle_error_type=type(exc).__name__)
    return result


def find_reviews(root: Path, identity: dict, cid: int | None = None) -> list:
    candidates = []
    if not root.exists():
        return candidates
    for folder in sorted(root.glob(f"*{identity['bvid']}*")):
        if not folder.is_dir():
            continue
        try:
            status = json.loads((folder / "status.json").read_text(encoding="utf-8"))
            metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
            info = metadata.get("info") or metadata.get("video") or metadata
            if info.get("bvid") != identity["bvid"]:
                raise ValueError("BV不匹配")
            stored_cid = info.get("cid")
            stored_part = info.get("part") or info.get("page")
            if cid is not None:
                part_match = str(stored_cid) == str(cid)
            else:
                part_match = stored_part is not None and int(stored_part) == identity["part"]
            missing = [f for f in ("transcript.jsonl", "quality_report.json", "audio_zones.jsonl")
                       if not (folder / f).is_file()]
            if not missing:
                if not isinstance(json.loads((folder / "quality_report.json").read_text(
                        encoding="utf-8")), dict):
                    raise ValueError("质量报告格式不正确")
                for filename in ("transcript.jsonl", "audio_zones.jsonl"):
                    first = next((line for line in (folder / filename).read_text(
                        encoding="utf-8").splitlines() if line.strip()), None)
                    if first is None or not isinstance(json.loads(first), dict):
                        raise ValueError("转写/分区为空或格式不正确")
            candidates.append({"directory": str(folder), "job_status": status.get("status"),
                               "part_match": part_match, "missing_files": missing,
                               "reuse_candidate": status.get("status") == "completed"
                                                 and part_match and not missing,
                               "quality_review_required": True})
        except (OSError, ValueError, TypeError):
            candidates.append({"directory": str(folder), "reuse_candidate": False,
                               "error": "invalid_or_missing_review_metadata"})
    return candidates


def clean_backend_url(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    allowed = host == "douyin.com" or host.endswith(".douyin.com") or host == "union.bytedance.com"
    if parsed.scheme != "https" or not allowed:
        raise ValueError("来源必须是实际观察到的HTTPS抖音后台页面")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("来源地址不得包含凭据或非标准端口")
    return urlunsplit(("https", host, parsed.path or "/", "", ""))


def aware_time(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("时间必须是含时区的ISO字符串")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("时间必须明确时区")
    return parsed.isoformat()


def metric_value(raw, unit: str) -> tuple:
    if unit not in {"count", "yuan", "seconds", "percent", "ratio"}:
        raise ValueError("指标单位未知")
    if raw is None:
        return None, False
    if isinstance(raw, bool):
        raise ValueError("布尔值不是指标数值")
    approximate = False
    if isinstance(raw, str):
        text = raw.strip().replace(",", "")
        if text in {"", "--", "—", "NA", "N/A"}:
            return None, False
        scale = 1
        if text.endswith("%"):
            if unit != "percent":
                raise ValueError("百分号与单位不一致")
            text = text[:-1]
        if text.endswith(("万", "亿")):
            if unit in {"percent", "ratio"}:
                raise ValueError("缩写与比例单位不一致")
            scale = 10000 if text[-1] == "万" else 100000000
            text, approximate = text[:-1], True
        value = float(text) * scale
    elif isinstance(raw, (int, float)):
        value = raw
    else:
        raise ValueError("不支持的指标数值")
    if not math.isfinite(value) or value < 0:
        raise ValueError("数值必须非负且有限")
    if unit == "percent":
        if value > 100:
            raise ValueError("百分比超出范围")
        value /= 100
    elif unit == "ratio" and value > 1:
        raise ValueError("比例超出范围")
    elif unit == "count" and value != int(value):
        raise ValueError("人数/次数必须是整数")
    if unit == "count":
        value = int(value)
    return value, approximate


def normalize_capture(capture: dict) -> dict:
    """Accept explicitly mapped observations, not arbitrary HAR or backend JSON."""
    if not isinstance(capture, dict) or not isinstance(capture.get("metrics"), list):
        raise ValueError("需要显式映射的metrics列表，不能直接导入HAR")
    captured_at = aware_time(capture.get("captured_at"))
    if captured_at is None:
        raise ValueError("缺少采集时间")
    if capture.get("session_id") is not None and not isinstance(capture["session_id"], str):
        raise ValueError("场次ID必须是字符串或空值")
    rows = []
    for row in capture["metrics"]:
        if not isinstance(row, dict) or row.get("key") not in METRIC_KEYS:
            raise ValueError("指标必须先映射到受支持的运营字段")
        if row.get("kind") not in KINDS:
            raise ValueError("需区分窗口增量、累计、瞬时、队列或官方比例")
        value, approximate = metric_value(row.get("value"), row.get("unit"))
        start, end = aware_time(row.get("window_start")), aware_time(row.get("window_end"))
        if start and end and datetime.fromisoformat(end) < datetime.fromisoformat(start):
            raise ValueError("时间窗口倒置")
        rows.append({"key": row["key"], "raw_label": str(row.get("label") or ""),
                     "raw_value": row.get("value"), "value": value,
                     "unit": "ratio" if row["unit"] == "percent" else row["unit"],
                     "approximate": approximate, "kind": row["kind"],
                     "window_start": start, "window_end": end,
                     "traffic_source": str(row.get("traffic_source") or "unknown"),
                     "population": str(row.get("population") or "unknown"),
                     "definition_verified": row.get("definition_verified") is True})
    available = {r["key"] for r in rows if r["value"] is not None}
    return {"schema_version": "1.0", "example_only": capture.get("example_only") is True,
            "source_url": clean_backend_url(capture["source_url"]),
            "captured_at": captured_at, "session_id": capture.get("session_id"),
            "metrics": rows, "missing_target_fields": sorted(
                {"exposure", "entries", "newcomer_eligible60", "newcomer_retained60"} - available),
            "alignment_status": "not_aligned", "derived_rates": {},
            "status": "observations_normalized_not_validated"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    bili = sub.add_parser("bilibili")
    bili.add_argument("--url", required=True)
    bili.add_argument("--reviews-root", type=Path)
    bili.add_argument("--metadata-input", type=Path,
                      help="已从当前浏览器只读取得的页面元数据JSON；不读取浏览器凭据")
    bili.add_argument("--output", required=True, type=Path)
    backend = sub.add_parser("backend")
    backend.add_argument("--input", required=True, type=Path)
    backend.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "bilibili":
        observed = (json.loads(args.metadata_input.read_text(encoding="utf-8-sig"))
                    if args.metadata_input else None)
        result = probe_bilibili(args.url, observed)
        if args.reviews_root:
            result["existing_reviews"] = find_reviews(args.reviews_root, result, result.get("cid"))
    else:
        result = normalize_capture(json.loads(args.input.read_text(encoding="utf-8-sig")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "status": result["status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
