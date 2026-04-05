<!-- frontend/packages/ui/src/components/settings/SettingsPricing.svelte
     Pricing page — shown only to non-authenticated users.
     
     Displays credit packages with prices so visitors can explore costs before signing up.
     Also links to the App Store (browsable without login) and highlights the AI Ask skill,
     which is the biggest cost driver.
     
     This page is intentionally read-only. No purchase flow is exposed here —
     users must sign in to buy credits.
     
     Currency selector: defaults to EUR, user can switch to USD via a dropdown.
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { pricingTiers } from '../../config/pricing';
    import SettingsItem from '../SettingsItem.svelte';
    import { SettingsSectionHeading } from './elements';

    const dispatch = createEventDispatcher();

    // Currency selection: EUR by default, can switch to USD
    let selectedCurrency = $state<'eur' | 'usd'>('eur');

    // Format credits with dots as thousand separators (European style: 21.000)
    function formatCredits(credits: number): string {
        return credits.toString().replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    }

    // Navigate to the App Store (available for unauthenticated users)
    function openAppStore() {
        dispatch('openSettings', {
            settingsPath: 'app_store',
            direction: 'forward',
            icon: 'app',
            title: $text('settings.app_store')
        });
    }

    // Navigate directly to the AI Ask skill detail page in the App Store
    function openAiAskSkill() {
        dispatch('openSettings', {
            settingsPath: 'app_store/ai/skill/ask',
            direction: 'forward',
            icon: 'ai',
            title: $text('settings.pricing.ai_ask_skill')
        });
    }
</script>

<!-- Currency selector: EUR (default) / USD -->
<div class="currency-selector">
    <select
        class="currency-select"
        bind:value={selectedCurrency}
        aria-label="Currency"
    >
        <option value="eur">EUR (€)</option>
        <option value="usd">USD ($)</option>
    </select>
</div>

<!-- Credit Packages Section -->
<SettingsSectionHeading title={$text('settings.pricing.packages_heading')} icon="coins" />

{#each pricingTiers as tier}
    <div class="pricing-tier" class:recommended={tier.recommended}>
        <div class="tier-main">
            <span class="tier-credits">
                {formatCredits(tier.credits)} {$text('common.credits')}
            </span>
            {#if tier.recommended}
                <span class="tier-badge">{$text('settings.pricing.recommended')}</span>
            {/if}
        </div>
        <div class="tier-details">
            {#if selectedCurrency === 'eur'}
                <span class="tier-price">€{tier.price.eur}</span>
            {:else}
                <span class="tier-price">${tier.price.usd}</span>
            {/if}
            {#if tier.monthly_auto_top_up_extra_credits}
                <span class="tier-bonus">
                    +{formatCredits(tier.monthly_auto_top_up_extra_credits)} {$text('settings.pricing.bonus_credits')}
                </span>
            {/if}
        </div>
    </div>
{/each}

<p class="pricing-vat-note">{$text('settings.pricing.vat_note')}</p>

<!-- App Store Link Section -->
<SettingsSectionHeading title={$text('settings.pricing.explore_heading')} icon="search" />

<!-- AI Ask skill — highlighted as the biggest cost driver -->
<SettingsItem
    type="submenu"
    icon="ai"
    title={$text('settings.pricing.ai_ask_skill')}
    subtitle={$text('settings.pricing.ai_ask_subtitle')}
    onClick={openAiAskSkill}
/>

<!-- Link to the full App Store -->
<SettingsItem
    type="submenu"
    icon="app"
    title={$text('settings.pricing.browse_app_store')}
    subtitle={$text('settings.pricing.browse_app_store_subtitle')}
    onClick={openAppStore}
/>

<style>
    /* ─── Currency selector ───────────────────────────────────────────────────── */

    .currency-selector {
        display: flex;
        justify-content: flex-end;
        padding: var(--spacing-5) var(--spacing-8) var(--spacing-2);
    }

    .currency-select {
        appearance: none;
        -webkit-appearance: none;
        background-color: var(--color-grey-15, var(--color-grey-20));
        color: var(--color-grey-80);
        border: 1px solid var(--color-grey-20);
        border-radius: var(--radius-3);
        padding: 5px 28px 5px 10px;
        font-size: 0.82rem;
        font-weight: 500;
        cursor: pointer;
        /* Chevron arrow rendered via background SVG */
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%23888' stroke-width='1.5' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
        background-repeat: no-repeat;
        background-position: right 9px center;
        transition: background-color var(--duration-fast) var(--easing-default), border-color var(--duration-fast) var(--easing-default);
    }

    .currency-select:hover {
        background-color: var(--color-grey-20);
        border-color: var(--color-grey-30);
    }

    .currency-select:focus {
        border-color: var(--color-primary);
        box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-primary) 20%, transparent);
    }

    /* ─── Pricing tiers ───────────────────────────────────────────────────────── */

    .pricing-vat-note {
        font-size: 0.78rem;
        color: var(--color-text-muted);
        padding: var(--spacing-2) var(--spacing-8) var(--spacing-6);
        margin: 0;
        line-height: 1.4;
        opacity: 0.75;
    }

    .pricing-tier {
        display: flex;
        flex-direction: column;
        gap: var(--spacing-2);
        padding: var(--spacing-6) var(--spacing-8);
        border-bottom: 1px solid var(--color-grey-20);
        transition: background-color var(--duration-fast) var(--easing-default);
    }

    .pricing-tier:hover {
        background-color: var(--color-grey-10);
    }

    .pricing-tier.recommended {
        background-color: var(--color-grey-10);
    }

    .tier-main {
        display: flex;
        align-items: center;
        gap: var(--spacing-4);
    }

    .tier-credits {
        font-size: 0.95rem;
        font-weight: 600;
        color: var(--color-grey-100);
    }

    .tier-badge {
        font-size: 0.7rem;
        font-weight: 600;
        color: var(--color-primary);
        background-color: color-mix(in srgb, var(--color-primary) 12%, transparent);
        padding: 2px 7px;
        border-radius: var(--radius-4);
        text-transform: uppercase;
        letter-spacing: 0.03em;
    }

    .tier-details {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: var(--spacing-2);
    }

    .tier-price {
        font-size: 0.875rem;
        color: var(--color-grey-70);
    }

    .tier-bonus {
        font-size: 0.78rem;
        color: var(--color-primary);
        margin-left: var(--spacing-3);
        font-weight: 500;
    }
</style>
