<!--
PaymentAuth - Component for authenticating payment with passkey or 2FA
-->

<script lang="ts">
    import { createEventDispatcher, onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { getApiEndpoint, apiEndpoints } from '../../../config/api';
    import * as cryptoService from '../../../services/cryptoService';
    import { getSessionId } from '../../../utils/sessionId';

    const dispatch = createEventDispatcher();

    let { 
        hasPasskey = false,
        has2FA = false
    }: {
        hasPasskey?: boolean;
        has2FA?: boolean;
    } = $props();

    let isAuthenticating = $state(false);
    let errorMessage: string | null = $state(null);
    let show2FAInput = $state(false);
    let tfaCode = $state('');
    let isPasskeyLoading = $state(false);

    // Determine which auth method to use
    let authMethod = $derived(hasPasskey ? 'passkey' : (has2FA ? '2fa' : null));

    onMount(() => {
        // Auto-start passkey authentication if available
        if (hasPasskey) {
            handlePasskeyAuth();
        } else if (has2FA) {
            show2FAInput = true;
        }
    });

    async function handlePasskeyAuth() {
        if (!hasPasskey || isAuthenticating) {
            return;
        }

        isPasskeyLoading = true;
        isAuthenticating = true;
        errorMessage = null;

        try {
            // Get user email for passkey authentication
            const email = await cryptoService.getEmailDecryptedWithMasterKey();
            if (!email) {
                throw new Error('Email not available');
            }

            // Hash email for lookup
            const emailHash = await cryptoService.hashEmail(email);

            // Initiate passkey assertion
            const initiateResponse = await fetch(getApiEndpoint(apiEndpoints.auth.passkey_assertion_initiate), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    hashed_email: emailHash,
                    session_id: getSessionId()
                })
            });

            if (!initiateResponse.ok) {
                throw new Error('Failed to initiate passkey authentication');
            }

            const initiateData = await initiateResponse.json();
            if (!initiateData.success) {
                throw new Error(initiateData.message || 'Passkey authentication failed');
            }

            // Helper function to convert base64url to ArrayBuffer
            // This handles the base64url encoding used by WebAuthn
            function base64UrlToArrayBuffer(base64url: string): ArrayBuffer {
                let base64 = base64url.replace(/-/g, '+').replace(/_/g, '/');
                // Add padding if needed
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

            // Validate required fields from response
            if (!initiateData.challenge || !initiateData.rp?.id) {
                throw new Error('Invalid passkey challenge response');
            }

            // Construct PublicKeyCredentialRequestOptions from response fields
            // The backend returns individual fields (challenge, rp, timeout, allowCredentials, etc.)
            // that need to be assembled into the WebAuthn request options format
            const challenge = base64UrlToArrayBuffer(initiateData.challenge);

            // Prepare PRF extension input if available
            // Use the PRF eval.first from backend if provided, otherwise use challenge as fallback
            const prfEvalFirst = initiateData.extensions?.prf?.eval?.first || initiateData.challenge;
            const prfEvalFirstBuffer = base64UrlToArrayBuffer(prfEvalFirst);

            // Build the public key credential request options
            // Following the same pattern as Login.svelte for consistency
            const publicKeyCredentialRequestOptions: PublicKeyCredentialRequestOptions = {
                challenge: challenge,
                rpId: initiateData.rp.id,
                timeout: initiateData.timeout,
                userVerification: initiateData.userVerification as UserVerificationRequirement,
                allowCredentials: initiateData.allowCredentials?.length > 0
                    ? initiateData.allowCredentials.map((cred: any) => ({
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
                } as AuthenticationExtensionsClientInputs
            };

            // Request passkey authentication using WebAuthn API
            const credential = await navigator.credentials.get({
                publicKey: publicKeyCredentialRequestOptions
            }) as PublicKeyCredential;

            if (!credential) {
                throw new Error('Passkey authentication cancelled');
            }

            // Extract response data
            const response = credential.response as AuthenticatorAssertionResponse;
            const clientDataJSON = new Uint8Array(response.clientDataJSON);
            const authenticatorData = new Uint8Array(response.authenticatorData);
            const signature = new Uint8Array(response.signature);
            const userHandle = response.userHandle ? new Uint8Array(response.userHandle) : null;

            // Convert to base64
            const uint8ArrayToBase64 = (arr: Uint8Array) => {
                return btoa(String.fromCharCode(...arr))
                    .replace(/\+/g, '-')
                    .replace(/\//g, '_')
                    .replace(/=/g, '');
            };

            const credentialId = uint8ArrayToBase64(new Uint8Array(credential.rawId));
            const clientDataJSONB64 = uint8ArrayToBase64(clientDataJSON);
            const authenticatorDataB64 = uint8ArrayToBase64(authenticatorData);
            const signatureB64 = uint8ArrayToBase64(signature);
            const userHandleB64 = userHandle ? uint8ArrayToBase64(userHandle) : null;

            // Verify passkey assertion
            const verifyResponse = await fetch(getApiEndpoint(apiEndpoints.auth.passkey_assertion_verify), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    credential_id: credentialId,
                    assertion_response: {
                        authenticatorData: authenticatorDataB64,
                        clientDataJSON: clientDataJSONB64,
                        signature: signatureB64,
                        userHandle: userHandleB64
                    },
                    client_data_json: clientDataJSONB64,
                    authenticator_data: authenticatorDataB64,
                    session_id: getSessionId()
                })
            });

            if (!verifyResponse.ok) {
                const errorData = await verifyResponse.json();
                throw new Error(errorData.message || 'Passkey verification failed');
            }

            const verifyData = await verifyResponse.json();
            if (!verifyData.success) {
                throw new Error(verifyData.message || 'Passkey verification failed');
            }

            // Authentication successful
            dispatch('authSuccess');
        } catch (error) {
            console.error('Passkey authentication error:', error);
            errorMessage = error instanceof Error ? error.message : 'Passkey authentication failed';
            if (error instanceof Error && error.message.includes('cancelled')) {
                // User cancelled - don't show error, just close
                dispatch('authCancel');
            }
        } finally {
            isPasskeyLoading = false;
            isAuthenticating = false;
        }
    }

    async function handle2FASubmit() {
        if (tfaCode.length !== 6 || isAuthenticating) {
            return;
        }

        isAuthenticating = true;
        errorMessage = null;

        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.verifyDevice2FA), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    tfa_code: tfaCode
                })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.message || '2FA verification failed');
            }

            const data = await response.json();
            if (!data.success) {
                throw new Error(data.message || 'Invalid 2FA code');
            }

            // Authentication successful
            dispatch('authSuccess');
        } catch (error) {
            console.error('2FA authentication error:', error);
            errorMessage = error instanceof Error ? error.message : '2FA verification failed';
            tfaCode = '';
        } finally {
            isAuthenticating = false;
        }
    }

    function handleCancel() {
        dispatch('authCancel');
    }

    function handle2FAInput(event: Event) {
        const input = event.target as HTMLInputElement;
        tfaCode = input.value.replace(/\D/g, '').slice(0, 6);
        input.value = tfaCode;
        errorMessage = null;

        // Auto-submit when 6 digits are entered
        if (tfaCode.length === 6) {
            handle2FASubmit();
        }
    }
</script>

<div class="auth-modal-overlay" onclick={handleCancel} onkeydown={(e) => e.key === 'Escape' && handleCancel()} role="dialog" aria-modal="true" aria-labelledby="auth-title">
    <div class="auth-modal" onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.stopPropagation()}>
        <div class="auth-header">
            <h3 id="auth-title">{$text('settings.billing.payment_auth_title')}</h3>
            <button class="close-btn" onclick={handleCancel} aria-label="Close">×</button>
        </div>

        <div class="auth-content">
            {#if isPasskeyLoading}
                <div class="auth-loading">
                    <p>{$text('settings.billing.passkey_authenticating')}</p>
                </div>
            {:else if show2FAInput}
                <div class="auth-2fa">
                    <p>{$text('settings.billing.enter_2fa_code')}</p>
                    <input
                        type="text"
                        inputmode="numeric"
                        pattern="[0-9]*"
                        maxlength="6"
                        value={tfaCode}
                        oninput={handle2FAInput}
                        placeholder="000000"
                        disabled={isAuthenticating}
                        class="tfa-input"
                    />
                    {#if errorMessage}
                        <p class="error-message">{errorMessage}</p>
                    {/if}
                </div>
            {:else if authMethod === 'passkey'}
                <div class="auth-passkey">
                    <p>{$text('settings.billing.passkey_prompt')}</p>
                    <button
                        class="auth-btn"
                        onclick={handlePasskeyAuth}
                        disabled={isAuthenticating}
                    >
                        {$text('settings.billing.authenticate_with_passkey')}
                    </button>
                </div>
            {/if}
        </div>
    </div>
</div>

<style>
    .auth-modal-overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 1000;
    }

    .auth-modal {
        background: var(--color-grey-10);
        border-radius: 12px;
        padding: 24px;
        max-width: 400px;
        width: 90%;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
    }

    .auth-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 20px;
    }

    .auth-header h3 {
        margin: 0;
        font-size: 18px;
        font-weight: 600;
    }

    .close-btn {
        background: none;
        border: none;
        font-size: 24px;
        cursor: pointer;
        color: var(--color-grey-60);
        padding: 0;
        width: 32px;
        height: 32px;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .close-btn:hover {
        color: var(--color-grey-80);
    }

    .auth-content {
        margin-top: 20px;
    }

    .auth-loading,
    .auth-2fa,
    .auth-passkey {
        text-align: center;
    }

    .auth-2fa p,
    .auth-passkey p {
        margin-bottom: 16px;
        color: var(--color-grey-70);
    }

    .tfa-input {
        width: 100%;
        padding: 12px;
        font-size: 24px;
        text-align: center;
        letter-spacing: 8px;
        border: 2px solid var(--color-grey-30);
        border-radius: 8px;
        background: var(--color-grey-10);
        color: var(--color-grey-80);
        font-family: monospace;
    }

    .tfa-input:focus {
        outline: none;
        border-color: var(--color-primary);
    }

    .error-message {
        color: var(--color-danger);
        font-size: 13px;
        margin-top: 8px;
    }

    .auth-btn {
        width: 100%;
        padding: 12px 24px;
        background: var(--color-primary);
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.2s;
    }

    .auth-btn:hover:not(:disabled) {
        background: var(--color-primary-dark);
    }

    .auth-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
</style>
