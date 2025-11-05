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
    import { getSessionId } from '../utils/sessionId';

    const dispatch = createEventDispatcher();

    // Props using Svelte 5 runes
    let { 
        email = '',
        password = '',
        stayLoggedIn = false,
        isLoading = $bindable(false),
        errorMessage = null
    }: {
        email?: string;
        password?: string;
        stayLoggedIn?: boolean;
        isLoading?: boolean;
        errorMessage?: string | null;
    } = $props();

    // Form data
    let backupCode = $state('');
    let backupCodeInput: HTMLInputElement = $state();

    // Validation using Svelte 5 runes
    let isBackupCodeValid = $derived(backupCode.length === 14 && backupCode.includes('-')); // Format: XXXX-XXXX-XXXX

    // Dispatch activity when backup code changes using Svelte 5 runes
    $effect(() => {
        if (backupCode) {
            dispatch('userActivity');
        }
    });

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
        
        // Dispatch activity events whenever input changes
        dispatch('tfaActivity');
        dispatch('userActivity');
    }

    // Handle form submission
    async function handleSubmit(event) {
        // Prevent default form submission behavior
        event.preventDefault();
        if (!isBackupCodeValid || isLoading) return;

        isLoading = true;
        errorMessage = null;

        try {
            // Generate hashed email and lookup hash
            const hashed_email = await cryptoService.hashEmail(email);
            
            // Generate lookup hash (password + salt)
            // According to security.md: lookup_hash = SHA256(login_secret + salt)
            // We need to use the user_email_salt as the salt for the lookup hash
            const userEmailSalt = cryptoService.getEmailSalt();
            
            if (!userEmailSalt) {
                console.error('Email salt not found in storage. Cannot generate lookup hash.');
                errorMessage = 'Authentication data not found. Please try logging in again.';
                isLoading = false;
                return;
            }
            
            // Use the hashKey function from cryptoService which properly handles salt
            const lookup_hash = await cryptoService.hashKey(password, userEmailSalt);

            // Get email encryption key for zero-knowledge email decryption
            const email_encryption_key = cryptoService.getEmailEncryptionKeyForApi();
            
            // Send login request with backup code and email encryption key
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
                    code_type: 'backup',
                    email_encryption_key, // Include client-derived key for email decryption
                    stay_logged_in: stayLoggedIn, // Send stay logged in preference
                    session_id: getSessionId() // Add sessionId for device fingerprint uniqueness
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
        // CRITICAL: Store WebSocket token FIRST before any auth state changes
        // This must happen before calling setAuthenticatedState to prevent race conditions
        if (data.ws_token) {
            const { setWebSocketToken } = await import('../utils/cookies');
            setWebSocketToken(data.ws_token);
            console.debug('[EnterBackupCode] WebSocket token stored from login response');
        } else {
            console.warn('[EnterBackupCode] No ws_token in login response - WebSocket connection may fail on Safari/iPad');
        }
        
        // Decrypt and save master key (Web Crypto API)
        if (data.user && data.user.encrypted_key && data.user.salt) {
            try {
                // Decode salt from base64
                const saltString = atob(data.user.salt);
                const salt = new Uint8Array(saltString.length);
                for (let i = 0; i < saltString.length; i++) {
                    salt[i] = saltString.charCodeAt(i);
                }

                // Derive wrapping key from password
                const wrappingKey = await cryptoService.deriveKeyFromPassword(password, salt);

                // Unwrap master key with IV (Web Crypto API)
                const keyIv = data.user.key_iv || ''; // IV for key unwrapping
                const masterKey = await cryptoService.decryptKey(data.user.encrypted_key, keyIv, wrappingKey);

                if (masterKey) {
                    // Save extractable master key to IndexedDB
                    // Extractable keys allow wrapping for recovery keys while still using Web Crypto API
                    await cryptoService.saveKeyToSession(masterKey);
                    console.debug('Master key unwrapped and saved to IndexedDB (extractable).');

                    // Save email encrypted with master key for payment processing
                    const emailStoredSuccessfully = await cryptoService.saveEmailEncryptedWithMasterKey(email, false);
                    if (!emailStoredSuccessfully) {
                        console.error('Failed to encrypt and store email with master key during backup code login');
                    } else {
                        console.debug('Email encrypted and stored with master key for payment processing');
                    }
                    
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
        // Clear all local and session storage to remove email encryption key and salt
        localStorage.clear();
        sessionStorage.clear();
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

        <form onsubmit={handleSubmit}>
            <div class="input-group">
                <div class="input-wrapper">
                    <span class="clickable-icon icon_2fa"></span>
                    <input
                        bind:this={backupCodeInput}
                        type="text"
                        bind:value={backupCode}
                        oninput={handleBackupCodeInput}
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
            <button class="text-button" onclick={handleSwitchToOtp}>
                {$text('login.use_authenticator_app.text')}
            </button>
        </div>
    </div>

    <!-- Back to email button -->
    <div class="back-to-email">
        <button class="text-button" onclick={handleBackToEmail}>
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