<script lang="ts">
    /**
     * EnterBackupCode.svelte - Component for backup code authentication
     * Handles backup code input and submission to /login endpoint
     */
    import { createEventDispatcher } from 'svelte';
    import { fade } from 'svelte/transition';
    import { text } from '@repo/ui';
    import InputWarning from './common/InputWarning.svelte';
    import { getApiEndpoint, apiEndpoints } from '../config/api';
    import * as cryptoService from '../services/cryptoService';
    import { updateProfile } from '../stores/userProfile';

    const dispatch = createEventDispatcher();

    // Props
    export let email = '';
    export let password = '';
    export let stayLoggedIn = false;
    export let isLoading = false;
    export let errorMessage: string | null = null;

    // Form data
    let backupCode = '';
    let backupCodeInput: HTMLInputElement;

    // Validation
    $: isBackupCodeValid = backupCode.length === 14 && backupCode.includes('-'); // Format: XXXX-XXXX-XXXX

    // Dispatch activity when backup code changes
    $: if (backupCode) {
        dispatch('userActivity');
    }

    // Handle backup code input formatting
    function handleBackupCodeInput(event: Event) {
        const input = event.target as HTMLInputElement;
        let value = input.value.replace(/[^A-Za-z0-9]/g, '').toUpperCase(); // Remove non-alphanumeric and convert to uppercase
        
        // Add dashes at positions 4 and 9
        if (value.length > 4) {
            value = value.slice(0, 4) + '-' + value.slice(4);
        }
        if (value.length > 9) {
            value = value.slice(0, 9) + '-' + value.slice(9);
        }
        
        // Limit to 14 characters (XXXX-XXXX-XXXX)
        value = value.slice(0, 14);
        
        backupCode = value;
        input.value = value;
        
        // Dispatch activity event on input
        dispatch('userActivity');
    }

    // Handle form submission
    async function handleSubmit() {
        if (!isBackupCodeValid || isLoading) return;

        isLoading = true;
        errorMessage = null;

        try {
            // Generate hashed email and lookup hash
            const hashed_email = await cryptoService.hashEmail(email);
            
            // Generate lookup hash (email + password)
            const emailPasswordCombined = `${email}${password}`;
            const lookupHashBuffer = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(emailPasswordCombined));
            const lookupHashArray = new Uint8Array(lookupHashBuffer);
            let lookupHashBinary = '';
            for (let i = 0; i < lookupHashArray.length; i++) {
                lookupHashBinary += String.fromCharCode(lookupHashArray[i]);
            }
            const lookup_hash = window.btoa(lookupHashBinary);

            // Send login request with backup code
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.login), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'Origin': window.location.origin
                },
                body: JSON.stringify({
                    hashed_email,
                    lookup_hash,
                    tfa_code: backupCode,
                    code_type: 'backup'
                }),
                credentials: 'include'
            });

            const data = await response.json();

            if (response.ok && data.success) {
                // Login successful with backup code
                await handleSuccessfulLogin(data);
            } else {
                if (data.message === 'login.code_wrong.text') {
                    errorMessage = $text('login.code_wrong.text');
                } else {
                    errorMessage = data.message || $text('login.code_wrong.text');
                }
            }
        } catch (error) {
            console.error('Backup code login error:', error);
            errorMessage = 'An error occurred during backup code verification';
        } finally {
            isLoading = false;
        }
    }

    // Handle successful login
    async function handleSuccessfulLogin(data: any) {
        // Decrypt and save master key
        if (data.user && data.user.encrypted_key && data.user.salt) {
            try {
                const saltString = atob(data.user.salt);
                const salt = new Uint8Array(saltString.length);
                for (let i = 0; i < saltString.length; i++) {
                    salt[i] = saltString.charCodeAt(i);
                }
                const wrappingKey = await cryptoService.deriveKeyFromPassword(password, salt);
                const masterKey = cryptoService.decryptKey(data.user.encrypted_key, wrappingKey);

                if (masterKey) {
                    cryptoService.saveKeyToSession(masterKey, stayLoggedIn);
                    console.debug('Master key decrypted and saved to session/local storage.');
                    
                    // Update user profile with received data
                    if (data.user) {
                        const userProfileData = {
                            username: data.user.username || '',
                            profile_image_url: data.user.profile_image_url || null,
                            credits: data.user.credits || 0,
                            is_admin: data.user.is_admin || false,
                            last_opened: data.user.last_opened || '',
                            tfa_app_name: data.user.tfa_app_name || null,
                            tfa_enabled: data.user.tfa_enabled || false,
                            consent_privacy_and_apps_default_settings: data.user.consent_privacy_and_apps_default_settings || false,
                            consent_mates_default_settings: data.user.consent_mates_default_settings || false,
                            language: data.user.language || 'en',
                            darkmode: data.user.darkmode || false
                        };
                        
                        // Update the user profile store
                        updateProfile(userProfileData);
                        console.debug('User profile updated with login data:', userProfileData);
                    }
                    
                    // Check if user is in signup flow based on last_opened path
                    const inSignupFlow = data.user?.last_opened?.startsWith('/signup/') || false;
                    console.debug('Login success (backup code), in signup flow:', inSignupFlow);
                    
                    // Clear sensitive data
                    password = '';
                    backupCode = '';
                    
                    // Dispatch success event
                    dispatch('loginSuccess', {
                        user: data.user,
                        inSignupFlow: inSignupFlow,
                        backupCodeUsed: true
                    });
                } else {
                    errorMessage = 'Failed to decrypt master key. Please try again.';
                }
            } catch (e) {
                console.error('Error during key decryption:', e);
                errorMessage = 'Error during key decryption. Please try again.';
            }
        }
    }

    // Handle back to email
    function handleBackToEmail() {
        dispatch('backToEmail');
    }

    // Handle switch back to OTP
    function handleSwitchToOtp() {
        dispatch('switchToOtp', { email, password, stayLoggedIn });
    }

    // Focus input when component mounts
    import { onMount } from 'svelte';
    let isTouchDevice = false;

    onMount(() => {
        isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
        if (backupCodeInput && !isTouchDevice) {
            backupCodeInput.focus();
        }
    });
</script>

<div class="backup-code-login" in:fade={{ duration: 300 }}>
    <div class="backup-code-section">
        <p class="backup-code-text">
            {@html $text('login.enter_backup_code_description.text')}
        </p>

        <form on:submit|preventDefault={handleSubmit}>
            <div class="input-group">
                <div class="input-wrapper">
                    <span class="clickable-icon icon_2fa"></span>
                    <input
                        bind:this={backupCodeInput}
                        type="text"
                        bind:value={backupCode}
                        on:input={handleBackupCodeInput}
                        placeholder="XXXX-XXXX-XXXX"
                        maxlength="14"
                        autocomplete="one-time-code"
                        class:error={!!errorMessage}
                        style="font-family: monospace; letter-spacing: 0.1em;"
                    />
                    {#if errorMessage}
                        <InputWarning 
                            message={errorMessage} 
                            target={backupCodeInput} 
                        />
                    {/if}
                </div>
            </div>

            <button 
                type="submit" 
                class="login-button" 
                disabled={isLoading || !isBackupCodeValid} 
            >
                {#if isLoading}
                    <span class="loading-spinner"></span>
                {:else}
                    {$text('login.login_button.text')}
                {/if}
            </button>
        </form>

        <div class="backup-code-options">
            <button class="text-button" on:click={handleSwitchToOtp}>
                {$text('login.use_authenticator_app.text')}
            </button>
        </div>
    </div>

    <!-- Back to email button -->
    <div class="back-to-email">
        <button class="text-button" on:click={handleBackToEmail}>
            {$text('login.login_with_another_account.text')}
        </button>
    </div>
</div>

<style>
    .backup-code-login {
        display: flex;
        flex-direction: column;
        width: 100%;
    }

    .backup-code-section {
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
    }

    .backup-code-text {
        margin: 0 0 20px 0;
        color: var(--color-grey-60);
        line-height: 1.5;
    }

    .backup-code-options {
        margin-top: 20px;
    }

    .back-to-email {
        margin-top: 20px;
        text-align: center;
    }

    .loading-spinner {
        border: 3px solid rgba(255, 255, 255, 0.3);
        border-radius: 50%;
        border-top: 3px solid white;
        width: 18px;
        height: 18px;
        animation: spin 1s linear infinite;
    }

    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
</style>