<script lang="ts">
    /**
     * Account Recovery Component
     * 
     * Handles the "Can't login to account?" flow where users who have lost
     * their password, passkey, AND recovery key can reset their account.
     * 
     * IMPORTANT: This is a LAST RESORT that permanently deletes all chats,
     * settings, memories, and embeds. Users should use "Login with recovery key"
     * if they have their recovery key.
     * 
     * Flow:
     * 1. Auto-send verification code (email already known from login)
     * 2. Enter verification code + Confirm data loss via Toggle
     * 3. Verify code with backend (get verification token)
     * 4. Select login method (password or passkey)
     * 5. Set up new credentials and complete reset:
     *    - Password: Set up new password (2FA config is preserved server-side)
     *    - Passkey: Register new passkey with PRF extension
     * 
     * The new login method creates a new master encryption key and wraps it
     * appropriately (password-derived key or PRF-derived key).
     */
    import { text } from '@repo/ui';
    import { createEventDispatcher, onMount } from 'svelte';
    import { fade, slide } from 'svelte/transition';
    import Toggle from './Toggle.svelte';
    import LoginMethodSelector from './LoginMethodSelector.svelte';
    import { getApiEndpoint, apiEndpoints } from '../config/api';
    import { notificationStore } from '../stores/notificationStore';
    import * as cryptoService from '../services/cryptoService';
    import { checkAuth } from '../stores/authStore';
    import { userDB } from '../services/userDB';
    import { generateDeviceName } from '../utils/deviceName';
    
    const dispatch = createEventDispatcher();
    
    // Props - email is passed from the login form
    let { email: initialEmail = '' }: { email?: string } = $props();
    
    // Step states - 'passkey' step added for passkey registration
    type RecoveryStep = 'code' | 'setup' | 'password' | 'passkey' | 'complete';
    let currentStep = $state<RecoveryStep>('code');
    
    // Form data
    let email = $state(initialEmail);
    let verificationCode = $state('');
    let acknowledgeDataLoss = $state(false);
    let verificationToken = $state(''); // Token from verify-code endpoint
    
    // Loading states
    let isRequestingCode = $state(false);
    let isVerifying = $state(false);
    let isSettingUp = $state(false);
    let isRegisteringPasskey = $state(false);
    
    // Error states
    let codeError = $state('');
    let passkeyError = $state('');
    
    // Auto-request the code when component mounts
    onMount(() => {
        if (email) {
            requestResetCode();
        }
    });
    
    // Derived state for button enablement
    let canVerifyCode = $derived(
        verificationCode.length === 6 && acknowledgeDataLoss && !isVerifying
    );
    
    // ============================================================================
    // Helper Functions for WebAuthn
    // ============================================================================
    
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
    
    // ============================================================================
    // Code Request and Verification
    // ============================================================================
    
    /**
     * Request reset code to be sent to email
     * Handles rate limiting (429) responses with clear user feedback
     */
    async function requestResetCode() {
        if (isRequestingCode || !email) return;
        
        isRequestingCode = true;
        
        try {
            // Get dark mode setting from localStorage or system preference
            const prefersDarkMode = window.matchMedia && 
                window.matchMedia('(prefers-color-scheme: dark)').matches;
            const darkModeEnabled = localStorage.getItem('darkMode') === 'true' || prefersDarkMode;
            
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.recovery_request), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    email: email,
                    language: document.documentElement.lang || 'en',
                    darkmode: darkModeEnabled
                }),
                credentials: 'include'
            });
            
            // Handle rate limiting (429 Too Many Requests)
            if (response.status === 429) {
                console.warn('Rate limited when requesting recovery code');
                notificationStore.error(
                    $text('login.too_many_requests.text'),
                    8000
                );
                return;
            }
            
            // Always show success message to prevent email enumeration
            notificationStore.success(
                $text('login.recovery_code_sent.text'),
                6000
            );
        } catch (error) {
            console.error('Error requesting reset code:', error);
            notificationStore.error(
                $text('login.error_occurred.text'),
                5000
            );
        } finally {
            isRequestingCode = false;
        }
    }
    
    /**
     * Verify the code before showing login method selection
     */
    async function verifyCode() {
        if (isVerifying || !canVerifyCode) return;
        
        isVerifying = true;
        codeError = '';
        
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.recovery_verify), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    email: email,
                    code: verificationCode
                }),
                credentials: 'include'
            });
            
            const data = await response.json();
            
            if (data.success && data.verification_token) {
                verificationToken = data.verification_token;
                currentStep = 'setup';
            } else {
                codeError = data.message || 'Invalid verification code. Please try again.';
                notificationStore.error(codeError, 5000);
            }
        } catch (error) {
            console.error('Error verifying code:', error);
            codeError = $text('login.error_occurred.text');
            notificationStore.error(codeError, 5000);
        } finally {
            isVerifying = false;
        }
    }
    
    // ============================================================================
    // Login Method Selection
    // ============================================================================
    
    /**
     * Handle login method selection
     */
    function handleMethodSelect(event: CustomEvent<{ method: string }>) {
        const method = event.detail.method;
        
        if (method === 'password') {
            currentStep = 'password';
        } else if (method === 'passkey') {
            // Start passkey registration immediately
            registerPasskey();
        }
    }
    
    // ============================================================================
    // Password Reset Flow
    // ============================================================================
    
    // Password setup state
    let newPassword = $state('');
    let confirmPassword = $state('');
    let passwordError = $state('');
    
    /**
     * Submit password setup
     */
    async function submitPassword() {
        passwordError = '';
        
        if (newPassword.length < 8) {
            passwordError = $text('signup.password_too_short.text');
            return;
        }
        
        if (newPassword !== confirmPassword) {
            passwordError = $text('signup.passwords_do_not_match.text');
            return;
        }
        
        await resetWithPassword(newPassword);
    }
    
    /**
     * Reset account and set up password login
     * Generates new master key, wraps with password-derived key, and resets account
     */
    async function resetWithPassword(password: string) {
        if (isSettingUp || !verificationToken) return;
        
        isSettingUp = true;
        
        try {
            // Generate all cryptographic material (same as signup)
            const masterKey = await cryptoService.generateExtractableMasterKey();
            const emailSalt = cryptoService.generateEmailSalt();
            const emailSaltB64 = cryptoService.uint8ArrayToBase64(emailSalt);
            
            // Derive email encryption key
            const emailEncryptionKey = await cryptoService.deriveEmailEncryptionKey(email, emailSalt);
            
            // Save email encryption key and salt
            cryptoService.saveEmailEncryptionKey(emailEncryptionKey, true);
            cryptoService.saveEmailSalt(emailSalt, true);
            
            // Encrypt email for server
            const encryptedEmailForServer = await cryptoService.encryptEmail(email, emailEncryptionKey);
            
            // Encrypt email with master key for passwordless login
            const { encryptWithMasterKeyDirect } = await import('../services/cryptoService');
            const encryptedEmailWithMasterKey = await encryptWithMasterKeyDirect(email, masterKey);
            
            // Generate password-based wrapping
            const salt = cryptoService.generateSalt();
            const saltB64 = cryptoService.uint8ArrayToBase64(salt);
            const wrappingKey = await cryptoService.deriveKeyFromPassword(password, salt);
            const { wrapped: encryptedMasterKey, iv: keyIv } = await cryptoService.encryptKey(masterKey, wrappingKey);
            
            // Generate lookup hash from password
            const lookupHash = await cryptoService.hashKey(password, emailSalt);
            
            // Hash email for server lookup
            const hashedEmail = await cryptoService.hashEmail(email);
            
            // Call the reset endpoint with verification token
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.recovery_full_reset), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    email: email,
                    verification_token: verificationToken,
                    acknowledge_data_loss: true,
                    new_login_method: 'password',
                    hashed_email: hashedEmail,
                    encrypted_email: encryptedEmailForServer,
                    encrypted_email_with_master_key: encryptedEmailWithMasterKey,
                    user_email_salt: emailSaltB64,
                    lookup_hash: lookupHash,
                    encrypted_master_key: encryptedMasterKey,
                    salt: saltB64,
                    key_iv: keyIv
                }),
                credentials: 'include'
            });
            
            const data = await response.json();
            
            if (data.success) {
                // Save master key for session
                await cryptoService.saveKeyToSession(masterKey, true);
                await cryptoService.saveEmailEncryptedWithMasterKey(email, true);
                
                // Store login method
                await userDB.init();
                await userDB.updateUserData({ login_method: 'password' });
                
                notificationStore.success(
                    $text('login.account_reset_success.text'),
                    5000
                );
                
                currentStep = 'complete';
                
                // Check auth and redirect
                await checkAuth(undefined, true);
                dispatch('resetComplete', { username: data.username });
            } else {
                handleResetError(data);
            }
        } catch (error) {
            console.error('Error resetting account with password:', error);
            notificationStore.error(
                $text('login.error_occurred.text'),
                5000
            );
        } finally {
            isSettingUp = false;
        }
    }
    
    // ============================================================================
    // Passkey Registration Flow
    // ============================================================================
    
    /**
     * Register a new passkey for account recovery
     * This is similar to the signup passkey flow in SecureAccountTopContent.svelte
     * but uses the recovery endpoint instead of the signup endpoint
     */
    async function registerPasskey() {
        if (isRegisteringPasskey || !verificationToken) return;
        
        isRegisteringPasskey = true;
        passkeyError = '';
        currentStep = 'passkey';
        
        try {
            // Generate hashed email for lookup
            const hashedEmail = await cryptoService.hashEmail(email);
            
            // Step 1: Initiate passkey registration with backend
            // For recovery, we use a special mode that doesn't require existing authentication
            const initiateResponse = await fetch(getApiEndpoint(apiEndpoints.auth.passkey_registration_initiate), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    hashed_email: hashedEmail,
                    user_id: null, // No existing user session for recovery
                    username: null, // Username will be fetched from server
                    recovery_mode: true // Indicate this is for account recovery
                }),
                credentials: 'include'
            });
            
            if (!initiateResponse.ok) {
                const errorData = await initiateResponse.json();
                console.error('Passkey registration initiation failed:', errorData);
                passkeyError = errorData?.message || 'Failed to start passkey registration. Please try again.';
                notificationStore.error(passkeyError, 8000);
                currentStep = 'setup';
                isRegisteringPasskey = false;
                return;
            }
            
            const initiateData = await initiateResponse.json();
            
            if (!initiateData.success) {
                console.error('Passkey registration initiation failed:', initiateData.message);
                passkeyError = initiateData.message || 'Failed to start passkey registration. Please try again.';
                notificationStore.error(passkeyError, 8000);
                currentStep = 'setup';
                isRegisteringPasskey = false;
                return;
            }
            
            // Step 2: Prepare WebAuthn creation options
            const challenge = base64UrlToArrayBuffer(initiateData.challenge);
            const userId = base64UrlToArrayBuffer(initiateData.user.id);
            
            const publicKeyCredentialCreationOptions: PublicKeyCredentialCreationOptions = {
                challenge: challenge,
                rp: initiateData.rp,
                user: {
                    id: userId,
                    name: initiateData.user.name,
                    displayName: initiateData.user.displayName
                },
                pubKeyCredParams: initiateData.pubKeyCredParams,
                timeout: initiateData.timeout,
                attestation: initiateData.attestation as AttestationConveyancePreference,
                authenticatorSelection: initiateData.authenticatorSelection,
                extensions: {
                    prf: {
                        eval: {
                            first: base64UrlToArrayBuffer(initiateData.extensions?.prf?.eval?.first || initiateData.challenge)
                        }
                    }
                } as AuthenticationExtensionsClientInputs
            };
            
            // Step 3: Create passkey using WebAuthn API
            let credential: PublicKeyCredential;
            try {
                credential = await navigator.credentials.create({
                    publicKey: publicKeyCredentialCreationOptions
                }) as PublicKeyCredential;
            } catch (error: any) {
                console.error('[AccountRecovery] WebAuthn credential creation failed:', error);
                
                // Check if it's a PRF-related error
                if (error.name === 'NotSupportedError' || 
                    error.message?.includes('PRF') || 
                    error.message?.includes('prf') ||
                    error.message?.toLowerCase().includes('extension')) {
                    passkeyError = $text('signup.passkey_prf_not_supported.text');
                    notificationStore.error(passkeyError, 10000);
                    currentStep = 'setup';
                    isRegisteringPasskey = false;
                    return;
                }
                
                // Check for user cancellation
                if (error.name === 'NotAllowedError') {
                    console.log('[AccountRecovery] User cancelled passkey creation');
                    currentStep = 'setup';
                    isRegisteringPasskey = false;
                    return;
                }
                
                // Other errors
                passkeyError = 'Failed to create passkey. Please try again.';
                notificationStore.error(passkeyError, 8000);
                currentStep = 'setup';
                isRegisteringPasskey = false;
                return;
            }
            
            if (!credential || !(credential instanceof PublicKeyCredential)) {
                console.error('Invalid credential created');
                passkeyError = 'Failed to create passkey - invalid response. Please try again.';
                notificationStore.error(passkeyError, 8000);
                currentStep = 'setup';
                isRegisteringPasskey = false;
                return;
            }
            
            const response = credential.response as AuthenticatorAttestationResponse;
            
            // Step 4: Check PRF extension support (CRITICAL for zero-knowledge encryption)
            const clientExtensionResults = credential.getClientExtensionResults();
            console.log('[AccountRecovery] Client extension results:', clientExtensionResults);
            const prfResults = clientExtensionResults?.prf as any;
            console.log('[AccountRecovery] PRF results:', prfResults);
            
            // Validate PRF results
            if (!prfResults) {
                console.error('[AccountRecovery] PRF extension not found in client extension results');
                passkeyError = $text('signup.passkey_prf_not_supported.text') || 
                    'Your device does not support the required passkey security features. Please use password instead.';
                notificationStore.error(passkeyError, 10000);
                currentStep = 'setup';
                isRegisteringPasskey = false;
                return;
            }
            
            if (prfResults.enabled === false) {
                console.error('[AccountRecovery] PRF extension explicitly disabled');
                passkeyError = $text('signup.passkey_prf_not_supported.text') || 
                    'Your device does not support the required passkey security features. Please use password instead.';
                notificationStore.error(passkeyError, 10000);
                currentStep = 'setup';
                isRegisteringPasskey = false;
                return;
            }
            
            // Extract PRF signature
            const prfSignatureBuffer = prfResults.results?.first;
            if (!prfSignatureBuffer) {
                console.error('[AccountRecovery] PRF signature not found in results');
                passkeyError = $text('signup.passkey_prf_not_supported.text') || 
                    'Your device does not support the required passkey security features. Please use password instead.';
                notificationStore.error(passkeyError, 10000);
                currentStep = 'setup';
                isRegisteringPasskey = false;
                return;
            }
            
            // Convert PRF signature to Uint8Array - handle multiple formats
            let prfSignature: Uint8Array;
            if (typeof prfSignatureBuffer === 'string') {
                console.log('[AccountRecovery] PRF signature is hex string, converting to Uint8Array');
                const hexString = prfSignatureBuffer;
                prfSignature = new Uint8Array(hexString.match(/.{1,2}/g)!.map(byte => parseInt(byte, 16)));
            } else if (prfSignatureBuffer instanceof ArrayBuffer) {
                console.log('[AccountRecovery] PRF signature is ArrayBuffer, converting to Uint8Array');
                prfSignature = new Uint8Array(prfSignatureBuffer);
            } else if (ArrayBuffer.isView(prfSignatureBuffer)) {
                console.log('[AccountRecovery] PRF signature is TypedArray, converting to Uint8Array');
                prfSignature = new Uint8Array(prfSignatureBuffer.buffer, prfSignatureBuffer.byteOffset, prfSignatureBuffer.byteLength);
            } else {
                console.error('[AccountRecovery] PRF signature is in unknown format');
                passkeyError = 'Unexpected error during passkey creation. Please try again.';
                notificationStore.error(passkeyError, 8000);
                currentStep = 'setup';
                isRegisteringPasskey = false;
                return;
            }
            
            // Validate PRF signature length
            if (prfSignature.length < 16 || prfSignature.length > 64) {
                console.error('[AccountRecovery] PRF signature has invalid length:', prfSignature.length);
                passkeyError = 'Unexpected error during passkey creation. Please try again.';
                notificationStore.error(passkeyError, 8000);
                currentStep = 'setup';
                isRegisteringPasskey = false;
                return;
            }
            
            console.log('[AccountRecovery] PRF signature validated successfully', {
                length: prfSignature.length,
                enabled: prfResults.enabled,
                firstBytes: Array.from(prfSignature.slice(0, 4))
            });
            
            // Step 5: Generate master key and email salt
            const masterKey = await cryptoService.generateExtractableMasterKey();
            const emailSalt = cryptoService.generateEmailSalt();
            const emailSaltB64 = cryptoService.uint8ArrayToBase64(emailSalt);
            
            // Step 6: Derive wrapping key from PRF signature using HKDF
            const wrappingKey = await cryptoService.deriveWrappingKeyFromPRF(prfSignature, emailSalt);
            
            // Step 7: Wrap the master key for server storage
            const { wrapped: encryptedMasterKey, iv: keyIv } = await cryptoService.encryptKey(masterKey, wrappingKey);
            
            // Step 8: Save master key
            await cryptoService.saveKeyToSession(masterKey, true);
            
            // Step 9: Generate lookup hash from PRF signature (for authentication)
            const lookupHash = await cryptoService.hashKeyFromPRF(prfSignature, emailSalt);
            
            // Step 10: Derive email encryption key
            const emailEncryptionKey = await cryptoService.deriveEmailEncryptionKey(email, emailSalt);
            
            // Step 11: Store email encryption key and salt
            cryptoService.saveEmailEncryptionKey(emailEncryptionKey, true);
            cryptoService.saveEmailSalt(emailSalt, true);
            
            // Step 12: Encrypt email for server storage
            const encryptedEmailForServer = await cryptoService.encryptEmail(email, emailEncryptionKey);
            
            // Step 13: Encrypt email with master key for passwordless login
            const { encryptWithMasterKeyDirect } = await import('../services/cryptoService');
            const encryptedEmailWithMasterKey = await encryptWithMasterKeyDirect(email, masterKey);
            if (!encryptedEmailWithMasterKey) {
                console.error('Failed to encrypt email with master key');
                passkeyError = 'Failed to encrypt your data. Please try again.';
                notificationStore.error(passkeyError, 8000);
                currentStep = 'setup';
                isRegisteringPasskey = false;
                return;
            }
            
            // Step 14: Generate and encrypt device name
            const deviceName = generateDeviceName();
            const encryptedDeviceName = await encryptWithMasterKeyDirect(deviceName, masterKey);
            
            // Step 15: Save email encrypted with master key for client storage
            const emailStoredSuccessfully = await cryptoService.saveEmailEncryptedWithMasterKey(email, true);
            if (!emailStoredSuccessfully) {
                console.error('Failed to store encrypted email');
                passkeyError = 'Failed to store encrypted data. Please try again.';
                notificationStore.error(passkeyError, 8000);
                currentStep = 'setup';
                isRegisteringPasskey = false;
                return;
            }
            
            // Step 16: Extract credential data for backend
            const credentialId = arrayBufferToBase64Url(credential.rawId);
            const clientDataJSONB64 = cryptoService.uint8ArrayToBase64(new Uint8Array(response.clientDataJSON));
            const attestationObject = new Uint8Array(response.attestationObject);
            const attestationObjectB64 = cryptoService.uint8ArrayToBase64(attestationObject);
            const authenticatorData = attestationObject.slice(0, 37);
            const authenticatorDataB64 = cryptoService.uint8ArrayToBase64(authenticatorData);
            
            // Step 17: Call the recovery reset endpoint with passkey credential
            const resetResponse = await fetch(getApiEndpoint(apiEndpoints.auth.recovery_full_reset), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    email: email,
                    verification_token: verificationToken,
                    acknowledge_data_loss: true,
                    new_login_method: 'passkey',
                    hashed_email: hashedEmail,
                    encrypted_email: encryptedEmailForServer,
                    encrypted_email_with_master_key: encryptedEmailWithMasterKey,
                    user_email_salt: emailSaltB64,
                    lookup_hash: lookupHash,
                    encrypted_master_key: encryptedMasterKey,
                    salt: emailSaltB64, // Same as user_email_salt for passkeys
                    key_iv: keyIv,
                    // Passkey-specific credential data
                    passkey_credential: {
                        credential_id: credentialId,
                        attestation_response: {
                            attestationObject: attestationObjectB64,
                            publicKey: {}
                        },
                        client_data_json: clientDataJSONB64,
                        authenticator_data: authenticatorDataB64,
                        encrypted_device_name: encryptedDeviceName || null,
                        prf_enabled: true
                    }
                }),
                credentials: 'include'
            });
            
            const resetData = await resetResponse.json();
            
            if (resetData.success) {
                // Store login method
                await userDB.init();
                await userDB.updateUserData({ login_method: 'passkey' });
                
                notificationStore.success(
                    $text('login.account_reset_success.text'),
                    5000
                );
                
                currentStep = 'complete';
                
                // Check auth and redirect
                await checkAuth(undefined, true);
                dispatch('resetComplete', { username: resetData.username });
            } else {
                handleResetError(resetData);
            }
            
        } catch (error) {
            console.error('Error registering passkey:', error);
            passkeyError = 'An unexpected error occurred. Please try again.';
            notificationStore.error(passkeyError, 8000);
            currentStep = 'setup';
        } finally {
            isRegisteringPasskey = false;
        }
    }
    
    // ============================================================================
    // Error Handling
    // ============================================================================
    
    /**
     * Handle reset errors from the backend
     */
    function handleResetError(data: any) {
        codeError = data.message || 'Failed to reset account. Please try again.';
        notificationStore.error(codeError, 6000);
        
        // If token expired, go back to code step
        if (data.error_code === 'TOKEN_EXPIRED' || data.error_code === 'INVALID_TOKEN') {
            currentStep = 'code';
            verificationToken = '';
            verificationCode = '';
        } else {
            // For other errors, go back to login method selection
            currentStep = 'setup';
        }
    }
    
    /**
     * Go back to login
     */
    function backToLogin() {
        dispatch('back');
    }
    
    /**
     * Go back to login method selection
     */
    function backToMethodSelection() {
        currentStep = 'setup';
        newPassword = '';
        confirmPassword = '';
        passwordError = '';
        passkeyError = '';
    }
</script>

<div class="account-recovery" transition:fade>
    
    {#if currentStep === 'code'}
        <div class="step-content" transition:slide>
            <p class="info-text">
                {$text('login.enter_code_sent.text')}
            </p>
            
            <div class="input-group">
                <div class="input-wrapper">
                    <span class="clickable-icon icon_2fa"></span>
                    <input
                        id="verification-code"
                        type="text"
                        bind:value={verificationCode}
                        placeholder="123456"
                        maxlength="6"
                        pattern="[0-9]*"
                        inputmode="numeric"
                        disabled={isVerifying}
                        class:error={!!codeError}
                    />
                </div>
                {#if codeError}
                    <span class="error-text">{codeError}</span>
                {/if}
            </div>
            
            <div class="confirmation-section">
                <div class="toggle-row">
                    <Toggle 
                        bind:checked={acknowledgeDataLoss}
                        id="acknowledge-data-loss"
                        ariaLabel={$text('login.acknowledge_data_loss.text')}
                    />
                    <label for="acknowledge-data-loss" class="toggle-label">
                        {$text('login.acknowledge_data_loss.text')}
                    </label>
                </div>
            </div>
            
            <button
                onclick={verifyCode}
                disabled={!canVerifyCode}
            >
                {#if isVerifying}
                    <span class="loading-spinner"></span>
                {:else}
                    {$text('login.reset_account.text')}
                {/if}
            </button>
            
            <button 
                class="resend-button"
                onclick={requestResetCode}
                disabled={isRequestingCode}
            >
                {$text('login.resend_code.text')}
            </button>
        </div>
        
    {:else if currentStep === 'setup'}
        <div class="step-content" transition:slide>
            <div class="success-message">
                <div class="check-icon">✓</div>
                <span>{$text('login.code_verified.text')}</span>
            </div>
            
            <!-- Show both passkey and password options -->
            <LoginMethodSelector
                showPasskey={true}
                showRecommendedBadge={true}
                isLoading={isSettingUp || isRegisteringPasskey}
                on:select={handleMethodSelect}
            />
        </div>
        
    {:else if currentStep === 'passkey'}
        <div class="step-content" transition:slide>
            <div class="passkey-loading">
                <div class="passkey-icon">
                    <div class="clickable-icon icon_passkey" style="width: 64px; height: 64px;"></div>
                </div>
                <p class="info-text">
                    {$text('login.registering_passkey.text')}
                </p>
                <p class="info-text-secondary">
                    {$text('login.follow_passkey_prompts.text')}
                </p>
                {#if passkeyError}
                    <span class="error-text">{passkeyError}</span>
                    <button class="secondary-button" onclick={backToMethodSelection}>
                        {$text('login.try_another_method.text')}
                    </button>
                {/if}
            </div>
        </div>
        
    {:else if currentStep === 'password'}
        <div class="step-content" transition:slide>
            <button class="back-button" onclick={backToMethodSelection}>
                ← {$text('login.back.text')}
            </button>
            
            <p class="info-text">
                {$text('signup.create_password.text')}
            </p>
            
            <div class="input-group">
                <div class="input-wrapper">
                    <span class="clickable-icon icon_password"></span>
                    <input
                        id="new-password"
                        type="password"
                        bind:value={newPassword}
                        placeholder={$text('login.password_placeholder.text')}
                        disabled={isSettingUp}
                        minlength="8"
                        autocomplete="new-password"
                    />
                </div>
            </div>
            
            <div class="input-group">
                <div class="input-wrapper">
                    <span class="clickable-icon icon_password"></span>
                    <input
                        id="confirm-password"
                        type="password"
                        bind:value={confirmPassword}
                        placeholder={$text('signup.confirm_password.text')}
                        disabled={isSettingUp}
                        autocomplete="new-password"
                        onkeydown={(e) => e.key === 'Enter' && submitPassword()}
                    />
                </div>
                {#if passwordError}
                    <span class="error-text">{passwordError}</span>
                {/if}
            </div>
            
            <button
                onclick={submitPassword}
                disabled={isSettingUp || !newPassword || !confirmPassword}
            >
                {#if isSettingUp}
                    <span class="loading-spinner"></span>
                {:else}
                    {$text('login.complete_reset.text')}
                {/if}
            </button>
        </div>
        
    {:else if currentStep === 'complete'}
        <div class="step-content" transition:slide>
            <div class="success-icon">✓</div>
            <h3>{$text('login.account_reset_complete.text')}</h3>
            <p class="info-text">
                {$text('login.you_can_now_login.text')}
            </p>
            <button onclick={backToLogin}>
                {$text('login.go_to_login.text')}
            </button>
        </div>
    {/if}
</div>

<style>
    .account-recovery {
        width: 100%;
        max-width: 400px;
        margin: 0 auto;
        padding: 20px;
    }
    
    .step-content {
        display: flex;
        flex-direction: column;
        gap: 16px;
    }
    
    .info-text {
        color: var(--color-grey-60);
        font-size: 14px;
        line-height: 1.5;
        text-align: center;
    }
    
    .info-text-secondary {
        color: var(--color-grey-50);
        font-size: 13px;
        line-height: 1.4;
        text-align: center;
        margin-top: -8px;
    }
    
    .error-text {
        color: var(--color-red-50);
        font-size: 12px;
        margin-top: 4px;
    }
    
    .resend-button {
        padding: 10px;
        background: transparent;
        color: var(--color-grey-60);
        border: none;
        font-size: 14px;
        cursor: pointer;
        text-decoration: underline;
    }
    
    .resend-button:hover:not(:disabled) {
        color: var(--color-grey-80);
    }
    
    .resend-button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
    
    .back-button {
        all: unset;
        color: var(--color-grey-60);
        font-size: 14px;
        cursor: pointer;
        padding: 4px 0;
        align-self: flex-start;
    }
    
    .back-button:hover {
        color: var(--color-grey-80);
    }
    
    .secondary-button {
        padding: 10px 20px;
        background: var(--color-grey-20);
        color: var(--color-grey-70);
        border: none;
        border-radius: 8px;
        font-size: 14px;
        cursor: pointer;
        transition: all 0.2s ease;
    }
    
    .secondary-button:hover {
        background: var(--color-grey-25);
        color: var(--color-grey-80);
    }
    
    .confirmation-section {
        background: var(--color-grey-15);
        border-radius: 12px;
        padding: 16px;
    }
    
    .toggle-row {
        display: flex;
        align-items: flex-start;
        gap: 12px;
    }
    
    .toggle-label {
        font-size: 14px;
        color: var(--color-grey-70);
        line-height: 1.4;
        cursor: pointer;
    }
    
    .success-message {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        padding: 12px;
        background: var(--color-green-10);
        border-radius: 12px;
        color: var(--color-green-60);
        font-weight: 500;
    }
    
    .check-icon {
        width: 24px;
        height: 24px;
        background: var(--color-green-50);
        color: white;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 14px;
    }
    
    .loading-spinner {
        width: 20px;
        height: 20px;
        border: 2px solid transparent;
        border-top-color: currentColor;
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
    }
    
    @keyframes spin {
        to {
            transform: rotate(360deg);
        }
    }
    
    .success-icon {
        width: 60px;
        height: 60px;
        background: var(--color-green-50);
        color: white;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 30px;
        margin: 0 auto 16px;
    }
    
    .step-content h3 {
        text-align: center;
        margin: 0 0 8px;
        color: var(--color-grey-80);
    }
    
    /* Passkey loading state */
    .passkey-loading {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 16px;
        padding: 24px;
    }
    
    .passkey-icon {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 80px;
        height: 80px;
        background: var(--color-primary-10);
        border-radius: 16px;
    }
</style>
