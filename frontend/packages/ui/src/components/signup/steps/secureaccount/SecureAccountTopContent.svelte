<script lang="ts">
    /**
     * Secure Account Top Content Component
     * 
     * Handles selection of account security method (password or passkey).
     * For passkey, immediately triggers WebAuthn registration.
     */
    import { text } from '@repo/ui';
    import { theme } from '../../../../stores/theme';
    import { createEventDispatcher } from 'svelte';
    import { userDB } from '../../../../services/userDB';
    import { signupStore } from '../../../../stores/signupStore';
    import { requireInviteCode } from '../../../../stores/signupRequirements';
    import { get } from 'svelte/store';
    import { getApiEndpoint, apiEndpoints } from '../../../../config/api';
    import * as cryptoService from '../../../../services/cryptoService';
    import { generateDeviceName } from '../../../../utils/deviceName';
    import { checkAuth, authStore } from '../../../../stores/authStore';
    import { userProfile } from '../../../../stores/userProfile';
    
    const dispatch = createEventDispatcher();
    
    // Login method selection using Svelte 5 runes
    let selectedOption = $state<string | null>(null);
    let isRegisteringPasskey = $state(false);
    
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
     * Poll to verify user is authenticated and user data is loaded.
     * Retries with exponential backoff until auth state is confirmed or max attempts reached.
     * @param maxAttempts Maximum number of polling attempts
     * @param maxTimeoutMs Maximum total time to wait in milliseconds
     * @returns true if user is authenticated and data is loaded, false otherwise
     */
    async function pollAuthState(maxAttempts: number = 5, maxTimeoutMs: number = 2000): Promise<boolean> {
        const startTime = Date.now();
        const delayBetweenAttempts = Math.min(200, maxTimeoutMs / maxAttempts); // Adaptive delay
        
        for (let attempt = 1; attempt <= maxAttempts; attempt++) {
            // Check if we've exceeded max timeout
            if (Date.now() - startTime > maxTimeoutMs) {
                console.warn(`[SecureAccountTopContent] Auth state polling timeout after ${maxTimeoutMs}ms`);
                return false;
            }
            
            try {
                // Force auth check to ensure we get fresh data
                const authSuccess = await checkAuth(undefined, true);
                
                if (authSuccess) {
                    // Verify user data is actually loaded (check if username exists)
                    const currentAuth = get(authStore);
                    const currentProfile = get(userProfile);
                    
                    if (currentAuth.isAuthenticated && currentProfile.username) {
                        console.debug(`[SecureAccountTopContent] Auth state confirmed after ${attempt} attempt(s)`);
                        return true;
                    }
                }
                
                // If not authenticated yet, wait before next attempt (except on last attempt)
                if (attempt < maxAttempts) {
                    await new Promise(resolve => setTimeout(resolve, delayBetweenAttempts));
                }
            } catch (error) {
                console.warn(`[SecureAccountTopContent] Error checking auth state (attempt ${attempt}/${maxAttempts}):`, error);
                // Wait before retrying (except on last attempt)
                if (attempt < maxAttempts) {
                    await new Promise(resolve => setTimeout(resolve, delayBetweenAttempts));
                }
            }
        }
        
        console.warn(`[SecureAccountTopContent] Auth state not confirmed after ${maxAttempts} attempts`);
        return false;
    }
    
    /**
     * Handle passkey registration - triggered immediately when user clicks passkey option
     */
    async function registerPasskey() {
        if (isRegisteringPasskey) return;
        
        try {
            isRegisteringPasskey = true;
            selectedOption = 'passkey';
            
            // Store the selected login method in IndexedDB
            await userDB.updateUserData({ login_method: 'passkey' });
            
            // Get stored signup data
            const storeData = get(signupStore);
            const requireInviteCodeValue = get(requireInviteCode);
            
            // Validate required data
            if (!storeData.email || !storeData.username || (requireInviteCodeValue && !storeData.inviteCode)) {
                console.error('Missing required signup data');
                isRegisteringPasskey = false;
                return;
            }
            
            // Generate hashed email for lookup
            const hashedEmail = await cryptoService.hashEmail(storeData.email);
            
            // Step 1: Initiate passkey registration with backend
            const initiateResponse = await fetch(getApiEndpoint(apiEndpoints.auth.passkey_registration_initiate), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    hashed_email: hashedEmail,
                    user_id: null, // New user signup
                    username: storeData.username // Send username for passkey displayName
                }),
                credentials: 'include'
            });
            
            if (!initiateResponse.ok) {
                const errorData = await initiateResponse.json();
                console.error('Passkey registration initiation failed:', errorData);
                isRegisteringPasskey = false;
                return;
            }
            
            const initiateData = await initiateResponse.json();
            
            if (!initiateData.success) {
                console.error('Passkey registration initiation failed:', initiateData.message);
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
                console.error('[Signup] WebAuthn credential creation failed:', error);
                // Check if it's a PRF-related error or user cancellation
                if (error.name === 'NotSupportedError' || 
                    error.message?.includes('PRF') || 
                    error.message?.includes('prf') ||
                    error.message?.toLowerCase().includes('extension')) {
                    // PRF not supported - show error screen
                    console.error('[Signup] PRF-related error during credential creation:', {
                        name: error.name,
                        message: error.message
                    });
                    dispatch('step', { step: 'passkey_prf_error' });
                    isRegisteringPasskey = false;
                    return;
                }
                // Other errors (user cancellation, etc.)
                isRegisteringPasskey = false;
                return;
            }
            
            if (!credential || !(credential instanceof PublicKeyCredential)) {
                console.error('Invalid credential created');
                isRegisteringPasskey = false;
                return;
            }
            
            const response = credential.response as AuthenticatorAttestationResponse;
            
            // Step 4: Check PRF extension support (CRITICAL for zero-knowledge encryption)
            const clientExtensionResults = credential.getClientExtensionResults();
            console.log('[Signup] Client extension results:', clientExtensionResults);
            const prfResults = clientExtensionResults?.prf as any;
            console.log('[Signup] PRF results:', prfResults);
            
            // CRITICAL: PRF must be enabled for zero-knowledge encryption
            if (!prfResults) {
                console.error('[Signup] PRF extension not found in client extension results', {
                    clientExtensionResults,
                    hasPrf: !!clientExtensionResults?.prf
                });
                dispatch('step', { step: 'passkey_prf_error' });
                isRegisteringPasskey = false;
                return;
            }
            
            // Check if PRF is explicitly disabled
            if (prfResults.enabled === false) {
                console.error('[Signup] PRF extension explicitly disabled', {
                    prfResults,
                    enabled: prfResults.enabled
                });
                dispatch('step', { step: 'passkey_prf_error' });
                isRegisteringPasskey = false;
                return;
            }
            
            // Extract PRF signature (first result) - handle both ArrayBuffer and hex string formats
            const prfSignatureBuffer = prfResults.results?.first;
            if (!prfSignatureBuffer) {
                console.error('[Signup] PRF signature not found in results', {
                    prfResults,
                    hasResults: !!prfResults.results,
                    resultsKeys: prfResults.results ? Object.keys(prfResults.results) : []
                });
                dispatch('step', { step: 'passkey_prf_error' });
                isRegisteringPasskey = false;
                return;
            }
            
            // Convert PRF signature to Uint8Array - handle both formats
            let prfSignature: Uint8Array;
            if (typeof prfSignatureBuffer === 'string') {
                // Hex string format
                console.log('[Signup] PRF signature is hex string, converting to Uint8Array');
                const hexString = prfSignatureBuffer;
                prfSignature = new Uint8Array(hexString.match(/.{1,2}/g)!.map(byte => parseInt(byte, 16)));
            } else if (prfSignatureBuffer instanceof ArrayBuffer) {
                // ArrayBuffer format
                console.log('[Signup] PRF signature is ArrayBuffer, converting to Uint8Array');
                prfSignature = new Uint8Array(prfSignatureBuffer);
            } else if (ArrayBuffer.isView(prfSignatureBuffer)) {
                // TypedArray format
                console.log('[Signup] PRF signature is TypedArray, converting to Uint8Array');
                prfSignature = new Uint8Array(prfSignatureBuffer.buffer, prfSignatureBuffer.byteOffset, prfSignatureBuffer.byteLength);
            } else {
                console.error('[Signup] PRF signature is in unknown format', {
                    type: typeof prfSignatureBuffer,
                    constructor: prfSignatureBuffer?.constructor?.name,
                    value: prfSignatureBuffer
                });
                dispatch('step', { step: 'passkey_prf_error' });
                isRegisteringPasskey = false;
                return;
            }
            
            // Validate PRF signature length (should be 32 bytes for SHA-256)
            if (prfSignature.length < 16 || prfSignature.length > 64) {
                console.error('[Signup] PRF signature has invalid length', {
                    length: prfSignature.length,
                    expected: '16-64 bytes'
                });
                dispatch('step', { step: 'passkey_prf_error' });
                isRegisteringPasskey = false;
                return;
            }
            
            console.log('[Signup] PRF signature validated successfully', {
                length: prfSignature.length,
                enabled: prfResults.enabled,
                firstBytes: Array.from(prfSignature.slice(0, 4))
            });
            
            // Step 5: Generate master key and email salt (same as password flow)
            const masterKey = await cryptoService.generateExtractableMasterKey();
            const emailSalt = cryptoService.generateEmailSalt();
            const emailSaltB64 = cryptoService.uint8ArrayToBase64(emailSalt);
            
            // Step 6: Derive wrapping key from PRF signature using HKDF
            const wrappingKey = await cryptoService.deriveWrappingKeyFromPRF(prfSignature, emailSalt);
            
            // Step 7: Wrap the master key for server storage
            const { wrapped: encryptedMasterKey, iv: keyIv } = await cryptoService.encryptKey(masterKey, wrappingKey);
            
            // Step 8: Save master key (respect "stay logged in" choice)
            await cryptoService.saveKeyToSession(masterKey, storeData.stayLoggedIn);
            
            // Step 9: Generate lookup hash from PRF signature (for authentication)
            const lookupHash = await cryptoService.hashKeyFromPRF(prfSignature, emailSalt);
            
            // Step 10: Derive email encryption key
            const emailEncryptionKey = await cryptoService.deriveEmailEncryptionKey(storeData.email, emailSalt);
            
            // Step 11: Store email encryption key and salt
            cryptoService.saveEmailEncryptionKey(emailEncryptionKey, storeData.stayLoggedIn);
            cryptoService.saveEmailSalt(emailSalt, storeData.stayLoggedIn);
            
            // Step 12: Encrypt email for server storage (encrypted with email_encryption_key)
            const encryptedEmailForServer = await cryptoService.encryptEmail(storeData.email, emailEncryptionKey);
            
            // Step 13: Encrypt email with master key for server storage (for passwordless login)
            // This allows the server to return encrypted email that client can decrypt with master key
            const { encryptWithMasterKeyDirect } = await import('../../../../services/cryptoService');
            const encryptedEmailWithMasterKey = await encryptWithMasterKeyDirect(storeData.email, masterKey);
            if (!encryptedEmailWithMasterKey) {
                console.error('Failed to encrypt email with master key for server storage');
                isRegisteringPasskey = false;
                return;
            }
            
            // Step 13.5: Generate and encrypt device name for passkey
            const deviceName = generateDeviceName();
            const encryptedDeviceName = await encryptWithMasterKeyDirect(deviceName, masterKey);
            if (!encryptedDeviceName) {
                console.warn('Failed to encrypt device name, continuing without it');
            }
            
            // Step 14: Encrypt email with master key for client storage (IndexedDB)
            const emailStoredSuccessfully = await cryptoService.saveEmailEncryptedWithMasterKey(storeData.email, storeData.stayLoggedIn);
            if (!emailStoredSuccessfully) {
                console.error('Failed to encrypt and store email with master key');
                isRegisteringPasskey = false;
                return;
            }
            
            // Step 15: Extract credential data for backend
            const credentialId = arrayBufferToBase64Url(credential.rawId);
            const clientDataJSON = new TextDecoder().decode(response.clientDataJSON);
            const clientDataJSONB64 = cryptoService.uint8ArrayToBase64(new Uint8Array(response.clientDataJSON));
            const attestationObject = new Uint8Array(response.attestationObject);
            const attestationObjectB64 = cryptoService.uint8ArrayToBase64(attestationObject);
            
            // Extract authenticator data (simplified - backend should parse CBOR)
            const authenticatorData = attestationObject.slice(0, 37);
            const authenticatorDataB64 = cryptoService.uint8ArrayToBase64(authenticatorData);
            
            // Step 16: Complete passkey registration with backend
            const completeResponse = await fetch(getApiEndpoint(apiEndpoints.auth.passkey_registration_complete), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    credential_id: credentialId,
                    attestation_response: {
                        attestationObject: attestationObjectB64,
                        publicKey: {}
                    },
                    client_data_json: clientDataJSONB64,
                    authenticator_data: authenticatorDataB64,
                    hashed_email: hashedEmail,
                    username: storeData.username,
                    invite_code: requireInviteCodeValue ? storeData.inviteCode : "",
                    encrypted_email: encryptedEmailForServer,
                    encrypted_email_with_master_key: encryptedEmailWithMasterKey, // For passwordless login
                    encrypted_device_name: encryptedDeviceName || null, // Encrypted device name (client-side encrypted)
                    user_email_salt: emailSaltB64,
                    encrypted_master_key: encryptedMasterKey,
                    key_iv: keyIv,
                    salt: emailSaltB64,
                    lookup_hash: lookupHash,
                    language: storeData.language || 'en',
                    darkmode: storeData.darkmode || false,
                    prf_enabled: true
                }),
                credentials: 'include'
            });
            
            if (!completeResponse.ok) {
                const errorData = await completeResponse.json();
                console.error('Passkey registration completion failed:', errorData);
                isRegisteringPasskey = false;
                return;
            }
            
            const completeData = await completeResponse.json();
            
            if (!completeData.success) {
                console.error('Passkey registration failed:', completeData.message);
                isRegisteringPasskey = false;
                return;
            }
            
            // Step 16: Update signup store and clear sensitive data
            signupStore.update(store => ({
                ...store,
                encryptedMasterKey: encryptedMasterKey,
                salt: emailSaltB64,
                userId: completeData.user?.id,
                loginMethod: 'passkey'
            }));

            // Clear sensitive data from store
            signupStore.update(store => ({
                ...store,
                username: '',
                inviteCode: '',
                email: ''
            }));

            // CRITICAL: Update authentication state after account creation
            // This ensures that when we move to the next step, last_opened will be updated
            // both client-side and server-side (via WebSocket)
            // Poll to verify user is authenticated and data is loaded rather than using delays
            console.debug('[SecureAccountTopContent] Updating auth state after passkey account creation...');
            try {
                // Poll to verify authentication and user data is loaded
                const authSuccess = await pollAuthState(5, 2000); // 5 attempts, 2 seconds total
                if (authSuccess) {
                    console.debug('[SecureAccountTopContent] Auth state updated successfully');
                } else {
                    console.warn('[SecureAccountTopContent] Auth state not confirmed after polling - user data may not be fully loaded');
                    // Still continue - user data will be loaded on next checkAuth call or page reload
                }
            } catch (error) {
                console.warn('[SecureAccountTopContent] Failed to update auth state:', error);
                // Continue even if checkAuth fails - the step change will still work
                // User data will be loaded on next checkAuth call or page reload
            }

            // Continue to next step (skip to recovery key for passkeys)
            // The Signup component will update last_opened when this step change is processed
            dispatch('step', { step: 'recovery_key' });
            
        } catch (error) {
            console.error('Error registering passkey:', error);
            isRegisteringPasskey = false;
        }
    }
    
    /**
     * Handle selection of login method (password or passkey)
     * For passkey, immediately triggers registration
     */
    function selectOption(option: string) {
        if (option === 'password') {
            selectedOption = option;
            signupStore.update(store => ({ ...store, loginMethod: 'password' }));
            userDB.updateUserData({ login_method: option })
                .catch(error => {
                    console.error("Error storing login method:", error);
                });
            dispatch('step', { step: 'password' });
        } else if (option === 'passkey') {
            // Immediately trigger passkey registration
            registerPasskey();
        }
    }
</script>

<div class="content">
    <div class="signup-header">
        <div class="icon header_size secret"></div>
        <h2 class="signup-menu-title">{@html $text('signup.secure_your_account.text')}</h2>
    </div>

    <div class="options-container">
        <p class="instruction-text">{@html $text('signup.how_to_login.text')}</p>
        
        <!-- Passkey Option -->
        <div class="option-wrapper">
            <div class="recommended-badge">
                <div class="thumbs-up-icon"></div>
                <span>{@html $text('signup.recommended.text')}</span>
            </div>
            <button
                class="option-button"
                class:selected={selectedOption === 'passkey'}
                class:loading={isRegisteringPasskey}
                disabled={isRegisteringPasskey}
                onclick={() => selectOption('passkey')}
            >
                <div class="option-header">
                    <div class="option-icon">
                        <div class="clickable-icon icon_passkey" style="width: 30px; height: 30px"></div>
                    </div>
                    <div class="option-content">
                        <h3 class="option-title">{@html $text('signup.passkey.text')}</h3>
                    </div>
                </div>
                <p class="option-description">
                    {isRegisteringPasskey
                        ? $text('login.loading.text')
                        : $text('signup.passkey_descriptor.text')}
                </p>
            </button>
        </div>

        <!-- Password Option -->
        <button
            class="option-button"
            class:selected={selectedOption === 'password'}
            onclick={() => selectOption('password')}
        >
            <div class="option-header">
                <div class="option-icon">
                    <div class="clickable-icon icon_password" style="width: 30px; height: 30px"></div>
                </div>
                <div class="option-content">
                    <h3 class="option-title">{@html $text('signup.password.text')}</h3>
                </div>
            </div>
            <p class="option-description">{@html $text('signup.password_descriptor.text')}</p>
        </button>
    </div>
</div>

<style>
    .content {
        padding: 24px;
        height: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
    }
    
    .signup-header {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 16px;
        margin-bottom: 20px;
        margin-top: 20px;
    }
    
    .options-container {
        width: 100%;
        max-width: 400px;
        display: flex;
        flex-direction: column;
        gap: 16px;
        height: 100%;
        position: relative;
    }
    
    .instruction-text {
        color: var(--color-grey-60);
        font-size: 16px;
        text-align: center;
        margin-bottom: 8px;
    }
    
    .option-wrapper {
        position: relative;
        width: 100%;
        margin-top: 10px; /* Space for badge */
    }

    .recommended-badge {
        position: absolute;
        top: 0;
        left: 50%;
        transform: translate(-50%, -50%);
        background: var(--color-primary);
        border-radius: 19px;
        padding: 4px 10px;
        display: flex;
        align-items: center;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
        z-index: 2;
        white-space: nowrap;
    }

    .thumbs-up-icon {
        width: 12px;
        height: 12px;
        background-image: url('@openmates/ui/static/icons/thumbsup.svg');
        background-size: contain;
        background-repeat: no-repeat;
        filter: invert(1);
        margin-right: 5px;
    }
    
    .recommended-badge span {
        color: white;
        font-size: 12px;
        font-weight: 600;
    }

    .option-button {
        display: flex;
        flex-direction: column;
        gap: 5px;
        padding: 15px;
        background: var(--color-grey-20);
        border-radius: 16px;
        cursor: pointer;
        transition: all 0.2s ease;
        text-align: center;
        width: 100%;
        height: auto;
        border: none; /* Ensure no border by default */
        position: relative;
    }

    /* Add recommended style for passkey option */
    .option-wrapper:first-child .option-button {
        border: 3px solid transparent;
        background: linear-gradient(var(--color-grey-20), var(--color-grey-20)) padding-box,
                    var(--color-primary) border-box;
    }
    
    .option-button:disabled {
        cursor: not-allowed;
        opacity: 0.6;
    }
    
    .option-button.loading {
        cursor: wait;
    }
    
    .option-header {
        display: flex;
        align-items: center;
        gap: 16px;
    }
    
    .option-icon {
        flex-shrink: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        width: 48px;
        height: 48px;
        background: var(--color-grey-15);
        border-radius: 8px;
    }
    
    .option-button.selected .option-icon {
        background: var(--color-primary-20);
    }
    
    
    .option-content {
        flex: 1;
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    
    .option-title {
        font-size: 16px;
        font-weight: 600;
        color: var(--color-grey-80);
        margin: 0;
    }
    
    .option-description {
        font-size: 14px;
        color: var(--color-grey-60);
        margin: 0;
        line-height: 1.4;
    }
</style>
