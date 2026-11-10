---
numero: "0001"
titolo: Traccia video equivalente all'audio
stato: bozza
creata: 2026-11-10
aggiornata: 2026-11-10
origine: analisi su claude.ai (progetto parallelo a taper) e bozza di Claude Code, con le risposte dell'autore del 2026-11-10
branch: proposals/0001-video-track
branch-lavoro: feature/video-track
task: TPR-003
issue:
tocca: [src/taper/core/fetch.py, src/taper/core/cut.py, src/taper/core/pipeline.py, src/taper/core/export.py, src/taper/core/library.py, src/taper/core/ffmpeg.py, src/taper/models.py, src/taper/cli.py, tests/, README.md, docs/esempio.md]
---

# Traccia video equivalente all'audio

> **Per chi legge.** Questa è una **bozza** scritta da Claude Code a partire dalle
> risposte dell'autore. Si chiede a claude.ai (che sta ragionando sul progetto
> parallelo) di rivederla: in particolare **D3**, il contratto di integrazione, per
> cui l'autore darà istruzioni. Le decisioni D1, D2, D4 e D5 sono già prese e vanno
> solo controllate; D3, D6 e D7 sono aperte.

## In breve

taper scarica anche la **traccia video** della stessa sorgente e la taglia con gli
**stessi tagli** del piano audio, così ogni brano ha affiancato il suo video. È il
punto di contatto con un **progetto parallelo**, fuori da taper, che consuma la
libreria: taper resta "scarica, taglia, tagga, archivia" e il resto sta altrove.

## Contesto

- Oggi taper scarica solo audio: `build_ydl_options` in `src/taper/core/fetch.py`
  chiede `bestaudio/best` e `remux_native` tiene l'audio nel suo codec, per copia.
  Il video non viene mai scaricato.
- `src/taper/core/cut.py` taglia l'audio in stream copy, con `-ss` dopo `-i`, e
  verifica durata e inizio di ogni brano con ffprobe; ricodifica un singolo brano
  solo se il taglio non è preciso, e lo dichiara.
- La libreria è `Artista/Anno - Album/NN - Titolo.ext` più un database SQLite
  (`.taper/library.db`, schema versionato con `PRAGMA user_version`, oggi 1) con le
  tabelle `sources` e `tracks`.
- Il progetto parallelo non è descritto qui: di lui serve solo il contratto con
  taper (D3).

## Vincoli

Quelli del progetto sono in [CLAUDE.md](../../CLAUDE.md#vincoli-di-progetto). In più:

- **Opt-in.** Senza opzioni video taper si comporta esattamente come oggi.
- **Mai ricodificare in silenzio**, anche per il video: stream copy per
  impostazione, ricodifica solo se richiesta e dichiarata.
- **Stesso piano.** Un solo piano di taglio per audio e video; niente piani separati.
- **Lo spazio su disco è fuori scope** per ora (D4); un tetto di qualità invece sì.

## Proposta

### Cosa si aggiunge

| Comando | Novità |
|---|---|
| `taper fetch <url> --video` | scarica anche lo stream video, **senza audio**, accanto all'audio: `<id>/<id>.video.<ext>` |
| `taper run <url> --video` | come `fetch` + `plan` + revisione + `cut`, con il video |
| `taper cut <file> --plan <piano>` | se trova il video della sorgente lo taglia con gli stessi segmenti |
| `--video-quality <N>` | tetto di qualità: altezza massima in pixel (es. 720, 1080) |
| `--reencode-video` | taglio preciso al frame, **con ricodifica dichiarata** |

### Equivalenza (D1)

Il video di un brano è il tratto della sorgente video con gli **stessi `start` e `end`**
del brano audio: stessa durata, stesso taglio. L'audio resta quello di sempre, in
file e codec nativi; il video è un file in più, solo video, con lo **stesso nome base**
(`NN - Titolo.mp4`, `NN - Titolo.webm`, ...) accanto al file audio.

### Download

yt-dlp scarica già audio e video come stream separati. Si aggiunge un secondo formato,
`bestvideo[height<=N]`, senza audio. Il video segue la regola dell'audio:
`remux_video_native()` lo mette nel suo contenitore per **copia** (avc1 in `.mp4`,
vp9 in `.webm`, av1 in `.mp4`) e un codec che taper non sa conservare ferma il comando
con un errore chiaro e un suggerimento, senza ricodificare (D5). Una verifica di
coerenza confronta la durata del video con quella dell'audio e avvisa se non
coincidono.

### Taglio e precisione (D2)

Il video non si taglia al campione come l'audio: in stream copy si può partire solo da
un **keyframe**. Un esperimento (vedi "Verifiche fatte") mostra i due comportamenti
possibili di ffmpeg con `-c copy` quando il taglio cade tra due keyframe:

| Taglio | Cosa succede | Problema |
|---|---|---|
| `-ss` **prima** di `-i` | il file parte dal keyframe precedente e i frame prima del taglio sono marcati come scartati (edit list) | esatto solo nei player che rispettano l'edit list; il file contiene secondi in più |
| `-ss` **dopo** `-i` | il file parte dal keyframe **successivo** | il video parte in ritardo rispetto all'audio |

Proposta: usare la prima forma, perché non perde il contenuto e non desincronizza, e
**misurare e registrare** lo scarto reale: `video_offset_ms` è la differenza tra
l'inizio del primo frame decodificabile e l'`start` del piano. Con `--reencode-video`
il segmento si ricodifica (stessa famiglia di codec, qualità dichiarata), il taglio è
preciso al frame, `video_offset_ms` vale 0 e il comando avvisa della perdita di qualità,
come già fa taper per l'audio.

### Contratto di integrazione (D3, aperta)

Il progetto parallelo deve poter trovare, per ogni brano, il suo audio e il suo video
senza indovinare. Proposta di default (**A**), da confermare con le istruzioni
dell'autore:

- **File.** Stesso nome base dell'audio, estensione del contenitore video.
- **Database.** Schema 2 (migrazione da 1 senza perdere righe): colonne in `tracks`
  `video_path`, `video_codec`, `video_width`, `video_height`, `video_duration_ms`,
  `video_offset_ms`, `video_reencoded`.
- **Documento.** `docs/contratto-video.md` descrive file e colonne come interfaccia
  stabile tra i due progetti, con la versione dello schema.

### Moduli toccati

- `fetch.py`: formato video, `FetchResult.video`, `remux_video_native`.
- `cut.py`: taglio video in stream copy e variante con ricodifica, con verifica ffprobe
  e scrittura atomica, come per l'audio.
- `ffmpeg.py`: `probe_video` e misura del primo frame decodificabile.
- `models.py`: `Track.video` opzionale (`VideoTrack`), con `to_dict`/`from_dict`.
- `export.py`, `library.py`: copia atomica del video accanto all'audio e migrazione dello schema.
- `cli.py`: le opzioni sopra, solo come guscio; la logica resta in `core/`.

## Alternative considerate

| Opzione | Pro | Contro | Esito |
|---|---|---|---|
| Video **muxato** nello stesso file dell'audio | un solo file per brano | cambia l'audio nativo (opus in mp4) o lo duplica; rompe "i brani sono come l'originale" | scartata |
| Video **intero**, non tagliato | semplice e preciso | il progetto parallelo dovrebbe tagliare da sé | scartata per D1 |
| **Sempre ricodificare** il video | taglio preciso al frame | perdita di qualità e tempo; viola il principio guida | scartata per D2 |
| Comando separato `taper video` | separazione netta | duplica `fetch`/`cut` e il concetto di sorgente | scartata: meglio un'opzione |
| Opzione `--video` su `fetch`/`run`/`cut` | un solo flusso e un solo piano | `cut` e `pipeline` acquistano un ramo in più | **scelta** |

## Decisioni aperte

- [x] **D1. Equivalenza.** Stessa durata e stesso taglio: il video di un brano usa gli
      stessi `start`/`end` del brano audio. Chiusa 2026-11-10, risposta dell'autore.
- [x] **D2. Precisione.** Stream copy sui keyframe, con lo scarto misurato e dichiarato;
      ricodifica solo con `--reencode-video`, dichiarata. Chiusa 2026-11-10, risposta
      dell'autore ("ok" alla proposta).
- [ ] **D3. Contratto di integrazione con il progetto parallelo.** Come si trovano audio
      e video della stessa sorgente e cosa si garantisce (nome base, colonne del database,
      offset del video, documento). Default proposto: **A** sopra. In attesa delle
      istruzioni dell'autore e della revisione di claude.ai. Alternative: B) un file
      `.json` accanto a ogni brano; C) un manifest per album.
- [x] **D4. Spazio.** Ignorato per ora (nessuna pulizia dei download, nessun tetto di
      dimensione); sì al **tetto di qualità** `--video-quality`. Chiusa 2026-11-10,
      risposta dell'autore.
- [x] **D5. Codec e contenitore.** Remux per copia; un codec video non conservabile ferma
      il comando con errore e suggerimento. Chiusa 2026-11-10, risposta dell'autore ("ok").
- [ ] **D6. Valori predefiniti.** Il video è opt-in (`--video`) o attivo per impostazione?
      Tetto di qualità predefinito: nessuno, 1080 o altro? Proposta: opt-in e 1080.
- [ ] **D7. Sorgenti locali.** Per un file audio locale il video si può passare con
      `--video-file <file>`? Proposta: fuori dalla prima versione, che copre solo le
      sorgenti scaricate con `fetch`/`run`.

Quando una decisione si chiude: `[x]`, la scelta, la data e dove è stata presa.

## Criteri di accettazione

Da confermare quando la proposta passa ad `accettata`; sono la checklist della PR.

- [ ] Senza opzioni video nulla cambia: i test esistenti (214) passano invariati.
- [ ] `taper fetch <url> --video` produce `<id>.video.<ext>` e conserva il codec video
      della sorgente, senza ricodifica. Controllo: test con video sintetico (`testsrc`)
      e confronto del codec con ffprobe; nessuna rete.
- [ ] Ogni brano ha il video accanto all'audio, con lo stesso nome base. Controllo: test
      su sorgente sintetica con keyframe a distanza nota.
- [ ] `video_offset_ms` nel database coincide con lo scarto misurato con ffprobe sul
      file tagliato (tolleranza 1 frame), e il video copre almeno l'intervallo `start`-`end`.
- [ ] `--reencode-video` ricodifica solo i video, lo dichiara a video e nel database
      (`video_reencoded`), ed è preciso al frame.
- [ ] Un codec video non conservabile ferma il comando con errore e suggerimento e non
      lascia file a metà (come l'audio).
- [ ] `--video-quality N` limita l'altezza. Controllo: test sul formato richiesto a yt-dlp
      (puro, senza rete).
- [ ] Una libreria con schema 1 viene migrata a 2 senza perdere righe. Controllo: test con
      un database 1 reale.
- [ ] README, `docs/esempio.md` (con output vero) e `docs/contratto-video.md` aggiornati.

## Verifiche fatte

- Letto il codice di `fetch.py` (formato `bestaudio/best`), `cut.py` (`-ss` dopo `-i`,
  verifica con ffprobe) e `library.py` (schema 1, `PRAGMA user_version`).
- **Esperimento ffmpeg** (2026-11-10): video sintetico `testsrc` 320x180, 25 fps, un
  keyframe ogni 4 s (0, 4, 8, 12, ...). Taglio richiesto a 13,500 s, durata 10 s, `-c copy`:
  - `-ss` prima di `-i`: primo pacchetto a -1,52 s con flag *discard* (il file parte dal
    keyframe a 12,0 s e l'edit list nasconde i frame prima del taglio); durata 10,16 s;
  - `-ss` dopo `-i`: primo pacchetto a 2,50 s, cioè il file parte dal keyframe a 16,0 s,
    **2,5 s dopo** il taglio richiesto; durata 10,18 s;
  - con il taglio esattamente su un keyframe (12,000 s) entrambe le forme sono esatte.
- **Non verificato**: quali formati video offre yt-dlp per le sorgenti reali e quali codec
  (avc1, vp9, av1) incontreremo; il comportamento dell'edit list nei player del progetto
  parallelo; webm (senza edit list) con la prima forma di taglio; i tempi di ricodifica.

## File

| File | Cosa |
|---|---|
| `README.md` | questa proposta |
| `revisioni/` | pareri di altri strumenti (vuota per ora) |

## Piano di integrazione

Da eseguire su `feature/video-track`, dopo l'accettazione e la chiusura di D3, D6 e D7:

```
Sul branch feature/video-track, leggi CLAUDE.md, proposals/README.md e
proposals/0001-video-track/README.md e realizza la proposta, un commit per passo
(TPR-003: <commit-message>, una riga, in inglese):
1. schema 2 della libreria e migrazione, con test su un database 1;
2. download del video in fetch (formato con tetto, remux per copia, errori chiari);
3. taglio video in stream copy con misura di video_offset_ms, scrittura atomica;
4. --reencode-video;
5. cli, README, docs/esempio.md e docs/contratto-video.md.
Alla fine aggiorna stato e registro della proposta, la riga dell'indice in
proposals/README.md e il registro dei task in docs/statuto-ia.md, poi apri una
sola PR con gh pr create.
```

## Registro

| Data | Dove | Cosa |
|---|---|---|
| 2026-11-10 | Claude Code | prima bozza dalle risposte dell'autore (D1, D2, D4, D5 chiuse; D3, D6, D7 aperte); esperimento ffmpeg sui tagli video |
