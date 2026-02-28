<!--
Storage Overview - Account Settings Sub-page
Displays the current user's storage usage broken down by file-type category,
along with free-tier status and weekly billing information.

Below the overview, an expandable "Your Files" section lets the user browse,
open (in a new tab), and delete their uploaded files — individually, by
category, or all at once.

API endpoints:
  GET  /v1/settings/storage              → overview (totals, billing, breakdown)
  GET  /v1/settings/storage/files        → file list (optionally filtered by category)
  GET  /v1/settings/storage/files/{embed_id}/view → server-decrypted file stream
  DELETE /v1/settings/storage/files     → delete by scope (single / category / all)

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

    interface StorageFileItem {
        id: string;
        embed_id: string;
        original_filename: string;
        content_type: string;
        category: string;
        file_size_bytes: number;
        variant_count: number;
        created_at: number | null;
    }

    interface StorageFilesListResponse {
        files: StorageFileItem[];
        total_count: number;
        total_bytes: number;
    }

    // =========================================================================
    // CONSTANTS
    // =========================================================================

    /**
     * All recognised category names in display order.
     * "all" is a synthetic filter meaning "no category filter applied".
     */
    const CATEGORIES = ['all', 'images', 'videos', 'audio', 'pdf', 'code', 'docs', 'sheets', 'archives', 'other'] as const;
    type CategoryName = typeof CATEGORIES[number];

    // =========================================================================
    // STATE — overview
    // =========================================================================

    /** Storage overview data from the API. Null until loaded. */
    let overview = $state<StorageOverview | null>(null);

    /** True while the initial API fetch is in progress. */
    let isLoading = $state(true);

    /** Error message if the API call fails. Null when no error. */
    let errorMessage = $state<string | null>(null);

    // =========================================================================
    // STATE — file list
    // =========================================================================

    /**
     * The currently selected category tab.
     * "all" means fetch all files (no filter).
     * Any other value fetches only that category.
     * Null means no tab has been clicked yet — file list is not loaded.
     */
    let selectedCategory = $state<CategoryName | null>(null);

    /** File list for the currently selected category. Null = not loaded yet. */
    let fileList = $state<StorageFileItem[] | null>(null);

    /** True while the file list is being fetched. */
    let isLoadingFiles = $state(false);

    /** Error message for the file list fetch. */
    let fileListError = $state<string | null>(null);

    // =========================================================================
    // STATE — deletion
    // =========================================================================

    /**
     * The pending delete action.
     * Set when the user clicks a delete button (confirmation required).
     * Null means no confirmation is pending.
     */
    let pendingDelete = $state<{
        scope: 'single' | 'category' | 'all';
        fileId?: string;
        filename?: string;
        category?: string;
        count: number;
        bytes: number;
    } | null>(null);

    /** True while a delete request is in flight. */
    let isDeleting = $state(false);

    /** Success/error toast message after deletion. */
    let deleteToast = $state<{ type: 'success' | 'error'; message: string } | null>(null);

    // =========================================================================
    // DERIVED — overview
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
    // DERIVED — file list
    // =========================================================================

    /** Files currently displayed, always newest-first (API already sorts them). */
    let displayedFiles = $derived(fileList ?? []);

    /** Total bytes for the displayed files. */
    let displayedBytes = $derived(
        displayedFiles.reduce((sum, f) => sum + f.file_size_bytes, 0)
    );

    // =========================================================================
    // HELPERS
    // =========================================================================

    /**
     * Format a byte count into a human-readable string.
     * Uses 1024-based units (B, KB, MB, GB, TB).
     */
    function formatBytes(bytes: number): string {
        if (bytes === 0) return '0 B';
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(1024));
        const value = bytes / Math.pow(1024, i);
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

    /**
     * Short human-readable label for a file's MIME type.
     * Used as a fallback when the filename extension is not obvious.
     */
    function mimeLabel(contentType: string): string {
        const lower = contentType.toLowerCase();
        if (lower.startsWith('image/')) return lower.replace('image/', '').split(';')[0].toUpperCase();
        if (lower.startsWith('video/')) return lower.replace('video/', '').split(';')[0].toUpperCase();
        if (lower.startsWith('audio/')) return lower.replace('audio/', '').split(';')[0].toUpperCase();
        if (lower === 'application/pdf') return 'PDF';
        return lower.split('/').pop()?.toUpperCase() ?? contentType;
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

    // =========================================================================
    // API — overview
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
    // API — file list
    // =========================================================================

    /**
     * Load the file list for the given category.
     * Called when the user clicks a category tab.
     * "all" = fetch without category filter.
     */
    async function loadFilesForCategory(category: CategoryName): Promise<void> {
        // If the user clicks the already-selected tab, do nothing (list is already loaded).
        if (selectedCategory === category && fileList !== null) return;

        selectedCategory = category;
        isLoadingFiles = true;
        fileListError = null;
        fileList = null;

        try {
            const url = new URL(getApiEndpoint('/v1/settings/storage/files'));
            if (category !== 'all') {
                url.searchParams.set('category', category);
            }

            const response = await fetch(url.toString(), { credentials: 'include' });

            if (!response.ok) {
                const body = await response.text().catch(() => '');
                throw new Error(`HTTP ${response.status}: ${body || response.statusText}`);
            }

            const data: StorageFilesListResponse = await response.json();
            fileList = data.files;
        } catch (err) {
            console.error('[SettingsStorage] Failed to load file list:', err);
            fileListError = err instanceof Error ? err.message : String(err);
        } finally {
            isLoadingFiles = false;
        }
    }

    // =========================================================================
    // FILE — open in new tab
    // =========================================================================

    /**
     * Open a stored file in a new browser tab by navigating to the view endpoint,
     * which server-side decrypts and streams the file with the correct Content-Type.
     */
    function openFileInNewTab(file: StorageFileItem): void {
        const url = getApiEndpoint(`/v1/settings/storage/files/${encodeURIComponent(file.embed_id)}/view`);
        window.open(url, '_blank', 'noopener,noreferrer');
    }

    // =========================================================================
    // API — deletion
    // =========================================================================

    /**
     * Initiate deletion of a single file.
     * Shows the confirmation dialog; actual deletion happens in confirmDelete().
     */
    function requestDeleteSingle(file: StorageFileItem): void {
        pendingDelete = {
            scope: 'single',
            fileId: file.id,
            filename: file.original_filename,
            count: 1,
            bytes: file.file_size_bytes,
        };
    }

    /**
     * Initiate deletion of all files in the current category.
     */
    function requestDeleteCategory(): void {
        if (!selectedCategory || selectedCategory === 'all') return;
        pendingDelete = {
            scope: 'category',
            category: selectedCategory,
            count: displayedFiles.length,
            bytes: displayedBytes,
        };
    }

    /**
     * Initiate deletion of ALL files.
     */
    function requestDeleteAll(): void {
        const total = overview?.total_files ?? displayedFiles.length;
        const totalBytes = overview?.total_bytes ?? displayedBytes;
        pendingDelete = {
            scope: 'all',
            count: total,
            bytes: totalBytes,
        };
    }

    function cancelDelete(): void {
        pendingDelete = null;
    }

    /**
     * Execute the confirmed deletion.
     * Calls DELETE /v1/settings/storage/files with the appropriate scope,
     * then refreshes both the file list and the storage overview.
     */
    async function confirmDelete(): Promise<void> {
        if (!pendingDelete) return;

        isDeleting = true;
        deleteToast = null;

        const body: Record<string, string> = { scope: pendingDelete.scope };
        if (pendingDelete.scope === 'single' && pendingDelete.fileId) {
            body['file_id'] = pendingDelete.fileId;
        }
        if (pendingDelete.scope === 'category' && pendingDelete.category) {
            body['category'] = pendingDelete.category;
        }

        const snapshot = pendingDelete;
        pendingDelete = null;

        try {
            const response = await fetch(getApiEndpoint('/v1/settings/storage/files'), {
                method: 'DELETE',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            if (!response.ok) {
                const errBody = await response.text().catch(() => '');
                throw new Error(`HTTP ${response.status}: ${errBody || response.statusText}`);
            }

            const result: { deleted_count: number; bytes_freed: number } = await response.json();

            deleteToast = {
                type: 'success',
                message: $text('settings.storage.storage_delete_success', {
                    values: {
                        count: result.deleted_count,
                        size: formatBytes(result.bytes_freed),
                    },
                }),
            };

            // Refresh overview stats
            await fetchStorageOverview();

            // Reload the file list if a category is selected
            if (selectedCategory !== null) {
                // If we just deleted the selected category or all, switch to "all"
                if (snapshot.scope === 'all' || snapshot.scope === 'category') {
                    selectedCategory = null;
                    fileList = null;
                } else {
                    // Re-fetch the current category to remove the deleted row
                    const cat = selectedCategory;
                    selectedCategory = null; // force reload
                    fileList = null;
                    await loadFilesForCategory(cat);
                }
            }
        } catch (err) {
            console.error('[SettingsStorage] Deletion failed:', err);
            deleteToast = {
                type: 'error',
                message: $text('settings.storage.storage_delete_error'),
            };
        } finally {
            isDeleting = false;

            // Auto-dismiss toast after 5 s
            setTimeout(() => { deleteToast = null; }, 5000);
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
                    values: {
                        used: formatBytes(overview.total_bytes),
                        free: formatBytes(overview.free_bytes),
                    }
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
                        {$text('settings.storage.storage_credits_per_week', { values: { credits: overview.weekly_cost_credits } })}
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
                                    {$text('settings.storage.storage_files_count', { values: { count: item.file_count } })}
                                </span>
                            </div>
                            <span class="breakdown-size">{formatBytes(item.bytes_used)}</span>
                        </li>
                    {/each}
                </ul>
            </div>
        {/if}

        <!-- ── Your Files section ──────────────────────────────────────────── -->
        <div class="files-section">

            <!-- Section header row: title + delete-all button -->
            <div class="files-header">
                <h3 class="files-title">{$text('settings.storage.storage_files_title')}</h3>

                <!-- Bulk delete dropdown (only show when files exist) -->
                {#if overview.total_files > 0}
                    <div class="bulk-delete-wrapper">
                        <details class="bulk-delete-dropdown">
                            <summary class="btn-bulk-delete">
                                <span>{$text('settings.storage.storage_delete_all')}</span>
                                <span class="dropdown-arrow">▾</span>
                            </summary>
                            <div class="dropdown-menu">
                                <!-- Delete all files of a non-"all" selected category -->
                                {#if selectedCategory && selectedCategory !== 'all' && displayedFiles.length > 0}
                                    <button
                                        class="dropdown-item"
                                        onclick={requestDeleteCategory}
                                    >
                                        {$text('settings.storage.storage_delete_category', {
                                            values: { category: $text(categoryLabel(selectedCategory)) }
                                        })}
                                    </button>
                                {/if}
                                <!-- Delete everything -->
                                <button
                                    class="dropdown-item danger"
                                    onclick={requestDeleteAll}
                                >
                                    {$text('settings.storage.storage_delete_all')}
                                </button>
                            </div>
                        </details>
                    </div>
                {/if}
            </div>

            <!-- Category filter tabs -->
            <div class="category-tabs" role="tablist">
                {#each CATEGORIES as cat}
                    <!-- Only show a category tab if there are files in it (or it's "all") -->
                    {#if cat === 'all' || overview.breakdown.some(b => b.category === cat)}
                        <button
                            class="tab-btn"
                            class:active={selectedCategory === cat}
                            role="tab"
                            aria-selected={selectedCategory === cat}
                            onclick={() => loadFilesForCategory(cat)}
                        >
                            {#if cat === 'all'}
                                {$text('settings.storage.storage_filter_all')}
                            {:else}
                                {$text(categoryLabel(cat))}
                            {/if}
                        </button>
                    {/if}
                {/each}
            </div>

            <!-- File list area (only rendered once a tab has been clicked) -->
            {#if selectedCategory !== null}
                <div class="file-list-area">

                    {#if isLoadingFiles}
                        <!-- Loading state -->
                        <div class="files-loading">
                            <div class="spinner-sm"></div>
                            <span>{$text('settings.storage.storage_files_loading')}</span>
                        </div>

                    {:else if fileListError}
                        <!-- Error state -->
                        <div class="files-error">
                            <p class="error-text">{fileListError}</p>
                        </div>

                    {:else if displayedFiles.length === 0}
                        <!-- Empty state -->
                        <div class="files-empty">
                            <p>{$text('settings.storage.storage_files_empty')}</p>
                        </div>

                    {:else}
                        <!-- File rows -->
                        <ul class="file-list">
                            {#each displayedFiles as file (file.id)}
                                <li class="file-row">
                                    <!-- Clickable area: opens file in new tab -->
                                    <button
                                        class="file-info-btn"
                                        onclick={() => openFileInNewTab(file)}
                                        title={file.original_filename}
                                    >
                                        <span class="file-name">{file.original_filename}</span>
                                        <span class="file-meta">
                                            <span class="file-type">{mimeLabel(file.content_type)}</span>
                                            {#if file.variant_count > 1}
                                                <span class="file-variants">×{file.variant_count}</span>
                                            {/if}
                                            <span class="file-size">{formatBytes(file.file_size_bytes)}</span>
                                            {#if file.created_at}
                                                <span class="file-date">{formatDate(file.created_at)}</span>
                                            {/if}
                                        </span>
                                    </button>

                                    <!-- Delete button -->
                                    <button
                                        class="btn-delete-file"
                                        onclick={(e) => { e.stopPropagation(); requestDeleteSingle(file); }}
                                        aria-label={$text('settings.storage.storage_delete_file')}
                                        title={$text('settings.storage.storage_delete_file')}
                                    >
                                        <div class="icon icon_trash"></div>
                                    </button>
                                </li>
                            {/each}
                        </ul>

                        <!-- Footer: file count + total size for current view -->
                        <div class="file-list-footer">
                            <span>
                                {$text('settings.storage.storage_files_count', { values: { count: displayedFiles.length } })}
                                · {formatBytes(displayedBytes)}
                            </span>
                        </div>
                    {/if}

                </div>
            {/if}
        </div>

    {/if}
</div>

<!-- ── Delete confirmation dialog ──────────────────────────────────────────── -->
{#if pendingDelete}
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <div class="dialog-backdrop" role="presentation" onclick={cancelDelete}>
        <div class="dialog" role="alertdialog" aria-modal="true" tabindex="-1" onclick={(e) => e.stopPropagation()}>
            <p class="dialog-text">
                {#if pendingDelete.scope === 'single'}
                    {$text('settings.storage.storage_delete_confirm_single', {
                        values: {
                            filename: pendingDelete.filename ?? '',
                            size: formatBytes(pendingDelete.bytes),
                        }
                    })}
                {:else if pendingDelete.scope === 'category' && pendingDelete.category}
                    {$text('settings.storage.storage_delete_confirm_category', {
                        values: {
                            category: $text(categoryLabel(pendingDelete.category)),
                            count: pendingDelete.count,
                            size: formatBytes(pendingDelete.bytes),
                        }
                    })}
                {:else}
                    {$text('settings.storage.storage_delete_confirm_all', {
                        values: {
                            count: pendingDelete.count,
                            size: formatBytes(pendingDelete.bytes),
                        }
                    })}
                {/if}
            </p>
            <div class="dialog-actions">
                <button class="btn-cancel" onclick={cancelDelete} disabled={isDeleting}>
                    Cancel
                </button>
                <button class="btn-confirm-delete" onclick={confirmDelete} disabled={isDeleting}>
                    {#if isDeleting}
                        <div class="spinner-sm"></div>
                    {:else}
                        Delete
                    {/if}
                </button>
            </div>
        </div>
    </div>
{/if}

<!-- ── Toast notification ──────────────────────────────────────────────────── -->
{#if deleteToast}
    <div class="toast" class:toast-success={deleteToast.type === 'success'} class:toast-error={deleteToast.type === 'error'}>
        {deleteToast.message}
    </div>
{/if}

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

    .spinner-sm {
        width: 14px;
        height: 14px;
        border: 2px solid var(--color-grey-30);
        border-top-color: var(--color-primary);
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
        flex-shrink: 0;
        display: inline-block;
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

    /* ── Files section ─────────────────────────────────────────────────────── */
    .files-section {
        background: var(--color-grey-10);
        border-radius: 12px;
        padding: 20px;
        display: flex;
        flex-direction: column;
        gap: 16px;
    }

    /* Section header */
    .files-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
    }

    .files-title {
        font-size: 14px;
        font-weight: 600;
        color: var(--color-grey-60);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin: 0;
    }

    /* Bulk delete dropdown */
    .bulk-delete-wrapper {
        position: relative;
    }

    .bulk-delete-dropdown {
        position: relative;
    }

    .bulk-delete-dropdown summary {
        list-style: none;
    }

    .bulk-delete-dropdown summary::-webkit-details-marker {
        display: none;
    }

    .btn-bulk-delete {
        display: flex;
        align-items: center;
        gap: 4px;
        padding: 6px 12px;
        background: transparent;
        border: 1px solid var(--color-danger);
        border-radius: 6px;
        color: var(--color-danger);
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.15s, color 0.15s;
        user-select: none;
    }

    .btn-bulk-delete:hover {
        background: var(--color-danger);
        color: white;
    }

    .dropdown-arrow {
        font-size: 10px;
        margin-top: 1px;
    }

    .dropdown-menu {
        position: absolute;
        top: calc(100% + 4px);
        right: 0;
        min-width: 200px;
        background: var(--color-surface);
        border: 1px solid var(--color-grey-20);
        border-radius: 8px;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
        overflow: hidden;
        z-index: 100;
    }

    .dropdown-item {
        display: block;
        width: 100%;
        padding: 10px 16px;
        background: none;
        border: none;
        text-align: left;
        font-size: 14px;
        color: var(--color-grey-70);
        cursor: pointer;
        transition: background 0.1s;
    }

    .dropdown-item:hover {
        background: var(--color-grey-10);
    }

    .dropdown-item.danger {
        color: var(--color-danger);
    }

    .dropdown-item.danger:hover {
        background: var(--color-danger-light);
    }

    /* ── Category tabs ─────────────────────────────────────────────────────── */
    .category-tabs {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
    }

    .tab-btn {
        padding: 5px 12px;
        border-radius: 20px;
        border: 1px solid var(--color-grey-20);
        background: transparent;
        color: var(--color-grey-60);
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        transition: background 0.15s, color 0.15s, border-color 0.15s;
    }

    .tab-btn:hover {
        background: var(--color-grey-15);
        color: var(--color-grey-80);
    }

    .tab-btn.active {
        background: var(--color-primary);
        border-color: var(--color-primary);
        color: white;
    }

    /* ── File list area ────────────────────────────────────────────────────── */
    .file-list-area {
        display: flex;
        flex-direction: column;
        gap: 0;
    }

    .files-loading {
        display: flex;
        align-items: center;
        gap: 8px;
        color: var(--color-grey-60);
        font-size: 14px;
        padding: 16px 0;
    }

    .files-error {
        padding: 12px 0;
    }

    .files-error .error-text {
        font-size: 13px;
        color: var(--color-danger);
    }

    .files-empty {
        padding: 20px 0;
        color: var(--color-grey-50);
        font-size: 14px;
        text-align: center;
    }

    /* File list */
    .file-list {
        list-style: none;
        padding: 0;
        margin: 0;
    }

    .file-row {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 0;
        border-bottom: 1px solid var(--color-grey-15);
    }

    .file-row:last-child {
        border-bottom: none;
    }

    /* File info button (opens file in new tab) */
    .file-info-btn {
        flex: 1;
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 2px;
        padding: 4px 6px;
        background: none;
        border: none;
        border-radius: 6px;
        text-align: left;
        cursor: pointer;
        transition: background 0.12s;
        min-width: 0;
    }

    .file-info-btn:hover {
        background: var(--color-grey-15);
    }

    .file-name {
        font-size: 14px;
        font-weight: 500;
        color: var(--color-grey-80);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 100%;
    }

    .file-meta {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
    }

    .file-type {
        font-size: 11px;
        font-weight: 600;
        color: var(--color-grey-50);
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .file-variants {
        font-size: 11px;
        color: var(--color-grey-40);
        background: var(--color-grey-15);
        padding: 1px 5px;
        border-radius: 3px;
    }

    .file-size {
        font-size: 12px;
        color: var(--color-grey-60);
    }

    .file-date {
        font-size: 12px;
        color: var(--color-grey-40);
    }

    /* Delete file button */
    .btn-delete-file {
        flex-shrink: 0;
        width: 32px;
        height: 32px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: none;
        border: none;
        border-radius: 6px;
        cursor: pointer;
        opacity: 0.4;
        transition: opacity 0.15s, background 0.15s;
    }

    .btn-delete-file:hover {
        opacity: 1;
        background: var(--color-danger-light);
    }

    .btn-delete-file .icon {
        width: 16px;
        height: 16px;
        background: var(--color-danger);
        mask-size: contain;
        mask-repeat: no-repeat;
    }

    /* File list footer */
    .file-list-footer {
        padding: 10px 0 0;
        font-size: 12px;
        color: var(--color-grey-50);
        text-align: right;
    }

    /* ── Confirmation dialog ───────────────────────────────────────────────── */
    .dialog-backdrop {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.45);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 1000;
        padding: 16px;
    }

    .dialog {
        background: var(--color-surface);
        border-radius: 14px;
        padding: 24px;
        max-width: 380px;
        width: 100%;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
        display: flex;
        flex-direction: column;
        gap: 20px;
    }

    .dialog-text {
        margin: 0;
        font-size: 15px;
        line-height: 1.5;
        color: var(--color-grey-80);
    }

    .dialog-actions {
        display: flex;
        gap: 10px;
        justify-content: flex-end;
    }

    .btn-cancel {
        padding: 8px 16px;
        background: var(--color-grey-15);
        border: none;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 600;
        color: var(--color-grey-70);
        cursor: pointer;
        transition: opacity 0.15s;
    }

    .btn-cancel:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .btn-confirm-delete {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        min-width: 80px;
        padding: 8px 16px;
        background: var(--color-danger);
        border: none;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 600;
        color: white;
        cursor: pointer;
        transition: opacity 0.15s;
    }

    .btn-confirm-delete:disabled {
        opacity: 0.7;
        cursor: not-allowed;
    }

    .btn-confirm-delete:hover:not(:disabled) {
        opacity: 0.88;
    }

    /* ── Toast ─────────────────────────────────────────────────────────────── */
    .toast {
        position: fixed;
        bottom: 24px;
        left: 50%;
        transform: translateX(-50%);
        padding: 12px 20px;
        border-radius: 10px;
        font-size: 14px;
        font-weight: 500;
        max-width: 420px;
        text-align: center;
        z-index: 1100;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
        animation: toast-in 0.2s ease;
    }

    .toast-success {
        background: var(--color-success-light, #e8f5e9);
        color: var(--color-success);
        border: 1px solid var(--color-success);
    }

    .toast-error {
        background: var(--color-danger-light);
        color: var(--color-danger);
        border: 1px solid var(--color-danger);
    }

    @keyframes toast-in {
        from { opacity: 0; transform: translateX(-50%) translateY(8px); }
        to   { opacity: 1; transform: translateX(-50%) translateY(0); }
    }
</style>
