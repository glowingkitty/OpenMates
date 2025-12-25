<!--
Support Monthly Payment Confirmation - Success screen after monthly support payment setup
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';

    const dispatch = createEventDispatcher();

    const { amount = 0, currency = 'EUR' }: { amount?: number; currency?: string } = $props();

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

    // Navigate back to support section
    function goBackToSupport() {
        dispatch('openSettings', {
            settingsPath: 'support',
            direction: 'backward',
            icon: 'support',
            title: $text('settings.support.text')
        });
    }
</script>

<!-- Success Icon and Message -->
<div class="success-section">
    <div class="success-icon-wrapper">
        <div class="success-icon"></div>
    </div>
    <h2 class="success-title">{$text('settings.support.subscription_successful.text')}</h2>
</div>

<!-- Amount Display -->
<div class="amount-info">
    <div class="amount-display">
        <span class="heart-icon"></span>
        <span class="amount-value">{formatCurrency(amount, currency)}</span>
        <span class="amount-label">{$text('settings.support.per_month.text')}</span>
    </div>
    <p class="details-text">{$text('settings.support.monthly_confirmation_details.text')}</p>
</div>

<!-- Action Button -->
<div class="action-section">
    <button class="done-button" onclick={goBackToSupport}>
        {$text('settings.support.done.text')}
    </button>
</div>

<style>
    /* Success Section */
    .success-section {
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        gap: 12px;
        padding: 20px 0;
    }

    .success-icon-wrapper {
        width: 80px;
        height: 80px;
        border-radius: 50%;
        background: linear-gradient(135deg, #10b981 0%, #059669 100%);
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
    }

    .success-icon {
        width: 40px;
        height: 40px;
        background-image: url('@openmates/ui/static/icons/check.svg');
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        filter: invert(1);
    }

    .success-title {
        font-size: 20px;
        font-weight: 600;
        color: var(--color-grey-100);
        margin: 0;
    }

    /* Amount Info Section */
    .amount-info {
        padding: 0 10px;
        display: flex;
        flex-direction: column;
        gap: 16px;
    }

    .amount-display {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 10px;
        padding: 20px;
        background: var(--color-grey-10);
        border-radius: 12px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }

    .amount-value {
        color: var(--color-grey-100);
        font-size: 28px;
        font-weight: 600;
    }

    .amount-label {
        color: var(--color-grey-60);
        font-size: 14px;
    }

    .heart-icon {
        width: 28px;
        height: 28px;
        background-image: url('@openmates/ui/static/icons/heart.svg');
        background-size: contain;
        background-repeat: no-repeat;
        filter: invert(1);
    }

    .details-text {
        font-size: 14px;
        color: var(--color-grey-60);
        text-align: center;
        line-height: 1.5;
        margin: 0;
        padding: 0 10px;
    }

    /* Action Section */
    .action-section {
        padding: 0 10px;
        margin-top: 20px;
    }

    .done-button {
        width: 100%;
        padding: 14px 24px;
        background: var(--color-primary);
        color: white;
        border: none;
        border-radius: 12px;
        font-size: 16px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.2s ease;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }

    .done-button:hover {
        background: var(--color-primary-dark);
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
        transform: translateY(-1px);
    }

    .done-button:active {
        transform: translateY(0);
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }

    /* Responsive Styles */
    @media (max-width: 768px) {
        .amount-display {
            padding: 16px;
        }

        .amount-value {
            font-size: 24px;
        }

        .success-icon-wrapper {
            width: 70px;
            height: 70px;
        }

        .success-icon {
            width: 35px;
            height: 35px;
        }

        .success-title {
            font-size: 18px;
        }
    }

    @media (max-width: 480px) {
        .amount-value {
            font-size: 22px;
        }

        .heart-icon {
            width: 24px;
            height: 24px;
        }

        .done-button {
            padding: 12px 20px;
            font-size: 15px;
        }
    }
</style>
