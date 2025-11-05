<script lang="ts">
    /**
     * Password Bottom Content Component
     *
     * This component handles:
     * - Password submission and account creation
     * - Master key generation and storage
     * - Email encryption key generation and storage
     * - Email encryption with master key for client storage
     *
     * Security Flow:
     * 1. Generate master key and store it in session/local storage based on stayLoggedIn preference
     * 2. Generate email encryption key and store it in session/local storage
     * 3. Encrypt the email with the master key and store it in session/local storage
     * 4. Send the encrypted email (encrypted with email encryption key) to the server
     * 5. Remove plaintext email from the store after encryption
     *
     * After this step, components that need the email should decrypt it on demand
     * using cryptoService.getEmailDecryptedWithMasterKey() rather than accessing it from the store.
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
    import { replace } from 'lodash-es';
    
    const dispatch = createEventDispatcher();
    
    // Get password data from parent component using Svelte 5 runes
    let { 
        password = '',
        passwordRepeat = '',
        isFormValid = false
    }: {
        password?: string,
        passwordRepeat?: string,
        isFormValid?: boolean
    } = $props();
    
    // Create a local variable to track form validity
    // Update local variable when props change using Svelte 5 runes
    let localIsFormValid = $derived(isFormValid);
    
    let isLoading = $state(false);
    
    // Handle form submission
    async function handleContinue() {
        if (!localIsFormValid) return;
        
        try {
            isLoading = true;
            
            // Get stored signup data from previous steps
            const storeData = get(signupStore);
            const requireInviteCodeValue = get(requireInviteCode);
            
            // Only check for inviteCode if it's required
            if (!storeData.email || !storeData.username || (requireInviteCodeValue && !storeData.inviteCode)) {
                console.error('Missing required signup data');
                return;
            }
            
            // Generate extractable master key for wrapping (Web Crypto API)
            const masterKey = await cryptoService.generateExtractableMasterKey();
            const salt = cryptoService.generateSalt();

            // Derive wrapping key from password
            const wrappingKey = await cryptoService.deriveKeyFromPassword(password, salt);

            // Wrap the master key for server storage
            const { wrapped: encryptedMasterKey, iv: keyIv } = await cryptoService.encryptKey(masterKey, wrappingKey);

            // Save master key to IndexedDB as extractable for session use
            // Extractable keys allow wrapping for recovery keys while still using Web Crypto API
            await cryptoService.saveKeyToSession(masterKey);
            
            // Convert salt to base64 for storage
            let saltBinary = '';
            const saltLen = salt.byteLength;
            for (let i = 0; i < saltLen; i++) {
                saltBinary += String.fromCharCode(salt[i]);
            }
            const saltB64 = window.btoa(saltBinary);
            
            // Generate hashed email for lookup
            const hashedEmail = await cryptoService.hashEmail(storeData.email);
            
            // Generate email salt and derive email encryption key
            const emailSalt = cryptoService.generateEmailSalt();
            const emailSaltB64 = cryptoService.uint8ArrayToBase64(emailSalt);
            
            // Generate lookup hash from password using user_email_salt instead of a random salt
            // This makes authentication more efficient as we don't need to query encryption_keys
            const lookupHash = await cryptoService.hashKey(password, emailSalt);
            
            // Derive email encryption key (for server use)
            const emailEncryptionKey = await cryptoService.deriveEmailEncryptionKey(storeData.email, emailSalt);
            
            // Store the email encryption key on the client (for future server communication)
            cryptoService.saveEmailEncryptionKey(emailEncryptionKey, storeData.stayLoggedIn);
            
            // Store the email salt on the client (for recovery key and other authentication methods)
            cryptoService.saveEmailSalt(emailSalt, storeData.stayLoggedIn);
            
            // Encrypt the email with the email encryption key (for server storage)
            const encryptedEmailForServer = await cryptoService.encryptEmail(storeData.email, emailEncryptionKey);
            
            // Encrypt the email with the master key (for client storage)
            // CRITICAL: Must await this async function to ensure email is encrypted before proceeding
            const emailStoredSuccessfully = await cryptoService.saveEmailEncryptedWithMasterKey(storeData.email, storeData.stayLoggedIn);
            
            if (!emailStoredSuccessfully) {
                console.error('Failed to encrypt and store email with master key');
                return;
            }
            
            // Make API call to setup password and create user account
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.setup_password), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    hashed_email: hashedEmail, // Hashed email for lookup
                    encrypted_email: encryptedEmailForServer, // Client-side encrypted email
                    user_email_salt: emailSaltB64, // Salt for email encryption
                    username: storeData.username,
                    invite_code: requireInviteCodeValue ? storeData.inviteCode : "",
                    encrypted_master_key: encryptedMasterKey,
                    key_iv: keyIv, // IV for master key encryption (Web Crypto API)
                    salt: saltB64,
                    lookup_hash: lookupHash, // Hash of email + password
                    language: storeData.language || 'en',
                    darkmode: storeData.darkmode || false
                }),
                credentials: 'include'
            });
            
            if (!response.ok) {
                const errorData = await response.json();
                console.error('Password setup failed:', errorData);
                // Handle specific error cases
                if (response.status === 400) {
                    // Handle validation errors
                    console.error('Validation error:', errorData.message);
                } else if (response.status === 409) {
                    // Handle conflicts (e.g., email already exists)
                    console.error('Conflict error:', errorData.message);
                }
                return;
            }
            
            const data = await response.json();
            
            if (data.success) {
                // Update the signup store with encrypted data and user info
                signupStore.update(store => ({
                    ...store,
                    password, // Store temporarily for the signup process
                    encryptedMasterKey: encryptedMasterKey,
                    salt: saltB64,
                    userId: data.user?.id
                }));
                
                // Clear sensitive data from local variables
                password = '';
                passwordRepeat = '';
                
                // Clear sensitive basic information from the signup store for privacy
                // Email is now encrypted with master key in storage, so we can remove it from the store
                signupStore.update(store => ({
                    ...store,
                    username: '',
                    inviteCode: '',
                    email: '' // Remove plaintext email from store since it's now encrypted
                }));
                
                // Continue to next step (OTP setup)
                dispatch('step', { step: 'one_time_codes' });
            } else {
                console.error('Password setup failed:', data.message);
            }
            
        } catch (error) {
            console.error('Error setting up password:', error);
            // Handle network or other errors appropriately
        } finally {
            isLoading = false;
        }
    }
</script>

<div class="password-bottom-content" in:fade={{ duration: 300 }} out:fade={{ duration: 200 }}>
    <div class="action-button-container">
        <button 
            class="action-button signup-button" 
            class:loading={isLoading}
            disabled={!localIsFormValid || isLoading}
            onclick={handleContinue}
        >
            {isLoading ? $text('login.loading.text') : $text('signup.continue.text')}
        </button>
    </div>
    
    <div class="password-manager-info">
        <p class="password-manager-text">
            {$text('signup.dont_have_password_manager_yet.text')}<br>
            <a href="https://search.brave.com/search?q=best+password+manager" target="_blank" rel="noopener noreferrer" style="text-decoration: unset; color: unset;">
                <mark>{$text('signup.click_here_to_show_password_managers.text')}</mark>
            </a>
        </p>
    </div>
</div>

<style>
    .password-bottom-content {
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
    
    .password-manager-info {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 8px;
        text-align: center;
    }
    
    .password-manager-text {
        font-size: 14px;
        color: var(--color-grey-60);
        margin: 0;
        line-height: 1.5;
    }
</style>
