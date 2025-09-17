<script lang="ts">
    import { text } from '@repo/ui';
    import InputWarning from '../common/InputWarning.svelte';
    import { getWebsiteUrl, routes } from '../../config/links';
    import { fade } from 'svelte/transition';
    import { createEventDispatcher, onMount } from 'svelte';

    // Props using Svelte 5 runes
    let { 
        purchasePrice = 20,
        currency = 'EUR',
        userEmail = null,
        hasConsentedToLimitedRefund = false,
        validationErrors = null,
        paymentError = null,
        isPaymentElementComplete = false,
        isLoading = false,
        isButtonCooldown = false,
        stripe = null,
        elements = null,
        clientSecret = null,
        darkmode = false
    }: {
        purchasePrice?: number;
        currency?: string;
        userEmail?: string | null;
        hasConsentedToLimitedRefund?: boolean;
        validationErrors?: string | null;
        paymentError?: string | null;
        isPaymentElementComplete?: boolean;
        isLoading?: boolean;
        isButtonCooldown?: boolean;
        stripe?: any;
        elements?: any;
        clientSecret?: string | null;
        darkmode?: boolean;
    } = $props();

    // Track if form was submitted
    let attemptedSubmit = false;

    // Event dispatcher for parent communication
    const dispatch = createEventDispatcher();

    // Add a function to handle the secure payment info click
    function handleSecurePaymentInfoClick() {
        // TODO add link to documentation page once available
        // For now, we can just open the Stripe privacy page
        window.open('https://stripe.com/privacy', '_blank');
        // window.open(getWebsiteUrl(routes.docs.userGuide_signup_10_2), '_blank');
    }

    // Handle form submission
    function handleSubmit(event: Event) {
        event.preventDefault(); // Prevent default form submission
        attemptedSubmit = true;
        // Notify parent to set loading state immediately
        dispatch('submitPayment');
        // The parent component will handle the submission
    }

    // Derived state for button enable/disable using Svelte 5 runes
    let canSubmit = $derived(hasConsentedToLimitedRefund && isPaymentElementComplete && !validationErrors && !paymentError);
    
    // Allow parent to set payment failed state
    export function setPaymentFailed(message?: string) {
        paymentError = message || 'Payment failed. Please try again.';
    }
</script>

<div class="payment-form" in:fade={{ duration: 300 }}>
    <form onsubmit={handleSubmit}>
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
        <button type="button" class="text-button" onclick={handleSecurePaymentInfoClick}>
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
    


    .vat-info {
        font-size: 14px;
        text-align: center;
        margin-top: 10px;
        margin-bottom: 10px;
    }

</style>
