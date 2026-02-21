<!-- yaml_details
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
component:
  name: SettingsSoftwareUpdate
  description: Component for checking and installing software updates
  states:
    - checking: Initial state showing loading indicator and checking for updates message
    - updateAvailable: Shows version and install button
    - installing: Installing update state showing download progress
    - restarting: Server restarting state
    - complete: Installation complete state with success message
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { createEventDispatcher, onMount } from 'svelte';
    import SettingsItem from '../../SettingsItem.svelte';
    import { fade } from 'svelte/transition';

    const dispatch = createEventDispatcher();

    // Generate version number based on current date
    const currentDate = new Date();
    const versionYear = currentDate.getFullYear();
    const versionMonth = String(currentDate.getMonth() + 1).padStart(2, '0');
    const versionDay = String(currentDate.getDate()).padStart(2, '0');
    const softwareVersion = `v${versionYear}.${versionMonth}.${versionDay}`;
    
    // State variables
    let isChecking = $state(true);
    let updateState = $state('idle'); // idle, installing, restarting, complete
    let subtitleText = $state($text('settings.new_update_available'));
    
    function handleInstallUpdate() {
        // Set installing state
        updateState = 'installing';
        
        // Simulate installation process - downloading
        setTimeout(() => {
            // Transition to restarting state
            updateState = 'restarting';
            
            // Simulate server restart
            setTimeout(() => {
                // Transition to complete state
                updateState = 'complete';
                subtitleText = $text('settings.installed');
                
                // Reset state after showing completion message
                setTimeout(() => {
                    dispatch('back');
                }, 2000);
            }, 3000);
        }, 3000);
    }

    onMount(() => {
        // Simulate checking for updates
        setTimeout(() => {
            isChecking = false;
        }, 2000);
    });
</script>

{#if isChecking}
    <div class="checking-container" in:fade={{ duration: 300 }}>
        <span class="search-icon"></span>
        <p class="checking-text">{$text('settings.checking_for_updates')}</p>
    </div>
{:else}
    <div in:fade={{ duration: 300 }}>
        <SettingsItem 
            type="heading"
            icon="subsetting_icon download"
            subtitleTop={subtitleText}
            title={softwareVersion}
        />

        {#if updateState === 'idle'}
            <div class="install-button-container">
                <button onclick={handleInstallUpdate}>
                    {$text('settings.install')}
                </button>
            </div>

            <p class="restart-notice">{@html $text('settings.server_will_be_restarted')}</p>
        {:else if updateState === 'installing'}
            <div class="progress-container" in:fade={{ duration: 300 }}>
                <span class="download-icon"></span>
                <p class="progress-text">{$text('settings.installing_update')}</p>
            </div>
        {:else if updateState === 'restarting'}
            <div class="progress-container" in:fade={{ duration: 300 }}>
                <span class="server-icon"></span>
                <p class="progress-text">{$text('settings.restarting_server')}</p>
            </div>
        {:else if updateState === 'complete'}
            <div class="progress-container" in:fade={{ duration: 300 }}>
                <span class="check-icon"></span>
                <p class="progress-text">{$text('settings.update_successful')}</p>
            </div>
        {/if}
    </div>
{/if}

<style>
    .checking-container,
    .progress-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        margin-top: 40px;
        width: 100%;
    }
    
    .search-icon,
    .download-icon,
    .server-icon,
    .check-icon {
        width: 57px;
        height: 57px;
        -webkit-mask-size: contain;
        mask-size: contain;
        background: var(--color-primary);
    }
    
    .search-icon {
        -webkit-mask: url('@openmates/ui/static/icons/search.svg') no-repeat center;
        mask: url('@openmates/ui/static/icons/search.svg') no-repeat center;
    }
    
    .download-icon {
        -webkit-mask: url('@openmates/ui/static/icons/download.svg') no-repeat center;
        mask: url('@openmates/ui/static/icons/download.svg') no-repeat center;
    }
    
    .server-icon {
        -webkit-mask: url('@openmates/ui/static/icons/server.svg') no-repeat center;
        mask: url('@openmates/ui/static/icons/server.svg') no-repeat center;
    }
    
    .check-icon {
        -webkit-mask: url('@openmates/ui/static/icons/check.svg') no-repeat center;
        mask: url('@openmates/ui/static/icons/check.svg') no-repeat center;
        background: #58BC00;
    }
    
    .checking-text,
    .progress-text {
        color: var(--color-grey-60);
        font-size: 14px;
        text-align: center;
    }
    
    .install-button-container {
        display: flex;
        justify-content: center;
        align-items: center;
        margin-top: 10px;
    }

    .restart-notice {
        color: var(--color-grey-60);
        font-size: 14px;
        text-align: center;
        margin-top: 10px;
    }
</style>
