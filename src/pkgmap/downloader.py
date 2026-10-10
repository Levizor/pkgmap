import urllib.parse
import urllib.request
from pathlib import Path

import typer

from pkgmap.logger import setup_logger

logger = setup_logger("pkgmap-downloader")


def download_file(
    url: str,
    dest_path: Path,
    show_progress: bool = True,
    label: str = "Downloading",
    chunk_size: int = 1024 * 1024,
) -> Path:
    """Download a file with streaming chunks and optional Typer progress bar.

    Writes to a temporary `.tmp` file and atomically renames on completion to
    prevent corrupt or partial files.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Downloading from {url} to {dest_path}")

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "pkgmap/0.1.0 (https://github.com/levizor/pkgmap)"},
    )

    temp_path = dest_path.with_name(f"{dest_path.name}.tmp")
    try:
        with urllib.request.urlopen(req) as response:
            content_length = getattr(response, "headers", {}).get("Content-Length")
            total_size = (
                int(content_length)
                if isinstance(content_length, str) and content_length.isdigit()
                else None
            )

            if show_progress and total_size is not None:
                with typer.progressbar(
                    length=total_size,
                    label=label,
                    show_eta=True,
                    show_percent=True,
                ) as progress:
                    with open(temp_path, "wb") as out_file:
                        while chunk := response.read(chunk_size):
                            out_file.write(chunk)
                            progress.update(len(chunk))
            else:
                with open(temp_path, "wb") as out_file:
                    while chunk := response.read(chunk_size):
                        out_file.write(chunk)

        temp_path.replace(dest_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    logger.info(f"Download complete: {dest_path}")
    return dest_path
