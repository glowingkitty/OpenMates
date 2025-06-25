<script lang="ts">
    import { text } from '@repo/ui';
    import InputWarning from '../common/InputWarning.svelte';
    import { getWebsiteUrl, routes } from '../../config/links';
    import { fade } from 'svelte/transition';
    import { createEventDispatcher, onMount } from 'svelte';

    export let purchasePrice: number = 20;
    export let currency: string = 'EUR';
    export let userEmail: string | null; // Can be null initially

    // New props for consent and errors
    export let hasConsentedToLimitedRefund: boolean = false;
    export let validationErrors: string | null = null;
    export let paymentError: string | null = null;

    // New prop for Payment Element validity
    export let isPaymentElementComplete: boolean = false;

    // Loading state from parent
    export let isLoading: boolean = false;
    export let isButtonCooldown: boolean = false;

    // Stripe related props
    export let stripe: any;
    export let elements: any;
    export let clientSecret: string | null;
    export let darkmode: boolean;

    // Track if form was submitted
    let attemptedSubmit = false;

    // Event dispatcher for parent communication
    const dispatch = createEventDispatcher();

    // Add a function to handle the secure payment info click
    function handleSecurePaymentInfoClick() {
        window.open(getWebsiteUrl(routes.docs.userGuide_signup_10_2), '_blank');
    }

    // Handle form submission
    function handleSubmit(event: Event) {
        attemptedSubmit = true;
        // Notify parent to set loading state immediately
        dispatch('submitPayment');
        // The parent component will handle the submission
    }

    // Derived state for button enable/disable
    $: canSubmit = hasConsentedToLimitedRefund && isPaymentElementComplete && !validationErrors && !paymentError;
    
    // Allow parent to set payment failed state
    export function setPaymentFailed(message?: string) {
        paymentError = message || 'Payment failed. Please try again.';
    }
</script>

<div class="payment-form" in:fade={{ duration: 300 }}>
    <form on:submit|preventDefault={handleSubmit}>
        <button
            type="submit"
            class="buy-button"
            disabled={!canSubmit || isLoading || isButtonCooldown}
        >
            {#if isLoading}
                {$text('login.loading.text')}
            {:else}
                {$text('signup.buy_for.text').replace(
                    '{currency}', currency
                ).replace(
                    '{amount}', purchasePrice.toString()
                )}
            {/if}
        </button>
        
        <p class="vat-info color-grey-60">
            {@html $text('signup.vat_info.text')}
        </p>
    </form>
    
    <div class="bottom-container">
        <button type="button" class="text-button" on:click={handleSecurePaymentInfoClick}>
            <span class="clickable-icon icon_lock inline-lock-icon"></span>
            {@html $text('signup.secured_and_powered_by.text').replace('{provider}', 'Stripe')}
        </button>
    </div>
</div>

<style>
    .payment-form {
        width: 100%;
        position: relative;
        display: flex;
        flex-direction: column;
        padding-bottom: 60px; /* Make room for bottom container */
    }

    .payment-title {
        text-align: center;
        margin-bottom: 10px;
    }
    
    .input-group {
        margin-bottom: 12px;
    }

    .input-icon-wrapper {
        display: flex;
        align-items: center;
        height: 48px; /* Standard height for inputs */
        border: 1px solid var(--color-grey-40);
        border-radius: 12px; /* Match Payment.svelte borderRadius */
        padding: 0 16px; /* Adjust padding to match new input padding */
        background-color: var(--color-grey-10); /* Lighter background for inputs */
        box-shadow: 0px 2px 4px rgba(0, 0, 0, 0.05); /* Subtle shadow */
    }

    .input-icon {
        margin-right: 10px;
        color: var(--color-icon); /* Use the custom icon color from appearance */
        font-size: 20px; /* Adjust icon size if needed */
    }

    .stripe-element-container {
        flex: 1;
        height: 100%;
        display: flex;
        align-items: center;
    }

    .input-group-row {
        display: flex;
        gap: 12px;
        margin-bottom: 12px;
    }

    .input-group-row .input-group {
        flex: 1;
        margin-bottom: 0; /* Remove bottom margin for items in a row */
    }
    
    .inline-lock-icon {
        position: unset;
        transform: none;
        display: inline-block;
        vertical-align: middle;
        margin-right: 5px;
    }
    
    .buy-button {
        width: 100%;
        margin-top: 20px;
    }
    
    .buy-button:disabled {
        opacity: 0.7;
        cursor: not-allowed;
    }
    
    .or-divider {
        display: flex;
        align-items: center;
        justify-content: center;
        margin: 12px 0;
        text-align: center;
    }

    .payment-request-button-container {
        width: 100%;
        margin-top: 12px; /* Same margin as the old button */
        min-height: 50px; /* Ensure space is reserved */
        display: flex; /* Center button if needed */
        justify-content: center; /* Center button if needed */
    }

    /* Revolut might inject specific classes, inspect element if styling needed */
    .payment-request-button-container > div {
         width: 100%; /* Make injected button take full width */
    }


    .vat-info {
        font-size: 14px;
        text-align: center;
        margin: 16px 0;
    }

    /* Stripe element specific overrides */
    /* These styles target the iframes created by Stripe */
    .stripe-element-container > div {
        width: 100%;
        height: 100%;
    }

    /* Override Stripe's default input styles to match our custom appearance */
    .stripe-input {
        /* These are set in Payment.svelte appearance rules, but can be overridden here if needed */
    }

    .stripe-input--focus {
        /* These are set in Payment.svelte appearance rules, but can be overridden here if needed */
    }

    .stripe-input--invalid {
        /* These are set in Payment.svelte appearance rules, but can be overridden here if needed */
    }
</style>
