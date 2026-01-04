import { writable } from 'svelte/store';

// Step name constants
export const STEP_ALPHA_DISCLAIMER = 'alpha_disclaimer';
export const STEP_BASICS = 'basics';
export const STEP_CONFIRM_EMAIL = 'confirm_email';
export const STEP_SECURE_ACCOUNT = 'secure_account';
export const STEP_PASSWORD = 'password';
// export const STEP_PROFILE_PICTURE = 'profile_picture'; // Moved to settings menu
export const STEP_ONE_TIME_CODES = 'one_time_codes';
export const STEP_BACKUP_CODES = 'backup_codes';
export const STEP_RECOVERY_KEY = 'recovery_key';
export const STEP_TFA_APP_REMINDER = 'tfa_app_reminder';
export const STEP_SETTINGS = 'settings';
export const STEP_MATE_SETTINGS = 'mate_settings';
export const STEP_CREDITS = 'credits';
export const STEP_PAYMENT = 'payment';
export const STEP_AUTO_TOP_UP = 'auto_top_up';
export const STEP_COMPLETION = 'completion';

// Define step sequence for ordering
export const STEP_SEQUENCE = [
    STEP_BASICS,
    STEP_CONFIRM_EMAIL,
    STEP_SECURE_ACCOUNT,
    STEP_PASSWORD,
    STEP_ONE_TIME_CODES,
    STEP_BACKUP_CODES,
    STEP_TFA_APP_REMINDER,
    // STEP_PROFILE_PICTURE, // Moved to settings menu
    // STEP_SETTINGS and STEP_MATE_SETTINGS are skipped for now but kept in the code
    // STEP_SETTINGS,
    // STEP_MATE_SETTINGS,
    STEP_CREDITS,
    STEP_PAYMENT,
    STEP_AUTO_TOP_UP,
    STEP_COMPLETION
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
 * - Chat loading should skip encrypted chats and load demo-welcome instead
 * - Decryption operations should be skipped to avoid errors
 * - The flag is reset after the forced logout completes
 * 
 * This is different from `isLoggingOut` which is set slightly later in the logout flow.
 * `forcedLogoutInProgress` specifically handles the case where we detect the master key
 * is missing and need to immediately prevent any decryption attempts.
 */
export const forcedLogoutInProgress = writable(false);

// Store to track current signup step
// Initialize to null/empty so that Signup.svelte can properly detect new signups and show alpha disclaimer
export const currentSignupStep = writable<string>('');

// Store to track if user is resetting 2FA from TFA App Reminder step
export const isResettingTFA = writable<boolean>(false);

// Helper to determine if we're in settings steps
export function isSettingsStep(step: string): boolean {
    const settingsSteps = [STEP_SETTINGS, STEP_MATE_SETTINGS, STEP_CREDITS, STEP_PAYMENT, STEP_AUTO_TOP_UP];
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
    return path.startsWith('/signup/') || path.startsWith('#signup/');
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
    if (path.startsWith('#')) {
        normalizedPath = path.substring(1); // Remove leading #
    }
    
    // Parse path format: /signup/basics or signup/basics (after removing #)
    const pathParts = normalizedPath.split('/');
    if (pathParts.length >= 2 && pathParts[pathParts.length - 2] === 'signup') {
        const stepSlug = pathParts[pathParts.length - 1];
        
        // Handle both hyphenated and underscore formats
        const normalizedSlug = stepSlug.replace(/_/g, '-');
        
        // Map URL slugs to step names
        switch (normalizedSlug) {
            case 'basics': return STEP_BASICS;
            case 'confirm-email': return STEP_CONFIRM_EMAIL;
            case 'secure-account': return STEP_SECURE_ACCOUNT;
            case 'password': return STEP_PASSWORD;
            // case 'profile-picture': return STEP_PROFILE_PICTURE; // Moved to settings
            case 'one-time-codes': return STEP_ONE_TIME_CODES;
            case 'backup-codes': return STEP_BACKUP_CODES;
            case 'tfa-app-reminder': return STEP_TFA_APP_REMINDER;
            case 'recovery-key': return STEP_RECOVERY_KEY;
            case 'settings': return STEP_SETTINGS;
            case 'mate-settings': return STEP_MATE_SETTINGS;
            case 'credits': return STEP_CREDITS;
            case 'payment': return STEP_PAYMENT;
            case 'auto-top-up': return STEP_AUTO_TOP_UP;
            case 'completion': return STEP_COMPLETION;
            // Legacy support for old numeric format
            default:
                // Try to extract step name from the URL slug
                for (const stepName of STEP_SEQUENCE) {
                    if (normalizedSlug.includes(stepName.replace('_', '-'))) {
                        return stepName;
                    }
                }
                console.debug(`[signupState] Could not map path "${path}" to a step, defaulting to basics`);
                return STEP_BASICS;
        }
    }
    
    return STEP_BASICS;
}

/**
 * Convert step name to last_opened path format
 * This is the reverse of getStepFromPath - converts step names like 'one_time_codes' to hash-based paths like '#signup/one-time-codes'
 * Uses hash-based format for consistency with other deep linking (e.g., #settings, #chat_id=)
 * @param stepName The step name constant (e.g., STEP_ONE_TIME_CODES)
 * @returns The hash-based path format (e.g., '#signup/one-time-codes')
 */
export function getPathFromStep(stepName: string): string {
    if (!stepName) return '#signup/basics';
    
    // Map step names to URL slugs (convert underscores to hyphens)
    const stepSlug = stepName.replace(/_/g, '-');
    
    // Return the hash-based path format for consistency with other deep linking
    return `#signup/${stepSlug}`;
}
