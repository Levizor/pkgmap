import logging
import sys
from pathlib import Path


def setup_logger(
    name: str = "pkgmap",
    level: int = logging.INFO,
    file: bool = False,
    log_file: Path | str | None = None,
) -> logging.Logger:
    """Configure and return a logger suitable for CLI or pipeline use."""
    target_logger = logging.getLogger(name)
    target_logger.setLevel(level)
    target_logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    target_logger.addHandler(console_handler)

    if file:
        dest = log_file or f"{name}.log"
        file_handler = logging.FileHandler(dest, mode="a", encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        target_logger.addHandler(file_handler)

    return target_logger
