# pkgmap - Agent Instructions

This document defines core conventions, architecture, and standards for `pkgmap`.

## Repository Purpose
`pkgmap` provides an offline, queryable SQLite database and a companion Python library/CLI to resolve equivalent package names across different Linux distributions and package repositories (e.g. Debian, Ubuntu, Arch, Fedora, Alpine, Nixpkgs).

## Architecture

- **`pipeline/`**: Data extraction pipeline. Streams Repology database dumps (`.sql.zst`), extracts package-to-project mappings without loading multi-gigabyte SQL dumps into memory, and generates an optimized SQLite database (`package_map.sqlite`).
- **`src/pkgmap/`**: Python client library and CLI. Manages local caching (`~/.cache/pkgmap/package_map.sqlite`), lazy database downloads from GitHub releases, and provides `resolve(package, from_repo, to_repo)`.
- **`tests/`**: Unit and integration test suite using `pytest` and `tmp_path`.
- **`.github/workflows/`**: Automation workflows for periodic database generation, release publishing, and library CI.

## Database Schema
The database uses a project-centered star schema and repository metadata to enable any-to-any repository resolution with minimal storage overhead:

```sql
CREATE TABLE repositories (
    name TEXT PRIMARY KEY,               -- canonical Repology slug, e.g. 'debian_12', 'nix_unstable'
    family TEXT NOT NULL,                -- e.g. 'debian', 'alpine', 'nix', 'arch', 'fedora'
    package_count INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE repository_aliases (
    alias TEXT PRIMARY KEY,              -- e.g. 'debian', 'nixpkgs', 'alpine'
    target_repo TEXT NOT NULL REFERENCES repositories(name)
);

CREATE TABLE packages (
    repo TEXT NOT NULL,                  -- foreign key to repositories(name)
    package_name TEXT NOT NULL,          -- native package name, e.g. 'batcat'
    project TEXT NOT NULL,               -- canonical upstream project, e.g. 'bat'
    version TEXT,                        -- normalized upstream version, e.g. '0.24.0'
    category TEXT,                       -- category/component, e.g. 'utils'
    PRIMARY KEY (repo, package_name)
);

CREATE INDEX idx_project ON packages (project);
```

Resolving a package from repo `A` to repo `B` performs an indexed self-join on `project`:

```sql
SELECT dst.package_name, dst.version
FROM packages src
JOIN packages dst ON src.project = dst.project
WHERE src.repo = ? AND src.package_name = ? AND dst.repo = ?;
```

## Implementation Standards

- **Tone & Style**: Dead simple, clear developer English. No fluff or buzzwords.
- **Minimal Comments**: Do not write comments for obvious code. Avoid numbers in comments.
- **Type Safety**: Use modern lowercase collection type hints (`list[str]`, `dict[str, Any]`, etc.).
- **Streaming & Memory Efficiency**: The pipeline must stream compressed data on the fly; never decompress the entire Repology SQL dump to disk or buffer it in memory.
- **Testing**: Test all pipeline parsers and library functions using `pytest` and `tmp_path`.
- **Attribution**: Always maintain clear attribution to Repology in documentation and release notes.
