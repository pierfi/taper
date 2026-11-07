"""Thin Typer shell: parse arguments, call the core, print results."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from taper import __version__
from taper.core.plan import DEFAULT_MIN_SEGMENT_S, DEFAULT_SILENCE_DB, DEFAULT_SILENCE_MIN_S
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
def plan(
    file: Annotated[Path, typer.Argument(help="File audio sorgente.", exists=True, dir_okay=False)],
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Dove scrivere il piano (default: <file>.plan.yaml)."),
    ] = None,
    source: Annotated[
        str, typer.Option("--source", help="auto | chapters | description | silence")
    ] = "auto",
    silence_db: Annotated[
        float, typer.Option("--silence-db", help="Soglia del silenzio in dB.")
    ] = DEFAULT_SILENCE_DB,
    silence_min: Annotated[
        float, typer.Option("--silence-min", help="Durata minima del silenzio (s).")
    ] = DEFAULT_SILENCE_MIN_S,
    min_segment: Annotated[
        float, typer.Option("--min-segment", help="Durata minima di un brano (s), solo silenzi.")
    ] = DEFAULT_MIN_SEGMENT_S,
    force: Annotated[bool, typer.Option("--force", help="Sovrascrivi un piano esistente.")] = False,
) -> None:
    """Genera un piano di taglio YAML modificabile a mano."""
    from taper.core.ffmpeg import probe_audio
    from taper.core.plan import PlanOptions, generate_plan, save_plan
    from taper.core.sidecar import load_sidecar
    from taper.core.timestamps import format_short

    target = out or file.with_name(file.stem + ".plan.yaml")
    try:
        if target.exists() and not force:
            raise TaperError(
                f"Il piano '{target}' esiste già.",
                "Usa --force per sovrascriverlo o scegli un altro --out.",
            )
        info = load_sidecar(file)
        duration_ms = probe_audio(file).duration_ms
        options = PlanOptions(source, silence_db, silence_min, min_segment)
        result = generate_plan(file, info, duration_ms, options)
        save_plan(result.plan, target, result.notes, overwrite=force)
    except TaperError as error:
        raise fail(error) from error

    typer.secho(
        f"Piano creato da '{result.source}': {len(result.plan.segments)} segmenti",
        fg=typer.colors.GREEN,
    )
    for i, seg in enumerate(result.plan.segments, start=1):
        start, end = format_short(seg.start_ms), format_short(seg.end_ms)
        typer.echo(f"  {i:2d}. {start:>8} → {end:>8}  {seg.title}")
    for note in result.notes:
        typer.secho(f"  ! {note}", fg=typer.colors.YELLOW)
    typer.echo(f"\nPiano: {target}\nModificalo se serve, poi: taper cut {file} --plan {target}")


@app.command()
def cut(
    file: Annotated[Path, typer.Argument(help="File audio sorgente.", exists=True, dir_okay=False)],
    plan: Annotated[
        Path, typer.Option("--plan", help="Piano di taglio YAML.", exists=True, dir_okay=False)
    ],
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Cartella dei brani (default: <cartella>/tracks)."),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Rigenera brani già esistenti.")] = False,
    no_cover: Annotated[
        bool, typer.Option("--no-cover", help="Non incorporare la copertina.")
    ] = False,
) -> None:
    """Taglia i segmenti (stream copy quando possibile) e scrive tag e copertina."""
    from taper.core.cut import MODE_COPY, MODE_LOSSLESS
    from taper.core.pipeline import cut_and_tag
    from taper.core.plan import load_plan
    from taper.core.sidecar import load_sidecar
    from taper.core.timestamps import format_short

    target_dir = out or file.parent / "tracks"

    def render(event: ProgressEvent) -> None:
        if event.stage in ("cut", "tag"):
            verb = "taglio" if event.stage == "cut" else "tag"
            typer.echo(f"  {verb} [{event.message}]", err=True)

    try:
        loaded = load_plan(plan)
        if loaded.source_file and loaded.source_file != file.name:
            typer.secho(
                f"Attenzione: il piano è stato creato per '{loaded.source_file}', "
                f"ma stai tagliando '{file.name}'.",
                fg=typer.colors.YELLOW,
                err=True,
            )
        outcome = cut_and_tag(
            file,
            loaded,
            target_dir,
            info=load_sidecar(file),
            embed_cover=not no_cover,
            overwrite=force,
            on_event=render,
        )
    except TaperError as error:
        raise fail(error) from error
    results = outcome.results

    labels = {MODE_COPY: "copy", MODE_LOSSLESS: "flac (lossless)"}
    typer.secho(f"Tagliati {len(results)} brani in {target_dir}", fg=typer.colors.GREEN)
    for r in results:
        mode = labels.get(r.mode, "RICODIFICATO")
        typer.echo(f"  {r.path.name}  ({format_short(r.audio_info.duration_ms)}, {mode})")
    for r in results:
        for warning in r.warnings:
            typer.secho(f"  ! {warning}", fg=typer.colors.YELLOW)
    reencoded = sum(r.reencoded for r in results)
    if reencoded:
        typer.secho(f"{reencoded} brani ricodificati: qualità ridotta.", fg=typer.colors.YELLOW)
    else:
        typer.echo("Nessuna perdita di qualità.")
    cover = "con copertina" if outcome.cover else "senza copertina"
    typer.echo(f"Tag scritti ({cover}). Export in libreria: prossimo passo.")
    for note in outcome.notes:
        typer.secho(f"  ! {note}", fg=typer.colors.YELLOW)


@app.command()
def run(
    url: Annotated[str, typer.Argument(help="URL supportato da yt-dlp.")],
    yes: Annotated[bool, typer.Option("--yes", help="Salta la revisione del piano.")] = False,
) -> None:
    """fetch + plan, revisione del piano, poi cut + tag + export."""
    _not_implemented("run")
