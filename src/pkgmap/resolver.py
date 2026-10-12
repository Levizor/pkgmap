import sqlite3
from collections.abc import Sequence
from pathlib import Path

from pkgmap.db import DatabaseVariant, ensure_database
from pkgmap.schema import PackageResolution, Repository

DEFAULT_ALIASES: dict[str, str] = {
    "debian": "debian_12",
    "debian_stable": "debian_12",
    "ubuntu": "ubuntu_24_04",
    "ubuntu_lts": "ubuntu_24_04",
    "nix": "nix_unstable",
    "nixpkgs": "nix_unstable",
    "alpine": "alpine_3_20",
    "fedora": "fedora_rawhide",
    "arch": "arch",
    "archlinux": "arch",
    "void": "void_packages",
    "freebsd": "freebsd",
    "gentoo": "gentoo",
    "macports": "macports",
    "opensuse": "opensuse_tumbleweed",
}


def find_repo_name(conn: sqlite3.Connection, repo_input: str) -> str | None:
    """Find the canonical repository slug in the database, or None if not found."""
    normalized = repo_input.strip().lower().replace("-", "_")
    cursor = conn.cursor()

    # 1. Exact match in repositories
    cursor.execute("SELECT name FROM repositories WHERE name = ?", (normalized,))
    row = cursor.fetchone()
    if row:
        return str(row[0])

    # 2. Check repository_aliases table in the database
    cursor.execute(
        "SELECT target_repo FROM repository_aliases WHERE alias = ?", (normalized,)
    )
    row = cursor.fetchone()
    if row:
        return str(row[0])

    # 3. Check fallback DEFAULT_ALIASES if target exists in repositories
    if normalized in DEFAULT_ALIASES:
        fallback = DEFAULT_ALIASES[normalized]
        cursor.execute("SELECT name FROM repositories WHERE name = ?", (fallback,))
        row = cursor.fetchone()
        if row:
            return str(row[0])

    # 4. Prefix matching (e.g. 'debian' -> highest package_count debian_* repo)
    cursor.execute(
        "SELECT name FROM repositories WHERE name LIKE ? ORDER BY package_count DESC LIMIT 1",
        (f"{normalized}%",),
    )
    row = cursor.fetchone()
    if row:
        return str(row[0])

    # 5. Family matching (e.g. 'debuntu' or family name)
    cursor.execute(
        "SELECT name FROM repositories WHERE family = ? ORDER BY package_count DESC LIMIT 1",
        (normalized,),
    )
    row = cursor.fetchone()
    if row:
        return str(row[0])

    return None


def resolve_repo_name(conn: sqlite3.Connection, repo_input: str) -> str:
    """Resolve a user-supplied repository alias or name to its canonical slug."""
    return find_repo_name(conn, repo_input) or repo_input


def get_missing_repositories(
    repos: Sequence[str],
    db_path: Path | str | None = None,
    variant: DatabaseVariant | None = None,
) -> list[str]:
    """Return any repository names from `repos` that cannot be resolved in the database."""
    if not repos:
        return []
    conn = sqlite3.connect(ensure_database(db_path, variant=variant))
    try:
        return [r for r in repos if find_repo_name(conn, r) is None]
    finally:
        conn.close()


BATCH_CHUNK_SIZE = 500


def resolve_batch_all(
    packages: Sequence[str],
    from_repo: str | None = None,
    to_repo: str | None = None,
    db_path: Path | str | None = None,
    variant: DatabaseVariant | None = None,
) -> dict[str, list[PackageResolution]]:
    """Resolve a batch of packages or projects, returning all matches for each package."""
    if not packages:
        return {}

    results: dict[str, list[PackageResolution]] = {pkg: [] for pkg in packages}
    unique_pkgs = list(dict.fromkeys(packages))
    conn = sqlite3.connect(ensure_database(db_path, variant=variant))

    try:
        cursor = conn.cursor()
        src_repo = resolve_repo_name(conn, from_repo) if from_repo else None
        dst_repo = resolve_repo_name(conn, to_repo) if to_repo else None

        for i in range(0, len(unique_pkgs), BATCH_CHUNK_SIZE):
            chunk = unique_pkgs[i : i + BATCH_CHUNK_SIZE]
            placeholders = ",".join("?" for _ in chunk)

            if src_repo:
                sql = f"""
                SELECT src.package_name, dst.package_name, dst.version, dst_repo.name, dst_repo.family
                FROM packages src
                JOIN repositories src_repo ON src.repo_id = src_repo.id
                JOIN packages dst ON src.project_id = dst.project_id
                JOIN repositories dst_repo ON dst.repo_id = dst_repo.id
                WHERE src_repo.name = ? AND src.package_name IN ({placeholders})
                """
                params: list[str] = [src_repo, *chunk]
            else:
                sql = f"""
                SELECT pr.name, dst.package_name, dst.version, dst_repo.name, dst_repo.family
                FROM projects pr
                JOIN packages dst ON pr.id = dst.project_id
                JOIN repositories dst_repo ON dst.repo_id = dst_repo.id
                WHERE pr.name IN ({placeholders})
                """
                params = list(chunk)

            if dst_repo:
                sql += " AND dst_repo.name = ?"
                params.append(dst_repo)

            sql += " ORDER BY 1, dst_repo.name, dst.package_name;"

            cursor.execute(sql, params)
            for row in cursor.fetchall():
                key = row[0]
                if key in results:
                    results[key].append(
                        PackageResolution(
                            name=row[1],
                            version=row[2],
                            repo=row[3],
                            repo_family=row[4],
                        )
                    )
        return results
    finally:
        conn.close()


def resolve_batch(
    packages: Sequence[str],
    from_repo: str | None = None,
    to_repo: str | None = None,
    db_path: Path | str | None = None,
    variant: DatabaseVariant | None = None,
) -> dict[str, PackageResolution | None]:
    """Resolve a batch of packages or projects, returning the first match for each package."""
    all_res = resolve_batch_all(
        packages,
        from_repo=from_repo,
        to_repo=to_repo,
        db_path=db_path,
        variant=variant,
    )
    return {pkg: matches[0] if matches else None for pkg, matches in all_res.items()}


def resolve_all(
    package: str,
    from_repo: str | None = None,
    to_repo: str | None = None,
    db_path: Path | str | None = None,
    variant: DatabaseVariant | None = None,
) -> list[PackageResolution]:
    """Resolve all equivalent packages across target repository or all repositories."""
    return resolve_batch_all(
        [package],
        from_repo=from_repo,
        to_repo=to_repo,
        db_path=db_path,
        variant=variant,
    ).get(package, [])


def resolve(
    package: str,
    from_repo: str | None = None,
    to_repo: str | None = None,
    db_path: Path | str | None = None,
    variant: DatabaseVariant | None = None,
) -> PackageResolution | None:
    """Resolve a package or project to its primary equivalent."""
    return resolve_batch(
        [package],
        from_repo=from_repo,
        to_repo=to_repo,
        db_path=db_path,
        variant=variant,
    ).get(package)


def resolve_project(
    effname: str,
    to_repo: str | None = None,
    db_path: Path | str | None = None,
    variant: DatabaseVariant | None = None,
) -> list[PackageResolution]:
    """Resolve packages matching the canonical upstream project name."""
    return resolve_all(
        effname,
        from_repo=None,
        to_repo=to_repo,
        db_path=db_path,
        variant=variant,
    )


def list_repositories(
    db_path: Path | str | None = None,
    variant: DatabaseVariant | None = None,
) -> list[Repository]:
    """Return all repositories registered in the package database."""
    resolved_db = ensure_database(db_path, variant=variant)
    conn = sqlite3.connect(resolved_db)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, family, package_count, id FROM repositories ORDER BY name"
        )
        return [
            Repository(
                name=row[0],
                family=row[1],
                package_count=row[2],
                id=row[3],
            )
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()
