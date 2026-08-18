"""Hear the difference streaming makes, and measure it.

Runs the same request twice against the local model. The blocking pass waits for
the whole reply before saying anything, which is what the app does today. The
streaming pass speaks each sentence as the model finishes writing it.

Run it as a module from the repository root, so the ``src`` layout resolves:

    python -m scripts.demo_streaming_speech
    python -m scripts.demo_streaming_speech --prompt "how do I poach an egg"
    python -m scripts.demo_streaming_speech --silent   # measure, do not speak

The number that matters is time to first audio. Total time barely moves, because
the same words still have to be generated and spoken; what changes is how long
the user sits in silence first.
"""

# Standard library
import argparse
import json
import sys
import time
import urllib.request
from collections.abc import Iterator

# Local
from voice_concierge.reasoning.ollama import _StructuredReasoningResponse
from voice_concierge.reasoning.streaming_json import SpokenResponseExtractor
from voice_concierge.voice_output.sentences import SentenceAccumulator
from voice_concierge.voice_output.streaming import StreamingSpeaker

DEFAULT_PROMPT = "Talk me through making scrambled eggs, step by step."
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


def _raw_chunks(prompt: str, model: str) -> Iterator[str]:
    """Yield raw JSON fragments from the model as they arrive."""
    with urllib.request.urlopen(_request(prompt, model, stream=True), timeout=300) as r:
        for line in r:
            if not line.strip():
                continue
            piece = json.loads(line).get("message", {}).get("content", "")
            if piece:
                yield piece


def _spoken_text_stream(prompt: str, model: str) -> Iterator[str]:
    """Yield the spoken field of the reply as the model writes it."""
    extractor = SpokenResponseExtractor()
    for chunk in _raw_chunks(prompt, model):
        text = extractor.feed(chunk)
        if text:
            yield text
        if extractor.finished:
            return


def _build_voice(silent: bool, *, use_piper: bool = False):
    """Return a text-to-speech backend and player, or None when silent.

    Uses macOS `say` rather than the factory default, which is Piper. Piper is
    broken on macOS arm64 (issue #52) and raises on every synthesis, so the
    default would measure the cost of failing rather than of speaking. Every
    other demo in this directory makes the same substitution.
    """
    if silent:
        return None, None
    from voice_concierge.audio.player import SoundDevicePlayer

    if use_piper:
        from voice_concierge.voice_output.factory import build_text_to_speech

        return build_text_to_speech(), SoundDevicePlayer()

    from voice_concierge.voice_output.say import SayTextToSpeech

    return SayTextToSpeech(), SoundDevicePlayer()


def run_blocking(
    prompt: str, model: str, *, silent: bool, use_piper: bool = False
) -> None:
    """Wait for the entire reply, then speak it. Today's behaviour."""
    print("\n--- BLOCKING (what the app does now) ---")
    tts, player = _build_voice(silent, use_piper=use_piper)
    start = time.perf_counter()

    with urllib.request.urlopen(
        _request(prompt, model, stream=False), timeout=300
    ) as response:
        payload = json.loads(json.loads(response.read())["message"]["content"])
    reply = payload["spoken_response"]
    generated_at = time.perf_counter() - start
    print(f"  reply ready after {generated_at:.2f}s ({len(reply)} chars)")

    if tts is not None and player is not None:
        player.play(tts.synthesize(reply))
    first_audio = time.perf_counter() - start

    print(f"  TIME TO FIRST AUDIO : {first_audio:.2f}s")
    print(f"  total               : {time.perf_counter() - start:.2f}s")


def run_streaming(
    prompt: str, model: str, *, silent: bool, use_piper: bool = False
) -> None:
    """Speak each sentence as soon as the model finishes it."""
    print("\n--- STREAMING (this branch) ---")
    tts, player = _build_voice(silent, use_piper=use_piper)
    start = time.perf_counter()
    first_audio: float | None = None

    def announce(sentence: str) -> None:
        nonlocal first_audio
        if first_audio is None:
            first_audio = time.perf_counter() - start
            print(f"  first sentence ready after {first_audio:.2f}s")
        print(f"  > {sentence}")

    if tts is None or player is None:
        # Measure the sentence boundaries without a voice attached.
        accumulator = SentenceAccumulator()
        for chunk in _spoken_text_stream(prompt, model):
            for sentence in accumulator.feed(chunk):
                announce(sentence)
        for sentence in accumulator.flush():
            announce(sentence)
    else:
        StreamingSpeaker(tts, player, on_sentence=announce).speak_stream(
            _spoken_text_stream(prompt, model)
        )

    if first_audio is None:
        print("  nothing was said — is the model returning the expected schema?")
        return

    print(f"  TIME TO FIRST AUDIO : {first_audio:.2f}s")
    print(f"  total               : {time.perf_counter() - start:.2f}s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--silent", action="store_true", help="Measure timings without speaking."
    )
    parser.add_argument(
        "--streaming-only", action="store_true", help="Skip the blocking baseline."
    )
    parser.add_argument(
        "--piper",
        action="store_true",
        help="Use the factory default Piper voice, which is broken on macOS arm64.",
    )
    args = parser.parse_args(argv)

    print(f'Prompt: "{args.prompt}"')
    print(f"Model : {args.model}")
    print("Warming the model so the first pass is not paying for a cold load...")
    try:
        with urllib.request.urlopen(
            _request("hello", args.model, stream=False), timeout=300
        ) as response:
            response.read()
    except OSError as exc:
        print(f"Could not reach Ollama at {HOST}: {exc}", file=sys.stderr)
        return 1

    if not args.streaming_only:
        run_blocking(args.prompt, args.model, silent=args.silent, use_piper=args.piper)
    run_streaming(args.prompt, args.model, silent=args.silent, use_piper=args.piper)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
