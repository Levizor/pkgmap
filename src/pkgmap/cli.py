import json
from pathlib import Path
from typing import Annotated

import typer

from pkgmap.db import (
    DatabaseVariant,
    get_database_path,
    resolve_cli_variant,
    set_default_variant,
    update_database,
)
from pkgmap.resolver import (
    get_missing_repositories,
    list_repositories,
    resolve_batch_all,
)

cli_app = typer.Typer(
    name="pkgmap",
    help="Cross-distribution Linux package name resolution CLI",
    add_completion=False,
)


def _select_variant(core: bool, full: bool) -> DatabaseVariant:
    if core and full:
        typer.secho(
            "Error: Cannot specify both --core and --full.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)
    variant = resolve_cli_variant(full=full, core=core)
    set_default_variant(variant)
    return variant


@cli_app.callback()
def cli_callback(
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable verbose debug logging"),
    ] = False,
) -> None:
    if verbose:
        import logging

        for name in ("pkgmap", "pkgmap-db", "pkgmap-downloader", "pkgmap-consumer"):
            log = logging.getLogger(name)
            log.setLevel(logging.DEBUG)
            for handler in log.handlers:
                handler.setLevel(logging.DEBUG)


def _format_not_found_msg(
    package: str,
    from_repo: str | None,
    to_repo: str | None,
    project: bool,
) -> str:
    if from_repo and not project:
        if to_repo:
            return f"No equivalent package found for '{package}' from '{from_repo}' to '{to_repo}'."
        return f"No equivalent package found for '{package}' from '{from_repo}'."
    if to_repo:
        return f"No equivalent package found for project '{package}' in '{to_repo}'."
    return f"No equivalent package found for project '{package}'."


@cli_app.command(name="resolve")
def resolve_cmd(
    packages: Annotated[
        list[str],
        typer.Argument(help="Package or upstream project name(s) to resolve"),
    ],
    to_repo: Annotated[
        str | None,
        typer.Option(
            "--to",
            "-t",
            help="Target repository/distribution (e.g. nixpkgs, alpine). If omitted, matches across all repositories.",
        ),
    ] = None,
    from_repo: Annotated[
        str | None,
        typer.Option(
            "--from",
            "-f",
            help="Source repository/distribution (e.g. debian, arch). If omitted, package is resolved by upstream project name.",
        ),
    ] = None,
    project: Annotated[
        bool,
        typer.Option(
            "--project",
            "-p",
            help="Resolve package directly as an upstream project name",
        ),
    ] = False,
    all_matches: Annotated[
        bool,
        typer.Option("--all", "-a", help="Show all matching target packages"),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output results in JSON format"),
    ] = False,
    core: Annotated[
        bool,
        typer.Option("--core", help="Use the core database (top 10 repositories)"),
    ] = False,
    full: Annotated[
        bool,
        typer.Option("--full", help="Use the full database (all repositories)"),
    ] = False,
    db_path: Annotated[
        Path | None,
        typer.Option("--db-path", help="Custom path to pkgmap.db database"),
    ] = None,
) -> None:
    """Resolve one or more package names across Linux distributions."""
    if project and from_repo:
        typer.secho(
            "Error: Cannot specify both --from and --project.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)

    variant = _select_variant(core=core, full=full)
    effective_from = from_repo if not project else None
    batch_results = resolve_batch_all(
        packages,
        from_repo=effective_from,
        to_repo=to_repo,
        db_path=db_path,
    )

    is_batch = len(packages) > 1
    any_found = any(batch_results.get(pkg) for pkg in packages)

    if not any_found:
        if json_output:
            empty_payload: list[object] | dict[str, list[object]] = (
                {pkg: [] for pkg in packages} if is_batch else []
            )
            typer.echo(json.dumps(empty_payload, indent=2 if is_batch else None))
        else:
            for pkg in packages:
                msg = _format_not_found_msg(pkg, from_repo, to_repo, project)
                typer.secho(msg, fg=typer.colors.YELLOW)

            requested_repos = [r for r in (from_repo, to_repo) if r]
            missing_repos = get_missing_repositories(requested_repos, db_path=db_path)
            if missing_repos and variant == "core":
                missing_str = ", ".join(f"'{r}'" for r in missing_repos)
                typer.secho(
                    f"Repository {missing_str} is not in the core database. "
                    "Try the full database with: pkgmap update --full",
                    fg=typer.colors.CYAN,
                )
        raise typer.Exit(code=1)

    if json_output:
        if not is_batch:
            pkg = packages[0]
            matches = batch_results.get(pkg, [])
            items = matches if (all_matches or to_repo is None) else matches[:1]
            data = [
                {
                    "name": r.name,
                    "version": r.version,
                    "repo": r.repo,
                    "repo_family": r.repo_family,
                }
                for r in items
            ]
            typer.echo(json.dumps(data, indent=2))
        else:
            batch_data = {
                pkg: [
                    {
                        "name": r.name,
                        "version": r.version,
                        "repo": r.repo,
                        "repo_family": r.repo_family,
                    }
                    for r in (
                        batch_results.get(pkg, [])
                        if (all_matches or to_repo is None)
                        else batch_results.get(pkg, [])[:1]
                    )
                ]
                for pkg in packages
            }
            typer.echo(json.dumps(batch_data, indent=2))
        return

    for pkg in packages:
        matches = batch_results.get(pkg, [])
        items_to_show = matches if (all_matches or to_repo is None) else matches[:1]
        if not items_to_show:
            typer.secho(f"{pkg} -> not found", fg=typer.colors.YELLOW)
            continue
        for res in items_to_show:
            version_str = f" ({res.version})" if res.version else ""
            repo_prefix = f"{res.repo}: " if to_repo is None else ""
            pkg_prefix = f"{pkg} -> " if is_batch else ""
            typer.echo(f"{pkg_prefix}{repo_prefix}{res.name}{version_str}")


@cli_app.command(name="update")
def update_cmd(
    core: Annotated[
        bool,
        typer.Option("--core", help="Download the core database (top 10 repositories)"),
    ] = False,
    full: Annotated[
        bool,
        typer.Option("--full", help="Download the full database (all repositories)"),
    ] = False,
    db_path: Annotated[
        Path | None,
        typer.Option("--db-path", help="Custom path to save pkgmap.db database"),
    ] = None,
) -> None:
    """Explicitly download and update the local package map database."""
    variant = _select_variant(core=core, full=full)
    target_path = get_database_path(db_path, variant=variant)
    typer.echo(f"Updating {variant} package database at {target_path}...")
    update_database(db_path=target_path, show_progress=True, variant=variant)
    typer.secho(
        f"Successfully updated {variant} database at {target_path}",
        fg=typer.colors.GREEN,
    )


@cli_app.command(name="repos")
def repos_cmd(
    core: Annotated[
        bool,
        typer.Option("--core", help="List repositories from the core database"),
    ] = False,
    full: Annotated[
        bool,
        typer.Option("--full", help="List repositories from the full database"),
    ] = False,
    db_path: Annotated[
        Path | None,
        typer.Option("--db-path", help="Custom path to pkgmap.db database"),
    ] = None,
) -> None:
    """List all available distributions and repositories."""
    _select_variant(core=core, full=full)
    repos = list_repositories(db_path=db_path)
    typer.echo(f"{'Repository':<25} {'Family':<15} {'Packages':>10}")
    typer.echo("-" * 52)
    for r in sorted(repos, key=lambda x: x.name):
        typer.echo(f"{r.name:<25} {r.family:<15} {r.package_count:>10,}")


def main() -> None:
    cli_app()


if __name__ == "__main__":
    main()
