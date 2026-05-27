/**
 * @fileoverview Stores the last successful login method for this browser only.
 * The value is intentionally limited to a non-identifying enum so the login UI
 * can help users remember whether they used passkey or email/password.
 * It is never synced, logged, or sent to the backend.
 */

const LAST_AUTH_METHOD_KEY = 'openmates:last-auth-method';

export type LastAuthMethod = 'passkey' | 'email';

function isLastAuthMethod(value: string | null): value is LastAuthMethod {
    return value === 'passkey' || value === 'email';
}

export function getLastAuthMethod(): LastAuthMethod | null {
    if (typeof localStorage === 'undefined') return null;

    const value = localStorage.getItem(LAST_AUTH_METHOD_KEY);
    return isLastAuthMethod(value) ? value : null;
}

export function setLastAuthMethod(method: LastAuthMethod): void {
    if (typeof localStorage === 'undefined') return;

    localStorage.setItem(LAST_AUTH_METHOD_KEY, method);
}

export function clearLastAuthMethod(): void {
    if (typeof localStorage === 'undefined') return;

    localStorage.removeItem(LAST_AUTH_METHOD_KEY);
}
