<!--
Recovery Key Top Content - MANDATORY Generation with User-Controlled Storage
============================================================================
This component automatically generates a recovery key during signup, but lets
the user choose HOW to save it (download, copy, or print).

Security Model:
- Recovery key generation is MANDATORY - users cannot skip this step
- User CONTROLS the storage method (not auto-downloaded without consent)
- User must CONFIRM they saved it via toggle before proceeding
- This approach respects user agency while ensuring recovery capability

Flow:
1. Component mounts → auto-generates recovery key
2. User chooses how to save: Download / Copy to Clipboard / Print
3. User confirms via toggle (in RecoveryKeyBottomContent) that they saved it
4. Only then can they proceed to the next step

Security Notes:
- Recovery key is generated client-side using cryptoService
- Recovery key wraps the master key for account recovery
- Server stores only the wrapped key + lookup hash (zero-knowledge)
- We also have account recovery flow, but recovery key is the primary method
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { onMount } from 'svelte';
    import { fade } from 'svelte/transition';
    import { tooltip } from '../../../../actions/tooltip';
    import { setRecoveryKeyLoaded, setRecoveryKeyData } from '../../../../stores/recoveryKeyState';
    import { setRecoveryKeyCreationActive } from '../../../../stores/recoveryKeyUIState';
    import * as cryptoService from '../../../../services/cryptoService';
    import { userDB } from '../../../../services/userDB';
    import { notificationStore } from '../../../../stores/notificationStore';

    // State using Svelte 5 runes
    let loading = $state(true);
    let recoveryKey: string = $state('');
    let loginMethod: string = $state('password');
    let loginSecretText: string = $state('');
    let errorMessage: string = $state('');
    
    // Track which save methods the user has used (for visual feedback)
    let hasDownloaded = $state(false);
    let hasCopied = $state(false);
    let hasPrinted = $state(false);
    
    // Store the lookup hash for later use in RecoveryKeyBottomContent
    let recoveryKeyLookupHash: string = '';
    
    onMount(async () => {
        // Set recovery key creation as active immediately
        setRecoveryKeyCreationActive(true);
        
        // Retrieve the login method from IndexedDB for display purposes
        try {
            await userDB.init();
            const userData = await userDB.getUserData();
            if (userData && userData.login_method) {
                loginMethod = userData.login_method;
            }
            
            // Get the appropriate translation based on the login method
            if (loginMethod === 'password') {
                loginSecretText = $text('signup.password.text');
            } else if (loginMethod === 'passkey') {
                loginSecretText = $text('signup.passkey.text');
            } else if (loginMethod === 'security_key') {
                loginSecretText = $text('signup.security_key.text');
            } else {
                loginSecretText = $text('signup.password.text');
            }
        } catch (error) {
            console.error("Error retrieving login method:", error);
            loginSecretText = $text('signup.password.text');
        }
        
        // Auto-generate recovery key immediately on mount
        await generateRecoveryKey();
    });
    
    /**
     * Generate the recovery key and store data for server submission.
     * Called automatically on mount - recovery key is mandatory.
     */
    async function generateRecoveryKey() {
        loading = true;
        errorMessage = '';
        setRecoveryKeyLoaded(false);
        
        try {
            // Step 1: Generate recovery key locally
            recoveryKey = cryptoService.generateSecureRecoveryKey();
            console.log('[RECOVERY_KEY] Generated secure recovery key');
            
            // Step 2: Get the user's email (needed for lookup hash context)
            const email = cryptoService.getEmailDecryptedWithMasterKey();
            if (!email) {
                errorMessage = $text('signup.recovery_key_error_email.text');
                console.error('[RECOVERY_KEY] Could not retrieve email');
                loading = false;
                return;
            }
            
            // Step 3: Get the master key that needs to be wrapped
            const masterKey = await cryptoService.getKeyFromStorage();
            if (!masterKey) {
                errorMessage = $text('signup.recovery_key_error_encryption_key.text');
                console.error('[RECOVERY_KEY] Could not retrieve master key');
                loading = false;
                return;
            }

            // Step 4: Get the user's email salt for lookup hash generation
            const userEmailSalt = cryptoService.getEmailSalt();
            if (!userEmailSalt) {
                errorMessage = $text('signup.recovery_key_error_encryption_data.text');
                console.error('[RECOVERY_KEY] Email salt is required');
                loading = false;
                return;
            }

            // Step 5: Create a hash of the recovery key for server-side lookup
            recoveryKeyLookupHash = await cryptoService.hashKey(recoveryKey, userEmailSalt);

            // Step 6: Generate salt for key derivation (wrapping the master key)
            const salt = cryptoService.generateSalt();
            const saltB64 = cryptoService.uint8ArrayToBase64(salt);

            // Step 7: Derive wrapping key from recovery key
            const wrappingKey = await cryptoService.deriveKeyFromPassword(recoveryKey, salt);

            // Step 8: Wrap the master key with the recovery key
            const { wrapped: wrappedMasterKey, iv: keyIv } = await cryptoService.encryptKey(masterKey, wrappingKey);

            // Step 9: Store the data for RecoveryKeyBottomContent to send to server
            setRecoveryKeyData(recoveryKeyLookupHash, wrappedMasterKey, saltB64, keyIv);
            
            // Mark as loaded and ready
            loading = false;
            setRecoveryKeyLoaded(true);
            
            console.log('[RECOVERY_KEY] Recovery key generated successfully');
            
        } catch (err) {
            console.error('[RECOVERY_KEY] Error generating recovery key:', err);
            errorMessage = $text('signup.recovery_key_error_generic.text');
            loading = false;
        }
    }

    /**
     * Download the recovery key as a text file.
     */
    function handleDownload() {
        if (!recoveryKey) return;
        
        const content = recoveryKey;
        const blob = new Blob([content], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'openmates_recovery_key.txt';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        
        hasDownloaded = true;
        console.log('[RECOVERY_KEY] Recovery key file downloaded');
    }
    
    /**
     * Copy the recovery key to clipboard.
     */
    async function handleCopy() {
        if (!recoveryKey) return;
        
        try {
            await navigator.clipboard.writeText(recoveryKey);
            hasCopied = true;
            notificationStore.success($text('enter_message.press_and_hold_menu.copied_to_clipboard.text'), 3000);
            console.log('[RECOVERY_KEY] Recovery key copied to clipboard');
        } catch (err) {
            console.error('[RECOVERY_KEY] Failed to copy to clipboard:', err);
            notificationStore.error($text('signup.copy_failed.text'), 3000);
        }
    }
    
    /**
     * Open print dialog with the recovery key.
     * Uses translations for all text content.
     */
    function handlePrint() {
        if (!recoveryKey) return;
        
        // Get translated strings for the print page
        const printTitle = $text('signup.recovery_key_print_title.text');
        const printWarning = $text('signup.recovery_key_print_warning.text');
        const storageTitle = $text('signup.recovery_key_print_storage_title.text');
        const storage1 = $text('signup.recovery_key_print_storage_1.text');
        const storage2 = $text('signup.recovery_key_print_storage_2.text');
        const storage3 = $text('signup.recovery_key_print_storage_3.text');
        const storage4 = $text('signup.recovery_key_print_storage_4.text');
        
        // Create a printable window with the recovery key
        const printWindow = window.open('', '_blank');
        if (printWindow) {
            printWindow.document.write(`
                <!DOCTYPE html>
                <html>
                <head>
                    <title>${printTitle}</title>
                    <style>
                        body {
                            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
                            padding: 40px;
                            max-width: 600px;
                            margin: 0 auto;
                        }
                        h1 {
                            color: #333;
                            font-size: 24px;
                            margin-bottom: 20px;
                        }
                        .warning {
                            background: #fff3cd;
                            border: 1px solid #ffc107;
                            border-radius: 8px;
                            padding: 16px;
                            margin-bottom: 24px;
                        }
                        .warning p {
                            margin: 0;
                            color: #856404;
                        }
                        .key-container {
                            background: #f5f5f5;
                            border: 2px dashed #ccc;
                            border-radius: 8px;
                            padding: 20px;
                            text-align: center;
                        }
                        .recovery-key {
                            font-family: 'Courier New', monospace;
                            font-size: 18px;
                            font-weight: bold;
                            letter-spacing: 2px;
                            word-break: break-all;
                            color: #333;
                        }
                        .instructions {
                            margin-top: 24px;
                            color: #666;
                            font-size: 14px;
                        }
                        .instructions li {
                            margin-bottom: 8px;
                        }
                    </style>
                </head>
                <body>
                    <h1>🔐 ${printTitle}</h1>
                    <div class="warning">
                        <p><strong>⚠️ ${printWarning}</strong></p>
                    </div>
                    <div class="key-container">
                        <div class="recovery-key">${recoveryKey}</div>
                    </div>
                    <div class="instructions">
                        <p><strong>${storageTitle}</strong></p>
                        <ul>
                            <li>${storage1}</li>
                            <li>${storage2}</li>
                            <li>${storage3}</li>
                            <li>${storage4}</li>
                        </ul>
                    </div>
                </body>
                </html>
            `);
            printWindow.document.close();
            printWindow.print();
            hasPrinted = true;
            console.log('[RECOVERY_KEY] Recovery key print dialog opened');
        }
    }
    
    /**
     * Retry generation if there was an error
     */
    function handleRetry() {
        errorMessage = '';
        generateRecoveryKey();
    }
</script>

<div class="content">
    <div class="signup-header">
        <div class="icon header_size warning"></div>
        <h2 class="signup-menu-title">{@html $text('signup.recovery_key.text')}</h2>
    </div>

    <div class="recovery-content" in:fade>
        {#if loading}
            <!-- Loading state while generating -->
            <div class="loading-container">
                <div class="spinner"></div>
                <p class="loading-text">{$text('signup.generating_recovery_key.text')}</p>
            </div>
        {:else if errorMessage}
            <!-- Error state with retry option -->
            <div class="error-container">
                <p class="error-text">{errorMessage}</p>
                <button class="retry-button" onclick={handleRetry}>
                    {$text('login.retry.text')}
                </button>
            </div>
        {:else}
            <!-- Success state - show key and save options -->
            <div class="description-text">
                {@html $text('signup.recovery_key_save_description.text').replace('{login_secret}', loginSecretText)}
            </div>

            <!-- Save options -->
            <div class="save-options">
                <p class="save-instruction">{$text('signup.choose_how_to_save.text')}</p>
                
                <div class="save-buttons">
                    <!-- Download button -->
                    <button
                        class="save-button"
                        class:used={hasDownloaded}
                        onclick={handleDownload}
                        aria-label={$text('enter_message.press_and_hold_menu.download.text')}
                        use:tooltip
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
                        aria-label={$text('signup.copy.text')}
                        use:tooltip
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
                        aria-label={$text('signup.print.text')}
                        use:tooltip
                    >
                        <span class="print-icon">🖨️</span>
                        <span>{$text('signup.print.text')}</span>
                        {#if hasPrinted}
                            <span class="check-mark">✓</span>
                        {/if}
                    </button>
                </div>
            </div>
        {/if}
    </div>
</div>

<style>
    .content {
        padding: 24px;
        height: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
    }

    .signup-header {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 16px;
        margin-bottom: 16px;
    }

    .recovery-content {
        width: 100%;
        max-width: 420px;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 16px;
    }

    .description-text {
        text-align: center;
        color: var(--color-grey-70);
        line-height: 1.5;
        font-size: 15px;
    }

    .warning-box {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 14px 16px;
        background: var(--color-warning-bg, rgba(255, 193, 7, 0.1));
        border-radius: 12px;
        border: 1px solid var(--color-warning, #ffc107);
        width: 100%;
    }

    .warning-box mark {
        background: transparent;
        color: var(--color-grey-80);
        font-weight: 500;
        font-size: 14px;
    }

    .warning-icon {
        width: 24px;
        height: 24px;
        min-width: 24px;
        background-image: url('@openmates/ui/static/icons/warning.svg');
        background-size: contain;
        background-repeat: no-repeat;
        flex-shrink: 0;
    }

    .key-display-section {
        width: 100%;
    }

    .key-container {
        background: var(--color-grey-15);
        border: 2px dashed var(--color-grey-40);
        border-radius: 12px;
        padding: 16px;
        text-align: center;
    }

    .recovery-key-text {
        font-family: 'Courier New', Monaco, monospace;
        font-size: 16px;
        font-weight: 600;
        letter-spacing: 1.5px;
        word-break: break-all;
        color: var(--color-grey-90);
        user-select: all;
        line-height: 1.6;
    }

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
        padding: 14px;
        background: var(--color-grey-15);
        border-radius: 12px;
        width: 100%;
    }

    .important-notice p {
        color: var(--color-grey-60);
        font-size: 13px;
        line-height: 1.5;
        text-align: center;
        margin: 0;
    }

    /* Loading state styles */
    .loading-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 16px;
        padding: 40px 20px;
    }

    .spinner {
        width: 40px;
        height: 40px;
        border: 3px solid var(--color-grey-30);
        border-top-color: var(--color-primary);
        border-radius: 50%;
        animation: spin 1s linear infinite;
    }

    @keyframes spin {
        to {
            transform: rotate(360deg);
        }
    }

    .loading-text {
        color: var(--color-grey-60);
        font-size: 16px;
    }

    /* Error state styles */
    .error-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 16px;
        padding: 20px;
    }

    .error-text {
        color: var(--color-error, #ef4444);
        text-align: center;
    }

    .retry-button {
        padding: 12px 24px;
        background: var(--color-primary);
        color: white;
        border: none;
        border-radius: 12px;
        cursor: pointer;
        font-size: 16px;
        font-weight: 500;
        transition: transform 0.2s;
    }

    .retry-button:hover {
        transform: scale(1.02);
    }
</style>
