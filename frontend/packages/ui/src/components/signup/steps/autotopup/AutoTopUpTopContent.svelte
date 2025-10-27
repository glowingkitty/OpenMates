<!--
Auto Top-Up Top Content - Success message and purchase summary
-->

<script lang="ts">
    import { text } from '@repo/ui';

    // Use Svelte 5 runes for props
    let {
        purchasedCredits = 0,
        purchasedPrice = 0,
        currency = 'eur'
    }: {
        purchasedCredits?: number;
        purchasedPrice?: number;
        currency?: string;
    } = $props();

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

            <div class="divider"></div>

            <div class="auto-topup-intro">
                <div class="intro-title">{$text('signup.never_run_out.text')}</div>
                <div class="intro-text">{@html $text('signup.auto_topup_benefits.text')}</div>
            </div>
        </div>
    </div>
</div>

<style>
    .container {
        position: relative;
        width: 100%;
        height: 100%;
    }

    .top-container {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 130px;
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
        padding-bottom: 20px;
        gap: 12px;
    }

    .success-icon {
        width: 48px;
        height: 48px;
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
        top: 130px;
        left: 0;
        right: 0;
        bottom: 0;
        padding: 0 24px;
        overflow-y: auto;
    }

    @media (max-width: 600px) {
        .top-container {
            height: 80px;
        }
        .bottom-container {
            top: 80px;
        }
    }

    .main-content {
        display: flex;
        flex-direction: column;
        align-items: center;
        padding: 25px 0;
        gap: 20px;
    }

    .primary-text {
        color: white;
        font-size: 20px;
        font-weight: 500;
    }

    .purchase-summary {
        width: 100%;
        max-width: 400px;
        background: rgba(255, 255, 255, 0.05);
        border-radius: 12px;
        padding: 20px;
        display: flex;
        flex-direction: column;
        gap: 12px;
    }

    .summary-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    .label {
        color: var(--color-grey-60);
        font-size: 14px;
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
        width: 20px;
        height: 20px;
        background-image: url('@openmates/ui/static/icons/coins.svg');
        background-size: contain;
        background-repeat: no-repeat;
        vertical-align: middle;
        filter: invert(1);
    }

    .divider {
        width: 100%;
        max-width: 400px;
        height: 1px;
        background: rgba(255, 255, 255, 0.1);
    }

    .auto-topup-intro {
        width: 100%;
        max-width: 400px;
        text-align: center;
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .intro-title {
        color: white;
        font-size: 18px;
        font-weight: 500;
    }

    .intro-text {
        color: var(--color-grey-60);
        font-size: 14px;
        line-height: 1.5;
    }
</style>
