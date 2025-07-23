<!-- yaml_details
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
step_5_top_content_svelte:
    backup_codes_explainer:
        type: 'text'
        text:
            - $text('signup.backup_codes.text')
            - $text('signup.dont_lose_access.text')
            - $text('signup.store_backup_codes_safely.text')
        purpose:
            - 'Explains the purpose of backup codes'
            - 'Asks user to store backup codes safely'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - '2fa'
            - 'backup codes'
        connected_documentation:
            - '/signup/backup-codes'
    download_backup_codes_button:
        type: 'button (icon only)'
        icon: 'download'
        purpose:
            - 'User can download the backup codes if auto-download failed'
        processing:
            - 'On page load, backup codes are auto-downloaded'
            - 'If auto download fails: User clicks the button'
            - 'Backup codes are downloaded'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - '2fa'
            - 'backup codes'
        connected_documentation:
            - '/signup/backup-codes'
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { onMount, createEventDispatcher } from 'svelte';
    import { fade, fly } from 'svelte/transition';
    import { tooltip } from '../../../../actions/tooltip';
    import { getApiEndpoint, apiEndpoints } from '../../../../config/api';
    import { setBackupCodesLoaded } from '../../../../stores/backupCodesState';

    const dispatch = createEventDispatcher();
    
    let loading = true;
    let codesDownloaded = false;
    let backupCodes: string[] = [];
    let showOptions = true;
    let showDownloadContent = false;

    onMount(async () => {
        // Don't automatically request backup codes until user chooses to create them
    });
    
    async function requestBackupCodes() {
        loading = true;
        // Reset backup codes loaded state
        setBackupCodesLoaded(false);
        
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.request_backup_codes), {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include'
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                backupCodes = data.backup_codes;
                loading = false;
                
                // Update backup codes loaded state
                setBackupCodesLoaded(true);
                
                // Auto download immediately if user hasn't downloaded manually
                if (!codesDownloaded && backupCodes.length > 0) {
                    downloadBackupCodes();
                }
                
                // Note: confirmCodesStored is now called from Step5BottomContent when user confirms
            } else {
                console.error('Failed to get backup codes:', data.message);
                // Still set loading to false to show the UI (user can retry by clicking download)
                loading = false;
            }
        } catch (err) {
            console.error('Error getting backup codes:', err);
            loading = false;
        }
    }
    
    // confirmCodesStored function removed - now handled in Step5BottomContent.svelte

    function downloadBackupCodes() {
        if (backupCodes.length === 0) {
            // If no codes available, try fetching them again
            requestBackupCodes();
            return;
        }
        
        codesDownloaded = true;
        const content = backupCodes.join('\n');
        const blob = new Blob([content], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'openmates_backup_codes.txt';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }
    
    function handleCreateBackupCodes() {
        showOptions = false;
        showDownloadContent = true;
        requestBackupCodes();
    }
    
    function handleSkip() {
        dispatch('step', { step: 'profile_picture' }); // Skip to next step
    }
</script>

<div class="content">
    <div class="signup-header">
        <div class="icon header_size warning"></div>
        <h2 class="signup-menu-title">{@html $text('signup.backup_codes.text')}</h2>
    </div>

    {#if showOptions}
        <div class="options-container" in:fade>
            <p class="instruction-text">{@html $text('signup.click_on_an_option.text')}</p>
            
            <!-- Create Backup Codes Option -->
            <button 
                class="option-button recommended"
                on:click={handleCreateBackupCodes}
            >
                <div class="option-header">
                    <div class="option-icon">
                        <div class="clickable-icon icon_create" style="width: 30px; height: 30px"></div>
                    </div>
                    <div class="option-content">
                        <h3 class="option-title">{@html $text('signup.create_backup_codes.text')}</h3>
                    </div>
                </div>
                <p class="option-description">{@html $text('signup.create_backup_codes_description.text')}</p>
            </button>

            <!-- Skip Option -->
            <button 
                class="option-button"
                on:click={handleSkip}
            >
                <div class="option-header">
                    <div class="option-icon">
                        <div class="clickable-icon icon_back" style="width: 30px; height: 30px"></div>
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
                {$text('signup.store_backup_codes_safely.text')}
            </mark>

            {#if !loading && backupCodes.length > 0}
            <button
                class="clickable-icon icon_download download-button"
                on:click={downloadBackupCodes}
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
        margin-bottom: 30px;
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
    
    .option-button.recommended::before {
        content: "Recommended";
        position: absolute;
        top: -10px;
        left: 50%;
        transform: translateX(-50%);
        background: var(--color-primary-50);
        color: white;
        padding: 2px 10px;
        border-radius: 10px;
        font-size: 12px;
        font-weight: 600;
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
        width: 48px;
        height: 48px;
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
    }
    
    .warning-text {
        font-size: 14px;
        color: var(--color-warning);
        text-align: center;
        margin-top: auto;
        font-style: italic;
        position: absolute;
        bottom: 0;
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
</style>