// frontend/packages/ui/src/stores/authSessionActions.ts
/**
 * @fileoverview Actions related to checking and initializing the user's session state.
 */

import { get } from 'svelte/store';
import { getApiEndpoint, apiEndpoints } from '../config/api';
import { currentSignupStep, isInSignupProcess, getStepFromPath } from './signupState';
import { requireInviteCode } from './signupRequirements';
import { userDB } from '../services/userDB';
import { chatDB } from '../services/db'; // Import chatDB
import { userProfile, defaultProfile, updateProfile } from './userProfile';
import { locale } from 'svelte-i18n';
import * as cryptoService from '../services/cryptoService';
import { deleteSessionId } from '../utils/sessionId'; // Import deleteSessionId
import { sessionExpiredWarning } from './uiStateStore'; // Import sessionExpiredWarning
import { logout, deleteAllCookies } from './authLoginLogoutActions'; // Import logout function and deleteAllCookies
import { setWebSocketToken, clearWebSocketToken } from '../utils/cookies'; // Import WebSocket token utilities

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
export async function checkAuth(deviceSignals?: Record<string, string | null>, force: boolean = false): Promise<boolean> {
    // Prevent check if already checking or initialized (unless forced)
    // Allow check if needsDeviceVerification is true, as this indicates a pending state that needs resolution.
    if (!force && (get(isCheckingAuth) || (get(authStore).isInitialized && !get(needsDeviceVerification)))) {
        console.debug("Auth check skipped (already checking or initialized, and not in device verification flow).");
        return get(authStore).isAuthenticated;
    }

    isCheckingAuth.set(true);
    needsDeviceVerification.set(false); // Reset verification need

    try {
        // Import getSessionId to include session_id in the request
        const { getSessionId } = await import('../utils/sessionId');
        
        console.debug("Checking authentication with session endpoint...");
        const response = await fetch(getApiEndpoint(apiEndpoints.auth.session), {
            method: 'POST',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'Origin': window.location.origin
            },
            body: JSON.stringify({ 
                deviceSignals: deviceSignals || {},
                session_id: getSessionId() // Include session_id for device fingerprinting
            }),
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

        // Update the requireInviteCode store based on the session response
        if (data.require_invite_code !== undefined) {
            requireInviteCode.set(data.require_invite_code);
            console.debug(`Setting requireInviteCode to ${data.require_invite_code}`);
        }

        // Handle Successful Authentication
        if (data.success && data.user) {
            // Store WebSocket token if provided (for Safari iOS compatibility)
            // This MUST happen before updating authStore to avoid race conditions
            if (data.ws_token) {
                setWebSocketToken(data.ws_token);
                console.debug('[AuthSessionActions] WebSocket token stored from session response');
            } else {
                console.warn('[AuthSessionActions] No ws_token in session response - WebSocket connection may fail on Safari/iPad');
            }

            const masterKey = await cryptoService.getKeyFromStorage(); // Use getKeyFromStorage (now async)
            if (!masterKey) {
                console.warn("User is authenticated but master key is not found in storage. Forcing logout and clearing data.");

                // Set auth state and show warning first (don't block on database deletion)
                authStore.update(state => ({
                    ...state,
                    isAuthenticated: false,
                    isInitialized: true
                }));
                sessionExpiredWarning.set(true); // Show warning message immediately
                
                // Trigger server logout and local data cleanup
                // Database deletion happens asynchronously without blocking UI
                logout({
                    skipServerLogout: false, // Explicitly send logout request to server
                    isSessionExpiredLogout: true, // Custom flag for this scenario
                    afterLocalLogout: async () => {
                        // Clear IndexedDB data in background (non-blocking)
                        setTimeout(async () => {
                            try {
                                await userDB.deleteDatabase();
                                console.debug("[AuthSessionActions] UserDB database deleted due to missing master key.");
                            } catch (dbError) {
                                console.warn("[AuthSessionActions] Failed to delete userDB database (may be blocked):", dbError);
                            }
                            try {
                                await chatDB.deleteDatabase();
                                console.debug("[AuthSessionActions] ChatDB database deleted due to missing master key.");
                            } catch (dbError) {
                                console.warn("[AuthSessionActions] Failed to delete chatDB database (may be blocked):", dbError);
                            }
                        }, 100);
                    }
                }).catch(err => {
                    console.error("[AuthSessionActions] Logout failed:", err);
                });

                deleteSessionId(); // Remove session_id on forced logout
                cryptoService.clearAllEmailData(); // Clear email encryption key, encrypted email, and salt
                deleteAllCookies(); // Clear all cookies on forced logout
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
            // Handle Other Failures - Auto-delete all local data when not logged in
            console.info("Session check failed or user not logged in:", data.message);
            
            // Check if master key was present before clearing (to show session expired warning)
            const hadMasterKey = !!(await cryptoService.getKeyFromStorage());

            // Clear master key and all email data from storage
            await cryptoService.clearKeyFromStorage();
            cryptoService.clearAllEmailData(); // Clear email encryption key, encrypted email, and salt
            
            // Delete session ID and cookies
            deleteSessionId();
            deleteAllCookies(); // Clear all cookies on forced logout
            clearWebSocketToken(); // Clear WebSocket token from sessionStorage
            console.debug("[AuthSessionActions] Cookies, session ID, and WebSocket token deleted.");
            
            // ONLY delete databases if user was previously authenticated
            // This prevents race conditions on fresh page loads where databases are being initialized
            if (hadMasterKey) {
                console.debug("[AuthSessionActions] Master key was present - cleaning up user data.");
                
                // Clear IndexedDB databases asynchronously without blocking UI
                // Use setTimeout to defer deletion and avoid blocking the auth initialization
                setTimeout(async () => {
                    try {
                        await userDB.deleteDatabase();
                        console.debug("[AuthSessionActions] UserDB database deleted due to session expiration.");
                    } catch (dbError) {
                        console.warn("[AuthSessionActions] Failed to delete userDB database (may be blocked by open connections):", dbError);
                    }
                    
                    try {
                        await chatDB.deleteDatabase();
                        console.debug("[AuthSessionActions] ChatDB database deleted due to session expiration.");
                    } catch (dbError) {
                        console.warn("[AuthSessionActions] Failed to delete chatDB database (may be blocked by open connections):", dbError);
                    }
                }, 100); // Small delay to allow current operations to complete
                
                // Show session expired warning
                sessionExpiredWarning.set(true);
                console.debug("[AuthSessionActions] Session expired warning shown.");
            } else {
                console.debug("[AuthSessionActions] No master key found - user was not previously authenticated, skipping database deletion.");
            }
            
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
            
            console.debug("[AuthSessionActions] Auth state reset completed.");
            return false;
        }
    } catch (error) {
        console.error("Auth check error:", error);
        needsDeviceVerification.set(false);

        // Clear sensitive data on auth check error (but don't block on database deletion)
        await cryptoService.clearKeyFromStorage();
        cryptoService.clearAllEmailData(); // Clear email encryption key, encrypted email, and salt
        deleteSessionId();
        deleteAllCookies(); // Clear all cookies
        clearWebSocketToken(); // Clear WebSocket token from sessionStorage
        console.debug("[AuthSessionActions] All sensitive data cleared due to auth check error.");
        
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

/**
 * Updates the authentication state to authenticated after successful login.
 * This should be called by login components after they have successfully
 * authenticated the user and updated the user profile.
 */
export function setAuthenticatedState(): void {
    console.debug("Setting authentication state to authenticated after successful login");
    authStore.update(state => ({
        ...state,
        isAuthenticated: true,
        isInitialized: true
    }));
    needsDeviceVerification.set(false);
}
