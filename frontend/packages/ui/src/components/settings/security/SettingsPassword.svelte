<!--
SettingsPassword - Password Management Settings
Allows users to add a new password (for passkey users) or change existing password.
Requires authentication (passkey or current password) before allowing password changes.

IMPORTANT SECURITY FLOW:
Password and 2FA must ALWAYS be set together. The flow is:
1. User enters new password
2. If user doesn't have 2FA, they MUST complete 2FA setup BEFORE password is saved
3. Password is only saved to server AFTER 2FA setup is confirmed
4. If user cancels 2FA setup, password is NOT saved - both must succeed together

This ensures users can never have a password without 2FA enabled.
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { getApiEndpoint, apiEndpoints } from '../../../config/api';
    import * as cryptoService from '../../../services/cryptoService';
    import { getMasterKey } from '../../../services/cryptoKeyStorage';
    import SecurityAuth from './SecurityAuth.svelte';
    import SettingsTwoFactorAuth from './SettingsTwoFactorAuth.svelte';

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
     * - tfa-setup: 2FA setup (required after adding new password if 2FA not enabled)
     * - success: Final success state
     */
    let currentStep = $state<'loading' | 'auth' | 'form' | 'tfa-setup' | 'success'>('loading');
    
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

    /**
     * Pending password data - stored when 2FA setup is required.
     * Password is NOT saved to server until 2FA setup completes.
     * This ensures password and 2FA are always set together.
     */
    interface PendingPasswordData {
        hashedEmail: string;
        lookupHash: string;
        encryptedMasterKey: string;
        salt: string;
        keyIv: string;
        isNewPassword: boolean;
    }
    let pendingPasswordData = $state<PendingPasswordData | null>(null);

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
     * Prepare password data and check if 2FA setup is required.
     * If 2FA is not set up, stores password data as pending and redirects to 2FA setup.
     * Password is ONLY saved after 2FA setup completes (if 2FA was needed).
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

            // Generate password-derived salt (different from email salt)
            const passwordSalt = cryptoService.generateSalt();
            const passwordSaltB64 = cryptoService.uint8ArrayToBase64(passwordSalt);

            // Derive wrapping key from new password
            const wrappingKey = await cryptoService.deriveKeyFromPassword(newPassword, passwordSalt);

            // Wrap the existing master key with the new password-derived key
            const { wrapped: encryptedMasterKey, iv: keyIv } = await cryptoService.encryptKey(masterKey, wrappingKey);

            // Generate lookup hash from new password (for authentication)
            const lookupHash = await cryptoService.hashKey(newPassword, emailSalt);

            // Prepare password data
            const passwordData: PendingPasswordData = {
                hashedEmail,
                lookupHash,
                encryptedMasterKey,
                salt: passwordSaltB64,
                keyIv,
                isNewPassword: !hasPassword
            };

            // Check if 2FA setup is required BEFORE saving password
            // Password and 2FA must ALWAYS be set together
            if (!has2FA) {
                console.log('[SettingsPassword] 2FA not set up, storing password data pending and starting 2FA setup');
                // Store password data - will be saved only after 2FA setup completes
                pendingPasswordData = passwordData;
                // Transition to 2FA setup step
                currentStep = 'tfa-setup';
            } else {
                // User already has 2FA, safe to save password immediately
                console.log('[SettingsPassword] 2FA already enabled, saving password directly');
                await savePasswordToServer(passwordData);
            }

        } catch (error) {
            console.error('[SettingsPassword] Error preparing password:', error);
            errorMessage = error instanceof Error ? error.message : 'Failed to prepare password';
        } finally {
            isSubmitting = false;
        }
    }

    /**
     * Save password data to server.
     * Called directly if 2FA is already set up, or after 2FA setup completes.
     */
    async function savePasswordToServer(passwordData: PendingPasswordData) {
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.settings.updatePassword), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    hashed_email: passwordData.hashedEmail,
                    lookup_hash: passwordData.lookupHash,
                    encrypted_master_key: passwordData.encryptedMasterKey,
                    salt: passwordData.salt,
                    key_iv: passwordData.keyIv,
                    is_new_password: passwordData.isNewPassword
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

            console.log('[SettingsPassword] Password saved to server successfully');
            
            // Update local state
            hasPassword = true;
            
            // Show success
            successMessage = passwordData.isNewPassword 
                ? $text('settings.security.password_added_success.text')
                : $text('settings.security.password_changed_success.text');
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
        currentStep = 'auth';
    }

    /**
     * Handle 2FA setup completion.
     * Called when the embedded SettingsTwoFactorAuth component completes setup.
     * NOW we can save the pending password data since 2FA is confirmed.
     */
    async function handleTfaSetupComplete() {
        console.log('[SettingsPassword] 2FA setup complete');
        has2FA = true;

        // Now save the pending password data
        if (pendingPasswordData) {
            console.log('[SettingsPassword] Saving pending password data after 2FA setup');
            try {
                await savePasswordToServer(pendingPasswordData);
                // Clear pending data
                pendingPasswordData = null;
                // Success message is set by savePasswordToServer, but override for combined success
                successMessage = $text('settings.security.password_and_tfa_success.text');
            } catch (error) {
                console.error('[SettingsPassword] Failed to save password after 2FA setup:', error);
                errorMessage = error instanceof Error ? error.message : 'Failed to save password';
                // Stay on current step to show error
                // User might need to try again
            }
        } else {
            console.error('[SettingsPassword] No pending password data after 2FA setup - this should not happen');
            successMessage = $text('settings.security.tfa_setup_complete.text');
            currentStep = 'success';
        }
    }

    /**
     * Handle 2FA setup cancellation.
     * Password is NOT saved - user must complete both password and 2FA together.
     */
    function handleTfaSetupCancel() {
        console.log('[SettingsPassword] 2FA setup cancelled, discarding pending password data');
        // Clear pending password data - password will NOT be saved
        pendingPasswordData = null;
        // Show a message explaining why we're going back
        errorMessage = $text('settings.security.tfa_required_for_password.text');
        // Go back to password form
        currentStep = 'form';
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
    {:else if currentStep === 'tfa-setup'}
        <!-- 2FA Setup Step - Required after adding new password -->
        <div class="tfa-setup-step">
            <div class="step-header">
                <h2>{$text('settings.security.tfa_setup_required.text')}</h2>
                <p class="description">{$text('settings.security.tfa_setup_required_description.text')}</p>
            </div>

            <div class="tfa-info-banner">
                <div class="info-icon">🔐</div>
                <p>{$text('settings.security.password_needs_tfa.text')}</p>
            </div>

            <!-- Embedded 2FA setup component - auto-starts setup, skips auth (already authenticated) -->
            <!-- If user cancels, password is NOT saved - both must be set together -->
            <SettingsTwoFactorAuth
                autoStartSetup={true}
                skipAuth={true}
                embedded={true}
                onSetupComplete={handleTfaSetupComplete}
                onCancel={handleTfaSetupCancel}
            />
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

    /* 2FA Setup Step */
    .tfa-setup-step {
        display: flex;
        flex-direction: column;
        gap: 24px;
    }

    .tfa-info-banner {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        padding: 16px;
        background: var(--color-primary-light);
        border: 1px solid var(--color-primary);
        border-radius: 8px;
    }

    .tfa-info-banner .info-icon {
        font-size: 24px;
        line-height: 1;
    }

    .tfa-info-banner p {
        color: var(--color-grey-90);
        font-size: 14px;
        line-height: 1.5;
        margin: 0;
    }

    /* Style adjustments for embedded 2FA component */
    .tfa-setup-step :global(.tfa-settings) {
        padding: 0;
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

