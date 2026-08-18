# tests/unit/routines/test_intent.py
# Third-party
import pytest

# Local
from voice_concierge.routines.intent import ROUTINE_TRIGGERS, is_routine_request


@pytest.mark.unit
class TestRoutineRequests:
    @pytest.mark.parametrize(
        "transcript",
        [
            "guide me through making pasta",
            "walk me through changing a tyre",
            "talk me through folding a shirt",
            "coach me through making bread",
            "start a guided routine for banana bread",
            "guide me step by step through making tea",
            "take me through changing a tyre",
        ],
    )
    def test_guidance_requests_are_detected(self, transcript: str) -> None:
        assert is_routine_request(transcript) is True

    def test_detection_ignores_case(self) -> None:
        assert is_routine_request("GUIDE ME THROUGH making tea") is True

    @pytest.mark.parametrize("trigger", ROUTINE_TRIGGERS)
    def test_every_published_trigger_matches(self, trigger: str) -> None:
        """The exported list and the matcher never drift apart."""
        assert is_routine_request(f"please {trigger} something") is True


@pytest.mark.unit
class TestNonRoutineRequests:
    @pytest.mark.parametrize(
        "transcript",
        [
            "what is the weather today",
            "remind me to call mum at six",
            "add milk to the shopping list",
            "what did i say yesterday",
            "give me three steps to boil an egg",
            "how do i make bread",
            "show me how to fold a shirt",
            "recipe for banana bread",
            "",
        ],
    )
    def test_ordinary_requests_fall_through(self, transcript: str) -> None:
        """A false positive would hijack the turn, so these must stay False."""
        assert is_routine_request(transcript) is False
