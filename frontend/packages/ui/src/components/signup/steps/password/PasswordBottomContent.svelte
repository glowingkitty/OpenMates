<script lang="ts">
    import { text } from '@repo/ui';
    import { fade } from 'svelte/transition';
    import { createEventDispatcher } from 'svelte';
    import { getWebsiteUrl, routes } from '../../../../config/links';
    import { getApiEndpoint, apiEndpoints } from '../../../../config/api';
    import { signupStore } from '../../../../stores/signupStore';
    import * as cryptoService from '../../../../services/cryptoService';
    import { get } from 'svelte/store';
    
    const dispatch = createEventDispatcher();
    
    // Get password data from parent component
    export let password = '';
    export let passwordRepeat = '';
    export let isFormValid = false;
    
    let isLoading = false;
    
    // Handle form submission
    async function handleContinue() {
        if (!isFormValid) return;
        
        try {
            isLoading = true;
            
            // Get stored signup data from previous steps
            const storeData = get(signupStore);
            if (!storeData.email || !storeData.username || !storeData.inviteCode) {
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
                    invite_code: storeData.inviteCode,
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
    
    function openPasswordManagerInfo() {
        // For now, open a generic link - this should be updated when the actual route is available
        window.open('https://search.brave.com/search?q=best+password+manager', '_blank');
    }
</script>

<div class="password-bottom-content" in:fade={{ duration: 300 }} out:fade={{ duration: 200 }}>
    <div class="action-button-container">
        <button 
            class="action-button continue-button" 
            class:loading={isLoading}
            disabled={!isFormValid || isLoading}
            on:click={handleContinue}
        >
            {isLoading ? $text('login.loading.text') : $text('signup.continue.text')}
        </button>
    </div>
    
    <div class="password-manager-info">
        <p class="password-manager-text">
            {@html $text('signup.dont_have_password_manager_yet.text', { 
                values: { 
                    password_manager_list_link: 'https://search.brave.com/search?q=best+password+manager' 
                } 
            })}
        </p>
    </div>
</div>

<style>
    .password-bottom-content {
        width: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 24px;
        padding-top: 20px;
    }
    
    .action-button-container {
        width: 100%;
        max-width: 400px;
        display: flex;
        justify-content: center;
    }
    
    .action-button {
        width: 100%;
        max-width: 300px;
        padding: 16px 24px;
        background: var(--color-primary);
        color: white;
        border: none;
        border-radius: 12px;
        font-size: 16px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.2s ease;
    }
    
    .action-button:hover:not(:disabled) {
        background: var(--color-primary-dark);
        transform: translateY(-1px);
    }
    
    .action-button:disabled {
        background: var(--color-grey-30);
        cursor: not-allowed;
        transform: none;
    }
    
    .action-button.loading {
        opacity: 0.6;
        cursor: not-allowed;
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
    
    .text-button {
        background: none;
        border: none;
        color: var(--color-primary);
        font-size: 14px;
        cursor: pointer;
        text-decoration: none;
        padding: 4px 0;
    }
    
    .text-button:hover {
        text-decoration: underline;
    }
</style>
