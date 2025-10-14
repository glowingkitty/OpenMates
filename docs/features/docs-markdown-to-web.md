# Docs Markdown to Web Pages

> **Status**: ✅ Implemented

## Overview
Auto-convert markdown files from `/docs` to Svelte pages during build process, making docs the single source of truth for the website docs section.

## Build Process
- Convert during Vercel deployment build via [`../../frontend/apps/website/scripts/process-docs.js`](../../frontend/apps/website/scripts/process-docs.js)
- Works in `pnpm dev` mode for local testing
- Source: `/docs/**/*.md` → Output: Svelte pages

## Features

### 1. Copy Button
Copies current page or entire folder (all sub-chapters) as **markdown** to clipboard (not HTML). Implemented in:
- [`../../frontend/apps/website/src/routes/docs/+page.svelte`](../../frontend/apps/website/src/routes/docs/+page.svelte) (root docs page)
- [`../../frontend/apps/website/src/routes/docs/[...slug]/+page.svelte`](../../frontend/apps/website/src/routes/docs/[...slug]/+page.svelte) (dynamic docs pages)

### 2. Offline Mode (PWA)
Docs work offline by default as a Progressive Web App.

### 3. Download PDF Button
Downloads current page or folder as PDF, generated on-demand (works offline). Uses client-side PDF generation via [`../../frontend/apps/website/src/lib/utils/pdfGenerator.ts`](../../frontend/apps/website/src/lib/utils/pdfGenerator.ts).

### 4. Sidebar Navigation
Reuse existing chat sidebar design from web app for showing chapters/files. Can be opened/closed. Implemented in [`../../frontend/apps/website/src/lib/components/DocsSidebar.svelte`](../../frontend/apps/website/src/lib/components/DocsSidebar.svelte).

## Implementation Files

### Core Processing
- **Build Script**: [`../../frontend/apps/website/scripts/process-docs.js`](../../frontend/apps/website/scripts/process-docs.js) - Processes markdown files and generates JSON structure
- **Content Renderer**: [`../../frontend/apps/website/src/lib/components/DocsContent.svelte`](../../frontend/apps/website/src/lib/components/DocsContent.svelte) - Renders processed content as HTML

### Page Components
- **Root Docs Page**: [`../../frontend/apps/website/src/routes/docs/+page.svelte`](../../frontend/apps/website/src/routes/docs/+page.svelte) - Main documentation index
- **Dynamic Docs Pages**: [`../../frontend/apps/website/src/routes/docs/[...slug]/+page.svelte`](../../frontend/apps/website/src/routes/docs/[...slug]/+page.svelte) - Individual document pages

### Utilities
- **PDF Generator**: [`../../frontend/apps/website/src/lib/utils/pdfGenerator.ts`](../../frontend/apps/website/src/lib/utils/pdfGenerator.ts) - Client-side PDF generation using jsPDF
- **Sidebar Component**: [`../../frontend/apps/website/src/lib/components/DocsSidebar.svelte`](../../frontend/apps/website/src/lib/components/DocsSidebar.svelte) - Navigation sidebar with collapsible folders

## Implementation Notes
- Use existing sidebar component pattern from web app
- Markdown → HTML conversion at build time via `process-docs.js`
- PDF generation: client-side using jsPDF
- PWA service worker for offline caching
- **Copy functionality**: Always copies markdown source, not rendered HTML

