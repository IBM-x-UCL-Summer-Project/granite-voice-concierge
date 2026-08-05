"""Tests for temporal expression extraction."""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from voice_concierge.memory.temporal_extractor import TemporalExtractor


class TestTemporalExtractor:
    """Test temporal expression extraction to ISO 8601 format."""

    @pytest.fixture
    def reference_time(self):
        """Fixed reference time for consistent testing."""
        return datetime(2026, 7, 16, 12, 0, 0)  # Wednesday, July 16, 2026

    def test_extract_yesterday(self, reference_time):
        """Test extracting 'yesterday'."""
        result = TemporalExtractor.extract_iso_datetime(
            "Met Alice yesterday", reference_time
        )
        assert result == "2026-07-15T12:00:00"

    def test_extract_today(self, reference_time):
        """Test extracting 'today'."""
        result = TemporalExtractor.extract_iso_datetime(
            "Started a new project today", reference_time
        )
        assert result == "2026-07-16T12:00:00"

    def test_extract_tomorrow(self, reference_time):
        """Test extracting 'tomorrow'."""
        result = TemporalExtractor.extract_iso_datetime(
            "Meeting with John tomorrow", reference_time
        )
        assert result == "2026-07-17T12:00:00"

    def test_extract_next_friday(self, reference_time):
        """Test extracting 'next Friday at 3pm' (from Thursday July 16)."""
        result = TemporalExtractor.extract_iso_datetime(
            "I have a meeting next Friday at 3pm", reference_time
        )
        # From Thursday July 16, "next Friday" is the upcoming Friday = July 17 at 3PM
        assert result == "2026-07-17T15:00:00"

    def test_extract_last_monday(self, reference_time):
        """Test extracting 'last Monday' (from Thursday July 16)."""
        result = TemporalExtractor.extract_iso_datetime(
            "Saw the client last Monday", reference_time
        )
        # From Thursday July 16, last Monday is July 13
        assert result == "2026-07-13T12:00:00"

    def test_extract_in_days(self, reference_time):
        """Test extracting 'in X days'."""
        result = TemporalExtractor.extract_iso_datetime(
            "Deadline is in 5 days", reference_time
        )
        assert result == "2026-07-21T12:00:00"

    def test_extract_in_weeks(self, reference_time):
        """Test extracting 'in X weeks'."""
        result = TemporalExtractor.extract_iso_datetime(
            "Conference starts in 2 weeks", reference_time
        )
        assert result == "2026-07-30T12:00:00"

    def test_extract_in_months(self, reference_time):
        """Test extracting 'in X months'."""
        result = TemporalExtractor.extract_iso_datetime(
            "Vacation booked in 3 months", reference_time
        )
        assert result == "2026-10-16T12:00:00"

    def test_extract_days_ago(self, reference_time):
        """Test extracting 'X days ago'."""
        result = TemporalExtractor.extract_iso_datetime(
            "Had coffee with Sarah 3 days ago", reference_time
        )
        assert result == "2026-07-13T12:00:00"

    def test_extract_weeks_ago(self, reference_time):
        """Test extracting 'X weeks ago'."""
        result = TemporalExtractor.extract_iso_datetime(
            "Finished the project 2 weeks ago", reference_time
        )
        assert result == "2026-07-02T12:00:00"

    def test_extract_months_ago(self, reference_time):
        """Test extracting 'X months ago'."""
        result = TemporalExtractor.extract_iso_datetime(
            "Started learning Python 1 month ago", reference_time
        )
        assert result == "2026-06-16T12:00:00"

    def test_iso_8601_format(self, reference_time):
        """Test that output is valid ISO 8601 format."""
        result = TemporalExtractor.extract_iso_datetime(
            "Event yesterday", reference_time
        )
        # Parse to verify format
        parsed = datetime.fromisoformat(result)
        assert isinstance(parsed, datetime)

    def test_case_insensitive(self, reference_time):
        """Test that extraction is case-insensitive."""
        result1 = TemporalExtractor.extract_iso_datetime(
            "Yesterday was great", reference_time
        )
        result2 = TemporalExtractor.extract_iso_datetime(
            "YESTERDAY was great", reference_time
        )
        assert result1 == result2

    def test_no_temporal_expression(self, reference_time):
        """Test text with no temporal expression returns None."""
        result = TemporalExtractor.extract_iso_datetime("I like pizza", reference_time)
        assert result is None

    def test_empty_text(self, reference_time):
        """Test empty text returns None."""
        result = TemporalExtractor.extract_iso_datetime("", reference_time)
        assert result is None

    def test_multiple_temporal_expressions_first_match(self, reference_time):
        """Test that first temporal expression is matched."""
        # "yesterday" should match first
        result = TemporalExtractor.extract_iso_datetime(
            "Yesterday I planned for tomorrow", reference_time
        )
        assert result == "2026-07-15T12:00:00"

    def test_partial_match_in_sentence(self, reference_time):
        """Test extraction from middle of sentence."""
        result = TemporalExtractor.extract_iso_datetime(
            "I met with Alice yesterday and we discussed the project", reference_time
        )
        assert result == "2026-07-15T12:00:00"


class TestTemporalExtractorEdgeCases:
    """Test edge cases and error handling."""

    @pytest.fixture
    def reference_time(self):
        return datetime(2026, 7, 16, 12, 0, 0)

    def test_singular_day(self, reference_time):
        """Test '1 day ago' with singular."""
        result = TemporalExtractor.extract_iso_datetime(
            "Did it 1 day ago", reference_time
        )
        assert result == "2026-07-15T12:00:00"

    def test_words_not_matching(self, reference_time):
        """Test word boundaries - shouldn't match 'yesterday' in other contexts."""
        # This should not match because "yesterdayish" isn't a word boundary
        result = TemporalExtractor.extract_iso_datetime(
            "yesterdayish was not good", reference_time
        )
        assert result is None

    def test_plural_forms(self, reference_time):
        """Test plural forms like 'days', 'weeks', 'months'."""
        result = TemporalExtractor.extract_iso_datetime(
            "It was 3 days ago", reference_time
        )
        assert result == "2026-07-13T12:00:00"

    def test_default_reference_time(self):
        """Test that default reference time is approximately now."""
        result = TemporalExtractor.extract_iso_datetime("Met someone yesterday")
        assert result is not None
        # Should be approximately yesterday's date
        parsed = datetime.fromisoformat(result)
        today = datetime.now(timezone.utc).replace(tzinfo=None)
        delta = (today - parsed).days
        # Should be approximately 1 day (allow for time zone differences)
        assert 0 <= delta <= 2
