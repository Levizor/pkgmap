"""Cross-distribution Linux package name resolution library."""

from pkgmap.db import ensure_database, get_database_path, update_database
from pkgmap.resolver import (
    PackageResolution,
    list_repositories,
    resolve,
    resolve_all,
    resolve_batch,
    resolve_batch_all,
    resolve_project,
)

__version__ = "0.1.0"
__all__ = [
    "PackageResolution",
    "ensure_database",
    "get_database_path",
    "list_repositories",
    "resolve",
    "resolve_all",
    "resolve_batch",
    "resolve_batch_all",
    "resolve_project",
    "update_database",
]
