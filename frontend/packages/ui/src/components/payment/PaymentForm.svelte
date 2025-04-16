<script lang="ts">
    import { text } from '@repo/ui';
    import { createEventDispatcher, tick, onMount } from 'svelte';
    import InputWarning from '../common/InputWarning.svelte';
    import { getWebsiteUrl, routes } from '../../config/links';
    import { fade } from 'svelte/transition';
    import { tooltip } from '../../actions/tooltip';
    
    const dispatch = createEventDispatcher();
    
    export let purchasePrice: number = 20;
    export let currency: string = 'EUR';
    export let showSensitiveData: boolean = false;
    export let initialPaymentDetails = null;
    export let cardFieldLoaded: boolean = false;
    
    // Form state
    let nameOnCard = '';
    let cardNumber = '';
    let expireDate = '';
    let cvv = '';
    
    // Track if card has been entered and user finished typing
    let isCardNumberComplete = false;
    
    // Input element references
    let nameInput: HTMLInputElement;
    let cardInputVisible: HTMLInputElement;
    let cardInputHidden: HTMLInputElement;
    let expireInput: HTMLInputElement;
    let cvvInputVisible: HTMLInputElement;
    let cvvInputHidden: HTMLInputElement;

    // CardField target for Revolut iframe
    export let cardFieldTarget: HTMLElement;
    
    // Validation states
    let nameError = '';
    let cardError = '';
    let expireError = '';
    let cvvError = '';
    
    let showNameWarning = false;
    let showCardWarning = false;
    let showExpireWarning = false;
    let showCVVWarning = false;
    
    // Payment failure state
    let paymentFailed = false;
    
    // Track if form was submitted
    let attemptedSubmit = false;
    
    // Initialize with saved payment details if provided
    onMount(() => {
        if (initialPaymentDetails) {
            nameOnCard = initialPaymentDetails.nameOnCard || '';
            cardNumber = initialPaymentDetails.cardNumber || '';
            expireDate = initialPaymentDetails.expireDate || '';
            cvv = initialPaymentDetails.cvv || '';
            
            // Mark card as complete if it has enough digits
            const digits = cardNumber.replace(/\D/g, '');
            isCardNumberComplete = digits.length >= 13;
            
            // If we have initial details and they're from a failed payment, show error
            if (initialPaymentDetails.failed) {
                setPaymentFailed();
            }
        }
    });
    
    // Watch for initialPaymentDetails changes to handle payment failure recovery
    $: if (initialPaymentDetails) {
        nameOnCard = initialPaymentDetails.nameOnCard || nameOnCard;
        cardNumber = initialPaymentDetails.cardNumber || cardNumber;
        expireDate = initialPaymentDetails.expireDate || expireDate;
        cvv = initialPaymentDetails.cvv || cvv;
        
        // Mark card as complete if it has enough digits
        const digits = cardNumber.replace(/\D/g, '');
        isCardNumberComplete = digits.length >= 13;
    }
    
    // Toggle visibility of sensitive data
    function toggleSensitiveDataVisibility() {
        showSensitiveData = !showSensitiveData;
        dispatch('toggleSensitiveData', { showSensitiveData });
        
        // Focus the appropriate input after toggling
        setTimeout(() => {
            const activeElement = document.activeElement;
            if (activeElement === cardInputVisible || activeElement === cardInputHidden) {
                const focusElement = showSensitiveData ? cardInputVisible : cardInputHidden;
                if (focusElement) focusElement.focus();
            }
            
            if (activeElement === cvvInputVisible || activeElement === cvvInputHidden) {
                const focusElement = showSensitiveData ? cvvInputVisible : cvvInputHidden;
                if (focusElement) focusElement.focus();
            }
        }, 0);
    }
    
    // Add a function to handle the secure payment info click
    function handleSecurePaymentInfoClick() {
        window.open(getWebsiteUrl(routes.docs.userGuide_signup_10_2), '_blank');
    }
    
    // Validate name on card - simple length check for international compatibility
    function validateName(name: string): boolean {
        if (name.trim().length < 3) {
            nameError = $text('signup.name_too_short.text');
            // Only show warning if field is not empty or if user attempted to submit
            showNameWarning = name.trim().length > 0 || attemptedSubmit;
            return false;
        }
        
        nameError = '';
        showNameWarning = false;
        return true;
    }
    
    // Luhn algorithm for credit card validation
    function validateCardNumber(cardNum: string): boolean {
        // If payment failed previously, show that error instead
        if (paymentFailed) {
            cardError = $text('signup.payment_failed.text');
            showCardWarning = true;
            return false;
        }
        
        // Remove all non-digits
        const digits = cardNum.replace(/\D/g, '');
        
        if (digits.length < 13 || digits.length > 19) {
            cardError = $text('signup.invalid_card_number.text');
            // Only show warning if field is not empty or if user attempted to submit
            showCardWarning = digits.length > 0 || attemptedSubmit;
            return false;
        }
        
        // Luhn algorithm implementation
        let sum = 0;
        let shouldDouble = false;
        
        for (let i = digits.length - 1; i >= 0; i--) {
            let digit = parseInt(digits.charAt(i));
            
            if (shouldDouble) {
                digit *= 2;
                if (digit > 9) digit -= 9;
            }
            
            sum += digit;
            shouldDouble = !shouldDouble;
        }
        
        if (sum % 10 !== 0) {
            cardError = $text('signup.invalid_card_number.text');
            showCardWarning = true;
            return false;
        }
        
        cardError = '';
        showCardWarning = false;
        return true;
    }
    
    // Format and validate expiration date
    function formatExpireDate(input: string): string {
        // Remove any non-digit characters
        const digits = input.replace(/\D/g, '');
        
        // Format as MM/YY
        if (digits.length <= 2) {
            return digits;
        } else {
            return `${digits.substring(0, 2)}/${digits.substring(2, 4)}`;
        }
    }
    
    function validateExpireDate(date: string): boolean {
        // Check format
        if (!/^\d{2}\/\d{2}$/.test(date)) {
            expireError = $text('signup.invalid_expiry_format.text');
            // Only show warning if field is not empty or if user attempted to submit
            showExpireWarning = date.length > 0 || attemptedSubmit;
            return false;
        }
        
        const [monthStr, yearStr] = date.split('/');
        const month = parseInt(monthStr, 10);
        const year = parseInt(yearStr, 10) + 2000; // Assuming 20xx
        
        // Check month validity
        if (month < 1 || month > 12) {
            expireError = $text('signup.invalid_month.text');
            showExpireWarning = true;
            return false;
        }
        
        // Check expiry against current date
        const now = new Date();
        const currentYear = now.getFullYear();
        const currentMonth = now.getMonth() + 1;
        
        if (year < currentYear || (year === currentYear && month < currentMonth)) {
            expireError = $text('signup.card_expired.text');
            showExpireWarning = true;
            return false;
        }
        
        expireError = '';
        showExpireWarning = false;
        return true;
    }
    
    // Validate CVV
    function validateCVV(cvvCode: string): boolean {
        const digits = cvvCode.replace(/\D/g, '');
        
        if (digits.length !== 3 && digits.length !== 4) {
            cvvError = $text('signup.invalid_cvv.text');
            // Only show warning if field is not empty or if user attempted to submit
            showCVVWarning = digits.length > 0 || attemptedSubmit;
            return false;
        }
        
        cvvError = '';
        showCVVWarning = false;
        return true;
    }
    
    // Handle card number formatting as user types
    async function handleCardNumberInput(event: Event) {
        // Clear payment failed state when user starts editing
        paymentFailed = false;
        
        const input = event.target as HTMLInputElement;
        const cursorPosition = input.selectionStart || 0;
        const previousLength = cardNumber.length;
        
        // Remove all non-digit characters for processing
        const digits = input.value.replace(/\D/g, '');
        
        // Format with spaces every 4 digits
        let formatted = '';
        for (let i = 0; i < digits.length; i++) {
            if (i > 0 && i % 4 === 0) {
                formatted += ' ';
            }
            formatted += digits[i];
        }
        
        // Limit to reasonable card number length
        cardNumber = formatted.substring(0, 23); // 16 digits + 3 spaces
        
        // Adjust cursor position after formatting
        await tick();
        const newPosition = cursorPosition + (cardNumber.length - previousLength);
        
        // Set cursor position for active input
        const activeElement = document.activeElement;
        if (activeElement === cardInputVisible) {
            cardInputVisible.setSelectionRange(newPosition, newPosition);
        } else if (activeElement === cardInputHidden) {
            cardInputHidden.setSelectionRange(newPosition, newPosition);
        }
    }
    
    // Handle card field blur event
    function handleCardBlur() {
        // Mark as complete if there are enough digits
        const digits = cardNumber.replace(/\D/g, '');
        isCardNumberComplete = digits.length >= 13;
        
        // Validate the card number
        validateCardNumber(cardNumber);
    }
    
    // Handle card field focus event
    function handleCardFocus() {
        // Reset the completion status while editing
        isCardNumberComplete = false;
    }
    
    // Get the last four digits of the card number
    function getLastFourDigits(cardNum: string): string {
        const digits = cardNum.replace(/\D/g, '');
        if (digits.length < 4) return digits;
        return digits.slice(-4);
    }
    
    // Handle expiration date input
    async function handleExpireDateInput(event: Event) {
        const input = event.target as HTMLInputElement;
        const cursorPosition = input.selectionStart || 0;
        const previousLength = expireDate.length;
        
        // Format the date
        expireDate = formatExpireDate(input.value);
        
        // Adjust cursor position after formatting
        await tick();
        const newPosition = cursorPosition + (expireDate.length - previousLength);
        input.setSelectionRange(newPosition, newPosition);

        // If expire date is complete (MM/YY format is fully entered), validate it immediately
        if (expireDate.length === 5) {
            validateExpireDate(expireDate);
        }
    }
    
    // Handle CVV input - numbers only
    function handleCVVInput(event: Event) {
        const input = event.target as HTMLInputElement;
        cvv = input.value.replace(/\D/g, '').substring(0, 4);
    }
    
    // Overall form validation
    $: isFormValid = 
        nameOnCard && !nameError &&
        cardNumber && !cardError && 
        expireDate && !expireError && 
        cvv && !cvvError;
    
    function handleBuyClick() {
        // Set flag that user attempted to submit
        attemptedSubmit = true;
        
        // Validate all fields before submission
        const isNameValid = validateName(nameOnCard);
        const isCardValid = validateCardNumber(cardNumber);
        const isExpireValid = validateExpireDate(expireDate);
        const isCvvValid = validateCVV(cvv);
        
        if (isNameValid && isCardValid && isExpireValid && isCvvValid) {
            // Reset payment failed state on new submission
            paymentFailed = false;
            
            // Dispatch payment event with form data
            dispatch('startPayment', {
                nameOnCard,
                cardNumber,
                expireDate,
                cvv,
                lastFourDigits: getLastFourDigits(cardNumber)
            });
        }
    }
    
    // Reset error state
    export function resetErrors() {
        nameError = '';
        cardError = '';
        expireError = '';
        cvvError = '';
        showNameWarning = false;
        showCardWarning = false;
        showExpireWarning = false;
        showCVVWarning = false;
        attemptedSubmit = false;
        paymentFailed = false;
    }
    
    // Set payment failure state
    export function setPaymentFailed() {
        paymentFailed = true;
        cardError = $text('signup.payment_failed.text');
        showCardWarning = true;
        
        // Focus the card input field
        setTimeout(() => {
            if (showSensitiveData && cardInputVisible) {
                cardInputVisible.focus();
            } else if (cardInputHidden) {
                cardInputHidden.focus();
            }
        }, 300);
    }
    
    // Safely get card input element for tooltip
    function getCardInput() {
        return showSensitiveData ? cardInputVisible : cardInputHidden;
    }
</script>

<div class="visibility-toggle">
    <button 
        class="visibility-button"
        on:click={toggleSensitiveDataVisibility}
        aria-label={showSensitiveData ? $text('signup.hide_sensitive_data.text') :$text('signup.show_sensitive_data.text')}
        use:tooltip
    >
        <span class={`clickable-icon ${showSensitiveData ? 'icon_visible' : 'icon_hidden'}`}></span>
    </button>
</div>

<div class="payment-form" in:fade={{ duration: 300 }} style="opacity: {cardFieldLoaded ? 1 : 0}; transition: opacity 0.3s;">
    <div class="color-grey-60 payment-title">
        {@html $text('signup.pay_with_card.text')}
    </div>
    
    <form>
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
            <div class="input-wrapper cardfield-dark">
                <span class="clickable-icon icon_billing"></span>
                <!-- Only the Revolut CardField iframe, styled to match dark/rounded input -->
                <div bind:this={cardFieldTarget} class="card-field-wrapper"></div>
            </div>
        </div>
        
        <!-- Removed custom expiry and CVV fields: CardField handles all card data entry -->
        
        <button 
            type="button" 
            class="buy-button" 
            disabled={!isFormValid}
            on:click={handleBuyClick}
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
    .visibility-toggle {
        position: absolute;
        top: 0px;
        right: 0px;
        z-index: 10;
    }

    .visibility-button {
        all: unset;
        cursor: pointer;
    }

    .visibility-button .clickable-icon {
        position: static;
        transform: none;
        width: 20px;
        height: 20px;
    }
    
    .payment-title {
        text-align: center;
        margin-bottom: 10px;
    }
    
    .input-row {
        display: flex;
        justify-content: space-between;
        width: 100%;
        gap: 12px;
    }
    
    .half {
        width: calc(50% - 6px);
        flex: 1;
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
    
    /* Override default password bullet appearance */
    input[type="password"] {
        font-family: text-security-disc;
        -webkit-text-security: disc;
    }
    
    .card-input-container {
        position: relative;
        width: 100%;
        display: block;
    }
    
    .card-input-container input {
        width: 100%;
        box-sizing: border-box;
        padding-right: 70px;
    }
    
    .last-four-overlay {
        position: absolute;
        right: 12px;
        top: 50%;
        transform: translateY(-50%);
        display: flex;
        align-items: center;
        pointer-events: none;
        z-index: 5;
    }
    
    .last-four-spacer {
        flex: 1;
    }
    
    .last-four-digits {
        font-family: inherit;
        font-size: inherit;
        color: inherit;
        white-space: nowrap;
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
