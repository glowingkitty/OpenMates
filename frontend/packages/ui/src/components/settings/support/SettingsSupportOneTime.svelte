<!--
    SettingsSupportOneTime Component

    One-time support contribution form.
    Shows predefined support amounts and includes payment form with email field.
    Works for both authenticated and non-authenticated users.
-->

<script lang="ts">
    import { tick } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';
    import Payment from '../../Payment.svelte';
    import BankTransferPayment from '../../payment/BankTransferPayment.svelte';
    import { authStore } from '../../../stores/authStore';
    import { apiEndpoints } from '../../../config/api';
    import InputWarning from '../../common/InputWarning.svelte';
    import { SettingsInput, SettingsInfoBox } from '../elements';
    import SettingsSupportOneTimeConfirmation from './SettingsSupportOneTimeConfirmation.svelte';

    // Predefined support amounts in EUR
    const supportTiers = [
        { amount: 5, credits: 0 },
        { amount: 10, credits: 0 },
        { amount: 20, credits: 0 },
        { amount: 50, credits: 0 },
        { amount: 100, credits: 0 },
        { amount: 200, credits: 0 }
    ];

    let selectedTier = $state<typeof supportTiers[0] | null>(null);
    let showPaymentForm = $state(false);
    let showConfirmation = $state(false);
    let currency = $state('EUR');
    let paymentStarted = $state(false);
    let showBankTransfer = $state(false);
    let bankTransferAvailable = $state(false);

    // Check bank transfer availability on mount
    (async () => {
        try {
            const response = await fetch(apiEndpoints.payments.config, { credentials: 'include' });
            if (response.ok) {
                const config = await response.json();
                bankTransferAvailable = config.bank_transfer_available || false;
            }
        } catch { /* silently ignore */ }
    })();

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
        };
        const symbol = symbols[currency.toUpperCase()] || currency.toUpperCase();
        return `${symbol}${amount}`;
    }

    // Navigate to payment form for a specific tier
    function selectSupportTier(tier: typeof supportTiers[0]) {
        selectedTier = tier;
        showPaymentForm = true;
        paymentStarted = false;
    }

    // Handle going back to tier selection
    function backToTierSelection() {
        showPaymentForm = false;
        showConfirmation = false;
        selectedTier = null;
        paymentStarted = false;
        emailTouched = false;
    }

    function validateEmailValue(value: string): string {
        if (!value) return 'Please enter your email address';
        if (value.length < 5) return 'Email address is too short';
        if (!value.includes('@')) return $text('signup.at_missing');

        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(value)) return 'Please enter a valid email address';
        if (!value.match(/\.[a-z]{2,}$/i)) return $text('signup.domain_ending_missing');

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
            // Show confirmation screen
            showPaymentForm = false;
            showConfirmation = true;
            paymentStarted = false;
        } else if (paymentState === 'failure') {
            // Keep the payment form open; Payment component shows the error.
        }
    }
</script>

{#if showConfirmation && selectedTier}
    <!-- Confirmation Screen -->
    <SettingsSupportOneTimeConfirmation
        amount={selectedTier.amount}
        currency={currency}
        on:openSettings
    />

{:else if !showPaymentForm}
    <!-- Support Tier Selection -->
    <SettingsInfoBox type="info">
        {$text('settings.support.disclaimer')}
    </SettingsInfoBox>

    <div class="tier-spacer"></div>

    {#each supportTiers as tier}
        <SettingsItem
            type="submenu"
            icon="subsetting_icon heart"
            title={formatCurrency(tier.amount, currency)}
            onClick={() => selectSupportTier(tier)}
        />
    {/each}

{:else if selectedTier}
    <!-- Payment Form -->
    <div class="payment-form-container">
        <div class="back-button-container">
            <button class="back-button" onclick={backToTierSelection}>
                <span class="clickable-icon icon_back"></span>
                {$text('settings.support.back_to_amounts')}
            </button>
        </div>

        <div class="selected-tier-info">
            <h3>{formatCurrency(selectedTier.amount, currency)}</h3>
        </div>

        {#if !isAuthenticated}
            <div class="email-field-container">
                <div class="email-field-label">
                    {$text('common.email')}
                </div>
                <SettingsInput
                    bind:value={email}
                    bind:inputRef={emailInput}
                    type="email"
                    placeholder={$text('login.email_placeholder')}
                    autocomplete="email"
                    disabled={paymentStarted}
                    hasError={emailTouched && !!emailError}
                    onBlur={() => (emailTouched = true)}
                    onKeydown={(e) => e.key === 'Enter' && continueToPayment()}
                />
                {#if emailTouched && emailError}
                    <InputWarning
                        message={emailError}
                    />
                {/if}
            </div>
        {/if}

        {#if !isAuthenticated}
            <div class="button-group">
                <button class="primary-button" onclick={continueToPayment} disabled={!canContinue}>
                    {$text('common.continue')}
                </button>
                {#if paymentStarted}
                    <button class="secondary-button" onclick={changeEmail}>
                        Change email
                    </button>
                {/if}
            </div>
        {/if}

        {#if paymentStarted && !showBankTransfer}
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
                    on:paymentStateChange={handlePaymentComplete}
                />
                {#if bankTransferAvailable}
                    <div class="provider-switch-container">
                        <button class="provider-switch-btn" onclick={() => { showBankTransfer = true; }} data-testid="support-switch-to-bank-transfer">
                            {$text('settings.billing.bank_transfer')}
                        </button>
                    </div>
                {/if}
            </div>
        {:else if paymentStarted && showBankTransfer}
            <div class="payment-component-container">
                <button class="provider-switch-btn" onclick={() => { showBankTransfer = false; }} data-testid="support-bank-transfer-back">
                    &larr; {$text('common.back')}
                </button>
                <BankTransferPayment
                    credits_amount={0}
                    price={selectedTier.amount * 100}
                    currency={currency}
                    isSupportContribution={true}
                    supportEmail={isAuthenticated ? '' : trimmedEmail}
                    on:paymentStateChange={handlePaymentComplete}
                />
            </div>
        {/if}
    </div>
{/if}

<style>
    .tier-spacer {
        height: 1rem;
    }

    .payment-form-container {
        padding: 0 15px;
    }

    .back-button-container {
        margin-bottom: var(--spacing-10);
    }

    .back-button {
        display: flex;
        align-items: center;
        gap: var(--spacing-4);
        background: none;
        border: none;
        color: var(--color-grey-60);
        cursor: pointer;
        font-size: var(--font-size-small);
        padding: 8px 0;
        transition: color var(--duration-normal);
    }

    .back-button:hover {
        color: var(--color-grey-80);
    }

    .back-button .clickable-icon {
        width: 20px;
        height: 20px;
    }

    .selected-tier-info {
        margin-bottom: var(--spacing-12);
        text-align: center;
    }

    .selected-tier-info h3 {
        margin: 0;
        font-size: var(--font-size-h3-mobile);
        font-weight: 600;
        color: var(--color-grey-80);
    }

    .email-field-container {
        margin-bottom: var(--spacing-12);
    }

    .email-field-label {
        margin-bottom: var(--spacing-4);
        font-size: var(--font-size-small);
        font-weight: 500;
        color: var(--color-grey-70);
    }

    .button-group {
        display: flex;
        gap: var(--spacing-4);
        margin-top: var(--spacing-4);
        justify-content: center;
    }

    .primary-button {
        padding: var(--spacing-5) var(--spacing-8);
        border-radius: var(--radius-3);
        font-size: var(--font-size-small);
        font-weight: 500;
        cursor: pointer;
        transition: all var(--duration-normal) var(--easing-default);
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
        padding: var(--spacing-5) var(--spacing-8);
        border-radius: var(--radius-3);
        font-size: var(--font-size-small);
        font-weight: 500;
        cursor: pointer;
        transition: all var(--duration-normal) var(--easing-default);
        border: 1px solid var(--color-grey-30);
        background: transparent;
        color: var(--color-grey-100);
    }

    .secondary-button:hover:not(:disabled) {
        background: var(--color-grey-10);
    }

    .payment-component-container {
        margin-top: var(--spacing-12);
    }

    @media (max-width: 480px) {
        .payment-form-container {
            padding: 0 5px;
        }
    }
</style>
