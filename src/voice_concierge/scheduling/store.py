"""Local SQLite storage for reminders.

Reminders have to outlive the process. A timer is forgivable to lose on a
restart; "take your tablets at eight every morning" is not, so every reminder is
written to disk as soon as it is made and read back on start.

Nothing here leaves the device and nothing needs a network. The file sits beside
the memory databases under `.local/`, so the privacy centre can account for it
in the same place as everything else stored about the user.
"""

# Standard library
import sqlite3
import threading
import time
from pathlib import Path

# Local
from voice_concierge.local_storage import REMINDER_DATABASE_PATH
from voice_concierge.scheduling.errors import SchedulingError
from voice_concierge.scheduling.types import Kind, Recurrence, Reminder, Schedule

DEFAULT_REMINDER_DB_PATH = REMINDER_DATABASE_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    text             TEXT NOT NULL,
    kind             TEXT NOT NULL,
    due_at           INTEGER NOT NULL,
    recurrence       TEXT NOT NULL,
    interval_seconds INTEGER,
    weekday          INTEGER,
    completed        INTEGER NOT NULL DEFAULT 0,
    created_at       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS reminders_due ON reminders (completed, due_at);
"""


class ReminderStore:
    """Reads and writes reminders in a local SQLite file."""

    def __init__(self, path: Path | str = DEFAULT_REMINDER_DB_PATH) -> None:
        self._path = Path(path)
        if self._path.parent != Path(""):
            self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # check_same_thread=False because the background reminder runner
            # polls from its own thread; every access is serialised by the lock
            # below, so the connection is never used concurrently.
            self._connection = sqlite3.connect(str(self._path), check_same_thread=False)
        except sqlite3.Error as exc:
            raise SchedulingError(f"Could not open {self._path}: {exc}") from exc
        self._lock = threading.Lock()
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.executescript(_SCHEMA)
            self._connection.commit()

    def add(self, reminder: Reminder, *, now: int | None = None) -> Reminder:
        """Store a reminder, returning it with the identifier it was given."""
        created = reminder.created_at or int(now if now is not None else time.time())
        schedule = reminder.schedule
        with self._lock:
            cursor = self._connection.execute(
                "INSERT INTO reminders (text, kind, due_at, recurrence, "
                "interval_seconds, weekday, completed, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
                (
                    reminder.text,
                    reminder.kind,
                    schedule.due_at,
                    schedule.recurrence,
                    schedule.interval_seconds,
                    schedule.weekday,
                    created,
                ),
            )
            self._connection.commit()
        return Reminder(
            text=reminder.text,
            schedule=schedule,
            kind=reminder.kind,
            identifier=cursor.lastrowid,
            created_at=created,
        )

    def get(self, identifier: int) -> Reminder | None:
        """Return one reminder, or None when nothing has that identifier."""
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM reminders WHERE id = ?", (identifier,)
            ).fetchone()
        return None if row is None else _to_reminder(row)

    def list_pending(self) -> tuple[Reminder, ...]:
        """Every reminder still waiting to fire, soonest first."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM reminders WHERE completed = 0 ORDER BY due_at"
            ).fetchall()
        return tuple(_to_reminder(row) for row in rows)

    def list_all(self) -> tuple[Reminder, ...]:
        """Every reminder including those already delivered, soonest first."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM reminders ORDER BY due_at"
            ).fetchall()
        return tuple(_to_reminder(row) for row in rows)

    def reschedule(self, identifier: int, schedule: Schedule) -> None:
        """Move a repeating reminder to its next firing."""
        with self._lock:
            self._connection.execute(
                "UPDATE reminders SET due_at = ?, recurrence = ?, "
                "interval_seconds = ?, weekday = ? WHERE id = ?",
                (
                    schedule.due_at,
                    schedule.recurrence,
                    schedule.interval_seconds,
                    schedule.weekday,
                    identifier,
                ),
            )
            self._connection.commit()

    def update(self, reminder: Reminder) -> Reminder:
        """Replace the editable fields of one stored reminder."""

        if reminder.identifier is None:
            raise SchedulingError("An unsaved reminder cannot be updated.")
        schedule = reminder.schedule
        with self._lock:
            cursor = self._connection.execute(
                "UPDATE reminders SET text = ?, kind = ?, due_at = ?, "
                "recurrence = ?, interval_seconds = ?, weekday = ? "
                "WHERE id = ? AND completed = 0",
                (
                    reminder.text,
                    reminder.kind,
                    schedule.due_at,
                    schedule.recurrence,
                    schedule.interval_seconds,
                    schedule.weekday,
                    reminder.identifier,
                ),
            )
            self._connection.commit()
        if cursor.rowcount == 0:
            raise SchedulingError(
                f"No pending reminder with id {reminder.identifier} is set."
            )
        return reminder

    def complete(self, identifier: int) -> None:
        """Mark a reminder as delivered so it does not fire again."""
        with self._lock:
            self._connection.execute(
                "UPDATE reminders SET completed = 1 WHERE id = ?", (identifier,)
            )
            self._connection.commit()

    def delete(self, identifier: int) -> bool:
        """Remove a reminder. False when there was nothing to remove."""
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM reminders WHERE id = ?", (identifier,)
            )
            self._connection.commit()
        return cursor.rowcount > 0

    def delete_all(self) -> int:
        """Remove every reminder, returning how many were removed."""
        with self._lock:
            cursor = self._connection.execute("DELETE FROM reminders")
            self._connection.commit()
        return cursor.rowcount

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            self._connection.close()


def _to_reminder(row: sqlite3.Row) -> Reminder:
    """Rebuild a reminder from a stored row."""
    recurrence: Recurrence = row["recurrence"]
    kind: Kind = row["kind"]
    return Reminder(
        text=row["text"],
        schedule=Schedule(
            due_at=row["due_at"],
            recurrence=recurrence,
            interval_seconds=row["interval_seconds"],
            weekday=row["weekday"],
        ),
        kind=kind,
        identifier=row["id"],
        completed=bool(row["completed"]),
        created_at=row["created_at"],
    )
