<p align="center">
  <img src="assets/logo.svg" alt="Logo di taper: una forma d'onda tagliata da un marcatore" width="140">
</p>

<h1 align="center">taper</h1>

<p align="center">
  <em>Scarica, taglia, tagga, archivia. Senza ricodificare.</em>
</p>

---

App personale a riga di comando per scaricare tracce audio (YouTube e le altre fonti
supportate da [yt-dlp](https://github.com/yt-dlp/yt-dlp)), dividerle in brani — caso d'uso
principale: i concerti —, taggarle e archiviarle in una libreria ordinata.

Principio guida: **non ricodificare mai se non serve**, e dirlo ogni volta che si perde qualità.

> **Nota legale.** Scaricare da YouTube può violare i suoi termini di servizio. L'uso
> previsto è su contenuti propri o liberi. taper non aggira DRM né accessi a pagamento e
> non gestisce login o cookie.

## Requisiti e installazione

- Linux, WSL, macOS o Windows. Python 3.11+ (lo gestisce uv).
- [uv](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **ffmpeg e ffprobe nel PATH**: `sudo apt install ffmpeg` (Debian/Ubuntu/WSL),
  `brew install ffmpeg` (macOS), `winget install ffmpeg` (Windows).
- Per YouTube yt-dlp richiede un runtime JavaScript esterno, consigliato
  [deno](https://deno.com): senza, taper mostra un avviso e alcuni formati possono mancare.
  Se un download fallisce senza motivo evidente, aggiorna yt-dlp:
  `uv lock --upgrade-package yt-dlp && uv sync`.

```bash
git clone <questo repo> && cd taper
uv sync                  # crea l'ambiente e installa le dipendenze
uv run taper --help      # si usa con "uv run taper ..."
# oppure, per avere il comando "taper" ovunque:
uv tool install .
```

## Avvio rapido

```bash
uv run taper run "https://www.youtube.com/watch?v=..." \
    --artist "Nome Artista" --album "Live a Roma" --year 2019
```

Scarica, prepara il piano di taglio e **si ferma per farti controllare** artista, album,
anno e brani; poi taglia, tagga ed esporta in `~/taper-library`. Dettagli sotto.

## Comandi

| Comando | Cosa fa |
|---|---|
| `taper fetch <url>` | Scarica il miglior stream audio nel codec nativo (opus o m4a), senza ricodificare |
| `taper plan <file>` | Crea un piano di taglio YAML modificabile a mano |
| `taper cut <file> --plan <piano>` | Taglia, tagga, esporta in libreria, registra nel database |
| `taper run <url>` | `fetch` + `plan` + revisione interattiva + `cut` |

`taper <comando> --help` elenca tutte le opzioni.

### fetch

```bash
uv run taper fetch "https://www.youtube.com/watch?v=..." -o taper-downloads
```

Crea `taper-downloads/<id>/` con l'audio, la miniatura e `<id>.taper.json` (titolo, uploader,
data, capitoli, descrizione, miniatura). Se il video è già stato scaricato lo riusa invece
di riscaricarlo.

L'audio viene tenuto nel codec originale: il contenitore cambia (webm → `.opus`, mp4 →
`.m4a`) ma lo stream è copiato. Se la sorgente ha un codec che taper non sa conservare
(ac3, eac3, dts...) il comando si ferma con un errore chiaro invece di ricodificare in
silenzio. I warning di yt-dlp vengono mostrati in giallo (ad esempio la mancanza di un
runtime JavaScript, che può far sparire alcuni formati).

### plan

```bash
uv run taper plan taper-downloads/<id>/<id>.opus
uv run taper plan file.opus --source silence --silence-db -25 --min-segment 60
```

Sorgenti dei tagli, in ordine di priorità (`--source` per forzarne una):

1. **capitoli** del video;
2. **timestamp nella descrizione**: `00:00 Titolo`, `1:02:33 - Titolo`, `[00:00] Titolo`,
   `(1:02) Titolo`, `1. 00:00 Titolo`, `Titolo 00:00` e i range `00:00 - 04:12 Titolo`;
3. **rilevamento dei silenzi** con ffmpeg (`--silence-db`, `--silence-min`, `--min-segment`).
   Nei concerti tra un brano e l'altro ci sono spesso applausi e non silenzio: qui i tagli
   vanno controllati.

Il piano è un file YAML: per ogni segmento `start`, `end`, `title` e `source` (da quale
sorgente arriva il taglio). Tempi e titoli sono sempre tra virgolette (in YAML `1:02:33`
non quotato sarebbe un numero e `No` un booleano). I segmenti devono essere in ordine e
non sovrapposti. Un piano esistente non viene mai sovrascritto senza `--force`.

**Controlla sempre artista, album e anno.** Sono ricavati dal video — canale, titolo e
data di upload — e di solito non coincidono con quelli del concerto. Correggili nel
piano oppure con `--artist`, `--album`, `--year`.

### cut

```bash
uv run taper cut taper-downloads/<id>/<id>.opus --plan taper-downloads/<id>/<id>.plan.yaml
```

Come si taglia, senza perdere qualità:

- **Sorgenti lossy** (opus, m4a/aac, mp3, ogg): *stream copy*, poi ffprobe verifica durata e
  inizio di ogni brano. Solo se il taglio non è preciso (oltre 2 frame del codec) quel
  singolo segmento viene ricodificato con lo stesso codec, e il comando lo segnala.
- **Sorgenti lossless** (flac, wav, alac): ricodificate in FLAC, preciso al campione e
  senza perdite.
- L'originale non viene mai modificato; i brani già esistenti non vengono sovrascritti senza
  `--force`. I brani vengono prodotti in una cartella temporanea e spostati al loro posto solo
  se tutti sono riusciti: un errore a metà non lascia file a metà.
- **Precisione.** Con lo stream copy il taglio è preciso al frame del codec (circa 20 ms per
  opus). I segmenti dei piani generati sono contigui, ma i brani copiati **non sono gapless
  al campione**: ogni segmento opus eredita il pre-skip della sorgente (circa 6,5 ms che i
  decoder scartano) e mp3/vorbis possono perdere qualche ms ai confini. Con una sorgente
  lossless (FLAC) i brani sono contigui al campione. La precisione è verificata nei test
  sull'audio decodificato (impulsi a posizioni note), non solo sui metadati.
- Segmenti più brevi di 100 ms vengono rifiutati dalla validazione del piano.

Poi scrive i **tag** (titolo, artista, album artist, album, anno, numero traccia e totale)
e incorpora la **copertina**: la miniatura ritagliata in quadrato al centro (JPEG, max
1200 px). Formati: opus, ogg, m4a, mp3, flac. Per i file locali la copertina viene cercata
come `<nome>.jpg|png|webp` o `cover.jpg` accanto al file; `--no-cover` la disattiva.

### run

Scarica (o riusa) la sorgente, crea il piano e **si ferma**: mostra artista, album, anno e
l'elenco dei brani con gli avvisi su ciò che è stato dedotto, poi chiede `c` continua,
`e` apre il piano nell'editor (`$VISUAL` / `$EDITOR`, altrimenti nano/vim) e lo ricontrolla,
`a` annulla (il piano resta salvato). Un piano non valido non si può confermare.

- `--yes` salta la revisione (serve anche senza terminale, ad esempio negli script).
- Un piano già esistente per quel video viene riutilizzato: le tue modifiche non si perdono.
- Una sorgente già in libreria viene rifiutata *prima* della revisione (`--allow-duplicate`
  per esportarla comunque); una libreria non ammessa viene rifiutata prima di scaricare.

## Libreria

```
<libreria>/Artista/Anno - Album/NN - Titolo.ext      (+ cover.jpg)
<libreria>/.taper/library.db                         (percorsi relativi: la libreria è spostabile)
```

- **Dove**: `--library`, altrimenti `$TAPER_LIBRARY`, altrimenti `~/taper-library` (default
  provvisorio, nel filesystem Linux/WSL). Una libreria su un disco Windows (`/mnt/c/...`)
  viene rifiutata, a meno di impostare `TAPER_ALLOW_WINDOWS_PATHS=1`.
- **Mai sovrascrivere**: se la cartella dell'album esiste già ne viene creata una nuova
  (`Anno - Album (2)`). I nomi sono sanificati per Linux e Windows (caratteri vietati, nomi
  riservati, punti finali, massimo 255 byte).
- **Idempotenza**: la sorgente è identificata dall'hash del file, non dall'URL. Se cancelli a
  mano una cartella di album il database se ne accorge: la sorgente non risulta più "già in
  libreria" e i vecchi record vengono ripuliti al prossimo export.
- **Database** (SQLite): per ogni brano salva URL di origine, data di aggiunta, percorso,
  codec, bitrate, durata e se è stato ricodificato.
- `--no-library` salta export e database e lascia i brani taggati nella cartella `--out`.

## Formato dei file

taper mantiene il codec nativo dello stream: da YouTube di solito **opus** (`.opus`),
a volte AAC (`.m4a`). È la scelta che non perde qualità, ma non tutte le app leggono
`.opus` (ad esempio Apple Music/iPhone e i file locali di Spotify no). Convertire in mp3
significherebbe una seconda compressione con perdita: se serve una copia compatibile, va
trattata come export derivato e non come archivio (vedi punti di estensione).

## Struttura del codice

```
src/taper/
  cli.py          guscio Typer: argomenti, stampe, domande all'utente. Nessuna logica
  config.py       dove sta la libreria (opzione > $TAPER_LIBRARY > default)
  models.py       dataclass: SourceInfo, Chapter, Segment, AlbumMeta, CutPlan, Track
  errors.py       TaperError(message, hint) e sottoclassi
  core/           nessuna dipendenza dalla CLI: non stampa e non fa domande
    fetch.py      yt-dlp -> cartella di lavoro + sidecar <id>.taper.json
    plan.py       capitoli / descrizione / silenzi, YAML, validate_plan()
    timestamps.py parsing dei timestamp (puro)
    cut.py        stream copy verificato, ricodifica per segmento, lossless -> FLAC
    tagging.py    tag per opus/ogg/m4a/mp3/flac (mutagen)
    cover.py      ritaglio quadrato, JPEG
    export.py     layout Artista/Anno - Album e copia atomica
    library.py    SQLite
    pipeline.py   prepare(), cut_and_tag(), apply_plan(): le operazioni di alto livello
    ffmpeg.py     wrapper di ffmpeg/ffprobe        naming.py  nomi file sicuri
    progress.py   ProgressEvent e annullamento     sidecar.py lettura/scrittura sidecar
```

## Punti di estensione

Non implementati (fuori scopo per ora), ma il codice li prevede:

- **Interfaccia web locale (FastAPI + wavesurfer.js)**: il core è sincrono (si esegue in un
  threadpool), riporta l'avanzamento con `ProgressEvent` tramite una callback (ogni fase ha il
  suo `*_done`; `prepared` e `done` segnano la fine di `prepare()` e `apply_plan()`), si annulla
  con un `threading.Event` (anche il download, i tagli e il rilevamento dei silenzi), e i modelli dati (`models.py`) hanno `to_dict`/`from_dict`. `validate_plan()`
  restituisce tutti gli errori con l'indice del segmento; `prepare()` e `apply_plan()`
  sono già le due operazioni che la UI chiamerebbe, con la revisione in mezzo.
- **Nuove fonti (es. Live Music Archive)**: una funzione che produce un `FetchResult`
  (cartella con audio + sidecar) è tutto ciò che `plan` e `cut` richiedono.
- **Identificazione (AcoustID)**: un passo tra `cut` e `export` che completa i tag
  (`write_tags` riscrive i tag di un file già tagliato). Per salvare il risultato nel
  database basta una migrazione: lo schema è versionato con `PRAGMA user_version`.
- **EQ / confronto qualità / copie derivate (mp3, m4a)**: sono trasformazioni dei file in
  `tracks/` prima dell'export, oppure export aggiuntivi che usano `Track.reencoded` per
  dichiarare la perdita di qualità.

## Sviluppo

```bash
uv run pytest                                  # i test ffmpeg usano audio sintetico; senza ffmpeg vengono saltati
uv run ruff check . && uv run ruff format .
```

I test non scrivono mai nella libreria reale (`TAPER_LIBRARY` è reindirizzata a una cartella
temporanea) e non usano la rete.
