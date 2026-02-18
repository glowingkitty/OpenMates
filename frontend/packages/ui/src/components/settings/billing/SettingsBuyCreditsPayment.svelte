<!--
Buy Credits Payment - Payment form wrapper that determines which tier to show
Supports both saved payment methods and new payment form
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
    } as Writable<number>;
</script>

<script lang="ts">
    import { createEventDispatcher, onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { pricingTiers } from '../../../config/pricing';
    import Payment from '../../Payment.svelte';
    import Toggle from '../../Toggle.svelte';
    import { getApiEndpoint, apiEndpoints } from '../../../config/api';
    import * as cryptoService from '../../../services/cryptoService';
    import { loadStripe } from '@stripe/stripe-js';
    import PaymentAuth from './PaymentAuth.svelte';

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
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let stripe: any = $state(null);
    let isProcessingPayment = $state(false);

    // Dual-provider state for the saved-method flow.
    // The <Payment> component handles provider detection internally when showPaymentForm is true.
    // When showing the saved-method list (Stripe-only), we also detect the active provider
    // so we can show or hide the saved-method UI and the switch-to-Polar button.
    let detectedProvider: 'stripe' | 'polar' | null = $state(null);
    // providerOverride: if the user explicitly switches provider from the saved-method view
    let savedMethodProviderOverride: 'stripe' | 'polar' | null = $state(null);

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

    // Load payment methods on mount — also detect active provider
    onMount(async () => {
        await detectProviderAndLoadMethods();
    });

    /**
     * Detect the active payment provider from /config, then load saved payment methods
     * if on Stripe. Polar does not support saved methods (Stripe-only feature).
     */
    async function detectProviderAndLoadMethods() {
        isLoadingPaymentMethods = true;
        try {
            // Build config URL — append provider_override if the user has explicitly switched
            let configUrl = getApiEndpoint(apiEndpoints.payments.config);
            if (savedMethodProviderOverride) {
                configUrl += `?provider_override=${savedMethodProviderOverride}`;
            }

            const configResponse = await fetch(configUrl, { credentials: 'include' });
            if (configResponse.ok) {
                const config = await configResponse.json();
                detectedProvider = (config.provider as 'stripe' | 'polar') || 'stripe';
            } else {
                // If config fails, assume Stripe (safe default)
                detectedProvider = 'stripe';
            }

            // Saved payment methods are Stripe-only
            if (detectedProvider === 'polar') {
                hasSavedPaymentMethods = false;
                showPaymentForm = true;
                return;
            }

            await checkPaymentMethods();
        } catch (error) {
            console.error('Error detecting provider:', error);
            detectedProvider = 'stripe';
            showPaymentForm = true;
        } finally {
            isLoadingPaymentMethods = false;
        }
    }

    async function checkPaymentMethods() {
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
        }
    }

    /**
     * Switch from the saved-method Stripe view to Polar.
     * Resets saved-method state and re-fetches config with override.
     */
    async function switchToProvider(newProvider: 'stripe' | 'polar') {
        savedMethodProviderOverride = newProvider;
        showPaymentForm = false;
        hasSavedPaymentMethods = false;
        paymentMethods = [];
        selectedPaymentMethodId = null;
        detectedProvider = null;
        isLoadingPaymentMethods = true;
        await detectProviderAndLoadMethods();
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
            
            // Create payment order with saved method
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.processPaymentWithSavedMethod), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    payment_method_id: selectedPaymentMethodId,
                    credits_amount: selectedCreditsAmount,
                    currency: selectedCurrency,
                    email_encryption_key: emailEncryptionKey
                })
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Failed to process payment');
            }

            const data = await response.json();
            
            if (!data.success || !data.client_secret) {
                throw new Error(data.message || 'Payment processing failed');
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
            const { error, paymentIntent } = await stripe.confirmCardPayment(data.client_secret);

            if (error) {
                throw new Error(error.message || 'Payment confirmation failed');
            }

            if (paymentIntent && paymentIntent.status === 'succeeded') {
                // Payment successful
                dispatch('openSettings', {
                    settingsPath: 'billing/buy-credits/confirmation',
                    direction: 'forward',
                    icon: 'check',
                    title: $text('settings.billing.purchase_successful')
                });
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

    // Handle payment completion from Payment component (for new payment form)
    async function handlePaymentComplete(event: CustomEvent<{ state: string, payment_intent_id?: string, isDelayed?: boolean }>) {
        const paymentState = event.detail?.state;
        
        if (paymentState === 'success') {
            // Refresh payment methods after successful payment
            // The payment method should now be saved and available for future purchases
            await checkPaymentMethods();
            
            dispatch('openSettings', {
                settingsPath: 'billing/buy-credits/confirmation',
                direction: 'forward',
                icon: 'check',
                title: $text('settings.billing.purchase_successful')
            });
        }
    }
</script>

{#if isLoadingPaymentMethods}
    <div class="loading-container">
        <p>{$text('settings.billing.loading_payment_methods')}</p>
    </div>
{:else if hasSavedPaymentMethods && !showPaymentForm && detectedProvider === 'stripe'}
    <!-- Show saved payment methods (Stripe-only feature) -->
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

        <!-- Switch to Polar for non-EU cards -->
        <div class="provider-switch-container">
            <button class="provider-switch-btn" onclick={() => switchToProvider('polar')}>
                {$text('signup.switch_to_non_eu_card')}
            </button>
        </div>
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
    <!-- Show payment form for new payment method or Polar provider.
         The <Payment> component handles provider detection and switching internally. -->
    <div class="payment-container">
        <Payment
            purchasePrice={selectedPrice()}
            currency={selectedCurrency}
            credits_amount={selectedCreditsAmount}
            requireConsent={true}
            compact={false}
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

    /* Provider switch button — shown below saved-method list to switch to Polar */
    .provider-switch-container {
        display: flex;
        justify-content: center;
        margin-top: 12px;
    }

    .provider-switch-btn {
        background: none;
        border: none;
        padding: 0;
        font-size: 13px;
        color: var(--color-grey-60);
        cursor: pointer;
        text-decoration: underline;
        transition: color 0.15s;
    }

    .provider-switch-btn:hover {
        color: var(--color-grey-80);
    }
</style>
