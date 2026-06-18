---
status: active
last_verified: 2026-06-15
key_files:
- frontend/apps/web_app/scripts/process-docs.js
- frontend/apps/web_app/scripts/vite-plugin-docs.js
- frontend/apps/web_app/src/routes/docs/+layout.svelte
- frontend/apps/web_app/src/routes/docs/+page.ts
- frontend/apps/web_app/src/routes/docs/[...slug]/+page.svelte
- frontend/apps/web_app/src/routes/docs/[...slug]/+page.ts
- frontend/apps/web_app/src/routes/docs/api/+page.svelte
- frontend/apps/web_app/src/lib/components/docs/DocsSidebar.svelte
- frontend/apps/web_app/src/lib/components/docs/DocsMessage.svelte
- frontend/apps/web_app/src/lib/generated/docs-manifest.json
- frontend/apps/web_app/static/generated/docs/
claims:
- id: arch-frontend-docs-web-app-behavior
  type: unit
  claim: Docs Web App is grounded in current source-of-truth files that parse or resolve successfully.
  source:
  - frontend/apps/web_app/scripts/process-docs.js
  - frontend/apps/web_app/scripts/vite-plugin-docs.js
  - frontend/apps/web_app/src/routes/docs/+layout.svelte
  - frontend/apps/web_app/src/routes/docs/+page.ts
  - frontend/apps/web_app/src/routes/docs/[...slug]/+page.svelte
  test:
    file: scripts/tests/test_architecture_behavioral_claims.py
    command: python3 -m pytest scripts/tests/test_architecture_behavioral_claims.py
    assertion: arch-frontend-docs-web-app-behavior
  verified: '2026-06-11'
- id: arch-frontend-docs-web-app-source-1
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-frontend-docs-web-app-source-1
  anchors:
  - type: file_exists
    path: frontend/apps/web_app/scripts/process-docs.js
- id: arch-frontend-docs-web-app-source-2
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-frontend-docs-web-app-source-2
  anchors:
  - type: file_exists
    path: frontend/apps/web_app/scripts/vite-plugin-docs.js
- id: arch-frontend-docs-web-app-source-3
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-frontend-docs-web-app-source-3
  anchors:
  - type: file_exists
    path: frontend/apps/web_app/src/lib/components/docs/DocsMessage.svelte
---

# Docs Web App

> Documentation system integrated into the main web app at `openmates.org/docs`, rendering repository markdown files with fast static payloads, search, navigation, and API reference.

## Why This Exists

Keeps all documentation in a single codebase (`/docs/**/*.md`) and serves it through the web app rather than a separate docs site. The runtime architecture optimizes first load by shipping a small navigation manifest up front, then loading only the current page or search index when needed.

## How It Works

### Build Pipeline (`process-docs.js`)

1. Scans `/docs/**/*.md` (respects `.docsignore` exclusion patterns)
2. Converts markdown to HTML using `markdown-it` with `highlight.js` syntax highlighting
3. Generates heading IDs for anchor links, resolves relative links, fixes image paths
4. Outputs `src/lib/generated/docs-manifest.json` containing only navigation metadata: titles, slugs, descriptions, word counts, and static payload URLs.
5. Outputs one static JSON payload per page under `static/generated/docs/pages/` containing rendered HTML and original markdown for download/copy.
6. Outputs `static/generated/docs/search.json` for full-text search. This file is loaded only when search is used.

### Dev Mode (`vite-plugin-docs.js`)

Vite plugin watches `/docs` directory and hot-reloads on markdown changes using the same processing pipeline.

### Frontend Components

Located in `frontend/apps/web_app/src/lib/components/docs/`:

| Component | Purpose |
|-----------|---------|
| `DocsSidebar.svelte` | Collapsible tree navigation, active page highlighting, mobile drawer, lazy full-text search |
| `DocsMessage.svelte` | Static HTML renderer styled like an assistant docs message; Mermaid is enhanced on demand |

### Layout

The docs layout (`+layout.svelte`) mirrors the main chat page pattern:
- Fixed-position sidebar (325px) with slide transition
- Main content area offset by sidebar width
- Responsive: sidebar slides off-screen on mobile

Individual doc pages (`[...slug]/+page.svelte`) render content as a single assistant-style docs message using build-time HTML. The docs route intentionally does not use TipTap or chat message parsing so the first load stays small.

### URL Structure

```
/docs                      -- Documentation index
/docs/architecture/chats   -- Specific doc page
/docs/api                  -- Interactive API reference (OpenAPI from FastAPI)
```

### Authentication Integration

- Logged-in users: API docs auto-inject user's API key for "Try it" functionality
- Public access: All docs are readable without login; API testing prompts login

### Offline Support

The docs page does not provide a dedicated offline mode. The web app's legacy service worker unregisters itself, and docs assets rely on normal browser/CDN caching. This keeps the docs implementation simpler and prioritizes fast online loading.

## Related Docs

- [Web App Architecture](./web-app.md) -- overall app structure
- [REST API](../apps/rest-api.md) -- API endpoint documentation
