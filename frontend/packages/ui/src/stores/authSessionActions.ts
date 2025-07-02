// frontend/packages/ui/src/stores/authSessionActions.ts
/**
 * @fileoverview Actions related to checking and initializing the user's session state.
 */

import { get } from 'svelte/store';
import { getApiEndpoint, apiEndpoints } from '../config/api';
import { currentSignupStep, isInSignupProcess, getStepFromPath } from './signupState';
import { userDB } from '../services/userDB';
import { chatDB } from '../services/db'; // Import chatDB
import { userProfile, defaultProfile, updateProfile } from './userProfile';
import { locale } from 'svelte-i18n';
import * as cryptoService from '../services/cryptoService';
import { deleteSessionId } from '../utils/sessionId'; // Import deleteSessionId
import { sessionExpiredWarning } from './uiStateStore'; // Import sessionExpiredWarning
import { logout } from './authLoginLogoutActions'; // Import logout function

// Import core auth state and related flags
import { authStore, isCheckingAuth, needsDeviceVerification } from './authState';
// Import auth types
import type { SessionCheckResult } from './authTypes';

/**
 * Checks the current authentication status by calling the session endpoint.
 * Updates auth state, user profile, and handles device verification requirements.
 * @param deviceSignals Optional device fingerprinting data.
 * @returns True if fully authenticated, false otherwise.
 */
export async function checkAuth(deviceSignals?: Record<string, string | null>): Promise<boolean> {
    // Prevent check if already checking or initialized (unless forced, add force param if needed)
    // Allow check if needsDeviceVerification is true, as this indicates a pending state that needs resolution.
    if (get(isCheckingAuth) || (get(authStore).isInitialized && !get(needsDeviceVerification))) {
        console.debug("Auth check skipped (already checking or initialized, and not in device verification flow).");
        return get(authStore).isAuthenticated;
    }

    isCheckingAuth.set(true);
    needsDeviceVerification.set(false); // Reset verification need

    try {
        console.debug("Checking authentication with session endpoint...");
        const response = await fetch(getApiEndpoint(apiEndpoints.auth.session), {
            method: 'POST',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'Origin': window.location.origin
            },
            body: JSON.stringify({ deviceSignals: deviceSignals || {} }),
            credentials: 'include'
        });

        const data: SessionCheckResult = await response.json();
        console.debug("Session check response:", data);

        // Handle Device Verification Required
        if (!data.success && data.re_auth_required === '2fa') {
            console.warn("Session check indicates device 2FA verification is required.");
            needsDeviceVerification.set(true);
            authStore.update(state => ({
                ...state,
                isAuthenticated: false,
                isInitialized: true
            }));
            // Clear potentially stale user data
            updateProfile({
                username: null, profile_image_url: null, tfa_app_name: null,
                tfa_enabled: false, credits: 0, is_admin: false, last_opened: null,
                consent_privacy_and_apps_default_settings: false, consent_mates_default_settings: false,
                darkmode: defaultProfile.darkmode // Reset darkmode
            });
            return false;
        }

        // Handle Successful Authentication
        if (data.success && data.user) {
            const masterKey = cryptoService.getKeyFromStorage(); // Use getKeyFromStorage
            if (!masterKey) {
                console.warn("User is authenticated but master key is not found in storage. Forcing logout and clearing data.");
                // Trigger server logout and local data cleanup
                await logout({
                    skipServerLogout: false, // Explicitly send logout request to server
                    isSessionExpiredLogout: true, // Custom flag for this scenario
                    afterLocalLogout: async () => {
                        // Clear IndexedDB data
                        try {
                            await userDB.deleteDatabase();
                            console.debug("[AuthSessionActions] UserDB database deleted due to session expiration.");
                        } catch (dbError) {
                            console.error("[AuthSessionActions] Failed to delete userDB database on session expiration:", dbError);
                        }
                        try {
                            await chatDB.deleteDatabase();
                            console.debug("[AuthSessionActions] ChatDB database deleted due to session expiration.");
                        } catch (dbError) {
                            console.error("[AuthSessionActions] Failed to delete chatDB database on session expiration:", dbError);
                        }
                        sessionExpiredWarning.set(true); // Show warning message
                    }
                });

                authStore.update(state => ({
                    ...state,
                    isAuthenticated: false,
                    isInitialized: true
                }));
                deleteSessionId(); // Remove session_id on forced logout
                return false;
            }

            needsDeviceVerification.set(false);
            const inSignupFlow = data.user.last_opened?.startsWith('/signup/');

            if (inSignupFlow) {
                console.debug("User is in signup process:", data.user.last_opened);
                const step = getStepFromPath(data.user.last_opened);
                currentSignupStep.set(step);
                isInSignupProcess.set(true);
            } else {
                isInSignupProcess.set(false);
            }

            authStore.update(state => ({
                ...state,
                isAuthenticated: true,
                isInitialized: true
            }));

            try {
                await userDB.saveUserData(data.user);
                const tfa_enabled = !!data.user.tfa_enabled;
                const consent_privacy = !!data.user.consent_privacy_and_apps_default_settings;
                const consent_mates = !!data.user.consent_mates_default_settings;
                const userLanguage = data.user.language || defaultProfile.language;
                const userDarkMode = data.user.darkmode ?? defaultProfile.darkmode;

                if (userLanguage && userLanguage !== get(locale)) {
                    console.debug(`Applying user language from session: ${userLanguage}`);
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
            } catch (dbError) {
                console.error("Failed to save user data to database:", dbError);
            }
            return true;
        } else {
            // Handle Other Failures
            console.info("Session check failed or user not logged in:", data.message);
            needsDeviceVerification.set(false);
            authStore.update(state => ({
                ...state,
                isAuthenticated: false,
                isInitialized: true
            }));
            // Clear profile
            updateProfile({
                username: null, profile_image_url: null, tfa_app_name: null,
                tfa_enabled: false, credits: 0, is_admin: false, last_opened: null,
                consent_privacy_and_apps_default_settings: false, consent_mates_default_settings: false
            });
            return false;
        }
    } catch (error) {
        console.error("Auth check error:", error);
        needsDeviceVerification.set(false);
        authStore.update(state => ({
            ...state,
            isAuthenticated: false,
            isInitialized: true
        }));
        // Clear profile
        updateProfile({
            username: null, profile_image_url: null, tfa_app_name: null,
            tfa_enabled: false, credits: 0, is_admin: false, last_opened: null,
            consent_privacy_and_apps_default_settings: false, consent_mates_default_settings: false
        });
        return false;
    } finally {
        isCheckingAuth.set(false);
    }
}

/**
 * Initializes the authentication state by calling checkAuth.
 * Should be called once on application startup.
 * @param deviceSignals Optional device fingerprinting data.
 * @returns The result of the checkAuth call (true if authenticated, false otherwise).
 */
export async function initialize(deviceSignals?: Record<string, string | null>): Promise<boolean> {
    console.debug("Initializing auth state...");
    // Check if already initialized to prevent redundant checks
    if (get(authStore).isInitialized) {
        console.debug("Auth state already initialized.");
        return get(authStore).isAuthenticated;
    }
    return await checkAuth(deviceSignals);
}
