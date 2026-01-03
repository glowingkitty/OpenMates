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
     *    - Password: Set up new password
     *    - Passkey: Register new passkey with PRF extension
     * 6. Show loading screen during reset
     * 7. On success, redirect to login page with success notification
     * 
     * CRITICAL: After reset, user is NOT automatically logged in.
     * They must login with their new credentials.
     * 
     * NOTE: If the user previously had 2FA configured, it is preserved server-side
     * (vault encrypted). They will be prompted for 2FA on next login.
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
    import { generateDeviceName } from '../utils/deviceName';
    
    // ========================================================================
    // WebAuthn PRF Extension Types
    // ========================================================================
    // TypeScript's DOM types don't include PRF extension, so we define custom types.
    // PRF (Pseudorandom Function) extension is critical for zero-knowledge encryption
    // - it allows deriving a stable key from passkey authentication.
    // 
    // Note: We use 'unknown' and type assertions to avoid ESLint 'no-undef' errors
    // for DOM types like PublicKeyCredentialRpEntity that aren't available at lint time.
    
    /** PRF extension output from credential operation */
    interface PRFExtensionOutputs {
        enabled?: boolean;
        results?: {
            first: ArrayBuffer;
            second?: ArrayBuffer;
        };
    }
    
    /** Client extension results with PRF support */
    interface WebAuthnResultsWithPRF {
        prf?: PRFExtensionOutputs;
        [key: string]: unknown;
    }
    
    const dispatch = createEventDispatcher();
    
    // Props - email is passed from the login form
    let { email: initialEmail = '' }: { email?: string } = $props();
    
    // Step states:
    // - 'code': Enter verification code
    // - 'setup': Select login method (password or passkey)
    // - 'password': Set up new password
    // - '2fa_setup': Set up 2FA (required for password method if user doesn't have 2FA)
    // - 'passkey': Register passkey (shows loading while WebAuthn prompt is active)
    // - 'resetting': Loading screen while account is being reset
    // - 'complete': Reset complete, redirect to login
    type RecoveryStep = 'code' | 'setup' | 'password' | '2fa_setup' | 'passkey' | 'resetting' | 'complete';
    let currentStep = $state<RecoveryStep>('code');
    
    // Form data
    let email = $state(initialEmail);
    let verificationCode = $state('');
    let acknowledgeDataLoss = $state(false);
    let verificationToken = $state(''); // Token from verify-code endpoint
    
    // User 2FA status from verify response
    let userHas2FA = $state(false);
    
    // 2FA setup data
    let tfaSecret = $state('');
    let tfaVerificationCode = $state('');
    let tfaAppName = $state('');
    let tfaQrCodeSvg = $state('');
    
    // Loading states
    let isRequestingCode = $state(false);
    let isVerifying = $state(false);
    let isSettingUp = $state(false);
    let isRegisteringPasskey = $state(false);
    let isSettingUp2FA = $state(false);
    let isVerifying2FA = $state(false);
    
    // Error states
    let codeError = $state('');
    let passkeyError = $state('');
    let tfaError = $state('');
    
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
                // Store whether user already has 2FA configured
                userHas2FA = data.has_2fa === true;
                console.log('[AccountRecovery] User has 2FA:', userHas2FA);
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
     * If user doesn't have 2FA, proceed to 2FA setup step first
     * If user already has 2FA, proceed directly to reset
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
        
        // If user doesn't have 2FA, they need to set it up first
        if (!userHas2FA) {
            console.log('[AccountRecovery] User needs to set up 2FA before reset');
            await setup2FA();
        } else {
            // User already has 2FA, proceed directly to reset
            await resetWithPassword(newPassword);
        }
    }
    
    // ============================================================================
    // 2FA Setup Flow
    // ============================================================================
    
    /**
     * Request 2FA setup data from the server
     * Called when user submits password and doesn't have 2FA configured
     */
    async function setup2FA() {
        if (isSettingUp2FA || !verificationToken) return;
        
        isSettingUp2FA = true;
        tfaError = '';
        
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.recovery_setup_2fa), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    email: email,
                    verification_token: verificationToken
                }),
                credentials: 'include'
            });
            
            const data = await response.json();
            
            if (data.success && data.secret && data.otpauth_url) {
                tfaSecret = data.secret;
                
                // Generate QR code SVG
                try {
                    const QRCode = (await import('qrcode-svg')).default;
                    const qr = new QRCode({
                        content: data.otpauth_url,
                        padding: 0,
                        width: 180,
                        height: 180,
                        color: 'currentColor',
                        background: 'transparent',
                        ecl: 'M'
                    });
                    tfaQrCodeSvg = qr.svg();
                } catch (qrError) {
                    console.error('[AccountRecovery] Failed to generate QR code:', qrError);
                }
                
                // Move to 2FA setup step
                currentStep = '2fa_setup';
            } else {
                tfaError = data.message || 'Failed to set up 2FA. Please try again.';
                notificationStore.error(tfaError, 5000);
            }
        } catch (error) {
            console.error('[AccountRecovery] Error setting up 2FA:', error);
            tfaError = 'An error occurred while setting up 2FA. Please try again.';
            notificationStore.error(tfaError, 5000);
        } finally {
            isSettingUp2FA = false;
        }
    }
    
    /**
     * Verify 2FA code and proceed to reset
     * Called from 2FA setup step after user enters the code from their app
     */
    async function verify2FAAndReset() {
        if (isVerifying2FA || !tfaSecret || tfaVerificationCode.length !== 6) return;
        
        isVerifying2FA = true;
        tfaError = '';
        
        // Proceed to reset with the 2FA data
        // The server will verify the code
        await resetWithPassword(newPassword);
        
        isVerifying2FA = false;
    }
    
    /**
     * Reset account and set up password login
     * Generates new master key, wraps with password-derived key, and resets account.
     * 
     * CRITICAL: After reset completes, the user is NOT automatically logged in.
     * The backend creates the new credentials but does NOT create a session.
     * User must login with their new credentials after reset.
     */
    async function resetWithPassword(password: string) {
        if (isSettingUp || !verificationToken) return;
        
        isSettingUp = true;
        // Show dedicated loading screen during the reset process
        currentStep = 'resetting';
        
        try {
            // Generate all cryptographic material (same as signup)
            const masterKey = await cryptoService.generateExtractableMasterKey();
            const emailSalt = cryptoService.generateEmailSalt();
            const emailSaltB64 = cryptoService.uint8ArrayToBase64(emailSalt);
            
            // Derive email encryption key (needed for server to encrypt email)
            const emailEncryptionKey = await cryptoService.deriveEmailEncryptionKey(email, emailSalt);
            
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
            
            // Build request body
            const requestBody: Record<string, unknown> = {
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
            };
            
            // Include 2FA data if it was set up during recovery
            if (tfaSecret && tfaVerificationCode) {
                requestBody.tfa_secret = tfaSecret;
                requestBody.tfa_verification_code = tfaVerificationCode;
                requestBody.tfa_app_name = tfaAppName || '2FA App';
                console.log('[AccountRecovery] Including 2FA data in reset request');
            }
            
            // Call the reset endpoint with verification token
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.recovery_full_reset), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(requestBody),
                credentials: 'include'
            });
            
            const data = await response.json();
            
            if (data.success) {
                // CRITICAL: Do NOT save master key or try to auto-login!
                // The backend does NOT create a session - user must login with new credentials.
                // Clear any crypto data that was generated during this process to ensure clean state.
                console.log('[AccountRecovery] Password reset successful, clearing temp crypto data');
                
                // Show success state
                currentStep = 'complete';
                
                // Dispatch completion - parent will show notification and reset to login
                dispatch('resetComplete', { username: data.username, success: true });
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
            
            // Build creation options with PRF extension
            // PRF extension is critical for zero-knowledge encryption - it generates
            // a stable cryptographic key from passkey authentication.
            // We cast to 'unknown' first then to the DOM type to satisfy TypeScript
            // while including the PRF extension that's not in standard types.
            const publicKeyCredentialCreationOptions = {
                challenge: challenge,
                rp: initiateData.rp,
                user: {
                    id: userId,
                    name: initiateData.user.name,
                    displayName: initiateData.user.displayName
                },
                pubKeyCredParams: initiateData.pubKeyCredParams,
                timeout: initiateData.timeout,
                attestation: initiateData.attestation,
                authenticatorSelection: initiateData.authenticatorSelection,
                extensions: {
                    prf: {
                        eval: {
                            first: base64UrlToArrayBuffer(initiateData.extensions?.prf?.eval?.first || initiateData.challenge)
                        }
                    }
                }
            // eslint-disable-next-line no-undef -- DOM type available at runtime
            } as unknown as PublicKeyCredentialCreationOptions;
            
            // Step 3: Create passkey using WebAuthn API
            let credential: PublicKeyCredential;
            try {
                credential = await navigator.credentials.create({
                    publicKey: publicKeyCredentialCreationOptions
                }) as PublicKeyCredential;
            } catch (error: unknown) {
                console.error('[AccountRecovery] WebAuthn credential creation failed:', error);
                const webauthnError = error as Error & { name: string };
                
                // Check if it's a PRF-related error
                if (webauthnError.name === 'NotSupportedError' || 
                    webauthnError.message?.includes('PRF') || 
                    webauthnError.message?.includes('prf') ||
                    webauthnError.message?.toLowerCase().includes('extension')) {
                    passkeyError = $text('signup.passkey_prf_not_supported.text');
                    notificationStore.error(passkeyError, 10000);
                    currentStep = 'setup';
                    isRegisteringPasskey = false;
                    return;
                }
                
                // Check for user cancellation
                if (webauthnError.name === 'NotAllowedError') {
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
            const clientExtensionResults = credential.getClientExtensionResults() as WebAuthnResultsWithPRF;
            console.log('[AccountRecovery] Client extension results:', clientExtensionResults);
            const prfResults = clientExtensionResults?.prf;
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
            
            // Extract PRF signature - this is the key material for encryption
            const prfSignatureRaw = prfResults.results?.first;
            if (!prfSignatureRaw) {
                console.error('[AccountRecovery] PRF signature not found in results');
                passkeyError = $text('signup.passkey_prf_not_supported.text') || 
                    'Your device does not support the required passkey security features. Please use password instead.';
                notificationStore.error(passkeyError, 10000);
                currentStep = 'setup';
                isRegisteringPasskey = false;
                return;
            }
            
            // Convert PRF signature to Uint8Array
            // PRF result is always an ArrayBuffer per WebAuthn spec
            console.log('[AccountRecovery] Converting PRF signature to Uint8Array');
            const prfSignature = new Uint8Array(prfSignatureRaw);
            
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
            
            // Step 8: Generate lookup hash from PRF signature (for authentication)
            const lookupHash = await cryptoService.hashKeyFromPRF(prfSignature, emailSalt);
            
            // Step 9: Derive email encryption key (needed for server to encrypt email)
            const emailEncryptionKey = await cryptoService.deriveEmailEncryptionKey(email, emailSalt);
            
            // Step 10: Encrypt email for server storage
            const encryptedEmailForServer = await cryptoService.encryptEmail(email, emailEncryptionKey);
            
            // Step 11: Encrypt email with master key for passwordless login
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
            
            // Step 12: Generate and encrypt device name
            const deviceName = generateDeviceName();
            const encryptedDeviceName = await encryptWithMasterKeyDirect(deviceName, masterKey);
            
            // Step 13: Extract credential data for backend
            const credentialId = arrayBufferToBase64Url(credential.rawId);
            const clientDataJSONB64 = cryptoService.uint8ArrayToBase64(new Uint8Array(response.clientDataJSON));
            const attestationObject = new Uint8Array(response.attestationObject);
            const attestationObjectB64 = cryptoService.uint8ArrayToBase64(attestationObject);
            const authenticatorData = attestationObject.slice(0, 37);
            const authenticatorDataB64 = cryptoService.uint8ArrayToBase64(authenticatorData);
            
            // Step 14: Show loading screen while resetting account
            currentStep = 'resetting';
            
            // Step 15: Call the recovery reset endpoint with passkey credential
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
                // CRITICAL: Do NOT save master key or try to auto-login!
                // The backend does NOT create a session - user must login with new credentials.
                console.log('[AccountRecovery] Passkey reset successful, showing completion');
                
                // Show success state
                currentStep = 'complete';
                
                // Dispatch completion - parent will show notification and reset to login
                dispatch('resetComplete', { username: resetData.username, success: true });
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
    
    /** Backend error response type */
    interface ResetErrorResponse {
        success: boolean;
        message?: string;
        error_code?: string;
    }
    
    /**
     * Handle reset errors from the backend
     */
    function handleResetError(data: ResetErrorResponse) {
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
                disabled={isSettingUp || isSettingUp2FA || !newPassword || !confirmPassword}
            >
                {#if isSettingUp || isSettingUp2FA}
                    <span class="loading-spinner"></span>
                {:else if !userHas2FA}
                    <!-- User needs to set up 2FA next -->
                    {$text('login.continue.text')}
                {:else}
                    {$text('login.complete_reset.text')}
                {/if}
            </button>
        </div>
        
    {:else if currentStep === '2fa_setup'}
        <!-- 2FA Setup Step - Required for password users without existing 2FA -->
        <div class="step-content" transition:slide>
            <button class="back-button" onclick={() => currentStep = 'password'}>
                ← {$text('login.back.text')}
            </button>
            
            <div class="tfa-setup-header">
                <div class="icon header_size tfa"></div>
                <h3>{$text('signup.one_time_codes.text')}</h3>
            </div>
            
            <p class="info-text">
                {$text('signup.prevent_access.text')}
            </p>
            
            <!-- QR Code Section -->
            {#if tfaQrCodeSvg}
                <div class="qr-code-container">
                    <!-- eslint-disable-next-line svelte/no-at-html-tags -- SVG is generated locally from trusted otpauth URL -->
                    {@html tfaQrCodeSvg}
                </div>
            {/if}
            
            <!-- Secret Key (for manual entry) -->
            {#if tfaSecret}
                <div class="secret-key-container">
                    <span class="secret-label">{$text('signup.or_enter_manually.text')}</span>
                    <code class="secret-key">{tfaSecret}</code>
                </div>
            {/if}
            
            <!-- 2FA Code Input -->
            <div class="input-group">
                <label for="tfa-code" class="input-label">{$text('signup.enter_one_time_code.text')}</label>
                <div class="input-wrapper">
                    <span class="clickable-icon icon_2fa"></span>
                    <input
                        id="tfa-code"
                        type="text"
                        bind:value={tfaVerificationCode}
                        placeholder="123456"
                        maxlength="6"
                        pattern="[0-9]*"
                        inputmode="numeric"
                        disabled={isVerifying2FA}
                        onkeydown={(e) => e.key === 'Enter' && tfaVerificationCode.length === 6 && verify2FAAndReset()}
                    />
                </div>
                {#if tfaError}
                    <span class="error-text">{tfaError}</span>
                {/if}
            </div>
            
            <!-- App Name Input (optional) -->
            <div class="input-group">
                <label for="tfa-app-name" class="input-label">{$text('signup.which_2fa_app.text')}</label>
                <div class="input-wrapper">
                    <input
                        id="tfa-app-name"
                        type="text"
                        bind:value={tfaAppName}
                        placeholder="Google Authenticator, Authy, etc."
                        disabled={isVerifying2FA}
                    />
                </div>
            </div>
            
            <button
                onclick={verify2FAAndReset}
                disabled={isVerifying2FA || tfaVerificationCode.length !== 6}
            >
                {#if isVerifying2FA}
                    <span class="loading-spinner"></span>
                {:else}
                    {$text('login.complete_reset.text')}
                {/if}
            </button>
        </div>
        
    {:else if currentStep === 'resetting'}
        <!-- Dedicated loading screen during account reset process -->
        <div class="step-content resetting-step" transition:slide>
            <div class="resetting-animation">
                <div class="resetting-icon">
                    <div class="loading-spinner large"></div>
                </div>
                <h3>{$text('login.resetting_account.text')}</h3>
                <p class="info-text">
                    {$text('login.resetting_account_description.text')}
                </p>
            </div>
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
    
    /* Resetting account loading state */
    .resetting-step {
        min-height: 200px;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    
    .resetting-animation {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 20px;
        padding: 32px;
    }
    
    .resetting-icon {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 80px;
        height: 80px;
        background: var(--color-primary-10);
        border-radius: 50%;
    }
    
    .loading-spinner.large {
        width: 40px;
        height: 40px;
        border-width: 3px;
        border-color: var(--color-primary-50);
        border-top-color: transparent;
    }
    
    /* 2FA Setup Step Styles */
    .tfa-setup-header {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 12px;
        margin-bottom: 8px;
    }
    
    .tfa-setup-header h3 {
        margin: 0;
        color: var(--color-grey-80);
    }
    
    .qr-code-container {
        display: flex;
        justify-content: center;
        padding: 16px;
        background: var(--color-grey-10);
        border-radius: 12px;
        color: var(--color-grey-80);
    }
    
    .secret-key-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 8px;
        padding: 12px;
        background: var(--color-grey-10);
        border-radius: 8px;
    }
    
    .secret-label {
        font-size: 12px;
        color: var(--color-grey-50);
    }
    
    .secret-key {
        font-family: monospace;
        font-size: 14px;
        color: var(--color-grey-70);
        word-break: break-all;
        text-align: center;
        user-select: all;
    }
    
    .input-label {
        display: block;
        font-size: 13px;
        color: var(--color-grey-60);
        margin-bottom: 6px;
    }
</style>
