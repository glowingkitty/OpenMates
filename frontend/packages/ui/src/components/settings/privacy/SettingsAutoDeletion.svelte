<!--
Auto Deletion Period Editor - Allows users to change the auto-deletion period
for a specific data category (chats, files, usage_data).

The category is determined from the activeSettingsView prop:
  "privacy/auto-deletion/chats"      → chats
  "privacy/auto-deletion/files"      → files
  "privacy/auto-deletion/usage_data" → usage_data

Each category has a set of selectable period options. The selected period is
persisted to the user's privacy settings.
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';

    const dispatch = createEventDispatcher();

    // ─── Props ───────────────────────────────────────────────────────────────

    interface Props {
        activeSettingsView?: string;
    }

    let { activeSettingsView = '' }: Props = $props();

    // ─── Determine Category ──────────────────────────────────────────────────

    /**
     * Extract the category from the active settings view path.
     * E.g., "privacy/auto-deletion/chats" → "chats"
     */
    let category = $derived(activeSettingsView.split('/').pop() || 'chats');

    // ─── Period Options ──────────────────────────────────────────────────────

    /**
     * Available auto-deletion period options per category.
     * Each option has a key (for persistence) and uses a translation key for display.
     *
     * Chats and Files: shorter retention options (30d to never)
     * Usage data: longer retention options (90d to never)
     */
    interface PeriodOption {
        /** Unique key for persistence (e.g., "30d", "1y") */
        key: string;
        /** Translation key suffix for the option label */
        translationKey: string;
    }

    const PERIOD_OPTIONS_SHORT: PeriodOption[] = [
        { key: '30d', translationKey: 'privacy.auto_deletion.period.30_days' },
        { key: '60d', translationKey: 'privacy.auto_deletion.period.60_days' },
        { key: '90d', translationKey: 'privacy.auto_deletion.period.90_days' },
        { key: '6m', translationKey: 'privacy.auto_deletion.period.6_months' },
        { key: '1y', translationKey: 'privacy.auto_deletion.period.1_year' },
        { key: '2y', translationKey: 'privacy.auto_deletion.period.2_years' },
        { key: '5y', translationKey: 'privacy.auto_deletion.period.5_years' },
        { key: 'never', translationKey: 'privacy.auto_deletion.period.never' },
    ];

    const PERIOD_OPTIONS_LONG: PeriodOption[] = [
        { key: '90d', translationKey: 'privacy.auto_deletion.period.90_days' },
        { key: '6m', translationKey: 'privacy.auto_deletion.period.6_months' },
        { key: '1y', translationKey: 'privacy.auto_deletion.period.1_year' },
        { key: '2y', translationKey: 'privacy.auto_deletion.period.2_years' },
        { key: '5y', translationKey: 'privacy.auto_deletion.period.5_years' },
        { key: 'never', translationKey: 'privacy.auto_deletion.period.never' },
    ];

    /** Get the period options for the current category */
    let periodOptions = $derived(
        category === 'usage_data' ? PERIOD_OPTIONS_LONG : PERIOD_OPTIONS_SHORT
    );

    /** Default periods per category (matching the values shown on the parent page) */
    const DEFAULT_PERIODS: Record<string, string> = {
        chats: '90d',
        files: '90d',
        usage_data: '1y',
    };

    // ─── Selected Period State ───────────────────────────────────────────────

    let selectedPeriod = $state('');

    // Initialize with the default period for this category
    $effect(() => {
        // TODO: Load persisted period from user settings when backend supports it
        selectedPeriod = DEFAULT_PERIODS[category] || '90d';
    });

    // ─── Icon per Category ───────────────────────────────────────────────────

    const CATEGORY_ICONS: Record<string, string> = {
        chats: 'chat',
        files: 'files',
        usage_data: 'usage',
    };

    let categoryIcon = $derived(CATEGORY_ICONS[category] || 'delete');

    // ─── Save Handler ────────────────────────────────────────────────────────

    function selectPeriod(periodKey: string) {
        selectedPeriod = periodKey;

        // TODO: Persist the selected period to the server via user profile settings
        // For now, the selection is visual-only. Backend persistence will be added
        // when the auto-deletion feature is implemented server-side.
        console.debug(`[SettingsAutoDeletion] Selected period for ${category}: ${periodKey}`);

        // Navigate back to the privacy settings page after a brief delay
        // so the user can see their selection take effect
        setTimeout(() => {
            dispatch('openSettings', {
                settingsPath: 'privacy',
                direction: 'backward',
                icon: 'privacy',
                title: $text('settings.privacy.privacy')
            });
        }, 200);
    }
</script>

<!-- Category description -->
<div class="auto-deletion-description">
    <p class="description-text">
        {$text(`settings.privacy.privacy.auto_deletion.${category}.description`)}
    </p>
</div>

<!-- Period options list -->
<SettingsItem
    type="heading"
    icon={categoryIcon}
    title={$text(`settings.privacy.privacy.auto_deletion.select_period`)}
/>

{#each periodOptions as option}
    <button
        class="period-option"
        class:selected={selectedPeriod === option.key}
        onclick={() => selectPeriod(option.key)}
    >
        <span class="period-label">
            {$text(`settings.privacy.privacy.${option.translationKey}`)}
        </span>
        {#if selectedPeriod === option.key}
            <span class="check-mark">&#10003;</span>
        {/if}
    </button>
{/each}

<style>
    .auto-deletion-description {
        padding: 10px 16px 16px;
    }

    .description-text {
        font-size: 16px;
        color: var(--color-grey-100);
        line-height: 1.5;
        margin: 0;
    }

    .period-option {
        display: flex;
        align-items: center;
        justify-content: space-between;
        width: 100%;
        padding: 14px 20px;
        margin: 0 0 1px 0;
        border: none;
        background-color: white;
        cursor: pointer;
        font-size: 16px;
        font-family: inherit;
        color: var(--color-grey-100);
        text-align: left;
        transition: background-color 0.15s ease;
    }

    .period-option:first-of-type {
        border-radius: 12px 12px 0 0;
    }

    .period-option:last-of-type {
        border-radius: 0 0 12px 12px;
    }

    .period-option:hover {
        background-color: var(--color-grey-10, #f5f5f5);
    }

    .period-option.selected {
        background-color: var(--color-grey-10, #f5f5f5);
        font-weight: 600;
    }

    .period-label {
        flex: 1;
    }

    .check-mark {
        color: var(--color-cta, #ff553b);
        font-size: 18px;
        font-weight: 700;
        margin-left: 12px;
    }
</style>
