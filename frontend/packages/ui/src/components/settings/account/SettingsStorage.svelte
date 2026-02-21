<!--
Storage Overview - Account Settings Sub-page
Displays the current user's storage usage broken down by file-type category,
along with free-tier status and weekly billing information.

API: GET /v1/settings/storage
Pricing: First 1 GB is free; 3 credits per additional GB per week.
Billing runs every Sunday at 03:00 UTC.
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { getApiEndpoint } from '../../../config/api';

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

    /** Storage overview data from the API. Null until loaded. */
    let overview = $state<StorageOverview | null>(null);

    /** True while the initial API fetch is in progress. */
    let isLoading = $state(true);

    /** Error message if the API call fails. Null when no error. */
    let errorMessage = $state<string | null>(null);

    // =========================================================================
    // DERIVED
    // =========================================================================

    /**
     * Percentage of the free 1 GB tier used (0–100), capped at 100.
     * Used to draw the progress bar.
     */
    let usedPercent = $derived(
        overview
            ? Math.min(100, Math.round((overview.total_bytes / overview.free_bytes) * 100))
            : 0
    );

    /** True when the user is within the free 1 GB tier. */
    let isWithinFreeTier = $derived(
        overview ? overview.total_bytes <= overview.free_bytes : true
    );

    // =========================================================================
    // HELPERS
    // =========================================================================

    /**
     * Format a byte count into a human-readable string.
     * Uses 1024-based units (KiB, MiB, GiB).
     */
    function formatBytes(bytes: number): string {
        if (bytes === 0) return '0 B';
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(1024));
        const value = bytes / Math.pow(1024, i);
        // Show one decimal place for MB and above; whole numbers for B/KB.
        return i >= 2 ? `${value.toFixed(1)} ${units[i]}` : `${Math.round(value)} ${units[i]}`;
    }

    /**
     * Format a Unix timestamp into a localised date string.
     * Uses the browser's locale so it matches the user's regional settings.
     */
    function formatDate(ts: number): string {
        return new Date(ts * 1000).toLocaleDateString(undefined, {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
        });
    }

    /**
     * Map an API category name to the matching i18n key suffix.
     * Category names returned by the backend are defined in _classify_mime_type().
     */
    function categoryLabel(category: string): string {
        const keyMap: Record<string, string> = {
            images: 'settings.storage.storage_category_images',
            videos: 'settings.storage.storage_category_videos',
            audio: 'settings.storage.storage_category_audio',
            pdf: 'settings.storage.storage_category_pdf',
            code: 'settings.storage.storage_category_code',
            docs: 'settings.storage.storage_category_docs',
            sheets: 'settings.storage.storage_category_sheets',
            archives: 'settings.storage.storage_category_archives',
            other: 'settings.storage.storage_category_other',
        };
        return keyMap[category] ?? category;
    }

    // =========================================================================
    // EFFECTS
    // =========================================================================

    /**
     * Fetch storage overview from the API when the component mounts.
     * Re-runs automatically if the component is remounted (e.g. navigating away
     * and back), keeping data fresh after file deletions.
     */
    $effect(() => {
        fetchStorageOverview();
    });

    async function fetchStorageOverview(): Promise<void> {
        isLoading = true;
        errorMessage = null;

        try {
            const response = await fetch(getApiEndpoint('/v1/settings/storage'), {
                credentials: 'include',
            });

            if (!response.ok) {
                // Surface the HTTP error text so it is visible, not hidden.
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
</script>

<div class="storage-container">

    <!-- ── Loading state ──────────────────────────────────────────────────── -->
    {#if isLoading}
        <div class="loading-state">
            <div class="spinner"></div>
            <span>{$text('settings.storage.storage_loading')}</span>
        </div>

    <!-- ── Error state ────────────────────────────────────────────────────── -->
    {:else if errorMessage}
        <div class="error-state">
            <div class="icon icon_error"></div>
            <p class="error-text">{$text('settings.storage.storage_error')}</p>
            <p class="error-detail">{errorMessage}</p>
            <button class="btn-retry" onclick={fetchStorageOverview}>
                Retry
            </button>
        </div>

    <!-- ── Loaded state ───────────────────────────────────────────────────── -->
    {:else if overview}

        <!-- Total usage + progress bar -->
        <div class="usage-card">
            <div class="usage-label">
                {$text('settings.storage.storage_total_used', {
                    used: formatBytes(overview.total_bytes),
                    free: formatBytes(overview.free_bytes),
                })}
            </div>

            <div class="progress-bar" role="progressbar" aria-valuenow={usedPercent} aria-valuemin={0} aria-valuemax={100}>
                <div
                    class="progress-fill"
                    class:over-limit={!isWithinFreeTier}
                    style="width: {usedPercent}%"
                ></div>
            </div>

            <div class="usage-meta">
                <span class="free-tier-label">{$text('settings.storage.storage_free_tier_label')}: {formatBytes(overview.free_bytes)}</span>
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
                        {$text('settings.storage.storage_credits_per_week', { credits: overview.weekly_cost_credits })}
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

        <!-- Per-category breakdown -->
        {#if overview.breakdown.length > 0}
            <div class="breakdown-section">
                <h3 class="breakdown-title">{$text('settings.storage.storage_breakdown_title')}</h3>
                <ul class="breakdown-list">
                    {#each overview.breakdown as item}
                        <li class="breakdown-item">
                            <div class="breakdown-info">
                                <span class="breakdown-name">{$text(categoryLabel(item.category))}</span>
                                <span class="breakdown-count">
                                    {$text('settings.storage.storage_files_count', { count: item.file_count })}
                                </span>
                            </div>
                            <span class="breakdown-size">{formatBytes(item.bytes_used)}</span>
                        </li>
                    {/each}
                </ul>
            </div>
        {/if}

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

    /* Progress bar */
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

    /* Free tier notice */
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

    /* Billing rows */
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
        padding: 20px;
    }

    .breakdown-title {
        font-size: 14px;
        font-weight: 600;
        color: var(--color-grey-60);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin: 0 0 16px;
    }

    .breakdown-list {
        list-style: none;
        padding: 0;
        margin: 0;
        display: flex;
        flex-direction: column;
        gap: 0;
    }

    .breakdown-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 0;
        border-bottom: 1px solid var(--color-grey-15);
    }

    .breakdown-item:last-child {
        border-bottom: none;
        padding-bottom: 0;
    }

    .breakdown-info {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }

    .breakdown-name {
        font-size: 14px;
        font-weight: 500;
        color: var(--color-grey-80);
    }

    .breakdown-count {
        font-size: 12px;
        color: var(--color-grey-50);
    }

    .breakdown-size {
        font-size: 14px;
        font-weight: 600;
        color: var(--color-grey-70);
        white-space: nowrap;
    }
</style>
