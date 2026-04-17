---
status: planned
last_verified: 2026-04-11
key_files: []
---

# Native Apps Architecture (Apple-First)

> OpenMates plans to ship fully native client apps across the Apple ecosystem —
> iPhone, iPad, Mac, and (eventually) an independent Apple Watch app — built
> with Swift and SwiftUI. This document captures the strategy, constraints, and
> rollout order. No native-app code exists yet; this is the plan of record.

## Why Native, Apple-First

The web app at `openmates.org` remains the primary surface and gets new
features first. Native apps exist to deliver a polished, high-trust
experience on devices where users expect deep OS integration:

- Keychain-backed E2EE key storage and iCloud Keychain sync
- Native push notifications (APNs), Live Activities, Widgets, Shortcuts
- Handoff between iPhone / iPad / Mac
- Face ID / Touch ID for hidden chats and sensitive actions
- Independent Apple Watch usage without a tethered iPhone (long-term goal)

We start with the Apple ecosystem because SwiftUI is Apple's unified
cross-device UI framework: one Xcode project can target iOS, iPadOS, macOS,
watchOS, tvOS, and visionOS with 70-90% shared code. This gives us four (or
more) high-quality native clients from a single codebase with a single team.

Android and other platforms are explicitly out of scope for this phase.

## Technology Choices

| Layer | Choice | Notes |
|---|---|---|
| Language | Swift 6 | Strict concurrency, memory safety |
| UI | SwiftUI | Declarative, adapts per platform |
| Persistence | SwiftData | Modern Core Data replacement |
| Networking | `URLSession` + `URLSessionWebSocketTask` | Native WebSockets for phased sync |
| Secrets | Keychain + iCloud Keychain | E2EE key storage + multi-device sync |
| IDE / Build | Xcode multiplatform app target | One project, many destinations |

## Repository Layout

The native apps live in a separate repository (`OpenMates-Apple`) to keep the
Swift project isolated from the web codebase and its tooling. The backend
(`backend/`) is platform-agnostic and is reused unchanged.

Inside the native repo the target layout is:

```
OpenMates-Apple/
├── Shared/              # 70-90% of the code
│   ├── Models/          # Mirrors backend Pydantic schemas
│   ├── Networking/      # API client + WebSocket phased-sync
│   ├── Crypto/          # E2EE key lifecycle (ports ChatKeyManager)
│   ├── Persistence/     # SwiftData stores
│   ├── ViewModels/
│   └── Views/           # Most SwiftUI views
├── iOS/                 # iPhone / iPad specifics
├── macOS/               # Menu bar, window management, keyboard shortcuts
└── watchOS/             # Watch-only UI, complications, background refresh
```

Platform-specific branches are handled with `#if os(iOS)` / `#if os(watchOS)`
conditionals or separate files, never with runtime checks.

## Rollout Order

1. **iPhone MVP** — auth, chat list, single chat, streaming AI responses,
   E2EE key management, phased sync, core embeds.
2. **iPad** — mostly layout adjustments via `NavigationSplitView` and size
   classes. Minimal new code.
3. **Mac** — menu bar, window management, keyboard-heavy workflows.
4. **Apple Watch (independent)** — standalone watch app that syncs directly
   with the backend over LTE / Wi-Fi, no iPhone required. This is the most
   specialized target and is saved for last because of constrained UI,
   battery, and connectivity edge cases.

Each step should ship to TestFlight before the next begins.

## What Has to Be Ported From the Web App

These are the subsystems that need Swift equivalents, in rough order of effort:

- **E2EE key lifecycle** — `ChatKeyManager` logic must be re-implemented
  against Apple Keychain + iCloud Keychain sync. See
  [core/client-side-encryption.md](../core/client-side-encryption.md) and
  [core/master-key-lifecycle.md](../core/master-key-lifecycle.md).
- **Phased sync protocol** — the 3-phase WebSocket sync in
  [data/sync.md](../data/sync.md) needs a native client.
- **Embed renderers** — 30+ embed types currently rendered by
  `UnifiedEmbedPreview.svelte` / `UnifiedEmbedFullscreen.svelte` need Swift
  equivalents. This is the single largest porting effort.
- **Markdown / TipTap rendering** — message rendering with inline embeds.
- **PII protection** — client-side detection + placeholder rendering.

The backend (FastAPI, Directus, providers) is platform-agnostic and needs
no changes to support native clients. Shared API contracts should be
generated from the existing Pydantic schemas to keep frontend/backend in sync.

## Development Workflow Constraints

Native Apple development has hard constraints that shape how work gets done:

- **Xcode runs only on macOS.** Any contributor working on native apps
  needs a Mac (Apple Silicon recommended).
- **A paid Apple Developer Program membership** is required for real device
  testing, Apple Watch development, push notifications, and distribution.
- **Apple Watch development requires a physical device pair** for meaningful
  testing. The watchOS simulator is limited.
- **Signing, provisioning, and capabilities** are managed through Xcode's
  GUI and `developer.apple.com`. These steps cannot be fully scripted.
- **Apps Connect submission** (screenshots, metadata, review) is a
  manual process that happens per platform.

Because of these constraints, the native repo has its own lint / CI /
release tooling separate from the web repo's `sessions.py` workflow.

## Fallback: WebView Shell

If fully native SwiftUI development turns out to be too much effort for the
team's capacity — especially porting the 30+ embed types — we keep a
fallback plan in reserve:

Wrap the existing SvelteKit web app in a native shell using `WKWebView`,
with native bridges for:

- Keychain-backed auth and E2EE keys
- APNs push notifications
- Face ID / Touch ID unlock
- Handoff and Universal Links
- Native file pickers and share sheets

This gets us "OpenMates on iPhone" in days instead of months and keeps the
web app as the single source of truth for all rendering. Individual screens
can be replaced with native SwiftUI over time where polish matters most.

This is explicitly a fallback, not the default plan. We go fully native
first and only drop to the WebView shell if we hit a wall.

## Out of Scope

- Android, Windows, and Linux native clients
- React Native / Flutter / Kotlin Multiplatform
- Catalyst (iPad app running on Mac) — we prefer a true macOS target
- Any backend changes specific to native clients

## Related Docs

- [Web App](./web-app.md) — current primary client
- [Sync](../data/sync.md) — phased WebSocket sync to port
- [Client-Side Encryption](../core/client-side-encryption.md) — E2EE to port
- [Master Key Lifecycle](../core/master-key-lifecycle.md) — Keychain mapping
- [Embeds](../messaging/embeds.md) — embed system to reimplement
