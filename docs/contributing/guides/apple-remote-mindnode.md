# MindNode through Apple Remote

Status: capability discovery implemented; native document read/update and Mac
round-trip verification are pending. Tracking: TASK-4239. Do not use personal
maps as fixtures or interpret an exported outline as a native round trip.

## Current capability contract

`scripts/_apple_remote_mindnode.py` is a dependency-free remote helper intended
for the guarded `scripts/apple_remote.py` transport. It does not provide SSH or
an alternative Mac execution path. The shared transport integration must be
agreed with the current Apple Remote guard owner before remote execution.

The only accepted request is:

```json
{"action":"capabilities"}
```

The result has `ok`, `apps`, `write_enabled: false`, and
`native_round_trip_verified: false`. Each app reports its bundle path, bundle
identifier, version/build, document type declarations and scripting dictionary.
`scripting.status` is `dictionary_present` or `not_declared`; a present public
dictionary includes its SHA-256 and XML. Presence does not prove node editing,
Automation permission, application availability or persistence.

The probe checks only `MindNode*.app` in the system and user Applications
directories. It does not enumerate documents, inspect CloudKit, request broad
filesystem permission, run Shortcuts, launch MindNode or modify files. Metadata
reads are size-bounded and reject symlinks and dictionary path traversal.

Errors return `ok: false`, `error.code`, and exit status 2. Codes include
`mindnode_not_found`, `unsafe_bundle_path`, `metadata_too_large`,
`unsupported_dictionary`, `capability_read_failed`, `unsupported_request`,
`request_too_large` and `invalid_request`. Error text omits private file contents.

Run the Linux-safe tooling tests:

```bash
python3 -I scripts/tests/test_apple_remote_mindnode.py
```

## Native-format and automation limits

MindNode's current [Shortcuts guide](https://www.mindnode.com/support/guides/apple-shortcuts)
documents document creation/export/search and node creation/search/editing.
These are supported app actions, but their availability on the installed Mac
must be discovered. Do not infer an AppleScript dictionary from Shortcuts support.

The current app uses local application storage and
[CloudKit synchronization](https://www.mindnode.com/support/guides/how-does-mindnode-store-documents-in-the-cloud).
Creating a document through its app-library action is therefore unsuitable for
this test unless repository-only storage can be demonstrated first. Do not
create test documents in the user's normal or iCloud collections.

The vendor's [import/export guide](https://www.mindnode.com/support/guides/import-and-export)
distinguishes MindNode Next and Classic formats and warns that some Classic
features are unsupported. Text, Markdown, OPML and FreeMind interchange do not
prove preservation of native IDs, geometry, rich text, attachments or metadata.
No undocumented native decoder or writer is enabled by this helper.

## Required native read/update proof

Before implementing mutation, inspect the installed app's supported dictionary
or documented mechanism. Bind every request to a verified repository root,
canonical document path, document identity and expected revision. Reads must
return explicit node identities and parent relationships; updates must target
one bound node or parent, never the current/first document or a title match.

The first test must create a new, unmistakably named map in an ignored
repository test-artifacts directory. Refuse existing destinations. Keep inputs,
backups, temporary files, exports and receipts under that verified directory.
Reject symlink escapes, identity/revision mismatches and unsupported native
formats before modifying anything. Preserve original native data in a retained
backup; use an app-supported save or an atomic native replacement only after
its structure/metadata preservation has been verified.

Required sequence: create new map → read nodes → add a bounded test node →
rename/update that node → reopen the native map in the actual application →
read and verify persistence and unchanged unrelated node IDs/metadata. Record
metadata-only before/after checks for existing maps without printing titles or
contents. An app permission prompt or library-only persistence must produce an
explicit unsupported/needs-user-action result, never a fabricated success.

The deletion policy and any terminal policy stop remain owned by the shared
Apple Remote guard. MindNode helpers must not bypass or clear that policy.
