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
    import { getSessionId } from '../utils/sessionId';

    const dispatch = createEventDispatcher();

    // Props using Svelte 5 runes
    let { 
        email = '',
        isLoading = $bindable(false),
        errorMessage = null,
        stayLoggedIn = false
    }: {
        email?: string;
        isLoading?: boolean;
        errorMessage?: string | null;
        stayLoggedIn?: boolean;
    } = $props();

    // Form data
    let recoveryKey = $state('');
    let recoveryKeyInput: HTMLInputElement = $state();

    // Validation - recovery keys are typically longer strings using Svelte 5 runes
    let isRecoveryKeyValid = $derived(recoveryKey.length == 24);

    // Dispatch activity when recovery key changes using Svelte 5 runes
    $effect(() => {
        if (recoveryKey) {
            dispatch('userActivity');
        }
    });

    // Handle recovery key input
    function handleRecoveryKeyInput(event: Event) {
        const input = event.target as HTMLInputElement;
        // Allow alphanumeric characters and special characters used in recovery keys
        // Based on generateSecureRecoveryKey in cryptoService.ts
        recoveryKey = input.value.replace(/[^A-Za-z0-9\-_#=+&%$]/g, '');
        
        // Don't manually set input.value as it interferes with Svelte's binding
        // Let Svelte handle the DOM update through the binding
        
        // Dispatch activity event on input
        dispatch('userActivity');
    }

    // Handle form submission
    async function handleSubmit(event) {
        // Prevent default form submission behavior
        event.preventDefault();
        if (!isRecoveryKeyValid || isLoading) return;

        isLoading = true;
        errorMessage = null;

        try {
            // Generate hashed email for lookup
            const hashed_email = await cryptoService.hashEmail(email);
            
            // For recovery key login, we need to hash the recovery key with the user's email salt
            // This must match how it was generated during signup in RecoveryKeyTopContent.svelte
            const userEmailSalt = cryptoService.getEmailSalt();
            if (!userEmailSalt) {
                console.error('Email salt is required for recovery key login');
                errorMessage = 'Email salt not found. Please try logging in with email again.';
                return;
            }
            
            // Use the same hashKey function as during signup with the recovery key and user's email salt
            const lookup_hash = await cryptoService.hashKey(recoveryKey, userEmailSalt);

            // Get email encryption key for zero-knowledge email decryption
            const email_encryption_key = cryptoService.getEmailEncryptionKeyForApi();
            
            // Send login request with recovery key and email encryption key
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
                    email_encryption_key, // Include client-derived key for email decryption
                    login_method: 'recovery_key', // Explicitly indicate this is a recovery key login
                    session_id: getSessionId(), // Add sessionId for device fingerprint uniqueness
                    stay_logged_in: stayLoggedIn // Send stay logged in preference
                }),
                credentials: 'include'
            });

            const data = await response.json();

            if (response.ok && data.success) {
                // Recovery key login successful
                await handleSuccessfulLogin(data);
            } else {
                if (data.message === 'login.recovery_key_wrong.text') {
                    errorMessage = $text('login.recovery_key_wrong.text');
                } else {
                    errorMessage = data.message || $text('login.recovery_key_wrong.text');
                }
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
        // CRITICAL: Store WebSocket token FIRST before any auth state changes
        // This must happen before calling setAuthenticatedState to prevent race conditions
        if (data.ws_token) {
            const { setWebSocketToken } = await import('../utils/cookies');
            setWebSocketToken(data.ws_token);
            console.debug('[EnterRecoveryKey] WebSocket token stored from login response');
        } else {
            console.warn('[EnterRecoveryKey] No ws_token in login response - WebSocket connection may fail on Safari/iPad');
        }
        
        // Decrypt and save master key - similar to password login but using recovery key (Web Crypto API)
        if (data.user && data.user.encrypted_key && data.user.salt) {
            try {
                // Decode salt from base64
                const saltString = atob(data.user.salt);
                const salt = new Uint8Array(saltString.length);
                for (let i = 0; i < saltString.length; i++) {
                    salt[i] = saltString.charCodeAt(i);
                }

                // Use the recovery key to derive the wrapping key (similar to password)
                const wrappingKey = await cryptoService.deriveKeyFromPassword(recoveryKey, salt);

                // Unwrap master key with IV (Web Crypto API)
                const keyIv = data.user.key_iv || ''; // IV for key unwrapping
                const masterKey = await cryptoService.decryptKey(data.user.encrypted_key, keyIv, wrappingKey);

                if (masterKey) {
                    // Save extractable master key to IndexedDB
                    // Extractable keys allow wrapping for recovery keys while still using Web Crypto API
                    // Pass stayLoggedIn to ensure key is cleared on tab/browser close if user didn't check "Stay logged in"
                    await cryptoService.saveKeyToSession(masterKey, stayLoggedIn);
                    console.debug('Master key unwrapped with recovery key and saved to IndexedDB (extractable).');

                    // Save email encrypted with master key for payment processing
                    const emailStoredSuccessfully = await cryptoService.saveEmailEncryptedWithMasterKey(email, false);
                    if (!emailStoredSuccessfully) {
                        console.error('Failed to encrypt and store email with master key during recovery key login');
                    } else {
                        console.debug('Email encrypted and stored with master key for payment processing');
                    }
                    
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
                    // Import isSignupPath helper for checking signup paths
                    const { isSignupPath } = await import('../stores/signupState');
                    const inSignupFlow = isSignupPath(data.user?.last_opened) || false;
                    console.debug('Login success (recovery key), in signup flow:', inSignupFlow);
                    
                    // Clear sensitive data
                    recoveryKey = '';
                    
                    // Dispatch success event
                    dispatch('loginSuccess', {
                        user: data.user,
                        inSignupFlow: inSignupFlow,
                        recoveryKeyUsed: true
                    });
                } else {
                    errorMessage = 'Failed to decrypt master key with recovery key. Please verify your recovery key.';
                }
            } catch (e) {
                console.error('Error during recovery key login processing:', e);
                errorMessage = 'Error decrypting master key with recovery key. Please try again.';
            }
        } else {
            // If no user data or missing encryption data, show error
            errorMessage = 'Invalid recovery key or missing encryption data from server.';
        }
    }

    // Handle back to email
    function handleBackToEmail() {
        // Clear all local and session storage to remove email encryption key and salt
        localStorage.clear();
        sessionStorage.clear();
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
    <!-- Show email address above recovery key text -->
    <div class="email-display">
        <span class="color-grey-70">{email}</span>
    </div>

    <p class="recovery-key-text">
        {@html $text('login.use_for_emergencies_only.text')}
    </p>

    <form onsubmit={handleSubmit}>
        <div class="input-group">
            <div class="input-wrapper">
                <span class="clickable-icon icon_warning"></span>
                <input
                    bind:this={recoveryKeyInput}
                    type="password"
                    bind:value={recoveryKey}
                    oninput={handleRecoveryKeyInput}
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
            <button class="login-option-button" onclick={handleBackToEmail}>
                <span class="clickable-icon icon_user"></span>
                <mark>{$text('login.login_with_another_account.text')}</mark>
            </button>
        </div>

        <!-- Login with password and TFA button -->
        <div>
            <button class="login-option-button" onclick={handleSwitchToPasswordAndTfa}>
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

    .email-display {
        text-align: center;
        margin-bottom: 10px;
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