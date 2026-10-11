# Terminal cache startup performance

TASK-5386, session 8a64. TypeScript CLI only; no web/backend changes.

The benchmark uses a disposable synthetic encrypted cache: 500 chat metadata rows,
500 messages and 10,000 embed records, five samples, median, Node 24 on Linux ARM64.
It includes local ciphertext file read and decryption, excluding terminal paint,
module import, login, background sync, network and AI inference. Before uses the
installed 0.27.0-alpha.53 SDK; after uses this source's compiled SDK.

| Operation | Before first / complete | After first / complete |
| --- | ---: | ---: |
| Recent workspace previews | 454 / 454 ms | 19 / 155 ms |
| Recent chat messages | 681 / 681 ms | 42 / 158 ms |

Run `node scripts/tui-startup-benchmark.mjs --module /absolute/sdk/dist/index.js --output /private/result.json`.
Raw measurements and import counts are in `benchmark.json`; these are local fixture
measurements, not end-to-end macOS claims.

Keys are imported as nonextractable, decrypt-only WebCrypto keys local to each
operation. No process-wide plaintext/key cache or disk format change. Eight-row
batches retain canonical ordering. The first 32 previews and newest 100 cached
messages are published early; older entries remain available. Warm refresh keeps
the visible full inventory until the replacement is complete, preserving selection. Account, Team,
master-key and cancellation checks fence publication; unauthorized Team cache
reads still require local authorized keys. Embed lookup changes from repeated
full scans to a per-operation hashed-message index.

Coverage checks cold/unsorted caches, field preservation, invalid ciphertext and
AAD, nonextractability/import counts, owner changes with the same key, Team/key
switches, cancellation, unauthorized Team keys, network window ordering and draft
preservation. The synthetic terminal recording verifies the actual local SDK and
TUI without claiming server/auth timing. The authenticated rich-chat recording
also checks returning home and reopening while offline.
