<script lang="ts">
    import { text } from '@repo/ui';
    import { onMount, createEventDispatcher, tick } from 'svelte';
    import { fade } from 'svelte/transition';
    import { getWebsiteUrl, routes } from '../config/links';
    
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

    // Toggle state for consent
    let hasConsentedToLimitedRefund = false;
    
    // Add state to track if sensitive data should be visible
    let showSensitiveData = false;
    
    // Payment processing states
    let paymentState: 'idle' | 'processing' | 'success' | 'failure' = 'idle';
    
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
    
    // Handle visibility toggle
    function handleToggleSensitiveData(event) {
        showSensitiveData = event.detail.showSensitiveData;
    }
    
    // Start payment processing
    function handleStartPayment(event) {
        // Store payment details for potential failure recovery
        paymentDetails = { ...event.detail };
        
        paymentState = 'processing';
        dispatch('paymentProcessing', { processing: true });
        dispatch('paymentStateChange', { state: 'processing' });
        
        // Simulate payment processing with 3 second delay
        setTimeout(() => {
            // Check if payment should fail (demo)
            if (event.detail.nameOnCard.trim() === 'Max Mustermann') {
                paymentState = 'failure';
                dispatch('paymentStateChange', { state: 'failure' });
                
                // Reset to payment form with error
                setTimeout(() => {
                    if (paymentFormComponent) {
                        paymentFormComponent.setPaymentFailed();
                    }
                }, 100);
            } else {
                paymentState = 'success';
                dispatch('paymentStateChange', { state: 'success' });
                
                // After payment succeeds, notify parent components
                setTimeout(() => {
                    dispatch('paymentSuccess', {
                        nameOnCard: event.detail.nameOnCard,
                        lastFourDigits: event.detail.lastFourDigits,
                        amount: credits_amount,
                        price: purchasePrice,
                        currency
                    });
                }, 2000);
            }
            
            dispatch('paymentProcessing', { processing: false });
        }, 3000); // Changed to 3 seconds as specified
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
        // When payment fails, reset back to payment form after a short delay
        setTimeout(() => {
            paymentState = 'idle';
        }, 1000);
    }
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
