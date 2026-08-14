"""Assemble the reminder stack over the local database."""

# Standard library
from pathlib import Path

# Local
from voice_concierge.scheduling.service import ReminderService
from voice_concierge.scheduling.store import DEFAULT_REMINDER_DB_PATH, ReminderStore


def build_reminder_service(
    *, database_path: Path | str = DEFAULT_REMINDER_DB_PATH
) -> ReminderService:
    """Build a ReminderService over the local reminder database."""
    return ReminderService(ReminderStore(database_path))
