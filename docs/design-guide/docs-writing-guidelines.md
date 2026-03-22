# Documentation Writing Guidelines

Guidelines for writing and maintaining OpenMates documentation — for both human and AI contributors.

## Document Structure
- Keep docs concise and scannable
- Use headings as questions users might ask
- Start with a brief overview (2-3 sentences max)
- Include a "Related Docs" section at the bottom linking to related pages
- Every architecture doc should have a "Key Files" section linking to source code

## Writing for the Right Audience

### User Guide (non-technical)
- Plain language, no jargon
- Use "digital team mates" instead of "AI agents"
- Avoid terms like "LLM", "API", "WebSocket" — use simpler alternatives
- Step-by-step instructions with expected outcomes
- Screenshots and examples where helpful

### Architecture & CLI (developers)
- Technical terms are fine but define them on first use
- Focus on the "why" behind design decisions
- Link to specific source files instead of including code examples
- Document trade-offs and alternatives considered

### Design Guide (humans & AI)
- Focus on principles over prescriptions
- Include links to live preview pages where applicable
- Reference specific component names and file paths

## No Code Examples — Link to Code Files Instead

Code examples in docs go stale fast. Instead:
- Link to the actual source file: `[cryptoService.ts](../path/to/cryptoService.ts)`
- Reference function names: "See `decryptChatData()` in `cryptoService.ts`"
- Links are processed by the build system — relative `.md` links become `/docs/` routes, relative code links become GitHub URLs

## Cross-References
- Link to related docs, don't duplicate content
- Use relative markdown links (processed automatically by the build system)
- When referencing architecture decisions, link to the architecture doc rather than explaining inline

## Freshness
- Architecture docs are tracked via `code-mapping.yml` — when mapped code changes, the doc is flagged as stale
- Every doc should have clear enough content that staleness can be detected by reviewing the linked code files
- When updating code, check if it appears in `docs/architecture/code-mapping.yml` and update the corresponding doc

## File Naming
- Use kebab-case: `message-processing.md`, not `MessageProcessing.md`
- Use descriptive names that match the topic: `payment-processing.md`, not `payments.md`
- User-facing docs use the feature name: `sharing.md`, `keyboard-shortcuts.md`

## Header Comments
Every new documentation file should start with a title (`# Title`) and a brief overview paragraph. No frontmatter or metadata headers are needed — the build system extracts the title from the first `#` heading.
