
<script lang="ts">
    import { text } from '@repo/ui';
    import { onMount, createEventDispatcher } from 'svelte';
    import { fade, fly } from 'svelte/transition';
    import { tooltip } from '../../../../actions/tooltip';
    import { getApiEndpoint, apiEndpoints } from '../../../../config/api';
    import { setRecoveryKeyLoaded, setRecoveryKeyData } from '../../../../stores/recoveryKeyState';
    import * as cryptoService from '../../../../services/cryptoService';

    const dispatch = createEventDispatcher();
    
    let loading = true;
    let keyDownloaded = false;
    let recoveryKey: string = '';
    let showOptions = true;
    let showDownloadContent = false;
    
    // Store the lookup hash and wrapped key for later use in RecoveryKeyBottomContent
    let recoveryKeyLookupHash: string = '';
    let wrappedMasterKey: string = '';
    
    onMount(async () => {
        // Don't automatically request backup codes until user chooses to create them
    });
    
    async function requestRecoveryKey() {
        loading = true;
        // Reset recovery key loaded state
        setRecoveryKeyLoaded(false);
        
        try {
            // Generate recovery key locally
            recoveryKey = cryptoService.generateSecureRecoveryKey();
            
            // Get the user's email to create the lookup hash
            const email = cryptoService.getEmailDecryptedWithMasterKey();
            if (!email) {
                console.error('Could not retrieve email for recovery key generation');
                loading = false;
                return;
            }
            
            // Get the master key that needs to be wrapped
            const masterKey = cryptoService.getKeyFromStorage();
            if (!masterKey) {
                console.error('Could not retrieve master key for wrapping');
                loading = false;
                return;
            }
            
            // Generate salt for key derivation
            const salt = cryptoService.generateSalt();
            const saltB64 = cryptoService.uint8ArrayToBase64(salt);
            
            // Create a hash of the recovery key for lookup (using the same salt as for key derivation)
            // This is similar to how password login works, but without using the email
            recoveryKeyLookupHash = await cryptoService.hashKey(recoveryKey, salt);
            
            // Derive wrapping key from recovery key
            const wrappingKey = await cryptoService.deriveKeyFromPassword(recoveryKey, salt);
            
            // Encrypt (wrap) the master key with the recovery key
            wrappedMasterKey = cryptoService.encryptKey(masterKey, wrappingKey);
            
            // Store the data in the recoveryKeyData store for RecoveryKeyBottomContent to use
            setRecoveryKeyData(recoveryKeyLookupHash, wrappedMasterKey, saltB64);
            
            // Update recovery key loaded state
            loading = false;
            setRecoveryKeyLoaded(true);
            
            // Auto download immediately if user hasn't downloaded manually
            if (!keyDownloaded && recoveryKey) {
                downloadRecoveryKey();
            }
        } catch (err) {
            console.error('Error getting recovery key:', err);
            loading = false;
        }
    }
    
    // confirmCodesStored function removed - now handled in Step5BottomContent.svelte

    function downloadRecoveryKey() {
        if (!recoveryKey) {
            // If no recovery key available, try fetching it again
            requestRecoveryKey();
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
    }
    
    function handleCreateRecoveryKey() {
        showOptions = false;
        showDownloadContent = true;
        requestRecoveryKey();
    }
    
    function handleSkip() {
        dispatch('step', { step: 'profile_picture' }); // Skip to next step
    }
</script>

<div class="content">
    <div class="signup-header">
        <div class="icon header_size warning"></div>
        <h2 class="signup-menu-title">{@html $text('signup.recovery_key.text')}</h2>
    </div>

    {#if showOptions}
        <div class="options-container" in:fade>
            <p class="instruction-text">{@html $text('signup.click_on_an_option.text')}</p>
            
            <!-- Create Recovery Key Option -->
            <button
                class="option-button recommended"
                on:click={handleCreateRecoveryKey}
            >
                <div class="recommended-badge">
                    <div class="thumbs-up-icon"></div>
                    <span>{@html $text('signup.recommended.text')}</span>
                </div>
                <div class="option-header">
                    <div class="option-icon">
                        <div class="clickable-icon icon_create" style="width: 25px; height: 25px"></div>
                    </div>
                    <div class="option-content">
                        <h3 class="option-title">{@html $text('signup.create_recovery_key.text')}</h3>
                    </div>
                </div>
                <p class="option-description">{@html $text('signup.create_recovery_key_description.text')}</p>
            </button>

            <!-- Skip Option -->
            <button 
                class="option-button"
                on:click={handleSkip}
            >
                <div class="option-header">
                    <div class="option-icon">
                        <div class="clickable-icon icon_back" style="width: 25px; height: 25px; transform: rotate(180deg);"></div>
                    </div>
                    <div class="option-content">
                        <h3 class="option-title">{@html $text('signup.skip.text')}</h3>
                    </div>
                </div>
                <p class="option-description">{@html $text('signup.accept_lockedout_risk.text')}</p>
            </button>
            
            <p class="warning-text">{@html $text('signup.we_cant_help_you.text')}</p>
        </div>
    {/if}

    {#if showDownloadContent}
        <div class="download-content" in:fade>
            <div class="text-block">
                {$text('signup.dont_lose_access.text')}
            </div>

            <mark>
                {$text('signup.store_recovery_key_safely.text')}
            </mark>

            {#if !loading && recoveryKey}
            <button
                class="clickable-icon icon_download download-button"
                on:click={downloadRecoveryKey}
                aria-label={$text('enter_message.press_and_hold_menu.download.text')}
                use:tooltip
                transition:fade
            ></button>
            {/if}
        </div>
    {/if}
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
    }

    .text-block {
        margin: 20px 0 20px 0;
        text-align: center;
    }

    .download-button {
        width: 87px;
        height: 87px;
        transition: transform 0.2s;
        margin-top: 30px;
    }

    .download-button:hover {
        transform: scale(1.05);
    }

    .download-button:active {
        transform: scale(0.95);
    }

    .download-icon {
        width: 40px;
        height: 40px;
        mask: url(/icons/download.svg) no-repeat 50% 50%;
        mask-size: contain;
        -webkit-mask: url(/icons/download.svg) no-repeat 50% 50%;
        -webkit-mask-size: contain;
        background-color: var(--color-white);
    }
    
    /* Options styling */
    .options-container {
        width: 100%;
        max-width: 400px;
        display: flex;
        flex-direction: column;
        gap: 16px;
        height: 100%;
        position: relative;
    }
    
    .instruction-text {
        color: var(--color-grey-60);
        font-size: 16px;
        text-align: center;
        margin-bottom: 8px;
    }
    
    .option-button {
        display: flex;
        flex-direction: column;
        gap: 5px;
        padding: 15px;
        background: var(--color-grey-20);
        border-radius: 16px;
        cursor: pointer;
        transition: all 0.2s ease;
        text-align: left;
        width: 100%;
        height: auto;
        position: relative;
    }
    
    .option-button.recommended {
        border: 3px solid transparent;
        background: linear-gradient(var(--color-grey-20), var(--color-grey-20)) padding-box,
                    var(--color-primary) border-box;
    }
    
    .option-header {
        display: flex;
        align-items: center;
        gap: 16px;
    }
    
    .option-icon {
        flex-shrink: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        width: 38px;
        height: 38px;
        background: var(--color-grey-15);
        border-radius: 8px;
    }
    
    .option-content {
        flex: 1;
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    
    .option-title {
        font-size: 16px;
        font-weight: 600;
        color: var(--color-grey-80);
        margin: 0;
    }
    
    .option-description {
        font-size: 14px;
        color: var(--color-grey-60);
        margin: 0;
        line-height: 1.4;
        text-align: center;
    }
    
    .warning-text {
        font-size: 14px;
        color: var(--color-grey-80);
        text-align: center;
        margin-top: auto;
        position: absolute;
        bottom: 5px;
        left: 0;
        right: 0;
        padding-bottom: 16px;
    }
    
    .download-content {
        display: flex;
        flex-direction: column;
        align-items: center;
        width: 100%;
    }

    .recommended-badge {
        position: absolute;
        top: 0;
        transform: translateY(-50%);
        background: var(--color-primary);
        border-radius: 19px;
        padding: 6px 12px;
        display: flex;
        align-items: center;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
        z-index: 2;
    }
    
    .thumbs-up-icon {
        width: 13px;
        height: 13px;
        background-image: url('@openmates/ui/static/icons/thumbsup.svg');;
        background-size: contain;
        background-repeat: no-repeat;
        filter: invert(1);
        margin-right: 6px;
    }
    
    .recommended-badge span {
        color: white;
        font-size: 14px;
        font-weight: 500;
    }
</style>
