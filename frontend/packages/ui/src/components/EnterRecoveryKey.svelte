<script lang="ts">
    /**
     * EnterRecoveryKey.svelte - Component for recovery key authentication
     * Handles recovery key input and submission to /login endpoint
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
    export let isLoading = false;
    export let errorMessage: string | null = null;

    // Form data
    let recoveryKey = '';
    let recoveryKeyInput: HTMLInputElement;

    // Validation - recovery keys are typically longer strings
    $: isRecoveryKeyValid = recoveryKey.length >= 32; // Minimum length for recovery keys

    // Handle recovery key input
    function handleRecoveryKeyInput(event: Event) {
        const input = event.target as HTMLInputElement;
        // Allow alphanumeric characters, hyphens, and underscores
        recoveryKey = input.value.replace(/[^A-Za-z0-9\-_]/g, '');
        input.value = recoveryKey;
    }

    // Handle form submission
    async function handleSubmit() {
        if (!isRecoveryKeyValid || isLoading) return;

        isLoading = true;
        errorMessage = null;

        try {
            // Generate hashed email for lookup
            const hashed_email = await cryptoService.hashEmail(email);
            
            // For recovery key login, we use the recovery key as the lookup hash
            // This is different from password login where we combine email+password
            const recoveryKeyBuffer = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(recoveryKey));
            const recoveryKeyArray = new Uint8Array(recoveryKeyBuffer);
            let recoveryKeyBinary = '';
            for (let i = 0; i < recoveryKeyArray.length; i++) {
                recoveryKeyBinary += String.fromCharCode(recoveryKeyArray[i]);
            }
            const lookup_hash = window.btoa(recoveryKeyBinary);

            // Send login request with recovery key
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
                    // Recovery key login doesn't require additional parameters
                }),
                credentials: 'include'
            });

            const data = await response.json();

            if (response.ok && data.success) {
                // Recovery key login successful
                await handleSuccessfulLogin(data);
            } else {
                errorMessage = data.message || 'Invalid recovery key';
            }
        } catch (error) {
            console.error('Recovery key login error:', error);
            errorMessage = 'An error occurred during recovery key verification';
        } finally {
            isLoading = false;
        }
    }

    // Handle successful login
    async function handleSuccessfulLogin(data: any) {
        // For recovery key login, the master key should already be decrypted by the server
        // or we need to handle it differently since we don't have the password
        if (data.user) {
            try {
                // Update user profile with received data
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
                
                // Check if user is in signup flow based on last_opened path
                const inSignupFlow = data.user?.last_opened?.startsWith('/signup/') || false;
                console.debug('Login success (recovery key), in signup flow:', inSignupFlow);
                
                // Clear sensitive data
                recoveryKey = '';
                
                // Dispatch success event
                dispatch('loginSuccess', {
                    user: data.user,
                    inSignupFlow: inSignupFlow,
                    recoveryKeyUsed: true
                });
            } catch (e) {
                console.error('Error during recovery key login processing:', e);
                errorMessage = 'Error processing recovery key login. Please try again.';
            }
        } else {
            // If no user data, show error
            errorMessage = 'Invalid recovery key or server error.';
        }
    }

    // Handle back to email
    function handleBackToEmail() {
        dispatch('backToEmail');
    }

    // Handle switch to password and TFA
    function handleSwitchToPasswordAndTfa() {
        // Use the same event name as EnterBackupCode component
        // This will make the parent component switch to the password step
        dispatch('switchToOtp');
    }

    // Focus input when component mounts
    import { onMount } from 'svelte';
    let isTouchDevice = false;

    onMount(() => {
        isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
        if (recoveryKeyInput && !isTouchDevice) {
            recoveryKeyInput.focus();
        }
    });
</script>

<div class="recovery-key-login" in:fade={{ duration: 300 }}>
    <p class="recovery-key-text">
        {@html $text('login.use_for_emergencies_only.text')}
    </p>

    <form on:submit|preventDefault={handleSubmit}>
        <div class="input-group">
            <div class="input-wrapper">
                <span class="clickable-icon icon_warning"></span>
                <input
                    bind:this={recoveryKeyInput}
                    type="password"
                    bind:value={recoveryKey}
                    on:input={handleRecoveryKeyInput}
                    placeholder={$text('login.recoverykey_placeholder.text')}
                    autocomplete="off"
                    class:error={!!errorMessage}
                    style="font-family: monospace;"
                />
                {#if errorMessage}
                    <InputWarning
                        message={errorMessage}
                        target={recoveryKeyInput}
                    />
                {/if}
            </div>
        </div>

        <button
            type="submit"
            class="login-button"
            disabled={isLoading || !isRecoveryKeyValid}
        >
            {#if isLoading}
                <span class="loading-spinner"></span>
            {:else}
                {$text('login.login_button.text')}
            {/if}
        </button>
    </form>

    <!-- Login options container -->
    <div class="login-options-container">
        <!-- Back to email button -->
        <div>
            <button class="login-option-button" on:click={handleBackToEmail}>
                <span class="clickable-icon icon_user"></span>
                <mark>{$text('login.login_with_another_account.text')}</mark>
            </button>
        </div>

        <!-- Login with password and TFA button -->
        <div>
            <button class="login-option-button" on:click={handleSwitchToPasswordAndTfa}>
                <span class="clickable-icon icon_password"></span>
                <mark>{$text('login.login_with_password_and_tfa.text')}</mark>
            </button>
        </div>
    </div>
</div>

<style>
    .recovery-key-login {
        display: flex;
        flex-direction: column;
        width: 100%;
    }

    .recovery-key-text {
        margin: 0 0 20px 0;
        color: var(--color-grey-60);
        line-height: 1.5;
        text-align: center;
    }

    .login-button {
        margin: 20px 0px 10px 0px;
    }

    .login-options-container {
        display: flex;
        flex-direction: column;
        align-self: center;
        width: fit-content;
    }

    .login-option-button {
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 0px 0px;
        background: none;
        border: none;
        cursor: pointer;
        filter: none;
    }

    .login-option-button .clickable-icon {
        margin-right: 8px;
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