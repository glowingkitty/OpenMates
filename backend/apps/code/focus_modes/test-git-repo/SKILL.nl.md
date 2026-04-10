---
# Localized override for code/test_git_repo
id: test_git_repo
app: code
name: "Git-repository testen"
description: "Kloon een git-repository en test of het werkt."
lang: nl
verified_by_human: false
source_hash: 4f29005037badc1c1de458029057dc8d03eb29fdddd15c1ba78b867b6e54b567
---

# Git-repository testen

## Process

- als nog niet opgegeven, vraag de gebruiker om de github/gitlab repo URL
- als nog niet opgegeven, vraag de gebruiker wat hij wil testen / wat zijn gebruiksscenario is
- gebruik de vaardigheid om in issues te controleren of er recentelijk kritieke problemen zijn gemeld
- als het project als kapot wordt gerapporteerd, vraag de gebruiker of hij door wil gaan met testen
- vraag de gebruiker waar de repo gekloond en getest moet worden: nieuwe machine instellen? github codespaces? lokale machine? enz.
- kloon de repo naar de opgegeven locatie
- lees de map- en bestandsstructuur van het project en readme.md voor een overzicht
- uitzoeken hoe het project getest moet worden en beginnen met testen
