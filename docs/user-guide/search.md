---
status: active
doc_type: guide
audience:
  - users
last_verified: 2026-06-11
claims:
  - id: user-guide-search-source
    type: unit
    claim: Search behavior is grounded in the local search service and settings/app catalog sources.
    file: scripts/tests/test_user_guide_product_docs_claims.py
    assertion: user-guide-search-source
---

# Search

> Find messages, chats, settings, apps, and memories from one search bar. Search runs locally from decrypted data already available on your device.

## What It Does

Search lets you quickly find content across your OpenMates experience. Because your data is encrypted, the app builds an in-memory index locally from decrypted chats, messages, embeds, settings, apps, skills, focus modes, and memories. Your query is not sent to the server for private chat search.

## What You Can Search

- **Chat messages** -- Find text within any of your conversations.
- **Chat titles and summaries** -- Locate chats by name or topic.
- **Chat tags** -- Filter by automatically assigned tags.
- **Settings menus** -- Jump to any settings page.
- **Apps and skills** -- Find apps in the Apps.
- **App memories** -- Search entries you have saved (movie titles, restaurant names, trip notes, and so on).
- **Embed content** -- Find text extracted from supported embed payloads.

## How to Use It

1. Open the search bar.
2. Start typing. Results appear as the local index warms up and matches your query.
3. Click a result to navigate to it.

### Auto-Complete

As you type, suggestions based on your chat tags appear automatically, helping you find the right term faster.

### Fuzzy Matching

Search is forgiving of typos and spelling mistakes. If your query is close to the correct word, relevant results will still appear. Exact matches are ranked higher.

## How Search Works Behind the Scenes

- When a new message arrives, it is indexed immediately on your device.
- On first load, the app indexes your 100 most recent chats in the background (this runs once per device).
- After that, the index is maintained automatically as new messages come in.
- Older chats beyond the top 100 are not indexed by default, but you can search them on demand with a "Search older messages" option.
- Search runs in the background so it does not slow down the rest of the app.

## Tips

- Private chat search is local. Your chat search terms are not sent to a server.
- If you have many chats, the first-time indexing may take a moment while encrypted content is decrypted locally.
- Use specific terms for best results. Tags and chat titles are great starting points.

## Related

- [Chats](chats.md) -- Chat management
- [Keyboard Shortcuts](keyboard-shortcuts.md) -- Quick navigation
