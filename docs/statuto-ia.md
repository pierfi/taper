# Lo statuto in pratica: strumenti IA, review e branch

Guida illustrata allo [statuto](../CLAUDE.md): chi fa cosa nella fase creativa,
come funziona la review di un secondo assistente, e quale **strategia di
branch** segue una proposta dall'idea al merge. Le regole di dettaglio restano
in [CLAUDE.md](../CLAUDE.md), [workflow.md](workflow.md) e
[proposals/README.md](../proposals/README.md); qui il quadro d'insieme.

I diagrammi sono Mermaid: GitHub li disegna da solo.

## 1. Le tre fasi e gli strumenti

```mermaid
flowchart LR
    subgraph F1["1. Fase creativa"]
        A["claude.ai<br/>brainstorming e scrittura<br/>della proposta"]
    end
    subgraph F2["2. Review"]
        B["Altri assistenti<br/>seconda opinione"]
        R["revisioni/<br/>AAAA-MM-GG-strumento.md"]
    end
    subgraph F3["3. Sviluppo e controllo"]
        C["Claude Code<br/>prototipi, codice, test"]
        D["Pull request<br/>gh pr create + CI"]
        E["Autore<br/>review e merge"]
    end
    A -- "README della proposta" --> B
    B -- "risposta copiata, mai applicata da sola" --> R
    R -- "l'autore decide cosa tenere" --> A
    A -- "proposta accettata" --> C
    C --> D --> E

    classDef idea fill:#EEEDFE,stroke:#534AB7,color:#3C3489
    classDef rev fill:#FAEEDA,stroke:#854F0B,color:#633806
    classDef dev fill:#E1F5EE,stroke:#0F6E56,color:#085041
    classDef gh fill:#F1EFE8,stroke:#5F5E5A,color:#444441
    class A idea
    class B,R rev
    class C dev
    class D,E gh
```

| Strumento | Fase | Legge | Scrive | Non fa mai |
|---|---|---|---|---|
| **claude.ai** (o altra chat) | creativa | `main`, la proposta | il testo della proposta | codice nel repo |
| **Altri assistenti** | review | README della proposta + vincoli di `CLAUDE.md` | solo la risposta, che finisce in `revisioni/` | modificare la proposta |
| **Claude Code** | sviluppo | tutto il repo | prototipi, codice, documenti, stato e registro | commit senza ok, merge, push su `main` |
| **L'autore** | tutte | tutto | le decisioni | - |

Un assistente **non decide**: propone. Ogni decisione passa dall'autore e viene
scritta nel registro della proposta (`D1`, `D2`, ... con data e motivo).

## 2. La fase creativa e la review, passo per passo

```mermaid
sequenceDiagram
    autonumber
    actor Autore
    participant CAI as claude.ai
    participant CC as Claude Code
    participant EXT as Altro assistente
    participant GH as GitHub

    Autore->>CAI: idea, gusti, vincoli
    CAI->>Autore: proposta in Markdown<br/>(modello _modello/README.md)
    Autore->>CC: "salva la proposta 0001"
    CC->>GH: branch proposals/0001-nome<br/>(tocca solo proposals/)
    Autore->>EXT: README della proposta + vincoli + prompt di review
    EXT->>Autore: parere (regge? D1..Dn? problemi? cosa togliere?)
    Autore->>CC: "metti il parere in revisioni/"
    CC->>GH: commit "TPR-007: Add the review of proposal 0001"
    Autore->>CAI: decisioni prese
    CAI->>Autore: proposta aggiornata, D1..Dn chiuse
    Autore->>CC: "accettata: realizzala"
    CC->>GH: feature/nome, poi PR con gh pr create
    GH->>Autore: PR + CI verde
    Autore->>GH: review e merge
```

Regole del giro creativo:

- **Il repo è il canale.** claude.ai e Claude Code non si parlano: si passano
  tutto attraverso i file (e le persone).
- **Il parere esterno non cambia la proposta da solo.** Si salva com'è in
  `revisioni/`, poi l'autore scrive in fondo "Cosa ne teniamo" e le decisioni
  vere entrano nel README della proposta e nel suo registro.
- **La proposta è autosufficiente**: chi la legge senza conoscere il progetto
  deve poter rispondere. I vincoli stanno in un posto solo (`CLAUDE.md`).
- I prompt pronti per claude.ai, per Claude Code e per un assistente esterno
  sono in [proposals/README.md](../proposals/README.md#chi-fa-cosa).

## 3. Gli stati di una proposta

```mermaid
stateDiagram-v2
    [*] --> bozza
    bozza --> in_discussione: se ne parla
    in_discussione --> accettata: si decide di farla
    accettata --> realizzata: PR mergiata su main
    in_discussione --> scartata: motivo nel registro
    in_discussione --> sostituita: rimanda alla nuova proposta
    note right of bozza
        branch proposals/NNNN-nome
    end note
    note right of accettata
        branch feature/nome
    end note
    note right of realizzata
        entra in main insieme al codice
    end note
```

| Stato | Branch | Dove vive la proposta |
|---|---|---|
| `bozza`, `in-discussione` | `proposals/NNNN-nome` | solo su quel branch |
| `accettata` | `feature/<nome>` (staccato dal branch della proposta) | su `feature/<nome>` |
| `realizzata` | `main` | in `main`, come storia, col link alla PR |
| `scartata`, `sostituita` | `proposals/NNNN-nome` | resta sul suo branch, col motivo |

## 4. La strategia di branch

Una proposta nasce da `main`, vive su un branch dedicato e **non entra in
`main` finché non è realizzata**. Quando è accettata si stacca la feature dal
branch della proposta e lì si fa tutto; una sola PR riporta in `main` proposta
e codice insieme.

```mermaid
gitGraph
    commit id: "main aggiornato"
    branch "proposals/0001-nome"
    checkout "proposals/0001-nome"
    commit id: "TPR-007: Add the draft of proposal 0001"
    commit id: "TPR-008: Add the external review"
    commit id: "TPR-009: Close decisions D1-D3"
    branch "feature/nome"
    checkout "feature/nome"
    commit id: "TPR-010: Mark proposal 0001 accepted"
    commit id: "TPR-010: Add the prototype"
    commit id: "TPR-010: Implement it with tests"
    checkout main
    commit id: "altro lavoro (PR di altri)"
    checkout "feature/nome"
    merge main id: "git merge main"
    commit id: "TPR-010: Mark proposal 0001 done"
    checkout main
    merge "feature/nome" tag: "PR #N"
```

Le regole, in ordine:

1. **`proposals/NNNN-nome`** nasce da `main` aggiornato, così porta le regole e
   il modello più recenti. Tocca **solo** `proposals/`. Qui scrivono la
   proposta (claude.ai, via Claude Code o l'autore) e vanno le revisioni.
2. **`feature/<nome>`** si stacca dal branch della proposta quando questa
   passa ad `accettata`. Qui si chiudono le decisioni aperte e si fanno
   prototipi, test, codice, documenti. Il branch della proposta resta com'era.
3. **Si aggiorna con `git merge main`**, mai con rebase o force push dopo la
   pubblicazione: la storia del branch non si riscrive.
4. **Una sola PR verso `main`**, aperta con `gh pr create` e il
   [template](../.github/pull_request_template.md), quando la proposta è
   completa: decisioni chiuse, criteri di accettazione soddisfatti, codice e
   documenti pronti. Entrano insieme la cartella della proposta (stato
   `realizzata`, registro, riga dell'indice) e il codice.
5. **Review e merge sono dell'autore**: merge commit, mai squash; mai commit
   diretti su `main`.

### Altri branch

| Branch | Quando | Da | Verso |
|---|---|---|---|
| `tpr-XXX-<nome>` | task senza proposta: flusso di lavoro, manutenzione, bug o ritocco piccolo (basta una issue) | `main` | PR su `main` |

### Cosa vede ogni strumento

```mermaid
flowchart TB
    M["main<br/>regole, codice, proposte realizzate"]
    P["proposals/NNNN-nome<br/>proposta in discussione + revisioni/"]
    F["feature/nome<br/>proposta accettata + prototipi + codice"]
    M -- "nasce da" --> P
    P -- "si stacca quando accettata" --> F
    F -- "git merge main (aggiornamento)" --> F
    F == "una sola PR (gh pr create)" ==> M

    classDef main fill:#F1EFE8,stroke:#5F5E5A,color:#444441
    classDef prop fill:#EEEDFE,stroke:#534AB7,color:#3C3489
    classDef feat fill:#E1F5EE,stroke:#0F6E56,color:#085041
    class M main
    class P prop
    class F feat
```

| Branch | claude.ai | Altri assistenti | Claude Code |
|---|---|---|---|
| `main` | legge le regole | legge i vincoli | legge e (via PR) aggiorna |
| `proposals/NNNN-nome` | scrive la proposta | legge il README | salva proposta e revisioni |
| `feature/nome` | rilegge la proposta | - | prototipi, codice, test, PR |

## 5. Checklist rapida

**Nuova proposta**

- [ ] `git switch main && git pull && git switch -c proposals/NNNN-nome`
- [ ] copia `proposals/_modello/` in `proposals/NNNN-nome/` e scrivi il README
- [ ] commit `TPR-XXX: <commit-message>` (una riga, in inglese), push del branch (nessuna PR finché si discute)
- [ ] review esterna: risposta in `revisioni/`, "Cosa ne teniamo" compilato
- [ ] decisioni chiuse nel README e nel registro

**Realizzazione**

- [ ] `git switch -c feature/<nome>` dal branch della proposta, stato `accettata`
- [ ] test verdi a ogni commit, `git merge main` se serve
- [ ] stato `realizzata`, registro e riga dell'indice aggiornati
- [ ] `gh pr create` con il template; l'autore rivede e mergia
