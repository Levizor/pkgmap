import sqlite3
from pathlib import Path

from pkgmap.consumer import SQLiteConsumer, build_core_database, load_repos_config
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
        ),
        PackageRecord(
            repo="arch",
            package_name="bat",
            effname="bat",
            version="0.24.0",
        ),
        PackageRecord(
            repo="debian_12",
            package_name="ripgrep",
            effname="ripgrep",
            version="14.1.0",
        ),
        PackageRecord(
            repo="nix_unstable",
            package_name="ripgrep",
            effname="ripgrep",
            version="14.1.0",
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

    # Check packages and projects tables
    cursor.execute(
        """
        SELECT r.name, p.package_name, pr.name, p.version
        FROM packages p
        JOIN repositories r ON p.repo_id = r.id
        JOIN projects pr ON p.project_id = pr.id
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

    # Check projects table existence
    cursor.execute("SELECT name FROM projects ORDER BY name")
    projects = [r[0] for r in cursor.fetchall()]
    assert projects == ["bat", "ripgrep"]

    # Check repository_aliases populated from repos.toml
    cursor.execute("SELECT target_repo FROM repository_aliases WHERE alias = 'nixpkgs'")
    assert cursor.fetchone() == ("nix_unstable",)

    # Check index existence
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_package_name'"
    )
    assert cursor.fetchone() is not None

    # Test cross-repo resolution self-join query
    cursor.execute(
        """
        SELECT dst.package_name, dst.version
        FROM packages src
        JOIN repositories src_repo ON src.repo_id = src_repo.id
        JOIN packages dst ON src.project_id = dst.project_id
        JOIN repositories dst_repo ON dst.repo_id = dst_repo.id
        WHERE src_repo.name = ? AND src.package_name = ? AND dst_repo.name = ?;
        """,
        ("debian_12", "batcat", "arch"),
    )
    result = cursor.fetchone()
    assert result == ("bat", "0.24.0")

    conn.close()


def test_load_default_repos_config() -> None:
    core_repos, aliases = load_repos_config()
    assert len(core_repos) == 20
    assert "nix_unstable" in core_repos
    assert "debian_unstable" in core_repos
    assert "fedora" in core_repos
    assert aliases["nixpkgs"] == "nix_unstable"
    assert aliases["debian"] == "debian_unstable"


def test_build_core_database_filters_repos_and_projects(tmp_path: Path) -> None:
    full_db = tmp_path / "pkgmap.db"
    core_db = tmp_path / "pkgmap-core.db"

    consumer = SQLiteConsumer(output_file=full_db)
    records = [
        PackageRecord("debian_unstable", "batcat", "bat", "0.24.0"),
        PackageRecord("nix_unstable", "bat", "bat", "0.24.0"),
        # Versioned prefix: fedora_42 has 2 packages, fedora_41 has 1 -> fedora_42 selected
        PackageRecord("fedora_42", "bat", "bat", "0.24.0"),
        PackageRecord("fedora_42", "ripgrep", "ripgrep", "14.1.0"),
        PackageRecord("fedora_41", "bat", "bat", "0.23.0"),
        # Non-core repository with an exclusive project that should be pruned in core
        PackageRecord("haikuports_master", "haiku_only_pkg", "haiku-only", "1.0"),
    ]
    repo_families: RepoFamilyMap = {
        "debian_unstable": "debian",
        "nix_unstable": "nix",
        "fedora_42": "fedora",
        "fedora_41": "fedora",
        "haikuports_master": "haikuports",
    }
    consumer(records, repo_families)

    core_packages, core_repos = build_core_database(full_db, core_db)
    assert core_repos == 3
    assert core_packages == 4

    conn = sqlite3.connect(core_db)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM repositories ORDER BY name")
    assert [r[0] for r in cursor.fetchall()] == [
        "debian_unstable",
        "fedora_42",
        "nix_unstable",
    ]

    cursor.execute("SELECT name FROM projects ORDER BY name")
    assert [r[0] for r in cursor.fetchall()] == ["bat", "ripgrep"]

    cursor.execute(
        "SELECT alias, target_repo FROM repository_aliases WHERE alias IN ('debian', 'fedora', 'nixpkgs') ORDER BY alias"
    )
    assert cursor.fetchall() == [
        ("debian", "debian_unstable"),
        ("fedora", "fedora_42"),
        ("nixpkgs", "nix_unstable"),
    ]
    conn.close()
