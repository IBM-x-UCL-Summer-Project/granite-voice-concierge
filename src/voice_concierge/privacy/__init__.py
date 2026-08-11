"""Reviewing, correcting and removing what the assistant stores about you."""

from voice_concierge.privacy.centre import PrivacyCentre
from voice_concierge.privacy.disclosure import (
    NOT_RETAINED,
    build_report,
    describe_location,
    format_report,
)
from voice_concierge.privacy.errors import PrivacyError
from voice_concierge.privacy.factory import (
    build_privacy_centre,
    default_database_paths,
)
from voice_concierge.privacy.fakes import FakeMemoryArchive
from voice_concierge.privacy.interfaces import MemoryArchive
from voice_concierge.privacy.types import (
    LAYER_DESCRIPTIONS,
    PrivacyReport,
    StorageLocation,
    StoredMemory,
)

__all__ = [
    "LAYER_DESCRIPTIONS",
    "NOT_RETAINED",
    "FakeMemoryArchive",
    "MemoryArchive",
    "PrivacyCentre",
    "PrivacyError",
    "PrivacyReport",
    "StorageLocation",
    "StoredMemory",
    "build_privacy_centre",
    "build_report",
    "default_database_paths",
    "describe_location",
    "format_report",
]
