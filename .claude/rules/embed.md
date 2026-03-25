---
description: Embed component development standards
globs:
  - "**/embed*"
  - "frontend/packages/ui/src/components/embeds/**"
  - "backend/apps/*/skills/embed*"
---

## Embed Development

- Always use `UnifiedEmbedPreview.svelte` / `UnifiedEmbedFullscreen.svelte` as base components.
- For full guide on adding new embed types: `python3 scripts/sessions.py context --doc add-embed-type`
