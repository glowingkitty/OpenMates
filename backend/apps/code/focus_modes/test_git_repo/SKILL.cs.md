---
# Localized override for code/test_git_repo
id: test_git_repo
app: code
name: "Otestovat git úložiště"
description: "Naklonujte git úložiště a otestujte, zda funguje."
lang: cs
verified_by_human: false
source_hash: 4f29005037badc1c1de458029057dc8d03eb29fdddd15c1ba78b867b6e54b567
---

# Otestovat git úložiště

## Process

- pokud ještě není poskytnuto, požádat uživatele o URL github/gitlab repozitáře
- pokud ještě není poskytnuto, zeptat se uživatele, co chce testovat / jaký je jeho případ použití
- použít dovednost ke kontrole issues, zda byly nedávno nahlášeny kritické problémy s použitím repozitáře
- pokud je projekt hlášen jako nefunkční, zeptat se uživatele, zda chce pokračovat v testování
- zeptat se uživatele, kde klonovat a testovat repo: nastavit nový stroj? github codespaces? lokální stroj? atd.
- klonovat repo na určené místo
- přečíst strukturu složek a souborů projektu a readme.md pro přehled o projektu
- zjistit, jak projekt testovat, a začít s testováním
