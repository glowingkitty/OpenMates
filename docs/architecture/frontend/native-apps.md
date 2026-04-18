---
status: in-progress
last_verified: 2026-04-17
key_files:
  - apple/project.yml
  - apple/OpenMates/Sources/App/OpenMatesApp.swift
  - apple/OpenMates/Sources/Core/Networking/APIClient.swift
  - apple/OpenMates/Sources/Core/Crypto/CryptoManager.swift
  - apple/OpenMates/Sources/Features/Auth/ViewModels/AuthManager.swift
  - frontend/packages/ui/src/tokens/generated/swift/
---

# Native Apps Architecture (Apple-First)

> OpenMates ships a fully native universal app across the Apple ecosystem —
> iPhone, iPad, Mac, and (later) an independent Apple Watch app and Apple
> Vision Pro — built with Swift 6 and SwiftUI. The native app lives in the
> monorepo under `apple/` and shares design tokens from the frontend pipeline.

## Why Native, Apple-First

The web app at `openmates.org` remains the primary surface and gets new
features first. Native apps exist to deliver a polished, high-trust
experience on devices where users expect deep OS integration:

- Keychain-backed E2EE key storage and iCloud Keychain sync
- Native push notifications (APNs), Live Activities, Widgets, Shortcuts
- Handoff between iPhone / iPad / Mac
- Face ID / Touch ID for hidden chats and sensitive actions
- Independent Apple Watch usage without a tethered iPhone (long-term goal)

We use SwiftUI as Apple's unified cross-device UI framework: one Xcode
project targets iOS, iPadOS, macOS, watchOS, and visionOS with 70-90%
shared code. This gives us multiple high-quality native clients from a
single codebase.

Android and other platforms are explicitly out of scope for this phase.

## Technology Choices

| Layer | Choice | Notes |
|---|---|---|
| Language | Swift 6 | Strict concurrency, memory safety |
| UI | SwiftUI | Declarative, adapts per platform |
| Persistence | SwiftData | Modern Core Data replacement |
| Networking | `URLSession` + `URLSessionWebSocketTask` | Native WebSockets for phased sync |
| Secrets | Keychain + iCloud Keychain | E2EE key storage + multi-device sync |
| Passkeys | `ASAuthorizationController` | Native Face ID / Touch ID auth |
| Build | Xcode multiplatform + XcodeGen | `project.yml` → `.xcodeproj` |

## Repository Layout (Monorepo)

The native app lives in the existing OpenMates monorepo under `apple/`.
Design tokens are generated from the same YAML sources as the web app
and imported directly into the Xcode project.

```
OpenMates/
├── apple/                              # Xcode project root
│   ├── project.yml                     # XcodeGen spec (generates .xcodeproj)
│   ├── .gitignore                      # Excludes .xcodeproj, build artifacts
│   └── OpenMates/
│       ├── Sources/
│       │   ├── App/                    # Entry point, RootView, MainAppView
│       │   ├── Core/
│       │   │   ├── Networking/         # APIClient, WebSocketManager
│       │   │   ├── Crypto/             # CryptoManager, KeychainHelper
│       │   │   ├── Persistence/        # SwiftData stores (TODO)
│       │   │   └── Models/             # AuthModels, ChatModels
│       │   ├── Features/
│       │   │   ├── Auth/               # Login flow views + AuthManager
│       │   │   ├── Chat/               # Chat list + chat view
│       │   │   └── Settings/           # Settings view
│       │   └── Shared/
│       │       ├── Components/         # OMButtonStyles, AppIconView
│       │       └── Extensions/         # Data, Color, ThemeManager
│       ├── Resources/                  # Info.plist, entitlements
│       ├── iOS/                        # iPhone/iPad-specific (future)
│       └── macOS/                      # Mac-specific (future)
├── frontend/
│   └── packages/ui/src/tokens/
│       ├── sources/*.yml               # Token source of truth
│       └── generated/swift/            # Auto-generated Swift files + xcassets
│           ├── ColorTokens.generated.swift
│           ├── TypographyTokens.generated.swift
│           ├── SpacingTokens.generated.swift
│           ├── GradientTokens.generated.swift
│           ├── IconMapping.generated.swift
│           ├── ComponentTokens.generated.swift
│           ├── Tokens.generated.swift
│           ├── Assets.xcassets/        # 18 theme-aware color sets
│           └── Icons.xcassets/         # 202 custom SVG icons
```

The `.xcodeproj` is git-ignored — regenerate with `cd apple && xcodegen generate`.
Platform-specific code uses `#if os(iOS)` / `#if os(macOS)` conditionals.

## Design Token Integration

The token pipeline (`pnpm --filter @repo/ui build:tokens`) generates Swift
outputs alongside CSS and TypeScript from the same YAML sources. The Xcode
project references these generated files directly — no manual copying.

Available in Swift code:
- `Color.grey0`, `Color.fontPrimary`, `Color.buttonPrimary` (18 theme-aware)
- `LinearGradient.appAi`, `.appHealth`, `.primary` (50+ app gradients)
- `Font.omH1` through `.omMicro` (12 typography scales with pt values)
- `CGFloat.spacing4`, `.radius3`, `.iconSizeMd` (spacing, radii, icon sizes)
- `Image.iconOpenmates`, `.iconChat`, `.iconAi` (202 custom icons)
- `SFSymbol.bell`, `.chevronLeft` (31 Lucide → SF Symbol mappings)
- `DS.SnippetCard`, `DS.LoadingText` (component primitives)

## Rollout Phases

### Phase 1: Login + Core Chat (iPhone MVP) — IN PROGRESS

**Scope:** Login → chat list → single chat → streaming AI responses.
Signup links to web app.

**Login flow (native SwiftUI):**
1. Email lookup (`EmailLookupView` → `/v1/auth/lookup`)
2. Password + 2FA (`PasswordLoginView` → `/v1/auth/login`)
3. Passkey (`PasskeyLoginView` → `ASAuthorizationController`)
4. Recovery key (`RecoveryKeyView` → `/v1/auth/login`)
5. Backup code (`BackupCodeView` → `/v1/auth/login`)
6. Device verification (`DeviceVerificationView` → `/v1/auth/2fa/verify/device`)

**Signup:** Opens `SFSafariViewController` → `openmates.org/signup`

**Chat:** `NavigationSplitView` with sidebar chat list + detail chat view.
Streaming responses via WebSocket. Message bubbles with user/assistant styling.

**Payment:** Links to web app for credit purchases.

### Phase 2: iPad + Mac Polish

Mostly layout — `NavigationSplitView` adapts automatically. Mac additions:
menu bar commands, keyboard shortcuts (`⌘N` new chat), window management.

### Phase 3: Native Signup (except payment)

Port all 13 signup steps to native SwiftUI. Passkeys will be better natively
(`ASAuthorizationController` vs WebAuthn JS). Payment step → SFSafariViewController
to web Stripe checkout, or Apple IAP as alternative payment method.

### Phase 4: watchOS + visionOS

Standalone watch app with voice-first interface. visionOS when there's demand.

## What Has to Be Ported From the Web App

In rough order of effort:

- **E2EE key lifecycle** — `ChatKeyManager` → Apple CryptoKit + Keychain +
  iCloud Keychain sync. See [core/client-side-encryption.md](../core/client-side-encryption.md).
- **Phased sync protocol** — 3-phase WebSocket sync →
  `URLSessionWebSocketTask`. See [data/sync.md](../data/sync.md).
- **Embed renderers** — 30+ embed types → SwiftUI equivalents for top 10,
  `WKWebView` fallback for the rest. Largest porting effort.
- **Markdown / message rendering** — inline embeds, code blocks, links.
- **PII protection** — client-side detection + placeholder rendering.

The backend is platform-agnostic and needs no changes.

## Development Workflow

- **Xcode runs only on macOS.** Contributors need a Mac (Apple Silicon recommended).
- **Paid Apple Developer Program** required for device testing, push, and distribution.
- **XcodeGen** keeps project config version-controlled: `cd apple && xcodegen generate`.
- **Design tokens** auto-update: run `pnpm --filter @repo/ui build:tokens` after
  editing YAML sources — Swift files regenerate alongside CSS/TS.
- **Signing & provisioning** managed through Xcode GUI and developer.apple.com.

## Out of Scope

- Android, Windows, and Linux native clients
- React Native / Flutter / Kotlin Multiplatform
- Catalyst (iPad app running on Mac) — we prefer a true macOS target
- Backend changes specific to native clients

## Related Docs

- [Web App](./web-app.md) — current primary client
- [Design Tokens](./design-tokens.md) — unified token system (web + native)
- [Sync](../data/sync.md) — phased WebSocket sync to port
- [Client-Side Encryption](../core/client-side-encryption.md) — E2EE to port
- [Master Key Lifecycle](../core/master-key-lifecycle.md) — Keychain mapping
- [Embeds](../messaging/embeds.md) — embed system to reimplement
