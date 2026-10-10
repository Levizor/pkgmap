from pkgmap.schema import PackageRecord, RepologyPackageRow, Repository


def test_repository_model() -> None:
    repo = Repository(name="debian_12", family="debian", package_count=42)
    assert repo.name == "debian_12"
    assert repo.family == "debian"
    assert repo.package_count == 42


def test_package_record_model() -> None:
    pkg = PackageRecord(
        repo="debian_12",
        visiblename="batcat",
        effname="bat",
        version="0.24.0",
        category="utils",
    )
    assert pkg.repo == "debian_12"
    assert pkg.visiblename == "batcat"
    assert pkg.effname == "bat"
    assert pkg.version == "0.24.0"
    assert pkg.category == "utils"


def test_repology_row_conversion_to_package_record() -> None:
    row = RepologyPackageRow(
        repo="nix_unstable",
        family="nix",
        visiblename="bat",
        effname="bat",
        version="0.24.0",
        category="tools",
        subrepo="nixpkgs",
        origversion="0.24.0",
        flags=0,
        shadow=False,
    )
    pkg = row.to_package_record()
    assert isinstance(pkg, PackageRecord)
    assert pkg.repo == "nix_unstable"
    assert pkg.visiblename == "bat"
    assert pkg.effname == "bat"
    assert pkg.version == "0.24.0"
    assert pkg.category == "tools"
