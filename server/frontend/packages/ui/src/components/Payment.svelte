<script lang="ts">
    import { text } from '@repo/ui';
    import { onMount, createEventDispatcher, tick } from 'svelte';
    import Toggle from './Toggle.svelte';
    import InputWarning from './common/InputWarning.svelte';
    import { getWebsiteUrl, routes } from '../config/links';
    import { fade } from 'svelte/transition';
    
    const dispatch = createEventDispatcher();
    
    // Accept props
    export let purchasePrice: number = 20;
    export let currency: string = 'EUR';
    export let credits_amount: number = 21000;
    export let requireConsent: boolean = true;
    export let compact: boolean = false; // For tighter layouts

    // Toggle state for consent
    let hasConsentedToLimitedRefund = false;
    
    // Add state to track if sensitive data should be visible
    let showSensitiveData = false;
    
    // Track if card has been entered and user finished typing
    let isCardNumberComplete = false;
    
    $: if (hasConsentedToLimitedRefund) {
        dispatch('consentGiven', { consented: true });
    }
    
    // Payment form state
    export let showPaymentForm = !requireConsent;
    let nameOnCard = '';
    let cardNumber = '';
    let expireDate = '';
    let cvv = '';
    
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
    
    // Format number with thousand separators
    function formatNumber(num: number): string {
        return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    }

    // Show payment form after consent is given
    $: if (requireConsent && hasConsentedToLimitedRefund && !showPaymentForm) {
        setTimeout(() => {
            showPaymentForm = true;
            
            // Focus the name field after transition
            setTimeout(() => {
                if (nameInput) nameInput.focus();
            }, 300);
        }, 300); // Delay to allow fade out animation
    }
    
    // Function to handle toggle click
    function handleRowClick() {
        hasConsentedToLimitedRefund = !hasConsentedToLimitedRefund;
    }
    
    // Function to prevent toggle click from triggering row click
    function handleToggleClick(event: Event) {
        event.stopPropagation();
    }
    
    // Toggle visibility of sensitive data
    function toggleSensitiveDataVisibility() {
        showSensitiveData = !showSensitiveData;
        
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
    
    function openRefundInfo() {
        // Open refund info in new tab
        window.open(getWebsiteUrl(routes.docs.userGuide_signup_10_1), '_blank');
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
        const activeInput = document.activeElement;
        if (activeInput === cardInputVisible) {
            cardInputVisible.setSelectionRange(newPosition, newPosition);
        } else if (activeInput === cardInputHidden) {
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
            dispatch('payment', {
                nameOnCard,
                cardNumber,
                expireDate,
                cvv,
                amount: credits_amount,
                price: purchasePrice,
                currency
            });
        }
    }
</script>

<div class="payment-component {compact ? 'compact' : ''}">
    {#if requireConsent && !showPaymentForm}
        <div class="consent-view" in:fade={{ duration: 300 }} out:fade={{ duration: 200 }}>
            <div class="signup-header">
                <div class="icon header_size legal"></div>
                <h2 class="signup-menu-title">{@html $text('signup.limited_refund.text')}</h2>
            </div>

            <div class="consent-container">
                <div class="confirmation-row" 
                    on:click={handleRowClick}
                    on:keydown={(e) => e.key === 'Enter' || e.key === ' ' ? handleRowClick() : null}
                    role="button"
                    tabindex="0">
                    <div on:click={handleToggleClick} on:keydown|stopPropagation role="button" tabindex="0">
                        <Toggle bind:checked={hasConsentedToLimitedRefund} />
                    </div>
                    <span class="confirmation-text">
                        {@html $text('signup.i_agree_to_limited_refund.text')}
                    </span>
                </div>
                <button on:click={openRefundInfo} class="text-button learn-more-button">
                    {@html $text('signup.click_here_learn_more.text')}
                </button>
            </div>
        </div>
    {:else}
        <div class="payment-form" in:fade={{ duration: 300 }}>
            <div class="visibility-toggle">
                <button 
                    class="visibility-button"
                    on:click={toggleSensitiveDataVisibility}
                    aria-label={showSensitiveData ? "Hide sensitive data" : "Show sensitive data"}
                >
                    <span class={`clickable-icon ${showSensitiveData ? 'icon_visible' : 'icon_hidden'}`}></span>
                </button>
            </div>
            
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
                
                <button type="button" class="apple-pay-button">
                    <span class="apple-pay-text">Pay with Apple Pay</span>
                </button>
                
                <div class="payment-info">
                    <p class="vat-info color-grey-60">
                        {@html $text('signup.vat_info.text')}
                    </p>
                    <button type="button" class="secured-by">
                        <span class="lock-icon"></span>
                        {@html $text('signup.secured_and_powered_by.text').replace('{provider}', 'mollie')}
                    </button>
                </div>
            </form>
        </div>
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

    .visibility-toggle {
        position: absolute;
        top: 10px;
        right: 10px;
        z-index: 10;
    }

    .visibility-button {
        background: transparent;
        border: none;
        cursor: pointer;
        padding: 5px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .visibility-button .clickable-icon {
        position: static;
        transform: none;
        width: 20px;
        height: 20px;
    }
    
    .card-input-container {
        position: relative;
        width: 100%;
        display: block;
    }
    
    .card-input-container input {
        width: 100%;
        box-sizing: border-box;
        padding-right: 70px; /* Add padding to leave space for the last four digits */
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

    /* Override default password bullet appearance */
    input[type="password"] {
        font-family: text-security-disc;
        -webkit-text-security: disc;
        /* Fix width issues for password inputs */
        width: 100%;
        box-sizing: border-box;
    }
    
    /* Ensure all inputs have consistent width */
    input {
        width: 100%;
        box-sizing: border-box;
    }

    .signup-header {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 16px;
    }
    
    .consent-container {
        width: 100%;
        max-width: 400px;
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 24px;
        padding-top: 30px;
    }
    
    .confirmation-row {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        cursor: pointer;
        width: 100%;
    }
    
    .confirmation-text {
        color: var(--color-grey-60);
        font-size: 16px;
        text-align: left;
        flex: 1;
    }

    .learn-more-button {
        padding-left: 66px;
        text-align: left;
    }

    .payment-form {
        width: 100%;
        height: 100%;
        display: flex;
        flex-direction: column;
    }
    
    .payment-title {
        font-size: 18px;
        text-align: center;
        margin-bottom: 20px;
        padding-top: 8px;
    }
    
    .input-row {
        display: flex;
        gap: 10px;
        width: 100%;
    }
    
    .half {
        width: calc(50% - 5px);
    }

    .clickable-icon {
        position: absolute;
        left: 15px;
        top: 50%;
        transform: translateY(-50%);
        width: 20px;
        height: 20px;
        background-size: contain;
        background-position: center;
        background-repeat: no-repeat;
        opacity: 0.6;
        z-index: 1;
    }
    
    .buy-button {
        width: 100%;
    }

    .buy-button:disabled {
        opacity: 0.7;
        cursor: not-allowed;
    }
    
    :global(.coin-icon-inline) {
        display: inline-flex;
        width: 16px;
        height: 16px;
        background-image: url('@openmates/ui/static/icons/coins.svg');
        background-size: contain;
        background-repeat: no-repeat;
        vertical-align: middle;
        filter: invert(1);
        margin-left: 5px;
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
    
    .payment-info {
        margin-top: 16px;
    }
    
    .vat-info {
        font-size: 14px;
        text-align: center;
        margin-bottom: 10px;
    }
    
    .secured-by {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        width: 100%;
        font-size: 14px;
        color: var(--color-grey-60);
        background: transparent;
        border: none;
        cursor: pointer;
    }

</style>
