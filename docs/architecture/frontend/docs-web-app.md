---
status: active
last_verified: 2026-03-24
key_files:
  - frontend/apps/web_app/scripts/process-docs.js
  - frontend/apps/web_app/scripts/vite-plugin-docs.js
  - frontend/apps/web_app/src/routes/docs/+layout.svelte
  - frontend/apps/web_app/src/routes/docs/[...slug]/+page.svelte
  - frontend/apps/web_app/src/routes/docs/api/+page.svelte
  - frontend/apps/web_app/src/lib/components/docs/DocsSidebar.svelte
  - frontend/apps/web_app/src/lib/components/docs/DocsContent.svelte
  - frontend/apps/web_app/src/lib/components/docs/DocsSearch.svelte
  - frontend/apps/web_app/src/lib/generated/docs-data.json
---

# Docs Web App

> Documentation system integrated into the main web app at `openmates.org/docs`, rendering repository markdown files with search, navigation, and API reference.

## Why This Exists

Keeps all documentation in a single codebase (`/docs/**/*.md`) and serves it through the web app rather than a separate docs site. Users get seamless access with their existing session, and offline access via the service worker.

## How It Works

### Build Pipeline (`process-docs.js`)

1. Scans `/docs/**/*.md` (respects `.docsignore` exclusion patterns)
2. Converts markdown to HTML using `markdown-it` with `highlight.js` syntax highlighting
3. Generates heading IDs for anchor links, resolves relative links, fixes image paths
4. Outputs `src/lib/generated/docs-data.json` containing:
   - Navigation tree structure
   - HTML content per page
   - Original markdown (for copy functionality)
   - Metadata (titles, slugs, paths)
5. Generates FlexSearch index for full-text search

### Dev Mode (`vite-plugin-docs.js`)

Vite plugin watches `/docs` directory and hot-reloads on markdown changes using the same processing pipeline.

### Frontend Components

Located in `frontend/apps/web_app/src/lib/components/docs/`:

| Component | Purpose |
|-----------|---------|
| `DocsSidebar.svelte` | Collapsible tree navigation, active page highlighting, mobile drawer |
| `DocsContent.svelte` | HTML renderer with table of contents, copy-to-clipboard, PDF download, "Edit on GitHub" link |
| `DocsSearch.svelte` | FlexSearch full-text search with context snippets, Cmd/Ctrl+K shortcut |

### Layout

The docs layout (`+layout.svelte`) mirrors the main chat page pattern:
- Fixed-position sidebar (325px) with slide transition
- Main content area offset by sidebar width
- Responsive: sidebar slides off-screen on mobile

Individual doc pages (`[...slug]/+page.svelte`) render content as a single assistant message using `DocsMessage` + TipTap, matching the chat UI style.

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

Integrated with the web app's PWA service worker. `docs-data.json` and search index are cached for offline access.

## Related Docs

- [Web App Architecture](./web-app.md) -- overall app structure
- [REST API](../apps/rest-api.md) -- API endpoint documentation
