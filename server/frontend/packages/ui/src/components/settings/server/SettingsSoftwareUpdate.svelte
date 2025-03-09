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
    - installing: Installing update state
    - complete: Installation complete state
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
    let isInstalling = false;
    let installComplete = false;
    let isChecking = true;
    
    function handleInstallUpdate() {
        // Set installing state
        isInstalling = true;
        
        // Simulate installation process
        setTimeout(() => {
            isInstalling = false;
            installComplete = true;
            
            // Reset state after showing completion message
            setTimeout(() => {
                installComplete = false;
                dispatch('back');
            }, 2000);
        }, 2000);
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
        <p class="checking-text">{$text('settings.checking_for_updates.text')}</p>
    </div>
{:else}
    <div in:fade={{ duration: 300 }}>
        <SettingsItem 
            type="heading"
            icon="subsetting_icon subsetting_icon_download"
            subtitleTop={$text('settings.new_update_available.text')}
            title={softwareVersion}
        />

        <div class="install-button-container">
            <button 
                disabled={isInstalling || installComplete}
                on:click={handleInstallUpdate}
            >
                {$text('settings.install.text')}
            </button>
        </div>

        <p class="restart-notice">{@html $text('settings.server_will_be_restarted.text')}</p>
    </div>
{/if}

<style>
    .checking-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        margin-top: 40px;
        width: 100%;
    }
    
    .search-icon {
        width: 73px;
        height: 73px;
        -webkit-mask: url('@openmates/ui/static/icons/search.svg') no-repeat center;
        mask: url('@openmates/ui/static/icons/search.svg') no-repeat center;
        -webkit-mask-size: contain;
        mask-size: contain;
        background-color: #9e9e9e;
        margin-bottom: 20px;
    }
    
    .checking-text {
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
