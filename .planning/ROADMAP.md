# Roadmap: Apple App Web Parity

## Overview

A systematic effort to bring the OpenMates Apple app to exact visual and functional parity with the Svelte web app. Work proceeds from shared foundation (tokens, primitives, font) through the primary chat surfaces, then the new chat screen, and finally settings and chat list. Every phase ends with a simulator screenshot vs. Firecrawl web screenshot comparison — done when a user cannot tell the apps apart.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Foundation** - Verify and fix tokens, OM* primitives, and font registration so every downstream screen inherits a correct base
- [ ] **Phase 2: Chat Display & Content** - Bring chat view, message bubbles, embeds, and chat content to pixel-accurate parity with the web app (Milestone 1)
- [ ] **Phase 3: New Chat Screen** - Implement the full new chat screen matching web app design and follow-up suggestion chips (Milestone 2)
- [ ] **Phase 4: Settings & Chat List** - Bring settings menus and chat list to visual and functional parity with the web app (Milestone 3)

## Phase Details

### Phase 1: Foundation
**Goal**: The shared token, primitive, and font layer is verified correct so all downstream screens inherit an accurate base
**Depends on**: Nothing (first phase)
**Requirements**: FOUN-01, FOUN-02, FOUN-03
**Success Criteria** (what must be TRUE):
  1. A side-by-side screenshot of an OM* primitive (OMToggle, OMDropdown, OMSettingsRow) in the simulator matches its web counterpart with no visible color, spacing, or shape difference
  2. Lexend Deca renders in the simulator at all weights — no fallback to SF Pro visible in any view
  3. Generated Swift token files (ColorTokens, SpacingTokens, TypographyTokens, GradientTokens) match their CSS source values — no stale hex or spacing values remain
  4. The lint-swift-design-tokens.sh script passes with zero violations on the current codebase
**Plans**: 2 plans

Plans:
- [x] 01-01-PLAN.md — Audit and regenerate Swift token files, fix DataExtensions gradient drift, verify Lexend Deca font registration
- [ ] 01-02-PLAN.md — Fix OM* primitive visual differences (toggle color, dropdown radius, row padding), visual checkpoint

**UI hint**: yes

### Phase 2: Chat Display & Content
**Goal**: The chat view, message bubbles, chat banner, embeds, and chat content (example chats, app cards, AI model references) match the web app visually on iPhone, iPad, and Mac simultaneously
**Depends on**: Phase 1
**Requirements**: CHAT-01, CHAT-02, CHAT-03, CHAT-04, CONT-01, CONT-02, CONT-03
**Success Criteria** (what must be TRUE):
  1. A Firecrawl screenshot of the web chat view and an XcodeBuildMCP simulator screenshot of the same chat show identical message bubble colors, tail shapes, shadows, and corner radius
  2. The chat banner shows the correct gradient and decorative icon for every chat type (for-everyone, for-developers, example chats, legal chats, user-created chats) — verified by switching between chat types in the simulator
  3. Tapping an embed preview card opens a fullscreen view that matches the web app's UnifiedEmbedFullscreen layout and controls
  4. Example chats in the for-everyone intro chat load, display, and are tappable — app cards and AI model references render with correct images and typography
**Plans**: TBD
**UI hint**: yes

### Phase 3: New Chat Screen
**Goal**: The new chat screen is fully implemented matching the web app's daily inspiration banner, suggestions layout, and follow-up suggestion chips
**Depends on**: Phase 2
**Requirements**: NEWC-01, NEWC-02, NEWC-03
**Success Criteria** (what must be TRUE):
  1. Tapping the new chat button in the simulator navigates to the new chat screen without errors on iPhone, iPad, and Mac
  2. A side-by-side comparison of the new chat screen (simulator) vs. the web app (Firecrawl) shows matching daily inspiration banner with gradient, orbs, mate avatar, and suggestions layout
  3. Follow-up suggestion chips scroll horizontally, match the pill shape and typography from the web app, and respond to taps
**Plans**: TBD
**UI hint**: yes

### Phase 4: Settings & Chat List
**Goal**: The settings menu, all settings sub-pages, and the chat list match the web app visually and functionally, with correct auth-gating and sort order
**Depends on**: Phase 3
**Requirements**: SETT-01, SETT-02, SETT-03, LIST-01, LIST-02, LIST-03
**Success Criteria** (what must be TRUE):
  1. A side-by-side comparison of the settings menu (simulator vs. Firecrawl) shows matching layout, typography, icons, and spacing — no native iOS chrome (gray grouped background, blue toggles, system separators) visible
  2. Navigating into settings sub-pages works correctly and each sub-page renders matching its web Svelte counterpart
  3. A non-authenticated user sees only the appropriate settings sections — auth-gated sections are hidden or shown consistent with the web app's logic
  4. Chat list rows match web app layout and typography; the sort order in the simulator matches the order produced by chats.svelte
  5. A typing/streaming indicator appears in the correct chat list row during an active AI response
**Plans**: TBD
**UI hint**: yes

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 1/2 (task 1 of plan 02 done, awaiting visual checkpoint) | In Progress|  |
| 2. Chat Display & Content | 0/TBD | Not started | - |
| 3. New Chat Screen | 0/TBD | Not started | - |
| 4. Settings & Chat List | 0/TBD | Not started | - |
