import logging
import os
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def download_file(url: str, dest_path: str):
    """
    Downloads a file from a URL to a specified destination.
    Skips downloading if the file already exists.
    """
    if os.path.exists(dest_path):
        logging.info(f"File already exists, skipping download: {dest_path}")
        return

    logging.info(f"Downloading {url} \n -> to {dest_path}...")
    try:
        urllib.request.urlretrieve(url, dest_path)
        logging.info("Download complete.")
    except Exception as e:
        logging.error(f"Failed to download {url}. Error: {e}")


if __name__ == "__main__":
    # Define model URLs
    onnx_url = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx"
    json_url = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx.json"

    # Define local destination paths
    current_dir = os.path.dirname(os.path.abspath(__file__))
    onnx_dest = os.path.join(current_dir, "en_GB-alan-medium.onnx")
    json_dest = os.path.join(current_dir, "en_GB-alan-medium.onnx.json")

    # Execute downloads
    logging.info("Checking Piper TTS model dependencies...")
    download_file(onnx_url, onnx_dest)
    download_file(json_url, json_dest)
    logging.info("All model dependencies are ready.")
