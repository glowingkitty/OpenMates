<script lang="ts">
    import { text } from '@repo/ui';
    import { onMount, createEventDispatcher, tick } from 'svelte';
    import { fade } from 'svelte/transition';
    import { getWebsiteUrl, routes } from '../config/links';
    import RevolutCheckout from '@revolut/checkout';
    import { apiEndpoints, getApiEndpoint } from '../config/api';
    import { userProfile, updateProfile } from '../stores/userProfile'; // Import updateProfile
    import { get } from 'svelte/store';

    // Import our new component modules
    import LimitedRefundConsent from './payment/LimitedRefundConsent.svelte';
    import PaymentForm from './payment/PaymentForm.svelte';
    import ProcessingPayment from './payment/ProcessingPayment.svelte';

    const dispatch = createEventDispatcher();

    // Accept props
    export let purchasePrice: number = 20;
    export let currency: string = 'EUR';
    export let credits_amount: number = 21000;
    export let requireConsent: boolean = true;
    export let compact: boolean = false;
    export let initialState: 'idle' | 'processing' | 'success' | 'failure' = 'idle';
    export let isGift: boolean = false;

    // Consent state
    let hasConsentedToLimitedRefund = false;

    // Sensitive data toggle
    let showSensitiveData = false;

    // Payment state
    let paymentState: 'idle' | 'processing' | 'success' | 'failure' = initialState;

    // Payment form state
    export let showPaymentForm = !requireConsent;

    // References to child components
    let paymentFormComponent;

    // Store payment details for re-use after failure
    let paymentDetails = {
        nameOnCard: '',
        cardNumber: '',
        expireDate: '',
        cvv: '',
        lastFourDigits: ''
    };

    // Revolut/Payment state
    let revolutPublicKey: string | null = null;
    let orderToken: string | null = null;
    let lastOrderId: string | null = null;
    let cardFieldInstance: any = null;
    let cardFieldLoaded: boolean = false;
    let isLoading = false;
    let errorMessage: string | null = null;
    let validationErrors: string | null = null;
    let pollTimeoutId: number | null = null;
    let isPollingStopped = false;
    let userEmail: string | null = null;

    // CardField target from PaymentForm
    let cardFieldTarget: HTMLElement;
    
    // Subscribe to userProfile store
    // Allowed locales for Revolut card field
    const allowedRevolutLocales = [
        "en", "en-US", "nl", "fr", "de", "cs", "it", "lt", "pl", "pt", "es", "hu", "sk", "ja", "sv", "bg", "ro", "ru", "el", "hr", "auto"
    ];

    // Helper to map user profile language to allowed locale
    function mapLocale(lang: string | null | undefined): typeof allowedRevolutLocales[number] {
        if (!lang) return "en";
        // Try exact match
        if (allowedRevolutLocales.includes(lang)) return lang as typeof allowedRevolutLocales[number];
        // Try language only (e.g., "en" from "en-GB")
        const base = lang.split('-')[0];
        if (allowedRevolutLocales.includes(base)) return base as typeof allowedRevolutLocales[number];
        return "en";
    }

    let darkmode = false;
    let locale: typeof allowedRevolutLocales[number] = "en";

    let userProfileUnsubscribe = userProfile.subscribe(profile => {
        darkmode = !!profile.darkmode;
        locale = mapLocale(profile.language);
    });

    // Helper to get Revolut card field class based on dark mode
    function getRevolutCardFieldClass() {
        return darkmode ? 'revolut-card-field-dark' : 'revolut-card-field-light';
    }

    // --- Fetch user email ---
    async function fetchUserEmail() {
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.settings.user.getEmail), {
                credentials: 'include'
            });
            if (!response.ok) throw new Error('Failed to fetch user email');
            const data = await response.json();
            userEmail = data.email || null;
        } catch (err) {
            userEmail = null;
        }
    }

    // --- Fetch Revolut Config ---
    async function fetchConfig() {
        isLoading = true;
        errorMessage = null;
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.config), {
                credentials: 'include'
            });
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const config = await response.json();
            if (!config.revolut_public_key) throw new Error('Revolut Public Key not found in config response.');
            revolutPublicKey = config.revolut_public_key;
        } catch (error) {
            errorMessage = `Failed to load payment configuration. ${error instanceof Error ? error.message : String(error)}`;
        } finally {
            isLoading = false;
        }
    }

    // --- Create Payment Order ---
    async function createOrder() {
        if (!revolutPublicKey) {
            errorMessage = 'Cannot create order: Revolut Public Key is missing.';
            return false;
        }
        isLoading = true;
        errorMessage = null;
        orderToken = null;
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.createOrder), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    credits_amount: credits_amount,
                    currency: currency
                })
            });
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(`Failed to create order: ${response.status} ${response.statusText}. ${errorData.detail || ''}`);
            }
            const order = await response.json();
            if (!order.order_token) throw new Error('Order created, but order_token is missing in the response.');
            orderToken = order.order_token;
            lastOrderId = order.order_id;
            return true;
        } catch (error) {
            errorMessage = `Failed to create payment order. ${error instanceof Error ? error.message : String(error)}`;
            return false;
        } finally {
            isLoading = false;
        }
    }

    // --- Initialize CardField ---
    async function initializeCardField() {
        console.log('[initializeCardField] called', {
            orderToken,
            cardFieldTarget,
            revolutPublicKey
        });

        if (!orderToken || !cardFieldTarget || !revolutPublicKey) {
            console.warn('[initializeCardField] Missing prerequisites:', {
                orderToken,
                cardFieldTarget,
                revolutPublicKey
            });
            errorMessage = 'Cannot initialize payment field: Missing Order ID, target element, or Public Key.';
            cardFieldLoaded = false;
            return;
        }

        // Destroy previous instance
        if (cardFieldInstance) {
            console.log('[initializeCardField] Destroying previous cardFieldInstance');
            try { cardFieldInstance.destroy(); } catch (e) { console.warn('[initializeCardField] Error destroying previous instance', e); }
            cardFieldInstance = null;
        }

        validationErrors = null;
        try {
            console.log('[initializeCardField] Creating card field instance...');
            const environment = 'sandbox';
            const { createCardField } = await RevolutCheckout(orderToken, environment);
            cardFieldInstance = createCardField({
                target: cardFieldTarget,
                theme: darkmode ? 'dark' : 'light',
                locale: locale as
                    | "en" | "en-US" | "nl" | "fr" | "de" | "cs" | "it" | "lt" | "pl" | "pt" | "es" | "hu" | "sk" | "ja" | "sv" | "bg" | "ro" | "ru" | "el" | "hr" | "auto",
                classes: {
                    default: getRevolutCardFieldClass(),
                    invalid: 'revolut-card-field--invalid'
                },
                onSuccess() {
                    console.log('[initializeCardField] onSuccess called');
                    errorMessage = null;
                    validationErrors = null;
                    showPaymentForm = false;
                    paymentState = 'processing';
                    pollOrderStatus();
                },
                onError(error) {
                    console.error('[initializeCardField] onError called', error);
                    errorMessage = `Payment failed: ${error?.message || 'Unknown error'}`;
                    validationErrors = null;
                    paymentState = 'failure';
                    showPaymentForm = true;
                    cardFieldLoaded = false;
                    if (paymentFormComponent) {
                        paymentFormComponent.setPaymentFailed();
                    }
                },
                onValidation(errors) {
                    console.log('[initializeCardField] onValidation called', errors);
                    const concatenatedErrors = errors?.join('; ');
                    if (concatenatedErrors?.length) {
                        validationErrors = concatenatedErrors;
                        errorMessage = null;
                    } else {
                        validationErrors = null;
                    }
                }
            });
            cardFieldLoaded = true;
            console.log('[initializeCardField] Card field initialized successfully');
        } catch (error) {
            console.error('[initializeCardField] Error initializing card field', error);
            errorMessage = `Failed to initialize payment field. ${error instanceof Error ? error.message : String(error)}`;
            cardFieldInstance = null;
            cardFieldLoaded = false;
        }
        console.log('[initializeCardField] function end', { cardFieldLoaded, cardFieldInstance });
    }

    // --- Poll Backend for Order Status ---
    async function pollOrderStatus() {
        if (!orderToken) {
            errorMessage = 'Order token missing. Cannot verify payment status.';
            return;
        }
        let attempts = 0;
        const maxAttempts = 20;
        const pollInterval = 2000;
        isPollingStopped = false;
        let orderId = lastOrderId;
        if (!orderId) {
            errorMessage = 'Order ID missing. Cannot verify payment status.';
            return;
        }
        async function poll() {
            if (isPollingStopped) return;
            attempts++;
            try {
                const response = await fetch(getApiEndpoint(apiEndpoints.payments.orderStatus), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify({ order_id: orderId })
                });
                if (!response.ok) throw new Error(`Failed to fetch order status: ${response.status} ${response.statusText}`);
                const data = await response.json();
                const state = data.state;
                if (typeof state === 'string' && state.toLowerCase() === 'completed') {
                    paymentState = 'success';
                    errorMessage = null;
                    validationErrors = null;
                    orderToken = null;
                    lastOrderId = null;
                    isPollingStopped = true;
                    if (pollTimeoutId) clearTimeout(pollTimeoutId);
                    pollTimeoutId = null;

                    // Update user profile store with new credits from response
                    if (typeof data.current_credits === 'number') {
                        console.log(`Updating profile credits to: ${data.current_credits}`);
                        updateProfile({ credits: data.current_credits });
                    } else {
                        console.warn('Order completed, but current_credits not found in response. Credits may be stale.');
                    }
                    return;
                } else if (typeof state === 'string' && (state.toLowerCase() === 'failed' || state.toLowerCase() === 'cancelled')) {
                    paymentState = 'failure';
                    errorMessage = 'Payment failed or was cancelled. Please try again.';
                    validationErrors = null;
                    orderToken = null;
                    lastOrderId = null;
                    isPollingStopped = true;
                    if (pollTimeoutId) clearTimeout(pollTimeoutId);
                    pollTimeoutId = null;
                    showPaymentForm = true;
                    if (paymentFormComponent) {
                        paymentFormComponent.setPaymentFailed();
                    }
                    return;
                } else {
                    if (attempts < maxAttempts && !isPollingStopped) {
                        pollTimeoutId = setTimeout(poll, pollInterval);
                    } else if (!isPollingStopped) {
                        errorMessage = 'Payment processing timed out. Please check your order status later.';
                        paymentState = 'failure';
                        validationErrors = null;
                        orderToken = null;
                        lastOrderId = null;
                        isPollingStopped = true;
                        if (pollTimeoutId) clearTimeout(pollTimeoutId);
                        pollTimeoutId = null;
                        showPaymentForm = true;
                        if (paymentFormComponent) {
                            paymentFormComponent.setPaymentFailed();
                        }
                    }
                }
            } catch (err) {
                errorMessage = `Error checking payment status: ${err instanceof Error ? err.message : String(err)}`;
                paymentState = 'failure';
                validationErrors = null;
                orderToken = null;
                lastOrderId = null;
                isPollingStopped = true;
                if (pollTimeoutId) clearTimeout(pollTimeoutId);
                pollTimeoutId = null;
                showPaymentForm = true;
                if (paymentFormComponent) {
                    paymentFormComponent.setPaymentFailed();
                }
            }
        }
        if (pollTimeoutId) clearTimeout(pollTimeoutId);
        pollTimeoutId = null;
        isPollingStopped = false;
        pollTimeoutId = setTimeout(poll, 1500);
    }

    // --- Consent handler ---
    function handleConsentChanged(event) {
        hasConsentedToLimitedRefund = event.detail.consented;
        if (hasConsentedToLimitedRefund) {
            dispatch('consentGiven', { consented: true });
        }
        if (requireConsent && hasConsentedToLimitedRefund && !showPaymentForm) {
            setTimeout(() => {
                showPaymentForm = true;
                dispatch('paymentFormVisibility', { visible: showPaymentForm });
            }, 300);
        }
    }

    // --- Sensitive data toggle handler ---
    function handleToggleSensitiveData(event) {
        showSensitiveData = event.detail.showSensitiveData;
    }

    // --- Payment start handler ---
    async function handleStartPayment(event) {
        console.log('[handleStartPayment] called', { eventDetail: event.detail });

        // Store payment details for potential failure recovery
        paymentDetails = { ...event.detail };
        errorMessage = null;
        validationErrors = null;
        isLoading = true;

        // Fetch user email if not already
        if (!userEmail) await fetchUserEmail();
        if (!userEmail) {
            console.warn('[handleStartPayment] Could not retrieve user email');
            errorMessage = 'Could not retrieve your email address for payment.';
            isLoading = false;
            return;
        }

        // Fetch Revolut config if not already
        if (!revolutPublicKey) await fetchConfig();
        if (!revolutPublicKey) {
            console.warn('[handleStartPayment] Revolut public key missing after fetchConfig');
            isLoading = false;
            return;
        }

        // Create payment order
        const orderCreated = await createOrder();
        if (!orderCreated) {
            console.warn('[handleStartPayment] Order creation failed');
            isLoading = false;
            return;
        }

        // Wait for Svelte to update DOM so cardFieldTarget is bound
        await tick();

        // Initialize CardField
        console.log('[handleStartPayment] Calling initializeCardField...');
        await initializeCardField();
        console.log('[handleStartPayment] Returned from initializeCardField', { cardFieldInstance });

        // Submit payment via CardField
        if (cardFieldInstance) {
            console.log('[handleStartPayment] Submitting payment via cardFieldInstance');
            cardFieldInstance.submit({
                name: event.detail.nameOnCard,
                email: userEmail
            });
        } else {
            console.error('[handleStartPayment] cardFieldInstance is not set after initializeCardField');
            errorMessage = 'Payment field is not ready.';
            isLoading = false;
            return;
        }

        isLoading = false;
        console.log('[handleStartPayment] Payment process finished');
    }

    // Notify parent when payment form visibility changes
    $: if (showPaymentForm !== previousPaymentFormState) {
        if (previousPaymentFormState !== undefined) {
            dispatch('paymentFormVisibility', { visible: showPaymentForm });
        }
        previousPaymentFormState = showPaymentForm;
    }
    let previousPaymentFormState;

    // Watch payment state and return to form on failure
    $: if (paymentState === 'failure') {
        setTimeout(() => {
            paymentState = 'idle';
        }, 1000);
    }

    // --- Automatically load and initialize card field when payment form is shown ---
    // Only initialize card field when form is visible and target is set
    $: if (showPaymentForm && cardFieldTarget && !cardFieldInstance && paymentState === 'idle') {
        tick().then(() => autoInitCardField());
    }
    async function autoInitCardField() {
        console.log('[autoInitCardField] called', {
            showPaymentForm,
            cardFieldTarget,
            cardFieldInstance,
            paymentState
        });
        // Only run if payment form is visible, card field target is set, and card field is not already initialized
        if (
            showPaymentForm &&
            cardFieldTarget &&
            !cardFieldInstance &&
            paymentState === 'idle'
        ) {
            console.log('[autoInitCardField] Payment form is visible, initializing card field...');
            // Fetch Revolut config if needed
            if (!revolutPublicKey) {
                console.log('[autoInitCardField] revolutPublicKey missing, calling fetchConfig...');
                await fetchConfig();
                if (!revolutPublicKey) {
                    console.warn('[autoInitCardField] revolutPublicKey still missing after fetchConfig');
                    return;
                }
            }
            // Create order if needed
            if (!orderToken) {
                console.log('[autoInitCardField] orderToken missing, calling createOrder...');
                const orderCreated = await createOrder();
                if (!orderCreated) {
                    console.warn('[autoInitCardField] orderToken still missing after createOrder');
                    return;
                }
            }
            // Wait for DOM update
            await tick();
            // Initialize card field
            console.log('[autoInitCardField] Calling initializeCardField...');
            await initializeCardField();
            console.log('[autoInitCardField] Returned from initializeCardField', { cardFieldInstance });
        } else {
            console.log('[autoInitCardField] Not initializing card field. State:', {
                showPaymentForm,
                cardFieldTarget,
                cardFieldInstance,
                paymentState
            });
        }
    }

    // Cleanup on destroy
    onMount(() => {
        fetchUserEmail();
        return () => {
            if (cardFieldInstance) {
                try { cardFieldInstance.destroy(); } catch {}
            }
            isPollingStopped = true;
            if (pollTimeoutId) clearTimeout(pollTimeoutId);
            if (userProfileUnsubscribe) userProfileUnsubscribe();
        };
    });
</script>

<div class="payment-component {compact ? 'compact' : ''}">
    {#if paymentState === 'processing' || paymentState === 'success'}
        <ProcessingPayment
            state={paymentState}
            {isGift}
        />
    {:else}
        <div class="payment-form-overlay-wrapper">
            <PaymentForm
                bind:this={paymentFormComponent}
                purchasePrice={purchasePrice}
                currency={currency}
                cardFieldInstance={cardFieldInstance}
                userEmail={userEmail}
                bind:cardFieldTarget
                cardFieldLoaded={cardFieldLoaded}
            />
            {#if requireConsent && !hasConsentedToLimitedRefund}
                <div class="consent-overlay" transition:fade>
                    <LimitedRefundConsent
                        bind:hasConsentedToLimitedRefund={hasConsentedToLimitedRefund}
                        on:consentChanged={handleConsentChanged}
                    />
                </div>
            {/if}
        </div>
    {/if}
</div>

<style>
    .payment-component {
        width: 100%;
        height: 100%;
        position: relative;
    }

    .payment-form-overlay-wrapper {
        position: relative;
        width: 100%;
        height: 100%;
    }

    .consent-overlay {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: var(--color-consent-overlay, #f5f6fa); /* fallback color, can be themed */
        z-index: 10;
        display: flex;
        align-items: center;
        justify-content: center;
        pointer-events: all;
        /* Optional: add a slight box-shadow for separation */
        box-shadow: 0 0 8px 0 rgba(0,0,0,0.04);
        /* Prevent interaction with underlying payment form */
    }

    .consent-overlay :global(*) {
        pointer-events: auto;
    }

    .compact {
        max-width: 500px;
        margin: 0 auto;
    }
</style>
