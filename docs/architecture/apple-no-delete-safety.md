# Mac no-delete safety

TASK-752 applies to **every Mac file**, including generated or temporary files.
Approval never permits an agent to delete. When deletion is needed, the affected
task stops immediately and presents the exact manual command and reason to the
user. Only the user performs deletion. Their fresh response must confirm manual
execution or that deletion is unwanted; later deletions are independent stops.
Unknown operations are blocked conservatively, without inventing a deletion
command for the user to run.

## Implemented boundary

`scripts/apple_remote.py` checks CLI operations before reading configuration or
credentials. Every SSH/SCP constructor also checks the shared policy, covering
helpers that previously bypassed `run_remote`. The legacy destructive flag and
Python keyword cannot bypass it. The substring blacklist has been removed.

The fixed diagnostics `true`, `/usr/bin/true`, `/usr/bin/uname -s`, and
`/bin/df -h`, plus the exact reviewed typed helper below, are allowed. Shell expansion, interpreters, arbitrary argv, pipelines,
redirection and extra arguments are rejected. `status` uses a fixed diagnostic;
`finalize-proof` is local-only but still honors an existing task stop.

All other legacy helpers are blocked. This intentionally suspends native builds, tests,
patches, sync, upload/download, signing, installation, cache cleanup and most
readiness reports until their entire execution paths are proven deletion-free.
A command being called “read-only” is insufficient: tool startup, credential
expiry, package scripts and cleanup handlers can remove files.

A local SQLite ledger at `~/.local/state/openmates/apple-no-delete.sqlite3`
preserves the first stop, its task identity, reason, request and timestamp.
Commands may contain private paths; this ledger is local-only and mode 0600.
Missing identity, corrupt records and unreadable state fail closed. No timeout,
interrupt, continuation, role=user transcript, matching message, coordinator
relay, `--confirmed` flag or claimed keyboard source can release a stop. **There
is no automatic release API.** The existing transcript reader cannot distinguish
human input from coordinator `turn/start`; it is not reused for this purpose.
This limits automatic resumption even after a genuine human reply. Operators
must handle that case explicitly; agents must not edit the ledger to resume a
real deletion-stopped task. No new platform redesign is required to deploy this
conservative guard.

The canonical hook returns `continue=false` and denies all subsequent tools.
Codex/Claude checks run before and after tools. OpenCode checks all tools before
and after execution, calls `session.abort`, and suppresses queued media and
continuations. A stop is never wrapped in a “retry another command” instruction.
The Apple skill tells agents to end the task immediately, including on runtimes
that do not honor these hook events.

## Deletion-path inventory

| Path | Why blocked |
| --- | --- |
| Raw shell, argv, Python, Node, AppleScript | Arbitrary code can delete without a deletion substring |
| rsync/SCP/upload, cp/mv/install | Destination replacement, temporary-file cleanup or remote helper execution |
| Git sync/reset/clean/checkout/pull/gc | Checkout replacement, removed paths, locks, hooks and maintenance |
| Xcode, simulator and device build/test/install | Derived data replacement, uninstall, tooling cleanup and test code |
| Startup verification and proof recording | Explicit `rmtree`, archive removal, logs and simulator uninstall |
| Proof credential broker/materialization | Expiry processes and finally-block unlink of credentials and envelopes |
| Certificates/signing/TestFlight | Temporary certificate/probe removal, replacement and subprocess cleanup |
| Xcode cache cleaner | Explicit removal of cache directories and files |
| Package managers/browser teardown | Package removal/replacement, lifecycle scripts and temporary profile cleanup |
| Reviewed patch helper and doctor/report Python | Arbitrary Python transport is not admitted by the complete-command policy |

## Enforcement limits

This is deterministic wrapper and installed-hook enforcement, not a tamper-proof
sandbox. An agent with unrestricted shell access can access alternate SSH tools,
change environment routing hints, modify guard files or alter its own local
ledger. A subprocess exit cannot itself stop an external inference runtime.
Codex/Claude hook behavior depends on the host actually supporting and loading
those events; OpenCode abort behavior depends on the installed plugin version.
Deployment of source does not hot-reload a running OpenCode server.

The SSH account and its login environment are trusted. A shell startup script
could have side effects even for a fixed diagnostic. A stronger boundary would
require an operator-managed restricted account/forced command or read-only
filesystem policy, and host-owned all-tool dispatch/state controls. None was
installed or tested on the Mac for this task. A blacklist or a per-command
sandbox wrapper cannot enforce the rule against alternate unrestricted access.

## Verification and test-state isolation

Negative tests are local; non-destructive Mac policy queries and typed inspection
provide separate positive execution evidence. Fake runners prove rejection before remote dispatch;
subprocess tests reopen temporary SQLite state. Shared autouse fixtures isolate
every Apple transport test from real agent state. Tests cover indirect deletion,
legacy overrides, restart/alternate calls, corrupt state, forged confirmations,
hook stop output, OpenCode abort and repeated continuation attempts. Positive
human-provenance resume is not claimed because no reliable reader is available.

An early legacy patch transport test injected only its process runner and
accidentally latched the implementation chat. The user authorized continuing
local work without deletion through the coordinator's direct conversation. That
single identified test record was quarantined under a test identity, retaining
its original contents. This one-off local test-state repair is not a production
release mechanism; precise attribution is recorded in the coordinator status
file, outside committed source.


## Typed Remotion source/inspection path (TASK-752 follow-up)

`apple_remote.py remotion-op --request request.json --output response.json`
accepts JSON data for the fixed `_apple_remotion_remote.py` helper. It does not
admit caller shell/Python code. Request `repo` is the explicit Mac project
ending in `videos/remotion`.

- `action: inspect`: bounded installed renderer code/package audit and existing
  announcement asset names/sizes; no rendering or package execution.
- `action: source-read`, `file`: read a specific UTF-8 file in `src/` or
  `public/announcement-assets/`; response includes content and SHA-256.
- `action: source-put`, `file`, `content`, `expected_sha256`: null hash means
  exclusive creation. An existing file needs its exact hash; backup bytes are
  retained alongside it, and the existing inode is updated in place. No Git
  apply, rename, replacement, unlink, or cleanup is used. Symlinks and hardlinks
  are rejected. Parent directories may be exclusively created and retained.
- `action: sandbox-probe`: launch only a fixed read-only policy-query helper
  under macOS sandbox-exec. It asks sandbox_check about permissions; it never
  executes unlink. A passing query is not render-retention proof.

Unknown capabilities now return `UNSUPPORTED_REMOTE_OPERATION` without creating
an artificial human deletion request. Explicit removal commands and known
removal helpers still create terminal stops. Existing stops also block every
new typed operation and are never automatically cleared.

Rendering remains unexposed until the installed browser/encoder cleanup paths
and retained-artifact behavior are verified. The existing stock Remotion entry
points must not be used as an unguarded alternative.

Scoped inspection also returns nested original-media names/sizes and media manifests from the two approved input roots, bounded to 500 entries and four directory levels. `config-read` accepts only package.json, remotion.config.ts, or tsconfig.json. `media-probe` accepts a MOV/MP4/M4V/WAV/MP3 under either original-media root; installed ffprobe runs under a verified read-only sandbox with only the file protocol. No installation or decoder output is exposed. `sandbox-probe` additionally queries no-unlink policy in parent, child, and grandchild processes; SIGKILL-on-denial profile compilation is checked without triggering a denial. Query evidence does not prove signal delivery or native render compatibility.

## Explicit two-original relocation

User separately authorized relocating gemini_find_doctor_appointments.mov and openmates_is_better.mov from renders/mac-local/announcement-video/originals/ to input-media/announcement-video/originals/. `relocation-info` with `file` set to one exact filename returns source/destination and identity {device,inode,bytes,sha256}. `relocate-original` requires that exact identity object as `expected`. Directory descriptors reject symlinks, source must be regular/non-hardlinked, and devices must match. Mac renameatx_np uses RENAME_EXCL | RENAME_NOFOLLOW_ANY | RENAME_RESOLVE_BENEATH; unsupported flags or filesystem support fail without fallback. Existing destination is refused atomically. Post-rename identity/hash must match. No copy/unlink/overwrite or automatic rollback exists. This explicit identity-preserving relocation does not enable general moves, deletion, or alter render sandbox policy. See Apple XNU bsd/sys/stdio.h for flag definitions.
