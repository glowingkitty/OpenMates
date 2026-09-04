# Task commands

OpenMates Tasks keep their title, description, labels, comments, and attachment-key material encrypted by clients. The CLI decrypts authorized content locally.

Create and assign Tasks with one command:

```bash
openmates tasks create --title "Prepare release" --assign openmates
openmates tasks create --title "Implement bridge" --assign external-ai --external-chat opencode:ses_123
openmates tasks create --title "Buy test device" --assign user
```

Assignment has two separate parts. `user`, `openmates`, `external_ai`, and `unassigned` describe who owns execution. An allowlisted identity describes a named AI: `openmates` displays as OpenMates and `opencode` displays as OpenCode. The `external-ai` CLI value creates `external_ai/opencode`; callers cannot supply arbitrary display names.

Task Activity uses ordinary comments and server-generated lifecycle rows:

```bash
openmates tasks activity list TASK-1234
openmates tasks activity add TASK-1234 --message "The API specification behavior is verified."
openmates tasks activity delete TASK-1234 <entry-id>
```

Each comment is encrypted directly with the Task key using a fresh AES-GCM nonce and Task/entry/version authenticated data. Attachment key material is encrypted separately with another nonce. The server stores ciphertext, safe actor attribution, timestamps, event type, and lifecycle status metadata. Creation and actual status changes automatically append system lifecycle entries; clients do not create those entries.

`--as-assignee` is reserved for the trusted OpenCode bridge. It attributes the comment to the Task's validated `external_ai/opencode` assignment.

The OpenCode bridge automatically waits and retries when the development API is briefly unavailable during a restart. It uses five bounded delays (2, 4, 8, 12, and 16 seconds). Authentication, validation, permission, and version-conflict errors fail immediately; they are not made less visible by retrying.
