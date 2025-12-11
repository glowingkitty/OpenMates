<!--
Billing Settings - Credit purchases, subscription management, and auto top-up configuration
-->

<script lang="ts">
    import { onMount, createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { apiEndpoints, getApiEndpoint } from '../../config/api';
    import { userProfile } from '../../stores/userProfile';
    import SettingsItem from '../SettingsItem.svelte';

    const dispatch = createEventDispatcher();
    
    let isLoading = $state(false);
    let errorMessage: string | null = $state(null);

    // Current user credits
    let currentCredits = $state(0);

    // Subscription state
    let hasActiveSubscription = $state(false);
    let subscriptionDetails: any = $state(null);

    // Low balance auto top-up state
    let lowBalanceEnabled = $state(false);
    let lowBalanceThreshold = $state(1000);

    // Format credits with dots as thousand separators
    function formatCredits(credits: number): string {
        return credits.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    }

    // Load user profile data
    userProfile.subscribe(profile => {
        currentCredits = profile.credits || 0;

        // Load low balance settings from profile
        lowBalanceEnabled = profile.auto_topup_low_balance_enabled || false;
        lowBalanceThreshold = profile.auto_topup_low_balance_threshold || 1000;
    });

    // Fetch subscription details
    async function fetchSubscriptionDetails() {
        isLoading = true;
        errorMessage = null;

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
            errorMessage = 'Failed to load subscription details';
        } finally {
            isLoading = false;
        }
    }

    // Helper function to dispatch navigation events to parent
    function navigateToSubview(path: string) {
        // Convert path to translation key format (replace hyphens and slashes with underscores)
        const translationKey = path.replace(/[-\/]/g, '_');

        // Map path to icon name
        const iconMap: Record<string, string> = {
            'buy-credits': 'coins',
            'auto-topup': 'reload',
            'invoices': 'document'
        };
        const iconName = iconMap[path.split('/')[0]] || path.split('/')[0];

        dispatch('openSettings', {
            settingsPath: `billing/${path}`,
            direction: 'forward',
            icon: iconName,
            title: $text(`settings.billing.${translationKey}.text`)
        });
    }

    onMount(() => {
        fetchSubscriptionDetails();
    });
</script>

<!-- Current Balance Display -->
<div class="balance-info">
    <div class="balance-display">
        <span class="coin-icon"></span>
        <span class="balance-amount">{formatCredits(currentCredits)}</span>
        <span class="balance-label">{$text('settings.billing.credits.text')}</span>
    </div>
</div>

<!-- Buy Credits Menu Item -->
<SettingsItem
    type="submenu"
    icon="subsetting_icon subsetting_icon_coins"
    title={$text('settings.billing.buy_credits.text')}
    onClick={() => navigateToSubview('buy-credits')}
/>

<!-- Auto Top-up Menu Item -->
<SettingsItem
    type="submenu"
    icon="subsetting_icon subsetting_icon_reload"
    title={$text('settings.billing.auto_topup.text')}
    onClick={() => navigateToSubview('auto-topup')}
/>

<!-- Invoices Menu Item -->
<SettingsItem
    type="submenu"
    icon="subsetting_icon subsetting_icon_document"
    title={$text('settings.billing.invoices.text')}
    onClick={() => navigateToSubview('invoices')}
/>

{#if errorMessage}
    <div class="error-message">{errorMessage}</div>
{/if}
<!-- TODO: Create separate components for sub-views:
     - SettingsBillingBuyCredits.svelte
     - SettingsBillingAutoTopup.svelte  
     - SettingsBillingLowBalance.svelte
     - SettingsBillingMonthly.svelte
     
     These should be registered in Settings.svelte as:
     'billing/buy-credits': SettingsBillingBuyCredits,
     'billing/auto-topup': SettingsBillingAutoTopup,
     'billing/auto-topup/low-balance': SettingsBillingLowBalance,
     'billing/auto-topup/monthly': SettingsBillingMonthly,
-->

<style>
    /* Balance Info Section */
    .balance-info {
        padding: 10px;
        margin-bottom: 8px;
    }

    .balance-display {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 10px;
        padding: 20px;
        background: var(--color-grey-10);
        border-radius: 12px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }

    .balance-amount {
        color: var(--color-grey-100);
        font-size: 28px;
        font-weight: 600;
    }

    .balance-label {
        color: var(--color-grey-60);
        font-size: 14px;
    }

    /* Icons - restored original styling */
    .coin-icon {
        width: 28px;
        height: 28px;
        background-image: url('@openmates/ui/static/icons/coins.svg');
        background-size: contain;
        background-repeat: no-repeat;
        filter: invert(1);
    }

    /* Error Message */
    .error-message {
        background: rgba(223, 27, 65, 0.1);
        color: #df1b41;
        padding: 12px;
        border-radius: 8px;
        font-size: 13px;
        border: 1px solid rgba(223, 27, 65, 0.3);
        margin-top: 8px;
    }

    /* Responsive Styles */
    @media (max-width: 768px) {
        .balance-display {
            padding: 16px;
        }

        .balance-amount {
            font-size: 24px;
        }
    }

    @media (max-width: 480px) {
        .balance-amount {
            font-size: 22px;
        }

        .coin-icon {
            width: 24px;
            height: 24px;
        }
    }
</style>
