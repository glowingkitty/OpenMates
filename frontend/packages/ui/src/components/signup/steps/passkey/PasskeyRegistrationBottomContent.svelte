<script lang="ts">
    /**
     * Passkey Registration Bottom Content Component
     * 
     * Handles WebAuthn passkey registration flow:
     * 1. Initiates registration with backend
     * 2. Creates passkey using WebAuthn API
     * 3. Checks for PRF extension support (REQUIRED for zero-knowledge encryption)
     * 4. Derives wrapping key from PRF signature
     * 5. Wraps master key and completes registration
     * 
     * If PRF is not supported, dispatches to PRF error screen.
     */
    import { text } from '@repo/ui';
    import { fade } from 'svelte/transition';
    import { createEventDispatcher } from 'svelte';
    import { getWebsiteUrl, routes } from '../../../../config/links';
    import { getApiEndpoint, apiEndpoints } from '../../../../config/api';
    import { signupStore } from '../../../../stores/signupStore';
    import { requireInviteCode } from '../../../../stores/signupRequirements';
    import * as cryptoService from '../../../../services/cryptoService';
    import { get } from 'svelte/store';
    
    const dispatch = createEventDispatcher();
    
    let isLoading = $state(false);
    
    /**
     * Converts ArrayBuffer to base64url (WebAuthn format)
     */
    function arrayBufferToBase64Url(buffer: ArrayBuffer): string {
        const bytes = new Uint8Array(buffer);
        let binary = '';
        for (let i = 0; i < bytes.byteLength; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        // Convert to base64url (replace + with -, / with _, remove padding)
        return window.btoa(binary)
            .replace(/\+/g, '-')
            .replace(/\//g, '_')
            .replace(/=/g, '');
    }
    
    /**
     * Converts base64url to ArrayBuffer (WebAuthn format)
     */
    function base64UrlToArrayBuffer(base64url: string): ArrayBuffer {
        // Convert base64url to base64
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
    
    /**
     * Handle passkey registration button click
     */
    async function handleRegisterPasskey() {
        if (isLoading) return;
        
        try {
            isLoading = true;
            
            // Get stored signup data from previous steps
            const storeData = get(signupStore);
            const requireInviteCodeValue = get(requireInviteCode);
            
            // Validate required data
            if (!storeData.email || !storeData.username || (requireInviteCodeValue && !storeData.inviteCode)) {
                console.error('Missing required signup data');
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
                return;
            }
            
            const initiateData = await initiateResponse.json();
            
            if (!initiateData.success) {
                console.error('Passkey registration initiation failed:', initiateData.message);
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
                console.error('WebAuthn credential creation failed:', error);
                // Check if it's a PRF-related error or user cancellation
                if (error.name === 'NotSupportedError' || error.message?.includes('PRF')) {
                    // PRF not supported - show error screen
                    dispatch('step', { step: 'passkey_prf_error' });
                    return;
                }
                // Other errors (user cancellation, etc.)
                return;
            }
            
            if (!credential || !(credential instanceof PublicKeyCredential)) {
                console.error('Invalid credential created');
                return;
            }
            
            const response = credential.response as AuthenticatorAttestationResponse;
            
            // Step 4: Check PRF extension support (CRITICAL for zero-knowledge encryption)
            const clientExtensionResults = credential.getClientExtensionResults();
            const prfResults = clientExtensionResults?.prf as any;
            
            if (!prfResults || !prfResults.enabled) {
                // PRF not supported - show error screen
                console.error('PRF extension not supported by this authenticator');
                dispatch('step', { step: 'passkey_prf_error' });
                return;
            }
            
            // Extract PRF signature (first result)
            const prfSignatureBuffer = prfResults.results?.first;
            if (!prfSignatureBuffer) {
                console.error('PRF signature not found in results');
                dispatch('step', { step: 'passkey_prf_error' });
                return;
            }
            
            // Convert PRF signature to Uint8Array
            const prfSignature = new Uint8Array(prfSignatureBuffer);
            
            // Step 5: Generate master key and email salt (same as password flow)
            const masterKey = await cryptoService.generateExtractableMasterKey();
            const emailSalt = cryptoService.generateEmailSalt();
            const emailSaltB64 = cryptoService.uint8ArrayToBase64(emailSalt);
            
            // Step 6: Derive wrapping key from PRF signature using HKDF
            const wrappingKey = await cryptoService.deriveWrappingKeyFromPRF(prfSignature, emailSalt);
            
            // Step 7: Wrap the master key for server storage
            const { wrapped: encryptedMasterKey, iv: keyIv } = await cryptoService.encryptKey(masterKey, wrappingKey);
            
            // Step 8: Save master key to IndexedDB
            await cryptoService.saveKeyToSession(masterKey);
            
            // Step 9: Generate lookup hash from PRF signature (for authentication)
            const lookupHash = await cryptoService.hashKeyFromPRF(prfSignature, emailSalt);
            
            // Step 10: Derive email encryption key
            const emailEncryptionKey = await cryptoService.deriveEmailEncryptionKey(storeData.email, emailSalt);
            
            // Step 11: Store email encryption key and salt
            cryptoService.saveEmailEncryptionKey(emailEncryptionKey, storeData.stayLoggedIn);
            cryptoService.saveEmailSalt(emailSalt, storeData.stayLoggedIn);
            
            // Step 12: Encrypt email for server storage
            const encryptedEmailForServer = await cryptoService.encryptEmail(storeData.email, emailEncryptionKey);
            
            // Step 13: Encrypt email with master key for client storage
            const emailStoredSuccessfully = await cryptoService.saveEmailEncryptedWithMasterKey(storeData.email, storeData.stayLoggedIn);
            if (!emailStoredSuccessfully) {
                console.error('Failed to encrypt and store email with master key');
                return;
            }
            
            // Step 14: Extract credential data for backend
            const credentialId = arrayBufferToBase64Url(credential.rawId);
            const clientDataJSON = new TextDecoder().decode(response.clientDataJSON);
            const clientDataJSONB64 = cryptoService.uint8ArrayToBase64(new Uint8Array(response.clientDataJSON));
            const attestationObject = new Uint8Array(response.attestationObject);
            const attestationObjectB64 = cryptoService.uint8ArrayToBase64(attestationObject);
            
            // Extract authenticator data (first 37 bytes of attestationObject)
            // For now, we'll send the full attestationObject and let backend parse it
            // TODO: Parse CBOR to extract authenticator_data properly
            const authenticatorData = attestationObject.slice(0, 37); // Simplified
            const authenticatorDataB64 = cryptoService.uint8ArrayToBase64(authenticatorData);
            
            // Step 15: Complete passkey registration with backend
            const completeResponse = await fetch(getApiEndpoint(apiEndpoints.auth.passkey_registration_complete), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    credential_id: credentialId,
                    attestation_response: {
                        // Send minimal attestation data - backend will verify
                        attestationObject: attestationObjectB64,
                        publicKey: {} // Placeholder - backend should extract from attestationObject
                    },
                    client_data_json: clientDataJSONB64,
                    authenticator_data: authenticatorDataB64,
                    hashed_email: hashedEmail,
                    username: storeData.username,
                    invite_code: requireInviteCodeValue ? storeData.inviteCode : "",
                    encrypted_email: encryptedEmailForServer,
                    user_email_salt: emailSaltB64,
                    encrypted_master_key: encryptedMasterKey,
                    key_iv: keyIv,
                    salt: emailSaltB64, // Same as user_email_salt for passkeys
                    lookup_hash: lookupHash,
                    language: storeData.language || 'en',
                    darkmode: storeData.darkmode || false,
                    prf_enabled: true // Confirmed PRF is enabled
                }),
                credentials: 'include'
            });
            
            if (!completeResponse.ok) {
                const errorData = await completeResponse.json();
                console.error('Passkey registration completion failed:', errorData);
                return;
            }
            
            const completeData = await completeResponse.json();
            
            if (!completeData.success) {
                console.error('Passkey registration failed:', completeData.message);
                return;
            }
            
            // Step 16: Update signup store and clear sensitive data
            signupStore.update(store => ({
                ...store,
                encryptedMasterKey: encryptedMasterKey,
                salt: emailSaltB64,
                userId: completeData.user?.id
            }));

            // Clear sensitive data from store EXCEPT username (keep plaintext copy before it gets encrypted by backend)
            signupStore.update(store => ({
                ...store,
                inviteCode: '',
                email: '' // Remove plaintext email from store
            }));
            
            // Continue to next step (OTP setup)
            dispatch('step', { step: 'one_time_codes' });
            
        } catch (error) {
            console.error('Error registering passkey:', error);
        } finally {
            isLoading = false;
        }
    }
</script>

<div class="passkey-bottom-content" in:fade={{ duration: 300 }} out:fade={{ duration: 200 }}>
    <div class="action-button-container">
        <button 
            class="action-button signup-button" 
            class:loading={isLoading}
            disabled={isLoading}
            onclick={handleRegisterPasskey}
        >
            {isLoading ? $text('login.loading.text') : $text('signup.create_passkey.text')}
        </button>
    </div>
    
    <div class="passkey-info">
        <p class="passkey-text">
            {@html $text('signup.passkey_info.text')}
        </p>
    </div>
</div>

<style>
    .passkey-bottom-content {
        width: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 10px;
        padding-top: 0px;
    }
    
    .action-button-container {
        width: 100%;
        max-width: 400px;
        display: flex;
        justify-content: center;
    }
    
    .passkey-info {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 8px;
        text-align: center;
    }
    
    .passkey-text {
        font-size: 14px;
        color: var(--color-grey-60);
        margin: 0;
        line-height: 1.5;
    }
</style>

