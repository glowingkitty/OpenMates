---
status: planned
last_verified: 2026-03-24
key_files: []
---

# Client-Side Vector Search for Personalization

> Planned feature: privacy-preserving personalization via client-side semantic matching of user interests against message tags, with only relevant interests sent to the backend.

## Why This Exists

Personalization typically requires server-side user profiles, which conflicts with OpenMates' privacy-first design. Client-side vector search keeps the full interest profile on-device and shares only contextually relevant tags per request.

## How It Works (Planned)

### Setup Phase

During onboarding, the user selects interest topics. These are converted to vector embeddings and stored locally (IndexedDB or SQLite-WASM). No data leaves the device.

### Message Processing

1. User sends a message.
2. Server preprocessing returns semantic tags for the message.
3. Client performs local vector similarity search against stored interest embeddings.
4. Top-N relevant interests sent to backend as plain text with the inference request.

### Technology Options

| Component    | Candidates                              |
|-------------|------------------------------------------|
| Embeddings  | text-embedding-3-small, MiniLM-L6-v2    |
| Vector Store| hnswlib-wasm, vectordb, SQLite-VSS       |
| Storage     | IndexedDB, WASM SQLite                   |

### Privacy Properties

- No server-side storage of interests or embeddings.
- Only minimal relevant metadata sent per request.
- Cannot reconstruct full user profile from individual requests.
- GDPR-friendly: no profiling, no tracking.

### Performance

Client-side vector search: <10ms for <10,000 interests. No network overhead for personalization logic.

## Future

- Encrypted local backups for cross-device interest sync.
- Model versioning to prevent embedding drift.
- Local embedding generation via transformers.js for full offline mode.

## Related Docs

- [Learning Mode](../ai/learning-mode.md) -- related personalization concept
