---
# Localized override for code/test_git_repo
id: test_git_repo
app: code
name: "Testa repository git"
description: "Clona un repository git e testa se funziona."
lang: it
verified_by_human: false
source_hash: 4f29005037badc1c1de458029057dc8d03eb29fdddd15c1ba78b867b6e54b567
---

# Testa repository git

## Process

- se non già fornito, chiedere all'utente l'URL del repository github/gitlab
- se non già fornito, chiedere all'utente cosa vuole testare / qual è il suo caso d'uso
- usare la competenza per verificare nelle issues se ci sono problemi critici recentemente segnalati con il repository
- se il progetto è segnalato come rotto, chiedere all'utente se vuole continuare a testarlo
- chiedere all'utente dove clonare e testare il repository: nuova macchina? github codespaces? macchina locale? ecc.
- clonare il repository nella posizione specificata
- leggere la struttura di cartelle e file del progetto e readme.md per avere una panoramica
- capire come testare il progetto e iniziare il testing
