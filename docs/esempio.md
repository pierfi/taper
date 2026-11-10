# Esempio d'uso

Un concerto di un'ora e cinquanta, da un URL a una libreria di 20 brani taggati,
passo per passo. I blocchi di output sono quelli veri di taper (taglio solo le
righe ripetitive, segnate con `[...]` e i percorsi lunghi accorciati); la
cartella `taper-downloads/` e la libreria sono fuori da git.
Per i comandi nel dettaglio: [README](../README.md).

> Usa taper su contenuti tuoi o liberi: vedi la nota legale nel README.

## 1. Scaricare

```bash
taper fetch "https://www.youtube.com/watch?v=J_7TEw59ww8" -o taper-downloads
```

taper scarica l'audio **nel codec originale** (qui opus), senza ricodificare, e
crea una cartella per il video:

```
taper-downloads/J_7TEw59ww8/
├── J_7TEw59ww8.opus        99 MB   l'audio, intatto
├── J_7TEw59ww8.taper.json   3 KB   titolo, canale, data, capitoli, descrizione
└── J_7TEw59ww8.webp        46 KB   la miniatura (diventerà la copertina)
```

Rilanciare il comando riusa la cartella invece di riscaricare.

## 2. Preparare il piano di taglio

```bash
taper plan taper-downloads/J_7TEw59ww8/J_7TEw59ww8.opus
```

```
Piano creato da 'chapters': 20 segmenti
  Artista: Sepehr Rashidi  |  Album: John Mayer - Rise For The River (21/08/2022)  |  Anno: 2023
   1.     0:00 →     8:25  Queen of California
   2.     8:25 →    11:52  The Age of Worry
   3.    11:52 →    16:15  Shadow Days
  [...]
  19.  1:32:32 →  1:40:40  Dear Marie
  20.  1:40:40 →  1:51:15  In the Blood
  ! Artista ricavato dal canale 'Sepehr Rashidi': probabilmente va corretto in 'album.artist' (o con --artist).
  ! Anno ricavato dalla data di upload (20230828): potrebbe non essere l'anno del concerto (--year).
  ! Il titolo dell'album è il titolo del video: sistemalo in 'album.album' (--album).

Piano: taper-downloads/J_7TEw59ww8/J_7TEw59ww8.plan.yaml
```

I tagli arrivano dai **capitoli** del video. Se non ci sono, taper cerca i
timestamp nella descrizione e, in ultima istanza, i silenzi (vedi
[più sotto](#quando-non-ci-sono-capitoli-né-timestamp)). Le righe con `!` dicono
cosa è stato **dedotto** e quindi va controllato: qui artista, album e anno sono
quelli del canale e del video, non del concerto.

## 3. Correggere il piano

Il piano è un file YAML da modificare a mano. Si correggono i metadati dell'album
(oppure si passano `--artist`, `--album`, `--year` a `plan`):

```yaml
album:
  artist: "John Mayer"            # era "Sepehr Rashidi"
  album: "Rise For The River"     # era il titolo del video
  year: 2022                      # era 2023
segments:
  - start: "0:00:00.000"
    end: "0:08:25.000"
    title: "Queen of California"
    source: chapters              # da dove arriva questo taglio
  [...]
```

Tempi e titoli restano tra virgolette; i segmenti devono essere in ordine e non
sovrapposti. Si possono rinominare, spostare i confini, togliere o unire brani.

## 4. Tagliare, taggare, archiviare

```bash
taper cut taper-downloads/J_7TEw59ww8/J_7TEw59ww8.opus \
    --plan taper-downloads/J_7TEw59ww8/J_7TEw59ww8.plan.yaml \
    --library ./taper-library
```

```
  taglio [1/20 Queen of California]
  [...]
  export [20/20 20 - In the Blood.opus]
  Export completato
Tagliati 20 brani → [...]/taper-library/John Mayer/2022 - Rise For The River
  01 - Queen of California.opus  (8:25, copy)
  02 - The Age of Worry.opus  (3:27, copy)
  [...]
  20 - In the Blood.opus  (10:35, copy)
Nessuna perdita di qualità.
Tag scritti (con copertina).
```

Con `copy` accanto a ogni brano: **stream copy**, nessuna ricodifica (circa 20
secondi per l'intero concerto). Se un taglio non fosse preciso, taper
ricodificherebbe solo quel brano e lo direbbe qui.

Senza `--library` la libreria è `$TAPER_LIBRARY`, altrimenti `~/taper-library`.

## 5. Il risultato

```
taper-library/
├── .taper/library.db
└── John Mayer/
    └── 2022 - Rise For The River/
        ├── 01 - Queen of California.opus
        ├── 02 - The Age of Worry.opus
        ├── [...]
        ├── 20 - In the Blood.opus
        └── cover.jpg
```

I tag di un brano (`08 - Love Is a Verb.opus`), con la copertina incorporata:

```
album         Rise For The River
albumartist   John Mayer
artist        John Mayer
date          2022
title         Love Is a Verb
tracknumber   8
totaltracks   20
```

Il database (SQLite, `.taper/library.db`) ricorda per ogni brano titolo, artista,
album, anno, codec, bitrate, durata e se è stato ricodificato (`reencoded`: qui 0
per tutti i 20 brani).

Rilanciare `cut` sulla stessa sorgente non crea doppioni: la sorgente è
riconosciuta dal suo hash.

```
Errore: Questa sorgente è già in libreria ('John Mayer - Rise For The River (21/08/2022)',
20 brani, aggiunta il 2026-11-10T19:19:57+00:00; es. John Mayer/2022 - Rise For The River/01 - Queen of California.opus).
Suggerimento: Usa --allow-duplicate per esportarla di nuovo in una nuova cartella.
```

## Tutto in un comando: `run`

I passi 1-4 si possono fare in uno, con la pausa di revisione in mezzo:

```bash
taper run "https://www.youtube.com/watch?v=J_7TEw59ww8" \
    --artist "John Mayer" --album "Rise For The River" --year 2022
```

`run` scarica (o riusa), prepara il piano e **si ferma** per farti controllare
artista, album, anno e brani: continui, apri il piano nell'editor o annulli.
`--yes` salta la revisione (per gli script).

## Quando non ci sono capitoli né timestamp

Non tutti i video sono così ordinati. Questo è un altro concerto, senza capitoli
e con la scaletta nella descrizione ma senza tempi:

```bash
taper plan taper-downloads/353lHGbvu8o/353lHGbvu8o.opus
```

```
Piano creato da 'silence': 12 segmenti
  Artista: KEXP  |  Album: The Lumineers - Full Performance (Live on KEXP)  |  Anno: 2016
   1.     0:00 →     1:10  Track 01
   2.     1:10 →     7:31  Track 02
  [...]
  10.    38:16 →    55:44  Track 10
  11.    55:44 →    56:35  Track 11
  12.    56:35 →  1:06:39  Track 12
  ! Tagli da silenzi: controlla i confini, nei live possono essere imprecisi.
  [...]
```

taper ha tagliato sui silenzi e lo dice: la descrizione elenca 15 brani, i silenzi
ne trovano 12, e `Track 10` dura 17 minuti perché tra un brano e l'altro ci sono
applausi, non silenzio. Qui il piano va corretto ascoltando: si aggiungono i
confini mancanti, si danno i titoli veri e solo dopo si lancia `cut`. È il motivo
per cui `run` si ferma sempre a chiedere.
