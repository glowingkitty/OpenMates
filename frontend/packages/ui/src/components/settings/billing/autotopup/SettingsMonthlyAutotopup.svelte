<!--
Monthly Auto Top-Up Subscription - View and manage monthly subscription
Allows creating new subscriptions if user has a saved payment method
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { apiEndpoints, getApiEndpoint } from '../../../../config/api';
    import { pricingTiers } from '../../../../config/pricing';
    import Toggle from '../../../Toggle.svelte';

    let isLoading = $state(false);
    let hasActiveSubscription = $state(false);
    let subscriptionDetails: any = $state(null);
    let hasPaymentMethod = $state(false);
    let showCreateForm = $state(false);
    
    // Create subscription form state
    let selectedTierCredits = $state<number | null>(null);
    let selectedCurrency = $state('EUR');
    let isCreating = $state(false);

    // Format credits with dots as thousand separators
    function formatCredits(credits: number): string {
        return credits.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    }

    /**
     * Format currency amount for display.
     * Handles both API prices (in cents) and pricing config prices (in main currency units).
     * 
     * @param amount - Price amount
     * @param currency - Currency code (EUR, USD, JPY)
     * @param isInCents - Whether the amount is in cents (true for API responses, false for pricing config). Defaults to true.
     * @returns Formatted currency string (e.g., "€20.00" or "¥4000")
     */
    function formatCurrency(amount: number, currency: string, isInCents: boolean = true): string {
        const symbols: Record<string, string> = {
            'EUR': '€',
            'USD': '$',
            'JPY': '¥'
        };
        const symbol = symbols[currency.toUpperCase()] || '€';
        const currencyUpper = currency.toUpperCase();
        
        // JPY doesn't use decimal places - use amount as-is
        if (currencyUpper === 'JPY') {
            return `${symbol}${amount.toLocaleString('en-US')}`;
        }
        
        // EUR/USD: convert from cents to main currency unit if needed, then format with 2 decimal places
        const mainCurrencyAmount = isInCents ? amount / 100 : amount;
        return `${symbol}${mainCurrencyAmount.toFixed(2)}`;
    }

    // Get available subscription tiers (tiers with bonus credits > 0)
    function getAvailableSubscriptionTiers() {
        return pricingTiers.filter(tier => (tier.monthly_auto_top_up_extra_credits || 0) > 0);
    }

    // Get price for a tier in selected currency
    function getTierPrice(tier: any): number {
        const currencyKey = selectedCurrency.toLowerCase() as 'eur' | 'usd' | 'jpy';
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
                subscriptionDetails = data;
                hasActiveSubscription = data.status === 'active';
            } else if (response.status === 404) {
                // No subscription found
                hasActiveSubscription = false;
                subscriptionDetails = null;
            } else {
                throw new Error('Failed to fetch subscription details');
            }
        } catch (error) {
            console.error('Error fetching subscription:', error);
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
                    currency: selectedCurrency.toLowerCase()
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
</script>

<div class="monthly-container">
    {#if isLoading}
        <p class="info-text">Loading...</p>
    {:else if hasActiveSubscription && subscriptionDetails}
        <!-- Active Subscription View -->
        <div class="subscription-info">
            <div class="info-row">
                <span class="info-label">{$text('settings.billing.status.text')}:</span>
                <span class="status-badge active">Active</span>
            </div>
            <div class="info-row">
                <span class="info-label">{$text('settings.billing.amount.text')}:</span>
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
                <span class="info-label">{$text('settings.billing.price.text')}:</span>
                <span class="info-value">
                    {formatCurrency(subscriptionDetails.price || 0, subscriptionDetails.currency || 'EUR')}/month
                </span>
            </div>
            {#if subscriptionDetails.next_billing_date}
                <div class="info-row">
                    <span class="info-label">{$text('settings.billing.next_charge.text')}:</span>
                    <span class="info-value">{new Date(subscriptionDetails.next_billing_date).toLocaleDateString()}</span>
                </div>
            {/if}
        </div>
        <div class="button-group">
            <button class="danger-button" onclick={cancelSubscription} disabled={isLoading}>
                {$text('settings.billing.cancel.text')}
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
                    <select id="tier" bind:value={selectedTierCredits} disabled={isCreating}>
                        {#each getAvailableSubscriptionTiers() as tier}
                            <option value={tier.credits}>
                                {formatCredits(tier.credits)} credits
                                {#if tier.monthly_auto_top_up_extra_credits > 0}
                                    (+ {formatCredits(tier.monthly_auto_top_up_extra_credits)} bonus)
                                {/if}
                                - {formatCurrency(getTierPrice(tier), selectedCurrency, false)}/month
                            </option>
                        {/each}
                    </select>
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
                    <select id="currency" bind:value={selectedCurrency} disabled={isCreating}>
                        <option value="EUR">EUR (€)</option>
                        <option value="USD">USD ($)</option>
                        <option value="JPY">JPY (¥)</option>
                    </select>
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
            {$text('settings.billing.no_subscription.text')}
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
        gap: 16px;
    }

    /* Subscription Info */
    .subscription-info {
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding: 12px;
        background: var(--color-grey-10);
        border-radius: 8px;
    }

    .info-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    .info-label {
        color: var(--color-grey-60);
        font-size: 14px;
    }

    .info-value {
        color: var(--color-grey-100);
        font-size: 14px;
        font-weight: 500;
        display: flex;
        align-items: center;
        gap: 4px;
    }

    .info-text {
        color: var(--color-grey-60);
        font-size: 14px;
        padding: 0;
        margin: 0 0 8px 0;
    }

    .status-badge {
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 600;
    }

    .status-badge.active {
        background: rgba(88, 188, 0, 0.2);
        color: #58BC00;
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
        gap: 8px;
        margin-top: 8px;
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

    .secondary-button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .danger-button {
        padding: 10px 16px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
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
        gap: 16px;
        padding: 12px;
        background: var(--color-grey-10);
        border-radius: 8px;
    }

    .form-title {
        color: var(--color-grey-100);
        font-size: 18px;
        font-weight: 600;
        margin: 0 0 8px 0;
    }

    .form-group {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .form-group label {
        color: var(--color-grey-100);
        font-size: 14px;
        font-weight: 500;
    }

    .form-group select {
        background: var(--color-grey-10);
        border: 1px solid var(--color-grey-30);
        border-radius: 8px;
        color: var(--color-grey-100);
        padding: 10px 12px;
        font-size: 14px;
        cursor: pointer;
        transition: border-color 0.2s ease;
    }

    .form-group select:focus {
        outline: none;
        border-color: var(--color-primary);
    }

    .form-group select:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .help-text {
        color: var(--color-grey-60);
        font-size: 12px;
        margin: 0;
        line-height: 1.4;
    }

    /* Info Boxes */
    .info-box {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 12px;
        border-radius: 8px;
        font-size: 13px;
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
            gap: 6px;
        }
    }

    @media (max-width: 480px) {
        .monthly-container {
            padding: 0 5px;
        }
    }
</style>
