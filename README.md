# pkgmap

Cross-distribution Linux package name resolution.

Different distributions often package the exact same software under different names (for example, `ninja` on Arch is `ninja-build` on Debian and Alpine; `bat` on Arch is `rust-bat` on Debian and Fedora; `fd` on Arch is `rust-fd-find` on Debian; Nixpkgs uses specific attribute paths). `pkgmap` provides an offline SQLite database and a companion Python library/CLI to translate package names between any pair of Linux distributions, resolve packages across all repositories, or look up native packages by upstream project name.

Data is updated daily from [Repology](https://repology.org) and indexed for instant local lookups. On first run, `pkgmap` automatically downloads and decompresses the latest daily database release (`~/.cache/pkgmap/pkgmap.db`).

---

## CLI Usage

### Translate between distributions

Use `--from` (`-f`) and `--to` (`-t`):

```bash
# What is Arch's 'bat' called in Debian?
pkgmap resolve bat --from arch --to debian
# Output: rust-bat (0.22.1) [category: misc]

# What is Arch's 'fd' in Nixpkgs?
pkgmap resolve fd -f arch -t nixpkgs
# Output: fd (10.5.0)
```

### Resolve across all distributions

Omit `--to` to see equivalents across every indexed distribution:

```bash
pkgmap resolve bat --from arch
```

Output:
```text
alpine_3_20: bat (0.24.0)
debian_12: rust-bat (0.22.1) [category: misc]
fedora_rawhide: rust-bat (0.26.1)
nix_unstable: bat (0.26.1)
ubuntu_24_04: rust-bat (0.24.0)
...
```

### Look up by upstream project name

Omit `--from` (or pass `--project` / `-p`) to resolve packages directly from an upstream project name:

```bash
pkgmap resolve ripgrep --to debian
# Output: rust-ripgrep (13.0.0) [category: misc]
```

### JSON output

To output machine-readable JSON (great for automation and scripts), add `--json` / `-j`:

```bash
pkgmap resolve bat -f arch -t debian --json
```

```json
[
  {
    "name": "rust-bat",
    "version": "0.22.1",
    "category": "misc",
    "repo": "debian_12",
    "repo_family": "debuntu",
    "install_name": "rust-bat"
  }
]
```

### Other commands

```bash
# List available distributions and repository slugs
pkgmap repos

# Manually refresh the local database snapshot
pkgmap update
```

---

## Python API

You can also use `pkgmap` as a Python library:

```python
from pkgmap import resolve, resolve_all, resolve_batch

# 1. Single package resolution
res = resolve("bat", from_repo="arch", to_repo="debian")
if res:
    print(res.install_name, res.version)
    # Output: rust-bat 0.22.1

# 2. Query all repositories for equivalents
matches = resolve_all("bat", from_repo="arch")
for r in matches:
    print(f"{r.repo}: {r.install_name}")

# 3. High-performance batch resolution (executed in a single SQL query)
packages = ["bat", "fd", "ripgrep"]
results = resolve_batch(packages, from_repo="arch", to_repo="nixpkgs")

for pkg, match in results.items():
    if match:
        print(f"{pkg} -> {match.install_name}")
```

### API Methods

- `resolve(package, from_repo=None, to_repo=None, db_path=None)`: Resolves a package to a single match.
- `resolve_all(package, from_repo=None, to_repo=None, db_path=None)`: Returns all matching packages.
- `resolve_batch(packages, from_repo=None, to_repo=None, db_path=None)`: Resolves a sequence of packages in a single batch query, returning `{package: PackageResolution | None}`.
- `resolve_batch_all(packages, from_repo=None, to_repo=None, db_path=None)`: Batch resolution returning `{package: list[PackageResolution]}`.
- `list_repositories(db_path=None)`: Returns all repositories with package counts and families.

---

## Configuration

By default, the database is stored at:
- `~/.cache/pkgmap/pkgmap.db`

You can customize the location using:
- The `PKGMAP_DB_PATH` environment variable:
  ```bash
  export PKGMAP_DB_PATH="/path/to/custom/pkgmap.db"
  ```
- Or the `--db-path` argument on the CLI / `db_path` parameter in Python.

---

## Attribution

Data is sourced daily from [Repology](https://repology.org). Repology's data is published under the [CC-BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) license.
