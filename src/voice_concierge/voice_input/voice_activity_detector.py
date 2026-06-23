# Standard library
import time
import tracemalloc
from typing import Callable, Optional

# Third-party
import numpy as np
import psutil
import pyaudio
import torch
from silero_vad import VADIterator, load_silero_vad

# Audio constants
DEFAULT_CHUNK: int = 512            # ~32ms at 16kHz (required by Silero VAD)
DEFAULT_RATE: int = 16000           # sample rate required by Silero VAD
DEFAULT_CHANNELS: int = 1           # mono audio
DEFAULT_FORMAT: int = pyaudio.paInt16

# VAD constants — values from spike benchmarks
DEFAULT_SPEECH_CONFIDENCE_THRESHOLD: float = 0.5
DEFAULT_MIN_SILENCE_BEFORE_UTTERANCE_END_MS: int = 300
DEFAULT_UTTERANCE_BOUNDARY_PADDING_MS: int = 100
DEFAULT_MAX_SPEECH_START_WAIT_S: int = 5


# VAD constants — values from spike benchmarks
DEFAULT_CONFIDENCE_THRESHOLD: float = 0.5
DEFAULT_MIN_SILENCE_MS: int = 300
DEFAULT_PADDING_MS: int = 100
DEFAULT_MAX_WAIT_S: int = 5


class VoiceActivityDetector:
    """
    Captures a user utterance from live microphone input using Silero VAD.

    Listens after the wake word fires, detects speech boundaries, and returns
    the captured audio as a numpy array via callback. Times out cleanly if no
    speech is detected within the configured window.

    Usage:
        vad = VoiceActivityDetector()
        vad.capture_utterance(on_utterance_captured=my_callback)
    """

    def __init__(
        self,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        min_silence_ms: int = DEFAULT_MIN_SILENCE_MS,
        padding_ms: int = DEFAULT_PADDING_MS,
        max_wait_s: int = DEFAULT_MAX_WAIT_S,
        chunk: int = DEFAULT_CHUNK,
        rate: int = DEFAULT_RATE,
        channels: int = DEFAULT_CHANNELS,
        fmt: int = DEFAULT_FORMAT,
        collect_metrics: bool = False,
    ) -> None:
        """
        Initialise the voice activity detector.

        Args:
            confidence_threshold: minimum VAD confidence to detect speech.
            min_silence_ms: ms of silence before utterance is considered complete.
            padding_ms: ms of padding added to utterance boundaries.
            max_wait_s: seconds before VAD times out if no speech detected.
            chunk: number of audio samples per chunk.
            rate: audio sample rate in Hz.
            channels: number of audio channels.
            fmt: PyAudio format constant.
            collect_metrics: if True, collect and print performance metrics on
                each utterance capture. Defaults to False.
        """
        self._confidence_threshold = confidence_threshold
        self._min_silence_ms = min_silence_ms
        self._padding_ms = padding_ms
        self._max_wait_s = max_wait_s
        self._chunk = chunk
        self._rate = rate
        self._channels = channels
        self._fmt = fmt
        self._collect_metrics = collect_metrics
        self._process: psutil.Process = psutil.Process()

        self._vad_model = load_silero_vad()
        self._vad_iterator: VADIterator = VADIterator(
            self._vad_model,
            threshold=self._confidence_threshold,
            sampling_rate=self._rate,
            min_silence_duration_ms=self._min_silence_ms,
            speech_pad_ms=self._padding_ms,
        )

    def _collect_perf_metrics(
        self, t_start: float, utterance: np.ndarray
    ) -> dict[str, float]:
        """Collect and return performance metrics at point of utterance capture."""
        latency: float = (time.perf_counter() - t_start) * 1000
        current_ram, peak_ram = tracemalloc.get_traced_memory()
        ram_system: float = self._process.memory_info().rss / 1024 / 1024
        cpu: float = self._process.cpu_percent()

        return {
            "latency_ms": latency,
            "ram_current_mb": current_ram / 1024 / 1024,
            "ram_peak_mb": peak_ram / 1024 / 1024,
            "ram_system_mb": ram_system,
            "cpu_percent": cpu,
            "samples": len(utterance),
        }

    def _print_metrics(self, metrics: dict[str, float]) -> None:
        """Print performance metrics in a formatted way."""
        print("Speech ended — utterance captured")
        print(f"  Utterance duration : {metrics['latency_ms']:.1f} ms")
        print(f"  Samples captured   : {int(metrics['samples'])}")
        print(f"  RAM (python) current : {metrics['ram_current_mb']:.1f} MB")
        print(f"  RAM (python) peak    : {metrics['ram_peak_mb']:.1f} MB")
        print(f"  RAM (system)         : {metrics['ram_system_mb']:.1f} MB")
        print(f"  CPU                  : {metrics['cpu_percent']:.1f}%")

    def capture_utterance(
        self, on_utterance_captured: Callable[[np.ndarray], None]
    ) -> None:
        """
        Listen for a user utterance and pass it to the callback when captured.

        Blocks until an utterance is captured or the timeout is reached.
        Calls on_utterance_captured() with the captured audio as a numpy array.

        Args:
            on_utterance_captured: callback to invoke with the captured utterance.
        """
        if self._collect_metrics:
            tracemalloc.start()
            self._process.cpu_percent()  # warm up CPU measurement

        print("VAD listening — speak your command...")

        audio_buffer: bytearray = bytearray()
        speech_started: bool = False
        t_speech_start: float = 0.0
        t_listen_start: float = time.perf_counter()

        p: pyaudio.PyAudio = pyaudio.PyAudio()
        stream: pyaudio.Stream = p.open(
            format=self._fmt,
            channels=self._channels,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk,
        )

        try:
            while True:
                # Time out if speech has not started within the configured window
                if not speech_started:
                    elapsed: float = time.perf_counter() - t_listen_start
                    if elapsed > self._max_wait_s:
                        print("VAD timed out — no speech detected")
                        break

                audio_chunk: bytes = stream.read(
                    self._chunk, exception_on_overflow=False
                )
                audio_np: np.ndarray = np.frombuffer(audio_chunk, dtype=np.int16)

                # Normalize int16 [-32768, 32767] to float32 [-1.0, 1.0]
                audio_float: torch.Tensor = torch.from_numpy(
                    audio_np.astype(np.float32, copy=False) / 32768.0
                )

                vad_result: Optional[dict[str, float]] = self._vad_iterator(
                    audio_float, return_seconds=False
                )

                if vad_result is not None:
                    if "start" in vad_result and not speech_started:
                        speech_started = True
                        t_speech_start = time.perf_counter()
                        print("Speech started...")

                    if "end" in vad_result and speech_started:
                        utterance: np.ndarray = np.frombuffer(
                            audio_buffer, dtype=np.int16
                        )

                        if self._collect_metrics:
                            metrics: dict[str, float] = self._collect_perf_metrics(
                                t_speech_start, utterance
                            )
                            self._print_metrics(metrics)

                        if tracemalloc.is_tracing():
                            tracemalloc.stop()

                        on_utterance_captured(utterance)
                        break

                if speech_started:
                    audio_buffer.extend(audio_chunk)

        except KeyboardInterrupt:
            print("\nVAD stopped.")
        finally:
            if tracemalloc.is_tracing():
                tracemalloc.stop()
            stream.stop_stream()
            stream.close()
            p.terminate()
