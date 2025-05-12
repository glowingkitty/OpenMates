// frontend/packages/ui/src/stores/authState.ts
/**
 * @fileoverview Manages the core authentication state for the application.
 * Includes the main writable store for authentication status and initialization,
 * as well as flags for tracking ongoing authentication checks and device verification needs.
 */

import { writable } from 'svelte/store';
import type { AuthState } from './authTypes';

// Create the initial state based on the AuthState interface
const initialState: AuthState = {
  isAuthenticated: false, // User is not authenticated by default
  isInitialized: false    // Auth state has not been checked initially
};

// Export auth checking state - Tracks if an auth check (e.g., session check) is in progress.
export const isCheckingAuth = writable<boolean>(false);

// Export state for device verification requirement - Tracks if the current device needs 2FA verification.
export const needsDeviceVerification = writable<boolean>(false);

// Create the main writable store for authentication state
// This store holds whether the user is fully authenticated and if the initial check is done.
const mainAuthStore = writable<AuthState>(initialState);

// Export the main auth store and its update method for use by actions
export const authStore = {
    subscribe: mainAuthStore.subscribe,
    set: mainAuthStore.set,
    update: mainAuthStore.update
};

// Export the initial state for potential resets or comparisons
export { initialState as authInitialState };