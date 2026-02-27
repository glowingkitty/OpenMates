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
        };
        const symbol = symbols[currency.toUpperCase()] || currency.toUpperCase();
        return `${symbol}${amount}`;
    }

    // Helper to get price for a tier in selected currency
    function getTierPrice(tier: any): number {
        const currencyKey = selectedCurrency.toLowerCase() as 'eur' | 'usd';
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

<!-- Explainer: why the user needs credits -->
<p class="credits-explainer">{$text('settings.billing.buy_credits_explainer')}</p>

<!-- Credit Tier Selection as Menu Items -->
{#each pricingTiers as tier}
    <SettingsItem
        type="submenu"
        icon="subsetting_icon coins"
        title={formatCredits(tier.credits)}
        subtitle={formatCurrency(getTierPrice(tier), selectedCurrency)}
        onClick={() => selectCreditTier(tier)}
    />
{/each}

<style>
    .credits-explainer {
        font-size: 0.85rem;
        color: var(--color-text-muted);
        padding: 12px 16px 4px;
        margin: 0;
        line-height: 1.4;
    }
</style>
