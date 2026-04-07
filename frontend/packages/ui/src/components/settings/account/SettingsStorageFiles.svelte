<!--
Storage File List — sub-page for a single file category.

Reached by tapping a category row in SettingsStorage.svelte.
The active route is "account/storage/<category>", e.g. "account/storage/images".
The category is extracted from the `activeSettingsView` prop.

Each file row shows:
  - filename (large, clickable — opens in new tab via the /view endpoint)
  - size · date (small, muted)
  - trash button (2-press confirm: first press → "Confirm?", second press → deletes)

At the bottom there are two bulk-delete buttons, both using the same 2-press pattern:
  - "Delete all [category]" — deletes all files in this category
  - "Delete all files"      — deletes ALL uploaded files across all categories

After the last file in this category is deleted the component dispatches
`navigateBack` so the user returns to the overview automatically.

API endpoints:
  GET    /v1/settings/storage/files?category=<cat>  → file list
  GET    /v1/settings/storage/files/<embed_id>/view → server-decrypt + stream
  DELETE /v1/settings/storage/files                 → delete by scope
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { getApiEndpoint } from '../../../config/api';

    // =========================================================================
    // PROPS
    // =========================================================================

    /**
     * The currently active settings route, e.g. "account/storage/images".
     * The category is the last path segment.
     */
    const { activeSettingsView }: { activeSettingsView: string } = $props();

    const dispatch = createEventDispatcher();

    // =========================================================================
    // TYPES
    // =========================================================================

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
    // DERIVED — category from route
    // =========================================================================

    /**
     * Extract the category from the route path.
     * "account/storage/images" → "images"
     */
    let category = $derived(activeSettingsView.split('/').pop() ?? '');

    // =========================================================================
    // STATE — file list
    // =========================================================================

    let files = $state<StorageFileItem[]>([]);
    let isLoading = $state(true);
    let loadError = $state<string | null>(null);

    // =========================================================================
    // STATE — per-file 2-press confirm
    // =========================================================================

    /**
     * Maps file.id → true when that file's delete button is in confirm mode.
     * Only one file is ever in confirm mode at a time (selecting another resets the previous).
     */
    let confirmFileId = $state<string | null>(null);
    let confirmFileTimeout: ReturnType<typeof setTimeout> | null = null;

    // =========================================================================
    // STATE — bulk delete 2-press confirm
    // =========================================================================

    /**
     * "category" = "Delete all [category]" button in confirm mode.
     * "all"      = "Delete all files" button in confirm mode.
     * null       = neither button is in confirm mode.
     */
    let confirmBulk = $state<'category' | 'all' | null>(null);
    let confirmBulkTimeout: ReturnType<typeof setTimeout> | null = null;

    // =========================================================================
    // STATE — deletion in flight
    // =========================================================================

    let isDeleting = $state(false);

    /** Toast shown after a delete completes. */
    let toast = $state<{ type: 'success' | 'error'; message: string } | null>(null);

    // =========================================================================
    // DERIVED
    // =========================================================================

    let totalBytes = $derived(files.reduce((s, f) => s + f.file_size_bytes, 0));

    /**
     * Map a backend category name to the matching i18n key.
     */
    function categoryLabel(cat: string): string {
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
        return keyMap[cat] ?? cat;
    }

    // =========================================================================
    // HELPERS
    // =========================================================================

    function formatBytes(bytes: number): string {
        if (bytes === 0) return '0 B';
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(1024));
        const value = bytes / Math.pow(1024, i);
        return i >= 2 ? `${value.toFixed(1)} ${units[i]}` : `${Math.round(value)} ${units[i]}`;
    }

    function formatDate(ts: number): string {
        return new Date(ts * 1000).toLocaleDateString(undefined, {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
        });
    }

    // =========================================================================
    // EFFECTS
    // =========================================================================

    /**
     * Load the file list whenever the category changes (i.e. on mount and if
     * the user somehow lands on a different category sub-page).
     */
    $effect(() => {
        const cat = category;
        if (cat) loadFiles(cat);
    });

    // =========================================================================
    // API — load
    // =========================================================================

    async function loadFiles(cat: string): Promise<void> {
        isLoading = true;
        loadError = null;
        files = [];

        try {
            const url = new URL(getApiEndpoint('/v1/settings/storage/files'));
            url.searchParams.set('category', cat);

            const resp = await fetch(url.toString(), { credentials: 'include' });
            if (!resp.ok) {
                const body = await resp.text().catch(() => '');
                throw new Error(`HTTP ${resp.status}: ${body || resp.statusText}`);
            }

            const data: StorageFilesListResponse = await resp.json();
            files = data.files;
        } catch (err) {
            console.error('[SettingsStorageFiles] Failed to load files:', err);
            loadError = err instanceof Error ? err.message : String(err);
        } finally {
            isLoading = false;
        }
    }

    // =========================================================================
    // FILE — open in new tab
    // =========================================================================

    /**
     * Open a stored file in a new browser tab.
     * The /view endpoint server-side decrypts and streams the file.
     * Session cookies are sent automatically by the browser for same-origin requests.
     */
    function openFile(file: StorageFileItem): void {
        const url = getApiEndpoint(
            `/v1/settings/storage/files/${encodeURIComponent(file.embed_id)}/view`
        );
        window.open(url, '_blank', 'noopener,noreferrer');
    }

    // =========================================================================
    // DELETE — per-file 2-press
    // =========================================================================

    /**
     * Handle a tap on a file's trash button.
     *
     * First tap:  enter confirm mode for this file (auto-resets after 3 s).
     *             Any other file in confirm mode is immediately reset.
     * Second tap: execute the deletion.
     */
    async function handleDeleteFile(file: StorageFileItem): Promise<void> {
        if (confirmFileId !== file.id) {
            // First press — enter confirm mode
            clearFileConfirm();
            clearBulkConfirm();
            confirmFileId = file.id;
            confirmFileTimeout = setTimeout(() => { confirmFileId = null; }, 3000);
            return;
        }

        // Second press — execute
        clearFileConfirm();
        await executeDelete({ scope: 'single', file_id: file.id });
    }

    function clearFileConfirm(): void {
        if (confirmFileTimeout !== null) clearTimeout(confirmFileTimeout);
        confirmFileTimeout = null;
        confirmFileId = null;
    }

    // =========================================================================
    // DELETE — bulk 2-press
    // =========================================================================

    /**
     * Handle a tap on "Delete all [category]" or "Delete all files".
     * Same 2-press pattern as per-file, but tracked separately.
     */
    async function handleBulkDelete(scope: 'category' | 'all'): Promise<void> {
        if (confirmBulk !== scope) {
            // First press — enter confirm mode
            clearBulkConfirm();
            clearFileConfirm();
            confirmBulk = scope;
            confirmBulkTimeout = setTimeout(() => { confirmBulk = null; }, 3000);
            return;
        }

        // Second press — execute
        clearBulkConfirm();
        const body: Record<string, string> = { scope };
        if (scope === 'category') body['category'] = category;
        await executeDelete(body);
    }

    function clearBulkConfirm(): void {
        if (confirmBulkTimeout !== null) clearTimeout(confirmBulkTimeout);
        confirmBulkTimeout = null;
        confirmBulk = null;
    }

    // =========================================================================
    // DELETE — execution
    // =========================================================================

    /**
     * Call DELETE /v1/settings/storage/files, update state, and show toast.
     *
     * After successful deletion:
     * - If this category now has no files → navigate back to the overview.
     * - Otherwise reload the file list.
     */
    async function executeDelete(body: Record<string, string>): Promise<void> {
        if (isDeleting) return;
        isDeleting = true;
        toast = null;

        try {
            const resp = await fetch(getApiEndpoint('/v1/settings/storage/files'), {
                method: 'DELETE',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            if (!resp.ok) {
                const errBody = await resp.text().catch(() => '');
                throw new Error(`HTTP ${resp.status}: ${errBody || resp.statusText}`);
            }

            const result: { deleted_count: number; bytes_freed: number } = await resp.json();

            toast = {
                type: 'success',
                message: $text('settings.storage.storage_delete_success', {
                    values: {
                        count: result.deleted_count,
                        size: formatBytes(result.bytes_freed),
                    },
                }),
            };
            setTimeout(() => { toast = null; }, 5000);

            // Reload to see what's left in this category
            await loadFiles(category);

            // If the category is now empty, go back to the storage overview.
            // Give the toast a moment to be visible first.
            if (files.length === 0) {
                setTimeout(() => {
                    dispatch('navigateBack');
                }, 1200);
            }
        } catch (err) {
            console.error('[SettingsStorageFiles] Deletion failed:', err);
            toast = {
                type: 'error',
                message: $text('settings.storage.storage_delete_error'),
            };
            setTimeout(() => { toast = null; }, 5000);
        } finally {
            isDeleting = false;
        }
    }
</script>

<div class="files-container">

    <!-- ── Loading ─────────────────────────────────────────────────────────── -->
    {#if isLoading}
        <div class="loading-state">
            <div class="spinner"></div>
            <span>{$text('settings.storage.storage_files_loading')}</span>
        </div>

    <!-- ── Error ───────────────────────────────────────────────────────────── -->
    {:else if loadError}
        <div class="error-state">
            <p class="error-text">{loadError}</p>
        </div>

    <!-- ── Empty ───────────────────────────────────────────────────────────── -->
    {:else if files.length === 0}
        <div class="empty-state">
            <p>{$text('settings.storage.storage_files_empty')}</p>
        </div>

    <!-- ── File list ───────────────────────────────────────────────────────── -->
    {:else}
        <ul class="file-list">
            {#each files as file (file.id)}
                <li class="file-row">
                    <!--
                        Clickable filename area — opens the decrypted file in a new tab.
                        The server authenticates via session cookie before streaming.
                    -->
                    <button
                        class="file-info"
                        onclick={() => openFile(file)}
                        title={file.original_filename}
                        disabled={isDeleting}
                    >
                        <span class="file-name">{file.original_filename}</span>
                        <span class="file-meta">
                            {formatBytes(file.file_size_bytes)}
                            {#if file.created_at}
                                · {formatDate(file.created_at)}
                            {/if}
                        </span>
                    </button>

                    <!--
                        Trash button with 2-press confirm.
                        First press → turns red and shows "Confirm?" label.
                        Second press (within 3 s) → executes deletion.
                        Pressing a different file's trash resets this one.
                    -->
                    <button
                        class="btn-delete"
                        class:confirm-mode={confirmFileId === file.id}
                        onclick={() => handleDeleteFile(file)}
                        aria-label={confirmFileId === file.id
                            ? $text('settings.storage.storage_delete_confirm')
                            : $text('settings.storage.storage_delete_file')}
                        disabled={isDeleting}
                    >
                        {#if confirmFileId === file.id}
                            <span class="confirm-label">
                                {$text('settings.storage.storage_delete_confirm')}
                            </span>
                        {:else}
                            <div class="icon icon_trash"></div>
                        {/if}
                    </button>
                </li>
            {/each}
        </ul>

        <!-- Footer: summary line -->
        <div class="list-footer">
            {$text('settings.storage.storage_files_count', { values: { count: files.length } })}
            · {formatBytes(totalBytes)}
        </div>

        <!-- Bulk delete buttons -->
        <div class="bulk-actions">
            <!--
                "Delete all [category]" — 2-press confirm.
                Only deletes files in this category.
            -->
            <button
                class="btn-bulk"
                class:confirm-mode={confirmBulk === 'category'}
                onclick={() => handleBulkDelete('category')}
                disabled={isDeleting}
            >
                {#if confirmBulk === 'category'}
                    {$text('settings.storage.storage_delete_confirm')}
                {:else}
                    {$text('settings.storage.storage_delete_category', {
                        values: { category: $text(categoryLabel(category)) }
                    })}
                {/if}
            </button>

            <!--
                "Delete all files" — 2-press confirm.
                Deletes ALL uploaded files across every category.
            -->
            <button
                class="btn-bulk btn-bulk-danger"
                class:confirm-mode={confirmBulk === 'all'}
                onclick={() => handleBulkDelete('all')}
                disabled={isDeleting}
            >
                {#if confirmBulk === 'all'}
                    {$text('settings.storage.storage_delete_confirm')}
                {:else}
                    {$text('settings.storage.storage_delete_all')}
                {/if}
            </button>
        </div>
    {/if}

</div>

<!-- ── Toast ───────────────────────────────────────────────────────────────── -->
{#if toast}
    <div
        class="toast"
        class:toast-success={toast.type === 'success'}
        class:toast-error={toast.type === 'error'}
    >
        {toast.message}
    </div>
{/if}

<style>
    /* ── Container ─────────────────────────────────────────────────────────── */
    .files-container {
        display: flex;
        flex-direction: column;
        /* No extra padding — SettingsItem rows handle their own horizontal padding */
    }

    /* ── Loading ───────────────────────────────────────────────────────────── */
    .loading-state {
        display: flex;
        align-items: center;
        gap: var(--spacing-6);
        color: var(--color-grey-60);
        padding: var(--spacing-16) var(--spacing-12);
    }

    .spinner {
        width: 18px;
        height: 18px;
        border: 2px solid var(--color-grey-30);
        border-top-color: var(--color-primary);
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
        flex-shrink: 0;
    }

    @keyframes spin {
        to { transform: rotate(360deg); }
    }

    /* ── Error / Empty ─────────────────────────────────────────────────────── */
    .error-state,
    .empty-state {
        padding: var(--spacing-16) var(--spacing-12);
        color: var(--color-grey-50);
        font-size: var(--font-size-small);
    }

    .error-text {
        margin: 0;
        color: var(--color-danger);
        font-size: var(--font-size-xs);
    }

    /* ── File list ─────────────────────────────────────────────────────────── */
    .file-list {
        list-style: none;
        padding: 0;
        margin: 0;
    }

    .file-row {
        display: flex;
        align-items: center;
        gap: var(--spacing-4);
        padding: var(--spacing-6) var(--spacing-10);
        border-bottom: 1px solid var(--color-grey-15);
    }

    .file-row:last-child {
        border-bottom: none;
    }

    /* Filename / info area (clickable) */
    .file-info {
        flex: 1;
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 3px;
        padding: 2px 0;
        background: none;
        border: none;
        text-align: left;
        cursor: pointer;
        min-width: 0;
        border-radius: var(--radius-2);
        transition: opacity 0.12s;
    }

    .file-info:disabled {
        opacity: 0.5;
        cursor: default;
    }

    .file-name {
        font-size: var(--font-size-small);
        font-weight: 500;
        color: var(--color-grey-80);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 100%;
    }

    .file-meta {
        font-size: var(--font-size-xxs);
        color: var(--color-grey-50);
        white-space: nowrap;
    }

    /* Per-file trash / confirm button */
    .btn-delete {
        flex-shrink: 0;
        height: 32px;
        min-width: 32px;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 0 6px;
        background: none;
        border: 1px solid transparent;
        border-radius: var(--radius-2);
        cursor: pointer;
        opacity: 0.45;
        transition: opacity var(--duration-fast), background var(--duration-fast), border-color var(--duration-fast), color var(--duration-fast);
        color: var(--color-grey-60);
    }

    .btn-delete .icon {
        width: 16px;
        height: 16px;
        background: var(--color-grey-60);
        mask-size: contain;
        mask-repeat: no-repeat;
    }

    .btn-delete:hover:not(:disabled) {
        opacity: 1;
        background: var(--color-danger-light);
        border-color: var(--color-danger);
    }

    .btn-delete:hover:not(:disabled) .icon {
        background: var(--color-danger);
    }

    /* Confirm mode: already red and fully opaque */
    .btn-delete.confirm-mode {
        opacity: 1;
        background: var(--color-danger);
        border-color: var(--color-danger);
        color: white;
        padding: 0 10px;
    }

    .btn-delete:disabled {
        opacity: 0.3;
        cursor: not-allowed;
    }

    .confirm-label {
        font-size: var(--font-size-xxs);
        font-weight: 600;
        white-space: nowrap;
    }

    /* ── Footer summary ────────────────────────────────────────────────────── */
    .list-footer {
        padding: var(--spacing-5) var(--spacing-10);
        font-size: var(--font-size-xxs);
        color: var(--color-grey-50);
        border-top: 1px solid var(--color-grey-15);
    }

    /* ── Bulk actions ──────────────────────────────────────────────────────── */
    .bulk-actions {
        display: flex;
        flex-direction: column;
        gap: var(--spacing-5);
        padding: var(--spacing-10);
        border-top: 1px solid var(--color-grey-15);
    }

    .btn-bulk {
        width: 100%;
        padding: 11px 16px;
        border-radius: var(--radius-4);
        border: 1px solid var(--color-grey-25);
        background: transparent;
        font-size: var(--font-size-small);
        font-weight: 600;
        color: var(--color-grey-70);
        cursor: pointer;
        transition: background var(--duration-fast), border-color var(--duration-fast), color var(--duration-fast);
        text-align: center;
    }

    .btn-bulk:hover:not(:disabled) {
        background: var(--color-grey-10);
    }

    /* "Delete all [category]" danger styling */
    .btn-bulk.btn-bulk-danger {
        border-color: var(--color-danger);
        color: var(--color-danger);
    }

    .btn-bulk.btn-bulk-danger:hover:not(:disabled) {
        background: var(--color-danger-light);
    }

    /* Confirm mode for both bulk buttons */
    .btn-bulk.confirm-mode {
        background: var(--color-danger);
        border-color: var(--color-danger);
        color: white;
    }

    .btn-bulk.confirm-mode:hover:not(:disabled) {
        opacity: 0.88;
        background: var(--color-danger);
    }

    .btn-bulk:disabled {
        opacity: 0.4;
        cursor: not-allowed;
    }

    /* ── Toast ─────────────────────────────────────────────────────────────── */
    .toast {
        position: fixed;
        bottom: 24px;
        left: 50%;
        transform: translateX(-50%);
        padding: var(--spacing-6) var(--spacing-10);
        border-radius: var(--radius-4);
        font-size: var(--font-size-small);
        font-weight: 500;
        max-width: 420px;
        text-align: center;
        z-index: 1100;
        box-shadow: var(--shadow-lg);
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
