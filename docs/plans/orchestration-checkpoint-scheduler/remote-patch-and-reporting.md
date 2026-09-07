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

- 14 focused remote patch tests and 12 continuation hook tests passed.
- A real temporary Mac Git checkout passed dry-run, apply, and stale-hash rejection.
  The temporary checkout was removed; no marketing source or footage was changed.
- Runtime delivery and resumed worker evidence will be recorded after deployment.
