import csv
import io
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from .models import LiveEvent

DATA_DIR = Path(os.getenv("LIVE_OPS_DATA_DIR", "data"))
DB_PATH = DATA_DIR / "wanghan_live_ops.sqlite3"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    room_id TEXT NOT NULL,
                    title TEXT,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    bilibili_url TEXT,
                    bilibili_bvid TEXT,
                    bilibili_title TEXT
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    timestamp TEXT NOT NULL,
                    type TEXT NOT NULL,
                    room_id TEXT NOT NULL,
                    user_id TEXT,
                    nickname TEXT,
                    content TEXT,
                    count INTEGER,
                    value REAL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_events_session_time
                ON events(session_id, timestamp);

                CREATE TABLE IF NOT EXISTS markers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    label TEXT NOT NULL,
                    note TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_markers_session_time
                ON markers(session_id, timestamp);

                CREATE TABLE IF NOT EXISTS transcript_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    start_seconds REAL NOT NULL,
                    end_seconds REAL NOT NULL,
                    text TEXT NOT NULL,
                    speaker TEXT NOT NULL DEFAULT '王焓',
                    source TEXT NOT NULL DEFAULT 'bilibili'
                );

                CREATE INDEX IF NOT EXISTS idx_transcript_session_start
                ON transcript_segments(session_id, start_seconds);
                """
            )

    def start_session(self, room_id: str, title: str = "") -> Dict[str, Any]:
        session_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        started_at = _now_iso()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO sessions(id, room_id, title, started_at) VALUES (?, ?, ?, ?)",
                (session_id, room_id, title, started_at),
            )
        return {
            "id": session_id,
            "room_id": room_id,
            "title": title,
            "started_at": started_at,
        }

    def stop_session(self, session_id: str) -> Dict[str, Any]:
        ended_at = _now_iso()
        with self.connect() as conn:
            conn.execute(
                "UPDATE sessions SET ended_at=? WHERE id=?",
                (ended_at, session_id),
            )
        return {"id": session_id, "ended_at": ended_at}

    def save_event(self, event: LiveEvent, session_id: Optional[str]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO events(
                    session_id, timestamp, type, room_id, user_id, nickname,
                    content, count, value, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    event.timestamp.isoformat(),
                    event.type.value,
                    event.room_id,
                    event.user_id,
                    event.nickname,
                    event.content,
                    event.count,
                    event.value,
                    json.dumps(event.metadata, ensure_ascii=False),
                ),
            )

    def add_marker(
        self,
        session_id: str,
        label: str,
        note: str = "",
        timestamp: Optional[str] = None,
    ) -> Dict[str, Any]:
        ts = timestamp or _now_iso()
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO markers(session_id, timestamp, label, note) VALUES (?, ?, ?, ?)",
                (session_id, ts, label, note),
            )
        return {"id": cur.lastrowid, "timestamp": ts, "label": label, "note": note}

    def attach_bilibili(
        self,
        session_id: str,
        url: str,
        bvid: str,
        title: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET bilibili_url=?, bilibili_bvid=?, bilibili_title=?
                WHERE id=?
                """,
                (url, bvid, title, session_id),
            )

    def replace_transcript(
        self,
        session_id: str,
        segments: Iterable[Dict[str, Any]],
        source: str,
    ) -> int:
        rows = list(segments)
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM transcript_segments WHERE session_id=?",
                (session_id,),
            )
            conn.executemany(
                """
                INSERT INTO transcript_segments(
                    session_id, start_seconds, end_seconds, text, speaker, source
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        session_id,
                        float(row["start_seconds"]),
                        float(row["end_seconds"]),
                        str(row["text"]),
                        str(row.get("speaker", "王焓")),
                        source,
                    )
                    for row in rows
                ],
            )
        return len(rows)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id=?",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    def timeline_csv(self, session_id: str) -> str:
        session = self.get_session(session_id)
        if not session:
            raise KeyError(session_id)

        started = datetime.fromisoformat(session["started_at"])
        rows = []

        with self.connect() as conn:
            for row in conn.execute(
                "SELECT * FROM events WHERE session_id=? ORDER BY timestamp",
                (session_id,),
            ):
                ts = datetime.fromisoformat(row["timestamp"])
                sec = max(0.0, (ts - started).total_seconds())
                meta = json.loads(row["metadata_json"] or "{}")
                rows.append(
                    {
                        "seconds": round(sec, 3),
                        "clock": row["timestamp"],
                        "kind": "event",
                        "type": row["type"],
                        "speaker_or_user": row["nickname"] or "",
                        "content": row["content"] or "",
                        "count": row["count"] if row["count"] is not None else "",
                        "value": row["value"] if row["value"] is not None else "",
                        "extra": json.dumps(meta, ensure_ascii=False),
                    }
                )

            for row in conn.execute(
                "SELECT * FROM markers WHERE session_id=? ORDER BY timestamp",
                (session_id,),
            ):
                ts = datetime.fromisoformat(row["timestamp"])
                sec = max(0.0, (ts - started).total_seconds())
                rows.append(
                    {
                        "seconds": round(sec, 3),
                        "clock": row["timestamp"],
                        "kind": "marker",
                        "type": row["label"],
                        "speaker_or_user": "",
                        "content": row["note"] or "",
                        "count": "",
                        "value": "",
                        "extra": "",
                    }
                )

            for row in conn.execute(
                """
                SELECT * FROM transcript_segments
                WHERE session_id=?
                ORDER BY start_seconds
                """,
                (session_id,),
            ):
                rows.append(
                    {
                        "seconds": round(float(row["start_seconds"]), 3),
                        "clock": "",
                        "kind": "speech",
                        "type": row["source"],
                        "speaker_or_user": row["speaker"],
                        "content": row["text"],
                        "count": "",
                        "value": "",
                        "extra": f'end_seconds={row["end_seconds"]}',
                    }
                )

        rows.sort(key=lambda x: (float(x["seconds"]), x["kind"]))
        stream = io.StringIO()
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "seconds",
                "clock",
                "kind",
                "type",
                "speaker_or_user",
                "content",
                "count",
                "value",
                "extra",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
        return stream.getvalue()


storage = Storage()
