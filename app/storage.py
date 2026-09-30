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

                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    name TEXT NOT NULL,
                    hypothesis TEXT NOT NULL,
                    target_metric TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'planned',
                    session_id TEXT,
                    control_experiment_id TEXT,
                    variables_json TEXT NOT NULL DEFAULT '{}',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    ended_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_experiments_category_status
                ON experiments(category, status);

                CREATE INDEX IF NOT EXISTS idx_experiments_session
                ON experiments(session_id);

                CREATE TABLE IF NOT EXISTS experiment_results (
                    experiment_id TEXT PRIMARY KEY,
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    conclusion TEXT NOT NULL DEFAULT '',
                    decision TEXT NOT NULL DEFAULT 'inconclusive',
                    next_experiment TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS daily_reviews (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL UNIQUE,
                    review_date TEXT NOT NULL,
                    review_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_daily_reviews_date
                ON daily_reviews(review_date);
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

    def create_experiment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        category = str(payload["category"])
        if hasattr(payload["category"], "value"):
            category = payload["category"].value
        prefix = {
            "visual": "VIS",
            "opening": "OPEN",
            "content": "CONT",
            "audience": "AUD",
            "retention": "RET",
            "clips": "CLIP",
        }.get(category, "OPS")
        experiment_id = f"WH-{prefix}-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
        created_at = _now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO experiments(
                    id, category, name, hypothesis, target_metric, status,
                    session_id, control_experiment_id, variables_json, notes,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, 'planned', ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    category,
                    payload["name"],
                    payload["hypothesis"],
                    payload["target_metric"],
                    payload.get("session_id"),
                    payload.get("control_experiment_id"),
                    json.dumps(payload.get("variables", {}), ensure_ascii=False),
                    payload.get("notes", ""),
                    created_at,
                ),
            )
        return self.get_experiment(experiment_id) or {"id": experiment_id}

    def _hydrate_experiment_row(self, row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        data["variables"] = json.loads(data.pop("variables_json") or "{}")
        return data

    def get_experiment(self, experiment_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM experiments WHERE id=?",
                (experiment_id,),
            ).fetchone()
            if not row:
                return None
            data = self._hydrate_experiment_row(row)
            result = conn.execute(
                "SELECT * FROM experiment_results WHERE experiment_id=?",
                (experiment_id,),
            ).fetchone()
        if result:
            result_data = dict(result)
            result_data["metrics"] = json.loads(result_data.pop("metrics_json") or "{}")
            data["result"] = result_data
        else:
            data["result"] = None
        return data

    def list_experiments(
        self,
        category: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[Dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if category:
            clauses.append("category=?")
            params.append(category)
        if status:
            clauses.append("status=?")
            params.append(status)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM experiments{where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._hydrate_experiment_row(row) for row in rows]

    def start_experiment(self, experiment_id: str, session_id: str) -> Dict[str, Any]:
        started_at = _now_iso()
        with self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE experiments
                SET status='running', session_id=?, started_at=?
                WHERE id=?
                """,
                (session_id, started_at, experiment_id),
            )
            if cur.rowcount == 0:
                raise KeyError(experiment_id)
        return self.get_experiment(experiment_id) or {"id": experiment_id}

    def save_experiment_result(
        self,
        experiment_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not self.get_experiment(experiment_id):
            raise KeyError(experiment_id)
        now = _now_iso()
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT created_at FROM experiment_results WHERE experiment_id=?",
                (experiment_id,),
            ).fetchone()
            created_at = existing["created_at"] if existing else now
            conn.execute(
                """
                INSERT INTO experiment_results(
                    experiment_id, metrics_json, conclusion, decision,
                    next_experiment, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(experiment_id) DO UPDATE SET
                    metrics_json=excluded.metrics_json,
                    conclusion=excluded.conclusion,
                    decision=excluded.decision,
                    next_experiment=excluded.next_experiment,
                    updated_at=excluded.updated_at
                """,
                (
                    experiment_id,
                    json.dumps(payload.get("metrics", {}), ensure_ascii=False),
                    payload.get("conclusion", ""),
                    payload.get("decision", "inconclusive"),
                    payload.get("next_experiment", ""),
                    created_at,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE experiments
                SET status='completed', ended_at=?
                WHERE id=?
                """,
                (now, experiment_id),
            )
        return self.get_experiment(experiment_id) or {"id": experiment_id}

    def save_daily_review(
        self,
        session_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        now = _now_iso()
        review_id = f"REV-{session_id}"
        review_date = now[:10]
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT created_at FROM daily_reviews WHERE session_id=?",
                (session_id,),
            ).fetchone()
            created_at = existing["created_at"] if existing else now
            conn.execute(
                """
                INSERT INTO daily_reviews(
                    id, session_id, review_date, review_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    review_date=excluded.review_date,
                    review_json=excluded.review_json,
                    updated_at=excluded.updated_at
                """,
                (
                    review_id,
                    session_id,
                    review_date,
                    json.dumps(payload, ensure_ascii=False),
                    created_at,
                    now,
                ),
            )
        return self.get_daily_review(session_id) or {"id": review_id}

    def get_daily_review(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM daily_reviews WHERE session_id=?",
                (session_id,),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["review"] = json.loads(data.pop("review_json") or "{}")
        return data

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
