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
                "TTS model or config file is missing. "
                "Please ensure they are downloaded."
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

    def stop(self) -> bool:
        """Stop active playback when the audio backend supports it."""
        try:
            sd.stop()
            return True
        except Exception as e:
            logging.error(f"Error stopping TTS playback: {e}")
            return False


if __name__ == "__main__":
    #  (How to use the class)
    tts_engine = OfflineTTS()
    success = tts_engine.speak(
        "Hello! I am your Granite voice concierge. I am ready to help."
    )
    if success:
        print("\n[Playback completed successfully]")
