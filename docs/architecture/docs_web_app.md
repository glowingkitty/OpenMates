# Docs web app architecture

The documentation web app (`docs.openmates.org`) is a separate offline-first PWA that serves as the single source of truth for user-facing documentation.

## Design principles

- **Offline-first PWA**: All docs are loaded and cached on first visit, enabling full offline functionality thereafter
- **Separate domain**: Keeps documentation independent from the main web app, with its own deployment pipeline and caching strategy
- **Complete on first load**: Users don't encounter missing pages offline; all docs are available after the initial visit
- **Docs-only search**: Internal search within the docs app indexes only documentation, not web app content

## Offline strategy

### First visit

When a user visits `docs.openmates.org` for the first time:

1. Service worker downloads and caches all documentation pages
2. Search index for docs is built and cached locally
3. Full offline functionality is enabled

### Subsequent visits

All documentation is served from cache, enabling offline access regardless of internet connectivity or which specific doc page is visited.

## Search

The docs web app includes its own search functionality that indexes only documentation content. This is separate from the main web app's unified search (which includes a compact docs index and can search chats, settings, etc.).

### Docs search features

- Indexes all doc pages, titles, and content
- Fast offline search with no network required
- Returns results with snippets showing context
- Links to relevant doc pages

## PWA setup

- **Service worker**: Pre-caches all documentation assets and pages
- **Web app manifest**: Defines app metadata and icon
- **Cache strategy**: Network-first for initial load (to check for updates), then cache-first for offline support
- **Storage**: Uses IndexedDB for search index, browser cache for document pages

## Build integration

Documentation is generated from markdown files in `/docs`. The build process:

1. Converts markdown to web-optimized HTML/JSON
2. Generates search index for internal docs search
3. Bundles all assets for PWA distribution
4. Creates compact search index snippet for main web app (via build pipeline)

## Related

- [Search architecture](./search.md) - unified search in main web app that includes docs reference
