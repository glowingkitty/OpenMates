import { writable } from 'svelte/store';

// Store to track 2FA setup status
export const twoFASetupComplete = writable<boolean>(false);

// Store to track 2FA data for the current session
export const twoFASetupData = writable<{
    secret: string;
    qrCodeUrl: string;
    otpauthUrl: string;
}>({
    secret: '',
    qrCodeUrl: '',
    otpauthUrl: ''
});

// Store to track 2FA verification status
export const twoFAVerificationStatus = writable<{
    verifying: boolean;
    error: boolean;
    errorMessage: string;
}>({
    verifying: false,
    error: false,
    errorMessage: ''
});

// Helper functions
export function setTwoFAData(secret: string, qrCodeUrl: string, otpauthUrl: string) {
    twoFASetupData.set({ secret, qrCodeUrl, otpauthUrl });
    twoFASetupComplete.set(true);
}

export function resetTwoFAData() {
    twoFASetupData.set({ secret: '', qrCodeUrl: '', otpauthUrl: '' });
    twoFASetupComplete.set(false);
}

export function setVerifying(isVerifying: boolean) {
    twoFAVerificationStatus.update(status => ({
        ...status,
        verifying: isVerifying,
        error: isVerifying ? false : status.error,
    }));
}

export function setVerificationError(message: string) {
    twoFAVerificationStatus.set({
        verifying: false,
        error: true,
        errorMessage: message
    });
}

export function clearVerificationError() {
    twoFAVerificationStatus.update(status => ({
        ...status,
        error: false,
        errorMessage: ''
    }));
}