import { writable, derived } from 'svelte/store';

// Make the isInSignupProcess store more responsive by marking it as needing immediate update
export const isInSignupProcess = writable<boolean>(false);
export const isLoggingOut = writable(false);

// Store to track current signup step
export const currentSignupStep = writable(1);

// Helper to determine if we're in settings steps (7+)
export function isSettingsStep(step: number): boolean {
    return step >= 7;
}

// Store to track if we're in a settings step
export const isSignupSettingsStep = writable(false);

// Parse step number from last_opened path
export function getStepFromPath(path: string): number {
    if (!path) return 1;
    
    const match = path.match(/\/signup\/step-(\d+)/);
    if (match && match[1]) {
        return parseInt(match[1], 10);
    }
    return 1;
}
