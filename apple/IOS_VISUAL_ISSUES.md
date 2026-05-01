# iOS App — Visual Differences vs Web App

Comprehensive element-by-element audit comparing the iOS app against the web app at `app.dev.openmates.org`.
Initial audit: 2026-04-30. Web = source of truth.

---

## Fix Progress (2026-05-01)

### Completed Fixes

| # | Priority | Issue | Status |
|---|----------|-------|--------|
| 1 | P0 | **Font**: Lexend Deca bundled (6 weights: Light→ExtraBold), registered in Info.plist + FontRegistration.swift, TypographyTokens updated to `"Lexend Deca"` family name. Font files added to Xcode project build resources. | ✅ Done |
| 2 | P0 | **AI avatar**: Blue/purple `.primary` gradient instead of brown `.appAi`. OpenMates official chats show `openmates` icon, no AI badge | ✅ Done |
| 3 | P0 | **Header logo**: "Open" uses `LinearGradient.primary` as text foreground (gradient text) | ✅ Done |
| 4 | P0 | **Follow-up suggestions**: Hidden for demo/example/legal chats | ✅ Done |
| 5 | P1 | **Sidebar sections**: "INTRO" / "EXAMPLE CHATS" headers for unauthenticated users | ✅ Done |
| 6 | P1 | **Chat row timestamps**: Hidden for demo/example/legal/announcement chats | ✅ Done |
| 7 | P1 | **Sign up button**: Larger padding, bold weight, `.radiusFull` | ✅ Done |
| 8 | P1 | **Heading scale**: Capped (H1→30pt, H2→20pt, H3→16pt) for in-message readability | ✅ Done |
| 9 | P1 | **Scroll to top**: Demo/example chats scroll to banner on load | ✅ Done |
| 10 | P1 | **Header hamburger**: Uses `menu`/`close` Icon at 0.6 opacity instead of custom animated lines | ✅ Done |
| 11 | P1 | **Settings icon**: Uses `LinearGradient.primary` gradient color | ✅ Done |
| 12 | P1 | **New chat CTA**: Demo/intro/legal chats show full-width "New chat" button instead of input field | ✅ Done |
| 13 | P1 | **Input icons**: Action buttons use app-specific gradients (maps→appMaps, modify→appDesign, camera→appPhotos) | ✅ Done |
| 14 | P1 | **Settings panel**: Slides from right as overlay (323px, shadow, backdrop dim) instead of centered modal | ✅ Done |
| 15 | P1 | **Settings icons**: All rows use colorful gradient circles matching web (28px, rounded) | ✅ Done |
| 16 | P1 | **Responsive messages**: Mobile stacked layout — avatar above message on compact width | ✅ Done |
| 17 | P1 | **Selected chat highlight**: Uses `buttonPrimary.opacity(0.12)` instead of plain grey | ✅ Done |
| 18 | P1 | **Chat header decorative icons**: Raw AI sparkle SVG shapes at 0.4 opacity (not gradient circles), clipped at edges | ✅ Done |
| 19 | P0 | **Chat banner rewrite**: Living gradient orbs (TimelineView-driven), floating deco icons, shimmer loading, proper category gradients, nav arrows, bottom-only rounded corners — matches ChatHeader.svelte | ✅ Done |
| 20 | P0 | **Chat banner gradient**: demo-for-everyone uses `openMatesOfficial` indigo gradient (#6366f1→#4f46e5) instead of brown/orange `appAi` | ✅ Done |
| 21 | P0 | **Chat banner teaser copy**: Intro chat shows three teaser lines ("AI team mates." / "For everyday tasks..." / "With privacy...") left-aligned instead of centered title+description | ✅ Done |
| 22 | P0 | **Chat header video**: Bundled 595KB intro teaser (silent, looping) with play button overlay. Mobile: text↔video crossfade loop (6s per phase). Desktop/landscape: side-by-side split layout. Play button opens streamed full video from api.video. | ✅ Done |
| 23 | P0 | **Chat header nav arrows**: Prev/next chevron buttons wired to ChatStore navigation. Swipe gesture (50pt threshold) for chat switching. | ✅ Done |
| 24 | P0 | **Responsive teaser layout**: Uses actual banner width (520pt breakpoint matching web's max-width:520px) instead of sizeClass alone — works correctly in iPhone landscape, iPad, and macOS | ✅ Done |
| 25 | P0 | **Info.plist UIAppFonts**: Added all 6 Lexend Deca font entries | ✅ Done |
| 26 | P0 | **Signup CTA removed from banner**: Was duplicating the header bar's Sign up button | ✅ Done |

### Remaining Issues

| # | Priority | Issue | Notes |
|---|----------|-------|-------|
| 27 | P2 | **New chat screen**: Full new-chat view with daily inspiration banner, suggestion cards, "Continue where you left off" | Currently uses simplified NewChatView |
| 28 | P2 | **AppStoreCards in chat**: For-everyone content includes horizontal app/skill/focus cards | Rendered as part of chat message content on web |
| 29 | P2 | **Sidebar search**: Simplify to icon toggle | Web: icon-only search trigger |
| 30 | P2 | **Hidden chats link**: Move to top of sidebar | Web: shows at top |

---

## Files Modified (2026-05-01 session)

| File | Changes |
|---|---|
| `ChatBannerView.swift` | Full rewrite: TimelineView-driven orb animation, raw SVG deco icons (not gradient circles), intro teaser split layout with bundled video, mobile crossfade loop, play button overlay, full video streaming, responsive width-based layout (520pt breakpoint), swipe gesture for chat navigation, removed signup CTA |
| `ChatView.swift` | Added `onPreviousChat`/`onNextChat` callbacks, passes `isIntroChat`, `teaserVideoURL`, `fullVideoURL` to banner |
| `MainAppView.swift` | Changed demo-for-everyone appId to `"openmates"`, added `orderedChatIds` computed property, `previousChatAction`/`nextChatAction` navigation helpers |
| `AppIconView.swift` | Added `"openmates"` case → `openMatesOfficial` gradient + `"ai"` icon name |
| `AppStrings.swift` | Added `teaserLine1/2/3` accessors for intro teaser copy |
| `DataExtensions.swift` | Added `openMatesOfficial` indigo gradient |
| `Info.plist` | Added `UIAppFonts` array with 6 Lexend Deca entries |
| `OpenMates.xcodeproj/project.pbxproj` | Added 6 font TTF files + intro-teaser.mp4 as bundle resources |
| `Resources/Videos/intro-teaser.mp4` | Bundled 595KB silent teaser clip (copied from web app static) |
| `Resources/i18n/en.json` | Updated from latest web build (teaser_line keys) |

---

## Reference Files

| What | iOS file | Web file |
|---|---|---|
| Header | `MainAppView.swift` (OpenMatesWebHeader) | `Header.svelte` |
| Chat banner | `ChatBannerView.swift` | `ChatHeader.svelte` |
| Message bubble | `ChatView.swift` (MessageBubble) | `ChatMessage.svelte` |
| Input bar | `ChatView.swift` (inputBar) | `MessageInput.svelte` |
| Follow-up suggestions | `FollowUpSuggestions.swift` | `FollowUpSuggestions.svelte` |
| Sidebar | `MainAppView.swift` (chatsPanel) | `ChatHistory.svelte` |
| Chat row | `ChatListRow.swift` | `chats/Chat.svelte` |
| AI avatar | `ChatView.swift` (MessageBubble) | `ChatMessage.svelte` |
| App icon | `AppIconView.swift` | `categoryUtils.ts` |
| Settings | `SettingsView.swift` | `CurrentSettingsPage.svelte` |
| Font tokens | `TypographyTokens.generated.swift` | `tokens/typography.css` |
| Gradient tokens | `GradientTokens.generated.swift` | `tokens/gradients.css` |
| Video registry | `videos.ts` (teaser bundled in Resources/Videos/) | `demo_chats/data/videos.ts` |
