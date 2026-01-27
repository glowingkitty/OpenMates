// frontend/packages/ui/src/stores/authSessionActions.ts
/**
 * @fileoverview Actions related to checking and initializing the user's session state.
 */

import { get } from 'svelte/store';
import { getApiEndpoint, apiEndpoints } from '../config/api';
import { currentSignupStep, isInSignupProcess, getStepFromPath, STEP_ALPHA_DISCLAIMER, isSignupPath } from './signupState';
import { requireInviteCode } from './signupRequirements';
import { userDB } from '../services/userDB';
import { chatDB } from '../services/db'; // Import chatDB
import { userProfile, defaultProfile, updateProfile } from './userProfile';
import { locale } from 'svelte-i18n';
import * as cryptoService from '../services/cryptoService';
import { deleteSessionId } from '../utils/sessionId'; // Import deleteSessionId
import { logout, deleteAllCookies } from './authLoginLogoutActions'; // Import logout function and deleteAllCookies
import { setWebSocketToken, clearWebSocketToken } from '../utils/cookies'; // Import WebSocket token utilities
import { notificationStore } from './notificationStore'; // Import notification store for logout notifications
import { loadUserProfileFromDB } from './userProfile'; // Import to load user profile from IndexedDB
import { loginInterfaceOpen } from './uiStateStore'; // Import loginInterfaceOpen to control login interface visibility
import { activeChatStore } from './activeChatStore'; // Import activeChatStore to navigate to demo-for-everyone on logout
import { clearSignupData, clearIncompleteSignupData } from './signupStore'; // Import signup cleanup functions
import { clearAllSessionStorageDrafts } from '../services/drafts/sessionStorageDraftService'; // Import sessionStorage draft cleanup
import { isLoggingOut, forcedLogoutInProgress } from './signupState'; // Import isLoggingOut and forcedLogoutInProgress to track logout state

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
        
        let response: Response;
        let data: SessionCheckResult;
        
        try {
            response = await fetch(getApiEndpoint(apiEndpoints.auth.session), {
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

            // Check if response is OK (status 200-299)
            // If not OK, treat as network/server error and be optimistic
            if (!response.ok) {
                console.warn(`[AuthSessionActions] Session endpoint returned non-OK status: ${response.status} - treating as network error (offline-first mode)`);
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            data = await response.json();
            console.debug("Session check response:", data);
        } catch (fetchError) {
            // Network error, timeout, or non-OK response - be optimistic
            console.warn("[AuthSessionActions] Network error or non-OK response during auth check (offline-first):", fetchError);
            throw fetchError; // Re-throw to be caught by outer catch block
        }

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

            // CRITICAL: Prevent duplicate forced logout triggers if already in progress
            if (get(forcedLogoutInProgress)) {
                console.debug("[AuthSessionActions] Forced logout already in progress, skipping duplicate trigger");
                return false;
            }

            const masterKey = await cryptoService.getKeyFromStorage(); // Use getKeyFromStorage (now async)
            if (!masterKey) {
                console.warn("User is authenticated but master key is not found in storage. Forcing logout and clearing data.");

                // CRITICAL: Set forcedLogoutInProgress flag FIRST, SYNCHRONOUSLY, before ANY other state changes
                // This prevents race conditions where other components try to load/decrypt encrypted chats
                // that can no longer be decrypted (because master key is missing).
                // This flag is checked in chat loading and decryption code to skip those operations.
                forcedLogoutInProgress.set(true);
                console.debug("[AuthSessionActions] Set forcedLogoutInProgress to true - blocking encrypted chat loading");
                
                // CRITICAL: Navigate to demo-for-everyone IMMEDIATELY (synchronously) BEFORE auth state changes
                // This ensures any component reading activeChatStore will see demo-for-everyone, not the old chat
                if (typeof window !== 'undefined') {
                    activeChatStore.setActiveChat('demo-for-everyone');
                    window.location.hash = 'chat-id=demo-for-everyone';
                    console.debug("[AuthSessionActions] Navigated to demo-for-everyone chat IMMEDIATELY (synchronous) - missing master key");
                }

                // Set auth state (don't block on database deletion)
                authStore.update(state => ({
                    ...state,
                    isAuthenticated: false,
                    isInitialized: true
                }));
                
                // Show notification that user was logged out
                notificationStore.warning("You have been logged out. Please log in again.", 5000);
                
                // CRITICAL: Set isLoggingOut flag to true BEFORE navigating to demo-for-everyone
                // This ensures ActiveChat component knows we're explicitly logging out and should clear shared chats
                // and load demo-for-everyone, even if the chat is a shared chat
                isLoggingOut.set(true);
                console.debug("[AuthSessionActions] Set isLoggingOut to true for missing master key logout");
                
                // Trigger server logout and local data cleanup
                // Database deletion is handled by the logout() function's background IIFE
                // CRITICAL: Do NOT reset forcedLogoutInProgress until AFTER database deletion completes
                // This prevents race conditions where other code re-opens the database during logout
                logout({
                    skipServerLogout: false, // Explicitly send logout request to server
                    isSessionExpiredLogout: true, // Custom flag for this scenario
                    afterLocalLogout: async () => {
                        // NOTE: Do NOT reset flags here - database deletion happens in logout()'s background IIFE
                        // and we need forcedLogoutInProgress to remain true until deletion completes
                        // This prevents chatDB.init() from being called during the deletion window
                        console.debug("[AuthSessionActions] afterLocalLogout called - flags NOT reset yet (waiting for DB cleanup)");
                    },
                    afterServerCleanup: async () => {
                        // CRITICAL: Reset flags AFTER database deletion completes (in logout()'s background IIFE)
                        // This ensures forcedLogoutInProgress stays true during the entire deletion process
                        isLoggingOut.set(false);
                        forcedLogoutInProgress.set(false);
                        console.debug("[AuthSessionActions] Reset logout flags after server cleanup and DB deletion");
                    }
                }).catch(err => {
                    console.error("[AuthSessionActions] Logout failed:", err);
                    // Reset logout flags even if logout fails
                    isLoggingOut.set(false);
                    forcedLogoutInProgress.set(false);
                });

                deleteSessionId(); // Remove session_id on forced logout
                cryptoService.clearAllEmailData(); // Clear email encryption key, encrypted email, and salt
                deleteAllCookies(); // Clear all cookies on forced logout
                return false;
            }

            // CRITICAL FIX: Reset forcedLogoutInProgress and isLoggingOut flags when authentication succeeds with valid master key
            // This handles the race condition where the flags were set (e.g., during page load detecting
            // "profile exists but no master key") but the user then successfully authenticates.
            // Without this reset, the flags stay true and cause database operations to fail.
            if (get(forcedLogoutInProgress)) {
                console.debug("[AuthSessionActions] Resetting forcedLogoutInProgress to false - auth succeeded with valid master key");
                forcedLogoutInProgress.set(false);
            }
            if (get(isLoggingOut)) {
                console.debug("[AuthSessionActions] Resetting isLoggingOut to false - auth succeeded with valid master key");
                isLoggingOut.set(false);
            }
            // Also clear the cleanup marker to prevent future false positives
            if (typeof localStorage !== 'undefined') {
                localStorage.removeItem('openmates_needs_cleanup');
            }

            needsDeviceVerification.set(false);
            
            // CRITICAL: Check URL hash directly - hash takes absolute precedence over everything
            // This ensures hash-based signup state works even if set after checkAuth() starts
            let hasSignupHash = false;
            let hashStep: string | null = null;
            if (typeof window !== 'undefined' && window.location.hash.startsWith('#signup/')) {
                hasSignupHash = true;
                const signupHash = window.location.hash.substring(1); // Remove leading #
                hashStep = getStepFromPath(signupHash);
                console.debug("checkAuth() found signup hash in URL:", window.location.hash, "-> step:", hashStep);
            }
            
            // Check if signup state was already set from URL hash (hash takes precedence)
            // If isInSignupProcess is already true, it means the hash was processed before initialize()
            // and we should NOT override it based on last_opened
            const signupStateFromHash = hasSignupHash || get(isInSignupProcess);
            
            // A user is in signup flow if:
            // 1. URL hash indicates signup (hash takes absolute precedence), OR
            // 2. Signup state was already set from URL hash, OR
            // 3. last_opened starts with '/signup/' or '#signup/' (explicit signup path)
            // NOTE: Do NOT infer signup from tfa_enabled=false to avoid forcing passkey users into OTP setup
            const inSignupFlow = hasSignupHash || 
                                signupStateFromHash || 
                                isSignupPath(data.user.last_opened);

            if (inSignupFlow) {
                // If hash is present, use hash step (hash takes absolute precedence)
                if (hasSignupHash && hashStep) {
                    console.debug("Setting signup state from URL hash:", hashStep);
                    currentSignupStep.set(hashStep);
                    isInSignupProcess.set(true);
                    loginInterfaceOpen.set(true);
                } else if (!signupStateFromHash) {
                    // Only update signup state if it wasn't already set from hash
                    // This ensures hash-based signup state takes precedence
                    console.debug("User is in signup process:", {
                        last_opened: data.user.last_opened,
                        tfa_enabled: data.user.tfa_enabled
                    });
                    // Determine step from last_opened (hash-based paths) to resume precisely
                    const step = getStepFromPath(data.user.last_opened);
                    currentSignupStep.set(step);
                    isInSignupProcess.set(true);
                    // CRITICAL: Open login interface to show signup flow on page reload
                    // This ensures the signup flow is visible immediately when the page reloads
                    loginInterfaceOpen.set(true);
                    console.debug("Set signup step to:", step, "and opened login interface");
                } else {
                    console.debug("Signup state already set from URL hash, preserving it");
                }
            } else {
                // Only clear signup state if it wasn't set from hash
                // CRITICAL: Don't clear signup state if user is currently in signup process
                // This prevents clearing signup state if checkAuth runs before user profile loads
                if (!signupStateFromHash) {
                    // Check if signup state is already set (e.g., from login() function)
                    // If it is, preserve it - user profile might load asynchronously
                    const currentInSignup = get(isInSignupProcess);
                    if (!currentInSignup) {
                        // Signup state is not set - safe to clear
                        isInSignupProcess.set(false);
                    } else {
                        // Signup state is already set - preserve it
                        // This handles the case where login() set it but checkAuth() runs before profile loads
                        console.debug("[AuthSessionActions] Preserving existing signup state (user profile may load asynchronously)");
                    }
                }
            }

            authStore.update(state => ({
                ...state,
                isAuthenticated: true,
                isInitialized: true
            }));

            try {
                // Log auto top-up fields from backend response - ERROR if missing
                const hasAutoTopupFields = 'auto_topup_low_balance_enabled' in data.user;
                if (!hasAutoTopupFields) {
                    console.error('[AuthSessionActions] ERROR: Auto top-up fields missing from backend response (session check)!');
                    console.error('[AuthSessionActions] Received user object keys:', Object.keys(data.user));
                    console.error('[AuthSessionActions] Full user object:', data.user);
                } else {
                    console.debug('[AuthSessionActions] Auto top-up fields from backend (session check):', {
                        enabled: data.user.auto_topup_low_balance_enabled,
                        threshold: data.user.auto_topup_low_balance_threshold,
                        amount: data.user.auto_topup_low_balance_amount,
                        currency: data.user.auto_topup_low_balance_currency
                    });
                }
                
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
                    darkmode: userDarkMode,
                    // Low balance auto top-up fields
                    auto_topup_low_balance_enabled: data.user.auto_topup_low_balance_enabled ?? false,
                    auto_topup_low_balance_threshold: data.user.auto_topup_low_balance_threshold,
                    auto_topup_low_balance_amount: data.user.auto_topup_low_balance_amount,
                    auto_topup_low_balance_currency: data.user.auto_topup_low_balance_currency
                });
            } catch (dbError) {
                console.error("Failed to save user data to database:", dbError);
            }
            return true;
        } else {
            // Handle Server Explicitly Saying User Is Not Logged In
            // This is different from network errors - server successfully responded saying user is not authenticated
            console.info("Server explicitly indicates user is not logged in:", data.message);
            
            // Check if master key was present before clearing (to determine if user was previously authenticated)
            const hadMasterKey = !!(await cryptoService.getKeyFromStorage());

            // Only logout and show notification if user was previously authenticated
            if (hadMasterKey) {
                console.debug("[AuthSessionActions] User was previously authenticated - showing logout notification and cleaning up.");
                
                // CRITICAL: Set isLoggingOut flag to true BEFORE dispatching logout event
                // This ensures ActiveChat component knows we're explicitly logging out and should clear shared chats
                // and load demo-for-everyone, even if the chat is a shared chat
                isLoggingOut.set(true);
                console.debug("[AuthSessionActions] Set isLoggingOut to true for session expiration logout");
                
                // CRITICAL: Dispatch logout event IMMEDIATELY to clear UI state (chats, etc.)
                // This must happen before database deletion to ensure UI updates right away
                console.debug("[AuthSessionActions] Dispatching userLoggingOut event to clear UI state immediately");
                window.dispatchEvent(new CustomEvent('userLoggingOut'));
                
                // Show notification that user was logged out
                notificationStore.warning("You have been logged out. Please log in again.", 5000);
                
                // CRITICAL: If user is in signup flow, close signup interface and return to demo
                // This ensures the signup/login interface is closed when logout notification appears during signup
                const wasInSignupProcess = get(isInSignupProcess);
                if (wasInSignupProcess) {
                    console.debug("[AuthSessionActions] User was in signup process - closing signup interface and returning to demo");
                    
                    // Reset signup process state FIRST to ensure Login component switches to login view
                    // This prevents the signup view from remaining visible after closing
                    isInSignupProcess.set(false);
                    
                    // Clear the signup store data when closing to demo
                    clearSignupData();
                    
                    // Clear incomplete signup data from IndexedDB when closing to demo
                    // This ensures username doesn't persist if user interrupts signup
                    clearIncompleteSignupData().catch(error => {
                        console.error("[AuthSessionActions] Error clearing incomplete signup data:", error);
                    });
                    
                    // Reset signup step to alpha disclaimer for next time
                    currentSignupStep.set(STEP_ALPHA_DISCLAIMER);
                    
                    // CRITICAL: Clear all sessionStorage drafts when returning to demo mode
                    // This ensures drafts don't persist if user interrupts login/signup
                    clearAllSessionStorageDrafts();
                    console.debug("[AuthSessionActions] Cleared all sessionStorage drafts when returning to demo");
                    
                    // Close the login interface and load demo chat
                    // This dispatches a global event that ActiveChat.svelte listens to
                    window.dispatchEvent(new CustomEvent('closeLoginInterface'));
                    
                    // Small delay to ensure the interface closes before loading chat
                    setTimeout(() => {
                        // Dispatch event to load demo chat (ActiveChat will handle this)
                        window.dispatchEvent(new CustomEvent('loadDemoChat'));
                    }, 100);
                }
                
                // CRITICAL: Navigate to demo-for-everyone chat to hide the previously open chat
                // This ensures the previous chat is not visible after logout
                // Small delay to ensure auth state changes are processed first
                setTimeout(() => {
                    if (typeof window !== 'undefined') {
                        activeChatStore.setActiveChat('demo-for-everyone');
                        window.location.hash = 'chat-id=demo-for-everyone';
                        console.debug("[AuthSessionActions] Navigated to demo-for-everyone chat after logout notification");
                    }
                }, 50);
                
                // Clear master key and all email data from storage
                await cryptoService.clearKeyFromStorage();
                cryptoService.clearAllEmailData(); // Clear email encryption key, encrypted email, and salt
                
                // Delete session ID and cookies
                deleteSessionId();
                deleteAllCookies(); // Clear all cookies on forced logout
                clearWebSocketToken(); // Clear WebSocket token from sessionStorage
                console.debug("[AuthSessionActions] Cookies, session ID, and WebSocket token deleted.");
                
                // Clear IndexedDB databases asynchronously without blocking UI
                // Use setTimeout to defer deletion and avoid blocking the auth initialization
                // The UI state has already been cleared via the event above
                setTimeout(async () => {
                    try {
                        await userDB.deleteDatabase();
                        console.debug("[AuthSessionActions] UserDB database deleted due to server logout response.");
                    } catch (dbError) {
                        console.warn("[AuthSessionActions] Failed to delete userDB database (may be blocked by open connections):", dbError);
                    }
                    
                    try {
                        await chatDB.deleteDatabase();
                        console.debug("[AuthSessionActions] ChatDB database deleted due to server logout response.");
                    } catch (dbError) {
                        console.warn("[AuthSessionActions] Failed to delete chatDB database (may be blocked by open connections):", dbError);
                    }
                    
                    // CRITICAL: Reset isLoggingOut flag after logout cleanup completes
                    // This ensures the flag is reset even if logout was triggered by session expiration
                    // Use a small delay to ensure all logout handlers have finished processing
                    setTimeout(() => {
                        isLoggingOut.set(false);
                        console.debug("[AuthSessionActions] Reset isLoggingOut flag after session expiration logout cleanup");
                    }, 500);
                }, 100); // Small delay to allow current operations to complete
            } else {
                console.debug("[AuthSessionActions] No master key found - user was not previously authenticated, skipping cleanup.");
            }

            // CRITICAL: Check for orphaned database cleanup even if user was never authenticated
            // This handles the case where the page was reloaded with stayLoggedIn=false but
            // the databases were previously initialized and contain encrypted data that needs cleanup
            const cleanupMarker = typeof localStorage !== 'undefined' &&
                localStorage.getItem('openmates_needs_cleanup') === 'true';

            if (cleanupMarker) {
                console.warn("[AuthSessionActions] ORPHANED DATABASE CLEANUP: Found cleanup marker - triggering database deletion");

                // CRITICAL: Clear the cleanup marker immediately to prevent showing this notification again
                if (typeof localStorage !== 'undefined') {
                    localStorage.removeItem('openmates_needs_cleanup');
                    console.debug("[AuthSessionActions] Cleared cleanup marker to prevent repeated notifications");
                }

                // CRITICAL: Set isLoggingOut flag to true for orphaned database cleanup
                isLoggingOut.set(true);
                console.debug("[AuthSessionActions] Set isLoggingOut to true for orphaned database cleanup");

                // No notification needed - this is automatic cleanup

                // Clear IndexedDB databases asynchronously without blocking UI
                setTimeout(async () => {
                    try {
                        await userDB.deleteDatabase();
                        console.debug("[AuthSessionActions] UserDB database deleted during orphaned cleanup.");
                    } catch (dbError) {
                        console.warn("[AuthSessionActions] Failed to delete userDB database during orphaned cleanup (may be blocked by open connections):", dbError);
                    }

                    try {
                        await chatDB.deleteDatabase();
                        console.debug("[AuthSessionActions] ChatDB database deleted during orphaned cleanup.");
                    } catch (dbError) {
                        console.warn("[AuthSessionActions] Failed to delete chatDB database during orphaned cleanup (may be blocked by open connections):", dbError);
                    }

                    // CRITICAL: Reset isLoggingOut flag after cleanup completes
                    setTimeout(() => {
                        isLoggingOut.set(false);
                        console.debug("[AuthSessionActions] Reset isLoggingOut flag after orphaned database cleanup");
                    }, 500);
                }, 100); // Small delay to allow current operations to complete
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
        // Network error or fetch failure - be optimistic and load local data
        console.warn("[AuthSessionActions] Network error during auth check (offline-first):", error);
        console.debug("[AuthSessionActions] Loading local user data optimistically - assuming user is still authenticated");
        
        needsDeviceVerification.set(false);
        
        try {
            // Load user profile from IndexedDB optimistically
            await loadUserProfileFromDB();
            
            // Check if we have local user data (master key and user profile)
            const masterKey = await cryptoService.getKeyFromStorage();
            const localProfile = get(userProfile);
            const hasLocalData = masterKey && localProfile && localProfile.username;
            
            if (hasLocalData) {
                // User has local data - optimistically assume they're still authenticated
                console.debug("[AuthSessionActions] ✅ Local user data found - assuming authenticated (offline-first mode)");
                
                authStore.update(state => ({
                    ...state,
                    isAuthenticated: true,
                    isInitialized: true
                }));
                
                // Check if user is in signup flow (offline-first mode)
                // A user is in signup flow only if last_opened explicitly indicates signup
                // Avoid using tfa_enabled=false to keep passkey-only users out of OTP setup
                const inSignupFlow = isSignupPath(localProfile.last_opened);
                
                if (inSignupFlow) {
                    console.debug("[AuthSessionActions] User is in signup process (offline-first mode):", {
                        last_opened: localProfile.last_opened,
                        tfa_enabled: localProfile.tfa_enabled
                    });
                    // Determine step directly from last_opened (hash-based paths)
                    const step = getStepFromPath(localProfile.last_opened);
                    currentSignupStep.set(step);
                    isInSignupProcess.set(true);
                    // CRITICAL: Open login interface to show signup flow on page reload (offline-first mode)
                    loginInterfaceOpen.set(true);
                    console.debug("[AuthSessionActions] Set signup step to:", step, "and opened login interface (offline-first mode)");
                } else {
                    isInSignupProcess.set(false);
                }
                
                // Apply language from local profile if available
                if (localProfile.language) {
                    const currentLocale = get(locale);
                    if (localProfile.language !== currentLocale) {
                        console.debug(`[AuthSessionActions] Applying local user language: ${localProfile.language}`);
                        locale.set(localProfile.language);
                    }
                }
                
                return true; // Return true to indicate optimistic authentication
            } else {
                // No local data - user was never authenticated or data was cleared
                console.debug("[AuthSessionActions] No local user data found - user is not authenticated");
                
                authStore.update(state => ({
                    ...state,
                    isAuthenticated: false,
                    isInitialized: true
                }));
                
                return false;
            }
        } catch (loadError) {
            // If loading local data fails, fall back to not authenticated
            console.error("[AuthSessionActions] Error loading local user data:", loadError);
            
            authStore.update(state => ({
                ...state,
                isAuthenticated: false,
                isInitialized: true
            }));
            
            return false;
        }
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
