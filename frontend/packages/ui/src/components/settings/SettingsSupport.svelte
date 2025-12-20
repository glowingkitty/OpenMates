<!--
    SettingsSupport Component
    
    This component displays support options for users, including:
    - Sponsor on GitHub link
-->
<script lang="ts">
    import { text } from '@repo/ui';
    import SettingsItem from '../SettingsItem.svelte';

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
    icon="subsetting_icon subsetting_icon_volunteering"
    title={$text('settings.support_sponsor_github.text')}
    subtitleTop={$text('settings.support_sponsor_github_description.text')}
    onClick={openGitHubSponsors}
/>