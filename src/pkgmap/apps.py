from pathlib import Path
from typing import Annotated

import typer

from pkgmap import cli, pipeline
from pkgmap.pipeline import download_pipeline_dump, set_github_output

cli_app = typer.Typer(
    name="pkgmap",
    help="Map packages across repositories",
    add_completion=False,
)

pipeline_app = typer.Typer(
    name="pkgmap-pipeline",
    help="Download dump, transform, and build package map database",
    add_completion=False,
)


@cli_app.command()
def cli_main() -> None:
    cli.main()


@pipeline_app.command(name="download")
def pipeline_download(
    link: Annotated[
        str | None,
        typer.Option("--link", "-l", help="Dump link to download from"),
    ] = None,
    dest_dir: Annotated[
        Path | None,
        typer.Option("--dest-dir", "-d", help="Directory where to save the dump file"),
    ] = None,
) -> None:
    """Download the latest Repology database dump."""
    dump_file, dump_date = download_pipeline_dump(dump_link=link, dest_dir=dest_dir)
    set_github_output(
        date=dump_date,
        tag=f"db-{dump_date}",
        dump_path=str(dump_file.resolve()),
    )
    typer.echo(f"Downloaded Repology dump ({dump_date}) to {dump_file}")


@pipeline_app.command(name="build")
def pipeline_build(
    input_dump: Annotated[
        Path | None,
        typer.Option(
            "--input-dump",
            "-i",
            help="Dump file to take as an input to the processing pipeline",
        ),
    ] = None,
    output_file: Annotated[
        Path,
        typer.Option(
            "-o",
            "--output-path",
            help="Path for the output SQLite database",
        ),
    ] = Path("package_map.sqlite"),
    batch_size: Annotated[
        int,
        typer.Option(
            "--batch-size",
            help="Number of records per batch in the processing pipeline",
        ),
    ] = 50_000,
    release_notes: Annotated[
        Path | None,
        typer.Option("--release-notes", help="Path to generate release notes markdown"),
    ] = None,
    dump_date: Annotated[
        str | None,
        typer.Option("--dump-date", help="Snapshot date (YYYY-MM-DD)"),
    ] = None,
) -> None:
    """Process Repology dump and generate SQLite package map database."""
    pipeline.main(
        dump_file=input_dump,
        output_file=output_file,
        batch_size=batch_size,
        release_notes=release_notes,
        dump_date=dump_date,
    )


if __name__ == "__main__":
    cli_app()
