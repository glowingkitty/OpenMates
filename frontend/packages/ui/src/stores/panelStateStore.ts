import { writable, derived, get } from 'svelte/store';
import { authStore } from './authStore';
import { isInSignupProcess, isLoggingOut } from './signupState';
import { isMobileView } from './uiStateStore';

type ActivityHistoryUserIntent = 'auto' | 'closed';

// --- Internal Writable Stores ---
const _isActivityHistoryOpen = writable<boolean>(false);
const _isSettingsOpen = writable<boolean>(false);
const _activityHistoryUserIntent = writable<ActivityHistoryUserIntent>('auto');

// --- Actions ---

/**
 * Toggles the Activity History panel based on user interaction.
 * Updates the user intent.
 * CRITICAL: Does not allow opening during signup process - panel must remain closed.
 */
function toggleChats(): void {
    const currentlyOpen = get(_isActivityHistoryOpen);
    const mobileView = get(isMobileView); // Get current mobile state
    const inSignupProcess = get(isInSignupProcess); // Check if user is in signup process

    console.debug('[PanelState] toggleChats called:', {
        currentlyOpen,
        mobileView,
        inSignupProcess,
        timestamp: Date.now()
    });

    // CRITICAL: Never allow opening during signup process - panel must remain closed
    if (inSignupProcess) {
        console.debug('[PanelState] Blocked toggleChats - user is in signup process, panel must remain closed');
        // Ensure panel is closed if somehow it got opened
        _isActivityHistoryOpen.set(false);
        _activityHistoryUserIntent.set('closed');
        return;
    }

    if (currentlyOpen) {
        // User is manually closing it
        console.debug('[PanelState] Closing chats panel');
        _activityHistoryUserIntent.set('closed');
        // Explicitly close on mobile for immediate effect, otherwise rely on derived store
        if (mobileView) {
            _isActivityHistoryOpen.set(false);
        }
        // Note: Derived store will still run and confirm false on mobile.
        // On desktop, derived store handles closing based on intent.
    } else {
        // User is manually opening it (overrides 'auto' logic temporarily)
        // Keep original logic for opening, as the header button seems to work.
        console.debug('[PanelState] Opening chats panel');
        _activityHistoryUserIntent.set('auto'); // Allow auto logic to take over again if conditions change
        _isActivityHistoryOpen.set(true); // Force open immediately
    }
    // Note: The derived store will recalculate and might override the forced open/close
    // if conditions (like mobile view or signup process) dictate it.
}

/**
 * Opens the Settings panel.
 */
function openSettings(): void {
    _isSettingsOpen.set(true);
}

/**
 * Closes the Settings panel.
 */
function closeSettings(): void {
    _isSettingsOpen.set(false);
}

/**
 * Resets the user intent for Activity History, allowing auto-logic to take over.
 * Useful when conditions change (e.g., login/logout).
 */
function resetActivityHistoryIntent(): void {
    _activityHistoryUserIntent.set('auto');
}


// --- Derived State Logic ---

// Determine the *intended* state of Activity History based on conditions
const intendedActivityHistoryOpen = derived(
    [authStore, isInSignupProcess, isLoggingOut, isMobileView, _activityHistoryUserIntent],
    ([$authStore, $isInSignupProcess, $isLoggingOut, $isMobileView, $activityHistoryUserIntent]) => {
        // CHANGED: Allow non-authenticated users to see the sidebar (with demo chats)
        // Only close during signup process or logout
        if ($isInSignupProcess || $isLoggingOut) {
            console.debug('[PanelState] Intended AH Closed: In Signup/Logout');
            return false; // Must be closed during signup or logout
        }
        if ($isMobileView) {
            console.debug('[PanelState] Intended AH Closed: Mobile View');
            return false; // Must be closed on mobile
        }
        if ($activityHistoryUserIntent === 'closed') {
            console.debug('[PanelState] Intended AH Closed: User Manually Closed');
            return false; // Must be closed if user manually closed it
        }
        // If none of the above, it should be open on desktop (both authenticated and non-authenticated)
        console.debug('[PanelState] Intended AH Open: Default Desktop State');
        return true;
    }
);

// Determine the *intended* state of Settings (simpler logic)
const intendedSettingsOpen = derived(
    [authStore, isInSignupProcess, isLoggingOut, _isSettingsOpen],
     ([$authStore, $isInSignupProcess, $isLoggingOut, $isSettingsOpen]) => {
        if (!$authStore.isAuthenticated || $isLoggingOut) {
             console.debug('[PanelState] Intended Settings Closed: Not Authenticated or Logging out');
            return false; // Close settings if not authenticated or logging out
        }
        // Otherwise, respect the current state (_isSettingsOpen) set by actions
        return $isSettingsOpen;
    }
);


// --- Subscriptions to update actual state based on intended state ---

intendedActivityHistoryOpen.subscribe(intendedState => {
    if (get(_isActivityHistoryOpen) !== intendedState) {
        console.debug(`[PanelState] Updating Activity History Open: ${get(_isActivityHistoryOpen)} -> ${intendedState}`);
        _isActivityHistoryOpen.set(intendedState);
    }
});

intendedSettingsOpen.subscribe(intendedState => {
    // Only close reactively. Opening is handled by explicit actions.
    if (!intendedState && get(_isSettingsOpen)) {
         console.debug(`[PanelState] Reactively Closing Settings: ${get(_isSettingsOpen)} -> ${intendedState}`);
        _isSettingsOpen.set(false);
    }
    // We don't automatically open settings here, only close based on auth/logout state.
    // Actual opening happens via openSettings() action.
});

// Reset user intent when auth state changes significantly (login/logout)
// Subscribe specifically to isAuthenticated and isLoggingOut
derived([authStore, isLoggingOut], ([$authStore, $isLoggingOut]) => ({isAuthenticated: $authStore.isAuthenticated, isLoggingOut: $isLoggingOut}))
    .subscribe(authChanges => {
        console.debug('[PanelState] Auth state changed, resetting Activity History user intent to auto.');
        resetActivityHistoryIntent();
});

// CRITICAL: Immediately close panel when signup process starts
// This ensures the panel is closed even if it was opened before signup detection
isInSignupProcess.subscribe(inSignup => {
    if (inSignup) {
        console.debug('[PanelState] Signup process started - immediately closing Activity History panel');
        _isActivityHistoryOpen.set(false);
        _activityHistoryUserIntent.set('closed');
    }
});


// --- Exports ---
export const panelState = {
    subscribe: derived(
        [_isActivityHistoryOpen, _isSettingsOpen],
        ([$_isActivityHistoryOpen, $_isSettingsOpen]) => ({
            isActivityHistoryOpen: $_isActivityHistoryOpen,
            isSettingsOpen: $_isSettingsOpen,
        })
    ).subscribe,
    toggleChats,
    openSettings,
    closeSettings,
    // Expose reset for potential use elsewhere if needed, e.g., deep linking
    resetActivityHistoryIntent
};

// Optional: Export individual states if needed directly elsewhere, though panelState is preferred
export const isActivityHistoryOpen = derived(_isActivityHistoryOpen, state => state);
export const isSettingsOpen = derived(_isSettingsOpen, state => state);