"""Thin Typer shell: parse arguments, call the core, print results."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from taper import __version__
from taper.core.progress import ProgressEvent
from taper.errors import TaperError

app = typer.Typer(
    name="taper",
    help="Scarica audio, dividilo in brani, taggalo e archivialo in una libreria.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"taper {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version_callback, is_eager=True, help="Mostra la versione."
        ),
    ] = False,
) -> None:
    """taper — audio downloader, splitter and tagger."""


def _not_implemented(command: str) -> None:
    typer.secho(f"'{command}' non è ancora implementato.", fg=typer.colors.YELLOW, err=True)
    raise typer.Exit(code=2)


def fail(error: TaperError) -> typer.Exit:
    """Print a TaperError as a clear message and return an Exit to raise."""
    typer.secho(f"Errore: {error.message}", fg=typer.colors.RED, err=True)
    if error.hint:
        typer.secho(f"Suggerimento: {error.hint}", err=True)
    return typer.Exit(code=1)


@app.command()
def fetch(
    url: Annotated[str, typer.Argument(help="URL supportato da yt-dlp.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Cartella radice dei download.")] = Path(
        "taper-downloads"
    ),
) -> None:
    """Scarica il miglior stream audio nel codec nativo, senza ricodificare."""
    from taper.core.fetch import fetch as fetch_source

    last_stage = {"name": ""}

    def render(event: ProgressEvent) -> None:
        if event.stage == "download" and event.fraction is not None:
            typer.echo(f"\r  download {event.fraction:6.1%}", nl=False, err=True)
            last_stage["name"] = "download"
        elif event.stage != last_stage["name"]:
            if last_stage["name"] == "download":
                typer.echo("", err=True)
            if event.message:
                typer.echo(f"  {event.message}", err=True)
            last_stage["name"] = event.stage

    try:
        result = fetch_source(url, out, on_event=render)
    except TaperError as error:
        raise fail(error) from error

    a = result.audio_info
    bitrate = f"{a.bitrate // 1000} kbps" if a.bitrate else "bitrate n/d"
    minutes, seconds = divmod(a.duration_ms // 1000, 60)
    typer.secho(f"Scaricato: {result.info.title}", fg=typer.colors.GREEN)
    typer.echo(f"  file:     {result.audio}")
    typer.echo(f"  codec:    {a.codec} ({bitrate}), {minutes}:{seconds:02d}")
    typer.echo(f"  capitoli: {len(result.info.chapters)}")
    typer.echo(f"  sidecar:  {result.sidecar}")
    if result.thumbnail:
        typer.echo(f"  miniatura: {result.thumbnail}")


@app.command()
def plan(file: Annotated[Path, typer.Argument(help="File audio sorgente.")]) -> None:
    """Genera un piano di taglio YAML modificabile a mano."""
    _not_implemented("plan")


@app.command()
def cut(
    file: Annotated[Path, typer.Argument(help="File audio sorgente.")],
    plan: Annotated[Path, typer.Option("--plan", help="Piano di taglio YAML.")],
) -> None:
    """Taglia, tagga ed esporta i segmenti del piano."""
    _not_implemented("cut")


@app.command()
def run(
    url: Annotated[str, typer.Argument(help="URL supportato da yt-dlp.")],
    yes: Annotated[bool, typer.Option("--yes", help="Salta la revisione del piano.")] = False,
) -> None:
    """fetch + plan, revisione del piano, poi cut + tag + export."""
    _not_implemented("run")
