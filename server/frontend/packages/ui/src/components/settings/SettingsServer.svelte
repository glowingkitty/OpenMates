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
    import SettingsItem from '../SettingsItem.svelte';
    import SettingsSoftwareUpdate from './server/SettingsSoftwareUpdate.svelte';

    const dispatch = createEventDispatcher();
    
    // Track current view within this component
    let currentView = 'main';
    let childComponent = null;

    function showSoftwareUpdateSettings(event = null) {
        // Stop propagation to prevent the event from bubbling up
        if (event) event.stopPropagation();
        
        currentView = 'softwareUpdate';
        childComponent = SettingsSoftwareUpdate;
        
        dispatch('openSettings', {
            settingsPath: 'server/software-update', 
            direction: 'forward',
            icon: 'download',
            title: $text('settings.software_updates.text'),
            translationKey: 'settings.software_updates'
        });
    }

    // Handle navigation back event
    function handleBack() {
        currentView = 'main';
        childComponent = null;
        
        // Let parent Settings component know we want to go back to server main view
        dispatch('navigateBack');
    }
</script>

{#if currentView === 'main'}
    <SettingsItem 
        icon="download"
        title={$text('settings.software_updates.text')}
        onClick={() => showSoftwareUpdateSettings()}
    />
{:else if currentView === 'softwareUpdate' && childComponent}
    <svelte:component 
        this={childComponent}
        on:back={handleBack}
    />
{/if}