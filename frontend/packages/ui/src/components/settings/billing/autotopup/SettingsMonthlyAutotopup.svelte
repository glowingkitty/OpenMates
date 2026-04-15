<!--
Monthly Auto Top-Up Subscription - View and manage monthly subscription
Allows creating new subscriptions if user has a saved payment method
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { SettingsSectionHeading } from '../../elements';
    import { apiEndpoints, getApiEndpoint } from '../../../../config/api';
    import { pricingTiers } from '../../../../config/pricing';
    import SettingsDropdown from '../../elements/SettingsDropdown.svelte';

    let isLoading = $state(false);
    let hasSubscription = $state(false);
    let hasActiveSubscription = $state(false);
    let subscriptionDetails: Record<string, unknown> | null = $state(null);
    let hasPaymentMethod = $state(false);
    let showCreateForm = $state(false);

    // Create subscription form state
    let selectedTierCredits = $state<number | null>(null);
    let selectedCurrency = $state('EUR');
    let isCreating = $state(false);
    let billingDayPreference = $state('anniversary'); // 'anniversary' or 'first_of_month'
    let isUpdatingBillingDay = $state(false);

    // Format credits with dots as thousand separators
    function formatCredits(credits: number): string {
        return credits.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    }

    function isActiveLikeSubscription(status?: string): boolean {
        const normalized = (status || '').toLowerCase();
        return normalized === 'active' || normalized === 'trialing';
    }

    function parseNextChargeDate(details: Record<string, unknown> | null): Date | null {
        const raw =
            details?.next_billing_date ??
            details?.nextBillingDate ??
            details?.next_payment_date ??
            details?.nextPaymentDate ??
            null;

        if (raw === null || raw === undefined || raw === '') return null;

        if (typeof raw === 'number' && Number.isFinite(raw)) {
            const ms = raw < 1e12 ? raw * 1000 : raw;
            const date = new Date(ms);
            return Number.isNaN(date.getTime()) ? null : date;
        }

        const date = new Date(raw);
        return Number.isNaN(date.getTime()) ? null : date;
    }

    /**
     * Format currency amount for display.
     * Handles both API prices (in cents) and pricing config prices (in main currency units).
     *
     * @param amount - Price amount
     * @param currency - Currency code (EUR, USD)
     * @param isInCents - Whether the amount is in cents (true for API responses, false for pricing config). Defaults to true.
     * @returns Formatted currency string (e.g., "€20.00" or "$30.00")
     */
    function formatCurrency(amount: number, currency: string, isInCents: boolean = true): string {
        const symbols: Record<string, string> = {
            'EUR': '€',
            'USD': '$',
        };
        const symbol = symbols[currency.toUpperCase()] || currency.toUpperCase();

        // EUR/USD: convert from cents to main currency unit if needed, then format with 2 decimal places
        const mainCurrencyAmount = isInCents ? amount / 100 : amount;
        return `${symbol}${mainCurrencyAmount.toFixed(2)}`;
    }

    // Get available subscription tiers (tiers with bonus credits > 0).
    // Bank-transfer-only tiers (SEPA) are excluded — subscriptions require recurring card payments.
    function getAvailableSubscriptionTiers() {
        return pricingTiers.filter(
            tier => (tier.monthly_auto_top_up_extra_credits || 0) > 0 && !tier.bank_transfer_only
        );
    }

    // Get price for a tier in selected currency
    function getTierPrice(tier: import('../../../../../config/pricing').PricingTier): number {
        const currencyKey = selectedCurrency.toLowerCase() as 'eur' | 'usd';
        return tier.price[currencyKey];
    }

    // Fetch subscription details
    async function fetchSubscriptionDetails() {
        isLoading = true;

        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.getSubscription), {
                credentials: 'include'
            });

            if (response.ok) {
                const data = await response.json();
                subscriptionDetails = data?.subscription ?? null;
                hasSubscription = Boolean(data?.has_subscription && subscriptionDetails);
                hasActiveSubscription = Boolean(hasSubscription && isActiveLikeSubscription(subscriptionDetails?.status));
                // Set billing preference from API response
                billingDayPreference = subscriptionDetails?.billing_day_preference || 'anniversary';
            } else if (response.status === 404) {
                // No subscription found
                hasSubscription = false;
                hasActiveSubscription = false;
                subscriptionDetails = null;
            } else {
                throw new Error('Failed to fetch subscription details');
            }
        } catch (error) {
                console.error('Error fetching subscription:', error);
                hasSubscription = false;
                hasActiveSubscription = false;
                subscriptionDetails = null;
            } finally {
                isLoading = false;
            }
    }

    // Check if user has payment method
    async function checkPaymentMethod() {
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.hasPaymentMethod), {
                credentials: 'include'
            });

            if (response.ok) {
                const data = await response.json();
                hasPaymentMethod = data.has_payment_method || false;
            } else {
                hasPaymentMethod = false;
            }
        } catch (error) {
            console.error('Error checking payment method:', error);
            hasPaymentMethod = false;
        }
    }

    // Create subscription
    async function createSubscription() {
        if (!selectedTierCredits || !selectedTier) {
            alert('Please select a subscription tier');
            return;
        }

        isCreating = true;

        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.createSubscription), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    credits_amount: selectedTierCredits,
                    currency: selectedCurrency.toLowerCase(),
                    billing_day_preference: billingDayPreference
                })
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Failed to create subscription');
            }

            // Refresh subscription details
            await fetchSubscriptionDetails();
            showCreateForm = false;
            alert('Monthly auto top-up subscription created successfully!');
        } catch (error) {
            console.error('Error creating subscription:', error);
            alert(error instanceof Error ? error.message : 'Failed to create subscription. Please try again.');
        } finally {
            isCreating = false;
        }
    }

    // Update billing day preference
    async function updateBillingDayPreference(newPreference: string) {
        isUpdatingBillingDay = true;

        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.updateBillingDayPreference), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    billing_day_preference: newPreference
                })
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Failed to update billing day preference');
            }

            const _result = await response.json();

            // Update local state
            billingDayPreference = newPreference;

            // Refresh subscription details to get updated next billing date
            await fetchSubscriptionDetails();

            alert('Billing day preference updated successfully!');
        } catch (error) {
            console.error('Error updating billing day preference:', error);
            alert(error instanceof Error ? error.message : 'Failed to update billing day preference. Please try again.');
        } finally {
            isUpdatingBillingDay = false;
        }
    }

    // Cancel subscription
    async function cancelSubscription() {
        if (!confirm('Are you sure you want to cancel your monthly auto top-up subscription?')) {
            return;
        }

        isLoading = true;

        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.cancelSubscription), {
                method: 'POST',
                credentials: 'include'
            });

            if (!response.ok) {
                throw new Error('Failed to cancel subscription');
            }

            await fetchSubscriptionDetails();
            alert('Subscription cancelled successfully');
        } catch (error) {
            console.error('Error cancelling subscription:', error);
            alert('Failed to cancel subscription. Please try again.');
        } finally {
            isLoading = false;
        }
    }

    // Get selected tier object
    let selectedTier = $derived(
        selectedTierCredits 
            ? getAvailableSubscriptionTiers().find(t => t.credits === selectedTierCredits) || null
            : null
    );

    // Initialize selected tier when form is shown
    function showCreateSubscriptionForm() {
        const availableTiers = getAvailableSubscriptionTiers();
        if (availableTiers.length > 0) {
            selectedTierCredits = availableTiers[0].credits; // Default to first available tier
        }
        showCreateForm = true;
    }

    onMount(() => {
        fetchSubscriptionDetails();
        checkPaymentMethod();
    });

    let nextChargeDate = $derived(parseNextChargeDate(subscriptionDetails));

    // Dropdown option arrays for SettingsDropdown
    let tierOptions = $derived(
        getAvailableSubscriptionTiers().map(tier => ({
            value: String(tier.credits),
            label: (() => {
                const bonus = tier.monthly_auto_top_up_extra_credits > 0
                    ? ` (+ ${formatCredits(tier.monthly_auto_top_up_extra_credits)} bonus)`
                    : '';
                return `${formatCredits(tier.credits)} credits${bonus} - ${formatCurrency(getTierPrice(tier), selectedCurrency, false)}/month`;
            })()
        }))
    );

    const currencyOptions = [
        { value: 'EUR', label: 'EUR (€)' },
        { value: 'USD', label: 'USD ($)' },
    ];

    const billingDayOptions = [
        { value: 'anniversary', label: 'Monthly (30 days from activation)' },
        { value: 'first_of_month', label: '1st of each month' },
    ];

    const billingDayCreateOptions = [
        { value: 'anniversary', label: 'Monthly (30 days from now)' },
        { value: 'first_of_month', label: '1st of each month' },
    ];

    let selectedTierCreditsStr = $derived(selectedTierCredits !== null ? String(selectedTierCredits) : '');
</script>

<div class="monthly-container">
    {#if isLoading}
        <p class="info-text">Loading...</p>
    {:else if hasSubscription && subscriptionDetails}
        <!-- Subscription View -->
        <div class="subscription-info">
            <div class="info-row">
                <span class="info-label">{$text('common.status')}:</span>
                <span class="status-badge {hasActiveSubscription ? 'active' : 'inactive'}">
                    {subscriptionDetails.status || 'unknown'}
                </span>
            </div>
            <div class="info-row">
                <span class="info-label">{$text('settings.billing.amount')}:</span>
                <span class="info-value">
                    <span class="coin-icon-small"></span>
                    {formatCredits(subscriptionDetails.credits_amount || 0)} credits/month
                </span>
            </div>
            {#if subscriptionDetails.bonus_credits > 0}
                <div class="info-row">
                    <span class="info-label">Bonus credits:</span>
                    <span class="info-value">
                        <span class="coin-icon-small"></span>
                        {formatCredits(subscriptionDetails.bonus_credits)} credits/month
                    </span>
                </div>
            {/if}
            <div class="info-row">
                <span class="info-label">{$text('settings.billing.price')}:</span>
                <span class="info-value">
                    {formatCurrency(subscriptionDetails.price || 0, subscriptionDetails.currency || 'EUR')}/month
                </span>
            </div>
            <div class="info-row">
                <span class="info-label">{$text('settings.billing.next_charge')}:</span>
                <span class="info-value">{nextChargeDate ? nextChargeDate.toLocaleDateString() : '—'}</span>
            </div>
            <div class="info-row">
                <span class="info-label">Billing day:</span>
                <span class="info-value">
                    {billingDayPreference === 'first_of_month' ? '1st of each month' : 'Monthly (anniversary)'}
                </span>
            </div>
        </div>

        <!-- Billing day preference selector -->
        <div class="billing-day-section">
            <SettingsSectionHeading title="Change Billing Day" icon="calendar" />
            <SettingsDropdown
                bind:value={billingDayPreference}
                options={billingDayOptions}
                disabled={isUpdatingBillingDay}
                onChange={() => updateBillingDayPreference(billingDayPreference)}
            />
            <p class="help-text-small">
                {billingDayPreference === 'first_of_month'
                    ? 'You will be charged on the 1st of each month'
                    : 'You will be charged every 30 days from your subscription activation date'}
            </p>
        </div>

        <div class="button-group">
            <button class="danger-button" onclick={cancelSubscription} disabled={isLoading}>
                {$text('settings.billing.cancel')}
            </button>
        </div>
    {:else if showCreateForm}
        <!-- Create Subscription Form -->
        <div class="create-form">
            <h3 class="form-title">Create Monthly Auto Top-Up</h3>
            
            {#if !hasPaymentMethod}
                <div class="info-box warning">
                    <div class="warning-icon-small"></div>
                    <span>No payment method saved. Please make a purchase first to save your payment method.</span>
                </div>
            {:else}
                <!-- Tier Selection -->
                <div class="form-group">
                    <label for="tier">Select Subscription Tier</label>
                    <SettingsDropdown
                        value={selectedTierCreditsStr}
                        options={tierOptions}
                        disabled={isCreating}
                        onChange={(v) => { selectedTierCredits = parseInt(v, 10); }}
                    />
                    {#if selectedTier && selectedTier.monthly_auto_top_up_extra_credits > 0}
                        <p class="help-text">
                            You'll receive {formatCredits(selectedTier.credits)} base credits 
                            + {formatCredits(selectedTier.monthly_auto_top_up_extra_credits)} bonus credits 
                            = {formatCredits(selectedTier.credits + selectedTier.monthly_auto_top_up_extra_credits)} total credits per month
                        </p>
                    {/if}
                </div>

                <!-- Currency Selection -->
                <div class="form-group">
                    <label for="currency">Currency</label>
                    <SettingsDropdown
                        bind:value={selectedCurrency}
                        options={currencyOptions}
                        disabled={isCreating}
                    />
                </div>

                <!-- Billing Day Preference -->
                <div class="form-group">
                    <label for="billingDayCreate">Billing Day</label>
                    <SettingsDropdown
                        bind:value={billingDayPreference}
                        options={billingDayCreateOptions}
                        disabled={isCreating}
                    />
                    <p class="help-text">
                        {billingDayPreference === 'first_of_month'
                            ? 'You will be charged on the 1st of each month'
                            : 'You will be charged every 30 days starting from today'}
                    </p>
                </div>

                <div class="button-group">
                    <button class="primary-button" onclick={createSubscription} disabled={isCreating || !selectedTier}>
                        {isCreating ? 'Creating...' : 'Create Subscription'}
                    </button>
                    <button class="secondary-button" onclick={() => showCreateForm = false} disabled={isCreating}>
                        Cancel
                    </button>
                </div>
            {/if}
        </div>
    {:else}
        <!-- No Subscription - Show Create Option -->
        <p class="info-text">
            {$text('settings.billing.no_subscription')}
        </p>
        {#if hasPaymentMethod}
            <button class="primary-button" onclick={showCreateSubscriptionForm}>
                Create Monthly Auto Top-Up
            </button>
        {:else}
            <div class="info-box warning">
                <div class="warning-icon-small"></div>
                <span>No payment method saved. Please make a purchase first to save your payment method.</span>
            </div>
        {/if}
    {/if}
</div>

<style>
    .monthly-container {
        padding: 0 10px;
        display: flex;
        flex-direction: column;
        gap: var(--spacing-8);
    }

    /* Subscription Info */
    .subscription-info {
        display: flex;
        flex-direction: column;
        gap: var(--spacing-6);
        padding: var(--spacing-6);
        background: var(--color-grey-10);
        border-radius: var(--radius-3);
    }

    .info-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    .info-label {
        color: var(--color-grey-60);
        font-size: var(--font-size-small);
    }

    .info-value {
        color: var(--color-grey-100);
        font-size: var(--font-size-small);
        font-weight: 500;
        display: flex;
        align-items: center;
        gap: var(--spacing-2);
    }

    .info-text {
        color: var(--color-grey-60);
        font-size: var(--font-size-small);
        padding: 0;
        margin: 0 0 8px 0;
    }

    .status-badge {
        padding: var(--spacing-2) var(--spacing-6);
        border-radius: var(--radius-5);
        font-size: var(--font-size-xxs);
        font-weight: 600;
    }

	    .status-badge.active {
	        background: rgba(88, 188, 0, 0.2);
	        color: #58BC00;
	    }
	
	    .status-badge.inactive {
	        background: rgba(255, 165, 0, 0.18);
	        color: #FFA500;
	    }

    /* Icon */
    .coin-icon-small {
        display: inline-block;
        width: 14px;
        height: 14px;
        background-image: url('@openmates/ui/static/icons/coins.svg');
        background-size: contain;
        background-repeat: no-repeat;
        filter: invert(1);
        vertical-align: middle;
    }

    .warning-icon-small {
        width: 16px;
        height: 16px;
        background-color: #FFA500;
        mask-image: url('@openmates/ui/static/icons/warning.svg');
        mask-size: contain;
        mask-repeat: no-repeat;
        flex-shrink: 0;
    }

    /* Buttons */
    .button-group {
        display: flex;
        gap: var(--spacing-4);
        margin-top: var(--spacing-4);
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

    .secondary-button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .danger-button {
        padding: var(--spacing-5) var(--spacing-8);
        border-radius: var(--radius-3);
        font-size: var(--font-size-small);
        font-weight: 500;
        cursor: pointer;
        transition: all var(--duration-normal) var(--easing-default);
        border: none;
        background: rgba(223, 27, 65, 0.1);
        color: #df1b41;
    }

    .danger-button:hover:not(:disabled) {
        background: rgba(223, 27, 65, 0.2);
    }

    .danger-button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    /* Create Form */
    .create-form {
        display: flex;
        flex-direction: column;
        gap: var(--spacing-8);
        padding: var(--spacing-6);
        background: var(--color-grey-10);
        border-radius: var(--radius-3);
    }

    .form-title {
        color: var(--color-grey-100);
        font-size: var(--font-size-h3-mobile);
        font-weight: 600;
        margin: 0 0 8px 0;
    }

    .form-group {
        display: flex;
        flex-direction: column;
        gap: var(--spacing-4);
    }

    .form-group label {
        color: var(--color-grey-100);
        font-size: var(--font-size-small);
        font-weight: 500;
    }

    .help-text {
        color: var(--color-grey-60);
        font-size: var(--font-size-xxs);
        margin: 0;
        line-height: 1.4;
    }

    .help-text-small {
        color: var(--color-grey-60);
        font-size: var(--font-size-tiny);
        margin: 4px 0 0 0;
        line-height: 1.3;
    }

    /* Billing Day Section */
    .billing-day-section {
        display: flex;
        flex-direction: column;
        gap: var(--spacing-4);
        padding: var(--spacing-6);
        background: var(--color-grey-10);
        border-radius: var(--radius-3);
        border: 1px solid var(--color-grey-20);
    }


    /* Info Boxes */
    .info-box {
        display: flex;
        align-items: center;
        gap: var(--spacing-5);
        padding: var(--spacing-6);
        border-radius: var(--radius-3);
        font-size: var(--font-size-xs);
    }

    .info-box.warning {
        background: rgba(255, 165, 0, 0.1);
        color: #FFA500;
        border: 1px solid rgba(255, 165, 0, 0.3);
    }

    /* Responsive Styles */
    @media (max-width: 768px) {
        .button-group {
            flex-direction: column;
        }

        .primary-button,
        .secondary-button,
        .danger-button {
            width: 100%;
        }

        .info-row {
            flex-direction: column;
            align-items: flex-start;
            gap: var(--spacing-3);
        }
    }

    @media (max-width: 480px) {
        .monthly-container {
            padding: 0 5px;
        }
    }
</style>
