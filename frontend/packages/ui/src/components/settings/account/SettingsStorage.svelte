<script lang="ts">
    import { createEventDispatcher, onMount } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';
    import { SettingsSectionHeading, SettingsPageContainer, SettingsCard, SettingsDetailRow, SettingsProgressBar, SettingsInfoBox, SettingsLoadingState, SettingsButton } from '../../settings/elements';
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
        logical_s3_bytes: number;
        metering_categories: Record<string, number>;
        metering_policy_version: string;
        metering_source_version: string;
        measurement_at: number;
        free_bytes: number;
        billable_gb: number;
        credits_per_gb_per_week: number;
        weekly_cost_credits: number;
        next_billing_date: number | null;
        last_billed_at: number | null;
        breakdown: StorageCategoryBreakdown[];
    }

    interface AffectedUnit {
        unit_id: string;
        kind: 'upload' | 'cold_chat' | 'artifact_history';
        resource_id: string;
        oldest_at: number;
        bytes: number;
    }

    interface StorageNotice {
        episode_id: string | null;
        warning_count: number;
        deadline_at: number | null;
        manual_review: boolean;
        units: AffectedUnit[];
        has_more: boolean;
        next_after_unit_id: string | null;
    }

    let notice = $state<StorageNotice | null>(null);
    let noticeLoading = $state(false);
    let noticeError = $state(false);
    const logicalLabels: Record<string, string> = {
        chat_pages: 'storage_category_saved_chats',
        chat_oversized: 'storage_category_large_messages',
        cold_chat_graphs: 'storage_category_older_chats',
        sealed_recovery: 'storage_category_pending_outputs',
        embed_versions: 'storage_category_artifact_history',
    };
    let logicalBreakdown = $derived(
        overview ? Object.entries(overview.metering_categories).filter(([, bytes]) => bytes > 0) : []
    );

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

    /** Percentage of the free 1 GiB tier used (0–100), capped at 100. */
    let usedPercent = $derived(
        overview
            ? Math.min(100, Math.round((overview.total_bytes / overview.free_bytes) * 100))
            : 0
    );

    /** True when the user is within the free 1 GiB tier. */
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
        const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
        const i = Math.min(4, Math.floor(Math.log(bytes) / Math.log(1024)));
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
    onMount(() => {
        void fetchStorageOverview();
        void fetchNotice();
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
                throw new Error(`HTTP ${response.status}`);
            }

            overview = await response.json();
        } catch (err) {
            console.error('[SettingsStorage] Failed to load storage overview:', err);
            errorMessage = err instanceof Error ? err.message : String(err);
        } finally {
            isLoading = false;
        }
    }

    function measurementDate(ts: number): string {
        return new Date(ts * 1000).toLocaleString(undefined, { timeZone: 'UTC' }) + ' UTC';
    }

    async function fetchNotice(loadMore = false): Promise<void> {
        if (noticeLoading) return;
        noticeLoading = true;
        noticeError = false;
        const after = loadMore ? notice?.next_after_unit_id : null;
        const query = new URLSearchParams({ limit: '50' });
        if (after) query.set('after_unit_id', after);
        try {
            const response = await fetch(getApiEndpoint(`/v1/settings/storage/notice?${query}`), {
                credentials: 'include',
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const next: StorageNotice = await response.json();
            if (loadMore && notice && notice.episode_id === next.episode_id) {
                const known = new Set(notice.units.map(unit => unit.unit_id));
                next.units = [...notice.units, ...next.units.filter(unit => !known.has(unit.unit_id))];
            }
            notice = next;
        } catch (error) {
            console.error('[SettingsStorage] Failed to load storage notice:', error);
            noticeError = true;
        } finally {
            noticeLoading = false;
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

<SettingsPageContainer>
    {#if isLoading}
        <SettingsLoadingState text={$text('settings.storage.storage_loading')} />
    {:else if errorMessage}
        <SettingsInfoBox type="error">{$text('settings.storage.storage_error')}</SettingsInfoBox>
        <SettingsButton variant="secondary" onClick={fetchStorageOverview}>{$text('settings.storage.storage_retry')}</SettingsButton>
    {:else if overview}
        <SettingsCard>
            <SettingsProgressBar value={usedPercent} variant={isWithinFreeTier ? 'default' : 'warning'} showPercent label={$text('settings.storage.storage_total_used', { values: { used: formatBytes(overview.total_bytes), free: formatBytes(overview.free_bytes) } })} />
            <SettingsDetailRow label={$text('settings.storage.storage_free_tier_label')} value={formatBytes(overview.free_bytes)} />
            <SettingsDetailRow label={$text('settings.storage.storage_measured_at')} value={measurementDate(overview.measurement_at)} />
        </SettingsCard>
        <SettingsInfoBox data-testid="storage-pricing-policy">{$text('settings.storage.storage_pricing_policy')}</SettingsInfoBox>
        <SettingsCard>
            {#if isWithinFreeTier}
                <SettingsInfoBox type="success">{$text('settings.storage.storage_within_free_tier')}</SettingsInfoBox>
            {:else}
                <SettingsDetailRow label={$text('settings.storage.storage_billable')} value={`${overview.billable_gb} GiB`} />
                <SettingsDetailRow label={$text('settings.storage.storage_weekly_cost')} value={$text('settings.storage.storage_credits_per_week', { values: { credits: overview.weekly_cost_credits } })} highlight />
                {#if overview.next_billing_date}
                    <SettingsDetailRow label={$text('settings.storage.storage_next_billing')} value={measurementDate(overview.next_billing_date)} />
                {/if}
            {/if}
            {#if overview.last_billed_at}
                <SettingsDetailRow label={$text('settings.storage.storage_last_billed')} value={formatDate(overview.last_billed_at)} muted />
            {/if}
        </SettingsCard>

        {#if logicalBreakdown.length > 0}
            <SettingsSectionHeading title={$text('settings.storage.storage_logical_breakdown')} icon="storage" />
            <SettingsCard>
                {#each logicalBreakdown as [category, bytes]}
                    <SettingsDetailRow label={logicalLabels[category] ? $text(`settings.storage.${logicalLabels[category]}`) : category} value={formatBytes(bytes)} />
                {/each}
            </SettingsCard>
        {/if}
        {#if visibleBreakdown.length > 0}
            <SettingsSectionHeading title={$text('settings.storage.storage_breakdown_title')} icon="cloud" />
            {#each visibleBreakdown as item}
                <SettingsItem type="submenu" icon="storage" title={$text(categoryLabel(item.category))} subtitle="{$text('settings.storage.storage_files_count', { values: { count: item.file_count } })} · {formatBytes(item.bytes_used)}" onClick={() => openCategory(item.category)} />
            {/each}
        {/if}

        <SettingsSectionHeading title={$text('settings.storage.storage_notice_heading')} icon="storage" />
        {#if notice?.episode_id}
            <SettingsInfoBox type="warning" data-testid="storage-active-notice">
                {$text('settings.storage.storage_notice_policy')}
            </SettingsInfoBox>
            <SettingsCard>
                <SettingsDetailRow label={$text('settings.storage.storage_notices_delivered')} value={`${notice.warning_count} / 4`} />
                {#if notice.deadline_at}
                    <SettingsDetailRow label={$text('settings.storage.storage_notice_deadline')} value={measurementDate(notice.deadline_at)} />
                {/if}
            </SettingsCard>
            {#if notice.manual_review}
                <SettingsInfoBox type="warning">{$text('settings.storage.storage_notice_manual_review')}</SettingsInfoBox>
            {/if}
            {#each notice.units as unit (unit.unit_id)}
                <SettingsCard>
                    <SettingsDetailRow label={$text('settings.storage.storage_unit_type')} value={$text(`settings.storage.storage_unit_${unit.kind}`)} />
                    <SettingsDetailRow label={$text('settings.storage.storage_unit_id')} value={unit.unit_id} />
                    <SettingsDetailRow label={$text('settings.storage.storage_resource_id')} value={unit.resource_id} />
                    <SettingsDetailRow label={$text('settings.storage.storage_unit_oldest')} value={formatDate(unit.oldest_at)} />
                    <SettingsDetailRow label={$text('settings.storage.storage_unit_size')} value={formatBytes(unit.bytes)} />
                </SettingsCard>
            {/each}
            {#if notice.has_more}
                <SettingsButton variant="secondary" loading={noticeLoading} onClick={() => fetchNotice(true)}>{$text('settings.storage.storage_notice_load_more')}</SettingsButton>
            {/if}
        {:else if notice && !noticeError}
            <SettingsInfoBox data-testid="storage-notice-empty">{$text('settings.storage.storage_notice_empty')}</SettingsInfoBox>
        {/if}
        {#if noticeError}
            <SettingsInfoBox type="error">{$text('settings.storage.storage_notice_error')}</SettingsInfoBox>
            <SettingsButton variant="secondary" onClick={() => fetchNotice(Boolean(notice?.has_more))}>{$text('settings.storage.storage_retry')}</SettingsButton>
        {:else if noticeLoading && !notice}
            <SettingsLoadingState text={$text('settings.storage.storage_loading')} />
        {/if}
        <SettingsInfoBox>{$text('settings.storage.storage_invoice_notice')}</SettingsInfoBox>
    {/if}
</SettingsPageContainer>
