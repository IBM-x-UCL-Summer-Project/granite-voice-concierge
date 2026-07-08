"""Manual smoke test: wake word -> VAD -> STT, printing the transcript.

Run from the repo root inside the project venv:

    .venv/bin/python scripts/demo_voice_input.py

Say the wake word ("hey jarvis"), then speak a command. Press Ctrl+C to stop.
First run downloads the openWakeWord and Whisper models.
"""

from voice_concierge.audio import CapturedAudio
from voice_concierge.voice_input import build_voice_input_pipeline
from voice_concierge.voice_input.stt import build_speech_to_text


def main() -> None:
    print("Loading speech-to-text model (first run downloads it)...")
    stt = build_speech_to_text()
    pipeline = build_voice_input_pipeline()

    def on_utterance_captured(audio: CapturedAudio) -> None:
        print(
            f"Captured {len(audio.samples)} samples "
            f"({audio.duration_seconds:.1f}s) — transcribing..."
        )
        transcript = stt.transcribe(audio)
        print(f"\n>>> Transcript: {transcript.text!r}")
        if transcript.language:
            print(
                f"    (language: {transcript.language}, "
                f"p={transcript.language_probability:.2f})\n"
            )

    print("Say the wake word ('hey jarvis'), then speak. Ctrl+C to quit.\n")
    pipeline.run(on_utterance_captured=on_utterance_captured)


if __name__ == "__main__":
    main()
