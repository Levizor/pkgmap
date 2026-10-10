import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import zstandard as zstd

from pkgmap.consumer import SQLiteConsumer
from pkgmap.pipeline import (
    do_fn,
    download_dump_file,
    download_pipeline_dump,
    fetch_latest_database_dump_link,
    generate_release_notes,
    main,
    parse_repology_records,
    run_pipeline,
    set_github_output,
    stream_dump_lines,
)
from pkgmap.schema import PackageRecord, RepoFamilyMap, RepologyPackageRow


def test_do_fn_filters_shadow_and_populates_repo_families() -> None:
    raw_records = [
        RepologyPackageRow(
            repo="debian_12",
            family="debian",
            visiblename="batcat",
            effname="bat",
            version="0.24.0",
            category="utils",
            subrepo="main",
            origversion="0.24.0",
            flags=0,
            shadow=False,
        ),
        RepologyPackageRow(
            repo="debian_12",
            family="debian",
            visiblename="batcat-shadow",
            effname="bat",
            version="0.23.0",
            category="utils",
            subrepo="backports",
            origversion="0.23.0",
            flags=0,
            shadow=True,  # Shadowed package should be excluded
        ),
        RepologyPackageRow(
            repo="arch",
            family="arch",
            visiblename="bat",
            effname="bat",
            version="0.24.0",
            category="extra",
            subrepo="core",
            origversion="0.24.0",
            flags=0,
            shadow=False,
        ),
    ]

    repo_families: RepoFamilyMap = {}
    packages = list(do_fn(raw_records, repo_families))

    assert len(packages) == 2
    assert packages[0] == PackageRecord("debian_12", "batcat", "bat", "0.24.0", "utils")
    assert packages[1] == PackageRecord("arch", "bat", "bat", "0.24.0", "extra")

    assert repo_families == {
        "debian_12": "debian",
        "arch": "arch",
    }


def test_parse_repology_records() -> None:
    # Simulated PostgreSQL COPY stream
    raw_lines = [
        "-- PostgreSQL dump",
        "COPY public.packages (repo, family, visiblename, effname, version, category, shadow) FROM stdin;",
        "debian_12\tdebian\tbatcat\tbat\t0.24.0\tutils\tf",
        "arch\tarch\tbat\tbat\t0.24.0\textra\tf",
        "arch\tarch\toldbat\tbat\t0.20.0\textra\tt",
        "\\.",
        "-- End of dump",
    ]

    records = list(parse_repology_records(raw_lines))

    assert len(records) == 3
    assert records[0].repo == "debian_12"
    assert records[0].family == "debian"
    assert records[0].visiblename == "batcat"
    assert records[0].effname == "bat"
    assert records[0].version == "0.24.0"
    assert records[0].shadow is False


def test_stream_dump_lines(tmp_path: Path) -> None:
    # Create a small compressed .sql.zst file
    sample_text = "line 1\nline 2\nline 3\n"
    dump_path = tmp_path / "sample.sql.zst"

    compressor = zstd.ZstdCompressor()
    compressed_bytes = compressor.compress(sample_text.encode("utf-8"))
    dump_path.write_bytes(compressed_bytes)

    lines = list(stream_dump_lines(dump_path))
    assert lines == ["line 1\n", "line 2\n", "line 3\n"]


def test_fetch_latest_database_dump_link() -> None:
    mock_resp = MagicMock()
    mock_resp.headers = {"Last-Modified": "Fri, 09 Oct 2026 04:11:39 GMT"}
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        link, dump_date = fetch_latest_database_dump_link()
        req = mock_urlopen.call_args[0][0]
        assert req.get_method() == "HEAD"

    assert link == "https://dumps.repology.org/repology-database-dump-latest.sql.zst"
    assert dump_date == "2026-10-09"


def test_download_dump_file(tmp_path: Path) -> None:
    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Length": "38"}
    mock_resp.read.side_effect = [b"compressed chunk 1", b"compressed chunk 2", b""]
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        dest = download_dump_file(
            "https://example.com/test.sql.zst", dest_dir=tmp_path, show_progress=False
        )

    assert isinstance(dest, Path)
    assert dest.exists()
    assert dest.read_bytes() == b"compressed chunk 1compressed chunk 2"


def test_run_pipeline_integration(tmp_path: Path) -> None:
    # 1. Compress mock SQL lines to a temporary .sql.zst file
    mock_sql = (
        "COPY public.packages (repo, family, visiblename, effname, version, category, shadow) FROM stdin;\n"
        "debian_12\tdebian\tbatcat\tbat\t0.24.0\tutils\tf\n"
        "arch\tarch\tbat\tbat\t0.24.0\textra\tf\n"
        "nix_unstable\tnix\tbat\tbat\t0.24.0\ttools\tf\n"
        "debian_12\tdebian\tbat-old\tbat\t0.20.0\tutils\tt\n"
        "\\.\n"
    )
    dump_path = tmp_path / "mock_dump.sql.zst"
    compressor = zstd.ZstdCompressor()
    dump_path.write_bytes(compressor.compress(mock_sql.encode("utf-8")))

    output_db = tmp_path / "package_map.sqlite"
    consumer = SQLiteConsumer(output_file=output_db, batch_size=2)

    # 2. Run the pipeline
    run_pipeline(dump=dump_path, consumer=consumer)

    # 3. Verify SQLite database was generated properly
    assert output_db.exists()

    conn = sqlite3.connect(output_db)
    cursor = conn.cursor()

    cursor.execute("SELECT count(*) FROM packages")
    assert cursor.fetchone()[0] == 3  # Shadow record filtered out

    cursor.execute("SELECT name, package_count FROM repositories ORDER BY name")
    repos = cursor.fetchall()
    assert repos == [("arch", 1), ("debian_12", 1), ("nix_unstable", 1)]

    # 4. Verify resolution query works on generated database
    cursor.execute(
        """
        SELECT dst.visiblename, dst.version
        FROM packages src
        JOIN repositories src_repo ON src.repo_id = src_repo.id
        JOIN packages dst ON src.effname = dst.effname
        JOIN repositories dst_repo ON dst.repo_id = dst_repo.id
        WHERE src_repo.name = ? AND src.visiblename = ? AND dst_repo.name = ?;
        """,
        ("debian_12", "batcat", "nix_unstable"),
    )
    assert cursor.fetchone() == ("bat", "0.24.0")
    conn.close()


def test_generate_release_notes(tmp_path: Path) -> None:
    notes_file = tmp_path / "release_notes.md"
    content = generate_release_notes(
        dump_date="2026-10-10",
        total_packages=3_500_000,
        total_repos=283,
        output_path=notes_file,
    )

    assert notes_file.exists()
    assert "2026-10-10" in content
    assert "3,500,000" in content
    assert "283" in content
    assert "Repology" in content


def test_set_github_output(tmp_path: Path, monkeypatch) -> None:
    output_file = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

    set_github_output(date="2026-10-10", tag="db-2026-10-10")

    assert output_file.exists()
    lines = output_file.read_text().splitlines()
    assert "date=2026-10-10" in lines
    assert "tag=db-2026-10-10" in lines


def test_download_pipeline_dump_with_override(tmp_path: Path) -> None:
    mock_file = tmp_path / "custom.sql.zst"
    mock_file.write_bytes(b"mock")

    with patch("pkgmap.pipeline.download_dump_file", return_value=mock_file):
        dest, date_str = download_pipeline_dump(
            dump_link="https://example.com/repology-database-dump-2026-10-09.sql.zst",
            dest_dir=tmp_path,
        )

    assert dest == mock_file
    assert date_str == "2026-10-09"


def test_pipeline_main_with_release_notes(tmp_path: Path, monkeypatch) -> None:
    # Create sample dump
    sample_sql = (
        "COPY public.packages (repo, family, visiblename, effname, version, category, shadow) FROM stdin;\n"
        "debian_12\tdebian\tbatcat\tbat\t0.24.0\tutils\tf\n"
        "\\.\n"
    )
    dump_file = tmp_path / "repology-database-dump-2026-10-09.sql.zst"
    compressor = zstd.ZstdCompressor()
    dump_file.write_bytes(compressor.compress(sample_sql.encode("utf-8")))

    output_db = tmp_path / "out.sqlite"
    release_notes = tmp_path / "notes.md"
    gh_output = tmp_path / "gh.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_output))

    consumer = main(
        dump_file=dump_file,
        output_file=output_db,
        batch_size=10,
        release_notes=release_notes,
    )

    assert consumer.total_records == 1
    assert release_notes.exists()
    assert "2026-10-09" in release_notes.read_text()
    assert "tag=db-2026-10-09" in gh_output.read_text()
