# Contract: application files as Project files (P11)

Status: draft, owned by plan `cloud-project-development` package P11.

## Decisions (user, 2026-11-10)

1. One embed per file. The code embeds an application creates in a chat ARE the
   Project files; assistant and user edits create revisions of that one embed.
2. One write path. A Project-linked file is changed only through the Project
   file operations (`project_create_file`, `project_update_file`,
   `project_rename_file`, `project_delete_file`), which commit through the hosted
   revision transaction. A raw chat diff block that targets a Project-linked
   embed never writes; it is reported as not applied and the model is told to
   use the Project file tool. The diff card in chat is rendered from the
   committed revision (before/after), never from an uncommitted block.
3. Every embed inside a Project is readable by all Project members. The
   application embed and test-result embeds created in a Project chat get a
   Project-key wrapper and their own Project link.
4. Files can be renamed and deleted by the assistant and by the user.

## Adopt an existing chat embed into a Project

`POST /v1/projects/{project_id}/items/adopt-embed` — first-party session only
(client-encrypted data; not available to API keys without a wrapped master key
path, not a public integration endpoint).

Request body:

| field | meaning |
| --- | --- |
| `operation_id` | idempotency key; a replay returns the first result |
| `chat_id` | chat that owns the embed today |
| `embed_id` | existing embed to adopt |
| `project_item_id` | client-derived id; for files `hosted_file_identity(Item, "<folder>/<path>")` |
| `kind` | `file`, `application` or `test_result` |
| `target_id_encrypted` | embed id encrypted with the Project key |
| `encrypted_display_name` | display name encrypted with the Project key |
| `encrypted_metadata` | Project-key ciphertext, see below |
| `project_key_wrapper` | the embed key wrapped with the Project key |
| `team_id` | present for Team Projects |

Metadata plaintext by kind:

- `file`: `{path, source: "hosted_project_file", application_embed_id, application_path}`
- `application`: `{path: "<folder>", source: "project_application", entry_path}`
- `test_result`: `{source: "project_test_result", run_id}`

Server behaviour (one atomic operation `adoptProjectEmbed` in the
embed-version-transaction extension):

- verifies the caller may write the Project and owns the chat embed;
- stores the Project-key wrapper beside the existing chat-key wrapper (the
  embed stays readable in the chat);
- creates the `project_items` link; refuses a second link with a different
  `project_item_id` for the same embed (`embed_already_linked`) and a path
  collision (`path_conflict`);
- from then on the embed is fenced: legacy/server writers get
  `project_context_required`.

Server-owned fields: for `application` and `test_result` links the server may
still update a narrow allow-list of non-content fields (thumbnail/preview frame
reference, run status) without a client revision. File content is never in
that list.

Errors use stable codes: `project_not_found`, `forbidden`, `embed_not_found`,
`embed_already_linked`, `path_conflict`, `invalid_request`.

## Rename and delete

- `POST /v1/projects/{project_id}/items/{project_item_id}/rename` with
  `{operation_id, new_project_item_id, encrypted_display_name,
  encrypted_metadata}`. The link changes path; the embed id and its revision
  history are kept. `path_conflict` when the target path exists.
- `DELETE /v1/projects/{project_id}/items/{project_item_id}` with
  `{operation_id}` removes the link from the folder. The embed and its
  revisions stay so a commit restore can relink the file.

Both are recorded so Project commits and the timeline can show them.

Wire details (agreed between the backend and the Rust core):

- Rename and delete take `team_id` as a query parameter (`?team_id=`) for
  Team Projects; adopt takes it in the body.
- Refusals are `{"detail": "<code>"}` with the stable code as a plain string.
  The client keeps only codes from its closed set (the list above plus the
  extra codes under "Implementation notes") and never forwards other text.
- Item ids are UUIDs shaped by the client as UUIDv5 (keyed HMAC of the
  Project key). `file` links (adopt and rename targets) must be UUIDv5:
  `hosted_file_identity(Item, path)`. `application` and `test_result` links use
  the keyed id `["openmates-project-embed-link-v1", kind, embed_id]`.
- Hosted file listings never show `application` or `test_result` links as
  files (by `link_kind`, or by metadata `source` for listings without it).

## Client (Rust core)

- When a Project focus is active and an application finishes in the chat, the
  core adopts each finished child code embed at `<folder>/<path>` (default
  folder `web-app`, taken from the application title when several exist), then
  the application embed itself with kind `application`.
- Language is derived from the path, not fixed to `text`.
- The preview is built from the folder's current file heads.
- CLI: `projects hosted rename|delete`, `projects hosted adopt` (explicit
  repair), and `--text` on `projects hosted create|update` accepts values that
  start with a dash.

## Backend diff guard

`stream_consumer._apply_diff_block_to_existing_embed` checks
`requires_atomic_project_embed_write` before applying. For a linked embed it
emits a not-applied result with code `project_file_tool_required` instead of
writing.

## Job payloads

The assistant tools `project_rename_file` and `project_delete_file` issue
ordinary client-executed Project file jobs (`project_file_operation_*`
WebSocket frames, protocol version 1). The server only issues the job; the
client resolves the path, derives the new item id, encrypts and calls the
routes above. Both operations are mutations: a `completed` result needs a
`proposal_commitment` and passes the same write-policy and approval checks as
`create_file`/`update_file`; with a `source_id` the source needs
`write_request`.

| tool | job `operation` | `arguments` (exact keys) |
| --- | --- | --- |
| `project_rename_file` | `rename_file` | `{path, new_path}` — both Project-relative, no absolute path or `..`, `new_path` differs from `path` |
| `project_delete_file` | `delete_file` | `{path}` |

`completed` result fields (the Rust executor sends at least these):
`{proposal_commitment, project_item_id, previous_project_item_id}` for rename
and `{proposal_commitment, project_item_id}` for delete. A rename onto a linked
path is `conflict` with `{code: "path_conflict", reason: "path_conflict"}`
(every `conflict` result carries its code as both fields).

The proposal commitment is the Project-key HMAC of the proposal tuple
(`openmates-project-file-proposal-v1`); a rename appends `new_path` to the
tuple, create/update tuples are unchanged. The server never recomputes it: it
binds approvals and receipts to the opaque digest. The web TypeScript
`projectFileMutationProtocol.ts` still knows only create/update, so web
always-ask approval of a rename/delete is not supported yet.

## Implementation notes (backend)

- Extension routes (internal token): `POST /embed-version-transaction/project-items/{adopt|rename|delete}`.
- Receipts live in `project_item_operations` (operation kind, target hash, item
  ids, link kind; no paths or ciphertext). `project_items.link_kind` stores
  `file`/`application`/`test_result`; null is a legacy file link.
- Extra stable codes beyond the list above: `project_item_not_found` (404) for
  rename/delete of an unknown link, `operation_payload_mismatch` (409) when an
  operation id is reused with a different body.
- Rename applies to `file` links only; application and test-result links are
  refused with `invalid_request`.
- Server-owned fields: the server writers grant one exact next version
  (`application`: `latest_screenshot`; `test_result`: `is_current`,
  `stale_reason`, `run_status`) after checking that nothing else changed; the
  client's `store_embed` for that version passes the fence only when every link
  of the embed has that kind. `file` links never pass.
