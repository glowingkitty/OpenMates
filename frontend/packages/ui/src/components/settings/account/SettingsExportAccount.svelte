<!--
Export Account Settings - GDPR Article 20 Data Portability
Allows users to export all their data as a ZIP file with YML format
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { exportAllUserData, type ExportProgress } from '../../../services/accountExportService';
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

    // ========================================================================
    // COMPUTED
    // ========================================================================
    
    /** Progress bar percentage (0-100) */
    let progressPercent = $derived(exportProgress?.progress ?? 0);
    
    /** Human-readable phase name */
    let phaseName = $derived(() => {
        if (!exportProgress) return '';
        switch (exportProgress.phase) {
            case 'init': return 'Initializing...';
            case 'manifest': return 'Checking data...';
            case 'syncing': return 'Syncing chats...';
            case 'loading': return 'Loading data...';
            case 'decrypting': return 'Decrypting...';
            case 'downloading_pdfs': return 'Downloading invoices...';
            case 'creating_zip': return 'Creating archive...';
            case 'complete': return 'Complete!';
            case 'error': return 'Error';
            default: return 'Processing...';
        }
    });

    // ========================================================================
    // HANDLERS
    // ========================================================================
    
    /**
     * Handle export progress updates from the service
     */
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
    
    /**
     * Start the data export process
     */
    async function startExport(): Promise<void> {
        // Check authentication
        if (!$authStore.isAuthenticated) {
            errorMessage = $text('settings.account.export_requires_login');
            return;
        }
        
        // Reset state
        errorMessage = null;
        successMessage = null;
        isExporting = true;
        exportProgress = null;
        
        try {
            await exportAllUserData(handleProgress);
        } catch (error) {
            console.error('[SettingsExportAccount] Export failed:', error);
            errorMessage = error instanceof Error ? error.message : $text('settings.account.export_failed');
            isExporting = false;
        }
    }
    
    /**
     * Reset the export state to allow another export
     */
    function resetState(): void {
        exportProgress = null;
        errorMessage = null;
        successMessage = null;
    }
</script>

<div class="export-account-container">
    <!-- Header -->
    <div class="export-header">
        <h2>{$text('settings.account.export_title')}</h2>
        <p class="description">{$text('settings.account.export_description')}</p>
    </div>

    <!-- What's Included Section -->
    <div class="info-box">
        <h3>{$text('settings.account.export_includes_title')}</h3>
        <ul class="includes-list">
            <li>
                <div class="icon icon_chat"></div>
                <span>{$text('settings.account.export_includes_chats')}</span>
            </li>
            <li>
                <div class="icon icon_document"></div>
                <span>{$text('settings.account.export_includes_invoices')}</span>
            </li>
            <li>
                <div class="icon icon_stats"></div>
                <span>{$text('settings.account.export_includes_usage')}</span>
            </li>
            <li>
                <div class="icon icon_settings"></div>
                <span>{$text('settings.account.export_includes_settings')}</span>
            </li>
            <li>
                <div class="icon icon_user"></div>
                <span>{$text('settings.account.export_includes_profile')}</span>
            </li>
        </ul>
    </div>

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
            <button
                class="btn btn-secondary"
                onclick={resetState}
            >
                {$text('settings.account.export_another')}
            </button>
        {:else}
            <button
                class="btn btn-primary"
                onclick={startExport}
                disabled={isExporting || !$authStore.isAuthenticated}
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

    <!-- Login Required Notice (for non-authenticated users) -->
    {#if !$authStore.isAuthenticated}
        <div class="login-notice">
            <p>{$text('settings.account.export_login_required')}</p>
        </div>
    {/if}
</div>

<style>
    .export-account-container {
        padding: 24px;
        max-width: 600px;
    }

    .export-header {
        margin-bottom: 24px;
    }

    .export-header h2 {
        font-size: 20px;
        font-weight: 600;
        color: var(--color-grey-80);
        margin-bottom: 8px;
    }

    .description {
        color: var(--color-grey-60);
        line-height: 1.5;
    }

    .info-box {
        background: var(--color-grey-10);
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 20px;
    }

    .info-box h3 {
        font-size: 16px;
        font-weight: 600;
        color: var(--color-grey-80);
        margin-bottom: 16px;
    }

    .includes-list {
        list-style: none;
        padding: 0;
        margin: 0;
    }

    .includes-list li {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 8px 0;
        color: var(--color-grey-70);
    }

    .includes-list .icon {
        width: 20px;
        height: 20px;
        background: var(--color-primary);
        flex-shrink: 0;
    }

    .gdpr-notice {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        background: var(--color-info-light);
        border: 1px solid var(--color-info);
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 24px;
    }

    .gdpr-notice .icon {
        width: 20px;
        height: 20px;
        background: var(--color-info);
        flex-shrink: 0;
        margin-top: 2px;
    }

    .gdpr-notice p {
        color: var(--color-grey-70);
        font-size: 14px;
        line-height: 1.5;
        margin: 0;
    }

    .progress-container {
        background: var(--color-grey-10);
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 20px;
    }

    .progress-header {
        display: flex;
        justify-content: space-between;
        margin-bottom: 12px;
    }

    .phase-name {
        font-weight: 600;
        color: var(--color-grey-80);
    }

    .progress-percent {
        color: var(--color-primary);
        font-weight: 600;
    }

    .progress-bar {
        height: 8px;
        background: var(--color-grey-20);
        border-radius: 4px;
        overflow: hidden;
    }

    .progress-fill {
        height: 100%;
        background: var(--color-primary);
        border-radius: 4px;
        transition: width 0.3s ease;
    }

    .progress-message {
        margin-top: 12px;
        color: var(--color-grey-60);
        font-size: 14px;
    }

    .current-item {
        margin-top: 4px;
        color: var(--color-grey-50);
        font-size: 13px;
        font-style: italic;
    }

    .error-message {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 16px;
        background: var(--color-danger-light);
        border: 1px solid var(--color-danger);
        border-radius: 8px;
        margin-bottom: 20px;
    }

    .error-message .icon {
        width: 20px;
        height: 20px;
        background: var(--color-danger);
        flex-shrink: 0;
    }

    .error-message span {
        color: var(--color-danger);
    }

    .success-message {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 16px;
        background: var(--color-success-light);
        border: 1px solid var(--color-success);
        border-radius: 8px;
        margin-bottom: 20px;
    }

    .success-message .icon {
        width: 20px;
        height: 20px;
        background: var(--color-success);
        flex-shrink: 0;
    }

    .success-message span {
        color: var(--color-success);
    }

    .action-buttons {
        margin-top: 24px;
    }

    .btn {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        width: 100%;
        padding: 14px 24px;
        border: none;
        border-radius: 8px;
        font-size: 16px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.2s, opacity 0.2s;
    }

    .btn-primary {
        background: var(--color-primary);
        color: white;
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
        color: var(--color-grey-80);
    }

    .btn-secondary:hover {
        background: var(--color-grey-30);
    }

    .btn .icon {
        width: 20px;
        height: 20px;
        background: white;
    }

    .loading-spinner {
        width: 20px;
        height: 20px;
        border: 2px solid rgba(255, 255, 255, 0.3);
        border-top-color: white;
        border-radius: 50%;
        animation: spin 1s linear infinite;
    }

    @keyframes spin {
        to {
            transform: rotate(360deg);
        }
    }

    .login-notice {
        margin-top: 16px;
        padding: 12px 16px;
        background: var(--color-warning-light);
        border: 1px solid var(--color-warning);
        border-radius: 8px;
    }

    .login-notice p {
        color: var(--color-grey-70);
        font-size: 14px;
        margin: 0;
    }
</style>

