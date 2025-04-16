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
    export let initialState: 'idle' | 'processing' | 'success' = 'idle';
    export let isGift: boolean = false;

    // Consent state
    let hasConsentedToLimitedRefund = false;

    // Payment state
    let paymentState: 'idle' | 'processing' | 'success' = initialState;

    // Payment form state
    /* showPaymentForm is no longer needed; payment form is always rendered and initialized regardless of consent */

    // References to child components
    let paymentFormComponent;

    // Revolut/Payment state
    let revolutPublicKey: string | null = null;
    let orderToken: string | null = null;
    let lastOrderId: string | null = null;
    let cardFieldInstance: any = null;
    let cardFieldLoaded: boolean = false;
    let isLoading = false;
    let isButtonCooldown = false;
    let errorMessage: string | null = null;
    let validationErrors: string | null = null;
    let pollTimeoutId: number | null = null;
    let isPollingStopped = false;
    let userEmail: string | null = null;
    
    // Timeout for card payment submission (UI-level)
    let cardSubmitTimeoutId: number | null = null;

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
        console.debug('[initializeCardField] called', {
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
            console.debug('[initializeCardField] Destroying previous cardFieldInstance');
            try { cardFieldInstance.destroy(); } catch (e) { console.warn('[initializeCardField] Error destroying previous instance', e); }
            cardFieldInstance = null;
        }

        validationErrors = null;
        try {
            console.debug('[initializeCardField] Creating card field instance...');
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
                    console.debug('[initializeCardField] onSuccess called');
                    // Clear card submit timeout if it exists
                    if (cardSubmitTimeoutId) {
                        clearTimeout(cardSubmitTimeoutId);
                        cardSubmitTimeoutId = null;
                    }
                    errorMessage = null;
                    validationErrors = null;
                    paymentState = 'processing';
                    pollOrderStatus();
                },
                onError(error) {
                    console.debug('[initializeCardField] onError called', error);
                    // Clear card submit timeout if it exists
                    if (cardSubmitTimeoutId) {
                        clearTimeout(cardSubmitTimeoutId);
                        cardSubmitTimeoutId = null;
                    }
                    errorMessage = error?.message ? error.message.replace(/\. /g, '.<br>') : 'Unknown error';
                    validationErrors = null;
                    paymentState = 'idle';
                    isLoading = false;
                    isButtonCooldown = true;
                    setTimeout(() => {
                        isButtonCooldown = false;
                    }, 2000);
                    if (paymentFormComponent) {
                        paymentFormComponent.setPaymentFailed(errorMessage);
                    }
                },
                onValidation(errors) {
                    console.debug('[initializeCardField] onValidation called', errors);
                    // Only show the 'message' field from each error object
                    const concatenatedErrors = errors?.map(e => e?.message || String(e)).join('; ');
                    if (concatenatedErrors?.length) {
                        validationErrors = concatenatedErrors;
                        errorMessage = null;
                    } else {
                        validationErrors = null;
                    }
                }
            });
            cardFieldLoaded = true;
            console.debug('[initializeCardField] Card field initialized successfully');
        } catch (error) {
            console.error('[initializeCardField] Error initializing card field', error);
            errorMessage = `Failed to initialize payment field. ${error instanceof Error ? error.message : String(error)}`;
            cardFieldInstance = null;
            cardFieldLoaded = false;
        }
        console.debug('[initializeCardField] function end', { cardFieldLoaded, cardFieldInstance });
    }

    // --- Poll Backend for Order Status ---
    async function pollOrderStatus() {
        if (!orderToken) {
            errorMessage = 'Order token missing. Cannot verify payment status.';
            return;
        }
        let attempts = 0;
        const maxAttempts = 5; // Reduced from 20 for a ~10 second timeout
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
                    paymentState = 'idle';
                    errorMessage = 'Payment failed or was cancelled. Please try again.';
                    validationErrors = null;
                    orderToken = null;
                    lastOrderId = null;
                    isPollingStopped = true;
                    if (pollTimeoutId) clearTimeout(pollTimeoutId);
                    pollTimeoutId = null;
                    if (paymentFormComponent) {
                        paymentFormComponent.setPaymentFailed();
                    }
                    return;
                } else {
                    if (attempts < maxAttempts && !isPollingStopped) {
                        pollTimeoutId = setTimeout(poll, pollInterval);
                    } else if (!isPollingStopped) {
                        errorMessage = 'Payment processing timed out. Please check your order status later.';
                        paymentState = 'idle';
                        validationErrors = null;
                        orderToken = null;
                        lastOrderId = null;
                        isPollingStopped = true;
                        if (pollTimeoutId) clearTimeout(pollTimeoutId);
                        pollTimeoutId = null;
                        if (paymentFormComponent) {
                            paymentFormComponent.setPaymentFailed();
                        }
                    }
                }
            } catch (err) {
                errorMessage = `Error checking payment status: ${err instanceof Error ? err.message : String(err)}`;
                paymentState = 'idle';
                validationErrors = null;
                orderToken = null;
                lastOrderId = null;
                isPollingStopped = true;
                if (pollTimeoutId) clearTimeout(pollTimeoutId);
                pollTimeoutId = null;
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
        // No longer need to toggle showPaymentForm; overlay will fade out on consent
        // Optionally, can dispatch an event if parent needs to know
        if (requireConsent && hasConsentedToLimitedRefund) {
            setTimeout(() => {
                dispatch('paymentFormVisibility', { visible: true });
            }, 300);
        }
    }

    // Notify parent when payment form visibility changes
    /* showPaymentForm is removed; no need to track its state for parent notification */

    // Watch payment state and return to form on failure
    // Removed: auto-reset of paymentState from 'failure' to 'idle' (no longer needed, as we set to 'idle' on error directly)

    // --- Automatically load and initialize card field when payment form is shown ---
    // Only initialize card field when form is visible and target is set
    $: if (cardFieldTarget && !cardFieldInstance && paymentState === 'idle') {
        tick().then(() => autoInitCardField());
    }
    async function autoInitCardField() {
        console.debug('[autoInitCardField] called', {
            cardFieldTarget,
            cardFieldInstance,
            paymentState
        });
        // Only run if card field target is set, card field is not already initialized, and payment is idle
        if (
            cardFieldTarget &&
            !cardFieldInstance &&
            paymentState === 'idle'
        ) {
            console.debug('[autoInitCardField] Payment form is present, initializing card field...');
            // Fetch Revolut config if needed
            if (!revolutPublicKey) {
                console.debug('[autoInitCardField] revolutPublicKey missing, calling fetchConfig...');
                await fetchConfig();
                if (!revolutPublicKey) {
                    console.warn('[autoInitCardField] revolutPublicKey still missing after fetchConfig');
                    return;
                }
            }
            // Create order if needed
            if (!orderToken) {
                console.debug('[autoInitCardField] orderToken missing, calling createOrder...');
                const orderCreated = await createOrder();
                if (!orderCreated) {
                    console.warn('[autoInitCardField] orderToken still missing after createOrder');
                    return;
                }
            }
            // Wait for DOM update
            await tick();
            // Initialize card field
            console.debug('[autoInitCardField] Calling initializeCardField...');
            await initializeCardField();
            console.debug('[autoInitCardField] Returned from initializeCardField', { cardFieldInstance });
        } else {
            console.debug('[autoInitCardField] Not initializing card field. State:', {
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
    // Handle PaymentForm submit event to set loading state immediately
    function handleFormSubmit() {
        isLoading = true;
        // Clear any previous card submit timeout
        if (cardSubmitTimeoutId) {
            clearTimeout(cardSubmitTimeoutId);
            cardSubmitTimeoutId = null;
        }
        // Start a timeout for card payment UI response (e.g., 12 seconds)
        cardSubmitTimeoutId = setTimeout(() => {
            errorMessage = 'Payment could not be processed in time. Please try again.';
            paymentState = 'idle';
            isLoading = false;
            // Clean up card field instance and order state
            if (cardFieldInstance) {
                try { cardFieldInstance.destroy(); } catch {}
                cardFieldInstance = null;
            }
            cardFieldLoaded = false;
            orderToken = null;
            lastOrderId = null;
            if (paymentFormComponent && typeof paymentFormComponent.setPaymentFailed === 'function') {
                paymentFormComponent.setPaymentFailed(errorMessage);
            }
            cardSubmitTimeoutId = null;
        }, 12000); // 12 seconds
    }
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
                hasConsentedToLimitedRefund={hasConsentedToLimitedRefund}
                validationErrors={validationErrors}
                paymentError={errorMessage}
                isLoading={isLoading}
                isButtonCooldown={isButtonCooldown}
                on:submitPayment={handleFormSubmit}
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
        background: var(--color-grey-20);
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
