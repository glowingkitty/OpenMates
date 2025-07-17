// frontend/packages/ui/src/stores/authTypes.ts
/**
 * @fileoverview Defines the TypeScript types and interfaces used within the authentication stores.
 * This includes the shape of the authentication state, API response types for session checks and login,
 * and the structure of the user profile data.
 */

import type { UserProfile } from './userProfile'; // Assuming userProfile types are correctly defined here

// Define the types for the auth store state
export interface AuthState {
  isAuthenticated: boolean; // Represents full authentication (session valid AND device known)
  isInitialized: boolean; // Indicates if the initial auth check has completed
}

// Define return type for session check API response
export interface SessionCheckResult {
    success: boolean;
    user?: UserProfile; // Use UserProfile type from userProfile store
    message?: string;
    re_auth_required?: '2fa' | null; // Indicates if device verification (2FA) is needed
    token_refresh_needed?: boolean;
    require_invite_code?: boolean; // Indicates if invite code is required for signup
}

// Define return type for the login API response
export interface LoginResult {
  success: boolean;
  tfa_required: boolean; // Indicates if a 2FA code is needed after password validation
  message?: string;
  tfa_app_name?: string | null; // Name of the 2FA app if available
  user?: UserProfile; // User profile data on successful login
  inSignupFlow?: boolean; // Flag if user is mid-signup
  backup_code_used?: boolean; // Flag if a backup code was used for login
  remaining_backup_codes?: number; // Number of remaining backup codes after use
  encrypted_key?: string;
  salt?: string;
}

// Define the structure for logout callbacks
export interface LogoutCallbacks {
    beforeLocalLogout?: () => void | Promise<void>; // Called before local state reset
    afterLocalLogout?: () => void | Promise<void>;  // Called after local state reset, before async cleanup
    afterServerCleanup?: () => void | Promise<void>; // Called after server logout & DB clear
    onError?: (error: any) => void | Promise<void>; // Called on any error during logout
    skipServerLogout?: boolean; // Option to skip the server API call
    isPolicyViolation?: boolean; // Flag for special policy violation logout handling
    isSessionExpiredLogout?: boolean; // New flag for session expired logout handling
}
