---
numero: "NNNN"
titolo: Titolo breve
stato: bozza            # bozza | in-discussione | accettata | realizzata | scartata | sostituita
creata: AAAA-MM-GG
aggiornata: AAAA-MM-GG
origine: dove è nata (es. brainstorming su claude.ai)
branch: proposals/NNNN-nome
branch-lavoro: feature/nome   # quando è accettata
task:                         # codice del task, es. TPR-007
issue:                        # numero della issue GitHub, se c'è
tocca: [cartelle o file del repo che cambierebbero]
---

# Titolo

> **Per chi legge.** Chi deve leggerla (persona o assistente) e cosa gli si
> chiede: decidere D1-Dn, rivederla, realizzarla.

## In breve

Tre righe: cosa si propone e perché.

## Contesto

Da dove nasce, cosa c'è già nel repo e cosa manca.

## Vincoli

Quelli del progetto sono in [CLAUDE.md](../../CLAUDE.md#vincoli-di-progetto).
Qui solo quelli in più per questa proposta.

## Proposta

La soluzione, con esempi veri (output di comandi reali) e riferimenti.

## Alternative considerate

| Opzione | Pro | Contro | Esito |
|---|---|---|---|

## Decisioni aperte

- [ ] **D1. Domanda.** Opzioni, cosa cambia con ciascuna, proposta di default.

Quando una decisione si chiude: `[x]`, la scelta, la data e dove è stata presa.

## Criteri di accettazione

- [ ] Cosa deve essere vero perché la realizzazione si consideri fatta, e come
      si controlla (test, comando, output da confrontare).

Si scrivono quando la proposta passa ad `accettata`: sono il contratto per
Claude Code e la checklist della PR.

## Verifiche fatte

Cosa è stato controllato e come. Anche cosa **non** è stato verificato.

## Piano di integrazione

Il prompt per Claude Code: branch, file da creare o modificare, test,
documentazione, aggiornamento di stato e registro.

## Registro

| Data | Dove | Cosa |
|---|---|---|
| GG/MM/AAAA | claude.ai | prima versione |
