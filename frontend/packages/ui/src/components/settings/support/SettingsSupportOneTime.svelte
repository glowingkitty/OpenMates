<!--
    SettingsSupportOneTime Component

    One-time support contribution form.
    Shows predefined support amounts and includes payment form with email field.
    Works for both authenticated and non-authenticated users.
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';
    import Payment from '../../Payment.svelte';
    import { getApiEndpoint, apiEndpoints } from '../../../config/api';
    import { authStore } from '../../../stores/authStore';
    import { userProfile } from '../../../stores/userProfile';
    import InputWarning from '../../common/InputWarning.svelte';

    const dispatch = createEventDispatcher();

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
    let currency = $state('EUR');

    // Email field for non-authenticated users
    let email = $state('');
    let emailInput = $state<HTMLInputElement>();
    let showEmailWarning = $state(false);
    let emailError = $state('');
    let isEmailValidationPending = $state(false);

    // Check if user is authenticated
    let isAuthenticated = $derived($authStore.isAuthenticated);
    let userEmail = $derived($userProfile.email);

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
    function selectSupportTier(tier: typeof supportTiers[0]) {
        selectedTier = tier;
        showPaymentForm = true;
    }

    // Handle going back to tier selection
    function backToTierSelection() {
        showPaymentForm = false;
        selectedTier = null;
    }

    // Email validation (same as signup form)
    function debounce<T extends (...args: any[]) => void>(
        fn: T,
        delay: number
    ): (...args: Parameters<T>) => void {
        let timeoutId: ReturnType<typeof setTimeout>;
        return (...args: Parameters<T>) => {
            clearTimeout(timeoutId);
            timeoutId = setTimeout(() => fn(...args), delay);
        };
    }

    const debouncedCheckEmail = debounce((email: string) => {
        if (!email) {
            emailError = '';
            showEmailWarning = false;
            isEmailValidationPending = false;
            return;
        }

        // Check minimum length
        if (email.length < 5) {
            emailError = 'Email address is too short';
            showEmailWarning = true;
            isEmailValidationPending = false;
            return;
        }

        if (!email.includes('@')) {
            emailError = $text('signup.at_missing.text');
            showEmailWarning = true;
            isEmailValidationPending = false;
            return;
        }

        // Check for proper email format
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(email)) {
            emailError = 'Please enter a valid email address';
            showEmailWarning = true;
            isEmailValidationPending = false;
            return;
        }

        if (!email.match(/\.[a-z]{2,}$/i)) {
            emailError = $text('signup.domain_ending_missing.text');
            showEmailWarning = true;
            isEmailValidationPending = false;
            return;
        }

        emailError = '';
        showEmailWarning = false;
        isEmailValidationPending = false;
    }, 800);

    // Watch email changes and validate
    $effect(() => {
        if (!isAuthenticated && email) {
            isEmailValidationPending = true;
            debouncedCheckEmail(email);
        } else if (!isAuthenticated) {
            emailError = '';
            showEmailWarning = false;
            isEmailValidationPending = false;
        }
    });

    // Check if form is ready for payment
    let isFormReady = $derived(
        selectedTier &&
        (isAuthenticated || (email && !emailError && !isEmailValidationPending))
    );

    // Handle payment completion
    function handlePaymentComplete(event: CustomEvent<{ state: string, payment_intent_id?: string }>) {
        const paymentState = event.detail?.state;

        if (paymentState === 'success') {
            // Show success message and go back to tier selection
            backToTierSelection();
            // Could dispatch an event to show success notification
        }
    }
</script>

{#if !showPaymentForm}
    <!-- Support Tier Selection -->
    <div class="disclaimer-container">
        <div class="disclaimer">
            <span class="clickable-icon icon_info"></span>
            <p>{$text('settings.support.disclaimer.text')}</p>
        </div>
    </div>

    {#each supportTiers as tier}
        <SettingsItem
            type="submenu"
            icon="subsetting_icon subsetting_icon_heart"
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
                {$text('settings.support.back_to_amounts.text')}
            </button>
        </div>

        <div class="selected-tier-info">
            <h3>{formatCurrency(selectedTier.amount, currency)}</h3>
        </div>

        {#if !isAuthenticated}
            <!-- Email field for non-authenticated users -->
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
                        class:error={!!emailError}
                    />
                    {#if showEmailWarning && emailError}
                        <InputWarning
                            message={emailError}
                            target={emailInput}
                        />
                    {/if}
                </div>
            </div>
        {/if}

        {#if isFormReady}
            <div class="payment-component-container">
                <Payment
                    purchasePrice={selectedTier.amount * 100}
                    currency={currency}
                    credits_amount={0}
                    requireConsent={false}
                    compact={false}
                    disableWebSocketHandlers={true}
                    supportContribution={true}
                    supportEmail={isAuthenticated ? userEmail : email}
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

    .disclaimer p {
        margin: 0;
        font-size: 14px;
        line-height: 1.4;
        color: var(--color-info-dark, #1976d2);
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
        margin: 0;
        font-size: 18px;
        font-weight: 600;
        color: var(--color-grey-80);
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