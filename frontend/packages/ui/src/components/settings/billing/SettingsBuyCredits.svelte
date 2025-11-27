<!--
Buy Credits - Credit tier selection
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { pricingTiers } from '../../../config/pricing';
    import SettingsItem from '../../SettingsItem.svelte';
    import { selectedTierStore } from './SettingsBuyCreditsPayment.svelte';
    import GiftCardRedeem from './GiftCardRedeem.svelte';

    const dispatch = createEventDispatcher();

    let selectedCurrency = $state('EUR');
    let showGiftCardInput = $state(false);

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
            title: `${formatCredits(tier.credits)} ${$text('settings.billing.credits.text')}`
        });
    }

    // Handle gift card redemption success
    function handleGiftCardRedeemed() {
        // Navigate to confirmation screen
        dispatch('openSettings', {
            settingsPath: 'billing/buy-credits/confirmation',
            direction: 'forward',
            icon: 'check',
            title: $text('settings.billing.purchase_successful.text')
        });
    }

    // Cancel gift card input and return to credit selection
    function cancelGiftCard() {
        showGiftCardInput = false;
    }
</script>

<div class="buy-credits-container">
    {#if showGiftCardInput}
        <!-- Gift Card Redemption Form -->
        <GiftCardRedeem
            on:redeemed={handleGiftCardRedeemed}
            on:cancel={cancelGiftCard}
        />
    {:else}
        <!-- "I have a gift card" Button -->
        <SettingsItem
            type="submenu"
            icon="subsetting_icon subsetting_icon_coins"
            title={$text('settings.billing.gift_card.have_code.text')}
            onClick={() => showGiftCardInput = true}
        />
        
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
    {/if}
</div>

<style>
    .buy-credits-container {
        padding: 0 10px;
    }

    /* Responsive Styles */
    @media (max-width: 480px) {
        .buy-credits-container {
            padding: 0 5px;
        }
    }
</style>

