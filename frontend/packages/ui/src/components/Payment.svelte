<script lang="ts">
    
    import { createEventDispatcher} from 'svelte';

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
    function handleStartPaymentProcessing() {
        console.debug("Payment.svelte: handleStartPaymentProcessing triggered");
        paymentState = 'processing';
        dispatch('paymentProcessing', { processing: true });
        dispatch('paymentStateChange', { state: 'processing' });
        // No simulation needed, Revolut handles the actual processing
    }

    // Called by PaymentForm's onSuccess callback from Revolut
    function handlePaymentSuccess(event) {
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
