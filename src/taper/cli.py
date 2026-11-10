"""Thin Typer shell: parse arguments, call the core, print results and ask questions.

All interaction (prompts, opening the editor) lives here; the core never asks anything.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from taper import __version__
from taper.config import DEFAULT_LIBRARY, ENV_LIBRARY, resolve_library
from taper.core.plan import DEFAULT_MIN_SEGMENT_S, DEFAULT_SILENCE_DB, DEFAULT_SILENCE_MIN_S
from taper.core.progress import ProgressEvent
from taper.errors import TaperError
from taper.models import AlbumMeta, CutPlan

if TYPE_CHECKING:
    from taper.core.pipeline import ApplyResult, Prepared

app = typer.Typer(
    name="taper",
    help="Scarica audio, dividilo in brani, taggalo e archivialo in una libreria.",
    no_args_is_help=True,
    add_completion=False,
)

# Options shared by several commands.
ArtistOpt = Annotated[
    str | None, typer.Option("--artist", help="Artista (sostituisce quello ricavato dal video).")
]
AlbumOpt = Annotated[
    str | None, typer.Option("--album", help="Titolo album (sostituisce il titolo del video).")
]
YearOpt = Annotated[
    int | None, typer.Option("--year", help="Anno (sostituisce quello della data di upload).")
]
SourceOpt = Annotated[str, typer.Option("--source", help="auto | chapters | description | silence")]
SilenceDbOpt = Annotated[float, typer.Option("--silence-db", help="Soglia del silenzio in dB.")]
SilenceMinOpt = Annotated[
    float, typer.Option("--silence-min", help="Durata minima del silenzio (s).")
]
MinSegmentOpt = Annotated[
    float, typer.Option("--min-segment", help="Durata minima di un brano (s), solo silenzi.")
]
LibraryOpt = Annotated[
    Path | None,
    typer.Option(
        "--library",
        "-l",
        help=f"Radice della libreria (default: ${ENV_LIBRARY} o {DEFAULT_LIBRARY}).",
    ),
]
NoLibraryOpt = Annotated[
    bool, typer.Option("--no-library", help="Solo brani taggati, senza export né database.")
]
NoCoverOpt = Annotated[bool, typer.Option("--no-cover", help="Non incorporare la copertina.")]
AllowDuplicateOpt = Annotated[
    bool, typer.Option("--allow-duplicate", help="Esporta anche se la sorgente è già in libreria.")
]


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
    """taper - audio downloader, splitter and tagger."""


def fail(error: TaperError) -> typer.Exit:
    """Print a TaperError as a clear message and return an Exit to raise."""
    typer.secho(f"Errore: {error.message}", fg=typer.colors.RED, err=True)
    if error.hint:
        typer.secho(f"Suggerimento: {error.hint}", err=True)
    return typer.Exit(code=1)


def os_error(error: OSError) -> TaperError:
    """A file-system failure (permissions, full disk, missing folder...) as a clear message."""
    where = f" ({error.filename})" if error.filename else ""
    return TaperError(
        f"Errore di accesso ai file: {error.strerror or error}{where}",
        "Controlla permessi, spazio su disco e che le cartelle indicate esistano.",
    )


# ------------------------------------------------------------------------ helpers


def _progress_renderer() -> Callable[[ProgressEvent], None]:
    """One renderer for every stage: a live percentage for downloads, lines for the rest."""
    verbs = {"cut": "taglio", "tag": "tag", "export": "export"}
    state = {"stage": ""}

    def render(event: ProgressEvent) -> None:
        if event.stage == "warning":
            if state["stage"] == "download":
                typer.echo("", err=True)
                state["stage"] = ""
            typer.secho(f"  ! {event.message}", fg=typer.colors.YELLOW, err=True)
            return
        if event.stage == "download" and event.fraction is not None:
            typer.echo(f"\r  download {event.fraction:6.1%}", nl=False, err=True)
            state["stage"] = "download"
            return
        if state["stage"] == "download":
            typer.echo("", err=True)
        if event.stage in verbs:
            typer.echo(f"  {verbs[event.stage]} [{event.message}]", err=True)
        elif event.stage != state["stage"] and event.message:
            typer.echo(f"  {event.message}", err=True)
        state["stage"] = event.stage

    return render


def _album_override(artist: str | None, album: str | None, year: int | None) -> AlbumMeta | None:
    if not (artist or album or year):
        return None
    return AlbumMeta(artist=artist, album=album, year=year)


def _print_plan(plan: CutPlan, notes: list[str]) -> None:
    from taper.core.timestamps import format_short

    meta = plan.album
    typer.echo(
        f"  Artista: {meta.artist or '(vuoto)'}  |  Album: {meta.album or '(vuoto)'}  "
        f"|  Anno: {meta.year or '(vuoto)'}"
    )
    for i, seg in enumerate(plan.segments, start=1):
        start, end = format_short(seg.start_ms), format_short(seg.end_ms)
        typer.echo(f"  {i:2d}. {start:>8} → {end:>8}  {seg.title}")
    for note in notes:
        typer.secho(f"  ! {note}", fg=typer.colors.YELLOW)


def _print_apply(outcome: ApplyResult, target_dir: Path, library_root: Path | None) -> None:
    from taper.core.cut import MODE_COPY, MODE_LOSSLESS
    from taper.core.library import db_path
    from taper.core.timestamps import format_short

    results = outcome.results
    labels = {MODE_COPY: "copy", MODE_LOSSLESS: "flac (lossless)"}
    where = outcome.export.album_dir if outcome.export else target_dir
    typer.secho(f"Tagliati {len(results)} brani → {where}", fg=typer.colors.GREEN)
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
    typer.echo(f"Tag scritti ({cover}).")
    if outcome.export and library_root:
        typer.echo(f"Libreria: {library_root}")
        typer.echo(f"Database: {db_path(library_root)}")
    if outcome.cover_path:
        typer.echo(f"Copertina: {outcome.cover_path}")
    for note in outcome.notes:
        typer.secho(f"  ! {note}", fg=typer.colors.YELLOW)


def _editor_command() -> list[str] | None:
    """`$VISUAL` / `$EDITOR`, else the first common editor found in PATH."""
    for var in ("VISUAL", "EDITOR"):
        if os.environ.get(var):
            return shlex.split(os.environ[var], posix=os.name != "nt")
    for name in ("nano", "vim", "vi", "notepad"):
        if shutil.which(name):
            return [name]
    return None


def _edit_file(path: Path) -> None:
    """Open `path` in the user's editor and wait; if there is none, ask them to edit by hand."""
    command = _editor_command()
    if command:
        try:
            subprocess.run([*command, str(path)], check=False)
            return
        except OSError as exc:
            typer.secho(f"Impossibile avviare l'editor ({exc}).", fg=typer.colors.YELLOW)
    typer.prompt(
        f"Modifica il file a mano:\n  {path}\ne premi Invio quando hai finito",
        default="",
        show_default=False,
    )


def _ask(choices: dict[str, str], default: str) -> str:
    """Prompt until the answer starts with one of the `choices` keys; return that key."""
    legend = ", ".join(
        f"[{k}]{v[1:]}" if v.startswith(k) else f"[{k}] {v}" for k, v in choices.items()
    )
    while True:
        answer = typer.prompt(legend, default=default).strip().lower()[:1]
        if answer in choices:
            return answer
        typer.secho(f"Risposta non valida: scegli tra {', '.join(choices)}.", fg=typer.colors.RED)


def _review_plan(prepared: Prepared) -> CutPlan:
    """Show the plan, let the user edit it as many times as needed, return the approved plan."""
    from taper.core.plan import load_plan, validate_plan
    from taper.errors import InvalidPlanError

    duration = prepared.fetch.audio_info.duration_ms
    notes = prepared.notes
    while True:
        plan: CutPlan | None
        try:
            plan = load_plan(prepared.plan_path)
            problems = validate_plan(plan, duration)
        except InvalidPlanError as exc:
            plan, problems = None, exc.problems

        typer.secho(f"\nPiano: {prepared.plan_path}", bold=True)
        if plan:
            _print_plan(plan, notes)
        for problem in problems:
            typer.secho(f"  ✗ {problem}", fg=typer.colors.RED)
        notes = []  # show the hints only once, not after every edit

        if problems:
            choice = _ask({"e": "edita il piano", "a": "annulla"}, default="e")
        else:
            choice = _ask({"c": "continua", "e": "edita il piano", "a": "annulla"}, default="c")
        if choice == "a":
            typer.echo(
                "Annullato. Il piano resta salvato: potrai riprendere con lo stesso comando."
            )
            raise typer.Exit(code=1)
        if choice == "e":
            _edit_file(prepared.plan_path)
            continue
        assert plan is not None
        return plan


# ----------------------------------------------------------------------- commands


@app.command()
def fetch(
    url: Annotated[str, typer.Argument(help="URL supportato da yt-dlp.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Cartella radice dei download.")] = Path(
        "taper-downloads"
    ),
) -> None:
    """Scarica il miglior stream audio nel codec nativo, senza ricodificare."""
    from taper.core.fetch import fetch as fetch_source

    try:
        result = fetch_source(url, out, on_event=_progress_renderer())
    except TaperError as error:
        raise fail(error) from error
    except OSError as error:
        raise fail(os_error(error)) from error

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
    source: SourceOpt = "auto",
    silence_db: SilenceDbOpt = DEFAULT_SILENCE_DB,
    silence_min: SilenceMinOpt = DEFAULT_SILENCE_MIN_S,
    min_segment: MinSegmentOpt = DEFAULT_MIN_SEGMENT_S,
    artist: ArtistOpt = None,
    album: AlbumOpt = None,
    year: YearOpt = None,
    force: Annotated[bool, typer.Option("--force", help="Sovrascrivi un piano esistente.")] = False,
) -> None:
    """Genera un piano di taglio YAML modificabile a mano."""
    from taper.core.ffmpeg import probe_audio
    from taper.core.plan import PlanOptions, generate_plan, save_plan
    from taper.core.sidecar import load_sidecar

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
        result = generate_plan(
            file, info, duration_ms, options, album_override=_album_override(artist, album, year)
        )
        save_plan(result.plan, target, result.notes, overwrite=force)
    except TaperError as error:
        raise fail(error) from error
    except OSError as error:
        raise fail(os_error(error)) from error

    typer.secho(
        f"Piano creato da '{result.source}': {len(result.plan.segments)} segmenti",
        fg=typer.colors.GREEN,
    )
    _print_plan(result.plan, result.notes)
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
    no_cover: NoCoverOpt = False,
    library: LibraryOpt = None,
    no_library: NoLibraryOpt = False,
    allow_duplicate: AllowDuplicateOpt = False,
) -> None:
    """Taglia (stream copy quando possibile), tagga, esporta in libreria e registra nel DB."""
    from taper.core.pipeline import apply_plan
    from taper.core.plan import load_plan
    from taper.core.sidecar import load_sidecar

    target_dir = out or file.parent / "tracks"
    try:
        loaded = load_plan(plan)
        if loaded.source_file and loaded.source_file != file.name:
            typer.secho(
                f"Attenzione: il piano è stato creato per '{loaded.source_file}', "
                f"ma stai tagliando '{file.name}'.",
                fg=typer.colors.YELLOW,
                err=True,
            )
        library_root = None if no_library else resolve_library(library)
        outcome = apply_plan(
            file,
            loaded,
            target_dir,
            library=library_root,
            info=load_sidecar(file),
            embed_cover=not no_cover,
            overwrite=force,
            allow_duplicate=allow_duplicate,
            on_event=_progress_renderer(),
        )
    except TaperError as error:
        raise fail(error) from error
    except OSError as error:
        raise fail(os_error(error)) from error
    _print_apply(outcome, target_dir, library_root)


@app.command()
def run(
    url: Annotated[str, typer.Argument(help="URL supportato da yt-dlp.")],
    yes: Annotated[
        bool,
        typer.Option(
            "--yes", "-y", help="Salta la revisione del piano (serve se non c'è un terminale)."
        ),
    ] = False,
    out: Annotated[Path, typer.Option("--out", "-o", help="Cartella radice dei download.")] = Path(
        "taper-downloads"
    ),
    source: SourceOpt = "auto",
    silence_db: SilenceDbOpt = DEFAULT_SILENCE_DB,
    silence_min: SilenceMinOpt = DEFAULT_SILENCE_MIN_S,
    min_segment: MinSegmentOpt = DEFAULT_MIN_SEGMENT_S,
    artist: ArtistOpt = None,
    album: AlbumOpt = None,
    year: YearOpt = None,
    no_cover: NoCoverOpt = False,
    library: LibraryOpt = None,
    no_library: NoLibraryOpt = False,
    allow_duplicate: AllowDuplicateOpt = False,
    force: Annotated[
        bool, typer.Option("--force", help="Rigenera brani già presenti in <id>/tracks.")
    ] = False,
) -> None:
    """fetch + plan, revisione del piano, poi cut + tag + export."""
    from taper.core.pipeline import apply_plan, check_duplicate, prepare
    from taper.core.plan import PlanOptions, validate_plan

    render = _progress_renderer()
    try:
        # Fail early on a bad library path, before downloading anything.
        library_root = None if no_library else resolve_library(library)
        prepared = prepare(
            url,
            out,
            options=PlanOptions(source, silence_db, silence_min, min_segment),
            album_override=_album_override(artist, album, year),
            on_event=render,
        )
        info = prepared.fetch.info
        typer.secho(f"Sorgente: {info.title}", fg=typer.colors.GREEN)
        if library_root is not None:
            # Do not make the user review a plan for something that would be refused anyway.
            check_duplicate(prepared.audio, library_root, allow_duplicate=allow_duplicate)

        if yes:
            plan = prepared.plan
            _print_plan(plan, prepared.notes)
            problems = validate_plan(plan, prepared.fetch.audio_info.duration_ms)
            if problems:
                from taper.errors import InvalidPlanError

                raise InvalidPlanError(problems)
        else:
            plan = _review_plan(prepared)

        staging = prepared.fetch.workdir / "tracks"
        outcome = apply_plan(
            prepared.audio,
            plan,
            staging,
            library=library_root,
            info=info,
            embed_cover=not no_cover,
            overwrite=force,
            allow_duplicate=allow_duplicate,
            on_event=render,
        )
    except TaperError as error:
        raise fail(error) from error
    except OSError as error:
        raise fail(os_error(error)) from error
    _print_apply(outcome, staging, library_root)
