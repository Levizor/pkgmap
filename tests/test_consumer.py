import sqlite3
from pathlib import Path

from pkgmap.consumer import SQLiteConsumer
from pkgmap.schema import PackageRecord, RepoFamilyMap


def test_sqlite_consumer_ingestion(tmp_path: Path) -> None:
    db_file = tmp_path / "test_pkgmap.db"
    consumer = SQLiteConsumer(output_file=db_file, batch_size=2)

    records = [
        PackageRecord(
            repo="debian_12",
            package_name="batcat",
            effname="bat",
            version="0.24.0",
            category="utils",
        ),
        PackageRecord(
            repo="arch",
            package_name="bat",
            effname="bat",
            version="0.24.0",
            category="extra",
        ),
        PackageRecord(
            repo="debian_12",
            package_name="ripgrep",
            effname="ripgrep",
            version="14.1.0",
            category="utils",
        ),
        PackageRecord(
            repo="nix_unstable",
            package_name="ripgrep",
            effname="ripgrep",
            version="14.1.0",
            category="tools",
        ),
    ]

    repo_families: RepoFamilyMap = {
        "debian_12": "debian",
        "arch": "arch",
        "nix_unstable": "nix",
    }

    consumer(records, repo_families)

    assert db_file.exists()

    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    # Check packages table
    cursor.execute(
        """
        SELECT r.name, p.package_name, p.effname, p.version
        FROM packages p
        JOIN repositories r ON p.repo_id = r.id
        ORDER BY r.name, p.package_name
        """
    )
    packages = cursor.fetchall()
    assert len(packages) == 4
    assert packages[0] == ("arch", "bat", "bat", "0.24.0")
    assert packages[1] == ("debian_12", "batcat", "bat", "0.24.0")

    # Check repositories table aggregation
    cursor.execute("SELECT name, family, package_count FROM repositories ORDER BY name")
    repos = cursor.fetchall()
    assert len(repos) == 3
    assert repos[0] == ("arch", "arch", 1)
    assert repos[1] == ("debian_12", "debian", 2)
    assert repos[2] == ("nix_unstable", "nix", 1)

    # Check index existence
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_effname'"
    )
    assert cursor.fetchone() is not None

    # Test cross-repo resolution self-join query
    cursor.execute(
        """
        SELECT dst.package_name, dst.version
        FROM packages src
        JOIN repositories src_repo ON src.repo_id = src_repo.id
        JOIN packages dst ON src.effname = dst.effname
        JOIN repositories dst_repo ON dst.repo_id = dst_repo.id
        WHERE src_repo.name = ? AND src.package_name = ? AND dst_repo.name = ?;
        """,
        ("debian_12", "batcat", "arch"),
    )
    result = cursor.fetchone()
    assert result == ("bat", "0.24.0")

    conn.close()
