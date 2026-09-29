import { webcrypto } from 'node:crypto';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { createPasswordV2Proof, derivePasswordV2Direct, loginWithPasswordVersions, migrateUnlockedLegacyPassword, requirePasswordCredentialVersion, toBase64Url } from '../passwordV2';

beforeAll(() => {
    Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true });
});

afterEach(() => vi.unstubAllGlobals());

const nonce = 'ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8';
const salt = Uint8Array.from({ length: 16 }, (_, index) => index);
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('password v2 cross-client protocol', () => {
    // contract-test: supporting surface=gui.web assertions=auth.password.versioned-protection
    it('matches the backend Argon2id/HKDF/HMAC vector', async () => {
        const { authKey, wrapKey } = await derivePasswordV2Direct('Correct Horse Battery Staple!', salt);
        expect(toBase64Url(authKey)).toBe('vH4NzewPmDGymGUgH11VasH-0clzgc98FEOnn6SEB5o');
        expect(toBase64Url(wrapKey)).toBe('d8EIpdqJ7JF5dhaA6xIcpQJTNu9kZGZimmu--sR-2Hc');
        expect(authKey).not.toEqual(wrapKey);
        expect(await createPasswordV2Proof(authKey, 'ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8', 'login'))
            .toBe('4BZxiDKNYrtneUG0v46ZS8a65q64y1AsHKXpgB9XwO0');
    });

    // contract-test: supporting surface=gui.web assertions=auth.password.versioned-protection
    it('uses a one-use v2 login proof without sending the static auth key or legacy lookup', async () => {
        const calls: Record<string, unknown>[] = [];
        vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
            const body = JSON.parse(String(init.body));
            calls.push(body);
            return calls.length === 1
                ? json({ challenge_id: 'challenge-one', nonce })
                : json({ success: true, user: { id: 'account-id', credential_version: 2 } });
        }));
        const result = await loginWithPasswordVersions({
            password: 'Correct Horse Battery Staple!', hashedEmail: 'hashed-email',
            userEmailSalt: salt, sessionId: 'session-123', fields: { stay_logged_in: true },
        });
        expect(result.data.success).toBe(true);
        expect(calls).toHaveLength(2);
        expect(calls[1]).toMatchObject({ credential_version: 2, challenge_id: 'challenge-one',
            password_proof: '4BZxiDKNYrtneUG0v46ZS8a65q64y1AsHKXpgB9XwO0' });
        expect(calls[1]).not.toHaveProperty('password_auth_key');
        expect(calls[1]).not.toHaveProperty('lookup_hash');
    });

    // contract-test: supporting surface=gui.web assertions=auth.password.versioned-protection
    it('tries legacy only after a generic v2 authentication rejection', async () => {
        const calls: Record<string, unknown>[] = [];
        vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
            calls.push(JSON.parse(String(init.body)));
            if (calls.length === 1) return json({ challenge_id: 'challenge-two', nonce });
            if (calls.length === 2) return json({ success: true, tfa_required: true });
            return json({ success: true, user: { id: 'legacy-account', credential_version: 1 } });
        }));
        const result = await loginWithPasswordVersions({
            password: 'Correct Horse Battery Staple!', hashedEmail: 'hashed-email',
            userEmailSalt: salt, sessionId: 'session-123', fields: {},
        });
        expect(result.data.user?.id).toBe('legacy-account');
        expect(calls).toHaveLength(3);
        expect(calls[1]).not.toHaveProperty('lookup_hash');
        expect(calls[2]).toMatchObject({ credential_version: 1, login_method: 'password' });
        expect(calls[2].lookup_hash).toEqual(expect.any(String));
    });

    // contract-test: supporting surface=gui.web assertions=auth.password.versioned-protection
    it('does not downgrade when the v2 challenge service is unavailable', async () => {
        const fetchMock = vi.fn(async () => json({ detail: 'unavailable' }, 503));
        vi.stubGlobal('fetch', fetchMock);
        await expect(loginWithPasswordVersions({
            password: 'Correct Horse Battery Staple!', hashedEmail: 'hashed-email',
            userEmailSalt: salt, sessionId: 'session-123', fields: {},
        })).rejects.toThrow('Password challenge unavailable');
        expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    // contract-test: supporting surface=gui.web assertions=auth.password.versioned-protection
    it('retains the typed old password when staged migration is interrupted', async () => {
        const calls: string[] = [];
        vi.stubGlobal('fetch', vi.fn(async (url: string) => {
            calls.push(url);
            if (calls.length === 1) return json({ detail: 'No pending password migration' }, 409);
            if (url.endsWith('/migrate')) return json({ success: true, migration_status: 'pending_confirmation' });
            return json({ detail: 'temporarily unavailable' }, 503);
        }));
        const masterKey = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt', 'decrypt']);
        const result = await migrateUnlockedLegacyPassword('Correct Horse Battery Staple!', salt, masterKey);
        expect(result).toBe('pending_confirmation');
        expect(calls).toHaveLength(3);
        expect(calls.some((url) => url.includes('confirm-migration'))).toBe(false);
    });

    // contract-test: supporting surface=gui.web assertions=auth.password.versioned-protection
    it('resumes an earlier typed stage on the next v1 login without trying to stage again', async () => {
        const masterKey = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt', 'decrypt']);
        const { wrapKey } = await derivePasswordV2Direct('Correct Horse Battery Staple!', salt);
        const { encryptKey, uint8ArrayToBase64 } = await import('../cryptoService');
        const wrapped = await encryptKey(masterKey, wrapKey);
        const paths: string[] = [];
        vi.stubGlobal('fetch', vi.fn(async (url: string) => {
            paths.push(url);
            if (url.includes('/staged-challenge')) return json({ challenge_id: 'resumed-stage', nonce });
            if (url.includes('/verify-staged')) return json({ encrypted_key: wrapped.wrapped,
                salt: uint8ArrayToBase64(salt), key_iv: wrapped.iv, credential_version: 2 });
            if (url.includes('/confirm-migration')) return json({ success: true, migration_status: 'typed_retired' });
            throw new Error('A pending migration must not be staged again');
        }));
        expect(await migrateUnlockedLegacyPassword('Correct Horse Battery Staple!', salt, masterKey)).toBe('typed_retired');
        expect(paths).toHaveLength(3);
        expect(paths.some((url) => url.endsWith('/migrate'))).toBe(false);
    });

    // contract-test: supporting surface=gui.web assertions=auth.password.versioned-protection
    it('does not treat ambiguous legacy credential deferral as a resumable stage', async () => {
        const paths: string[] = [];
        vi.stubGlobal('fetch', vi.fn(async (url: string) => {
            paths.push(url);
            if (url.includes('/staged-challenge')) return json({ detail: 'No pending password migration' }, 409);
            if (url.endsWith('/migrate')) return json({ detail: {
                error: 'legacy_credential_binding_required', migration_status: 'deferred_legacy_credentials',
            } }, 409);
            throw new Error('Deferred legacy credentials must not be verified or confirmed');
        }));
        const masterKey = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt', 'decrypt']);
        expect(await migrateUnlockedLegacyPassword('Correct Horse Battery Staple!', salt, masterKey))
            .toBe('deferred_legacy_credentials');
        expect(paths).toHaveLength(2);
    });

    // contract-test: supporting surface=gui.web assertions=auth.password.versioned-protection,auth.sensitive-actions.recent-verification
    it('defers background migration when the server requires recent verification', async () => {
        const paths: string[] = [];
        vi.stubGlobal('fetch', vi.fn(async (url: string) => {
            paths.push(url);
            if (url.includes('/staged-challenge')) return json({ detail: 'No pending password migration' }, 409);
            if (url.endsWith('/migrate')) return json({ detail: { error: 'recent_verification_required' } }, 428);
            throw new Error('Ordinary login must not start email verification or staged migration');
        }));
        const masterKey = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt', 'decrypt']);
        expect(await migrateUnlockedLegacyPassword('Correct Horse Battery Staple!', salt, masterKey))
            .toBe('deferred_recent_verification');
        expect(paths).toHaveLength(2);
    });

    // contract-test: supporting surface=gui.web assertions=auth.password.versioned-protection,auth.sensitive-actions.recent-verification
    it('leaves a staged migration pending when verification expires before confirmation', async () => {
        const masterKey = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt', 'decrypt']);
        const { wrapKey } = await derivePasswordV2Direct('Correct Horse Battery Staple!', salt);
        const { encryptKey, uint8ArrayToBase64 } = await import('../cryptoService');
        const wrapped = await encryptKey(masterKey, wrapKey);
        const paths: string[] = [];
        vi.stubGlobal('fetch', vi.fn(async (url: string) => {
            paths.push(url);
            if (url.includes('/staged-challenge')) return json({ challenge_id: 'pending-stage', nonce });
            if (url.includes('/verify-staged')) return json({ encrypted_key: wrapped.wrapped,
                salt: uint8ArrayToBase64(salt), key_iv: wrapped.iv, credential_version: 2 });
            if (url.includes('/confirm-migration')) return json({ detail: { error: 'recent_verification_required' } }, 428);
            throw new Error('A pending migration must not be staged again');
        }));
        expect(await migrateUnlockedLegacyPassword('Correct Horse Battery Staple!', salt, masterKey))
            .toBe('deferred_recent_verification');
        expect(paths).toHaveLength(3);
    });

    // contract-test: supporting surface=gui.web assertions=auth.password.versioned-protection
    it('confirms a staged migration only after the returned v2 wrapper matches the unlocked key', async () => {
        let staged: Record<string, string> | undefined;
        const paths: string[] = [];
        let challengeCount = 0;
        vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
            paths.push(url);
            if (url.includes('/staged-challenge')) {
                challengeCount++;
                return challengeCount === 1
                    ? json({ detail: 'No pending password migration' }, 409)
                    : json({ challenge_id: 'staged-one', nonce });
            }
            if (url.includes('/migrate')) {
                staged = JSON.parse(String(init.body));
                return json({ success: true, migration_status: 'pending_confirmation' });
            }
            if (url.includes('/verify-staged')) {
                const body = JSON.parse(String(init.body));
                expect(body.password_proof).toMatch(/^[A-Za-z0-9_-]{43}$/);
                return json({ encrypted_key: staged?.encrypted_master_key, salt: staged?.salt,
                    key_iv: staged?.key_iv, credential_version: 2 });
            }
            return json({ success: true, migration_status: 'typed_retired' });
        }));
        const masterKey = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt', 'decrypt']);
        expect(await migrateUnlockedLegacyPassword('Correct Horse Battery Staple!', salt, masterKey)).toBe('typed_retired');
        expect(paths.at(-1)).toContain('/confirm-migration');
    });

    // contract-test: supporting surface=gui.web assertions=auth.password.versioned-protection
    it('refuses to retire v1 when the staged wrapper cannot unlock the same master key', async () => {
        let staged: Record<string, string> | undefined;
        const paths: string[] = [];
        let challengeCount = 0;
        vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
            paths.push(url);
            if (url.includes('/staged-challenge')) {
                challengeCount++;
                return challengeCount === 1
                    ? json({ detail: 'No pending password migration' }, 409)
                    : json({ challenge_id: 'staged-two', nonce });
            }
            if (url.includes('/migrate')) {
                staged = JSON.parse(String(init.body));
                return json({ success: true, migration_status: 'pending_confirmation' });
            }
            if (url.includes('/verify-staged')) return json({ encrypted_key: `${staged?.encrypted_master_key}invalid`,
                salt: staged?.salt, key_iv: staged?.key_iv, credential_version: 2 });
            return json({ success: true, migration_status: 'typed_retired' });
        }));
        const masterKey = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt', 'decrypt']);
        await expect(migrateUnlockedLegacyPassword('Correct Horse Battery Staple!', salt, masterKey)).rejects.toThrow();
        expect(paths.some((url) => url.includes('/confirm-migration'))).toBe(false);
    });

    // contract-test: supporting surface=gui.web assertions=auth.password.versioned-protection
    it('rejects unsupported versions and malformed one-use challenges', async () => {
        expect(requirePasswordCredentialVersion(undefined)).toBe(1);
        expect(requirePasswordCredentialVersion(2)).toBe(2);
        expect(() => requirePasswordCredentialVersion(3)).toThrow('Unsupported password credential version');
        await expect(createPasswordV2Proof(new Uint8Array(32), 'not-a-32-byte-nonce', 'login')).rejects.toThrow('Invalid password challenge');
    });
});
