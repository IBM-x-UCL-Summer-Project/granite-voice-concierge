import os
from faster_whisper import WhisperModel


def test_offline_stt(audio_path):
    print("Loading offline STT model (faster-whisper)...")
    # Using base.en model, running on CPU only, with int8 quantization to significantly reduce memory usage
    model = WhisperModel("base.en", device="cpu", compute_type="int8")
    print("Model loaded successfully! Starting transcription...\n")

    # vad_filter=True automatically filters out silent parts
    segments, info = model.transcribe(audio_path, beam_size=5, vad_filter=True)

    print(f"Detected language: {info.language} (Confidence: {info.language_probability:.2f})")

    full_text = ""
    for segment in segments:
        print(f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}")
        full_text += segment.text + " "

    print("\n--- Final Transcription Result ---")
    print(full_text.strip())


if __name__ == "__main__":
    # Ensure your test audio file exists
    audio_file = "test_audio.wav"

    if os.path.exists(audio_file):
        test_offline_stt(audio_file)
    else:
        print(f"Error: Cannot find test audio file '{audio_file}'. Please place an audio file here first.")