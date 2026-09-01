"""Tests for session-safe browser wake-word streaming."""

from __future__ import annotations

import numpy as np
import pytest

from voice_concierge.app.web_wake_word import (
    WakeWordSessionInactiveError,
    WebWakeWordService,
    sensitivity_to_threshold,
)
from voice_concierge.voice_input.wake_word_detector import WakeWordPrediction


class FakeStreamDetector:
    def __init__(self) -> None:
        self.prediction: WakeWordPrediction | None = None
        self.calls: list[tuple[np.ndarray, float | None]] = []
        self.reset_count = 0

    def process_audio(
        self,
        audio: np.ndarray,
        *,
        confidence_threshold: float | None = None,
    ) -> WakeWordPrediction | None:
        self.calls.append((audio, confidence_threshold))
        return self.prediction

    def reset(self) -> None:
        self.reset_count += 1


@pytest.mark.parametrize(
    ("sensitivity", "threshold"),
    [(20, 0.5), (60, 0.3), (100, 0.1)],
)
def test_sensitivity_maps_to_detector_threshold(
    sensitivity: int,
    threshold: float,
) -> None:
    assert sensitivity_to_threshold(sensitivity) == threshold


def test_stream_returns_detection_for_active_session() -> None:
    detector = FakeStreamDetector()
    detector.prediction = WakeWordPrediction("hey_jarvis", 0.81)
    service = WebWakeWordService(detector)
    service.start("session-a", sensitivity=60)

    result = service.process_pcm("session-a", np.zeros(3200, dtype="<i2").tobytes())

    assert result.detected is True
    assert result.phrase == "hey_jarvis"
    assert result.confidence == 0.81
    samples, threshold = detector.calls[0]
    assert samples.dtype == np.int16
    assert threshold == 0.3


def test_new_tab_supersedes_old_stream_without_crossing_audio() -> None:
    detector = FakeStreamDetector()
    service = WebWakeWordService(detector)
    service.start("session-a", sensitivity=60)
    service.start("session-b", sensitivity=60)

    with pytest.raises(WakeWordSessionInactiveError):
        service.process_pcm("session-a", b"\0\0")

    assert service.stop("session-a") is False
    assert service.stop("session-b") is True
    assert detector.reset_count == 3


def test_stale_connection_cannot_stop_new_stream_in_the_same_session() -> None:
    detector = FakeStreamDetector()
    service = WebWakeWordService(detector)
    service.start("session-a", sensitivity=60, stream_id="old")
    service.start("session-a", sensitivity=80, stream_id="new")

    assert service.stop("session-a", stream_id="old") is False
    result = service.process_pcm("session-a", b"\0\0", stream_id="new")

    assert result.detected is False
    assert detector.calls[-1][1] == 0.2


def test_reset_can_update_sensitivity_without_replacing_stream_owner() -> None:
    detector = FakeStreamDetector()
    service = WebWakeWordService(detector)
    service.start("session-a", sensitivity=60, stream_id="stream")

    threshold = service.reset(
        "session-a",
        stream_id="stream",
        sensitivity=100,
    )
    service.process_pcm("session-a", b"\0\0", stream_id="stream")

    assert threshold == 0.1
    assert detector.calls[-1][1] == 0.1


@pytest.mark.parametrize("pcm", [b"", b"\0"])
def test_stream_rejects_empty_or_partial_samples(pcm: bytes) -> None:
    service = WebWakeWordService(FakeStreamDetector())
    service.start("session-a", sensitivity=60)

    with pytest.raises(ValueError, match="16-bit"):
        service.process_pcm("session-a", pcm)
