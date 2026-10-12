import sqlite3
from pathlib import Path

import pytest

from pkgmap.resolver import (
    list_repositories,
    resolve,
    resolve_all,
    resolve_batch,
    resolve_batch_all,
    resolve_project,
    resolve_repo_name,
)


@pytest.fixture
def mock_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test_package_map.sqlite"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.executescript("""
    CREATE TABLE projects (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE NOT NULL
    );

    CREATE TABLE repositories (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        family TEXT NOT NULL,
        package_count INTEGER DEFAULT 0
    );

    CREATE TABLE repository_aliases (
        alias TEXT PRIMARY KEY,
        target_repo TEXT NOT NULL REFERENCES repositories(name)
    );

    CREATE TABLE packages (
        project_id INTEGER NOT NULL REFERENCES projects(id),
        repo_id INTEGER NOT NULL REFERENCES repositories(id),
        package_name TEXT NOT NULL,
        version TEXT,
        PRIMARY KEY (project_id, repo_id, package_name)
    ) WITHOUT ROWID;

    CREATE INDEX idx_package_name ON packages (package_name);

    INSERT INTO projects (id, name) VALUES
        (1, 'bat'),
        (2, 'ripgrep'),
        (3, 'emacs-magit'),
        (4, 'typst'),
        (5, 'haskell:typst');

    INSERT INTO repositories (id, name, family, package_count) VALUES
        (1, 'debian_12', 'debian', 100),
        (2, 'arch', 'arch', 90),
        (3, 'nix_unstable', 'nix', 150),
        (4, 'fedora_rawhide', 'fedora', 80);

    INSERT INTO repository_aliases (alias, target_repo) VALUES
        ('deb', 'debian_12');

    INSERT INTO packages (project_id, repo_id, package_name, version) VALUES
        (1, 1, 'batcat', '0.24.0'),
        (1, 2, 'bat', '0.24.0'),
        (1, 3, 'bat', '0.24.0'),
        (2, 1, 'ripgrep', '14.1.0'),
        (2, 2, 'ripgrep', '14.1.0'),
        (3, 3, 'emacsPackages.magit', '4.0.0'),
        (4, 2, 'typst', '0.15.1'),
        (5, 2, 'haskell-typst', '0.12'),
        (4, 3, 'typst', '0.15.1'),
        (5, 3, 'haskellPackages.typst', '0.12');
    """)
    conn.commit()
    conn.close()
    return db_path


def test_resolve_repo_name(mock_db: Path) -> None:
    conn = sqlite3.connect(mock_db)
    try:
        assert resolve_repo_name(conn, "debian") == "debian_12"
        assert resolve_repo_name(conn, "deb") == "debian_12"
        assert resolve_repo_name(conn, "arch") == "arch"
        assert resolve_repo_name(conn, "nixpkgs") == "nix_unstable"
        assert resolve_repo_name(conn, "fedora") == "fedora_rawhide"
        assert resolve_repo_name(conn, "debian_12") == "debian_12"
        assert resolve_repo_name(conn, "unknown_repo") == "unknown_repo"
    finally:
        conn.close()


def test_resolve_package(mock_db: Path) -> None:
    # batcat in debian -> bat in arch
    res = resolve("batcat", from_repo="debian", to_repo="arch", db_path=mock_db)
    assert res is not None
    assert res.name == "bat"
    assert res.version == "0.24.0"
    assert res.repo == "arch"
    assert res.repo_family == "arch"


def test_resolve_nix_package_name(mock_db: Path) -> None:
    res = resolve_project("emacs-magit", to_repo="nixpkgs", db_path=mock_db)
    assert len(res) == 1
    assert res[0].name == "emacsPackages.magit"
    assert res[0].repo_family == "nix"


def test_resolve_nix_typst_exact_match(mock_db: Path) -> None:
    # Exact top-level match: typst -> typst (NOT haskell-typst)
    res_top = resolve("typst", from_repo="nixpkgs", to_repo="arch", db_path=mock_db)
    assert res_top is not None
    assert res_top.name == "typst"
    assert res_top.version == "0.15.1"

    # Exact namespaced match: haskellPackages.typst -> haskell-typst
    res_haskell = resolve(
        "haskellPackages.typst",
        from_repo="nixpkgs",
        to_repo="arch",
        db_path=mock_db,
    )
    assert res_haskell is not None
    assert res_haskell.name == "haskell-typst"
    assert res_haskell.version == "0.12"

    # Reverse resolution from Arch to Nixpkgs
    res_arch_to_nix = resolve(
        "typst", from_repo="arch", to_repo="nixpkgs", db_path=mock_db
    )
    assert res_arch_to_nix is not None
    assert res_arch_to_nix.name == "typst"

    res_haskell_to_nix = resolve(
        "haskell-typst", from_repo="arch", to_repo="nixpkgs", db_path=mock_db
    )
    assert res_haskell_to_nix is not None
    assert res_haskell_to_nix.name == "haskellPackages.typst"


def test_resolve_not_found(mock_db: Path) -> None:
    res = resolve("nonexistent", from_repo="debian", to_repo="arch", db_path=mock_db)
    assert res is None

    res_all = resolve_all(
        "nonexistent", from_repo="debian", to_repo="arch", db_path=mock_db
    )
    assert res_all == []


def test_resolve_project(mock_db: Path) -> None:
    res = resolve_project("bat", to_repo="debian", db_path=mock_db)
    assert len(res) == 1
    assert res[0].name == "batcat"
    assert res[0].version == "0.24.0"


def test_resolve_all_across_all_repos(mock_db: Path) -> None:
    res = resolve_all("batcat", from_repo="debian", to_repo=None, db_path=mock_db)
    assert len(res) == 3
    repo_names = [r.repo for r in res]
    assert repo_names == ["arch", "debian_12", "nix_unstable"]


def test_resolve_project_across_all_repos(mock_db: Path) -> None:
    res = resolve_project("bat", to_repo=None, db_path=mock_db)
    assert len(res) == 3
    repo_names = [r.repo for r in res]
    assert repo_names == ["arch", "debian_12", "nix_unstable"]


def test_resolve_without_repos(mock_db: Path) -> None:
    res = resolve("bat", db_path=mock_db)
    assert res is not None
    assert res.name == "bat"
    assert res.repo == "arch"


def test_list_repositories(mock_db: Path) -> None:
    repos = list_repositories(db_path=mock_db)
    repo_names = [r.name for r in repos]
    assert "debian_12" in repo_names
    assert "arch" in repo_names
    assert "nix_unstable" in repo_names
    assert "fedora_rawhide" in repo_names
    assert len(repos) == 4


def test_resolve_batch_single_match(mock_db: Path) -> None:
    res = resolve_batch(
        ["batcat", "ripgrep", "nonexistent"],
        from_repo="debian",
        to_repo="arch",
        db_path=mock_db,
    )
    assert len(res) == 3
    assert res["batcat"] is not None
    assert res["batcat"].name == "bat"
    assert res["ripgrep"] is not None
    assert res["ripgrep"].name == "ripgrep"
    assert res["nonexistent"] is None


def test_resolve_batch_all_matches(mock_db: Path) -> None:
    res = resolve_batch_all(
        ["batcat", "nonexistent"],
        from_repo="debian",
        to_repo=None,
        db_path=mock_db,
    )
    assert len(res) == 2
    assert len(res["batcat"]) == 3
    assert [r.repo for r in res["batcat"]] == ["arch", "debian_12", "nix_unstable"]
    assert res["nonexistent"] == []


def test_resolve_batch_projects(mock_db: Path) -> None:
    res = resolve_batch(
        ["bat", "emacs-magit"],
        to_repo="nixpkgs",
        db_path=mock_db,
    )
    assert len(res) == 2
    assert res["bat"] is not None
    assert res["bat"].name == "bat"
    assert res["emacs-magit"] is not None
    assert res["emacs-magit"].name == "emacsPackages.magit"


def test_resolve_batch_empty(mock_db: Path) -> None:
    res = resolve_batch([], db_path=mock_db)
    assert res == {}
