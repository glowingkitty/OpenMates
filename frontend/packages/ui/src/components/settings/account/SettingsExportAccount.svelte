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
    import SettingsButton from '../elements/SettingsButton.svelte';
    import SettingsButtonGroup from '../elements/SettingsButtonGroup.svelte';
    import SettingsCard from '../elements/SettingsCard.svelte';
    import SettingsCheckboxList from '../elements/SettingsCheckboxList.svelte';
    import SettingsInfoBox from '../elements/SettingsInfoBox.svelte';
    import SettingsProgressBar from '../elements/SettingsProgressBar.svelte';
    import SettingsSectionHeading from '../elements/SettingsSectionHeading.svelte';

    type CheckboxOption = {
        id: keyof ExportOptions;
        label: string;
        description?: string;
        icon?: string;
        checked: boolean;
    };

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

    let exportCategoryOptions = $derived<CheckboxOption[]>([
        {
            id: 'includeChats',
            label: $text('settings.account.export_includes_chats'),
            description: $text('settings.account.export_includes_chats'),
            icon: 'icon_chat',
            checked: exportOptions.includeChats,
        },
        {
            id: 'includeProfile',
            label: $text('settings.account.export_includes_profile'),
            description: $text('settings.account.export_includes_profile_desc'),
            icon: 'icon_user',
            checked: exportOptions.includeProfile,
        },
        {
            id: 'includeSettings',
            label: $text('settings.account.export_includes_settings'),
            description: $text('settings.account.export_includes_settings_desc'),
            icon: 'icon_settings',
            checked: exportOptions.includeSettings,
        },
        {
            id: 'includeUsage',
            label: $text('settings.account.export_includes_usage'),
            description: $text('settings.account.export_includes_usage_desc'),
            icon: 'icon_task',
            checked: exportOptions.includeUsage,
        },
        {
            id: 'includeInvoices',
            label: $text('settings.account.export_includes_invoices'),
            description: $text('settings.account.export_includes_invoices'),
            icon: 'icon_files',
            checked: exportOptions.includeInvoices,
        },
    ]);

    let chatFileOptions = $derived<CheckboxOption[]>([
        {
            id: 'includeChatFiles',
            label: $text('settings.account.export_includes_chat_files'),
            description: $text('settings.account.export_includes_chat_files_desc'),
            icon: 'icon_files',
            checked: exportOptions.includeChatFiles,
        },
    ]);

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

    function updateExportOption(id: string, checked: boolean): void {
        if (!(id in exportOptions)) return;

        exportOptions = {
            ...exportOptions,
            [id]: checked,
        };
    }
</script>

<div class="export-account-container">
    <p class="description">{$text('settings.account.export_description')}</p>

    <!-- Selective Export Options -->
    {#if !isExporting && !successMessage}
        <SettingsSectionHeading
            title={$text('settings.account.export_includes_title')}
            icon="download"
        />
        <SettingsCard padding="sm">
            <SettingsButtonGroup align="space-between">
                <SettingsButton variant="ghost" size="sm" onClick={selectAll}>
                    {$text('common.select_all')}
                </SettingsButton>
                <SettingsButton variant="ghost" size="sm" onClick={deselectAll}>
                    {$text('settings.account.export_deselect_all')}
                </SettingsButton>
            </SettingsButtonGroup>
            <div class="checkbox-block">
                <SettingsCheckboxList
                    options={exportCategoryOptions}
                    onChange={updateExportOption}
                />
                {#if exportOptions.includeChats}
                    <SettingsCheckboxList
                        options={chatFileOptions}
                        nested={true}
                        onChange={updateExportOption}
                    />
                {/if}
            </div>
        </SettingsCard>
    {/if}

    <!-- GDPR Notice -->
    <SettingsInfoBox type="info" icon="icon_question">
        <p>{$text('settings.account.export_gdpr_notice')}</p>
    </SettingsInfoBox>

    <!-- Export Progress -->
    {#if isExporting && exportProgress}
        <SettingsCard>
            <SettingsProgressBar value={progressPercent} label={phaseName()} showPercent={true} />
            {#if exportProgress.message}
                <p class="progress-message">{exportProgress.message}</p>
            {/if}
            {#if exportProgress.currentItem}
                <p class="current-item">{exportProgress.currentItem}</p>
            {/if}
        </SettingsCard>
    {/if}

    <!-- Error Message -->
    {#if errorMessage}
        <SettingsInfoBox type="error" icon="icon_warning">
            <span>{errorMessage}</span>
        </SettingsInfoBox>
    {/if}

    <!-- Success Message -->
    {#if successMessage}
        <SettingsInfoBox type="success" icon="icon_check">
            <span>{successMessage}</span>
        </SettingsInfoBox>
    {/if}

    <!-- Action Buttons -->
    <SettingsButtonGroup align="left">
        {#if successMessage}
            <SettingsButton variant="secondary" fullWidth={true} onClick={resetState}>
                {$text('settings.account.export_another')}
            </SettingsButton>
        {:else}
            <SettingsButton
                variant="primary"
                fullWidth={true}
                onClick={startExport}
                disabled={isExporting || !$authStore.isAuthenticated || !hasSelection}
                loading={isExporting}
            >
                {#if isExporting}
                    {$text('settings.account.exporting')}
                {:else}
                    <span class="button-icon clickable-icon icon_download"></span>
                    {$text('settings.account.export_button')}
                {/if}
            </SettingsButton>
        {/if}
    </SettingsButtonGroup>

    {#if !$authStore.isAuthenticated}
        <SettingsInfoBox type="warning">
            <p>{$text('settings.account.export_login_required')}</p>
        </SettingsInfoBox>
    {/if}
</div>

<style>
    .export-account-container {
        max-width: 640px;
        padding-bottom: 2rem;
    }

    .description {
        padding: 0 0.625rem;
        color: var(--color-font-secondary);
        font-size: var(--font-size-p);
        line-height: 1.5;
        margin-bottom: 1.5rem;
    }

    .checkbox-block {
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
        margin-top: 0.75rem;
    }

    :global(.export-account-container .settings-card) {
        margin-bottom: 1.5rem;
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

    .button-icon {
        width: 1.25rem;
        height: 1.25rem;
        background: var(--color-grey-0);
        margin-right: 0.5rem;
    }
</style>
