# pkgmap

Cross-distribution Linux package name resolution.

Different distributions often package the exact same software under different names (for example, `ninja` on Arch is `ninja-build` on Debian and Alpine; `bat` on Arch is `rust-bat` on Debian and Fedora; `fd` on Arch is `rust-fd-find` on Debian; Nixpkgs uses specific attribute paths). `pkgmap` provides an offline SQLite database and a companion Python library/CLI to translate package names between any pair of Linux distributions, resolve packages across all repositories, or look up native packages by upstream project name.

Data is updated daily from [Repology](https://repology.org) and indexed for instant local lookups. On first run, `pkgmap` automatically downloads and decompresses the latest daily database snapshot (`~/.cache/pkgmap/`).

- **PyPI**: [`pkgmap-py`](https://pypi.org/project/pkgmap-py/)
- **Web Interface**: [levizor.github.io/pkgmap](https://levizor.github.io/pkgmap/) (runs 100% client-side via SQLite WebAssembly + OPFS)

---

## CLI Usage

### Translate between distributions

Use `--from` (`-f`) and `--to` (`-t`):

```bash
# What is Arch's 'bat' called in Debian?
pkgmap resolve bat --from arch --to debian
# Output: rust-bat (0.24.0)

# What is Arch's 'fd' in Nixpkgs?
pkgmap resolve fd -f arch -t nixpkgs
# Output: fd (10.5.0)
```

### Batch resolution

Pass multiple package names to resolve them in a single query:

```bash
pkgmap resolve git gcc bat --from nix --to gnuguix
```

Output:
```text
git -> git (2.54.0)
gcc -> gcc (15.2.0)
bat -> bat (0.26.1)
```

### Resolve across all distributions

Omit `--to` to see equivalents across every indexed distribution:

```bash
pkgmap resolve bat --from arch
```

Output:
```text
alpine_edge: bat (0.24.0)
debian_unstable: rust-bat (0.24.0)
fedora_rawhide: rust-bat (0.26.1)
nix_unstable: bat (0.26.1)
ubuntu_24_04: rust-bat (0.24.0)
...
```

### Look up by upstream project name

Omit `--from` (or pass `--project` / `-p`) to resolve packages directly from an upstream project name:

```bash
pkgmap resolve ripgrep --to debian
# Output: rust-ripgrep (14.1.0)
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
    "version": "0.24.0",
    "repo": "debian_unstable",
    "repo_family": "debuntu"
  }
]
```

When multiple packages are passed with `--json`, the output is a dictionary keyed by each input package name.

### Other commands

```bash
# List available distributions and repository slugs
pkgmap repos

# Manually refresh the local database snapshot
pkgmap update

# Download the full database (all 330+ Repology repositories)
pkgmap update --full
```

---

## Core vs. Full Database Variants

`pkgmap` publishes two database snapshots with every daily release:

| Variant | File | Compressed Size | Coverage | Default For |
| :--- | :--- | :--- | :--- | :--- |
| **Core** | `pkgmap-core.db` | ~12 MB | Top 10 repositories (Nixpkgs, Arch, AUR, Debian, Ubuntu, Fedora, Alpine, openSUSE, Gentoo, Void) | **CLI & Web UI** |
| **Full** | `pkgmap.db` | ~40 MB | All 330+ Repology repositories | **Python Library** |

- **CLI behavior**: Defaults to the **Core** database (`~/.cache/pkgmap/pkgmap-core.db`) unless the Full database is already downloaded locally or `--full` is passed. If you query a repository not present in Core, the CLI prompts you to run `pkgmap update --full`. You can also pass `--core` or `--full` to any CLI command (`resolve`, `update`, `repos`).
- **Python library behavior**: Defaults to the **Full** database (`~/.cache/pkgmap/pkgmap.db`). Call `set_default_variant("core")` (or set `PKGMAP_DB_VARIANT=core`) to use the Core database instead.

---

## Python API

You can use `pkgmap` as a Python library:

```python
from pkgmap import resolve, resolve_all, resolve_batch, set_default_variant

# Optional: switch library default from 'full' to 'core'
# set_default_variant("core")

# 1. Single package resolution
res = resolve("bat", from_repo="arch", to_repo="debian")
if res:
    print(res.name, res.version)
    # Output: rust-bat 0.24.0

# 2. Query all repositories for equivalents
matches = resolve_all("bat", from_repo="arch")
for r in matches:
    print(f"{r.repo}: {r.name}")

# 3. High-performance batch resolution (executed in a single SQL query)
packages = ["bat", "fd", "ripgrep"]
results = resolve_batch(packages, from_repo="arch", to_repo="nixpkgs")

for pkg, match in results.items():
    if match:
        print(f"{pkg} -> {match.name}")
```

### API Methods

- `resolve(package, from_repo=None, to_repo=None, db_path=None)`: Resolves a package to a single match.
- `resolve_all(package, from_repo=None, to_repo=None, db_path=None)`: Returns all matching packages.
- `resolve_batch(packages, from_repo=None, to_repo=None, db_path=None)`: Resolves a sequence of packages in a single batch query, returning `{package: PackageResolution | None}`.
- `resolve_batch_all(packages, from_repo=None, to_repo=None, db_path=None)`: Batch resolution returning `{package: list[PackageResolution]}`.
- `list_repositories(db_path=None)`: Returns all repositories with package counts and families.
- `set_default_variant(variant)`: Sets the default database variant (`"full"` or `"core"`).
- `get_default_variant()`: Returns the active default database variant.

---

## Configuration

By default, databases are cached at:
- Full database: `~/.cache/pkgmap/pkgmap.db`
- Core database: `~/.cache/pkgmap/pkgmap-core.db`

You can customize behavior using environment variables:
- `PKGMAP_DB_VARIANT`: Set to `core` or `full` to override the default database variant.
- `PKGMAP_DB_PATH`: Override the database file path directly:
  ```bash
  export PKGMAP_DB_PATH="/path/to/custom/pkgmap.db"
  ```
- Or pass `--db-path` on the CLI / `db_path` in Python.

---

## Attribution

Data is sourced daily from [Repology](https://repology.org). Repology's data is published under the [CC-BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) license.
