<!--
Recovery Key Top Content - MANDATORY Setup
==========================================
This component automatically generates and downloads a recovery key during signup.
Recovery keys are now mandatory - they provide the only way to recover an account
if the user loses access to their password or passkey.

Flow:
1. Component mounts → auto-generates recovery key
2. Auto-downloads recovery key file
3. User must confirm they saved it before continuing

Security Notes:
- Recovery key is generated client-side using cryptoService
- Recovery key wraps the master key for account recovery
- Server stores only the wrapped key + lookup hash (zero-knowledge)
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

    // State using Svelte 5 runes
    let loading = $state(true);
    let keyDownloaded = $state(false);
    let recoveryKey: string = $state('');
    let loginMethod: string = $state('password');
    let loginSecretText: string = $state('');
    let errorMessage: string = $state('');
    
    // Store the lookup hash and wrapped key for later use in RecoveryKeyBottomContent
    let recoveryKeyLookupHash: string = '';
    
    onMount(async () => {
        // Set recovery key creation as active immediately
        setRecoveryKeyCreationActive(true);
        
        // Get the login method for display purposes
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
        await generateAndDownloadRecoveryKey();
    });
    
    /**
     * Generate the recovery key and automatically trigger download.
     * This is the main function that handles the mandatory recovery key setup.
     */
    async function generateAndDownloadRecoveryKey() {
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
                errorMessage = 'Could not retrieve email for recovery key generation. Please try again.';
                console.error('[RECOVERY_KEY] Could not retrieve email');
                loading = false;
                return;
            }
            
            // Step 3: Get the master key that needs to be wrapped
            const masterKey = await cryptoService.getKeyFromStorage();
            if (!masterKey) {
                errorMessage = 'Could not retrieve encryption key. Please try again.';
                console.error('[RECOVERY_KEY] Could not retrieve master key');
                loading = false;
                return;
            }

            // Step 4: Get the user's email salt for lookup hash generation
            const userEmailSalt = cryptoService.getEmailSalt();
            if (!userEmailSalt) {
                errorMessage = 'Missing encryption data. Please try again.';
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
            
            console.log('[RECOVERY_KEY] Recovery key generated successfully, triggering download');
            
            // Step 10: Auto-download the recovery key file
            downloadRecoveryKey();
            
        } catch (err) {
            console.error('[RECOVERY_KEY] Error generating recovery key:', err);
            errorMessage = 'An error occurred while generating your recovery key. Please try again.';
            loading = false;
        }
    }

    /**
     * Download the recovery key as a text file.
     * Called automatically after generation and available for manual re-download.
     */
    function downloadRecoveryKey() {
        if (!recoveryKey) {
            // If no recovery key available, try generating again
            generateAndDownloadRecoveryKey();
            return;
        }
        
        keyDownloaded = true;
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
        
        console.log('[RECOVERY_KEY] Recovery key file downloaded');
    }
    
    /**
     * Retry generation if there was an error
     */
    function handleRetry() {
        errorMessage = '';
        generateAndDownloadRecoveryKey();
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
                <p class="loading-text">{$text('signup.generating_recovery_key.text') || 'Generating your recovery key...'}</p>
            </div>
        {:else if errorMessage}
            <!-- Error state with retry option -->
            <div class="error-container">
                <p class="error-text">{errorMessage}</p>
                <button class="retry-button" onclick={handleRetry}>
                    {$text('common.retry.text') || 'Try Again'}
                </button>
            </div>
        {:else}
            <!-- Success state - show download option and instructions -->
            <div class="text-block">
                {@html $text('signup.recovery_key_mandatory_description.text') || $text('signup.create_recovery_key_description.text').replace('{login_secret}', loginSecretText)}
            </div>

            <div class="download-section">
                <button
                    class="download-button"
                    onclick={downloadRecoveryKey}
                    aria-label={$text('enter_message.press_and_hold_menu.download.text')}
                    use:tooltip
                >
                    <div class="clickable-icon icon_download" style="width: 30px; height: 30px"></div>
                    <span>{$text('signup.download_again.text') || 'Download Again'}</span>
                </button>
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
        margin-bottom: 24px;
    }

    .recovery-content {
        width: 100%;
        max-width: 400px;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 20px;
    }

    .text-block {
        text-align: center;
        color: var(--color-grey-70);
        line-height: 1.5;
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

    .warning-box mark {
        background: transparent;
        color: var(--color-grey-80);
        font-weight: 500;
    }

    .warning-icon {
        width: 24px;
        height: 24px;
        background-image: url('@openmates/ui/static/icons/warning.svg');
        background-size: contain;
        background-repeat: no-repeat;
        flex-shrink: 0;
    }

    .download-section {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 16px;
        padding: 20px;
        background: var(--color-grey-15);
        border-radius: 16px;
        width: 100%;
    }

    .download-instruction {
        color: var(--color-grey-60);
        font-size: 14px;
        text-align: center;
    }

    .download-instruction.success {
        color: var(--color-success, #22c55e);
        font-weight: 500;
    }

    .download-success {
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .checkmark-icon {
        width: 20px;
        height: 20px;
        background-color: var(--color-success, #22c55e);
        mask-image: url('@openmates/ui/static/icons/check.svg');
        mask-size: contain;
        mask-repeat: no-repeat;
        -webkit-mask-image: url('@openmates/ui/static/icons/check.svg');
        -webkit-mask-size: contain;
        -webkit-mask-repeat: no-repeat;
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
        width: 100%;
    }

    .important-notice p {
        color: var(--color-grey-70);
        font-size: 14px;
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
