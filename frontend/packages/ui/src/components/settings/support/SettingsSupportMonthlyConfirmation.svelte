<!--
Support Monthly Payment Confirmation - Success screen after monthly support payment setup
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';

    const dispatch = createEventDispatcher();

    const { amount = 0, currency = 'EUR' }: { amount?: number; currency?: string } = $props();

    // Format currency
    function formatCurrency(amount: number, currency: string): string {
        const symbols: Record<string, string> = {
            'EUR': '€',
            'USD': '$',
        };
        const symbol = symbols[currency.toUpperCase()] || currency.toUpperCase();
        return `${symbol}${amount}`;
    }

    // Navigate back to support section
    function goBackToSupport() {
        dispatch('openSettings', {
            settingsPath: 'support',
            direction: 'backward',
            icon: 'support',
            title: $text('settings.support')
        });
    }
</script>

<!-- Success Icon and Message -->
<div class="success-section">
    <div class="ds-success-icon-wrapper">
        <div class="success-icon"></div>
    </div>
    <h2 class="ds-success-title">{$text('settings.support.subscription_successful')}</h2>
</div>

<!-- Amount Display -->
<div class="amount-info">
    <div class="amount-display">
        <span class="heart-icon"></span>
        <span class="amount-value">{formatCurrency(amount, currency)}</span>
        <span class="amount-label">{$text('settings.support.per_month')}</span>
    </div>
    <p class="details-text">{$text('settings.support.monthly_confirmation_details')}</p>
</div>

<!-- Action Button -->
<div class="action-section">
    <button class="done-button" onclick={goBackToSupport}>
        {$text('common.done')}
    </button>
</div>

<style>
    /* Success Section */
    .success-section {
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        gap: var(--spacing-6);
        padding: 20px 0;
    }

    /* Base styles for .ds-success-icon-wrapper / .ds-success-title are generated
       from frontend/packages/ui/src/tokens/sources/components/status-feedback.yml
       See docs/architecture/frontend/design-tokens.md (Phase E). */

    .success-icon {
        width: 40px;
        height: 40px;
        background-image: url('@openmates/ui/static/icons/check.svg');
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        filter: invert(1);
    }

    /* Amount Info Section */
    .amount-info {
        padding: 0 10px;
        display: flex;
        flex-direction: column;
        gap: var(--spacing-8);
    }

    .amount-display {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: var(--spacing-5);
        padding: var(--spacing-10);
        background: var(--color-grey-10);
        border-radius: var(--radius-5);
        box-shadow: var(--shadow-xs);
    }

    .amount-value {
        color: var(--color-grey-100);
        font-size: var(--font-size-xxl);
        font-weight: 600;
    }

    .amount-label {
        color: var(--color-grey-60);
        font-size: var(--font-size-small);
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
        font-size: var(--font-size-small);
        color: var(--color-grey-60);
        text-align: center;
        line-height: 1.5;
        margin: 0;
        padding: 0 10px;
    }

    /* Action Section */
    .action-section {
        padding: 0 10px;
        margin-top: var(--spacing-10);
    }

    .done-button {
        width: 100%;
        padding: 14px 24px;
        background: var(--color-primary);
        color: white;
        border: none;
        border-radius: var(--radius-5);
        font-size: var(--font-size-p);
        font-weight: 600;
        cursor: pointer;
        transition: all var(--duration-normal) var(--easing-default);
        box-shadow: var(--shadow-xs);
    }

    .done-button:hover {
        background: var(--color-primary-dark);
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
        transform: translateY(-1px);
    }

    .done-button:active {
        transform: translateY(0);
        box-shadow: var(--shadow-xs);
    }

    /* Responsive Styles */
    @media (max-width: 768px) {
        .amount-display {
            padding: var(--spacing-8);
        }

        .amount-value {
            font-size: var(--font-size-h2-mobile);
        }

        .ds-success-icon-wrapper {
            width: 70px;
            height: 70px;
        }

        .success-icon {
            width: 35px;
            height: 35px;
        }

        .ds-success-title {
            font-size: var(--font-size-h3-mobile);
        }
    }

    @media (max-width: 480px) {
        .amount-value {
            font-size: var(--font-size-xl);
        }

        .heart-icon {
            width: 24px;
            height: 24px;
        }

        .done-button {
            padding: var(--spacing-6) var(--spacing-10);
            font-size: null;
        }
    }
</style>
