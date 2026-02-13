<!--
Buy Gift Cards - Credit tier selection for purchasing gift cards
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { pricingTiers } from '../../../config/pricing';
    import SettingsItem from '../../SettingsItem.svelte';
    import { selectedGiftCardTierStore } from './SettingsGiftCardsBuyPayment.svelte';

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
    function selectGiftCardTier(tier: any) {
        const tierIndex = pricingTiers.indexOf(tier);
        // Store the selected tier index
        selectedGiftCardTierStore.set(tierIndex);
        // Navigate to payment view
        dispatch('openSettings', {
            settingsPath: `gift_cards/buy/payment`,
            direction: 'forward',
            icon: 'coins',
            title: `${formatCredits(tier.credits)} ${$text('settings.gift_cards.credits')}`
        });
    }
</script>

<div class="info-message">
    <p>{$text('settings.gift_cards.buy_info')}</p>
</div>

<!-- Credit Tier Selection as Menu Items -->
{#each pricingTiers as tier}
    <SettingsItem
        type="submenu"
        icon="subsetting_icon subsetting_icon_coins"
        title={formatCredits(tier.credits)}
        subtitle={formatCurrency(getTierPrice(tier), selectedCurrency)}
        onClick={() => selectGiftCardTier(tier)}
    />
{/each}

<style>
    .info-message {
        padding: 12px;
        margin-bottom: 8px;
        background: var(--color-grey-10);
        border-radius: 8px;
        color: var(--color-grey-60);
        font-size: 13px;
    }
</style>
