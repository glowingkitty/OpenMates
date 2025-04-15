<script lang="ts">
    import { text } from '@repo/ui'; // Assuming this is okay per user feedback
    import { createEventDispatcher, onMount } from 'svelte';
    import InputWarning from '../common/InputWarning.svelte';
    import { getWebsiteUrl, routes } from '../../config/links';
    import { fade } from 'svelte/transition';

    const dispatch = createEventDispatcher();

    // --- Props ---
    export let currency: string = 'EUR';
    // Removed credits_amount - parent handles it
    export let initialPaymentDetails = null; // Keep for pre-filling name
    export let isInitializing: boolean = true; // Passed down from Payment.svelte
    export let initializationError: string | null = null; // Passed down from Payment.svelte

    // --- Form State ---
    let nameOnCard = '';

    // --- Element References ---
    let nameInput: HTMLInputElement;
    let cardFieldContainer: HTMLDivElement; // Container for Revolut element (mounted by parent)

    // --- Validation State ---
    let nameError = '';
    let showNameWarning = false;
    let attemptedSubmit = false;

    // --- Initialization ---
    onMount(() => {
        // Pre-fill name if available from previous attempt or failure
        if (initialPaymentDetails) {
            nameOnCard = initialPaymentDetails.nameOnCard || '';
            // Note: Failure message display is now handled by the parent based on initializationError prop
        }
    });

    // --- Expose Container Element ---
    // Parent (Payment.svelte) will use bind:this and call this after mount
    export function getCardFieldContainerElement(): HTMLDivElement {
        return cardFieldContainer;
    }

    // --- Name Validation ---
    function validateName(name: string): boolean {
        if (name.trim().length < 3) {
            nameError = $text('signup.name_too_short.text');
            showNameWarning = name.trim().length > 0 || attemptedSubmit;
            return false;
        }
        nameError = '';
        showNameWarning = false;
        return true;
    }

    // --- Submit Handler ---
    function handleBuyClick() {
        console.debug("PaymentForm: Buy button clicked.");
        attemptedSubmit = true;

        // 1. Validate local fields (just Name)
        const isNameValid = validateName(nameOnCard);
        if (!isNameValid) {
            console.warn("PaymentForm: Name validation failed.");
            nameInput?.focus();
            return;
        }

        // 2. Dispatch submit event with name to parent
        console.debug("PaymentForm: Dispatching submit event with name:", nameOnCard);
        dispatch('submit', { nameOnCard });
    }

    // --- Error Handling ---
    // Simplified: Parent controls initialization errors. This component only resets its own validation.
    export function resetValidation() {
        console.debug("PaymentForm: Resetting validation.");
        nameError = '';
        showNameWarning = false;
        attemptedSubmit = false;
    }

    // Function to handle the secure payment info click
    function handleSecurePaymentInfoClick() {
        window.open(getWebsiteUrl(routes.docs.userGuide_signup_10_2), '_blank');
    }

    function handleRetryInit() {
        dispatch('retryInit');
    }

</script>

<div class="payment-form" class:loading={isInitializing} in:fade={{ duration: 300 }}>
    {#if isInitializing}
        <div class="loading-indicator">Loading Payment Form...</div>
    {:else if initializationError}
         <div class="error-message color-error">
             <span class="clickable-icon icon_warning"></span>
             {initializationError}
             <!-- Allow retry on init errors -->
             <button class="text-button" on:click={handleRetryInit}>Retry</button>
         </div>
    {/if}

    <div class="color-grey-60 payment-title">
        {@html $text('signup.pay_with_card.text')}
    </div>

    <form on:submit|preventDefault={handleBuyClick}>
        <!-- Name Input -->
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
                    disabled={isInitializing || !!initializationError}
                />
                {#if showNameWarning && nameError}
                    <InputWarning
                        message={nameError}
                        target={nameInput}
                    />
                {/if}
            </div>
        </div>

        <!-- Revolut Card Field Container (Managed by Parent) -->
        <div class="input-group revolut-card-field-wrapper">
             <div bind:this={cardFieldContainer} id="revolut-card-field">
                 <!-- Revolut Card Field will be mounted here by Payment.svelte -->
                 {#if isInitializing}<!-- Show text while parent is loading element -->
                    <span class="color-grey-60">Loading card details...</span>
                 {/if}
             </div>
        </div>

        <button
            type="submit"
            class="buy-button"
            disabled={isInitializing || !!initializationError || !nameOnCard || !!nameError}
        >
            {$text('signup.buy_for.text').replace(
                '{currency}', currency
            ).replace(
                '{amount}', '' // Placeholder or update text as needed
            ).replace(' for {amount}','')}
        </button>

        <!-- OR Divider and Apple/Google Pay -->
        <div class="or-divider">
            <span class="color-grey-60">{@html $text('signup.or.text')}</span>
        </div>

        <button type="button" class="apple-pay-button" disabled> <!-- Disable for now -->
            <span class="apple-pay-text">Pay with Apple Pay</span>
        </button>
         <!-- TODO: Implement Apple Pay / Google Pay using Revolut -->

        <p class="vat-info color-grey-60">
            {@html $text('signup.vat_info.text')}
        </p>
    </form>

    <!-- Bottom Container -->
    <div class="bottom-container">
         <button type="button" class="text-button" on:click={handleSecurePaymentInfoClick}>
             <span class="clickable-icon icon_lock inline-lock-icon"></span>
             {@html $text('signup.secured_and_powered_by.text').replace('{provider}', 'Revolut')}
         </button>
     </div>
</div>

<style>
    /* Styles for loading and error states */
    .loading-indicator {
        text-align: center;
        padding: 40px 20px;
        color: var(--color-grey-60);
    }
    .error-message {
        background-color: var(--color-error-bg);
        color: var(--color-error);
        padding: 10px 15px;
        border-radius: var(--radius-input);
        margin-bottom: 15px;
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 14px;
    }
    .error-message .clickable-icon {
        position: static;
        transform: none;
        background-color: var(--color-error);
        width: 18px;
        height: 18px;
        flex-shrink: 0;
    }
     .error-message button {
         margin-left: auto;
         color: var(--color-error);
         text-decoration: underline;
         font-size: 14px;
         flex-shrink: 0;
     }

    /* Style the container for the Revolut element */
    .revolut-card-field-wrapper {
        min-height: 48px; /* Ensure it has height while loading */
        border: 1px solid var(--color-input-border);
        border-radius: var(--radius-input);
        background-color: var(--color-input-bg);
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 0;
        transition: border-color 0.2s ease;
    }
     #revolut-card-field {
         width: 100%;
     }
     #revolut-card-field span { /* Style internal loading text */
        font-size: 14px;
     }

     /* Ensure loading state doesn't allow interaction */
     .payment-form.loading form {
         opacity: 0.6;
         pointer-events: none;
     }

    /* --- Keep existing styles --- */
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
        position: relative;
    }
    .input-wrapper {
        height: 48px;
        position: relative;
        display: flex;
        align-items: center;
    }
     .input-wrapper .clickable-icon {
        position: absolute;
        left: 12px;
        top: 50%;
        transform: translateY(-50%);
        width: 20px;
        height: 20px;
        background-color: var(--color-grey-60);
        pointer-events: none;
    }
     .input-wrapper input {
        padding-left: 40px;
        width: 100%;
        height: 100%;
        box-sizing: border-box;
    }
     .input-wrapper input.error {
         border-color: var(--color-error);
         color: var(--color-error);
     }

    .inline-lock-icon {
        position: unset;
        transform: none;
        display: inline-block;
        vertical-align: middle;
        margin-right: 5px;
        width: 16px;
        height: 16px;
    }
    .buy-button {
        width: 100%;
        margin-top: 10px;
    }
    .buy-button:disabled {
        opacity: 0.7;
        cursor: not-allowed;
    }
    .or-divider {
        display: flex;
        align-items: center;
        justify-content: center;
        margin: 16px 0;
        text-align: center;
    }
     .or-divider span {
         padding: 0 10px;
         font-size: 14px;
     }
     .or-divider::before,
     .or-divider::after {
         content: '';
         flex-grow: 1;
         height: 1px;
         background-color: var(--color-grey-20);
     }

    .apple-pay-button {
        width: 100%;
        height: 48px;
        background-color: black;
        color: white;
        border: none;
        border-radius: var(--radius-input);
        font-size: 16px;
        font-weight: 500;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 5px;
    }
     .apple-pay-button:disabled {
         opacity: 0.5;
         cursor: not-allowed;
     }

    .apple-pay-text {
        font-size: 16px;
    }
    .vat-info {
        font-size: 14px;
        text-align: center;
        margin: 16px 0 0;
    }
    .bottom-container {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        padding: 10px 0;
        display: flex;
        justify-content: center;
    }
     .bottom-container .text-button {
         color: var(--color-grey-60);
         font-size: 14px;
     }

</style>
