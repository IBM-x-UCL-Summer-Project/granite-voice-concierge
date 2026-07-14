# Standard library
from unittest.mock import patch

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.audio import FakeAudioSource
from voice_concierge.command_control import (
    CommandListener,
    FakeCommandSpotter,
    FakePlaybackController,
    PhraseCommandSpotter,
    build_command_listener,
    build_stop_command_control,
    build_vosk_command_spotter,
)
from voice_concierge.command_control.spotter import DEFAULT_PHRASE_COMMANDS
from voice_concierge.command_control.types import CommandEvent

_FRAME = np.zeros(512, dtype=np.int16).tobytes()


class TestBuildCommandListener:
    """Unit tests for the build_command_listener factory."""

    @pytest.mark.unit
    def test_wires_spotter_dispatch_to_controller(self) -> None:
        """A spotted event flows through the dispatcher to the controller."""
        event = CommandEvent(command="stop", phrase="stop")
        controller = FakePlaybackController()
        listener = build_command_listener(
            FakeCommandSpotter([event]),
            controller,
            audio_source=FakeAudioSource(fill=_FRAME),
        )

        listener._pump()  # drive one frame: spotter -> dispatch -> controller

        assert isinstance(listener, CommandListener)
        assert controller.actions == ["stop"]

    @pytest.mark.unit
    @patch("voice_concierge.command_control.factory.PyAudioSource")
    def test_builds_default_pyaudio_source(self, mock_source: patch) -> None:
        """Without an injected source, a PyAudioSource is created for the chunk."""
        build_command_listener(
            FakeCommandSpotter(), FakePlaybackController(), chunk=256
        )

        mock_source.assert_called_once_with(frames_per_buffer=256)


class TestBuildVoskCommandSpotter:
    """Unit tests for the build_vosk_command_spotter factory."""

    @pytest.mark.unit
    @patch("voice_concierge.command_control.factory.VoskPhraseRecognizer")
    def test_wires_default_vocabulary(self, mock_recognizer: patch) -> None:
        """The factory builds a Vosk recognizer over the default command words."""
        spotter = build_vosk_command_spotter(model_name="m", sample_rate=8000)

        mock_recognizer.assert_called_once_with(
            tuple(DEFAULT_PHRASE_COMMANDS), model_name="m", sample_rate=8000
        )
        assert isinstance(spotter, PhraseCommandSpotter)

    @pytest.mark.unit
    @patch("voice_concierge.command_control.factory.VoskPhraseRecognizer")
    def test_wires_custom_phrase_commands(self, mock_recognizer: patch) -> None:
        """A custom phrase map drives both the grammar vocabulary and mapping."""
        build_vosk_command_spotter(phrase_commands={"halt": "stop"})

        (vocabulary,), _ = mock_recognizer.call_args
        assert vocabulary == ("halt",)


class TestBuildStopCommandControl:
    """Unit tests for the stop-only assembly factory."""

    @pytest.mark.unit
    @patch("voice_concierge.command_control.factory.VoskPhraseRecognizer")
    def test_assembles_stop_only_listener(self, mock_recognizer: patch) -> None:
        """The stop assembly recognizes only 'stop' and returns a listener."""
        listener = build_stop_command_control(audio_source=FakeAudioSource(fill=_FRAME))

        assert isinstance(listener, CommandListener)
        (vocabulary,), _ = mock_recognizer.call_args
        assert vocabulary == ("stop",)
