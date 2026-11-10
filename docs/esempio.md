# Esempio d'uso

Da un file audio di un "concerto" a una libreria di brani taggati, passo per
passo. L'esempio è **riproducibile da zero**: la sorgente è un file sintetico
generato con ffmpeg (quattro note separate da silenzi), quindi non serve
scaricare niente né usare contenuti di altri. I blocchi di output sono quelli
veri di taper; le righe ripetitive sono abbreviate con `[...]`.

Per i comandi nel dettaglio: [README](../README.md). Un piano di taglio
commentato da copiare: [templates/esempio.plan.yaml](templates/esempio.plan.yaml).

## 0. La sorgente

```bash
ffmpeg -f lavfi -i "sine=frequency=262:duration=45" -f lavfi -i "anullsrc=r=48000:cl=mono:d=3" \
       -f lavfi -i "sine=frequency=330:duration=60" -f lavfi -i "anullsrc=r=48000:cl=mono:d=3" \
       -f lavfi -i "sine=frequency=392:duration=50" -f lavfi -i "anullsrc=r=48000:cl=mono:d=3" \
       -f lavfi -i "sine=frequency=523:duration=40" \
       -filter_complex "[0][1][2][3][4][5][6]concat=n=7:v=0:a=1,aformat=sample_rates=48000:channel_layouts=mono" \
       -c:a libopus -b:a 64k concerto.opus
```

Con un video vero il punto di partenza è `taper fetch <url>`: scarica l'audio
**nel codec originale** (di solito opus), senza ricodificare, in una cartella
con l'audio, la miniatura e un file `.taper.json` con titolo, canale, data,
capitoli e descrizione. Rilanciarlo riusa quella cartella. Da qui in poi i
passi sono gli stessi: taper lavora su qualunque file audio locale.

> Usa taper su contenuti tuoi o liberi: vedi la nota legale nel README.

## 1. Preparare il piano di taglio

```bash
taper plan concerto.opus --artist "Trio Sintetico" --album "Live a Nessun Posto" --year 2026
```

```
Piano creato da 'silence': 4 segmenti
  Artista: Trio Sintetico  |  Album: Live a Nessun Posto  |  Anno: 2026
   1.     0:00 →     0:46  Track 01
   2.     0:46 →     1:49  Track 02
   3.     1:49 →     2:42  Track 03
   4.     2:42 →     3:24  Track 04
  ! Tagli da silenzi: controlla i confini, nei live possono essere imprecisi.

Piano: concerto.plan.yaml
Modificalo se serve, poi: taper cut concerto.opus --plan concerto.plan.yaml
```

Questo file non ha capitoli né timestamp, quindi taper ha tagliato sui
**silenzi** e lo dice. Con un video di YouTube i tagli arrivano, in ordine di
priorità, dai capitoli, dai timestamp nella descrizione (`00:00 Titolo`) e solo
in ultima istanza dai silenzi. Le righe con `!` segnalano cosa è stato
**dedotto** e va controllato: con un video vero, artista, album e anno
verrebbero da canale, titolo e data di upload, che di solito non sono quelli del
concerto (qui li abbiamo già passati con `--artist`, `--album`, `--year`).

## 2. Correggere il piano

Il piano è un file YAML da modificare a mano
([un esempio commentato](templates/esempio.plan.yaml)). Qui bastano i titoli:

```yaml
segments:
  - start: "0:00:00.000"
    end: "0:00:46.500"
    title: "Do"                   # era "Track 01"
    source: silence
  [...]
```

Tempi e titoli restano tra virgolette; i segmenti devono essere in ordine e non
sovrapposti. Si possono rinominare, spostare i confini, togliere o unire brani.

## 3. Tagliare, taggare, archiviare

```bash
taper cut concerto.opus --plan concerto.plan.yaml --library ./taper-library
```

```
  taglio [1/4 Do]
  [...]
  Taglio completato
  tag [1/4 Do]
  [...]
  Tag scritti
  export [1/4 01 - Do.opus]
  [...]
  Export completato
  Fatto
Tagliati 4 brani → ./taper-library/Trio Sintetico/2026 - Live a Nessun Posto
  01 - Do.opus  (0:46, copy)
  02 - Mi.opus  (1:03, copy)
  03 - Sol.opus  (0:53, copy)
  04 - Do alto.opus  (0:41, copy)
Nessuna perdita di qualità.
Tag scritti (senza copertina).
Libreria: ./taper-library
Database: ./taper-library/.taper/library.db
  ! Nessuna copertina trovata: i brani non avranno immagine incorporata.
```

Con `copy` accanto a ogni brano: **stream copy**, nessuna ricodifica. Se un
taglio non fosse preciso, taper ricodificherebbe solo quel brano e lo direbbe
qui. La copertina, per un file locale, si cerca come `concerto.jpg` (o
`cover.jpg`) accanto al file; per un video scaricato è la miniatura.

Senza `--library` la libreria è `$TAPER_LIBRARY`, altrimenti `~/taper-library`.

## 4. Il risultato

```
taper-library/
├── .taper/library.db
└── Trio Sintetico/
    └── 2026 - Live a Nessun Posto/
        ├── 01 - Do.opus
        ├── 02 - Mi.opus
        ├── 03 - Sol.opus
        └── 04 - Do alto.opus
```

I tag di un brano, letti con
`ffprobe -v error -select_streams a:0 -show_entries stream_tags -of default=nw=1 "02 - Mi.opus"`:

```
TAG:title=Mi
TAG:artist=Trio Sintetico
TAG:album=Live a Nessun Posto
TAG:album_artist=Trio Sintetico
TAG:date=2026
TAG:track=2
TAG:tracktotal=4
TAG:totaltracks=4
```

Il database (SQLite, `.taper/library.db`) ricorda per ogni brano titolo, artista,
album, anno, codec, bitrate, durata e se è stato ricodificato (`reencoded`, qui 0
per tutti).

Rilanciare `cut` sulla stessa sorgente non crea doppioni: la sorgente è
riconosciuta dal suo hash.

```
Errore: Questa sorgente è già in libreria ('concerto', 4 brani, aggiunta il 2026-11-10T20:33:40+00:00; es. Trio Sintetico/2026 - Live a Nessun Posto/01 - Do.opus).
Suggerimento: Usa --allow-duplicate per esportarla di nuovo in una nuova cartella.
```

## Tutto in un comando: `run`

Per un URL, i passi di scaricamento, piano e taglio si fanno in uno, con la
pausa di revisione in mezzo:

```bash
taper run "https://www.youtube.com/watch?v=..." \
    --artist "Nome Artista" --album "Live a Roma" --year 2019
```

`run` scarica (o riusa), prepara il piano e **si ferma** per farti controllare
artista, album, anno e brani: continui, apri il piano nell'editor o annulli.
`--yes` salta la revisione (per gli script). È il motivo per cui `run` si ferma
sempre: i tagli da silenzi o da una descrizione imprecisa vanno controllati
ascoltando, prima di tagliare.
