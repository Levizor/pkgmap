import sqlite3
import tomllib
from collections.abc import Iterable
from pathlib import Path

from pkgmap.logger import setup_logger
from pkgmap.schema import PackageRecord, RepoFamilyMap, Repository

logger = setup_logger("pkgmap-consumer")

DEFAULT_REPOS_CONFIG = Path(__file__).with_name("repos.toml")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS repositories (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    family TEXT NOT NULL,
    package_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS repository_aliases (
    alias TEXT PRIMARY KEY,
    target_repo TEXT NOT NULL REFERENCES repositories(name)
);
CREATE TABLE IF NOT EXISTS packages (
    project_id INTEGER NOT NULL REFERENCES projects(id),
    repo_id INTEGER NOT NULL REFERENCES repositories(id),
    package_name TEXT NOT NULL,
    version TEXT,
    PRIMARY KEY (project_id, repo_id, package_name)
) WITHOUT ROWID;
"""

INSERT_PROJECTS_QUERY = "INSERT OR IGNORE INTO projects (id, name) VALUES (?, ?)"
INSERT_PACKAGES_QUERY = (
    "INSERT OR IGNORE INTO packages (project_id, repo_id, package_name, version) "
    "VALUES (?, ?, ?, ?)"
)

INSERT_REPOSITORIES_QUERY = "INSERT OR REPLACE INTO repositories (id, name, family, package_count) VALUES (?, ?, ?, ?)"
INSERT_ALIASES_QUERY = (
    "INSERT OR REPLACE INTO repository_aliases (alias, target_repo) VALUES (?, ?)"
)

SELECT_REPO_COUNTS_QUERY = "SELECT repo_id, COUNT(*) FROM packages GROUP BY repo_id"

CREATE_INDEX_PKGNAME_QUERY = (
    "CREATE INDEX IF NOT EXISTS idx_package_name ON packages (package_name);"
)


def load_repos_config(
    config_path: Path | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Load core repository specs and alias mappings from repos.toml."""
    path = config_path or DEFAULT_REPOS_CONFIG
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    core_repos: list[str] = list(data.get("core", {}).get("repositories", []))
    aliases: dict[str, str] = dict(data.get("aliases", {}))
    return core_repos, aliases


def resolve_repo_spec(
    conn: sqlite3.Connection, spec: str, table: str = "repositories"
) -> tuple[int, str] | None:
    """Resolve a repository spec by exact slug or highest package_count prefix match."""
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT id, name FROM {table}
        WHERE name = ? OR name LIKE ?
        ORDER BY (name = ?) DESC, package_count DESC
        LIMIT 1
        """,
        (spec, f"{spec}_%", spec),
    )
    row = cursor.fetchone()
    return (int(row[0]), str(row[1])) if row else None


def populate_repository_aliases(
    conn: sqlite3.Connection, aliases: dict[str, str]
) -> None:
    """Populate the repository_aliases table from configured alias mappings."""
    rows: list[tuple[str, str]] = []
    for alias, target_spec in aliases.items():
        match = resolve_repo_spec(conn, target_spec)
        if match:
            rows.append((alias, match[1]))
    if rows:
        conn.executemany(INSERT_ALIASES_QUERY, rows)
        conn.commit()


class SQLiteConsumer:
    def __init__(
        self,
        output_file: Path,
        batch_size: int = 50_000,
        repos_config: Path | None = None,
    ) -> None:
        self.output_file = output_file
        self.batch_size = batch_size
        self.repos_config = repos_config
        self.batch_counter = 0
        self.total_records = 0
        self.repo_ids: dict[str, int] = {}
        self.project_ids: dict[str, int] = {}

    def init_db_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(SCHEMA_SQL)

    def send_batch(self, conn: sqlite3.Connection, batch: list[PackageRecord]) -> None:
        self.batch_counter += 1
        self.total_records += len(batch)
        logger.info(
            f"Sending batch {self.batch_counter} (size={len(batch):,}, total={self.total_records:,})"
        )
        new_projects: list[tuple[int, str]] = []
        rows: list[tuple[int, int, str, str | None]] = []

        for pkg in batch:
            if pkg.effname not in self.project_ids:
                proj_id = len(self.project_ids) + 1
                self.project_ids[pkg.effname] = proj_id
                new_projects.append((proj_id, pkg.effname))
            else:
                proj_id = self.project_ids[pkg.effname]

            repo_id = self.repo_ids.setdefault(pkg.repo, len(self.repo_ids) + 1)
            rows.append((proj_id, repo_id, pkg.package_name, pkg.version))

        if new_projects:
            conn.executemany(INSERT_PROJECTS_QUERY, new_projects)

        conn.executemany(INSERT_PACKAGES_QUERY, rows)
        conn.commit()
        batch.clear()
        logger.info(
            f"Batch {self.batch_counter} saved ({self.total_records:,} records committed so far)."
        )

    def populate_repositories(
        self, conn: sqlite3.Connection, repo_families: RepoFamilyMap
    ) -> None:
        cursor = conn.cursor()
        cursor.execute(SELECT_REPO_COUNTS_QUERY)
        counts = dict(cursor.fetchall())
        for repo_name in repo_families:
            if repo_name not in self.repo_ids:
                self.repo_ids[repo_name] = len(self.repo_ids) + 1

        repositories = [
            Repository(
                id=repo_id,
                name=repo_name,
                family=repo_families.get(repo_name, "unknown"),
                package_count=counts.get(repo_id, 0),
            )
            for repo_name, repo_id in sorted(
                self.repo_ids.items(), key=lambda item: item[1]
            )
        ]
        cursor.executemany(
            INSERT_REPOSITORIES_QUERY,
            [(r.id, r.name, r.family, r.package_count) for r in repositories],
        )
        conn.commit()

    def __call__(
        self, records: Iterable[PackageRecord], repo_families: RepoFamilyMap
    ) -> None:
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        self.repo_ids = {}
        self.project_ids = {}
        conn = sqlite3.connect(self.output_file)

        # WAL mode: Appends writes sequentially to a write-ahead log rather than altering the main DB
        # file directly with rollback journals, providing high write throughput for bulk ingestion.
        conn.execute("PRAGMA journal_mode = WAL;")

        # NORMAL sync: Syncs WAL to disk at checkpoint intervals rather than blocking on every
        # batch commit with hardware fsync, eliminating disk I/O bottlenecks.
        conn.execute("PRAGMA synchronous = NORMAL;")

        self.init_db_schema(conn)

        batch: list[PackageRecord] = []
        for pkg in records:
            batch.append(pkg)
            if len(batch) >= self.batch_size:
                self.send_batch(conn, batch)

        if batch:
            self.send_batch(conn, batch)

        self.populate_repositories(conn, repo_families)
        _, aliases = load_repos_config(self.repos_config)
        populate_repository_aliases(conn, aliases)

        conn.execute(CREATE_INDEX_PKGNAME_QUERY)
        conn.commit()

        # Checkpoint WAL: Merges all pages from the write-ahead log back into the main database
        # file and truncates the WAL file, leaving a clean, self-contained single .sqlite file.
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")

        # VACUUM: Rebuilds the database file into a contiguous structure and reclaims unallocated pages.
        conn.execute("VACUUM;")
        conn.close()

        logger.info(
            f"Database generation complete: {self.total_records:,} packages saved to {self.output_file}"
        )


def build_core_database(
    full_db_path: Path,
    core_db_path: Path,
    config_path: Path | None = None,
) -> tuple[int, int]:
    """Extract the core subset database from a full pkgmap SQLite database."""
    core_specs, aliases = load_repos_config(config_path)
    core_db_path.parent.mkdir(parents=True, exist_ok=True)
    if core_db_path.exists():
        core_db_path.unlink()

    conn = sqlite3.connect(core_db_path)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.executescript(SCHEMA_SQL)

    conn.execute("ATTACH DATABASE ? AS full", (str(full_db_path),))

    repo_ids: list[int] = []
    for spec in core_specs:
        match = resolve_repo_spec(conn, spec, table="full.repositories")
        if match and match[0] not in repo_ids:
            repo_ids.append(match[0])
        elif not match:
            logger.warning(
                f"Core repository spec '{spec}' did not match any repository"
            )

    if repo_ids:
        placeholders = ",".join("?" for _ in repo_ids)
        conn.execute(
            f"INSERT INTO repositories SELECT * FROM full.repositories WHERE id IN ({placeholders})",
            repo_ids,
        )
        conn.execute(
            f"INSERT INTO packages SELECT * FROM full.packages WHERE repo_id IN ({placeholders})",
            repo_ids,
        )
        conn.execute(
            """
            INSERT INTO projects
            SELECT id, name FROM full.projects
            WHERE id IN (SELECT DISTINCT project_id FROM packages)
            """
        )

    populate_repository_aliases(conn, aliases)
    conn.execute(CREATE_INDEX_PKGNAME_QUERY)
    conn.commit()

    total_packages = int(conn.execute("SELECT COUNT(*) FROM packages").fetchone()[0])
    total_repos = int(conn.execute("SELECT COUNT(*) FROM repositories").fetchone()[0])

    conn.execute("DETACH DATABASE full")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    conn.execute("VACUUM;")
    conn.close()

    logger.info(
        f"Core database generation complete: {total_packages:,} packages across "
        f"{total_repos} repositories saved to {core_db_path}"
    )
    return total_packages, total_repos
