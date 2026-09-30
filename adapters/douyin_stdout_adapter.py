"""Convert common Douyin collector stdout lines into WangHan Live Ops events.

Usage:
    python collector.py | python adapters/douyin_stdout_adapter.py

This adapter does not include or copy any third-party collector code.
It only parses textual output and sends normalized events to /ingest.
"""

import os
import re
import sys
from typing import Optional

import requests

API_URL = os.getenv("LIVE_OPS_URL", "http://127.0.0.1:8080/ingest")
API_KEY = os.getenv("LIVE_OPS_API_KEY", "change-me")
ROOM_ID = os.getenv("DOUYIN_ROOM_ID", "WANGHAN_ROOM")

RE_CHAT = re.compile(r"【聊天msg】\[(?P<uid>[^\]]+)\](?P<nick>.*?):\s*(?P<content>.*)")
RE_ENTER = re.compile(r"【进场msg】\[(?P<uid>[^\]]+)\](?:\[[^\]]*\])?(?P<nick>.*?)\s+进入了直播间")
RE_LIKE = re.compile(r"【点赞msg】(?P<nick>.*?)\s+点了(?P<count>\d+)个赞")
RE_GIFT = re.compile(r"【礼物msg】(?P<nick>.*?)\s+送出了\s+(?P<gift>.*?)[x×](?P<count>\d+)")
RE_FAN = re.compile(r"【粉丝团msg】\s*恭喜\s+(?P<nick>.*?)\s+成为粉丝团")
RE_STATS = re.compile(r"【统计msg】当前观看人数:\s*(?P<current>[\d.万亿]+),\s*累计观看人数:\s*(?P<total>[\d.万亿]+)")


def cn_number(text: str) -> int:
    text = text.strip()
    multiplier = 1
    if text.endswith("万"):
        multiplier = 10_000
        text = text[:-1]
    elif text.endswith("亿"):
        multiplier = 100_000_000
        text = text[:-1]
    return int(float(text) * multiplier)


def parse_line(line: str) -> Optional[dict]:
    line = line.strip()

    if m := RE_CHAT.search(line):
        return {
            "type": "chat",
            "room_id": ROOM_ID,
            "user_id": m["uid"],
            "nickname": m["nick"].strip(),
            "content": m["content"].strip(),
            "metadata": {"source": "douyin_stdout"},
        }

    if m := RE_ENTER.search(line):
        return {
            "type": "enter",
            "room_id": ROOM_ID,
            "user_id": m["uid"],
            "nickname": m["nick"].strip(),
            "metadata": {"source": "douyin_stdout"},
        }

    if m := RE_LIKE.search(line):
        return {
            "type": "like",
            "room_id": ROOM_ID,
            "nickname": m["nick"].strip(),
            "count": int(m["count"]),
            "metadata": {"source": "douyin_stdout"},
        }

    if m := RE_GIFT.search(line):
        gift = m["gift"].strip()
        return {
            "type": "gift",
            "room_id": ROOM_ID,
            "nickname": m["nick"].strip(),
            "content": gift,
            "count": int(m["count"]),
            "metadata": {"gift_name": gift, "source": "douyin_stdout"},
        }

    if m := RE_FAN.search(line):
        return {
            "type": "fanclub",
            "room_id": ROOM_ID,
            "nickname": m["nick"].strip(),
            "metadata": {"source": "douyin_stdout"},
        }

    if m := RE_STATS.search(line):
        return {
            "type": "audience_stats",
            "room_id": ROOM_ID,
            "metadata": {
                "current_audience": cn_number(m["current"]),
                "total_viewers": cn_number(m["total"]),
                "source": "douyin_stdout",
            },
        }

    return None


def push(event: dict) -> None:
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    response = requests.post(API_URL, json=event, headers=headers, timeout=5)
    response.raise_for_status()


def main() -> None:
    for raw_line in sys.stdin:
        print(raw_line, end="", file=sys.stderr)
        event = parse_line(raw_line)
        if not event:
            continue
        try:
            push(event)
        except Exception as exc:
            print(f"[adapter] push failed: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
