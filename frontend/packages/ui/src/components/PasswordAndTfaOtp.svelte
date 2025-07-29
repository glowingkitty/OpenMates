<script lang="ts">
    /**
     * PasswordAndTfaOtp.svelte - Component for password input with optional 2FA
     * Makes a single request to /login with all required data
     */
    import { createEventDispatcher } from 'svelte';
    import { fade } from 'svelte/transition';
    import { text } from '@repo/ui';
    import InputWarning from './common/InputWarning.svelte';
    import Toggle from './Toggle.svelte';
    import { getApiEndpoint, apiEndpoints } from '../config/api';
    import * as cryptoService from '../services/cryptoService';

    const dispatch = createEventDispatcher();

    // Props
    export let email = '';
    export let isLoading = false;
    export let errorMessage: string | null = null;
    export let stayLoggedIn = false;

    // Form data
    let password = '';
    let tfaCode = '';
    let showTfaInput = false;
    let tfa_app_name: string | null = null;

    // Input references
    let passwordInput: HTMLInputElement;
    let tfaInput: HTMLInputElement;

    // Validation
    $: isPasswordValid = password.length > 0;
    $: isTfaValid = !showTfaInput || tfaCode.length === 6;
    $: isFormValid = isPasswordValid && isTfaValid;

    // Handle form submission - makes single request to /login
    async function handleSubmit() {
        if ((!isPasswordValid && !showTfaInput) || (showTfaInput && !isTfaValid) || isLoading) return;

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
            if (showTfaInput && tfaCode) {
                requestBody.tfa_code = tfaCode;
                requestBody.code_type = 'otp';
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
                if (data.tfa_required && !showTfaInput) {
                    // First request - 2FA required, show 2FA input
                    showTfaInput = true;
                    tfa_app_name = data.user?.tfa_app_name || null;
                    // Focus TFA input after a tick
                    setTimeout(() => {
                        if (tfaInput) tfaInput.focus();
                    }, 100);
                } else {
                    // Login successful (either no 2FA required or 2FA completed)
                    await handleSuccessfulLogin(data);
                }
            } else {
                if (showTfaInput) {
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

    // Handle input for TFA code
    function handleTfaInput(event: Event) {
        const input = event.target as HTMLInputElement;
        // Allow only digits and limit length
        tfaCode = input.value.replace(/\D/g, '').slice(0, 6);
        input.value = tfaCode;

        // Auto-submit when 6 digits are entered
        if (tfaCode.length === 6) {
            handleSubmit();
        }
    }

    // Handle back to email
    function handleBackToEmail() {
        dispatch('backToEmail');
    }

    // Handle switch to backup code
    function handleSwitchToBackupCode() {
        dispatch('switchToBackupCode', { email, password, stayLoggedIn });
    }
</script>

<div class="password-tfa-login" in:fade={{ duration: 300 }}>
    {#if !showTfaInput}
        <!-- Password input form -->
        <form on:submit|preventDefault={handleSubmit}>
            <div class="input-group">
                <div class="input-wrapper">
                    <span class="clickable-icon icon_secret"></span>
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

            <div class="input-group toggle-group">
                <Toggle 
                    id="stayLoggedIn" 
                    name="stayLoggedIn" 
                    bind:checked={stayLoggedIn} 
                    ariaLabel={$text('login.stay_logged_in.text')} 
                />
                <label for="stayLoggedIn" class="agreement-text">{@html $text('login.stay_logged_in.text')}</label>
            </div>

            <button 
                type="submit" 
                class="login-button" 
                disabled={isLoading || !isPasswordValid} 
            >
                {#if isLoading}
                    <span class="loading-spinner"></span>
                {:else}
                    {$text('login.login_button.text')}
                {/if}
            </button>
        </form>
    {:else}
        <!-- 2FA input form -->
        <div class="tfa-section" in:fade={{ duration: 200 }}>
            <p class="check-2fa-text">
                {@html $text('login.check_your_2fa_app.text')}
            </p>
            
            {#if tfa_app_name}
                <p class="app-name">
                    <span class="icon provider-google mini-icon"></span>
                    <span>{tfa_app_name}</span>
                </p>
            {/if}

            <form on:submit|preventDefault={handleSubmit}>
                <div class="input-group">
                    <div class="input-wrapper">
                        <span class="clickable-icon icon_2fa"></span>
                        <input
                            bind:this={tfaInput}
                            type="text"
                            bind:value={tfaCode}
                            on:input={handleTfaInput}
                            placeholder={$text('signup.enter_one_time_code.text')}
                            inputmode="numeric"
                            maxlength="6"
                            autocomplete="one-time-code"
                            class:error={!!errorMessage}
                        />
                        {#if errorMessage}
                            <InputWarning 
                                message={errorMessage} 
                                target={tfaInput} 
                            />
                        {/if}
                    </div>
                </div>

                <button 
                    type="submit" 
                    class="login-button" 
                    disabled={isLoading || !isTfaValid} 
                >
                    {#if isLoading}
                        <span class="loading-spinner"></span>
                    {:else}
                        {$text('login.login_button.text')}
                    {/if}
                </button>
            </form>

            <div class="tfa-options">
                <button class="text-button" on:click={handleSwitchToBackupCode}>
                    {$text('login.enter_backup_code.text')}
                </button>
            </div>
        </div>
    {/if}

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

    .toggle-group {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 12px;
        max-width: 350px;
        margin: 0 auto;
    }

    .agreement-text {
        text-align: left;
        cursor: pointer;
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

    .tfa-options {
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