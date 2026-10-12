"""Cross-distribution Linux package name resolution library."""

from pkgmap.db import (
    DatabaseVariant,
    ensure_database,
    get_database_path,
    get_default_variant,
    set_default_variant,
    update_database,
)
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
    "DatabaseVariant",
    "PackageResolution",
    "ensure_database",
    "get_database_path",
    "get_default_variant",
    "list_repositories",
    "resolve",
    "resolve_all",
    "resolve_batch",
    "resolve_batch_all",
    "resolve_project",
    "set_default_variant",
    "update_database",
]
