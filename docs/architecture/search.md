# Search Architecture

**Status**: 🚧 Not Implemented Yet

## Overview

This document describes the search architecture for OpenMates, including what content is searchable, user experience features, and the detailed technical implementation for privacy-preserving, offline-capable search functionality. The design maintains the zero-knowledge encryption model while providing fast, responsive search across thousands of messages.

---

## Search Scope

The search functionality searches with a low debounce time of 100ms after the user stops typing across:

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

### Auto Complete

When user types in search input, show instant auto complete suggestions based on the tags of the chats (filtered to remove duplicates).

### Search Quality Requirements

The search implementation should be **resilient to spelling mistakes** and typos. This means:
- Fuzzy matching should be implemented to handle common typos and misspellings
- Users should be able to find content even when their search query contains spelling errors
- The search algorithm should prioritize exact matches but still return relevant results for approximate matches

### Documentation Search

Documentation is included in the offline-first search via a compact search index generated at build time. The index contains:

- page titles
- summaries and excerpts
- keywords and tags
- clickable links to full documentation

This index is bundled with the web app during build, keeping it lightweight (a few KB) while enabling fast, fully offline search. When users click a result, they navigate to the docs web app (`docs.openmates.org`), which loads all documentation on first visit and then works offline regardless of which page is accessed.

If the user has previously visited the docs web app, all pages are cached by the PWA service worker and available offline. If they haven't visited before, they'll see a search result summary that links to the docs.

---

## Core Principle: Incremental Indexing + Encrypted Storage

**Don't rebuild on every message** - instead, maintain an incremental search index that updates only when new content arrives.

---

## Data Structure

### New IndexedDB Stores (2 additions):

#### 1. `search_index` store
```
- message_id (primary key)
- chat_id (indexed)
- encrypted_search_data (contains: tokens, preview snippet)
- created_at (indexed)
- metadata (role, has_attachments, word_count)
```

**Indexes**:
- `chat_id` - for filtering search by chat
- `created_at` - for date range queries
- `chat_id_created_at` - compound index for efficient chat + time queries

#### 2. `chat_search_metadata` store
```
- chat_id (primary key)
- encrypted_title_tokens
- message_count
- last_indexed_message_id
- indexed_at
```

---

## When Things Get Indexed

### Real-time (on message arrival):
1. New message saved to `messages` store
2. Immediately decrypt content with chat key
3. Generate search tokens (words, phrases)
4. Re-encrypt tokens with same chat key
5. Insert one record into `search_index`
6. Update `chat_search_metadata` counter

**Cost per message**: 1 decrypt + 1 encrypt + 2 IndexedDB writes (~5-10ms)

### Background (on app load or idle):
1. Check for unindexed messages (compare `messages` vs `search_index`)
2. Process in batches of 50 messages
3. Yield to UI thread between batches (requestIdleCallback)
4. Index only the 100 most recent chats
5. Mark completion in metadata store

**One-time cost**: Runs once per device, then maintains incrementally

---

## Search Flow

### User types query → Results appear:

#### 1. Query preparation (instant)
- Tokenize search terms
- Apply filters (date range, chat_id, role)

#### 2. Index scan (5-20ms for 10k messages)
- Query `search_index` store using IndexedDB indexes
- Filter by metadata first (no decryption needed)
- Get candidate message_ids

#### 3. Token matching (20-100ms in Web Worker)
- Decrypt `encrypted_search_data` for candidates
- Match tokens against query (exact matches prioritized)
- Apply fuzzy matching for typo tolerance (spelling mistake resilience)
- Score and rank matches (exact matches score higher than fuzzy matches)
- Return top 50 message_ids

#### 4. Result hydration (10-50ms)
- Fetch full Message objects from `messages` store
- Decrypt only the matched messages (not all messages!)
- Format for display with highlighted snippets

---

## Key Design Decisions

### Encryption Strategy
- **Search tokens encrypted with chat key** (not master key)
  - Maintains chat-level isolation
  - Server can never read search data
  - Survives page reload via IndexedDB

### Scope Limiting
- **Only index 100 most recent chats**
  - Covers 99% of user searches
  - Keeps index size manageable
  - Old chats fall back to slower on-demand search

### Performance Optimizations

#### Metadata-first filtering
- Check `has_content`, `role`, `created_at` before decryption
- Reduces decryption operations by 70-90%

#### Web Worker decryption
- Token matching happens off main thread
- UI stays responsive during search

#### Result pagination
- Decrypt top 20 matches first
- Load more on scroll (lazy decryption)

### Storage Efficiency
- **Token deduplication**
  - Store unique tokens per message, not full text
  - Average: 150 bytes per message vs 5KB full content
  - 10k messages = ~1.5MB search index

### Tokenization Strategy

#### Basic tokenization:
```
text.toLowerCase()
  .split(/\W+/)
  .filter(token => token.length > 2)
  .slice(0, 100) // Limit tokens per message
```

#### Considerations:
- Skip common stop words (the, a, an, is, etc.)
- Support multi-language tokenization
- Handle code snippets differently (preserve camelCase, snake_case)
- Extract hashtags and mentions as special tokens
- Consider n-gram indexing for partial word matching
- **Fuzzy matching for typo tolerance**: The search must be resilient to spelling mistakes (see Search Quality Requirements above)

---

## Maintenance Operations

### Index Pruning
- Delete search entries when message deleted
- Delete chat metadata when chat deleted
- Periodic cleanup of orphaned entries

### Re-indexing Triggers
- Chat key rotation (decrypt with old key, re-encrypt with new)
- Master key recovery (re-encrypt all chat keys, then search index)
- Schema version upgrade (rebuild index with new tokenization)

### Corruption Recovery
- If search fails, mark index as stale
- Background job rebuilds affected chat's index
- Graceful degradation: fall back to full-text scan

---

## Fallback Strategy

### For searches that miss the index:
1. User searches for term in old unindexed chat
2. System detects no results from index
3. Offer "Search older messages" button
4. On-demand: fetch chat messages, decrypt, scan
5. Optionally index that chat while searching

This keeps initial indexing fast while still supporting comprehensive search when needed.

---

## Performance Targets

- **Index update on new message**: < 10ms
- **Search 10k indexed messages**: < 100ms
- **Full result rendering**: < 200ms
- **Background indexing**: 50 messages/second (non-blocking)
- **Storage overhead**: ~150 bytes per indexed message

---

## Privacy Guarantees Maintained

✅ All search data encrypted at rest (chat key)
✅ No plaintext ever in IndexedDB
✅ Server never sees search index
✅ Chat isolation preserved (separate keys)
✅ Master key compromise doesn't expose search history directly
✅ Search queries never logged or sent to server

---

## Implementation Phases

### Phase 1: Basic Infrastructure
- Add new IndexedDB stores (`search_index`, `chat_search_metadata`)
- Implement basic tokenization
- Add index entry on new message save
- Simple keyword search (no ranking)

### Phase 2: Background Indexing
- Implement background indexing service
- Add `requestIdleCallback` batching
- Index 100 most recent chats on app load
- Progress indicator for indexing

### Phase 3: Advanced Search
- Move token matching to Web Worker
- Implement relevance ranking algorithm
- Add search filters (date, chat, role)
- Result highlighting and snippets
- **Implement fuzzy matching for typo tolerance** (core requirement)

### Phase 4: Optimization
- Implement metadata-first filtering
- Add result pagination
- Optimize tokenization for code/multi-language
- Performance monitoring and tuning

### Phase 5: Polish
- Fallback to on-demand search for old chats
- Index corruption recovery
- Search analytics (local only, privacy-preserving)
- User preferences (index scope, indexing schedule)

---

## Related Files

- `frontend/packages/ui/src/services/db.ts` - Main database service (IndexedDB operations)
- `frontend/packages/ui/src/services/cryptoService.ts` - Encryption/decryption utilities
- `frontend/packages/ui/src/types/chat.ts` - Chat and Message type definitions

---

## Security Considerations

### Threat Model
- **Attacker with IndexedDB access**: Cannot read search index (encrypted with chat keys)
- **Attacker with memory dump**: May see decrypted search results in memory (temporary)
- **Malicious browser extension**: Could intercept search queries (same risk as current message viewing)

### Mitigations
- Keep decrypted search results in memory for minimal time
- Clear search results when switching chats
- Consider memory encryption for high-security mode
- Regular security audits of search implementation

---

## Future Enhancements

### Advanced Features (Post-MVP)
- Enhanced fuzzy matching algorithms (beyond basic typo tolerance)
- Phrase search ("exact phrase")
- Boolean operators (AND, OR, NOT)
- Regular expression search
- Search within code blocks specifically
- Search by file attachments
- Search by date ranges with natural language ("last week", "this month")

**Note**: Basic fuzzy matching for typo tolerance is a core requirement (not a future enhancement) - see Search Quality Requirements above.

### AI-Powered Search
- Semantic search (meaning-based, not just keyword)
- Question answering over chat history
- Auto-suggest search queries
- Search result summarization

### Cross-Device Sync
- Sync search index across devices (encrypted)
- Differential sync to minimize bandwidth
- Conflict resolution for concurrent indexing

---

## Open Questions

1. **Should we index message edits/deletions?**
   - Track edit history in search?
   - Remove deleted messages from index immediately or with delay?

2. **How to handle very large messages?**
   - Truncate token extraction after N words?
   - Index only first paragraph?

3. **Should chat titles be indexed separately?**
   - Prioritize chat title matches vs message matches?
   - Separate search for "find chat by name"?

4. **Memory constraints on mobile?**
   - Smaller index scope (50 chats instead of 100)?
   - More aggressive cache eviction?