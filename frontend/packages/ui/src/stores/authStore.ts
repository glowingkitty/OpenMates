// frontend/packages/ui/src/stores/authStore.ts
/**
 * @fileoverview Central export point for authentication-related stores and actions.
 * This file aggregates exports from the various auth modules (state, types, actions, derived stores)
 * to provide a unified interface for the rest of the application.
 */

// Export core state and flags
export { authStore, isCheckingAuth, needsDeviceVerification, authInitialState } from './authState';

// Export types
export type { AuthState, SessionCheckResult, LoginResult, LogoutCallbacks } from './authTypes';

// Export actions
export { checkAuth, initialize } from './authSessionActions';
export { login, logout } from './authLoginLogoutActions';
export { setup2FAProvider, completeSignup, updateUser, setAuthenticated } from './authMiscActions';

// Export derived stores
export { profileImage } from './authDerivedStores';

// Note: The original createAuthStore function and its instance are no longer needed here
// as the logic is now distributed across the imported modules.
// The exported `authStore` from './authState' provides the core state management.
