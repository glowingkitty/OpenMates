<!--
Redeem Gift Card - Component for redeeming gift card codes
This component wraps the GiftCardRedeem component and handles navigation after successful redemption.
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import GiftCardRedeem from './GiftCardRedeem.svelte';

    const dispatch = createEventDispatcher();

    /**
     * Handle successful gift card redemption
     * Navigates to the confirmation screen after redemption
     */
    function handleGiftCardRedeemed() {
        // Navigate to confirmation screen
        dispatch('openSettings', {
            settingsPath: 'billing/buy-credits/confirmation',
            direction: 'forward',
            icon: 'check',
            title: $text('settings.billing.purchase_successful')
        });
    }

    /**
     * Handle cancel action - navigate back to billing settings
     */
    function handleCancel() {
        dispatch('openSettings', {
            settingsPath: 'billing',
            direction: 'back',
            icon: 'coins',
            title: $text('settings.billing')
        });
    }
</script>

<GiftCardRedeem
    on:redeemed={handleGiftCardRedeemed}
    on:cancel={handleCancel}
/>
