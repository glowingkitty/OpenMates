<!--
Buy Gift Cards Payment - Payment form wrapper for gift card purchases
Supports both saved payment methods and new payment form
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
    import Toggle from '../../Toggle.svelte';
    import { getApiEndpoint, apiEndpoints } from '../../../config/api';
    import * as cryptoService from '../../../services/cryptoService';
    import { loadStripe } from '@stripe/stripe-js';
    import PaymentAuth from '../billing/PaymentAuth.svelte';
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
        const amount = tier.price[currencyKey];
        // Convert to cents for decimal currencies, use as-is for JPY
        return selectedCurrency.toUpperCase() === 'JPY' ? amount : amount * 100;
    });

    // Payment method state
    let hasSavedPaymentMethods = $state(false);
    let paymentMethods: Array<{
        id: string;
        type: string;
        card: {
            brand: string;
            last4: string;
            exp_month: number;
            exp_year: number;
        };
        created: number;
    }> = $state([]);
    let selectedPaymentMethodId: string | null = $state(null);
    let isLoadingPaymentMethods = $state(false);
    let showPaymentForm = $state(false);
    let showAuthModal = $state(false);
    let authMethods: { has_passkey: boolean; has_2fa: boolean } | null = $state(null);
    let stripe: any = $state(null);
    let isProcessingPayment = $state(false);

    let giftCardCode: string | null = $state(null);
    let creditsValue: number = $state(0);
    let orderId: string | null = $state(null);
    let isWaitingForGiftCard = $state(false);
    let delayedPaymentTimeoutId: ReturnType<typeof setTimeout> | null = null;

    // Format card brand name
    function formatCardBrand(brand: string): string {
        const brandMap: Record<string, string> = {
            'visa': 'Visa',
            'mastercard': 'Mastercard',
            'amex': 'American Express',
            'discover': 'Discover',
            'jcb': 'JCB',
            'diners': 'Diners Club',
            'unionpay': 'UnionPay'
        };
        return brandMap[brand.toLowerCase()] || brand.charAt(0).toUpperCase() + brand.slice(1);
    }

    // Format expiration date
    function formatExpDate(expMonth: number, expYear: number): string {
        return `${expMonth.toString().padStart(2, '0')}/${expYear.toString().slice(-2)}`;
    }

    // Load payment methods on mount
    onMount(async () => {
        await checkPaymentMethods();
    });

    async function checkPaymentMethods() {
        isLoadingPaymentMethods = true;
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.listPaymentMethods), {
                credentials: 'include'
            });
            
            if (response.ok) {
                const data = await response.json();
                paymentMethods = data.payment_methods || [];
                hasSavedPaymentMethods = paymentMethods.length > 0;
                
                // If no saved methods, show payment form
                if (!hasSavedPaymentMethods) {
                    showPaymentForm = true;
                }
            } else {
                // If endpoint fails, fall back to payment form
                hasSavedPaymentMethods = false;
                showPaymentForm = true;
            }
        } catch (error) {
            console.error('Error checking payment methods:', error);
            // Fall back to payment form on error
            hasSavedPaymentMethods = false;
            showPaymentForm = true;
        } finally {
            isLoadingPaymentMethods = false;
        }
    }

    // Handle payment method selection
    function handlePaymentMethodToggle(paymentMethodId: string, checked: boolean) {
        if (checked) {
            // Only one payment method can be selected
            selectedPaymentMethodId = paymentMethodId;
        } else {
            selectedPaymentMethodId = null;
        }
    }

    // Handle "Add payment method" button
    function handleAddPaymentMethod() {
        showPaymentForm = true;
    }

    // Handle "Buy now" button
    async function handleBuyNow() {
        if (!selectedPaymentMethodId) {
            return;
        }

        // Check authentication methods
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.getUserAuthMethods), {
                credentials: 'include'
            });
            
            if (response.ok) {
                authMethods = await response.json();
                showAuthModal = true;
            } else {
                console.error('Failed to get auth methods');
                // Proceed without auth modal (shouldn't happen, but handle gracefully)
                await processPayment();
            }
        } catch (error) {
            console.error('Error getting auth methods:', error);
            // Proceed without auth modal
            await processPayment();
        }
    }

    // Handle authentication success
    async function handleAuthSuccess() {
        showAuthModal = false;
        await processPayment();
    }

    // Process payment with saved method
    async function processPayment() {
        if (!selectedPaymentMethodId) {
            return;
        }

        isProcessingPayment = true;
        try {
            // Get email encryption key
            const emailEncryptionKey = cryptoService.getEmailEncryptionKeyForApi();
            
            // Create payment order with saved method (use buy-gift-card endpoint)
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.buyGiftCard), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    credits_amount: selectedCreditsAmount,
                    currency: selectedCurrency,
                    email_encryption_key: emailEncryptionKey,
                    payment_method_id: selectedPaymentMethodId  // Add payment method ID for saved method
                })
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Failed to process payment');
            }

            const data = await response.json();
            
            if (!data.client_secret) {
                throw new Error('Payment order creation failed');
            }

            // Initialize Stripe if not already done
            if (!stripe) {
                const configResponse = await fetch(getApiEndpoint(apiEndpoints.payments.config), {
                    credentials: 'include'
                });
                if (!configResponse.ok) {
                    throw new Error('Failed to load payment configuration');
                }
                const config = await configResponse.json();
                stripe = await loadStripe(config.public_key);
            }

            // Confirm payment with Stripe
            // PaymentIntent is already created with the payment method attached, so we just need to confirm it
            const { error, paymentIntent } = await stripe.confirmCardPayment(data.client_secret);

            if (error) {
                throw new Error(error.message || 'Payment confirmation failed');
            }

            if (paymentIntent && paymentIntent.status === 'succeeded') {
                // Payment successful - wait for gift card creation
                orderId = paymentIntent.id;
                isWaitingForGiftCard = true;
                
                // Show notification that we're waiting for gift card code
                notificationStore.info(
                    $text('settings.gift_cards.buy_processing'),
                    5000
                );

                // Start timeout for gift card creation
                delayedPaymentTimeoutId = setTimeout(() => {
                    if (isWaitingForGiftCard) {
                        // Store delayed flag in sessionStorage
                        sessionStorage.setItem('gift_card_delayed', 'true');
                        // Navigate to confirmation page which will show delayed payment message
                        dispatch('openSettings', {
                            settingsPath: 'gift_cards/buy/confirmation',
                            direction: 'forward',
                            icon: 'check',
                            title: $text('settings.gift_cards.purchase_successful')
                        });
                    }
                }, 20000);
            } else {
                throw new Error('Payment was not successful');
            }
        } catch (error) {
            console.error('Error processing payment:', error);
            alert(error instanceof Error ? error.message : 'An error occurred while processing your payment');
        } finally {
            isProcessingPayment = false;
        }
    }

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
            title: $text('settings.gift_cards.purchase_successful')
        });
    }

    // Handle payment completion from Payment component (for new payment form)
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
                title: $text('settings.gift_cards.purchase_successful')
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
                    title: $text('settings.gift_cards.purchase_successful')
                });
            } else {
                // Show notification that we're waiting for gift card code
                notificationStore.info(
                    $text('settings.gift_cards.buy_processing'),
                    5000
                );
            }
        }
    }

    onDestroy(() => {
        if (delayedPaymentTimeoutId) {
            clearTimeout(delayedPaymentTimeoutId);
        }
    });
</script>

{#if isLoadingPaymentMethods}
    <div class="loading-container">
        <p>{$text('settings.billing.loading_payment_methods')}</p>
    </div>
{:else if hasSavedPaymentMethods && !showPaymentForm}
    <!-- Show saved payment methods -->
    <div class="payment-methods-container">
        <h3>{$text('settings.billing.select_payment_method')}</h3>
        
        <div class="payment-methods-list">
            {#each paymentMethods as paymentMethod (paymentMethod.id)}
                <div class="payment-method-item">
                    <div class="payment-method-info">
                        <div class="card-brand">{formatCardBrand(paymentMethod.card.brand)}</div>
                        <div class="card-details">
                            <span class="card-number">•••• •••• •••• {paymentMethod.card.last4}</span>
                            <span class="card-expiry">{formatExpDate(paymentMethod.card.exp_month, paymentMethod.card.exp_year)}</span>
                        </div>
                    </div>
                    <Toggle
                        checked={selectedPaymentMethodId === paymentMethod.id}
                        on:change={(e) => handlePaymentMethodToggle(paymentMethod.id, e.detail.checked)}
                        ariaLabel={$text('settings.billing.select_payment_method')}
                    />
                </div>
            {/each}
        </div>

        <button
            class="add-payment-method-btn"
            onclick={handleAddPaymentMethod}
        >
            {$text('settings.billing.add_payment_method')}
        </button>

        <button
            class="buy-now-btn"
            class:disabled={!selectedPaymentMethodId || isProcessingPayment}
            onclick={handleBuyNow}
            disabled={!selectedPaymentMethodId || isProcessingPayment}
        >
            {isProcessingPayment ? $text('settings.billing.processing') : $text('settings.billing.buy_now')}
        </button>
    </div>

    {#if showAuthModal && authMethods}
        <PaymentAuth
            hasPasskey={authMethods.has_passkey}
            has2FA={authMethods.has_2fa}
            on:authSuccess={handleAuthSuccess}
            on:authCancel={() => showAuthModal = false}
        />
    {/if}
{:else}
    <!-- Show payment form for new payment method -->
    <div class="payment-container">
        <Payment
            purchasePrice={selectedPrice()}
            currency={selectedCurrency}
            credits_amount={selectedCreditsAmount}
            requireConsent={true}
            compact={false}
            isGiftCard={true}
            disableWebSocketHandlers={true}
            on:paymentStateChange={handlePaymentComplete}
        />
    </div>
{/if}

<style>
    .loading-container {
        padding: 20px;
        text-align: center;
    }

    .payment-methods-container {
        width: 90%;
        padding: 0 10px;
    }

    .payment-methods-container h3 {
        margin-bottom: 16px;
        font-size: 16px;
        font-weight: 600;
    }

    .payment-methods-list {
        display: flex;
        flex-direction: column;
        gap: 12px;
        margin-bottom: 16px;
    }

    .payment-method-item {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 16px;
        background: var(--color-grey-10);
        border-radius: 8px;
        border: 2px solid transparent;
        transition: border-color 0.2s;
    }

    .payment-method-item:hover {
        border-color: var(--color-grey-30);
    }

    .payment-method-info {
        display: flex;
        flex-direction: column;
        gap: 4px;
        flex: 1;
    }

    .card-brand {
        font-weight: 600;
        font-size: 14px;
        color: var(--color-grey-80);
    }

    .card-details {
        display: flex;
        gap: 12px;
        font-size: 13px;
        color: var(--color-grey-60);
    }

    .card-number {
        font-family: monospace;
    }

    .add-payment-method-btn,
    .buy-now-btn {
        width: 100%;
        padding: 12px 24px;
        margin-top: 16px;
        border: none;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.2s;
    }

    .add-payment-method-btn {
        background: var(--color-grey-20);
        color: var(--color-grey-80);
    }

    .add-payment-method-btn:hover {
        background: var(--color-grey-30);
    }

    .buy-now-btn {
        background: var(--color-primary);
        color: white;
    }

    .buy-now-btn:hover:not(.disabled) {
        background: var(--color-primary-dark);
    }

    .buy-now-btn.disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .payment-container {
        width: 90%;
        padding: 0 10px;
    }

    @media (max-width: 480px) {
        .payment-container,
        .payment-methods-container {
            padding: 0 5px;
        }
    }
</style>
