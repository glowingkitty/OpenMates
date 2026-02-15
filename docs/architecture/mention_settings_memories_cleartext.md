# Settings & Memories in @ Mention: Cleartext and Dropdown

> **Status**: Proposed (for your confirmation)
> **Last Updated**: 2025-02-15

Proposed architecture so that (1) settings/memories **can be searched and selected** in the @ dropdown (when the user types a query), and (2) when the user **submits** a message that includes a settings/memory mention, the backend receives cleartext and does not request the same category again during that request.

**Scope:** The **default** dropdown when the user types only `@` (no query) **does not change** — it remains the current 4 AI models. Changes apply only to **search** (what can be found and selected when the user types) and to **submit** (cleartext + backend behaviour).

---

## Current state

### Dropdown (MentionDropdown + mentionSearchService)

- **Empty query (`@` only):** Unchanged — `getDefaultMentionResults()` returns only 4 AI models.
- **With query:** `getAllMentionResults()` already includes **settings_memory** categories and **settings_memory_entry** (individual entries). With `limit = 4`, other types (models, mates, skills) often outscore them, so settings/memories and individual entries are hard to find. Search for individual items (e.g. “React”, “Trips”) can be crowded out.

### Send path (content and metadata)

- Message content is serialized to markdown; generic mentions become `mentionSyntax` (e.g. `@memory:travel:trips:list`, `@memory-entry:code:preferred_technologies:entry-uuid`). That string is sent in `message.content`.
- Client also sends `app_settings_memories_metadata`: list of keys in `"app_id-item_type"` format (what categories exist on device, **no content**). Backend uses this so the preprocessor knows which settings/memories are available.

### Backend (preprocessor + main processor)

- **Override parser** already parses `@memory:...` and `@memory-entry:...` into `UserOverrides.memory_categories` and `UserOverrides.memory_entries`. These are **not** currently used to inject cleartext or to avoid requesting.
- **Preprocessor** LLM returns `load_app_settings_and_memories` (e.g. `["travel:trips", "code:preferred_technologies"]`). Validation uses `user_app_settings_and_memories_metadata` (from client metadata).
- **Main processor** uses `load_app_settings_and_memories` to:
  - Read from cache (vault-encrypted, then decrypted server-side), or
  - Create an app_settings_memories request and wait for user permission (no LLM reply until next turn).

So: backend **never** receives decrypted settings/memories content from the client for the **current** message; it either uses cache from a previous permission or triggers a new permission request. When the user **explicitly** mentions e.g. @Travel-Trips, we want the backend to get that content in the same request and **not** request that category again.

---

## Proposed architecture

### 1. Dropdown: make settings/memories searchable and selectable (default unchanged)

**Goal**

- **Default stays as-is:** When the user types only `@` with no query, the dropdown continues to show the same default (e.g. 4 AI models). No change to `getDefaultMentionResults()`.
- **Search and selection:** When the user types a query (e.g. “Travel”, “Code”, “Trips”, “React”), settings/memory **categories** (e.g. Travel-Trips, Code-FavoriteTechnologies) and **individual entries** must be **in the searchable set** and **selectable** — i.e. they can appear in results and be chosen. Today they are in the pool but are often crowded out by the small result limit and scoring.

**Implementation**

- Ensure the search pool continues to include settings_memory and settings_memory_entry (already the case via `getAllMentionResults()`).
- Increase the result **limit** for `searchMentions` when there is a query (e.g. 6–8 instead of 4) and/or apply a small **score boost** for `settings_memory` and `settings_memory_entry` when the query matches their search terms, so that “Travel”, “Code”, “React”, “Trips”, etc. reliably surface settings/memories and individual entries. No change to what is shown when the query is empty.

### 2. Send payload: include cleartext for mentioned settings/memories

**Idea**

- When building the Phase 1 send payload, **parse the outgoing message content** (the same markdown we send, which already contains `@memory:...` and `@memory-entry:...`) for these patterns.
- For each **category** mention (`@memory:app_id:memory_id:type`): resolve the **full decrypted content** for that category from the client store (e.g. `appSettingsMemoriesStore` / decrypted entries for that `app_id` + `memory_id`).
- For each **entry** mention (`@memory-entry:app_id:category_id:entry_id`): resolve the **single entry’s decrypted content** (one item in the same shape the backend expects for that category, or a minimal representation the backend can inject).
- Add a new payload field, e.g. **`mentioned_settings_memories_cleartext`**, as a map:
  - **Key:** `app_id:item_key` (category key; backend already uses this format for cache and `load_app_settings_and_memories`).
  - **Value:** Decrypted content for that category (full list for category mention; for a single entry mention, either a list of one item or an agreed single-entry shape).

So the backend receives, in one request, both:

- `message.content` (with `@memory:...` / `@memory-entry:...` in text), and  
- `mentioned_settings_memories_cleartext`: `{ "travel:trips": [...], "code:preferred_technologies": [...] }` (or similar) for every mentioned category/entry.

**Client implementation notes**

- Reuse the same semantics as backend `override_parser` (e.g. regex or shared pattern) so keys and parsing stay in sync. Key format: **colon-separated** `app_id:item_key` to match backend cache/request keys.
- Resolve cleartext only from already-decrypted client store (no extra decryption path). If a category/entry is missing (e.g. deleted after composing), send nothing for that key; backend will fall back to cache/request for that key if the LLM still asks for it.
- Single-entry mention: backend can treat value as “content for this category for this message” (e.g. list of one entry). No need for a separate key format for “entry-only” as long as the value is valid for the existing “category content” shape.

### 3. Backend: use cleartext and do not re-request

**Main processor (and optionally preprocessor)**

- **New request field:** Add `mentioned_settings_memories_cleartext: Optional[Dict[str, Any]]` to the ask-skill request (or equivalent) and pass it through to the main processor.
- **When loading app settings/memories:**
  1. Initialize `loaded_app_settings_and_memories_content` from `request.mentioned_settings_memories_cleartext` (if present). Keys are `app_id:item_key`; values are the cleartext (list or dict) for that category.
  2. For each key in `preprocessing_results.load_app_settings_and_memories`:
     - If the key is **already** in `loaded_app_settings_and_memories_content` (from client), **skip** cache lookup and **skip** creating an app_settings_memories request for that key.
     - Otherwise, keep current behavior: read from cache or create permission request for missing keys.
  3. Build the system-prompt “Relevant Information from Your App Settings and Memories” section from `loaded_app_settings_and_memories_content` as today (so client-provided cleartext is used the same way as cache-decrypted content).

Result: for any category the user explicitly mentioned, the backend gets cleartext in the same request and **does not** attempt to request that category again during this chat message processing.

**Optional preprocessor improvement**

- Pass `user_overrides.memory_categories` / `memory_entries` (or the set of keys derived from them, e.g. `travel:trips`) into the preprocessor so the LLM is told “user already included these categories in the message.” Then the preprocessor can include those keys in `load_app_settings_and_memories` (so the main processor has a key to fill from cleartext) without the LLM having to “guess” from the raw message text. Alternatively, main processor can merge “keys from user_overrides” into the set of keys to consider for loading; for any key in `mentioned_settings_memories_cleartext`, it still must not request again.

### 4. Summary of changes

| Layer | Change |
|-------|--------|
| **MentionDropdown / mentionSearchService** | **Default unchanged.** With a query: increase search limit and/or score boost so settings/memory categories and individual entries can appear and be selected. |
| **Send payload (chatSyncServiceSenders)** | Parse message content for `@memory:...` and `@memory-entry:...`; resolve decrypted content from client store; add `mentioned_settings_memories_cleartext` to payload. |
| **Backend ask-skill request** | New optional field: `mentioned_settings_memories_cleartext: Optional[Dict[str, Any]]`. |
| **Backend main processor** | Fill `loaded_app_settings_and_memories_content` from `mentioned_settings_memories_cleartext` first; for keys already present, do not request from cache or create permission request. |
| **Backend (optional)** | Use `user_overrides.memory_categories` / `memory_entries` so that user-mentioned categories are in the load list and filled from cleartext. |

---

## Security / privacy

- Cleartext is sent only for categories/entries the **user explicitly mentioned** in the message (same as override syntax). No extra categories are sent.
- Transport remains as today (e.g. over existing secure channel). No new key material.

---

## Open decisions (for you to confirm)

1. **Single-entry value shape:** For `@memory-entry:app_id:cat_id:entry_id`, should `mentioned_settings_memories_cleartext[app_id:cat_id]` be exactly “list of one entry” (same schema as full category) or a different structure? Recommendation: list of one entry for simplicity.
2. **Preprocessor:** Should we explicitly pass user-mentioned memory keys into the preprocessor so `load_app_settings_and_memories` always includes them, or rely on main processor to merge user_overrides + cleartext and only avoid re-request?

Once you confirm or correct these, implementation can follow this architecture.
