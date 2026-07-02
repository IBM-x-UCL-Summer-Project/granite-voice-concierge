# import os
# from faster_whisper import WhisperModel
# import time
#
#
#
# def test_offline_stt(audio_path):
#     print("Loading offline STT model (faster-whisper)...")
#     # Using base.en model, running on CPU only, with int8 quantization to significantly reduce memory usage
#     model = WhisperModel("base.en", device="cpu", compute_type="int8")
#     print("Model loaded successfully! Starting transcription...\n")
#
#     # vad_filter=True automatically filters out silent parts
#     segments, info = model.transcribe(audio_path, beam_size=5, vad_filter=True)
#
#     print(f"Detected language: {info.language} (Confidence: {info.language_probability:.2f})")
#
#     full_text = ""
#     for segment in segments:
#         print(f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}")
#         full_text += segment.text + " "
#
#     print("\n--- Final Transcription Result ---")
#     print(full_text.strip())
#
#
# if __name__ == "__main__":
#     # Ensure your test audio file exists
#     audio_file = "test_audio.wav"
#     start_time = time.time()
#
#     if os.path.exists(audio_file):
#         test_offline_stt(audio_file)
#         end_time = time.time()
#         print(f"Time taken: {end_time - start_time:.2f} seconds")
#     else:
#         print(f"Error: Cannot find test audio file '{audio_file}'. Please place an audio file here first.")


import logging
import os
import time

from faster_whisper import WhisperModel

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


class OfflineSTT:
    """
    Offline Speech-to-Text (STT) module using faster-whisper.
    Designed for low-latency edge deployment.
    """

    def __init__(
        self,
        model_size: str = "base.en",
        device: str = "cpu",
        compute_type: str = "int8",
    ):
        """
        Initializes the STT model and loads it into memory.
        """
        logging.info(f"Loading STT model '{model_size}' into memory...")
        try:
            self.model = WhisperModel(
                model_size, device=device, compute_type=compute_type
            )
            logging.info("STT model loaded successfully.")
        except Exception as e:
            logging.error(f"Failed to load STT model: {e}")
            raise

    def transcribe(
        self, audio_path: str, beam_size: int = 5, vad_filter: bool = True
    ) -> str:
        """
        Transcribes the given audio file to text.

        Args:
            audio_path (str): The file path to the audio file (.wav).
            beam_size (int): Beam size for transcription.
            vad_filter (bool): Whether to use Voice Activity Detection to filter silence.

        Returns:
            str: The transcribed text.
        """
        if not os.path.exists(audio_path):
            logging.error(f"Audio file not found: {audio_path}")
            return ""

        start_time = time.time()
        logging.info("Starting transcription...")

        try:
            segments, info = self.model.transcribe(
                audio_path, beam_size=beam_size, vad_filter=vad_filter
            )
            logging.info(
                f"Detected language: {info.language} (Confidence: {info.language_probability:.2f})"
            )

            full_text = " ".join([segment.text for segment in segments])

            elapsed_time = time.time() - start_time
            logging.info(f"Transcription completed in {elapsed_time:.2f} seconds.")

            return full_text.strip()

        except Exception as e:
            logging.error(f"Error during transcription: {e}")
            return ""


if __name__ == "__main__":
    #  (How to use the class)
    stt_engine = OfflineSTT()
    result = stt_engine.transcribe("test_audio.wav")
    print(f"\n[Final Output]: {result}")
