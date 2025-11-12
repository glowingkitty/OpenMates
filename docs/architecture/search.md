# Search architecture

## Auto complete

When user types in search input, show instant auto complete suggestions based on the tags of the chats (filtered to remove duplicates).

## Search

The search is searching with a low debounce time of 100ms after the user stops typing:

- all chat messages
- all chat titles
- all chat summaries
- all chat tags
- all settings menus & sub menus
- all apps in the app store (once apps are implemented)
- all app settings & memories of user (once apps are implemented)
  - All entry data across all categories (e.g., movie titles, restaurant names, trip destinations)
  - Entry metadata (categories, dates, notes, etc.)
  - Searchable across all apps and categories
- all app skills (once apps are implemented)
- all app focus modes (once apps are implemented)
- all documentation pages (compact search index bundled with the app)

### Documentation Search

Documentation is included in the offline-first search via a compact search index generated at build time. The index contains:

- page titles
- summaries and excerpts
- keywords and tags
- clickable links to full documentation

This index is bundled with the web app during build, keeping it lightweight (a few KB) while enabling fast, fully offline search. When users click a result, they navigate to the docs web app (`docs.openmates.org`), which loads all documentation on first visit and then works offline regardless of which page is accessed.

If the user has previously visited the docs web app, all pages are cached by the PWA service worker and available offline. If they haven't visited before, they'll see a search result summary that links to the docs.