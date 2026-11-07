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

## Nota legale

Scaricare da YouTube può violare i suoi termini di servizio. L'uso previsto è su
contenuti propri o liberi.
