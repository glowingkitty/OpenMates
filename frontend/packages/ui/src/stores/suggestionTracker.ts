// frontend/packages/ui/src/stores/suggestionTracker.ts
// Tracks clicked new chat suggestions so they can be deleted after the message is sent

import { writable } from 'svelte/store';

/**
 * Interface for tracking clicked new chat suggestion
 * We need both the decrypted text (for UI) and encrypted text (for server deletion)
 */
export interface ClickedSuggestion {
    text: string;           // Decrypted suggestion text
    encrypted: string;      // Encrypted suggestion text (for server deletion)
}

/**
 * Store to track the last clicked new chat suggestion.
 * When a user clicks a suggestion and then sends it as a message,
 * we delete this suggestion from both client and server storage.
 */
export const clickedNewChatSuggestion = writable<ClickedSuggestion | null>(null);

/**
 * Set the clicked suggestion with both decrypted and encrypted text
 */
export function setClickedSuggestion(suggestionText: string, encryptedSuggestion: string) {
    console.debug('[SuggestionTracker] Tracked clicked suggestion:', suggestionText);
    console.log('[SuggestionTracker] STORE DEBUG 1: setClickedSuggestion called with:', {
        text: `${suggestionText.substring(0, 50)}...`,
        encrypted: `${encryptedSuggestion.substring(0, 20)}...`
    });
    clickedNewChatSuggestion.set({
        text: suggestionText,
        encrypted: encryptedSuggestion
    });
    console.log('[SuggestionTracker] STORE DEBUG 2: Store updated');
}

/**
 * Clear the tracked suggestion (after deletion or when no longer needed)
 */
export function clearClickedSuggestion() {
    console.debug('[SuggestionTracker] Cleared tracked suggestion');
    console.log('[SuggestionTracker] STORE DEBUG 3: clearClickedSuggestion called');
    clickedNewChatSuggestion.set(null);
}

/**
 * Get the current clicked suggestion and clear it atomically
 * Returns the encrypted text for server deletion, or null if no suggestion tracked
 */
export function consumeClickedSuggestion(): string | null {
    let current: ClickedSuggestion | null = null;
    clickedNewChatSuggestion.subscribe(value => {
        current = value;
    })();
    
    console.log('[SuggestionTracker] STORE DEBUG 4: consumeClickedSuggestion called, current value:', {
        hasValue: !!current,
        text: current ? `${current.text.substring(0, 50)}...` : null,
        encrypted: current ? `${current.encrypted.substring(0, 20)}...` : null
    });
    
    if (current) {
        console.log('[SuggestionTracker] STORE DEBUG 5: Found suggestion to consume, clearing store');
        clearClickedSuggestion();
        console.log('[SuggestionTracker] STORE DEBUG 6: Returning encrypted suggestion:', `${current.encrypted.substring(0, 20)}...`);
        return current.encrypted; // Return encrypted text for server
    }
    
    console.log('[SuggestionTracker] STORE DEBUG 5B: No suggestion found to consume');
    return null;
}

