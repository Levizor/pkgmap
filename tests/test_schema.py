from pkgmap.schema import PackageRecord, RepologyPackageRow, Repository


def test_repository_model() -> None:
    repo = Repository(name="debian_12", family="debian", package_count=42)
    assert repo.name == "debian_12"
    assert repo.family == "debian"
    assert repo.package_count == 42


def test_package_record_model() -> None:
    pkg = PackageRecord(
        repo="debian_12",
        package_name="batcat",
        effname="bat",
        version="0.24.0",
        category="utils",
    )
    assert pkg.repo == "debian_12"
    assert pkg.package_name == "batcat"
    assert pkg.effname == "bat"
    assert pkg.version == "0.24.0"
    assert pkg.category == "utils"


def test_repology_row_conversion_to_package_record() -> None:
    row = RepologyPackageRow(
        repo="nix_unstable",
        family="nix",
        visiblename="bat",
        effname="bat",
        srcname="bat",
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
    assert pkg.package_name == "bat"
    assert pkg.effname == "bat"
    assert pkg.version == "0.24.0"
    assert pkg.category == "tools"


def test_repology_row_nix_attribute_resolution() -> None:
    # 1. Nix package with srcname (e.g. haskellPackages.typst)
    haskell_row = RepologyPackageRow(
        repo="nix_unstable",
        family="nix",
        visiblename="typst",
        effname="haskell:typst",
        srcname="haskellPackages.typst",
        category="haskellPackages",
    )
    assert haskell_row.to_package_record().package_name == "haskellPackages.typst"

    # 2. Nix package top-level (srcname is typst)
    top_row = RepologyPackageRow(
        repo="nix_unstable",
        family="nix",
        visiblename="typst",
        effname="typst",
        srcname="typst",
        category=None,
    )
    assert top_row.to_package_record().package_name == "typst"

    # 3. Nix package with category but missing srcname
    fallback_row = RepologyPackageRow(
        repo="nix_unstable",
        family="nix",
        visiblename="magit",
        effname="emacs-magit",
        srcname=None,
        category="emacsPackages",
    )
    assert fallback_row.to_package_record().package_name == "emacsPackages.magit"

    # 4. Non-nix package: category is NOT prepended
    debian_row = RepologyPackageRow(
        repo="debian_12",
        family="debian",
        visiblename="batcat",
        effname="bat",
        srcname=None,
        category="utils",
    )
    assert debian_row.to_package_record().package_name == "batcat"
