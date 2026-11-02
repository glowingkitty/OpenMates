# Tasks assignment and Activity

Task execution ownership and display identity are intentionally separate:

- `user`: a human; the authenticated user hash identifies the assignee.
- `openmates`: native OpenMates execution; identity is `openmates` and the UI displays OpenMates.
- `external_ai`: execution outside OpenMates; the allowlisted identity is `codex`, displayed as Codex.
- `unassigned`: no current owner.

Only `openmates` Tasks participate in native queue admission or capacity accounting. Codex creates `external_ai/codex` Tasks atomically with encrypted external-chat context. Work that the user must personally perform remains `user`-assigned.

External-chat providers are separate from assignee identities. `codex` (thread UUID) and `claude` (Claude Code session UUID from `CLAUDE_CODE_SESSION_ID`) are allowlisted `external_chat_provider` values; the external ID and title stay client-encrypted and filtering uses the provider-domain-separated blind index. A `claude` link is conversation ownership only: it never creates a `claude` assignee identity, creator receipt, connection or resume path, so older clients that decode assignee identities strictly are unaffected. Codex-only behaviors (dependency auto-release triggers, confirmed-deletion unlinking, the foreground delivery bridge) ignore `claude` links.

Activity is an append-oriented Task-scoped stream. User and agent updates reuse `comment_added`; deletion replaces comment content with a tombstone. The database mutation boundary automatically adds `lifecycle_update` rows for creation and real status transitions, including safe `previous_status` and `next_status` values. This keeps lifecycle history consistent across web, CLI, SDK, and automation callers.

Comment text is encrypted directly with the Task key. Every encryption uses a fresh AES-GCM nonce and versioned AAD containing the Task and Activity entry IDs. Embed-key material uses the same Task key but an independent nonce and distinct AAD domain. The obsolete per-comment wrapped entry key is not stored because Activity was unreleased and needs no compatibility path.
