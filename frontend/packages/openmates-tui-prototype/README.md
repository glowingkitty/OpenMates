# OpenMates Ratatui experiment

This is an isolated renderer prototype. The existing TypeScript CLI remains the owner of authentication, encryption, state, and network calls. The Rust process only receives a bounded presentation snapshot, renders it, and emits UI intents. The package is not wired into the default CLI or release packaging.

## Run

Use the local Rust toolchain or a current stable Rust toolchain (Ratatui requires Rust 1.88 or newer):

```sh
cargo run --release --manifest-path frontend/packages/openmates-tui-prototype/Cargo.toml -- --fixture frontend/packages/openmates-tui-prototype/fixtures/demo.json
cargo run --release --manifest-path frontend/packages/openmates-tui-prototype/Cargo.toml -- --benchmark frontend/packages/openmates-tui-prototype/fixtures/demo.json
```

The fixture mode opens the terminal with synthetic data. Press Ctrl+B for the initially closed sidebar, Tab to move focus, arrows to select chat, workspace row, or embed, Enter to activate/send, Alt+Enter for a draft newline, PageUp/PageDown or the mouse wheel to scroll, Esc to close/back, and Ctrl+C to exit. Click navigation, sidebar categories/chats, workspace rows, embeds, or the composer. Resizing redraws the layout. This experiment uses an append-only composer; selection, cursor editing, overlays, and broader terminal behavior remain TypeScript renderer features.

The synthetic TypeScript parent can also drive the private pipe bridge:

```sh
node --experimental-strip-types frontend/packages/openmates-cli/scripts/ratatui-prototype.mjs
```

Build the release binary first. Demo sends stay local in memory and do not contact an account or AI service. Benchmark commands and measured results are documented in `docs/plans/tui-renderer-evaluation/report.md`.

## Bridge v1

Launch `openmates-tui-prototype --bridge` with inherited fd 0 as the TTY for keyboard and mouse, fd 2 as the TTY for terminal drawing, fd 3 as a private parent-to-Rust JSONL pipe, and fd 4 as a private Rust-to-parent JSONL pipe. In Node this is `stdio: ['inherit', 'inherit', 'inherit', 'pipe', 'pipe']`. A snapshot on fd 3 must arrive before Rust enters the alternate screen. No credentials or secrets belong in arguments, snapshots, output, or persistent files. Do not bridge over a public TCP listener.

Snapshot wire shape:

```json
{"v":1,"type":"snapshot","epoch":1,"scope":"opaque-account:team:chat","state":{"view":"chats","sidebarOpen":false,"title":"Chat title","category":"travel","categories":[{"id":"travel","label":"Travel","color":"#32a4dd"}],"chats":[{"id":"chat-1","title":"Chat title","categoryId":"travel"}],"selectedChatId":"chat-1","messages":[{"id":"m1","role":"assistant","senderName":"Travel Mate","content":"fallback Markdown","lines":[{"spans":[{"text":"Heading","bold":true,"color":"#80caff"}]}],"embeds":[{"id":"e1","title":"Map","app":"maps","color":"#71bb8a"}]}],"draft":"","workspaceRows":[{"id":"task-1","label":"Task","detail":"Details","color":"#f29f4b"}]}}
```

`view` is one of `chats`, `apps`, `projects`, `workflows`, or `tasks`. A message `role` is `user` or `assistant`; optional `senderName` supplies the visible attribution for a remote person or named Mate. Without it, the header is `You` or `OpenMates`. `lines` takes precedence over `content`: the TypeScript projection should supply safe, already parsed Markdown spans for a fair renderer comparison. The fallback Rust Markdown parser only covers headings and `**bold**`; it does not implement the full TypeScript link, code, interactive question, or results view semantics. Colors are `#RRGGBB`; invalid colors use a fixed fallback. Strings are treated as data, with terminal controls stripped before drawing. Every frame is capped at 4 MiB, at 1,000 messages/chats/workspace rows, and at 8 KiB for the draft. Oversized or invalid frames are skipped. Rust drops snapshots unless their epoch strictly advances, including when the scope changes. The TypeScript parent owns the global epoch.

Each action is a JSON line on fd 4: `{"v":1,"type":"action","epoch":1,"scope":"opaque-account:team:chat","action":"open_chat","id":"chat-1"}`. Actions are `draft_changed` and `send_message` with `value`, `open_chat`, `open_embed`, `select_category`, `open_workspace`, and `open_workspace_item` with `id`, `set_sidebar` with `open`, and `back` without a payload. The parent must reject actions whose epoch or account/team/chat scope differs from the current state and must validate all IDs against its owned state. Rust's fence is only a first line of defense against stale snapshots; the TypeScript owner enforces the authoritative fence.

## Benchmark interpretation

`--benchmark FILE` reports averages over 20 cold, 20 unchanged warm, and 20 changed draft/scroll draws at 160×50 and 240×70. `coldAnsiBytes`, `warmAnsiBytes`, and `changedAnsiBytes` count actual bytes written by a `CrosstermBackend` through a counting writer. The `TestBackend` measurements exercise the same renderer without ANSI serialization and return a `testSnapshotHash` for repeatability. Cold creates a new terminal each draw; warm reuses one terminal, so terminal diffing can suppress unchanged output. Changed draws alternate the draft text and scroll position. The renderer projects the visible chat history and workspace rows; its window scan is included in the timing. The measurements include Rust's snapshot-to-widget projection and frame render; they exclude TypeScript projection, process launch, JSON serialization, bridge transfer, input handling, and real TTY latency. Compare these numbers with TypeScript draw-only measurements for the same typed snapshot. The fallback Markdown path is a different semantic workload from TypeScript's full parsed projection.

For the full bridge path, launch `--bridge-benchmark WIDTH HEIGHT` with the same private fd 3/4 pipes, no TTY needed. Send increasing-epoch v1 snapshots on fd 3. Each accepted snapshot returns `{"v":1,"type":"frame","epoch":2,"scope":"...","renderMicros":1234,"ansiBytes":5678,"width":160,"height":50}` on fd 4. This retains the terminal diff buffer between frames and skips stale/invalid snapshots. The parent's send-to-receipt clock includes TypeScript projection/serialization, IPC, Rust JSON parse, and render; `renderMicros` isolates Rust projection and draw. Use this alongside the native-only benchmark and visible terminal checks when deciding whether a port is justified.
