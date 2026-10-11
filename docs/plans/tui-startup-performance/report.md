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

The public chat-home `/refresh` now updates in place, preserving the selected card,
composer draft and route. It previously rerouted after loading, reset selection
and started a redundant second sync. The isolated recording found this path; a
focused interaction regression fails before the fix and passes with it.


The terminal composer now opens a web-aligned `@` picker using available live model routes, Mates, app skills, focus modes, Projects, populated memory categories and entries, and Wikipedia. The private catalog loads lazily through the existing encrypted account/Team-scoped cache; keystroke filtering and animation ticks do not refetch it. Only selecting a Project fetches that Project’s current write mode; failures fall back to read access. Already cached Project folders/files can be suggested without enumerating remote files while typing. Enter/Tab and click select without sending, model suggestions use the existing encrypted model preference service, and delayed work is fenced against owner, route and draft changes. Wikipedia searches are debounced and limited to five results.
