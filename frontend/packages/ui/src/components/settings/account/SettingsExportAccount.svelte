<!--
Export Account Settings - GDPR Article 20 Data Portability
Allows users to export all their data as a ZIP file with YAML/CSV/binary formats.
Users can select which categories to include (all selected by default).
See docs/architecture/sync.md for the encryption model.
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import {
        exportAllUserData,
        type ExportProgress,
        type ExportOptions,
        DEFAULT_EXPORT_OPTIONS,
    } from '../../../services/accountExportService';
    import { authStore } from '../../../stores/authStore';

    // ========================================================================
    // STATE
    // ========================================================================

    /** Whether export is currently in progress */
    let isExporting = $state(false);

    /** Current export progress */
    let exportProgress = $state<ExportProgress | null>(null);

    /** Error message if export fails */
    let errorMessage = $state<string | null>(null);

    /** Success message after export completes */
    let successMessage = $state<string | null>(null);

    /** Selective export options — all checked by default */
    let exportOptions = $state<ExportOptions>({ ...DEFAULT_EXPORT_OPTIONS });

    // ========================================================================
    // COMPUTED
    // ========================================================================

    /** Progress bar percentage (0-100) */
    let progressPercent = $derived(exportProgress?.progress ?? 0);

    /** Whether at least one category is selected */
    let hasSelection = $derived(
        exportOptions.includeChats ||
        exportOptions.includeInvoices ||
        exportOptions.includeUsage ||
        exportOptions.includeSettings ||
        exportOptions.includeProfile
    );

    /** Human-readable phase name */
    let phaseName = $derived(() => {
        if (!exportProgress) return '';
        switch (exportProgress.phase) {
            case 'init': return 'Initializing...';
            case 'manifest': return 'Checking data...';
            case 'syncing': return 'Syncing chats...';
            case 'loading': return 'Loading data...';
            case 'decrypting': return 'Decrypting data...';
            case 'downloading_pdfs': return 'Downloading invoices...';
            case 'downloading_files': return 'Downloading chat files...';
            case 'downloading_profile_image': return 'Downloading profile image...';
            case 'creating_zip': return 'Creating archive...';
            case 'complete': return 'Complete!';
            case 'error': return 'Error';
            default: return 'Processing...';
        }
    });

    // ========================================================================
    // HANDLERS
    // ========================================================================

    function handleProgress(progress: ExportProgress): void {
        exportProgress = progress;

        if (progress.phase === 'complete') {
            successMessage = $text('settings.account.export_success');
            isExporting = false;
        } else if (progress.phase === 'error') {
            errorMessage = progress.error || $text('settings.account.export_failed');
            isExporting = false;
        }
    }

    async function startExport(): Promise<void> {
        if (!$authStore.isAuthenticated) {
            errorMessage = $text('settings.account.export_requires_login');
            return;
        }
        if (!hasSelection) return;

        errorMessage = null;
        successMessage = null;
        isExporting = true;
        exportProgress = null;

        try {
            await exportAllUserData(handleProgress, exportOptions);
        } catch (error) {
            console.error('[SettingsExportAccount] Export failed:', error);
            errorMessage =
                error instanceof Error
                    ? error.message
                    : $text('settings.account.export_failed');
            isExporting = false;
        }
    }

    function resetState(): void {
        exportProgress = null;
        errorMessage = null;
        successMessage = null;
        // Reset options back to all-selected
        exportOptions = { ...DEFAULT_EXPORT_OPTIONS };
    }

    function selectAll(): void {
        exportOptions = { ...DEFAULT_EXPORT_OPTIONS };
    }

    function deselectAll(): void {
        exportOptions = {
            includeChats: false,
            includeChatFiles: false,
            includeInvoices: false,
            includeUsage: false,
            includeSettings: false,
            includeProfile: false,
        };
    }
</script>

<div class="export-account-container">
    <!-- Header -->
    <div class="export-header">
        <h2>{$text('settings.account.export_title')}</h2>
        <p class="description">{$text('settings.account.export_description')}</p>
    </div>

    <!-- Selective Export Options -->
    {#if !isExporting && !successMessage}
        <div class="select-section">
            <div class="select-header">
                <h3>{$text('settings.account.export_includes_title')}</h3>
                <div class="select-all-controls">
                    <button class="btn-link" onclick={selectAll} type="button">{$text('settings.account.export_select_all')}</button>
                    <span class="separator">·</span>
                    <button class="btn-link" onclick={deselectAll} type="button">{$text('settings.account.export_deselect_all')}</button>
                </div>
            </div>

            <ul class="export-options-list">
                <li class="option-item">
                    <label class="option-label">
                        <input
                            type="checkbox"
                            class="option-checkbox"
                            bind:checked={exportOptions.includeChats}
                            disabled={isExporting}
                        />
                        <div class="option-icon icon_chat"></div>
                        <div class="option-text">
                            <span class="option-name">{$text('settings.account.export_includes_chats')}</span>
                            <span class="option-desc">{$text('settings.account.export_includes_chats')}</span>
                        </div>
                    </label>
                    {#if exportOptions.includeChats}
                        <label class="option-label option-sub">
                            <input
                                type="checkbox"
                                class="option-checkbox"
                                bind:checked={exportOptions.includeChatFiles}
                                disabled={isExporting}
                            />
                            <div class="option-icon icon_attachment"></div>
                            <div class="option-text">
                                <span class="option-name">{$text('settings.account.export_includes_chat_files')}</span>
                                <span class="option-desc">{$text('settings.account.export_includes_chat_files_desc')}</span>
                            </div>
                        </label>
                    {/if}
                </li>

                <li class="option-item">
                    <label class="option-label">
                        <input
                            type="checkbox"
                            class="option-checkbox"
                            bind:checked={exportOptions.includeProfile}
                            disabled={isExporting}
                        />
                        <div class="option-icon icon_user"></div>
                        <div class="option-text">
                            <span class="option-name">{$text('settings.account.export_includes_profile')}</span>
                            <span class="option-desc">{$text('settings.account.export_includes_profile_desc')}</span>
                        </div>
                    </label>
                </li>

                <li class="option-item">
                    <label class="option-label">
                        <input
                            type="checkbox"
                            class="option-checkbox"
                            bind:checked={exportOptions.includeSettings}
                            disabled={isExporting}
                        />
                        <div class="option-icon icon_settings"></div>
                        <div class="option-text">
                            <span class="option-name">{$text('settings.account.export_includes_settings')}</span>
                            <span class="option-desc">{$text('settings.account.export_includes_settings_desc')}</span>
                        </div>
                    </label>
                </li>

                <li class="option-item">
                    <label class="option-label">
                        <input
                            type="checkbox"
                            class="option-checkbox"
                            bind:checked={exportOptions.includeUsage}
                            disabled={isExporting}
                        />
                        <div class="option-icon icon_stats"></div>
                        <div class="option-text">
                            <span class="option-name">{$text('settings.account.export_includes_usage')}</span>
                            <span class="option-desc">{$text('settings.account.export_includes_usage_desc')}</span>
                        </div>
                    </label>
                </li>

                <li class="option-item">
                    <label class="option-label">
                        <input
                            type="checkbox"
                            class="option-checkbox"
                            bind:checked={exportOptions.includeInvoices}
                            disabled={isExporting}
                        />
                        <div class="option-icon icon_document"></div>
                        <div class="option-text">
                            <span class="option-name">{$text('settings.account.export_includes_invoices')}</span>
                            <span class="option-desc">{$text('settings.account.export_includes_invoices')}</span>
                        </div>
                    </label>
                </li>
            </ul>
        </div>
    {/if}

    <!-- GDPR Notice -->
    <div class="gdpr-notice">
        <div class="icon icon_info"></div>
        <p>{$text('settings.account.export_gdpr_notice')}</p>
    </div>

    <!-- Export Progress -->
    {#if isExporting && exportProgress}
        <div class="progress-container">
            <div class="progress-header">
                <span class="phase-name">{phaseName()}</span>
                <span class="progress-percent">{progressPercent}%</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" style="width: {progressPercent}%"></div>
            </div>
            {#if exportProgress.message}
                <p class="progress-message">{exportProgress.message}</p>
            {/if}
            {#if exportProgress.currentItem}
                <p class="current-item">{exportProgress.currentItem}</p>
            {/if}
        </div>
    {/if}

    <!-- Error Message -->
    {#if errorMessage}
        <div class="error-message">
            <div class="icon icon_error"></div>
            <span>{errorMessage}</span>
        </div>
    {/if}

    <!-- Success Message -->
    {#if successMessage}
        <div class="success-message">
            <div class="icon icon_check"></div>
            <span>{successMessage}</span>
        </div>
    {/if}

    <!-- Action Buttons -->
    <div class="action-buttons">
        {#if successMessage}
            <button class="btn btn-secondary" onclick={resetState} type="button">
                {$text('settings.account.export_another')}
            </button>
        {:else}
            <button
                class="btn btn-primary"
                onclick={startExport}
                disabled={isExporting || !$authStore.isAuthenticated || !hasSelection}
                type="button"
            >
                {#if isExporting}
                    <span class="loading-spinner"></span>
                    {$text('settings.account.exporting')}
                {:else}
                    <div class="icon icon_download"></div>
                    {$text('settings.account.export_button')}
                {/if}
            </button>
        {/if}
    </div>

    {#if !$authStore.isAuthenticated}
        <div class="login-notice">
            <p>{$text('settings.account.export_login_required')}</p>
        </div>
    {/if}
</div>

<style>
    .export-account-container {
        max-width: 640px;
        padding-bottom: 2rem;
    }

    .export-header {
        margin-bottom: 1.5rem;
    }

    .export-header h2 {
        font-size: var(--font-size-h2);
        font-weight: 700;
        color: var(--color-font-primary);
        margin: 0 0 0.5rem 0;
    }

    .description {
        color: var(--color-font-secondary);
        font-size: var(--font-size-p);
        line-height: 1.5;
        margin: 0;
    }

    /* ── Select Section ──────────────────────────────────────────────────── */
    .select-section {
        background: var(--color-grey-10);
        border: 1px solid var(--color-grey-25);
        border-radius: 12px;
        padding: 1.25rem;
        margin-bottom: 1.5rem;
    }

    .select-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 1rem;
    }

    .select-header h3 {
        font-size: var(--font-size-p);
        font-weight: 600;
        color: var(--color-font-primary);
        margin: 0;
    }

    .select-all-controls {
        display: flex;
        align-items: center;
        gap: 0.25rem;
    }

    .separator {
        color: var(--color-font-tertiary);
    }

    .btn-link {
        background: none;
        border: none;
        padding: 0;
        color: var(--color-primary);
        font-size: var(--processing-details-font-size);
        cursor: pointer;
        text-decoration: underline;
        text-underline-offset: 2px;
    }

    .btn-link:hover {
        opacity: 0.8;
    }

    /* ── Export Options List ─────────────────────────────────────────────── */
    .export-options-list {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }

    .option-item {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
    }

    .option-label {
        display: flex;
        align-items: flex-start;
        gap: 0.75rem;
        cursor: pointer;
        padding: 0.625rem 0.75rem;
        border-radius: 8px;
        transition: background 0.15s;
    }

    .option-label:hover {
        background: var(--color-grey-20);
    }

    .option-label.option-sub {
        margin-left: 2rem;
        background: var(--color-grey-0);
        border: 1px solid var(--color-grey-25);
    }

    .option-label.option-sub:hover {
        background: var(--color-grey-10);
    }

    .option-checkbox {
        width: 1rem;
        height: 1rem;
        margin-top: 0.125rem;
        cursor: pointer;
        accent-color: var(--color-primary);
        flex-shrink: 0;
    }

    .option-icon {
        width: 1.125rem;
        height: 1.125rem;
        background: var(--color-font-secondary);
        flex-shrink: 0;
        margin-top: 0.125rem;
    }

    .option-text {
        display: flex;
        flex-direction: column;
        gap: 0.125rem;
    }

    .option-name {
        font-size: var(--font-size-p);
        font-weight: 500;
        color: var(--color-font-primary);
        line-height: 1.3;
    }

    .option-desc {
        font-size: var(--processing-details-font-size);
        color: var(--color-font-secondary);
        line-height: 1.4;
    }

    /* ── GDPR Notice ─────────────────────────────────────────────────────── */
    .gdpr-notice {
        display: flex;
        align-items: flex-start;
        gap: 0.75rem;
        background: var(--color-info-light);
        border: 1px solid var(--color-info);
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 1.5rem;
    }

    .gdpr-notice .icon {
        width: 1.25rem;
        height: 1.25rem;
        background: var(--color-info);
        flex-shrink: 0;
        margin-top: 0.125rem;
    }

    .gdpr-notice p {
        color: var(--color-font-secondary);
        font-size: var(--processing-details-font-size);
        line-height: 1.5;
        margin: 0;
    }

    /* ── Progress ────────────────────────────────────────────────────────── */
    .progress-container {
        background: var(--color-grey-10);
        border-radius: 12px;
        padding: 1.25rem;
        margin-bottom: 1.25rem;
    }

    .progress-header {
        display: flex;
        justify-content: space-between;
        margin-bottom: 0.75rem;
    }

    .phase-name {
        font-weight: 600;
        color: var(--color-font-primary);
        font-size: var(--font-size-p);
    }

    .progress-percent {
        color: var(--color-primary);
        font-weight: 600;
        font-size: var(--font-size-p);
    }

    .progress-bar {
        height: 0.5rem;
        background: var(--color-grey-20);
        border-radius: 0.25rem;
        overflow: hidden;
    }

    .progress-fill {
        height: 100%;
        background: var(--color-primary);
        border-radius: 0.25rem;
        transition: width 0.3s ease;
    }

    .progress-message {
        margin-top: 0.75rem;
        color: var(--color-font-secondary);
        font-size: var(--processing-details-font-size);
        margin-bottom: 0;
    }

    .current-item {
        margin-top: 0.25rem;
        color: var(--color-font-tertiary);
        font-size: var(--processing-details-font-size);
        font-style: italic;
        margin-bottom: 0;
    }

    /* ── Messages ────────────────────────────────────────────────────────── */
    .error-message {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 1rem;
        background: var(--color-danger-light);
        border: 1px solid var(--color-danger);
        border-radius: 8px;
        margin-bottom: 1.25rem;
    }

    .error-message .icon {
        width: 1.25rem;
        height: 1.25rem;
        background: var(--color-danger);
        flex-shrink: 0;
    }

    .error-message span {
        color: var(--color-danger);
        font-size: var(--font-size-p);
    }

    .success-message {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 1rem;
        background: var(--color-success-light);
        border: 1px solid var(--color-success);
        border-radius: 8px;
        margin-bottom: 1.25rem;
    }

    .success-message .icon {
        width: 1.25rem;
        height: 1.25rem;
        background: var(--color-success);
        flex-shrink: 0;
    }

    .success-message span {
        color: var(--color-success);
        font-size: var(--font-size-p);
    }

    /* ── Buttons ─────────────────────────────────────────────────────────── */
    .action-buttons {
        margin-top: 1.5rem;
    }

    .btn {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 0.5rem;
        width: 100%;
        padding: 0.875rem 1.5rem;
        border: none;
        border-radius: 8px;
        font-size: var(--button-font-size);
        font-weight: 600;
        cursor: pointer;
        transition: background 0.2s, opacity 0.2s;
    }

    .btn-primary {
        background: var(--color-primary);
        color: var(--color-grey-0);
    }

    .btn-primary:hover:not(:disabled) {
        background: var(--color-primary-dark);
    }

    .btn-primary:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .btn-secondary {
        background: var(--color-grey-20);
        color: var(--color-font-primary);
    }

    .btn-secondary:hover {
        background: var(--color-grey-30);
    }

    .btn .icon {
        width: 1.25rem;
        height: 1.25rem;
        background: var(--color-grey-0);
    }

    .loading-spinner {
        width: 1.25rem;
        height: 1.25rem;
        border: 2px solid rgba(255, 255, 255, 0.3);
        border-top-color: var(--color-grey-0);
        border-radius: 50%;
        animation: spin 1s linear infinite;
        flex-shrink: 0;
    }

    @keyframes spin {
        to { transform: rotate(360deg); }
    }

    .login-notice {
        margin-top: 1rem;
        padding: 0.75rem 1rem;
        background: var(--color-warning-bg);
        border: 1px solid var(--color-warning);
        border-radius: 8px;
    }

    .login-notice p {
        color: var(--color-font-secondary);
        font-size: var(--processing-details-font-size);
        margin: 0;
    }
</style>
