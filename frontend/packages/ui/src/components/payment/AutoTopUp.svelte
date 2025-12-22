<!--
Auto Top-Up Component - Displays auto top-up configuration options in a white card
with toggles for "On low balance" and "Every month" options.
Matches the design from the signup flow screenshot.
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { pricingTiers } from '../../config/pricing';
    import Toggle from '../Toggle.svelte';
    import { createEventDispatcher, onMount } from 'svelte';
    import { userProfile } from '../../stores/userProfile';
    import { apiEndpoints, getApiUrl } from '../../config/api';
    import { getEmailDecryptedWithMasterKey } from '../../services/cryptoService';

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

    // State for toggles - will be synced with user profile data
    let lowBalanceEnabled = $state(false);
    let monthlyEnabled = $state(false);
    let isProcessing = $state(false);
    let isLoadingSettings = $state(true);
    let lowBalanceEmailError: string | null = $state(null);
    
    // State for subscription details
    let hasActiveSubscription = $state(false);
    let subscriptionDetails: any = $state(null);

    // Fetch subscription details to sync monthly toggle
    async function fetchSubscriptionDetails() {
        try {
            const response = await fetch(getApiUrl() + apiEndpoints.payments.getSubscription, {
                credentials: 'include'
            });

            if (response.ok) {
                const data = await response.json();
                subscriptionDetails = data;
                hasActiveSubscription = data.status === 'active';
                // Sync monthly toggle with subscription status
                monthlyEnabled = hasActiveSubscription;
                console.debug('[AutoTopUp] Subscription status:', hasActiveSubscription, data);
            } else if (response.status === 404) {
                // No subscription found
                hasActiveSubscription = false;
                subscriptionDetails = null;
                monthlyEnabled = false;
            }
        } catch (error) {
            console.error('[AutoTopUp] Error fetching subscription:', error);
            hasActiveSubscription = false;
            monthlyEnabled = false;
        }
    }

    // NOTE: fetchLastInvoice function removed - we now use hardcoded defaults
    // This simplifies the implementation and avoids issues with invoice fetching

    // Sync toggles with user profile data
    function syncWithUserProfile() {
        const profile = $userProfile;
        
        // Sync low balance toggle with existing settings
        lowBalanceEnabled = profile.auto_topup_low_balance_enabled || false;
        
        // If low balance is enabled and we have existing settings, use them
        if (lowBalanceEnabled && profile.auto_topup_low_balance_amount) {
            lowBalanceAmount = profile.auto_topup_low_balance_amount;
            if (profile.auto_topup_low_balance_currency) {
                currency = profile.auto_topup_low_balance_currency.toLowerCase();
            }
            // Get price for the credits amount from pricing tiers
            const tier = pricingTiers.find(t => t.credits === lowBalanceAmount);
            if (tier) {
                lowBalancePrice = tier.price[currency.toLowerCase() as 'eur' | 'usd' | 'jpy'] || 0;
            }
            console.debug('[AutoTopUp] Synced low balance settings from profile:', {
                enabled: lowBalanceEnabled,
                amount: lowBalanceAmount,
                currency: currency,
                price: lowBalancePrice
            });
        }
        
        console.debug('[AutoTopUp] Synced toggles with user profile:', {
            lowBalanceEnabled,
            monthlyEnabled: hasActiveSubscription
        });
    }

    // Determine suggested tier for monthly auto top-up
    // Monthly always defaults to 21000 credits (recommended tier) regardless of purchase
    function getMonthlyTier() {
        // Always use the recommended tier (21000 credits) for monthly auto top-up
        const recommended = pricingTiers.find(tier => tier.recommended);
        if (recommended) return recommended;
        // Fallback to first tier with monthly_auto_top_up_extra_credits
        return pricingTiers.find(tier => tier.monthly_auto_top_up_extra_credits) || pricingTiers[1];
    }

    // NOTE: getDefaultLowBalanceAmount function removed - we now use hardcoded default of 10,000 credits

    // State for low balance defaults - SIMPLIFIED: Use hardcoded defaults
    // Default: 21,000 credits for low balance auto top-up (recommended tier, same as monthly)
    let lowBalanceAmount = $state(21000);
    let lowBalancePrice = $state(20); // Default to 20 EUR (will be updated from tier in onMount)
    
    // Calculate auto top-up values for monthly (always uses recommended tier: 21,000 + 1,000 bonus = 22,000 total)
    let monthlyTier = $derived(getMonthlyTier());
    let baseCredits = $derived(monthlyTier ? monthlyTier.credits : 21000); // Default to 21,000 if tier not found
    let bonusCredits = $derived(monthlyTier ? (monthlyTier.monthly_auto_top_up_extra_credits || 0) : 1000); // Default to 1,000 bonus
    let totalCredits = $derived(baseCredits + bonusCredits); // Should be 22,000 total
    let monthlyPrice = $derived(monthlyTier ? monthlyTier.price[currency.toLowerCase() as 'eur' | 'usd' | 'jpy'] : 20); // Default to 20 EUR
    
    // Fixed threshold: always 100 credits
    const lowBalanceThreshold = 100;
    
    // NOTE: We no longer use $effect to update from purchasedCredits prop
    // Instead, we always fetch the last invoice from the server in onMount
    // This ensures consistency regardless of timing (fresh purchase, page reload, new device)
    // The invoice is the single source of truth for what credits were actually purchased

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

    // Load settings on mount
    onMount(async () => {
        isLoadingSettings = true;
        
        try {
            // CRITICAL: Always sync with user profile data first to get existing settings
            // This ensures we respect any previously configured auto top-up settings
            syncWithUserProfile();
            
            // Fetch subscription details to sync monthly toggle
            await fetchSubscriptionDetails();
            
            // SIMPLIFIED: Use hardcoded defaults instead of fetching invoice
            // Default values:
            // - Low balance: 21,000 credits (recommended tier, same as monthly)
            // - Monthly: 21,000 credits + 1,000 bonus = 22,000 total (recommended tier)
            const profile = $userProfile;
            
            // Only set defaults if user doesn't already have low balance settings configured
            if (!profile.auto_topup_low_balance_amount) {
                console.debug('[AutoTopUp] No existing low balance settings, using default values...');
                
                // Default: 21,000 credits for low balance auto top-up (recommended tier)
                const defaultLowBalanceAmount = 21000;
                const defaultTier = pricingTiers.find(tier => tier.credits === defaultLowBalanceAmount);
                
                if (defaultTier) {
                    const currentCurrency = (profile.auto_topup_low_balance_currency || currency || 'eur').toLowerCase() as 'eur' | 'usd' | 'jpy';
                    lowBalanceAmount = defaultLowBalanceAmount;
                    lowBalancePrice = defaultTier.price[currentCurrency] || defaultTier.price.eur;
                    
                    console.debug('[AutoTopUp] Set default low balance values:', {
                        amount: lowBalanceAmount,
                        price: lowBalancePrice,
                        currency: currentCurrency
                    });
                } else {
                    console.warn('[AutoTopUp] Could not find pricing tier for default low balance amount (21000), using fallback');
                    // Fallback: keep defaults set in state initialization (21000 credits, 20 EUR)
                }
            } else {
                console.debug('[AutoTopUp] User has existing low balance settings, using those:', {
                    amount: profile.auto_topup_low_balance_amount,
                    currency: profile.auto_topup_low_balance_currency
                });
            }
        } catch (error) {
            console.error('[AutoTopUp] Error loading settings:', error);
        } finally {
            isLoadingSettings = false;
        }
    });

    // Subscribe to user profile changes to keep toggles in sync
    $effect(() => {
        const profile = $userProfile;
        // Update low balance toggle when profile changes
        if (profile.auto_topup_low_balance_enabled !== undefined) {
            lowBalanceEnabled = profile.auto_topup_low_balance_enabled;
        }
    });

    // Handle finish button
    async function handleFinish() {
        isProcessing = true;
        lowBalanceEmailError = null;

        try {
            // CRITICAL: Save low balance auto top-up settings if enabled
            // This ensures settings are persisted to backend (cache and Directus)
            if (lowBalanceEnabled && lowBalanceAmount > 0) {
                try {
                    const decryptedEmail = await getEmailDecryptedWithMasterKey();
                    if (!decryptedEmail) {
                        lowBalanceEmailError = 'Email could not be decrypted on this device. Disable low-balance auto top-up or log in again to unlock encryption keys.';
                        isProcessing = false;
                        return;
                    }
                    console.debug('[AutoTopUp] Saving low balance auto top-up settings:', {
                        enabled: lowBalanceEnabled,
                        amount: lowBalanceAmount,
                        currency: currency,
                        hasDecryptedEmail: Boolean(decryptedEmail)
                    });
                    
                    const response = await fetch(getApiUrl() + apiEndpoints.settings.autoTopUp.lowBalance, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'include',
                        body: JSON.stringify({
                            enabled: lowBalanceEnabled,
                            threshold: lowBalanceThreshold, // Always 100 credits (fixed)
                            amount: lowBalanceAmount,
                            currency: currency.toLowerCase(),
                            email: decryptedEmail
                        })
                    });

                    if (!response.ok) {
                        const errorData = await response.json().catch(() => ({}));
                        console.error('[AutoTopUp] Failed to save low balance settings:', errorData.detail || 'Unknown error');
                        // Continue anyway - user can set up later in settings
                    } else {
                        console.debug('[AutoTopUp] Low balance auto top-up settings saved successfully');
                        
                        // Update user profile store with new settings
                        userProfile.update(profile => ({
                            ...profile,
                            auto_topup_low_balance_enabled: lowBalanceEnabled,
                            auto_topup_low_balance_threshold: 100, // Always 100 credits
                            auto_topup_low_balance_amount: lowBalanceAmount,
                            auto_topup_low_balance_currency: currency.toLowerCase()
                        }));
                    }
                } catch (error) {
                    console.error('[AutoTopUp] Error saving low balance settings:', error);
                    // Continue anyway - user can set up later in settings
                }
            } else if (!lowBalanceEnabled) {
                // If disabled, ensure settings are cleared (save with enabled=false)
                try {
                    const response = await fetch(getApiUrl() + apiEndpoints.settings.autoTopUp.lowBalance, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'include',
                        body: JSON.stringify({
                            enabled: false,
                            threshold: lowBalanceThreshold,
                            amount: lowBalanceAmount || 10000, // Use current amount or default
                            currency: currency.toLowerCase()
                        })
                    });

                    if (response.ok) {
                        // Update user profile store
                        userProfile.update(profile => ({
                            ...profile,
                            auto_topup_low_balance_enabled: false
                        }));
                    }
                } catch (error) {
                    console.error('[AutoTopUp] Error disabling low balance settings:', error);
                    // Continue anyway
                }
            }

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
                    // The parent component will handle completion (including updating last_opened)
                    return;
                }
            } else if (monthlyEnabled && !paymentMethodSaved) {
                // Payment method wasn't saved - can't activate subscription
                // This shouldn't happen as the toggle is disabled, but handle it defensively
                console.error('Cannot activate subscription: Payment method was not saved');
                // Still complete signup - user has finished the signup flow
                // They can set up auto top-up later in settings
            }

            // If no subscription activation needed, complete signup
            // CRITICAL: Always call oncomplete when finish button is pressed
            // This ensures last_opened is updated to '/chat/new' so signup doesn't reopen on reload
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
            // Even on error, try to complete signup if possible
            // This ensures user doesn't get stuck in signup flow
            if (oncomplete && !monthlyEnabled) {
                oncomplete(new CustomEvent('complete', {
                    detail: {
                        lowBalanceEnabled: lowBalanceEnabled,
                        monthlyEnabled: false
                    }
                }));
            }
        }
    }

    async function handleLowBalanceToggleChange(event: CustomEvent<{ checked: boolean }>) {
        lowBalanceEmailError = null;
        if (!event.detail.checked) return;

        const decryptedEmail = await getEmailDecryptedWithMasterKey();
        if (!decryptedEmail) {
            lowBalanceEmailError = 'Email could not be decrypted on this device. Log in again to unlock encryption keys.';
            lowBalanceEnabled = false;
        }
    }
</script>

<!-- Auto top-up header with icon -->
<div class="header-section">
    <div class="icon settings_size refund">
    </div>
    <div class="header-text">
        {$text('settings.billing.auto_topup.text')}
    </div>
</div>

<!-- Introductory text - matches screenshot exactly -->
<div class="intro-text">
    {@html $text('settings.billing.auto_topup_intro.text')}
</div>

<!-- Low Balance Auto Top-Up Toggle -->
<div class="toggle-option">
    <div class="toggle-row">
        <Toggle bind:checked={lowBalanceEnabled} id="low-balance-toggle" disabled={isProcessing} on:change={handleLowBalanceToggleChange} />
        <div class="warning-icon"></div>
        <label for="low-balance-toggle" class="option-label">
            {$text('settings.billing.on_low_balance.text')}
        </label>
    </div>
    {#if lowBalanceEmailError}
        <div class="error-message">{lowBalanceEmailError}</div>
    {/if}
    {#if lowBalanceEnabled}
        <div class="option-description">
            {@html $text('settings.billing.auto_topup_low_balance_description.text')
                .replace('{lowbalancethreshold}', formatCredits(lowBalanceThreshold))
                .replace('{credits}', formatCredits(lowBalanceAmount))
                .replace('{price}', formatPrice(lowBalancePrice, currency))}
        </div>
    {/if}
</div>

<!-- Monthly Auto Top-Up Toggle -->
<div class="toggle-option">
    <div class="toggle-row">
        <Toggle 
            bind:checked={monthlyEnabled} 
            id="monthly-toggle" 
            disabled={isProcessing || !paymentMethodSaved} 
        />
        <div class="calendar-icon"></div>
        <label for="monthly-toggle" class="option-label">
            {$text('settings.billing.monthly.text')}
        </label>
    </div>
    {#if !paymentMethodSaved}
        <div class="error-message">
            {$text('settings.billing.auto_topup_payment_method_error.text')}
        </div>
    {:else if monthlyEnabled}
        <div class="option-description">
            {$text('settings.billing.auto_topup_monthly_description.text')
                .replace('{credits}', formatCredits(totalCredits))
                .replace('{price}', formatPrice(monthlyPrice, currency))}
            {#if bonusCredits > 0}
                <div class="recommended-badge">
                    <div class="gift-icon"></div>
                    <strong>{$text('settings.billing.auto_topup_bonus_credits.text')
                        .replace('{bonuscredits}', formatCredits(bonusCredits))}</strong>
                </div>
            {/if}
        </div>
    {/if}
</div>

<!-- Help text -->
<div class="help-text">
    {$text('settings.billing.auto_topup_settings_help.text')}
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

<style>
    /* Match the container structure used in PaymentTopContent for payment form */
    .separated-block {
        position: relative;
        width: 95%;
        max-width: 400px;
        height: 100%;
        background-color: var(--color-grey-20);
        border-radius: 16px;
        padding: 16px;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
        display: flex;
        flex-direction: column;
        overflow-y: auto; /* Allow scrolling if content exceeds container */
        overflow-x: hidden;
        box-sizing: border-box;
    }

    .header-section {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 12px;
    }

    .icon-wrapper {
        width: 40px;
        height: 40px;
        background-color: #1E3A8A; /* Dark blue background */
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .auto-topup-icon {
        width: 24px;
        height: 24px;
        background-color: white;
        mask-image: url('@openmates/ui/static/icons/reload.svg');
        mask-size: contain;
        mask-repeat: no-repeat;
        mask-position: center;
    }

    .header-text {
        font-size: 18px;
        font-weight: 600;
        color: var(--color-grey-100);
    }

    .intro-text {
        color: var(--color-grey-100);
        font-size: 16px;
        line-height: 1.5;
        margin-bottom: 15px;
        margin-top: 15px;
    }

    .toggle-option {
        display: flex;
        flex-direction: column;
        gap: 8px;
        margin-bottom: 10px;
    }

    .toggle-row {
        display: flex;
        align-items: center;
        gap: 10px;
        cursor: pointer;
    }

    .warning-icon {
        width: 20px;
        height: 20px;
        background: var(--color-primary); /* Blue color */
        mask-image: url('@openmates/ui/static/icons/warning.svg');
        mask-size: contain;
        mask-repeat: no-repeat;
        mask-position: center;
    }

    .calendar-icon {
        width: 20px;
        height: 20px;
        background: var(--color-primary); /* Blue color */
        /* Using time icon as calendar icon alternative */
        mask-image: url('@openmates/ui/static/icons/time.svg');
        mask-size: contain;
        mask-repeat: no-repeat;
        mask-position: center;
    }

    .option-label {
        color: var(--color-primary-end); /* Blue color */
        font-size: 16px;
        font-weight: 600;
        cursor: pointer;
        flex: 1;
        text-align: left;
    }

    .option-description {
        color: var(--color-grey-70);
        font-size: 14px;
        line-height: 1.5;
        padding-left: 60px; /* Align with toggle + icon + label */
        text-align: left;
        margin-top: -8px;
    }

    .recommended-badge {
        background: var(--color-primary);
        border-radius: 19px;
        padding: 6px 12px;
        display: flex;
        align-items: center;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
        z-index: 2;
        margin-top: 5px;
    }

    .recommended-badge strong {
        color: white;
        margin-left: 10px;
    }

    .gift-icon {
        width: 16px;
        height: 16px;
        background-color: white;
        mask-image: url('@openmates/ui/static/icons/gift.svg');
        mask-size: contain;
        mask-repeat: no-repeat;
        mask-position: center;
    }

    .help-text {
        color: var(--color-grey-70);
        font-size: 14px;
        text-align: center;
        margin-bottom: 15px;
    }

    .error-message {
        background-color: var(--color-grey-10);
        color: #ff6b6b;
        padding: 8px 12px;
        border-radius: 8px;
        font-size: 14px;
        line-height: 1.4;
        margin-top: 6px;
        border: 1px solid var(--color-grey-30);
    }
</style>
