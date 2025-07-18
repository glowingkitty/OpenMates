<script lang="ts">
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
    
    // Get password data from parent component
    export let password = '';
    export let passwordRepeat = '';
    export let isFormValid = false;
    
    // Create a local variable to track form validity
    let localIsFormValid = isFormValid;
    
    // Update local variable when props change
    $: {
        localIsFormValid = isFormValid;
    }
    
    let isLoading = false;
    
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
            
            // Generate master key and salt
            const masterKey = cryptoService.generateUserMasterKey();
            const salt = cryptoService.generateSalt();
            
            // Derive wrapping key from password
            const wrappingKey = await cryptoService.deriveKeyFromPassword(password, salt);
            
            // Encrypt (wrap) the master key
            const encryptedMasterKey = cryptoService.encryptKey(masterKey, wrappingKey);
            
            // Convert salt to base64 for storage
            let saltBinary = '';
            const saltLen = salt.byteLength;
            for (let i = 0; i < saltLen; i++) {
                saltBinary += String.fromCharCode(salt[i]);
            }
            const saltB64 = window.btoa(saltBinary);
            
            // Generate lookup hash (email + password)
            const emailPasswordCombined = `${storeData.email}${password}`;
            const lookupHashBuffer = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(emailPasswordCombined));
            const lookupHashArray = new Uint8Array(lookupHashBuffer);
            let lookupHashBinary = '';
            for (let i = 0; i < lookupHashArray.length; i++) {
                lookupHashBinary += String.fromCharCode(lookupHashArray[i]);
            }
            const lookupHash = window.btoa(lookupHashBinary);
            
            // Generate hashed email for lookup
            const hashedEmailBuffer = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(storeData.email));
            const hashedEmailArray = new Uint8Array(hashedEmailBuffer);
            let hashedEmailBinary = '';
            for (let i = 0; i < hashedEmailArray.length; i++) {
                hashedEmailBinary += String.fromCharCode(hashedEmailArray[i]);
            }
            const hashedEmail = window.btoa(hashedEmailBinary);
            
            // Make API call to setup password and create user account
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.setup_password), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    email: storeData.email, // Cleartext email
                    hashed_email: hashedEmail, // Hashed email for lookup
                    username: storeData.username,
                    invite_code: requireInviteCodeValue ? storeData.inviteCode : "",
                    encrypted_master_key: encryptedMasterKey,
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
            on:click={handleContinue}
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
