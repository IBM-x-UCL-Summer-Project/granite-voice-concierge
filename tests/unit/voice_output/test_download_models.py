"""Tests for explicit Piper voice model downloads."""

from pathlib import Path
from unittest.mock import Mock, call, patch

import pytest

from voice_concierge.voice_output import download_models


def test_downloads_each_selected_voice_to_output_directory(tmp_path: Path) -> None:
    downloader = Mock()

    paths = download_models.download_piper_voices(
        ["en_GB-alan-medium", "en_US-lessac-medium"],
        tmp_path,
        downloader=downloader,
    )

    assert downloader.call_args_list == [
        call("en_GB-alan-medium", tmp_path),
        call("en_US-lessac-medium", tmp_path),
    ]
    assert paths == (
        (
            tmp_path / "en_GB-alan-medium.onnx",
            tmp_path / "en_GB-alan-medium.onnx.json",
        ),
        (
            tmp_path / "en_US-lessac-medium.onnx",
            tmp_path / "en_US-lessac-medium.onnx.json",
        ),
    )


def test_rejects_empty_voice_selection(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="At least one"):
        download_models.download_piper_voices([], tmp_path)


@patch("voice_concierge.voice_output.download_models.download_piper_voices")
def test_cli_downloads_default_voice(mock_download: Mock, tmp_path: Path) -> None:
    result = download_models.main(["--output-directory", str(tmp_path)])

    assert result == 0
    mock_download.assert_called_once_with(
        ["en_GB-alan-medium"],
        tmp_path,
    )


@patch("voice_concierge.voice_output.download_models.list_voices")
def test_cli_can_list_upstream_voices(mock_list: Mock) -> None:
    result = download_models.main(["--list"])

    assert result == 0
    mock_list.assert_called_once_with()
