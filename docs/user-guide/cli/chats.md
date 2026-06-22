---
status: active
doc_type: reference
audience:
  - end-users
  - technical-users
last_verified: 2026-06-21
claims:
  - id: cli-chats-help-lists-chat-operations
    type: unit
    claim: Chat command help lists the documented list, search, show, send, share, download, delete, and incognito operations.
    source:
      - frontend/packages/openmates-cli/src/cli.ts
      - frontend/packages/openmates-cli/src/client.ts
      - frontend/packages/openmates-cli/src/ws.ts
      - frontend/packages/openmates-cli/src/shareEncryption.ts
    test:
      file: frontend/packages/openmates-cli/tests/cli.test.ts
      command: cd frontend/packages/openmates-cli && npm run build && npm run test:unit:cli
      assertion: cli-chats-help-lists-chat-operations
    verified: '2026-06-11'
  - id: cli-unauthenticated-example-chats
    type: unit
    claim: Logged-out users can list and show clearly labeled public example chats, while private encrypted chats still require login.
    source:
      - frontend/packages/openmates-cli/src/cli.ts
      - frontend/packages/openmates-cli/src/exampleChats.ts
      - frontend/packages/ui/src/demo_chats/exampleChatData.ts
    test:
      file: frontend/packages/openmates-cli/tests/cli.test.ts
      command: cd frontend/packages/openmates-cli && npm run build && npm run test:unit:cli
      assertion: cli-unauthenticated-example-chats
    verified: '2026-06-11'
  - id: cli-tui-examples-continue-with-full-history
    type: unit
    claim: CLI TUI example continuations keep the public example transcript as request history instead of sending only a source marker.
    source:
      - frontend/packages/openmates-cli/src/tui.ts
      - frontend/packages/openmates-cli/src/tuiExampleContinuation.ts
    test:
      file: frontend/packages/openmates-cli/tests/tuiExampleContinuation.test.ts
      command: cd frontend/packages/openmates-cli && npm run test:unit:tui
      assertion: cli-tui-examples-continue-with-full-history
    verified: '2026-06-21'
---

# Chat Commands

Encrypted chat operations -- list, search, view, send messages, share, download, and send incognito messages. Private saved chat data is decrypted client-side using your session's encryption keys.

Without a session, `list`, `show`, and `open` expose only public example chats from the web app. These entries are labeled `EXAMPLE CHAT` and do not include private user data. In the interactive TUI, use `/examples` to browse those examples; typing into an example starts a new continuation chat while keeping the bundled example read-only.

## Interactive Chat TUI

```
openmates
```

Plain `openmates` opens the chat UI when stdin and stdout are both interactive TTYs. The start screen includes the OpenMates intro, `/examples` guidance, file-reference hints such as `@./notes.md` and `@~/Downloads/report.pdf`, and a bottom input field.

Useful TUI commands:

| Command | Description |
|---------|-------------|
| `/examples` | Choose local interest tags and browse ranked public examples |
| `/help` | Show TUI commands |
| `/login` | Run pair-auth login and return to the TUI |
| `/signup` | Leave the TUI and run guided signup with hidden prompts |
| `/embed <id>` | Show the fallback command for full embed details |
| `/clear` | Clear the current terminal transcript view |
| `/exit` | Restore the shell and exit |

If plain `openmates` is run from a script, pipe, or redirected shell, it does not enter alternate-screen mode. It prints common programmatic commands such as `openmates chats new`, `openmates chats send --chat <chat-id>`, `openmates chats list`, and `openmates embeds show <embed-id>`.

### Continuing Public Examples

Example transcripts are read-only, but their input footer behaves like normal chat input. When you continue an example, the CLI starts a new chat context and sends the full public transcript as history with your first continuation message. Logged-out continuations use anonymous free chat history; signed-in continuations use the authenticated chat pipeline. The public example itself is unchanged.

## Listing Chats

```
openmates chats list
openmates chats list --limit 20 --page 2
openmates chats list --json
```

Logged-out output lists public examples. Logged-in output lists your private synced chats.

| Option | Default | Description |
|--------|---------|-------------|
| `--limit <n>` | 10 | Number of chats per page |
| `--page <n>` | 1 | Page number |

## Searching Chats

```
openmates chats search "Madrid"
openmates chats search "flight connections" --json
```

Searches across chat titles and decrypted content. Returns all matching chats.

## Viewing a Chat

```
openmates chats show <chat-id>
openmates chats show example-gigantic-airplanes
openmates chats show last
openmates chats show "Flight Connections Berlin to Bangkok"
openmates chats show d262cb68 --raw
openmates chats show d262cb68 --json
```

For private chats, the chat ID accepts: full UUID, 8-character short ID, exact or partial title match, or the keyword `last` for the most recent chat. When logged out, use an example chat ID, slug, title, or position from `openmates chats list`; the full output starts with an `EXAMPLE CHAT` banner.

| Option | Description |
|--------|-------------|
| `--raw` | Show raw decrypted content without rendering embeds or cleaning embed references (useful for debugging) |
| `--json` | Includes follow-up suggestions in the JSON output |

## Starting a New Chat

```
openmates chats new "Hello, what can you help me with?"
openmates chats new "@Sophia tell me about React hooks"
openmates chats new "@Web-Search latest AI news"
openmates chats new "@best review @./src/app.ts"
openmates chats new "Research flights" --auto-approve
```

Creates a new chat and streams the AI response to your terminal. Supports @mentions for models, mates, skills, and local file attachments. See [embeds-and-sharing.md](./embeds-and-sharing.md) for mention types.

| Option | Description |
|--------|-------------|
| `--auto-approve` | Automatically approve server-requested sub-chat batches for trusted non-interactive runs |
| `--auto-approve-memories` | Explicitly approve server-requested memory categories for trusted non-interactive runs. Memories are never approved by default. |

## Sending a Message to an Existing Chat

```
openmates chats send --chat d262cb68 "follow-up question"
openmates chats send --chat d262cb68 --followup 1
openmates chats send --chat d262cb68 --incognito "private question"
openmates chats send --chat d262cb68 "continue" --auto-approve-memories
```

| Option | Description |
|--------|-------------|
| `--chat <id>` | Chat to continue (full UUID or 8-char short ID) |
| `--followup <n>` | Send the nth AI-generated follow-up suggestion instead of typing a message (requires `--chat`) |
| `--incognito` | Send without saving to chat history |
| `--auto-approve` | Automatically approve server-requested sub-chat batches for trusted non-interactive runs |
| `--auto-approve-memories` | Explicitly approve server-requested memory categories for trusted non-interactive runs. Memories are never approved by default. |

Without `--auto-approve-memories`, memory requests are recorded in chat history and the CLI stops. Continue the chat in the web app to explicitly approve or reject the memory request.

## Opening a Chat in the Browser

```
openmates chats open
openmates chats open 3
openmates chats open gigantic-airplanes-transporting-rocket-parts
```

Opens a chat in your default browser. Logged in, the optional number selects by private-chat position (1 = most recent, 2 = second most recent, etc.). Logged out, the number, example ID, or example slug opens the public `/example/<slug>` page. Defaults to 1.

## Downloading a Chat

```
openmates chats download last
openmates chats download d262cb68 --output ~/exports
openmates chats download last --zip
```

Downloads the chat as a folder containing:
- `.yml` -- YAML export of the full conversation
- `.md` -- Markdown-formatted conversation
- `code/` -- Extracted code embeds (with original filenames when available)
- `transcripts/` -- Video transcript embeds

| Option | Default | Description |
|--------|---------|-------------|
| `--output <path>` | Current directory | Target directory for the download |
| `--zip` | Off | Create a `.zip` archive instead of a folder |

## Deleting Chats

```
openmates chats delete d262cb68
openmates chats delete d262cb68 a1b2c3d4 --yes
```

Deletes one or more chats. Shows chat titles and asks for confirmation before deleting. Use `--yes` to skip the confirmation prompt.

## Sharing a Chat

```
openmates chats share d262cb68
openmates chats share last --expires 604800
openmates chats share d262cb68 --password mypass
```

Creates an encrypted share link for the chat. See [embeds-and-sharing.md](./embeds-and-sharing.md) for details on zero-knowledge share encryption.

| Option | Description |
|--------|-------------|
| `--expires <seconds>` | Link expiration time (0 = no expiry) |
| `--password <pwd>` | Password-protect the link (max 10 characters) |

## Incognito Mode

Incognito messages are not saved to the server and are not stored locally by the CLI. There is no incognito transcript to show or clear after the command exits.

```
openmates chats incognito "private question"
openmates chats incognito "private question" --auto-approve
openmates chats incognito-history
openmates chats incognito-history --json
openmates chats incognito-clear
```

`incognito-history` and `incognito-clear` are retained as compatibility no-ops. They explain that incognito chats are not stored.

## Inspirations

Fetches today's daily inspirations. Works both logged in (personalized, decrypted) and logged out (public).

```
openmates inspirations
openmates inspirations --lang de
openmates inspirations --json
```

| Option | Default | Description |
|--------|---------|-------------|
| `--lang <code>` | en | ISO 639-1 language code (en, de, zh, es, fr, pt, ru, ja, ko, it, tr, vi, id, pl, nl, ar, hi, th, cs, sv) |

## New Chat Suggestions

Shows personalized new chat suggestions generated by the AI after conversations. Requires login.

```
openmates newchatsuggestions
openmates newchatsuggestions --limit 5
openmates newchatsuggestions --json
```

## Key Files

- See [cli.ts](../../../frontend/packages/openmates-cli/src/cli.ts) for `handleChats()` and all chat subcommand handlers
- See [client.ts](../../../frontend/packages/openmates-cli/src/client.ts) for chat API methods (`listChats`, `searchChats`, `getChatMessages`, `sendMessage`)
- See [ws.ts](../../../frontend/packages/openmates-cli/src/ws.ts) for WebSocket streaming during `send` and `new`
- See [shareEncryption.ts](../../../frontend/packages/openmates-cli/src/shareEncryption.ts) for share link encryption

## Related Docs

- [README](./README.md) -- CLI overview
- [Authentication](./authentication.md) -- login, signup, and session security
- [Embeds & Sharing](./embeds-and-sharing.md) -- @mentions and share link encryption
- [Apps & Skills](./apps-and-skills.md) -- skill invocation via @mentions in chat
