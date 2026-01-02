<!--
SettingsPassword - Password Management Settings
Allows users to add a new password (for passkey users) or change existing password.
Requires authentication (passkey or current password) before allowing password changes.
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { getApiEndpoint, apiEndpoints } from '../../../config/api';
    import * as cryptoService from '../../../services/cryptoService';
    import { getMasterKeyFromIndexedDB } from '../../../services/cryptoKeyStorage';
    import SecurityAuth from './SecurityAuth.svelte';

    // ========================================================================
    // STATE
    // ========================================================================
    
    /** Whether user has an existing password */
    let hasPassword = $state(false);
    
    /** Whether user has a passkey for authentication */
    let hasPasskey = $state(false);
    
    /** Whether user has 2FA enabled */
    let has2FA = $state(false);
    
    /** Current step in the password change process */
    let currentStep = $state<'loading' | 'auth' | 'form' | 'success'>('loading');
    
    /** Loading state for initial data fetch */
    let isLoading = $state(true);
    
    /** Loading state for password submission */
    let isSubmitting = $state(false);
    
    /** Error message to display */
    let errorMessage = $state<string | null>(null);
    
    /** Success message to display */
    let successMessage = $state<string | null>(null);
    
    // Password form state
    let newPassword = $state('');
    let confirmPassword = $state('');
    let passwordStrengthError = $state('');
    let showPasswordStrengthWarning = $state(false);

    // ========================================================================
    // COMPUTED
    // ========================================================================
    
    /** Whether passwords match */
    let passwordsMatch = $derived(!confirmPassword || newPassword === confirmPassword);
    
    /** Whether the form is valid */
    let isFormValid = $derived(
        newPassword.length >= 8 && 
        confirmPassword && 
        passwordsMatch &&
        !passwordStrengthError
    );
    
    /** Page title based on whether user has password */
    let pageTitle = $derived(
        hasPassword 
            ? $text('settings.security.change_password.text')
            : $text('settings.security.add_password.text')
    );
    
    /** Page description based on whether user has password */
    let pageDescription = $derived(
        hasPassword 
            ? $text('settings.security.change_password_description.text')
            : $text('settings.security.add_password_description.text')
    );

    // ========================================================================
    // LIFECYCLE
    // ========================================================================
    
    onMount(async () => {
        await fetchAuthMethods();
    });

    // ========================================================================
    // DATA FETCHING
    // ========================================================================
    
    /**
     * Fetch user's available authentication methods.
     */
    async function fetchAuthMethods() {
        isLoading = true;
        errorMessage = null;

        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.getUserAuthMethods), {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include'
            });

            if (!response.ok) {
                throw new Error('Failed to fetch authentication methods');
            }

            const data = await response.json();
            hasPasskey = data.has_passkey || false;
            has2FA = data.has_2fa || false;
            hasPassword = data.has_password || false;

            console.log('[SettingsPassword] Auth methods loaded:', { hasPasskey, has2FA, hasPassword });
            
            // Move to auth step
            currentStep = 'auth';
        } catch (error) {
            console.error('[SettingsPassword] Error fetching auth methods:', error);
            errorMessage = error instanceof Error ? error.message : 'Failed to load settings';
        } finally {
            isLoading = false;
        }
    }

    // ========================================================================
    // PASSWORD VALIDATION
    // ========================================================================
    
    /**
     * Check password strength.
     * Basic validation: length, mixed case, numbers.
     */
    function checkPasswordStrength(pwd: string) {
        if (pwd.length < 8) {
            passwordStrengthError = $text('signup.password_too_short.text');
            showPasswordStrengthWarning = true;
            return;
        }

        // Check for mixed case
        const hasUpperCase = /[A-Z]/.test(pwd);
        const hasLowerCase = /[a-z]/.test(pwd);
        const hasNumbers = /[0-9]/.test(pwd);

        if (!hasUpperCase || !hasLowerCase || !hasNumbers) {
            // Warning but not error - password is still valid
            showPasswordStrengthWarning = true;
            passwordStrengthError = '';
        } else {
            showPasswordStrengthWarning = false;
            passwordStrengthError = '';
        }
    }

    // Watch for password changes
    $effect(() => {
        if (newPassword) {
            checkPasswordStrength(newPassword);
        } else {
            passwordStrengthError = '';
            showPasswordStrengthWarning = false;
        }
    });

    // ========================================================================
    // EVENT HANDLERS
    // ========================================================================
    
    /**
     * Handle successful authentication.
     * Move to password form step.
     * @param data - Auth success data (method used, credential ID if passkey)
     */
    function handleAuthSuccess(data: { method: string; credentialId?: string }) {
        console.log('[SettingsPassword] Authentication successful:', data.method);
        currentStep = 'form';
    }

    /**
     * Handle authentication failure.
     * @param message - Error message from authentication
     */
    function handleAuthFailed(message: string) {
        console.error('[SettingsPassword] Authentication failed:', message);
        errorMessage = message;
        currentStep = 'auth';
    }

    /**
     * Handle authentication cancel.
     * Go back or show message.
     */
    function handleAuthCancel() {
        console.log('[SettingsPassword] Authentication cancelled');
        // Could dispatch event to go back, for now just show auth step again
        currentStep = 'auth';
    }

    /**
     * Submit new password.
     * Creates new encryption key with password-derived wrapping.
     */
    async function submitPassword() {
        if (!isFormValid || isSubmitting) {
            return;
        }

        errorMessage = null;
        isSubmitting = true;

        try {
            // Get email for salt operations
            const email = await cryptoService.getEmailDecryptedWithMasterKey();
            if (!email) {
                throw new Error('Email not available. Please log out and log back in.');
            }

            // Get email salt
            const emailSalt = cryptoService.getEmailSalt();
            if (!emailSalt) {
                throw new Error('Email salt not available. Please log out and log back in.');
            }

            // Get master key from IndexedDB
            const masterKey = await getMasterKeyFromIndexedDB();
            if (!masterKey) {
                throw new Error('Master key not available. Please log out and log back in.');
            }

            // Hash email for server lookup
            const hashedEmail = await cryptoService.hashEmail(email);

            // Generate password-derived salt (different from email salt)
            const passwordSalt = cryptoService.generateSalt();
            const passwordSaltB64 = cryptoService.uint8ArrayToBase64(passwordSalt);

            // Derive wrapping key from new password
            const wrappingKey = await cryptoService.deriveKeyFromPassword(newPassword, passwordSalt);

            // Wrap the existing master key with the new password-derived key
            const { wrapped: encryptedMasterKey, iv: keyIv } = await cryptoService.encryptKey(masterKey, wrappingKey);

            // Generate lookup hash from new password (for authentication)
            const lookupHash = await cryptoService.hashKey(newPassword, emailSalt);

            // Call backend to update/add password
            const response = await fetch(getApiEndpoint(apiEndpoints.settings.updatePassword), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    hashed_email: hashedEmail,
                    lookup_hash: lookupHash,
                    encrypted_master_key: encryptedMasterKey,
                    salt: passwordSaltB64,
                    key_iv: keyIv,
                    is_new_password: !hasPassword
                })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to update password');
            }

            const data = await response.json();
            if (!data.success) {
                throw new Error(data.message || 'Password update failed');
            }

            // Success!
            console.log('[SettingsPassword] Password updated successfully');
            successMessage = hasPassword 
                ? $text('settings.security.password_changed_success.text')
                : $text('settings.security.password_added_success.text');
            currentStep = 'success';
            
            // Update local state
            hasPassword = true;

        } catch (error) {
            console.error('[SettingsPassword] Error updating password:', error);
            errorMessage = error instanceof Error ? error.message : 'Failed to update password';
        } finally {
            isSubmitting = false;
        }
    }

    /**
     * Reset form to allow another password change.
     */
    function resetForm() {
        newPassword = '';
        confirmPassword = '';
        passwordStrengthError = '';
        showPasswordStrengthWarning = false;
        errorMessage = null;
        successMessage = null;
        currentStep = 'auth';
    }
</script>

<div class="password-settings-container">
    {#if isLoading}
        <!-- Loading State -->
        <div class="loading-container">
            <div class="loading-spinner"></div>
            <p>{$text('settings.security.loading.text')}</p>
        </div>
    {:else if currentStep === 'auth'}
        <!-- Authentication Step -->
        <div class="auth-step">
            <div class="step-header">
                <h2>{pageTitle}</h2>
                <p class="description">{pageDescription}</p>
            </div>

            <div class="auth-info">
                <div class="info-icon">🔐</div>
                <p>{$text('settings.security.auth_required_for_password.text')}</p>
            </div>

            <SecurityAuth
                {hasPasskey}
                {hasPassword}
                {has2FA}
                title={$text('settings.security.verify_identity.text')}
                description={$text('settings.security.verify_identity_description.text')}
                autoStart={hasPasskey}
                onSuccess={handleAuthSuccess}
                onFailed={handleAuthFailed}
                onCancel={handleAuthCancel}
            />
        </div>
    {:else if currentStep === 'form'}
        <!-- Password Form Step -->
        <div class="form-step">
            <div class="step-header">
                <h2>{pageTitle}</h2>
                <p class="description">{pageDescription}</p>
            </div>

            <div class="password-form">
                <!-- New Password Input -->
                <div class="form-group">
                    <label for="new-password">{$text('settings.security.new_password.text')}</label>
                    <input
                        id="new-password"
                        type="password"
                        bind:value={newPassword}
                        placeholder={$text('settings.security.new_password_placeholder.text')}
                        disabled={isSubmitting}
                        class:error={passwordStrengthError}
                    />
                    {#if passwordStrengthError}
                        <span class="field-error">{passwordStrengthError}</span>
                    {:else if showPasswordStrengthWarning}
                        <span class="field-warning">{$text('settings.security.password_strength_warning.text')}</span>
                    {/if}
                </div>

                <!-- Confirm Password Input -->
                <div class="form-group">
                    <label for="confirm-password">{$text('settings.security.confirm_password.text')}</label>
                    <input
                        id="confirm-password"
                        type="password"
                        bind:value={confirmPassword}
                        placeholder={$text('settings.security.confirm_password_placeholder.text')}
                        disabled={isSubmitting}
                        class:error={confirmPassword && !passwordsMatch}
                    />
                    {#if confirmPassword && !passwordsMatch}
                        <span class="field-error">{$text('signup.passwords_do_not_match.text')}</span>
                    {/if}
                </div>

                <!-- Password Requirements -->
                <div class="password-requirements">
                    <p class="requirements-title">{$text('settings.security.password_requirements.text')}</p>
                    <ul>
                        <li class:valid={newPassword.length >= 8}>
                            {$text('settings.security.password_req_length.text')}
                        </li>
                        <li class:valid={/[A-Z]/.test(newPassword) && /[a-z]/.test(newPassword)}>
                            {$text('settings.security.password_req_case.text')}
                        </li>
                        <li class:valid={/[0-9]/.test(newPassword)}>
                            {$text('settings.security.password_req_number.text')}
                        </li>
                    </ul>
                </div>

                <!-- Error Message -->
                {#if errorMessage}
                    <div class="error-message">
                        <div class="icon icon_error"></div>
                        <span>{errorMessage}</span>
                    </div>
                {/if}

                <!-- Submit Button -->
                <button
                    class="submit-btn"
                    onclick={submitPassword}
                    disabled={!isFormValid || isSubmitting}
                >
                    {#if isSubmitting}
                        <span class="loading-spinner-small"></span>
                    {/if}
                    {hasPassword 
                        ? $text('settings.security.change_password_button.text')
                        : $text('settings.security.add_password_button.text')}
                </button>
            </div>
        </div>
    {:else if currentStep === 'success'}
        <!-- Success Step -->
        <div class="success-step">
            <div class="success-icon">✓</div>
            <h2>{$text('settings.security.password_updated.text')}</h2>
            <p>{successMessage}</p>
            
            <button class="done-btn" onclick={resetForm}>
                {$text('settings.security.change_password_again.text')}
            </button>
        </div>
    {/if}
</div>

<style>
    .password-settings-container {
        padding: 24px;
        max-width: 500px;
    }

    .loading-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 60px 20px;
        text-align: center;
    }

    .loading-spinner {
        width: 40px;
        height: 40px;
        border: 3px solid var(--color-grey-30);
        border-top-color: var(--color-primary);
        border-radius: 50%;
        animation: spin 1s linear infinite;
        margin-bottom: 16px;
    }

    .loading-spinner-small {
        width: 18px;
        height: 18px;
        border: 2px solid rgba(255, 255, 255, 0.3);
        border-top-color: white;
        border-radius: 50%;
        animation: spin 1s linear infinite;
    }

    @keyframes spin {
        to {
            transform: rotate(360deg);
        }
    }

    .step-header {
        margin-bottom: 24px;
    }

    .step-header h2 {
        font-size: 20px;
        font-weight: 600;
        color: var(--color-grey-100);
        margin-bottom: 8px;
    }

    .description {
        color: var(--color-grey-60);
        line-height: 1.5;
    }

    .auth-info {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        padding: 16px;
        background: var(--color-grey-10);
        border-radius: 8px;
        margin-bottom: 24px;
    }

    .info-icon {
        font-size: 24px;
        line-height: 1;
    }

    .auth-info p {
        color: var(--color-grey-70);
        font-size: 14px;
        line-height: 1.5;
        margin: 0;
    }

    .password-form {
        display: flex;
        flex-direction: column;
        gap: 20px;
    }

    .form-group {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .form-group label {
        font-size: 14px;
        font-weight: 500;
        color: var(--color-grey-80);
    }

    .form-group input {
        padding: 12px 16px;
        font-size: 16px;
        border: 2px solid var(--color-grey-30);
        border-radius: 8px;
        background: var(--color-grey-5);
        color: var(--color-grey-100);
        transition: border-color 0.2s;
    }

    .form-group input:focus {
        outline: none;
        border-color: var(--color-primary);
    }

    .form-group input.error {
        border-color: var(--color-danger);
    }

    .form-group input:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }

    .field-error {
        color: var(--color-danger);
        font-size: 13px;
    }

    .field-warning {
        color: var(--color-warning);
        font-size: 13px;
    }

    .password-requirements {
        padding: 16px;
        background: var(--color-grey-10);
        border-radius: 8px;
    }

    .requirements-title {
        font-size: 13px;
        font-weight: 600;
        color: var(--color-grey-70);
        margin-bottom: 12px;
    }

    .password-requirements ul {
        list-style: none;
        padding: 0;
        margin: 0;
    }

    .password-requirements li {
        font-size: 13px;
        color: var(--color-grey-60);
        padding: 4px 0;
        padding-left: 24px;
        position: relative;
    }

    .password-requirements li::before {
        content: '○';
        position: absolute;
        left: 0;
        color: var(--color-grey-40);
    }

    .password-requirements li.valid::before {
        content: '✓';
        color: var(--color-success);
    }

    .password-requirements li.valid {
        color: var(--color-success);
    }

    .error-message {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 16px;
        background: var(--color-danger-light);
        border: 1px solid var(--color-danger);
        border-radius: 8px;
    }

    .error-message .icon {
        width: 20px;
        height: 20px;
        background: var(--color-danger);
        flex-shrink: 0;
    }

    .error-message span {
        color: var(--color-danger);
        font-size: 14px;
    }

    .submit-btn {
        width: 100%;
        padding: 14px 24px;
        background: var(--color-primary);
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 16px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.2s;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
    }

    .submit-btn:hover:not(:disabled) {
        background: var(--color-primary-dark);
    }

    .submit-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .cancel-link {
        background: none;
        border: none;
        color: var(--color-grey-60);
        font-size: 14px;
        cursor: pointer;
        padding: 8px;
        text-align: center;
    }

    .cancel-link:hover {
        color: var(--color-grey-80);
    }

    .success-step {
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        padding: 40px 20px;
    }

    .success-icon {
        width: 64px;
        height: 64px;
        background: var(--color-success);
        color: white;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 32px;
        margin-bottom: 24px;
    }

    .success-step h2 {
        font-size: 20px;
        font-weight: 600;
        color: var(--color-grey-100);
        margin-bottom: 12px;
    }

    .success-step p {
        color: var(--color-grey-60);
        margin-bottom: 32px;
    }

    .done-btn {
        padding: 12px 32px;
        background: var(--color-grey-20);
        color: var(--color-grey-80);
        border: none;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.2s;
    }

    .done-btn:hover {
        background: var(--color-grey-30);
    }

    /* Hide auth modal from SecurityAuth when in auth step - we don't want overlay */
    .auth-step :global(.auth-modal-overlay) {
        position: static;
        background: none;
    }

    .auth-step :global(.auth-modal) {
        max-width: none;
        width: 100%;
        padding: 0;
        box-shadow: none;
        background: transparent;
    }

    .auth-step :global(.auth-header) {
        display: none;
    }

    .auth-step :global(.auth-description) {
        display: none;
    }
</style>

