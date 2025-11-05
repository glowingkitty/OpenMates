<!--
Monthly Auto Top-Up Subscription - View and manage monthly subscription
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { apiEndpoints, getApiEndpoint } from '../../../../config/api';

    let isLoading = $state(false);
    let hasActiveSubscription = $state(false);
    let subscriptionDetails: any = $state(null);

    // Format credits with dots as thousand separators
    function formatCredits(credits: number): string {
        return credits.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    }

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
        } finally {
            isLoading = false;
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

    onMount(() => {
        fetchSubscriptionDetails();
    });
</script>

<div class="monthly-container">
    {#if isLoading}
        <p class="info-text">Loading...</p>
    {:else if hasActiveSubscription && subscriptionDetails}
        <div class="subscription-info">
            <div class="info-row">
                <span class="info-label">{$text('settings.billing.status.text')}:</span>
                <span class="status-badge active">Active</span>
            </div>
            <div class="info-row">
                <span class="info-label">{$text('settings.billing.amount.text')}:</span>
                <span class="info-value">
                    <span class="coin-icon-small"></span>
                    {formatCredits(subscriptionDetails.credits || 0)} credits/month
                </span>
            </div>
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
            <button class="danger-button" onclick={cancelSubscription}>
                {$text('settings.billing.cancel.text')}
            </button>
        </div>
    {:else}
        <p class="info-text">
            {$text('settings.billing.no_subscription.text')}
        </p>
        <p class="info-text">
            {$text('settings.billing.subscription_coming_soon.text')}
        </p>
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

    /* Buttons */
    .button-group {
        display: flex;
        gap: 8px;
        margin-top: 8px;
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

    .danger-button:hover {
        background: rgba(223, 27, 65, 0.2);
    }

    /* Responsive Styles */
    @media (max-width: 768px) {
        .button-group {
            flex-direction: column;
        }

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

