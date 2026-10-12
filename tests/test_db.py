from pathlib import Path
from unittest.mock import patch

import pytest
import zstandard as zstd

from pkgmap.db import (
    DEFAULT_CORE_DB_PATH,
    DEFAULT_DB_PATH,
    GITHUB_RELEASE_CORE_LATEST_URL,
    GITHUB_RELEASE_LATEST_URL,
    decompress_zstd_file,
    ensure_database,
    get_database_path,
    get_database_url,
    get_default_variant,
    resolve_cli_variant,
    set_default_variant,
    update_database,
)


def test_get_database_path_explicit() -> None:
    path = Path("/custom/path/db.sqlite")
    assert get_database_path(path) == path.resolve()


def test_get_database_path_env_var(monkeypatch) -> None:
    monkeypatch.setenv("PKGMAP_DB_PATH", "/env/path/pkg.sqlite")
    assert get_database_path() == Path("/env/path/pkg.sqlite").resolve()


def test_get_database_path_default(monkeypatch) -> None:
    monkeypatch.delenv("PKGMAP_DB_PATH", raising=False)
    monkeypatch.delenv("PKGMAP_DB_VARIANT", raising=False)
    set_default_variant("full")
    assert get_database_path() == DEFAULT_DB_PATH.expanduser().resolve()
    assert (
        get_database_path(variant="core") == DEFAULT_CORE_DB_PATH.expanduser().resolve()
    )


def test_set_default_variant_and_urls(monkeypatch) -> None:
    monkeypatch.delenv("PKGMAP_DB_PATH", raising=False)
    monkeypatch.delenv("PKGMAP_DB_VARIANT", raising=False)
    try:
        set_default_variant("core")
        assert get_default_variant() == "core"
        assert get_database_path() == DEFAULT_CORE_DB_PATH.expanduser().resolve()
        assert get_database_url() == GITHUB_RELEASE_CORE_LATEST_URL
        assert get_database_url(variant="full") == GITHUB_RELEASE_LATEST_URL

        with pytest.raises(ValueError):
            set_default_variant("invalid")  # type: ignore[arg-type]
    finally:
        set_default_variant("full")


def test_resolve_cli_variant(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("PKGMAP_DB_VARIANT", raising=False)
    fake_full = tmp_path / "pkgmap.db"
    monkeypatch.setattr("pkgmap.db.DEFAULT_DB_PATH", fake_full)

    # When full DB does not exist locally, CLI defaults to 'core'
    assert resolve_cli_variant() == "core"
    assert resolve_cli_variant(full=True) == "full"

    # Once full DB exists locally, CLI defaults to 'full' unless --core is passed
    fake_full.write_bytes(b"sqlite")
    assert resolve_cli_variant() == "full"
    assert resolve_cli_variant(core=True) == "core"


def test_decompress_zstd_file(tmp_path: Path) -> None:
    original_data = b"SQLite format 3\x00test-database-content"
    cctx = zstd.ZstdCompressor()
    compressed_data = cctx.compress(original_data)

    compressed_file = tmp_path / "test.sqlite.zst"
    compressed_file.write_bytes(compressed_data)

    decompressed_file = tmp_path / "test.sqlite"
    decompress_zstd_file(compressed_file, decompressed_file)

    assert decompressed_file.read_bytes() == original_data


def test_update_database(tmp_path: Path) -> None:
    target_db = tmp_path / "pkg.sqlite"
    original_content = b"fake sqlite content"
    compressed_content = zstd.ZstdCompressor().compress(original_content)

    def fake_download_file(
        url: str, dest_path: Path, show_progress: bool, label: str
    ) -> None:
        dest_path.write_bytes(compressed_content)

    with patch("pkgmap.db.download_file", side_effect=fake_download_file):
        result_path = update_database(db_path=target_db, show_progress=False)
        assert result_path == target_db.resolve()
        assert target_db.read_bytes() == original_content


def test_ensure_database_already_exists(tmp_path: Path) -> None:
    existing_db = tmp_path / "existing.sqlite"
    existing_db.write_bytes(b"existing content")

    with patch("pkgmap.db.update_database") as mock_update:
        res = ensure_database(db_path=existing_db)
        assert res == existing_db.resolve()
        mock_update.assert_not_called()


def test_ensure_database_fetches_when_missing(tmp_path: Path) -> None:
    missing_db = tmp_path / "missing.sqlite"

    with patch(
        "pkgmap.db.update_database", return_value=missing_db.resolve()
    ) as mock_update:
        res = ensure_database(db_path=missing_db)
        assert res == missing_db.resolve()
        mock_update.assert_called_once()
