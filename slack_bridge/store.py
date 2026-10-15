"""Bridge state, persisted in SQLite: thread → conversation, and escalations.

One Slack thread = one Dify conversation, so follow-up questions in a thread
keep their context ("Do I need a receipt for that?" after a rideshare question) while a new
top-level question starts fresh. SQLite keeps the mapping across restarts;
Bolt runs listeners on a thread pool, hence the lock.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Escalation:
    """A question the policy did not cover, handed to a human owner."""

    id: str
    channel: str
    thread_ts: str
    asker: str
    question: str
    permalink: str
    escalation_channel: str
    escalation_ts: str
    status: str  # "open" | "answered" | "resolved"
    handled_by: str


class ConversationStore:
    def __init__(self, path: str) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS threads ("
            " channel TEXT NOT NULL,"
            " thread_ts TEXT NOT NULL,"
            " conversation_id TEXT NOT NULL,"
            " PRIMARY KEY (channel, thread_ts))"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS escalations ("
            " id TEXT PRIMARY KEY,"
            " channel TEXT NOT NULL,"
            " thread_ts TEXT NOT NULL,"
            " asker TEXT NOT NULL,"
            " question TEXT NOT NULL,"
            " permalink TEXT NOT NULL,"
            " escalation_channel TEXT NOT NULL DEFAULT '',"
            " escalation_ts TEXT NOT NULL DEFAULT '',"
            " status TEXT NOT NULL DEFAULT 'open',"
            " handled_by TEXT NOT NULL DEFAULT '')"
        )
        self._db.commit()

    def get(self, channel: str, thread_ts: str) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT conversation_id FROM threads WHERE channel = ? AND thread_ts = ?",
                (channel, thread_ts),
            ).fetchone()
        return row[0] if row else None

    def put(self, channel: str, thread_ts: str, conversation_id: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO threads (channel, thread_ts, conversation_id) VALUES (?, ?, ?)"
                " ON CONFLICT (channel, thread_ts) DO UPDATE SET conversation_id = excluded.conversation_id",
                (channel, thread_ts, conversation_id),
            )
            self._db.commit()

    def create_escalation(
        self, id: str, channel: str, thread_ts: str, asker: str, question: str, permalink: str
    ) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO escalations (id, channel, thread_ts, asker, question, permalink)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (id, channel, thread_ts, asker, question, permalink),
            )
            self._db.commit()

    def set_escalation_message(self, id: str, escalation_channel: str, escalation_ts: str) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE escalations SET escalation_channel = ?, escalation_ts = ? WHERE id = ?",
                (escalation_channel, escalation_ts, id),
            )
            self._db.commit()

    def close_escalation(self, id: str, status: str, handled_by: str) -> bool:
        """Mark an open escalation answered/resolved. False if someone got there first."""
        with self._lock:
            cursor = self._db.execute(
                "UPDATE escalations SET status = ?, handled_by = ? WHERE id = ? AND status = 'open'",
                (status, handled_by, id),
            )
            self._db.commit()
        return cursor.rowcount == 1

    def reopen_escalation(self, id: str) -> None:
        with self._lock:
            self._db.execute("UPDATE escalations SET status = 'open', handled_by = '' WHERE id = ?", (id,))
            self._db.commit()

    def get_escalation(self, id: str) -> Escalation | None:
        with self._lock:
            row = self._db.execute(
                "SELECT id, channel, thread_ts, asker, question, permalink,"
                " escalation_channel, escalation_ts, status, handled_by"
                " FROM escalations WHERE id = ?",
                (id,),
            ).fetchone()
        return Escalation(*row) if row else None
