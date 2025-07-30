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

    const dispatch = createEventDispatcher();

    // Props
    export let email = '';
    export let isLoading = false;
    export let errorMessage: string | null = null;
    export let stayLoggedIn = false;
    export let tfaAppName: string | null = null;
    export let previewMode = false;
    export let previewTfaAppName = 'Google Authenticator';
    export let highlight: (
        'check-2fa' |
        'app-name' |
        'input-area' |
        'login-btn' |
        'enter-backup-code'
    )[] = [];

    // Form data
    let password = '';
    let tfaCode = '';
    let isBackupMode = false;

    // Input references
    let passwordInput: HTMLInputElement;
    let tfaInput: HTMLInputElement;

    // TFA app display logic
    let currentAppIndex = 0;
    let animationInterval: number | null = null;
    let currentDisplayedApp = previewMode ? previewTfaAppName : (tfaAppName || '');
    const appNames = Object.keys(tfaAppIcons);

    // Get the icon class for the app name, or undefined if not found
    $: tfaAppIconClass = currentDisplayedApp in tfaAppIcons ? tfaAppIcons[currentDisplayedApp] : undefined;

    // Reactive statements for backup mode
    $: inputPlaceholder = isBackupMode ? $text('login.enter_backup_code.text') : $text('signup.enter_one_time_code.text');
    $: toggleButtonText = isBackupMode ? $text('login.enter_2fa_app_code.text') : $text('login.enter_backup_code.text');
    $: inputMode = isBackupMode ? 'text' : 'numeric';
    $: inputMaxLength = isBackupMode ? 14 : 6;

    // Validation
    $: isPasswordValid = password.length > 0;
    $: isTfaValid = isBackupMode ? tfaCode.length === 14 : tfaCode.length === 6;
    $: isFormValid = isPasswordValid && isTfaValid;

    // Helper function to generate opacity style
    type HighlightableId = typeof highlight[number];
    $: getStyle = (id: HighlightableId) => `opacity: ${highlight.length === 0 || highlight.includes(id) ? 1 : 0.5}`;

    // Update the animation logic to stop when a selected app is provided
    $: {
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
    }

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
    });

    onDestroy(() => {
        if (animationInterval) clearInterval(animationInterval);
    });

    // Handle form submission - makes single request to /login
    async function handleSubmit() {
        if (!isPasswordValid || !isTfaValid || isLoading) return;

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

            // Prepare request body
            const requestBody: any = {
                hashed_email,
                lookup_hash
            };

            // Add 2FA code if provided
            if (tfaCode) {
                requestBody.tfa_code = tfaCode;
                requestBody.code_type = isBackupMode ? 'backup' : 'otp';
            }

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

            const data = await response.json();

            if (response.ok && data.success) {
                // Login successful
                await handleSuccessfulLogin(data);
            } else {
                if (data.tfa_required) {
                    errorMessage = data.message || 'Invalid verification code';
                } else {
                    errorMessage = data.message || 'Invalid email or password';
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
                    
                    // Clear sensitive data
                    password = '';
                    tfaCode = '';
                    
                    // Dispatch success event
                    dispatch('loginSuccess', {
                        user: data.user,
                        inSignupFlow: data.inSignupFlow
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

        // Dispatch activity event whenever input changes
        dispatch('tfaActivity');

        // Optionally auto-submit when code reaches required length
        const requiredLength = isBackupMode ? 14 : 6;
        if (tfaCode.length === requiredLength) {
            handleSubmit();
        }
    }

    // Function to toggle between OTP and Backup Code mode
    function toggleBackupMode() {
        isBackupMode = !isBackupMode;
        tfaCode = ''; // Clear input when switching modes
        errorMessage = null; // Clear error message
        if (tfaInput) {
            tfaInput.focus(); // Re-focus input
        }
    }

    // Handle back to email
    function handleBackToEmail() {
        dispatch('backToEmail');
    }

    // Handle switch to recovery key
    function handleSwitchToRecoveryKey() {
        dispatch('switchToRecoveryKey');
    }

    // Clear error message when user starts typing again
    $: if (tfaCode) {
        errorMessage = null;
    }
</script>

<div class="password-tfa-login" in:fade={{ duration: 300 }}>
    <!-- Combined password and 2FA form -->
    <form on:submit|preventDefault={handleSubmit}>
        <!-- Show email address above password input -->
        <div class="email-display">
            <span class="email-text">{email}</span>
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
                />
                {#if errorMessage}
                    <InputWarning
                        message={errorMessage}
                        target={passwordInput}
                    />
                {/if}
            </div>
        </div>

        <!-- 2FA section - always visible -->
        <div class="tfa-section" class:preview={previewMode}>
            <!-- Wrap check-2fa text for conditional hiding -->
            <div class="check-2fa-container" class:hidden={isBackupMode}>
                <p id="check-2fa" class="check-2fa-text" style={getStyle('check-2fa')}>
                    {#if isBackupMode}
                        {@html $text('login.backup_code_is_single_use.text')}
                    {:else if currentDisplayedApp}
                        {@html $text('login.check_your_2fa_app.text').replace('{tfa_app}', '')}
                        <span class="app-name-inline">
                            {#if tfaAppIconClass}
                                <span class="icon provider-{tfaAppIconClass} mini-icon {previewMode && !tfaAppName ? 'fade-animation' : ''}"></span>
                            {/if}
                            <span class="{previewMode && !tfaAppName ? 'fade-text' : ''}">{currentDisplayedApp}</span>
                        </span>
                    {:else}
                        {@html $text('login.check_your_2fa_app.text', { tfa_app: $text('login.your_tfa_app.text') })}
                    {/if}
                </p>
            </div>

            <div id="input-area" style={getStyle('input-area')}>
                <div class="input-wrapper">
                    <span class="clickable-icon icon_2fa"></span>
                    {#if isBackupMode}
                        <input
                            bind:this={tfaInput}
                            type="text"
                            bind:value={tfaCode}
                            on:input={handleTfaInput}
                            placeholder={inputPlaceholder}
                            inputmode="text"
                            maxlength={inputMaxLength}
                            autocomplete="one-time-code"
                            class:error={!!errorMessage}
                            on:keypress={(e) => { if (e.key === 'Enter') handleSubmit(); }}
                        />
                    {:else}
                        <input
                            bind:this={tfaInput}
                            type="text"
                            bind:value={tfaCode}
                            on:input={handleTfaInput}
                            placeholder={inputPlaceholder}
                            inputmode="numeric"
                            maxlength={inputMaxLength}
                            autocomplete="one-time-code"
                            class:error={!!errorMessage}
                            on:keypress={(e) => { if (e.key === 'Enter') handleSubmit(); }}
                        />
                    {/if}
                    {#if errorMessage}
                        <InputWarning
                            message={errorMessage}
                            target={tfaInput}
                        />
                    {/if}
                </div>
            </div>
        </div>

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

    <!-- Toggle Button -->
    <div id="enter-backup-code" class="enter-backup-code" style={getStyle('enter-backup-code')}>
        <button on:click={toggleBackupMode} class="text-button" disabled={isLoading}>
            {toggleButtonText}
        </button>
    </div>

    <!-- Login options -->
    <div class="login-options">
        <button class="text-button" on:click={handleSwitchToRecoveryKey}>
            {$text('login.login_with_recovery_key.text')}
        </button>
    </div>

    <!-- Back to email button -->
    <div class="back-to-email">
        <button class="text-button" on:click={handleBackToEmail}>
            {$text('login.login_with_another_account.text')}
        </button>
    </div>
</div>

<style>
    .password-tfa-login {
        display: flex;
        flex-direction: column;
        width: 100%;
    }

    .email-display {
        text-align: center;
        margin-bottom: 10px;
    }

    .email-text {
        color: var(--color-grey-70);
    }

    .tfa-section {
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
    }

    .check-2fa-text {
        margin: 0 0 15px 0;
        color: var(--color-grey-60);
    }

    .app-name {
        display: flex;
        align-items: center;
        justify-content: center;
        margin-bottom: 20px;
        gap: 10px;
    }

    .mini-icon {
        width: 24px;
        height: 24px;
        border-radius: 4px;
    }

    .login-options {
        margin-top: 20px;
        display: flex;
        flex-direction: column;
        gap: 10px;
        align-items: center;
    }

    .login-options .text-button {
        color: var(--color-primary);
        text-decoration: none;
        font-size: 14px;
        padding: 8px 16px;
        border-radius: 4px;
        transition: background-color 0.2s;
    }

    .login-options .text-button:hover {
        background-color: var(--color-grey-10);
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