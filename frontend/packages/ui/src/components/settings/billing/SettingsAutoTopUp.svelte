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

    type SubscriptionDetails = {
        status?: string;
        credits_amount?: number | null;
        next_billing_date?: string | null;
    };

    // Subscription state
    let hasActiveSubscription = $state(false);
    let subscriptionDetails: SubscriptionDetails | null = $state(null);

    // Low balance settings from user profile
    let lowBalanceEnabled = $state(false);
    // Fixed threshold: always 100 credits (cannot be changed to simplify setup)
    const lowBalanceThreshold = 100;

    // Format credits with dots as thousand separators
    function formatCredits(credits: number): string {
        return credits.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    }

    function isActiveLikeSubscription(status?: string): boolean {
        const normalized = (status || '').toLowerCase();
        return normalized === 'active' || normalized === 'trialing';
    }

    function parseNextChargeDate(details: SubscriptionDetails | null): Date | null {
        const raw = details?.next_billing_date;
        if (!raw) return null;
        const date = new Date(raw);
        return Number.isNaN(date.getTime()) ? null : date;
    }

    let nextChargeDate = $derived(parseNextChargeDate(subscriptionDetails));

    // Load user profile data
    userProfile.subscribe(profile => {
        lowBalanceEnabled = profile.auto_topup_low_balance_enabled || false;
        // Threshold is fixed at 100 credits and cannot be changed
    });

    // Fetch subscription details
    async function fetchSubscriptionDetails() {
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.getSubscription), {
                credentials: 'include'
            });

            if (response.ok) {
                const data = await response.json();
                subscriptionDetails = data?.subscription ?? null;
                const hasSubscription = Boolean(data?.has_subscription && subscriptionDetails);
                hasActiveSubscription = Boolean(hasSubscription && isActiveLikeSubscription(subscriptionDetails?.status));
            } else if (response.status === 404) {
                // Endpoint not available (payments disabled) or legacy "no subscription" response
                subscriptionDetails = null;
                hasActiveSubscription = false;
            } else {
                subscriptionDetails = null;
                hasActiveSubscription = false;
            }
        } catch (error) {
            console.error('Error fetching subscription:', error);
            subscriptionDetails = null;
            hasActiveSubscription = false;
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
            title: $text(`settings.billing.${translationKey}`)
        });
    }

    onMount(() => {
        fetchSubscriptionDetails();
    });
</script>

<!-- On Low Balance Menu Item -->
<SettingsItem
    icon="subsetting_icon low_balance"
    title={$text('settings.billing.on_low_balance')}
    subtitle={lowBalanceEnabled 
        ? `${$text('settings.enabled')} - ${$text('settings.billing.threshold')}: ${formatCredits(lowBalanceThreshold)}`
        : $text('settings.disabled')}
    onClick={() => navigateToSubview('low-balance')}
/>

<!-- Monthly Subscription Menu Item -->
<SettingsItem
    icon="subsetting_icon calendar"
    title={$text('settings.billing.monthly')}
    subtitle={hasActiveSubscription && subscriptionDetails
        ? `${$text('settings.active')} - ${formatCredits(subscriptionDetails.credits_amount || 0)} ${$text('settings.billing.credits')}/month${nextChargeDate ? ` • ${$text('settings.billing.next_charge')}: ${nextChargeDate.toLocaleDateString()}` : ''}`
        : $text('settings.billing.no_subscription')}
    onClick={() => navigateToSubview('monthly')}
/>
