<!--
Buy Credits Payment - Payment form wrapper that determines which tier to show
-->

<script lang="ts" module>
    import { writable } from 'svelte/store';
    
    // Store to track selected tier (shared across navigation)
    export const selectedTierStore = writable(0);
</script>

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { pricingTiers } from '../../../config/pricing';
    import Payment from '../../Payment.svelte';

    const dispatch = createEventDispatcher();
    
    let tierIndex = $state(0);
    
    // Subscribe to tier changes
    selectedTierStore.subscribe(value => {
        tierIndex = value;
    });

    let selectedCurrency = $state('EUR');
    
    // Get the tier based on index
    let tier = $derived(pricingTiers[tierIndex] || pricingTiers[0]);
    
    let selectedCreditsAmount = $derived(tier.credits);
    let selectedPrice = $derived(() => {
        const currencyKey = selectedCurrency.toLowerCase() as 'eur' | 'usd' | 'jpy';
        return tier.price[currencyKey];
    });

    // Handle payment completion
    function handlePaymentComplete(event: CustomEvent) {
        // Navigate to confirmation screen
        dispatch('openSettings', {
            settingsPath: 'billing/buy-credits/confirmation',
            direction: 'forward',
            icon: 'check',
            title: $text('settings.billing.purchase_successful.text')
        });

        // Credits will be updated via WebSocket 'user_credits_updated' event
        // No need to reload the page
    }
</script>

<div class="payment-container">
    <Payment
        purchasePrice={selectedPrice()}
        currency={selectedCurrency}
        credits_amount={selectedCreditsAmount}
        requireConsent={true}
        compact={false}
        on:paymentStateChange={handlePaymentComplete}
    />
</div>

<style>
    .payment-container {
        width: 100%;
        padding: 0 10px;
    }

    @media (max-width: 480px) {
        .payment-container {
            padding: 0 5px;
        }
    }
</style>

