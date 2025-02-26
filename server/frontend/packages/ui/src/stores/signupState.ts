import { writable } from 'svelte/store';

// Store to track if we're on the settings step in the signup process
export const isSignupSettingsStep = writable(false);

// Store to track if we're in any signup step
export const isInSignupProcess = writable(false);

// Helper function to reset all signup states
export function resetSignupState() {
    isSignupSettingsStep.set(false);
    isInSignupProcess.set(false);
}
