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
    import { onMount } from 'svelte';
    import { fade } from 'svelte/transition';
    import { tooltip } from '../../../../actions/tooltip';
    import { getApiEndpoint, apiEndpoints } from '../../../../config/api';
    import { setBackupCodesLoaded } from '../../../../stores/backupCodesState';
    import { tfaAppIcons } from '../../../../config/tfa';
    import { userDB } from '../../../../services/userDB'; // Import userDB service

    // Accept selected app name from parent
    export let selectedAppName: string | null = null;
    let loadingAppName = true; // Track loading state for app name

    // Get the icon class for the app name, or undefined if not found
    $: tfaAppIconClass = selectedAppName && selectedAppName in tfaAppIcons ? tfaAppIcons[selectedAppName] : undefined;

    let loading = true;
    let codesDownloaded = false;
    let backupCodes: string[] = [];

    onMount(async () => {
        // Load TFA app name from IndexedDB
        try {
            await userDB.init(); // Ensure DB is initialized
            const userData = await userDB.getUserData();
            
            // If we have a TFA app name in the database, use it
            if (userData?.tfa_app_name) {
                selectedAppName = userData.tfa_app_name;
            }
        } catch (error) {
            console.error("Error loading TFA app name from DB:", error);
        } finally {
            loadingAppName = false;
        }
        
        await requestBackupCodes();
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
</script>

<div class="content">
    <div class="signup-header">
        <div class="icon header_size text"></div>
        <h2 class="signup-menu-title">{@html $text('signup.backup_codes.text')}</h2>
    </div>

    <div class="text-block">
        {@html $text('signup.allows_you_to_log_in_without_tfa.text').replace('{tfa_app}', '')}
        
        <!-- App name container similar to Login2FA.svelte -->
        <!-- <div class="app-name-container"> -->
        {#if selectedAppName}
            <p class="app-name">
                <span class="app-name-content">
                    {#if tfaAppIconClass}
                        <span class="icon provider-{tfaAppIconClass} mini-icon"></span>
                    {/if}
                    <span>{selectedAppName}</span>
                </span>
            </p>
        {:else}
            <span>{$text('signup.your_tfa_app.text')}</span>
        {/if}
        <!-- </div> -->
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

    .app-name-container {
        margin: 10px 0;
        opacity: 1;
        overflow: hidden;
    }

    .app-name {
        display: flex;
        justify-content: center;
        width: 100%;
        margin: 5px 0;
    }
    
    .app-name-content {
        display: flex;
        align-items: center;
    }

    .mini-icon {
        width: 38px;
        height: 38px;
        border-radius: 8px;
        margin-right: 10px;
        opacity: 1;
    }

    .download-button {
        width: 60px;
        height: 60px;
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
</style>