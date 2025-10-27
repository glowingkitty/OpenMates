<!--
Auto Top-Up Bottom Content - Toggle and subscription activation
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { pricingTiers } from '../../../../config/pricing';

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

    // State for toggle
    let autoTopUpEnabled = $state(false);
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
    const bonusPercentage = bonusCredits > 0 ? Math.round((bonusCredits / baseCredits) * 100) : 0;

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

    // Handle skip button
    function handleSkip() {
        // Call completion callback to move to main app
        if (oncomplete) {
            oncomplete(new CustomEvent('complete', {
                detail: {
                    autoTopUpEnabled: false
                }
            }));
        }
    }

    // Handle activate button
    async function handleActivate() {
        if (!autoTopUpEnabled) {
            // User needs to toggle it on first
            return;
        }

        isProcessing = true;

        try {
            // Call subscription activation callback
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
        } catch (error) {
            console.error('Error activating auto top-up:', error);
            isProcessing = false;
        }
    }
</script>

<div class="container">
    <div class="content">
        <!-- Toggle Section -->
        <div class="toggle-section">
            <div class="toggle-header">
                <span class="toggle-label">{$text('signup.activate_monthly_auto_topup.text')}</span>
                <button
                    class="toggle {autoTopUpEnabled ? 'active' : ''}"
                    onclick={() => autoTopUpEnabled = !autoTopUpEnabled}
                    disabled={isProcessing}
                    aria-label={autoTopUpEnabled ? 'Disable monthly auto top-up' : 'Enable monthly auto top-up'}
                >
                    <div class="toggle-slider"></div>
                </button>
            </div>
        </div>

        {#if autoTopUpEnabled}
            <!-- Subscription Details -->
            <div class="subscription-details">
                <div class="credit-breakdown">
                    <div class="credit-item">
                        <span class="credit-label">{$text('signup.base_credits.text')}</span>
                        <span class="credit-value">
                            <span class="coin-icon-inline"></span>
                            {formatCredits(baseCredits)}
                        </span>
                    </div>
                    {#if bonusCredits > 0}
                        <div class="credit-item bonus">
                            <span class="credit-label">
                                {$text('signup.bonus_credits.text')}
                                <span class="bonus-badge">+{bonusPercentage}%</span>
                            </span>
                            <span class="credit-value bonus">
                                <span class="coin-icon-inline"></span>
                                +{formatCredits(bonusCredits)}
                            </span>
                        </div>
                        <div class="divider"></div>
                        <div class="credit-item total">
                            <span class="credit-label">{$text('signup.total_per_month.text')}</span>
                            <span class="credit-value">
                                <span class="coin-icon-inline"></span>
                                {formatCredits(totalCredits)}
                            </span>
                        </div>
                    {/if}
                </div>

                <div class="price-info">
                    <span class="price">{formatPrice(monthlyPrice, currency)}</span>
                    <span class="period">/{$text('signup.month.text')}</span>
                </div>

                <!-- Benefits -->
                <div class="benefits">
                    <div class="benefit-item">
                        <div class="check-icon"></div>
                        <span>{$text('signup.auto_topup_benefit_1.text')}</span>
                    </div>
                    <div class="benefit-item">
                        <div class="check-icon"></div>
                        <span>{@html $text('signup.auto_topup_benefit_2.text').replace('{percent}', bonusPercentage.toString())}</span>
                    </div>
                    <div class="benefit-item">
                        <div class="check-icon"></div>
                        <span>{$text('signup.auto_topup_benefit_3.text')}</span>
                    </div>
                </div>
            </div>
        {/if}

        <!-- Buttons -->
        <div class="button-container">
            <button
                class="secondary-button"
                onclick={handleSkip}
                disabled={isProcessing}
            >
                {$text('signup.skip.text')}
            </button>

            <button
                class="primary-button"
                onclick={handleActivate}
                disabled={!autoTopUpEnabled || isProcessing}
            >
                {#if isProcessing}
                    {$text('signup.processing.text')}
                {:else if autoTopUpEnabled}
                    {$text('signup.activate_and_finish.text')}
                {:else}
                    {$text('signup.finish_setup.text')}
                {/if}
            </button>
        </div>
    </div>
</div>

<style>
    .container {
        width: 100%;
        height: 100%;
        display: flex;
        justify-content: center;
        padding: 20px;
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

    /* Toggle Section */
    .toggle-section {
        background: rgba(255, 255, 255, 0.05);
        border-radius: 12px;
        padding: 20px;
    }

    .toggle-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 16px;
    }

    .toggle-label {
        color: white;
        font-size: 16px;
        font-weight: 500;
    }

    /* Toggle Switch */
    .toggle {
        position: relative;
        width: 52px;
        height: 28px;
        background: rgba(255, 255, 255, 0.2);
        border-radius: 14px;
        border: none;
        cursor: pointer;
        transition: background 0.3s ease;
        flex-shrink: 0;
    }

    .toggle:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .toggle.active {
        background: #58BC00;
    }

    .toggle-slider {
        position: absolute;
        width: 24px;
        height: 24px;
        background: white;
        border-radius: 50%;
        top: 2px;
        left: 2px;
        transition: transform 0.3s ease;
    }

    .toggle.active .toggle-slider {
        transform: translateX(24px);
    }

    /* Subscription Details */
    .subscription-details {
        display: flex;
        flex-direction: column;
        gap: 20px;
        animation: slideIn 0.3s ease-out;
    }

    @keyframes slideIn {
        from {
            opacity: 0;
            transform: translateY(-10px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }

    .credit-breakdown {
        background: rgba(255, 255, 255, 0.05);
        border-radius: 12px;
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 12px;
    }

    .credit-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    .credit-label {
        color: var(--color-grey-60);
        font-size: 14px;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .credit-item.bonus .credit-label {
        color: #58BC00;
    }

    .credit-item.total .credit-label {
        color: white;
        font-weight: 500;
    }

    .credit-value {
        color: white;
        font-size: 16px;
        display: flex;
        align-items: center;
        gap: 6px;
    }

    .credit-item.bonus .credit-value {
        color: #58BC00;
    }

    .credit-item.total .credit-value {
        font-weight: 600;
        font-size: 18px;
    }

    .bonus-badge {
        background: #58BC00;
        color: white;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 600;
    }

    :global(.coin-icon-inline) {
        display: inline-flex;
        width: 18px;
        height: 18px;
        background-image: url('@openmates/ui/static/icons/coins.svg');
        background-size: contain;
        background-repeat: no-repeat;
        filter: invert(1);
    }

    .divider {
        height: 1px;
        background: rgba(255, 255, 255, 0.1);
    }

    .price-info {
        text-align: center;
        padding: 16px;
        background: rgba(255, 255, 255, 0.05);
        border-radius: 12px;
    }

    .price {
        color: white;
        font-size: 32px;
        font-weight: 600;
    }

    .period {
        color: var(--color-grey-60);
        font-size: 16px;
    }

    /* Benefits */
    .benefits {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .benefit-item {
        display: flex;
        align-items: center;
        gap: 8px;
        color: var(--color-grey-60);
        font-size: 14px;
    }

    .check-icon {
        width: 20px;
        height: 20px;
        background-color: #58BC00;
        mask-image: url('@openmates/ui/static/icons/check.svg');
        mask-size: contain;
        mask-repeat: no-repeat;
        mask-position: center;
        flex-shrink: 0;
    }

    /* Buttons */
    .button-container {
        display: flex;
        gap: 12px;
        margin-top: auto;
        padding-top: 20px;
    }

    .primary-button,
    .secondary-button {
        flex: 1;
        padding: 14px 24px;
        border-radius: 8px;
        font-size: 16px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
        border: none;
    }

    .primary-button {
        background: #58BC00;
        color: white;
    }

    .primary-button:hover:not(:disabled) {
        background: #6BD100;
        transform: translateY(-1px);
    }

    .primary-button:disabled {
        background: rgba(88, 188, 0, 0.5);
        cursor: not-allowed;
    }

    .secondary-button {
        background: rgba(255, 255, 255, 0.1);
        color: white;
    }

    .secondary-button:hover:not(:disabled) {
        background: rgba(255, 255, 255, 0.15);
    }

    .secondary-button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    @media (max-width: 600px) {
        .button-container {
            flex-direction: column-reverse;
        }
    }
</style>
