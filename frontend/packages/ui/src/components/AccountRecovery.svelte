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
     * 3. Set up new login method (password only - passkey can be added later via settings)
     */
    import { text } from '@repo/ui';
    import { createEventDispatcher, onMount } from 'svelte';
    import { fade, slide } from 'svelte/transition';
    import Toggle from './Toggle.svelte';
    import { getApiEndpoint, apiEndpoints } from '../config/api';
    import { notificationStore } from '../stores/notificationStore';
    import * as cryptoService from '../services/cryptoService';
    import { checkAuth } from '../stores/authStore';
    import { userDB } from '../services/userDB';
    
    const dispatch = createEventDispatcher();
    
    // Props - email is passed from the login form
    let { email: initialEmail = '' }: { email?: string } = $props();
    
    // Step states - start at 'code' since email is already known
    type RecoveryStep = 'code' | 'setup' | 'complete';
    let currentStep = $state<RecoveryStep>('code');
    
    // Form data - email comes from props
    let email = $state(initialEmail);
    let verificationCode = $state('');
    let acknowledgeDataLoss = $state(false);
    
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
    let canResetAccount = $derived(
        verificationCode.length === 6 && acknowledgeDataLoss && !isVerifying
    );
    
    /**
     * Request reset code to be sent to email
     */
    async function requestResetCode() {
        if (isRequestingCode || !email) return;
        
        isRequestingCode = true;
        
        try {
            await fetch(getApiEndpoint(apiEndpoints.auth.recovery_request), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    email: email,
                    language: document.documentElement.lang || 'en',
                    darkmode: document.documentElement.classList.contains('dark')
                }),
                credentials: 'include'
            });
            
            // Always show success message to prevent email enumeration
            notificationStore.success(
                $text('login.recovery_code_sent.text') || 
                'If an account exists with this email, a verification code has been sent.',
                6000
            );
        } catch (error) {
            console.error('Error requesting reset code:', error);
            notificationStore.error(
                $text('login.error_occurred.text') || 'An error occurred. Please try again.',
                5000
            );
        } finally {
            isRequestingCode = false;
        }
    }
    
    /**
     * Reset account and set up password login
     */
    async function resetWithPassword(password: string) {
        if (isSettingUp) return;
        
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
            
            // Call the full reset endpoint
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.recovery_full_reset), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    email: email,
                    code: verificationCode,
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
                    $text('login.account_reset_success.text') || 'Account reset successfully!',
                    5000
                );
                
                currentStep = 'complete';
                
                // Check auth and redirect
                await checkAuth(undefined, true);
                dispatch('resetComplete', { username: data.username });
            } else {
                codeError = data.message || 'Failed to reset account. Please try again.';
                notificationStore.error(codeError, 6000);
            }
        } catch (error) {
            console.error('Error resetting account with password:', error);
            notificationStore.error(
                $text('login.error_occurred.text') || 'An error occurred. Please try again.',
                5000
            );
        } finally {
            isSettingUp = false;
        }
    }
    
    // NOTE: Passkey setup during account recovery is not supported.
    // Users can add a passkey later via settings after logging in with password.
    // This simplifies the recovery flow and avoids WebAuthn complexity during a critical operation.
    
    /**
     * Go back to login
     */
    function backToLogin() {
        dispatch('back');
    }
    
    // Password setup state
    let showPasswordSetup = $state(false);
    let newPassword = $state('');
    let confirmPassword = $state('');
    let passwordError = $state('');
    
    /**
     * Show password setup form
     */
    function showSetupPassword() {
        showPasswordSetup = true;
    }
    
    /**
     * Submit password setup
     */
    async function submitPassword() {
        passwordError = '';
        
        if (newPassword.length < 8) {
            passwordError = $text('signup.password_too_short.text') || 'Password must be at least 8 characters';
            return;
        }
        
        if (newPassword !== confirmPassword) {
            passwordError = $text('signup.passwords_do_not_match.text') || 'Passwords do not match';
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
                onclick={() => currentStep = 'setup'}
                disabled={!canResetAccount}
            >
                {#if isVerifying}
                    <span class="loading-spinner"></span>
                {:else}
                    {$text('login.reset_account.text')}
                {/if}
            </button>
        </div>
        
    {:else if currentStep === 'setup'}
        <div class="step-content" transition:slide>
            {#if !showPasswordSetup}
                <p class="info-text">
                    {$text('login.choose_login_method.text')}
                </p>
                
                <div class="login-method-options">
                    <!-- Passkey option - temporarily disabled for recovery -->
                    <!-- <button 
                        class="method-button"
                        onclick={selectPasskey}
                        disabled={isSettingUp}
                    >
                        <div class="clickable-icon icon_passkey" style="width: 30px; height: 30px"></div>
                        <span>{$text('signup.passkey.text') || 'Passkey'}</span>
                    </button> -->
                    
                    <button 
                        class="method-button"
                        onclick={showSetupPassword}
                        disabled={isSettingUp}
                    >
                        <div class="clickable-icon icon_password" style="width: 30px; height: 30px"></div>
                        <span>{$text('signup.password.text')}</span>
                    </button>
                </div>
            {:else}
                <p class="info-text">
                    {$text('signup.create_password.text') || 'Create a new password for your account:'}
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
                            placeholder={$text('signup.confirm_password.text') || 'Confirm password'}
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
                        {$text('login.complete_reset.text') || 'Complete reset'}
                    {/if}
                </button>
            {/if}
        </div>
        
    {:else if currentStep === 'complete'}
        <div class="step-content" transition:slide>
            <div class="success-icon">✓</div>
            <h3>{$text('login.account_reset_complete.text') || 'Account reset complete!'}</h3>
            <p class="info-text">
                {$text('login.you_can_now_login.text') || 'You can now login with your new credentials.'}
            </p>
            <button class="primary-button" onclick={backToLogin}>
                {$text('login.go_to_login.text') || 'Go to login'}
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
    }
    
    .error-text {
        color: var(--color-red-50);
        font-size: 12px;
        margin-top: 4px;
    }
    
    .primary-button {
        padding: 14px 24px;
        background: var(--color-primary);
        color: white;
        border: none;
        border-radius: 12px;
        font-size: 16px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.2s;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
    }
    
    .primary-button:hover:not(:disabled) {
        background: var(--color-primary-dark);
    }
    
    .primary-button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
    
    .danger-button {
        padding: 14px 24px;
        background: var(--color-red-50);
        color: white;
        border: none;
        border-radius: 12px;
        font-size: 16px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.2s;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
    }
    
    .danger-button:hover:not(:disabled) {
        background: var(--color-red-60);
    }
    
    .danger-button:disabled {
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
    
    .login-method-options {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }
    
    .method-button {
        display: flex;
        align-items: center;
        gap: 16px;
        padding: 16px;
        background: var(--color-grey-20);
        border: 2px solid transparent;
        border-radius: 12px;
        cursor: pointer;
        transition: all 0.2s;
        font-size: 16px;
        font-weight: 500;
        color: var(--color-grey-80);
    }
    
    .method-button:hover:not(:disabled) {
        border-color: var(--color-primary);
    }
    
    .method-button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
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

