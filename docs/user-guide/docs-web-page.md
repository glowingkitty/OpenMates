# Docs Markdown to Web Pages

> **Status**: 🚧 In Progress (Unified Implementation)

## Overview

Auto-convert markdown files from `/docs` to web pages accessible at `openmates.org/docs`, making docs the single source of truth for all documentation. This unified approach integrates markdown documentation with API documentation under a single authenticated experience.

## Architecture Decision

### Unified Domain Approach (`openmates.org/docs`)

We chose to integrate documentation into the main web app rather than a separate `docs.openmates.org` domain:

**Benefits:**
- **Shared authentication**: Users logged into the web app are already authenticated
- **API key auto-selection**: "Try it" functionality in API docs uses the user's existing API key
- **Unified SEO**: All content benefits a single domain's authority
- **Simpler deployment**: Single SvelteKit app handles everything
- **Easy cross-linking**: Between app features and relevant documentation

## Content Types

### 1. Markdown Documentation (`/docs/*`)
- Architecture docs, FAQ, user guides, developer documentation
- Rendered at build time from `/docs/**/*.md`
- Respects `.docsignore` patterns

### 2. API Documentation (`/docs/api`)
- Interactive OpenAPI/Swagger documentation
- Auto-uses logged-in user's API key for "Try it" requests
- Replaces `api.openmates.org/docs`

## Build Process

- Convert during Vercel deployment build via `frontend/apps/web_app/scripts/process-docs.js`
- Works in `pnpm dev` mode for local testing with hot-reload
- Source: `/docs/**/*.md` → Output: `docs-data.json` (navigation + content)

## Features

### 1. Copy Button
Copies current page or entire folder (all sub-chapters) as **markdown** to clipboard (not HTML).

### 2. Offline Mode (PWA)
Docs work offline by default as a Progressive Web App, integrated with web app's existing service worker.

### 3. Download PDF Button
Downloads current page or folder as PDF, generated on-demand client-side.

### 4. Sidebar Navigation
Tree-based navigation with collapsible folders, reusing design patterns from chat sidebar.

### 5. Search
Full-text search within documentation using FlexSearch, with results showing context snippets.

### 6. API Interactive Testing
When logged in, API docs auto-inject the user's API key for testing endpoints directly.

## Implementation Files

### Core Processing
- **Build Script**: `frontend/apps/web_app/scripts/process-docs.js` - Processes markdown files and generates JSON structure
- **Vite Plugin**: Integrated into `vite.config.ts` for dev mode hot-reload

### Page Components
- **Root Docs Page**: `frontend/apps/web_app/src/routes/docs/+page.svelte` - Documentation index
- **Dynamic Docs Pages**: `frontend/apps/web_app/src/routes/docs/[...slug]/+page.svelte` - Individual document pages
- **API Docs**: `frontend/apps/web_app/src/routes/docs/api/+page.svelte` - OpenAPI interactive docs

### Shared Components (in `@repo/ui`)
- **DocsSidebar.svelte**: Navigation sidebar with collapsible folders
- **DocsContent.svelte**: Renders processed markdown content as HTML
- **DocsSearch.svelte**: Search within documentation

### Utilities
- **PDF Generator**: `pdfGenerator.ts` - Client-side PDF generation using jsPDF

## Implementation Notes

- Markdown → HTML conversion at build time via `marked`
- Syntax highlighting for code blocks via `highlight.js`
- PDF generation: client-side using jsPDF
- PWA service worker caches docs for offline access
- **Copy functionality**: Always copies markdown source, not rendered HTML
- API docs: Embed Scalar or Swagger UI with authentication integration

## Migration Plan

1. Implement `/docs` routes in web_app
2. Test alongside existing `api.openmates.org/docs`
3. Add redirect from `api.openmates.org/docs` → `openmates.org/docs/api`
4. Deprecate old API docs endpoint
