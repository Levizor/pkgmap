import re
from typing import NamedTuple


class Repository(NamedTuple):
    name: str
    family: str
    package_count: int = 0
    id: int | None = None


class RepositoryAlias(NamedTuple):
    alias: str
    target_repo: str


type RepoFamilyMap = dict[str, str]


class PackageRecord(NamedTuple):
    repo: str
    package_name: str  # native package name
    effname: str  # unique project name, same for all packages
    version: str | None = None


class PackageResolution(NamedTuple):
    name: str
    version: str | None = None
    repo: str = ""
    repo_family: str = ""


# Upstream Repology PostgreSQL schema definition:
# https://github.com/repology/repology-updater/blob/master/sql.d/schema/create_schema_tables.sql
REPOLOGY_SCHEMA_URL = "https://github.com/repology/repology-updater/blob/master/sql.d/schema/create_schema_tables.sql"


def normalize_nix_package_name(name: str) -> str:
    """Normalize Nix package names by stripping unwrapped derivation markers."""
    return re.sub(r"-unwrapped(?=($|[\"_-]))", "", name)


class RepologyPackageRow(NamedTuple):
    """Repology 'packages' table row schema extracted from PostgreSQL dumps.

    Reference:
    https://github.com/repology/repology-updater/blob/master/sql.d/schema/create_schema_tables.sql#L31-L75
    """

    repo: str
    family: str
    visiblename: str
    effname: str  # Canonical upstream project name
    srcname: str | None = None
    version: str | None = None
    category: str | None = None
    subrepo: str | None = None
    origversion: str | None = None
    flags: int = 0
    shadow: bool = False

    def to_package_record(self) -> "PackageRecord":
        package_name = self.visiblename
        if self.family == "nix":
            if self.srcname:
                package_name = self.srcname
            elif self.category:
                package_name = f"{self.category}.{self.visiblename}"
            package_name = normalize_nix_package_name(package_name)

        return PackageRecord(
            repo=self.repo,
            package_name=package_name,
            effname=self.effname,
            version=self.version,
        )
