import json
from pathlib import Path
from typing import Annotated

import typer

from pkgmap.db import get_database_path, update_database
from pkgmap.resolver import list_repositories, resolve_all, resolve_project

cli_app = typer.Typer(
    name="pkgmap",
    help="Cross-distribution Linux package name resolution CLI",
    add_completion=False,
)


@cli_app.command(name="resolve")
def resolve_cmd(
    package: Annotated[
        str, typer.Argument(help="Package or upstream project name to resolve")
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
    db_path: Annotated[
        Path | None,
        typer.Option("--db-path", help="Custom path to pkgmap.db database"),
    ] = None,
) -> None:
    """Resolve a package name across Linux distributions."""
    if project and from_repo:
        typer.secho(
            "Error: Cannot specify both --from and --project.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)

    if from_repo and not project:
        results = resolve_all(
            package, from_repo=from_repo, to_repo=to_repo, db_path=db_path
        )
    else:
        results = resolve_project(package, to_repo=to_repo, db_path=db_path)

    if not results:
        if json_output:
            typer.echo(json.dumps([]))
        else:
            if from_repo and not project:
                if to_repo:
                    msg = f"No equivalent package found for '{package}' from '{from_repo}' to '{to_repo}'."
                else:
                    msg = f"No equivalent package found for '{package}' from '{from_repo}'."
            else:
                if to_repo:
                    msg = f"No equivalent package found for project '{package}' in '{to_repo}'."
                else:
                    msg = f"No equivalent package found for project '{package}'."
            typer.secho(msg, fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)

    items_to_show = results if (all_matches or to_repo is None) else results[:1]

    if json_output:
        data = [
            {
                "name": r.name,
                "version": r.version,
                "category": r.category,
                "repo": r.repo,
                "repo_family": r.repo_family,
                "install_name": r.install_name,
            }
            for r in items_to_show
        ]
        typer.echo(json.dumps(data, indent=2))
        return

    for res in items_to_show:
        version_str = f" ({res.version})" if res.version else ""
        meta_parts = []
        if res.category and res.repo_family != "nix":
            meta_parts.append(f"category: {res.category}")
        meta_str = f" [{', '.join(meta_parts)}]" if meta_parts else ""
        repo_prefix = f"{res.repo}: " if to_repo is None else ""
        typer.echo(f"{repo_prefix}{res.install_name}{version_str}{meta_str}")


@cli_app.command(name="update")
def update_cmd(
    db_path: Annotated[
        Path | None,
        typer.Option("--db-path", help="Custom path to save pkgmap.db database"),
    ] = None,
) -> None:
    """Explicitly download and update the local package map database."""
    target_path = get_database_path(db_path)
    typer.echo(f"Updating package database at {target_path}...")
    update_database(db_path=target_path, show_progress=True)
    typer.secho(
        f"Successfully updated database at {target_path}", fg=typer.colors.GREEN
    )


@cli_app.command(name="repos")
def repos_cmd(
    db_path: Annotated[
        Path | None,
        typer.Option("--db-path", help="Custom path to pkgmap.db database"),
    ] = None,
) -> None:
    """List all available distributions and repositories."""
    repos = list_repositories(db_path=db_path)
    typer.echo(f"{'Repository':<25} {'Family':<15} {'Packages':>10}")
    typer.echo("-" * 52)
    for r in sorted(repos, key=lambda x: x.name):
        typer.echo(f"{r.name:<25} {r.family:<15} {r.package_count:>10,}")


def main() -> None:
    cli_app()


if __name__ == "__main__":
    main()
