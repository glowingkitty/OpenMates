---
id: test_git_repo
app: code
stage: planning

name: test-git-repo
description: Clone a git repo and test if it works.


allowed-models: []
recommended-model: null
allowed-apps: []
allowed-skills: []
denied-skills: []

lang: en
verified_by_human: true
source_hash: null
---

# Test git repo

## Process

- if not provided already, ask user for the github/gitlab repo url
- if not provided already, ask user what they want to test / what their usecase is
- use skill to check in issues if there are any critital issues recently with using the repo reported
- if project is reported to be broken, ask user if they want to continue with testing it
- ask user where to clone and test the repo? setting up new machine? using github codespaces? local machine? etc.
- clone the repo to the specified location
- read project folder & file structure and readme.md to get an overview of the project
- figure out how to test the project and start testing it
