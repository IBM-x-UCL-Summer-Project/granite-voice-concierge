# Standard library
import subprocess
import wave
from pathlib import Path
from unittest.mock import patch

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.audio import CapturedAudio
from voice_concierge.voice_output import (
    SayTextToSpeech,
    TextToSpeech,
    TextToSpeechBackendUnavailableError,
    TextToSpeechSynthesisError,
)


def _write_wav_at_output(sample_rate: int = 22050, channels: int = 1, width: int = 2):
    """Return a subprocess.run side effect that writes a WAV to the -o path."""

    def _side_effect(command, **kwargs):
        output_path = Path(command[command.index("-o") + 1])
        if width == 2:
            CapturedAudio(
                samples=np.zeros(160, dtype=np.int16),
                sample_rate=sample_rate,
                channels=channels,
            ).to_wav_file(output_path)
        else:
            with wave.open(str(output_path), "wb") as wav_file:
                wav_file.setnchannels(channels)
                wav_file.setsampwidth(width)
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(b"\x00" * 160)
        return None

    return _side_effect


class TestSayTextToSpeechSynthesize:
    """Unit tests for SayTextToSpeech.synthesize()."""

    @pytest.mark.unit
    @patch("voice_concierge.voice_output.say.subprocess.run")
    def test_returns_captured_audio(self, mock_run: patch) -> None:
        """synthesize() reads say's WAV output into a CapturedAudio."""
        mock_run.side_effect = _write_wav_at_output(sample_rate=22050)

        audio = SayTextToSpeech().synthesize("hello there")

        assert isinstance(audio, CapturedAudio)
        assert audio.sample_rate == 22050
        assert len(audio.samples) == 160

    @pytest.mark.unit
    @patch("voice_concierge.voice_output.say.subprocess.run")
    def test_builds_default_command(self, mock_run: patch) -> None:
        """The default command requests a 16-bit WAV and passes the text."""
        mock_run.side_effect = _write_wav_at_output()

        SayTextToSpeech().synthesize("speak this")

        (command,), _ = mock_run.call_args
        assert command[0] == "say"
        assert "--data-format=LEI16@22050" in command
        assert "--file-format=WAVE" in command
        assert command[-1] == "speak this"
        assert "-v" not in command
        assert "-r" not in command

    @pytest.mark.unit
    @patch("voice_concierge.voice_output.say.subprocess.run")
    def test_forwards_voice_and_rate(self, mock_run: patch) -> None:
        """A configured voice and rate are passed to say."""
        mock_run.side_effect = _write_wav_at_output()

        SayTextToSpeech(voice="Daniel", rate_wpm=150).synthesize("hi")

        (command,), _ = mock_run.call_args
        assert command[command.index("-v") + 1] == "Daniel"
        assert command[command.index("-r") + 1] == "150"

    @pytest.mark.unit
    @patch("voice_concierge.voice_output.say.subprocess.run")
    def test_missing_executable_raises_backend_unavailable(
        self, mock_run: patch
    ) -> None:
        """A missing say executable raises TextToSpeechBackendUnavailableError."""
        mock_run.side_effect = FileNotFoundError("say")

        with pytest.raises(TextToSpeechBackendUnavailableError):
            SayTextToSpeech().synthesize("hello")

    @pytest.mark.unit
    @patch("voice_concierge.voice_output.say.subprocess.run")
    def test_nonzero_exit_raises_synthesis_error(self, mock_run: patch) -> None:
        """A non-zero say exit raises TextToSpeechSynthesisError."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "say", stderr=b"boom")

        with pytest.raises(TextToSpeechSynthesisError):
            SayTextToSpeech().synthesize("hello")

    @pytest.mark.unit
    @patch("voice_concierge.voice_output.say.subprocess.run")
    def test_missing_output_file_raises_synthesis_error(self, mock_run: patch) -> None:
        """A run that produces no output file raises TextToSpeechSynthesisError."""
        mock_run.return_value = None  # succeeds but writes nothing

        with pytest.raises(TextToSpeechSynthesisError):
            SayTextToSpeech().synthesize("hello")

    @pytest.mark.unit
    @patch("voice_concierge.voice_output.say.subprocess.run")
    def test_non_16bit_output_raises_synthesis_error(self, mock_run: patch) -> None:
        """A non-16-bit WAV from say raises TextToSpeechSynthesisError."""
        mock_run.side_effect = _write_wav_at_output(width=1)

        with pytest.raises(TextToSpeechSynthesisError):
            SayTextToSpeech().synthesize("hello")

    @pytest.mark.unit
    @patch("voice_concierge.voice_output.say.subprocess.run")
    def test_unreadable_output_raises_synthesis_error(self, mock_run: patch) -> None:
        """Malformed say output remains inside the typed fallback boundary."""

        def _write_invalid_wav(command, **kwargs):
            output_path = Path(command[command.index("-o") + 1])
            output_path.write_bytes(b"not a WAV file")
            return None

        mock_run.side_effect = _write_invalid_wav

        with pytest.raises(TextToSpeechSynthesisError, match="unreadable WAV"):
            SayTextToSpeech().synthesize("hello")

    @pytest.mark.unit
    def test_satisfies_text_to_speech_protocol(self) -> None:
        """SayTextToSpeech satisfies the runtime-checkable protocol."""
        assert isinstance(SayTextToSpeech(), TextToSpeech)
