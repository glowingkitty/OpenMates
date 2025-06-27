// frontend/packages/ui/src/stores/authLoginLogoutActions.ts
/**
 * @fileoverview Actions related to user login and logout processes.
 */

import { get } from 'svelte/store';
import { getApiEndpoint, apiEndpoints } from '../config/api';
import { currentSignupStep, isInSignupProcess, getStepFromPath, isResettingTFA } from './signupState';
import { userDB } from '../services/userDB';
import { chatDB } from '../services/db';
// Import defaultProfile directly for logout reset
import { userProfile, defaultProfile, updateProfile, type UserProfile } from './userProfile';
import { resetTwoFAData } from './twoFAState';
import { processedImageUrl } from './profileImage';
import { locale } from 'svelte-i18n';
import * as cryptoService from '../services/cryptoService';
import { deleteSessionId } from '../utils/sessionId';

// Import core auth state and related flags
import { authStore, needsDeviceVerification, authInitialState } from './authState';
// Import auth types
import type { LoginResult, LogoutCallbacks } from './authTypes';

/**
 * Attempts to log the user in via the API. Handles password, 2FA codes, and backup codes.
 * Updates auth state and user profile on success.
 * @param email User's email.
 * @param password User's password.
 * @param tfaCode Optional 2FA code (OTP or backup).
 * @param codeType Type of the tfaCode ('otp' or 'backup').
 * @returns LoginResult object indicating success, 2FA requirement, messages, etc.
 */
export async function login(
    email: string,
    password: string,
    tfaCode?: string,
    codeType?: 'otp' | 'backup'
): Promise<LoginResult> {
    try {
        console.debug(`Attempting login... (TFA Code Provided: ${!!tfaCode}, Type: ${codeType || 'otp'})`);

        const requestBody: any = { email: email.trim(), password: password };
        if (tfaCode) {
            requestBody.tfa_code = tfaCode;
            requestBody.code_type = codeType || 'otp';
        }

        const response = await fetch(getApiEndpoint(apiEndpoints.auth.login), {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'Origin': window.location.origin
            },
            body: JSON.stringify(requestBody),
            credentials: 'include'
        });

        if (response.status === 429) {
            return { success: false, tfa_required: !!tfaCode, message: "Too many login attempts. Please try again later." };
        }

        // Use LoginResult type for the response data
        const data: LoginResult = await response.json();
        console.debug("Login response data:", data);

        if (data.success) {
            if (data.tfa_required) {
                // Password OK, 2FA needed
                console.debug("Login step 1 successful, 2FA required.");
                return {
                    success: true,
                    tfa_required: true,
                    // Check if user exists before accessing tfa_app_name
                    tfa_app_name: data.user?.tfa_app_name
                };
            } else {
                // Full success
                console.debug("Login fully successful.");
                // Check if user exists before accessing last_opened
                const inSignupFlow = data.user?.last_opened?.startsWith('/signup/');

                if (inSignupFlow && data.user?.last_opened) { // Add check for last_opened existence
                    console.debug("User is in signup process:", data.user.last_opened);
                    const step = getStepFromPath(data.user.last_opened);
                    currentSignupStep.set(step);
                    isInSignupProcess.set(true);
                } else {
                    isInSignupProcess.set(false);
                }

                authStore.update(state => ({ ...state, isAuthenticated: true, isInitialized: true }));

                try {
                    if (data.user) { // Ensure user data exists before proceeding
                        await userDB.saveUserData(data.user);
                        const tfa_enabled = !!data.user.tfa_enabled;
                        const consent_privacy = !!data.user.consent_privacy_and_apps_default_settings;
                        const consent_mates = !!data.user.consent_mates_default_settings;
                        const userLanguage = data.user.language || defaultProfile.language;
                        const userDarkMode = data.user.darkmode ?? defaultProfile.darkmode;

                        if (userLanguage && userLanguage !== get(locale)) {
                            console.debug(`Applying user language from login: ${userLanguage}`);
                            locale.set(userLanguage);
                        }

                        updateProfile({
                            username: data.user.username,
                            profile_image_url: data.user.profile_image_url,
                            tfa_app_name: data.user.tfa_app_name,
                            tfa_enabled: tfa_enabled,
                            credits: data.user.credits,
                            is_admin: data.user.is_admin,
                            last_opened: data.user.last_opened,
                            consent_privacy_and_apps_default_settings: consent_privacy,
                            consent_mates_default_settings: consent_mates,
                            language: userLanguage,
                            darkmode: userDarkMode
                        });
                    } else {
                        console.warn("Login successful but no user data received in response.");
                         // Even if no user data, mark as authenticated
                         authStore.update(state => ({ ...state, isAuthenticated: true, isInitialized: true }));
                    }
                } catch (dbError) {
                    console.error("Failed to save user data to database:", dbError);
                }

                return {
                    success: true,
                    tfa_required: false,
                    inSignupFlow,
                    backup_code_used: data.backup_code_used || false,
                    remaining_backup_codes: data.remaining_backup_codes,
                    user: data.user // Pass user data back
                };
            }
        } else {
            // Login failed
            if (data.tfa_required) {
                // Invalid 2FA code
                console.warn("Login failed: Invalid 2FA code.");
                return { success: false, tfa_required: true, message: data.message || "Invalid 2FA code" };
            } else {
                // General failure (e.g., invalid password)
                console.warn("Login failed:", data.message);
                return { success: false, tfa_required: false, message: data.message || "Login failed" };
            }
        }
    } catch (error) {
        console.error("Login fetch/network error:", error);
        return { success: false, tfa_required: false, message: "An error occurred during login" };
    }
}


/**
 * Logs the user out. Resets local state immediately for UI responsiveness,
 * then performs server logout and database cleanup asynchronously.
 * @param callbacks Optional callbacks for different stages of the logout process.
 * @returns True if local logout initiated successfully, false otherwise.
 */
export async function logout(callbacks?: LogoutCallbacks): Promise<boolean> {
    console.debug('Attempting to log out and clear local data...');

    try {
        // Clear the master key from the session
        cryptoService.clearKeyFromSession();
        deleteSessionId();

        if (callbacks?.beforeLocalLogout) {
            await callbacks.beforeLocalLogout();
        }

        // --- Local Database Cleanup ---
        // Attempt this before resetting local UI state.
        // Errors here are logged, and onError callback is called if provided.
        // The logout process (UI state reset, server logout) will continue even if DB deletion fails.
        console.debug('[AuthStore] Attempting local database cleanup...');
        try {
            await userDB.deleteDatabase();
            console.debug("[AuthStore] UserDB database deleted successfully.");
        } catch (dbError) {
            console.error("[AuthStore] Failed to delete userDB database:", dbError);
            if (callbacks?.onError) await callbacks.onError(dbError);
        }
        try {
            await chatDB.deleteDatabase();
            console.debug("[AuthStore] ChatDB database deleted successfully.");
        } catch (dbError) {
            console.error("[AuthStore] Failed to delete chatDB database:", dbError);
            if (callbacks?.onError) await callbacks.onError(dbError);
        }
        console.debug('[AuthStore] Local database cleanup attempt finished.');

        // --- Reset Local UI State ---
        console.debug('[AuthStore] Resetting local UI state...');
        const currentLang = get(userProfile).language;
        const currentMode = get(userProfile).darkmode;
        userProfile.set({
           ...defaultProfile,
           language: currentLang,
           darkmode: currentMode
        });
        console.debug('[UserProfileStore] In-memory profile reset via set()');

        processedImageUrl.set(null);
        resetTwoFAData();
        currentSignupStep.set(1);
        isResettingTFA.set(false);
        needsDeviceVerification.set(false);
        authStore.set({
            ...authInitialState,
            isInitialized: true
        });
        console.debug('[AuthStore] Local UI state reset complete.');

        if (callbacks?.afterLocalLogout) {
            await callbacks.afterLocalLogout();
        }

        // --- Asynchronous Server Logout Operations & Final Callbacks ---
        // These operations can happen in the background.
        (async () => {
            console.debug('[AuthStore] Performing server-side logout operations...');
            try {
                if (!callbacks?.skipServerLogout) {
                    try {
                        const logoutApiUrl = getApiEndpoint(apiEndpoints.auth.logout);
                        const response = await fetch(logoutApiUrl, {
                            method: 'POST',
                            credentials: 'include',
                            headers: { 'Content-Type': 'application/json' }
                        });
                        if (!response.ok) {
                            console.error('Server logout request failed:', response.statusText);
                        } else {
                            console.debug('[AuthStore] Server logout successful.');
                        }
                    } catch (e) {
                        console.error("[AuthStore] Server logout API call or URL resolution failed:", e);
                        if (callbacks?.onError) await callbacks.onError(e);
                    }
                } else if (callbacks?.isPolicyViolation) {
                    try {
                        const policyLogoutApiUrl = getApiEndpoint(apiEndpoints.auth.policyViolationLogout);
                        const response = await fetch(policyLogoutApiUrl, {
                            method: 'POST',
                            credentials: 'include',
                            headers: { 'Content-Type': 'application/json' }
                        });
                        console.debug('[AuthStore] Policy violation logout response:', response.ok);
                    } catch (e) {
                        console.error("[AuthStore] Policy violation logout API call or URL resolution failed:", e);
                        if (callbacks?.onError) await callbacks.onError(e);
                    }
                }
            } catch (serverError) {
                console.error("[AuthStore] Unexpected error during server logout processing:", serverError);
                if (callbacks?.onError) await callbacks.onError(serverError);
            }

            // --- Final Callbacks --- (after server operations)
            if (callbacks?.afterServerCleanup) {
                try {
                    await callbacks.afterServerCleanup();
                } catch (cbError) {
                    console.error("[AuthStore] Error in afterServerCleanup callback:", cbError);
                }
            }
        })(); // End of IIFE for server operations

        return true; // Indicate local logout (UI state reset, DB cleanup attempt) initiated successfully.

    } catch (error) {
        // Handle critical errors during the synchronous part (e.g., beforeLocalLogout, state reset)
        console.error("[AuthStore] Critical error during logout process:", error);
        if (callbacks?.onError) {
            await callbacks.onError(error);
        }
        // Attempt to reset essential auth state even on critical error
        try {
            authStore.set({ ...authInitialState, isInitialized: true });
            const currentLang = get(userProfile)?.language ?? defaultProfile.language;
            const currentMode = get(userProfile)?.darkmode ?? defaultProfile.darkmode;
            userProfile.set({
                ...defaultProfile,
                language: currentLang,
                darkmode: currentMode
            });
        } catch (resetError) {
            console.error("[AuthStore] Failed to reset state even during critical error handling:", resetError);
        }
        // It's debatable if afterServerCleanup should run here, as server part is async.
        // For consistency with original, keeping it.
        if (callbacks?.afterServerCleanup) {
            try { await callbacks.afterServerCleanup(); } catch { /* Ignore */ }
        }
        return false; // Indicate critical logout failure
    }
}
