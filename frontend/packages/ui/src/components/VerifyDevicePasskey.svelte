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
    import { getSessionId } from '../utils/sessionId';

    // Props using Svelte 5 runes
    let {
        reason = null,
        isLoading = $bindable(false),
        errorMessage = $bindable(null)
    }: {
        reason?: 'new_device' | 'location_change' | null;
        isLoading?: boolean;
        errorMessage?: string | null;
    } = $props();

    const dispatch = createEventDispatcher();

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
        if (isLoading) return;

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
        dispatch('switchToLogin');
    }

    // Auto-start passkey verification on mount
    onMount(() => {
        // Small delay to allow the UI to render before prompting WebAuthn
        setTimeout(() => {
            handlePasskeyVerification();
        }, 300);
    });
</script>

<div class="verify-device-passkey">
    {#if reason === 'location_change'}
        <div class="location-change-notice">
            <span class="icon icon_shield"></span>
            <p>{$text('login.verify_device_location_change_notice')}</p>
        </div>
    {/if}

    <p class="verify-prompt">
        {$text('login.verify_device_passkey_prompt')}
    </p>

    <div class="action-area">
        {#if isLoading}
            <div class="loading-indicator">
                <span class="spinner"></span>
            </div>
        {:else}
            <button
                class="verify-button"
                onclick={handlePasskeyVerification}
                disabled={isLoading}
            >
                <span class="icon icon_passkey"></span>
                {$text('login.verify_device_passkey_button')}
            </button>
        {/if}

        {#if errorMessage}
            <InputWarning message={errorMessage} />
        {/if}
    </div>

    <div class="switch-account">
        <button type="button" onclick={handleSwitchToLogin} class="text-button">
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
        gap: 10px;
        padding: 12px 14px;
        margin-bottom: 15px;
        background-color: var(--color-warning-bg, var(--color-grey-10));
        border-radius: 8px;
        border-left: 3px solid var(--color-warning, var(--color-primary));
    }

    .location-change-notice .icon {
        width: 20px;
        height: 20px;
        flex-shrink: 0;
        margin-top: 2px;
    }

    .location-change-notice p {
        margin: 0;
        font-size: 14px;
        line-height: 1.4;
        color: var(--color-grey-70);
    }

    .verify-prompt {
        margin: 0px;
        margin-bottom: 15px;
        color: var(--color-grey-60);
    }

    .action-area {
        display: flex;
        flex-direction: column;
        gap: 10px;
    }

    .verify-button {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        padding: 12px 24px;
        background-color: var(--color-primary);
        color: var(--color-white);
        border: none;
        border-radius: 8px;
        font-size: 16px;
        cursor: pointer;
        transition: background-color 0.2s ease;
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
        padding: 12px;
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
        margin-top: 10px;
    }

    @media (max-width: 600px) {
        .verify-device-passkey {
            align-items: center;
        }
    }
</style>
