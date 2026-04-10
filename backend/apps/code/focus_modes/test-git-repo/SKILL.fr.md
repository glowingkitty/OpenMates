---
# Localized override for code/test_git_repo
id: test_git_repo
app: code
name: "Tester le dépôt git"
description: "Clonez un dépôt git et testez s'il fonctionne."
lang: fr
verified_by_human: false
source_hash: 4f29005037badc1c1de458029057dc8d03eb29fdddd15c1ba78b867b6e54b567
---

# Tester le dépôt git

## Process

- si non fourni, demander à l'utilisateur l'URL du dépôt github/gitlab
- si non fourni, demander à l'utilisateur ce qu'il veut tester / quel est son cas d'utilisation
- utiliser la compétence pour vérifier dans les issues s'il y a des problèmes critiques récents signalés
- si le projet est signalé comme défaillant, demander si l'utilisateur veut continuer les tests
- demander à l'utilisateur où cloner et tester le dépôt : nouvelle machine ? github codespaces ? machine locale ? etc.
- cloner le dépôt à l'emplacement spécifié
- lire la structure des dossiers et fichiers du projet et le readme.md pour avoir un aperçu
- trouver comment tester le projet et commencer les tests
