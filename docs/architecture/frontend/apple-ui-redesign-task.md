---
status: todo
created: 2026-04-18
priority: critical
scope: apple/OpenMates/Sources/Features/Chat/, apple/OpenMates/Sources/App/, apple/OpenMates/Sources/Shared/Components/
---

# Task: Redesign Apple App UI to Match Web App 1:1

> The iOS/iPadOS/macOS app looks nothing like the web app. The web app is the
> source of truth for all visual design. The design tokens (colors, spacing,
> typography, gradients) are already shared and generated — see
> `docs/architecture/frontend/design-tokens.md`. The problem is that the Swift
> UI components use **native SwiftUI controls** (NavigationSplitView,
> List(.sidebar), plain TextFields) instead of custom-styled components that
> match the web app's look. This task fixes that.

## Goal

Opening the iOS app must feel visually identical to opening the web app on a
mobile browser — same message bubbles with tails and shadows, same pill-shaped
input field, same sidebar styling, same color scheme, same spacing. The native
app should look like a native implementation of the web design, not a generic
iOS app.

---

## Source of Truth: Web App Files to READ

Read ALL of these before writing any code. They contain the exact CSS values,
layout structures, and component patterns to replicate.

### CSS (exact design specs)

| File | What it defines |
|------|----------------|
| `frontend/packages/ui/src/styles/chat.css` | Message bubbles, speech tails, message layout, alignment |
| `frontend/packages/ui/src/styles/theme.css` | Global theme, backgrounds, focus rings, scrollbars |
| `frontend/packages/ui/src/styles/buttons.css` | Button styles (pill-shaped, shadows, hover/press states) |
| `frontend/packages/ui/src/styles/fields.css` | Input fields (rounded, focus/hover states, caret color) |
| `frontend/packages/ui/src/styles/mates.css` | Avatar/mate profile styling (60px circle, shadow, badge) |
| `frontend/packages/ui/src/styles/cards.css` | Card patterns |
| `frontend/packages/ui/src/styles/animations.css` | Keyframe animations (fade-in, morph) |
| `frontend/packages/ui/src/styles/settings.css` | Settings panel (out of scope for this task) |

### Svelte Components (layout structure)

| File | What it defines |
|------|----------------|
| `frontend/packages/ui/src/components/Header.svelte` | Top navigation bar |
| `frontend/packages/ui/src/components/ChatHeader.svelte` | Chat title bar in the detail area |
| `frontend/packages/ui/src/components/ChatHistory.svelte` | Sidebar chat list container |
| `frontend/packages/ui/src/components/Chat.svelte` | Single chat row in sidebar |
| `frontend/packages/ui/src/components/chats/Chat.svelte` | Main chat view (message list + input) |
| `frontend/packages/ui/src/components/ChatMessage.svelte` | Individual message bubble rendering |
| `frontend/packages/ui/src/components/enter_message/MessageInput.svelte` | Message input area |

### Generated Design Tokens (already available in Swift — DO NOT edit)

| File | Contents |
|------|----------|
| `frontend/packages/ui/src/tokens/generated/swift/ColorTokens.generated.swift` | All color extensions on `Color` |
| `frontend/packages/ui/src/tokens/generated/swift/SpacingTokens.generated.swift` | Spacing & radius on `CGFloat` |
| `frontend/packages/ui/src/tokens/generated/swift/TypographyTokens.generated.swift` | Font size extensions on `Font` |
| `frontend/packages/ui/src/tokens/generated/swift/GradientTokens.generated.swift` | 70+ app gradients + primary gradient |
| `frontend/packages/ui/src/tokens/generated/swift/ComponentTokens.generated.swift` | Component-level token enums |
| `frontend/packages/ui/src/tokens/generated/swift/IconMapping.generated.swift` | SF Symbol + custom icon mappings |

### Speech Bubble SVG (reference for the tail shape)

`frontend/static/speechbubble.svg` — 12px wide × 20px tall triangular tail

---

## Apple App Files to MODIFY

| File | What to change |
|------|---------------|
| `apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift` | MessageBubble redesign, input bar redesign, chat layout |
| `apple/OpenMates/Sources/Features/Chat/Views/ChatHeaderView.swift` | Simplify header, use generated gradient tokens |
| `apple/OpenMates/Sources/App/MainAppView.swift` | Sidebar styling, remove native List chrome |
| `apple/OpenMates/Sources/Shared/Components/ChatListRow.swift` | Custom chat row styling |
| `apple/OpenMates/Sources/Shared/Components/OMButtonStyles.swift` | Pill-shaped buttons, shadows |
| `apple/OpenMates/Sources/Features/Chat/Views/FollowUpSuggestions.swift` | Pill-shaped suggestion buttons |
| `apple/OpenMates/Sources/Features/Chat/Views/InputActionButtons.swift` | Input action button styling |

You will likely need to **create** a new file:
- `apple/OpenMates/Sources/Shared/Components/SpeechBubbleShape.swift` — Custom SwiftUI `Shape` for message tail

---

## Detailed Design Specifications

### 1. Message Bubbles (highest visual impact)

**Current state (broken):** Flat rounded rectangles with `radius5` (12px), no
shadows, no speech bubble tails. User messages use `LinearGradient.primary`
(blue-purple gradient). Assistant messages use `Color.grey10` (light grey).

**Target (from web app CSS — read `chat.css` for exact values):**

- **Shape:** Speech bubble with a triangular tail. User tail on the right,
  assistant tail on the left. Tail is ~12px wide × ~20px tall. Implement as a
  custom SwiftUI `Shape` or overlay.
- **Border radius:** 13px on the bubble body
- **Drop shadow:** On ALL bubbles: `shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)`
- **User message background:** `Color.greyBlue` (the `--color-grey-blue` token
  = `#e6eaff` light / `#2d2f35` dark). **NOT** a gradient — the current
  `LinearGradient.primary` is wrong.
- **User message text color:** `Color.grey100`
- **Assistant message background:** `Color.grey0` (white in light mode,
  `#171717` in dark mode)
- **Assistant message text color:** `Color.fontPrimary`
- **Padding inside bubble:** 12px (`.spacing6`) all sides
- **Max width constraint:** User messages should not span the full width.
  On iPhone: leave ~20px margin on the opposite side.
  On iPad/Mac: leave ~100px margin on the opposite side.
- **Assistant avatar:** 60px circular, positioned left of the message, with
  shadow `shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)`. Include
  a small AI badge (white 24px circle at bottom-right of avatar with blue
  gradient 16px icon inside). On compact widths (<500pt), the avatar stacks
  above the message instead of inline.
- **User messages:** Right-aligned (`Spacer()` on the left)
- **Assistant messages:** Left-aligned (`Spacer()` on the right)
- **Fade-in animation:** `opacity(0→1)` + `offset(y: 10→0)` over 0.4s with
  `easeIn` timing. Respect `accessibilityReduceMotion`.

### 2. Input Bar

**Current state (broken):** Plain TextField with `grey10` background, `radius5`
(12px), divider on top, basic `arrow.up.circle.fill` send button.

**Target (from web app CSS — read `fields.css` for exact values):**

- **Shape:** Fully rounded pill (`radius` = 24px or use `.radiusFull`)
- **Background:** `Color.grey0` (adapt to theme)
- **Border:** 2px stroke, `Color.grey0` default → `Color.buttonPrimary`
  (`#ff553b`) on focus
- **Padding inside:** 12px vertical, 16px horizontal
- **Placeholder text:** "Type a message..." in `Color.fontFieldPlaceholder`
  (`#9e9e9e`)
- **Cursor/tint color:** `Color.buttonPrimary` — use `.tint(Color.buttonPrimary)`
- **Focus glow:** When focused, add a subtle orange glow:
  `shadow(color: Color.buttonPrimary.opacity(0.22), radius: 3, x: 0, y: 0)`
  plus `shadow(color: .black.opacity(0.08), radius: 12, x: 0, y: 4)`
- **Send button:** Circular orange `Color.buttonPrimary` fill when there's text
  to send, `Color.fontTertiary` when empty/disabled. Arrow-up icon inside.
- Remove the `Divider()` above the input — the web app doesn't have one.

### 3. Buttons (OMPrimaryButtonStyle / OMSecondaryButtonStyle)

**Current state (broken):** `radius3` (8px) rectangular, small padding.

**Target (from web app CSS — read `buttons.css` for exact values):**

- **Shape:** Pill-shaped with `radius8` (20px) — `RoundedRectangle(cornerRadius: .radius8)`
- **Padding:** 16px vertical (`.spacing8`), 24px horizontal (`.spacing12`)
- **Min height:** 41px
- **Font:** `.omP` (16pt), semibold
- **Primary background:** `Color.buttonPrimary` (`#ff553b`)
- **Primary text:** `Color.fontButton` (white)
- **Drop shadow:** `shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)`
- **Press animation:** Scale to 0.98 with 0.15s animation
- **Disabled:** opacity 0.6
- **Secondary background:** `Color.buttonSecondary` (`#808080`)
- Same shape, padding, shadow for secondary

### 4. Sidebar / Chat List

**Current state (broken):** Native `List(.sidebar)` with system styling. Looks
like a standard iOS settings list with system section headers and dividers.

**Target (from web app — read `ChatHistory.svelte` and `Chat.svelte`):**

The sidebar should look like the web app's chat history panel:

- **Option A (recommended):** Keep `List` but use `.listStyle(.plain)` and
  `.listRowBackground(Color.clear)` to strip native chrome, then style each row
  manually.
- **Option B:** Replace `List` with `ScrollView` + `LazyVStack` for full
  control (but loses native swipe-to-delete and selection binding — you'd need
  to reimplement).

**Chat row styling:**
- App icon (gradient circle via `AppIconView`, ~36px) on the left
- Chat title: `.omP` font, medium weight, `Color.fontPrimary`, single line
- Relative timestamp: `.omXs`, `Color.fontTertiary`, right-aligned
- Pin indicator: Small pin icon if pinned
- **Row padding:** 8px vertical (`.spacing4`), 12px horizontal (`.spacing6`)
- **Selected row:** Background `Color.grey10` or `Color.grey20`
- **Hover (Mac):** Subtle background highlight
- **Section headers:** Keep "Pinned" / "Recent" labels, styled with `.omXs`
  font, `Color.fontTertiary`, uppercase

### 5. Chat Header

**Current state (broken):** 80px gradient banner with hardcoded gradient colors
per app type (not using generated tokens).

**Target (from web app — read `ChatHeader.svelte`):**

- Remove the 80px fixed-height gradient banner
- Use the standard navigation bar with `.navigationBarTitleDisplayMode(.inline)`
- Add a custom `titleView` in the toolbar with: app icon (small, ~20px) + chat
  title text in an HStack
- Subtle gradient accent: If desired, a very faint (5-10% opacity) gradient tint
  behind the navigation bar using the generated gradient tokens from
  `GradientTokens.generated.swift` — NOT the hardcoded `gradientColors(for:)`
  function
- Delete the `gradientColors(for:)` function entirely — use `LinearGradient`
  extensions from the generated tokens

### 6. Overall Layout

**Web app layout on desktop/iPad:**
```
┌──────────────────────────────────────┐
│  Navigation bar (standard height)    │
├─────────────┬────────────────────────┤
│  Sidebar    │  Chat content area     │
│  (chat      │  (max-width ~1000pt,   │
│   list)     │   centered)            │
│             │                        │
│             │  ┌──────────────────┐  │
│             │  │ Messages         │  │
│             │  │ (scrollable)     │  │
│             │  └──────────────────┘  │
│             │  ┌──────────────────┐  │
│             │  │ Input bar        │  │
│             │  └──────────────────┘  │
└─────────────┴────────────────────────┘
```

- **Chat content max-width:** On iPad and Mac, cap the message area at ~1000pt
  and center it horizontally within the detail pane. Use
  `.frame(maxWidth: 1000)` on the content VStack inside ChatView.
- **Background:** `Color.grey0` for the main content area — NOT system
  background. Apply `.background(Color.grey0)` to the root VStack.
- Keep `NavigationSplitView` for adaptive sidebar behavior.

### 7. Follow-Up Suggestions

Style as pill-shaped buttons:
- Background: `Color.grey10` or `Color.grey20`
- Border radius: `.radiusFull` (pill)
- Font: `.omSmall`, medium weight
- Text: `Color.fontPrimary`
- Padding: `.spacing3` vertical, `.spacing6` horizontal
- Horizontal scroll if they overflow

### 8. Streaming Indicator

Keep the bouncing dots but match web styling:
- Background: `Color.grey0` (not `grey10`)
- Same drop shadow as assistant messages
- Same 13px border radius

---

## Token Mapping Quick Reference

These tokens already exist in the generated Swift extensions. Use them directly.

| Web CSS Variable | Swift Token | Value |
|---|---|---|
| `--color-grey-0` | `Color.grey0` | #ffffff / #171717 |
| `--color-grey-10` | `Color.grey10` | #f9f9f9 (adaptive) |
| `--color-grey-20` | `Color.grey20` | #f3f3f3 (adaptive) |
| `--color-grey-30` | `Color.grey30` | #e3e3e3 (adaptive) |
| `--color-grey-blue` | `Color.greyBlue` | #e6eaff / #2d2f35 |
| `--color-grey-100` | `Color.grey100` | #000000 / #ffffff |
| `--color-font-primary` | `Color.fontPrimary` | Named asset color |
| `--color-font-secondary` | `Color.fontSecondary` | Named asset color |
| `--color-font-tertiary` | `Color.fontTertiary` | Named asset color |
| `--color-font-button` | `Color.fontButton` | #ffffff |
| `--color-font-field-placeholder` | `Color.fontFieldPlaceholder` | #9e9e9e |
| `--color-button-primary` | `Color.buttonPrimary` | #ff553b |
| `--color-button-primary-hover` | `Color.buttonPrimaryHover` | #ff6b54 |
| `--color-button-primary-pressed` | `Color.buttonPrimaryPressed` | #ff4422 |
| `--color-button-secondary` | `Color.buttonSecondary` | #808080 |
| `--color-error` | `Color.error` | Named asset color |
| `--color-warning` | `Color.warning` | Named asset color |
| `--spacing-1` | `.spacing1` | 2pt |
| `--spacing-2` | `.spacing2` | 4pt |
| `--spacing-3` | `.spacing3` | 6pt |
| `--spacing-4` | `.spacing4` | 8pt |
| `--spacing-5` | `.spacing5` | 10pt |
| `--spacing-6` | `.spacing6` | 12pt |
| `--spacing-8` | `.spacing8` | 16pt |
| `--spacing-10` | `.spacing10` | 20pt |
| `--spacing-12` | `.spacing12` | 24pt |
| `--spacing-16` | `.spacing16` | 32pt |
| `--radius-1` | `.radius1` | 4pt |
| `--radius-2` | `.radius2` | 6pt |
| `--radius-3` | `.radius3` | 8pt |
| `--radius-4` | `.radius4` | 10pt |
| `--radius-5` | `.radius5` | 12pt |
| `--radius-6` | `.radius6` | 14pt |
| `--radius-7` | `.radius7` | 16pt |
| `--radius-8` | `.radius8` | 20pt |
| `--radius-full` | `.radiusFull` | 9999pt |
| `--font-h1` | `.omH1` | 60pt |
| `--font-h2` | `.omH2` | 30pt |
| `--font-h3` | `.omH3` | 20pt |
| `--font-h4` | `.omH4` | 16pt |
| `--font-p` | `.omP` | 16pt |
| `--font-small` | `.omSmall` | 14pt |
| `--font-xs` | `.omXs` | 13pt |
| `--font-xxs` | `.omXxs` | 12pt |
| `--font-tiny` | `.omTiny` | 11pt |
| `--font-micro` | `.omMicro` | 9pt |

---

## What NOT to Change

- **DO NOT** touch business logic, networking, API calls, encryption, WebSocket
  handling, data models, or any code in `Core/`
- **DO NOT** change navigation flow or which screens/sheets exist
- **DO NOT** modify generated token files (`*.generated.swift`)
- **DO NOT** change Siri Intents, Spotlight indexing, Handoff, or widget code
- **DO NOT** change the Settings screen (separate task)
- **DO NOT** remove accessibility labels or identifiers — preserve or update
  them if the view hierarchy changes
- **DO NOT** change any of the `.task {}`, `.onReceive {}`, `.onChange {}`,
  `.sheet {}` modifiers on MainAppView — only change the visual presentation

## Approach (execution order)

1. **Read** all web app CSS files and Svelte components listed above
2. **Read** all Apple app Swift files listed under "Files to MODIFY"
3. **Read** the generated Swift token files to confirm available tokens
4. **Create** `SpeechBubbleShape.swift` — a custom SwiftUI `Shape` for the
   message tail (triangular, 12×20pt, on left or right side)
5. **Modify** `OMButtonStyles.swift` — pill-shaped, shadows, updated padding
6. **Modify** `ChatView.swift` — redesign `MessageBubble`, `inputBar`,
   `streamingBanner`, `messageList` layout with max-width cap
7. **Modify** `ChatHeaderView.swift` — simplify, use generated gradient tokens
8. **Modify** `ChatListRow.swift` — custom styling to match web
9. **Modify** `MainAppView.swift` — strip native sidebar chrome, style chat
   list to match web
10. **Modify** `FollowUpSuggestions.swift` — pill-shaped buttons
11. **Build** the project to verify compilation
12. **Use** `XcodeRefreshCodeIssuesInFile` on each modified file for fast
    compiler diagnostics

## Verification

After all changes:
1. Build succeeds with zero errors
2. On iPhone: message bubbles have tails + shadows, user messages are blue-tinted
   and right-aligned, assistant messages are white and left-aligned with avatar,
   input is a rounded pill with orange focus ring
3. On iPad: same as iPhone + sidebar visible with custom-styled chat rows, chat
   content area capped at ~1000pt width and centered
4. Light and dark mode both look correct (tokens handle this automatically)
5. All existing accessibility identifiers still present
6. No business logic or data flow changes — only visual presentation
