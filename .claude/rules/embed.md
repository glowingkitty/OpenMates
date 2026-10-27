---
description: Embed component development standards
globs:
  - "**/embed*"
  - "frontend/packages/ui/src/components/embeds/**"
  - "backend/apps/*/skills/embed*"
---

## Embed Development

- **Mandatory result design:** Read `docs/design-guide/result-embeds.md` before
  implementing or changing result previews/fullscreens. Reuse its shared layouts
  and icon information components. Preserve specialized Code, Docs and Sheets designs.

- Always use `UnifiedEmbedPreview.svelte` / `UnifiedEmbedFullscreen.svelte` as base components.
- For full guide on adding new embed types: `python3 scripts/sessions.py context --doc add-embed-type`
