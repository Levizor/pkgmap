import sqlite3
from collections.abc import Iterable
from pathlib import Path

from pkgmap.logger import setup_logger
from pkgmap.schema import PackageRecord, RepoFamilyMap, Repository

logger = setup_logger("pkgmap-consumer")

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

SELECT_REPO_COUNTS_QUERY = "SELECT repo_id, COUNT(*) FROM packages GROUP BY repo_id"

CREATE_INDEX_PKGNAME_QUERY = (
    "CREATE INDEX IF NOT EXISTS idx_package_name ON packages (package_name);"
)


class SQLiteConsumer:
    def __init__(self, output_file: Path, batch_size: int = 50_000) -> None:
        self.output_file = output_file
        self.batch_size = batch_size
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
