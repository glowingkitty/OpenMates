<!--
Buy Gift Cards Payment - Payment form wrapper for gift card purchases
-->

<script lang="ts" module>
    import { writable, type Writable } from 'svelte/store';
    import { browser } from '$app/environment';
    
    // Store to track selected tier for gift card purchase (shared across navigation)
    // SSR-safe initialization - only create store on the client
    export const selectedGiftCardTierStore: Writable<number> = browser ? writable(0) : {
        subscribe: () => () => {},
        set: () => {},
        update: () => {}
    } as any;
</script>

<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import { text } from '@repo/ui';
    import { pricingTiers } from '../../../config/pricing';
    import Payment from '../../Payment.svelte';
    import { webSocketService } from '../../../services/websocketService';
    import { notificationStore } from '../../../stores/notificationStore';

    const dispatch = createEventDispatcher();
    
    let tierIndex = $state(0);
    
    // Subscribe to tier changes
    selectedGiftCardTierStore.subscribe(value => {
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

    let giftCardCode: string | null = $state(null);
    let creditsValue: number = $state(0);
    let orderId: string | null = $state(null);

    // Listen for gift card created event from webhook
    function handleGiftCardCreated(payload: { order_id: string, gift_card_code: string, credits_value: number }) {
        console.log('[SettingsGiftCardsBuyPayment] Received gift_card_created notification:', payload);
        
        // Clear any pending timeout
        if (delayedPaymentTimeoutId) {
            clearTimeout(delayedPaymentTimeoutId);
            delayedPaymentTimeoutId = null;
        }
        isWaitingForGiftCard = false;
        
        // Store the gift card code and order ID
        giftCardCode = payload.gift_card_code;
        creditsValue = payload.credits_value;
        orderId = payload.order_id;
        
        // Store in sessionStorage so confirmation component can access it
        if (giftCardCode) {
            sessionStorage.setItem('gift_card_code', giftCardCode);
            sessionStorage.setItem('gift_card_credits', creditsValue.toString());
        }
        
        // Navigate to confirmation screen
        dispatch('openSettings', {
            settingsPath: 'gift_cards/buy/confirmation',
            direction: 'forward',
            icon: 'check',
            title: $text('settings.gift_cards.purchase_successful.text')
        });
    }

    let isWaitingForGiftCard = $state(false);
    let delayedPaymentTimeoutId: ReturnType<typeof setTimeout> | null = null;

    // Handle payment completion
    function handlePaymentComplete(event: CustomEvent<{ state: string, payment_intent_id?: string, isDelayed?: boolean, gift_card_code?: string, credits_value?: number }>) {
        const paymentState = event.detail?.state;
        orderId = event.detail?.payment_intent_id || null;
        
        // Check if gift card code is in the event (from Payment component - only happens if webhook already processed)
        if (event.detail?.gift_card_code) {
            giftCardCode = event.detail.gift_card_code;
            creditsValue = event.detail.credits_value || 0;
            // Clear any pending timeout
            if (delayedPaymentTimeoutId) {
                clearTimeout(delayedPaymentTimeoutId);
                delayedPaymentTimeoutId = null;
            }
            isWaitingForGiftCard = false;
            // Navigate to confirmation immediately with gift card code
            // Store in sessionStorage so confirmation component can access it
            if (giftCardCode) {
                sessionStorage.setItem('gift_card_code', giftCardCode);
                sessionStorage.setItem('gift_card_credits', creditsValue.toString());
            }
            dispatch('openSettings', {
                settingsPath: 'gift_cards/buy/confirmation',
                direction: 'forward',
                icon: 'check',
                title: $text('settings.gift_cards.purchase_successful.text')
            });
            return;
        }
        
        // For gift cards, we wait for the gift_card_created webhook event
        // If payment succeeds but we haven't received the webhook yet, wait up to 20 seconds
        if (paymentState === 'success' && !giftCardCode) {
            isWaitingForGiftCard = true;
            
            // If payment was delayed (already waited 20 seconds), navigate to confirmation with delayed message
            if (event.detail?.isDelayed) {
                // Store delayed flag in sessionStorage
                sessionStorage.setItem('gift_card_delayed', 'true');
                // Navigate to confirmation page which will show delayed payment message
                // The confirmation page will wait for the gift_card_created event
                dispatch('openSettings', {
                    settingsPath: 'gift_cards/buy/confirmation',
                    direction: 'forward',
                    icon: 'check',
                    title: $text('settings.gift_cards.purchase_successful.text')
                });
            } else {
                // Show notification that we're waiting for gift card code
                notificationStore.info(
                    $text('settings.gift_cards.buy_processing.text'),
                    5000
                );
            }
        }
    }

    onMount(() => {
        // Don't register gift_card_created handler here - Payment component already handles it
        // and dispatches it via paymentStateChange event which we handle in handlePaymentComplete
        // This prevents duplicate handlers
    });

    onDestroy(() => {
        // No cleanup needed - Payment component handles all websocket events
    });
</script>

<div class="payment-container">
    <Payment
        purchasePrice={selectedPrice()}
        currency={selectedCurrency}
        credits_amount={selectedCreditsAmount}
        requireConsent={true}
        compact={false}
        isGiftCard={true}
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
