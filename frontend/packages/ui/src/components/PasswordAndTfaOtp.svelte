<script lang="ts">
    /**
     * PasswordAndTfaOtp.svelte - Component for password input with optional 2FA
     * Makes a single request to /login with all required data
     * Integrates Login2FA functionality for enhanced UX
     */
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import { fade } from 'svelte/transition';
    import { text } from '@repo/ui';
    import InputWarning from './common/InputWarning.svelte';
    import { getApiEndpoint, apiEndpoints } from '../config/api';
    import { tfaAppIcons } from '../config/tfa';
    import * as cryptoService from '../services/cryptoService';
    import { updateProfile } from '../stores/userProfile';
    import { getSessionId } from '../utils/sessionId';

    const dispatch = createEventDispatcher();

    // Props using Svelte 5 runes mode
    let { 
        email = '',
        isLoading = $bindable(false),
        errorMessage = null,
        tfaErrorMessage = null,
        stayLoggedIn = false,
        tfaAppName = null,
        previewMode = false,
        previewTfaAppName = 'Google Authenticator',
        tfa_required = true,
        highlight = []
    }: {
        email?: string,
        isLoading?: boolean,
        errorMessage?: string | null,
        tfaErrorMessage?: string | null,
        stayLoggedIn?: boolean,
        tfaAppName?: string | null,
        previewMode?: boolean,
        previewTfaAppName?: string,
        tfa_required?: boolean,
        highlight?: (
            'check-2fa' |
            'app-name' |
            'input-area' |
            'login-btn' |
            'login-with-another-account' |
            'login-with-backup-code' |
            'login-with-recoverykey'
        )[]
    } = $props();

    // Form data using Svelte 5 runes
    let password = $state('');
    let tfaCode = $state('');
    let isBackupMode = $state(false);

    // Input references using Svelte 5 runes
    let passwordInput: HTMLInputElement = $state();
    let tfaInput: HTMLInputElement = $state();

    // Add rate limiting state using Svelte 5 runes
    const RATE_LIMIT_DURATION = 120000; // 120 seconds in milliseconds
    let isRateLimited = $state(false);
    let rateLimitTimer: ReturnType<typeof setTimeout>;

    // TFA app display logic using Svelte 5 runes
    let currentAppIndex = $state(0);
    let animationInterval: number | null = null;
    let currentDisplayedApp = $state(previewMode ? previewTfaAppName : (tfaAppName || ''));
    const appNames = Object.keys(tfaAppIcons);

    // Get the icon class for the app name, or undefined if not found using Svelte 5 runes
    let tfaAppIconClass = $derived(currentDisplayedApp in tfaAppIcons ? tfaAppIcons[currentDisplayedApp] : undefined);

    // Reactive statements for backup mode using Svelte 5 runes
    let inputPlaceholder = $derived(isBackupMode ? $text('login.enter_backup_code.text') : $text('signup.enter_one_time_code.text'));
    let toggleButtonText = $derived(isBackupMode ? $text('login.login_with_tfa_app.text') : $text('login.login_with_backup_code.text'));
    let inputMaxLength = $derived(isBackupMode ? 14 : 6);

    // Validation using Svelte 5 runes
    let isPasswordValid = $derived(password.length > 0);
    let isTfaValid = $derived(!tfa_required || (isBackupMode ? tfaCode.length === 14 : tfaCode.length === 6));
    let isFormValid = $derived(isPasswordValid && isTfaValid);

    // Helper function to generate opacity style using Svelte 5 runes
    type HighlightableId = typeof highlight[number];
    let getStyle = $derived((id: HighlightableId) => `opacity: ${highlight.length === 0 || highlight.includes(id) ? 1 : 0.5}`);

    // Rate limiting functions
    function setRateLimitTimer(duration: number) {
        if (rateLimitTimer) clearTimeout(rateLimitTimer);
        rateLimitTimer = setTimeout(() => {
            isRateLimited = false;
            localStorage.removeItem('passwordTfaRateLimit');
        }, duration);
    }

    // Update the animation logic to stop when a selected app is provided using Svelte 5 runes
    $effect(() => {
        if (tfaAppName) {
            currentDisplayedApp = tfaAppName;
            if (animationInterval) clearInterval(animationInterval);
        } else if (previewMode) {
            if (animationInterval) clearInterval(animationInterval);
            animationInterval = setInterval(() => {
                currentAppIndex = (currentAppIndex + 1) % appNames.length;
                currentDisplayedApp = appNames[currentAppIndex];
            }, 4000) as unknown as number;
        } else {
            currentDisplayedApp = tfaAppName || (previewMode ? previewTfaAppName : '');
        }
    });

    // Start animation in preview mode if no app name is selected
    onMount(() => {
        if (previewMode && !tfaAppName) {
            animationInterval = setInterval(() => {
                currentAppIndex = (currentAppIndex + 1) % appNames.length;
                currentDisplayedApp = appNames[currentAppIndex];
            }, 4000) as unknown as number;
        } else {
            currentDisplayedApp = tfaAppName || (previewMode ? previewTfaAppName : '');
        }
        // Focus password input on mount if not preview mode
        if (!previewMode && passwordInput) {
            passwordInput.focus();
        }
        
        // Check if we're still rate limited on mount
        const rateLimitTimestamp = localStorage.getItem('passwordTfaRateLimit');
        if (rateLimitTimestamp) {
            const timeLeft = parseInt(rateLimitTimestamp) + RATE_LIMIT_DURATION - Date.now();
            if (timeLeft > 0) {
                isRateLimited = true;
                setRateLimitTimer(timeLeft);
            } else {
                localStorage.removeItem('passwordTfaRateLimit');
            }
        }
    });

    onDestroy(() => {
        if (animationInterval) clearInterval(animationInterval);
        if (rateLimitTimer) clearTimeout(rateLimitTimer);
    });

    // Handle form submission - makes single request to /login
    async function handleSubmit() {
        if (!isPasswordValid || (tfa_required && !isTfaValid) || isLoading) return;

        isLoading = true;
        errorMessage = null;
        tfaErrorMessage = null;

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
                return;
            }
            
            // Use the hashKey function from cryptoService which properly handles salt
            const lookup_hash = await cryptoService.hashKey(password, userEmailSalt);

            // Prepare request body
            const requestBody: any = {
                hashed_email,
                lookup_hash
            };

            // Add 2FA code if provided and required
            if (tfa_required && tfaCode) {
                requestBody.tfa_code = tfaCode;
                requestBody.code_type = isBackupMode ? 'backup' : 'otp';
            }
            
            // Add email encryption key for zero-knowledge email decryption
            const email_encryption_key = cryptoService.getEmailEncryptionKeyForApi();
            if (email_encryption_key) {
                requestBody.email_encryption_key = email_encryption_key;
            }

            // Add sessionId for device fingerprint uniqueness (multi-browser support)
            requestBody.session_id = getSessionId();

            // Send single login request
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.login), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'Origin': window.location.origin
                },
                body: JSON.stringify(requestBody),
                credentials: 'include'
            });

            // Check for rate limiting first
            if (response.status === 429) {
                console.warn("Rate limit hit for password/TFA login");
                isRateLimited = true;
                localStorage.setItem('passwordTfaRateLimit', Date.now().toString());
                setRateLimitTimer(RATE_LIMIT_DURATION);
                return;
            }

            const data = await response.json();

            if (response.ok && data.success) {
                // Login successful
                await handleSuccessfulLogin(data);
            } else {
                if (data.tfa_required) {
                    // Update local tfa_required state if server indicates it's needed
                    tfa_required = true;
                    // Show TFA-specific error message only for TFA field
                    if (data.message === 'login.code_wrong.text') {
                        tfaErrorMessage = $text('login.code_wrong.text');
                        errorMessage = null;
                    } else {
                        tfaErrorMessage = data.message || $text('login.code_wrong.text');
                        errorMessage = null;
                    }
                } else {
                    // Show password/email error for password field
                    if (data.message === 'login.email_or_password_wrong.text') {
                        errorMessage = $text('login.email_or_password_wrong.text');
                    } else {
                        errorMessage = data.message || $text('login.email_or_password_wrong.text');
                    }
                    tfaErrorMessage = null;
                }
            }
        } catch (error) {
            console.error('Login error:', error);
            errorMessage = 'An error occurred during login';
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
                    
                    // Save email encrypted with master key for payment processing
                    const emailStoredSuccessfully = cryptoService.saveEmailEncryptedWithMasterKey(email, stayLoggedIn);
                    if (!emailStoredSuccessfully) {
                        console.error('Failed to encrypt and store email with master key during login');
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
                    console.debug('Login success, in signup flow:', inSignupFlow);
                    
                    // Clear sensitive data
                    password = '';
                    tfaCode = '';
                    
                    // Dispatch success event
                    dispatch('loginSuccess', {
                        user: data.user,
                        inSignupFlow: inSignupFlow
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

    // Handle input for TFA code (supports both OTP and backup codes)
    function handleTfaInput(event: Event) {
        const input = event.target as HTMLInputElement;
        let value = input.value;

        if (isBackupMode) {
            // Allow letters, digits, hyphens. Convert to uppercase. Limit length.
            // Basic format XXXX-XXXX-XXXX
            value = value.toUpperCase().replace(/[^A-Z0-9-]/g, '');
            // Auto-add hyphens (simple approach)
            if (value.length === 4 || value.length === 9) {
                if (!value.endsWith('-')) {
                    value += '-';
                }
            }
            tfaCode = value.slice(0, 14); // Limit to XXXX-XXXX-XXXX format length
        } else {
            // Allow only digits and limit length for OTP
            tfaCode = value.replace(/\D/g, '').slice(0, 6);
        }
        
        input.value = tfaCode; // Ensure input reflects sanitized value

        // Dispatch activity events whenever input changes
        dispatch('tfaActivity');
        dispatch('userActivity');
    }

    // Function to toggle between OTP and Backup Code mode
    function toggleBackupMode() {
        isBackupMode = !isBackupMode;
        tfaCode = ''; // Clear input when switching modes
        errorMessage = null; // Clear error message
        tfaErrorMessage = null; // Clear TFA error message
        if (tfaInput) {
            tfaInput.focus(); // Re-focus input
        }
    }

    // Handle back to email
    function handleBackToEmail() {
        // Clear all local and session storage to remove email encryption key and salt
        localStorage.clear();
        sessionStorage.clear();
        dispatch('backToEmail');
    }

    // Handle switch to recovery key
    function handleSwitchToRecoveryKey() {
        dispatch('switchToRecoveryKey');
    }

    // Clear error message when user starts typing again and dispatch activity using Svelte 5 runes
    $effect(() => {
        if (tfaCode) {
            tfaErrorMessage = null;
            dispatch('userActivity');
        }
    });

    // Dispatch activity when password changes and clear password error using Svelte 5 runes
    $effect(() => {
        if (password) {
            errorMessage = null;
            dispatch('userActivity');
        }
    });
</script>

<div class="password-tfa-login" in:fade={{ duration: 300 }}>
    {#if isRateLimited}
        <div class="rate-limit-message" in:fade={{ duration: 200 }}>
            {$text('signup.too_many_requests.text')}
        </div>
    {:else}
        <!-- Combined password and 2FA form -->
        <form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
        <!-- Hidden username field for accessibility -->
        <input
            type="email"
            name="username"
            value={email}
            autocomplete="username"
            style="position: absolute; left: -9999px; opacity: 0; pointer-events: none;"
            tabindex="-1"
            readonly
        />

        <!-- Show email address above password input -->
        <div class="email-display">
            <span class="color-grey-70">{email}</span>
        </div>

        <!-- Password input -->
        <div class="input-group">
            <div class="input-wrapper">
                <span class="clickable-icon icon_password"></span>
                <input
                    bind:this={passwordInput}
                    type="password"
                    bind:value={password}
                    placeholder={$text('login.password_placeholder.text')}
                    required
                    autocomplete="current-password"
                    class:error={!!errorMessage}
                    oninput={() => dispatch('userActivity')}
                />
                {#if errorMessage}
                    <InputWarning
                        message={errorMessage}
                        target={passwordInput}
                    />
                {/if}
            </div>
        </div>

        <!-- 2FA section - only visible if required -->
        {#if tfa_required}
        <!-- Wrap check-2fa text for conditional hiding -->
        <div class="check-2fa-container" class:hidden={isBackupMode}>
            <p id="check-2fa" class="check-2fa-text" style={getStyle('check-2fa')}>
                {#if isBackupMode}
                    {@html $text('login.backup_code_is_single_use.text')}
                {:else if currentDisplayedApp}
                    <span class="app-name-inline">{@html $text('login.check_your_2fa_app.text').replace('{tfa_app}', '')}</span>
                    <span class="app-name-inline">
                        {#if tfaAppIconClass}
                            <span class="icon provider-{tfaAppIconClass} mini-icon {previewMode && !tfaAppName ? 'fade-animation' : ''}"></span>
                        {/if}
                        <span class="{previewMode && !tfaAppName ? 'fade-text' : ''}">{currentDisplayedApp}</span>
                    </span>
                {:else}
                    {@html $text('login.check_your_2fa_app.text').replace('{tfa_app}', $text('login.your_tfa_app.text'))}
                {/if}
            </p>

            <div id="input-group" style={getStyle('input-area')}>
                <div class="input-wrapper">
                    {#if isBackupMode}
                        <span class="clickable-icon icon_text"></span>
                        <input
                            bind:this={tfaInput}
                            type="text"
                            bind:value={tfaCode}
                            oninput={handleTfaInput}
                            placeholder={inputPlaceholder}
                            inputmode="text"
                            maxlength={inputMaxLength}
                            autocomplete="one-time-code"
                            class:error={!!errorMessage}
                            onkeypress={(e) => { if (e.key === 'Enter') handleSubmit(); }}
                        />
                    {:else}
                        <span class="clickable-icon icon_2fa"></span>
                        <input
                            bind:this={tfaInput}
                            type="text"
                            bind:value={tfaCode}
                            oninput={handleTfaInput}
                            placeholder={inputPlaceholder}
                            inputmode="numeric"
                            maxlength={inputMaxLength}
                            autocomplete="one-time-code"
                            class:error={!!errorMessage}
                            onkeypress={(e) => { if (e.key === 'Enter') handleSubmit(); }}
                        />
                    {/if}
                    {#if tfaErrorMessage}
                        <InputWarning
                            message={tfaErrorMessage}
                            target={tfaInput}
                        />
                    {/if}
                </div>
            </div>
        </div>
        {/if}

        <button
            type="submit"
            class="login-button"
            disabled={isLoading || !isFormValid}
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
        <div id="login-with-another-account" style={getStyle('login-with-another-account')}>
            <button class="login-option-button" onclick={handleBackToEmail}>
                <span class="clickable-icon icon_user"></span>
                <mark>{$text('login.login_with_another_account.text')}</mark>
            </button>
        </div>

        <!-- Toggle Button - only if TFA is required -->
        {#if tfa_required}
        <div id="login-with-backup-code" style={getStyle('login-with-backup-code')}>
            <button class="login-option-button" onclick={toggleBackupMode} disabled={isLoading}>
                {#if isBackupMode}
                <span class="clickable-icon icon_2fa"></span>
                {:else}
                <span class="clickable-icon icon_text"></span>
                {/if}
                <mark>{toggleButtonText}</mark>
            </button>
        </div>
        {/if}

        <!-- Login options -->
        <div id="login-with-recoverykey" style={getStyle('login-with-recoverykey')}>
            <button class="login-option-button" onclick={handleSwitchToRecoveryKey}>
                <span class="clickable-icon icon_warning"></span>
                <mark>{$text('login.login_with_recovery_key.text')}</mark>
            </button>
        </div>
    </div>
    {/if}
</div>

<style>
    .login-button {
        margin: 20px 0px 10px 0px;
    }
    .password-tfa-login {
        display: flex;
        flex-direction: column;
        width: 100%;
    }

    .email-display {
        text-align: center;
        margin-bottom: 10px;
    }

    .login-options-container {
        display: flex;
        flex-direction: column;
        align-self: center;
        width: fit-content;
    }

    .check-2fa-text {
        margin: 0 0 10px 0;
    }

    .app-name-inline {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        vertical-align: middle
    }

    .mini-icon {
        width: 24px;
        height: 24px;
        border-radius: 4px;
        flex-shrink: 0;
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

    .rate-limit-message {
        color: var(--color-error);
        padding: 24px;
        text-align: center;
        font-weight: 500;
        font-size: 16px;
        line-height: 1.5;
        background-color: var(--color-error-light);
        border-radius: 8px;
        margin: 24px 0;
    }
</style>