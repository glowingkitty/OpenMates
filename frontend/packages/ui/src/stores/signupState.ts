import { writable, derived } from 'svelte/store';

// Step name constants
export const STEP_BASICS = 'basics';
export const STEP_CONFIRM_EMAIL = 'confirm_email';
export const STEP_SECURE_ACCOUNT = 'secure_account';
export const STEP_PASSWORD = 'password';
export const STEP_PROFILE_PICTURE = 'profile_picture';
export const STEP_ONE_TIME_CODES = 'one_time_codes';
export const STEP_BACKUP_CODES = 'backup_codes';
export const STEP_RECOVERY_KEY = 'recovery_key';
export const STEP_TFA_APP_REMINDER = 'tfa_app_reminder';
export const STEP_SETTINGS = 'settings';
export const STEP_MATE_SETTINGS = 'mate_settings';
export const STEP_CREDITS = 'credits';
export const STEP_PAYMENT = 'payment';
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
    STEP_PROFILE_PICTURE,
    // STEP_SETTINGS and STEP_MATE_SETTINGS are skipped for now but kept in the code
    // STEP_SETTINGS,
    // STEP_MATE_SETTINGS,
    STEP_CREDITS,
    STEP_PAYMENT,
    STEP_COMPLETION
];

// Make the isInSignupProcess store more responsive by marking it as needing immediate update
export const isInSignupProcess = writable<boolean>(false);
export const isLoggingOut = writable(false);

// Store to track current signup step
export const currentSignupStep = writable<string>(STEP_BASICS);

// Store to track if user is resetting 2FA from TFA App Reminder step
export const isResettingTFA = writable<boolean>(false);

// Helper to determine if we're in settings steps
export function isSettingsStep(step: string): boolean {
    const settingsSteps = [STEP_SETTINGS, STEP_MATE_SETTINGS, STEP_CREDITS, STEP_PAYMENT];
    return settingsSteps.includes(step);
}

// Store to track if we're in a settings step
export const isSignupSettingsStep = writable(false);

// Store to explicitly control footer visibility during signup
export const showSignupFooter = writable(true);

// Stores related to gifted credits check in Step 9
export const isLoadingGiftCheck = writable<boolean>(true); // Track loading state for gift check API call
export const hasGiftForSignup = writable<boolean>(false); // Track if user has a gift

// Parse step name from last_opened path
export function getStepFromPath(path: string): string {
    if (!path) return STEP_BASICS;
    
    // New URL format would be like /signup/basics, /signup/confirm-email, etc.
    const pathParts = path.split('/');
    if (pathParts.length >= 3 && pathParts[1] === 'signup') {
        const stepSlug = pathParts[2];
        
        // Handle both hyphenated and underscore formats
        const normalizedSlug = stepSlug.replace(/_/g, '-');
        
        // Map URL slugs to step names
        switch (normalizedSlug) {
            case 'basics': return STEP_BASICS;
            case 'confirm-email': return STEP_CONFIRM_EMAIL;
            case 'secure-account': return STEP_SECURE_ACCOUNT;
            case 'password': return STEP_PASSWORD;
            case 'profile-picture': return STEP_PROFILE_PICTURE;
            case 'one-time-codes': return STEP_ONE_TIME_CODES;
            case 'backup-codes': return STEP_BACKUP_CODES;
            case 'tfa-app-reminder': return STEP_TFA_APP_REMINDER;
            case 'recovery-key': return STEP_RECOVERY_KEY;
            case 'settings': return STEP_SETTINGS;
            case 'mate-settings': return STEP_MATE_SETTINGS;
            case 'credits': return STEP_CREDITS;
            case 'payment': return STEP_PAYMENT;
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
