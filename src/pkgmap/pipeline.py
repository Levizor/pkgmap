import io
import logging
import os
import re
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import zstandard as zstd

from pkgmap.consumer import SQLiteConsumer
from pkgmap.downloader import download_file
from pkgmap.logger import setup_logger
from pkgmap.schema import (
    PackageRecord,
    RepoFamilyMap,
    RepologyPackageRow,
)

REPOLOGY_LATEST_DUMP_URL = (
    "https://dumps.repology.org/repology-database-dump-latest.sql.zst"
)

logger = setup_logger("pkgmap-pipeline", logging.DEBUG, file=True)

OutputConsumer = Callable[[Iterable[PackageRecord], RepoFamilyMap], None]


def fetch_latest_database_dump_link(
    url: str = REPOLOGY_LATEST_DUMP_URL,
) -> tuple[str, str]:
    """Inspect latest dump URL and return (url, date) based on HTTP Last-Modified header."""
    req = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": "pkgmap/0.1.0 (https://github.com/Levizor/pkgmap)"},
    )
    with urllib.request.urlopen(req) as resp:
        last_modified = resp.headers.get("Last-Modified")
        if last_modified:
            dump_date = parsedate_to_datetime(last_modified).strftime("%Y-%m-%d")
        else:
            dump_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    logger.info(f"Targeting latest dump from {dump_date}: {url}")
    return url, dump_date


def download_dump_file(
    dump_link: str | None = None,
    dest_dir: Path | None = None,
    show_progress: bool = True,
) -> tuple[Path, str]:
    """Download the Repology dump file and return (dump_path, dump_date)."""
    if not dump_link:
        dump_link, dump_date = fetch_latest_database_dump_link()
    else:
        match = re.search(r"(\d{4}-\d{2}-\d{2})", dump_link)
        dump_date = (
            match.group(1) if match else datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )

    target_dir = dest_dir or Path.cwd()
    parsed_path = urllib.parse.urlparse(dump_link).path
    filename = Path(urllib.parse.unquote(parsed_path)).name or "repology_dump.sql.zst"
    dest_path = target_dir / filename

    dump_path = download_file(
        url=dump_link,
        dest_path=dest_path,
        show_progress=show_progress,
        label="Downloading Repology dump",
    )
    return dump_path, dump_date


def stream_dump_lines(dump: Path) -> Iterator[str]:
    """Stream lines from a dump file (.sql.zst or plain .sql)."""
    if str(dump).endswith(".zst"):
        dctx = zstd.ZstdDecompressor()
        with open(dump, "rb") as fh:
            with dctx.stream_reader(fh) as reader:
                text_stream = io.TextIOWrapper(
                    reader, encoding="utf-8", errors="replace"
                )
                for line in text_stream:
                    yield line
    else:
        with open(dump, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                yield line


def parse_repology_records(lines: Iterable[str]) -> Iterator[RepologyPackageRow]:
    """Parse tab-separated package rows from PostgreSQL COPY stream."""
    in_packages = False
    columns: list[str] = []

    for line in lines:
        if line.startswith("COPY "):
            table_part = line[5 : line.find("(")].strip()
            table_name = table_part.split(".")[-1]
            if table_name == "packages":
                in_packages = True
                col_str = line[line.find("(") + 1 : line.rfind(")")]
                columns = [c.strip().strip('"') for c in col_str.split(",")]
                continue

        if in_packages:
            if line.startswith(r"\.") or line.startswith("\\."):
                in_packages = False
                continue

            parts = line.rstrip("\r\n").split("\t")
            row = dict(zip(columns, parts, strict=False))

            repo = row.get("repo", "")
            visiblename = row.get("visiblename", "")
            effname = row.get("effname", "")
            if not repo or not visiblename or not effname:
                continue

            yield RepologyPackageRow(
                repo=repo,
                family=row.get("family", ""),
                visiblename=visiblename,
                effname=effname,
                version=None
                if row.get("version") in (None, r"\N")
                else row.get("version"),
                category=None
                if row.get("category") in (None, r"\N")
                else row.get("category"),
                subrepo=None
                if row.get("subrepo") in (None, r"\N")
                else row.get("subrepo"),
                origversion=None
                if row.get("origversion") in (None, r"\N")
                else row.get("origversion"),
                flags=int(row["flags"]) if row.get("flags", "").isdigit() else 0,
                shadow=row.get("shadow") in ("t", "true", "1"),
            )


def do_fn(
    records: Iterable[RepologyPackageRow], repo_families: RepoFamilyMap
) -> Iterator[PackageRecord]:
    for row in records:
        if row.shadow:
            continue
        repo_families[row.repo] = row.family
        yield row.to_package_record()


def run_pipeline(dump: Path, consumer: OutputConsumer) -> None:
    lines = stream_dump_lines(dump)
    raw_records = parse_repology_records(lines)
    repo_families: RepoFamilyMap = {}
    packages = do_fn(raw_records, repo_families)
    consumer(packages, repo_families)


def set_github_output(**kwargs: str) -> None:
    """Append key-value pairs to GITHUB_OUTPUT environment file if present."""
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if not gh_output:
        return
    with open(gh_output, "a", encoding="utf-8") as f:
        for key, value in kwargs.items():
            f.write(f"{key}={value}\n")


def generate_release_notes(
    dump_date: str,
    total_packages: int,
    total_repos: int,
    output_path: Path,
) -> str:
    """Generate markdown release notes for GitHub Releases."""
    content = f"""## Repology Database Snapshot ({dump_date})

Generated offline SQLite database mapping packages across Linux distributions and repositories.

### Metadata
- **Snapshot Date**: `{dump_date}`
- **Total Packages**: `{total_packages:,}`
- **Repositories**: `{total_repos}`

### Attribution
Data sourced from [Repology](https://repology.org) database dump.
Repology is published under the [CC-BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) license.
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    logger.info(f"Generated release notes at {output_path}")
    return content


def main(
    dump_file: Path | None = None,
    dump_link: str | None = None,
    output_file: Path = Path("pkgmap.db"),
    batch_size: int = 50_000,
    release_notes: Path | None = None,
    dump_date: str | None = None,
) -> SQLiteConsumer:
    logger.debug(
        f"input arguments: {
            dict(
                {
                    'dump_file': dump_file,
                    'dump_link': dump_link,
                    'output_file': output_file,
                }
            )
        }"
    )

    if not dump_file:
        dump_file, detected_date = download_dump_file(dump_link=dump_link)
        if not dump_date:
            dump_date = detected_date
    elif not dump_date:
        match = re.search(r"(\d{4}-\d{2}-\d{2})", dump_file.name)
        dump_date = (
            match.group(1) if match else datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )

    if not dump_file.exists():
        raise FileNotFoundError(f"Dump file does not exist: {dump_file}")

    logger.info("Starting the pipeline!")
    consumer = SQLiteConsumer(output_file, batch_size)
    run_pipeline(dump_file, consumer)
    logger.info("Finished!")

    if release_notes:
        generate_release_notes(
            dump_date=dump_date,
            total_packages=consumer.total_records,
            total_repos=len(consumer.repo_ids),
            output_path=release_notes,
        )

    set_github_output(
        packages=str(consumer.total_records),
        repos=str(len(consumer.repo_ids)),
        date=dump_date,
        tag=f"db-{dump_date}",
    )

    return consumer


if __name__ == "__main__":
    main()
