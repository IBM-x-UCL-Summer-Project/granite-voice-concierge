"""macOS voice player with OS acoustic echo cancellation (AVAudioEngine).

Plays audio through the macOS Voice-Processing audio unit (the same acoustic echo
cancellation video-call apps use) and taps the echo-cancelled microphone, so the
assistant does not hear its own playback and a spoken command can interrupt it in
a single audio graph (which also avoids the two-stream CoreAudio -50 collision).

macOS only: requires pyobjc-framework-AVFoundation, imported lazily so this module
stays importable everywhere. The recognizer never runs on the audio thread: the
tap only queues a converted microphone block, and play() delivers those blocks
and applies playback commands on its own thread.

Satisfies the AudioPlayer protocol (play) and the PlaybackController protocol
(stop/pause/resume) structurally, so the audio package stays independent of
command control.
"""

# Standard library
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

# Third-party
import numpy as np

# Local
from voice_concierge.audio.errors import AudioDeviceError
from voice_concierge.audio.types import CapturedAudio

VOSK_RATE: int = 16000  # sample rate the command recognizer expects
DEFAULT_BLOCKSIZE: int = 1024  # frames per tap callback
_POLL: float = 0.02  # seconds to wait for a captured block


def mic_to_command_bytes(
    mono_float: np.ndarray, in_rate: int, out_rate: int = VOSK_RATE
) -> bytes:
    """Convert float32 mono mic audio at in_rate to out_rate mono int16 bytes."""
    factor = max(1, in_rate // out_rate)
    if factor > 1:
        kernel = np.ones(factor, dtype=np.float32) / factor  # light anti-alias
        mono_float = np.convolve(mono_float, kernel, mode="same")[::factor]
    return np.clip(mono_float * 32767.0, -32768, 32767).astype(np.int16).tobytes()


def resample_int16_to_float(
    samples: np.ndarray, in_rate: int, out_rate: int
) -> np.ndarray:
    """Linear-resample int16 mono to out_rate, returned as float32 in [-1, 1]."""
    floats = samples.astype(np.float32) / 32768.0
    if in_rate == out_rate:
        return floats
    n_out = int(round(len(floats) * out_rate / in_rate))
    positions = np.linspace(0, len(floats), num=n_out, endpoint=False)
    return np.interp(positions, np.arange(len(floats)), floats).astype(np.float32)


class VoiceProcessingAudioPlayer:
    """Plays audio with OS echo cancellation and taps the cleaned microphone."""

    def __init__(self, *, blocksize: int = DEFAULT_BLOCKSIZE) -> None:
        self._blocksize = blocksize
        self._pending: str | None = None
        self._lock = threading.Lock()
        self._input_queue: queue.Queue[bytes] = queue.Queue()
        self._paused = False

    def stop(self) -> None:
        """Request that playback stop (applied on the play() thread)."""
        self._record("stop")

    def pause(self) -> None:
        """Request that playback pause."""
        self._record("pause")

    def resume(self) -> None:
        """Request that playback resume."""
        self._record("resume")

    def _record(self, command: str) -> None:
        with self._lock:
            self._pending = command

    def _take(self) -> str | None:
        with self._lock:
            command, self._pending = self._pending, None
            return command

    @property
    def is_paused(self) -> bool:
        """Whether playback is currently held by a pause command."""
        return self._paused

    def _drain_input(self) -> None:
        while not self._input_queue.empty():
            self._input_queue.get_nowait()

    def _pump_once(
        self, player: Any, on_input_frame: Callable[[bytes], None] | None
    ) -> bool:
        """Deliver at most one mic block and apply any command. True means stop."""
        if on_input_frame is None:
            time.sleep(_POLL)
        else:
            try:
                on_input_frame(self._input_queue.get(timeout=_POLL))
            except queue.Empty:
                pass
        command = self._take()
        if command == "stop":
            player.stop()
            return True
        if command == "pause":
            self._paused = True
            player.pause()
        elif command == "resume":
            self._paused = False
            player.play()
        return False

    def play(  # pragma: no cover - native AVAudioEngine orchestration
        self,
        audio: CapturedAudio,
        *,
        on_input_frame: Callable[[bytes], None] | None = None,
    ) -> None:
        """Play the audio with echo cancellation, streaming cleaned mic blocks.

        Blocks until the audio finishes or stop() is requested. macOS only.
        """
        self._paused = False
        av = _load_avfoundation()
        engine = av.AVAudioEngine.alloc().init()
        input_node = engine.inputNode()
        output_node = engine.outputNode()

        ok, err = input_node.setVoiceProcessingEnabled_error_(True, None)
        if not ok:
            raise AudioDeviceError(f"could not enable voice processing: {err}")

        play_format = output_node.inputFormatForBus_(0)
        play_rate = int(play_format.sampleRate())
        channels = int(play_format.channelCount())
        floats = resample_int16_to_float(audio.samples, audio.sample_rate, play_rate)
        buffer = _make_buffer(av, play_format, floats, channels)

        player = av.AVAudioPlayerNode.alloc().init()
        engine.attachNode_(player)
        engine.connect_to_format_(player, output_node, play_format)

        tap_format = input_node.inputFormatForBus_(0)
        in_rate = int(tap_format.sampleRate())
        self._drain_input()

        def tap(pcm_buffer: Any, when: Any) -> None:
            frames = int(pcm_buffer.frameLength())
            channel_data = pcm_buffer.floatChannelData()
            if frames == 0 or channel_data is None:
                return
            mono = np.frombuffer(channel_data[0].as_buffer(frames), dtype=np.float32)
            self._input_queue.put_nowait(mic_to_command_bytes(mono, in_rate))

        input_node.installTapOnBus_bufferSize_format_block_(
            0, self._blocksize, tap_format, tap
        )

        ok, err = engine.startAndReturnError_(None)
        if not ok:
            input_node.removeTapOnBus_(0)
            raise AudioDeviceError(f"could not start the audio engine: {err}")

        done = threading.Event()
        player.scheduleBuffer_completionHandler_(buffer, lambda: done.set())
        player.play()
        # Safety timeout in case the completion handler never fires. Count it
        # down only while actually playing, so a pause holds the audio open
        # instead of ending it at the original duration.
        remaining = len(floats) / play_rate + 1.0
        last = time.monotonic()
        try:
            while not done.is_set() and remaining > 0:
                if self._pump_once(player, on_input_frame):
                    break
                now = time.monotonic()
                if not self._paused:
                    remaining -= now - last
                last = now
        finally:
            input_node.removeTapOnBus_(0)
            engine.stop()


def _load_avfoundation() -> Any:  # pragma: no cover - macOS native
    try:
        import AVFoundation
    except ImportError as exc:
        raise AudioDeviceError(
            "pyobjc-framework-AVFoundation is required for echo cancellation "
            "(macOS only)."
        ) from exc
    return AVFoundation


def _make_buffer(  # pragma: no cover - native buffer marshalling
    av: Any, play_format: Any, floats: np.ndarray, channels: int
) -> Any:
    n = len(floats)
    buffer = av.AVAudioPCMBuffer.alloc().initWithPCMFormat_frameCapacity_(
        play_format, n
    )
    buffer.setFrameLength_(n)
    data = floats.astype(np.float32).tobytes()
    channel_data = buffer.floatChannelData()
    for channel in range(channels):
        channel_data[channel].as_buffer(n)[:] = data
    return buffer
