# Third-party
import pytest

# Local
from voice_concierge.routines.errors import RoutineError


@pytest.mark.unit
def test_routine_error_is_exception() -> None:
    """RoutineError is a raisable Exception carrying a message."""
    with pytest.raises(RoutineError, match="boom"):
        raise RoutineError("boom")
