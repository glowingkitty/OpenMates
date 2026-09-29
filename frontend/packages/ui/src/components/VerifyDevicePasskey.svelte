<!--
VerifyDevicePasskey - Component for passkey-based device verification.
Shown when a passkey-only user accesses the app from a new/unknown device.
Uses WebAuthn API to verify the user's identity via their registered passkey,
then calls the backend /passkey/verify/device endpoint to register the new device.

Follows the same event-based pattern as VerifyDevice2FA.svelte:
- Dispatches 'deviceVerified' on success (Login.svelte re-checks auth)
- Dispatches 'switchToLogin' to return to the login form
- Dispatches 'passkeyActivity' for inactivity timer management
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { onMount, createEventDispatcher } from 'svelte';
    import InputWarning from './common/InputWarning.svelte';
    import { getApiEndpoint, apiEndpoints } from '../config/api';
    import * as cryptoService from '../services/cryptoService';
    import { createPasswordV2Proof, derivePasswordV2, requirePasswordCredentialVersion } from '../services/passwordV2';
    import { getSessionId } from '../utils/sessionId';

    // Props using Svelte 5 runes
    let {
        reason = null,
        passwordFallbackAvailable = false,
        passwordCredentialVersion = null,
        isLoading = $bindable(false),
        errorMessage = $bindable(null)
    }: {
        reason?: 'new_device' | 'location_change' | null;
        passwordFallbackAvailable?: boolean;
        passwordCredentialVersion?: number | null;
        isLoading?: boolean;
        errorMessage?: string | null;
    } = $props();

    const dispatch = createEventDispatcher();
    let fallbackStep = $state<'passkey' | 'password' | 'email_code'>('passkey');
    let password = $state('');
    let code = $state('');
    let challengeId = $state('');
    let hashedEmail = '';
    let lookupHash = '';
    let passwordChallengeId = '';
    let passwordProof = '';

    function clearFallbackProof() {
        password = '';
        code = '';
        challengeId = '';
        hashedEmail = '';
        lookupHash = '';
        passwordChallengeId = '';
        passwordProof = '';
    }

    async function requestEmailCode(event: SubmitEvent) {
        event.preventDefault();
        if (!passwordFallbackAvailable || isLoading || !password) return;
        isLoading = true;
        errorMessage = null;
        dispatch('passkeyActivity');
        try {
            const email = await cryptoService.getEmailDecryptedWithMasterKey();
            const salt = cryptoService.getEmailSalt();
            if (!email || !salt) throw new Error('Local account credentials unavailable');
            if (passwordCredentialVersion === null) throw new Error('Password credential version unavailable');
            const version = requirePasswordCredentialVersion(passwordCredentialVersion);
            hashedEmail = await cryptoService.hashEmail(email);
            const response = await fetch(getApiEndpoint('/v1/auth/sensitive/email/request'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ purpose: 'device_approval', email, session_id: getSessionId() })
            });
            const data = await response.json();
            if (!response.ok || !data.challenge_id) throw new Error('Email challenge unavailable');
            if (version === 2) {
                if (!data.password_challenge_id || !data.password_nonce) throw new Error('Password challenge unavailable');
                const { authKey } = await derivePasswordV2(password, salt);
                passwordProof = await createPasswordV2Proof(authKey, data.password_nonce, 'sensitive:device_approval');
                authKey.fill(0);
                passwordChallengeId = data.password_challenge_id;
            } else {
                lookupHash = await cryptoService.hashKey(password, salt);
            }
            password = '';
            challengeId = data.challenge_id;
            fallbackStep = 'email_code';
        } catch {
            clearFallbackProof();
            errorMessage = $text('login.error_occurred');
        } finally {
            isLoading = false;
        }
    }

    async function verifyEmailCode(event: SubmitEvent) {
        event.preventDefault();
        if (isLoading || !challengeId || !/^[0-9]{6}$/.test(code)) return;
        isLoading = true;
        errorMessage = null;
        dispatch('passkeyActivity');
        try {
            const response = await fetch(getApiEndpoint('/v1/auth/sensitive/email/verify'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    purpose: 'device_approval', challenge_id: challengeId, code,
                    hashed_email: hashedEmail,
                    lookup_hash: lookupHash || undefined,
                    password_challenge_id: passwordChallengeId || undefined,
                    password_proof: passwordProof || undefined,
                    session_id: getSessionId()
                })
            });
            const data = await response.json();
            if (!response.ok || !data.success) throw new Error('Device approval failed');
            clearFallbackProof();
            dispatch('deviceVerified');
        } catch {
            code = '';
            errorMessage = $text('login.error_occurred');
        } finally {
            isLoading = false;
        }
    }

    function showPasskey() {
        clearFallbackProof();
        errorMessage = null;
        fallbackStep = 'passkey';
    }

    // ========================================================================
    // HELPER FUNCTIONS
    // ========================================================================

    /** Convert base64url string to ArrayBuffer */
    function base64UrlToArrayBuffer(base64url: string): ArrayBuffer {
        let base64 = base64url.replace(/-/g, '+').replace(/_/g, '/');
        while (base64.length % 4) {
            base64 += '=';
        }
        const binary = window.atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
        }
        return bytes.buffer;
    }

    /** Convert Uint8Array to base64url string */
    function uint8ArrayToBase64(arr: Uint8Array): string {
        return btoa(String.fromCharCode(...arr))
            .replace(/\+/g, '-')
            .replace(/\//g, '_')
            .replace(/=/g, '');
    }

    // ========================================================================
    // PASSKEY VERIFICATION FLOW
    // ========================================================================

    /**
     * Initiates the WebAuthn passkey assertion flow for device verification.
     * 1. Gets the user's hashed email for passkey lookup
     * 2. Calls passkey_assertion_initiate to get a WebAuthn challenge
     * 3. Prompts the user for biometric/PIN verification via WebAuthn API
     * 4. Sends the assertion result to passkey_verify_device endpoint
     * 5. On success, dispatches 'deviceVerified' event
     */
    async function handlePasskeyVerification() {
        if (isLoading || fallbackStep !== 'passkey') return;

        isLoading = true;
        errorMessage = null;
        dispatch('passkeyActivity');

        try {
            // Step 1: Get user email for passkey lookup
            const email = await cryptoService.getEmailDecryptedWithMasterKey();
            if (!email) {
                // If no email in storage, this is an edge case - user needs to re-login
                throw new Error('Email not available for passkey verification');
            }

            const emailHash = await cryptoService.hashEmail(email);

            // Step 2: Initiate passkey assertion to get WebAuthn challenge
            const initiateResponse = await fetch(getApiEndpoint(apiEndpoints.auth.passkey_assertion_initiate), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Origin': window.location.origin
                },
                credentials: 'include',
                body: JSON.stringify({
                    hashed_email: emailHash,
                    session_id: getSessionId()
                })
            });

            if (!initiateResponse.ok) {
                throw new Error('Failed to initiate passkey verification');
            }

            const initiateData = await initiateResponse.json();
            if (!initiateData.success) {
                throw new Error(initiateData.message || 'Passkey verification initiation failed');
            }

            // Validate required fields from response
            if (!initiateData.challenge || !initiateData.rp?.id) {
                throw new Error('Invalid passkey challenge response from server');
            }

            // Step 3: Build WebAuthn credential request options
            const challenge = base64UrlToArrayBuffer(initiateData.challenge);
            const prfEvalFirst = initiateData.extensions?.prf?.eval?.first || initiateData.challenge;
            const prfEvalFirstBuffer = base64UrlToArrayBuffer(prfEvalFirst);

            const publicKeyCredentialRequestOptions = {
                challenge: challenge,
                rpId: initiateData.rp.id,
                timeout: initiateData.timeout,
                userVerification: initiateData.userVerification,
                allowCredentials: initiateData.allowCredentials?.length > 0
                    ? initiateData.allowCredentials.map((cred: { type: string; id: string; transports?: string[] }) => ({
                        type: cred.type,
                        id: base64UrlToArrayBuffer(cred.id),
                        transports: cred.transports
                    }))
                    : [],
                extensions: {
                    prf: {
                        eval: {
                            first: prfEvalFirstBuffer
                        }
                    }
                }
            };

            // Step 4: Prompt user for passkey authentication (biometrics/PIN)
            const credential = await navigator.credentials.get({
                publicKey: publicKeyCredentialRequestOptions
            }) as PublicKeyCredential;

            if (!credential) {
                throw new Error('Passkey authentication was cancelled');
            }

            // Step 5: Extract assertion response data
            const response = credential.response as AuthenticatorAssertionResponse;
            const clientDataJSON = new Uint8Array(response.clientDataJSON);
            const authenticatorData = new Uint8Array(response.authenticatorData);
            const signature = new Uint8Array(response.signature);

            const credentialId = uint8ArrayToBase64(new Uint8Array(credential.rawId));
            const clientDataJSONB64 = uint8ArrayToBase64(clientDataJSON);
            const authenticatorDataB64 = uint8ArrayToBase64(authenticatorData);
            const signatureB64 = uint8ArrayToBase64(signature);

            // Step 6: Send assertion to the device verification endpoint
            // This endpoint verifies the passkey AND registers the new device
            const verifyResponse = await fetch(getApiEndpoint(apiEndpoints.auth.passkey_verify_device), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'Origin': window.location.origin
                },
                credentials: 'include',
                body: JSON.stringify({
                    credential_id: credentialId,
                    assertion_response: {
                        authenticatorData: authenticatorDataB64,
                        clientDataJSON: clientDataJSONB64,
                        signature: signatureB64
                    },
                    client_data_json: clientDataJSONB64,
                    authenticator_data: authenticatorDataB64,
                    session_id: getSessionId()
                })
            });

            const verifyData = await verifyResponse.json();

            if (verifyResponse.ok && verifyData.success) {
                console.debug('[VerifyDevicePasskey] Device verification successful.');
                dispatch('deviceVerified');
            } else {
                console.warn('[VerifyDevicePasskey] Device verification failed:', verifyData.message);
                errorMessage = verifyData.message || $text('login.verify_device_passkey_error');
            }

        } catch (error) {
            console.error('[VerifyDevicePasskey] Passkey device verification error:', error);

            if (error instanceof Error) {
                if (error.name === 'NotAllowedError' || error.message.includes('cancelled')) {
                    // User cancelled the WebAuthn prompt - not an error, just reset
                    errorMessage = null;
                } else {
                    errorMessage = $text('login.verify_device_passkey_error');
                }
            } else {
                errorMessage = $text('login.verify_device_passkey_error');
            }
        } finally {
            isLoading = false;
        }
    }

    // Handler to switch back to login
    function handleSwitchToLogin(event: Event) {
        event.preventDefault();
        clearFallbackProof();
        dispatch('switchToLogin');
    }

    // Auto-start passkey verification on mount
    onMount(() => {
        // Small delay to allow the UI to render before prompting WebAuthn
        // A password login may reach this screen on a device without its passkey.
        // Let the user choose before opening an unavailable WebAuthn prompt.
        if (!passwordFallbackAvailable) {
            setTimeout(() => { void handlePasskeyVerification(); }, 300);
        }
    });
</script>

<div class="verify-device-passkey">
    {#if reason === 'location_change'}
        <div class="location-change-notice" data-testid="location-change-notice">
            <span class="icon icon_shield"></span>
            <p>{$text('login.verify_device_location_change_notice')}</p>
        </div>
    {/if}

    {#if fallbackStep === 'passkey'}
        <p class="verify-prompt">{$text('login.verify_device_passkey_prompt')}</p>
    {:else if fallbackStep === 'password'}
        <p class="verify-prompt">{$text('settings.security.enter_password')}</p>
    {:else}
        <p class="verify-prompt">{$text('login.enter_code_sent')}</p>
    {/if}

    <div class="action-area">
        {#if isLoading}
            <div class="loading-indicator">
                <span class="spinner"></span>
            </div>
        {:else if fallbackStep === 'passkey'}
            <button
                class="verify-button"
                onclick={handlePasskeyVerification}
                disabled={isLoading}
                data-testid="verify-device-passkey-button"
            >
                <span class="icon icon_passkey"></span>
                {$text('login.verify_device_passkey_button')}
            </button>
            {#if passwordFallbackAvailable}
                <button type="button" class="text-button" data-testid="device-password-fallback"
                    onclick={() => { errorMessage = null; fallbackStep = 'password'; }}>
                    {$text('settings.security.use_password_instead')}
                </button>
            {/if}
        {:else if fallbackStep === 'password'}
            <form onsubmit={requestEmailCode} class="fallback-form">
                <input type="password" autocomplete="current-password" bind:value={password}
                    data-testid="device-password-input" aria-label={$text('settings.security.enter_password')} />
                <button type="submit" class="verify-button" disabled={!password} data-testid="device-request-email-code">
                    {$text('login.continue')}
                </button>
            </form>
            <button type="button" class="text-button" onclick={showPasskey}>
                {$text('settings.security.use_passkey_instead')}
            </button>
        {:else}
            <form onsubmit={verifyEmailCode} class="fallback-form">
                <input type="text" inputmode="numeric" autocomplete="one-time-code" maxlength="6"
                    value={code} oninput={(event) => { code = event.currentTarget.value.replace(/\D/g, '').slice(0, 6); dispatch('passkeyActivity'); }}
                    data-testid="device-email-code-input" aria-label={$text('login.verification_code')} />
                <button type="submit" class="verify-button" disabled={!/^[0-9]{6}$/.test(code)} data-testid="device-verify-email-code">
                    {$text('login.continue')}
                </button>
            </form>
            <button type="button" class="text-button" onclick={showPasskey}>
                {$text('settings.security.use_passkey_instead')}
            </button>
        {/if}

        {#if errorMessage}
            <InputWarning message={errorMessage} />
        {/if}
    </div>

    <div class="switch-account">
        <button type="button" onclick={handleSwitchToLogin} class="text-button" data-testid="text-button">
            {$text('login.login_with_another_account')}
        </button>
    </div>
</div>

<style>
    .verify-device-passkey {
        display: flex;
        flex-direction: column;
    }

    .location-change-notice {
        display: flex;
        align-items: flex-start;
        gap: var(--spacing-5);
        padding: 12px 14px;
        margin-bottom: 15px;
        background-color: var(--color-warning-bg, var(--color-grey-10));
        border-radius: var(--radius-3);
        border-left: 3px solid var(--color-warning, var(--color-primary));
    }

    .location-change-notice .icon {
        width: 20px;
        height: 20px;
        flex-shrink: 0;
        margin-top: var(--spacing-1);
    }

    .location-change-notice p {
        margin: 0;
        font-size: var(--font-size-small);
        line-height: 1.4;
        color: var(--color-grey-70);
    }

    .verify-prompt {
        margin: var(--spacing-0);
        margin-bottom: 15px;
        color: var(--color-grey-60);
    }

    .action-area {
        display: flex;
        flex-direction: column;
        gap: var(--spacing-5);
    }

    .fallback-form {
        display: flex;
        flex-direction: column;
        gap: var(--spacing-5);
    }

    .fallback-form input {
        width: 100%;
        box-sizing: border-box;
        padding: var(--spacing-6);
        border: 1px solid var(--color-grey-30);
        border-radius: var(--radius-3);
        background: var(--color-background);
        color: var(--color-text);
        font: inherit;
    }

    .verify-button {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: var(--spacing-4);
        padding: var(--spacing-6) var(--spacing-12);
        background-color: var(--color-primary);
        color: var(--color-white);
        border: none;
        border-radius: var(--radius-3);
        font-size: var(--font-size-p);
        cursor: pointer;
        transition: background-color var(--duration-normal) var(--easing-default);
    }

    .verify-button:hover:not(:disabled) {
        background-color: var(--color-primary-hover, var(--color-primary));
    }

    .verify-button:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }

    .verify-button .icon {
        width: 20px;
        height: 20px;
    }

    .loading-indicator {
        display: flex;
        justify-content: center;
        padding: var(--spacing-6);
    }

    .spinner {
        width: 24px;
        height: 24px;
        border: 3px solid var(--color-grey-30);
        border-top-color: var(--color-primary);
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
    }

    @keyframes spin {
        to { transform: rotate(360deg); }
    }

    .switch-account {
        margin-top: var(--spacing-5);
    }

    @media (max-width: 600px) {
        .verify-device-passkey {
            align-items: center;
        }
    }
</style>
