<!--
Storage Overview — Account Settings sub-page.

Shows total usage, progress bar, billing info, and a per-category breakdown.
Each category row is tappable and navigates to a dedicated file-list sub-page
(account/storage/<category>) where the user can view, open, and delete files.

Categories with zero files are hidden.

Below the breakdown an info notice explains that invoice PDFs are stored
separately, are free of charge, and auto-deleted after 10 years per §147 AO.

API endpoint used here:
  GET /v1/settings/storage  →  overview (totals, billing, breakdown)

File-list endpoints are handled in SettingsStorageFiles.svelte.
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';
    import { SettingsSectionHeading } from '../../settings/elements';
    import { getApiEndpoint } from '../../../config/api';

    const dispatch = createEventDispatcher();

    // =========================================================================
    // TYPES
    // =========================================================================

    interface StorageCategoryBreakdown {
        category: string;
        bytes_used: number;
        file_count: number;
    }

    interface StorageOverview {
        total_bytes: number;
        total_files: number;
        free_bytes: number;
        billable_gb: number;
        credits_per_gb_per_week: number;
        weekly_cost_credits: number;
        next_billing_date: number | null;
        last_billed_at: number | null;
        breakdown: StorageCategoryBreakdown[];
    }

    // =========================================================================
    // STATE
    // =========================================================================

    /** Storage overview from the API. Null until loaded. */
    let overview = $state<StorageOverview | null>(null);

    /** True while the initial fetch is in progress. */
    let isLoading = $state(true);

    /** Error message if the API call fails. */
    let errorMessage = $state<string | null>(null);

    // =========================================================================
    // DERIVED
    // =========================================================================

    /** Percentage of the free 1 GB tier used (0–100), capped at 100. */
    let usedPercent = $derived(
        overview
            ? Math.min(100, Math.round((overview.total_bytes / overview.free_bytes) * 100))
            : 0
    );

    /** True when the user is within the free 1 GB tier. */
    let isWithinFreeTier = $derived(
        overview ? overview.total_bytes <= overview.free_bytes : true
    );

    /**
     * Breakdown rows that actually have files (file_count > 0).
     * Categories with no files are not shown.
     */
    let visibleBreakdown = $derived(
        overview ? overview.breakdown.filter(b => b.file_count > 0) : []
    );

    // =========================================================================
    // HELPERS
    // =========================================================================

    /**
     * Format a byte count into a human-readable string (1024-based).
     */
    function formatBytes(bytes: number): string {
        if (bytes === 0) return '0 B';
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(1024));
        const value = bytes / Math.pow(1024, i);
        return i >= 2 ? `${value.toFixed(1)} ${units[i]}` : `${Math.round(value)} ${units[i]}`;
    }

    /**
     * Format a Unix timestamp into a localised short date string.
     */
    function formatDate(ts: number): string {
        return new Date(ts * 1000).toLocaleDateString(undefined, {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
        });
    }

    /**
     * Map a backend category name to the matching i18n key.
     */
    function categoryLabel(category: string): string {
        const keyMap: Record<string, string> = {
            images:   'settings.storage.storage_category_images',
            videos:   'settings.storage.storage_category_videos',
            audio:    'settings.storage.storage_category_audio',
            pdf:      'settings.storage.storage_category_pdf',
            code:     'settings.storage.storage_category_code',
            docs:     'settings.storage.storage_category_docs',
            sheets:   'settings.storage.storage_category_sheets',
            archives: 'settings.storage.storage_category_archives',
            other:    'settings.storage.storage_category_other',
        };
        return keyMap[category] ?? category;
    }

    // =========================================================================
    // EFFECTS
    // =========================================================================

    /**
     * Fetch storage overview on mount.
     * Re-runs on remount so stats are fresh after returning from a file-list
     * sub-page where files may have been deleted.
     */
    $effect(() => {
        fetchStorageOverview();
    });

    // =========================================================================
    // API
    // =========================================================================

    async function fetchStorageOverview(): Promise<void> {
        isLoading = true;
        errorMessage = null;

        try {
            const response = await fetch(getApiEndpoint('/v1/settings/storage'), {
                credentials: 'include',
            });

            if (!response.ok) {
                const body = await response.text().catch(() => '');
                throw new Error(`HTTP ${response.status}: ${body || response.statusText}`);
            }

            overview = await response.json();
        } catch (err) {
            console.error('[SettingsStorage] Failed to load storage overview:', err);
            errorMessage = err instanceof Error ? err.message : String(err);
        } finally {
            isLoading = false;
        }
    }

    // =========================================================================
    // NAVIGATION
    // =========================================================================

    /**
     * Navigate to the file list sub-page for a given category.
     * Route: account/storage/<category>
     */
    function openCategory(category: string): void {
        dispatch('openSettings', {
            settingsPath: `account/storage/${category}`,
            direction: 'forward',
            icon: 'storage',
            title: $text(categoryLabel(category)),
        });
    }
</script>

<div class="storage-container">

    <!-- ── Loading ─────────────────────────────────────────────────────────── -->
    {#if isLoading}
        <div class="loading-state">
            <div class="spinner"></div>
            <span>{$text('settings.storage.storage_loading')}</span>
        </div>

    <!-- ── Error ───────────────────────────────────────────────────────────── -->
    {:else if errorMessage}
        <div class="error-state">
            <div class="icon icon_error"></div>
            <p class="error-text">{$text('settings.storage.storage_error')}</p>
            <p class="error-detail">{errorMessage}</p>
            <button class="btn-retry" onclick={fetchStorageOverview}>
                Retry
            </button>
        </div>

    <!-- ── Loaded ──────────────────────────────────────────────────────────── -->
    {:else if overview}

        <!-- Total usage + progress bar -->
        <div class="usage-card">
            <div class="usage-label">
                {$text('settings.storage.storage_total_used', {
                    values: {
                        used: formatBytes(overview.total_bytes),
                        free: formatBytes(overview.free_bytes),
                    }
                })}
            </div>

            <div
                class="progress-bar"
                role="progressbar"
                aria-valuenow={usedPercent}
                aria-valuemin={0}
                aria-valuemax={100}
            >
                <div
                    class="progress-fill"
                    class:over-limit={!isWithinFreeTier}
                    style="width: {usedPercent}%"
                ></div>
            </div>

            <div class="usage-meta">
                <span class="free-tier-label">
                    {$text('settings.storage.storage_free_tier_label')}: {formatBytes(overview.free_bytes)}
                </span>
                <span class="used-percent">{usedPercent}%</span>
            </div>
        </div>

        <!-- Billing info -->
        <div class="billing-card">
            {#if isWithinFreeTier}
                <div class="free-tier-notice">
                    <div class="icon icon_check"></div>
                    <p>{$text('settings.storage.storage_within_free_tier')}</p>
                </div>
            {:else}
                <div class="billing-row">
                    <span class="billing-key">{$text('settings.storage.storage_billable')}</span>
                    <span class="billing-value">{overview.billable_gb} GB</span>
                </div>
                <div class="billing-row">
                    <span class="billing-key">{$text('settings.storage.storage_weekly_cost')}</span>
                    <span class="billing-value highlight">
                        {$text('settings.storage.storage_credits_per_week', {
                            values: { credits: overview.weekly_cost_credits }
                        })}
                    </span>
                </div>
                {#if overview.next_billing_date}
                    <div class="billing-row">
                        <span class="billing-key">{$text('settings.storage.storage_next_billing')}</span>
                        <span class="billing-value">{formatDate(overview.next_billing_date)}</span>
                    </div>
                {/if}
            {/if}

            {#if overview.last_billed_at}
                <div class="billing-row muted">
                    <span class="billing-key">{$text('settings.storage.storage_last_billed')}</span>
                    <span class="billing-value">{formatDate(overview.last_billed_at)}</span>
                </div>
            {/if}
        </div>

        <!-- Per-category breakdown — only categories with files are shown -->
        {#if visibleBreakdown.length > 0}
            <div class="breakdown-section">
                <SettingsSectionHeading title={$text('settings.storage.storage_breakdown_title')} icon="cloud" />

                <!--
                    Each row is a tappable SettingsItem that navigates to the
                    dedicated file-list sub-page for that category.
                    The subtitle shows file count + size.
                -->
                {#each visibleBreakdown as item}
                    <SettingsItem
                        type="submenu"
                        icon="storage"
                        title={$text(categoryLabel(item.category))}
                        subtitle="{$text('settings.storage.storage_files_count', {
                            values: { count: item.file_count }
                        })} · {formatBytes(item.bytes_used)}"
                        onClick={() => openCategory(item.category)}
                    />
                {/each}
            </div>
        {/if}

        <!-- Invoice PDF info notice -->
        <div class="invoice-notice">
            <div class="icon icon_info"></div>
            <p class="invoice-notice-text">
                {$text('settings.storage.storage_invoice_notice')}
            </p>
        </div>

    {/if}
</div>

<style>
    /* ── Container ─────────────────────────────────────────────────────────── */
    .storage-container {
        padding: 24px;
        max-width: 560px;
        display: flex;
        flex-direction: column;
        gap: 20px;
    }

    /* ── Loading ───────────────────────────────────────────────────────────── */
    .loading-state {
        display: flex;
        align-items: center;
        gap: 12px;
        color: var(--color-grey-60);
        padding: 32px 0;
    }

    .spinner {
        width: 20px;
        height: 20px;
        border: 2px solid var(--color-grey-30);
        border-top-color: var(--color-primary);
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
        flex-shrink: 0;
    }

    @keyframes spin {
        to { transform: rotate(360deg); }
    }

    /* ── Error ─────────────────────────────────────────────────────────────── */
    .error-state {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 8px;
        padding: 20px;
        background: var(--color-danger-light);
        border: 1px solid var(--color-danger);
        border-radius: 12px;
    }

    .error-state .icon {
        width: 24px;
        height: 24px;
        background: var(--color-danger);
        mask-size: contain;
        mask-repeat: no-repeat;
    }

    .error-text {
        font-weight: 600;
        color: var(--color-danger);
        margin: 0;
    }

    .error-detail {
        font-size: 13px;
        color: var(--color-danger);
        margin: 0;
        word-break: break-word;
    }

    .btn-retry {
        margin-top: 8px;
        padding: 8px 16px;
        background: var(--color-danger);
        color: white;
        border: none;
        border-radius: 6px;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        transition: opacity 0.15s;
    }

    .btn-retry:hover {
        opacity: 0.85;
    }

    /* ── Usage card ────────────────────────────────────────────────────────── */
    .usage-card {
        background: var(--color-grey-10);
        border-radius: 12px;
        padding: 20px;
    }

    .usage-label {
        font-size: 15px;
        font-weight: 600;
        color: var(--color-grey-80);
        margin-bottom: 12px;
    }

    .progress-bar {
        height: 8px;
        background: var(--color-grey-20);
        border-radius: 4px;
        overflow: hidden;
        margin-bottom: 8px;
    }

    .progress-fill {
        height: 100%;
        background: var(--color-primary);
        border-radius: 4px;
        transition: width 0.4s ease;
    }

    .progress-fill.over-limit {
        background: var(--color-warning);
    }

    .usage-meta {
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    .free-tier-label {
        font-size: 13px;
        color: var(--color-grey-60);
    }

    .used-percent {
        font-size: 13px;
        font-weight: 600;
        color: var(--color-grey-70);
    }

    /* ── Billing card ──────────────────────────────────────────────────────── */
    .billing-card {
        background: var(--color-grey-10);
        border-radius: 12px;
        padding: 20px;
        display: flex;
        flex-direction: column;
        gap: 12px;
    }

    .free-tier-notice {
        display: flex;
        align-items: flex-start;
        gap: 12px;
    }

    .free-tier-notice .icon {
        width: 20px;
        height: 20px;
        background: var(--color-success);
        flex-shrink: 0;
        margin-top: 2px;
    }

    .free-tier-notice p {
        margin: 0;
        color: var(--color-grey-70);
        font-size: 14px;
        line-height: 1.5;
    }

    .billing-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
    }

    .billing-row.muted {
        opacity: 0.7;
    }

    .billing-key {
        font-size: 14px;
        color: var(--color-grey-60);
    }

    .billing-value {
        font-size: 14px;
        font-weight: 600;
        color: var(--color-grey-80);
    }

    .billing-value.highlight {
        color: var(--color-primary);
    }

    /* ── Breakdown section ─────────────────────────────────────────────────── */
    .breakdown-section {
        background: var(--color-grey-10);
        border-radius: 12px;
        padding: 4px 0;
        overflow: hidden;
    }


    /* ── Invoice notice ────────────────────────────────────────────────────── */
    .invoice-notice {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        padding: 14px 16px;
        background: var(--color-grey-10);
        border-radius: 10px;
        border: 1px solid var(--color-grey-20);
    }

    .invoice-notice .icon {
        width: 18px;
        height: 18px;
        background: var(--color-grey-50);
        mask-size: contain;
        mask-repeat: no-repeat;
        flex-shrink: 0;
        margin-top: 1px;
    }

    .invoice-notice-text {
        margin: 0;
        font-size: 13px;
        color: var(--color-grey-60);
        line-height: 1.5;
    }
</style>
