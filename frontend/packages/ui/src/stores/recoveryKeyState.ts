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
    keyIv: string;
}>({
    lookupHash: '',
    wrappedMasterKey: '',
    salt: '',
    keyIv: ''
});

// Helper functions
export function setRecoveryKeyLoaded(loaded: boolean) {
    recoveryKeyLoaded.set(loaded);
}

export function setRecoveryKeyData(lookupHash: string, wrappedMasterKey: string, salt: string, keyIv: string) {
    recoveryKeyData.set({
        lookupHash,
        wrappedMasterKey,
        salt,
        keyIv
    });
}