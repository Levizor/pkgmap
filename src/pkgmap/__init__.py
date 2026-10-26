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
from pkgmap.schema import normalize_nix_package_name

__version__ = "0.2.0"
__all__ = [
    "DatabaseVariant",
    "PackageResolution",
    "ensure_database",
    "get_database_path",
    "get_default_variant",
    "list_repositories",
    "normalize_nix_package_name",
    "resolve",
    "resolve_all",
    "resolve_batch",
    "resolve_batch_all",
    "resolve_project",
    "set_default_variant",
    "update_database",
]
