<!-- yaml_details
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml

-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { createEventDispatcher, onMount } from 'svelte';
    import SettingsItem from '../../SettingsItem.svelte';

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
</script>

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

{@html $text('settings.server_will_be_restarted.text')}

<style>
    
    .install-button-container {
        display: flex;
        justify-content: center;
        align-items: center;
        margin-top: 10px;
    }

</style>
