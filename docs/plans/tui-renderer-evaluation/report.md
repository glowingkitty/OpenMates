# TUI rendering evaluation — 2026-10-10

Recommendation: keep the optimized TypeScript TUI as the default. Continue the small Rust experiment only with incremental presentation updates and a concrete parity checklist. The measurements do not justify a full rewrite for performance alone.

## Implemented

- Private, bounded per-owner chat layout cache; account, Team, chat, width, content, aliases and embed changes invalidate it. Interactive content and pointer registrations remain live.
- Faster Markdown text runs and grapheme width calculation, preserving sanitization and Unicode behavior.
- Incremental ANSI row painting, latest-frame backpressure, cursor/selection handling, and full repaint on resize/resume. Mouse packets are ignored while output is blocked, including packets spanning a drain, so clicks cannot use undisplayed targets. Terminal proof readers now reconstruct incremental frames.
- Opt-in Ratatui/Crossterm developer prototype for chat history, composer, closed-by-default sidebar and embed carousel, with keyboard/mouse interaction and private fd3/fd4 presentation pipes. Existing TypeScript owns authentication, keys, sync and authority. The installed CLI does not launch Rust.

## Measurements

Synthetic alternating human/assistant messages include headings, bold text, wiki links, lists and code. Same Linux ARM64 Neoverse-N1 host, Node 24.20.0, 10 draft and 10 scroll samples per TypeScript workload. Baseline is published source `64c9ff539162308ce50ee0d03c1f7d438f7f0770`. The TypeScript column measures synchronous complete frame construction. ANSI output is counted separately. These are renderer measurements, not end-to-end user latency or network/sync benchmarks.

| History / viewport | TypeScript before, draft median | Optimized, draft median | Optimized cold frame | Prepared snapshot through Rust, median | Rust draw within bridge, median |
|---|---:|---:|---:|---:|---:|
| 100 / 160×50 | 1,210.6 ms | 5.1 ms | 64.4 ms | 3.0 ms | 1.0 ms |
| 500 / 160×50 | 5,832.5 ms | 10.7 ms | 291.0 ms | 13.1 ms | 1.3 ms |
| 500 / 240×70 | 5,768.4 ms | 8.5 ms | 309.1 ms | 12.8 ms | 1.8 ms |

At 160×50, average output per draft update falls from 11,914 to 266 bytes (97.8% less). Identical frames emit zero bytes. Scrolling still changes most visible rows: 11,918 → 8,833 bytes. Cold opening remains more expensive than typing; parsing 500 messages still takes hundreds of milliseconds.

The Rust bridge column includes JSON serialization, real private OS pipes, Rust parsing/projection/drawing, and acknowledgment. It **excludes initial TypeScript Markdown projection**, Node startup, actual terminal/SSH latency and input scheduling. Each 500-message update transfers approximately 0.5 MB. Native drawing is fast; full snapshots consume most of that advantage. Both use the same source text and prepared Markdown spans, but the prototype has fewer product features and a different chrome layout. Do not interpret these figures as a full-port speedup.

The first Rust bridge frame takes 6–21 ms after process launch with a prepared payload. Fresh full-history Markdown preparation in optimized TypeScript takes about 34 ms for 100 messages and 158–183 ms for 500, including fixture serialization/write. It must be cached or sent as message deltas before a hybrid renderer is useful.

Memory snapshots are exploratory: TypeScript benchmark RSS was 779 MiB before and 400 MiB after, with heap used 56 and 115 MiB respectively; isolated Rust renderer RSS was 3–8 MiB. These are process samples, not peak/retained-memory measurements or an equivalent full CLI comparison. Garbage collection and the much smaller Rust feature set prevent attributing those differences solely to the renderer language. A hybrid still retains the Node process.

A separate five-column 500-task board at 240×70 takes 128.1 ms before and 125.7 ms after per draft redraw (five warm samples). The chat cache does not cover this board, and all task cards are still constructed. This is a known next optimization target; the Rust prototype does not provide a comparable Kanban implementation. [Task measurements](tasks-benchmark.json).

Raw synthetic results: [baseline](typescript-baseline.json), [optimized](typescript-optimized.json), [private-pipe Rust](rust-bridge.json).

## Verification and limits

376 TypeScript TUI unit tests pass, including cache owner/content invalidation, Unicode/Markdown parity, fresh pointer targets, lifecycle, backpressure, resize and frame reconstruction. Rust: ten tests, formatting, Clippy with warnings denied, and release build pass. 57 recorder tests pass. Isolated rich-chat/pointer product checks accompany this change; final CI receipts and all recordings are delivered in the task chat.

Final isolated pointer proof passed on source `00f60522b09dc634eb7049c0573c008e5ba416e1` (GitHub run `38044628197`). The rich-chat proof on that source failed in both attempts because its saved-message request returned HTTP 503 before rendering assertions (run `38044625890`). The request code is unchanged by this renderer patch; the service failure's cause remains unresolved. All 30 available recordings from ten dispatched jobs were uploaded, including failures and retries. Final publication adds only ANSI-parser lint comments and this verification note to that source; no further product test rerun is claimed.

One isolated rich-chat attempt became signed out after accepting `/chat`; the same source loaded correctly on retry. Retained logs did not identify the invalidation cause. This is an unresolved authentication observation, not evidence that the renderer caused it. Earlier proof-tool failures and the scroll-viewport correction are retained with all recordings.

A later retained rich-chat recording loaded about 10.18 seconds after the open action, just beyond the recorder's default 10-second readiness deadline. Chat-open checkpoints use a bounded 30-second deadline while keeping every content assertion. That isolated cold-open observation includes SDK/cache/sync work and is separate from the synthetic renderer measurements above.

Package-wide `tsc --noEmit` is blocked by missing Svelte/UI dependencies in this older bound checkout; there are no diagnostics in the touched renderer, bridge or cache files. The CLI bundled build and generated type declarations succeed.

The Rust fixture and private-pipe modes were exercised in a real terminal/PTY. This is a renderer experiment, not a replacement CLI: no account operations, real message sends, offline synchronization, comprehensive embeds/settings/Team workflows, full composer editing, or accessibility parity are claimed. The presentation protocol bounds frames and rejects stale epochs/scopes; a future product integration must retain authoritative TypeScript action checks.

## Next steps

1. Ship the TypeScript optimizations and measure real input-to-paint, chat-open, resize, task-board and embed timings on macOS, tablet SSH and slower connections. Separate SDK initialization, disk, decryption and sync from drawing.
2. Improve cold opening by parsing visible history first and preparing older rows on demand; construct only visible Kanban task cards rather than the complete board on every input update. Keep selection, scroll anchors, live sync and owner fences correct.
3. If Rust still offers useful value, add message/layout deltas, a cached TypeScript projection, and bounded coalescing. Repeat the full parent-to-visible-frame comparison. Target whole-path latency and memory, not native draw timing alone.
4. Only then consider a staged renderer migration using the existing single `feature.terminal-ui@1` specification: composer editing, focus/mouse, Markdown/actions, embed previews/fullscreen, sidebar hierarchy, Tasks/Projects/Workflows, settings/Teams, offline/cache and cross-platform packaging. Keep one authoritative encrypted client rather than duplicating it in Rust prematurely.

## Reproduce

```sh
node --experimental-strip-types frontend/packages/openmates-cli/scripts/tui-render-benchmark.mjs --output /tmp/tui.json --fixtures /tmp/tui-fixtures
cargo build --release --manifest-path frontend/packages/openmates-tui-prototype/Cargo.toml
node frontend/packages/openmates-cli/scripts/tui-prototype-bridge-benchmark.mjs --fixtures /tmp/tui-fixtures --output /tmp/rust-bridge.json
node --experimental-strip-types frontend/packages/openmates-cli/scripts/ratatui-prototype.mjs
```

Use a current stable Rust toolchain and an interactive terminal for the demo. Benchmark fixtures are synthetic and never require an authenticated account. See the [prototype protocol and limitations](../../../frontend/packages/openmates-tui-prototype/README.md).
