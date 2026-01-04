<!--
Settings Recovery Key Component
================================
This component allows users to:
1. View their current recovery key status
2. Generate a new recovery key (which invalidates the old one)

Security Flow (matches signup flow):
1. User must authenticate first (via SecurityAuth component)
2. New recovery key is generated client-side
3. User chooses how to save: Download / Copy to Clipboard / Print
4. User confirms via toggle that they saved it
5. Only then can they click Continue
6. Master key is wrapped with new recovery key and uploaded to server
7. Old recovery key entry is deleted from server

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
    import { notificationStore } from '../../../stores/notificationStore';
    import { 
        downloadRecoveryKey, 
        copyRecoveryKeyToClipboard, 
        printRecoveryKey 
    } from '../../../utils/recoveryKeyUtils';
    import SecurityAuth from './SecurityAuth.svelte';
    import Toggle from '../../Toggle.svelte';

    // ========================================================================
    // STATE
    // ========================================================================

    /** Whether user has a recovery key set up */
    let hasRecoveryKey = $state<boolean | null>(null);

    /** Timestamp when recovery key was last stored */
    let recoveryKeyTimestamp = $state<number | null>(null);

    /** Current step in the flow */
    type Step = 'overview' | 'auth' | 'generating' | 'save';
    let currentStep = $state<Step>('overview');

    /** Whether authentication is in progress */
    let isAuthenticating = $state(false);

    /** User authentication methods - needed for SecurityAuth component */
    let hasPasskey = $state(false);
    let hasPassword = $state(false);
    let has2FA = $state(false);

    /** The newly generated recovery key */
    let newRecoveryKey = $state<string>('');

    /** Recovery key data to send to server */
    let recoveryKeyData = $state<{
        lookupHash: string;
        wrappedMasterKey: string;
        salt: string;
        keyIv: string;
    } | null>(null);

    /** Track which save methods the user has used (for visual feedback) */
    let hasDownloaded = $state(false);
    let hasCopied = $state(false);
    let hasPrinted = $state(false);

    /** User must confirm they saved the key via toggle before continuing */
    let hasConfirmedStorage = $state(false);

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
     * Fetch user's recovery key status and authentication methods.
     * Auth methods are needed for the SecurityAuth component to know
     * which authentication options to display (passkey, password, 2FA).
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
            }

            // Always fetch auth methods from server - needed for SecurityAuth component
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.getUserAuthMethods), {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include'
            });

            if (response.ok) {
                const data = await response.json();
                // Set recovery key status if not already set from profile
                if (hasRecoveryKey === null) {
                    hasRecoveryKey = data.has_recovery_key || false;
                }
                // Set authentication methods for SecurityAuth component
                hasPasskey = data.has_passkey || false;
                hasPassword = data.has_password || false;
                has2FA = data.has_2fa || false;
                console.log('[SettingsRecoveryKey] Auth methods loaded:', { hasPasskey, hasPassword, has2FA, hasRecoveryKey });
            } else {
                console.error('[SettingsRecoveryKey] Failed to fetch auth methods');
                if (hasRecoveryKey === null) {
                    hasRecoveryKey = false;
                }
            }
        } catch (error) {
            console.error('[SettingsRecoveryKey] Error fetching recovery key status:', error);
            if (hasRecoveryKey === null) {
                hasRecoveryKey = false;
            }
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

    /** Whether Continue button should be enabled */
    let canContinue = $derived(hasConfirmedStorage && !isSaving);

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
     * Does NOT auto-download - user must choose how to save.
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

            // Step 9: Store the data for later submission (when user clicks Continue)
            recoveryKeyData = {
                lookupHash,
                wrappedMasterKey,
                salt: saltB64,
                keyIv
            };

            console.log('[SettingsRecoveryKey] Recovery key generated successfully');

            // Move to save step - user must choose how to save
            currentStep = 'save';

        } catch (error) {
            console.error('[SettingsRecoveryKey] Error generating recovery key:', error);
            errorMessage = error instanceof Error ? error.message : 'Failed to generate recovery key';
            currentStep = 'overview';
        }
    }

    // ========================================================================
    // SAVE METHODS (using shared utilities from recoveryKeyUtils.ts)
    // ========================================================================

    /**
     * Download the recovery key as a text file.
     */
    function handleDownload() {
        const result = downloadRecoveryKey(newRecoveryKey);
        if (result.success) {
            hasDownloaded = true;
        }
    }

    /**
     * Copy the recovery key to clipboard.
     */
    async function handleCopy() {
        const result = await copyRecoveryKeyToClipboard(newRecoveryKey);
        if (result.success) {
            hasCopied = true;
            notificationStore.success($text('enter_message.press_and_hold_menu.copied_to_clipboard.text'), 3000);
        } else {
            notificationStore.error($text('signup.copy_failed.text'), 3000);
        }
    }

    /**
     * Open print dialog with the recovery key.
     */
    function handlePrint() {
        const result = printRecoveryKey(newRecoveryKey);
        if (result.success) {
            hasPrinted = true;
        }
    }

    // ========================================================================
    // SERVER SUBMISSION
    // ========================================================================

    /**
     * Save the new recovery key to the server.
     * Only called after user confirms storage via toggle and clicks Continue.
     * This replaces the old recovery key.
     */
    async function saveRecoveryKey() {
        if (!recoveryKeyData) {
            errorMessage = 'No recovery key data to save';
            return;
        }

        if (!hasConfirmedStorage) {
            errorMessage = $text('settings.security.recovery_key_confirm_required.text');
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

                // Reset state and go back to overview
                resetState();
                currentStep = 'overview';
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
     * Reset all temporary state.
     */
    function resetState() {
        newRecoveryKey = '';
        recoveryKeyData = null;
        hasDownloaded = false;
        hasCopied = false;
        hasPrinted = false;
        hasConfirmedStorage = false;
        errorMessage = '';
    }

    /**
     * Cancel and go back to overview.
     */
    function handleCancel() {
        resetState();
        currentStep = 'overview';
    }
</script>

<div class="settings-recovery-key">
    {#if currentStep === 'auth' && isAuthenticating}
        <!-- Authentication Step -->
        <!-- Pass hasPasskey, hasPassword, has2FA so SecurityAuth knows which auth methods to offer -->
        <SecurityAuth
            {hasPasskey}
            {hasPassword}
            {has2FA}
            autoStart={hasPasskey}
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
    {:else if currentStep === 'save'}
        <!-- Save Step - User chooses how to save, then confirms via toggle -->
        <div class="save-container" in:fade>
            <div class="header">
                <div class="icon header_size warning"></div>
                <h2>{$text('settings.security.recovery_key_download_title.text')}</h2>
            </div>

            <div class="warning-box">
                <div class="warning-icon"></div>
                <p>{$text('settings.security.recovery_key_warning.text')}</p>
            </div>

            <!-- Save options - same as signup flow -->
            <div class="save-options">
                <p class="save-instruction">{$text('signup.choose_how_to_save.text')}</p>
                
                <div class="save-buttons">
                    <!-- Download button -->
                    <button
                        class="save-button"
                        class:used={hasDownloaded}
                        onclick={handleDownload}
                    >
                        <div class="clickable-icon icon_download" style="width: 24px; height: 24px"></div>
                        <span>{$text('signup.download.text')}</span>
                        {#if hasDownloaded}
                            <span class="check-mark">✓</span>
                        {/if}
                    </button>
                    
                    <!-- Copy button -->
                    <button
                        class="save-button"
                        class:used={hasCopied}
                        onclick={handleCopy}
                    >
                        <div class="clickable-icon icon_copy" style="width: 24px; height: 24px"></div>
                        <span>{$text('signup.copy.text')}</span>
                        {#if hasCopied}
                            <span class="check-mark">✓</span>
                        {/if}
                    </button>
                    
                    <!-- Print button -->
                    <button
                        class="save-button"
                        class:used={hasPrinted}
                        onclick={handlePrint}
                    >
                        <span class="print-icon">🖨️</span>
                        <span>{$text('signup.print.text')}</span>
                        {#if hasPrinted}
                            <span class="check-mark">✓</span>
                        {/if}
                    </button>
                </div>
            </div>

            <div class="important-notice">
                <p>{$text('settings.security.recovery_key_important_no_html.text')}</p>
            </div>

            {#if errorMessage}
                <div class="error-message" in:fade>
                    {errorMessage}
                </div>
            {/if}

            <!-- Confirmation toggle - must be checked before Continue is enabled -->
            <div class="confirmation-section">
                <div class="confirmation-row">
                    <Toggle bind:checked={hasConfirmedStorage} id="confirm-storage-toggle" />
                    <label for="confirm-storage-toggle" class="confirmation-text">
                        {$text('signup.i_stored_recovery_key.text')}
                    </label>
                </div>
                <p class="toggle-hint">{$text('signup.click_toggle_to_continue.text')}</p>
            </div>

            <!-- Action buttons -->
            <div class="action-buttons">
                <button
                    class="secondary-button"
                    onclick={handleCancel}
                    disabled={isSaving}
                >
                    {$text('common.cancel.text')}
                </button>
                <button
                    class="primary-button"
                    onclick={saveRecoveryKey}
                    disabled={!canContinue}
                >
                    {#if isSaving}
                        <div class="button-spinner"></div>
                    {:else}
                        {$text('common.continue.text')}
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
        min-width: 120px;
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

    .secondary-button {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        padding: 12px 24px;
        background: var(--color-grey-20);
        color: var(--color-grey-80);
        border: 1px solid var(--color-grey-30);
        border-radius: 12px;
        cursor: pointer;
        font-size: 16px;
        font-weight: 500;
        transition: opacity 0.2s, transform 0.2s;
        min-width: 120px;
    }

    .secondary-button:hover:not(:disabled) {
        background: var(--color-grey-25);
    }

    .secondary-button:disabled {
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

    /* Save step */
    .save-container {
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

    /* Save options - matching signup flow */
    .save-options {
        width: 100%;
        display: flex;
        flex-direction: column;
        gap: 12px;
    }

    .save-instruction {
        color: var(--color-grey-60);
        font-size: 14px;
        text-align: center;
        margin: 0;
    }

    .save-buttons {
        display: flex;
        gap: 10px;
        justify-content: center;
        flex-wrap: wrap;
    }

    .save-button {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 10px 16px;
        background: var(--color-grey-20);
        border: 1px solid var(--color-grey-30);
        border-radius: 10px;
        cursor: pointer;
        font-size: 14px;
        font-weight: 500;
        color: var(--color-grey-80);
        transition: all 0.2s ease;
        position: relative;
    }

    .save-button:hover {
        background: var(--color-grey-25);
        border-color: var(--color-grey-40);
        transform: translateY(-1px);
    }

    .save-button:active {
        transform: translateY(0);
    }

    .save-button.used {
        background: var(--color-success-bg, rgba(34, 197, 94, 0.1));
        border-color: var(--color-success, #22c55e);
    }

    .check-mark {
        color: var(--color-success, #22c55e);
        font-weight: bold;
        font-size: 16px;
    }

    .print-icon {
        font-size: 18px;
        line-height: 1;
    }

    .important-notice {
        padding: 16px;
        background: var(--color-grey-15);
        border-radius: 12px;
    }

    .important-notice p {
        color: var(--color-grey-60);
        font-size: 13px;
        line-height: 1.5;
        text-align: center;
        margin: 0;
    }

    /* Confirmation section */
    .confirmation-section {
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding: 16px;
        background: var(--color-grey-15);
        border-radius: 12px;
    }

    .confirmation-row {
        display: flex;
        align-items: center;
        gap: 12px;
    }

    .confirmation-text {
        color: var(--color-grey-70);
        font-size: 15px;
        cursor: pointer;
    }

    .toggle-hint {
        color: var(--color-grey-50);
        font-size: 13px;
        margin: 0;
        padding-left: 48px;
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
