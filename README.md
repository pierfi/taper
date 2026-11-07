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

```bash
# Taglia i segmenti del piano in <cartella>/tracks/NN - Titolo.ext
uv run taper cut taper-downloads/<id>/<id>.opus --plan taper-downloads/<id>/<id>.plan.yaml
```

Come si taglia (senza perdere qualità):

- **Sorgenti lossy** (opus, m4a/aac, mp3, ogg): *stream copy*, poi ffprobe verifica durata e
  inizio del brano. Solo se il taglio non è preciso (oltre 2 frame del codec) quel singolo
  segmento viene ricodificato con lo stesso codec, e il comando lo segnala in giallo.
- **Sorgenti lossless** (flac, wav, alac): ricodificate in FLAC, che è preciso al campione
  e non perde nulla.
- L'originale non viene mai modificato; i brani esistenti non vengono sovrascritti senza
  `--force`. I segmenti contigui dei piani generati non lasciano buchi tra un brano e
  l'altro (gapless), ma con lo stream copy di mp3/aac può restare un piccolo click ai
  confini.

Subito dopo il taglio `cut` scrive i tag (titolo, artista, album artist, album, anno,
numero traccia e totale) e incorpora la copertina: la miniatura del video ritagliata in
quadrato al centro (JPEG, max 1200 px). Formati supportati: opus, ogg, m4a, mp3, flac.
Per file locali la copertina viene cercata come `<nome>.jpg|png|webp` o `cover.jpg` accanto
al file; `--no-cover` la disattiva. I tag vengono dal piano YAML (sezione `album` e titoli
dei segmenti), quindi correggi lì artista, album e anno prima di tagliare.

## Libreria

`taper cut` esporta i brani taggati in una libreria ordinata e li registra in SQLite:

```
<libreria>/Artista/Anno - Album/NN - Titolo.ext      (+ cover.jpg)
<libreria>/.taper/library.db                         (percorsi relativi: la libreria è spostabile)
```

- **Dove**: `--library`, altrimenti `$TAPER_LIBRARY`, altrimenti `~/taper-library` (default
  temporaneo, nel filesystem Linux/WSL). Una libreria su un disco Windows (`/mnt/c/...`)
  viene rifiutata, a meno di impostare `TAPER_ALLOW_WINDOWS_PATHS=1`.
- **Mai sovrascrivere**: se la cartella dell'album esiste già ne viene creata una nuova
  (`Anno - Album (2)`); i nomi sono sanificati per Linux e Windows (max 255 byte).
- **Idempotenza**: la sorgente è identificata dall'hash del file; riesportarla è rifiutato
  prima di tagliare, a meno di `--allow-duplicate`.
- **Database**: per ogni brano salva URL di origine, data di aggiunta, percorso, codec,
  bitrate, durata e se è stato ricodificato.
- `--no-library` salta export e database e lascia i brani taggati in `--out`.

Nota: per YouTube yt-dlp può richiedere un runtime JavaScript esterno (es. deno);
se il download fallisce, aggiorna yt-dlp (`uv lock --upgrade-package yt-dlp`).

## Nota legale

Scaricare da YouTube può violare i suoi termini di servizio. L'uso previsto è su
contenuti propri o liberi.
