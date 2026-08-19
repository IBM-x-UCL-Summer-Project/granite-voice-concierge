# Standard library
import json
import sys
import types
from unittest.mock import patch

# Third-party
import pytest

# Local
from voice_concierge.command_control.errors import CommandSpotterUnavailableError
from voice_concierge.command_control.interfaces import PhraseRecognizer
from voice_concierge.command_control.vosk_recognizer import (
    VoskPhraseRecognizer,
    _build_recognizer,
)


class _FakeVoskRecognizer:
    """Minimal stand-in for a Vosk KaldiRecognizer."""

    def __init__(self, final: bool, text: str = "", partial: str = "") -> None:
        self._final = final
        self._text = text
        self._partial = partial
        self.frames: list[bytes] = []
        self.reset_count = 0

    def AcceptWaveform(self, frame: bytes) -> bool:
        self.frames.append(frame)
        return self._final

    def Result(self) -> str:
        return json.dumps({"text": self._text})

    def PartialResult(self) -> str:
        return json.dumps({"partial": self._partial})

    def Reset(self) -> None:
        self.reset_count += 1


class TestVoskPhraseRecognizerInit:
    """Unit tests for VoskPhraseRecognizer construction."""

    @pytest.mark.unit
    def test_uses_injected_recognizer(self) -> None:
        """An injected recognizer is used directly without building one."""
        fake = _FakeVoskRecognizer(final=False)

        recognizer = VoskPhraseRecognizer(["stop"], recognizer=fake)

        assert recognizer._recognizer is fake

    @pytest.mark.unit
    @patch("voice_concierge.command_control.vosk_recognizer._build_recognizer")
    def test_builds_grammar_constrained_recognizer(self, mock_build: patch) -> None:
        """Without an injected recognizer, a grammar-constrained one is built."""
        VoskPhraseRecognizer(["stop", "pause"], model_name="m", sample_rate=8000)

        mock_build.assert_called_once_with(
            "m", 8000, json.dumps(["stop", "pause", "[unk]"])
        )

    @pytest.mark.unit
    @patch("voice_concierge.command_control.vosk_recognizer._build_recognizer")
    def test_wraps_build_failure(self, mock_build: patch) -> None:
        """A model load failure is wrapped in CommandSpotterUnavailableError."""
        mock_build.side_effect = RuntimeError("no model")

        with pytest.raises(CommandSpotterUnavailableError):
            VoskPhraseRecognizer(["stop"])

    @pytest.mark.unit
    def test_satisfies_phrase_recognizer_protocol(self) -> None:
        """VoskPhraseRecognizer satisfies the PhraseRecognizer protocol."""
        recognizer = VoskPhraseRecognizer(
            ["stop"], recognizer=_FakeVoskRecognizer(final=False)
        )

        assert isinstance(recognizer, PhraseRecognizer)


class TestBuildRecognizer:
    """Unit tests for the lazy _build_recognizer helper."""

    @pytest.mark.unit
    def test_builds_from_vosk_module(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_build_recognizer constructs a KaldiRecognizer from a Vosk model."""
        calls: dict[str, object] = {}

        class _Model:
            def __init__(self, model_name: str) -> None:
                calls["model_name"] = model_name

        class _Kaldi:
            def __init__(self, model, rate, grammar) -> None:
                calls.update(model=model, rate=rate, grammar=grammar)

        fake_vosk = types.SimpleNamespace(Model=_Model, KaldiRecognizer=_Kaldi)
        monkeypatch.setitem(sys.modules, "vosk", fake_vosk)

        result = _build_recognizer("model", 16000, "[]")

        assert isinstance(result, _Kaldi)
        assert calls["model_name"] == "model"
        assert calls["rate"] == 16000
        assert calls["grammar"] == "[]"


class TestVoskPhraseRecognizerRecognize:
    """Unit tests for VoskPhraseRecognizer.recognize()."""

    @pytest.mark.unit
    def test_returns_none_when_nothing_recognized(self) -> None:
        """recognize() returns None with neither a final nor a partial result."""
        fake = _FakeVoskRecognizer(final=False, partial="")
        recognizer = VoskPhraseRecognizer(["stop"], recognizer=fake)

        assert recognizer.recognize(b"frame") is None
        assert fake.reset_count == 0  # nothing to emit, so no reset

    @pytest.mark.unit
    def test_returns_partial_before_finalization(self) -> None:
        """A partial phrase is emitted without waiting for a silence boundary."""
        fake = _FakeVoskRecognizer(final=False, partial="stop")
        recognizer = VoskPhraseRecognizer(["stop"], recognizer=fake)

        assert recognizer.recognize(b"frame") == "stop"
        assert fake.reset_count == 0  # retained so stability can be observed

    @pytest.mark.unit
    def test_returns_newest_word_of_a_partial(self) -> None:
        """An accumulated partial yields its newest word, not the whole phrase."""
        fake = _FakeVoskRecognizer(final=False, partial="stop back")
        recognizer = VoskPhraseRecognizer(["stop", "back"], recognizer=fake)

        assert recognizer.recognize(b"frame") == "back"

    @pytest.mark.unit
    def test_returns_recognized_phrase(self) -> None:
        """recognize() returns the finalized phrase text."""
        recognizer = VoskPhraseRecognizer(
            ["stop"], recognizer=_FakeVoskRecognizer(final=True, text="stop")
        )

        assert recognizer.recognize(b"frame") == "stop"

    @pytest.mark.unit
    def test_returns_none_for_empty_result(self) -> None:
        """recognize() returns None when the final result text is empty."""
        recognizer = VoskPhraseRecognizer(
            ["stop"], recognizer=_FakeVoskRecognizer(final=True, text="")
        )

        assert recognizer.recognize(b"frame") is None

    @pytest.mark.unit
    def test_reset_discards_partial_audio(self) -> None:
        fake = _FakeVoskRecognizer(final=False)
        recognizer = VoskPhraseRecognizer(["yes"], recognizer=fake)

        recognizer.reset()

        assert fake.reset_count == 1
