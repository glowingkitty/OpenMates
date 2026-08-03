---
status: draft
doc_type: reference
audience:
  - technical-users
last_verified: 2026-08-03
---

# Remote Access

`openmates remote-access` keeps a read-only connection open between your local
project files and OpenMates. The command runs in the foreground until you press
Ctrl+C, so closing it makes its sources unavailable in OpenMates.

## Commands

```bash
openmates remote-access [--path <folder>]... [--personal|--team <team>] [--json]
```

Interactive hosting confirms the current Personal or Team context before any
folder discovery. Non-interactive and JSON hosting must pass `--personal` or
`--team <team>`; otherwise it fails with `context_confirmation_required`.

Without `--path`, the CLI discovers accessible Git repositories below the
current folder, reconnects existing Project associations, and asks before
creating or binding missing Projects. Repeating `--path` replaces that default
discovery scope; only those folders are connected. The CLI warns and asks for
additional confirmation before exposing a broad root such as your home folder.

OpenMates can browse bounded directory listings, search safe text files, and
preview a selected text file while the source is connected. A preview remains
ephemeral unless you explicitly choose **Upload to OpenMates**.

Request those files from another authenticated CLI with deterministic commands:

```bash
openmates projects files list <project> --personal --json
openmates projects files search <project> billing --team acme --source <source-id> --json
openmates projects files read <project> src/billing.ts --team acme --source <source-id> --json
```

Live filesystem hosting and requests are CLI-only; stored encrypted Project data
is the separate surface intended for npm and pip SDK parity.

Live file requests always require an explicit Personal or Team flag in JSON or
non-interactive mode. Multiple online sources require `--source`; reads require
an exact source-relative path returned by list or search. These operations have
fixed path, depth, query, result-byte, concurrency, rate, and protocol-timeout
limits and never fall back to an AI model or broader source/context.

Use `openmates projects --help` for deterministic list/show/open/create/update,
archive/unarchive/delete, item, and source commands. Stored Project commands may
use the persisted context. Team viewers can read, members can mutate Projects
and remove links/sources they attached, and owners/admins can change settings,
remove any link/source, and permanently delete. API permission denials remain
stable machine-readable errors.
Project deletion sends the exact Project ID to the server for confirmation, and
source removal sends the exact source ID. Missing or mismatched IDs are rejected;
a generic boolean confirmation is not accepted.

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
openmates remote-access --personal

# Connect only these approved roots
openmates remote-access --team acme --path ./web --path ../api

# Emit structured lifecycle events while remaining in the foreground
openmates remote-access --personal --path ./my-repo --json
```
