// frontend/packages/ui/src/stores/authStore.ts
/**
 * @fileoverview Central export point for authentication-related stores and actions.
 * This file aggregates exports from the various auth modules (state, types, actions, derived stores)
 * to provide a unified interface for the rest of the application.
 */

import {
  authStore as coreAuthStore,
  isCheckingAuth,
  needsDeviceVerification,
  deviceVerificationType,
  deviceVerificationReason,
  authInitialState,
} from "./authState";
import * as sessionActions from "./authSessionActions";
import * as loginLogoutActions from "./authLoginLogoutActions";
import * as miscActions from "./authMiscActions";
import * as derivedStores from "./authDerivedStores";

// Combine the core store with all action functions
export const authStore = {
  ...coreAuthStore,
  ...sessionActions,
  ...loginLogoutActions,
  ...miscActions,
};

// Re-export everything for individual use if needed
export {
  isCheckingAuth,
  needsDeviceVerification,
  deviceVerificationType,
  deviceVerificationReason,
  authInitialState,
};
export * from "./authTypes";
export * from "./authSessionActions";
export * from "./authLoginLogoutActions";
export * from "./authMiscActions";
export * from "./authDerivedStores";
