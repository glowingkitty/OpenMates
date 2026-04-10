---
# Localized override for code/test_git_repo
id: test_git_repo
app: code
name: "Testa git-repo"
description: "Klona ett git-repo och testa om det fungerar."
lang: sv
verified_by_human: false
source_hash: 4f29005037badc1c1de458029057dc8d03eb29fdddd15c1ba78b867b6e54b567
---

# Testa git-repo

## Process

- om inte redan angett, be användaren om github/gitlab repo URL
- om inte redan angett, fråga användaren vad de vill testa / vad deras användningsfall är
- använd kompetensen för att kontrollera issues om det finns nyligen rapporterade kritiska problem med att använda repot
- om projektet rapporterats som trasigt, fråga användaren om de vill fortsätta med testningen
- fråga användaren var repot ska klonas och testas: ny maskin? github codespaces? lokal maskin? osv.
- klona repot till den angivna platsen
- läs projektets mapp- och filstruktur samt readme.md för att få en översikt av projektet
- ta reda på hur projektet ska testas och börja testa det
