import { writable } from "svelte/store";

// Step name constants
export const STEP_ALPHA_DISCLAIMER = "alpha_disclaimer";
export const STEP_BASICS = "basics";
export const STEP_CONFIRM_EMAIL = "confirm_email";
export const STEP_SECURE_ACCOUNT = "secure_account";
export const STEP_PASSWORD = "password";
// export const STEP_PROFILE_PICTURE = 'profile_picture'; // Moved to settings menu
export const STEP_ONE_TIME_CODES = "one_time_codes";
export const STEP_SKIP_2FA_CONSENT = "skip_2fa_consent";
export const STEP_BACKUP_CODES = "backup_codes";
export const STEP_RECOVERY_KEY = "recovery_key";
export const STEP_TFA_APP_REMINDER = "tfa_app_reminder";
export const STEP_SETTINGS = "settings";
export const STEP_MATE_SETTINGS = "mate_settings";
export const STEP_CREDITS = "credits";
export const STEP_PAYMENT = "payment";
export const STEP_AUTO_TOP_UP = "auto_top_up";
export const STEP_COMPLETION = "completion";

// Define step sequence for ordering
export const STEP_SEQUENCE = [
  STEP_BASICS,
  STEP_CONFIRM_EMAIL,
  STEP_SECURE_ACCOUNT,
  STEP_PASSWORD,
  STEP_ONE_TIME_CODES,
  STEP_SKIP_2FA_CONSENT,
  STEP_BACKUP_CODES,
  STEP_TFA_APP_REMINDER,
  // STEP_PROFILE_PICTURE, // Moved to settings menu
  // STEP_SETTINGS and STEP_MATE_SETTINGS are skipped for now but kept in the code
  // STEP_SETTINGS,
  // STEP_MATE_SETTINGS,
  STEP_CREDITS,
  STEP_PAYMENT,
  STEP_AUTO_TOP_UP,
  STEP_COMPLETION,
];

// Make the isInSignupProcess store more responsive by marking it as needing immediate update
export const isInSignupProcess = writable<boolean>(false);
export const isLoggingOut = writable(false);

/**
 * Flag to track when a forced logout is in progress due to missing master key.
 *
 * CRITICAL: This flag must be set SYNCHRONOUSLY at the very start of the forced logout handling,
 * BEFORE any auth state changes. This prevents race conditions where other components try to
 * load and decrypt encrypted chats that can no longer be decrypted (because master key is missing).
 *
 * When this flag is true:
 * - Chat loading should skip encrypted chats and load demo-for-everyone instead
 * - Decryption operations should be skipped to avoid errors
 * - The flag is reset after the forced logout completes
 *
 * This is different from `isLoggingOut` which is set slightly later in the logout flow.
 * `forcedLogoutInProgress` specifically handles the case where we detect the master key
 * is missing and need to immediately prevent any decryption attempts.
 */
export const forcedLogoutInProgress = writable(false);

/**
 * Timestamp (ms since epoch) of when forcedLogoutInProgress was last set to true.
 * Used by the visibilitychange handler in WebSocketService to detect stale flags
 * that got stuck (e.g., when the logout flow hangs during device sleep).
 *
 * If the flag has been true for more than FORCED_LOGOUT_STALENESS_MS, it's considered
 * stale and can be safely reset.
 */
export let forcedLogoutSetAt = 0;

/**
 * Maximum time (ms) that forcedLogoutInProgress should stay true before being
 * considered stale. 10 seconds is generous — the logout flow (server request +
 * DB deletion) should complete in 2–5 seconds in normal conditions.
 * Reduced from 30s so that false-positive triggers (e.g., iOS memory eviction
 * on wake) recover within 10s instead of 30s.
 */
export const FORCED_LOGOUT_STALENESS_MS = 10_000;

/**
 * Timestamp (ms since epoch) of the most recent page-resume event
 * (visibilitychange or pageshow.persisted). Set by WebSocketService.handlePageResume().
 *
 * Used by ChatDatabase.init() to suppress orphan detection for a short window
 * after a wake event, preventing a race condition where the async IDB key check
 * runs before memory-key stores have had a chance to re-initialize.
 *
 * 0 means no resume has occurred yet this session.
 */
export let lastResumeTimestamp = 0;

/**
 * Grace period (ms) after a resume event during which the orphan database check
 * in ChatDatabase.init() is suppressed. After this window, the check runs normally.
 * 3 seconds is enough for auth flows to complete their re-initialization.
 */
export const RESUME_ORPHAN_GRACE_MS = 3_000;

/**
 * Record that a page resume event just occurred.
 * Called by WebSocketService.handlePageResume() on every visibilitychange/pageshow.
 */
export function recordPageResume(): void {
  lastResumeTimestamp = Date.now();
}

/**
 * Safety timeout ID for auto-resetting forcedLogoutInProgress if the logout flow hangs.
 * Stored at module level so it can be cleared when the flag is reset normally.
 */
let forcedLogoutSafetyTimeoutId: ReturnType<typeof setTimeout> | null = null;

/**
 * Set forcedLogoutInProgress to true with a safety timeout.
 * If the flag is not reset within FORCED_LOGOUT_STALENESS_MS, it auto-resets.
 * This prevents the app from getting stuck in a permanent "logout in progress" state
 * when the async logout flow hangs (e.g., during device sleep/wake).
 */
export function setForcedLogoutInProgress(): void {
  forcedLogoutInProgress.set(true);
  forcedLogoutSetAt = Date.now();

  // Clear any previous safety timeout
  if (forcedLogoutSafetyTimeoutId !== null) {
    clearTimeout(forcedLogoutSafetyTimeoutId);
  }

  // Auto-reset after FORCED_LOGOUT_STALENESS_MS if the logout flow doesn't complete
  forcedLogoutSafetyTimeoutId = setTimeout(() => {
    forcedLogoutSafetyTimeoutId = null;
    // Only reset if the flag is still true (wasn't reset by the normal flow)
    if (
      forcedLogoutSetAt > 0 &&
      Date.now() - forcedLogoutSetAt >= FORCED_LOGOUT_STALENESS_MS
    ) {
      console.warn(
        `[signupState] forcedLogoutInProgress has been true for ${FORCED_LOGOUT_STALENESS_MS / 1000}s — auto-resetting to prevent stuck state`,
      );
      forcedLogoutInProgress.set(false);
      forcedLogoutSetAt = 0;
      // CRITICAL: Also remove the cleanup marker from localStorage to prevent
      // chatDB.init() from re-detecting it and re-setting forcedLogoutInProgress,
      // which would create an infinite toggle loop every FORCED_LOGOUT_STALENESS_MS.
      if (typeof localStorage !== "undefined") {
        localStorage.removeItem("openmates_needs_cleanup");
      }
    }
  }, FORCED_LOGOUT_STALENESS_MS);
}

/**
 * Reset forcedLogoutInProgress to false and clear the safety timeout.
 * Call this instead of forcedLogoutInProgress.set(false) to ensure proper cleanup.
 */
export function resetForcedLogoutInProgress(): void {
  forcedLogoutInProgress.set(false);
  forcedLogoutSetAt = 0;
  if (forcedLogoutSafetyTimeoutId !== null) {
    clearTimeout(forcedLogoutSafetyTimeoutId);
    forcedLogoutSafetyTimeoutId = null;
  }
}

// Store to track current signup step
// Initialize to null/empty so that Signup.svelte can properly detect new signups and show alpha disclaimer
export const currentSignupStep = writable<string>("");

// Store to track if user is resetting 2FA from TFA App Reminder step
export const isResettingTFA = writable<boolean>(false);

// Helper to determine if we're in settings steps
export function isSettingsStep(step: string): boolean {
  const settingsSteps = [
    STEP_SETTINGS,
    STEP_MATE_SETTINGS,
    STEP_CREDITS,
    STEP_PAYMENT,
    STEP_AUTO_TOP_UP,
  ];
  return settingsSteps.includes(step);
}

// Store to track if we're in a settings step
export const isSignupSettingsStep = writable(false);

// Store to explicitly control footer visibility during signup
export const showSignupFooter = writable(true);

/**
 * Check if a path indicates the user is in signup flow
 * Supports both /signup/ and #signup/ formats for backward compatibility
 * @param path The last_opened path to check
 * @returns True if the path indicates signup flow
 */
export function isSignupPath(path: string | null | undefined): boolean {
  if (!path) return false;
  // Support both /signup/ and #signup/ formats
  return path.startsWith("/signup/") || path.startsWith("#signup/");
}

// Stores related to gifted credits check in Step 9
export const isLoadingGiftCheck = writable<boolean>(true); // Track loading state for gift check API call
export const hasGiftForSignup = writable<boolean>(false); // Track if user has a gift

// Parse step name from last_opened path
// Supports both /signup/ and #signup/ formats for backward compatibility
export function getStepFromPath(path: string): string {
  if (!path) return STEP_BASICS;

  // Normalize path: remove leading # if present, and handle both /signup/ and #signup/ formats
  let normalizedPath = path;
  if (path.startsWith("#")) {
    normalizedPath = path.substring(1); // Remove leading #
  }

  // Parse path format: /signup/basics or signup/basics (after removing #)
  const pathParts = normalizedPath.split("/");
  if (pathParts.length >= 2 && pathParts[pathParts.length - 2] === "signup") {
    const stepSlug = pathParts[pathParts.length - 1];

    // Handle both hyphenated and underscore formats
    const normalizedSlug = stepSlug.replace(/_/g, "-");

    // Map URL slugs to step names
    switch (normalizedSlug) {
      case "basics":
        return STEP_BASICS;
      case "confirm-email":
        return STEP_CONFIRM_EMAIL;
      case "secure-account":
        return STEP_SECURE_ACCOUNT;
      case "password":
        return STEP_PASSWORD;
      // case 'profile-picture': return STEP_PROFILE_PICTURE; // Moved to settings
      case "one-time-codes":
        return STEP_ONE_TIME_CODES;
      case "skip-2fa-consent":
        return STEP_SKIP_2FA_CONSENT;
      case "backup-codes":
        return STEP_BACKUP_CODES;
      case "tfa-app-reminder":
        return STEP_TFA_APP_REMINDER;
      case "recovery-key":
        return STEP_RECOVERY_KEY;
      case "settings":
        return STEP_SETTINGS;
      case "mate-settings":
        return STEP_MATE_SETTINGS;
      case "credits":
        return STEP_CREDITS;
      case "payment":
        return STEP_PAYMENT;
      case "auto-top-up":
        return STEP_AUTO_TOP_UP;
      case "completion":
        return STEP_COMPLETION;
      // Legacy support for old numeric format
      default:
        // Try to extract step name from the URL slug
        for (const stepName of STEP_SEQUENCE) {
          if (normalizedSlug.includes(stepName.replace("_", "-"))) {
            return stepName;
          }
        }
        console.debug(
          `[signupState] Could not map path "${path}" to a step, defaulting to basics`,
        );
        return STEP_BASICS;
    }
  }

  return STEP_BASICS;
}

/**
 * Convert step name to last_opened path format
 * This is the reverse of getStepFromPath - converts step names like 'one_time_codes' to hash-based paths like '#signup/one-time-codes'
 * Uses hash-based format for consistency with other deep linking (e.g., #settings, #chat-id=)
 * @param stepName The step name constant (e.g., STEP_ONE_TIME_CODES)
 * @returns The hash-based path format (e.g., '#signup/one-time-codes')
 */
export function getPathFromStep(stepName: string): string {
  if (!stepName) return "#signup/basics";

  // Map step names to URL slugs (convert underscores to hyphens)
  const stepSlug = stepName.replace(/_/g, "-");

  // Return the hash-based path format for consistency with other deep linking
  return `#signup/${stepSlug}`;
}
