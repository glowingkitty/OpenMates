<script lang="ts">
    /**
     * PasskeyLogin Component
     * 
     * Handles passkey authentication (login) flow:
     * 1. Initiates assertion with backend
     * 2. Performs WebAuthn assertion (get credentials)
     * 3. Checks for PRF extension support
     * 4. Derives wrapping key from PRF signature
     * 5. Unwraps master key and completes login
     * 
     * Supports both:
     * - Manual button click (explicit passkey login)
     * - Browser auto-detection (conditional UI)
     */
    import { text } from '@repo/ui';
    import { fade } from 'svelte/transition';
    import { createEventDispatcher } from 'svelte';
    import { getApiEndpoint, apiEndpoints } from '../config/api';
    import * as cryptoService from '../services/cryptoService';
    import { onMount } from 'svelte';
    
    const dispatch = createEventDispatcher();
    
    // Props using Svelte 5 runes
    let {
        email = '',
        hashedEmail = '',
        stayLoggedIn = false,
        autoTrigger = false // If true, automatically attempt passkey login on mount
    }: {
        email?: string;
        hashedEmail?: string;
        stayLoggedIn?: boolean;
        autoTrigger?: boolean;
    } = $props();
    
    let isLoading = $state(false);
    let errorMessage = $state<string | null>(null);
    
    /**
     * Converts ArrayBuffer to base64url (WebAuthn format)
     */
    function arrayBufferToBase64Url(buffer: ArrayBuffer): string {
        const bytes = new Uint8Array(buffer);
        let binary = '';
        for (let i = 0; i < bytes.byteLength; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return window.btoa(binary)
            .replace(/\+/g, '-')
            .replace(/\//g, '_')
            .replace(/=/g, '');
    }
    
    /**
     * Converts base64url to ArrayBuffer (WebAuthn format)
     */
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
    
    /**
     * Handle passkey login - can be triggered manually or automatically
     * Supports passwordless login without email (resident/discoverable credentials)
     */
    async function handlePasskeyLogin() {
        if (isLoading) return;
        
        try {
            isLoading = true;
            errorMessage = null;
            
            // Step 1: Initiate passkey assertion with backend
            // For resident credentials, we don't need email - the authenticator will provide user ID
            // If email is provided, we can use it for optimization, but it's not required
            const requestBody: any = {};
            
            if (email) {
                // Generate hashed email if provided (for optimization/non-resident credentials)
                const hashed_email = hashedEmail || await cryptoService.hashEmail(email);
                requestBody.hashed_email = hashed_email;
            }
            // If no email, backend will rely on resident credentials to identify user
            
            const initiateResponse = await fetch(getApiEndpoint(apiEndpoints.auth.passkey_assertion_initiate), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(requestBody),
                credentials: 'include'
            });
            
            if (!initiateResponse.ok) {
                const errorData = await initiateResponse.json();
                console.error('Passkey assertion initiation failed:', errorData);
                errorMessage = errorData.message || 'Failed to initiate passkey login';
                isLoading = false;
                return;
            }
            
            const initiateData = await initiateResponse.json();
            
            if (!initiateData.success) {
                console.error('Passkey assertion initiation failed:', initiateData.message);
                errorMessage = initiateData.message || 'Failed to initiate passkey login';
                isLoading = false;
                return;
            }
            
            // Step 2: Prepare WebAuthn request options
            const challenge = base64UrlToArrayBuffer(initiateData.challenge);
            
            // Prepare PRF extension input
            // Use the PRF eval.first from backend if provided, otherwise use challenge as fallback
            const prfEvalFirst = initiateData.extensions?.prf?.eval?.first || initiateData.challenge;
            const prfEvalFirstBuffer = base64UrlToArrayBuffer(prfEvalFirst);
            console.log('[PasskeyLogin] PRF extension request:', {
                hasPrfExtension: !!initiateData.extensions?.prf,
                prfEvalFirst: prfEvalFirst.substring(0, 20) + '...',
                usingFallback: !initiateData.extensions?.prf?.eval?.first,
                challenge: initiateData.challenge.substring(0, 20) + '...'
            });
            
            // For resident/discoverable credentials, allowCredentials should be empty
            // This allows the authenticator to find the right credential automatically
            const publicKeyCredentialRequestOptions: PublicKeyCredentialRequestOptions = {
                challenge: challenge,
                rpId: initiateData.rp.id,
                timeout: initiateData.timeout,
                userVerification: initiateData.userVerification as UserVerificationRequirement,
                // Empty allowCredentials array enables resident credential discovery
                // If backend provides specific credentials, use them; otherwise discover all
                allowCredentials: initiateData.allowCredentials?.length > 0 
                    ? initiateData.allowCredentials.map((cred: any) => ({
                        type: cred.type,
                        id: base64UrlToArrayBuffer(cred.id),
                        transports: cred.transports
                    }))
                    : [], // Empty array = discover all resident credentials
                extensions: {
                    prf: {
                        eval: {
                            first: prfEvalFirstBuffer
                        }
                    }
                } as AuthenticationExtensionsClientInputs
            };
            
            console.log('[PasskeyLogin] WebAuthn request options prepared:', {
                rpId: publicKeyCredentialRequestOptions.rpId,
                hasExtensions: !!publicKeyCredentialRequestOptions.extensions,
                hasPrfExtension: !!(publicKeyCredentialRequestOptions.extensions as any)?.prf,
                allowCredentialsCount: publicKeyCredentialRequestOptions.allowCredentials?.length || 0
            });
            
            // Step 3: Get passkey assertion using WebAuthn API
            let assertion: PublicKeyCredential;
            try {
                assertion = await navigator.credentials.get({
                    publicKey: publicKeyCredentialRequestOptions
                }) as PublicKeyCredential;
            } catch (error: any) {
                console.error('WebAuthn assertion failed:', error);
                // User cancellation or other errors
                if (error.name === 'NotAllowedError') {
                    errorMessage = 'Passkey login cancelled';
                } else {
                    errorMessage = 'Passkey login failed. Please try again.';
                }
                isLoading = false;
                return;
            }
            
            if (!assertion || !(assertion instanceof PublicKeyCredential)) {
                console.error('Invalid assertion received');
                errorMessage = 'Invalid passkey response';
                isLoading = false;
                return;
            }
            
            const response = assertion.response as AuthenticatorAssertionResponse;
            
            // Step 4: Check PRF extension support
            const clientExtensionResults = assertion.getClientExtensionResults();
            console.log('[PasskeyLogin] Client extension results:', clientExtensionResults);
            const prfResults = clientExtensionResults?.prf as any;
            console.log('[PasskeyLogin] PRF results:', prfResults);
            
            // Check if PRF is enabled and has results
            // Note: Some authenticators may return PRF results even if enabled is false/undefined
            // We need to check both enabled flag and presence of results
            if (!prfResults) {
                console.error('[PasskeyLogin] PRF extension not found in client extension results', {
                    clientExtensionResults,
                    hasPrf: !!clientExtensionResults?.prf
                });
                errorMessage = 'Your passkey does not support the required security features. Please use password login instead.';
                isLoading = false;
                return;
            }
            
            // Check if PRF is enabled (some browsers may not set this flag correctly)
            if (prfResults.enabled === false) {
                console.error('[PasskeyLogin] PRF extension explicitly disabled', {
                    prfResults,
                    enabled: prfResults.enabled
                });
                errorMessage = 'Your passkey does not support the required security features. Please use password login instead.';
                isLoading = false;
                return;
            }
            
            // Extract PRF signature - handle both ArrayBuffer and hex string formats
            const prfSignatureBuffer = prfResults.results?.first;
            if (!prfSignatureBuffer) {
                console.error('[PasskeyLogin] PRF signature not found in results', {
                    prfResults,
                    hasResults: !!prfResults.results,
                    resultsKeys: prfResults.results ? Object.keys(prfResults.results) : []
                });
                errorMessage = 'Passkey authentication failed. Please try again.';
                isLoading = false;
                return;
            }
            
            // Convert PRF signature to Uint8Array
            // Handle both ArrayBuffer and hex string formats
            let prfSignature: Uint8Array;
            if (typeof prfSignatureBuffer === 'string') {
                // Hex string format (e.g., "65caf64f0349e41168307bc91df7157fb8e22c8b59f96d445c716731fa6445bb")
                console.log('[PasskeyLogin] PRF signature is hex string, converting to Uint8Array');
                const hexString = prfSignatureBuffer;
                prfSignature = new Uint8Array(hexString.match(/.{1,2}/g)!.map(byte => parseInt(byte, 16)));
            } else if (prfSignatureBuffer instanceof ArrayBuffer) {
                // ArrayBuffer format
                console.log('[PasskeyLogin] PRF signature is ArrayBuffer, converting to Uint8Array');
                prfSignature = new Uint8Array(prfSignatureBuffer);
            } else if (ArrayBuffer.isView(prfSignatureBuffer)) {
                // TypedArray format (Uint8Array, etc.)
                console.log('[PasskeyLogin] PRF signature is TypedArray, converting to Uint8Array');
                prfSignature = new Uint8Array(prfSignatureBuffer.buffer, prfSignatureBuffer.byteOffset, prfSignatureBuffer.byteLength);
            } else {
                console.error('[PasskeyLogin] PRF signature is in unknown format', {
                    type: typeof prfSignatureBuffer,
                    constructor: prfSignatureBuffer?.constructor?.name,
                    value: prfSignatureBuffer
                });
                errorMessage = 'Passkey authentication failed. Please try again.';
                isLoading = false;
                return;
            }
            
            // Validate PRF signature length (should be 32 bytes for SHA-256)
            if (prfSignature.length < 16 || prfSignature.length > 64) {
                console.error('[PasskeyLogin] PRF signature has invalid length', {
                    length: prfSignature.length,
                    expected: '16-64 bytes'
                });
                errorMessage = 'Passkey authentication failed. Please try again.';
                isLoading = false;
                return;
            }
            
            console.log('[PasskeyLogin] PRF signature extracted successfully', {
                length: prfSignature.length,
                firstBytes: Array.from(prfSignature.slice(0, 4))
            });
            
            // Step 5: Extract credential data for backend
            const credentialId = arrayBufferToBase64Url(assertion.rawId);
            const clientDataJSONB64 = cryptoService.uint8ArrayToBase64(new Uint8Array(response.clientDataJSON));
            const authenticatorDataB64 = cryptoService.uint8ArrayToBase64(new Uint8Array(response.authenticatorData));
            
            // Step 6: Verify passkey assertion with backend
            // For resident credentials, backend will identify user from credential_id
            const verifyResponse = await fetch(getApiEndpoint(apiEndpoints.auth.passkey_assertion_verify), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    credential_id: credentialId,
                    assertion_response: {
                        authenticatorData: authenticatorDataB64,
                        clientDataJSON: clientDataJSONB64,
                        signature: cryptoService.uint8ArrayToBase64(new Uint8Array(response.signature)),
                        userHandle: response.userHandle ? cryptoService.uint8ArrayToBase64(new Uint8Array(response.userHandle)) : null
                    },
                    client_data_json: clientDataJSONB64,
                    authenticator_data: authenticatorDataB64,
                    // hashed_email is optional for resident credentials
                    ...(email ? { hashed_email: await cryptoService.hashEmail(email) } : {}),
                    stay_logged_in: stayLoggedIn,
                    session_id: getSessionId()
                }),
                credentials: 'include'
            });
            
            if (!verifyResponse.ok) {
                const errorData = await verifyResponse.json();
                console.error('Passkey assertion verification failed:', errorData);
                errorMessage = errorData.message || 'Passkey verification failed';
                isLoading = false;
                return;
            }
            
            const verifyData = await verifyResponse.json();
            
            if (!verifyData.success) {
                console.error('Passkey verification failed:', verifyData.message);
                errorMessage = verifyData.message || 'Passkey verification failed';
                isLoading = false;
                return;
            }
            
            // Step 7: Get user email from backend response (for resident credentials)
            let userEmail = email; // Use provided email if available
            if (!userEmail && verifyData.user_email) {
                userEmail = verifyData.user_email;
            }
            
            // Step 8: Get email salt for key derivation
            // For resident credentials, we get salt from backend response
            let emailSalt = cryptoService.getEmailSalt();
            
            // If salt not found locally, get it from backend response
            if (!emailSalt && verifyData.user_email_salt) {
                const { base64ToUint8Array } = await import('../services/cryptoService');
                emailSalt = base64ToUint8Array(verifyData.user_email_salt);
                // Store it for future use
                cryptoService.saveEmailSalt(emailSalt, stayLoggedIn);
            }
            
            if (!emailSalt) {
                console.error('Email salt not found');
                errorMessage = 'Authentication data not found. Please try logging in again.';
                isLoading = false;
                return;
            }
            
            // Step 9: Derive wrapping key from PRF signature using HKDF
            const wrappingKey = await cryptoService.deriveWrappingKeyFromPRF(prfSignature, emailSalt);
            
            // Step 10: Generate lookup hash from PRF signature (for authentication)
            const lookupHash = await cryptoService.hashKeyFromPRF(prfSignature, emailSalt);
            console.log('[PasskeyLogin] Lookup hash derived from PRF signature');
            
            // Step 11: Unwrap master key using PRF-derived wrapping key
            const encryptedMasterKey = verifyData.encrypted_master_key;
            const keyIv = verifyData.key_iv;
            
            if (!encryptedMasterKey || !keyIv) {
                console.error('Missing encrypted master key or IV');
                errorMessage = 'Failed to retrieve encryption keys';
                isLoading = false;
                return;
            }
            
            const masterKey = await cryptoService.decryptKey(encryptedMasterKey, keyIv, wrappingKey);
            
            if (!masterKey) {
                console.error('Failed to unwrap master key');
                errorMessage = 'Failed to decrypt account data';
                isLoading = false;
                return;
            }
            
            // Step 12: Save master key to IndexedDB
            // Pass stayLoggedIn to ensure key is cleared on tab/browser close if user didn't check "Stay logged in"
            await cryptoService.saveKeyToSession(masterKey, stayLoggedIn);
            
            // Step 13: Decrypt email using master key (for passwordless login)
            // The server returns encrypted_email encrypted with master key (encrypted_email_with_master_key)
            if (!userEmail && verifyData.encrypted_email) {
                // Decrypt email using master key (master key is already saved to storage at step 12)
                const { decryptWithMasterKey } = await import('../services/cryptoService');
                const decryptedEmail = await decryptWithMasterKey(verifyData.encrypted_email);
                if (decryptedEmail) {
                    userEmail = decryptedEmail;
                    console.log('[PasskeyLogin] Email decrypted from encrypted_email using master key');
                } else {
                    console.error('[PasskeyLogin] Failed to decrypt email with master key');
                    errorMessage = 'Failed to decrypt email. Please try again.';
                    isLoading = false;
                    return;
                }
            }
            
            // If still no email, we need it for key derivation
            if (!userEmail) {
                console.error('Email not available for key derivation');
                errorMessage = 'Unable to retrieve user email. Please try again.';
                isLoading = false;
                return;
            }
            
            // Step 14: Derive email encryption key
            const emailEncryptionKey = await cryptoService.deriveEmailEncryptionKey(userEmail, emailSalt);
            
            // Step 15: Store email encryption key and salt
            cryptoService.saveEmailEncryptionKey(emailEncryptionKey, stayLoggedIn);
            cryptoService.saveEmailSalt(emailSalt, stayLoggedIn);
            
            // Step 16: Store email with master key
            await cryptoService.saveEmailEncryptedWithMasterKey(userEmail, stayLoggedIn);
            
            // Step 17: Authenticate with backend using lookup_hash
            // If auth_session was not provided in verify response, we need to authenticate
            if (!verifyData.auth_session) {
                console.log('[PasskeyLogin] No auth_session in verify response, authenticating with lookup_hash');
                
                // Get hashed_email for authentication
                const hashedEmail = await cryptoService.hashEmail(userEmail);
                
                // Authenticate using the regular login endpoint with lookup_hash
                const authResponse = await fetch(getApiEndpoint(apiEndpoints.auth.login), {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        hashed_email: hashedEmail,
                        lookup_hash: lookupHash,
                        email_encryption_key: cryptoService.getEmailEncryptionKeyForApi(),
                        login_method: 'passkey',
                        stay_logged_in: stayLoggedIn,
                        session_id: getSessionId()
                    }),
                    credentials: 'include'
                });
                
                if (!authResponse.ok) {
                    const errorData = await authResponse.json();
                    console.error('Passkey authentication failed:', errorData);
                    errorMessage = errorData.message || 'Authentication failed. Please try again.';
                    isLoading = false;
                    return;
                }
                
                const authData = await authResponse.json();
                
                if (!authData.success) {
                    console.error('Passkey authentication failed:', authData.message);
                    errorMessage = authData.message || 'Authentication failed. Please try again.';
                    isLoading = false;
                    return;
                }
                
                // Use auth data from login endpoint
                verifyData.auth_session = authData.auth_session;
                console.log('[PasskeyLogin] Authentication successful via login endpoint');
            }
            
            // Step 18: Store WebSocket token if provided
            if (verifyData.auth_session?.ws_token) {
                const { setWebSocketToken } = await import('../utils/cookies');
                setWebSocketToken(verifyData.auth_session.ws_token);
                console.debug('[PasskeyLogin] WebSocket token stored from login response');
            }
            
            // Step 19: Update user profile if user data is available
            if (verifyData.auth_session?.user) {
                const { updateProfile } = await import('../stores/userProfile');
                const userProfileData = {
                    username: verifyData.auth_session.user.username || '',
                    profile_image_url: verifyData.auth_session.user.profile_image_url || null,
                    credits: verifyData.auth_session.user.credits || 0,
                    is_admin: verifyData.auth_session.user.is_admin || false,
                    last_opened: verifyData.auth_session.user.last_opened || '',
                    tfa_app_name: verifyData.auth_session.user.tfa_app_name || null,
                    tfa_enabled: verifyData.auth_session.user.tfa_enabled || false,
                    consent_privacy_and_apps_default_settings: verifyData.auth_session.user.consent_privacy_and_apps_default_settings || false,
                    consent_mates_default_settings: verifyData.auth_session.user.consent_mates_default_settings || false,
                    language: verifyData.auth_session.user.language || 'en',
                    darkmode: verifyData.auth_session.user.darkmode || false
                };
                updateProfile(userProfileData);
                console.debug('[PasskeyLogin] User profile updated with login data');
            }
            
            // Step 20: Check if user is in signup flow
            // Import isSignupPath helper for checking signup paths
            const { isSignupPath } = await import('../stores/signupState');
            const inSignupFlow = isSignupPath(verifyData.auth_session?.user?.last_opened) || 
                                (verifyData.auth_session?.user?.tfa_enabled === false);
            
            // Step 21: Dispatch login success
            dispatch('loginSuccess', {
                user: verifyData.auth_session?.user,
                inSignupFlow: inSignupFlow
            });
            
        } catch (error) {
            console.error('Error during passkey login:', error);
            errorMessage = 'An error occurred during passkey login. Please try again.';
            isLoading = false;
        }
    }
    
    /**
     * Get session ID for device fingerprinting
     */
    function getSessionId(): string {
        // Get or create session ID from sessionStorage
        let sessionId = sessionStorage.getItem('openmates_session_id');
        if (!sessionId) {
            sessionId = crypto.randomUUID();
            sessionStorage.setItem('openmates_session_id', sessionId);
        }
        return sessionId;
    }
    
    // Auto-trigger passkey login if requested (for browser auto-detection)
    $effect(() => {
        if (autoTrigger && email && !isLoading && !errorMessage) {
            handlePasskeyLogin();
        }
    });
</script>

<div class="passkey-login" in:fade={{ duration: 300 }}>
    {#if errorMessage}
        <div class="error-message" in:fade={{ duration: 200 }}>
            {errorMessage}
        </div>
    {/if}
    
    <button
        type="button"
        class="passkey-button"
        disabled={isLoading || !email}
        onclick={handlePasskeyLogin}
    >
        {#if isLoading}
            <span class="loading-spinner"></span>
            <span>{$text('login.loading.text')}</span>
        {:else}
            <span class="clickable-icon icon_secret" style="width: 20px; height: 20px; margin-right: 8px;"></span>
            <span>{$text('login.login_with_passkey.text')}</span>
        {/if}
    </button>
</div>

<style>
    .passkey-login {
        display: flex;
        flex-direction: column;
        width: 100%;
        gap: 12px;
    }
    
    .error-message {
        color: var(--color-error);
        font-size: 14px;
        padding: 12px;
        background-color: var(--color-error-light);
        border-radius: 8px;
        text-align: center;
    }
    
    .passkey-button {
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 12px 24px;
        background: var(--color-primary);
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 16px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.2s ease;
        width: 100%;
        max-width: 400px;
        margin: 0 auto;
    }
    
    .passkey-button:hover:not(:disabled) {
        background: var(--color-primary-dark);
    }
    
    .passkey-button:disabled {
        cursor: not-allowed;
        opacity: 0.6;
    }
    
    .loading-spinner {
        border: 3px solid rgba(255, 255, 255, 0.3);
        border-radius: 50%;
        border-top: 3px solid white;
        width: 18px;
        height: 18px;
        animation: spin 1s linear infinite;
        margin-right: 8px;
    }
    
    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
</style>

