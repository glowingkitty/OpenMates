<!--
Buy Credits - Credit tier selection
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { pricingTiers } from '../../../config/pricing';
    import SettingsItem from '../../SettingsItem.svelte';
    import { selectedTierStore } from './SettingsBuyCreditsPayment.svelte';

    const dispatch = createEventDispatcher();

    let selectedCurrency = $state('EUR');

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

    // Helper to get price for a tier in selected currency
    function getTierPrice(tier: any): number {
        const currencyKey = selectedCurrency.toLowerCase() as 'eur' | 'usd' | 'jpy';
        return tier.price[currencyKey];
    }

    // Navigate to payment view for a specific tier
    function selectCreditTier(tier: any) {
        const tierIndex = pricingTiers.indexOf(tier);
        // Store the selected tier index
        selectedTierStore.set(tierIndex);
        // Navigate to payment view
        dispatch('openSettings', {
            settingsPath: `billing/buy-credits/payment`,
            direction: 'forward',
            icon: 'coins',
            title: `${formatCredits(tier.credits)} ${$text('settings.billing.credits')}`
        });
    }
</script>

<!-- Credit Tier Selection as Menu Items -->
{#each pricingTiers as tier}
    <SettingsItem
        type="submenu"
        icon="subsetting_icon subsetting_icon_coins"
        title={formatCredits(tier.credits)}
        subtitle={formatCurrency(getTierPrice(tier), selectedCurrency)}
        onClick={() => selectCreditTier(tier)}
    />
{/each}

