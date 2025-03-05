<script lang="ts">
    import { text } from '@repo/ui';
    import { createEventDispatcher, tick } from 'svelte';
    import InputWarning from '../common/InputWarning.svelte';
    import { getWebsiteUrl, routes } from '../../config/links';
    import { fade } from 'svelte/transition';
    import { tooltip } from '../../actions/tooltip';
    
    const dispatch = createEventDispatcher();
    
    export let purchasePrice: number = 20;
    export let currency: string = 'EUR';
    export let showSensitiveData: boolean = false;
    
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
    
    // Validation states
    let nameError = '';
    let cardError = '';
    let expireError = '';
    let cvvError = '';
    
    let showNameWarning = false;
    let showCardWarning = false;
    let showExpireWarning = false;
    let showCVVWarning = false;
    
    // Track if form was submitted
    let attemptedSubmit = false;
    
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
    }
    
    // Set payment failure state
    export function setPaymentFailed() {
        cardError = $text('signup.payment_failed.text');
        showCardWarning = true;
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

<div class="payment-form" in:fade={{ duration: 300 }}>
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
            <div class="input-wrapper">
                <span class="clickable-icon icon_billing"></span>
                
                <!-- Show appropriate card input based on visibility preference -->
                {#if showSensitiveData}
                    <input 
                        bind:this={cardInputVisible}
                        type="text"
                        bind:value={cardNumber}
                        placeholder={$text('signup.card_number.text')}
                        on:input={handleCardNumberInput}
                        on:focus={handleCardFocus}
                        on:blur={handleCardBlur}
                        class:error={!!cardError}
                        required
                        inputmode="numeric"
                        autocomplete="cc-number"
                    />
                {:else}
                    <!-- We use a regular input with normalized value but apply CSS to make bullets -->
                    <div class="card-input-container">
                        <input 
                            bind:this={cardInputHidden}
                            type="password"
                            bind:value={cardNumber}
                            placeholder={$text('signup.card_number.text')}
                            on:input={handleCardNumberInput}
                            on:focus={handleCardFocus}
                            on:blur={handleCardBlur}
                            class:error={!!cardError}
                            required
                            inputmode="numeric"
                            autocomplete="cc-number"
                        />
                        <!-- Last four digits overlay when card is completed and not being edited -->
                        {#if isCardNumberComplete && cardNumber}
                        <div class="last-four-overlay">
                            <span class="last-four-spacer"></span>
                            <span class="last-four-digits">{getLastFourDigits(cardNumber)}</span>
                        </div>
                        {/if}
                    </div>
                {/if}
                
                {#if showCardWarning && cardError}
                    <InputWarning 
                        message={cardError}
                        target={showSensitiveData ? cardInputVisible : cardInputHidden}
                    />
                {/if}
            </div>
        </div>
        
        <div class="input-row">
            <div class="input-group half">
                <div class="input-wrapper">
                    <span class="clickable-icon icon_calendar"></span>
                    <input 
                        bind:this={expireInput}
                        type="text" 
                        bind:value={expireDate}
                        placeholder={$text('signup.mm_yy.text')}
                        on:input={handleExpireDateInput}
                        on:blur={() => validateExpireDate(expireDate)}
                        class:error={!!expireError}
                        required
                        maxlength="5"
                        inputmode="numeric"
                        autocomplete="cc-exp"
                    />
                    {#if showExpireWarning && expireError}
                        <InputWarning 
                            message={expireError}
                            target={expireInput}
                        />
                    {/if}
                </div>
            </div>
            
            <div class="input-group half">
                <div class="input-wrapper">
                    <span class="clickable-icon icon_secret"></span>
                    
                    <!-- Show appropriate CVV input based on visibility preference -->
                    {#if showSensitiveData}
                        <input 
                            bind:this={cvvInputVisible}
                            type="text"
                            bind:value={cvv}
                            placeholder={$text('signup.cvv.text')}
                            on:input={handleCVVInput}
                            on:blur={() => validateCVV(cvv)}
                            class:error={!!cvvError}
                            required
                            maxlength="4"
                            inputmode="numeric"
                            autocomplete="cc-csc"
                        />
                    {:else}
                        <input 
                            bind:this={cvvInputHidden}
                            type="password"
                            bind:value={cvv}
                            placeholder={$text('signup.cvv.text')}
                            on:input={handleCVVInput}
                            on:blur={() => validateCVV(cvv)}
                            class:error={!!cvvError}
                            required
                            maxlength="4"
                            inputmode="numeric"
                            autocomplete="cc-csc"
                        />
                    {/if}
                    
                    {#if showCVVWarning && cvvError}
                        <InputWarning 
                            message={cvvError}
                            target={showSensitiveData ? cvvInputVisible : cvvInputHidden}
                        />
                    {/if}
                </div>
            </div>
        </div>
        
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
        height: 100%;
        position: relative;
        display: flex;
        flex-direction: column;
        padding-bottom: 60px; /* Make room for bottom container */
    }
    
    .bottom-container {
        position: absolute;
        bottom: 0;
        left: 0;
        width: 100%;
        display: flex;
        justify-content: center;
        padding-bottom: 16px;
        align-items: center;
        min-height: 50px;
    }
    
    .visibility-toggle {
        position: absolute;
        top: 10px;
        right: 10px;
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
        margin-bottom: 24px;
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
