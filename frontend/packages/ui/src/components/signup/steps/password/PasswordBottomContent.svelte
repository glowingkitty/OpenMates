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
    import { checkAuth, authStore } from '../../../../stores/authStore';
    import { userProfile } from '../../../../stores/userProfile';
    import { notificationStore } from '../../../../stores/notificationStore';
    import { 
        isChunkLoadError, 
        logChunkLoadError, 
        CHUNK_ERROR_MESSAGE, 
        CHUNK_ERROR_NOTIFICATION_DURATION 
    } from '../../../../utils/chunkErrorHandler';
    
    const dispatch = createEventDispatcher();
    
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
                console.warn(`[PasswordBottomContent] Auth state polling timeout after ${maxTimeoutMs}ms`);
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
                        console.debug(`[PasswordBottomContent] Auth state confirmed after ${attempt} attempt(s)`);
                        return true;
                    }
                }
                
                // If not authenticated yet, wait before next attempt (except on last attempt)
                if (attempt < maxAttempts) {
                    await new Promise(resolve => setTimeout(resolve, delayBetweenAttempts));
                }
            } catch (error) {
                console.warn(`[PasswordBottomContent] Error checking auth state (attempt ${attempt}/${maxAttempts}):`, error);
                // Wait before retrying (except on last attempt)
                if (attempt < maxAttempts) {
                    await new Promise(resolve => setTimeout(resolve, delayBetweenAttempts));
                }
            }
        }
        
        console.warn(`[PasswordBottomContent] Auth state not confirmed after ${maxAttempts} attempts`);
        return false;
    }
    
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
                notificationStore.error('Missing required signup information. Please go back and try again.', 8000);
                return;
            }
            
            // Generate extractable master key for wrapping (Web Crypto API)
            const masterKey = await cryptoService.generateExtractableMasterKey();
            const salt = cryptoService.generateSalt();

            // Derive wrapping key from password
            const wrappingKey = await cryptoService.deriveKeyFromPassword(password, salt);

            // Wrap the master key for server storage
            const { wrapped: encryptedMasterKey, iv: keyIv } = await cryptoService.encryptKey(masterKey, wrappingKey);

            // Save master key (respect "stay logged in" choice)
            // Extractable keys allow wrapping for recovery keys while still using Web Crypto API
            await cryptoService.saveKeyToSession(masterKey, storeData.stayLoggedIn);
            
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
                notificationStore.error('Failed to store encrypted data. Please try again.', 8000);
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
                // Handle specific error cases with user-friendly messages
                if (response.status === 400) {
                    // Handle validation errors
                    console.error('Validation error:', errorData.message);
                    notificationStore.error(errorData.message || 'Invalid data provided. Please check your information and try again.', 8000);
                } else if (response.status === 409) {
                    // Handle conflicts (e.g., email already exists)
                    console.error('Conflict error:', errorData.message);
                    notificationStore.error(errorData.message || 'This email is already registered. Please try logging in instead.', 8000);
                } else {
                    notificationStore.error(errorData.message || 'Failed to create account. Please try again.', 8000);
                }
                return;
            }
            
            const data = await response.json();
            
            if (data.success) {
                // CRITICAL: Verify that we received a valid user ID from the server
                // Without a user ID, the signup cannot continue as we can't establish the user session
                const newUserId = data.user?.id;
                if (!newUserId) {
                    console.error('Password setup succeeded but no user ID returned');
                    notificationStore.error('Account creation incomplete - please try again or contact support.', 8000);
                    return;
                }
                
                console.log(`[PasswordBottomContent] Account created successfully, user ID: ${newUserId.substring(0, 8)}...`);
                
                // Update the signup store with encrypted data and user info
                signupStore.update(store => ({
                    ...store,
                    password, // Store temporarily for the signup process
                    encryptedMasterKey: encryptedMasterKey,
                    salt: saltB64,
                    userId: newUserId
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
                
                // CRITICAL: Update authentication state after account creation
                // This ensures that when we move to the next step, last_opened will be updated
                // both client-side and server-side (via WebSocket)
                // We MUST verify auth state before advancing to prevent "false positive" signups
                console.debug('[PasswordBottomContent] Verifying auth state after account creation...');
                try {
                    // Poll to verify authentication and user data is loaded
                    const authSuccess = await pollAuthState(10, 4000); // 10 attempts, 4 seconds total
                    if (authSuccess) {
                        console.debug('[PasswordBottomContent] Auth state confirmed successfully');
                    } else {
                        // Auth state not confirmed - this is a CRITICAL error
                        // Don't advance to next step as the user might not be properly logged in
                        console.error('[PasswordBottomContent] Auth state not confirmed after polling - blocking step advancement');
                        notificationStore.error('Account created but login failed. Please try logging in manually.', 10000);
                        // User will need to try logging in manually or retry signup
                        return;
                    }
                } catch (error) {
                    // Auth check failed - this is a CRITICAL error
                    console.error('[PasswordBottomContent] Failed to verify auth state:', error);
                    notificationStore.error('Account may have been created but we could not verify login. Please try logging in.', 10000);
                    return;
                }
                
                // All validations passed - safe to advance to next step
                console.log('[PasswordBottomContent] All validations passed, advancing to one_time_codes step');
                
                // Continue to next step (OTP setup)
                // The Signup component will update last_opened when this step change is processed
                dispatch('step', { step: 'one_time_codes' });
            } else {
                console.error('Password setup failed:', data.message);
                notificationStore.error(data.message || 'Failed to create account. Please try again.', 8000);
            }
            
        } catch (error) {
            console.error('Error setting up password:', error);
            
            // Check for chunk loading errors (stale cache after deployment)
            // These happen when dynamic imports fail because old JS references non-existent chunks
            if (isChunkLoadError(error)) {
                logChunkLoadError('PasswordBottomContent', error);
                notificationStore.error(CHUNK_ERROR_MESSAGE, CHUNK_ERROR_NOTIFICATION_DURATION);
                return;
            }
            
            notificationStore.error('An unexpected error occurred during signup. Please try again.', 8000);
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
