<!--
SettingsPassword - Password Management Settings
Allows users to add a new password (for passkey users) or change existing password.
Requires a recent same-session sensitive-action proof before changing credentials.
Users without enrolled TOTP can prove possession with their current password and
a one-use email code; TOTP and passkey remain available when enrolled.
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { getApiEndpoint, apiEndpoints } from '../../../config/api';
    import SettingsInput from '../elements/SettingsInput.svelte';
    import * as cryptoService from '../../../services/cryptoService';
    import { derivePasswordV2, toBase64Url } from '../../../services/passwordV2';
    import { getMasterKey } from '../../../services/cryptoKeyStorage';
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
    
    /** Current step in the password change process
     * - loading: Initial loading state
     * - auth: Authentication required before changes
     * - form: Password entry form
     * - success: Final success state
     */
    let currentStep = $state<'loading' | 'auth' | 'form' | 'success'>('loading');
    
    /** Loading state for initial data fetch */
    let isLoading = $state(true);
    
    /** Loading state for password submission */
    let isSubmitting = $state(false);
    
    /** Error message to display */
    let errorMessage = $state<string | null>(null);
    
    /** Success message to display */
    let successMessage = $state<string | null>(null);
    let legacyCredentialRetained = $state(false);
    
    // Password form state
    let newPassword = $state('');
    let confirmPassword = $state('');
    let passwordStrengthError = $state('');
    let showPasswordStrengthWarning = $state(false);

    interface PasswordUpdateData {
        hashedEmail: string;
        passwordAuthKey: string;
        encryptedMasterKey: string;
        salt: string;
        keyIv: string;
        isNewPassword: boolean;
    }

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
            ? $text('common.change_password')
            : $text('common.add_password')
    );
    
    /** Page description based on whether user has password */
    let pageDescription = $derived(
        hasPassword 
            ? $text('settings.security.change_password_description')
            : $text('settings.security.add_password_description')
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
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.methods), {
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
            passwordStrengthError = $text('signup.password_too_short');
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
        errorMessage = null;
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
     * Wrap the master key with the new password and save the credential. The
     * server verifies the recent same-session proof before accepting the write.
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

            // Get master key from memory (stayLoggedIn=false) or IndexedDB (stayLoggedIn=true)
            const masterKey = await getMasterKey();
            if (!masterKey) {
                throw new Error('Master key not available. Please log out and log back in.');
            }

            // Hash email for server lookup
            const hashedEmail = await cryptoService.hashEmail(email);

            // Version 2 binds both independent password subkeys to the account email salt.
            const { authKey, wrapKey } = await derivePasswordV2(newPassword, emailSalt);

            // Wrap the existing master key with the new password-derived key
            const { wrapped: encryptedMasterKey, iv: keyIv } = await cryptoService.encryptKey(masterKey, wrapKey);

            // Prepare password data
            const passwordData: PasswordUpdateData = {
                hashedEmail,
                passwordAuthKey: toBase64Url(authKey),
                encryptedMasterKey,
                salt: cryptoService.uint8ArrayToBase64(emailSalt),
                keyIv,
                isNewPassword: !hasPassword
            };

            await savePasswordToServer(passwordData);

        } catch (error) {
            console.error('[SettingsPassword] Error preparing password:', error);
            errorMessage = error instanceof Error ? error.message : 'Failed to prepare password';
        } finally {
            isSubmitting = false;
        }
    }

    /**
     * Save password data to server.
     */
    async function savePasswordToServer(passwordData: PasswordUpdateData) {
        try {
            // Keep password endpoint aligned with CLI blocked operations:
            // frontend/packages/openmates-cli/src/client.ts (BLOCKED_SETTINGS_POST_PATHS)
            const response = await fetch(getApiEndpoint(apiEndpoints.settings.updatePassword), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    hashed_email: passwordData.hashedEmail,
                    credential_version: 2,
                    password_auth_key: passwordData.passwordAuthKey,
                    encrypted_master_key: passwordData.encryptedMasterKey,
                    salt: passwordData.salt,
                    key_iv: passwordData.keyIv,
                    is_new_password: passwordData.isNewPassword
                })
            });

            if (response.status === 401 || response.status === 428) {
                // The server's same-session proof may expire while this form is open.
                newPassword = '';
                confirmPassword = '';
                currentStep = 'auth';
                throw new Error($text('settings.security.verify_identity_description'));
            }
            if (!response.ok) {
                const errorData = await response.json();
                if (response.status === 409 && errorData.detail?.error === 'legacy_credential_binding_required') {
                    throw new Error($text('settings.security.password_legacy_binding_required'));
                }
                throw new Error(errorData.detail || 'Failed to update password');
            }

            const data = await response.json();
            if (!data.success) {
                throw new Error(data.message || 'Password update failed');
            }

            console.log('[SettingsPassword] Password saved to server successfully');
            
            // Update local state
            hasPassword = true;
            legacyCredentialRetained = data.legacy_password_retained === true;
            
            // Show success
            successMessage = legacyCredentialRetained
                ? $text('settings.security.password_legacy_retained_warning')
                : passwordData.isNewPassword
                    ? $text('settings.security.password_added_success')
                    : $text('settings.security.password_changed_success');
            newPassword = '';
            confirmPassword = '';
            currentStep = 'success';

        } catch (error) {
            console.error('[SettingsPassword] Error saving password to server:', error);
            throw error;
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
        legacyCredentialRetained = false;
        currentStep = 'auth';
    }

</script>

<div class="password-settings-container" data-testid="password-settings-container">
    {#if isLoading}
        <!-- Loading State -->
        <div class="loading-container">
            <div class="loading-spinner"></div>
            <p>{$text('common.loading')}</p>
        </div>
    {:else if currentStep === 'loading'}
        <div class="error-message" data-testid="password-settings-error">
            <div class="icon icon_error"></div>
            <span>{errorMessage}</span>
        </div>
        <button class="submit-btn" data-testid="password-settings-retry" onclick={fetchAuthMethods}>
            {$text('common.retry')}
        </button>
    {:else if currentStep === 'auth'}
        <!-- Authentication Step -->
        <div class="auth-step">
            <div class="step-header">
                <h2>{pageTitle}</h2>
                <p class="description">{pageDescription}</p>
            </div>

            <div class="auth-info">
                <div class="info-icon">🔐</div>
                <p>{$text('settings.security.auth_required_for_password')}</p>
            </div>
            {#if errorMessage}
                <div class="error-message" data-testid="password-settings-auth-error">
                    <div class="icon icon_error"></div>
                    <span>{errorMessage}</span>
                </div>
            {/if}

            <SecurityAuth
                {hasPasskey}
                {hasPassword}
                {has2FA}
                sensitiveActionPurpose="credential_change"
                title={$text('settings.security.verify_identity')}
                description={$text('settings.security.verify_identity_description')}
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
                    <label for="new-password">{$text('settings.security.new_password')}</label>
                    <SettingsInput
                        id="new-password"
                        type="password"
                        bind:value={newPassword}
                        placeholder={$text('settings.security.new_password_placeholder')}
                        disabled={isSubmitting}
                        hasError={!!passwordStrengthError}
                    />
                    {#if passwordStrengthError}
                        <span class="field-error">{passwordStrengthError}</span>
                    {:else if showPasswordStrengthWarning}
                        <span class="field-warning">{$text('settings.security.password_strength_warning')}</span>
                    {/if}
                </div>

                <!-- Confirm Password Input -->
                <div class="form-group">
                    <label for="confirm-password">{$text('settings.security.confirm_password')}</label>
                    <SettingsInput
                        id="confirm-password"
                        type="password"
                        bind:value={confirmPassword}
                        placeholder={$text('settings.security.confirm_password_placeholder')}
                        disabled={isSubmitting}
                        hasError={!!(confirmPassword && !passwordsMatch)}
                    />
                    {#if confirmPassword && !passwordsMatch}
                        <span class="field-error">{$text('signup.passwords_do_not_match')}</span>
                    {/if}
                </div>

                <!-- Password Requirements -->
                <div class="password-requirements">
                    <p class="requirements-title">{$text('settings.security.password_requirements')}</p>
                    <ul>
                        <li class:valid={newPassword.length >= 8}>
                            {$text('settings.security.password_req_length')}
                        </li>
                        <li class:valid={/[A-Z]/.test(newPassword) && /[a-z]/.test(newPassword)}>
                            {$text('settings.security.password_req_case')}
                        </li>
                        <li class:valid={/[0-9]/.test(newPassword)}>
                            {$text('settings.security.password_req_number')}
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
                        ? $text('common.change_password')
                        : $text('common.add_password')}
                </button>
            </div>
        </div>
    {:else if currentStep === 'success'}
        <!-- Success Step -->
        <div class="success-step">
            <div class="success-icon">✓</div>
            <h2>{legacyCredentialRetained ? $text('settings.security.password_legacy_retained_title') : $text('settings.security.password_updated')}</h2>
            <p>{successMessage}</p>
            
            <button class="done-btn" onclick={resetForm}>
                {$text('settings.security.change_password_again')}
            </button>
        </div>
    {/if}
</div>

<style>
    .password-settings-container {
        padding: var(--spacing-12);
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
        margin-bottom: var(--spacing-8);
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
        margin-bottom: var(--spacing-12);
    }

    .step-header h2 {
        font-size: var(--font-size-h3);
        font-weight: 600;
        color: var(--color-grey-100);
        margin-bottom: var(--spacing-4);
    }

    .description {
        color: var(--color-grey-60);
        line-height: 1.5;
    }

    .auth-info {
        display: flex;
        align-items: flex-start;
        gap: var(--spacing-6);
        padding: var(--spacing-8);
        background: var(--color-grey-10);
        border-radius: var(--radius-3);
        margin-bottom: var(--spacing-12);
    }

    .info-icon {
        font-size: var(--font-size-h2-mobile);
        line-height: 1;
    }

    .auth-info p {
        color: var(--color-grey-70);
        font-size: var(--font-size-small);
        line-height: 1.5;
        margin: 0;
    }

    .password-form {
        display: flex;
        flex-direction: column;
        gap: var(--spacing-10);
    }

    .form-group {
        display: flex;
        flex-direction: column;
        gap: var(--spacing-4);
    }

    .form-group label {
        font-size: var(--font-size-small);
        font-weight: 500;
        color: var(--color-grey-80);
    }

    .field-error {
        color: var(--color-danger);
        font-size: var(--font-size-xs);
    }

    .field-warning {
        color: var(--color-warning);
        font-size: var(--font-size-xs);
    }

    .password-requirements {
        padding: var(--spacing-8);
        background: var(--color-grey-10);
        border-radius: var(--radius-3);
    }

    .requirements-title {
        font-size: var(--font-size-xs);
        font-weight: 600;
        color: var(--color-grey-70);
        margin-bottom: var(--spacing-6);
    }

    .password-requirements ul {
        list-style: none;
        padding: 0;
        margin: 0;
    }

    .password-requirements li {
        font-size: var(--font-size-xs);
        color: var(--color-grey-60);
        padding: 4px 0;
        padding-left: var(--spacing-12);
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
        gap: var(--spacing-6);
        padding: var(--spacing-8);
        background: var(--color-danger-light);
        border: 1px solid var(--color-danger);
        border-radius: var(--radius-3);
    }

    .error-message .icon {
        width: 20px;
        height: 20px;
        background: var(--color-danger);
        flex-shrink: 0;
    }

    .error-message span {
        color: var(--color-danger);
        font-size: var(--font-size-small);
    }

    .submit-btn {
        width: 100%;
        padding: 14px 24px;
        background: var(--color-primary);
        color: white;
        border: none;
        border-radius: var(--radius-3);
        font-size: var(--font-size-p);
        font-weight: 600;
        cursor: pointer;
        transition: background var(--duration-normal);
        display: flex;
        align-items: center;
        justify-content: center;
        gap: var(--spacing-4);
    }

    .submit-btn:hover:not(:disabled) {
        background: var(--color-primary-dark);
    }

    .submit-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .success-step {
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        padding: var(--spacing-20) var(--spacing-10);
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
        font-size: var(--font-size-xxxl);
        margin-bottom: var(--spacing-12);
    }

    .success-step h2 {
        font-size: var(--font-size-h3);
        font-weight: 600;
        color: var(--color-grey-100);
        margin-bottom: var(--spacing-6);
    }

    .success-step p {
        color: var(--color-grey-60);
        margin-bottom: var(--spacing-16);
    }

    .done-btn {
        padding: var(--spacing-6) var(--spacing-16);
        background: var(--color-grey-20);
        color: var(--color-grey-80);
        border: none;
        border-radius: var(--radius-3);
        font-size: var(--font-size-small);
        font-weight: 600;
        cursor: pointer;
        transition: background var(--duration-normal);
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
