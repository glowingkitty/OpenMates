// frontend/packages/ui/src/stores/authLoginLogoutActions.ts
/**
 * @fileoverview Actions related to user login and logout processes.
 */

import { get } from "svelte/store";
import { getApiEndpoint, getApiUrl, apiEndpoints } from "../config/api";
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
import { webSocketService } from "../services/websocketService";

// Import core auth state and related flags
import {
  authStore,
  needsDeviceVerification,
  deviceVerificationType,
  authInitialState,
} from "./authState";
// Import auth types
import type { LoginResult, LogoutCallbacks } from "./authTypes";
import { getSessionId } from "../utils/sessionId";

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
      console.debug(
        `[Timezone] Browser timezone matches server (${browserTimezone}), no sync needed`,
      );
      return;
    }

    console.debug(
      `[Timezone] Syncing timezone: browser=${browserTimezone}, server=${serverTimezone || "not set"}`,
    );

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
    } else {
      console.debug(
        `[Timezone] Successfully synced timezone to server: ${browserTimezone}`,
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
  stayLoggedIn: boolean = false, // New parameter
): Promise<LoginResult> {
  try {
    console.debug(
      `Attempting login... (TFA Code Provided: ${!!tfaCode}, Type: ${codeType || "otp"}, Stay Logged In: ${stayLoggedIn})`,
    );

    const requestBody: any = { hashed_email, lookup_hash };
    if (tfaCode) {
      requestBody.tfa_code = tfaCode;
      requestBody.code_type = codeType || "otp";
    }
    // No need to send stayLoggedIn to backend, it's a frontend storage preference

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
    console.debug("Login response data:", data);

    if (data.success) {
      if (data.tfa_required) {
        // Password OK, 2FA needed
        console.debug("Login step 1 successful, 2FA required.");
        return {
          success: true,
          tfa_required: true,
          // Check if user exists before accessing tfa_app_name
          tfa_app_name: data.user?.tfa_app_name,
        };
      } else {
        // Full success
        console.debug("Login fully successful.");
        // Check if user exists before accessing last_opened
        // A user is in signup flow only if last_opened explicitly indicates signup
        // Do not infer signup from tfa_enabled=false (passkey users may not use OTP)
        const inSignupFlow = isSignupPath(data.user?.last_opened);

        if (inSignupFlow) {
          console.debug("User is in signup process:", {
            last_opened: data.user?.last_opened,
            tfa_enabled: data.user?.tfa_enabled,
          });
          // Determine step from last_opened to resume where the user left off
          const step = getStepFromPath(data.user.last_opened);
          currentSignupStep.set(step);
          isInSignupProcess.set(true);
          // CRITICAL: Open login interface to show signup flow after login
          // This ensures the signup flow is visible immediately after login
          const { loginInterfaceOpen } = await import("../stores/uiStateStore");
          loginInterfaceOpen.set(true);
          console.debug(
            "Set signup step to:",
            step,
            "and opened login interface",
          );
        } else {
          isInSignupProcess.set(false);
        }

        // CRITICAL: Store WebSocket token BEFORE updating authStore
        // This prevents a race condition where the WebSocket service tries to connect
        // before the token is stored in sessionStorage (especially important for Safari/iPad)
        if (data.ws_token) {
          const { setWebSocketToken } = await import("../utils/cookies");
          setWebSocketToken(data.ws_token);
          console.debug("[Login] WebSocket token stored from login response");
        } else {
          console.warn(
            "[Login] No ws_token in login response - WebSocket connection may fail on Safari/iPad",
          );
        }

        // CRITICAL: Reset forcedLogoutInProgress and isLoggingOut flags on successful login
        // This handles the race condition where orphaned database cleanup was triggered on page load
        // (setting these flags to true) but the user then successfully logs in.
        // Without this reset, userDB.saveUserData() would throw "Database initialization blocked during logout"
        const { get } = await import("svelte/store");
        const { forcedLogoutInProgress, isLoggingOut } =
          await import("./signupState");
        if (get(forcedLogoutInProgress)) {
          console.debug(
            "[Login] Resetting forcedLogoutInProgress to false - successful login with valid master key",
          );
          forcedLogoutInProgress.set(false);
        }
        if (get(isLoggingOut)) {
          console.debug(
            "[Login] Resetting isLoggingOut to false - successful login",
          );
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
            } else {
              console.debug("[Login] Auto top-up fields from backend:", {
                enabled: data.user.auto_topup_low_balance_enabled,
                threshold: data.user.auto_topup_low_balance_threshold,
                amount: data.user.auto_topup_low_balance_amount,
                currency: data.user.auto_topup_low_balance_currency,
              });
            }
            await userDB.saveUserData(data.user);
            const tfa_enabled = !!data.user.tfa_enabled;
            const consent_privacy =
              !!data.user.consent_privacy_and_apps_default_settings;
            const consent_mates = !!data.user.consent_mates_default_settings;
            const userLanguage = data.user.language || defaultProfile.language;
            const userDarkMode = data.user.darkmode ?? defaultProfile.darkmode;

            if (userLanguage && userLanguage !== get(locale)) {
              console.debug(
                `Applying user language from login: ${userLanguage}`,
              );
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
            });

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
  console.debug("Attempting to log out and clear local data...");

  try {
    // --- Pre-request cleanup (non-cookie items) ---
    // Clear sensitive crypto data BEFORE server request but AFTER any lookups
    console.debug("[AuthStore] Clearing sensitive data...");
    cryptoService.clearKeyFromStorage(); // Clear master key
    cryptoService.clearAllEmailData(); // Clear email encryption key, encrypted email, and salt
    deleteSessionId();
    // Disconnect WebSocket and clear handlers to prevent connection attempts during logout
    console.debug(
      "[AuthStore] Disconnecting WebSocket and clearing handlers...",
    );
    webSocketService.disconnectAndClearHandlers();

    // Clear WebSocket token from sessionStorage
    const { clearWebSocketToken } = await import("../utils/cookies");
    clearWebSocketToken();
    console.debug("[AuthStore] WebSocket token cleared from sessionStorage");
    // NOTE: Do NOT delete cookies yet - we need them for the server logout request!

    if (callbacks?.beforeLocalLogout) {
      await callbacks.beforeLocalLogout();
    }

    // --- Reset Local UI State IMMEDIATELY ---
    // This must happen synchronously and early to ensure the UI updates right away,
    // regardless of what happens next. The menu button needs this immediate feedback.
    console.debug("[AuthStore] Resetting local UI state immediately...");
    const currentLang = get(userProfile).language;
    const currentMode = get(userProfile).darkmode;
    userProfile.set({
      ...defaultProfile,
      language: currentLang,
      darkmode: currentMode,
    });
    console.debug("[UserProfileStore] In-memory profile reset via set()");

    processedImageUrl.set(null);
    resetTwoFAData();
    currentSignupStep.set("basics");
    isResettingTFA.set(false);
    needsDeviceVerification.set(false);
    deviceVerificationType.set(null);
    phasedSyncState.reset(); // Reset phased sync state on logout
    aiTypingStore.reset(); // Reset typing indicator state on logout to prevent stale "{mate} is typing" indicators
    authStore.set({
      ...authInitialState,
      isInitialized: true,
    });
    console.debug(
      "[AuthStore] Local UI state reset complete - menu button should now update immediately.",
    );

    if (callbacks?.afterLocalLogout) {
      await callbacks.afterLocalLogout();
    }

    // --- Return immediately so menu button responds instantly ---
    // All remaining cleanup happens in the background
    console.debug("[AuthStore] Returning to caller - UI updates are complete.");

    // --- Background cleanup and server logout (non-blocking) ---
    // These operations run asynchronously and do NOT block the return.
    // This ensures the logout works regardless of server connectivity or DB speed.
    (async () => {
      console.debug(
        "[AuthStore] Starting background database and server cleanup...",
      );
      try {
        // Delete local databases in the background
        console.debug(
          "[AuthStore] Attempting local database cleanup in background...",
        );
        try {
          await userDB.deleteDatabase();
          console.debug(
            "[AuthStore] UserDB database deleted successfully in background.",
          );
        } catch (dbError) {
          console.error(
            "[AuthStore] Failed to delete userDB database:",
            dbError,
          );
          if (callbacks?.onError) await callbacks.onError(dbError);
        }
        try {
          await chatDB.deleteDatabase();
          console.debug(
            "[AuthStore] ChatDB database deleted successfully in background.",
          );
        } catch (dbError) {
          console.error(
            "[AuthStore] Failed to delete chatDB database:",
            dbError,
          );
          if (callbacks?.onError) await callbacks.onError(dbError);
        }

        // Perform server logout - this ensures the backend is notified even if it's slow
        // If the server is unreachable, the request will fail gracefully and not affect the user
        console.debug(
          "[AuthStore] Performing server-side logout operations...",
        );
        if (!callbacks?.skipServerLogout) {
          try {
            const logoutApiUrl = getApiEndpoint(apiEndpoints.auth.logout);
            console.debug(
              "[AuthStore] Sending logout request to server with auth cookies...",
            );
            const response = await fetch(logoutApiUrl, {
              method: "POST",
              credentials: "include", // Include cookies with request
              headers: { "Content-Type": "application/json" },
            });
            if (!response.ok) {
              console.error(
                "Server logout request failed:",
                response.statusText,
              );
            } else {
              console.debug("[AuthStore] Server logout successful.");
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
            console.debug(
              "[AuthStore] Sending policy violation logout request to server with auth cookies...",
            );
            const response = await fetch(policyLogoutApiUrl, {
              method: "POST",
              credentials: "include", // Include cookies with request
              headers: { "Content-Type": "application/json" },
            });
            console.debug(
              "[AuthStore] Policy violation logout response:",
              response.ok,
            );
          } catch (e) {
            console.error(
              "[AuthStore] Policy violation logout API call failed (user already logged out locally):",
              e,
            );
            if (callbacks?.onError) await callbacks.onError(e);
          }
        }

        // --- CRITICAL: Delete cookies AFTER server logout request ---
        // This ensures the server receives the refresh token to properly invalidate the session
        console.debug(
          "[AuthStore] Deleting all cookies after server logout...",
        );
        deleteAllCookies();
      } catch (serverError) {
        console.error(
          "[AuthStore] Unexpected error during background server logout processing:",
          serverError,
        );
        if (callbacks?.onError) await callbacks.onError(serverError);
        // Still delete cookies even on error
        deleteAllCookies();
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
      console.debug(
        "[AuthStore] Attempting critical error recovery - resetting auth state...",
      );
      // Clear all sensitive cryptographic data even during error handling
      cryptoService.clearKeyFromStorage();
      cryptoService.clearAllEmailData();
      // CRITICAL: Clear session_id from sessionStorage for security
      // This ensures session_id is removed even if logout fails
      deleteSessionId();
      // Clear WebSocket token from sessionStorage
      const { clearWebSocketToken } = await import("../utils/cookies");
      clearWebSocketToken();
      console.debug(
        "[AuthStore] Session ID and WebSocket token cleared in error recovery",
      );

      authStore.set({ ...authInitialState, isInitialized: true });
      const currentLang = get(userProfile)?.language ?? defaultProfile.language;
      const currentMode = get(userProfile)?.darkmode ?? defaultProfile.darkmode;
      userProfile.set({
        ...defaultProfile,
        language: currentLang,
        darkmode: currentMode,
      });
      console.debug(
        "[AuthStore] Critical error recovery complete - UI state reset.",
      );
    } catch (resetError) {
      console.error(
        "[AuthStore] Failed to reset state even during critical error handling:",
        resetError,
      );
    }

    // Still attempt server logout and cleanup in background even on error
    // This ensures that even if something fails locally, the backend is still notified
    (async () => {
      try {
        console.debug(
          "[AuthStore] Attempting server logout from error recovery path...",
        );
        if (!callbacks?.skipServerLogout) {
          try {
            const logoutApiUrl = getApiEndpoint(apiEndpoints.auth.logout);
            console.debug(
              "[AuthStore] Sending logout request from error recovery with auth cookies...",
            );
            const response = await fetch(logoutApiUrl, {
              method: "POST",
              credentials: "include", // Include cookies with request
              headers: { "Content-Type": "application/json" },
            });
            if (response.ok) {
              console.debug(
                "[AuthStore] Server logout successful from error recovery.",
              );
            } else {
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

        // Delete cookies and session_id after server request
        deleteAllCookies();
        // Ensure session_id is cleared even in error recovery path
        deleteSessionId();
        // Clear WebSocket token from sessionStorage
        const { clearWebSocketToken } = await import("../utils/cookies");
        clearWebSocketToken();
        console.debug(
          "[AuthStore] Session ID and WebSocket token cleared in background error recovery",
        );

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
 * Deletes all cookies by setting their expiration date to the past.
 * This ensures complete cookie cleanup during logout for enhanced security.
 * Includes deletion of Stripe cookies (__stripe_mid, __stripe_sid) and all other cookies.
 */
export function deleteAllCookies(): void {
  console.debug("[AuthStore] Deleting all cookies...");
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

  console.debug("[AuthStore] All cookies deleted");
}
