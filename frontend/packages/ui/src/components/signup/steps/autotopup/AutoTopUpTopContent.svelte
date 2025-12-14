<!--
Auto Top-Up Top Content - Success message and auto top-up setup all in one full-height container
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
        paymentMethodSaved = true,
        paymentMethodSaveError = null,
        oncomplete,
        'onactivate-subscription': onactivateSubscription
    }: {
        purchasedCredits?: number;
        purchasedPrice?: number;
        currency?: string;
        paymentMethodSaved?: boolean;
        paymentMethodSaveError?: string | null;
        oncomplete?: (event: CustomEvent) => void;
        'onactivate-subscription'?: (event: CustomEvent) => void;
    } = $props();

    // State for toggles - both off by default
    let lowBalanceEnabled = $state(false);
    let monthlyEnabled = $state(false);
    let isProcessing = $state(false);

    // Determine suggested tier based on purchased credits
    function getSuggestedTier() {
        if (purchasedCredits === 1000) {
            return pricingTiers.find(tier => tier.credits === 10000) || pricingTiers[1];
        }
        const matchingTier = pricingTiers.find(tier => tier.credits === purchasedCredits);
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
            // Only activate subscription if payment method was saved successfully
            if (monthlyEnabled && paymentMethodSaved) {
                if (onactivateSubscription) {
                    onactivateSubscription(new CustomEvent('activate-subscription', {
                        detail: {
                            credits: baseCredits,
                            bonusCredits: bonusCredits,
                            price: monthlyPrice,
                            currency: currency
                        }
                    }));
                    // Wait for subscription activation to complete
                    // The parent component will handle completion
                    return;
                }
            } else if (monthlyEnabled && !paymentMethodSaved) {
                // Payment method wasn't saved - can't activate subscription
                console.error('Cannot activate subscription: Payment method was not saved');
                isProcessing = false;
                return;
            }

            // If no subscription activation needed, complete signup
            if (oncomplete) {
                oncomplete(new CustomEvent('complete', {
                    detail: {
                        lowBalanceEnabled: lowBalanceEnabled,
                        monthlyEnabled: false // Set to false if payment method wasn't saved
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
    <div class="top-container">
        <div class="header-content">
            <div class="success-icon"></div>
            <div class="primary-text">
                {@html $text('signup.purchase_successful.text')}
            </div>
        </div>
    </div>
    
    <div class="bottom-container">
        <div class="main-content">
            <div class="purchase-summary">
                <div class="summary-item">
                    <span class="label">{$text('signup.credits_purchased.text')}</span>
                    <span class="value">
                        <span class="coin-icon-inline"></span>
                        {formatCredits(purchasedCredits)}
                    </span>
                </div>
                <div class="summary-item">
                    <span class="label">{$text('signup.amount_paid.text')}</span>
                    <span class="value">{formatPrice(purchasedPrice, currency)}</span>
                </div>
            </div>

            <div class="auto-topup-section">
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
                        <Toggle 
                            bind:checked={monthlyEnabled} 
                            id="monthly-toggle" 
                            disabled={isProcessing || !paymentMethodSaved} 
                        />
                        <label for="monthly-toggle" class="confirmation-text">
                            {$text('settings.billing.monthly.text')}
                        </label>
                    </div>
                    {#if !paymentMethodSaved}
                        <div class="error-message">
                            Payment method could not be saved. Monthly auto top-up is not available. You can set this up later in settings.
                        </div>
                    {:else if monthlyEnabled}
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
    </div>
</div>

<style>
    .container {
        position: relative;
        width: 100%;
        height: 100%;
        min-height: 400px; /* Ensure minimum height for auto top-up form visibility */
    }
    
    .top-container {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 80px;
        padding: 0 24px;
        display: flex;
        align-items: flex-end;
        justify-content: center;
        z-index: 2;
    }
    
    .header-content {
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        padding-bottom: 8px;
        gap: 6px;
    }

    .success-icon {
        width: 36px;
        height: 36px;
        background-color: #58BC00;
        mask-image: url('@openmates/ui/static/icons/check.svg');
        mask-size: contain;
        mask-repeat: no-repeat;
        mask-position: center;
        animation: scaleIn 0.3s ease-out;
    }

    @keyframes scaleIn {
        from {
            transform: scale(0);
        }
        to {
            transform: scale(1);
        }
    }
    
    .bottom-container {
        position: absolute;
        top: 80px;
        left: 0;
        right: 0;
        bottom: 0;
        padding: 0 24px;
        overflow-y: auto; /* Allow scrolling if content exceeds container */
        overflow-x: hidden;
    }

    @media (max-width: 600px) {
        .top-container {
            height: 45px;
        }
        .bottom-container {
            top: 45px;
        }
    }
    
    .main-content {
        display: flex;
        flex-direction: column;
        justify-content: flex-start;
        align-items: center;
        height: 100%; /* Fill available space */
        padding: 10px 0;
        box-sizing: border-box;
        gap: 10px;
    }
    
    .primary-text {
        white-space: nowrap;
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-size: 18px;
        font-weight: 500;
    }

    .purchase-summary {
        width: 100%;
        max-width: 400px;
        background: rgba(255, 255, 255, 0.05);
        border-radius: 12px;
        padding: 10px;
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .summary-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    .label {
        color: var(--color-grey-60);
        font-size: 16px;
    }

    .value {
        color: white;
        font-size: 16px;
        font-weight: 500;
        display: flex;
        align-items: center;
        gap: 6px;
    }

    :global(.coin-icon-inline) {
        display: inline-flex;
        width: 18px;
        height: 18px;
        background-image: url('@openmates/ui/static/icons/coins.svg');
        background-size: contain;
        background-repeat: no-repeat;
        vertical-align: middle;
        filter: invert(1);
    }

    .auto-topup-section {
        width: 100%;
        max-width: 500px;
        display: flex;
        flex-direction: column;
        gap: 10px;
    }

    .intro-text {
        color: var(--color-grey-60);
        font-size: 16px;
        text-align: center;
        line-height: 1.3;
    }

    .toggle-option {
        background: rgba(255, 255, 255, 0.05);
        border-radius: 12px;
        padding: 10px;
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .confirmation-row {
        display: flex;
        align-items: center;
        gap: 10px;
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
        font-size: 16px;
        line-height: 1.3;
        padding-left: 36px;
        display: flex;
        flex-direction: column;
        gap: 2px;
    }

    .bonus-badge {
        background: var(--color-primary);
        color: white;
        padding: 3px 6px;
        border-radius: 4px;
        font-size: 16px;
        font-weight: 600;
        display: inline-block;
        margin-top: 1px;
        align-self: flex-start;
    }

    .help-text {
        color: var(--color-grey-50);
        font-size: 16px;
        text-align: center;
        margin-top: 2px;
    }

    .error-message {
        background-color: rgba(255, 0, 0, 0.1);
        color: var(--color-error-text, #ff6b6b);
        padding: 8px 12px;
        border-radius: 8px;
        font-size: 14px;
        line-height: 1.4;
        margin-top: 6px;
        border: 1px solid rgba(255, 0, 0, 0.2);
    }
</style>
