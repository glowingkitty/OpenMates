<!--
Gift Cards Redeem - Component for redeeming gift card codes
Reuses the existing GiftCardRedeem component
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import GiftCardRedeem from '../billing/GiftCardRedeem.svelte';

    const dispatch = createEventDispatcher();

    /**
     * Handle successful gift card redemption
     * Navigates to the redeemed list after redemption
     */
    function handleGiftCardRedeemed() {
        // Navigate to redeemed list
        dispatch('openSettings', {
            settingsPath: 'gift_cards/redeemed',
            direction: 'forward',
            icon: 'coins',
            title: $text('settings.gift_cards.redeemed.text')
        });
    }

    /**
     * Handle cancel action - navigate back to gift cards main
     */
    function handleCancel() {
        dispatch('openSettings', {
            settingsPath: 'gift_cards',
            direction: 'backward',
            icon: 'coins',
            title: $text('settings.gift_cards.text')
        });
    }
</script>

<GiftCardRedeem
    on:redeemed={handleGiftCardRedeemed}
    on:cancel={handleCancel}
/>
