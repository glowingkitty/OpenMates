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
openmates remote-access [--path <folder>]... [--personal|--team <team>] [--enable-commands] [--json]
```

Interactive hosting confirms the current Personal or Team context before any
folder discovery. Non-interactive and JSON hosting must pass `--personal` or
`--team <team>`; otherwise it fails with `context_confirmation_required`.

Without `--path`, the CLI discovers accessible Git repositories below the
current folder, reconnects existing Project associations, and asks before
creating or binding missing Projects. Repeating `--path` replaces that default
discovery scope; only those folders are connected. The CLI warns and asks for
additional confirmation before exposing a broad root such as your home folder.

Pass `--enable-commands` when you want this source to run approved terminal
commands. On supported Linux systems, the CLI checks the required confinement
and performs its one-time setup from files shipped in the installed OpenMates
package. The operating system may ask for administrator authorization in that
interactive terminal. OpenMates never asks you to enter the password into chat.
Without this flag, missing command protection leaves browsing and file editing
available and terminal commands disabled.

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

Deterministic list, search, and read requests cannot mutate or execute files.
Separate Project write and remote-command flows require their own current focus,
policy, approval, confinement, and freshness checks. Every operation stays inside
the approved real path and rejects symlink escapes, unsupported binary files, and
oversized results. Source associations are stored with owner-only permissions
under `~/.openmates/remote-sources.json`.

Git-ignore rules reduce discovery noise; they are not a privacy boundary.
Untracked ignored files do not appear in list or search and cannot be opened by
an exact read until the client shows that exact file to you for confirmation.
Approval creates a short-lived signed grant for that Project, source, chat,
request, and exact relative file. It does not approve a directory or wildcard.
Matching applies regardless of whether Git already tracks the file and behaves
the same in Git, hosted, and plain-folder sources. An approved confined command
may still need ignored dependencies such as `node_modules` or ignored build
outputs such as `dist/`.

Private paths are a separate deny boundary. OpenMates has built-in private rules
for credential and control files, including `.env`, `.git/config`, and
`.openmates/permissions.yml`. You can define normalized source-relative files or
directories in `.openmates/permissions.yml` and explicitly activate them as
trusted policy outside agent-controlled Project operations:

```yaml
file_access:
  private_paths:
    - secrets/
    - private/client-notes/
    - certificates/customer.pem
```

Private paths are omitted from dedicated Project list and search results and are
denied for reads, imports, edits, and recovery. A confined terminal may show that
a private filename exists, but it cannot open, read, execute, or change its
content. On supported Linux remote executors, an AppArmor-first adapter enforces
that boundary on every access to the original live folder. It covers newly created
matching private paths, symlinks that resolve into denied paths, and known
pre-existing hard-link aliases. The confined command cannot create or rename a
private file into an allowed alias. It does not copy the Project, create another
worktree, stage changes, or reconcile a writeback tree. If the boundary cannot be
enforced, the command reports unsupported confinement instead of running directly.

This protection is path based; it does not label or taint the bytes forever. If an
external unconfined owner deliberately copies or hard-links private data to a new
allowed pathname, that action republishes the data outside this boundary, just as
copying a secret into ordinary source would. Other processes that own the source
should use the same private-path policy.

Private rules are checked locally before file bytes leave the source. Ignored-file
confirmation, command approval, repository instructions, or agent changes to the
permissions file cannot weaken built-in or activated private rules. Deleting or
changing the Project copy does not silently relax an already activated rule.
These checks do not change remote or hosted encryption, and the backend receives
no new plaintext path or file-content authority.

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
