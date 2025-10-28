<!--
Auto Top-Up Settings - Submenu for low balance and monthly auto top-up options
-->

<script lang="ts">
    import { onMount, createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { apiEndpoints, getApiEndpoint } from '../../../config/api';
    import { userProfile } from '../../../stores/userProfile';
    import SettingsItem from '../../SettingsItem.svelte';

    const dispatch = createEventDispatcher();

    // Subscription state
    let hasActiveSubscription = $state(false);
    let subscriptionDetails: any = $state(null);
    let isLoading = $state(false);

    // Low balance settings from user profile
    let lowBalanceEnabled = $state(false);
    let lowBalanceThreshold = $state(1000);

    // Format credits with dots as thousand separators
    function formatCredits(credits: number): string {
        return credits.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    }

    // Load user profile data
    userProfile.subscribe(profile => {
        lowBalanceEnabled = profile.auto_topup_low_balance_enabled || false;
        lowBalanceThreshold = profile.auto_topup_low_balance_threshold || 1000;
    });

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
            }
        } catch (error) {
            console.error('Error fetching subscription:', error);
        } finally {
            isLoading = false;
        }
    }

    // Helper function to dispatch navigation events to parent
    function navigateToSubview(path: string) {
        // Convert path to translation key format (replace hyphens with underscores)
        const translationKey = path.replace(/-/g, '_');
        dispatch('openSettings', {
            settingsPath: `billing/auto-topup/${path}`,
            direction: 'forward',
            icon: path,
            title: $text(`settings.billing.${translationKey}.text`)
        });
    }

    onMount(() => {
        fetchSubscriptionDetails();
    });
</script>

<div class="auto-topup-container">
    <!-- On Low Balance Menu Item -->
    <SettingsItem
        icon="subsetting_icon subsetting_icon_low_balance"
        title={$text('settings.billing.on_low_balance.text')}
        subtitle={lowBalanceEnabled 
            ? `${$text('settings.enabled.text')} - ${$text('settings.billing.threshold.text')}: ${formatCredits(lowBalanceThreshold)}`
            : $text('settings.disabled.text')}
        onClick={() => navigateToSubview('low-balance')}
    />

    <!-- Monthly Subscription Menu Item -->
    <SettingsItem
        icon="subsetting_icon subsetting_icon_calendar"
        title={$text('settings.billing.monthly.text')}
        subtitle={hasActiveSubscription && subscriptionDetails
            ? `${$text('settings.active.text')} - ${formatCredits(subscriptionDetails.credits || 0)} ${$text('settings.billing.credits.text')}/month`
            : $text('settings.billing.no_subscription.text')}
        onClick={() => navigateToSubview('monthly')}
    />
</div>

<style>
    .auto-topup-container {
        padding: 0 10px;
    }

    @media (max-width: 480px) {
        .auto-topup-container {
            padding: 0 5px;
        }
    }
</style>

