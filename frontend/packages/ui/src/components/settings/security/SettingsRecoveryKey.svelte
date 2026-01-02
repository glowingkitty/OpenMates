<!--
Settings Recovery Key Component
================================
This component allows users to:
1. View their current recovery key status
2. Generate a new recovery key (which invalidates the old one)

Security Flow:
1. User must authenticate first (via SecurityAuth component)
2. New recovery key is generated client-side
3. Master key is wrapped with new recovery key
4. Server is updated with new wrapped key and lookup hash
5. Old recovery key entry is deleted from server
6. User downloads new recovery key file

Note: Recovery keys are the ONLY way to recover an account if password/passkey is lost.
Users should store them securely (offline, in a safe place).
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { fade } from 'svelte/transition';
    import { getApiEndpoint, apiEndpoints } from '../../../config/api';
    import { userProfile, updateProfile } from '../../../stores/userProfile';
    import * as cryptoService from '../../../services/cryptoService';
    import SecurityAuth from './SecurityAuth.svelte';

    // ========================================================================
    // STATE
    // ========================================================================

    /** Whether user has a recovery key set up */
    let hasRecoveryKey = $state<boolean | null>(null);

    /** Timestamp when recovery key was last stored */
    let recoveryKeyTimestamp = $state<number | null>(null);

    /** Current step in the flow */
    type Step = 'overview' | 'auth' | 'generating' | 'download' | 'confirm';
    let currentStep = $state<Step>('overview');

    /** Whether authentication is in progress */
    let isAuthenticating = $state(false);

    /** The newly generated recovery key */
    let newRecoveryKey = $state<string>('');

    /** Recovery key data to send to server */
    let recoveryKeyData = $state<{
        lookupHash: string;
        wrappedMasterKey: string;
        salt: string;
        keyIv: string;
    } | null>(null);

    /** Whether the key has been downloaded */
    let keyDownloaded = $state(false);

    /** Error message to display */
    let errorMessage = $state<string>('');

    /** Success message to display */
    let successMessage = $state<string>('');

    /** Whether data is loading */
    let isLoading = $state(true);

    /** Whether we're saving to server */
    let isSaving = $state(false);

    // ========================================================================
    // LIFECYCLE
    // ========================================================================

    onMount(async () => {
        await fetchRecoveryKeyStatus();
    });

    // ========================================================================
    // DATA FETCHING
    // ========================================================================

    /**
     * Fetch user's recovery key status from profile.
     */
    async function fetchRecoveryKeyStatus() {
        isLoading = true;
        try {
            // Check user profile for consent_recovery_key_stored_timestamp
            const profile = $userProfile;
            if (profile && profile.consent_recovery_key_stored_timestamp) {
                hasRecoveryKey = true;
                recoveryKeyTimestamp = profile.consent_recovery_key_stored_timestamp;
                console.log('[SettingsRecoveryKey] Recovery key status: has key, timestamp:', recoveryKeyTimestamp);
            } else {
                // If not in local profile, fetch from server
                const response = await fetch(getApiEndpoint(apiEndpoints.payments.getUserAuthMethods), {
                    method: 'GET',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include'
                });

                if (response.ok) {
                    const data = await response.json();
                    // Check if user has recovery_key in their login methods
                    hasRecoveryKey = data.has_recovery_key || false;
                    console.log('[SettingsRecoveryKey] Recovery key status from server:', hasRecoveryKey);
                } else {
                    console.error('[SettingsRecoveryKey] Failed to fetch auth methods');
                    hasRecoveryKey = false;
                }
            }
        } catch (error) {
            console.error('[SettingsRecoveryKey] Error fetching recovery key status:', error);
            hasRecoveryKey = false;
        } finally {
            isLoading = false;
        }
    }

    // ========================================================================
    // COMPUTED
    // ========================================================================

    /** Format timestamp to readable date */
    let formattedTimestamp = $derived(() => {
        if (!recoveryKeyTimestamp) return '';
        const date = new Date(recoveryKeyTimestamp * 1000);
        return date.toLocaleDateString(undefined, {
            year: 'numeric',
            month: 'long',
            day: 'numeric'
        });
    });

    // ========================================================================
    // RECOVERY KEY GENERATION
    // ========================================================================

    /**
     * Start the recovery key regeneration flow.
     * First requires authentication.
     */
    function startRegeneration() {
        errorMessage = '';
        successMessage = '';
        currentStep = 'auth';
        isAuthenticating = true;
    }

    /**
     * Called when authentication succeeds.
     * Proceeds to generate new recovery key.
     */
    async function handleAuthSuccess() {
        isAuthenticating = false;
        currentStep = 'generating';
        await generateNewRecoveryKey();
    }

    /**
     * Called when authentication fails.
     */
    function handleAuthFailed(message: string) {
        isAuthenticating = false;
        errorMessage = message || $text('settings.security.recovery_key_auth_failed.text');
        currentStep = 'overview';
    }

    /**
     * Called when authentication is cancelled.
     */
    function handleAuthCancel() {
        isAuthenticating = false;
        currentStep = 'overview';
    }

    /**
     * Generate a new recovery key and prepare data for server.
     */
    async function generateNewRecoveryKey() {
        errorMessage = '';
        
        try {
            console.log('[SettingsRecoveryKey] Starting recovery key generation...');

            // Step 1: Generate recovery key locally
            newRecoveryKey = cryptoService.generateSecureRecoveryKey();
            console.log('[SettingsRecoveryKey] Generated secure recovery key');

            // Step 2: Get the user's email (needed for lookup hash context)
            const email = cryptoService.getEmailDecryptedWithMasterKey();
            if (!email) {
                throw new Error('Could not retrieve email for recovery key generation');
            }

            // Step 3: Get the master key that needs to be wrapped
            const masterKey = await cryptoService.getKeyFromStorage();
            if (!masterKey) {
                throw new Error('Could not retrieve encryption key');
            }

            // Step 4: Get the user's email salt for lookup hash generation
            const userEmailSalt = cryptoService.getEmailSalt();
            if (!userEmailSalt) {
                throw new Error('Missing encryption data (email salt)');
            }

            // Step 5: Create a hash of the recovery key for server-side lookup
            const lookupHash = await cryptoService.hashKey(newRecoveryKey, userEmailSalt);

            // Step 6: Generate salt for key derivation (wrapping the master key)
            const salt = cryptoService.generateSalt();
            const saltB64 = cryptoService.uint8ArrayToBase64(salt);

            // Step 7: Derive wrapping key from recovery key
            const wrappingKey = await cryptoService.deriveKeyFromPassword(newRecoveryKey, salt);

            // Step 8: Wrap the master key with the recovery key
            const { wrapped: wrappedMasterKey, iv: keyIv } = await cryptoService.encryptKey(masterKey, wrappingKey);

            // Step 9: Store the data for later submission
            recoveryKeyData = {
                lookupHash,
                wrappedMasterKey,
                salt: saltB64,
                keyIv
            };

            console.log('[SettingsRecoveryKey] Recovery key generated successfully');

            // Move to download step
            currentStep = 'download';

            // Auto-download the key
            downloadRecoveryKey();

        } catch (error) {
            console.error('[SettingsRecoveryKey] Error generating recovery key:', error);
            errorMessage = error instanceof Error ? error.message : 'Failed to generate recovery key';
            currentStep = 'overview';
        }
    }

    /**
     * Download the recovery key as a text file.
     */
    function downloadRecoveryKey() {
        if (!newRecoveryKey) {
            console.error('[SettingsRecoveryKey] No recovery key to download');
            return;
        }

        keyDownloaded = true;
        const content = newRecoveryKey;
        const blob = new Blob([content], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'openmates_recovery_key.txt';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        console.log('[SettingsRecoveryKey] Recovery key file downloaded');
    }

    /**
     * Proceed to confirmation step after download.
     */
    function proceedToConfirm() {
        currentStep = 'confirm';
    }

    /**
     * Save the new recovery key to the server.
     * This replaces the old recovery key.
     */
    async function saveRecoveryKey() {
        if (!recoveryKeyData) {
            errorMessage = 'No recovery key data to save';
            return;
        }

        isSaving = true;
        errorMessage = '';

        try {
            console.log('[SettingsRecoveryKey] Saving recovery key to server...');

            const response = await fetch(getApiEndpoint(apiEndpoints.auth.regenerate_recovery_key), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    new_lookup_hash: recoveryKeyData.lookupHash,
                    new_wrapped_master_key: recoveryKeyData.wrappedMasterKey,
                    new_key_iv: recoveryKeyData.keyIv,
                    new_salt: recoveryKeyData.salt
                    // old_lookup_hash is optional, server will handle deletion
                })
            });

            const data = await response.json();

            if (response.ok && data.success) {
                console.log('[SettingsRecoveryKey] Recovery key saved successfully');
                successMessage = $text('settings.security.recovery_key_success.text');
                hasRecoveryKey = true;
                recoveryKeyTimestamp = Math.floor(Date.now() / 1000);

                // Update local profile
                updateProfile({ consent_recovery_key_stored_timestamp: recoveryKeyTimestamp });

                // Reset state
                currentStep = 'overview';
                newRecoveryKey = '';
                recoveryKeyData = null;
                keyDownloaded = false;
            } else {
                throw new Error(data.message || 'Failed to save recovery key');
            }
        } catch (error) {
            console.error('[SettingsRecoveryKey] Error saving recovery key:', error);
            errorMessage = error instanceof Error ? error.message : 'Failed to save recovery key';
        } finally {
            isSaving = false;
        }
    }

    /**
     * Cancel and go back to overview.
     */
    function cancel() {
        currentStep = 'overview';
        newRecoveryKey = '';
        recoveryKeyData = null;
        keyDownloaded = false;
        errorMessage = '';
    }
</script>

<div class="settings-recovery-key">
    {#if currentStep === 'auth' && isAuthenticating}
        <!-- Authentication Step -->
        <SecurityAuth
            onSuccess={handleAuthSuccess}
            onFailed={handleAuthFailed}
            onCancel={handleAuthCancel}
            title={$text('settings.security.recovery_key_auth_title.text')}
            description={$text('settings.security.recovery_key_auth_description.text')}
        />
    {:else if currentStep === 'generating'}
        <!-- Generating Step -->
        <div class="generating-container" in:fade>
            <div class="spinner"></div>
            <p class="generating-text">{$text('settings.security.recovery_key_generating.text')}</p>
        </div>
    {:else if currentStep === 'download'}
        <!-- Download Step -->
        <div class="download-container" in:fade>
            <div class="header">
                <div class="icon header_size warning"></div>
                <h2>{$text('settings.security.recovery_key_download_title.text')}</h2>
            </div>

            <div class="warning-box">
                <div class="warning-icon"></div>
                <p>{$text('settings.security.recovery_key_warning.text')}</p>
            </div>

            <div class="download-section">
                {#if keyDownloaded}
                    <div class="download-success">
                        <div class="checkmark-icon"></div>
                        <p>{$text('settings.security.recovery_key_downloaded.text')}</p>
                    </div>
                {/if}

                <button class="download-button" onclick={downloadRecoveryKey}>
                    <div class="clickable-icon icon_download" style="width: 24px; height: 24px"></div>
                    <span>{$text('settings.security.recovery_key_download_button.text')}</span>
                </button>
            </div>

            <div class="important-notice">
                <p>{@html $text('settings.security.recovery_key_important.text')}</p>
            </div>

            <div class="action-buttons">
                <button
                    onclick={proceedToConfirm}
                    disabled={!keyDownloaded}
                >
                    {$text('common.continue.text')}
                </button>
            </div>
        </div>
    {:else if currentStep === 'confirm'}
        <!-- Confirmation Step -->
        <div class="confirm-container" in:fade>
            <div class="header">
                <h2>{$text('settings.security.recovery_key_confirm_title.text')}</h2>
            </div>

            <p class="confirm-description">
                {$text('settings.security.recovery_key_confirm_description.text')}
            </p>

            {#if errorMessage}
                <div class="error-message" in:fade>
                    {errorMessage}
                </div>
            {/if}

            <div class="action-buttons">
                <button
                    class="primary-button"
                    onclick={saveRecoveryKey}
                    disabled={isSaving}
                >
                    {#if isSaving}
                        <div class="button-spinner"></div>
                    {:else}
                        {$text('settings.security.recovery_key_confirm_button.text')}
                    {/if}
                </button>
            </div>
        </div>
    {:else}
        <!-- Overview Step -->
        <div class="overview-container" in:fade>
            <div class="description">
                <p>{$text('settings.security.recovery_key_description.text')}</p>
            </div>

            {#if isLoading}
                <div class="loading-container">
                    <div class="spinner small"></div>
                </div>
            {:else}
                <div class="status-section">
                    <div class="status-row">
                        <span class="status-label">{$text('settings.security.recovery_key_status.text')}</span>
                        <span class="status-value" class:has-key={hasRecoveryKey}>
                            {#if hasRecoveryKey}
                                <div class="status-icon checkmark-icon"></div>
                                {$text('settings.security.recovery_key_set.text')}
                            {:else}
                                <div class="status-icon warning-icon"></div>
                                {$text('settings.security.recovery_key_not_set.text')}
                            {/if}
                        </span>
                    </div>

                    {#if hasRecoveryKey && formattedTimestamp()}
                        <div class="status-row">
                            <span class="status-label">{$text('settings.security.recovery_key_last_updated.text')}</span>
                            <span class="status-value">{formattedTimestamp()}</span>
                        </div>
                    {/if}
                </div>

                {#if successMessage}
                    <div class="success-message" in:fade>
                        {successMessage}
                    </div>
                {/if}

                {#if errorMessage}
                    <div class="error-message" in:fade>
                        {errorMessage}
                    </div>
                {/if}

                <div class="action-section">
                    <button class="primary-button" onclick={startRegeneration}>
                        {#if hasRecoveryKey}
                            {$text('settings.security.recovery_key_regenerate_button.text')}
                        {:else}
                            {$text('settings.security.recovery_key_create_button.text')}
                        {/if}
                    </button>
                    <p class="action-hint">
                        {#if hasRecoveryKey}
                            {$text('settings.security.recovery_key_regenerate_hint.text')}
                        {:else}
                            {$text('settings.security.recovery_key_create_hint.text')}
                        {/if}
                    </p>
                </div>
            {/if}
        </div>
    {/if}
</div>

<style>
    .settings-recovery-key {
        padding: 24px;
        height: 100%;
        display: flex;
        flex-direction: column;
    }

    .description {
        color: var(--color-grey-70);
        line-height: 1.6;
        margin-bottom: 24px;
    }

    .status-section {
        background: var(--color-grey-15);
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 24px;
    }

    .status-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 8px 0;
    }

    .status-row:not(:last-child) {
        border-bottom: 1px solid var(--color-grey-25);
    }

    .status-label {
        color: var(--color-grey-60);
        font-size: 14px;
    }

    .status-value {
        display: flex;
        align-items: center;
        gap: 8px;
        font-weight: 500;
        color: var(--color-grey-80);
    }

    .status-value.has-key {
        color: var(--color-success, #22c55e);
    }

    .status-icon {
        width: 16px;
        height: 16px;
    }

    .checkmark-icon {
        background-color: var(--color-success, #22c55e);
        mask-image: url('@openmates/ui/static/icons/check.svg');
        mask-size: contain;
        mask-repeat: no-repeat;
        -webkit-mask-image: url('@openmates/ui/static/icons/check.svg');
        -webkit-mask-size: contain;
        -webkit-mask-repeat: no-repeat;
    }

    .warning-icon {
        width: 24px;
        height: 24px;
        background-image: url('@openmates/ui/static/icons/warning.svg');
        background-size: contain;
        background-repeat: no-repeat;
        flex-shrink: 0;
    }

    .action-section {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 12px;
    }

    .action-hint {
        color: var(--color-grey-50);
        font-size: 13px;
        text-align: center;
    }

    .primary-button {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        padding: 12px 24px;
        background: var(--color-primary);
        color: white;
        border: none;
        border-radius: 12px;
        cursor: pointer;
        font-size: 16px;
        font-weight: 500;
        transition: opacity 0.2s, transform 0.2s;
        min-width: 200px;
    }

    .primary-button:hover:not(:disabled) {
        opacity: 0.9;
        transform: scale(1.02);
    }

    .primary-button:active:not(:disabled) {
        transform: scale(0.98);
    }

    .primary-button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .action-buttons {
        display: flex;
        gap: 12px;
        justify-content: center;
        margin-top: 24px;
    }

    /* Loading and generating states */
    .loading-container,
    .generating-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 40px 20px;
        gap: 16px;
    }

    .spinner {
        width: 40px;
        height: 40px;
        border: 3px solid var(--color-grey-30);
        border-top-color: var(--color-primary);
        border-radius: 50%;
        animation: spin 1s linear infinite;
    }

    .spinner.small {
        width: 24px;
        height: 24px;
        border-width: 2px;
    }

    .button-spinner {
        width: 20px;
        height: 20px;
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

    .generating-text {
        color: var(--color-grey-60);
        font-size: 16px;
    }

    /* Download step */
    .download-container,
    .confirm-container {
        display: flex;
        flex-direction: column;
        gap: 20px;
    }

    .header {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 16px;
    }

    .header h2 {
        margin: 0;
        color: var(--color-grey-90);
    }

    .warning-box {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 16px;
        background: var(--color-warning-bg, rgba(255, 193, 7, 0.1));
        border-radius: 12px;
        border: 1px solid var(--color-warning, #ffc107);
    }

    .warning-box p {
        color: var(--color-grey-80);
        font-weight: 500;
        margin: 0;
    }

    .download-section {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 16px;
        padding: 20px;
        background: var(--color-grey-15);
        border-radius: 16px;
    }

    .download-success {
        display: flex;
        align-items: center;
        gap: 8px;
        color: var(--color-success, #22c55e);
        font-weight: 500;
    }

    .download-success p {
        margin: 0;
    }

    .download-button {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 12px 24px;
        background: var(--color-primary);
        color: white;
        border: none;
        border-radius: 12px;
        cursor: pointer;
        font-size: 16px;
        font-weight: 500;
        transition: transform 0.2s, opacity 0.2s;
    }

    .download-button:hover {
        opacity: 0.9;
        transform: scale(1.02);
    }

    .download-button:active {
        transform: scale(0.98);
    }

    .important-notice {
        padding: 16px;
        background: var(--color-grey-20);
        border-radius: 12px;
    }

    .important-notice p {
        color: var(--color-grey-70);
        font-size: 14px;
        line-height: 1.5;
        text-align: center;
        margin: 0;
    }

    /* Confirm step */
    .confirm-description {
        color: var(--color-grey-70);
        text-align: center;
        line-height: 1.6;
    }

    /* Messages */
    .error-message {
        padding: 12px 16px;
        background: var(--color-error-bg, rgba(239, 68, 68, 0.1));
        border: 1px solid var(--color-error, #ef4444);
        border-radius: 8px;
        color: var(--color-error, #ef4444);
        text-align: center;
    }

    .success-message {
        padding: 12px 16px;
        background: var(--color-success-bg, rgba(34, 197, 94, 0.1));
        border: 1px solid var(--color-success, #22c55e);
        border-radius: 8px;
        color: var(--color-success, #22c55e);
        text-align: center;
        margin-bottom: 16px;
    }
</style>

