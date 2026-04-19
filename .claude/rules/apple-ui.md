# Apple UI — Web Source of Truth

Every Swift UI file must visually match its web counterpart exactly.
The web app (Svelte + CSS custom properties) is the design source of truth.
Design tokens are pre-generated — never hardcode colors, spacing, or radii.

---

## CRITICAL: No Hardcoded Strings — Ever

**Every user-visible string MUST go through `AppStrings` or `LocalizationManager`.**
Hardcoding English text in Swift files is a bug, not a shortcut.

### The chain
```
i18n YML source files  (frontend/packages/ui/src/i18n/sources/**/*.yml)
       ↓  built by npm run build:translations
i18n JSON locales      (frontend/packages/ui/src/i18n/locales/{locale}.json)
       ↓  bundled into the iOS/macOS app at build time
LocalizationManager    (apple/.../Core/I18n/LocalizationManager.swift)
       ↓  type-safe accessors
AppStrings             (apple/.../Core/I18n/AppStrings.swift)
       ↓
Swift UI
```

### Rules
1. **NEVER write `Text("Some English text")` in a Swift view.** Always `Text(AppStrings.myKey)`.
2. **NEVER call `LocalizationManager.shared.text("key")` directly from a view.** Add a
   typed accessor to `AppStrings` first, then use that.
3. **Every new string displayed in the UI needs a matching key in the YML source files**
   (under `frontend/packages/ui/src/i18n/sources/`) AND a typed accessor in `AppStrings.swift`.
4. If the key already exists in the JSON (check `en.json`), add only the `AppStrings` accessor.
5. If the key does NOT exist, add it to the appropriate YML source file FIRST, run
   `cd frontend/packages/ui && npm run build:translations`, then add the accessor.
6. Replacements (e.g. `{count}`, `{time}`) use `LocalizationManager.shared.text(key, replacements: [...])`
   wrapped in a typed `AppStrings` helper function.

### Quick reference — keys for chat banner UI (all exist in en.json)
| Displayed text | YML key | AppStrings accessor to add |
|---|---|---|
| "Creating new chat ..." | `chat.creating_new_chat` | `AppStrings.creatingNewChat` |
| "Just now" | `chat.header.just_now` | `AppStrings.chatHeaderJustNow` |
| "{n} min ago" | `chat.header.minutes_ago` | `AppStrings.chatHeaderMinutesAgo(count:)` |
| "Started today, HH:MM" | `chat.header.started_today` | `AppStrings.chatHeaderStartedToday(time:)` |
| "Started yesterday, HH:MM" | `chat.header.started_yesterday` | `AppStrings.chatHeaderStartedYesterday(time:)` |
| "Incognito Mode" | `settings.incognito_mode_active` | `AppStrings.incognitoModeActive` |
| Demo chat: "OpenMates \| For everyone" | `demo_chats.for_everyone.title` | `AppStrings.demoForEveryoneTitle` |
| Demo chat: description | `demo_chats.for_everyone.description` | `AppStrings.demoForEveryoneDescription` |
| Demo chat: "OpenMates \| For developers" | `demo_chats.for_developers.title` | `AppStrings.demoForDevelopersTitle` |
| Demo chat: description | `demo_chats.for_developers.description` | `AppStrings.demoForDevelopersDescription` |

---

## Mandatory: Web-Source Comment Block

Every `.swift` file under `apple/OpenMates/Sources/` with visual output MUST
have this block immediately after the file-level header comment:

```swift
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/ChatMessage.svelte
// CSS:     frontend/packages/ui/src/styles/chat.css
//          Classes: .mate-message-content, .user-message-content::before
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
```

Include only the files that directly drive the visual spec for that view.
Multiple Svelte files or CSS files are fine — list all that apply.

---

## Canonical File ↔ Web Mapping

| Swift file | Svelte source | CSS source |
|---|---|---|
| `ChatView.swift` — `MessageBubble` | `components/ChatMessage.svelte` | `styles/chat.css` — `.mate-message-content`, `.user-message-content`, `::before` tails |
| `ChatView.swift` — `inputBar` | `components/enter_message/MessageInput.svelte` | `styles/fields.css` |
| `ChatView.swift` — `StreamingIndicator` | `components/ChatHistory.svelte` (typing indicator) | `styles/chat.css` |
| `ChatView.swift` — `messageList` | `components/ChatHistory.svelte` | `styles/chat.css` — `.chat-history-content`, max-width 1000px |
| `ChatHeaderView.swift` | `components/ChatHeader.svelte` | — (gradient from `GradientTokens.generated.swift`) |
| `ChatListRow.swift` | `components/chats/Chat.svelte` | — |
| `MainAppView.swift` — sidebar | `components/ChatHistory.svelte`, `components/Header.svelte` | — |
| `OMButtonStyles.swift` | — | `styles/buttons.css` |
| `FollowUpSuggestions.swift` | `components/FollowUpSuggestions.svelte` | `styles/chat.css` — `.follow-up-suggestions-wrapper` |
| `NewChatBannerView.swift` | `components/ChatHeader.svelte` | — (gradient from `GradientTokens.generated.swift`) |
| `SpeechBubbleShape.swift` | — | `styles/chat.css` — `::before` SVG mask, `static/speechbubble.svg` |

---

## Design Rules (must follow before writing any Swift UI code)

### Before touching any Swift UI file
1. Read the mapped Svelte component listed above.
2. Read the mapped CSS file — note exact class names, pixel values, transitions.
3. Read the token mapping table in `docs/architecture/frontend/apple-ui-redesign-task.md`.
4. Only then write or modify Swift code.

### Colors — never hardcode
- Use `Color.*` extensions from `ColorTokens.generated.swift`.
- Use `LinearGradient.*` extensions from `GradientTokens.generated.swift`.
- No `Color(hex:)`, no `Color(.sRGB, r:g:b:)`, no `Color("name")` without a token.

### Spacing & radius — never hardcode (with one exception)
- Use `.spacingN` / `.radiusN` from `SpacingTokens.generated.swift`.
- Exception: message bubble corner radius is exactly `13` (not a token) — matches
  `border-radius: 13px` in `chat.css`.

### Typography — never hardcode
- Use `Font.omH1` … `Font.omMicro` from `TypographyTokens.generated.swift`.
- Never `Font.system(size:)` for text that appears in the UI.

### Native chrome — strip it
- `NavigationSplitView` sidebar: always `.listStyle(.plain)` +
  `.listRowBackground(Color.clear)` + `.listRowSeparator(.hidden)`.
- No `List(.sidebar)` styling.
- Sidebar column background: `.background(Color.grey0)`.

### Message bubbles (from `chat.css`)
- User bubble: `Color.greyBlue` background, `Color.grey100` text, tail bottom-right.
- Assistant bubble: `Color.grey0` background, `Color.fontPrimary` text, tail top-left.
- Both: `shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)`.
- `clipShape(RoundedRectangle(cornerRadius: 13))`.
- Fade-in: `opacity(0→1)` + `offset(y: 10→0)` over 0.4s `.easeIn`. Respect `accessibilityReduceMotion`.
- Assistant avatar: 60pt circle, same shadow. AI badge: 24pt white circle, 16pt gradient icon inside.
- Max width: `Spacer(minLength: 100)` on iPhone, `Spacer(minLength: 100)` on iPad/Mac (content capped at 1000pt).

### Input field (from `fields.css`)
- Shape: `.clipShape(RoundedRectangle(cornerRadius: .radiusFull))`.
- Border: 2pt stroke, `Color.grey0` default → `Color.buttonPrimary` when focused.
- Focus glow: `shadow(color: Color.buttonPrimary.opacity(0.22), radius: 3, x:0, y:0)` +
  `shadow(color: .black.opacity(0.08), radius: 12, x:0, y:4)`.
- Tint: `.tint(Color.buttonPrimary)`.
- Send button: circle, `Color.buttonPrimary` fill when text present, `Color.grey20` when empty.
- Apply consistently — not just in `ChatView.inputBar` but in `NewChatView` too.

### Buttons (from `buttons.css`)
- Shape: `RoundedRectangle(cornerRadius: .radius8)` — `radius8` = 20pt.
- Padding: `.spacing12` horizontal, `.spacing8` vertical. Min height 41pt.
- Font: `.omP` semibold.
- Primary fill: `Color.buttonPrimary`. Text: `Color.fontButton`.
- Shadow: `shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)`.
- Press: scale 0.98, 0.15s easeInOut. Disabled: opacity 0.6.

### Follow-up suggestions (from `chat.css` `.follow-up-suggestions-wrapper`)
- `clipShape(RoundedRectangle(cornerRadius: .radiusFull))`.
- Background `Color.grey10`, border `Color.grey30` (1pt stroke).
- Font `.omSmall` medium, `Color.fontPrimary`.
- Padding `.spacing6` H, `.spacing3` V.
- Horizontal `ScrollView`.

### Speech bubble tail (from `speechbubble.svg` + `chat.css ::before`)
- SVG viewBox 7×11 → rendered 12×20pt.
- User message: tail on bottom-trailing, `Color.greyBlue` fill.
- Assistant message: tail on top-leading, `Color.grey0` fill.
- Implemented as `Canvas` overlay in `SpeechBubbleShape.swift` (separate file).

---

## What NOT to change
- Business logic, networking, WebSocket, encryption (`Core/` directory).
- Navigation flow or sheets.
- Generated token files (`*.generated.swift`).
- Siri Intents, Spotlight, Handoff, widget code.
- Settings screen (separate task).
- Accessibility labels and identifiers — preserve or update when view hierarchy changes.
- `.task {}`, `.onReceive {}`, `.onChange {}`, `.sheet {}` modifiers in `MainAppView`.
