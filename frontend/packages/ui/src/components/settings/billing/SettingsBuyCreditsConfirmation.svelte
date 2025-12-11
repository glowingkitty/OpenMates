<!--
Buy Credits Confirmation - Success screen after purchase
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { userProfile } from '../../../stores/userProfile';
    import SettingsItem from '../../SettingsItem.svelte';

    const dispatch = createEventDispatcher();

    let currentCredits = $state(0);

    // Load user profile data
    userProfile.subscribe(profile => {
        currentCredits = profile.credits || 0;
    });

    // Format credits with dots as thousand separators
    function formatCredits(credits: number): string {
        return credits.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    }

    // Navigate back to main billing view
    function goBackToBilling() {
        dispatch('openSettings', {
            settingsPath: 'billing',
            direction: 'backward',
            icon: 'billing',
            title: $text('settings.billing.text')
        });
    }
</script>

<!-- Success Icon and Message -->
<div class="success-section">
    <div class="success-icon-wrapper">
        <div class="success-icon"></div>
    </div>
    <h2 class="success-title">{$text('settings.billing.purchase_successful.text')}</h2>
    <p class="success-subtitle">{$text('settings.billing.credits_added.text')}</p>
</div>

<!-- Updated Balance Display -->
<div class="balance-info">
    <div class="balance-display">
        <span class="coin-icon"></span>
        <span class="balance-amount">{formatCredits(currentCredits)}</span>
        <span class="balance-label">{$text('settings.billing.credits.text')}</span>
    </div>
</div>

<!-- Action Button -->
<div class="action-section">
    <button class="done-button" onclick={goBackToBilling}>
        {$text('settings.billing.done.text')}
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

    .success-subtitle {
        font-size: 14px;
        color: var(--color-grey-60);
        margin: 0;
    }

    /* Balance Info Section */
    .balance-info {
        padding: 0 10px;
    }

    .balance-display {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 10px;
        padding: 20px;
        background: var(--color-grey-10);
        border-radius: 12px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }

    .balance-amount {
        color: var(--color-grey-100);
        font-size: 28px;
        font-weight: 600;
    }

    .balance-label {
        color: var(--color-grey-60);
        font-size: 14px;
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
        .balance-display {
            padding: 16px;
        }

        .balance-amount {
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
        .balance-amount {
            font-size: 22px;
        }

        .coin-icon {
            width: 24px;
            height: 24px;
        }

        .done-button {
            padding: 12px 20px;
            font-size: 15px;
        }
    }
</style>
