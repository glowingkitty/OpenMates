# Tasks assignment and Activity

Task execution ownership and display identity are intentionally separate:

- `user`: a human; the authenticated user hash identifies the assignee.
- `openmates`: native OpenMates execution; identity is `openmates` and the UI displays OpenMates.
- `external_ai`: execution outside OpenMates; the initial allowlisted identity is `opencode`, displayed as OpenCode.
- `unassigned`: no current owner.

Only `openmates` Tasks participate in native queue admission or capacity accounting. OpenCode creates `external_ai/opencode` Tasks atomically with encrypted external-chat context. Work that the user must personally perform remains `user`-assigned.

Activity is an append-oriented Task-scoped stream. User and agent updates reuse `comment_added`; deletion replaces comment content with a tombstone. The database mutation boundary automatically adds `lifecycle_update` rows for creation and real status transitions, including safe `previous_status` and `next_status` values. This keeps lifecycle history consistent across web, CLI, SDK, and automation callers.

Comment text is encrypted directly with the Task key. Every encryption uses a fresh AES-GCM nonce and versioned AAD containing the Task and Activity entry IDs. Embed-key material uses the same Task key but an independent nonce and distinct AAD domain. The obsolete per-comment wrapped entry key is not stored because Activity was unreleased and needs no compatibility path.
