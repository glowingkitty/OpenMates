<!--
SecurityAuth - Shared component for security-sensitive operations requiring authentication
Used for: password change, account deletion, payment confirmation, etc.
Supports: passkey authentication, password authentication, 2FA verification

Svelte 5: Uses callback props instead of event dispatcher for parent communication.
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { getApiEndpoint, apiEndpoints } from '../../../config/api';
    import * as cryptoService from '../../../services/cryptoService';
    import SettingsInput from '../elements/SettingsInput.svelte';
    import { getSessionId } from '../../../utils/sessionId';
    import { focusTrap } from '../../../actions/focusTrap';

    // ========================================================================
    // PROPS
    // ========================================================================
    
    /** Auth result data passed to onSuccess callback */
    type AuthSuccessData = { 
        method: 'passkey' | 'password' | '2fa' | 'email_otp'; 
        credentialId?: string;  // For passkey authentication
        tfaCode?: string;       // For 2FA / email OTP authentication
    };
    
    let { 
        hasPasskey = false,
        hasPassword = false,
        has2FA = false,
        hasEmailOtp = false,
        verificationAction = '',
        title = '',
        description = '',
        autoStart = true, // Auto-start passkey auth if available
        // Callback props for Svelte 5 (replaces event dispatcher)
        onSuccess,
        onFailed,
        onCancel
    }: {
        hasPasskey?: boolean;
        hasPassword?: boolean;
        has2FA?: boolean;
        hasEmailOtp?: boolean;
        verificationAction?: string;
        title?: string;
        description?: string;
        autoStart?: boolean;
        /** Called when authentication succeeds - REQUIRED */
        onSuccess: (data: AuthSuccessData) => void;
        /** Called when authentication fails - REQUIRED */
        onFailed: (message: string) => void;
        /** Called when user cancels authentication - REQUIRED */
        onCancel: () => void;
    } = $props();

    // ========================================================================
    // STATE
    // ========================================================================
    
    let isAuthenticating = $state(false);
    let errorMessage = $state<string | null>(null);
    
    // Password auth state
    let showPasswordInput = $state(false);
    let password = $state('');
    let isPasswordLoading = $state(false);
    
    // 2FA state
    let show2FAInput = $state(false);
    let tfaCode = $state('');
    
    // Passkey state
    let isPasskeyLoading = $state(false);
    
    // Email OTP state
    let showEmailOtpInput = $state(false);
    let emailOtpCode = $state('');
    let emailOtpSent = $state(false);
    let isEmailOtpSending = $state(false);
    let isEmailOtpVerifying = $state(false);

    // ========================================================================
    // COMPUTED
    // ========================================================================
    
    // Determine which auth method to use (passkey takes priority)
    let authMethod = $derived(hasPasskey ? 'passkey' : (hasPassword ? 'password' : (has2FA ? '2fa' : (hasEmailOtp ? 'email_otp' : null))));
    
    // Compute the default title if not provided
    let displayTitle = $derived(title || $text('settings.security.auth_title'));
    
    // Compute the default description if not provided
    let displayDescription = $derived(description || $text('settings.security.auth_description'));

    // ========================================================================
    // LIFECYCLE
    // ========================================================================
    
    onMount(() => {
        // Auto-start passkey authentication if available and autoStart is true
        if (autoStart && hasPasskey) {
            handlePasskeyAuth();
        } else if (hasPassword) {
            showPasswordInput = true;
        } else if (has2FA) {
            show2FAInput = true;
        } else if (hasEmailOtp) {
            showEmailOtpInput = true;
        }
    });

    // ========================================================================
    // PASSKEY AUTHENTICATION
    // ========================================================================
    
    /**
     * Handle passkey authentication using WebAuthn API.
     * This verifies the user's identity via their registered passkey.
     */
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

            // Validate required fields from response
            if (!initiateData.challenge || !initiateData.rp?.id) {
                throw new Error('Invalid passkey challenge response');
            }

            // Construct PublicKeyCredentialRequestOptions
            const challenge = base64UrlToArrayBuffer(initiateData.challenge);
            const prfEvalFirst = initiateData.extensions?.prf?.eval?.first || initiateData.challenge;
            const prfEvalFirstBuffer = base64UrlToArrayBuffer(prfEvalFirst);

            // Build credential request options for WebAuthn
            // Using object literal with explicit type to avoid global WebAuthn type issues
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

            // Convert to base64url
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
            console.log('[SecurityAuth] Passkey authentication successful');
            onSuccess({ method: 'passkey', credentialId });
        } catch (error) {
            console.error('[SecurityAuth] Passkey authentication error:', error);
            const errMsg = error instanceof Error ? error.message : 'Passkey authentication failed';
            errorMessage = errMsg;
            if (error instanceof Error && error.message.includes('cancelled')) {
                // User cancelled - call cancel callback
                onCancel();
            } else {
                // Authentication failed - call failed callback
                onFailed(errMsg);
            }
        } finally {
            isPasskeyLoading = false;
            isAuthenticating = false;
        }
    }

    // ========================================================================
    // PASSWORD AUTHENTICATION
    // ========================================================================
    
    /**
     * Handle password authentication.
     * Verifies the password by attempting to derive the master key.
     */
    async function handlePasswordAuth() {
        if (!password.trim() || isAuthenticating) {
            return;
        }

        isPasswordLoading = true;
        isAuthenticating = true;
        errorMessage = null;

        try {
            // Get user email and salt for password verification
            const email = await cryptoService.getEmailDecryptedWithMasterKey();
            if (!email) {
                throw new Error('Email not available');
            }

            const emailSalt = cryptoService.getEmailSalt();
            if (!emailSalt) {
                throw new Error('Email salt not available');
            }

            // Hash email for lookup
            const hashedEmail = await cryptoService.hashEmail(email);

            // Generate lookup hash from password (same as during login)
            const lookupHash = await cryptoService.hashKey(password, emailSalt);

            // Verify password by calling the login endpoint
            // This validates that the lookup_hash matches
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.login), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    hashed_email: hashedEmail,
                    lookup_hash: lookupHash,
                    session_id: getSessionId(),
                    login_method: 'password'
                })
            });

            const data = await response.json();

            if (!data.success) {
                throw new Error(data.message || 'Invalid password');
            }

            // Check if 2FA is required
            if (data.tfa_required && has2FA) {
                // Show 2FA input
                showPasswordInput = false;
                show2FAInput = true;
                isPasswordLoading = false;
                isAuthenticating = false;
                return;
            }

            // Password authentication successful
            console.log('[SecurityAuth] Password authentication successful');
            onSuccess({ method: 'password' });
        } catch (error) {
            console.error('[SecurityAuth] Password authentication error:', error);
            const errMsg = error instanceof Error ? error.message : 'Password verification failed';
            errorMessage = errMsg;
            password = ''; // Clear password on error
            onFailed(errMsg);
        } finally {
            isPasswordLoading = false;
            isAuthenticating = false;
        }
    }

    // ========================================================================
    // 2FA AUTHENTICATION
    // ========================================================================
    
    /**
     * Handle 2FA code submission.
     */
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

            // Authentication successful - pass the OTP code for downstream verification
            console.log('[SecurityAuth] 2FA authentication successful');
            onSuccess({ method: '2fa', tfaCode });
        } catch (error) {
            console.error('[SecurityAuth] 2FA authentication error:', error);
            const errMsg = error instanceof Error ? error.message : '2FA verification failed';
            errorMessage = errMsg;
            tfaCode = '';
            onFailed(errMsg);
        } finally {
            isAuthenticating = false;
        }
    }

    // ========================================================================
    // EVENT HANDLERS
    // ========================================================================
    
    /**
     * Handle cancel button click.
     */
    function handleCancel() {
        onCancel();
    }

    /**
     * Handle 2FA input changes.
     */
    function handle2FAInput(rawValue: string) {
        tfaCode = rawValue.replace(/\D/g, '').slice(0, 6);
        errorMessage = null;

        // Auto-submit when 6 digits are entered
        if (tfaCode.length === 6) {
            handle2FASubmit();
        }
    }

    /**
     * Handle password input key press.
     */
    function handlePasswordKeydown(event: KeyboardEvent) {
        if (event.key === 'Enter') {
            handlePasswordAuth();
        }
    }

    /**
     * Switch to alternative auth method (for passkey users who want to use password).
     */
    function switchToPassword() {
        isPasskeyLoading = false;
        showPasswordInput = true;
        errorMessage = null;
    }

    /**
     * Switch to passkey auth.
     */
    function switchToPasskey() {
        showPasswordInput = false;
        errorMessage = null;
        handlePasskeyAuth();
    }

    /**
     * Send email OTP for action verification.
     * Calls POST /v1/settings/request-action-verification with the action type.
     */
    async function handleSendEmailOtp() {
        isEmailOtpSending = true;
        errorMessage = null;
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.settings.requestActionVerification), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ action: verificationAction })
            });
            const data = await response.json();
            if (response.ok && data.success) {
                emailOtpSent = true;
            } else {
                errorMessage = data.message || data.detail || 'Failed to send verification code';
            }
        } catch {
            errorMessage = 'Network error. Please try again.';
        } finally {
            isEmailOtpSending = false;
        }
    }

    /**
     * Handle email OTP code input with auto-submit when 6 digits entered.
     * Calls POST /v1/settings/verify-action-code to verify the code.
     */
    function handleEmailOtpInput(rawValue: string) {
        const cleaned = rawValue.replace(/\D/g, '').slice(0, 6);
        emailOtpCode = cleaned;

        if (cleaned.length === 6) {
            verifyEmailOtp(cleaned);
        }
    }

    /**
     * Verify the entered email OTP code against the backend.
     * On success, dispatches onSuccess with method 'email_otp'.
     */
    async function verifyEmailOtp(code: string) {
        isEmailOtpVerifying = true;
        errorMessage = null;
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.settings.verifyActionCode), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ action: verificationAction, code })
            });
            const data = await response.json();
            if (response.ok && data.success) {
                onSuccess({ method: 'email_otp' });
            } else {
                errorMessage = data.message || data.detail || 'Invalid code. Please try again.';
                emailOtpCode = '';
            }
        } catch {
            errorMessage = 'Network error. Please try again.';
            emailOtpCode = '';
        } finally {
            isEmailOtpVerifying = false;
        }
    }
</script>

<div
    class="auth-modal-overlay"
    data-testid="auth-modal"
    role="presentation"
    onmousedown={(e) => { if (e.target === e.currentTarget) handleCancel(); }}
>
    <div
        class="auth-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="auth-title"
        tabindex={-1}
        use:focusTrap={{ onEscape: handleCancel }}
    >
        <div class="auth-header">
            <h3 id="auth-title">{displayTitle}</h3>
            <button class="close-btn" onclick={handleCancel} aria-label="Close">×</button>
        </div>

        {#if displayDescription}
            <p class="auth-description">{displayDescription}</p>
        {/if}

        <div class="auth-content">
            {#if isPasskeyLoading}
                <!-- Passkey Loading State -->
                <div class="auth-loading">
                    <div class="loading-spinner"></div>
                    <p>{$text('settings.security.passkey_authenticating')}</p>
                </div>
            {:else if showPasswordInput}
                <!-- Password Input -->
                <div class="auth-password">
                    <p>{$text('settings.security.enter_password')}</p>
                    <SettingsInput
                        type="password"
                        bind:value={password}
                        placeholder={$text('common.password')}
                        disabled={isPasswordLoading}
                        onKeydown={handlePasswordKeydown}
                    />
                    {#if errorMessage}
                        <p class="error-message">{errorMessage}</p>
                    {/if}
                    <button
                        class="auth-btn"
                        data-testid="auth-btn"
                        onclick={handlePasswordAuth}
                        disabled={isPasswordLoading || !password.trim()}
                    >
                        {#if isPasswordLoading}
                            <span class="loading-spinner-small"></span>
                        {/if}
                        {$text('settings.security.verify_password')}
                    </button>
                    
                    {#if hasPasskey}
                        <button class="switch-method-btn" onclick={switchToPasskey}>
                            {$text('settings.security.use_passkey_instead')}
                        </button>
                    {/if}
                </div>
            {:else if show2FAInput}
                <!-- 2FA Input -->
                <div class="auth-2fa" data-testid="auth-2fa">
                    <p>{$text('settings.security.enter_2fa_code')}</p>
                    <SettingsInput
                        type="text"
                        inputmode="numeric"
                        pattern="[0-9]*"
                        maxlength={6}
                        bind:value={tfaCode}
                        placeholder="000000"
                        disabled={isAuthenticating}
                        dataTestid="tfa-input"
                        onInput={handle2FAInput}
                    />
                    {#if errorMessage}
                        <p class="error-message">{errorMessage}</p>
                    {/if}
                </div>
            {:else if authMethod === 'passkey'}
                <!-- Passkey Prompt (shown when autoStart is false or after error) -->
                <div class="auth-passkey">
                    <p>{$text('settings.security.passkey_prompt')}</p>
                    {#if errorMessage}
                        <p class="error-message">{errorMessage}</p>
                    {/if}
                    <button
                        class="auth-btn"
                        data-testid="auth-btn"
                        onclick={handlePasskeyAuth}
                        disabled={isAuthenticating}
                    >
                        {$text('settings.security.authenticate_with_passkey')}
                    </button>
                    
                    {#if hasPassword}
                        <button class="switch-method-btn" onclick={switchToPassword}>
                            {$text('settings.security.use_password_instead')}
                        </button>
                    {/if}
                </div>
            {:else if showEmailOtpInput}
                <!-- Email OTP Input -->
                <div class="auth-email-otp" data-testid="auth-email-otp">
                    {#if !emailOtpSent}
                        <p>{$text('settings.security.email_otp_description')}</p>
                        <button
                            class="auth-btn"
                            data-testid="auth-btn"
                            onclick={handleSendEmailOtp}
                            disabled={isEmailOtpSending}
                        >
                            {#if isEmailOtpSending}
                                <span class="loading-spinner-small"></span>
                            {/if}
                            {$text('settings.security.send_verification_code')}
                        </button>
                    {:else}
                        <p>{$text('settings.security.email_otp_enter_code')}</p>
                        <SettingsInput
                            type="text"
                            inputmode="numeric"
                            pattern="[0-9]*"
                            maxlength={6}
                            bind:value={emailOtpCode}
                            placeholder="000000"
                            disabled={isEmailOtpVerifying}
                            onInput={handleEmailOtpInput}
                        />
                        <button
                            class="switch-method-btn"
                            onclick={handleSendEmailOtp}
                            disabled={isEmailOtpSending}
                        >
                            {$text('settings.security.resend_code')}
                        </button>
                    {/if}
                    {#if errorMessage}
                        <p class="error-message">{errorMessage}</p>
                    {/if}
                </div>
            {:else}
                <!-- No auth method available -->
                <div class="no-auth">
                    <p class="error-message">{$text('settings.security.no_auth_method')}</p>
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
        background: var(--color-grey-20);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: var(--z-index-tooltip);
    }

    .auth-modal {
        background: var(--color-grey-20);
        border-radius: var(--radius-5);
        padding: var(--spacing-12);
        max-width: 400px;
        width: 90%;
    }

    .auth-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: var(--spacing-6);
    }

    .auth-header h3 {
        margin: 0;
        font-size: var(--font-size-h3-mobile);
        font-weight: 600;
        color: var(--color-grey-100);
    }

    .close-btn {
        background: none;
        border: none;
        font-size: var(--font-size-h2-mobile);
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

    .auth-description {
        color: var(--color-grey-60);
        font-size: var(--font-size-small);
        margin-bottom: var(--spacing-10);
        line-height: 1.5;
    }

    .auth-content {
        margin-top: var(--spacing-10);
    }

    .auth-loading,
    .auth-2fa,
    .auth-passkey,
    .auth-password,
    .auth-email-otp,
    .no-auth {
        text-align: center;
    }

    .auth-loading {
        padding: 20px 0;
    }

    .auth-2fa p,
    .auth-passkey p,
    .auth-password p,
    .auth-email-otp p {
        margin-bottom: var(--spacing-8);
        color: var(--color-grey-70);
    }

    .error-message {
        color: var(--color-danger);
        font-size: var(--font-size-xs);
        margin-top: var(--spacing-4);
        margin-bottom: var(--spacing-4);
    }

    .auth-btn {
        width: 100%;
        padding: var(--spacing-6) var(--spacing-12);
        background: var(--color-primary);
        color: white;
        border: none;
        border-radius: var(--radius-3);
        font-size: var(--font-size-small);
        font-weight: 600;
        cursor: pointer;
        transition: background var(--duration-normal);
        display: flex;
        align-items: center;
        justify-content: center;
        gap: var(--spacing-4);
    }

    .auth-btn:hover:not(:disabled) {
        background: var(--color-primary-dark);
    }

    .auth-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .switch-method-btn {
        margin-top: var(--spacing-8);
        background: none;
        border: none;
        color: var(--color-primary);
        font-size: var(--font-size-small);
        cursor: pointer;
        padding: var(--spacing-4) var(--spacing-8);
    }

    .switch-method-btn:hover {
        text-decoration: underline;
    }

    .loading-spinner {
        width: 40px;
        height: 40px;
        border: 3px solid var(--color-grey-30);
        border-top-color: var(--color-primary);
        border-radius: 50%;
        animation: spin 1s linear infinite;
        margin: 0 auto 16px;
    }

    .loading-spinner-small {
        width: 16px;
        height: 16px;
        border: 2px solid rgba(255, 255, 255, 0.3);
        border-top-color: white;
        border-radius: 50%;
        animation: spin 1s linear infinite;
    }

    @keyframes spin {
        to {
            transform: rotate(360deg);
        }
    }
</style>

