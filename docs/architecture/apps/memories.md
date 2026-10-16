# Focus modes and Memories

The product uses two concepts for assistant context. A **Focus mode** tells the assistant how to work; a **Memory** supplies facts, preferences or reusable guidance. **Specifications** remain the required result and acceptance criteria. Memory selection cannot approve requirements, override explicit user intent or grant tool access.

Focus phases are optional. An imported `AGENTS.md` or `CLAUDE.md` supplies a Project's default “Work on …” Focus without requiring phases or splitting its instructions into Memories. Optional phases only organize a Focus that actually needs sequential stages.

## Memory sources and loading

| Source | Storage | Inclusion |
|---|---|---|
| App-provided | Reviewed Markdown in `backend/apps/<app>/memories/` | Automatically selected when relevant from the authoritative eligible app catalog |
| Project | Encrypted Project documents under `.openmates/memories/` | Automatically selected when relevant within the currently active, authorized Project Focus |
| Personal or team | Existing encrypted app memory entries | Existing per-conversation request, selection, approval or rejection; an explicit mention includes only the named category/entry |

Examples of Project Memories include “The staging API uses port 8001”, “The current prototype targets tablet browsers” and “The team prefers Svelte components.” A Focus such as “Investigate this project's failure” defines the work process. A Specification such as “A rejected memory request must disclose no content” defines an obligation. Personal notes about a Project retain personal consent; their subject does not confer Project access.

Public documents contain exactly `title`, `description`, and `when_to_use` in YAML frontmatter, followed by the complete guidance body. Stable identity includes the owning app. Revisions identify the exact document, not a synthesized summary. Code supplies JavaScript, TypeScript, Svelte and Python guidance; Design supplies mobile first design and accessibility guidance.

Discovery uses the existing Memory cards for both sources: a small **Public** label with a white web icon for published app documents, and **Private** with a white lock icon for user-created memory types. Both labels appear at the top left in the description text color. Visibility describes publication and encryption; it does not grant access. Personal memory consent and active Project access remain separate loading policies.

Project source records, access and Focus activation are checked again after asynchronous selection/decryption. A source revision change invalidates the selected snapshot. Deactivation prevents future inclusion; content previously included in a chat remains part of that chat. Other selected Project document kinds still supply their existing Focus or Specification context.

## Discovery, consent and receipts

Published Memories appear read-only in the existing Memories hub and app details. Their display identifies the app-provided source and relevance-based automatic loading. Personal entries retain their existing encrypted editing and sync flows.

The npm SDK exposes `client.memories.published({appId: 'code'})`; the pip SDK exposes `client.memories.published(app_id='code')`. Omitting the app selects the complete published catalog. Both return a `memories` list with the exact public documents without sending account credentials. Existing private `list`, `types` and encrypted CRUD methods retain their meaning.

`memories_loaded` reports the exact app/Project documents actually applied to a prompt: source, identity, revision and body. Clients encrypt the receipt with the chat key and show “Loaded N memories”. The private-memory request/response badge remains a consent receipt; it does not imply that public or Project context received personal approval. Historical applied-context bodies are projected to identity/revision references before replay to the model, preventing stale guidance from becoming fresh authority.

## Compatibility

New account document writes use the encrypted `memory_documents` namespace; existing encrypted `rule_documents` are read and merged by their original identity. They are surfaced as the declared private `openmates/memories` category, with virtual `account-memory-…` entry IDs. Editing keeps the original document identity and preserves unrelated encrypted account preferences. Deletion removes that identity from both namespaces.

New Project Memory documents use `.openmates/memories/`. Existing `.openmates/rules/` and Project fact documents remain readable as Project Memories under current access checks. Historical `rules_loaded` receipts retain their original stored content and render through a bounded compatibility parser. No bulk history or ciphertext migration is required.

The owning contract is [feature.app-memories](../../../specifications/features/app-memories/specification.yml); the old Rules contract is superseded. [Focus modes](../../../specifications/features/focus-modes/specification.yml) and [Projects](../../../specifications/features/projects/specification.yml) define activation and optional-phase behavior.
