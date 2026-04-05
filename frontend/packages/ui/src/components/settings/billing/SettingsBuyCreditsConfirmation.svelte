<!--
Buy Credits Confirmation - Success screen after purchase.
Shows both the purchased credits amount (+X) and the new total balance.
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { userProfile } from '../../../stores/userProfile';
    import { purchasedCreditsStore } from './SettingsBuyCreditsPayment.svelte';

    const dispatch = createEventDispatcher();

    let currentCredits = $state(0);
    let purchasedCredits = $state(0);

    // Load user profile data (reactive — updates when WebSocket pushes new balance)
    userProfile.subscribe(profile => {
        currentCredits = profile.credits || 0;
    });

    // Read the purchased credits amount set by the payment component
    purchasedCreditsStore.subscribe(value => {
        purchasedCredits = value;
    });

    // Format credits with dots as thousand separators
    function formatCredits(credits: number): string {
        return credits.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    }

    // Navigate back to main billing view
    function goBackToBilling() {
        // Reset purchased credits store so it doesn't persist on next visit
        purchasedCreditsStore.set(0);
        dispatch('openSettings', {
            settingsPath: 'billing',
            direction: 'backward',
            icon: 'billing',
            title: $text('settings.billing')
        });
    }
</script>

<!-- Success Icon and Message -->
<div class="success-section">
    <div class="success-icon-wrapper">
        <div class="success-icon"></div>
    </div>
    <h2 class="success-title">{$text('settings.billing.purchase_successful')}</h2>
    <p class="success-subtitle">{$text('settings.billing.credits_added')}</p>
</div>

<!-- Purchased Credits Highlight (only shown when we know the amount) -->
{#if purchasedCredits > 0}
    <div class="purchased-credits-section">
        <div class="purchased-credits-badge">
            <span class="purchased-amount">+{formatCredits(purchasedCredits)}</span>
            <span class="purchased-label">{$text('common.credits')}</span>
        </div>
    </div>
{/if}

<!-- Updated Balance Display -->
<div class="balance-info">
    <div class="balance-display">
        <span class="coin-icon"></span>
        <span class="balance-amount">{formatCredits(currentCredits)}</span>
        <span class="balance-label">{$text('settings.billing.credits_total')}</span>
    </div>
</div>

<!-- Action Button -->
<div class="action-section">
    <button class="done-button" onclick={goBackToBilling}>
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
        font-size: var(--font-size-h3);
        font-weight: 600;
        color: var(--color-grey-100);
        margin: 0;
    }

    .success-subtitle {
        font-size: var(--font-size-small);
        color: var(--color-grey-60);
        margin: 0;
    }

    /* Purchased Credits Badge — green highlight showing +amount */
    .purchased-credits-section {
        display: flex;
        justify-content: center;
        padding: 0 10px 8px;
    }

    .purchased-credits-badge {
        display: flex;
        align-items: center;
        gap: var(--spacing-3);
        padding: var(--spacing-4) var(--spacing-8);
        background: rgba(16, 185, 129, 0.1);
        border: 1px solid rgba(16, 185, 129, 0.25);
        border-radius: var(--radius-8);
    }

    .purchased-amount {
        color: #10b981;
        font-size: var(--font-size-h3-mobile);
        font-weight: 700;
    }

    .purchased-label {
        color: #10b981;
        font-size: var(--font-size-xs);
        font-weight: 500;
    }

    /* Balance Info Section */
    .balance-info {
        padding: 0 10px;
    }

    .balance-display {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: var(--spacing-5);
        padding: var(--spacing-10);
        background: var(--color-grey-10);
        border-radius: var(--radius-5);
        box-shadow: var(--shadow-xs);
    }

    .balance-amount {
        color: var(--color-grey-100);
        font-size: var(--font-size-xxl);
        font-weight: 600;
    }

    .balance-label {
        color: var(--color-grey-60);
        font-size: var(--font-size-small);
    }

    .coin-icon {
        width: 28px;
        height: 28px;
        background-image: url('@openmates/ui/static/icons/coins.svg');
        background-size: contain;
        background-repeat: no-repeat;
        filter: invert(1);
    }

    /* Action Section */
    .action-section {
        padding: 0 10px;
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
        .balance-display {
            padding: var(--spacing-8);
        }

        .balance-amount {
            font-size: var(--font-size-h2-mobile);
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
            font-size: var(--font-size-h3-mobile);
        }

        .purchased-amount {
            font-size: var(--font-size-p);
        }
    }

    @media (max-width: 480px) {
        .balance-amount {
            font-size: var(--font-size-xl);
        }

        .coin-icon {
            width: 24px;
            height: 24px;
        }

        .done-button {
            padding: var(--spacing-6) var(--spacing-10);
            font-size: null;
        }
    }
</style>
