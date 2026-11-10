# Proposte

Idee per nuove funzioni di taper, scritte perché qualsiasi strumento le possa
leggere, discutere e portare avanti:

- **claude.ai** (o un'altra chat) per pensarle e cambiarle;
- **Claude Code** per realizzarle;
- **altri assistenti** per una seconda opinione.

Una proposta è una cartella: tutto quello che serve per capirla sta lì dentro,
e il suo README basta da solo a un assistente che non conosce il progetto. È il
primo passo del [flusso di lavoro](../docs/statuto-ia.md).

## Indice

Le proposte entrano in `main` solo da realizzate; finché sono in corso vivono
sul loro branch, con la loro riga di questo indice, che arriva in `main` con la
PR finale. Per vederle:

```bash
git fetch && git branch -r --list 'origin/proposals/*' 'origin/feature/*'
```

| N. | Proposta | Stato | Aggiornata | Decisioni aperte |
|---|---|---|---|---|
| [0001](0001-video-track/) | Traccia video equivalente all'audio | bozza | 2026-11-10 | D3 (contratto con il progetto parallelo), D6, D7 |

## Com'è fatta una proposta

```
proposals/
├── README.md              regole e indice (questo file)
├── _modello/              da copiare per una proposta nuova
│   ├── README.md
│   └── revisione.md
└── NNNN-nome/
    ├── README.md          la proposta: l'unico file obbligatorio
    ├── prototipo/         codice che gira dalla root del repo
    └── revisioni/         pareri di altri strumenti, un file ciascuno
```

- **Numero** a 4 cifre, in ordine, mai riusato; **nome** breve, minuscolo, con i trattini.
- **README autosufficiente**: in testa a chi è rivolto e cosa si chiede; poi
  contesto, proposta, alternative, decisioni aperte, criteri di accettazione,
  verifiche, piano di integrazione e registro. Si parte da
  [_modello/README.md](_modello/README.md).
- **Criteri di accettazione**: cosa deve essere vero, e come si controlla, perché
  la realizzazione si consideri fatta. Sono il contratto per Claude Code e la
  checklist della PR.
- **Decisioni aperte** numerate D1, D2, ... dentro la proposta; da fuori si
  citano con il numero della proposta: `0001/D3`.
- **Prototipo**: importa da `taper` ma non lo modifica, e scrive solo nella
  cartella della proposta.
- **Esempi veri**: output di comandi reali, mai scritti a mano.

## Stati

```
bozza ──► in-discussione ──► accettata ──► realizzata
                  │
                  └──► scartata  ·  sostituita
```

| Stato | Dove vive | Vuol dire |
|---|---|---|
| `bozza` | `proposals/NNNN-nome` | idea scritta, non ancora discussa |
| `in-discussione` | `proposals/NNNN-nome` | si discute, ci sono decisioni aperte |
| `accettata` | `feature/<nome>` | si fa: prototipi, test, chiusura delle decisioni, realizzazione |
| `realizzata` | `main` | proposta e codice entrati con una sola PR; la proposta resta come storia |
| `scartata` | il suo branch | resta, con il motivo nel registro |
| `sostituita` | il suo branch | rimanda alla proposta che la sostituisce |

## Branch

Lo schema illustrato è in [docs/statuto-ia.md](../docs/statuto-ia.md#5-la-strategia-di-branch).

- Una proposta nasce da `main` aggiornato, sul branch `proposals/NNNN-nome`;
  tocca solo `proposals/` e non entra in `main` finché si discute.
- Accettata, si stacca `feature/<nome>` e da lì si lavora; il branch della
  proposta resta com'era.
- Una sola PR verso `main`, aperta con `gh pr create`, quando la proposta è
  completa: decisioni chiuse, criteri soddisfatti, codice e documenti pronti.
- I commit seguono il formato di [CLAUDE.md](../CLAUDE.md#commit): una riga in
  inglese, `TPR-XXX: <commit-message>`, con il codice del task (non il numero
  della proposta) e senza righe di attribuzione.

## Chi fa cosa

| Strumento | Ruolo | Legge | Scrive |
|---|---|---|---|
| claude.ai o chat di ideazione | la proposta nasce e cambia qui | il README della proposta sul suo branch | README e registro della proposta |
| Claude Code | da accettata: realizzazione e verifiche | tutta la cartella | prototipi, codice, stato, registro, indice |
| Altri assistenti | seconda opinione | il README e i vincoli | niente: la risposta si salva in `revisioni/` |

### Da Claude Code

```
Sul branch feature/<nome>, leggi CLAUDE.md, proposals/README.md e
proposals/NNNN-nome/README.md e realizza il "Piano di integrazione".
Alla fine aggiorna stato e registro della proposta e la riga dell'indice,
poi apri la PR con gh pr create.
```

### Da claude.ai

claude.ai non scrive nel repo: legge i file che gli si danno (o il repo
collegato) e scrive la proposta come testo. Chi la riceve (Claude Code o
l'autore) la salva in `proposals/NNNN-nome/README.md` su un branch
`proposals/NNNN-nome`, con un commit e un push: **nessuna PR** finché la
proposta è in discussione (la PR è una sola, a feature realizzata).

```
Leggi README.md, CLAUDE.md, docs/statuto-ia.md e proposals/README.md di taper
(https://github.com/pierfi/taper). Valuta il lavoro fatto e scrivi una
proposta per la prossima funzione che ti sembra più utile, usando il modello
di proposals/_modello/README.md: in italiano, con decisioni aperte numerate,
criteri di accettazione verificabili e un piano di integrazione per Claude
Code. Rispetta i vincoli di progetto di CLAUDE.md.
```

### Da un altro assistente

Dagli il README della proposta e la sezione "Vincoli di progetto" di
[CLAUDE.md](../CLAUDE.md#vincoli-di-progetto). Poi questo prompt:

```
Rivedi una proposta per un progetto personale: taper, un'app a riga di comando
(Python) che scarica audio, lo divide in brani, lo tagga e lo archivia. Il file
allegato è la proposta; i vincoli del progetto sono nel testo allegato e nella
sezione "Vincoli" della proposta, le scelte ancora da fare in "Decisioni aperte".

Rispondi in italiano, in quest'ordine:
1. In una frase: la proposta regge?
2. Per ogni decisione aperta (D1, D2, ...): cosa sceglieresti e perché, in due righe.
3. Problemi che non vedo: concreti, citando la parte della proposta.
4. Cosa toglieresti.

Non riscrivere la proposta e non uscire dai vincoli.
```

La risposta va in `revisioni/AAAA-MM-GG-<strumento>.md`, con il modello
[_modello/revisione.md](_modello/revisione.md). Una revisione non cambia la
proposta da sola: le decisioni che ne nascono entrano nel README della proposta
e nel suo registro.
