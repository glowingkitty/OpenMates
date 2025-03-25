import { writable } from 'svelte/store';

// Store to track backup codes status
export const backupCodesLoaded = writable<boolean>(false);

// Helper functions
export function setBackupCodesLoaded(loaded: boolean) {
    backupCodesLoaded.set(loaded);
}