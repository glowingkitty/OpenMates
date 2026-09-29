import { getApiEndpoint } from '../config/api';
import { createPasswordV2Proof, derivePasswordV2Direct, fromBase64Url, requirePasswordCredentialVersion, toBase64Url } from './passwordV2Core';
import type { PasswordV2Keys } from './passwordV2Core';
export { createPasswordV2Proof, derivePasswordV2Direct, fromBase64Url, requirePasswordCredentialVersion, toBase64Url } from './passwordV2Core';
export type { PasswordV2Keys } from './passwordV2Core';

export async function derivePasswordV2(password: string, userEmailSalt: Uint8Array): Promise<PasswordV2Keys> {
    if (typeof window === 'undefined') return derivePasswordV2Direct(password, userEmailSalt);
    if (typeof Worker === 'undefined') return derivePasswordV2Direct(password, userEmailSalt);
    const worker = new Worker(new URL('./passwordV2Worker.ts', import.meta.url), { type: 'module' });
    return new Promise((resolve, reject) => {
        worker.onmessage = (event: MessageEvent<{ authKey?: Uint8Array; wrapKey?: Uint8Array; error?: string }>) => {
            worker.terminate();
            const { authKey, wrapKey, error } = event.data;
            if (error || !authKey || !wrapKey) reject(new Error(error || 'Password derivation failed'));
            else resolve({ authKey, wrapKey });
        };
        worker.onerror = () => { worker.terminate(); reject(new Error('Password derivation failed')); };
        worker.postMessage({ password, userEmailSalt });
    });
}

export async function requestPasswordV2LoginChallenge(hashedEmail: string, sessionId: string): Promise<{ challenge_id: string; nonce: string }> {
    const response = await fetch(getApiEndpoint('/v1/auth/password-v2/challenge'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
        body: JSON.stringify({ hashed_email: hashedEmail, session_id: sessionId, purpose: 'login' }),
    });
    if (!response.ok) throw new Error('Password challenge unavailable');
    const data = await response.json();
    if (typeof data.challenge_id !== 'string' || typeof data.nonce !== 'string' || fromBase64Url(data.nonce).length !== 32) {
        throw new Error('Invalid password challenge');
    }
    return { challenge_id: data.challenge_id, nonce: data.nonce };
}

/** A generic v2 attempt precedes legacy login; only an authentication failure permits fallback. */
export async function loginWithPasswordVersions(options: {
    password: string;
    hashedEmail: string;
    userEmailSalt: Uint8Array;
    sessionId: string;
    fields: Record<string, unknown>;
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- Login responses contain method-specific user fields.
}): Promise<{ response: Response; data: Record<string, any> }> {
    const { password, hashedEmail, userEmailSalt, sessionId, fields } = options;
    const { authKey, wrapKey } = await derivePasswordV2(password, userEmailSalt);
    let challenge: { challenge_id: string; nonce: string };
    let passwordProof: string;
    try {
        challenge = await requestPasswordV2LoginChallenge(hashedEmail, sessionId);
        passwordProof = await createPasswordV2Proof(authKey, challenge.nonce, 'login');
    } finally {
        authKey.fill(0);
        wrapKey.fill(0);
    }
    const endpoint = getApiEndpoint('/v1/auth/login');
    const headers = { 'Content-Type': 'application/json', 'Accept': 'application/json', 'Origin': window.location.origin };
    const response = await fetch(endpoint, {
        method: 'POST', headers, credentials: 'include',
        body: JSON.stringify({ ...fields, hashed_email: hashedEmail, session_id: sessionId,
            login_method: 'password', credential_version: 2,
            challenge_id: challenge.challenge_id, password_proof: passwordProof }),
    });
    const data = await response.json();
    if (response.status === 429 || response.status >= 500 || (response.ok && data.success && data.user?.id)) {
        return { response, data };
    }
    // An account with a typed v2 credential cannot authenticate through v1 server-side.
    const lookupHash = await import('./cryptoService').then((service) => service.hashKey(password, userEmailSalt));
    const legacyResponse = await fetch(endpoint, {
        method: 'POST', headers, credentials: 'include',
        body: JSON.stringify({ ...fields, hashed_email: hashedEmail, session_id: sessionId,
            login_method: 'password', credential_version: 1, lookup_hash: lookupHash }),
    });
    return { response: legacyResponse, data: await legacyResponse.json() };
}

/** Resume an interrupted typed migration before attempting any new enrollment. */
export async function migrateUnlockedLegacyPassword(
    password: string,
    userEmailSalt: Uint8Array,
    masterKey: CryptoKey,
): Promise<'typed_retired' | 'legacy_retained' | 'pending_confirmation' | 'deferred_legacy_credentials' | 'deferred_recent_verification'> {
    const cryptoService = await import('./cryptoService');
    const { authKey, wrapKey } = await derivePasswordV2(password, userEmailSalt);
    const stagedChallengeUrl = getApiEndpoint('/v1/auth/password-v2/staged-challenge');
    const requestStagedChallenge = () => fetch(stagedChallengeUrl, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    try {
        // A prior attempt may have committed the v2 record but lost the reply or
        // stopped before confirmation. The fresh v1 login binds this probe to the
        // exact old password; a successful probe is the only resume signal.
        let challengeResponse = await requestStagedChallenge();
        if (!challengeResponse.ok) {
            const details = await challengeResponse.json().catch(() => null);
            if (challengeResponse.status !== 409 || details?.detail !== 'No pending password migration') {
                throw new Error('Password migration status unavailable');
            }

            const oldLookupHash = await cryptoService.hashKey(password, userEmailSalt);
            const wrapped = await cryptoService.encryptKey(masterKey, wrapKey);
            const checked = await cryptoService.decryptKey(wrapped.wrapped, wrapped.iv, wrapKey);
            if (!checked || !await sameMasterKey(masterKey, checked)) {
                throw new Error('Password migration wrapper verification failed');
            }
            const response = await fetch(getApiEndpoint('/v1/auth/password-v2/migrate'), {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
                body: JSON.stringify({ old_lookup_hash: oldLookupHash, password_auth_key: toBase64Url(authKey),
                    encrypted_master_key: wrapped.wrapped, salt: cryptoService.uint8ArrayToBase64(userEmailSalt), key_iv: wrapped.iv }),
            });
            const data = await response.json().catch(() => null);
            if (response.status === 409 && data?.detail?.error === 'legacy_credential_binding_required') {
                // No v2 record was installed. This account needs manual legacy
                // credential binding; a staged proof would be the wrong path.
                return 'deferred_legacy_credentials';
            }
            if (response.status === 428 && data?.detail?.error === 'recent_verification_required') {
                // Ordinary login and local key unlock have already succeeded.
                // A later explicit sensitive-action proof may permit migration.
                return 'deferred_recent_verification';
            }
            if (!response.ok) throw new Error('Password migration unavailable');
            if (data?.migration_status === 'legacy_retained') return 'legacy_retained';
            if (data?.migration_status !== 'pending_confirmation') throw new Error('Invalid password migration response');
            challengeResponse = await requestStagedChallenge();
            if (!challengeResponse.ok) return 'pending_confirmation';
        }

        const challenge = await challengeResponse.json();
        const proof = await createPasswordV2Proof(authKey, challenge.nonce, 'migration');
        const verifyResponse = await fetch(getApiEndpoint('/v1/auth/password-v2/verify-staged'), {
            method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ challenge_id: challenge.challenge_id, password_proof: proof }),
        });
        if (!verifyResponse.ok) return 'pending_confirmation';
        const verified = await verifyResponse.json();
        if (requirePasswordCredentialVersion(verified.credential_version) !== 2 ||
            verified.salt !== cryptoService.uint8ArrayToBase64(userEmailSalt)) {
            throw new Error('Password migration returned an invalid credential');
        }
        const unlocked = await cryptoService.decryptKey(verified.encrypted_key, verified.key_iv, wrapKey);
        if (!unlocked || !await sameMasterKey(masterKey, unlocked)) {
            throw new Error('Password migration returned a different master key');
        }
        const confirmResponse = await fetch(getApiEndpoint('/v1/auth/password-v2/confirm-migration'), {
            method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: '{}',
        });
        if (!confirmResponse.ok) {
            const confirmError = await confirmResponse.json().catch(() => null);
            if (confirmResponse.status === 428 && confirmError?.detail?.error === 'recent_verification_required') {
                return 'deferred_recent_verification';
            }
            return 'pending_confirmation';
        }
        const confirmData = await confirmResponse.json();
        if (confirmData.migration_status !== 'typed_retired') return 'pending_confirmation';
        return 'typed_retired';
    } finally {
        authKey.fill(0); wrapKey.fill(0);
    }
}

async function sameMasterKey(first: CryptoKey, second: CryptoKey): Promise<boolean> {
    const [firstBytes, secondBytes] = await Promise.all([
        crypto.subtle.exportKey('raw', first), crypto.subtle.exportKey('raw', second),
    ]);
    const a = new Uint8Array(firstBytes);
    const b = new Uint8Array(secondBytes);
    let difference = a.length ^ b.length;
    for (let index = 0; index < a.length; index++) difference |= a[index] ^ (b[index] ?? 0);
    a.fill(0); b.fill(0);
    return difference === 0;
}
