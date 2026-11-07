Voglio sviluppare "taper", una app desktop personale per scaricare tracce audio
(YouTube e altre fonti supportate da yt-dlp), dividerle in più brani (caso d'uso
principale: concerti), taggarle e archiviarle in una libreria ordinata.
Partiamo da un MVP a riga di comando; in futuro ci sarà una UI web locale
(FastAPI + wavesurfer.js), quindi tieni la logica separata dalla CLI.

## Stack
- Python 3.11+, gestione progetto con uv, layout src/taper/
- Typer per la CLI, yt-dlp (come libreria) per il download, ffmpeg/ffprobe via
  subprocess, mutagen per i tag, Pillow per le copertine, SQLite (stdlib) per la
  libreria, PyYAML per i piani di taglio
- pytest per i test, ruff per lint e formattazione
- Compatibile con Linux, Windows e WSL: usa pathlib, niente path hardcoded

## Architettura
- Un core in `taper/core/` senza dipendenze dalla CLI: fetch.py, plan.py, cut.py,
  tagging.py, cover.py, library.py. La CLI in `taper/cli.py` è solo un guscio sottile.
- Ogni modulo espone funzioni pure e testabili, con dataclass per i dati
  (Track, CutPlan, Segment, SourceInfo).

## Funzioni MVP
1. `taper fetch <url>`: scarica il miglior stream audio nel codec NATIVO (es. opus
   o m4a), senza ricodificare. Salva accanto al file un JSON con titolo, uploader,
   data, capitoli, descrizione e miniatura.
2. `taper plan <file>`: genera un piano di taglio in YAML modificabile a mano
   (start, end, titolo per segmento). Sorgenti in ordine di priorità:
   a) capitoli del video; b) timestamp trovati nella descrizione (regex robusta
   per formati tipo "00:00 Titolo", "1:02:33 - Titolo"); c) rilevamento silenzi con
   ffmpeg silencedetect, con soglie configurabili. Scrivi nel piano da quale
   sorgente arriva ogni taglio.
3. `taper cut <file> --plan plan.yaml`: taglia i segmenti. Usa stream copy quando
   possibile; se il taglio non è preciso, ricodifica solo quel segmento e avvisa.
   Mai sovrascrivere l'originale.
4. Tagging e copertina: scrivi titolo, artista, album, anno, numero traccia,
   totale tracce; incorpora la copertina (miniatura ritagliata in quadrato) e salva
   anche cover.jpg nella cartella. Supporta opus, m4a, mp3, flac.
5. Export nella struttura `Artista/Anno - Album/NN - Titolo.ext` con nomi file
   sanificati. Registra ogni elemento in SQLite (URL di origine, data, percorso,
   codec, bitrate, durata).
6. `taper run <url>`: esegue fetch, plan, poi si ferma e chiede di rivedere il
   piano (apre il file YAML o mostra l'elenco) prima di tagliare e taggare.
   Aggiungi `--yes` per saltare la conferma.

## Regole
- Non ricodificare mai se non serve; segnala sempre quando perdi qualità.
- Errori chiari e utili (ffmpeg mancante, URL non supportato, piano non valido).
- Test sui pezzi puri (parsing timestamp, validazione piano, sanificazione nomi);
  per ffmpeg usa file audio sintetici generati nei test.
- README con installazione, esempi d'uso e una nota: scaricare da YouTube può
  violare i suoi termini di servizio, uso previsto su contenuti propri o liberi.
- Fuori scopo per ora: EQ, confronto qualità, UI, Live Music Archive, AcoustID.
  Non implementarli, ma lascia i punti di estensione.

## Come lavorare
Prima di scrivere codice proponimi in breve la struttura delle cartelle e le
scelte che ti sembrano dubbie. Poi procedi per passi piccoli, un commit per passo,
nell'ordine: scaffolding e CLI vuota, fetch, plan, cut, tagging e cover,
libreria e export, run end-to-end. Dopo ogni passo mostrami come provarlo.