"""Speak a question, hear how long the silence is before the answer starts.

The point of comparison is time to first audio: how long you sit in silence
after finishing your question. Streaming does not make the reply shorter, it
starts speaking it sooner.

    python scripts/demo_streaming_voice.py                 # streaming
    python scripts/demo_streaming_voice.py --blocking      # today's behaviour
    python scripts/demo_streaming_voice.py --wake-word     # say "hey jarvis" first

No wake word by default: just speak when prompted and stop, and the utterance
ends on silence. Run it once each way and the difference is obvious by ear.

Uses macOS `say` rather than the factory default, which is Piper and raises on
every synthesis on macOS arm64 (issue #52).
"""

# Standard library
import argparse
import json
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Local
from voice_concierge.app.live import (  # noqa: E402
    LiveAppConfig,
    build_utterance_capturer,
    build_wake_word_listener,
)
from voice_concierge.audio import CapturedAudio  # noqa: E402
from voice_concierge.audio.player import SoundDevicePlayer  # noqa: E402
from voice_concierge.reasoning.ollama import (  # noqa: E402
    _StructuredReasoningResponse,
)
from voice_concierge.reasoning.streaming_json import (  # noqa: E402
    SpokenResponseExtractor,
)
from voice_concierge.voice_input.stt.factory import (  # noqa: E402
    build_speech_to_text,
)
from voice_concierge.voice_output.say import SayTextToSpeech  # noqa: E402
from voice_concierge.voice_output.streaming import StreamingSpeaker  # noqa: E402

DEFAULT_MODEL = "granite4.1:8b"
HOST = "http://localhost:11434/api/chat"


def _request(prompt: str, model: str, *, stream: bool) -> urllib.request.Request:
    """Build the same structured-output request the app makes."""
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "format": _StructuredReasoningResponse.model_json_schema(),
            "stream": stream,
        }
    ).encode()
    return urllib.request.Request(HOST, body, {"Content-Type": "application/json"})


def _spoken_text_stream(prompt: str, model: str) -> Iterator[str]:
    """Yield the spoken field of the reply as the model writes it."""
    extractor = SpokenResponseExtractor()
    with urllib.request.urlopen(_request(prompt, model, stream=True), timeout=300) as r:
        for line in r:
            if not line.strip():
                continue
            piece = json.loads(line).get("message", {}).get("content", "")
            if not piece:
                continue
            text = extractor.feed(piece)
            if text:
                yield text
            if extractor.finished:
                return


def _answer_blocking(prompt: str, model: str, tts, player, start: float) -> None:
    """Wait for the whole reply, then speak it. What the app does today."""
    with urllib.request.urlopen(
        _request(prompt, model, stream=False), timeout=300
    ) as response:
        payload = json.loads(json.loads(response.read())["message"]["content"])
    reply = payload["spoken_response"]
    print(f"  (reply generated after {time.perf_counter() - start:.2f}s)")
    print(f"  Assistant: {reply}")

    audio = tts.synthesize(reply)
    first_audio = time.perf_counter() - start
    player.play(audio)
    _report(first_audio, start)


def _answer_streaming(prompt: str, model: str, tts, player, start: float) -> None:
    """Speak each sentence as the model finishes writing it."""
    first_audio: float | None = None

    def announce(sentence: str) -> None:
        nonlocal first_audio
        if first_audio is None:
            first_audio = time.perf_counter() - start
        print(f"  Assistant: {sentence}")

    StreamingSpeaker(tts, player, on_sentence=announce).speak_stream(
        _spoken_text_stream(prompt, model)
    )

    if first_audio is None:
        print("  Nothing was said — did the model return the expected schema?")
        return
    _report(first_audio, start)


def _report(first_audio: float, start: float) -> None:
    """Print the only two numbers worth comparing between the two modes."""
    print()
    print(f"  >>> SILENCE BEFORE THE REPLY STARTED : {first_audio:.2f}s")
    print(
        f"  >>> finished speaking after          : {time.perf_counter() - start:.2f}s"
    )
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--blocking",
        action="store_true",
        help="Wait for the whole reply before speaking, as the app does now.",
    )
    parser.add_argument(
        "--wake-word", action="store_true", help='Require "hey jarvis" each turn.'
    )
    args = parser.parse_args(argv)

    mode = "BLOCKING (today)" if args.blocking else "STREAMING"
    print(f"Mode: {mode}")
    print("Loading models (the first run may download them)...")

    config = LiveAppConfig(download_wake_models=args.wake_word)
    stt = build_speech_to_text()
    tts = SayTextToSpeech()
    player = SoundDevicePlayer()
    capturer = build_utterance_capturer(config)
    listener = build_wake_word_listener(config) if args.wake_word else None

    print("Warming the model so the first answer is not paying for a cold load...")
    try:
        with urllib.request.urlopen(
            _request("hello", args.model, stream=False), timeout=300
        ) as response:
            response.read()
    except OSError as exc:
        print(f"Could not reach Ollama at {HOST}: {exc}", file=sys.stderr)
        return 1

    answer = _answer_blocking if args.blocking else _answer_streaming

    def one_turn() -> None:
        captured: list[CapturedAudio] = []
        capturer.capture_utterance(on_utterance_captured=captured.append)
        if not captured:
            print("  (heard nothing)")
            return

        # The clock starts the moment you stop speaking, because that is when
        # the waiting begins from the user's side.
        start = time.perf_counter()
        transcript = stt.transcribe(captured[0]).text.strip()
        if not transcript:
            print("  (could not make out any words)")
            return
        print(f"  You: {transcript}")
        answer(transcript, args.model, tts, player, start)

    print("\nReady. Ask it something, then stop talking. Ctrl+C to finish.\n")
    try:
        while True:
            if listener is not None:
                print('Say "hey jarvis"...')
                listener.listen(on_wake_word=one_turn)
            else:
                print("Speak now...")
                one_turn()
    except KeyboardInterrupt:
        print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
