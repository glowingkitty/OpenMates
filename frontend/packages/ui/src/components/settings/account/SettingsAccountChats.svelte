<!--
Settings > Account > Chats
Displays total chat count, a timeline graph of chat creation dates, and a
"Delete Old Chats" section with a period dropdown and confirmation flow.

Architecture:
  - GET /v1/settings/chats  → chat count + per-day creation timeline
  - POST /v1/settings/chats/delete-old  → bulk-delete chats older than N days
  - Timeline renders as a pure-CSS bar chart (no external chart library needed).

Tests: none yet — this is a new settings sub-page.
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { getApiEndpoint, apiEndpoints } from '../../../config/api';

    // =========================================================================
    // TYPES
    // =========================================================================

    interface ChatCreationDataPoint {
        date: string;   // YYYY-MM-DD
        count: number;
    }

    interface ChatStats {
        total_count: number;
        creation_timeline: ChatCreationDataPoint[];
    }

    // =========================================================================
    // STATE
    // =========================================================================

    let stats = $state<ChatStats | null>(null);
    let isLoading = $state(true);
    let errorMessage = $state<string | null>(null);

    // Delete-old state
    type DeleteDays = 1 | 7 | 14 | 30 | 90;

    let selectedDays = $state<DeleteDays>(30);
    let showConfirm = $state(false);
    let isDeleting = $state(false);
    let deleteResult = $state<{ count: number } | null>(null);
    let deleteError = $state<string | null>(null);

    // =========================================================================
    // DERIVED
    // =========================================================================

    /** Max count in the timeline — used to normalise bar heights (0 if empty). */
    let maxCount = $derived(
        stats
            ? stats.creation_timeline.reduce((m, d) => Math.max(m, d.count), 0)
            : 0
    );

    /**
     * Bucket the raw per-day data into a fixed-width display of at most
     * MAX_BARS buckets. If there are fewer days than MAX_BARS, each day
     * gets its own bar; otherwise consecutive days are merged.
     */
    let displayBars = $derived((): { label: string; count: number; height: number }[] => {
        if (!stats || stats.creation_timeline.length === 0) return [];

        const MAX_BARS = 52;
        const days = stats.creation_timeline;
        const n = days.length;

        if (n <= MAX_BARS) {
            // One bar per day
            return days.map(d => ({
                label: d.date,
                count: d.count,
                height: maxCount > 0 ? Math.max(2, Math.round((d.count / maxCount) * 100)) : 0,
            }));
        }

        // Bucket: group consecutive days into MAX_BARS even buckets
        const bucketSize = Math.ceil(n / MAX_BARS);
        const buckets: { label: string; count: number; height: number }[] = [];

        for (let i = 0; i < n; i += bucketSize) {
            const slice = days.slice(i, i + bucketSize);
            const total = slice.reduce((s, d) => s + d.count, 0);
            buckets.push({
                label: slice[0].date,
                count: total,
                height: maxCount > 0 ? Math.max(2, Math.round((total / maxCount) * 100)) : 0,
            });
        }
        return buckets;
    });

    // =========================================================================
    // EFFECTS
    // =========================================================================

    $effect(() => {
        fetchChatStats();
    });

    // =========================================================================
    // API
    // =========================================================================

    async function fetchChatStats(): Promise<void> {
        isLoading = true;
        errorMessage = null;

        try {
            const res = await fetch(getApiEndpoint(apiEndpoints.settings.chatStats), {
                credentials: 'include',
            });
            if (!res.ok) {
                const body = await res.text().catch(() => '');
                throw new Error(`HTTP ${res.status}: ${body || res.statusText}`);
            }
            stats = await res.json();
        } catch (err) {
            console.error('[SettingsAccountChats] Failed to load chat stats:', err);
            errorMessage = err instanceof Error ? err.message : String(err);
        } finally {
            isLoading = false;
        }
    }

    async function performDelete(): Promise<void> {
        isDeleting = true;
        deleteError = null;
        deleteResult = null;
        showConfirm = false;

        try {
            const res = await fetch(getApiEndpoint(apiEndpoints.settings.deleteOldChats), {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ older_than_days: selectedDays }),
            });
            if (!res.ok) {
                const body = await res.text().catch(() => '');
                throw new Error(`HTTP ${res.status}: ${body || res.statusText}`);
            }
            const data = await res.json();
            deleteResult = { count: data.deleted_count };
            // Refresh stats so the count and chart update after deletion
            await fetchChatStats();
        } catch (err) {
            console.error('[SettingsAccountChats] Failed to delete old chats:', err);
            deleteError = err instanceof Error ? err.message : String(err);
        } finally {
            isDeleting = false;
        }
    }

    // =========================================================================
    // HELPERS
    // =========================================================================

    function formatDate(iso: string): string {
        try {
            return new Date(iso).toLocaleDateString(undefined, {
                month: 'short',
                day: 'numeric',
                year: 'numeric',
            });
        } catch {
            return iso;
        }
    }
</script>

<div class="chats-container">

    <!-- ── Loading ─────────────────────────────────────────────────────────── -->
    {#if isLoading}
        <div class="loading-state">
            <div class="spinner"></div>
            <span>{$text('settings.account.chats.loading')}</span>
        </div>

    <!-- ── Error ───────────────────────────────────────────────────────────── -->
    {:else if errorMessage}
        <div class="error-state">
            <p class="error-text">{$text('settings.account.chats.error')}</p>
            <p class="error-detail">{errorMessage}</p>
            <button class="btn-retry" onclick={fetchChatStats}>
                {$text('settings.account.chats.retry')}
            </button>
        </div>

    <!-- ── Loaded ──────────────────────────────────────────────────────────── -->
    {:else if stats !== null}

        <!-- Total count badge -->
        <div class="count-card">
            <div class="count-number">{stats.total_count.toLocaleString()}</div>
            <div class="count-label">{$text('settings.account.chats')}</div>
        </div>

        <!-- Timeline chart -->
        <div class="section-card">
            <h3 class="section-title">{$text('settings.account.chats.timeline_title')}</h3>

            {#if displayBars().length === 0}
                <p class="empty-notice">{$text('settings.account.chats.timeline_empty')}</p>
            {:else}
                <div class="chart" role="img" aria-label="Chat creation timeline">
                    {#each displayBars() as bar}
                        <div
                            class="bar-wrap"
                            title="{formatDate(bar.label)}: {bar.count}"
                        >
                            <div class="bar" style="height: {bar.height}%"></div>
                        </div>
                    {/each}
                </div>
                <div class="chart-dates">
                    {#if displayBars().length > 0}
                        <span>{formatDate(displayBars()[0].label)}</span>
                        <span>{formatDate(displayBars()[displayBars().length - 1].label)}</span>
                    {/if}
                </div>
            {/if}
        </div>

        <!-- Delete old chats -->
        <div class="section-card danger-section">
            <h3 class="section-title">{$text('settings.account.chats.delete_section_title')}</h3>
            <p class="section-desc">{$text('settings.account.chats.delete_section_desc')}</p>

            <div class="delete-controls">
                <div class="select-wrapper">
                    <span class="select-label">{$text('settings.account.chats.delete_older_than')}</span>
                    <select
                        class="period-select"
                        bind:value={selectedDays}
                        disabled={isDeleting}
                    >
                        <option value={1}>{$text('settings.account.chats.delete_option_1d')}</option>
                        <option value={7}>{$text('settings.account.chats.delete_option_7d')}</option>
                        <option value={14}>{$text('settings.account.chats.delete_option_14d')}</option>
                        <option value={30}>{$text('settings.account.chats.delete_option_30d')}</option>
                        <option value={90}>{$text('settings.account.chats.delete_option_90d')}</option>
                    </select>
                </div>

                <button
                    class="btn-delete"
                    onclick={() => { showConfirm = true; deleteResult = null; deleteError = null; }}
                    disabled={isDeleting}
                >
                    {$text('settings.account.chats.delete_button')}
                </button>
            </div>

            <!-- Result / error feedback -->
            {#if deleteResult !== null}
                <div class="feedback success">
                    {deleteResult.count === 0
                        ? $text('settings.account.chats.delete_none')
                        : $text('settings.account.chats.delete_success', { values: { count: String(deleteResult.count) } })}
                </div>
            {/if}
            {#if deleteError}
                <div class="feedback error">{deleteError}</div>
            {/if}

            <!-- Inline confirmation -->
            {#if showConfirm}
                <div class="confirm-box">
                    <p class="confirm-title">{$text('settings.account.chats.delete_confirm_title')}</p>
                    <p class="confirm-desc">
                        {$text('settings.account.chats.delete_confirm_desc', {
                            values: { days: String(selectedDays) }
                        })}
                    </p>
                    <div class="confirm-actions">
                        <button
                            class="btn-cancel"
                            onclick={() => (showConfirm = false)}
                        >
                            {$text('settings.account.chats.delete_cancel_button')}
                        </button>
                        <button
                            class="btn-confirm-delete"
                            onclick={performDelete}
                        >
                            {isDeleting
                                ? $text('settings.account.chats.delete_deleting')
                                : $text('settings.account.chats.delete_confirm_button')}
                        </button>
                    </div>
                </div>
            {/if}
        </div>

    {/if}
</div>

<style>
    /* ── Container ─────────────────────────────────────────────────────────── */
    .chats-container {
        padding: 20px;
        display: flex;
        flex-direction: column;
        gap: 16px;
        max-width: 560px;
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
        gap: 8px;
        padding: 20px;
        background: var(--color-danger-light, #fff0f0);
        border: 1px solid var(--color-danger, #e53e3e);
        border-radius: 12px;
    }

    .error-text {
        font-weight: 600;
        color: var(--color-danger, #e53e3e);
        margin: 0;
    }

    .error-detail {
        font-size: 13px;
        color: var(--color-danger, #e53e3e);
        margin: 0;
        word-break: break-word;
    }

    .btn-retry {
        align-self: flex-start;
        padding: 8px 16px;
        background: var(--color-danger, #e53e3e);
        color: white;
        border: none;
        border-radius: 6px;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
    }

    .btn-retry:hover { opacity: 0.85; }

    /* ── Count card ────────────────────────────────────────────────────────── */
    .count-card {
        background: var(--color-primary-light, #ebf4ff);
        border-radius: 14px;
        padding: 24px;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 4px;
    }

    .count-number {
        font-size: 48px;
        font-weight: 700;
        color: var(--color-primary, #3b82f6);
        line-height: 1;
    }

    .count-label {
        font-size: 14px;
        font-weight: 500;
        color: var(--color-primary, #3b82f6);
        opacity: 0.8;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }

    /* ── Section card ──────────────────────────────────────────────────────── */
    .section-card {
        background: var(--color-grey-10, #f8f8f8);
        border-radius: 14px;
        padding: 20px;
    }

    .section-title {
        font-size: 13px;
        font-weight: 600;
        color: var(--color-grey-60, #888);
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin: 0 0 14px;
    }

    .section-desc {
        font-size: 14px;
        color: var(--color-grey-60, #888);
        margin: 0 0 16px;
        line-height: 1.5;
    }

    /* ── Chart ─────────────────────────────────────────────────────────────── */
    .chart {
        display: flex;
        align-items: flex-end;
        gap: 2px;
        height: 80px;
        overflow: hidden;
    }

    .bar-wrap {
        flex: 1;
        min-width: 2px;
        height: 100%;
        display: flex;
        align-items: flex-end;
        cursor: default;
    }

    .bar {
        width: 100%;
        background: var(--color-primary, #3b82f6);
        border-radius: 2px 2px 0 0;
        min-height: 2px;
        transition: opacity 0.15s;
    }

    .bar-wrap:hover .bar {
        opacity: 0.75;
    }

    .chart-dates {
        display: flex;
        justify-content: space-between;
        margin-top: 6px;
        font-size: 11px;
        color: var(--color-grey-50, #aaa);
    }

    .empty-notice {
        font-size: 14px;
        color: var(--color-grey-50, #aaa);
        margin: 0;
        text-align: center;
        padding: 20px 0;
    }

    /* ── Delete section ────────────────────────────────────────────────────── */
    .danger-section {
        border: 1px solid var(--color-danger-light, #fde8e8);
    }

    .delete-controls {
        display: flex;
        align-items: center;
        gap: 12px;
        flex-wrap: wrap;
    }

    .select-wrapper {
        display: flex;
        align-items: center;
        gap: 8px;
        flex: 1;
        min-width: 0;
    }

    .select-label {
        font-size: 14px;
        color: var(--color-grey-70, #555);
        white-space: nowrap;
    }

    .period-select {
        flex: 1;
        padding: 8px 12px;
        border: 1px solid var(--color-grey-30, #ddd);
        border-radius: 8px;
        background: var(--color-surface, white);
        color: var(--color-grey-80, #222);
        font-size: 14px;
        cursor: pointer;
        appearance: auto;
    }

    .period-select:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .btn-delete {
        padding: 9px 18px;
        background: var(--color-danger, #e53e3e);
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        white-space: nowrap;
        transition: opacity 0.15s;
    }

    .btn-delete:hover:not(:disabled) { opacity: 0.85; }
    .btn-delete:disabled { opacity: 0.5; cursor: not-allowed; }

    /* ── Feedback ──────────────────────────────────────────────────────────── */
    .feedback {
        margin-top: 12px;
        padding: 10px 14px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
    }

    .feedback.success {
        background: var(--color-success-light, #e6f9f0);
        color: var(--color-success, #2f855a);
        border: 1px solid var(--color-success, #2f855a);
    }

    .feedback.error {
        background: var(--color-danger-light, #fff0f0);
        color: var(--color-danger, #e53e3e);
        border: 1px solid var(--color-danger, #e53e3e);
    }

    /* ── Inline confirm ────────────────────────────────────────────────────── */
    .confirm-box {
        margin-top: 16px;
        padding: 16px;
        background: var(--color-surface, white);
        border: 1px solid var(--color-danger, #e53e3e);
        border-radius: 10px;
    }

    .confirm-title {
        font-size: 15px;
        font-weight: 700;
        color: var(--color-danger, #e53e3e);
        margin: 0 0 6px;
    }

    .confirm-desc {
        font-size: 14px;
        color: var(--color-grey-70, #555);
        margin: 0 0 16px;
        line-height: 1.5;
    }

    .confirm-actions {
        display: flex;
        gap: 10px;
        justify-content: flex-end;
    }

    .btn-cancel {
        padding: 8px 16px;
        background: var(--color-grey-20, #eee);
        color: var(--color-grey-80, #222);
        border: none;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
    }

    .btn-cancel:hover { opacity: 0.8; }

    .btn-confirm-delete {
        padding: 8px 16px;
        background: var(--color-danger, #e53e3e);
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
    }

    .btn-confirm-delete:hover { opacity: 0.85; }
</style>
