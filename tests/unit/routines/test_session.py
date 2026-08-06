# tests/unit/routines/test_session.py
# Third-party
import pytest

# Local
from voice_concierge.routines.session import RoutineSession
from voice_concierge.routines.types import Routine, RoutineStep


def _routine(n: int = 3) -> Routine:
    return Routine(
        name="demo", steps=tuple(RoutineStep(f"step {i}") for i in range(1, n + 1))
    )


@pytest.mark.unit
class TestRoutineSession:
    def test_start_returns_first_step(self) -> None:
        s = RoutineSession(_routine())
        r = s.start()
        assert r.outcome == "started"
        assert (r.step.number, r.step.total) == (1, 3)
        assert s.status == "running"

    def test_next_advances(self) -> None:
        s = RoutineSession(_routine())
        s.start()
        r = s.next()
        assert r.outcome == "advanced"
        assert r.step.number == 2

    def test_next_on_last_step_finishes(self) -> None:
        s = RoutineSession(_routine(2))
        s.start()
        s.next()
        r = s.next()  # was on step 2 of 2
        assert r.outcome == "finished"
        assert r.step is None
        assert s.status == "finished"

    def test_next_while_paused_auto_resumes(self) -> None:
        s = RoutineSession(_routine())
        s.start()
        s.pause()
        r = s.next()
        assert r.outcome == "advanced"
        assert s.status == "running"

    def test_back_moves_back(self) -> None:
        s = RoutineSession(_routine())
        s.start()
        s.next()
        r = s.back()
        assert r.outcome == "moved_back"
        assert r.step.number == 1

    def test_back_on_first_step_stays(self) -> None:
        s = RoutineSession(_routine())
        s.start()
        r = s.back()
        assert r.outcome == "at_start"
        assert r.step.number == 1

    def test_repeat_returns_current_without_moving(self) -> None:
        s = RoutineSession(_routine())
        s.start()
        s.next()
        r = s.repeat()
        assert r.outcome == "repeated"
        assert r.step.number == 2

    def test_pause_then_resume(self) -> None:
        s = RoutineSession(_routine())
        s.start()
        p = s.pause()
        assert p.outcome == "paused"
        assert s.status == "paused"
        r = s.resume()
        assert r.outcome == "resumed"
        assert s.status == "running"

    def test_stop_is_terminal(self) -> None:
        s = RoutineSession(_routine())
        s.start()
        assert s.stop().outcome == "stopped"
        assert s.status == "stopped"
        assert s.next().outcome == "not_active"

    def test_commands_before_start_are_not_active(self) -> None:
        s = RoutineSession(_routine())
        assert s.next().outcome == "not_active"
        assert s.back().outcome == "not_active"
        assert s.repeat().outcome == "not_active"
        assert s.pause().outcome == "not_active"
        assert s.resume().outcome == "not_active"
        assert s.stop().outcome == "not_active"

    def test_current_step_none_when_inactive(self) -> None:
        s = RoutineSession(_routine())
        assert s.current_step is None
        s.start()
        assert s.current_step.number == 1
