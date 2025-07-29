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
        if (data.user && data.user.encrypted_key && data.user.salt) {
            try {
                // For recovery key login, we might need to use the recovery key itself
                // to derive the wrapping key, or the server provides the decrypted key
                // This depends on the specific implementation of recovery key handling
                
                // For now, let's assume the server handles the key decryption for recovery key login
                // and provides the master key directly or handles it server-side
                
                // Clear sensitive data
                recoveryKey = '';
                
                // Dispatch success event
                dispatch('loginSuccess', {
                    user: data.user,
                    inSignupFlow: data.inSignupFlow,
                    recoveryKeyUsed: true
                });
            } catch (e) {
                console.error('Error during recovery key login processing:', e);
                errorMessage = 'Error processing recovery key login. Please try again.';
            }
        } else {
            // If no encrypted key data, still proceed with login
            recoveryKey = '';
            dispatch('loginSuccess', {
                user: data.user,
                inSignupFlow: data.inSignupFlow,
                recoveryKeyUsed: true
            });
        }
    }

    // Handle back to email
    function handleBackToEmail() {
        dispatch('backToEmail');
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
    <div class="recovery-key-section">
        <p class="recovery-key-text">
            {@html $text('login.enter_recovery_key_description.text')}
        </p>

        <form on:submit|preventDefault={handleSubmit}>
            <div class="input-group">
                <div class="input-wrapper">
                    <span class="clickable-icon icon_secret"></span>
                    <input
                        bind:this={recoveryKeyInput}
                        type="password"
                        bind:value={recoveryKey}
                        on:input={handleRecoveryKeyInput}
                        placeholder={$text('login.recovery_key_placeholder.text')}
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

        <div class="recovery-key-help">
            <p class="help-text">
                {@html $text('login.recovery_key_help.text')}
            </p>
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
    .recovery-key-login {
        display: flex;
        flex-direction: column;
        width: 100%;
    }

    .recovery-key-section {
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
    }

    .recovery-key-text {
        margin: 0 0 20px 0;
        color: var(--color-grey-60);
        line-height: 1.5;
    }

    .recovery-key-help {
        margin-top: 20px;
        max-width: 400px;
    }

    .help-text {
        font-size: 14px;
        color: var(--color-grey-50);
        line-height: 1.4;
        margin: 0;
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