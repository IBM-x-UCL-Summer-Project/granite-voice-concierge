"""Session-safe wake-word detection for browser-streamed local PCM audio."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Protocol

import numpy as np

from voice_concierge.voice_input.wake_word_detector import WakeWordPrediction


class WakeWordStreamDetector(Protocol):
    """Detector operations needed by the browser transport."""

    def process_audio(
        self,
        audio: np.ndarray,
        *,
        confidence_threshold: float | None = None,
    ) -> WakeWordPrediction | None:
        """Return a threshold-crossing prediction, if one occurred."""

    def reset(self) -> None:
        """Discard audio buffered for the current stream."""


class WakeWordSessionInactiveError(RuntimeError):
    """Raised when a stale browser tab sends frames for another active tab."""


@dataclass(frozen=True)
class WebWakeWordResult:
    """Browser-safe result for one local PCM block."""

    detected: bool
    phrase: str | None = None
    confidence: float | None = None


class WebWakeWordService:
    """Own one stateful detector for the currently active local browser tab."""

    def __init__(self, detector: WakeWordStreamDetector) -> None:
        self._detector = detector
        self._active_session_id: str | None = None
        self._confidence_threshold = 0.3
        self._lock = RLock()

    def start(self, session_id: str, *, sensitivity: int) -> float:
        """Start or replace the active stream and return its score threshold."""

        threshold = sensitivity_to_threshold(sensitivity)
        with self._lock:
            self._detector.reset()
            self._active_session_id = session_id
            self._confidence_threshold = threshold
        return threshold

    def stop(self, session_id: str | None) -> bool:
        """Stop this session without allowing a stale tab to stop another."""

        with self._lock:
            if session_id is None or session_id != self._active_session_id:
                return False
            self._detector.reset()
            self._active_session_id = None
            return True

    def process_pcm(self, session_id: str | None, pcm: bytes) -> WebWakeWordResult:
        """Process little-endian mono int16 samples for the active session."""

        if not pcm or len(pcm) % 2:
            raise ValueError("pcm must contain complete 16-bit samples.")
        with self._lock:
            if session_id is None or session_id != self._active_session_id:
                raise WakeWordSessionInactiveError(
                    "Wake-word listening is not active for this browser session."
                )
            samples = np.frombuffer(pcm, dtype="<i2").astype(np.int16, copy=False)
            prediction = self._detector.process_audio(
                samples,
                confidence_threshold=self._confidence_threshold,
            )
        if prediction is None:
            return WebWakeWordResult(detected=False)
        return WebWakeWordResult(
            detected=True,
            phrase=prediction.phrase,
            confidence=prediction.confidence,
        )


def sensitivity_to_threshold(sensitivity: int) -> float:
    """Map the 20–100 UI scale onto conservative 0.5–0.1 model thresholds."""

    if isinstance(sensitivity, bool) or not isinstance(sensitivity, int):
        raise ValueError("sensitivity must be an integer.")
    if sensitivity < 20 or sensitivity > 100:
        raise ValueError("sensitivity must be between 20 and 100.")
    return (120 - sensitivity) / 200
