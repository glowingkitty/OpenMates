<!--
Settings > Account > Chats
Displays total server-side chat count and a "Delete Old Chats" section with:
  1. Period dropdown
  2. "Preview" button that shows how many chats will be deleted
  3. "Delete" confirm button that appears after preview
  4. After delete: cleans up IndexedDB client-side for deleted chat IDs

Architecture:
  - GET /v1/settings/chats            → total_count (single meta=total_count request)
  - GET /v1/settings/chats/preview    → count of chats older than N days
  - POST /v1/settings/chats/delete-old → delete + return deleted_ids for IndexedDB cleanup
  - created_at stored as Unix int in Directus; backend handles Unix timestamp filter

Tests: none yet — new settings sub-page.
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { getApiEndpoint, apiEndpoints } from '../../../config/api';

    // =========================================================================
    // STATE
    // =========================================================================

    let totalCount = $state<number | null>(null);
    let isLoading = $state(true);
    let errorMessage = $state<string | null>(null);

    // Delete-old state
    type DeleteDays = 0 | 1 | 7 | 14 | 30 | 90;

    let selectedDays = $state<DeleteDays>(30);

    // Preview state
    let previewCount = $state<number | null>(null);
    let isPreviewing = $state(false);
    let previewError = $state<string | null>(null);

    // Delete state
    let isDeleting = $state(false);
    let deleteResult = $state<{ count: number } | null>(null);
    let deleteError = $state<string | null>(null);

    // Reset preview whenever the user changes the period
    $effect(() => {
        // Reactively depend on selectedDays — reset preview on change
        void selectedDays;
        previewCount = null;
        previewError = null;
        deleteResult = null;
        deleteError = null;
    });

    // =========================================================================
    // EFFECTS
    // =========================================================================

    $effect(() => {
        fetchTotalCount();
    });

    // =========================================================================
    // API
    // =========================================================================

    async function fetchTotalCount(): Promise<void> {
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
            const data = await res.json();
            totalCount = data.total_count ?? 0;
        } catch (err) {
            console.error('[SettingsAccountChats] Failed to load chat count:', err);
            errorMessage = err instanceof Error ? err.message : String(err);
        } finally {
            isLoading = false;
        }
    }

    async function fetchPreview(): Promise<void> {
        isPreviewing = true;
        previewError = null;
        previewCount = null;
        deleteResult = null;
        deleteError = null;

        try {
            const url = getApiEndpoint(apiEndpoints.settings.previewOldChats) +
                `?older_than_days=${selectedDays}`;
            const res = await fetch(url, { credentials: 'include' });
            if (!res.ok) {
                const body = await res.text().catch(() => '');
                throw new Error(`HTTP ${res.status}: ${body || res.statusText}`);
            }
            const data = await res.json();
            previewCount = data.count ?? 0;
        } catch (err) {
            console.error('[SettingsAccountChats] Failed to preview:', err);
            previewError = err instanceof Error ? err.message : String(err);
        } finally {
            isPreviewing = false;
        }
    }

    async function performDelete(): Promise<void> {
        isDeleting = true;
        deleteError = null;
        deleteResult = null;

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

            // Clean up IndexedDB for deleted chats
            if (Array.isArray(data.deleted_ids) && data.deleted_ids.length > 0) {
                await cleanupIndexedDB(data.deleted_ids);
            }

            // Refresh total count after deletion
            previewCount = null;
            await fetchTotalCount();
        } catch (err) {
            console.error('[SettingsAccountChats] Failed to delete old chats:', err);
            deleteError = err instanceof Error ? err.message : String(err);
        } finally {
            isDeleting = false;
        }
    }

    // =========================================================================
    // INDEXEDDB CLEANUP
    // =========================================================================

    /**
     * Delete chat records from IndexedDB for the given IDs.
     * Uses the same DB name/store the chat store uses.
     */
    async function cleanupIndexedDB(chatIds: string[]): Promise<void> {
        try {
            const dbName = 'openmates';
            const db = await new Promise<IDBDatabase>((resolve, reject) => {
                const req = indexedDB.open(dbName);
                req.onsuccess = () => resolve(req.result);
                req.onerror = () => reject(req.error);
            });

            const storeNames = Array.from(db.objectStoreNames);
            const chatStores = storeNames.filter(name =>
                name === 'chats' || name === 'messages' || name === 'chat_messages'
            );

            if (chatStores.length === 0) {
                db.close();
                return;
            }

            const tx = db.transaction(chatStores, 'readwrite');
            const deletePromises: Promise<void>[] = [];

            // Delete from chats store by chat ID (keyPath = chat_id)
            if (storeNames.includes('chats')) {
                const store = tx.objectStore('chats');
                for (const id of chatIds) {
                    deletePromises.push(new Promise<void>((res, rej) => {
                        const r = store.delete(id);
                        r.onsuccess = () => res();
                        r.onerror = () => rej(r.error);
                    }));
                }
            }

            // Delete associated messages using the chat_id index
            if (storeNames.includes('messages')) {
                const msgStore = tx.objectStore('messages');
                const chatIdIndex = msgStore.index('chat_id');
                for (const id of chatIds) {
                    // Use index cursor to find and delete all messages for this chat
                    deletePromises.push(new Promise<void>((res, rej) => {
                        const req = chatIdIndex.openKeyCursor(IDBKeyRange.only(id));
                        req.onsuccess = () => {
                            const cursor = req.result;
                            if (cursor) {
                                msgStore.delete(cursor.primaryKey);
                                cursor.continue();
                            } else {
                                res(); // No more messages for this chat_id
                            }
                        };
                        req.onerror = () => rej(req.error);
                    }));
                }
            }

            await Promise.allSettled(deletePromises);
            await new Promise<void>((res, rej) => {
                tx.oncomplete = () => res();
                tx.onerror = () => rej(tx.error);
            });

            db.close();
            console.warn(`[SettingsAccountChats] Cleaned up ${chatIds.length} chats and their messages from IndexedDB`);
        } catch (err) {
            // Non-fatal: IndexedDB cleanup failure doesn't block the UI
            console.warn('[SettingsAccountChats] IndexedDB cleanup failed (non-fatal):', err);
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
            <button class="btn-retry" onclick={fetchTotalCount}>
                {$text('settings.account.chats.retry')}
            </button>
        </div>

    <!-- ── Loaded ──────────────────────────────────────────────────────────── -->
    {:else if totalCount !== null}

        <!-- Total count badge -->
        <div class="count-card">
            <div class="count-number">{totalCount.toLocaleString()}</div>
            <div class="count-label">{$text('settings.account.chats')}</div>
        </div>

        <!-- Delete old chats -->
        <div class="section-card danger-section">
            <h3 class="section-title">{$text('settings.account.chats.delete_section_title')}</h3>
            <p class="section-desc">{$text('settings.account.chats.delete_section_desc')}</p>

            <!-- Row 1: label + dropdown + Preview button -->
            <div class="delete-row">
                <span class="select-label">{$text('settings.account.chats.delete_older_than')}</span>
                <select
                    class="period-select"
                    bind:value={selectedDays}
                    disabled={isDeleting || isPreviewing}
                >
                    <option value={1}>{$text('settings.account.chats.delete_option_1d')}</option>
                    <option value={7}>{$text('settings.account.chats.delete_option_7d')}</option>
                    <option value={14}>{$text('settings.account.chats.delete_option_14d')}</option>
                    <option value={30}>{$text('settings.account.chats.delete_option_30d')}</option>
                    <option value={90}>{$text('settings.account.chats.delete_option_90d')}</option>
                    <option value={0}>{$text('settings.account.chats.delete_option_all')}</option>
                </select>
                <button
                    class="btn-preview"
                    onclick={fetchPreview}
                    disabled={isPreviewing || isDeleting}
                >
                    {isPreviewing
                        ? $text('settings.account.chats.preview_loading')
                        : $text('settings.account.chats.preview_button')}
                </button>
            </div>

            <!-- Preview result -->
            {#if previewCount !== null}
                <div class="preview-result">
                    {previewCount === 0
                        ? $text('settings.account.chats.preview_none')
                        : $text('settings.account.chats.preview_result', { values: { count: String(previewCount) } })}
                </div>
            {/if}
            {#if previewError}
                <div class="feedback error">{previewError}</div>
            {/if}

            <!-- Delete button — only shown after preview with count > 0 -->
            {#if previewCount !== null && previewCount > 0 && !deleteResult}
                <button
                    class="btn-delete"
                    onclick={performDelete}
                    disabled={isDeleting}
                >
                    {isDeleting
                        ? $text('settings.account.chats.delete_deleting')
                        : $text('settings.account.chats.delete_button')}
                </button>
            {/if}

            <!-- Delete result feedback -->
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
        border-top-color: var(--color-primary-start);
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
        background: var(--color-error-light);
        border: 1px solid var(--color-error);
        border-radius: 12px;
    }

    .error-text {
        font-weight: 600;
        color: var(--color-error);
        margin: 0;
    }

    .error-detail {
        font-size: 13px;
        color: var(--color-error);
        margin: 0;
        word-break: break-word;
    }

    .btn-retry {
        align-self: flex-start;
        padding: 8px 16px;
        background: var(--color-error);
        color: var(--color-grey-0);
        border: none;
        border-radius: 6px;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
    }

    .btn-retry:hover { opacity: 0.85; }

    /* ── Count card — uses grey vars so it works in both light and dark mode ── */
    .count-card {
        background: var(--color-grey-20);
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
        color: var(--color-primary-start);
        line-height: 1;
    }

    .count-label {
        font-size: 14px;
        font-weight: 500;
        color: var(--color-grey-60);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }

    /* ── Section card ──────────────────────────────────────────────────────── */
    .section-card {
        background: var(--color-grey-20);
        border-radius: 14px;
        padding: 20px;
        display: flex;
        flex-direction: column;
        gap: 14px;
    }

    .section-title {
        font-size: 13px;
        font-weight: 600;
        color: var(--color-grey-60);
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin: 0;
    }

    .section-desc {
        font-size: 14px;
        color: var(--color-grey-60);
        margin: 0;
        line-height: 1.5;
    }

    /* ── Delete section ────────────────────────────────────────────────────── */
    .danger-section {
        border: 1px solid var(--color-grey-30);
    }

    /* ── Delete controls row ───────────────────────────────────────────────── */
    .delete-row {
        display: flex;
        align-items: center;
        gap: 10px;
        flex-wrap: wrap;
    }

    .select-label {
        font-size: 14px;
        color: var(--color-grey-70);
        white-space: nowrap;
        flex-shrink: 0;
    }

    .period-select {
        flex: 1;
        min-width: 100px;
        padding: 8px 12px;
        border: 1px solid var(--color-grey-30);
        border-radius: 8px;
        background: var(--color-grey-10);
        color: var(--color-grey-90);
        font-size: 14px;
        cursor: pointer;
        appearance: auto;
    }

    .period-select:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .btn-preview {
        padding: 9px 16px;
        background: var(--color-grey-30);
        color: var(--color-grey-90);
        border: 1px solid var(--color-grey-40);
        border-radius: 8px;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        white-space: nowrap;
        flex-shrink: 0;
        transition: opacity 0.15s;
    }

    .btn-preview:hover:not(:disabled) { opacity: 0.75; }
    .btn-preview:disabled { opacity: 0.5; cursor: not-allowed; }

    /* ── Preview result ────────────────────────────────────────────────────── */
    .preview-result {
        font-size: 14px;
        font-weight: 600;
        color: var(--color-grey-90);
        padding: 10px 14px;
        background: var(--color-grey-30);
        border-radius: 8px;
    }

    /* ── Delete button ─────────────────────────────────────────────────────── */
    .btn-delete {
        align-self: flex-start;
        padding: 9px 18px;
        background: var(--color-error);
        color: var(--color-grey-0);
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
        padding: 10px 14px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
    }

    .feedback.success {
        background: var(--color-success-light, rgba(47, 133, 90, 0.15));
        color: var(--color-success, #2f855a);
        border: 1px solid var(--color-success, #2f855a);
    }

    .feedback.error {
        background: var(--color-error-light);
        color: var(--color-error);
        border: 1px solid var(--color-error);
    }
</style>
