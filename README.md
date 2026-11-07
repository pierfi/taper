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

```bash
# Genera un piano di taglio YAML modificabile a mano (accanto al file: <id>.plan.yaml)
uv run taper plan taper-downloads/<id>/<id>.opus
uv run taper plan file.opus --source silence --silence-db -25 --min-segment 60
```

Sorgenti dei tagli, in ordine di priorità: capitoli del video → timestamp nella
descrizione (`00:00 Titolo`, `1:02:33 - Titolo`, `[00:00]`, `Titolo 00:00`, range
`00:00 - 04:12 Titolo`...) → rilevamento silenzi con ffmpeg. Ogni segmento riporta
nel YAML da quale sorgente arriva. Controlla sempre `album.artist`, `album.album` e
`album.year`: sono ricavati dai metadati del video (canale e data di upload) e spesso
non coincidono con artista e data del concerto. Il piano esistente non viene mai
sovrascritto senza `--force`.

Nota: per YouTube yt-dlp può richiedere un runtime JavaScript esterno (es. deno);
se il download fallisce, aggiorna yt-dlp (`uv lock --upgrade-package yt-dlp`).

## Nota legale

Scaricare da YouTube può violare i suoi termini di servizio. L'uso previsto è su
contenuti propri o liberi.
