<!-- frontend/packages/ui/src/components/settings/SettingsPricing.svelte
     Pricing page — shown only to non-authenticated users.
     
     Displays credit packages with prices so visitors can explore costs before signing up.
     Also links to the App Store (browsable without login) and highlights the AI Ask skill,
     which is the biggest cost driver.
     
     This page is intentionally read-only. No purchase flow is exposed here —
     users must sign in to buy credits.
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { pricingTiers } from '../../config/pricing';
    import SettingsItem from '../SettingsItem.svelte';

    const dispatch = createEventDispatcher();

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

<!-- Short description explaining what credits are for -->
<p class="pricing-description">{$text('settings.pricing.description')}</p>

<!-- Credit Packages Section -->
<SettingsItem
    type="heading"
    icon="coins"
    title={$text('settings.pricing.packages_heading')}
/>

{#each pricingTiers as tier}
    <div class="pricing-tier" class:recommended={tier.recommended}>
        <div class="tier-main">
            <span class="tier-credits">
                {formatCredits(tier.credits)} {$text('settings.billing.credits')}
            </span>
            {#if tier.recommended}
                <span class="tier-badge">{$text('settings.pricing.recommended')}</span>
            {/if}
        </div>
        <div class="tier-details">
            <span class="tier-price-eur">€{tier.price.eur}</span>
            <span class="tier-price-sep"> / </span>
            <span class="tier-price-usd">${tier.price.usd}</span>
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
<SettingsItem
    type="heading"
    icon="app"
    title={$text('settings.pricing.explore_heading')}
/>

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
    .pricing-description {
        font-size: 0.85rem;
        color: var(--color-text-muted);
        padding: 12px 16px 4px;
        margin: 0;
        line-height: 1.4;
    }

    .pricing-vat-note {
        font-size: 0.78rem;
        color: var(--color-text-muted);
        padding: 4px 16px 12px;
        margin: 0;
        line-height: 1.4;
        opacity: 0.75;
    }

    .pricing-tier {
        display: flex;
        flex-direction: column;
        gap: 4px;
        padding: 12px 16px;
        border-bottom: 1px solid var(--color-grey-20);
        transition: background-color 0.15s ease;
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
        gap: 8px;
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
        border-radius: 10px;
        text-transform: uppercase;
        letter-spacing: 0.03em;
    }

    .tier-details {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 4px;
    }

    .tier-price-eur,
    .tier-price-usd {
        font-size: 0.875rem;
        color: var(--color-grey-70);
    }

    .tier-price-sep {
        font-size: 0.875rem;
        color: var(--color-grey-40);
    }

    .tier-bonus {
        font-size: 0.78rem;
        color: var(--color-primary);
        margin-left: 6px;
        font-weight: 500;
    }
</style>
