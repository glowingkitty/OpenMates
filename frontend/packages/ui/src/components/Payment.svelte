<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy, tick } from 'svelte';
    import { getApiUrl, apiEndpoints } from '../config/api';
    import RevolutCheckout from '@revolut/checkout';
    import type { RevolutCheckoutInstance, Mode } from '@revolut/checkout';
    import { text } from '@repo/ui'; // Assuming okay

    // Import component modules
    import LimitedRefundConsent from './payment/LimitedRefundConsent.svelte';
    import PaymentForm from './payment/PaymentForm.svelte';
    import ProcessingPayment from './payment/ProcessingPayment.svelte';

    const dispatch = createEventDispatcher();

    // --- Props ---
    export let currency: string = 'EUR';
    export let credits_amount: number = 21000;
    export let requireConsent: boolean = true;
    export let compact: boolean = false;
    export let initialState: 'idle' | 'processing' | 'success' | 'failure' = 'idle';
    export let isGift: boolean = false;
    // Removed purchasePrice prop as it's backend-driven

    // --- Component State ---
    let hasConsentedToLimitedRefund = false;
    let paymentState: 'idle' | 'initializing' | 'ready' | 'processing' | 'success' | 'failure' = 'idle'; // Added initializing/ready states
    let showPaymentForm = !requireConsent;

    // --- Revolut State (Moved from PaymentForm) ---
    let revolutCheckout: RevolutCheckoutInstance | null = null;
    let cardFieldInstance: any | null = null; // Use 'any' or let TS infer type
    let orderToken: string | null = null;
    let currentOrderId: string | null = null; // Renamed from orderId for clarity with polling
    let isLoadingRevolut = true; // Renamed to isInitializing internally
    let revolutError: string | null = null; // Renamed to initializationError internally
    let revolutPublicKey: string | null = null;
    let revolutEnvironment: 'sandbox' | 'production' | null = null;

    // --- Polling State (REMOVED) ---

    // --- References ---
    let paymentFormComponent: PaymentForm; // Still need reference to get container

    // --- Store payment details for re-use after failure ---
    // Only name is needed now as Revolut handles card details
    let paymentDetails = {
        nameOnCard: '',
        failed: false // Flag to indicate previous failure
    };

    // --- Lifecycle ---
    onMount(() => {
        // If consent is not required, or already given, initialize immediately
        if (!requireConsent || hasConsentedToLimitedRefund) {
            initializePaymentFlow();
        }
        // If starting in a specific state (e.g., deep link to processing/success)
        if (initialState !== 'idle') {
             paymentState = initialState;
             // If starting in processing, we might need an orderId passed in or fetched
             // For now, assume if initialState is processing/success, it's handled externally
        } else {
             paymentState = 'idle'; // Ensure correct initial state
        }
    });

    onDestroy(() => {
        // stopPolling(); // Removed, no longer needed
        // Destroy Revolut instance directly
        if (cardFieldInstance) {
            cardFieldInstance.destroy();
            cardFieldInstance = null;
            console.debug("Payment.svelte onDestroy: Revolut card field instance destroyed.");
        }
    });

    // --- Initialization Logic ---
    async function initializePaymentFlow() {
        if (paymentState === 'initializing' || paymentState === 'ready') return; // Prevent re-initialization

        console.debug("Payment.svelte: Initializing payment flow...");
        paymentState = 'initializing';
        isLoadingRevolut = true;
        revolutError = null;
        orderToken = null;
        currentOrderId = null;

        // Destroy previous instance if exists (e.g., on retry)
        if (cardFieldInstance) {
            cardFieldInstance.destroy();
            cardFieldInstance = null;
            console.debug("Payment.svelte: Destroyed previous Revolut card field instance.");
        }

        // Ensure PaymentForm component is rendered and its container is available
        await tick();
        const cardFieldContainer = paymentFormComponent?.getCardFieldContainerElement();

        if (!cardFieldContainer) {
            console.error("Payment.svelte: Could not get cardFieldContainer from PaymentForm.");
            revolutError = "Internal error: Payment form container not found.";
            paymentState = 'failure'; // Or maybe a specific 'init_failed' state
            isLoadingRevolut = false;
            dispatch('paymentFailure', { message: revolutError });
            return;
        }

        if (credits_amount === undefined || credits_amount === null || credits_amount <= 0) {
             revolutError = "Invalid credits amount specified.";
             isLoadingRevolut = false;
             paymentState = 'failure';
             console.error(`Payment.svelte Init Error: Invalid credits_amount: ${credits_amount}`);
             dispatch('paymentFailure', { message: revolutError });
             return;
        }

        try {
            // 1. Fetch Payment Config
            console.debug("Payment.svelte: Fetching payment config...");
            const configResponse = await fetch(getApiUrl() + apiEndpoints.payments.config, { /* ... headers ... */ credentials: 'include' });
            if (!configResponse.ok) throw new Error(`Failed to fetch payment config: ${configResponse.statusText}`);
            const configData = await configResponse.json();
            revolutPublicKey = configData.revolut_public_key;
            revolutEnvironment = configData.environment;
            console.debug(`Payment.svelte: Payment config received: Environment=${revolutEnvironment}`);

            // 2. Create Order
            const orderPayload = { currency: currency, credits_amount: credits_amount };
            console.debug("Payment.svelte: Creating payment order with payload:", orderPayload);
            const orderResponse = await fetch(getApiUrl() + apiEndpoints.payments.createOrder, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                credentials: 'include',
                body: JSON.stringify(orderPayload)
            });
            if (!orderResponse.ok) {
                const errorData = await orderResponse.json().catch(() => ({ detail: orderResponse.statusText }));
                throw new Error(`Failed to create payment order: ${errorData.detail || orderResponse.statusText}`);
            }
            const orderData = await orderResponse.json();
            orderToken = orderData.order_token;
            currentOrderId = orderData.order_id; // Store the order ID
            console.debug(`Payment.svelte: Order token/ID received: ${orderToken ? 'OK' : 'MISSING'}, ${currentOrderId ? 'OK' : 'MISSING'}`);
            if (!orderToken || !currentOrderId) throw new Error("Incomplete order details from backend.");

            // 3. Initialize Revolut Checkout
            console.debug(`Payment.svelte: Initializing RevolutCheckout with token for ${revolutEnvironment} env.`);
            revolutCheckout = await RevolutCheckout(orderToken, revolutEnvironment as Mode);
            if (!revolutCheckout) throw new Error("Failed to initialize Revolut Checkout.");

            // 4. Create and Mount Card Field
            console.debug("Payment.svelte: Creating Revolut card field instance...");
            cardFieldInstance = revolutCheckout.createCardField({
                target: cardFieldContainer, // Mount to the div inside PaymentForm
                styles: { /* ... styles ... */
                    default: { color: 'var(--color-text)', backgroundColor: 'var(--color-input-bg)', padding: '14px 12px', borderRadius: 'var(--radius-input)', border: '1px solid var(--color-input-border)', fontFamily: 'inherit', fontSize: '16px' },
                    focused: { borderColor: 'var(--color-primary)', boxShadow: '0 0 0 1px var(--color-primary)' },
                    invalid: { borderColor: 'var(--color-error)', color: 'var(--color-error)' },
                },
                locale: 'en',
                // --- Event Handlers (Now directly within Payment.svelte) ---
                onSuccess() {
                    console.info("Payment.svelte: Revolut onSuccess callback triggered.");
                    paymentState = 'success';
                    dispatch('paymentProcessing', { processing: false });
                    dispatch('paymentStateChange', { state: 'success' });
                    setTimeout(() => dispatch('paymentSuccess', { amount: credits_amount, currency: currency }), 1500);
                },
                onError(error) {
                    console.error("Payment.svelte: Revolut onError callback triggered:", error);
                    handlePaymentError("Payment failed. Please try again or use a different card.");
                },
                onCancel() {
                    console.info("Payment.svelte: Revolut onCancel callback triggered.");
                    handlePaymentError("Payment was cancelled.");
                },
                onValidation(errors) {
                    console.debug("Payment.svelte: Revolut validation event:", errors);
                    // Can potentially forward validation state to PaymentForm if needed
                },
            });

            console.debug("Payment.svelte: Revolut card field instance created and mounted.");
            paymentState = 'ready'; // Mark as ready for submission
            isLoadingRevolut = false;

        } catch (error) {
            console.error("Payment.svelte: Error initializing Revolut:", error);
            revolutError = error instanceof Error ? error.message : String(error) || "Failed to initialize payment form.";
            paymentState = 'failure'; // Or specific init_failed state
            isLoadingRevolut = false;
            dispatch('paymentFailure', { message: revolutError });
        }
    }

    // --- Event Handlers ---

    // Handle consent change
    function handleConsentChanged(event) {
        hasConsentedToLimitedRefund = event.detail.consented;
        if (hasConsentedToLimitedRefund) {
            dispatch('consentGiven', { consented: true });
            if (requireConsent && !showPaymentForm) {
                // Explicitly initialize after showing form
                setTimeout(() => {
                    showPaymentForm = true;
                    initializePaymentFlow(); // Call init explicitly here
                }, 300);
            } else if (hasConsentedToLimitedRefund && showPaymentForm && paymentState === 'idle') {
                 // If consent was already given but we are idle (e.g. after failure), re-init
                 initializePaymentFlow();
            }
        }
    }

    // Handle submit event from PaymentForm
    async function handleFormSubmit(event) {
        const nameOnCard = event.detail.nameOnCard;
        console.debug(`Payment.svelte: Received submit event with name: ${nameOnCard}`);
        paymentDetails.nameOnCard = nameOnCard; // Store name for potential retry

        if (!cardFieldInstance || paymentState !== 'ready') {
            console.error("Payment.svelte: Submit called but Revolut instance not ready or not in ready state.");
            // Optionally show an error message
            return;
        }

        paymentState = 'processing';
        dispatch('paymentProcessing', { processing: true });
        dispatch('paymentStateChange', { state: 'processing' });

        // Fetch email just-in-time
        let fetchedEmail: string | null = null;
        try {
            console.debug("Payment.svelte: Fetching user email for payment submission...");
            const emailResponse = await fetch(getApiUrl() + apiEndpoints.settings.user.getEmail, { /* ... headers ... */ credentials: 'include' });
            if (!emailResponse.ok) throw new Error(`Failed to fetch email: ${await emailResponse.text()}`);
            const emailData = await emailResponse.json();
            fetchedEmail = emailData.email;
            if (!fetchedEmail) throw new Error("Email not found in backend response.");
            console.debug("Payment.svelte: User email fetched successfully.");
        } catch (error) {
            console.error("Payment.svelte: Error fetching user email:", error);
            handlePaymentError("Could not retrieve user email for payment. Please try again.");
            return; // Stop submission
        }

        // Submit the Revolut Card Field
        try {
            console.debug(`Payment.svelte: Submitting card field with email and name: ${nameOnCard}`);
            await cardFieldInstance.submit({
                email: fetchedEmail,
                name: nameOnCard,
            });
            console.debug("Payment.svelte: cardField.submit() called successfully.");
            paymentState = 'processing';
            dispatch('paymentProcessing', { processing: true });
            dispatch('paymentStateChange', { state: 'processing' });
            // Success/Error is handled by the onSuccess/onError/onCancel callbacks
        } catch (error) {
            // Handle errors during the *initiation* of submit
            console.error("Payment.svelte: Error calling cardField.submit():", error);
            const message = error instanceof Error ? error.message : String(error) || "Unknown submission error";
            handlePaymentError(`Failed to initiate payment: ${message}`);
        }
    }

    // Generic internal error handler during submission phase
    function handlePaymentError(message: string) {
         // stopPolling(); // Removed, no longer needed
         revolutError = message;
         paymentState = 'failure';
         dispatch('paymentProcessing', { processing: false });
         dispatch('paymentStateChange', { state: 'failure' });
         setTimeout(() => {
             paymentDetails.failed = true;
             paymentState = 'idle';
             dispatch('paymentStateChange', { state: 'idle' });
             // Removed automatic re-initialization: if (showPaymentForm) { initializePaymentFlow(); }
         }, 2000); // Keep timeout to show error message before resetting state
    }

    // Handle retry button click from PaymentForm
    function handleRetryInit() {
        console.debug("Payment.svelte: Retry initialization requested.");
        // Reset state and re-initialize
        paymentState = 'idle';
        initializePaymentFlow();
    }


    // --- Polling Logic REMOVED ---

    // --- Reactive Statements ---

    // Removed reactive statement for initialization
    // $: if (showPaymentForm && paymentState === 'idle') {
    //     initializePaymentFlow();
    // }

    // Notify parent when payment form visibility changes (for layout adjustments etc.)
    $: if (showPaymentForm !== previousPaymentFormState) {
        if (previousPaymentFormState !== undefined) {
            dispatch('paymentFormVisibility', { visible: showPaymentForm });
        }
        previousPaymentFormState = showPaymentForm;
    }
    let previousPaymentFormState: boolean | undefined;

</script>

<div class="payment-component {compact ? 'compact' : ''}">
    {#if requireConsent && !showPaymentForm}
        <LimitedRefundConsent
            bind:hasConsentedToLimitedRefund={hasConsentedToLimitedRefund}
            on:consentChanged={handleConsentChanged}
        />
    {:else if paymentState === 'processing' || paymentState === 'success'}
        <ProcessingPayment
            state={paymentState === 'success' ? 'success' : 'processing'}
            {isGift}
        />
    {:else} <!-- idle, initializing, ready, failure -->
        <PaymentForm
            bind:this={paymentFormComponent}
            currency={currency}
            isInitializing={isLoadingRevolut || paymentState === 'initializing'}
            initializationError={revolutError}
            initialPaymentDetails={paymentDetails.failed ? paymentDetails : null}
            on:submit={handleFormSubmit}
            on:retryInit={handleRetryInit}
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
