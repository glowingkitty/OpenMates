<!--
Billing Settings - Credit purchases, subscription management, and auto top-up configuration
-->

<script lang="ts">
    import { onMount, createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { apiEndpoints, getApiEndpoint } from '../../config/api';
    import { userProfile } from '../../stores/userProfile';
    import SettingsItem from '../SettingsItem.svelte';
    import { SettingsSectionHeading } from './elements';
    import SettingsUsage from './SettingsUsage.svelte';

    const dispatch = createEventDispatcher();
    
    let errorMessage: string | null = $state(null);

    // Current user credits
    let currentCredits = $state(0);

    // Format credits with dots as thousand separators
    function formatCredits(credits: number): string {
        return credits.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    }

    // Load user profile data
    userProfile.subscribe(profile => {
        currentCredits = profile.credits || 0;
    });

    // Fetch subscription details (kept for future use — subscription display coming soon)
    async function fetchSubscriptionDetails() {
        errorMessage = null;

        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.getSubscription), {
                credentials: 'include'
            });

            if (!response.ok && response.status !== 404) {
                throw new Error('Failed to fetch subscription details');
            }
        } catch (error) {
            console.error('Error fetching subscription:', error);
            errorMessage = 'Failed to load subscription details';
        }
    }

    // Helper function to dispatch navigation events to parent
    function navigateToSubview(path: string) {
        // Convert path to translation key format (replace hyphens and slashes with underscores)
        const translationKey = path.replace(/[-/]/g, '_');

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
            title: $text(`settings.billing.${translationKey}`)
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
        <span class="balance-label">{$text('common.credits')}</span>
    </div>
</div>

<!-- Buy Credits Menu Item -->
<SettingsItem
    type="submenu"
    icon="subsetting_icon coins"
    title={$text('common.buy_credits')}
    onClick={() => navigateToSubview('buy-credits')}
/>

<!-- Auto Top-up Menu Item -->
<SettingsItem
    type="submenu"
    icon="subsetting_icon reload"
    title={$text('settings.billing.auto_topup')}
    onClick={() => navigateToSubview('auto-topup')}
/>

<!-- Invoices Menu Item -->
<SettingsItem
    type="submenu"
    icon="subsetting_icon document"
    title={$text('common.invoices')}
    onClick={() => navigateToSubview('invoices')}
/>

<!-- Gift Cards Menu Item -->
<SettingsItem
    type="submenu"
    icon="subsetting_icon icon_gift"
    title={$text('common.gift_cards')}
    onClick={() => dispatch('openSettings', {
        settingsPath: 'billing/gift-cards',
        direction: 'forward',
        icon: 'icon_gift',
        title: $text('common.gift_cards')
    })}
/>

<!-- Divider before Usage -->
<div class="section-divider"></div>

<!-- Usage Section -->
<SettingsSectionHeading title={$text('settings.usage')} icon="usage" />
<SettingsUsage
    on:chatSelected={(e) => dispatch('chatSelected', e.detail)}
    on:closeSettings={() => dispatch('closeSettings')}
/>

{#if errorMessage}
    <div class="settings-error">{errorMessage}</div>
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
        padding: var(--spacing-5);
        margin-bottom: var(--spacing-4);
    }

    .balance-display {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: var(--spacing-5);
        padding: var(--spacing-10);
        background: var(--color-grey-10);
        border-radius: var(--radius-5);
        box-shadow: var(--shadow-xs);
    }

    .balance-amount {
        color: var(--color-grey-100);
        font-size: var(--font-size-xxl);
        font-weight: 600;
    }

    .balance-label {
        color: var(--color-grey-60);
        font-size: var(--font-size-small);
    }

    /* Icons - restored original styling */
    .coin-icon {
        width: 28px;
        height: 28px;
        -webkit-mask-image: url('@openmates/ui/static/icons/coins.svg');
        -webkit-mask-size: contain;
        -webkit-mask-repeat: no-repeat;
        mask-image: url('@openmates/ui/static/icons/coins.svg');
        mask-size: contain;
        mask-repeat: no-repeat;
        background-color: var(--color-grey-90);
    }

    /* Divider between billing items and usage section */
    .section-divider {
        height: 1px;
        background: var(--color-grey-25);
        margin: var(--spacing-6) var(--spacing-5);
    }

    /* Error uses global .settings-error from settings.css */

    /* Responsive Styles */
    @media (max-width: 768px) {
        .balance-display {
            padding: var(--spacing-8);
        }

        .balance-amount {
            font-size: var(--font-size-h2-mobile);
        }
    }

    @media (max-width: 480px) {
        .balance-amount {
            font-size: var(--font-size-xl);
        }

        .coin-icon {
            width: 24px;
            height: 24px;
        }
    }
</style>
