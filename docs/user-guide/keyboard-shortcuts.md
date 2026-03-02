# Keyboard Shortcuts

OpenMates provides a comprehensive set of keyboard shortcuts to enhance productivity and streamline workflows. This document covers all available shortcuts and their behavior across different platforms.

## Platform Conventions

Throughout this document:
- **Ctrl** refers to `Ctrl` key on Windows/Linux and `Cmd (⌘)` key on macOS
- **Alt** refers to `Alt` key on Windows/Linux and `Option (⌥)` key on macOS
- All shortcuts automatically adapt to the user's platform

## Quick Reference Table

| Action | Windows/Linux | macOS | Context |
|--------|--------------|-------|---------|
| **Chat Management** |
| Create New Chat | `Ctrl + K, N` | `Cmd + K, N` | Global |
| Download Current Chat | `Ctrl + Shift + S` | `Cmd + Shift + S` | When chat is open |
| Copy Current Chat | `Ctrl + Shift + C` | `Cmd + Shift + C` | When chat is open |
| Toggle Chat History | `Ctrl + Shift + H` | `Cmd + Shift + H` | Global |
| Next Chat | `Ctrl + Shift + →` | `Cmd + Shift + →` | Chat history visible |
| Previous Chat | `Ctrl + Shift + ←` | `Cmd + Shift + ←` | Chat history visible |
| **Navigation** |
| Focus Message Input | `Shift + Enter` | `Shift + Enter` | When input not focused |
| Scroll to Top | `Ctrl + Shift + ↑` | `Cmd + Shift + ↑` | In chat |
| Scroll to Bottom | `Ctrl + Shift + ↓` | `Cmd + Shift + ↓` | In chat |

## Detailed Shortcuts

### Chat Management

#### Create New Chat
**Shortcut:** `Ctrl + K, N` (Win/Linux) / `Cmd + K, N` (Mac)

**Description:** Opens command palette, then press N to create a new empty chat, clearing the current conversation and resetting the view.

**Behavior:**
1. Press `Ctrl/Cmd + K` to open command palette mode (enter "listening" state)
2. Press `N` within 2 seconds to create a new chat
3. Press `Esc` to cancel command palette
4. Clears the current chat selection
5. Shows the welcome screen
6. Clears the message input field
7. Notifies the backend that no chat is active
8. Generates a temporary chat ID for draft saving

**Rationale:**
- **Modern UX Pattern**: Uses command palette pattern like VS Code, GitHub, Figma (very familiar to developers)
- **Zero Browser Conflicts**: Doesn't conflict with any browser shortcuts
- **More Intuitive**: Separated into two keystrokes makes it intentional and discoverable
- **Extensible**: Easy to add more commands (K+S for search, K+C for copy, etc.)
- **Cross-platform**: Works identically on all browsers and operating systems

**Implementation Details:**
- `Ctrl/Cmd + K` enters command palette mode
- While in command mode, single letters trigger actions (N for new)
- Command palette automatically cancels after 2 seconds or on `Esc` key
- Dispatches `chatDeselected` event
- Triggers scale-down animation for visual feedback
- Available globally when authenticated
- No browser conflicts - fully reliable

**Code References:**
- Component: `ActiveChat.svelte`
- Handler: `handleNewChatClick()`
- KeyboardShortcuts: Line 76-107 (command palette implementation)

---

#### Download Current Chat
**Shortcut:** `Ctrl + Shift + S` (Win/Linux) / `Cmd + Shift + S` (Mac)

**Description:** Downloads the currently open chat conversation as a file.

**Behavior:**
- Only available when a chat is open
- Downloads complete chat history with messages
- Preserves formatting and embedded content metadata
- Follows the same behavior as the download option in the context menu

**Rationale:** 
- `Ctrl/Cmd + Shift + S` follows the "Save As" convention familiar to users
- Avoids conflict with browser's native `Ctrl + S` (save page)
- Avoids conflict with browser's `Ctrl + D` (bookmark)

**Implementation Status:** 🚧 To be implemented
- Needs to be added to `KeyboardShortcuts.svelte`
- Needs handler in `ActiveChat.svelte`
- Should reuse logic from `ChatContextMenu.svelte`

**Proposed Implementation:**
```typescript
// In KeyboardShortcuts.svelte
if ((isMac ? event.metaKey : event.ctrlKey) && event.shiftKey && event.key === 's') {
  event.preventDefault();
  dispatch('downloadChat');
}

// In ActiveChat.svelte
<KeyboardShortcuts
  on:downloadChat={handleDownloadChat}
  ...
/>
```

---

#### Copy Current Chat
**Shortcut:** `Ctrl + Shift + C` (Win/Linux) / `Cmd + Shift + C` (Mac)

**Description:** Copies the entire current chat conversation to clipboard.

**Behavior:**
- Only available when a chat is open
- Copies all messages in plain text format
- Preserves message structure and sender information
- Shows a brief confirmation message
- Follows the same behavior as the copy option in the context menu

**Rationale:**
- `Ctrl/Cmd + Shift + C` is a natural extension of the standard copy command
- Commonly used in developer tools and terminal applications
- Distinct from `Ctrl/Cmd + C` which copies selected text only

**Implementation Status:** 🚧 To be implemented
- Needs to be added to `KeyboardShortcuts.svelte`
- Needs handler in `ActiveChat.svelte`
- Should reuse logic from `ChatContextMenu.svelte`

**Proposed Implementation:**
```typescript
// In KeyboardShortcuts.svelte
if ((isMac ? event.metaKey : event.ctrlKey) && event.shiftKey && event.key === 'c') {
  event.preventDefault();
  dispatch('copyChat');
}

// In ActiveChat.svelte
<KeyboardShortcuts
  on:copyChat={handleCopyChat}
  ...
/>
```

---

#### Toggle Chat History
**Shortcut:** `Ctrl + Shift + H` (Win/Linux) / `Cmd + Shift + H` (Mac)

**Description:** Shows or hides the chat history sidebar (`Chats.svelte`).

**Behavior:**
- Toggles the visibility of the chat list panel
- On mobile: Opens/closes as a modal overlay
- On desktop: Shows/hides the sidebar
- State is managed by `panelStateStore`

**Rationale:**
- `H` mnemonic for "History"
- `Ctrl/Cmd + Shift + H` avoids conflicts with browser history (`Ctrl + H`)
- Consistent with sidebar toggle patterns in applications like VS Code (`Ctrl + B`)
- Alternative considered: `Ctrl + Shift + L` for "List" (also acceptable)

**Implementation Status:** 🚧 To be implemented
- Needs to be added to `KeyboardShortcuts.svelte`
- Needs to dispatch event that toggles `panelState.toggleChats()`

**Proposed Implementation:**
```typescript
// In KeyboardShortcuts.svelte
if ((isMac ? event.metaKey : event.ctrlKey) && event.shiftKey && event.key === 'h') {
  event.preventDefault();
  dispatch('toggleChatHistory');
}

// In parent component (e.g., +page.svelte)
function handleToggleChatHistory() {
  panelState.toggleChats();
}
```

---

#### Navigate to Next Chat
**Shortcut:** `Ctrl + Shift + →` (Win/Linux) / `Cmd + Shift + →` (Mac)

**Description:** Selects the next chat in the chat history list.

**Behavior:**
- Moves selection down through the chat list
- If no chat is selected, selects the first chat
- If at the end of the list, stays at the last chat
- Automatically loads the selected chat
- Works even when chat history panel is closed

**Implementation Details:**
- Navigates through `flattenedNavigableChats` array
- Maintains selection state
- Component: `Chats.svelte`
- Handler: `navigateToNextChat()`
- KeyboardShortcuts: Line 83-91

---

#### Navigate to Previous Chat
**Shortcut:** `Ctrl + Shift + ←` (Win/Linux) / `Cmd + Shift + ←` (Mac)

**Description:** Selects the previous chat in the chat history list.

**Behavior:**
- Moves selection up through the chat list
- If no chat is selected, selects the first chat
- If at the start of the list, stays at the first chat
- Automatically loads the selected chat
- Works even when chat history panel is closed

**Implementation Details:**
- Navigates through `flattenedNavigableChats` array
- Maintains selection state
- Component: `Chats.svelte`
- Handler: `navigateToPreviousChat()`
- KeyboardShortcuts: Line 83-91

---

### Navigation

#### Focus Message Input
**Shortcut:** `Shift + Enter`

**Description:** Moves keyboard focus to the message input field.

**Behavior:**
- Only works when input field is NOT currently focused
- Places cursor at the end of existing content
- Does not trigger message sending
- Useful for quick navigation from chat history

**Implementation Details:**
- Component: `ActiveChat.svelte`
- Handler: `messageInputFieldRef.focus()`
- KeyboardShortcuts: Line 64-69

---

#### Scroll to Top
**Shortcut:** `Ctrl + Shift + ↑` (Win/Linux) / `Cmd + Shift + ↑` (Mac)

**Description:** Scrolls the chat view to the top (oldest messages).

**Behavior:**
- Instantly scrolls to the beginning of the conversation
- Useful for reviewing chat history
- Works regardless of current scroll position

**Implementation Details:**
- Component: `ActiveChat.svelte`
- Handler: `chatHistoryRef.scrollToTop()`
- KeyboardShortcuts: Line 72-80

---

#### Scroll to Bottom
**Shortcut:** `Ctrl + Shift + ↓` (Win/Linux) / `Cmd + Shift + ↓` (Mac)

**Description:** Scrolls the chat view to the bottom (newest messages).

**Behavior:**
- Instantly scrolls to the end of the conversation
- Useful for returning to latest messages
- Works regardless of current scroll position

**Implementation Details:**
- Component: `ActiveChat.svelte`
- Handler: `chatHistoryRef.scrollToBottom()`
- KeyboardShortcuts: Line 72-80

---

## Context-Specific Behavior

### When Message Input is Focused
- `Shift + Enter` does NOT work (as input is already focused)
- Standard text editing shortcuts work (copy, paste, select all, etc.)

### When Message Input is NOT Focused
- `Shift + Enter` focuses the input field
- Chat navigation shortcuts work
- Scroll shortcuts work
- Global shortcuts (new chat, toggle history) work

### When Chat History is Open
- Chat navigation shortcuts (next/previous) work
- Can still use global shortcuts
- Close button available in UI

### When No Chat is Open
- New chat shortcut is available (though creates empty state)
- Download and copy shortcuts are disabled (no content to act on)
- Navigation shortcuts have no effect

---

## Browser Conflicts and Solutions

### Potential Conflicts

| Shortcut | Browser Action | Our Solution | Success Rate |
|----------|---------------|--------------|--------------|
| `Ctrl + Shift + N` | New incognito/private window | We call `event.preventDefault()` to override (less frequently used in-app) | ⚠️ Varies by browser |
| `Ctrl + Shift + C` | Dev tools inspect | Different context - our shortcut works in app, dev tools requires element selection first | ✅ High |
| `Ctrl + Shift + S` | Save page as | We call `event.preventDefault()` to override | ✅ High |
| `Ctrl + H` | Browser history | We use `Ctrl + Shift + H` instead | ✅ High |
| `Ctrl + D` | Bookmark page | We use `Ctrl + Shift + S` for download instead | ✅ High |
| `Ctrl + N` | New window | We use `Ctrl + Shift + N` instead (more frequently needed than incognito) | N/A |

### Browser-Specific Notes

**Arc Browser:**
- `Cmd + Shift + N` may still open incognito tab despite our override attempts
- Arc captures some shortcuts at a deeper OS level
- **Workaround**: Use the UI button for new chat

**Chrome/Edge:**
- Most shortcuts work reliably with our override
- `Ctrl/Cmd + Shift + N` has mixed results

**Firefox:**
- Generally respects `preventDefault()` well
- Shortcuts work reliably

**Safari:**
- Some shortcuts may be captured by macOS before reaching the web page
- Test all shortcuts after deployment

### Testing Recommendations

When implementing new shortcuts, always:
1. Test on all major browsers (Chrome, Firefox, Safari, Edge)
2. Test on both Mac and Windows/Linux
3. Call `event.preventDefault()` to prevent browser defaults
4. Document any unavoidable conflicts
5. Provide UI alternatives for all keyboard actions

---

## Implementation Checklist

### Currently Implemented ✅
- [x] Create New Chat (`Ctrl/Cmd + K, N`) - **Modern command palette pattern, works everywhere**
- [x] Focus Message Input (`Shift + Enter`)
- [x] Scroll to Top (`Ctrl/Cmd + Shift + ↑`)
- [x] Scroll to Bottom (`Ctrl/Cmd + Shift + ↓`)
- [x] Next Chat (`Ctrl/Cmd + Shift + →`)
- [x] Previous Chat (`Ctrl/Cmd + Shift + ←`)
- [x] Download Current Chat (`Ctrl/Cmd + Shift + S`)
- [x] Copy Current Chat (`Ctrl/Cmd + Shift + C`)
- [x] Toggle Chat History (`Ctrl/Cmd + Shift + H`)

### To Be Implemented 🚧
- [ ] None - all planned shortcuts implemented!

### Removed/Not Yet Implemented ❌
- [ ] Voice Recording Shortcuts (Hold Space, etc.) - Audio recording feature pending implementation

---

## Implementation Guide

### Adding a New Keyboard Shortcut

1. **Add to KeyboardShortcuts.svelte**
   ```typescript
   // In the handleKeyDown function
   if ((isMac ? event.metaKey : event.ctrlKey) && event.shiftKey && event.key === 'yourKey') {
     event.preventDefault(); // Prevent browser default
     dispatch('yourEventName');
   }
   ```

2. **Add Handler in Parent Component**
   ```typescript
   // In the component that uses KeyboardShortcuts
   function handleYourAction() {
     // Implementation
   }
   ```

3. **Connect in Template**
   ```svelte
   <KeyboardShortcuts
     on:yourEventName={handleYourAction}
     ...
   />
   ```

4. **Update This Documentation**
   - Add to quick reference table
   - Add detailed section
   - Update implementation checklist

5. **Add Translation Keys**
   ```json
   // In translations file
   "shortcuts.yourAction.text": "Your Action",
   "shortcuts.yourAction.description": "Description of what it does"
   ```

6. **Add Tooltip/Help Text**
   - Add keyboard shortcut indicator to relevant UI elements
   - Consider adding a keyboard shortcuts help modal/page

---

## Accessibility Considerations

### Screen Readers
- All keyboard shortcuts should have equivalent click/tap actions in the UI
- Use ARIA labels to indicate keyboard shortcut availability
- Consider announcing shortcut availability in focus states

### Keyboard-Only Navigation
- All shortcuts should work without mouse/touch input
- Focus states should be clearly visible
- Tab order should be logical

### Customization (Future Enhancement)
Consider allowing users to:
- View all available shortcuts (shortcuts help page)
- Customize key bindings
- Disable specific shortcuts if they conflict with assistive technology

---

## Future Enhancements

### Potential Additional Shortcuts
- Search in chat: `Ctrl/Cmd + F`
- Search across chats: `Ctrl/Cmd + Shift + F`
- Quick mate selection: `