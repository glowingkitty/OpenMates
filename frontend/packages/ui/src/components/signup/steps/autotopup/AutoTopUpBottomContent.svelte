<!--
Auto Top-Up Bottom Content - Two separate toggles for low balance and monthly auto top-up
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { pricingTiers } from '../../../../config/pricing';
    import Toggle from '../../../Toggle.svelte';
    import { createEventDispatcher } from 'svelte';

    const dispatch = createEventDispatcher();

    // Use Svelte 5 runes for props
    let {
        purchasedCredits = 0,
        purchasedPrice = 0,
        currency = 'eur',
        oncomplete,
        'onactivate-subscription': onactivateSubscription
    }: {
        purchasedCredits?: number;
        purchasedPrice?: number;
        currency?: string;
        oncomplete?: (event: CustomEvent) => void;
        'onactivate-subscription'?: (event: CustomEvent) => void;
    } = $props();

    // State for toggles - both off by default
    let lowBalanceEnabled = $state(false);
    let monthlyEnabled = $state(false);
    let isProcessing = $state(false);

    // Determine suggested tier based on purchased credits
    // If user bought 1,000 credits -> suggest 10,000 tier
    // Otherwise suggest the same tier they purchased
    function getSuggestedTier() {
        // If purchased 1,000 credits, suggest 10,000 tier
        if (purchasedCredits === 1000) {
            return pricingTiers.find(tier => tier.credits === 10000) || pricingTiers[1];
        }

        // Otherwise find matching tier
        const matchingTier = pricingTiers.find(tier => tier.credits === purchasedCredits);

        // If no matching tier found (shouldn't happen), default to recommended or first with bonus
        if (!matchingTier) {
            const recommended = pricingTiers.find(tier => tier.recommended);
            if (recommended) return recommended;
            return pricingTiers.find(tier => tier.monthly_auto_top_up_extra_credits) || pricingTiers[1];
        }

        return matchingTier;
    }

    const suggestedTier = getSuggestedTier();
    const baseCredits = suggestedTier.credits;
    const bonusCredits = suggestedTier.monthly_auto_top_up_extra_credits || 0;
    const totalCredits = baseCredits + bonusCredits;
    const monthlyPrice = suggestedTier.price[currency.toLowerCase() as 'eur' | 'usd' | 'jpy'];
    
    // Low balance settings - use purchased credits as default amount
    const lowBalanceAmount = purchasedCredits;
    const lowBalancePrice = purchasedPrice;
    // Fixed threshold: always 100 credits (cannot be changed to simplify setup)
    const lowBalanceThreshold = 100;

    // Format currency symbol
    function getCurrencySymbol(curr: string): string {
        switch (curr.toLowerCase()) {
            case 'eur': return '€';
            case 'usd': return '$';
            case 'jpy': return '¥';
            default: return '€';
        }
    }

    // Format price based on currency
    function formatPrice(price: number, curr: string): string {
        const symbol = getCurrencySymbol(curr);
        if (curr.toLowerCase() === 'jpy') {
            return `${symbol}${price}`;
        }
        return `${symbol}${price}`;
    }

    // Format credits with European style (dots as thousand separators)
    function formatCredits(credits: number): string {
        return credits.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    }

    // Handle finish button
    async function handleFinish() {
        isProcessing = true;

        try {
            // If monthly auto top-up is enabled, activate subscription
            if (monthlyEnabled) {
                if (onactivateSubscription) {
                    onactivateSubscription(new CustomEvent('activate-subscription', {
                        detail: {
                            credits: baseCredits,
                            bonusCredits: bonusCredits,
                            price: monthlyPrice,
                            currency: currency
                        }
                    }));
                }
            }

            // If low balance is enabled, save settings (will be handled by backend in future)
            // For now, just complete the signup
            if (oncomplete) {
                oncomplete(new CustomEvent('complete', {
                    detail: {
                        lowBalanceEnabled: lowBalanceEnabled,
                        monthlyEnabled: monthlyEnabled
                    }
                }));
            }
        } catch (error) {
            console.error('Error finishing setup:', error);
            isProcessing = false;
        }
    }
</script>

<div class="container">
    <div class="content">
        <div class="intro-text">
            {@html $text('signup.auto_topup_benefits.text')}
        </div>

        <!-- Low Balance Auto Top-Up Toggle -->
        <div class="toggle-option">
            <div class="confirmation-row">
                <Toggle bind:checked={lowBalanceEnabled} id="low-balance-toggle" disabled={isProcessing} />
                <label for="low-balance-toggle" class="confirmation-text">
                    {$text('settings.billing.on_low_balance.text')}
                </label>
            </div>
            {#if lowBalanceEnabled}
                <div class="option-description">
                    Once credits below {formatCredits(lowBalanceThreshold)}: {formatCredits(lowBalanceAmount)} credits for {formatPrice(lowBalancePrice, currency)}.
                </div>
            {/if}
        </div>

        <!-- Monthly Auto Top-Up Toggle -->
        <div class="toggle-option">
            <div class="confirmation-row">
                <Toggle bind:checked={monthlyEnabled} id="monthly-toggle" disabled={isProcessing} />
                <label for="monthly-toggle" class="confirmation-text">
                    {$text('settings.billing.monthly.text')}
                </label>
            </div>
            {#if monthlyEnabled}
                <div class="option-description">
                    {formatCredits(totalCredits)} credits for {formatPrice(monthlyPrice, currency)}.
                    {#if bonusCredits > 0}
                        <span class="bonus-badge">
                            Incl. {formatCredits(bonusCredits)} free credits!
                        </span>
                    {/if}
                </div>
            {/if}
        </div>

        <div class="help-text">
            You can change these settings at any time.
        </div>

        <!-- Finish Button -->
        <button
            class="finish-button"
            onclick={handleFinish}
            disabled={isProcessing}
        >
            {#if isProcessing}
                {$text('signup.processing.text')}
            {:else}
                {$text('signup.finish_setup.text')}
            {/if}
        </button>
    </div>
</div>

<style>
    .container {
        width: 100%;
        height: 100%;
        display: flex;
        justify-content: center;
        padding: 24px;
        box-sizing: border-box;
        overflow-y: auto;
    }

    .content {
        width: 100%;
        max-width: 500px;
        display: flex;
        flex-direction: column;
        gap: 24px;
    }

    .intro-text {
        color: var(--color-grey-60);
        font-size: 14px;
        text-align: center;
        line-height: 1.5;
    }

    .toggle-option {
        background: rgba(255, 255, 255, 0.05);
        border-radius: 12px;
        padding: 20px;
        display: flex;
        flex-direction: column;
        gap: 12px;
    }

    .confirmation-row {
        display: flex;
        align-items: center;
        gap: 12px;
        cursor: pointer;
    }

    .confirmation-text {
        color: var(--color-grey-60);
        font-size: 16px;
        text-align: left;
        flex: 1;
        display: flex;
        align-items: center;
        gap: 8px;
        cursor: pointer;
    }


    .option-description {
        color: var(--color-grey-70);
        font-size: 14px;
        line-height: 1.5;
        padding-left: 44px;
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .bonus-badge {
        background: var(--color-primary);
        color: white;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 12px;
        font-weight: 600;
        display: inline-block;
        margin-top: 4px;
        align-self: flex-start;
    }

    .help-text {
        color: var(--color-grey-50);
        font-size: 14px;
        text-align: center;
        margin-top: 8px;
    }

    .finish-button {
        width: 100%;
        padding: 14px 24px;
        border-radius: 8px;
        font-size: 16px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
        border: none;
        background: #58BC00;
        color: white;
        margin-top: auto;
    }

    .finish-button:hover:not(:disabled) {
        background: #6BD100;
        transform: translateY(-1px);
    }

    .finish-button:disabled {
        background: rgba(88, 188, 0, 0.5);
        cursor: not-allowed;
    }
</style>
