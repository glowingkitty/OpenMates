<script lang="ts">
    /**
     * Account Recovery Component
     * 
     * Handles the "Can't login to account?" flow where users who have lost
     * their password, passkey, AND recovery key can reset their account.
     * 
     * IMPORTANT: This is a LAST RESORT that permanently deletes all chats,
     * settings, memories, and embeds. Users should use "Login with recovery key"
     * if they have their recovery key.
     * 
     * Flow:
     * 1. Auto-send verification code (email already known from login)
     * 2. Enter verification code + Confirm data loss via Toggle
     * 3. Verify code with backend (get verification token)
     * 4. Select login method (password or passkey)
     * 5. Set up new credentials and complete reset
     */
    import { text } from '@repo/ui';
    import { createEventDispatcher, onMount } from 'svelte';
    import { fade, slide } from 'svelte/transition';
    import Toggle from './Toggle.svelte';
    import LoginMethodSelector from './LoginMethodSelector.svelte';
    import { getApiEndpoint, apiEndpoints } from '../config/api';
    import { notificationStore } from '../stores/notificationStore';
    import * as cryptoService from '../services/cryptoService';
    import { checkAuth } from '../stores/authStore';
    import { userDB } from '../services/userDB';
    
    const dispatch = createEventDispatcher();
    
    // Props - email is passed from the login form
    let { email: initialEmail = '' }: { email?: string } = $props();
    
    // Step states
    type RecoveryStep = 'code' | 'setup' | 'password' | 'complete';
    let currentStep = $state<RecoveryStep>('code');
    
    // Form data
    let email = $state(initialEmail);
    let verificationCode = $state('');
    let acknowledgeDataLoss = $state(false);
    let verificationToken = $state(''); // Token from verify-code endpoint
    
    // Loading states
    let isRequestingCode = $state(false);
    let isVerifying = $state(false);
    let isSettingUp = $state(false);
    
    // Error states
    let codeError = $state('');
    
    // Auto-request the code when component mounts
    onMount(() => {
        if (email) {
            requestResetCode();
        }
    });
    
    // Derived state for button enablement
    let canVerifyCode = $derived(
        verificationCode.length === 6 && acknowledgeDataLoss && !isVerifying
    );
    
    /**
     * Request reset code to be sent to email
     * Handles rate limiting (429) responses with clear user feedback
     */
    async function requestResetCode() {
        if (isRequestingCode || !email) return;
        
        isRequestingCode = true;
        
        try {
            // Get dark mode setting from localStorage or system preference
            // This matches the approach used in other components like Basics.svelte
            const prefersDarkMode = window.matchMedia && 
                window.matchMedia('(prefers-color-scheme: dark)').matches;
            const darkModeEnabled = localStorage.getItem('darkMode') === 'true' || prefersDarkMode;
            
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.recovery_request), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    email: email,
                    language: document.documentElement.lang || 'en',
                    darkmode: darkModeEnabled
                }),
                credentials: 'include'
            });
            
            // Handle rate limiting (429 Too Many Requests)
            if (response.status === 429) {
                console.warn('Rate limited when requesting recovery code');
                notificationStore.error(
                    $text('login.too_many_requests.text'),
                    8000
                );
                return;
            }
            
            // Always show success message to prevent email enumeration
            // (even for non-429 error responses, to avoid revealing account existence)
            notificationStore.success(
                $text('login.recovery_code_sent.text'),
                6000
            );
        } catch (error) {
            console.error('Error requesting reset code:', error);
            notificationStore.error(
                $text('login.error_occurred.text'),
                5000
            );
        } finally {
            isRequestingCode = false;
        }
    }
    
    /**
     * Verify the code before showing login method selection
     */
    async function verifyCode() {
        if (isVerifying || !canVerifyCode) return;
        
        isVerifying = true;
        codeError = '';
        
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.recovery_verify), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    email: email,
                    code: verificationCode
                }),
                credentials: 'include'
            });
            
            const data = await response.json();
            
            if (data.success && data.verification_token) {
                verificationToken = data.verification_token;
                currentStep = 'setup';
            } else {
                codeError = data.message || 'Invalid verification code. Please try again.';
                notificationStore.error(codeError, 5000);
            }
        } catch (error) {
            console.error('Error verifying code:', error);
            codeError = $text('login.error_occurred.text') || 'An error occurred. Please try again.';
            notificationStore.error(codeError, 5000);
        } finally {
            isVerifying = false;
        }
    }
    
    /**
     * Handle login method selection
     */
    function handleMethodSelect(event: CustomEvent<{ method: string }>) {
        const method = event.detail.method;
        
        if (method === 'password') {
            currentStep = 'password';
        } else if (method === 'passkey') {
            // For account recovery, we recommend password first for simplicity
            // Passkey can be added later via settings
            notificationStore.info(
                $text('login.passkey_after_reset.text') || 
                'For security, please set up a password first. You can add a passkey in settings after login.',
                8000
            );
            currentStep = 'password';
        }
    }
    
    /**
     * Reset account and set up password login
     */
    async function resetWithPassword(password: string) {
        if (isSettingUp || !verificationToken) return;
        
        isSettingUp = true;
        
        try {
            // Generate all cryptographic material (same as signup)
            const masterKey = await cryptoService.generateExtractableMasterKey();
            const emailSalt = cryptoService.generateEmailSalt();
            const emailSaltB64 = cryptoService.uint8ArrayToBase64(emailSalt);
            
            // Derive email encryption key
            const emailEncryptionKey = await cryptoService.deriveEmailEncryptionKey(email, emailSalt);
            
            // Save email encryption key and salt
            cryptoService.saveEmailEncryptionKey(emailEncryptionKey, true);
            cryptoService.saveEmailSalt(emailSalt, true);
            
            // Encrypt email for server
            const encryptedEmailForServer = await cryptoService.encryptEmail(email, emailEncryptionKey);
            
            // Encrypt email with master key for passwordless login
            const { encryptWithMasterKeyDirect } = await import('../services/cryptoService');
            const encryptedEmailWithMasterKey = await encryptWithMasterKeyDirect(email, masterKey);
            
            // Generate password-based wrapping
            const salt = cryptoService.generateSalt();
            const saltB64 = cryptoService.uint8ArrayToBase64(salt);
            const wrappingKey = await cryptoService.deriveKeyFromPassword(password, salt);
            const { wrapped: encryptedMasterKey, iv: keyIv } = await cryptoService.encryptKey(masterKey, wrappingKey);
            
            // Generate lookup hash from password
            const lookupHash = await cryptoService.hashKey(password, emailSalt);
            
            // Hash email for server lookup
            const hashedEmail = await cryptoService.hashEmail(email);
            
            // Call the reset endpoint with verification token
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.recovery_full_reset), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    email: email,
                    verification_token: verificationToken,
                    acknowledge_data_loss: true,
                    new_login_method: 'password',
                    hashed_email: hashedEmail,
                    encrypted_email: encryptedEmailForServer,
                    encrypted_email_with_master_key: encryptedEmailWithMasterKey,
                    user_email_salt: emailSaltB64,
                    lookup_hash: lookupHash,
                    encrypted_master_key: encryptedMasterKey,
                    salt: saltB64,
                    key_iv: keyIv
                }),
                credentials: 'include'
            });
            
            const data = await response.json();
            
            if (data.success) {
                // Save master key for session
                await cryptoService.saveKeyToSession(masterKey, true);
                await cryptoService.saveEmailEncryptedWithMasterKey(email, true);
                
                // Store login method
                await userDB.init();
                await userDB.updateUserData({ login_method: 'password' });
                
                notificationStore.success(
                    $text('login.account_reset_success.text'),
                    5000
                );
                
                currentStep = 'complete';
                
                // Check auth and redirect
                await checkAuth(undefined, true);
                dispatch('resetComplete', { username: data.username });
            } else {
                codeError = data.message || 'Failed to reset account. Please try again.';
                notificationStore.error(codeError, 6000);
                
                // If token expired, go back to code step
                if (data.error_code === 'TOKEN_EXPIRED' || data.error_code === 'INVALID_TOKEN') {
                    currentStep = 'code';
                    verificationToken = '';
                    verificationCode = '';
                }
            }
        } catch (error) {
            console.error('Error resetting account with password:', error);
            notificationStore.error(
                $text('login.error_occurred.text'),
                5000
            );
        } finally {
            isSettingUp = false;
        }
    }
    
    /**
     * Go back to login
     */
    function backToLogin() {
        dispatch('back');
    }
    
    // Password setup state
    let newPassword = $state('');
    let confirmPassword = $state('');
    let passwordError = $state('');
    
    /**
     * Submit password setup
     */
    async function submitPassword() {
        passwordError = '';
        
        if (newPassword.length < 8) {
            passwordError = $text('signup.password_too_short.text');
            return;
        }
        
        if (newPassword !== confirmPassword) {
            passwordError = $text('signup.passwords_do_not_match.text');
            return;
        }
        
        await resetWithPassword(newPassword);
    }
</script>

<div class="account-recovery" transition:fade>
    
    {#if currentStep === 'code'}
        <div class="step-content" transition:slide>
            <p class="info-text">
                {$text('login.enter_code_sent.text')}
            </p>
            
            <div class="input-group">
                <div class="input-wrapper">
                    <span class="clickable-icon icon_2fa"></span>
                    <input
                        id="verification-code"
                        type="text"
                        bind:value={verificationCode}
                        placeholder="123456"
                        maxlength="6"
                        pattern="[0-9]*"
                        inputmode="numeric"
                        disabled={isVerifying}
                        class:error={!!codeError}
                    />
                </div>
                {#if codeError}
                    <span class="error-text">{codeError}</span>
                {/if}
            </div>
            
            <div class="confirmation-section">
                <div class="toggle-row">
                    <Toggle 
                        bind:checked={acknowledgeDataLoss}
                        id="acknowledge-data-loss"
                        ariaLabel={$text('login.acknowledge_data_loss.text')}
                    />
                    <label for="acknowledge-data-loss" class="toggle-label">
                        {$text('login.acknowledge_data_loss.text')}
                    </label>
                </div>
            </div>
            
            <button
                onclick={verifyCode}
                disabled={!canVerifyCode}
            >
                {#if isVerifying}
                    <span class="loading-spinner"></span>
                {:else}
                    {$text('login.reset_account.text')}
                {/if}
            </button>
            
            <button 
                class="resend-button"
                onclick={requestResetCode}
                disabled={isRequestingCode}
            >
                {$text('login.resend_code.text')}
            </button>
        </div>
        
    {:else if currentStep === 'setup'}
        <div class="step-content" transition:slide>
            <div class="success-message">
                <div class="check-icon">✓</div>
                <span>{$text('login.code_verified.text')}</span>
            </div>
            
            <LoginMethodSelector
                showPasskey={false}
                showRecommendedBadge={false}
                isLoading={isSettingUp}
                on:select={handleMethodSelect}
            />
        </div>
        
    {:else if currentStep === 'password'}
        <div class="step-content" transition:slide>
            <p class="info-text">
                {$text('signup.create_password.text')}
            </p>
            
            <div class="input-group">
                <div class="input-wrapper">
                    <span class="clickable-icon icon_password"></span>
                    <input
                        id="new-password"
                        type="password"
                        bind:value={newPassword}
                        placeholder={$text('login.password_placeholder.text')}
                        disabled={isSettingUp}
                        minlength="8"
                    />
                </div>
            </div>
            
            <div class="input-group">
                <div class="input-wrapper">
                    <span class="clickable-icon icon_password"></span>
                    <input
                        id="confirm-password"
                        type="password"
                        bind:value={confirmPassword}
                        placeholder={$text('signup.confirm_password.text')}
                        disabled={isSettingUp}
                        onkeydown={(e) => e.key === 'Enter' && submitPassword()}
                    />
                </div>
                {#if passwordError}
                    <span class="error-text">{passwordError}</span>
                {/if}
            </div>
            
            <button
                onclick={submitPassword}
                disabled={isSettingUp || !newPassword || !confirmPassword}
            >
                {#if isSettingUp}
                    <span class="loading-spinner"></span>
                {:else}
                    {$text('login.complete_reset.text')}
                {/if}
            </button>
        </div>
        
    {:else if currentStep === 'complete'}
        <div class="step-content" transition:slide>
            <div class="success-icon">✓</div>
            <h3>{$text('login.account_reset_complete.text')}</h3>
            <p class="info-text">
                {$text('login.you_can_now_login.text')}
            </p>
            <button onclick={backToLogin}>
                {$text('login.go_to_login.text')}
            </button>
        </div>
    {/if}
</div>

<style>
    .account-recovery {
        width: 100%;
        max-width: 400px;
        margin: 0 auto;
        padding: 20px;
    }
    
    .step-content {
        display: flex;
        flex-direction: column;
        gap: 16px;
    }
    
    .info-text {
        color: var(--color-grey-60);
        font-size: 14px;
        line-height: 1.5;
        text-align: center;
    }
    
    /* Input styles use global CSS classes from shared styles */
    
    .error-text {
        color: var(--color-red-50);
        font-size: 12px;
        margin-top: 4px;
    }
    
    .resend-button {
        padding: 10px;
        background: transparent;
        color: var(--color-grey-60);
        border: none;
        font-size: 14px;
        cursor: pointer;
        text-decoration: underline;
    }
    
    .resend-button:hover:not(:disabled) {
        color: var(--color-grey-80);
    }
    
    .resend-button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
    
    .confirmation-section {
        background: var(--color-grey-15);
        border-radius: 12px;
        padding: 16px;
    }
    
    .toggle-row {
        display: flex;
        align-items: flex-start;
        gap: 12px;
    }
    
    .toggle-label {
        font-size: 14px;
        color: var(--color-grey-70);
        line-height: 1.4;
        cursor: pointer;
    }
    
    .success-message {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        padding: 12px;
        background: var(--color-green-10);
        border-radius: 12px;
        color: var(--color-green-60);
        font-weight: 500;
    }
    
    .check-icon {
        width: 24px;
        height: 24px;
        background: var(--color-green-50);
        color: white;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 14px;
    }
    
    .loading-spinner {
        width: 20px;
        height: 20px;
        border: 2px solid transparent;
        border-top-color: currentColor;
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
    }
    
    @keyframes spin {
        to {
            transform: rotate(360deg);
        }
    }
    
    .success-icon {
        width: 60px;
        height: 60px;
        background: var(--color-green-50);
        color: white;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 30px;
        margin: 0 auto 16px;
    }
    
    .step-content h3 {
        text-align: center;
        margin: 0 0 8px;
        color: var(--color-grey-80);
    }
</style>
