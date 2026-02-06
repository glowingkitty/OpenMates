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
    import SettingsSoftwareUpdate from './server/SettingsSoftwareUpdate.svelte';
    import SettingsCommunitySuggestions from './server/SettingsCommunitySuggestions.svelte';
    import SettingsStats from './server/SettingsStats.svelte';
    import SettingsGiftCardGenerator from './server/SettingsGiftCardGenerator.svelte';

    const dispatch = createEventDispatcher();
    
    // Track current view within this component
    let currentView = $state('main');
    let childComponent = $state(null);

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

        scrollToTop();
    }

    function showCommunitySuggestions(event = null) {
        if (event) event.stopPropagation();

        currentView = 'communitySuggestions';
        childComponent = SettingsCommunitySuggestions;

        dispatch('openSettings', {
            settingsPath: 'server/community-suggestions',
            direction: 'forward',
            icon: 'users',
            title: $text('settings.server.community_suggestions.text'),
            translationKey: 'settings.server.community_suggestions'
        });

        scrollToTop();
    }

    function showStatsSettings(event = null) {
        if (event) event.stopPropagation();

        currentView = 'stats';
        childComponent = SettingsStats;

        dispatch('openSettings', {
            settingsPath: 'server/stats',
            direction: 'forward',
            icon: 'usage',
            title: $text('settings.server.stats.text'),
            translationKey: 'settings.server.stats'
        });

        scrollToTop();
    }

    function showGiftCardGenerator(event = null) {
        if (event) event.stopPropagation();

        currentView = 'giftCards';
        childComponent = SettingsGiftCardGenerator;

        dispatch('openSettings', {
            settingsPath: 'server/gift-cards',
            direction: 'forward',
            icon: 'gift_cards',
            title: $text('settings.server.gift_cards.text'),
            translationKey: 'settings.server.gift_cards'
        });

        scrollToTop();
    }

    function scrollToTop() {
        // Find settings content element and scroll to top
        const settingsContent = document.querySelector('.settings-content-wrapper');
        if (settingsContent) {
            settingsContent.scrollTo({
                top: 0,
                behavior: 'smooth'
            });
        }
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
    <SettingsItem
        icon="users"
        title={$text('settings.server.community_suggestions.text')}
        subtitleTop="Manage demo chats from community-shared conversations"
        onClick={() => showCommunitySuggestions()}
    />
    <SettingsItem
        icon="usage"
        title={$text('settings.server.stats.text')}
        subtitleTop="View global server usage and growth metrics"
        onClick={() => showStatsSettings()}
    />
    <SettingsItem
        icon="gift_cards"
        title={$text('settings.server.gift_cards.text')}
        subtitleTop={$text('settings.server.gift_cards.subtitle.text')}
        onClick={() => showGiftCardGenerator()}
    />
{:else if currentView === 'softwareUpdate' && childComponent}
    {@const Component = childComponent}
    <Component
        on:back={handleBack}
    />
{:else if currentView === 'communitySuggestions' && childComponent}
    {@const Component = childComponent}
    <Component
        on:back={handleBack}
    />
{:else if currentView === 'stats' && childComponent}
    {@const Component = childComponent}
    <Component
        on:back={handleBack}
    />
{:else if currentView === 'giftCards' && childComponent}
    {@const Component = childComponent}
    <Component
        on:back={handleBack}
    />
{/if}