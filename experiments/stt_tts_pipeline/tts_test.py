import subprocess
import sounddevice as sd
import soundfile as sf
import os


def test_offline_tts(text_to_speak, model_path, config_path, output_wav="test_audio.wav"):
    print(f"Preparing to synthesize speech: '{text_to_speak}'")

    # Construct the command line call for Piper
    # --length_scale 1.2 slightly slows down the speech rate, suitable for older adults in the Independent Living scenario
    command = [
        "piper",
        "-m", model_path,
        "-c", config_path,
        "-f", output_wav,
        "--length_scale", "1.2"
    ]

    print("Generating audio...")
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    process.communicate(input=text_to_speak.encode('utf-8'))

    if os.path.exists(output_wav):
        print("Audio generation complete, starting playback!")
        # Read and play the audio
        data, fs = sf.read(output_wav)
        sd.play(data, fs)
        sd.wait()  # Block execution until playback finishes

        # Clean up the temporary file after playback (commented out to keep the file for STT testing)
        # os.remove(output_wav)
        print("Playback finished!")
    else:
        print("Audio generation failed.")


if __name__ == "__main__":
    # Replace with your actual downloaded model filenames
    model_file = "en_GB-alan-medium.onnx"
    config_file = "en_GB-alan-medium.onnx.json"

    if os.path.exists(model_file) and os.path.exists(config_file):
        test_text = "Hello! I am your Granite voice concierge. I am running entirely offline."
        test_offline_tts(test_text, model_file, config_file)
    else:
        print("Error: Cannot find TTS model files. Please ensure both the .onnx and .json files are in the current directory.")