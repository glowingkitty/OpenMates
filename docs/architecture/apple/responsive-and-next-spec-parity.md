# Apple Responsive And Web Spec Parity Plan

Status: active  
Last updated: 2026-06-09

## Current Simulator Coverage

- `ChatResponsiveParityUITests` runs the debug-only seeded chat preview and checks that native breakpoint decisions match the web-mapped chat thresholds.
- Verified on iPhone 17 simulator: `chat-width=402`, compact chat state, assistant stacked at `<=500`, inline new-chat compact at `<=550`.
- Verified on iPad Pro 13-inch (M5) simulator: `chat-width=1032`, regular chat state, assistant not stacked, inline new-chat not compact.
- `ChatOpeningScalabilityUITests` covers large seeded chat opening on simulator without rendering the full history.
- `ChatFlowParityUITests` covers deterministic seeded chat hierarchy and no default table chrome.
- `MessageInputAttachmentUITests` covers simulator-safe pending attachment structure.
- `MessageInputAudioRecordingUITests` covers simulator-safe record button and recording overlay structure.

## Current Responsive Testing Gaps

- No automated Apple test resizes macOS windows from small to fullscreen.
- No automated Apple test currently runs the macOS target for app shell parity.
- No automated shell-level responsive test proves compact sidebar drawer behavior versus regular side-by-side panel behavior.
- No responsive coverage exists yet for settings pages, auth screens, embed fullscreen, search, chat context menus, or public/demo chat cards.
- Visual/pixel checks are still warning-only; current tests prove structural/testability and breakpoint decisions, not exact screenshot equality.

## Recommended Web Specs To Reproduce Next In Apple

1. `chat-flow.spec.ts`
   - Apple target: `ChatFlowParityUITests`, `ChatFlowRealAccountUITests`, new seeded transcript/header contract test.
   - Why: It is the core product path and already maps to native chat opening and real-account tests.
   - Next native assertions: `message-user`, `message-assistant`, `chat-header-title`, `chat-header-icon`, active `chat-item-wrapper`, sidebar closed/open behavior, reload persistence where simulator-safe.

2. `chat-management-flow.spec.ts`
   - Apple target: new `ChatManagementParityUITests` backed by seeded chats.
   - Why: Pin/unpin, unread badges, delete, and context menu actions are high-risk cross-platform UX.
   - Next native assertions: `chat-context-pin`, `chat-context-unpin`, `unread-badge`, `chat-context-mark-unread`, `chat-context-mark-read`, delete confirmation and touch menu persistence.

3. `chat-search-flow.spec.ts`
   - Apple target: new `ChatSearchParityUITests` with seeded public/user chats.
   - Why: Search is already partly identified by `search-button` but lacks native flow coverage.
   - Next native assertions: search bar opens, query filters chats, no-results state, Escape/close clears query, settings search result routes correctly where applicable.

4. `file-attachment-flow.spec.ts` and `file-attachment-code-flow.spec.ts`
   - Apple target: extend `MessageInputAttachmentUITests` and add embed fullscreen checks.
   - Why: Pending attachment structure is covered; sent-message embed preview/fullscreen parity is not.
   - Next native assertions: sent user message contains image/code embed preview, no raw JSON leakage, fullscreen image/code view opens and closes.

5. `audio-recording.spec.ts`
   - Apple target: extend `MessageInputAudioRecordingUITests`.
   - Why: Button and overlay structure are covered; interaction outcome states are not.
   - Next native assertions: short tap shows press-and-hold hint without an embed, cancel removes overlay without preview, fixture completion creates an audio pending embed.

6. `incognito-mode.spec.ts`
   - Apple target: new privacy-mode parity test after identifiers are aligned.
   - Why: It is privacy-sensitive and includes shell, settings, banner, and chat-list state.
   - Next native assertions: incognito toggle, `incognito-pill`, incognito chat grouping, persistence/exclusion behavior.

7. `model-override.spec.ts`
   - Apple target: mention dropdown/model selector parity test.
   - Why: It is a frequent chat composer flow and affects AI routing visibility.
   - Next native assertions: mention dropdown opens from `@`, model results render, selected model appears in generated-by metadata.

## Responsive Expansion Plan

- Add shell responsive tests for compact iPhone drawer versus regular iPad side panel using the same debug preview approach.
- Add a macOS UI test path or remote run command that launches `OpenMates_macOS`, resizes the window to narrow and fullscreen widths, and captures screenshots.
- Promote one visual check at a time only after two clean simulator runs and screenshot review against rendered web reference captures.
- Extend `apple-ui-contracts.spec.ts` to capture responsive variants for chat header, transcript, sidebar, composer, and embed fullscreen at mobile/tablet/desktop widths.
- Keep physical-device-only checks separate for camera, real microphone behavior, APNs, and OS-owned pickers.
