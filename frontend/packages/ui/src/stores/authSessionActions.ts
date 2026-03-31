// frontend/packages/ui/src/stores/authSessionActions.ts
/**
 * @fileoverview Actions related to checking and initializing the user's session state.
 */

import { get } from "svelte/store";
import { getApiEndpoint, apiEndpoints, isDevEnvironment } from "../config/api";
import {
  currentSignupStep,
  isInSignupProcess,
  getStepFromPath,
  STEP_ALPHA_DISCLAIMER,
  isSignupPath,
} from "./signupState";
import { requireInviteCode } from "./signupRequirements";
import { userDB } from "../services/userDB";
import { chatDB } from "../services/db"; // Import chatDB
import { userProfile, defaultProfile, updateProfile } from "./userProfile";
import { locale } from "svelte-i18n";
import * as cryptoService from "../services/cryptoService";
import { deleteSessionId } from "../utils/sessionId"; // Import deleteSessionId
import { logout, deleteAllCookies, bumpLoginSessionGeneration } from "./authLoginLogoutActions"; // Import logout function, deleteAllCookies, and bumpLoginSessionGeneration
import { setWebSocketToken, clearWebSocketToken } from "../utils/cookies"; // Import WebSocket token utilities
import { notificationStore } from "./notificationStore"; // Import notification store for logout notifications
import { loadUserProfileFromDB } from "./userProfile"; // Import to load user profile from IndexedDB
import { loginInterfaceOpen } from "./uiStateStore"; // Import loginInterfaceOpen to control login interface visibility
import { activeChatStore } from "./activeChatStore"; // Import activeChatStore to navigate to demo-for-everyone on logout
import { clearSignupData, clearIncompleteSignupData } from "./signupStore"; // Import signup cleanup functions
import { clearAllSessionStorageDrafts } from "../services/drafts/sessionStorageDraftService"; // Import sessionStorage draft cleanup
import {
  isLoggingOut,
  forcedLogoutInProgress,
  setForcedLogoutInProgress,
  resetForcedLogoutInProgress,
} from "./signupState"; // Import isLoggingOut and forcedLogoutInProgress to track logout state
import { phasedSyncState } from "./phasedSyncStateStore"; // Import phased sync state to reset on login
import { text } from "../i18n/translations"; // Import text store for translations
import { chatListCache } from "../services/chatListCache"; // Import chatListCache to clear stale chat data on session expiry
import { chatMetadataCache } from "../services/chatMetadataCache"; // Import chatMetadataCache to clear stale decrypted title/metadata cache on logout
import { clearAllSharedChatKeys } from "../services/sharedChatKeyStorage"; // Import to clear shared chat keys on session expiry
import { isValidLocale } from "../i18n/types"; // Import to validate localStorage language values (OPE-39)
import { clientLogForwarder } from "../services/clientLogForwarder"; // Admin live log streaming to OpenObserve
import { appSettingsMemoriesStore } from "./appSettingsMemoriesStore"; // Import to pre-load entries for @ mention dropdown
import { applyServerDarkMode } from "./theme"; // Apply server dark mode preference on session restore

// Import core auth state and related flags
import {
  authStore,
  isCheckingAuth,
  needsDeviceVerification,
  deviceVerificationType,
  deviceVerificationReason,
} from "./authState";
// Import auth types
import type { SessionCheckResult } from "./authTypes";

/**
 * Checks the current authentication status by calling the session endpoint.
 * Updates auth state, user profile, and handles device verification requirements.
 * @param deviceSignals Optional device fingerprinting data.
 * @returns True if fully authenticated, false otherwise.
 */
export async function checkAuth(
  deviceSignals?: Record<string, string | null>,
  force: boolean = false,
): Promise<boolean> {
  // Prevent check if already checking or initialized (unless forced)
  // Allow check if needsDeviceVerification is true, as this indicates a pending state that needs resolution.
  if (
    !force &&
    (get(isCheckingAuth) ||
      (get(authStore).isInitialized && !get(needsDeviceVerification)))
  ) {
    console.debug(
      "Auth check skipped (already checking or initialized, and not in device verification flow).",
    );
    return get(authStore).isAuthenticated;
  }

  isCheckingAuth.set(true);
  needsDeviceVerification.set(false); // Reset verification need
  deviceVerificationType.set(null); // Reset verification type
  deviceVerificationReason.set(null); // Reset verification reason

  try {
    // Import getSessionId to include session_id in the request
    const { getSessionId } = await import("../utils/sessionId");

    console.debug("Checking authentication with session endpoint...");

    let response: Response;
    let data: SessionCheckResult;

    try {
      // Use a 10-second AbortController timeout so that if the server is overloaded
      // (accepts TCP but never responds), the fetch aborts and hits the offline-first
      // catch block below instead of hanging indefinitely — which would leave
      // isAuthenticated=false and prevent IndexedDB chats from loading.
      const authAbortController = new AbortController();
      const authTimeoutId = setTimeout(() => {
        console.warn(
          "[AuthSessionActions] Session check timed out after 10s — server may be overloaded, switching to offline-first mode",
        );
        authAbortController.abort();
      }, 10000);

      try {
        response = await fetch(getApiEndpoint(apiEndpoints.auth.session), {
          method: "POST",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            Origin: window.location.origin,
          },
          body: JSON.stringify({
            deviceSignals: deviceSignals || {},
            session_id: getSessionId(), // Include session_id for device fingerprinting
          }),
          credentials: "include",
          signal: authAbortController.signal,
        });
      } finally {
        clearTimeout(authTimeoutId);
      }

      // Check if response is OK (status 200-299)
      // If not OK, treat as network/server error and be optimistic
      if (!response.ok) {
        console.warn(
          `[AuthSessionActions] Session endpoint returned non-OK status: ${response.status} - treating as network error (offline-first mode)`,
        );
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      data = await response.json();
      console.debug("Session check response:", data);
    } catch (fetchError) {
      // Network error, timeout, AbortError, or non-OK response - be optimistic
      console.warn(
        "[AuthSessionActions] Network error or non-OK response during auth check (offline-first):",
        fetchError,
      );
      throw fetchError; // Re-throw to be caught by outer catch block
    }

    // Handle Device Verification Required (2FA OTP or passkey)
    if (
      !data.success &&
      (data.re_auth_required === "2fa" || data.re_auth_required === "passkey")
    ) {
      console.warn(
        `Session check indicates device ${data.re_auth_required} verification is required (reason: ${data.re_auth_reason || "new_device"}).`,
      );
      needsDeviceVerification.set(true);
      deviceVerificationType.set(data.re_auth_required);
      deviceVerificationReason.set(data.re_auth_reason || "new_device");
      authStore.update((state) => ({
        ...state,
        isAuthenticated: false,
        isInitialized: true,
      }));
      // Clear potentially stale user data
      updateProfile({
        username: null,
        profile_image_url: null,
        tfa_app_name: null,
        tfa_enabled: false,
        credits: 0,
        is_admin: false,
        last_opened: null,
        consent_privacy_and_apps_default_settings: false,
        consent_mates_default_settings: false,
        darkmode: defaultProfile.darkmode, // Reset darkmode
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
        console.debug(
          "[AuthSessionActions] WebSocket token stored from session response",
        );
      } else {
        console.warn(
          "[AuthSessionActions] No ws_token in session response - WebSocket connection may fail on Safari/iPad",
        );
      }

      // Track whether forcedLogoutInProgress was already set (e.g. by +page.svelte onMount)
      // If so, we still need to proceed with cleanup — but skip duplicate notifications and flag-setting.
      const alreadyForcedLogout = get(forcedLogoutInProgress);

      const masterKey = await cryptoService.getKeyFromStorage(); // Use getKeyFromStorage (now async)
      if (!masterKey) {
        console.warn(
          "User is authenticated but master key is not found in storage. Forcing logout and clearing data.",
        );

        // CRITICAL: Set forcedLogoutInProgress flag FIRST, SYNCHRONOUSLY, before ANY other state changes
        // This prevents race conditions where other components try to load/decrypt encrypted chats
        // that can no longer be decrypted (because master key is missing).
        // This flag is checked in chat loading and decryption code to skip those operations.
        if (!alreadyForcedLogout) {
          setForcedLogoutInProgress();
          console.debug(
            "[AuthSessionActions] Set forcedLogoutInProgress to true - blocking encrypted chat loading",
          );
        } else {
          console.debug(
            "[AuthSessionActions] forcedLogoutInProgress already true (set by +page.svelte) - proceeding with cleanup",
          );
        }

        // CRITICAL: Navigate to demo-for-everyone IMMEDIATELY (synchronously) BEFORE auth state changes
        // This ensures any component reading activeChatStore will see demo-for-everyone, not the old chat
        //
        // EXCEPTION: If a shared chat redirect is in progress, do NOT override with demo-for-everyone.
        // Shared chats use URL-embedded encryption keys (not the master key), so they work perfectly
        // fine without a master key. The sessionStorage flag 'openmates_skip_orphan_detection' is set
        // by the share chat page to indicate a shared chat session is active.
        // The 'openmates_shared_chat_redirect' flag is set just before navigating from share page to root.
        const isSharedChatSession =
          typeof window !== "undefined" &&
          typeof sessionStorage !== "undefined" &&
          (sessionStorage.getItem("openmates_skip_orphan_detection") ===
            "true" ||
            sessionStorage.getItem("openmates_shared_chat_redirect") !== null);

        // PAIR LOGIN DETECTION: If user arrived via /#pair=TOKEN, they are about to
        // authenticate fresh. Firing destructive logout (server logout + cookie deletion)
        // would race with the new login and could invalidate the session established by
        // the passkey flow. Detect via URL hash or sessionStorage pendingDeepLink.
        const isPairLoginPending =
          typeof window !== "undefined" &&
          (/^#pair=[A-Za-z0-9]{6}$/i.test(window.location.hash) ||
            (typeof sessionStorage !== "undefined" &&
              /^#pair=[A-Za-z0-9]{6}$/i.test(
                sessionStorage.getItem("pendingDeepLink") ?? "",
              )));

        // OG image mode (?og=1): skip demo-for-everyone redirect so the welcome screen
        // (daily inspiration + for-everyone card) stays visible in /dev/og-image iframes.
        const isOgImageMode =
          typeof window !== "undefined" &&
          new URLSearchParams(window.location.search).get("og") === "1";

        if (typeof window !== "undefined") {
          if (isSharedChatSession) {
            console.debug(
              "[AuthSessionActions] Skipping demo-for-everyone override — shared chat session detected (key in URL fragment, not master key)",
            );
          } else if (isPairLoginPending) {
            console.debug(
              "[AuthSessionActions] Skipping demo-for-everyone override — pair login deep link pending, user will authenticate fresh",
            );
          } else if (isOgImageMode) {
            console.debug(
              "[AuthSessionActions] Skipping demo-for-everyone override — og=1 mode (welcome screen should stay visible)",
            );
          } else {
            activeChatStore.setActiveChat("demo-for-everyone");
            window.location.hash = "chat-id=demo-for-everyone";
            console.debug(
              "[AuthSessionActions] Navigated to demo-for-everyone chat IMMEDIATELY (synchronous) - missing master key",
            );
          }
        }

        // Set auth state (don't block on database deletion)
        authStore.update((state) => ({
          ...state,
          isAuthenticated: false,
          isInitialized: true,
        }));

        // Show notification with context-appropriate message — but only if we haven't already
        // shown one (when +page.svelte sets the flag, it shows its own notification via setTimeout).
        // Also skip for shared chat sessions and pair login — users opening a share link or pair
        // link shouldn't see logout alerts.
        // Also skip if the local profile is completely empty (username falsy, user_id null) — this
        // means the user has no local session record (e.g. DB schema upgrade wiped data, or a stale
        // server cookie survived an explicit logout). Showing "You have been logged out" is
        // misleading when the user was never logged in from the browser's perspective.
        const localProfile = get(userProfile);
        const hadLocalSession =
          localProfile?.username || localProfile?.user_id;

        if (
          !alreadyForcedLogout &&
          !isSharedChatSession &&
          !isPairLoginPending &&
          hadLocalSession
        ) {
          const $text = get(text);
          const { wasStayLoggedIn } =
            await import("../services/cryptoKeyStorage");
          const wasStorageEvicted = wasStayLoggedIn();

          if (wasStorageEvicted) {
            // User had stayLoggedIn=true but browser evicted IndexedDB (e.g. iOS Safari storage pressure)
            // Show reassuring message that data is safe
            console.warn(
              "[AuthSessionActions] Storage eviction detected: user had stayLoggedIn=true but master key is missing from IndexedDB",
            );
            notificationStore.autoLogout(
              $text("login.auto_logout_notification.storage_evicted_message"),
              undefined,
              10000, // Show for 10 seconds — this is unexpected, give user more time to read
              $text("login.auto_logout_notification.storage_evicted_title"),
            );
          } else {
            // Normal case: user had stayLoggedIn=false, key was in memory and lost on page reload
            notificationStore.autoLogout(
              $text("login.auto_logout_notification.message"),
              undefined,
              7000, // Show for 7 seconds so user can read the hint
              $text("login.auto_logout_notification.title"),
            );
          }
        }

        // CRITICAL: For shared chat sessions and pair login deep links, skip destructive logout.
        // Shared chats are stored in IndexedDB with their own encryption keys (from the URL
        // fragment). The logout() call below deletes the entire database, which would wipe
        // the shared chat data.
        // Pair login deep links will open the login screen — the user authenticates fresh and
        // derives a new master key. The background logout IIFE would race with the new session
        // (POST /auth/logout with credentials: 'include' sends the new session's cookies).
        // Simply clearing auth state is sufficient for both cases.
        if (!isSharedChatSession && !isPairLoginPending) {
          isLoggingOut.set(true);
          console.debug(
            "[AuthSessionActions] Set isLoggingOut to true for missing master key logout",
          );

          // CRITICAL: Close the settings menu and reset to main page during forced logout.
          // This prevents users from being stuck in an auth-only settings sub-page (e.g. account/security)
          // after being forced out. Dispatches a window event that Settings.svelte listens to,
          // avoiding circular module dependencies from importing the component directly.
          if (typeof window !== "undefined") {
            window.dispatchEvent(new CustomEvent("forceCloseSettings"));
            console.debug(
              "[AuthSessionActions] Dispatched forceCloseSettings event on forced logout",
            );
          }

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
              console.debug(
                "[AuthSessionActions] afterLocalLogout called - flags NOT reset yet (waiting for DB cleanup)",
              );
            },
            afterServerCleanup: async () => {
              // CRITICAL: Reset flags AFTER database deletion completes (in logout()'s background IIFE)
              // This ensures forcedLogoutInProgress stays true during the entire deletion process
              isLoggingOut.set(false);
              resetForcedLogoutInProgress();
              console.debug(
                "[AuthSessionActions] Reset logout flags after server cleanup and DB deletion",
              );
            },
          }).catch((err) => {
            console.error("[AuthSessionActions] Logout failed:", err);
            // Reset logout flags even if logout fails
            isLoggingOut.set(false);
            resetForcedLogoutInProgress();
          });

          deleteSessionId(); // Remove session_id on forced logout
        } else {
          console.debug(
            `[AuthSessionActions] Skipping destructive logout — ${isPairLoginPending ? "pair login pending" : "shared chat session"} — only clearing auth state`,
          );
          // Still reset forcedLogoutInProgress since we're not doing a full logout
          resetForcedLogoutInProgress();
        }
        cryptoService.clearAllEmailData(); // Clear email encryption key, encrypted email, and salt
        // Only delete cookies if not a pair login — the user needs the existing session
        // cookies intact so checkAuth() can validate after passkey login succeeds.
        if (!isPairLoginPending) {
          deleteAllCookies();
        }
        return false;
      }

      // CRITICAL FIX: Reset forcedLogoutInProgress and isLoggingOut flags when authentication succeeds with valid master key
      // This handles the race condition where the flags were set (e.g., during page load detecting
      // "profile exists but no master key") but the user then successfully authenticates.
      // Without this reset, the flags stay true and cause database operations to fail.
      if (get(forcedLogoutInProgress)) {
        console.debug(
          "[AuthSessionActions] Resetting forcedLogoutInProgress to false - auth succeeded with valid master key",
        );
        resetForcedLogoutInProgress();
      }
      if (get(isLoggingOut)) {
        console.debug(
          "[AuthSessionActions] Resetting isLoggingOut to false - auth succeeded with valid master key",
        );
        isLoggingOut.set(false);
      }
      // Also clear the cleanup marker to prevent future false positives
      if (typeof localStorage !== "undefined") {
        localStorage.removeItem("openmates_needs_cleanup");
      }

      needsDeviceVerification.set(false);
      deviceVerificationType.set(null);
      deviceVerificationReason.set(null);

      // CRITICAL: Check URL hash directly - hash takes absolute precedence over everything
      // This ensures hash-based signup state works even if set after checkAuth() starts
      let hasSignupHash = false;
      let hashStep: string | null = null;
      if (
        typeof window !== "undefined" &&
        window.location.hash.startsWith("#signup/")
      ) {
        hasSignupHash = true;
        const signupHash = window.location.hash.substring(1); // Remove leading #
        hashStep = getStepFromPath(signupHash);
        console.debug(
          "checkAuth() found signup hash in URL:",
          window.location.hash,
          "-> step:",
          hashStep,
        );
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
      const inSignupFlow =
        hasSignupHash ||
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
            tfa_enabled: data.user.tfa_enabled,
          });
          // Determine step from last_opened (hash-based paths) to resume precisely
          const step = getStepFromPath(data.user.last_opened);
          currentSignupStep.set(step);
          isInSignupProcess.set(true);
          // CRITICAL: Open login interface to show signup flow on page reload
          // This ensures the signup flow is visible immediately when the page reloads
          loginInterfaceOpen.set(true);
          console.debug(
            "Set signup step to:",
            step,
            "and opened login interface",
          );
        } else {
          console.debug(
            "Signup state already set from URL hash, preserving it",
          );
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
            console.debug(
              "[AuthSessionActions] Preserving existing signup state (user profile may load asynchronously)",
            );
          }
        }
      }

      authStore.update((state) => ({
        ...state,
        isAuthenticated: true,
        isInitialized: true,
      }));

      try {
        // Log auto top-up fields from backend response - ERROR if missing
        const hasAutoTopupFields =
          "auto_topup_low_balance_enabled" in data.user;
        if (!hasAutoTopupFields) {
          console.error(
            "[AuthSessionActions] ERROR: Auto top-up fields missing from backend response (session check)!",
          );
          console.error(
            "[AuthSessionActions] Received user object keys:",
            Object.keys(data.user),
          );
          console.error("[AuthSessionActions] Full user object:", data.user);
        } else {
          console.debug(
            "[AuthSessionActions] Auto top-up fields from backend (session check):",
            {
              enabled: data.user.auto_topup_low_balance_enabled,
              threshold: data.user.auto_topup_low_balance_threshold,
              amount: data.user.auto_topup_low_balance_amount,
              currency: data.user.auto_topup_low_balance_currency,
            },
          );
        }

        await userDB.saveUserData(data.user);
        const tfa_enabled = !!data.user.tfa_enabled;
        const consent_privacy =
          !!data.user.consent_privacy_and_apps_default_settings;
        const consent_mates = !!data.user.consent_mates_default_settings;
        const userLanguage = data.user.language || defaultProfile.language;
        const userDarkMode = data.user.darkmode ?? defaultProfile.darkmode;

        // ── Language reconciliation ──────────────────────────────────────
        // The user's localStorage may have a different language than the
        // server (e.g. user changed language in settings but the API call
        // failed silently, or the language was auto-detected at signup from
        // the browser locale and never corrected). If the user explicitly
        // chose a language locally (stored in localStorage.preferredLanguage),
        // push it to the server so they stay in sync.
        const rawLocalLanguage =
          typeof localStorage !== "undefined"
            ? localStorage.getItem("preferredLanguage")
            : null;
        // Validate localStorage value against supported locales (OPE-39: prevents
        // invalid values like "cs-CZ" from being pushed to the server)
        const localPreferredLanguage =
          rawLocalLanguage && isValidLocale(rawLocalLanguage)
            ? rawLocalLanguage
            : null;

        if (
          localPreferredLanguage &&
          localPreferredLanguage !== userLanguage &&
          data.user.language // only reconcile if server has a stored language
        ) {
          console.info(
            `[AuthSessionActions] Language mismatch: server="${userLanguage}", local="${localPreferredLanguage}" — pushing local preference to server`,
          );
          // Apply local preference immediately
          locale.set(localPreferredLanguage);
          // Push to server in background (non-blocking)
          import("../config/api")
            .then(({ getApiEndpoint }) => {
              const endpoint = getApiEndpoint("settings.user.language");
              if (endpoint) {
                fetch(endpoint, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  credentials: "include",
                  body: JSON.stringify({
                    language: localPreferredLanguage,
                  }),
                })
                  .then((resp) => {
                    if (resp.ok) {
                      console.info(
                        `[AuthSessionActions] Successfully synced local language "${localPreferredLanguage}" to server`,
                      );
                    } else {
                      console.warn(
                        `[AuthSessionActions] Failed to sync language to server: ${resp.status}`,
                      );
                    }
                  })
                  .catch((err) => {
                    console.warn(
                      "[AuthSessionActions] Error syncing language to server:",
                      err,
                    );
                  });
              }
            })
            .catch(() => {
              /* non-fatal */
            });
        } else if (userLanguage && userLanguage !== get(locale)) {
          console.debug(`Applying user language from session: ${userLanguage}`);
          locale.set(userLanguage);
        }

        // Use reconciled language (local takes priority if it differs)
        const effectiveLanguage =
          localPreferredLanguage &&
          localPreferredLanguage !== userLanguage &&
          data.user.language
            ? localPreferredLanguage
            : userLanguage;

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
          language: effectiveLanguage,
          darkmode: userDarkMode,
          timezone: data.user.timezone || null,
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
        });
        // Apply server dark mode preference to the theme store.
        // applyServerDarkMode is a no-op when the user already has a local
        // manual preference in localStorage, so local choices always win.
        applyServerDarkMode(userDarkMode);
      } catch (dbError) {
        console.error("Failed to save user data to database:", dbError);
      }

      // Start live console log streaming for admin users on session restore,
      // or for ALL authenticated users on dev (so frontend errors reach OpenObserve).
      if (data.user.is_admin || isDevEnvironment()) {
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
          // Non-critical
        }
      }

      // Register encrypted session metadata if the server indicates it hasn't been done yet.
      // The /session response includes session_device_info (plaintext device name, IP, country)
      // which the client encrypts with the master key and POSTs back. This is a one-time
      // operation per session, piggybacking on the existing /session flow.
      if (data.session_device_info && !data.session_meta_registered) {
        (async () => {
          try {
            const metaJson = JSON.stringify(data.session_device_info);
            const encryptedBlob =
              await cryptoService.encryptWithMasterKey(metaJson);
            if (encryptedBlob) {
              const res = await fetch(
                getApiEndpoint("/v1/auth/sessions/register-meta"),
                {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  credentials: "include",
                  body: JSON.stringify({
                    encrypted_meta: encryptedBlob,
                  }),
                },
              );
              if (res.ok) {
                console.warn(
                  "[AuthSessionActions] Session metadata registered successfully",
                );
              } else {
                console.warn(
                  "[AuthSessionActions] Failed to register session metadata:",
                  res.status,
                );
              }
            }
          } catch (err) {
            console.warn(
              "[AuthSessionActions] Error registering session metadata (non-fatal):",
              err,
            );
          }
        })();
      }

      // Pre-load all settings/memories entries from IndexedDB so they are immediately
      // available when the user types @ in the message editor.
      // Without this, the @ mention dropdown shows no settings_memory results because
      // the store is empty until the user manually opens the Settings panel.
      // Non-blocking: errors here must never prevent login from completing.
      appSettingsMemoriesStore.loadEntries().catch((err) => {
        console.warn(
          "[AuthSessionActions] Failed to pre-load settings/memories entries (non-fatal):",
          err,
        );
      });

      return true;
    } else {
      // Handle Server Explicitly Saying User Is Not Logged In
      // This is different from network errors - server successfully responded saying user is not authenticated
      console.info(
        "Server explicitly indicates user is not logged in:",
        data.message,
      );

      // Stop admin log streaming on session expiry
      void clientLogForwarder.stop();

      // Check if master key was present before clearing (to determine if user was previously authenticated)
      const hadMasterKey = !!(await cryptoService.getKeyFromStorage());

      // Only logout and show notification if user was previously authenticated
      if (hadMasterKey) {
        console.debug(
          "[AuthSessionActions] User was previously authenticated - showing logout notification and cleaning up.",
        );

        // CRITICAL: Set isLoggingOut flag to true BEFORE dispatching logout event
        // This ensures ActiveChat component knows we're explicitly logging out and should clear shared chats
        // and load demo-for-everyone, even if the chat is a shared chat
        isLoggingOut.set(true);
        console.debug(
          "[AuthSessionActions] Set isLoggingOut to true for session expiration logout",
        );

        // CRITICAL: Dispatch logout event IMMEDIATELY to clear UI state (chats, etc.)
        // This must happen before database deletion to ensure UI updates right away
        console.debug(
          "[AuthSessionActions] Dispatching userLoggingOut event to clear UI state immediately",
        );
        window.dispatchEvent(new CustomEvent("userLoggingOut"));

        // CRITICAL: Clear in-memory chat caches IMMEDIATELY on session expiry
        // The chatListCache singleton persists across component mounts/unmounts, so if Chats.svelte
        // is destroyed (sidebar closed on mobile) when session expires, its authStore subscriber
        // won't fire to clear the cache. Clearing here ensures stale chats never appear.
        chatListCache.clear();
        chatDB.clearAllChatKeys();
        // CRITICAL: Clear the decrypted metadata cache (title, category, icon, etc.) to prevent
        // stale entries (especially those with title: null from failed decryption during logout
        // transition) from being served after re-login, causing "Untitled chat" in the sidebar.
        chatMetadataCache.clearAll();
        console.debug(
          "[AuthSessionActions] Cleared chatListCache, chatMetadataCache, and chatDB.chatKeys on session expiry",
        );

        // CRITICAL: Set isAuthenticated=false IMMEDIATELY to close the auth gate.
        // Without this, WebSocket sync events that are still in-flight (phase_2, phase_3,
        // phasedSyncComplete) fire after userLoggingOut clears allChatsFromDB, see
        // isAuthenticated=true in updateChatListFromDBInternal, take the full authenticated
        // path, call chatDB.getAllChats() on the not-yet-deleted database, and repopulate
        // allChatsFromDB with all encrypted user chats — causing the "Untitled chats" sidebar
        // pollution visible in the screenshot after a forced logout.
        // Setting this here (before the async cleanup) ensures all subsequent DB read calls
        // take the non-authenticated path (shared chats only → empty set).
        authStore.update((state) => ({
          ...state,
          isAuthenticated: false,
          isInitialized: true,
        }));
        console.debug(
          "[AuthSessionActions] Set isAuthenticated=false immediately to prevent sync events from repopulating chat list",
        );

        // Clear shared chat keys in the background (async, non-blocking)
        clearAllSharedChatKeys().catch((e) =>
          console.warn(
            "[AuthSessionActions] Failed to clear shared chat keys on session expiry:",
            e,
          ),
        );

        // Show notification that user was logged out with hint about "Stay logged in"
        // This helps users understand they can avoid frequent logouts by enabling "Stay logged in"
        const $text = get(text);
        notificationStore.autoLogout(
          $text("login.auto_logout_notification.message"),
          undefined, // No secondary message needed
          7000, // Show for 7 seconds so user can read the hint
          $text("login.auto_logout_notification.title"),
        );

        // CRITICAL: If user is in signup flow, close signup interface and return to demo
        // This ensures the signup/login interface is closed when logout notification appears during signup
        const wasInSignupProcess = get(isInSignupProcess);
        if (wasInSignupProcess) {
          console.debug(
            "[AuthSessionActions] User was in signup process - closing signup interface and returning to demo",
          );

          // Reset signup process state FIRST to ensure Login component switches to login view
          // This prevents the signup view from remaining visible after closing
          isInSignupProcess.set(false);

          // Clear the signup store data when closing to demo
          clearSignupData();

          // Clear incomplete signup data from IndexedDB when closing to demo
          // This ensures username doesn't persist if user interrupts signup
          clearIncompleteSignupData().catch((error) => {
            console.error(
              "[AuthSessionActions] Error clearing incomplete signup data:",
              error,
            );
          });

          // Reset signup step to alpha disclaimer for next time
          currentSignupStep.set(STEP_ALPHA_DISCLAIMER);

          // CRITICAL: Clear all sessionStorage drafts when returning to demo mode
          // This ensures drafts don't persist if user interrupts login/signup
          clearAllSessionStorageDrafts();
          console.debug(
            "[AuthSessionActions] Cleared all sessionStorage drafts when returning to demo",
          );

          // Close the login interface and load demo chat
          // This dispatches a global event that ActiveChat.svelte listens to
          window.dispatchEvent(new CustomEvent("closeLoginInterface"));

          // Small delay to ensure the interface closes before loading chat
          setTimeout(() => {
            // Dispatch event to load demo chat (ActiveChat will handle this)
            window.dispatchEvent(new CustomEvent("loadDemoChat"));
          }, 100);
        }

        // CRITICAL: Navigate to demo-for-everyone chat to hide the previously open chat
        // This ensures the previous chat is not visible after logout
        // Small delay to ensure auth state changes are processed first
        // OG image mode (?og=1): skip demo-for-everyone redirect so the welcome screen stays visible
        const isOgImageModeLogout =
          typeof window !== "undefined" &&
          new URLSearchParams(window.location.search).get("og") === "1";
        if (!isOgImageModeLogout) {
          setTimeout(() => {
            if (typeof window !== "undefined") {
              activeChatStore.setActiveChat("demo-for-everyone");
              window.location.hash = "chat-id=demo-for-everyone";
              console.debug(
                "[AuthSessionActions] Navigated to demo-for-everyone chat after logout notification",
              );
            }
          }, 50);
        } else {
          console.debug(
            "[AuthSessionActions] Skipping demo-for-everyone redirect after logout — og=1 mode",
          );
        }

        // Clear master key and all email data from storage
        await cryptoService.clearKeyFromStorage();
        cryptoService.clearAllEmailData(); // Clear email encryption key, encrypted email, and salt

        // Delete session ID and cookies
        deleteSessionId();
        deleteAllCookies(); // Clear all cookies on forced logout
        clearWebSocketToken(); // Clear WebSocket token from sessionStorage
        console.debug(
          "[AuthSessionActions] Cookies, session ID, and WebSocket token deleted.",
        );

        // Clear IndexedDB databases asynchronously without blocking UI
        // Use setTimeout to defer deletion and avoid blocking the auth initialization
        // The UI state has already been cleared via the event above
        setTimeout(async () => {
          try {
            await userDB.deleteDatabase();
            console.debug(
              "[AuthSessionActions] UserDB database deleted due to server logout response.",
            );
          } catch (dbError) {
            console.warn(
              "[AuthSessionActions] Failed to delete userDB database (may be blocked by open connections):",
              dbError,
            );
          }

          try {
            await chatDB.deleteDatabase();
            console.debug(
              "[AuthSessionActions] ChatDB database deleted due to server logout response.",
            );
          } catch (dbError) {
            console.warn(
              "[AuthSessionActions] Failed to delete chatDB database (may be blocked by open connections):",
              dbError,
            );
          }

          // Clear any pending offline chat deletions from localStorage
          try {
            const { clearAllPendingChatDeletions } =
              await import("../services/pendingChatDeletions");
            clearAllPendingChatDeletions();
          } catch (clearError) {
            console.warn(
              "[AuthSessionActions] Failed to clear pending chat deletions:",
              clearError,
            );
          }

          // CRITICAL: Reset isLoggingOut flag after logout cleanup completes
          // This ensures the flag is reset even if logout was triggered by session expiration
          // Use a small delay to ensure all logout handlers have finished processing
          setTimeout(() => {
            isLoggingOut.set(false);
            console.debug(
              "[AuthSessionActions] Reset isLoggingOut flag after session expiration logout cleanup",
            );
          }, 500);
        }, 100); // Small delay to allow current operations to complete
      } else {
        console.debug(
          "[AuthSessionActions] No master key found - user was not previously authenticated, skipping cleanup.",
        );
      }

      // CRITICAL: Check for orphaned database cleanup even if user was never authenticated
      // This handles the case where the page was reloaded with stayLoggedIn=false but
      // the databases were previously initialized and contain encrypted data that needs cleanup
      const cleanupMarker =
        typeof localStorage !== "undefined" &&
        localStorage.getItem("openmates_needs_cleanup") === "true";

      if (cleanupMarker) {
        console.warn(
          "[AuthSessionActions] ORPHANED DATABASE CLEANUP: Found cleanup marker - triggering database deletion",
        );

        // CRITICAL: Clear the cleanup marker immediately to prevent showing this notification again
        if (typeof localStorage !== "undefined") {
          localStorage.removeItem("openmates_needs_cleanup");
          console.debug(
            "[AuthSessionActions] Cleared cleanup marker to prevent repeated notifications",
          );
        }

        // CRITICAL: Set isLoggingOut flag to true for orphaned database cleanup
        isLoggingOut.set(true);
        console.debug(
          "[AuthSessionActions] Set isLoggingOut to true for orphaned database cleanup",
        );

        // CRITICAL: Clear in-memory chat caches during orphaned database cleanup
        chatListCache.clear();
        chatDB.clearAllChatKeys();
        chatMetadataCache.clearAll();
        clearAllSharedChatKeys().catch(() => {});
        console.debug(
          "[AuthSessionActions] Cleared in-memory chat caches during orphaned database cleanup",
        );

        // No notification needed - this is automatic cleanup

        // Clear IndexedDB databases asynchronously without blocking UI
        setTimeout(async () => {
          try {
            await userDB.deleteDatabase();
            console.debug(
              "[AuthSessionActions] UserDB database deleted during orphaned cleanup.",
            );
          } catch (dbError) {
            console.warn(
              "[AuthSessionActions] Failed to delete userDB database during orphaned cleanup (may be blocked by open connections):",
              dbError,
            );
          }

          try {
            await chatDB.deleteDatabase();
            console.debug(
              "[AuthSessionActions] ChatDB database deleted during orphaned cleanup.",
            );
          } catch (dbError) {
            console.warn(
              "[AuthSessionActions] Failed to delete chatDB database during orphaned cleanup (may be blocked by open connections):",
              dbError,
            );
          }

          // Clear any pending offline chat deletions from localStorage
          try {
            const { clearAllPendingChatDeletions } =
              await import("../services/pendingChatDeletions");
            clearAllPendingChatDeletions();
          } catch (clearError) {
            console.warn(
              "[AuthSessionActions] Failed to clear pending chat deletions during orphaned cleanup:",
              clearError,
            );
          }

          // CRITICAL: Reset isLoggingOut flag after cleanup completes
          setTimeout(() => {
            isLoggingOut.set(false);
            console.debug(
              "[AuthSessionActions] Reset isLoggingOut flag after orphaned database cleanup",
            );
          }, 500);
        }, 100); // Small delay to allow current operations to complete
      }

      needsDeviceVerification.set(false);
      deviceVerificationType.set(null);
      deviceVerificationReason.set(null);
      authStore.update((state) => ({
        ...state,
        isAuthenticated: false,
        isInitialized: true,
      }));

      // Clear profile
      updateProfile({
        username: null,
        profile_image_url: null,
        tfa_app_name: null,
        tfa_enabled: false,
        credits: 0,
        is_admin: false,
        last_opened: null,
        consent_privacy_and_apps_default_settings: false,
        consent_mates_default_settings: false,
      });

      console.debug("[AuthSessionActions] Auth state reset completed.");
      return false;
    }
  } catch (error) {
    // Network error or fetch failure - be optimistic and load local data
    console.warn(
      "[AuthSessionActions] Network error during auth check (offline-first):",
      error,
    );
    console.debug(
      "[AuthSessionActions] Loading local user data optimistically - assuming user is still authenticated",
    );

    needsDeviceVerification.set(false);
    deviceVerificationType.set(null);
    deviceVerificationReason.set(null);

    try {
      // Load user profile from IndexedDB optimistically
      await loadUserProfileFromDB();

      // Check if we have local user data (master key and user profile)
      const masterKey = await cryptoService.getKeyFromStorage();
      const localProfile = get(userProfile);
      const hasLocalData = masterKey && localProfile && localProfile.username;

      if (hasLocalData) {
        // User has local data - optimistically assume they're still authenticated
        console.debug(
          "[AuthSessionActions] ✅ Local user data found - assuming authenticated (offline-first mode)",
        );

        authStore.update((state) => ({
          ...state,
          isAuthenticated: true,
          isInitialized: true,
        }));

        // Restore daily inspirations from IndexedDB when recovering via offline-first mode.
        //
        // Context: this code path is reached when the session check times out or the server
        // is momentarily unreachable (e.g. after a transient WS disconnect triggers checkAuth).
        // The inspiration store may have been wiped (dailyInspirationStore.reset()) if a
        // logout was partially triggered, or the Chats component may have remounted with an
        // empty store. Either way, the master key is confirmed present above (hasLocalData),
        // so IndexedDB decryption will succeed immediately — giving near-instant restoration
        // without waiting for Phase 1 to complete.
        //
        // loadDefaultInspirations is idempotent: if the store is already populated (because
        // the disruption was brief and the store survived intact) it exits immediately.
        void import("../demo_chats/loadDefaultInspirations")
          .then(({ loadDefaultInspirations }) =>
            loadDefaultInspirations({ allowIndexedDB: true }),
          )
          .catch((error) => {
            console.error(
              "[AuthSessionActions] Failed to restore inspirations after offline-first re-auth:",
              error,
            );
          });

        // Start clientLogForwarder for admin users in offline-first mode.
        // The normal (online) path starts the forwarder in checkAuth()'s happy path.
        // But if the server is unreachable, we restore auth from local IndexedDB here
        // without ever reaching the online success path — so we must start it here.
        if (localProfile.is_admin || isDevEnvironment()) {
          console.debug(
            "[AuthSessionActions] Starting clientLogForwarder (offline-first)",
          );
          clientLogForwarder.start();
        } else {
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
            // Non-critical
          }
        }

        // Check if user is in signup flow (offline-first mode)
        // A user is in signup flow only if last_opened explicitly indicates signup
        // Avoid using tfa_enabled=false to keep passkey-only users out of OTP setup
        const inSignupFlow = isSignupPath(localProfile.last_opened);

        if (inSignupFlow) {
          console.debug(
            "[AuthSessionActions] User is in signup process (offline-first mode):",
            {
              last_opened: localProfile.last_opened,
              tfa_enabled: localProfile.tfa_enabled,
            },
          );
          // Determine step directly from last_opened (hash-based paths)
          const step = getStepFromPath(localProfile.last_opened);
          currentSignupStep.set(step);
          isInSignupProcess.set(true);
          // CRITICAL: Open login interface to show signup flow on page reload (offline-first mode)
          loginInterfaceOpen.set(true);
          console.debug(
            "[AuthSessionActions] Set signup step to:",
            step,
            "and opened login interface (offline-first mode)",
          );
        } else {
          isInSignupProcess.set(false);
        }

        // Apply language from local profile if available
        if (localProfile.language) {
          const currentLocale = get(locale);
          if (localProfile.language !== currentLocale) {
            console.debug(
              `[AuthSessionActions] Applying local user language: ${localProfile.language}`,
            );
            locale.set(localProfile.language);
          }
        }

        return true; // Return true to indicate optimistic authentication
      } else {
        // No local data - user was never authenticated or data was cleared
        console.debug(
          "[AuthSessionActions] No local user data found - user is not authenticated",
        );

        authStore.update((state) => ({
          ...state,
          isAuthenticated: false,
          isInitialized: true,
        }));

        return false;
      }
    } catch (loadError) {
      // If loading local data fails, fall back to not authenticated
      console.error(
        "[AuthSessionActions] Error loading local user data:",
        loadError,
      );

      authStore.update((state) => ({
        ...state,
        isAuthenticated: false,
        isInitialized: true,
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
export async function initialize(
  deviceSignals?: Record<string, string | null>,
): Promise<boolean> {
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
  console.debug(
    "Setting authentication state to authenticated after successful login",
  );

  // CRITICAL: Bump login session generation to signal any in-flight background
  // logout IIFE (from a previous forced-logout) that a new session is established.
  // Without this, the IIFE's generation check passes and it POSTs /auth/logout
  // with the new session's cookies, destroying the freshly-established session.
  // This is the single chokepoint ALL successful login paths pass through
  // (passkey, password+TFA, backup code, recovery key).
  bumpLoginSessionGeneration();

  // CRITICAL: Reset phased sync state on login so syncing indicator shows.
  // This is needed because non-auth users have initialSyncCompleted=true (to prevent loading flash).
  // When they log in, we need to reset so the real sync can show progress.
  //
  // We use resetForLogin() (NOT reset()) to preserve userMadeExplicitChoice and
  // currentActiveChatId. The user may have clicked "new chat" before the login
  // WebSocket response arrived; calling reset() wipes those flags, causing the
  // Phase 1 sync handler to auto-open the old last_opened chat over the user's
  // explicit choice (race condition: issue 3a991b5c).
  phasedSyncState.resetForLogin();
  console.debug(
    "Reset phased sync state for new login (preserving user navigation choices) - syncing indicator will show",
  );

  // OPE-215: Clear the demo-for-everyone hash that was set during non-auth state or forced logout.
  // Without this, the sync completion handler in +page.svelte reads the stale hash and
  // auto-navigates to the demo chat instead of the user's last-opened chat.
  if (
    typeof window !== "undefined" &&
    window.location.hash === "#chat-id=demo-for-everyone"
  ) {
    // Use replaceState to avoid triggering hashchange events
    history.replaceState(
      null,
      "",
      window.location.pathname + window.location.search,
    );
    activeChatStore.clearActiveChat();
    console.debug(
      "[setAuthenticatedState] Cleared demo-for-everyone hash on login",
    );
  }

  authStore.update((state) => ({
    ...state,
    isAuthenticated: true,
    isInitialized: true,
  }));
  console.debug(
    "[setAuthenticatedState] authStore.isAuthenticated set to true — downstream $effects should fire",
  );
  needsDeviceVerification.set(false);
  deviceVerificationType.set(null);
  deviceVerificationReason.set(null);

  // Start live console log streaming for admin users on fresh login.
  // The user profile is populated by PasswordAndTfaOtp.svelte (via updateProfile) before
  // dispatching loginSuccess, so is_admin is available here when called from ActiveChat.
  const profile = get(userProfile);
  if (profile.is_admin || isDevEnvironment()) {
    console.debug(
      "[setAuthenticatedState] Starting clientLogForwarder",
    );
    clientLogForwarder.start();
  } else {
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
      // Non-critical
    }
  }
}
