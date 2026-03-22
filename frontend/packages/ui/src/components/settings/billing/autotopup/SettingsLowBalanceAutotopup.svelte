<!--
Low Balance Auto Top-Up Settings - Configure automatic credit purchases when balance is low
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { apiEndpoints, getApiEndpoint } from '../../../../config/api';
    import { userProfile } from '../../../../stores/userProfile';
    import { pricingTiers } from '../../../../config/pricing';
    import Toggle from '../../../Toggle.svelte';
    import { getEmailDecryptedWithMasterKey } from '../../../../services/cryptoService';

    let isLoading = $state(false);
    let errorMessage: string | null = $state(null);
    let emailErrorMessage: string | null = $state(null);

    // Low balance auto top-up state
    let lowBalanceEnabled = $state(false);
    // Fixed threshold: always 100 credits (cannot be changed to simplify setup)
    const lowBalanceThreshold = 100;
    let lowBalanceAmount = $state(10000);
    let lowBalanceCurrency = $state('EUR');
    let hasPaymentMethod = $state(false);

    // Format credits with dots as thousand separators
    function formatCredits(credits: number): string {
        return credits.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    }

    // Format currency
    function formatCurrency(amount: number, currency: string): string {
        const symbols: Record<string, string> = {
            'EUR': '€',
            'USD': '$',
        };
        const symbol = symbols[currency.toUpperCase()] || currency.toUpperCase();
        return `${symbol}${amount}`;
    }

    // Helper to get price for a tier in the configured currency
    function getTierPrice(tier: any): number {
        const currencyKey = lowBalanceCurrency.toLowerCase() as 'eur' | 'usd';
        return tier.price[currencyKey];
    }

    // Load user profile data
    userProfile.subscribe(profile => {
        lowBalanceEnabled = profile.auto_topup_low_balance_enabled || false;
        // Threshold is fixed at 100 credits and cannot be changed
        lowBalanceAmount = profile.auto_topup_low_balance_amount || 10000;
        lowBalanceCurrency = profile.auto_topup_low_balance_currency?.toUpperCase() || 'EUR';
    });

    // Fetch payment method status using the new endpoint
    async function checkPaymentMethod() {
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.hasPaymentMethod), {
                credentials: 'include'
            });

            if (response.ok) {
                const data = await response.json();
                hasPaymentMethod = data.has_payment_method || false;
            } else {
                // If endpoint fails, assume no payment method
                hasPaymentMethod = false;
            }
        } catch (error) {
            console.error('Error checking payment method:', error);
            hasPaymentMethod = false;
        }
    }

    // Save low balance settings
    async function saveLowBalanceSettings() {
        isLoading = true;
        errorMessage = null;
        emailErrorMessage = null;

        try {
            const decryptedEmail = lowBalanceEnabled ? await getEmailDecryptedWithMasterKey() : null;
            if (lowBalanceEnabled && !decryptedEmail) {
                emailErrorMessage = 'Email could not be decrypted on this device. Log in again to unlock encryption keys.';
                return;
            }
            const response = await fetch(getApiEndpoint(apiEndpoints.settings.autoTopUp.lowBalance), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    enabled: lowBalanceEnabled,
                    threshold: lowBalanceThreshold,
                    amount: lowBalanceAmount,
                    currency: lowBalanceCurrency.toLowerCase(),
                    ...(decryptedEmail ? { email: decryptedEmail } : {})
                })
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Failed to save settings');
            }

            // Update user profile store with new settings
            // Threshold is always 100 credits (fixed, cannot be changed)
            userProfile.update(profile => ({
                ...profile,
                auto_topup_low_balance_enabled: lowBalanceEnabled,
                auto_topup_low_balance_threshold: 100, // Always 100 credits
                auto_topup_low_balance_amount: lowBalanceAmount,
                auto_topup_low_balance_currency: lowBalanceCurrency.toLowerCase()
            }));

            alert('Low balance auto top-up settings saved successfully');
        } catch (error) {
            console.error('Error saving low balance settings:', error);
            errorMessage = error instanceof Error ? error.message : 'Failed to save settings. Please try again.';
        } finally {
            isLoading = false;
        }
    }

    async function handleLowBalanceToggleChange(event: CustomEvent<{ checked: boolean }>) {
        emailErrorMessage = null;
        if (!event.detail.checked) return;

        const decryptedEmail = await getEmailDecryptedWithMasterKey();
        if (!decryptedEmail) {
            emailErrorMessage = 'Email could not be decrypted on this device. Log in again to unlock encryption keys.';
            lowBalanceEnabled = false;
        }
    }

    onMount(() => {
        checkPaymentMethod();
    });
</script>

<div class="low-balance-container">
    <!-- Enable/Disable Toggle -->
    <div class="toggle-section">
        <div class="toggle-header">
            <span class="toggle-label">{$text('settings.billing.enable_low_balance')}</span>
            <Toggle 
                bind:checked={lowBalanceEnabled} 
                disabled={isLoading}
                id="low-balance-toggle"
                ariaLabel={lowBalanceEnabled ? 'Disable low balance auto top-up' : 'Enable low balance auto top-up'}
                on:change={handleLowBalanceToggleChange}
            />
        </div>
        <p class="help-text">
            {$text('settings.billing.low_balance_help')}
        </p>
    </div>

    {#if emailErrorMessage}
        <div class="error-message">{emailErrorMessage}</div>
    {/if}

    {#if lowBalanceEnabled}
        <!-- Threshold Display (Fixed at 100 credits) -->
        <div class="form-group">
            <label for="threshold">{$text('settings.billing.threshold')}</label>
            <div class="fixed-value-display">
                {formatCredits(lowBalanceThreshold)} {$text('settings.billing.credits')}
            </div>
            <p class="help-text">Auto top-up triggers when balance falls to or below {formatCredits(lowBalanceThreshold)} credits (fixed value)</p>
        </div>

        <!-- Amount Selection -->
        <div class="form-group">
            <label for="amount">{$text('settings.billing.topup_amount')}</label>
            <select id="amount" bind:value={lowBalanceAmount} disabled={isLoading}>
                {#each pricingTiers as tier}
                    <option value={tier.credits}>
                        {formatCredits(tier.credits)} credits - {formatCurrency(getTierPrice(tier), lowBalanceCurrency)}
                    </option>
                {/each}
            </select>
            <p class="help-text">Credits to purchase when threshold is reached</p>
        </div>

        <!-- Currency Selection -->
        <div class="form-group">
            <label for="currency">{$text('settings.billing.currency')}</label>
            <select id="currency" bind:value={lowBalanceCurrency} disabled={isLoading}>
                <option value="EUR">EUR (€)</option>
                <option value="USD">USD ($)</option>
            </select>
        </div>

        <!-- Payment Method Status -->
        <div class="info-box {hasPaymentMethod ? 'success' : 'warning'}">
            {#if hasPaymentMethod}
                <div class="check-icon-small"></div>
                <span>Payment method saved</span>
            {:else}
                <div class="warning-icon-small"></div>
                <span>No payment method saved. Please make a purchase first to save your payment method.</span>
            {/if}
        </div>
    {/if}

    <!-- Save Button -->
    <button
        class="save-button"
        onclick={saveLowBalanceSettings}
        disabled={isLoading || (lowBalanceEnabled && !hasPaymentMethod)}
    >
        {isLoading ? 'Saving...' : $text('settings.save')}
    </button>

    {#if errorMessage}
        <div class="error-message">{errorMessage}</div>
    {/if}
</div>

<style>
    .low-balance-container {
        padding: 0 10px;
        display: flex;
        flex-direction: column;
        gap: 16px;
    }

    /* Toggle Section */
    .toggle-section {
        display: flex;
        flex-direction: column;
        gap: 10px;
        padding: 12px;
        background: var(--color-grey-10);
        border-radius: 8px;
    }

    .toggle-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 16px;
    }

    .toggle-label {
        color: var(--color-grey-100);
        font-size: 15px;
        font-weight: 500;
        flex: 1;
    }

    /* Form Elements */
    .form-group {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .form-group label {
        color: var(--color-grey-100);
        font-size: 14px;
        font-weight: 500;
    }

    .form-group select {
        background: var(--color-grey-10);
        border: 1px solid var(--color-grey-30);
        border-radius: 8px;
        color: var(--color-grey-100);
        padding: 10px 12px;
        font-size: 14px;
        cursor: pointer;
        transition: border-color 0.2s ease;
    }

    .form-group select:focus {
        outline: none;
        border-color: var(--color-primary);
    }

    .form-group select:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .fixed-value-display {
        background: var(--color-grey-10);
        border: 1px solid var(--color-grey-30);
        border-radius: 8px;
        color: var(--color-grey-100);
        padding: 10px 12px;
        font-size: 14px;
        font-weight: 500;
    }

    .help-text {
        color: var(--color-grey-60);
        font-size: 12px;
        margin: 0;
        line-height: 1.4;
    }

    /* Icons */
    .check-icon-small {
        width: 16px;
        height: 16px;
        background-color: #58BC00;
        mask-image: url('@openmates/ui/static/icons/check.svg');
        mask-size: contain;
        mask-repeat: no-repeat;
        flex-shrink: 0;
    }

    .warning-icon-small {
        width: 16px;
        height: 16px;
        background-color: #FFA500;
        mask-image: url('@openmates/ui/static/icons/warning.svg');
        mask-size: contain;
        mask-repeat: no-repeat;
        flex-shrink: 0;
    }

    /* Info Boxes */
    .info-box {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 12px;
        border-radius: 8px;
        font-size: 13px;
    }

    .info-box.success {
        background: rgba(88, 188, 0, 0.1);
        color: #58BC00;
        border: 1px solid rgba(88, 188, 0, 0.3);
    }

    .info-box.warning {
        background: rgba(255, 165, 0, 0.1);
        color: #FFA500;
        border: 1px solid rgba(255, 165, 0, 0.3);
    }

    /* Save Button */
    .save-button {
        padding: 10px 16px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
        border: none;
        background: var(--color-primary);
        color: white;
    }

    .save-button:hover:not(:disabled) {
        background: var(--color-primary-hover);
    }

    .save-button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    /* Error Message */
    .error-message {
        background: rgba(223, 27, 65, 0.1);
        color: #df1b41;
        padding: 12px;
        border-radius: 8px;
        font-size: 13px;
        border: 1px solid rgba(223, 27, 65, 0.3);
    }

    /* Responsive Styles */
    @media (max-width: 480px) {
        .low-balance-container {
            padding: 0 5px;
        }
    }
</style>
