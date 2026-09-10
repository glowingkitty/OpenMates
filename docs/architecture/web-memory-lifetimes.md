# Web memory lifetimes

Imperative embed renderers mount independent Svelte roots. Removing their HTML
or destroying a TipTap node does not automatically unmount those roots. Use
`mountedEmbedLifecycle` for renderer mount/unmount calls, dispose the subtree
before replacing its HTML, and dispose its owner when the message is destroyed.
Register external retry subscriptions through `onEmbedCleanup`. Disposed targets
reject late asynchronous mounts. Ordinary Svelte child components retain normal
Svelte ownership.

Image and audio/video helpers share in-flight fetch/decryption. Components own
one reference per media key, including repeated reactive loads, and release all
references on destruction. Image displays use the cache's URL instead of making
a second URL for the same Blob. Unused images expire after 30 seconds and unused
audio/video after 60 seconds. Payload budgets (64 MiB images, 128 MiB audio/video)
can evict unused media earlier; media actively displayed or playing is protected.
The grace periods preserve quick reopening without network or decryption waits.

Recoverable embed entries use a 64 MiB / 2,000 entry LRU. Memory-only entries and
pending/failed IndexedDB writes are pinned: only successful transaction completion
makes that exact entry evictable. IndexedDB remains the source for evicted entries.
Processed message content has a 32 MiB / 100 entry budget; large entries skip the
extra cache clone. Budgets estimate retained payload, not total browser heap.

The plaintext search index has a 32 MiB / 500 chat budget. Warm-up and foreground
queries share at most five concurrent indexing jobs. Searches examine evicted
chats directly and retain their result snippets, so eviction does not remove
matches. Initial warm-up shows cached/title matches first and refreshes the active
query when complete. Superseded/closed queries stop between chats and cannot
replace newer results. Logout invalidates in-flight index writes and clears the
plaintext index and parsed-content cache.

These budgets bound caches, not active content or the only unsaved copy of data.
Do not evict unsaved data, interrupt active playback, disable animations, or add
arbitrary navigation delays to meet a memory target. Browser heap and live DOM /
listener counts after repeated equivalent navigation and garbage collection are
the useful leak indicators; process RSS alone includes graphics and allocator
high-water marks. Linux WebKit is not a reproduction of macOS Safari process RSS.
