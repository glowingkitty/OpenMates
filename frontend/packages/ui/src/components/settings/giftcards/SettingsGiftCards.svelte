<!--
Gift Cards Settings - Main menu for gift card operations
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';

    const dispatch = createEventDispatcher();

    /**
     * Navigate to a gift cards sub-view
     * @param path - The sub-path (e.g., 'redeem', 'redeemed', 'buy')
     * @param iconName - Icon name for the navigation
     * @param translationKey - Translation key for the title (without 'settings.gift_cards_' prefix)
     */
    function navigateToSubview(path: string, iconName: string = 'coins', translationKey: string = path) {
        dispatch('openSettings', {
            settingsPath: `gift_cards/${path}`,
            direction: 'forward',
            icon: iconName,
            title: $text(`settings.gift_cards.${translationKey}`)
        });
    }
</script>

<!-- Redeem Gift Card Menu Item -->
<SettingsItem
    type="submenu"
    icon="subsetting_icon coins"
    title={$text('settings.gift_cards.redeem')}
    onClick={() => navigateToSubview('redeem')}
/>

<!-- View Redeemed Gift Cards Menu Item -->
<SettingsItem
    type="submenu"
    icon="subsetting_icon coins"
    title={$text('settings.gift_cards.redeemed')}
    onClick={() => navigateToSubview('redeemed')}
/>

<!-- Buy Gift Card Menu Item -->
<SettingsItem
    type="submenu"
    icon="subsetting_icon coins"
    title={$text('settings.gift_cards.buy')}
    onClick={() => navigateToSubview('buy')}
/>
