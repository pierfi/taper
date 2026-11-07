# taper — piano d'opera

Sintesi di requisiti (`prompt_init.md`) + revisione di design (Opus). Un commit per passo.

## Struttura

```
pyproject.toml            uv + hatchling, entry point `taper = taper.cli:app`
src/taper/
  cli.py                  guscio Typer sottile (nessuna logica)
  errors.py               TaperError(message, hint) + 3 sottoclassi
  models.py               dataclass: SourceInfo, Segment, AlbumMeta, CutPlan, Track (to_dict/from_dict, tempi in ms interi)
  core/
    ffmpeg.py             wrapper subprocess: which, ffprobe JSON, run con errori chiari, progress
    naming.py             sanificazione nomi cross-platform, nomi file/cartelle, suffisso anti-collisione
    timestamps.py         parsing timestamp dalla descrizione (puro)
    fetch.py              yt-dlp come libreria -> workdir + <stem>.taper.json
    plan.py               capitoli > descrizione > silencedetect; YAML load/dump; validate_plan()
    cut.py                copy / ricodifica del singolo segmento
    tagging.py            tag per opus/m4a/mp3/flac (mutagen)
    cover.py              crop quadrato + JPEG, embedding
    export.py             layout Artista/Anno - Album/NN - Titolo.ext
    library.py            SQLite (una connessione per chiamata, user_version)
    pipeline.py           prepare(url) -> WorkDir ; apply(plan) -> list[Track]
tests/
```

## Decisioni di design (dalla review)

- **Core sincrono**, nessun async; FastAPI lo userà in threadpool. Niente print/typer/rich nel core.
- **Progresso**: un solo meccanismo `on_event(ProgressEvent(stage, fraction|None, message))`; cancellazione con `threading.Event`.
- **Il core non fa domande**: la pausa di `run` per la revisione vive solo nella CLI.
- **Tempi in ms interi**. YAML: tempi e titoli *sempre quotati* in scrittura (PyYAML legge `1:02:33` come intero base 60, `No`/`On` come bool); in lettura accetta int/float/str e rifiuta titoli non-str.
- **`validate_plan()` ritorna tutti gli errori** con indice del segmento (la UI modificherà lo stesso CutPlan).
- **Una workdir per sorgente** (audio, `<stem>.taper.json` ridotto e versionato, miniatura, `plan.yaml`, `tracks/`).
- **Sorgenti locali senza sidecar**: `SourceInfo` opzionale; chiave di idempotenza = hash file, non URL.
- **Taglio**: sorgente lossless → ricodifica FLAC (campione-preciso); lossy → `-ss` prima di `-i` + `-t` in copy, verifica durata/start con tolleranza 2 frame del codec (opus 20 ms, aac 1024/sr, mp3 1152/sr), altrimenti ricodifica del solo segmento + warning. Flag `reencoded` salvato in DB. Segmenti contigui di default (gapless). Scrittura su `.part` poi rename.
- **Remux webm→opus** delegato al postprocessor `FFmpegExtractAudio` di yt-dlp (senza codec forzato).
- **Metadati**: sezione `album:` (artist, album, year) nel YAML; default artist→creator→uploader; anno/artista evidenziati in review (l'upload date ≠ data del concerto).
- **Silencedetect**: fallback minimo (soglie + durata minima); se nulla, un solo segmento.
- **Regex descrizione**: `00:00 Titolo`, `1:02:33 - Titolo`, `[00:00]`, `(1:02)`, `1. 00:00`, `Titolo 00:00`, range `00:00 - 04:12 Titolo` (il secondo tempo è la fine); ≥2 match e monotoni crescenti.
- **Libreria**: DB in `<library>/.taper/library.db`, percorsi relativi alla root (portabile `/mnt/c` ↔ `C:\`), niente WAL su `/mnt/c`, niente platformdirs. Collisioni → suffisso, mai sovrascrivere. Limite 255 byte UTF-8 per componente.
- **CLI**: `taper cut` applica tutto (taglio, tag, cover, export, DB); `--no-library` produce solo i file taggati in una cartella.
- **Config**: solo dataclass `Settings` (`--library` + env var), nessun file di config.
- **Documentare**: yt-dlp su YouTube può richiedere un runtime JS (deno); non bloccare la versione di yt-dlp.

## Passi

| # | Passo | Contenuto | Test |
|---|-------|-----------|------|
| 0 | Scaffolding | pyproject, ruff/pytest, CLI vuota (`--version`, comandi stub), errors, models, naming | naming, round-trip modelli |
| 1 | fetch | ffmpeg.py, fetch.py, workdir, sidecar | build opzioni yt-dlp, scrittura sidecar (rete mockata) |
| 2 | plan | timestamps.py, capitoli, silencedetect, YAML I/O, validate_plan | parsing timestamp, validazione, YAML quoting |
| 3 | cut | copy/lossless/ricodifica + verifica, `.part`, `tracks/` | audio sintetico via ffmpeg (skipif senza ffmpeg) |
| 4 | tagging + cover | mutagen per 4 formati, crop quadrato, embedding | round-trip tag per formato |
| 5 | library + export | export.py, cover.jpg, SQLite, idempotenza | schema, collisioni, path relativi |
| 6 | run end-to-end | pipeline.py, conferma/`--yes`, apertura editor | integrazione su file sintetico |
| 7 | Rifinitura | README (installazione, esempi, nota ToS), messaggi d'errore | — |

## Prerequisiti ambiente

- `ffmpeg`/`ffprobe` **non installati** (serve `sudo apt install ffmpeg`); i test ffmpeg sono sotto `skipif`.
- Python 3.12 gestito da uv (`.python-version`).
