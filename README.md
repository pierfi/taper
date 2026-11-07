# taper

App personale per scaricare tracce audio (YouTube e altre fonti supportate da yt-dlp),
dividerle in brani (caso d'uso principale: concerti), taggarle e archiviarle in una libreria.

> Work in progress — vedi [PLAN.md](PLAN.md) per il piano d'opera.

## Installazione (sviluppo)

```bash
uv sync
uv run taper --help
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

Richiede `ffmpeg` e `ffprobe` nel PATH (`sudo apt install ffmpeg`).

## Uso

```bash
# Scarica il miglior stream audio nel codec nativo (nessuna ricodifica)
uv run taper fetch "https://www.youtube.com/watch?v=..." -o taper-downloads
```

Crea `taper-downloads/<id>/` con l'audio (`.opus` / `.m4a`...), la miniatura e
`<id>.taper.json` (titolo, uploader, data, capitoli, descrizione, miniatura).

Nota: per YouTube yt-dlp può richiedere un runtime JavaScript esterno (es. deno);
se il download fallisce, aggiorna yt-dlp (`uv lock --upgrade-package yt-dlp`).

## Nota legale

Scaricare da YouTube può violare i suoi termini di servizio. L'uso previsto è su
contenuti propri o liberi.
