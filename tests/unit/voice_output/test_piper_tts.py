# Standard library
import subprocess
from pathlib import Path
from unittest.mock import patch

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.audio import CapturedAudio
from voice_concierge.voice_output import (
    PiperTextToSpeech,
    TextToSpeech,
    TextToSpeechBackendUnavailableError,
    TextToSpeechSynthesisError,
)


def _write_wav_at_output(sample_rate: int = 22050, channels: int = 1):
    """Return a subprocess.run side effect that writes a WAV to the -f path."""

    def _side_effect(command, **kwargs):
        output_path = Path(command[command.index("-f") + 1])
        CapturedAudio(
            samples=np.zeros(160, dtype=np.int16),
            sample_rate=sample_rate,
            channels=channels,
        ).to_wav_file(output_path)
        return None

    return _side_effect


class TestPiperTextToSpeechSynthesize:
    """Unit tests for PiperTextToSpeech.synthesize()."""

    @pytest.mark.unit
    @patch("voice_concierge.voice_output.piper.subprocess.run")
    def test_returns_captured_audio_from_piper_output(self, mock_run: patch) -> None:
        """synthesize() reads Piper's WAV output into a CapturedAudio."""
        mock_run.side_effect = _write_wav_at_output(sample_rate=22050, channels=1)

        audio = PiperTextToSpeech().synthesize("hello there")

        assert isinstance(audio, CapturedAudio)
        assert audio.sample_rate == 22050
        assert audio.channels == 1
        assert len(audio.samples) == 160

    @pytest.mark.unit
    @patch("voice_concierge.voice_output.piper.subprocess.run")
    def test_passes_text_and_command_flags_to_piper(self, mock_run: patch) -> None:
        """synthesize() invokes Piper with the model, config and text."""
        mock_run.side_effect = _write_wav_at_output()

        PiperTextToSpeech(
            model_path="voice.onnx", config_path="voice.json", length_scale=1.5
        ).synthesize("speak this")

        command, kwargs = mock_run.call_args
        argv = command[0]
        assert argv[0] == "piper"
        assert "voice.onnx" in argv and "voice.json" in argv
        assert "1.5" in argv
        assert kwargs["input"] == b"speak this"

    @pytest.mark.unit
    @patch("voice_concierge.voice_output.piper.subprocess.run")
    def test_missing_executable_raises_backend_unavailable(
        self, mock_run: patch
    ) -> None:
        """A missing Piper executable raises TextToSpeechBackendUnavailableError."""
        mock_run.side_effect = FileNotFoundError("piper")

        with pytest.raises(TextToSpeechBackendUnavailableError):
            PiperTextToSpeech().synthesize("hello")

    @pytest.mark.unit
    @patch("voice_concierge.voice_output.piper.subprocess.run")
    def test_nonzero_exit_raises_synthesis_error(self, mock_run: patch) -> None:
        """A non-zero Piper exit raises TextToSpeechSynthesisError."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "piper", stderr=b"boom")

        with pytest.raises(TextToSpeechSynthesisError):
            PiperTextToSpeech().synthesize("hello")

    @pytest.mark.unit
    @patch("voice_concierge.voice_output.piper.subprocess.run")
    def test_missing_output_file_raises_synthesis_error(self, mock_run: patch) -> None:
        """A run that produces no output file raises TextToSpeechSynthesisError."""
        mock_run.return_value = None  # succeeds but writes nothing

        with pytest.raises(TextToSpeechSynthesisError):
            PiperTextToSpeech().synthesize("hello")

    @pytest.mark.unit
    def test_satisfies_text_to_speech_protocol(self) -> None:
        """PiperTextToSpeech satisfies the runtime-checkable protocol."""
        assert isinstance(PiperTextToSpeech(), TextToSpeech)
