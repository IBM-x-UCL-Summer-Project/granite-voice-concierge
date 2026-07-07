# Standard library
from collections import defaultdict, deque
from unittest.mock import MagicMock

# Third-party
import numpy as np
import pytest


class FakeEmbeddingService:
    """Deterministic embedding service for tests that do not exercise Ollama."""

    def __init__(self, dimension: int = 768) -> None:
        self.dimension = dimension

    def get_embedding(self, content: str) -> list[float]:
        return [0.0] * self.dimension


def pytest_configure(config: pytest.Config) -> None:
    """Register custom pytest markers."""
    config.addinivalue_line("markers", "unit: mark test as a unit test")
    config.addinivalue_line("markers", "integration: mark test as an integration test")


@pytest.fixture
def fake_embedding_service() -> FakeEmbeddingService:
    """Return a deterministic embedding service with the default vector width."""
    return FakeEmbeddingService()


@pytest.fixture
def mock_openwakeword_model(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch openWakeWord model loading for tests that do not need real ONNX files."""
    model = MagicMock()
    model.predict.return_value = None
    model.reset.return_value = None
    model.prediction_buffer = defaultdict(deque, {"hey_jarvis_v0.1.onnx": deque([0.0])})

    def build_model(*args, **kwargs):
        return model

    monkeypatch.setattr(
        "voice_concierge.voice_input.wake_word_detector.Model",
        build_model,
    )
    monkeypatch.setattr(
        "voice_concierge.voice_input.wake_word_detector.openwakeword.utils.download_models",
        MagicMock(),
        raising=False,
    )
    return model


@pytest.fixture
def silent_audio_chunk() -> np.ndarray:
    """
    Generate a single silent audio chunk matching openWakeWord's expected
    chunk size of 1280 samples at 16kHz.
    """
    return np.zeros(1280, dtype=np.int16)


@pytest.fixture
def silent_audio_stream() -> list[np.ndarray]:
    """
    Generate a list of silent audio chunks for continuous listening tests.
    Returns 100 chunks of 1280 samples each.
    """
    return [np.zeros(1280, dtype=np.int16) for _ in range(100)]


@pytest.fixture
def hey_jarvis_audio() -> np.ndarray:
    """
    Generate synthetic audio approximating a wake word utterance.
    Uses a sine wave burst to simulate speech energy rather than silence,
    giving the model something non-trivial to process.
    Note: this will not trigger a real detection — use for structural
    tests only, not confidence threshold tests.
    """
    sample_rate: int = 16000
    duration: float = 1.0  # seconds
    frequency: float = 440.0  # Hz — arbitrary tone to simulate speech energy

    t: np.ndarray = np.linspace(0, duration, int(sample_rate * duration))
    sine_wave: np.ndarray = (np.sin(2 * np.pi * frequency * t) * 32767).astype(np.int16)
    return sine_wave
