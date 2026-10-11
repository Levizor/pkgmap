# pkgmap - Agent Instructions

This document defines core conventions, architecture, and standards for `pkgmap`.

## Repository Purpose
`pkgmap` provides an offline, queryable SQLite database and a companion Python library/CLI to resolve equivalent package names across different Linux distributions and package repositories (e.g. Debian, Ubuntu, Arch, Fedora, Alpine, Nixpkgs).

## Architecture

- **`pipeline/`**: Data extraction pipeline. Streams Repology database dumps (`.sql.zst`), extracts package-to-project mappings without loading multi-gigabyte SQL dumps into memory, and generates an optimized SQLite database (`pkgmap.db`).
- **`src/pkgmap/`**: Python client library and CLI. Manages local caching (`~/.cache/pkgmap/pkgmap.db`), lazy database downloads from GitHub releases, and provides `resolve(package, from_repo, to_repo)`.
- **`tests/`**: Unit and integration test suite using `pytest` and `tmp_path`.
- **`.github/workflows/`**: Automation workflows for periodic database generation, release publishing, and library CI.

## Database Schema
The database uses a project-centered star schema and repository metadata to enable any-to-any repository resolution with minimal storage overhead:

```sql
CREATE TABLE repositories (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,           -- canonical Repology slug, e.g. 'debian_12', 'nix_unstable'
    family TEXT NOT NULL,                -- e.g. 'debian', 'alpine', 'nix', 'arch', 'fedora'
    package_count INTEGER DEFAULT 0
);

CREATE TABLE repository_aliases (
    alias TEXT PRIMARY KEY,              -- e.g. 'debian', 'nixpkgs', 'alpine'
    target_repo TEXT NOT NULL REFERENCES repositories(name)
);

CREATE TABLE packages (
    repo_id INTEGER NOT NULL REFERENCES repositories(id),
    package_name TEXT NOT NULL,          -- native package name, e.g. 'batcat'
    effname TEXT NOT NULL,               -- canonical upstream project/effective name, e.g. 'bat'
    version TEXT,                        -- normalized upstream version, e.g. '0.24.0'
    category TEXT,                       -- category/component, e.g. 'utils'
    PRIMARY KEY (repo_id, package_name)
) WITHOUT ROWID;

CREATE INDEX idx_effname ON packages (effname);
```

Resolving a package from repo `A` to repo `B` performs an indexed self-join on `effname`:

```sql
SELECT dst.package_name, dst.version
FROM packages src
JOIN repositories src_repo ON src.repo_id = src_repo.id
JOIN packages dst ON src.effname = dst.effname
JOIN repositories dst_repo ON dst.repo_id = dst_repo.id
WHERE src_repo.name = ? AND src.package_name = ? AND dst_repo.name = ?;
```

## Implementation Standards

- **Tone & Style**: Dead simple, clear developer English. No fluff or buzzwords.
- **Minimal Comments**: Do not write comments for obvious code. Avoid numbers in comments.
- **Type Safety**: Use modern lowercase collection type hints (`list[str]`, `dict[str, Any]`, etc.).
- **Streaming & Memory Efficiency**: The pipeline must stream compressed data on the fly; never decompress the entire Repology SQL dump to disk or buffer it in memory.
- **Testing**: Test all pipeline parsers and library functions using `pytest` and `tmp_path`.
- **Attribution**: Always maintain clear attribution to Repology in documentation and release notes.
