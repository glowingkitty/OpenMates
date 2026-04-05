// frontend/packages/ui/src/stores/authLoginLogoutActions.ts
/**
 * @fileoverview Actions related to user login and logout processes.
 */

import { get } from "svelte/store";
import { getApiEndpoint, getApiUrl, apiEndpoints, isDevEnvironment } from "../config/api";
import {
  currentSignupStep,
  isInSignupProcess,
  getStepFromPath,
  isResettingTFA,
  isSignupPath,
} from "./signupState";
import { userDB } from "../services/userDB";
import { chatDB } from "../services/db";
// Import defaultProfile directly for logout reset
import { userProfile, defaultProfile, updateProfile } from "./userProfile";
import { resetTwoFAData } from "./twoFAState";
import { processedImageUrl } from "./profileImage";
import { locale } from "svelte-i18n";
import * as cryptoService from "../services/cryptoService";
import { deleteSessionId } from "../utils/sessionId";
import { phasedSyncState } from "./phasedSyncStateStore";
import { aiTypingStore } from "./aiTypingStore";
import { dailyInspirationStore } from "./dailyInspirationStore";
import { webSocketService } from "../services/websocketService";
import { chatListCache } from "../services/chatListCache";
import { chatMetadataCache } from "../services/chatMetadataCache";
import { clearAllSharedChatKeys } from "../services/sharedChatKeyStorage";
import { clearAllSessionStorageDrafts } from "../services/drafts/sessionStorageDraftService";
import { resetChatNavigationList } from "./chatNavigationStore";
import { clientLogForwarder } from "../services/clientLogForwarder";
import { resetUserAvailableSkills } from "./appSkillsStore";
import { applyServerDarkMode } from "./theme";

// Import core auth state and related flags
import {
  authStore,
  needsDeviceVerification,
  deviceVerificationType,
  deviceVerificationReason,
  authInitialState,
} from "./authState";
// Import auth types
import type { LoginResult, LogoutCallbacks } from "./authTypes";
import { getSessionId } from "../utils/sessionId";

// Login session generation counter.
// Incremented on every successful login. The background logout IIFE captures the
// current value when it starts; before doing destructive operations (server logout
// fetch with credentials, cookie deletion) it re-checks the counter. If a new
// login happened in the meantime the counter will have changed, so the IIFE skips
// those operations to avoid invalidating the freshly-established session.
// This fixes the race condition where: forced-logout detects stale profile →
// fires background server-logout → user logs in via passkey → background IIFE
// sends POST /auth/logout with the *new* session's cookies → new session destroyed.
let loginSessionGeneration = 0;

/**
 * Returns the current login session generation.
 * Used by authSessionActions to capture before starting background logout.
 */
function getLoginSessionGeneration(): number {
  return loginSessionGeneration;
}

/**
 * Increments the login session generation counter.
 *
 * MUST be called by any login path that establishes a new authenticated session
 * but does not go through the `login()` function above (e.g., passkey login in
 * Login.svelte, which calls /auth/login directly via fetch()).
 *
 * The counter is checked by the background logout IIFE inside `logout()` — if a
 * new login bumped it, the IIFE skips the destructive POST /auth/logout and
 * cookie deletion that would otherwise destroy the freshly-established session.
 */
export function bumpLoginSessionGeneration(): void {
  loginSessionGeneration++;
  console.debug(
    `[AuthStore] Bumped loginSessionGeneration to ${loginSessionGeneration} (external login path)`,
  );
}

/**
 * Detects the user's timezone from the browser and syncs it to the server.
 * This is called after successful login to ensure the server always has the current timezone.
 * The timezone is used for reminders, scheduling, and displaying times in user's local time.
 *
 * @param serverTimezone - The timezone currently stored on the server (from user profile)
 */
async function syncBrowserTimezone(
  serverTimezone: string | null | undefined,
): Promise<void> {
  try {
    // Detect browser timezone using Intl API (IANA format, e.g., 'Europe/Berlin')
    const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;

    if (!browserTimezone) {
      console.warn("[Timezone] Could not detect browser timezone");
      return;
    }

    // Only sync if different from server or server has no timezone set
    if (browserTimezone === serverTimezone) {
      return;
    }

    // Update local profile first (optimistic update)
    updateProfile({ timezone: browserTimezone });

    // Sync to server
    const response = await fetch(
      getApiUrl() + apiEndpoints.settings.user.timezone,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({ timezone: browserTimezone }),
        credentials: "include", // Important for sending auth cookies
      },
    );

    if (!response.ok) {
      console.error(
        "[Timezone] Failed to sync timezone to server:",
        response.statusText,
      );
    }
  } catch (error) {
    console.error("[Timezone] Error syncing timezone:", error);
    // Non-blocking error - don't fail login if timezone sync fails
  }
}

/**
 * Attempts to log the user in via the API. Handles password, 2FA codes, and backup codes.
 * Updates auth state and user profile on success.
 * @param hashed_email Hashed email for lookup.
 * @param lookup_hash Hash of email + password for authentication.
 * @param tfaCode Optional 2FA code (OTP or backup).
 * @param codeType Type of the tfaCode ('otp' or 'backup').
 * @param stayLoggedIn Optional boolean to indicate if user wants to stay logged in.
 * @returns LoginResult object indicating success, 2FA requirement, messages, etc.
 */
export async function login(
  hashed_email: string,
  lookup_hash: string,
  tfaCode?: string,
  codeType?: "otp" | "backup",
  stayLoggedIn: boolean = false,
  loginMethod?: string, // e.g. "pair" — signals to backend to bypass 2FA for strong auth methods
): Promise<LoginResult> {
  try {
    const requestBody: Record<string, string | boolean> = {
      hashed_email,
      lookup_hash,
    };
    if (tfaCode) {
      requestBody.tfa_code = tfaCode;
      requestBody.code_type = codeType || "otp";
    }
    if (loginMethod) {
      requestBody.login_method = loginMethod;
    }
    // Send stay_logged_in so the backend stores the correct value in the session record
    // (used for cookie TTL and displayed in the Sessions settings page)
    requestBody.stay_logged_in = stayLoggedIn;

    // Add sessionId for device fingerprint uniqueness (multi-browser support)
    requestBody.session_id = getSessionId();

    const response = await fetch(getApiEndpoint(apiEndpoints.auth.login), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        Origin: window.location.origin,
      },
      body: JSON.stringify(requestBody),
      credentials: "include",
    });

    if (response.status === 429) {
      return {
        success: false,
        tfa_required: !!tfaCode,
        message: "Too many login attempts. Please try again later.",
      };
    }

    // Use LoginResult type for the response data
    const data: LoginResult = await response.json();

    if (data.success) {
      if (data.tfa_required) {
        // Password OK, 2FA needed
        return {
          success: true,
          tfa_required: true,
          // Check if user exists before accessing tfa_app_name
          tfa_app_name: data.user?.tfa_app_name,
        };
      } else {
        // Full success
        // Check if user exists before accessing last_opened
        // A user is in signup flow only if last_opened explicitly indicates signup
        // Do not infer signup from tfa_enabled=false (passkey users may not use OTP)
        const inSignupFlow = isSignupPath(data.user?.last_opened);

        if (inSignupFlow) {
          // Determine step from last_opened to resume where the user left off
          const step = getStepFromPath(data.user.last_opened);
          currentSignupStep.set(step);
          isInSignupProcess.set(true);
          // CRITICAL: Open login interface to show signup flow after login
          // This ensures the signup flow is visible immediately after login
          const { loginInterfaceOpen } = await import("../stores/uiStateStore");
          loginInterfaceOpen.set(true);
        } else {
          isInSignupProcess.set(false);
        }

        // CRITICAL: Store WebSocket token BEFORE updating authStore
        // This prevents a race condition where the WebSocket service tries to connect
        // before the token is stored in sessionStorage (especially important for Safari/iPad)
        if (data.ws_token) {
          const { setWebSocketToken } = await import("../utils/cookies");
          setWebSocketToken(data.ws_token);
        } else {
          console.warn(
            "[Login] No ws_token in login response - WebSocket connection may fail on Safari/iPad",
          );
        }

        // CRITICAL: Increment login session generation BEFORE resetting logout flags.
        // Any in-flight background logout IIFE from a previous forced-logout will see
        // the bumped counter and skip destructive operations (server logout fetch,
        // cookie deletion) that would otherwise invalidate this new session.
        loginSessionGeneration++;
        console.debug(
          `[AuthStore] Login success — bumped loginSessionGeneration to ${loginSessionGeneration}`,
        );

        // CRITICAL: Reset forcedLogoutInProgress and isLoggingOut flags on successful login
        // This handles the race condition where orphaned database cleanup was triggered on page load
        // (setting these flags to true) but the user then successfully logs in.
        // Without this reset, userDB.saveUserData() would throw "Database initialization blocked during logout"
        const { get } = await import("svelte/store");
        const {
          forcedLogoutInProgress,
          isLoggingOut,
          resetForcedLogoutInProgress,
        } = await import("./signupState");
        if (get(forcedLogoutInProgress)) {
          resetForcedLogoutInProgress();
        }
        if (get(isLoggingOut)) {
          isLoggingOut.set(false);
        }
        // Also clear the cleanup marker to prevent future false positives
        if (typeof localStorage !== "undefined") {
          localStorage.removeItem("openmates_needs_cleanup");
        }

        // Now it's safe to update auth state, which will trigger WebSocket connection
        authStore.update((state) => ({
          ...state,
          isAuthenticated: true,
          isInitialized: true,
        }));

        try {
          if (data.user) {
            // Ensure user data exists before proceeding
            // Log auto top-up fields from backend response - ERROR if missing
            const hasAutoTopupFields =
              "auto_topup_low_balance_enabled" in data.user;
            if (!hasAutoTopupFields) {
              console.error(
                "[Login] ERROR: Auto top-up fields missing from backend response!",
              );
              console.error(
                "[Login] Received user object keys:",
                Object.keys(data.user),
              );
              console.error("[Login] Full user object:", data.user);
            }
            await userDB.saveUserData(data.user);
            const tfa_enabled = !!data.user.tfa_enabled;
            const consent_privacy =
              !!data.user.consent_privacy_and_apps_default_settings;
            const consent_mates = !!data.user.consent_mates_default_settings;
            const userLanguage = data.user.language || defaultProfile.language;
            const userDarkMode = data.user.darkmode ?? defaultProfile.darkmode;

            if (userLanguage && userLanguage !== get(locale)) {
              locale.set(userLanguage);
            }

            updateProfile({
              user_id: (data.user as any).id || null,
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
              timezone: data.user.timezone || null, // Include timezone from server
              // Low balance auto top-up fields
              auto_topup_low_balance_enabled:
                data.user.auto_topup_low_balance_enabled ?? false,
              auto_topup_low_balance_threshold:
                data.user.auto_topup_low_balance_threshold,
              auto_topup_low_balance_amount:
                data.user.auto_topup_low_balance_amount,
              auto_topup_low_balance_currency:
                data.user.auto_topup_low_balance_currency,
              // Refund policy consent — used to skip redundant consent screens in settings
              has_accepted_refund_policy:
                data.user.has_accepted_refund_policy ?? false,
              // Push notification fields — synced from server on login
              push_notification_enabled:
                data.user.push_notification_enabled ?? false,
              push_notification_subscription:
                data.user.push_notification_subscription ?? undefined,
              push_notification_preferences:
                data.user.push_notification_preferences ?? undefined,
              push_notification_banner_shown:
                data.user.push_notification_banner_shown ?? false,
            });

            // Apply server dark mode preference to the theme store.
            // applyServerDarkMode is a no-op when the user already has a local
            // manual preference in localStorage, so local choices always win.
            applyServerDarkMode(userDarkMode);

            // Sync browser timezone to server (non-blocking)
            // This ensures the server always has the user's current timezone
            // for reminders and time-sensitive features
            void syncBrowserTimezone(data.user.timezone);
          } else {
            console.warn(
              "Login successful but no user data received in response.",
            );
            // Even if no user data, mark as authenticated
            authStore.update((state) => ({
              ...state,
              isAuthenticated: true,
              isInitialized: true,
            }));
          }
        } catch (dbError) {
          console.error("Failed to save user data to database:", dbError);
        }

        // Start live console log streaming for admin users,
        // or for ALL authenticated users on dev (frontend errors → OpenObserve).
        // Placed AFTER the try/catch so a userDB failure cannot prevent the
        // forwarder from starting — a DB error is non-fatal for log forwarding.
        if (data.user?.is_admin || isDevEnvironment()) {
          clientLogForwarder.start();
        } else {
          // Non-admin on prod: resume debug log sharing session if one was active
          try {
            const debugSession = localStorage.getItem("debug_session");
            if (debugSession) {
              const parsed = JSON.parse(debugSession);
              const expiresAt = parsed.expires_at
                ? new Date(parsed.expires_at).getTime()
                : Infinity;
              if (expiresAt > Date.now() && parsed.debugging_id) {
                clientLogForwarder.startDebugSession(parsed.debugging_id);
              } else {
                localStorage.removeItem("debug_session");
              }
            }
          } catch {
            // Non-critical — debug session resume is best-effort
          }
        }

        // Start ephemeral log forwarding (login path)
        if (!data.user?.console_log_forwarding_opted_out) {
          clientLogForwarder.startEphemeral();
        }

        return {
          success: true,
          tfa_required: false,
          inSignupFlow,
          backup_code_used: data.backup_code_used || false,
          remaining_backup_codes: data.remaining_backup_codes,
          user: data.user, // Pass user data back
        };
      }
    } else {
      // Login failed
      if (data.tfa_required) {
        // Invalid 2FA code
        console.warn("Login failed: Invalid 2FA code.");
        return {
          success: false,
          tfa_required: true,
          message: data.message || "Invalid 2FA code",
        };
      } else {
        // General failure (e.g., invalid password)
        console.warn("Login failed:", data.message);
        return {
          success: false,
          tfa_required: false,
          message: data.message || "Login failed",
        };
      }
    }
  } catch (error) {
    console.error("Login fetch/network error:", error);
    return {
      success: false,
      tfa_required: false,
      message: "An error occurred during login",
    };
  }
}

/**
 * Logs the user out. Resets local UI state immediately for instant menu feedback,
 * while performing database cleanup and server logout asynchronously in the background.
 * The function returns immediately, ensuring the logout menu button works regardless
 * of server connectivity or database operation speed.
 * @param callbacks Optional callbacks for different stages of the logout process.
 * @returns True if local logout initiated successfully, false otherwise.
 */
export async function logout(callbacks?: LogoutCallbacks): Promise<boolean> {
  // Capture login session generation BEFORE any async work.
  // Both the happy-path and error-recovery background IIFEs use this to detect
  // whether a new login() call succeeded while they were in flight.
  const logoutGeneration = loginSessionGeneration;

  try {
    // --- Pre-request cleanup (non-cookie items) ---
    // Stop admin log streaming before clearing auth state
    void clientLogForwarder.stop();

    // Stop OTel tracing (on prod it was started at login; on dev this is a no-op)
    import("../services/tracing/setup").then(({ stopTracing }) => {
      void stopTracing();
    }).catch(() => {});

    // Clear sensitive crypto data BEFORE server request but AFTER any lookups
    cryptoService.clearKeyFromStorage(); // Clear master key
    cryptoService.clearAllEmailData(); // Clear email encryption key, encrypted email, and salt
    deleteSessionId();
    // Disconnect WebSocket and clear handlers to prevent connection attempts during logout
    webSocketService.disconnectAndClearHandlers();

    // Clear WebSocket token from sessionStorage
    const { clearWebSocketToken } = await import("../utils/cookies");
    clearWebSocketToken();
    // NOTE: Do NOT delete cookies yet - we need them for the server logout request!

    if (callbacks?.beforeLocalLogout) {
      await callbacks.beforeLocalLogout();
    }

    // --- Reset Local UI State IMMEDIATELY ---
    // This must happen synchronously and early to ensure the UI updates right away,
    // regardless of what happens next. The menu button needs this immediate feedback.
    const currentLang = get(userProfile).language;
    const currentMode = get(userProfile).darkmode;
    userProfile.set({
      ...defaultProfile,
      language: currentLang,
      darkmode: currentMode,
    });

    processedImageUrl.set(null);
    resetTwoFAData();
    currentSignupStep.set("basics");
    isResettingTFA.set(false);
    needsDeviceVerification.set(false);
    deviceVerificationType.set(null);
    deviceVerificationReason.set(null);
    phasedSyncState.reset(); // Reset phased sync state on logout
    aiTypingStore.reset(); // Reset typing indicator state on logout to prevent stale "{mate} is typing" indicators
    resetUserAvailableSkills(); // Reset user-specific skill availability so next user gets fresh data
    dailyInspirationStore.reset(); // Clear user-specific inspirations on logout so defaults are shown to logged-out users
    // Immediately repopulate public default inspirations in the same tab session.
    // We intentionally skip IndexedDB on logout because the master key was just
    // cleared and any personalized encrypted records are not usable anymore.
    void import("../demo_chats/loadDefaultInspirations")
      .then(({ loadDefaultInspirations }) =>
        loadDefaultInspirations({ allowIndexedDB: false }),
      )
      .catch((error) => {
        console.error(
          "[AuthStore] Failed to reload public default inspirations after logout:",
          error,
        );
      });

    // CRITICAL: Clear in-memory chat caches IMMEDIATELY during synchronous logout
    // The chatListCache singleton persists across component mounts/unmounts, so if Chats.svelte
    // is destroyed (e.g., sidebar closed on mobile) when logout happens, its authStore subscriber
    // won't fire to clear the cache. Clearing here ensures stale chats never appear after logout.
    chatListCache.clear();
    // CRITICAL: Clear the decrypted metadata cache (title, category, icon, etc.) to prevent
    // stale entries with title: null from being served after re-login, causing "Untitled chat".
    chatMetadataCache.clearAll();
    // CRITICAL: Clear sessionStorage drafts so that the unauthenticated allChats
    // derived in Chats.svelte does NOT build virtual "Untitled chat" ghost entries
    // from stale draft IDs left over from the previous session. This runs BEFORE
    // authStore.set() flips isAuthenticated to false, so the derived never sees
    // the stale data. (Confirmed root cause: ghost chats survive until tab reload
    // because sessionStorage is tab-scoped and isn't cleared by any other logout path.)
    clearAllSessionStorageDrafts();
    chatDB.clearAllChatKeys();
    // Reset the module-level chat list in chatNavigationStore so that stale
    // user chats do not remain in memory when Chats.svelte is unmounted (sidebar
    // closed on mobile). Without this, updateNavFromCache() would use the old list
    // and show hasPrev=true on the intro chat immediately after logout.
    resetChatNavigationList();

    // Clear shared chat keys in the background (async, non-blocking)
    clearAllSharedChatKeys().catch((e) =>
      console.warn(
        "[AuthStore] Failed to clear shared chat keys during logout:",
        e,
      ),
    );

    authStore.set({
      ...authInitialState,
      isInitialized: true,
    });

    if (callbacks?.afterLocalLogout) {
      await callbacks.afterLocalLogout();
    }

    // --- Return immediately so menu button responds instantly ---
    // All remaining cleanup happens in the background

    // --- Background cleanup and server logout (non-blocking) ---
    // These operations run asynchronously and do NOT block the return.
    // This ensures the logout works regardless of server connectivity or DB speed.
    //
    // RACE CONDITION GUARD: logoutGeneration was captured at the top of logout()
    // before any async work. If a new login() succeeds while this IIFE is in-flight,
    // loginSessionGeneration will have been incremented. We check before server logout
    // fetch and cookie deletion — the two operations that would destroy a freshly-
    // established session. Database deletion is safe regardless (stale old-session data).
    (async () => {
      try {
        // Delete local databases in the background
        try {
          await userDB.deleteDatabase();
        } catch (dbError) {
          console.error(
            "[AuthStore] Failed to delete userDB database:",
            dbError,
          );
          if (callbacks?.onError) await callbacks.onError(dbError);
        }
        try {
          await chatDB.deleteDatabase();
        } catch (dbError) {
          console.error(
            "[AuthStore] Failed to delete chatDB database:",
            dbError,
          );
          if (callbacks?.onError) await callbacks.onError(dbError);
        }

        // Clear any pending offline chat deletions from localStorage
        try {
          const { clearAllPendingChatDeletions } =
            await import("../services/pendingChatDeletions");
          clearAllPendingChatDeletions();
        } catch (clearError) {
          console.error(
            "[AuthStore] Failed to clear pending chat deletions:",
            clearError,
          );
        }

        // RACE CONDITION CHECK: If a new login happened while we were deleting
        // databases, skip the server logout and cookie deletion — they would
        // invalidate the new session's credentials.
        if (loginSessionGeneration !== logoutGeneration) {
          console.warn(
            `[AuthStore] New login detected during background logout (gen ${logoutGeneration} → ${loginSessionGeneration}) — skipping server logout and cookie deletion to protect new session`,
          );
          // Still run afterServerCleanup so forcedLogoutInProgress gets reset
          if (callbacks?.afterServerCleanup) {
            try {
              await callbacks.afterServerCleanup();
            } catch (cbError) {
              console.error(
                "[AuthStore] Error in afterServerCleanup callback (skipped-logout path):",
                cbError,
              );
            }
          }
          return;
        }

        // Perform server logout - this ensures the backend is notified even if it's slow
        // If the server is unreachable, the request will fail gracefully and not affect the user
        if (!callbacks?.skipServerLogout) {
          try {
            const logoutApiUrl = getApiEndpoint(apiEndpoints.auth.logout);
            // Use AbortController with 10s timeout to prevent the fetch from hanging
            // indefinitely during device sleep/wake when the network is still recovering.
            // Without this, the afterServerCleanup callback (which resets forcedLogoutInProgress)
            // may never run, leaving the app stuck in a permanent "logout in progress" state.
            const logoutAbortController = new AbortController();
            const logoutTimeoutId = setTimeout(() => {
              logoutAbortController.abort();
              console.warn(
                "[AuthStore] Server logout request timed out after 10s — aborting",
              );
            }, 10_000);
            try {
              const response = await fetch(logoutApiUrl, {
                method: "POST",
                credentials: "include", // Include cookies with request
                headers: { "Content-Type": "application/json" },
                signal: logoutAbortController.signal,
              });
              if (!response.ok) {
                console.error(
                  "Server logout request failed:",
                  response.statusText,
                );
              }
            } finally {
              clearTimeout(logoutTimeoutId);
            }
          } catch (e) {
            console.error(
              "[AuthStore] Server logout API call or URL resolution failed (user already logged out locally):",
              e,
            );
            if (callbacks?.onError) await callbacks.onError(e);
          }
        } else if (callbacks?.isPolicyViolation) {
          try {
            const policyLogoutApiUrl = getApiEndpoint(
              apiEndpoints.auth.policyViolationLogout,
            );
            const policyAbortController = new AbortController();
            const policyTimeoutId = setTimeout(() => {
              policyAbortController.abort();
              console.warn(
                "[AuthStore] Policy violation logout request timed out after 10s — aborting",
              );
            }, 10_000);
            try {
              await fetch(policyLogoutApiUrl, {
                method: "POST",
                credentials: "include", // Include cookies with request
                headers: { "Content-Type": "application/json" },
                signal: policyAbortController.signal,
              });
            } finally {
              clearTimeout(policyTimeoutId);
            }
          } catch (e) {
            console.error(
              "[AuthStore] Policy violation logout API call failed (user already logged out locally):",
              e,
            );
            if (callbacks?.onError) await callbacks.onError(e);
          }
        }

        // RACE CONDITION CHECK (post-fetch): A login may have succeeded while the
        // server logout request was in flight. Skip cookie deletion to keep the
        // new session's cookies intact.
        if (loginSessionGeneration !== logoutGeneration) {
          console.warn(
            `[AuthStore] New login detected after server logout fetch (gen ${logoutGeneration} → ${loginSessionGeneration}) — skipping cookie deletion to protect new session`,
          );
        } else {
          // --- CRITICAL: Delete cookies AFTER server logout request ---
          // This ensures the server receives the refresh token to properly invalidate the session
          deleteAllCookies();
        }
      } catch (serverError) {
        console.error(
          "[AuthStore] Unexpected error during background server logout processing:",
          serverError,
        );
        if (callbacks?.onError) await callbacks.onError(serverError);
        // Only delete cookies if no new login happened
        if (loginSessionGeneration === logoutGeneration) {
          deleteAllCookies();
        }
      }

      // --- Final Callbacks --- (after server operations)
      if (callbacks?.afterServerCleanup) {
        try {
          await callbacks.afterServerCleanup();
        } catch (cbError) {
          console.error(
            "[AuthStore] Error in afterServerCleanup callback:",
            cbError,
          );
        }
      }
    })(); // End of background IIFE - this runs without blocking the return

    return true; // Indicate local logout initiated successfully - UI is already updated
  } catch (error) {
    // Handle critical errors during the synchronous part
    console.error("[AuthStore] Critical error during logout process:", error);
    if (callbacks?.onError) {
      await callbacks.onError(error);
    }

    // Attempt to reset essential auth state even on critical error
    try {
      // Clear all sensitive cryptographic data even during error handling
      cryptoService.clearKeyFromStorage();
      cryptoService.clearAllEmailData();
      // CRITICAL: Clear in-memory chat caches even during error recovery
      chatListCache.clear();
      chatMetadataCache.clearAll();
      chatDB.clearAllChatKeys();
      clearAllSharedChatKeys().catch(() => {});
      // CRITICAL: Clear session_id from sessionStorage for security
      // This ensures session_id is removed even if logout fails
      deleteSessionId();
      // Clear WebSocket token from sessionStorage
      const { clearWebSocketToken } = await import("../utils/cookies");
      clearWebSocketToken();

      authStore.set({ ...authInitialState, isInitialized: true });
      const currentLang = get(userProfile)?.language ?? defaultProfile.language;
      const currentMode = get(userProfile)?.darkmode ?? defaultProfile.darkmode;
      userProfile.set({
        ...defaultProfile,
        language: currentLang,
        darkmode: currentMode,
      });
    } catch (resetError) {
      console.error(
        "[AuthStore] Failed to reset state even during critical error handling:",
        resetError,
      );
    }

    // Still attempt server logout and cleanup in background even on error
    // This ensures that even if something fails locally, the backend is still notified
    // Uses logoutGeneration captured at the top of logout() to guard against new logins.
    (async () => {
      try {
        // RACE CONDITION CHECK: Skip server logout if a new login happened
        if (loginSessionGeneration !== logoutGeneration) {
          console.warn(
            `[AuthStore] New login detected during error-recovery logout (gen ${logoutGeneration} → ${loginSessionGeneration}) — skipping server logout`,
          );
        } else if (!callbacks?.skipServerLogout) {
          try {
            const logoutApiUrl = getApiEndpoint(apiEndpoints.auth.logout);
            const response = await fetch(logoutApiUrl, {
              method: "POST",
              credentials: "include", // Include cookies with request
              headers: { "Content-Type": "application/json" },
            });
            if (!response.ok) {
              console.error(
                "[AuthStore] Server logout failed from error recovery:",
                response.statusText,
              );
            }
          } catch (e) {
            console.error(
              "[AuthStore] Server logout failed in error recovery path:",
              e,
            );
          }
        }

        // Only delete cookies/session if no new login happened
        if (loginSessionGeneration === logoutGeneration) {
          deleteAllCookies();
          deleteSessionId();
          const { clearWebSocketToken } = await import("../utils/cookies");
          clearWebSocketToken();
        } else {
          console.warn(
            "[AuthStore] Skipping cookie/session deletion in error recovery — new login active",
          );
        }

        // Try afterServerCleanup even in error recovery
        if (callbacks?.afterServerCleanup) {
          try {
            await callbacks.afterServerCleanup();
          } catch (cbError) {
            console.error(
              "[AuthStore] Error in afterServerCleanup during error recovery:",
              cbError,
            );
          }
        }
      } catch (e) {
        console.error(
          "[AuthStore] Unexpected error during background error recovery logout:",
          e,
        );
      }
    })();

    return false; // Indicate critical logout failure occurred
  }
}

/**
 * Deletes all cookies visible to JavaScript by setting their expiration date to the past.
 *
 * LIMITATION: This function CANNOT delete httpOnly cookies (e.g., auth_refresh_token)
 * because document.cookie cannot enumerate them (browser security by design).
 * The backend logout endpoint (auth_logout.py) is the ONLY reliable mechanism for
 * clearing httpOnly auth cookies via Set-Cookie response headers.
 */
export function deleteAllCookies(): void {
  const cookies = document.cookie.split(";");

  for (let i = 0; i < cookies.length; i++) {
    const cookie = cookies[i];
    const eqPos = cookie.indexOf("=");
    const name = eqPos > -1 ? cookie.substring(0, eqPos).trim() : cookie.trim();

    if (name) {
      // Set expiration to a past date to delete the cookie with path /
      // Use SameSite=Lax to match backend cookie settings for Safari/iOS compatibility
      document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; SameSite=Lax`;
    }
  }
}
