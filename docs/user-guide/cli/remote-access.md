---
status: draft
doc_type: reference
audience:
  - technical-users
last_verified: 2026-08-02
---

# Remote Access

`openmates remote-access` keeps a read-only connection open between your local
project files and OpenMates. The command runs in the foreground until you press
Ctrl+C, so closing it makes its sources unavailable in OpenMates.

## Commands

```bash
openmates remote-access [--path <folder>]... [--json]
```

Without `--path`, the CLI discovers accessible Git repositories below the
current folder, reconnects existing Project associations, and asks before
creating or binding missing Projects. Repeating `--path` replaces that default
discovery scope; only those folders are connected. The CLI warns and asks for
additional confirmation before exposing a broad root such as your home folder.

OpenMates can browse bounded directory listings, search safe text files, and
preview a selected text file while the source is connected. A preview remains
ephemeral unless you explicitly choose **Upload to OpenMates**.

The CLI reconnects automatically after temporary network interruptions with a
bounded backoff. OpenMates marks the source offline after missed heartbeats and
blocks new reads until the foreground command reconnects.

## Safety

Remote access cannot create, edit, delete, rename, or execute files. Every
operation stays inside the approved real path and excludes symlink escapes,
Git-ignored files, protected paths such as `.env`, binary files, and oversized
results. Source associations are stored with owner-only permissions under
`~/.openmates/remote-sources.json`.

Paths, queries, snippets, and file previews are encrypted end to end between
the OpenMates client and CLI. The backend routes opaque ciphertext and live
status only; encryption keys and filesystem plaintext are not sent to it.

## Examples

```bash
# Discover repositories below the current folder
openmates remote-access

# Connect only these approved roots
openmates remote-access --path ./web --path ../api

# Emit structured lifecycle events while remaining in the foreground
openmates remote-access --path ./my-repo --json
```
