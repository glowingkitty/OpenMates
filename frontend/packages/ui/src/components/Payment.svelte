<script lang="ts">
    import { text } from '@repo/ui';
    import { onMount, createEventDispatcher, tick } from 'svelte';
    import { fade } from 'svelte/transition';
    import { getWebsiteUrl, routes } from '../config/links';
    import RevolutCheckout from '@revolut/checkout';
    import { apiEndpoints, getApiEndpoint } from '../config/api';

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
    let isLoading = false;
    let errorMessage: string | null = null;
    let validationErrors: string | null = null;
    let pollTimeoutId: number | null = null;
    let isPollingStopped = false;
    let userEmail: string | null = null;

    // CardField target from PaymentForm
    let cardFieldTarget: HTMLElement;

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
        if (!orderToken || !cardFieldTarget || !revolutPublicKey) {
            errorMessage = 'Cannot initialize payment field: Missing Order ID, target element, or Public Key.';
            return;
        }
        // Destroy previous instance
        if (cardFieldInstance) {
            try { cardFieldInstance.destroy(); } catch {}
            cardFieldInstance = null;
        }
        validationErrors = null;
        try {
            const environment = 'sandbox';
            const { createCardField } = await RevolutCheckout(orderToken, environment);
            cardFieldInstance = createCardField({
                target: cardFieldTarget,
                locale: 'en',
                // Style the iframe to match your dark/rounded UI
                styles: {
                    default: {
                        fontFamily: 'inherit',
                        fontSize: '16px',
                        color: 'var(--color-grey-100)',
                        background: 'var(--color-grey-0)',
                        border: '2px solid var(--color-grey-0)',
                        borderRadius: '24px',
                        boxShadow: '0 2px 8px rgba(0,0,0,0.05)',
                        padding: '12px 16px 12px 48px',
                        outline: 'none',
                        width: '100%',
                        transition: 'all 0.2s ease-in-out'
                    },
                    focused: {
                        borderColor: 'var(--color-grey-50)',
                        boxShadow: '0 4px 12px rgba(0,0,0,0.08)'
                    },
                    invalid: {
                        color: '#dc3545',
                        borderColor: '#dc3545'
                    },
                    completed: {
                        color: '#28a745'
                    }
                },
                classes: {
                    default: 'input-wrapper',
                    focused: 'input-wrapper input-focused',
                    invalid: 'input-wrapper input-error',
                    completed: 'input-wrapper input-completed'
                },
                onSuccess() {
                    errorMessage = null;
                    validationErrors = null;
                    showPaymentForm = false;
                    paymentState = 'processing';
                    pollOrderStatus();
                },
                onError(error) {
                    errorMessage = `Payment failed: ${error?.message || 'Unknown error'}`;
                    validationErrors = null;
                    paymentState = 'failure';
                    showPaymentForm = true;
                    if (paymentFormComponent) {
                        paymentFormComponent.setPaymentFailed();
                    }
                },
                onValidation(errors) {
                    const concatenatedErrors = errors?.join('; ');
                    if (concatenatedErrors?.length) {
                        validationErrors = concatenatedErrors;
                        errorMessage = null;
                    } else {
                        validationErrors = null;
                    }
                }
            });
        } catch (error) {
            errorMessage = `Failed to initialize payment field. ${error instanceof Error ? error.message : String(error)}`;
            cardFieldInstance = null;
        }
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
        // Store payment details for potential failure recovery
        paymentDetails = { ...event.detail };
        errorMessage = null;
        validationErrors = null;
        isLoading = true;

        // Fetch user email if not already
        if (!userEmail) await fetchUserEmail();
        if (!userEmail) {
            errorMessage = 'Could not retrieve your email address for payment.';
            isLoading = false;
            return;
        }

        // Fetch Revolut config if not already
        if (!revolutPublicKey) await fetchConfig();
        if (!revolutPublicKey) {
            isLoading = false;
            return;
        }

        // Create payment order
        const orderCreated = await createOrder();
        if (!orderCreated) {
            isLoading = false;
            return;
        }

        // Wait for Svelte to update DOM so cardFieldTarget is bound
        await tick();

        // Initialize CardField
        await initializeCardField();

        // Submit payment via CardField
        if (cardFieldInstance) {
            cardFieldInstance.submit({
                name: event.detail.nameOnCard,
                email: userEmail
            });
        } else {
            errorMessage = 'Payment field is not ready.';
            isLoading = false;
            return;
        }

        isLoading = false;
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
    $: autoInitCardField();
    async function autoInitCardField() {
        // Only run if payment form is visible, card field target is set, and card field is not already initialized
        if (
            showPaymentForm &&
            cardFieldTarget &&
            !cardFieldInstance &&
            paymentState === 'idle'
        ) {
            // Fetch Revolut config if needed
            if (!revolutPublicKey) {
                await fetchConfig();
                if (!revolutPublicKey) return;
            }
            // Create order if needed
            if (!orderToken) {
                const orderCreated = await createOrder();
                if (!orderCreated) return;
            }
            // Wait for DOM update
            await tick();
            // Initialize card field
            await initializeCardField();
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
        };
    });
</script>

<div class="payment-component {compact ? 'compact' : ''}">
    {#if requireConsent && !showPaymentForm}
        <LimitedRefundConsent
            bind:hasConsentedToLimitedRefund={hasConsentedToLimitedRefund}
            on:consentChanged={handleConsentChanged}
        />
    {:else if paymentState === 'processing' || paymentState === 'success'}
        <ProcessingPayment
            state={paymentState}
            {isGift}
        />
    {:else}
        <PaymentForm
            bind:this={paymentFormComponent}
            purchasePrice={purchasePrice}
            currency={currency}
            bind:showSensitiveData={showSensitiveData}
            initialPaymentDetails={paymentState === 'failure' ? paymentDetails : null}
            on:toggleSensitiveData={handleToggleSensitiveData}
            on:startPayment={handleStartPayment}
            bind:cardFieldTarget
        />
    {/if}
</div>

<style>
    .payment-component {
        width: 100%;
        height: 100%;
        position: relative;
    }
    
    .compact {
        max-width: 500px;
        margin: 0 auto;
    }
</style>
