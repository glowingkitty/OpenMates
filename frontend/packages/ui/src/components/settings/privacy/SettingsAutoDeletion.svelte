<!--
Auto Deletion Period Editor - Allows users to change the auto-deletion period
for a specific data category (chats, files, usage_data).

The category is determined from the activeSettingsView prop:
  "privacy/auto-deletion/chats"      → chats
  "privacy/auto-deletion/files"      → files
  "privacy/auto-deletion/usage_data" → usage_data

For "chats", the selected period is persisted to the server via
POST /v1/settings/auto-delete-chats and stored locally in the userProfile store
so subsequent visits show the correct selection without a network round-trip.

"files" and "usage_data" categories are not yet backed by a server endpoint;
their selections are therefore visual-only for now (same as before).
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';
    import { getApiUrl, apiEndpoints } from '../../../config/api';
    import { userProfile, updateProfile } from '../../../stores/userProfile';

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

    /**
     * Maps the server-stored integer day count back to a UI period key.
     * Mirrors _PERIOD_TO_DAYS in backend/core/api/app/schemas/settings.py.
     */
    const DAYS_TO_PERIOD: Record<number, string> = {
        30:   '30d',
        60:   '60d',
        90:   '90d',
        180:  '6m',
        365:  '1y',
        730:  '2y',
        1825: '5y',
    };

    /** Default periods per category (shown when the user has not configured a period yet) */
    const DEFAULT_PERIODS: Record<string, string> = {
        chats:      '90d',
        files:      '90d',
        usage_data: '1y',
    };

    // ─── Selected Period State ───────────────────────────────────────────────

    let selectedPeriod = $state('');
    let isSaving = $state(false);

    /**
     * Derive the initial period from the user profile store for the "chats" category.
     * For other categories we fall back to the hard-coded default (server not yet wired).
     */
    $effect(() => {
        if (category === 'chats') {
            const days = $userProfile?.auto_delete_chats_after_days;
            if (days == null) {
                // null / undefined means "never"
                selectedPeriod = 'never';
            } else if (days in DAYS_TO_PERIOD) {
                selectedPeriod = DAYS_TO_PERIOD[days];
            } else {
                // Unknown value stored on server — fall back to default
                selectedPeriod = DEFAULT_PERIODS.chats;
            }
        } else {
            selectedPeriod = DEFAULT_PERIODS[category] || '90d';
        }
    });

    // ─── Icon per Category ───────────────────────────────────────────────────

    const CATEGORY_ICONS: Record<string, string> = {
        chats:      'chat',
        files:      'files',
        usage_data: 'usage',
    };

    let categoryIcon = $derived(CATEGORY_ICONS[category] || 'delete');

    // ─── Save Handler ────────────────────────────────────────────────────────

    async function selectPeriod(periodKey: string) {
        if (periodKey === selectedPeriod || isSaving) return;

        selectedPeriod = periodKey;

        if (category === 'chats') {
            // Persist to the server and update the local profile store.
            isSaving = true;
            try {
                const response = await fetch(getApiUrl() + apiEndpoints.settings.autoDeleteChats, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                    },
                    body: JSON.stringify({ period: periodKey }),
                    credentials: 'include',
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    console.error(
                        `[SettingsAutoDeletion] Failed to save period for chats: ` +
                        `${response.status} – ${errorData?.detail ?? 'unknown error'}`
                    );
                    // Leave selectedPeriod as the newly-selected value so the UI
                    // still reflects user intent; it will be reconciled on next mount.
                } else {
                    // Mirror to the local profile store so sibling components and
                    // subsequent mounts read the up-to-date value without a refetch.
                    const PERIOD_TO_DAYS: Record<string, number | null> = {
                        '30d':  30,
                        '60d':  60,
                        '90d':  90,
                        '6m':   180,
                        '1y':   365,
                        '2y':   730,
                        '5y':   1825,
                        'never': null,
                    };
                    updateProfile({ auto_delete_chats_after_days: PERIOD_TO_DAYS[periodKey] });
                    console.debug(`[SettingsAutoDeletion] Saved period for chats: ${periodKey}`);
                }
            } catch (err) {
                console.error('[SettingsAutoDeletion] Network error while saving period:', err);
            } finally {
                isSaving = false;
            }
        } else {
            // For "files" and "usage_data" the server endpoint is not yet implemented.
            // The selection is visual-only until those categories are wired up.
            console.debug(`[SettingsAutoDeletion] Selected period for ${category}: ${periodKey} (visual-only)`);
        }

        // Navigate back to the privacy settings page after a brief delay
        // so the user can see their selection take effect visually.
        setTimeout(() => {
            dispatch('openSettings', {
                settingsPath: 'privacy',
                direction: 'backward',
                icon: 'privacy',
                title: $text('settings.privacy')
            });
        }, 200);
    }
</script>

<!-- Category description -->
<div class="auto-deletion-description">
    <p class="description-text">
        {$text(`settings.privacy.auto_deletion.${category}.description`)}
    </p>
</div>

<!-- Period options list -->
<SettingsItem
    type="heading"
    icon={categoryIcon}
    title={$text(`settings.privacy.auto_deletion.select_period`)}
/>

{#each periodOptions as option}
    <button
        class="period-option"
        class:selected={selectedPeriod === option.key}
        class:saving={isSaving}
        onclick={() => selectPeriod(option.key)}
        disabled={isSaving}
    >
        <span class="period-label">
            {$text(`settings.privacy.${option.translationKey}`)}
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

    .period-option.saving {
        opacity: 0.6;
        cursor: wait;
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
