import json
from pathlib import Path

from typer.testing import CliRunner

from pkgmap.cli import cli_app

runner = CliRunner()


def test_cli_resolve_success(tmp_path: Path) -> None:
    # Use test_resolver fixture logic to create a test DB
    import sqlite3

    db_path = tmp_path / "test_cli.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
    CREATE TABLE repositories (id INTEGER PRIMARY KEY, name TEXT UNIQUE, family TEXT, package_count INTEGER);
    CREATE TABLE repository_aliases (alias TEXT PRIMARY KEY, target_repo TEXT);
    CREATE TABLE packages (repo_id INTEGER, package_name TEXT, effname TEXT, version TEXT, PRIMARY KEY (repo_id, package_name)) WITHOUT ROWID;
    CREATE INDEX idx_effname ON packages (effname);

    INSERT INTO repositories VALUES (1, 'debian_12', 'debian', 10), (2, 'arch', 'arch', 10);
    INSERT INTO packages VALUES (1, 'batcat', 'bat', '0.24.0'), (2, 'bat', 'bat', '0.24.0');
    """)
    conn.commit()
    conn.close()

    result = runner.invoke(
        cli_app,
        [
            "resolve",
            "batcat",
            "--from",
            "debian",
            "--to",
            "arch",
            "--db-path",
            str(db_path),
        ],
    )
    assert result.exit_code == 0
    assert "bat (0.24.0)" in result.stdout


def test_cli_resolve_json(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "test_cli.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
    CREATE TABLE repositories (id INTEGER PRIMARY KEY, name TEXT UNIQUE, family TEXT, package_count INTEGER);
    CREATE TABLE repository_aliases (alias TEXT PRIMARY KEY, target_repo TEXT);
    CREATE TABLE packages (repo_id INTEGER, package_name TEXT, effname TEXT, version TEXT, PRIMARY KEY (repo_id, package_name)) WITHOUT ROWID;
    CREATE INDEX idx_effname ON packages (effname);

    INSERT INTO repositories VALUES (1, 'debian_12', 'debian', 10), (2, 'arch', 'arch', 10);
    INSERT INTO packages VALUES (1, 'batcat', 'bat', '0.24.0'), (2, 'bat', 'bat', '0.24.0');
    """)
    conn.commit()
    conn.close()

    result = runner.invoke(
        cli_app,
        [
            "resolve",
            "batcat",
            "--from",
            "debian",
            "--to",
            "arch",
            "--json",
            "--db-path",
            str(db_path),
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert len(data) == 1
    assert data[0]["name"] == "bat"


def test_cli_resolve_not_found(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "test_cli.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
    CREATE TABLE repositories (id INTEGER PRIMARY KEY, name TEXT UNIQUE, family TEXT, package_count INTEGER);
    CREATE TABLE repository_aliases (alias TEXT PRIMARY KEY, target_repo TEXT);
    CREATE TABLE packages (repo_id INTEGER, package_name TEXT, effname TEXT, version TEXT, PRIMARY KEY (repo_id, package_name)) WITHOUT ROWID;
    """)
    conn.commit()
    conn.close()

    result = runner.invoke(
        cli_app,
        [
            "resolve",
            "nonexistent",
            "--from",
            "debian",
            "--to",
            "arch",
            "--db-path",
            str(db_path),
        ],
    )
    assert result.exit_code == 1
    assert "No equivalent package found" in result.stdout


def test_cli_repos(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "test_cli.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
    CREATE TABLE repositories (id INTEGER PRIMARY KEY, name TEXT UNIQUE, family TEXT, package_count INTEGER);
    CREATE TABLE repository_aliases (alias TEXT PRIMARY KEY, target_repo TEXT);
    CREATE TABLE packages (repo_id INTEGER, package_name TEXT, effname TEXT, version TEXT, PRIMARY KEY (repo_id, package_name)) WITHOUT ROWID;

    INSERT INTO repositories VALUES (1, 'debian_12', 'debian', 50000);
    """)
    conn.commit()
    conn.close()

    result = runner.invoke(cli_app, ["repos", "--db-path", str(db_path)])
    assert result.exit_code == 0
    assert "debian_12" in result.stdout
    assert "50,000" in result.stdout


def test_cli_resolve_project_implicit(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "test_cli.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
    CREATE TABLE repositories (id INTEGER PRIMARY KEY, name TEXT UNIQUE, family TEXT, package_count INTEGER);
    CREATE TABLE repository_aliases (alias TEXT PRIMARY KEY, target_repo TEXT);
    CREATE TABLE packages (repo_id INTEGER, package_name TEXT, effname TEXT, version TEXT, PRIMARY KEY (repo_id, package_name)) WITHOUT ROWID;
    CREATE INDEX idx_effname ON packages (effname);

    INSERT INTO repositories VALUES (1, 'debian_12', 'debian', 10);
    INSERT INTO packages VALUES (1, 'batcat', 'bat', '0.24.0');
    """)
    conn.commit()
    conn.close()

    # --from is omitted; should resolve by upstream project name 'bat' to 'batcat' in debian
    result = runner.invoke(
        cli_app,
        ["resolve", "bat", "--to", "debian", "--db-path", str(db_path)],
    )
    assert result.exit_code == 0
    assert "batcat (0.24.0)" in result.stdout


def test_cli_resolve_project_explicit_flag(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "test_cli.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
    CREATE TABLE repositories (id INTEGER PRIMARY KEY, name TEXT UNIQUE, family TEXT, package_count INTEGER);
    CREATE TABLE repository_aliases (alias TEXT PRIMARY KEY, target_repo TEXT);
    CREATE TABLE packages (repo_id INTEGER, package_name TEXT, effname TEXT, version TEXT, PRIMARY KEY (repo_id, package_name)) WITHOUT ROWID;
    CREATE INDEX idx_effname ON packages (effname);

    INSERT INTO repositories VALUES (1, 'debian_12', 'debian', 10);
    INSERT INTO packages VALUES (1, 'batcat', 'bat', '0.24.0');
    """)
    conn.commit()
    conn.close()

    # Explicit -p / --project flag
    result = runner.invoke(
        cli_app,
        ["resolve", "-p", "bat", "-t", "debian", "--db-path", str(db_path)],
    )
    assert result.exit_code == 0
    assert "batcat (0.24.0)" in result.stdout


def test_cli_resolve_from_and_project_conflict(tmp_path: Path) -> None:
    result = runner.invoke(
        cli_app,
        ["resolve", "bat", "-f", "debian", "-p", "-t", "arch"],
    )
    assert result.exit_code == 2
    assert "Cannot specify both --from and --project" in result.stdout


def test_cli_resolve_all_repos_without_flags(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "test_cli.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
    CREATE TABLE repositories (id INTEGER PRIMARY KEY, name TEXT UNIQUE, family TEXT, package_count INTEGER);
    CREATE TABLE repository_aliases (alias TEXT PRIMARY KEY, target_repo TEXT);
    CREATE TABLE packages (repo_id INTEGER, package_name TEXT, effname TEXT, version TEXT, PRIMARY KEY (repo_id, package_name)) WITHOUT ROWID;
    CREATE INDEX idx_effname ON packages (effname);

    INSERT INTO repositories VALUES (1, 'debian_12', 'debian', 10), (2, 'arch', 'arch', 10);
    INSERT INTO packages VALUES (1, 'batcat', 'bat', '0.24.0'), (2, 'bat', 'bat', '0.24.0');
    """)
    conn.commit()
    conn.close()

    result = runner.invoke(
        cli_app,
        ["resolve", "bat", "--db-path", str(db_path)],
    )
    assert result.exit_code == 0
    assert "arch: bat (0.24.0)" in result.stdout
    assert "debian_12: batcat (0.24.0)" in result.stdout


def test_cli_resolve_all_repos_with_from(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "test_cli.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
    CREATE TABLE repositories (id INTEGER PRIMARY KEY, name TEXT UNIQUE, family TEXT, package_count INTEGER);
    CREATE TABLE repository_aliases (alias TEXT PRIMARY KEY, target_repo TEXT);
    CREATE TABLE packages (repo_id INTEGER, package_name TEXT, effname TEXT, version TEXT, PRIMARY KEY (repo_id, package_name)) WITHOUT ROWID;
    CREATE INDEX idx_effname ON packages (effname);

    INSERT INTO repositories VALUES (1, 'debian_12', 'debian', 10), (2, 'arch', 'arch', 10);
    INSERT INTO packages VALUES (1, 'batcat', 'bat', '0.24.0'), (2, 'bat', 'bat', '0.24.0');
    """)
    conn.commit()
    conn.close()

    result = runner.invoke(
        cli_app,
        ["resolve", "batcat", "-f", "debian", "--db-path", str(db_path)],
    )
    assert result.exit_code == 0
    assert "arch: bat (0.24.0)" in result.stdout
    assert "debian_12: batcat (0.24.0)" in result.stdout


def test_cli_resolve_all_repos_json(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "test_cli.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
    CREATE TABLE repositories (id INTEGER PRIMARY KEY, name TEXT UNIQUE, family TEXT, package_count INTEGER);
    CREATE TABLE repository_aliases (alias TEXT PRIMARY KEY, target_repo TEXT);
    CREATE TABLE packages (repo_id INTEGER, package_name TEXT, effname TEXT, version TEXT, PRIMARY KEY (repo_id, package_name)) WITHOUT ROWID;
    CREATE INDEX idx_effname ON packages (effname);

    INSERT INTO repositories VALUES (1, 'debian_12', 'debian', 10), (2, 'arch', 'arch', 10);
    INSERT INTO packages VALUES (1, 'batcat', 'bat', '0.24.0'), (2, 'bat', 'bat', '0.24.0');
    """)
    conn.commit()
    conn.close()

    result = runner.invoke(
        cli_app,
        ["resolve", "bat", "--json", "--db-path", str(db_path)],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert len(data) == 2
    repos = [item["repo"] for item in data]
    assert repos == ["arch", "debian_12"]


def test_cli_resolve_all_repos_not_found(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "test_cli.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
    CREATE TABLE repositories (id INTEGER PRIMARY KEY, name TEXT UNIQUE, family TEXT, package_count INTEGER);
    CREATE TABLE repository_aliases (alias TEXT PRIMARY KEY, target_repo TEXT);
    CREATE TABLE packages (repo_id INTEGER, package_name TEXT, effname TEXT, version TEXT, PRIMARY KEY (repo_id, package_name)) WITHOUT ROWID;
    """)
    conn.commit()
    conn.close()

    result = runner.invoke(
        cli_app,
        ["resolve", "nonexistent", "--db-path", str(db_path)],
    )
    assert result.exit_code == 1
    assert "No equivalent package found for project 'nonexistent'." in result.stdout
