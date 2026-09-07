# Remote patch and coordinator reporting repair

User approved this bounded follow-up after the marketing worker was blocked by
the source-write hook and scheduled checkpoint text appeared as a user message.

Acceptance checks:
- Keep raw shell source writes blocked; provide a reviewed remote patch command.
- Default to dry run; require exact file hashes and an explicit apply flag.
- Reject unlisted paths, symlinks, media, deletion, binary and mode changes.
- Preserve unrelated files and the Git index; never reset or clean user work.
- Mark scheduled prompts synthetic using the existing OpenCode message contract.
- Inject current authored reporting rules on each coordinator turn and compaction.
- Deploy the runtime, verify actual delivery/reporting, and resume the existing worker.

## Reviewed remote patch workflow

Prepare a local unified diff using the normal reviewable file-edit tool. Read the
remote source first, then capture its hashes:

```sh
python3 scripts/apple_remote.py patch-snapshot --repo /absolute/mac/checkout --file src/Root.tsx > /tmp/remote-hashes.json
python3 scripts/apple_remote.py apply-patch --repo /absolute/mac/checkout --patch /tmp/reviewed.patch --expected /tmp/remote-hashes.json
python3 scripts/apple_remote.py apply-patch --repo /absolute/mac/checkout --patch /tmp/reviewed.patch --expected /tmp/remote-hashes.json --apply
```

Repeat `--file` for each affected text file. A new file has a null hash. If a file
changes after the snapshot, reread it and prepare a new patch. JSON request data
travels on SSH stdin to a fixed helper; it is never interpolated into shell code.
The cooperative patch lock serializes this helper; unrelated external editors do
not participate in that lock, so this is stale-snapshot protection, not exclusive
ownership of the remote checkout.

## Verification

- 73 focused Python tests and 43 continuation/task-bridge/source-guard hook tests passed.
- The broader Apple suite reported 12 failures; all 12 reproduced against unchanged HEAD.
  They concern existing recording/simulator behavior outside this repair.
- A real temporary Mac Git checkout passed dry-run, apply, and stale-hash rejection.
  The temporary checkout was removed; no marketing source or footage was changed.
- Implementation deployed as `dc2c381dd547abed1c532ad343d51182ec1b9e1e`.
- Immutable runtime `ae6a323ef874-dc2c381dd547` selected with the existing verified binary.
  Managed restart manifest `opencode-restart-20260907T151749Z.json` verified both
  captured worker chats resumed. The active runtime checkout is clean at that commit.
- Existing marketing worker accepted the recovery handoff and began inspecting the
  supported helper at 15:18 UTC. This verifies resumption, not product completion.
- Live Tasks metadata now includes the every-reply table rule after coordinated
  API/worker refresh; all affected services reported healthy.
- Live scheduled prompts `msg_07c74730f0013GI1UWOvgIl8sw, msg_07c75d26d001rnNRoCl7qH5KmW` carry `synthetic: true`
  and the internal monitor metadata marker. The running binary's user-message
  renderer excludes synthetic text from ordinary user message display.
- Coordinator reply `msg_07c7514c10015vk9nDmBbqYtb6` contains all five chat rows, explicit stale/not-checked
  labels, and a bold user action. The following checkpoint for unaffected workers
  was delivered while the marketing connection problem remained unresolved.
- Coordinator presence reports the deployed hook SHA-256
  `f003a684c2cda23fdfbb7f361071573e589b523870e56dcf9d06cfe6e3590abf`.
- Marketing recognized the live patch command but encountered a later SSH timeout.
  Independent status checks from both the tested worktree and active runtime also
  returned `ssh_reachable=False`; product work awaits Mac connectivity. No agent
  modified marketing source or footage during this repair.

## Process observation

An activation preflight incorrectly looked for a script inside the hook-only
package instead of its pinned control-plane checkout. A shell sequence continued
past that failed assertion and performed one unnecessary managed restart; both
captured chats were restored. The corrected activation uses fail-fast execution
and validates the helper at the manifest commit before changing the release link.
Use that fail-fast activation check as the deterministic guard for future rollouts.

