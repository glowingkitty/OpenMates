# Docs Architecture

The documentation system is integrated into the main web app at `openmates.org/docs`, providing a unified experience for all OpenMates documentation including user guides, developer docs, and API reference.

## Design Principles

- **Unified experience**: Documentation is part of the main web app, not a separate domain
- **Authenticated by default**: Logged-in users have seamless access with their credentials
- **Offline-first PWA**: Docs are cached for offline access via the web app's service worker
- **Single source of truth**: All docs come from `/docs/**/*.md` in the repository
- **API integration**: Interactive API docs with auto-authentication

## Content Structure

### Markdown Documentation (`/docs/*`)

Documentation organized by purpose:

```
/docs
├── architecture/       # Technical architecture docs
│   ├── apps/          # App-specific architecture
│   └── ...
├── features/          # Feature specifications
├── business_plan/     # Business documentation
├── designguidelines/  # Design system docs
└── .docsignore        # Files to exclude from processing
```

### API Documentation (`/docs/api`)

Interactive API reference that:
- Displays OpenAPI spec from FastAPI backend
- Auto-injects logged-in user's API key
- Provides "Try it" functionality for all endpoints
- Shows real-time usage and rate limits

## Build Pipeline

### At Build Time

1. **process-docs.js** scans `/docs/**/*.md`
2. Respects `.docsignore` exclusion patterns
3. Converts markdown to HTML with:
   - Syntax highlighting (highlight.js)
   - Heading IDs for anchor links
   - Relative link resolution
   - Image path fixing
4. Generates `docs-data.json` with:
   - Navigation tree structure
   - HTML content for each page
   - Original markdown (for copy functionality)
   - Metadata (titles, slugs, paths)
5. Generates search index for FlexSearch

### In Dev Mode

- Vite plugin watches `/docs` directory
- Hot-reloads on markdown file changes
- Same processing pipeline as build

## Frontend Components

### DocsSidebar.svelte

Tree navigation component:
- Collapsible folder structure
- Active page highlighting
- Mobile-responsive (drawer on mobile)
- Keyboard navigation support

### DocsContent.svelte

Content renderer:
- Displays processed HTML
- Table of contents generation
- Copy to clipboard button
- PDF download button
- Edit on GitHub link

### DocsSearch.svelte

Full-text search:
- FlexSearch for fast offline search
- Results with context snippets
- Keyboard shortcuts (Cmd/Ctrl+K)

## Offline Strategy

Integrated with web app's existing PWA:

1. **First visit**: Service worker caches docs-data.json and all doc pages
2. **Subsequent visits**: Served from cache, network-first for updates
3. **Search**: Index stored in IndexedDB for offline search

## URL Structure

```
/docs                           → Documentation index
/docs/architecture              → Architecture section index
/docs/architecture/chats        → Specific doc page
/docs/api                       → Interactive API reference
/docs/api/endpoints/chats       → Specific API endpoint docs
```

## Authentication Integration

When users are logged in:

1. **API docs**: Automatically use user's API key for "Try it"
2. **Developer docs**: Show personalized examples with their credentials
3. **Usage display**: Show their current API usage and limits

When users are not logged in:

1. **Read-only access**: All docs are publicly readable
2. **API testing**: Prompts to log in for "Try it" functionality
3. **Sign-up links**: Contextual CTAs to create account

## Related Documentation

- [Search Architecture](./search.md) - Unified search including docs
- [PWA Architecture](./web_app.md) - Service worker and offline support
