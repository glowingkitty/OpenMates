<!--
Buy Credits Payment - Payment form wrapper that determines which tier to show
-->

<script lang="ts" module>
    import { writable, type Writable } from 'svelte/store';
    import { browser } from '$app/environment';
    
    // Store to track selected tier (shared across navigation)
    // SSR-safe initialization - only create store on the client
    export const selectedTierStore: Writable<number> = browser ? writable(0) : {
        subscribe: () => () => {},
        set: () => {},
        update: () => {}
    } as any;
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
    // This is called when payment state changes (processing -> success)
    // For fast payments: called immediately when payment succeeds
    // For slow payments: called after 10-second timeout when we proceed as if successful
    function handlePaymentComplete(event: CustomEvent<{ state: string, payment_intent_id?: string, isDelayed?: boolean }>) {
        const paymentState = event.detail?.state;
        
        // Only navigate to confirmation screen on success state
        // This handles both immediate success and delayed success (after timeout)
        if (paymentState === 'success') {
            // Navigate to confirmation screen
            dispatch('openSettings', {
                settingsPath: 'billing/buy-credits/confirmation',
                direction: 'forward',
                icon: 'check',
                title: $text('settings.billing.purchase_successful.text')
            });

            // Credits will be updated via WebSocket 'user_credits_updated' or 'payment_completed' event
            // If payment was delayed, notification will be shown when webhook processes payment
            // No need to reload the page
        }
        // For 'processing' or 'failure' states, don't navigate - let Payment component handle UI
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
        width: 90%;
        padding: 0 10px;
    }

    @media (max-width: 480px) {
        .payment-container {
            padding: 0 5px;
        }
    }
</style>

