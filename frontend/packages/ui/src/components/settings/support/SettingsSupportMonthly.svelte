<!--
    SettingsSupportMonthly Component

    Monthly recurring support contribution form.
    Shows predefined monthly support amounts and includes payment form with email field.
    Works for both authenticated and non-authenticated users.
    Includes cancellation information.
-->

<script lang="ts">
    import { tick } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';
    import Payment from '../../Payment.svelte';
    import { authStore } from '../../../stores/authStore';
    import InputWarning from '../../common/InputWarning.svelte';

    // Predefined monthly support amounts in EUR
    const monthlyTiers = [
        { amount: 5, credits: 0 },
        { amount: 10, credits: 0 },
        { amount: 20, credits: 0 },
        { amount: 50, credits: 0 },
        { amount: 100, credits: 0 },
        { amount: 200, credits: 0 }
    ];

    let selectedTier = $state<typeof monthlyTiers[0] | null>(null);
    let showPaymentForm = $state(false);
    let currency = $state('EUR');
    let paymentStarted = $state(false);

    // Email field for non-authenticated users
    let email = $state('');
    let emailInput = $state<HTMLInputElement>();
    let emailTouched = $state(false);

    // Check if user is authenticated
    let isAuthenticated = $derived($authStore.isAuthenticated);

    // Format currency
    function formatCurrency(amount: number, currency: string): string {
        const symbols: Record<string, string> = {
            'EUR': '€',
            'USD': '$',
            'JPY': '¥'
        };
        const symbol = symbols[currency.toUpperCase()] || '€';
        return currency.toUpperCase() === 'JPY' ? `${symbol}${amount}` : `${symbol}${amount}`;
    }

    // Navigate to payment form for a specific tier
    function selectMonthlyTier(tier: typeof monthlyTiers[0]) {
        selectedTier = tier;
        showPaymentForm = true;
        paymentStarted = false;
    }

    // Handle going back to tier selection
    function backToTierSelection() {
        showPaymentForm = false;
        selectedTier = null;
        paymentStarted = false;
        emailTouched = false;
    }

    function validateEmailValue(value: string): string {
        if (!value) return 'Please enter your email address';
        if (value.length < 5) return 'Email address is too short';
        if (!value.includes('@')) return $text('signup.at_missing.text');

        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(value)) return 'Please enter a valid email address';
        if (!value.match(/\.[a-z]{2,}$/i)) return $text('signup.domain_ending_missing.text');

        return '';
    }

    let trimmedEmail = $derived(email.trim());
    let emailError = $derived(!isAuthenticated ? validateEmailValue(trimmedEmail) : '');
    let canContinue = $derived(
        !!selectedTier &&
        !paymentStarted &&
        !isAuthenticated &&
        (!emailError && !!trimmedEmail)
    );

    $effect(() => {
        if (showPaymentForm && selectedTier && isAuthenticated) {
            paymentStarted = true;
        }
    });

    async function continueToPayment() {
        if (paymentStarted) return;

        if (!isAuthenticated) {
            emailTouched = true;
            const validationError = validateEmailValue(trimmedEmail);
            if (validationError) {
                await tick();
                emailInput?.focus();
                return;
            }
            email = trimmedEmail;
        }

        paymentStarted = true;
    }

    async function changeEmail() {
        paymentStarted = false;
        await tick();
        emailInput?.focus();
    }

    // Handle payment completion
    function handlePaymentComplete(event: CustomEvent<{ state: string, payment_intent_id?: string }>) {
        const paymentState = event.detail?.state;

        if (paymentState === 'success') {
            // Show success message and go back to tier selection
            backToTierSelection();
            // Could dispatch an event to show success notification
        } else if (paymentState === 'failure') {
            // Keep the payment form open; Payment component shows the error.
        }
    }
</script>

{#if !showPaymentForm}
    <!-- Monthly Support Tier Selection -->
    <div class="disclaimer-container">
        <div class="disclaimer">
            <span class="clickable-icon icon_info"></span>
            <div>
                <p>{$text('settings.support.disclaimer.text')}</p>
                <p class="cancellation-info">{$text('settings.support.monthly.cancellation_info.text')}</p>
            </div>
        </div>
    </div>

    {#each monthlyTiers as tier}
        <SettingsItem
            type="submenu"
            icon="subsetting_icon subsetting_icon_calendar"
            title={formatCurrency(tier.amount, currency) + '/' + $text('settings.support.monthly.per_month.text')}
            onClick={() => selectMonthlyTier(tier)}
        />
    {/each}

{:else if selectedTier}
    <!-- Payment Form -->
    <div class="payment-form-container">
        <div class="back-button-container">
            <button class="back-button" onclick={backToTierSelection}>
                <span class="clickable-icon icon_back"></span>
                {$text('settings.support.back_to_amounts.text')}
            </button>
        </div>

        <div class="selected-tier-info">
            <h3>{formatCurrency(selectedTier.amount, currency)}/{$text('settings.support.monthly.per_month.text')}</h3>
            <div class="recurring-info">
                <span class="clickable-icon icon_reload"></span>
                {$text('settings.support.monthly.recurring_notice.text')}
            </div>
        </div>

        {#if !isAuthenticated}
            <div class="email-field-container">
                <div class="email-field-label">
                    {$text('settings.support.email_label.text')}
                </div>
                <div class="input-wrapper">
                    <span class="clickable-icon icon_mail"></span>
                    <input
                        bind:this={emailInput}
                        type="email"
                        bind:value={email}
                        placeholder={$text('login.email_placeholder.text')}
                        required
                        autocomplete="email"
                        disabled={paymentStarted}
                        onblur={() => (emailTouched = true)}
                        onkeydown={(e) => e.key === 'Enter' && continueToPayment()}
                        class:error={emailTouched && !!emailError}
                    />
                    {#if emailTouched && emailError}
                        <InputWarning
                            message={emailError}
                            target={emailInput}
                        />
                    {/if}
                </div>
            </div>
        {/if}

        <div class="cancellation-notice">
            <span class="clickable-icon icon_info"></span>
            <p>{$text('settings.support.monthly.cancellation_details.text')}</p>
        </div>

        {#if !isAuthenticated}
            <div class="button-group">
                <button class="primary-button" onclick={continueToPayment} disabled={!canContinue}>
                    {$text('signup.continue.text')}
                </button>
                {#if paymentStarted}
                    <button class="secondary-button" onclick={changeEmail}>
                        Change email
                    </button>
                {/if}
            </div>
        {/if}

        {#if paymentStarted}
            <div class="payment-component-container">
                <Payment
                    purchasePrice={selectedTier.amount * 100}
                    currency={currency}
                    credits_amount={0}
                    requireConsent={false}
                    compact={false}
                    disableWebSocketHandlers={true}
                    supportContribution={true}
                    supportEmail={isAuthenticated ? null : trimmedEmail}
                    isRecurring={true}
                    on:paymentStateChange={handlePaymentComplete}
                />
            </div>
        {/if}
    </div>
{/if}

<style>
    .disclaimer-container {
        margin-bottom: 20px;
        padding: 0 15px;
    }

    .disclaimer {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        padding: 16px;
        background-color: var(--color-info-light, #e3f2fd);
        border: 1px solid var(--color-info, #2196f3);
        border-radius: 8px;
    }

    .disclaimer .clickable-icon {
        width: 20px;
        height: 20px;
        margin-top: 2px;
        flex-shrink: 0;
        background-color: var(--color-info, #2196f3);
    }

    .disclaimer div p {
        margin: 0 0 8px 0;
        font-size: 14px;
        line-height: 1.4;
        color: var(--color-info-dark, #1976d2);
    }

    .disclaimer div p:last-child {
        margin-bottom: 0;
    }

    .cancellation-info {
        font-size: 13px !important;
        font-style: italic;
    }

    .payment-form-container {
        padding: 0 15px;
    }

    .back-button-container {
        margin-bottom: 20px;
    }

    .back-button {
        display: flex;
        align-items: center;
        gap: 8px;
        background: none;
        border: none;
        color: var(--color-grey-60);
        cursor: pointer;
        font-size: 14px;
        padding: 8px 0;
        transition: color 0.2s;
    }

    .back-button:hover {
        color: var(--color-grey-80);
    }

    .back-button .clickable-icon {
        width: 20px;
        height: 20px;
    }

    .selected-tier-info {
        margin-bottom: 24px;
        text-align: center;
    }

    .selected-tier-info h3 {
        margin: 0 0 8px 0;
        font-size: 18px;
        font-weight: 600;
        color: var(--color-grey-80);
    }

    .recurring-info {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        font-size: 13px;
        color: var(--color-grey-60);
        font-style: italic;
    }

    .recurring-info .clickable-icon {
        width: 16px;
        height: 16px;
    }

    .email-field-container {
        margin-bottom: 24px;
    }

    .email-field-label {
        margin-bottom: 8px;
        font-size: 14px;
        font-weight: 500;
        color: var(--color-grey-70);
    }

    .input-wrapper {
        position: relative;
        display: flex;
        align-items: center;
        width: 100%;
    }

    .input-wrapper .clickable-icon {
        position: absolute;
        left: 12px;
        width: 20px;
        height: 20px;
        background-color: var(--color-grey-60);
        z-index: 1;
    }

    .input-wrapper input {
        width: 100%;
        padding: 12px 12px 12px 44px;
        border: 2px solid var(--color-grey-30);
        border-radius: 8px;
        font-size: 14px;
        background-color: var(--color-grey-10);
        transition: border-color 0.2s;
    }

    .input-wrapper input:focus {
        outline: none;
        border-color: var(--color-primary);
    }

    .input-wrapper input.error {
        border-color: var(--color-error, #e74c3c);
    }

    .button-group {
        display: flex;
        gap: 8px;
        margin-top: 8px;
        justify-content: center;
    }

    .primary-button {
        padding: 10px 16px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
        border: none;
        background: var(--color-primary);
        color: white;
        min-width: 140px;
    }

    .primary-button:hover:not(:disabled) {
        background: var(--color-primary-hover);
    }

    .primary-button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .secondary-button {
        padding: 10px 16px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
        border: 1px solid var(--color-grey-30);
        background: transparent;
        color: var(--color-grey-100);
    }

    .secondary-button:hover:not(:disabled) {
        background: var(--color-grey-10);
    }

    .cancellation-notice {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        padding: 12px 16px;
        margin-bottom: 20px;
        background-color: var(--color-warning-light, #fff3cd);
        border: 1px solid var(--color-warning, #ffc107);
        border-radius: 8px;
    }

    .cancellation-notice .clickable-icon {
        width: 18px;
        height: 18px;
        margin-top: 1px;
        flex-shrink: 0;
        background-color: var(--color-warning-dark, #856404);
    }

    .cancellation-notice p {
        margin: 0;
        font-size: 13px;
        line-height: 1.4;
        color: var(--color-warning-dark, #856404);
    }

    .payment-component-container {
        margin-top: 24px;
    }

    @media (max-width: 480px) {
        .payment-form-container {
            padding: 0 5px;
        }

        .disclaimer-container {
            padding: 0 5px;
        }
    }
</style>
