# Apple App Web Parity

## What This Is

A systematic effort to bring the OpenMates Apple app (iOS/iPadOS/macOS) to exact visual and functional parity with the Svelte web app. The web app is the sole design source of truth — every screen, interaction, and detail in the Apple app must be indistinguishable from its web counterpart.

## Core Value

A user cannot tell the Apple app apart from the web app — every screen matches pixel-for-pixel, every flow works identically.

## Requirements

### Validated

- Chat header for the "for-everyone" intro chat matches the web app (gradient, layout, text)

### Active

- [ ] Assistant avatar circles match web app (correct size per device, image loaded, OpenMates icon for intro/example chats)
- [ ] Chat header shows correct gradient and icon for all chat types (example chats, legal chats, not just for-everyone)
- [ ] Example chats in for-everyone intro chat load and display correctly
- [ ] Apps and AI models referenced in messages load and render
- [ ] Embeds in messages render correctly (preview cards, inline content)
- [ ] Fullscreen embed view opens and works like the web app
- [ ] New chat button navigates to the new chat screen
- [ ] New chat screen matches web app design and functionality
- [ ] Settings menu matches web app visually (layout, typography, spacing, icons)
- [ ] Settings sub-menus work and navigate correctly
- [ ] Settings content is auth-gated (authenticated vs non-authenticated user sees appropriate sections)
- [ ] Chat list matches web app appearance (layout, typography, metadata display)
- [ ] Chat list sorting matches web app (same sort order logic as chats.svelte)
- [ ] All screens work correctly on iPhone, iPad, and Mac simultaneously

### Out of Scope

- Login/signup auth flows — deferred to Milestone 4
- Backend API changes — Apple app consumes existing API
- Web app changes — web app is frozen as source of truth
- New features not in the web app — strict parity only

## Context

- The Apple app is built in SwiftUI, sharing the same backend API as the web app
- Design tokens are pre-generated from CSS custom properties into Swift files (`ColorTokens.generated.swift`, `SpacingTokens.generated.swift`, `TypographyTokens.generated.swift`, `GradientTokens.generated.swift`)
- The `apple/` directory has `CLAUDE.md` with detailed web-source mapping rules and forbidden native controls
- i18n strings flow from YML sources through `LocalizationManager` to `AppStrings` — no hardcoded English text allowed
- Previous Claude sessions have built the initial Apple app but left many visual and functional gaps
- `apple/IOS_VISUAL_ISSUES.md` and `apple/SVELTE_SWIFT_COUNTERPARTS.md` exist as reference docs

## Constraints

- **Design source:** Web app (Svelte + CSS custom properties) is the sole source of truth — no Figma
- **Platform parity:** iPhone, iPad, and Mac must all match simultaneously — no platform-first approach
- **No native chrome:** Forbidden native controls list in `apple/CLAUDE.md` must be followed (no Form, List, Toggle, Picker, etc.)
- **Token-only styling:** Colors, spacing, radius, and typography must use generated token files — no hardcoded values
- **i18n chain:** Every user-visible string must go through AppStrings, never hardcoded English

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Web app as sole design source | Single source of truth avoids design drift | -- Pending |
| 3 milestones before auth flows | Get visual/functional parity before tackling login/signup complexity | -- Pending |
| All platforms simultaneously | Users expect consistent experience across iPhone/iPad/Mac | -- Pending |
| Screen-by-screen approach per milestone | Focused scope, clear "done" criteria per milestone | -- Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? -> Move to Out of Scope with reason
2. Requirements validated? -> Move to Validated with phase reference
3. New requirements emerged? -> Add to Active
4. Decisions to log? -> Add to Key Decisions
5. "What This Is" still accurate? -> Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check -- still the right priority?
3. Audit Out of Scope -- reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-01 after initialization*
