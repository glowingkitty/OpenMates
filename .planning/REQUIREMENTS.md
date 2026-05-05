# Requirements: Apple App Web Parity

**Defined:** 2026-05-01
**Core Value:** A user cannot tell the Apple app apart from the web app

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Foundation

- [x] **FOUN-01**: Generated Swift token files (colors, spacing, typography, gradients) are verified in sync with CSS source files
- [ ] **FOUN-02**: All OM* primitive components (OMToggle, OMDropdown, OMSheet, OMConfirmDialog, OMSettingsPage, OMSettingsSection, OMSettingsRow, OMSegmentedControl) match their web equivalents visually
- [x] **FOUN-03**: Lexend Deca font is properly registered and rendering correctly across all platforms

### Chat Display

- [ ] **CHAT-01**: Assistant avatar circles are correctly sized per device (60pt circle on all platforms), load profile images, and show OpenMates icon for intro/example/legal chats
- [ ] **CHAT-02**: Chat header shows correct gradient and icon for ALL chat types -- example chats, legal chats, for-everyone, for-developers, and user-created chats
- [ ] **CHAT-03**: Embeds in messages render as preview cards matching the web app's UnifiedEmbedPreview
- [ ] **CHAT-04**: Tapping an embed opens a fullscreen view matching the web app's UnifiedEmbedFullscreen

### Chat Content

- [ ] **CONT-01**: Example chats in the for-everyone intro chat load, display correctly, and are tappable
- [ ] **CONT-02**: App cards/references in messages load and render matching the web app
- [ ] **CONT-03**: AI model references in messages load and render matching the web app

### New Chat

- [ ] **NEWC-01**: New chat button navigates to the new chat screen
- [ ] **NEWC-02**: New chat screen matches web app design (daily inspiration banner, suggestions layout, "continue" section)
- [ ] **NEWC-03**: Follow-up suggestion chips match web style (scroll, appearance, interaction)

### Settings

- [ ] **SETT-01**: Settings menu matches web app visually (layout, typography, spacing, icons)
- [ ] **SETT-02**: All settings sub-pages navigate correctly and render matching web counterparts
- [ ] **SETT-03**: Auth-gated sections show appropriate content for non-authenticated state, with logic matching web app for future authenticated state

### Chat List

- [ ] **LIST-01**: Chat list rows match web app appearance (layout, typography, metadata display)
- [ ] **LIST-02**: Chat list sorting matches web app logic (same sort order as chats.svelte)
- [ ] **LIST-03**: Typing/streaming indicator shows in chat list row during active AI response

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Authentication

- **AUTH-01**: User can log in with email/password
- **AUTH-02**: User can sign up with email
- **AUTH-03**: User session persists across app restart
- **AUTH-04**: User can log out

### Chat Features (Authenticated)

- **ACHAT-01**: User can create new chats with AI assistants
- **ACHAT-02**: User can send messages and receive AI responses
- **ACHAT-03**: User can view chat history synced from web app

## Out of Scope

| Feature | Reason |
|---------|--------|
| Login/signup auth flows | Deferred to Milestone 4 -- visual parity first |
| Backend API changes | Apple app consumes existing API as-is |
| Web app modifications | Web app is frozen as design source of truth |
| New features not in web app | Strict parity only, no native-only features |
| Siri/Spotlight/Widget work | Existing implementations are frozen |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FOUN-01 | Phase 1 | Complete |
| FOUN-02 | Phase 1 | Pending |
| FOUN-03 | Phase 1 | Complete |
| CHAT-01 | Phase 2 | Pending |
| CHAT-02 | Phase 2 | Pending |
| CHAT-03 | Phase 2 | Pending |
| CHAT-04 | Phase 2 | Pending |
| CONT-01 | Phase 2 | Pending |
| CONT-02 | Phase 2 | Pending |
| CONT-03 | Phase 2 | Pending |
| NEWC-01 | Phase 3 | Pending |
| NEWC-02 | Phase 3 | Pending |
| NEWC-03 | Phase 3 | Pending |
| SETT-01 | Phase 4 | Pending |
| SETT-02 | Phase 4 | Pending |
| SETT-03 | Phase 4 | Pending |
| LIST-01 | Phase 4 | Pending |
| LIST-02 | Phase 4 | Pending |
| LIST-03 | Phase 4 | Pending |

**Coverage:**
- v1 requirements: 19 total
- Mapped to phases: 19
- Unmapped: 0

---
*Requirements defined: 2026-05-01*
*Last updated: 2026-05-01 after roadmap creation — traceability complete*
