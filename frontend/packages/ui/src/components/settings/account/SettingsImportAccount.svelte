<!--
    Import Account Settings - Account Import V1
    Allows users to import Claude official exports and OpenMates Export V1
    archives. The browser parses locally, the server transiently scans selected
    plaintext, and this client encrypts chats/messages before permanent
    persistence. Legacy plaintext import endpoints remain disabled.
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { authStore } from '../../../stores/authStore';
    import {
        parseImportFile,
        previewImport,
        estimateImportCost,
        importChats,
        type ParsedAccountImport,
        type ImportCostEstimate,
        type ImportPreviewResponse,
        type ImportedChatResult,
        type ImportProgressCallback,
    } from '../../../services/chatImportService';
    import SettingsButton from '../elements/SettingsButton.svelte';
    import SettingsButtonGroup from '../elements/SettingsButtonGroup.svelte';
    import SettingsCard from '../elements/SettingsCard.svelte';
    import SettingsCheckboxList from '../elements/SettingsCheckboxList.svelte';
    import SettingsDetailRow from '../elements/SettingsDetailRow.svelte';
    import SettingsFileUpload from '../elements/SettingsFileUpload.svelte';
    import SettingsInfoBox from '../elements/SettingsInfoBox.svelte';
    import SettingsProgressBar from '../elements/SettingsProgressBar.svelte';
    import SettingsSectionHeading from '../elements/SettingsSectionHeading.svelte';

    type ChatOption = {
        id: string;
        label: string;
        description?: string;
        icon?: string;
        checked: boolean;
    };

    let selectedFile = $state<File | null>(null);
    let parsedImport = $state<ParsedAccountImport | null>(null);
    let preview = $state<ImportPreviewResponse | null>(null);
    let selectedIndices = $state<Set<number>>(new Set());
    let costEstimate = $state<ImportCostEstimate | null>(null);
    let isImporting = $state(false);
    let importStatus = $state('');
    let importProgress = $state(0);
    let importResults = $state<ImportedChatResult[] | null>(null);
    let totalCreditsCharged = $state(0);
    let errorMessage = $state<string | null>(null);

    let selectedChats = $derived(
        parsedImport ? parsedImport.chats.filter((_, index) => selectedIndices.has(index)) : []
    );
    let hasSelection = $derived(selectedChats.length > 0);
    let duplicateFingerprints = $derived(new Set(preview?.duplicate_fingerprints ?? []));
    let chatOptions = $derived<ChatOption[]>(
        parsedImport?.chats.map((chat, index) => {
            const messageCount = chat.messages.length;
            const duplicate = duplicateFingerprints.has(chat.source_fingerprint);
            const title = chat.title || $text('settings.account.import_untitled');
            return {
                id: String(index),
                label: duplicate ? `${title} (possible duplicate)` : title,
                description: `${messageCount} ${$text('settings.account.import_messages_count')}`,
                icon: chat.provider === 'claude' ? 'icon_ai' : 'icon_chat',
                checked: selectedIndices.has(index),
            };
        }) ?? []
    );

    const progressCallback: ImportProgressCallback = (phase, detail) => {
        importStatus = detail;
        importProgress = phase === 'parsing'
            ? 10
            : phase === 'previewing'
                ? 20
                : phase === 'scanning'
                    ? 45
                    : phase === 'encrypting'
                        ? 65
                        : phase === 'persisting'
                            ? 82
                            : phase === 'completing'
                                ? 94
                                : 100;
    };

    async function handleFileSelected(file: File): Promise<void> {
        resetState();
        selectedFile = file;
        importStatus = $text('settings.account.import_scanning');
        try {
            const parsed = await parseImportFile(file, progressCallback);
            const previewResult = await previewImport(parsed, progressCallback);
            parsedImport = parsed;
            preview = previewResult;
            const defaultCount = Math.min(
                previewResult.default_selection_count,
                previewResult.max_batch_count,
                parsed.chats.length
            );
            selectedIndices = new Set(parsed.chats.slice(0, defaultCount).map((_, index) => index));
            costEstimate = estimateImportCost(parsed.chats.slice(0, defaultCount));
            if (!previewResult.can_import) {
                errorMessage = previewResult.reason === 'insufficient_credits'
                    ? 'You do not have enough free allowance or credits for this import.'
                    : `Import is not available: ${previewResult.reason}`;
            }
        } catch (error) {
            errorMessage = error instanceof Error ? error.message : String(error);
        } finally {
            importStatus = '';
            importProgress = 0;
        }
    }

    function updateChatSelection(id: string, checked: boolean): void {
        if (!parsedImport || !preview) return;
        const index = Number(id);
        if (!Number.isInteger(index)) return;
        const next = new Set(selectedIndices);
        if (checked) {
            if (!next.has(index) && next.size >= preview.max_batch_count) {
                errorMessage = `Select ${preview.max_batch_count} chats or fewer for this import.`;
                return;
            }
            next.add(index);
        } else {
            next.delete(index);
        }
        selectedIndices = next;
        costEstimate = estimateImportCost(parsedImport.chats.filter((_, chatIndex) => next.has(chatIndex)));
        errorMessage = null;
    }

    function selectDefault(): void {
        if (!parsedImport || !preview) return;
        const count = Math.min(
            preview.default_selection_count,
            preview.max_batch_count,
            parsedImport.chats.length
        );
        selectedIndices = new Set(parsedImport.chats.slice(0, count).map((_, index) => index));
        costEstimate = estimateImportCost(parsedImport.chats.slice(0, count));
        errorMessage = null;
    }

    function deselectAll(): void {
        selectedIndices = new Set();
        costEstimate = null;
        errorMessage = null;
    }

    async function startImport(): Promise<void> {
        if (!$authStore.isAuthenticated || !parsedImport || !preview || !hasSelection) return;

        isImporting = true;
        errorMessage = null;
        importResults = null;
        importStatus = '';
        importProgress = 0;

        try {
            const response = await importChats(parsedImport, selectedChats, preview, progressCallback);
            importResults = response.imported;
            totalCreditsCharged = response.total_credits_charged;
        } catch (error) {
            errorMessage = error instanceof Error ? error.message : String(error);
        } finally {
            isImporting = false;
        }
    }

    function resetState(): void {
        selectedFile = null;
        parsedImport = null;
        preview = null;
        selectedIndices = new Set();
        costEstimate = null;
        isImporting = false;
        importStatus = '';
        importProgress = 0;
        importResults = null;
        totalCreditsCharged = 0;
        errorMessage = null;
    }
</script>

<SettingsInfoBox type="info" icon="icon_info">
    <p>{$text('settings.account.import_description')}</p>
</SettingsInfoBox>

    {#if importResults}
        <SettingsInfoBox type="success" icon="icon_check">
            <span>{$text('settings.account.import_success')}</span>
        </SettingsInfoBox>

        <SettingsCard padding="sm" ariaLabel="Imported chats">
            <div data-testid="import-results-container">
                {#each importResults as result}
                    <SettingsDetailRow
                        label={result.title || $text('settings.account.import_untitled')}
                        value={`${result.messages_imported} ${$text('settings.account.import_messages_imported')}${result.messages_blocked > 0 ? ` / ${result.messages_blocked} ${$text('settings.account.import_messages_blocked')}` : ''}`}
                        ariaLabel="Imported chat result"
                    />
                {/each}
            </div>
            {#if totalCreditsCharged > 0}
                <SettingsDetailRow
                    label={$text('settings.account.import_credits_charged')}
                    value={String(totalCreditsCharged)}
                    highlight={true}
                />
            {/if}
        </SettingsCard>

        <SettingsButtonGroup align="left">
            <SettingsButton variant="secondary" onClick={resetState} dataTestid="account-import-another">
                {$text('settings.account.import_another')}
            </SettingsButton>
        </SettingsButtonGroup>
    {:else}
        {#if !isImporting}
            <SettingsSectionHeading title={$text('settings.account.import_title')} icon="download" />
            <SettingsFileUpload
                accept=".zip,.json"
                label={selectedFile ? selectedFile.name : 'Select Claude export or OpenMates ZIP'}
                disabled={!$authStore.isAuthenticated}
                ariaLabel={$text('settings.account.import_choose_file')}
                dataTestid="account-import-file-upload"
                onFileSelected={handleFileSelected}
            />
        {/if}

        {#if parsedImport && preview && !isImporting}
            <SettingsCard padding="sm" ariaLabel="Import preview">
                <div data-testid="import-preview-summary">
                    <SettingsDetailRow label="Chats found" value={String(parsedImport.chats.length)} />
                    <SettingsDetailRow label="Default selection" value={String(preview.default_selection_count)} />
                    <SettingsDetailRow label="Batch limit" value={String(preview.max_batch_count)} />
                    {#if preview.free_remaining !== undefined}
                        <SettingsDetailRow label="Free allowance remaining" value={String(preview.free_remaining)} />
                    {/if}
                </div>
            </SettingsCard>

            {#if parsedImport.skippedDomains.length > 0}
                <SettingsInfoBox type="info" icon="icon_info">
                    <p>
                        This OpenMates archive also contains {parsedImport.skippedDomains.join(', ')}.
                        Account Import V1 imports chats, referenced embeds, and uploads only. Other domains are tracked in OPE-588.
                    </p>
                </SettingsInfoBox>
            {/if}

            {#if preview.duplicate_fingerprints.length > 0}
                <SettingsInfoBox type="warning" icon="icon_warning">
                    <p>
                        {preview.duplicate_fingerprints.length} selected chat(s) may already have been imported.
                        Continuing will create new chats and will not merge or overwrite existing chats.
                    </p>
                </SettingsInfoBox>
            {/if}

            <SettingsSectionHeading title={$text('settings.account.import_select_chats')} icon="chat" />
            <SettingsCard padding="sm">
                <SettingsButtonGroup align="space-between">
                    <SettingsButton variant="ghost" size="sm" onClick={selectDefault} dataTestid="account-import-select-default">
                        Select default
                    </SettingsButton>
                    <SettingsButton variant="ghost" size="sm" onClick={deselectAll} dataTestid="account-import-deselect-all">
                        {$text('settings.account.import_deselect_all')}
                    </SettingsButton>
                </SettingsButtonGroup>
                <div data-testid="import-select-section">
                    <SettingsCheckboxList
                        options={chatOptions}
                        onChange={updateChatSelection}
                        dataTestid="import-chat-list"
                    />
                </div>
            </SettingsCard>

            {#if costEstimate && hasSelection}
                <SettingsInfoBox type="info" icon="icon_credits">
                    <p>
                        {$text('settings.account.import_estimated_cost')}: ~{preview.estimated_credits} {$text('settings.account.import_credits')}
                        ({costEstimate.chatCount} {$text('settings.account.import_chats_selected')}, {costEstimate.messageCount} {$text('settings.account.import_messages_count')}).
                    </p>
                </SettingsInfoBox>
            {/if}
        {/if}

        {#if isImporting}
            <SettingsCard>
                <SettingsProgressBar value={importProgress} label={importStatus || $text('settings.account.import_scanning')} showPercent={true} />
            </SettingsCard>
            <SettingsInfoBox type="info" icon="icon_info">
                <p>{$text('settings.account.import_scanning_note')}</p>
            </SettingsInfoBox>
        {/if}

        {#if errorMessage}
            <SettingsInfoBox type="error" icon="icon_warning">
                <span>{errorMessage}</span>
            </SettingsInfoBox>
        {/if}

        <SettingsInfoBox type="info" icon="icon_info">
            <p>{$text('settings.account.import_safety_notice')}</p>
        </SettingsInfoBox>

        <SettingsButtonGroup align="left">
            <SettingsButton
                variant="primary"
                fullWidth={true}
                onClick={startImport}
                disabled={isImporting || !$authStore.isAuthenticated || !hasSelection || preview?.can_import === false}
                loading={isImporting}
                dataTestid="account-import-start"
            >
                {$text('settings.account.import_button')}
            </SettingsButton>
        </SettingsButtonGroup>

        {#if !$authStore.isAuthenticated}
            <SettingsInfoBox type="warning" icon="icon_warning">
                <p>{$text('settings.account.import_login_required')}</p>
            </SettingsInfoBox>
        {/if}
    {/if}
