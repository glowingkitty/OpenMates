<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy } from 'svelte'; // Added onMount, onDestroy
    import { getApiUrl, apiEndpoints } from '../config/api'; // Import API config

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
    export let initialState: 'idle' | 'processing' | 'success' | 'failure' = 'idle'; // New prop
    export let isGift: boolean = false; // New prop

    // Toggle state for consent
    let hasConsentedToLimitedRefund = false;
    
    // Payment processing states - Initialize with prop
    let paymentState: 'idle' | 'processing' | 'success' | 'failure' = initialState;
    let currentOrderId: string | null = null; // Store the order ID for polling
    let pollingIntervalId: ReturnType<typeof setInterval> | null = null;
    let pollingTimeoutId: ReturnType<typeof setTimeout> | null = null;

    const POLLING_INTERVAL_MS = 3000; // Check every 3 seconds
    const POLLING_TIMEOUT_MS = 60000; // Give up after 60 seconds
    
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
    
    // Handle consent change
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
    
    // Removed handleToggleSensitiveData function
    
    // --- New Event Handlers for Refactored PaymentForm ---

    // Called when PaymentForm starts the Revolut submit process
    function handleStartPaymentProcessing(event) {
        const orderId = event.detail?.orderId;
        console.debug(`Payment.svelte: handleStartPaymentProcessing triggered. Order ID: ${orderId}`);
        if (!orderId) {
             console.error("Payment.svelte: startPaymentProcessing event missing orderId!");
             // Handle error appropriately - maybe revert state? For now, just log.
             handlePaymentFailure({ detail: { message: "Internal error: Missing order ID for status check." } });
             return;
        }
        currentOrderId = orderId;
        paymentState = 'processing';
        dispatch('paymentProcessing', { processing: true });
        dispatch('paymentStateChange', { state: 'processing' });
        // Start polling for order status
        startPolling(currentOrderId);
    }

    // --- Polling Logic ---

    function stopPolling() {
        if (pollingIntervalId) {
            clearInterval(pollingIntervalId);
            pollingIntervalId = null;
            console.debug("Payment.svelte: Polling stopped.");
        }
        if (pollingTimeoutId) {
            clearTimeout(pollingTimeoutId);
            pollingTimeoutId = null;
        }
        // currentOrderId = null; // DO NOT clear order ID here, clear it only when process ends
    }

    async function checkOrderStatus(orderId: string) {
        console.debug(`Payment.svelte: Checking status for order ${orderId}...`);
        if (!orderId) {
            console.error("Payment.svelte: checkOrderStatus called without orderId.");
            stopPolling();
            handlePaymentFailure({ detail: { message: "Internal error checking payment status." } });
            return;
        }
        try {
            const statusUrl = getApiUrl() + apiEndpoints.payments.orderStatus; // Use the correct endpoint path
            const response = await fetch(statusUrl, {
                method: 'POST', // Change to POST
                headers: {
                    'Accept': 'application/json',
                    'Content-Type': 'application/json' // Add Content-Type header
                 },
                credentials: 'include',
                body: JSON.stringify({ order_id: orderId }) // Send orderId in the body
            });

            if (!response.ok) {
                // Handle non-2xx responses (e.g., 404 Not Found, 500 Server Error)
                const errorText = await response.text();
                console.error(`Payment.svelte: Error fetching order status ${response.status}: ${errorText}`);
                 // Stop polling on server error or if order not found
                if (response.status === 404 || response.status >= 500) {
                    stopPolling();
                    handlePaymentFailure({ detail: { message: `Failed to get payment status (${response.status}).` } });
                }
                // For other client errors (4xx), maybe continue polling briefly? Or fail? Let's fail for now.
                else if (response.status >= 400) {
                     stopPolling();
                     handlePaymentFailure({ detail: { message: `Error checking payment status (${response.status}).` } });
                }
                return; // Don't process further on error
            }

            const data = await response.json();
            const state = data.state?.toUpperCase(); // Normalize state
            console.debug(`Payment.svelte: Order ${orderId} status is ${state}`);

            switch (state) {
                case 'COMPLETED':
                    stopPolling();
                    // Use existing success handler, pass minimal detail for now
                    handlePaymentSuccess({ detail: { /* Can add details from 'data' if needed */ } });
                    break;
                case 'FAILED':
                case 'CANCELLED': // Treat cancelled like failed from polling perspective
                    stopPolling();
                    // Use existing failure handler
                    handlePaymentFailure({ detail: { message: `Payment ${state.toLowerCase()}.` } });
                    break;
                case 'CREATED':
                case 'PENDING':
                case 'AUTHORISED':
                    // Still processing, do nothing, wait for next poll interval
                    break;
                default:
                    console.warn(`Payment.svelte: Unknown order state received: ${state}`);
                    // Optionally stop polling and fail on unknown state
                    // stopPolling();
                    // handlePaymentFailure({ detail: { message: `Unknown payment status: ${state}` } });
                    break;
            }

        } catch (error) {
            console.error("Payment.svelte: Exception during checkOrderStatus fetch:", error);
            stopPolling();
            handlePaymentFailure({ detail: { message: "Error checking payment status." } });
        }
    }

    function handlePollingTimeout() {
         console.warn(`Payment.svelte: Polling timed out after ${POLLING_TIMEOUT_MS / 1000} seconds for order ${currentOrderId}.`);
         pollingTimeoutId = null; // Already cleared by stopPolling, but good practice
         stopPolling();
         handlePaymentFailure({ detail: { message: "Payment status check timed out. Please check your Revolut account or contact support." } });
    }

    function startPolling(orderId: string) {
        stopPolling(); // Clear any previous polling just in case
        console.debug(`Payment.svelte: Starting polling for order ${orderId}...`);

        // Initial check immediately
        checkOrderStatus(orderId);

        pollingIntervalId = setInterval(() => {
             if (currentOrderId) { // Check if polling hasn't been stopped
                 checkOrderStatus(currentOrderId);
             } else {
                 // Should not happen if stopPolling clears currentOrderId, but safety check
                 console.warn("Payment.svelte: Polling interval fired but currentOrderId is null. Stopping.");
                 stopPolling();
             }
        }, POLLING_INTERVAL_MS);

        pollingTimeoutId = setTimeout(handlePollingTimeout, POLLING_TIMEOUT_MS);
    }

    // --- End Polling Logic ---

    // Called by PaymentForm's onSuccess callback from Revolut
    function handlePaymentSuccess(event) {
        stopPolling(); // Ensure polling stops on success
        console.debug("Payment.svelte: handlePaymentSuccess triggered", event.detail);
        paymentState = 'success';
        dispatch('paymentProcessing', { processing: false });
        dispatch('paymentStateChange', { state: 'success' });
        // Forward the success event with details provided by PaymentForm
        // Wait a bit before dispatching to allow success animation to show
        setTimeout(() => {
            dispatch('paymentSuccess', event.detail);
        }, 1500); // Delay before notifying parent
    }

    // Called by PaymentForm's onError callback from Revolut or internal errors
    function handlePaymentFailure(event) {
        stopPolling(); // Ensure polling stops on failure
        console.warn("Payment.svelte: handlePaymentFailure triggered", event.detail);
        paymentState = 'failure'; // Keep failure state briefly for UI feedback
        dispatch('paymentProcessing', { processing: false });
        dispatch('paymentStateChange', { state: 'failure' });
        // Reset to idle state (showing form) after a delay
        setTimeout(() => {
            paymentState = 'idle';
            dispatch('paymentStateChange', { state: 'idle' });
            // Optionally pass the error message back to the form if needed
            if (paymentFormComponent) {
                 paymentFormComponent.setPaymentFailed(event.detail?.message || "Payment failed.");
            }
        }, 2000); // Show failure message for 2 seconds
    }

     // Called by PaymentForm's onCancel callback from Revolut
    function handlePaymentCancel() {
        stopPolling(); // Ensure polling stops on cancel
        console.info("Payment.svelte: handlePaymentCancel triggered");
        // Reset state back to idle (showing the form) immediately
        paymentState = 'idle';
        dispatch('paymentProcessing', { processing: false });
        dispatch('paymentStateChange', { state: 'idle' });
        // Optionally dispatch a cancel event to the parent if needed
        dispatch('paymentCancel');
    }

    // --- End New Event Handlers ---
    
    // Notify parent when payment form visibility changes
    $: if (showPaymentForm !== previousPaymentFormState) {
        if (previousPaymentFormState !== undefined) {
            dispatch('paymentFormVisibility', { visible: showPaymentForm });
        }
        previousPaymentFormState = showPaymentForm;
    }
    let previousPaymentFormState;
    
    // Watch payment state and return to form on failure
    // Removed explicit failure state watcher, handled in handlePaymentFailure now

    // Cleanup on component destroy
    onDestroy(() => {
        stopPolling();
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
            credits_amount={credits_amount}
            initialPaymentDetails={paymentState === 'failure' ? paymentDetails : null}
            on:startPaymentProcessing={handleStartPaymentProcessing}
            on:paymentSuccess={handlePaymentSuccess}
            on:paymentFailure={handlePaymentFailure}
            on:paymentCancel={handlePaymentCancel}
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
