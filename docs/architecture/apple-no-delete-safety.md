# Mac repository-scoped filesystem safety

TASK-752 policy `mac-repository-scope-v2-2026-09-07` implements the user's explicit
replacement of blanket no-delete: deletion is permitted within the actual
verified OpenMates and openmates-marketing checkouts. Checkout directories
themselves, parent/outside paths and original media remain protected.

## Authority and transition

The policy change was explicitly relayed from the user's coordinator conversation
`01a07d05-4f27-7111-91fb-9ef6fa875c9b`. `_apple_repository_policy.py` records this
source and the decision. The exact legacy browser stop
`e30e581ca54143adb3705cf158dd7444` remains in SQLite; a separate transition links
its original record to v2. The remote legacy marker likewise remains, with a
separate receipt. Neither receipt claims a manual deletion happened. New v2
stops, and unrelated historical stops, are never cleared by this transition.

## Verified boundaries

The typed helper verifies real directories without symlink ancestors and checks
`.git/config` against the known GitHub origins before constructing an OS profile.
The marketing project is inside the verified openmates-marketing checkout.
The sibling OpenMates clone target is explicit and must be absent, or already a
verified checkout. Clone uses the verified public HTTPS origin, no credential
helper or interactive prompt, and repository-local temporary storage. Existing
paths are never overwritten and failed clone directories are not cleaned up.

Seatbelt denies `file-write-unlink` outside the resolved repository subpaths and
at each repository root itself, with SIGKILL on violation. Protected original
media paths deny all filesystem writes. Native descendants inherit the policy.
Python realpath checks and Node filesystem guards reject escapes before typed
operations; strings beginning with a repository name are not proof of scope.
The scope probe queries allowed and denied paths in parent, child and grandchild
without attempting deletion. Separate harmless read probes established actual
SIGKILL delivery; SIGSTOP and nested sandbox initialization were not supported
in the observed Mac environment.

Only fixed typed helpers and four diagnostics are admitted. Arbitrary shell,
chained commands, interpreter snippets, SCP/rsync and legacy destructive helpers
remain rejected; allowing repository cleanup does not expose arbitrary commands.
The wrapper and all-tool hooks persist affected-task stops on outside-scope
violations. They do not turn a failed deletion into an instruction to retry it.

## Interfaces

`apple_remote.py remotion-op --request request.json --output response.json`
uses fixed reviewed helper code with caller values only as JSON data. Requests
include `repo`, the explicit marketing videos/remotion directory.

- `workspace-info`: verified roots/device/inode and absent clone target.
- `workspace-clone`: clone only the verified OpenMates public origin into the
  explicit absent sibling target; no overwrite or copy/delete fallback.
- `scope-probe`: inherited repository boundary policy query, no deletion syscall.
- `inspect`, `config-read`, `source-read`, `source-put`, `media-probe`: bounded
  metadata, fixed config/source paths and hashchecked source updates; original
  media remains read-only. ffprobe runs under a read-only sandbox.
- `relocation-info`, `relocate-original`: the two previously authorized original
  relocations retain exact device/inode/size/hash using atomic no-overwrite
  renameatx_np. No general overwrite or original deletion is admitted.
- `render-check`: bounded one-frame/encode tooling check with ordinary run paths
  under renders/runs, repository-local temporary/profile paths and scoped policy.
- `render-report`: bounded logs/outcomes for an exact run UUID.

Remotion cleanup inside the authorized roots is allowed. Old no-delete-retained
evidence is historical and is not erased as part of this change. Marketing owns
creative code, folder reorganization, source selections and final video work.

## Stop and host limits

An outside/protected-path stop ends the affected task. Only an actual fresh human
response can resolve it; transcript roles, coordinator relays and flags are not
proof of human input. The inspected host has no automatic trusted-human resume
adapter, and no such bypass is added here. A native signal does not identify an
exact deletion path; report that uncertainty rather than inventing a command.

This is scoped wrapper/OS-policy enforcement for reviewed operations, not a
claim of tamper-proof unrestricted host access. SSH login startup and installed
binaries are trusted. Alternate tools, local ledger tampering and host identity
routing require host enforcement. Shared hook architecture remains unchanged;
OpenCode release activation remains separate from source deployment.

## Verification

Focused Linux fixtures isolate all real stop state. They cover resolved paths,
symlink escape, prefix collisions, root/parent protection, original protection,
Git origin checks, retained transition history and subsequent terminal stops.
Real Mac scope queries and a bounded render check provide separate execution
proof. No outside deletion fixture or attempted outside deletion is used.
