# Standard library
from typing import Callable, Optional

# Third-party
import numpy as np

# Local
from voice_concierge.voice_input.voice_activity_detector import VoiceActivityDetector
from voice_concierge.voice_input.wake_word_detector import WakeWordDetector


class VoiceInputPipeline:
    """
    Orchestrates the full voice input pipeline: wake word detection followed
    by utterance capture via VAD.

    Runs continuously until interrupted, resetting after each utterance
    is captured and passed to the provided callback.

    Usage:
        pipeline = VoiceInputPipeline()
        pipeline.run(on_utterance_captured=my_callback)
    """

    def __init__(
        self,
        wake_word_detector: Optional[WakeWordDetector] = None,
        voice_activity_detector: Optional[VoiceActivityDetector] = None,
    ) -> None:
        """
        Initialise the voice input pipeline.

        Args:
            wake_word_detector: WakeWordDetector instance to use. If None,
                a default instance is created.
            voice_activity_detector: VoiceActivityDetector instance to use.
                If None, a default instance is created.
        """
        self._wake_word_detector: WakeWordDetector = (
            wake_word_detector or WakeWordDetector()
        )
        self._voice_activity_detector: VoiceActivityDetector = (
            voice_activity_detector or VoiceActivityDetector()
        )
        self._on_utterance_captured: Optional[Callable[[np.ndarray], None]] = None

    def _on_wake_word(self) -> None:
        """
        Called by WakeWordDetector when the wake word is detected.
        Triggers VAD to capture the following utterance.
        """
        print("Wake word detected — listening for command...")
        self._voice_activity_detector.capture_utterance(
            on_utterance_captured=self._handle_utterance
        )

    def _handle_utterance(self, audio: np.ndarray) -> None:
        """
        Called by VoiceActivityDetector when an utterance is captured.
        Passes the audio to the registered callback if one is set.

        Args:
            audio: captured utterance as a numpy array.
        """
        if self._on_utterance_captured is not None:
            self._on_utterance_captured(audio)
        else:
            print(f">>> Utterance captured ({len(audio)} samples) — STT not connected")

    def run(self, on_utterance_captured: Optional[Callable[[np.ndarray], None]]) -> None:
        """
        Start the voice input pipeline.

        Listens continuously for the wake word, captures the following
        utterance via VAD, and passes it to on_utterance_captured.
        Loops until KeyboardInterrupt.

        Note: in future this should pause between iterations until the full
        pipeline has completed and the user has received a response.

        Args:
            on_utterance_captured: callback to invoke with each captured utterance.
                Can be None if no callback is needed (e.g., for testing).
        """
        self._on_utterance_captured = on_utterance_captured
        print("Voice input pipeline started — say the wake word to begin.")

        try:
            while True:
                self._wake_word_detector.listen(on_wake_word=self._on_wake_word)
        except KeyboardInterrupt:
            print("\nVoice input pipeline stopped.")


if __name__ == "__main__":
    def on_utterance_captured(audio: np.ndarray) -> None:
        """Placeholder — this is where STT will connect later."""
        print(f">>> Utterance captured ({len(audio)} samples) — ready for STT")

    pipeline = VoiceInputPipeline()
    pipeline.run(on_utterance_captured=on_utterance_captured)
