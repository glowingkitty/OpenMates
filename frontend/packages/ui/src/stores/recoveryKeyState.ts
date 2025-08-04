import { writable } from 'svelte/store';

// Store to track recovery key status
// This store is used to control whether the recovery key confirmation UI
// in RecoveryKeyBottomContent is enabled or disabled/faded out
export const recoveryKeyLoaded = writable<boolean>(false);

// Store for recovery key data that needs to be shared between components
export const recoveryKeyData = writable<{
    lookupHash: string;
    wrappedMasterKey: string;
    salt: string;
}>({
    lookupHash: '',
    wrappedMasterKey: '',
    salt: ''
});

// Helper functions
export function setRecoveryKeyLoaded(loaded: boolean) {
    recoveryKeyLoaded.set(loaded);
}

export function setRecoveryKeyData(lookupHash: string, wrappedMasterKey: string, salt: string) {
    recoveryKeyData.set({
        lookupHash,
        wrappedMasterKey,
        salt
    });
}