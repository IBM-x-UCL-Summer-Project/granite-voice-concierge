# import subprocess
# import sounddevice as sd
# import soundfile as sf
# import os
# import time
#
# def test_offline_tts(text_to_speak, model_path, config_path, output_wav="test_audio.wav"):
#     print(f"Preparing to synthesize speech: '{text_to_speak}'")
#
#     # Construct the command line call for Piper
#     # --length_scale 1.2 slightly slows down the speech rate, suitable for older adults in the Independent Living scenario
#     command = [
#         "piper",
#         "-m", model_path,
#         "-c", config_path,
#         "-f", output_wav,
#         "--length_scale", "1.2"
#     ]
#
#     print("Generating audio...")
#     process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
#     process.communicate(input=text_to_speak.encode('utf-8'))
#
#     if os.path.exists(output_wav):
#         print("Audio generation complete, starting playback!")
#         # Read and play the audio
#         data, fs = sf.read(output_wav)
#         sd.play(data, fs)
#         sd.wait()  # Block execution until playback finishes
#
#         # Clean up the temporary file after playback (commented out to keep the file for STT testing)
#         # os.remove(output_wav)
#         print("Playback finished!")
#     else:
#         print("Audio generation failed.")
#
#
# if __name__ == "__main__":
#     # Replace with your actual downloaded model filenames
#     model_file = "en_GB-alan-medium.onnx"
#     config_file = "en_GB-alan-medium.onnx.json"
#     start_time = time.time()
#
#     if os.path.exists(model_file) and os.path.exists(config_file):
#         test_text = "Hello! I am your Granite voice concierge. I am running entirely offline."
#         test_offline_tts(test_text, model_file, config_file)
#         end_time = time.time()
#         print(f"Time taken: {end_time - start_time:.2f} seconds")
#     else:
#         print("Error: Cannot find TTS model files. Please ensure both the .onnx and .json files are in the current directory.")


import logging
import os
import subprocess
import time

import sounddevice as sd
import soundfile as sf

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


class OfflineTTS:
    """
    Offline Text-to-Speech (TTS) module using Piper.
    Optimized for independent living scenarios with adjustable speech pacing.
    """

    def __init__(
        self,
        model_path: str = "en_GB-alan-medium.onnx",
        config_path: str = "en_GB-alan-medium.onnx.json",
    ):
        """
        Initializes the TTS engine with the specified voice model.
        """
        self.model_path = model_path
        self.config_path = config_path

        if not os.path.exists(self.model_path) or not os.path.exists(self.config_path):
            logging.warning(
                "TTS model or config file is missing. Please ensure they are downloaded."
            )

    def speak(
        self, text: str, output_wav: str = "temp_output.wav", length_scale: float = 1.2
    ) -> bool:
        """
        Synthesizes text to speech and plays it back.

        Args:
            text (str): The text to be spoken.
            output_wav (str): Temporary file path to save the generated audio.
            length_scale (float): Controls speech speed (higher = slower).
                                  1.2 is ideal for older adults.

        Returns:
            bool: True if playback was successful, False otherwise.
        """
        logging.info(f"Synthesizing text: '{text}'")
        start_time = time.time()

        command = [
            "piper",
            "-m",
            self.model_path,
            "-c",
            self.config_path,
            "-f",
            output_wav,
            "--length_scale",
            str(length_scale),
        ]

        try:
            # Execute Piper via subprocess
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            process.communicate(input=text.encode("utf-8"))

            elapsed_time = time.time() - start_time
            logging.info(f"Audio generated in {elapsed_time:.2f} seconds.")

            if os.path.exists(output_wav):
                logging.info("Starting audio playback...")
                data, fs = sf.read(output_wav)
                sd.play(data, fs)
                sd.wait()  # Block until audio finishes

                # Cleanup
                os.remove(output_wav)
                return True
            else:
                logging.error("Expected output audio file was not created by Piper.")
                return False

        except Exception as e:
            logging.error(f"Error during TTS generation or playback: {e}")
            return False


if __name__ == "__main__":
    #  (How to use the class)
    tts_engine = OfflineTTS()
    success = tts_engine.speak(
        "Hello! I am your Granite voice concierge. I am ready to help."
    )
    if success:
        print("\n[Playback completed successfully]")
