---
# Localized override for code/test_git_repo
id: test_git_repo
app: code
name: "Przetestuj repozytorium git"
description: "Sklonuj repozytorium git i przetestuj, czy działa."
lang: pl
verified_by_human: false
source_hash: 4f29005037badc1c1de458029057dc8d03eb29fdddd15c1ba78b867b6e54b567
---

# Przetestuj repozytorium git

## Process

- jeśli nie podano, poprosić użytkownika o URL repozytorium github/gitlab
- jeśli nie podano, zapytać użytkownika, co chce przetestować / jaki jest jego przypadek użycia
- użyć umiejętności do sprawdzenia issues, czy były niedawno zgłoszone krytyczne problemy z użyciem repozytorium
- jeśli projekt jest zgłoszony jako uszkodzony, zapytać użytkownika, czy chce kontynuować testowanie
- zapytać użytkownika, gdzie sklonować i przetestować repo: nowa maszyna? github codespaces? maszyna lokalna? itp.
- sklonować repo do wskazanego miejsca
- przeczytać strukturę folderów i plików projektu oraz readme.md, aby uzyskać przegląd projektu
- dowiedzieć się, jak przetestować projekt, i rozpocząć testowanie
