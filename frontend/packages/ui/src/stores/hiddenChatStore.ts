/**
 * Hidden Chat Store
 *
 * Manages the locked/unlocked state of hidden chats and tracks activity for auto-lock.
 * State is stored in volatile memory only (never persisted).
 */

import { writable, derived } from 'svelte/store';
import { browser } from '$app/environment';
import { hiddenChatService } from '../services/hiddenChatService';

// Auto-lock configuration
const AUTO_LOCK_INACTIVITY_MS = 5 * 60 * 1000; // 5 minutes of inactivity

interface HiddenChatState {
    isUnlocked: boolean;
    isLockedOut: boolean;
    lockoutRemainingSeconds: number;
    lastActivityTime: number | null;
}

function createHiddenChatStore() {
    const { subscribe, set, update } = writable<HiddenChatState>({
        isUnlocked: false,
        isLockedOut: false,
        lockoutRemainingSeconds: 0,
        lastActivityTime: null
    });

    let autoLockTimer: ReturnType<typeof setTimeout> | null = null;
    let lockoutCheckInterval: ReturnType<typeof setInterval> | null = null;

    /**
     * Initialize store - ensure hidden chats are locked on page reload
     * For security, hidden chats must be explicitly unlocked by entering the password
     * after each page reload. The combined secret is stored in volatile memory only
     * and does not survive page reloads.
     */
    function init() {
        if (!browser) {
            return;
        }

        // CRITICAL: Always start in locked state on page reload for security
        // The combined secret is stored in volatile memory only and is automatically cleared on page reload
        // User must explicitly unlock by entering the password after each page reload
        // Note: The password may still be in sessionStorage for convenience, but we don't auto-unlock with it

        // Start lockout check interval
        startLockoutCheckInterval();
    }

    /**
     * Unlock hidden chats with a password
     * Tries to decrypt all hidden chats with the entered password.
     * Returns success status and count of decrypted chats.
     * 
     * @param password - Password (4-30 characters) entered by user
     * @param verifiedEncryptedChatKey - Optional: If provided, verify this encrypted chat key can be decrypted with the password
     * @returns Promise<{ success: boolean; decryptedCount: number }> - Success status and count of decrypted chats
     */
    async function unlockHiddenChats(password: string, verifiedEncryptedChatKey?: string): Promise<{ success: boolean; decryptedCount: number }> {
        try {
            const result = await hiddenChatService.unlockHiddenChats(password, verifiedEncryptedChatKey);
            if (result.success) {
                update(state => ({
                    ...state,
                    isUnlocked: true,
                    isLockedOut: false,
                    lockoutRemainingSeconds: 0,
                    lastActivityTime: Date.now()
                }));
                startAutoLockTimer();
                
                // Dispatch event to notify UI components (e.g., SettingsUsage)
                if (browser) {
                    window.dispatchEvent(new CustomEvent('hiddenChatsUnlocked'));
                }
                
                return result;
            } else {
                // Update lockout state
                updateLockoutState();
                return result;
            }
        } catch (error) {
            console.error('[HiddenChatStore] Error unlocking hidden chats:', error);
            updateLockoutState();
            throw error;
        }
    }

    /**
     * Lock hidden chats manually
     * Clears combined secret and all decrypted chat keys from memory
     */
    async function lockHiddenChats(): Promise<void> {
        await hiddenChatService.lockHiddenChats();
        update(state => ({
            ...state,
            isUnlocked: false,
            lastActivityTime: null
        }));
        stopAutoLockTimer();
        
        // Dispatch event to notify UI to refresh chat list (hidden chats will disappear)
        if (browser) {
            window.dispatchEvent(new CustomEvent('hiddenChatsLocked'));
        }
    }

    /**
     * Record activity on hidden chats (resets auto-lock timer)
     */
    function recordActivity(): void {
        update(state => {
            if (state.isUnlocked) {
                return {
                    ...state,
                    lastActivityTime: Date.now()
                };
            }
            return state;
        });
        // Restart auto-lock timer
        startAutoLockTimer();
    }

    /**
     * Start auto-lock timer
     */
    function startAutoLockTimer(): void {
        stopAutoLockTimer(); // Clear any existing timer

        autoLockTimer = setTimeout(() => {
            console.debug('[HiddenChatStore] Auto-locking hidden chats due to inactivity');
            lockHiddenChats();
            
            // Dispatch event to notify UI
            if (browser) {
                window.dispatchEvent(new CustomEvent('hiddenChatsAutoLocked'));
            }
        }, AUTO_LOCK_INACTIVITY_MS);
    }

    /**
     * Stop auto-lock timer
     */
    function stopAutoLockTimer(): void {
        if (autoLockTimer) {
            clearTimeout(autoLockTimer);
            autoLockTimer = null;
        }
    }

    /**
     * Start interval to check lockout state
     */
    function startLockoutCheckInterval(): void {
        if (lockoutCheckInterval) {
            return; // Already started
        }

        lockoutCheckInterval = setInterval(() => {
            updateLockoutState();
        }, 1000); // Check every second
    }

    /**
     * Stop lockout check interval
     */
    function stopLockoutCheckInterval(): void {
        if (lockoutCheckInterval) {
            clearInterval(lockoutCheckInterval);
            lockoutCheckInterval = null;
        }
    }

    /**
     * Update lockout state from service
     */
    function updateLockoutState(): void {
        const remainingSeconds = hiddenChatService.getRemainingLockoutTime();
        const isLockedOut = remainingSeconds > 0;

        update(state => ({
            ...state,
            isLockedOut,
            lockoutRemainingSeconds: remainingSeconds
        }));
    }

    // Initialize on store creation
    if (browser) {
        init();
    }

    return {
        subscribe,

        /**
         * Unlock hidden chats with a password
         */
        unlock: unlockHiddenChats,

        /**
         * Lock hidden chats manually
         */
        lock: lockHiddenChats,

        /**
         * Record activity (resets auto-lock timer)
         */
        recordActivity,

        /**
         * Check if hidden chats are unlocked
         */
        isUnlocked: () => {
            let value = false;
            subscribe(state => value = state.isUnlocked)();
            return value;
        },

        /**
         * Get current state (for one-time reads)
         */
        get: () => {
            let state: HiddenChatState = {
                isUnlocked: false,
                isLockedOut: false,
                lockoutRemainingSeconds: 0,
                lastActivityTime: null
            };
            subscribe(s => state = s)();
            return state;
        }
    };
}

export const hiddenChatStore = createHiddenChatStore();




