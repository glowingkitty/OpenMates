import { argon2id } from 'hash-wasm';

export const PASSWORD_V2_VERSION = 2;
export const PASSWORD_V2_MEMORY_KIB = 65536;
export const PASSWORD_V2_ITERATIONS = 3;
export const PASSWORD_V2_PARALLELISM = 1;

export interface PasswordV2Keys {
    authKey: Uint8Array;
    wrapKey: Uint8Array;
}

export function toBase64Url(bytes: Uint8Array): string {
    let binary = '';
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function fromBase64Url(value: string): Uint8Array {
    if (!/^[A-Za-z0-9_-]+$/.test(value) || value.length % 4 === 1) throw new Error('Invalid password challenge');
    const padded = value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - value.length % 4) % 4);
    const binary = atob(padded);
    return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

async function expandPasswordKey(root: Uint8Array, label: string): Promise<Uint8Array> {
    const material = await crypto.subtle.importKey('raw', root, 'HKDF', false, ['deriveBits']);
    const bits = await crypto.subtle.deriveBits({
        name: 'HKDF', hash: 'SHA-256', salt: new Uint8Array(0), info: new TextEncoder().encode(label),
    }, material, 256);
    return new Uint8Array(bits);
}

/** Direct implementation for the dedicated worker and cross-client vector tests. */
export async function derivePasswordV2Direct(password: string, userEmailSalt: Uint8Array): Promise<PasswordV2Keys> {
    if (!password || userEmailSalt.length < 16) throw new Error('Invalid password KDF input');
    const root = await argon2id({
        password: new TextEncoder().encode(password), salt: userEmailSalt,
        parallelism: PASSWORD_V2_PARALLELISM, iterations: PASSWORD_V2_ITERATIONS,
        memorySize: PASSWORD_V2_MEMORY_KIB, hashLength: 32, outputType: 'binary',
    });
    try {
        const authKey = await expandPasswordKey(root, 'openmates/password-v2/auth');
        const wrapKey = await expandPasswordKey(root, 'openmates/password-v2/wrap');
        return { authKey, wrapKey };
    } finally { root.fill(0); }
}

/** Run the 64 MiB Argon2id work off the browser UI thread. */
/** One-use challenge proof; the derived auth key itself is never sent at login. */
export async function createPasswordV2Proof(authKey: Uint8Array, nonce: string, purpose: string): Promise<string> {
    if (!purpose || purpose.includes('\0')) throw new Error('Invalid password proof purpose');
    const prefix = new TextEncoder().encode(`openmates/password-v2/proof\0${purpose}\0`);
    const nonceBytes = fromBase64Url(nonce);
    if (nonceBytes.length !== 32) throw new Error('Invalid password challenge');
    const message = new Uint8Array(prefix.length + nonceBytes.length);
    message.set(prefix); message.set(nonceBytes, prefix.length);
    const key = await crypto.subtle.importKey('raw', authKey, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
    return toBase64Url(new Uint8Array(await crypto.subtle.sign('HMAC', key, message)));
}

export function requirePasswordCredentialVersion(value: unknown): 1 | 2 {
    if (value === undefined || value === null || value === 1) return 1;
    if (value === 2) return 2;
    throw new Error('Unsupported password credential version');
}

