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
    import { createEventDispatcher } from 'svelte';
    import SettingsItem from '../SettingsItem.svelte';
    import SettingsLanguage from './interface/SettingsLanguage.svelte';

    const dispatch = createEventDispatcher();
    
    // Track current view within this component
    let currentView = 'main';
    let childComponent = null;

    // This function will properly dispatch the event to the parent Settings.svelte component
    function showLanguageSettings() {
        currentView = 'language';
        childComponent = SettingsLanguage;
        
        dispatch('openSettings', {
            settingsPath: 'interface/language', 
            direction: 'forward',
            icon: 'language',
            title: $text('settings.language.text')
        });
    }
</script>

{#if currentView === 'main'}
    <SettingsItem 
        type="subsubmenu"
        icon="subsetting_icon subsetting_icon_language"
        subtitle="Language"
        title="English (US)"
        onClick={showLanguageSettings}
    />
{:else if currentView === 'language' && childComponent}
    <svelte:component this={childComponent} />
{/if}