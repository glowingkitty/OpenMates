---
# Localized override for code/test_git_repo
id: test_git_repo
app: code
name: "Testar repositório git"
description: "Clone um repositório git e teste se funciona."
lang: pt
verified_by_human: false
source_hash: 4f29005037badc1c1de458029057dc8d03eb29fdddd15c1ba78b867b6e54b567
---

# Testar repositório git

## Process

- se não fornecido, pedir ao usuário a URL do repositório github/gitlab
- se não fornecido, perguntar ao usuário o que quer testar / qual é seu caso de uso
- usar habilidade para verificar issues se há problemas críticos reportados recentemente com o repositório
- se o projeto for reportado como quebrado, perguntar se o usuário quer continuar testando
- perguntar ao usuário onde clonar e testar o repositório? nova máquina? github codespaces? máquina local? etc.
- clonar o repositório no local especificado
- ler a estrutura de pastas e arquivos do projeto e readme.md para ter uma visão geral
- descobrir como testar o projeto e começar a testá-lo
