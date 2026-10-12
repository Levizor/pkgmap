import os
from pathlib import Path
from typing import Literal

import zstandard as zstd

from pkgmap.downloader import download_file
from pkgmap.logger import setup_logger

logger = setup_logger("pkgmap-db")

DatabaseVariant = Literal["full", "core"]

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "pkgmap"
DEFAULT_DB_PATH = DEFAULT_CACHE_DIR / "pkgmap.db"
DEFAULT_CORE_DB_PATH = DEFAULT_CACHE_DIR / "pkgmap-core.db"

GITHUB_RELEASE_LATEST_URL = (
    "https://github.com/Levizor/pkgmap/releases/latest/download/pkgmap.db.zst"
)
GITHUB_RELEASE_CORE_LATEST_URL = (
    "https://github.com/Levizor/pkgmap/releases/latest/download/pkgmap-core.db.zst"
)

_default_variant: DatabaseVariant = "full"


def set_default_variant(variant: DatabaseVariant) -> None:
    """Set the default database variant ('full' or 'core') for library calls."""
    global _default_variant
    if variant not in ("full", "core"):
        raise ValueError(
            f"Invalid database variant: {variant!r}. Expected 'full' or 'core'."
        )
    _default_variant = variant


def get_default_variant() -> DatabaseVariant:
    """Return the active default database variant ('full' or 'core')."""
    env_variant = os.environ.get("PKGMAP_DB_VARIANT", "").strip().lower()
    if env_variant in ("full", "core"):
        return env_variant  # type: ignore[return-value]
    return _default_variant


def resolve_cli_variant(full: bool = False, core: bool = False) -> DatabaseVariant:
    """Determine the database variant for CLI commands.

    Defaults to 'core' unless the full database is already downloaded locally
    or explicitly requested via --full or PKGMAP_DB_VARIANT=full.
    """
    if full:
        return "full"
    if core:
        return "core"
    env_variant = os.environ.get("PKGMAP_DB_VARIANT", "").strip().lower()
    if env_variant in ("full", "core"):
        return env_variant  # type: ignore[return-value]
    if DEFAULT_DB_PATH.expanduser().resolve().exists():
        return "full"
    return "core"


def get_database_url(variant: DatabaseVariant | None = None) -> str:
    """Return the GitHub release download URL for the given database variant."""
    effective = variant or get_default_variant()
    if effective == "core":
        return GITHUB_RELEASE_CORE_LATEST_URL
    return GITHUB_RELEASE_LATEST_URL


def get_database_path(
    db_path: Path | str | None = None,
    variant: DatabaseVariant | None = None,
) -> Path:
    """Resolve the path to the local package map SQLite database.

    Precedence:
    1. Explicit db_path argument
    2. PKGMAP_DB_PATH environment variable
    3. Default cache location for the selected variant:
       - 'full': ~/.cache/pkgmap/pkgmap.db
       - 'core': ~/.cache/pkgmap/pkgmap-core.db
    """
    if db_path is not None:
        return Path(db_path).expanduser().resolve()
    env_path = os.environ.get("PKGMAP_DB_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()
    effective = variant or get_default_variant()
    default_path = DEFAULT_CORE_DB_PATH if effective == "core" else DEFAULT_DB_PATH
    return default_path.expanduser().resolve()


def decompress_zstd_file(src_path: Path, dest_path: Path) -> None:
    """Stream decompress a .zst file to destination using chunked streaming."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dctx = zstd.ZstdDecompressor()
    with open(src_path, "rb") as in_fh, open(dest_path, "wb") as out_fh:
        dctx.copy_stream(in_fh, out_fh)


def update_database(
    db_path: Path | str | None = None,
    url: str | None = None,
    show_progress: bool = True,
    variant: DatabaseVariant | None = None,
) -> Path:
    """Download the latest database release from GitHub and decompress it locally."""
    target_path = get_database_path(db_path, variant=variant)
    resolved_url = url or get_database_url(variant=variant)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    compressed_tmp = target_path.with_name(f"{target_path.name}.zst.tmp")
    decompressed_tmp = target_path.with_name(f"{target_path.name}.decompressed.tmp")

    try:
        logger.info(f"Downloading latest database release from {resolved_url}")
        download_file(
            url=resolved_url,
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
    url: str | None = None,
    show_progress: bool = True,
    variant: DatabaseVariant | None = None,
) -> Path:
    """Ensure the package database exists locally, downloading it lazily if missing."""
    resolved_path = get_database_path(db_path, variant=variant)
    if resolved_path.exists():
        return resolved_path

    logger.info(
        f"Local package map database not found at {resolved_path}. Fetching release..."
    )
    return update_database(
        db_path=resolved_path,
        url=url,
        show_progress=show_progress,
        variant=variant,
    )
