---
# Localized override for code/test_git_repo
id: test_git_repo
app: code
name: "Git-Repository testen"
description: "Klone ein Git-Repository und teste, ob es funktioniert."
lang: de
verified_by_human: true
source_hash: 4f29005037badc1c1de458029057dc8d03eb29fdddd15c1ba78b867b6e54b567
---

# Git-Repository testen

## Process

- falls noch nicht angegeben, den Nutzer nach der github/gitlab-Repo-URL fragen
- falls noch nicht angegeben, den Nutzer fragen, was er testen möchte / was sein Anwendungsfall ist
- Fähigkeit verwenden, um in Issues zu prüfen, ob kürzlich kritische Probleme mit dem Repo gemeldet wurden
- wenn das Projekt als defekt gemeldet wurde, den Nutzer fragen, ob er mit dem Testen fortfahren möchte
- den Nutzer fragen, wo das Repo geklont und getestet werden soll? Neue Maschine einrichten? GitHub Codespaces verwenden? Lokale Maschine? usw.
- das Repo an den angegebenen Ort klonen
- Ordner- und Dateistruktur des Projekts sowie readme.md lesen, um einen Überblick über das Projekt zu erhalten
- herausfinden, wie das Projekt getestet werden soll, und mit dem Testen beginnen
