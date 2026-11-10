# CLAUDE.md

Statuto di cooperazione con gli strumenti IA: il contesto condiviso da ogni
istanza di Claude che lavora su questo repo (Claude Code CLI, web/app,
@claude su GitHub, claude.ai) e la base per le revisioni di altri
assistenti. Come si passa da un'idea alla PR: [docs/workflow.md](docs/workflow.md);
lo statuto in grafica, con la strategia di branch: [docs/statuto-ia.md](docs/statuto-ia.md).
Le istruzioni valide su una sola macchina stanno in `CLAUDE.local.md`, non
versionato.

## Scopo

App personale a riga di comando che scarica tracce audio (YouTube e le altre
fonti di yt-dlp), le divide in brani (caso d'uso principale: i concerti), le
tagga e le archivia in una libreria ordinata. Uso e comandi:
[README.md](README.md); esempio completo: [docs/esempio.md](docs/esempio.md);
piano d'opera storico: [PLAN.md](PLAN.md).

## Architettura

```
src/taper/
  cli.py      guscio Typer: argomenti, stampe, domande all'utente; nessuna logica
  core/       la logica; non dipende dalla CLI, non stampa e non fa domande
  models.py   dataclass dei dati, con to_dict/from_dict; tempi in ms interi
  errors.py   TaperError(message, hint) e sottoclassi
tests/        un file per modulo, pytest; audio sintetico, niente rete
docs/         guide e documenti (workflow, esempio), immagini in docs/img/
proposals/    proposte di nuove funzioni (proposals/README.md)
assets/       logo
```

- `cli.py` importa da `core/`, mai il contrario.
- Il core è sincrono; l'avanzamento passa da `ProgressEvent` e l'annullamento
  da un `threading.Event`, così una futura UI web lo userà in un threadpool.
- I file nati in analisi o sviluppo (prototipi, uscite di prova) vanno in
  `proposals/NNNN-nome/prototipo/` o in `docs/<tema>/`, mai sciolti in `docs/`.

## Vincoli di progetto

Valgono per ogni feature e ogni proposta:

- **Mai ricodificare in silenzio.** Lo stream copy è la regola; ogni
  ricodifica è un'eccezione, segnalata all'utente e registrata (`reencoded`).
- **Mai sovrascrivere**: né l'originale, né i brani o gli album già in
  libreria, né un piano esistente senza `--force`.
- **File scaricati mai versionati**: audio, video, miniature e libreria stanno
  fuori da git (`.gitignore`). I test usano solo audio sintetico, non toccano la
  libreria vera (`TAPER_LIBRARY` va su una cartella temporanea) e non usano la rete.
- Una libreria su disco Windows (`/mnt/c/...`) è rifiutata, salvo `TAPER_ALLOW_WINDOWS_PATHS=1`.
- Niente DRM aggirato, login o cookie: il README ha la nota legale.
- Compatibile con Linux, WSL, macOS e Windows: `pathlib`, niente path fissi.

## Comandi

```bash
uv sync                                  # ambiente di sviluppo
uv run pytest                            # tutti i test (~70 s; senza ffmpeg i test ffmpeg sono saltati)
uv run ruff check . && uv run ruff format --check .
uv run taper --help
```

## Convenzioni di codice

- Docstring, commenti, messaggi per l'utente e documentazione in italiano.
  Commit e titoli delle PR in inglese, nel formato dei [commit](#commit).
- Mai il trattino lungo (U+2014): sempre `-`, in codice, documenti, commit e PR.
  Se serve riconoscerlo in un input (come nel parser dei timestamp) si scrive
  l'escape `\u2014`, mai il carattere.
- Niente commenti a banner (`# ====`): al massimo una riga semplice.
- Test: `tests/test_<modulo>.py`; un comportamento nuovo ha il suo test, e un
  bug corretto ha il test che lo avrebbe preso. Lint e formato con ruff, 100 colonne.
- Gli esempi nei documenti riportano l'output vero di un comando, non scritto a mano.

## Regole di lavoro

- Mai commit diretti su `main` (dopo il primo caricamento del repo): si lavora
  su un branch e si entra con una **pull request**, che l'utente rivede e mergia.
- Le PR si aprono con **`gh pr create`**, usando il template di
  [.github/pull_request_template.md](.github/pull_request_template.md). Si mergia
  solo su richiesta dell'utente, con merge commit.
- Ogni funzione nuova parte da una proposta (`proposals/NNNN-nome/`) o da una
  issue con criteri di accettazione. I fix piccoli vanno direttamente in PR.
- Branch: `proposals/NNNN-nome` per una proposta in discussione (tocca solo
  `proposals/`), `feature/<nome>` per una feature, `tpr-XXX-<nome>` per un task
  senza proposta (flusso di lavoro, manutenzione, fix). Un branch lungo si aggiorna con
  `git merge main`, mai con rebase o force push dopo la pubblicazione.
- In una sessione interattiva: prima di ogni commit mostrare le modifiche e
  aspettare l'ok. Da @claude: branch e PR, mai merge.
- Commit piccoli e coerenti, test verdi a ogni commit.

### Codici dei task

- L'acronimo di progetto è **TPR** (taper). Ogni task futuro è `TPR-XXX`: tre
  cifre, in ordine, mai riusate (`TPR-001`, `TPR-002`, ...). Il codice compare
  nel [registro](docs/workflow.md#registro), nei commit, nel titolo della PR e,
  se il branch è di un solo task, nel suo nome (`tpr-XXX-<nome>`).
- Le fasi più grandi sono le **milestone**, con codice `M<N>` (`M1`, `M2`, ...),
  registrate nello stesso registro. Una fase può avere un codice specifico
  proprio, purché lo dichiari lì prima di usarlo.
- Il numero di una proposta (`0001`) identifica la proposta, non il lavoro: i
  commit che la riguardano portano il codice del task a cui appartengono.

### Commit

```
<task-code>: <commit-message>
```

- **Una sola riga**, in inglese, all'imperativo: niente corpo, niente label.
- `<task-code>` è `TPR-XXX` oppure il codice di una milestone (`M1`).
- Esempi: `TPR-012: Add the AcoustID tagging step`, `M1: Close the first usable release`.
- Il titolo della PR ha lo stesso formato. Il dettaglio sta nella descrizione
  della PR, che segue il [template](.github/pull_request_template.md).
- **Niente righe di attribuzione** (`Co-Authored-By`, `Claude-Session` o simili),
  né nei commit né nelle descrizioni delle PR.
- I commit precedenti a `TPR-001` (i `Step N:` della prima costruzione) restano
  com'erano.

## Documentazione

- `README.md` descrive comandi e uso per chi usa il progetto: si aggiorna
  quando cambiano. L'esempio in `docs/esempio.md` si rifà se cambia l'output.
- Una proposta tiene aggiornati il suo stato e il suo registro
  ([proposals/README.md](proposals/README.md)).
- Chiudendo un task si aggiorna il registro di `docs/workflow.md` con ogni task chiuso.
