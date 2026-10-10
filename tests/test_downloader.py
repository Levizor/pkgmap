from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pkgmap.downloader import download_file


def test_download_file_with_progress(tmp_path: Path) -> None:
    dest_path = tmp_path / "subdir" / "sample.db"
    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Length": "20"}
    mock_resp.read.side_effect = [b"1234567890", b"abcdefghij", b""]
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = download_file(
            url="https://example.com/sample.db",
            dest_path=dest_path,
            show_progress=True,
            label="Testing download",
            chunk_size=10,
        )

    assert result == dest_path
    assert dest_path.exists()
    assert dest_path.read_bytes() == b"1234567890abcdefghij"
    assert not dest_path.with_name(f"{dest_path.name}.tmp").exists()


def test_download_file_cleanup_on_error(tmp_path: Path) -> None:
    dest_path = tmp_path / "corrupt.db"
    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Length": "100"}
    mock_resp.read.side_effect = RuntimeError("Network stream broke")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="Network stream broke"):
            download_file(
                url="https://example.com/broken.db",
                dest_path=dest_path,
                show_progress=False,
            )

    assert not dest_path.exists()
    assert not dest_path.with_name(f"{dest_path.name}.tmp").exists()
