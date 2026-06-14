---
status: active
doc_type: reference
audience:
  - end-users
  - technical-users
last_verified: 2026-06-11
claims:
  - id: cli-embeds-sharing-help-lists-commands
    type: unit
    claim: CLI embeds and mentions help expose the documented sharing and mention-search command surface.
    source:
      - frontend/packages/openmates-cli/src/cli.ts
      - frontend/packages/openmates-cli/src/mentions.ts
      - frontend/packages/openmates-cli/src/embedRenderers.ts
    test:
      file: frontend/packages/openmates-cli/tests/cli.test.ts
      command: cd frontend/packages/openmates-cli && npm run build && npm run test:unit:cli
      assertion: cli-embeds-sharing-help-lists-commands
    verified: '2026-06-11'
  - id: cli-mentions-list-includes-skills-focus-and-memories
    type: unit
    claim: CLI mention search includes skills, focus modes, and memory categories.
    source:
      - frontend/packages/openmates-cli/src/mentions.ts
    test:
      file: frontend/packages/openmates-cli/tests/mentions.test.ts
      command: cd frontend/packages/openmates-cli && node --test --experimental-strip-types --loader ./tests/loader.mjs tests/mentions.test.ts
      assertion: cli-mentions-list-includes-skills-focus-and-memories
    verified: '2026-06-11'
  - id: cli-share-links-encrypt-chat-keys
    type: unit
    claim: CLI chat share links encrypt the chat key into a URL-safe key blob.
    source:
      - frontend/packages/openmates-cli/src/shareEncryption.ts
    test:
      file: frontend/packages/openmates-cli/tests/shareEncryption.test.ts
      command: cd frontend/packages/openmates-cli && node --test --experimental-strip-types tests/shareEncryption.test.ts
      assertion: cli-share-links-encrypt-chat-keys
    verified: '2026-06-11'
  - id: cli-share-links-use-web-share-routes
    type: unit
    claim: CLI share links use the same web `/share/chat/:id#key=...` route shape documented for users.
    source:
      - frontend/packages/openmates-cli/src/shareEncryption.ts
    test:
      file: frontend/packages/openmates-cli/tests/shareEncryption.test.ts
      command: cd frontend/packages/openmates-cli && node --test --experimental-strip-types tests/shareEncryption.test.ts
      assertion: cli-share-links-use-web-share-routes
    verified: '2026-06-11'
  - id: cli-embeds-docs-cover-remotion-video-create
    type: unit
    claim: Embed docs describe CLI terminal rendering for Remotion videos/create embeds.
    source:
      - frontend/packages/openmates-cli/src/embedRenderers.ts
      - frontend/packages/openmates-cli/src/client.ts
    test:
      file: frontend/packages/openmates-cli/tests/cli.test.ts
      command: cd frontend/packages/openmates-cli && npm run build && npm run test:unit:cli
      assertion: cli-embeds-docs-cover-remotion-video-create
    verified: '2026-06-11'
---

# Embeds & Sharing

View decrypted embed content, create encrypted share links, and search available @mentions. Embeds are rich content blocks (code snippets, search results, transcripts, etc.) attached to chat messages.

## Viewing an Embed

```
openmates embeds show <embed-id>
openmates embeds show a3f2b1c4
openmates embeds show a3f2b1c4 --json
```

Displays the full decrypted content of an embed in the terminal. The embed ID can be a full UUID or the first 8 characters. Embed IDs are shown when viewing chat conversations with `openmates chats show`.

### Remotion Video Create Embeds

`videos/create` embeds render as terminal-native status cards. While a Remotion render is `processing`, `rendering`, or `needs_rerender`, the CLI refreshes the embed content from the video status endpoint before printing it. Run the command again after rendering finishes to get the rendered video link and QR code.

## Sharing an Embed

```
openmates embeds share <embed-id>
openmates embeds share a3f2b1c4 --expires 604800
openmates embeds share a3f2b1c4 --password mypass
openmates embeds share a3f2b1c4 --json
```

Creates an encrypted share link for a single embed.

| Option | Description |
|--------|-------------|
| `--expires <seconds>` | Link expiration time (0 = no expiry) |
| `--password <pwd>` | Password-protect the link (max 10 characters) |

## Sharing a Chat

Chat share links are created via the `chats share` command. See [chats.md](./chats.md) for details.

```
openmates chats share <chat-id>
openmates chats share last --expires 604800 --password mypass
```

## Share Link Encryption (Zero-Knowledge)

Share links use zero-knowledge encryption. The decryption key is embedded in the URL fragment (after the `#`), which is never sent to the server. This means:

- The server stores only encrypted data and cannot read shared content.
- Anyone with the full URL can decrypt the content.
- Optional password protection adds a second layer -- the recipient must know both the URL and the password.
- Expiration is enforced server-side by deleting the encrypted blob after the specified duration.

See [shareEncryption.ts](../../../frontend/packages/openmates-cli/src/shareEncryption.ts) for the encryption implementation and [client-side-encryption.md](../../architecture/core/client-side-encryption.md) for the broader architecture.

## Mentions

@mentions let you invoke models, mates, skills, or attach files when sending chat messages.

### Listing Available Mentions

```
openmates mentions list
openmates mentions list --type model_alias
openmates mentions list --type skill
openmates mentions list --json
```

| Type | Description | Examples |
|------|-------------|---------|
| `model_alias` | Model shortcuts | @Best, @Fast |
| `model` | Specific AI models | @Claude-Opus-4.6, @GPT-5.4 |
| `mate` | AI mates/personas | @Sophia, @Finn |
| `skill` | App skills | @Web-Search, @Code-Get-Docs |
| `focus_mode` | Focus modes | @Web-Research |
| `settings_memory` | Memories | @Code-Projects |

### Searching Mentions

```
openmates mentions search "web"
openmates mentions search "sophia" --json
```

### Using Mentions in Chat

```
openmates chats new "@Sophia tell me about React hooks"
openmates chats send --chat abc "@best what's the weather?"
openmates chats new "@Web-Search latest AI news"
openmates chats new "@Code-Projects review my architecture"
```

### File Mentions

Attach local files to chat messages using `@/path/to/file` or `@./relative/path`:

```
openmates chats new "@best review @./src/app.ts"
openmates chats new "@best review @/home/user/project/.env"
```

Security rules for file mentions:
- Sensitive files (`.env`) are scrubbed locally before upload -- only variable names and the last 3 characters of values are sent.
- Private keys (`.pem`, `.key`, SSH keys) are blocked by default.

## Key Files

- See [cli.ts](../../../frontend/packages/openmates-cli/src/cli.ts) for `handleEmbeds()` and `handleMentions()`
- See [mentions.ts](../../../frontend/packages/openmates-cli/src/mentions.ts) for mention parsing and listing
- See [embedRenderers.ts](../../../frontend/packages/openmates-cli/src/embedRenderers.ts) for terminal embed rendering
- See [shareEncryption.ts](../../../frontend/packages/openmates-cli/src/shareEncryption.ts) for share link encryption
- See [fileEmbed.ts](../../../frontend/packages/openmates-cli/src/fileEmbed.ts) for file attachment processing
- See [outputRedactor.ts](../../../frontend/packages/openmates-cli/src/outputRedactor.ts) for auto-redaction of personal data in terminal output

## Related Docs

- [README](./README.md) -- CLI overview
- [Chat Commands](./chats.md) -- using mentions in chat, share command
- [Client-Side Encryption](../../architecture/core/client-side-encryption.md) -- encryption architecture
- [CLI Standards](../../contributing/standards/cli.md) -- Rule 5 on embed key resolution strategies
