<script lang="ts">
    import { text } from '@repo/ui';
    import InputWarning from '../common/InputWarning.svelte';
    import { getWebsiteUrl, routes } from '../../config/links';
    import { fade } from 'svelte/transition';

    export let purchasePrice: number = 20;
    export let currency: string = 'EUR';
    export let cardFieldLoaded: boolean = false;
    export let cardFieldInstance: any;
    export let userEmail: string;

    // New props for consent and errors
    export let hasConsentedToLimitedRefund: boolean = false;
    export let validationErrors: string | null = null;
    export let paymentError: string | null = null;

    // Form state
    let nameOnCard = '';
    // Input element references
    let nameInput: HTMLInputElement;

    // CardField target for Revolut iframe
    export let cardFieldTarget: HTMLElement;

    // Validation states
    let nameError = '';

    let showNameWarning = false;

    // Track if form was submitted
    let attemptedSubmit = false;

    // Add a function to handle the secure payment info click
    function handleSecurePaymentInfoClick() {
        window.open(getWebsiteUrl(routes.docs.userGuide_signup_10_2), '_blank');
    }

    // Validate name on card - simple length check for international compatibility
    function validateName(name: string): boolean {
        if (name.trim().length <= 4) {
            nameError = $text('signup.name_too_short.text');
            // Only show warning if field is not empty or if user attempted to submit
            showNameWarning = name.trim().length > 0 || attemptedSubmit;
            return false;
        }

        nameError = '';
        showNameWarning = false;
        return true;
    }

    // Handle form submission
    function handleSubmit(event: Event) {
        attemptedSubmit = true;
        if (!validateName(nameOnCard)) {
            return;
        }
        // Submit payment using the already-initialized CardField instance
        if (cardFieldInstance && userEmail) {
            cardFieldInstance.submit({
                name: nameOnCard,
                email: userEmail
            });
        } else {
            // Optionally show an error if cardFieldInstance or userEmail is missing
            nameError = 'Payment field is not ready. Please try again.';
        }
    }
    // Derived state for button enable/disable
    $: nameIsValid = nameOnCard.trim().length > 4 && !nameError;
    $: canSubmit = hasConsentedToLimitedRefund && nameIsValid && !validationErrors && !paymentError;
    // For debugging, you can use canSubmitReason to see why the button is disabled
    $: canSubmitReason = !hasConsentedToLimitedRefund
        ? 'Consent not given'
        : !nameIsValid
            ? 'Name invalid'
            : validationErrors
                ? 'Card validation error'
                : paymentError
                    ? 'Payment error'
                    : '';
    // Allow parent to set payment failed state
    export function setPaymentFailed(message?: string) {
        paymentError = message || 'Payment failed. Please try again.';
    }
</script>

<div class="payment-form" in:fade={{ duration: 300 }} style="opacity: {cardFieldLoaded ? 1 : 0}; transition: opacity 0.3s;">
    <div class="color-grey-60 payment-title">
        {@html $text('signup.pay_with_card.text')}
    </div>
    
    <form on:submit|preventDefault={handleSubmit}>
        <div class="input-group">
            <div class="input-wrapper">
                <span class="clickable-icon icon_user"></span>
                <input
                    bind:this={nameInput}
                    type="text"
                    bind:value={nameOnCard}
                    placeholder={$text('signup.full_name_on_card.text')}
                    on:blur={() => validateName(nameOnCard)}
                    class:error={!!nameError}
                    required
                    autocomplete="name"
                />
                {#if showNameWarning && nameError}
                    <InputWarning
                        message={nameError}
                        target={nameInput}
                    />
                {/if}
            </div>
        </div>
        
        <div class="input-group">
            <div class="input-wrapper">
                <!-- <span class="clickable-icon icon_billing"></span> -->
                <div bind:this={cardFieldTarget}></div>
                {#if (validationErrors || paymentError)}
                    <InputWarning
                        message={validationErrors ? validationErrors : paymentError}
                        target={cardFieldTarget}
                    />
                {/if}
            </div>
        </div>
        
        <!-- Removed custom expiry and CVV fields: CardField handles all card data entry -->
        
        {#if !canSubmitReason}
            <!-- Hidden, but for debugging: {canSubmitReason} -->
        {/if}
        <button
            type="submit"
            class="buy-button"
            disabled={!canSubmit}
        >
            {$text('signup.buy_for.text').replace(
                '{currency}', currency
            ).replace(
                '{amount}', purchasePrice.toString()
            )}
        </button>
        
        <div class="or-divider">
            <span class="color-grey-60">{@html $text('signup.or.text')}</span>
        </div>
        
        <button type="button" class="apple-pay-button">
            <span class="apple-pay-text">Pay with Apple Pay</span>
        </button>
        
        <p class="vat-info color-grey-60">
            {@html $text('signup.vat_info.text')}
        </p>
    </form>
    
    <div class="bottom-container">
        <button type="button" class="text-button" on:click={handleSecurePaymentInfoClick}>
            <span class="clickable-icon icon_lock inline-lock-icon"></span>
            {@html $text('signup.secured_and_powered_by.text').replace('{provider}', 'Revolut')}
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
    
    .input-wrapper {
        height: 48px;
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
    
    .apple-pay-button {
        width: 100%;
        height: 50px;
        background-color: black;
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 16px;
        font-weight: 500;
        margin-top: 12px;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 5px;
    }
    
    .apple-pay-text {
        font-size: 16px;
    }
    
    .vat-info {
        font-size: 14px;
        text-align: center;
        margin: 16px 0;
    }
</style>
