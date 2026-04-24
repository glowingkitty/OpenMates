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

    // Store to pass purchased credits amount to the confirmation screen.
    // Set by WebSocket handler when payment_completed arrives, read by SettingsBuyCreditsConfirmation.
    export const purchasedCreditsStore: Writable<number> = browser ? writable(0) : {
        subscribe: () => () => {},
        set: () => {},
        update: () => {}
    } as Writable<number>;
</script>

<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import { text } from '@repo/ui';
    import { pricingTiers } from '../../../config/pricing';
    import Payment from '../../Payment.svelte';
    import BankTransferPayment from '../../payment/BankTransferPayment.svelte';
    import Toggle from '../../Toggle.svelte';
    import { getApiEndpoint, apiEndpoints } from '../../../config/api';
    import * as cryptoService from '../../../services/cryptoService';
    import { loadStripe } from '@stripe/stripe-js';
    import PaymentAuth from './PaymentAuth.svelte';
    import { webSocketService } from '../../../services/websocketService';
    import { pendingInvoiceStore } from '../../../stores/pendingInvoiceStore';

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
        const currencyKey = selectedCurrency.toLowerCase() as 'eur' | 'usd';
        const amount = tier.price[currencyKey] ?? 0;
        // Convert to cents (EUR and USD both use 2 decimal places)
        return amount * 100;
    });
    // SEPA-only tier auto-routes to bank transfer (cards can't process this tier)
    let isSepaOnlyTier = $derived(!!tier.bank_transfer_only);

    // EU27 VAT country codes — must match backend geo_utils.EU_VAT_COUNTRY_CODES.
    // Non-EU cards (incl. CH, NO, GB, US…) require Checkout Sessions (Managed Payments).
    const EU_VAT_COUNTRIES = new Set([
        "AT","BE","BG","CY","CZ","DE","DK","EE","ES","FI",
        "FR","GR","HR","HU","IE","IT","LT","LU","LV","MT",
        "NL","PL","PT","RO","SE","SI","SK",
    ]);

    function isEuCard(country: string | null | undefined): boolean {
        return !!country && EU_VAT_COUNTRIES.has(country.toUpperCase());
    }

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
            country: string | null;
        };
        created: number;
    }> = $state([]);
    let selectedPaymentMethodId: string | null = $state(null);
    // Start as true so the {:else} branch (Payment.svelte) does not mount and call
    // createOrder() before onMount has had a chance to check for saved methods.
    // This prevents a premature mount that creates a stale PaymentIntent causing
    // the real payment to fail with payment_intent.payment_failed from Stripe.
    let isLoadingPaymentMethods = $state(true);
    let showPaymentForm = $state(false);
    let showAuthModal = $state(false);
    let authMethods: { has_passkey: boolean; has_2fa: boolean } | null = $state(null);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let stripe: any = $state(null);
    let isProcessingPayment = $state(false);

    // providerOverride: if the user explicitly switches mode from the saved-method view
    let savedMethodProviderOverride: 'stripe' | 'managed' | null = $state(null);
    // True when backend says use_managed_payments (non-EU user → Checkout Session flow)
    let isManaged = $state(false);

    // Bank transfer state
    let showBankTransfer = $state(false);
    let bankTransferAvailable = $state(false);

    // Check if bank transfer is available (from /config response)
    async function checkBankTransferAvailability() {
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.config), { credentials: 'include' });
            if (response.ok) {
                const config = await response.json();
                bankTransferAvailable = config.bank_transfer_available || false;
            }
        } catch {
            bankTransferAvailable = false;
        }
    }

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

    // Track whether we already navigated to confirmation (prevents double-navigation)
    let hasNavigatedToConfirmation = $state(false);

    /**
     * WebSocket handler: fires when the backend confirms payment_completed.
     * Immediately navigates to the confirmation screen with the purchased credits amount,
     * bypassing the 30-second timeout fallback in Payment.svelte.
     */
    function handlePaymentCompleted(payload: { order_id: string; credits_purchased: number; current_credits: number }) {

        if (hasNavigatedToConfirmation) return; // Prevent duplicate navigation
        hasNavigatedToConfirmation = true;

        // Store the purchased credits so the confirmation screen can display them
        purchasedCreditsStore.set(payload.credits_purchased);

        dispatch('openSettings', {
            settingsPath: 'billing/buy-credits/confirmation',
            direction: 'forward',
            icon: 'check',
            title: $text('settings.billing.purchase_successful')
        });
    }

    // Load payment methods on mount — also detect active provider and register WebSocket listener
    onMount(async () => {
        // Listen for payment_completed WebSocket events so we can navigate instantly
        // instead of waiting for the 30-second timeout in Payment.svelte
        webSocketService.on('payment_completed', handlePaymentCompleted);
        await Promise.all([
            detectProviderAndLoadMethods(),
            checkBankTransferAvailability(),
        ]);
    });

    // Cleanup WebSocket listener when component is destroyed
    onDestroy(() => {
        webSocketService.off('payment_completed', handlePaymentCompleted);
    });

    /**
     * Detect the active payment mode from /config, then load saved payment methods
     * if EU (PaymentIntent flow). Non-EU users use Checkout Sessions — Stripe handles
     * saved methods internally, so we skip the list and show the payment form directly.
     */
    async function detectProviderAndLoadMethods() {
        isLoadingPaymentMethods = true;
        try {
            const configResponse = await fetch(getApiEndpoint(apiEndpoints.payments.config), { credentials: 'include' });
            if (configResponse.ok) {
                const config = await configResponse.json();
                isManaged = !!config.use_managed_payments;
            }

            if (isManaged) {
                // Non-EU: Checkout Session handles its own saved methods — skip list
                showPaymentForm = true;
            } else {
                await checkPaymentMethods();
            }
        } catch (error) {
            console.error('Error loading payment methods:', error);
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
                const allMethods = data.payment_methods || [];

                // Only EU cards can use the PaymentIntent/saved-method flow.
                // Non-EU cards must go through Checkout Sessions (Managed Payments)
                // so Stripe can collect and remit local VAT automatically.
                paymentMethods = allMethods.filter((pm: { card: { country: string | null } }) =>
                    isEuCard(pm.card?.country)
                );
                hasSavedPaymentMethods = paymentMethods.length > 0;

                if (!hasSavedPaymentMethods) {
                    // No EU cards — if the user has non-EU cards, route to Checkout Session.
                    // If they have no cards at all, show the new-card payment form.
                    if (allMethods.length > 0) {
                        savedMethodProviderOverride = 'managed';
                    }
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

    // POLAR DISABLED 2026-04-23 — re-enable when Polar account is reactivated
    // async function switchToProvider(newProvider: 'stripe' | 'polar') {
    //     savedMethodProviderOverride = newProvider;
    //     showPaymentForm = false;
    //     hasSavedPaymentMethods = false;
    //     paymentMethods = [];
    //     selectedPaymentMethodId = null;
    //     isLoadingPaymentMethods = true;
    //     await detectProviderAndLoadMethods();
    // }

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

        // Double-check card country at purchase time (guards against null country on mount).
        // Non-EU cards must use Checkout Sessions — switch to managed flow if needed.
        const selectedMethod = paymentMethods.find(pm => pm.id === selectedPaymentMethodId);
        if (selectedMethod && !isEuCard(selectedMethod.card?.country)) {
            savedMethodProviderOverride = 'managed';
            showPaymentForm = true;
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
                // Payment successful — store purchased credits for confirmation screen
                if (hasNavigatedToConfirmation) return; // WebSocket may have already handled this
                hasNavigatedToConfirmation = true;
                // Store pending invoice so SettingsInvoices shows an optimistic row
                // while the Celery task generates the real invoice PDF.
                pendingInvoiceStore.set({
                    orderId: data.order_id,
                    creditsAmount: selectedCreditsAmount,
                    amountSmallestUnit: selectedPrice(),
                    currency: selectedCurrency,
                });
                purchasedCreditsStore.set(selectedCreditsAmount);
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
            // Never show raw Stripe/server error messages to users — use a generic translated message.
            // Technical details are logged to console above for debugging.
            alert($text('signup.payment_failed'));
        } finally {
            isProcessingPayment = false;
        }
    }

    // Handle payment completion from Payment component (for new payment form).
    // This fires when Payment.svelte's timeout fallback eventually triggers paymentStateChange.
    // If WebSocket already navigated us, hasNavigatedToConfirmation prevents double-navigation.
    async function handlePaymentComplete(event: CustomEvent<{ state: string, payment_intent_id?: string, isDelayed?: boolean }>) {
        const paymentState = event.detail?.state;
        
        if (paymentState === 'success') {
            if (hasNavigatedToConfirmation) return; // WebSocket already handled this
            hasNavigatedToConfirmation = true;

            // Refresh payment methods after successful payment
            // The payment method should now be saved and available for future purchases
            await checkPaymentMethods();

            // Store the selected credits amount for the confirmation screen
            // (WebSocket handler sets this from payload; here we use the locally selected tier)
            purchasedCreditsStore.set(selectedCreditsAmount);
            
            dispatch('openSettings', {
                settingsPath: 'billing/buy-credits/confirmation',
                direction: 'forward',
                icon: 'check',
                title: $text('settings.billing.purchase_successful')
            });
        }
    }
</script>

{#if showBankTransfer || isSepaOnlyTier}
    <!-- Bank transfer payment flow -->
    <div class="bank-transfer-container">
        {#if !isSepaOnlyTier}
            <button class="back-btn" onclick={() => { showBankTransfer = false; }} data-testid="bank-transfer-back">
                &larr; {$text('common.back')}
            </button>
        {/if}
        <BankTransferPayment
            credits_amount={selectedCreditsAmount}
            price={selectedPrice()}
            currency="EUR"
            emailEncryptionKey={cryptoService.getEmailEncryptionKeyForApi()}
            on:paymentStateChange={handlePaymentComplete}
        />
    </div>
{:else if isLoadingPaymentMethods}
    <div class="loading-container">
        <p>{$text('settings.billing.loading_payment_methods')}</p>
    </div>
{:else if hasSavedPaymentMethods && !showPaymentForm}
    <!-- Show saved payment methods (Stripe-only feature) -->
    <div class="payment-methods-container">
        <h3>{$text('settings.billing.select_payment_method')}</h3>
        
        <div class="payment-methods-list">
            {#each paymentMethods as paymentMethod (paymentMethod.id)}
                <div class="payment-method-item" data-testid="payment-method-item">
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
            {isProcessingPayment ? $text('common.processing') : $text('settings.billing.buy_now')}
        </button>

        <div class="provider-switch-container">
            <button class="provider-switch-btn" data-testid="switch-to-non-eu"
                onclick={() => { savedMethodProviderOverride = 'managed'; showPaymentForm = true; }}>
                {$text('signup.switch_to_non_eu_card')}
            </button>
            {#if bankTransferAvailable}
                <button class="provider-switch-btn" onclick={() => { showBankTransfer = true; }} data-testid="switch-to-bank-transfer">
                    {$text('settings.billing.bank_transfer')}
                </button>
            {/if}
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
         Pass savedMethodProviderOverride as initialProviderOverride so the Payment component
         immediately requests the correct provider (e.g. 'polar' when user clicked non-EU card),
         instead of re-detecting from geo which could fall back to stripe. -->
    <div class="payment-container">
        <Payment
            purchasePrice={selectedPrice()}
            currency={selectedCurrency}
            credits_amount={selectedCreditsAmount}
            requireConsent={false}
            compact={false}
            disableWebSocketHandlers={true}
            initialProviderOverride={savedMethodProviderOverride}
            on:paymentStateChange={handlePaymentComplete}
        />
        {#if bankTransferAvailable}
            <div class="provider-switch-container">
                <button class="provider-switch-btn" onclick={() => { showBankTransfer = true; }} data-testid="switch-to-bank-transfer">
                    {$text('settings.billing.bank_transfer')}
                </button>
            </div>
        {/if}
    </div>
{/if}

<style>
    .loading-container {
        padding: var(--spacing-10);
        text-align: center;
    }

    .bank-transfer-container {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .back-btn {
        align-self: flex-start;
        background: none;
        border: none;
        color: var(--ds-color-text-accent);
        cursor: pointer;
        padding: 4px 0;
        font-size: var(--ds-font-size-s);
    }

    .payment-methods-container {
        width: 90%;
        padding: 0 10px;
    }

    .payment-methods-container h3 {
        margin-bottom: var(--spacing-8);
        font-size: var(--font-size-p);
        font-weight: 600;
    }

    .payment-methods-list {
        display: flex;
        flex-direction: column;
        gap: var(--spacing-6);
        margin-bottom: var(--spacing-8);
    }

    .payment-method-item {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: var(--spacing-8);
        background: var(--color-grey-10);
        border-radius: var(--radius-3);
        border: 2px solid transparent;
        transition: border-color var(--duration-normal);
    }

    .payment-method-item:hover {
        border-color: var(--color-grey-30);
    }

    .payment-method-info {
        display: flex;
        flex-direction: column;
        gap: var(--spacing-2);
        flex: 1;
    }

    .card-brand {
        font-weight: 600;
        font-size: var(--font-size-small);
        color: var(--color-grey-80);
    }

    .card-details {
        display: flex;
        gap: var(--spacing-6);
        font-size: var(--font-size-xs);
        color: var(--color-grey-60);
    }

    .card-number {
        font-family: monospace;
    }

    .add-payment-method-btn,
    .buy-now-btn {
        width: 100%;
        padding: var(--spacing-6) var(--spacing-12);
        margin-top: var(--spacing-8);
        border: none;
        border-radius: var(--radius-3);
        font-size: var(--font-size-small);
        font-weight: 600;
        cursor: pointer;
        transition: all var(--duration-normal);
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
        /* Full width — Polar iframe needs to fill the entire panel.
           The Payment component handles its own internal layout. */
        width: 100%;
        padding: 0;
    }

    @media (max-width: 480px) {
        .payment-methods-container {
            padding: 0 5px;
        }
    }

    /* Provider switch button — shown below saved-method list to switch to Polar */
    .provider-switch-container {
        display: flex;
        justify-content: center;
        margin-top: var(--spacing-6);
    }

    .provider-switch-btn {
        background: none;
        border: none;
        padding: 0;
        font-size: var(--font-size-xs);
        color: var(--color-grey-60);
        cursor: pointer;
        text-decoration: underline;
        transition: color var(--duration-fast);
    }

    .provider-switch-btn:hover {
        color: var(--color-grey-80);
    }
</style>
