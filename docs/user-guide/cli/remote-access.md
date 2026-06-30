---
status: draft
doc_type: reference
audience:
  - technical-users
last_verified: 2026-06-30
---

# Remote Access Commands

`openmates remote-access` attaches a local folder or repository as a Project source and searches it from the CLI. Source metadata is stored locally under `~/.openmates/remote-sources.json`; source contents are not uploaded by `start`.

## Commands

```bash
openmates remote-access start --path <folder> [--source-id <id>] [--project <id>] [--type <type>] [--local-only] [--json]
openmates remote-access status [--json]
openmates remote-access search --source <id> <query> [--limit <n>] [--json]
```

Source types for this local bridge are `local_folder` and `local_git_repository`. The default is `local_folder`.

## Safety

Search is read-only and runs `rg` inside the approved source root. Results exclude high-risk, binary, and out-of-root paths by default. If the local metadata store is corrupt, the CLI fails visibly instead of treating it as an empty source list.

## Examples

```bash
openmates remote-access start --path ./my-repo --source-id repo-1 --local-only
openmates remote-access status
openmates remote-access search --source repo-1 "Project settings"
```
