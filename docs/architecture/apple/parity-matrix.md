# Apple/Web Parity Matrix

Status: initial audit scaffold  
Created: 2026-06-01  
Owner: Apple/web parity work

## Goal

The web app is the source of truth for OpenMates product UI and user-facing behavior. The Apple app should match that product experience one-to-one where OpenMates owns the UI, while still using idiomatic SwiftUI/UIKit boundaries where native platform APIs are the correct product contract.

This document tracks parity at the product-surface level, not at the file level. A web Svelte/TypeScript surface may map to one Swift file, several Swift files, or a shared Swift primitive.

## Source Of Truth

- Canonical counterpart map: `apple/SVELTE_SWIFT_COUNTERPARTS.md`
- Apple UI task baseline: `docs/architecture/frontend/apple-ui-redesign-task.md`
- Generated inventory: `test-results/apple-parity-inventory.json`
- Inventory script: `scripts/apple_parity_audit.py`
- Apple app rules: `apple/AGENTS.md`
- Web components: `frontend/packages/ui/src/components/`
- Web routes: `frontend/apps/web_app/src/routes/`
- Web tests: `frontend/apps/web_app/tests/**/*.spec.ts`
- Web styles: `frontend/packages/ui/src/styles/`
- Generated Swift tokens: `frontend/packages/ui/src/tokens/generated/swift/`
- Apple product UI: `apple/OpenMates/Sources/App/`, `apple/OpenMates/Sources/Features/`, `apple/OpenMates/Sources/Shared/Components/`

## Initial Automated Inventory

These counts are a first snapshot from the repo on 2026-06-01. They should be regenerated after we add a script for this matrix.

| Signal | Count | Meaning |
| --- | ---: | --- |
| Web Svelte components | 430 | Broad web component source surface |
| Web Svelte route files | 59 | Public/app route surface |
| Web Playwright specs | 148 | Existing web behavior coverage |
| Unique web `data-testid` values used by specs | 455 | Behavior/testability surface exposed by web flows |
| Apple `Features/**/*.swift` files | 107 | Existing native feature implementation surface |
| Apple `App/**/*.swift` files | 4 | Existing native app shell surface |
| Unique Apple `.accessibilityIdentifier(...)` values | 23 | Native testability surface currently exposed |
| Shared web/Apple IDs | 6 | Direct selector overlap usable for parity checks today |

Current shared IDs:

- `chat-item-wrapper`
- `embed-minimize`
- `embed-preview`
- `password-input`
- `search-button`
- `sidebar-toggle`

Current Apple accessibility identifiers:

- `chat-history-panel`
- `chat-item-wrapper`
- `continue-button`
- `dev-embed-preview-gallery`
- `dev-preview-app-\(app.rawValue)`
- `dev-preview-display-\(title)`
- `dev-preview-skill-\(skill.id)`
- `email-input`
- `embed-minimize`
- `embed-preview`
- `login-button`
- `login-signup-button`
- `pair-copy-link-button`
- `pair-pin-input`
- `pair-refresh-button`
- `password-input`
- `search-button`
- `settings-button`
- `sidebar-toggle`
- `stay-logged-in-toggle`
- `tfa-code-input`
- `welcome-message-input`
- `welcome-send-button`

## Findings From Initial Inventory

- Apple has substantially less explicit UI-test surface than web: 23 unique accessibility identifiers versus 455 unique web test IDs used by specs.
- The existing counterpart map covers the most important product surfaces, but it is hand-maintained and does not yet prove that all web source files or tested flows have Apple equivalents.
- The web test selector inventory is a strong input for behavior parity, but not enough for visual parity. Screenshot comparison and token/style checks are required separately.
- Apple needs a testability pass before reliable Apple UI tests can mirror web flows. Important controls should expose stable `.accessibilityIdentifier(...)` values, preferably aligned with web `data-testid` names when the product concept is the same.

## Parity Workflow

Use this workflow for each product surface.

1. Read the web source files and styles listed in `apple/SVELTE_SWIFT_COUNTERPARTS.md`.
2. Read the Apple counterpart files.
3. Extract web test IDs and user flows from relevant Playwright specs.
4. Check Apple identifiers and view accessibility for equivalent controls/states.
5. Compare behavior states: loading, empty, error, focused, disabled, selected, offline, syncing, streaming.
6. Compare design states: layout, spacing, typography, color tokens, radius, shadows, icons, animation, dark mode.
7. Mark the surface as `Missing`, `Partial`, `Visual Gap`, `Functional Gap`, `Testability Gap`, or `Parity Candidate`.
8. Create implementation tasks with web source, Apple target, acceptance criteria, and verification steps.

## Surface Matrix

| Surface | Web Source | Apple Source | Web Coverage Signals | Current Status | Next Audit Task |
| --- | --- | --- | --- | --- | --- |
| App shell and navigation | `+page.svelte`, `Header.svelte`, `ChatHistory.svelte` | `MainAppView.swift`, `RootView.swift`, `ChatListRow.swift` | `sidebar-toggle`, `profile-container`, `settings-menu`, `header-login-signup-btn`, navigation specs | Partial; known visual parity risk | Audit header/sidebar/mobile shell screenshots and align identifiers |
| Chat list/sidebar | `ChatHistory.svelte`, `components/chats/Chat.svelte` | `MainAppView.swift`, `ChatListRow.swift` | `chat-history`, `chat-item-wrapper`, `chat-item`, `group-title`, `unread-badge`, sub-chat IDs | Partial; only `chat-item-wrapper` overlaps | Add Apple identifiers for groups, unread state, active state, context actions |
| Chat transcript and message bubbles | `ChatMessage.svelte`, `RichMarkdownRenderer.svelte`, `chat.css`, `mates.css` | `ChatView.swift`, `RichMarkdownRenderer.swift`, embed renderers | `message-user`, `mate-message-content`, `user-message-content`, `mate-profile`, `chat-mate-name`, embed IDs | Partial; visual parity needs screenshot proof | Audit bubble tail, avatar, markdown, generated-by/report actions, highlights |
| Message input/composer | `MessageInput.svelte`, `ActionButtons.svelte`, `RecordAudio.svelte`, `fields.css` | `ChatView.swift`, `InputActionButtons.swift`, `AttachmentPicker.swift`, `VoiceRecordingView.swift` | `message-editor`, attachment/audio/PDF tests, paste classification, PII specs | Partial; Apple has `welcome-message-input` but not main `message-editor` | Align composer identifiers and verify focused/disabled/attachment states |
| Chat management | `ChatContextMenu.svelte`, chat stores, settings entry points | `ChatContextMenu.swift`, `MessageContextMenu.swift`, `ChatViewModel.swift` | `chat-context-delete`, pin/unpin/hide/mark-read IDs, `chat-management-flow.spec.ts` | Partial or unknown | Map every context action to Apple affordance and identifier |
| Search | `ChatSearch.svelte`, header search controls | `ChatSearchView.swift`, `MainAppView.swift` | `search-button`, chat search specs | Parity candidate for entry point; unknown detail parity | Audit search results, empty state, keyboard focus, mobile dismissal |
| Auth login/signup/recovery | login routes, `Signup.svelte`, recovery components | `AuthFlowView.swift`, `EmailLookupView.swift`, `PasswordLoginView.swift`, `PasskeyLoginView.swift`, `SignupFlowView.swift`, recovery views | passkey, backup code, recovery key, signup specs; `email-input`, `password-input`, `tfa-input`, `auth-btn` | Partial; some identifier overlap | Add missing auth modal/step identifiers and audit flows against specs |
| Settings main and sub-pages | `settings/**/*.svelte`, `settings/elements/*.svelte`, `settings.css` | `SettingsView.swift`, `SettingsSubPages.swift`, settings feature views, `OMDesignPrimitives.swift` | many settings specs and generic IDs like `primary-button`, `success-message`, `save-container` | Partial; likely largest testability gap | Audit page-by-page; enforce canonical Apple primitives and identifiers |
| Billing/payments | `Payment.svelte`, pricing/support settings | `SettingsBillingView.swift`, `SettingsPricingView.swift`, `StoreManager.swift` | Stripe/bank transfer/buy credits specs | Partial or platform-specific | Separate native IAP/StoreKit requirements from web billing parity |
| Embeds preview/fullscreen | `embeds/UnifiedEmbedPreview.svelte`, `UnifiedEmbedFullscreen.svelte`, renderers | `EmbedPreviewCard.swift`, `EmbedContentView.swift`, `EmbedFullscreenView.swift`, renderer files | `embed-preview`, `embed-minimize`, skill/embed specs | Partial; good source/target structure exists | Audit every embed type in specs against Apple renderer support |
| Skills outputs | app/skill Svelte embed components and backend payload schemas | `Features/Embeds/Renderers/*`, `Core/Intents/Skills/*` | `skill-*.spec.ts`, `demo-chat-embeds.spec.ts`, `cli-skills-pdf.spec.ts` | Partial | Generate embed-type matrix from web skill specs and Apple renderers |
| Projects | `routes/projects/+page.svelte`, project components | No obvious Apple feature surface in current counterpart map | `projects-flow.spec.ts` with project IDs | Missing or intentionally web-only | Decide if Projects is required on Apple; if yes create native spec |
| Interactive questions | `interactive_questions/**/*.svelte` | No obvious Apple counterpart in current map | `interactive-questions.spec.ts` | Unknown/missing | Decide native UX and map renderers if required |
| Daily inspiration | `DailyInspirationBanner.svelte`, `DailyInspiration.svelte` | `DailyInspirationView.swift`, intents/widgets data | daily inspiration specs | Partial | Audit banner/card/video states and widget/native differences |
| Reminders | reminder components and settings | `ReminderView.swift`, `ReminderIntents.swift` | reminder specs | Partial | Audit creation, repeat, cancel, settings affordances |
| Incognito/focus modes | `IncognitoMode.svelte`, `FocusModeSelector.svelte` | `IncognitoMode.swift`, `FocusModeView.swift` | incognito/focus specs | Partial | Audit active banners, mention/focus flows, privacy states |
| Sharing/import/public chats | share routes, public chat components, import components | `ChatShareView.swift`, `ChatImportView.swift`, `PublicChatListView.swift`, `LegalChatView.swift` | share/import/shared-chat specs | Partial | Audit native share sheet boundaries and public read-only UI parity |
| Offline/sync/resilience | web sync stores, banners, chat sync service UI | `SyncManager.swift`, `OfflineStore.swift`, `OfflineSyncBridge.swift`, banners | startup sync, message sync, connection resilience specs | Functional risk | Audit cold boot, empty IndexedDB equivalent, offline queues, banners |
| Developer/dev preview | dev preview routes | `DevEmbedPreviewGalleryView.swift` | `dev-preview.spec.ts`, embed preview specs | Partial | Keep as internal validation harness; not product parity priority |

## Vertical Slice Specs

- `docs/architecture/apple/sync-parity.md`
- `docs/architecture/apple/message-processing-parity.md`
- `docs/architecture/apple/streaming-parity.md`
- `docs/architecture/apple/notifications-parity.md`

## Status Definitions

- `Missing`: no Apple surface is mapped or obvious.
- `Partial`: an Apple surface exists but behavior, design, identifiers, or tests are incomplete.
- `Visual Gap`: behavior may exist, but screenshots/tokens/layout do not match web.
- `Functional Gap`: design may exist, but user flow or state behavior is incomplete.
- `Testability Gap`: behavior may exist, but Apple has no stable identifiers/tests to prove it.
- `Parity Candidate`: initial code structure and identifiers exist; needs screenshot/test verification before marking done.

## Task Template

```md
Task: <surface> Apple/web parity

Web source:
- <Svelte/CSS/TS files>

Apple target:
- <Swift files>

Observed gap:
- <missing behavior, visual mismatch, or missing identifier>

Acceptance criteria:
- <specific state/flow/design proof>

Verification:
- Build Apple app
- Capture simulator screenshot in relevant form factors
- Compare against web reference screenshot
- Run/add Apple UI test for equivalent flow
```

## Next Automation

Create a script that regenerates this inventory and writes machine-readable output, for example `scripts/apple_parity_audit.py` producing `test-results/apple-parity-inventory.json`. The script should extract:

- Unique web test IDs by spec file
- Unique Apple accessibility identifiers by Swift file
- IDs shared by web and Apple
- Web test IDs with no Apple equivalent
- Apple identifiers unused by web specs
- Svelte files listed in `apple/SVELTE_SWIFT_COUNTERPARTS.md`
- Swift files listed in `apple/SVELTE_SWIFT_COUNTERPARTS.md`
- Counterpart paths that no longer exist

The script should not decide product priority. It should only produce facts for this matrix.
