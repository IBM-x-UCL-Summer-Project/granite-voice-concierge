"""Extract and normalize temporal expressions to ISO 8601 format."""

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from dateutil import parser as dateutil_parser
from dateutil.relativedelta import relativedelta


class TemporalExtractor:
    """Extract temporal expressions from text and convert to ISO 8601."""

    # Common relative date patterns
    RELATIVE_PATTERNS = {
        r"\byesterday\b": lambda now: now - timedelta(days=1),
        r"\btoday\b": lambda now: now,
        r"\btomorrow\b": lambda now: now + timedelta(days=1),
        # "next Friday", "last Monday", etc.
        r"\b(next|last)\s+(monday|tuesday|wednesday|thursday|friday"
        r"|saturday|sunday)\b": None,
        # "in X days/weeks/months"
        r"\bin\s+(\d+)\s+(day|week|month|year)s?\b": None,
        # "X days/weeks/months ago"
        r"(\d+)\s+(day|week|month|year)s?\s+ago\b": None,
    }

    @staticmethod
    def extract_iso_datetime(
        text: str, reference_time: Optional[datetime] = None
    ) -> Optional[str]:
        """
        Extract and normalize temporal expression to ISO 8601 format.

        Args:
            text: Text containing temporal expression
            reference_time: Reference time for relative dates (default: now UTC)

        Returns:
            ISO 8601 string (YYYY-MM-DDTHH:MM:SS) or None if not found/parseable
        """
        if not text:
            return None

        if reference_time is None:
            reference_time = datetime.now(timezone.utc).replace(tzinfo=None)

        # Try local parsing first
        iso_result = TemporalExtractor._parse_relative_dates(text, reference_time)
        if iso_result:
            return iso_result

        # Try dateutil parser for absolute dates
        iso_result = TemporalExtractor._parse_absolute_dates(text)
        if iso_result:
            return iso_result

        return None

    @staticmethod
    def _parse_relative_dates(text: str, reference_time: datetime) -> Optional[str]:
        """Parse relative date expressions like 'yesterday', 'next Friday'."""
        text_lower = text.lower()

        # Extract time if present (e.g., "2PM", "3:30pm", "14:00")
        time_match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|AM|PM)?", text_lower)
        extracted_hour = None
        extracted_minute = None
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2)) if time_match.group(2) else 0
            is_pm = time_match.group(3) and "pm" in time_match.group(3).lower()

            # Convert to 24-hour format
            if is_pm and hour != 12:
                hour += 12
            elif not is_pm and hour == 12:
                hour = 0

            extracted_hour = hour
            extracted_minute = minute

        # "yesterday"
        if re.search(r"\byesterday\b", text_lower):
            result = reference_time - timedelta(days=1)
            if extracted_hour is not None:
                result = result.replace(hour=extracted_hour, minute=extracted_minute)
            return result.strftime("%Y-%m-%dT%H:%M:%S")

        # "today"
        if re.search(r"\btoday\b", text_lower):
            result = reference_time
            if extracted_hour is not None:
                result = result.replace(hour=extracted_hour, minute=extracted_minute)
            return result.strftime("%Y-%m-%dT%H:%M:%S")

        # "tomorrow"
        if re.search(r"\btomorrow\b", text_lower):
            result = reference_time + timedelta(days=1)
            if extracted_hour is not None:
                result = result.replace(hour=extracted_hour, minute=extracted_minute)
            return result.strftime("%Y-%m-%dT%H:%M:%S")

        # "next/last [day of week]"
        match = re.search(
            r"\b(next|last)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            text_lower,
        )
        if match:
            direction = match.group(1)
            day_name = match.group(2)
            result_date = TemporalExtractor._calculate_day_of_week(
                reference_time, day_name, direction
            )
            # If time was extracted, replace the time part
            if extracted_hour is not None:
                parsed = datetime.fromisoformat(result_date)
                parsed = parsed.replace(hour=extracted_hour, minute=extracted_minute)
                return parsed.strftime("%Y-%m-%dT%H:%M:%S")
            return result_date

        # "in X days/weeks/months/years"
        match = re.search(r"\bin\s+(\d+)\s+(day|week|month|year)s?\b", text_lower)
        if match:
            amount = int(match.group(1))
            unit = match.group(2)
            return TemporalExtractor._add_relative_time(reference_time, amount, unit)

        # "X days/weeks/months/years ago"
        match = re.search(r"(\d+)\s+(day|week|month|year)s?\s+ago\b", text_lower)
        if match:
            amount = int(match.group(1))
            unit = match.group(2)
            return TemporalExtractor._add_relative_time(reference_time, -amount, unit)

        return None

    @staticmethod
    def _parse_absolute_dates(text: str) -> Optional[str]:
        """Parse absolute dates like '2026-07-15', 'July 15, 2026'."""
        try:
            # Try dateutil parser for flexible date parsing
            parsed = dateutil_parser.parse(text, fuzzy=True)
            return parsed.strftime("%Y-%m-%dT%H:%M:%S")
        except (ValueError, TypeError, AttributeError):
            return None

    @staticmethod
    def _calculate_day_of_week(
        reference_time: datetime, day_name: str, direction: str
    ) -> str:
        """Calculate date for 'next/last [day of week]'."""
        days = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6,
        }

        target_day = days[day_name]
        current_day = reference_time.weekday()

        if direction == "next":
            # Calculate days until target day (always at least 1 day in future)
            days_ahead = (target_day - current_day) % 7
            if days_ahead == 0:
                days_ahead = 7  # Same day means next week
        else:  # last
            # Calculate days since target day (always in the past)
            days_behind = (current_day - target_day) % 7
            if days_behind == 0:
                days_behind = 7  # Same day means last week
            days_ahead = -days_behind

        result = reference_time + timedelta(days=days_ahead)
        return result.strftime("%Y-%m-%dT%H:%M:%S")

    @staticmethod
    def _add_relative_time(reference_time: datetime, amount: int, unit: str) -> str:
        """Add relative time offset and return ISO 8601."""
        if unit == "day":
            result = reference_time + timedelta(days=amount)
        elif unit == "week":
            result = reference_time + timedelta(weeks=amount)
        elif unit == "month":
            result = reference_time + relativedelta(months=amount)
        elif unit == "year":
            result = reference_time + relativedelta(years=amount)
        else:
            return reference_time.strftime("%Y-%m-%dT%H:%M:%S")

        return result.strftime("%Y-%m-%dT%H:%M:%S")
