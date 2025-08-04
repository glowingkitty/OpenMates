/**
 * Store to track UI state for the recovery key creation process
 */
import { writable } from 'svelte/store';

// Track whether the recovery key creation UI is showing
export const isRecoveryKeyCreationActive = writable<boolean>(false);

// Function to set the recovery key creation UI state
export function setRecoveryKeyCreationActive(active: boolean): void {
  isRecoveryKeyCreationActive.set(active);
}