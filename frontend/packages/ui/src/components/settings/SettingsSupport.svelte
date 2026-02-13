<!--
    SettingsSupport Component

    This component displays support options for users, including:
    - Support One Time: Make a one-time contribution
    - Support Monthly: Set up monthly recurring contribution
    - Sponsor on GitHub link
-->
<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../SettingsItem.svelte';

    const dispatch = createEventDispatcher();

    /**
     * Navigate to one-time support page
     */
    function openSupportOneTime() {
        dispatch('openSettings', {
            settingsPath: 'support/one-time',
            direction: 'forward',
            icon: 'coins',
            title: $text('settings.support.one_time')
        });
    }

    /**
     * Navigate to monthly support page
     */
    function openSupportMonthly() {
        dispatch('openSettings', {
            settingsPath: 'support/monthly',
            direction: 'forward',
            icon: 'calendar',
            title: $text('settings.support.monthly')
        });
    }

    /**
     * Open GitHub Sponsors page in a new tab.
     * Links to the OpenMates creator's GitHub Sponsors page.
     */
    function openGitHubSponsors() {
        window.open('https://github.com/sponsors/glowingkitty', '_blank', 'noopener,noreferrer');
    }
</script>

<SettingsItem
    type="submenu"
    icon="subsetting_icon subsetting_icon_coins"
    title={$text('settings.support.one_time')}
    subtitleTop={$text('settings.support.one_time_description')}
    onClick={openSupportOneTime}
/>

<SettingsItem
    type="submenu"
    icon="subsetting_icon subsetting_icon_calendar"
    title={$text('settings.support.monthly')}
    subtitleTop={$text('settings.support.monthly_description')}
    onClick={openSupportMonthly}
/>

<SettingsItem
    type="submenu"
    icon="subsetting_icon subsetting_icon_volunteering"
    title={$text('settings.support_sponsor_github')}
    subtitleTop={$text('settings.support_sponsor_github_description')}
    onClick={openGitHubSponsors}
/>