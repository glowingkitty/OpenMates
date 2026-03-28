<!--
Auto Deletion Period Editor - Allows users to change the auto-deletion period
for a specific data category (chats, files, usage_data).

The category is determined from the activeSettingsView prop:
  "privacy/auto-deletion/chats"      → chats
  "privacy/auto-deletion/files"      → files
  "privacy/auto-deletion/usage_data" → usage_data

For "chats": persisted via POST /v1/settings/auto-delete-chats.
For "usage_data": persisted via POST /v1/settings/auto-delete-usage.
  Default is 3 years (1095 days) when the user has not configured a period.
  "never" stores null, which applies the platform default on the server.

"files" category is not yet backed by a server endpoint; its selection is
visual-only for now.
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { SettingsSectionHeading } from '../../settings/elements';
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

    // Usage data has an additional "3 years" option (the platform default).
    // This is longer than the chat options because usage records are lower-value
    // privacy data and the server applies a 3-year default if the user sets "never".
    const PERIOD_OPTIONS_LONG: PeriodOption[] = [
        { key: '90d', translationKey: 'privacy.auto_deletion.period.90_days' },
        { key: '6m', translationKey: 'privacy.auto_deletion.period.6_months' },
        { key: '1y', translationKey: 'privacy.auto_deletion.period.1_year' },
        { key: '2y', translationKey: 'privacy.auto_deletion.period.2_years' },
        { key: '3y', translationKey: 'privacy.auto_deletion.period.3_years' },
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

    /**
     * Maps server-stored integer day count to UI period key for usage data.
     * Mirrors _USAGE_PERIOD_TO_DAYS in backend/core/api/app/schemas/settings.py.
     */
    const USAGE_DAYS_TO_PERIOD: Record<number, string> = {
        90:   '90d',
        180:  '6m',
        365:  '1y',
        730:  '2y',
        1095: '3y',
        1825: '5y',
    };

    /**
     * PERIOD_TO_DAYS map for usage data (mirrors _USAGE_PERIOD_TO_DAYS backend constant).
     */
    const USAGE_PERIOD_TO_DAYS: Record<string, number | null> = {
        '90d':  90,
        '6m':   180,
        '1y':   365,
        '2y':   730,
        '3y':   1095,
        '5y':   1825,
        'never': null,
    };

    /** Default periods per category (shown when the user has not configured a period yet) */
    const DEFAULT_PERIODS: Record<string, string> = {
        chats:      '90d',
        files:      '90d',
        // 3y = 1095 days — matches USAGE_DEFAULT_RETENTION_DAYS on the server.
        // "never" maps to null on the server, which also applies the 3y default.
        usage_data: '3y',
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
                selectedPeriod = 'never';
            } else if (days in DAYS_TO_PERIOD) {
                selectedPeriod = DAYS_TO_PERIOD[days];
            } else {
                selectedPeriod = DEFAULT_PERIODS.chats;
            }
        } else if (category === 'usage_data') {
            const days = $userProfile?.auto_delete_usage_after_days;
            if (days == null) {
                // null = platform default (3 years) — show as '3y' to the user
                selectedPeriod = DEFAULT_PERIODS.usage_data;
            } else if (days in USAGE_DAYS_TO_PERIOD) {
                selectedPeriod = USAGE_DAYS_TO_PERIOD[days];
            } else {
                selectedPeriod = DEFAULT_PERIODS.usage_data;
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
            isSaving = true;
            try {
                const response = await fetch(getApiUrl() + apiEndpoints.settings.autoDeleteChats, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                    body: JSON.stringify({ period: periodKey }),
                    credentials: 'include',
                });
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    console.error(
                        `[SettingsAutoDeletion] Failed to save period for chats: ` +
                        `${response.status} – ${errorData?.detail ?? 'unknown error'}`
                    );
                } else {
                    const PERIOD_TO_DAYS: Record<string, number | null> = {
                        '30d': 30, '60d': 60, '90d': 90, '6m': 180,
                        '1y': 365, '2y': 730, '5y': 1825, 'never': null,
                    };
                    updateProfile({ auto_delete_chats_after_days: PERIOD_TO_DAYS[periodKey] });
                }
            } catch (err) {
                console.error('[SettingsAutoDeletion] Network error while saving period:', err);
            } finally {
                isSaving = false;
            }
        } else if (category === 'usage_data') {
            isSaving = true;
            try {
                const response = await fetch(getApiUrl() + apiEndpoints.settings.autoDeleteUsage, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                    body: JSON.stringify({ period: periodKey }),
                    credentials: 'include',
                });
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    console.error(
                        `[SettingsAutoDeletion] Failed to save period for usage_data: ` +
                        `${response.status} – ${errorData?.detail ?? 'unknown error'}`
                    );
                } else {
                    // null = platform default (3 years); the server applies USAGE_DEFAULT_RETENTION_DAYS
                    updateProfile({ auto_delete_usage_after_days: USAGE_PERIOD_TO_DAYS[periodKey] });
                }
            } catch (err) {
                console.error('[SettingsAutoDeletion] Network error while saving usage period:', err);
            } finally {
                isSaving = false;
            }
        } else {
            // "files" category — server endpoint not yet implemented; selection is visual-only.
        }

        // Navigate back to the privacy settings page after a brief delay
        // so the user can see their selection take effect visually.
        setTimeout(() => {
            dispatch('openSettings', {
                settingsPath: 'privacy',
                direction: 'backward',
                icon: 'privacy',
                title: $text('common.privacy')
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
<SettingsSectionHeading title={$text(`settings.privacy.auto_deletion.select_period`)} icon={categoryIcon} />

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
