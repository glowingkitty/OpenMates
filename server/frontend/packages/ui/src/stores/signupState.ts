import { writable } from 'svelte/store';

// Track if we're in the signup process
export const isInSignupProcess = writable(false);

// Track if the current step should show settings
export const isSignupSettingsStep = writable(false);

// Set the threshold for settings-enabled steps
export const SETTINGS_STEP_THRESHOLD = 7;

// Helper function to check if a step should show settings (for step 7 and higher)
export function isSettingsStep(step: number): boolean {
    return step >= SETTINGS_STEP_THRESHOLD;
}
