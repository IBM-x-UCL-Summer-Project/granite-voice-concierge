"""Tests for browser-streamed guided-routine commands."""

from __future__ import annotations

import pytest

from voice_concierge.app.web_routine_commands import (
    RoutineCommandSessionInactiveError,
    WebRoutineCommandService,
)
from voice_concierge.command_control.types import CommandEvent


class FakeSpotter:
    def __init__(self, event: CommandEvent | None = None) -> None:
        self.event = event
        self.frames: list[bytes] = []
        self.reset_count = 0

    def process(self, frame: bytes) -> CommandEvent | None:
        self.frames.append(frame)
        return self.event

    def reset(self) -> None:
        self.reset_count += 1


def test_active_session_receives_spotted_command() -> None:
    spotter = FakeSpotter(CommandEvent(command="pause", phrase="pause"))
    service = WebRoutineCommandService(lambda: spotter)
    service.start("session-a")

    event = service.process_pcm("session-a", b"\0\0")

    assert event == CommandEvent(command="pause", phrase="pause")
    assert spotter.frames == [b"\0\0"]


def test_new_session_replaces_old_routine_command_stream() -> None:
    built: list[FakeSpotter] = []

    def factory() -> FakeSpotter:
        spotter = FakeSpotter()
        built.append(spotter)
        return spotter

    service = WebRoutineCommandService(factory)
    service.start("session-a")
    service.start("session-b")

    with pytest.raises(RoutineCommandSessionInactiveError):
        service.process_pcm("session-a", b"\0\0")

    assert len(built) == 2
    assert service.stop("session-a") is False
    assert service.stop("session-b") is True


def test_reset_discards_audio_without_rebuilding_model() -> None:
    spotter = FakeSpotter()
    builds = 0

    def factory() -> FakeSpotter:
        nonlocal builds
        builds += 1
        return spotter

    service = WebRoutineCommandService(factory)
    service.start("session-a")

    service.reset("session-a")

    assert spotter.reset_count == 1
    assert builds == 1


@pytest.mark.parametrize("pcm", [b"", b"\0"])
def test_routine_stream_rejects_empty_or_partial_samples(pcm: bytes) -> None:
    service = WebRoutineCommandService(FakeSpotter)
    service.start("session-a")

    with pytest.raises(ValueError, match="16-bit"):
        service.process_pcm("session-a", pcm)
