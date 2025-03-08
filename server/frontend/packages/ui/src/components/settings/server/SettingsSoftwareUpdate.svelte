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

<div class="software-update-container">
    <SettingsItem 
        type="subsubmenu"
        icon="download"
        subtitleTop={$text('settings.new_update_available.text')}
        title={softwareVersion}
    />
    
    <div class="install-button-container">
        <button 
            class="install-button"
            disabled={isInstalling || installComplete}
            on:click={handleInstallUpdate}
        >
            {$text('settings.install_and_restart.text')}
        </button>
    </div>
</div>

<style>
    .software-update-container {
        display: flex;
        flex-direction: column;
        gap: 24px;
    }
    
    .install-button-container {
        margin-top: 8px;
    }

    .install-button {
        background-color: var(--color-primary);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 12px 24px;
        font-size: 16px;
        font-weight: 500;
        cursor: pointer;
        width: 100%;
        position: relative;
        display: flex;
        justify-content: center;
        align-items: center;
        transition: background-color 0.2s;
    }

    .install-button:hover {
        background-color: var(--color-primary-dark, #0056b3);
    }

    .install-button:disabled {
        opacity: 0.7;
        cursor: not-allowed;
    }

    .loading-spinner {
        width: 16px;
        height: 16px;
        border: 2px solid rgba(255, 255, 255, 0.3);
        border-radius: 50%;
        border-top-color: white;
        animation: spin 1s linear infinite;
        margin-right: 8px;
    }

    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
</style>
