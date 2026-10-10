import os
from pathlib import Path

import zstandard as zstd

from pkgmap.downloader import download_file
from pkgmap.logger import setup_logger

logger = setup_logger("pkgmap-db")

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "pkgmap"
DEFAULT_DB_PATH = DEFAULT_CACHE_DIR / "package_map.sqlite"
GITHUB_RELEASE_LATEST_URL = (
    "https://github.com/Levizor/pkgmap/releases/latest/download/package_map.sqlite.zst"
)


def get_database_path(db_path: Path | str | None = None) -> Path:
    """Resolve the path to the package_map.sqlite database.

    Precedence:
    1. Explicit db_path argument
    2. PKGMAP_DB_PATH environment variable
    3. Default cache location: ~/.cache/pkgmap/package_map.sqlite
    """
    if db_path is not None:
        return Path(db_path).expanduser().resolve()
    env_path = os.environ.get("PKGMAP_DB_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return DEFAULT_DB_PATH.expanduser().resolve()


def decompress_zstd_file(src_path: Path, dest_path: Path) -> None:
    """Stream decompress a .zst file to destination using chunked streaming."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dctx = zstd.ZstdDecompressor()
    with open(src_path, "rb") as in_fh, open(dest_path, "wb") as out_fh:
        dctx.copy_stream(in_fh, out_fh)


def update_database(
    db_path: Path | str | None = None,
    url: str = GITHUB_RELEASE_LATEST_URL,
    show_progress: bool = True,
) -> Path:
    """Download the latest database release from GitHub and decompress it locally."""
    target_path = get_database_path(db_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    compressed_tmp = target_path.with_suffix(".sqlite.zst.tmp")
    decompressed_tmp = target_path.with_suffix(".sqlite.decompressed.tmp")

    try:
        logger.info(f"Downloading latest database release from {url}")
        download_file(
            url=url,
            dest_path=compressed_tmp,
            show_progress=show_progress,
            label="Downloading package database",
        )

        logger.info("Decompressing package database...")
        decompress_zstd_file(compressed_tmp, decompressed_tmp)

        # Atomic replacement of final database file
        decompressed_tmp.replace(target_path)
        logger.info(f"Database successfully saved to {target_path}")
        return target_path
    finally:
        if compressed_tmp.exists():
            compressed_tmp.unlink(missing_ok=True)
        if decompressed_tmp.exists():
            decompressed_tmp.unlink(missing_ok=True)


def ensure_database(
    db_path: Path | str | None = None,
    url: str = GITHUB_RELEASE_LATEST_URL,
    show_progress: bool = True,
) -> Path:
    """Ensure the package database exists locally, downloading it lazily if missing."""
    resolved_path = get_database_path(db_path)
    if resolved_path.exists():
        return resolved_path

    logger.info(
        f"Local package map database not found at {resolved_path}. Fetching release..."
    )
    return update_database(db_path=resolved_path, url=url, show_progress=show_progress)
