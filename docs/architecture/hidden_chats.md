# Hidden Chats Architecture

## Overview

Hidden chats allow users to protect sensitive conversations with a 4-6 digit code. Hidden chats remain invisible in the main chat list but appear in a separate password-protected section. The feature uses code-derived encryption to maintain zero-knowledge architecture: the server never sees the code or can access hidden chat content without it.

## User Experience

- **Always-visible menu**: "Show hidden chats" clickable text appears at the top of the chat list regardless of whether hidden chats exist (prevents external observation of hidden chat existence).
- **Code protection**: User sets a 4-6 digit code on first hide or when accessing the hidden chats menu
- **Separate section**: Hidden chats display in a scrollable area above the main chat list after entering the correct code
- **Lock/Unlock controls**: "Unlock hidden chats" button unlocks for this session; "Lock hidden chats" button immediately clears from memory and DOM
- **Auto-lock**: Hidden chats automatically lock after N minutes of inactivity (no interaction), clearing from memory and DOM
- **Context menu action**: "Hide" option available in ChatContextMenu alongside existing Download/Copy/Delete options

## Architecture

### Chat Model Changes

**No database schema changes needed.** Hidden chats are distinguished by decryption attempt result, not by a flag.

### Encryption Flow

**Visible Chats** (existing):
```
Login → Master Key → encryption_key_user_local → encryption_key_chat → Chat Content
```

**Hidden Chats** (new):
```
Master Key + 4-6 digit code → Argon2(master_key || code, salt) → combined_secret → encryption_key_chat → Chat Content
```

### Hidden Chat Detection & Memory Management

- **Detection**: No `is_hidden` flag stored
  - When loading chat: Try decrypt with master_key (fast path for visible chats)
  - If decryption fails: Try decrypt with combined_secret (hidden chat path)
  - Decryption success/failure determines visibility
  - Server cannot distinguish hidden from visible chats
  - Prevents enumeration attacks on chat hidden status

- **Memory state**: Hidden chats stored in client memory only when unlocked
  - Decrypted keys loaded into volatile state on code entry
  - Cleared from memory immediately on manual lock or auto-lock
  - Not persisted in localStorage (sessionStorage for code only, not decrypted data)

- **Code derivation**:
  - Combined secret: `PBKDF2(master_key || code, salt)` (Note: Architecture doc mentions Argon2, but implementation uses PBKDF2 for consistency with login flow)
  - Salt: User-specific, reuses `user_email_salt` from localStorage/sessionStorage (same across devices)
  - **CRITICAL**: Salt must be the same across all devices for the same user to enable cross-device decryption
  - The email salt is perfect for this: already user-specific, stored securely, and available after login
  - KDF: PBKDF2 with 100,000 iterations (matching login flow strength)
  - Scope: **Each chat can be encrypted with a different code**
    - When hiding a chat, the user enters a code (or uses the currently unlocked code)
    - The chat key is encrypted with `combined_secret = PBKDF2(master_key || code, salt)`
    - When unlocking, the user enters a code, and the system tries to decrypt all chats that failed normal decryption
    - Only chats encrypted with the entered code will decrypt and be shown
    - If no chats decrypt, the system shows "No hidden chats unlocked" (code may be wrong or no chats use that code)
    - This allows power users to have different sets of hidden chats visible with different codes

## Sync Considerations

### Phase 1-3 Behavior
- All chats (hidden and visible) included in normal phased sync—**no sync changes needed**
- Server makes no distinction between hidden and visible chats
- Client decryption failure naturally filters out locked hidden chats from display
- Chat with hidden key appears as decryption failure (treated same as corrupted chat until code entered)

### Multi-Device Flow
1. User hides chat on Device A (sets code, derives combined_secret, encrypts chat_key with it)
2. Chat syncs to Device B during phase 1-3 sync (server doesn't know it's hidden)
3. Device B receives encrypted chat with key encrypted via combined_secret
4. Device B cannot decrypt chat content (decryption fails) until code entered
5. Hidden chats appear in locked section with "Unlock hidden chats" button
6. User enters code on Device B, derives combined_secret independently
7. Hidden chat decryption succeeds, chat visible until manual or auto-lock

### Important: Chat Title Encryption
- Titles encrypted with `encryption_key_chat` (same as content)
- Code-protecting the chat key also protects titles
- Server cannot see title of hidden chats
- Prevents title enumeration attacks

## Security Properties

- ✅ **Zero-knowledge**: Server never sees code, code-derived secret, or plaintext hidden chat data
- ✅ **Indistinguishability**: Server cannot tell if a chat is hidden or just corrupted (failed decryption)
- ✅ **Metadata privacy**: Chat titles protected by combined_secret (not separate from content)
- ✅ **Information hiding**: Always-visible menu doesn't leak hidden chat existence; decryption failure is indistinguishable from corruption
- ✅ **Key isolation**: Hidden and visible chats use different decryption paths (master_key vs. master_key + code)
- ✅ **Cross-device compatibility**: Same user on different devices generates the same salt (user_id only), enabling hidden chats to be decrypted across devices with the same code
- ✅ **Inactivity protection**: Auto-lock removes decrypted secrets from memory after N minutes

## Implementation Notes

### Code Strength & Derivation
- **4-6 digits**: Weak in isolation (1M combinations) but sufficient when combined with master_key via Argon2
- **Master_key dependency**: Attack requires both knowing the 4-6 digit code AND having access to the master_key (requires compromised device or stolen local storage)
- **Client-side rate limiting**: 3 failed attempts → 30 second lockout to prevent brute force

### Lock/Unlock State Machine
**Locked state:**
- Hidden chats encrypted in local storage (sync)
- No derived keys in memory
- "Unlock hidden chats" button visible
- Chat content not readable (appears as decryption failure)

**Unlocked state:**
- Derived combined_secret in volatile memory only
- Hidden chat keys decrypted and available for chat rendering
- "Lock hidden chats" button visible
- Activity timer running (N minutes)

**Auto-lock trigger:**
- No interaction with hidden chats for N minutes
- Clear combined_secret from memory
- Remove hidden chats from DOM
- Reset to locked state

### Storage Duration
- **Code storage**: SessionStorage (lost on page close) or localStorage with explicit manual lock
- **Decrypted secrets**: Volatile memory only (never persisted)
- **Code entry**: Required per-session; optional 30-min idle timeout

### Future Enhancements
- Client-side brute-force detection and temporary account lockout
- Search integration (searchable only while unlocked)
