<!--
  Import Account Settings — Chat Import from ZIP or YAML
  Allows users to import chats exported via Settings → Account → Export.
  Accepts OpenMates export ZIP files (primary) and YAML files (secondary).
  Each message is safety-scanned by the backend (gpt-oss-safeguard-20b via
  OpenRouter) before storage. The user is shown a credit cost estimate before
  confirming, and charged only for successfully imported chats.

  See docs/architecture/account-backup.md for the export/import model.
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { authStore } from '../../../stores/authStore';
    import {
        parseImportFile,
        estimateImportCost,
        importChats,
        type ParsedImportChat,
        type ImportCostEstimate,
        type ImportedChatResult,
        type ImportFileType,
        type ImportProgressCallback,
    } from '../../../services/chatImportService';

    // ========================================================================
    // STATE
    // ========================================================================

    /** File chosen by the user via the file picker */
    let selectedFile = $state<File | null>(null);

    /** Detected file type (zip or yaml) */
    let fileType = $state<ImportFileType | null>(null);

    /** Parsed chats from the file (before submission) */
    let parsedChats = $state<ParsedImportChat[]>([]);

    /** Which chats the user has checked for import */
    let selectedIndices = $state<Set<number>>(new Set());

    /** Cost estimate for the selected chats */
    let costEstimate = $state<ImportCostEstimate | null>(null);

    /** Parse error displayed to the user */
    let parseError = $state<string | null>(null);

    /** Whether the import is currently running */
    let isImporting = $state(false);

    /** Live status message during import */
    let importStatus = $state<string>('');

    /** Import results after completion */
    let importResults = $state<ImportedChatResult[] | null>(null);

    /** Total credits charged in the last run */
    let totalCreditsCharged = $state(0);

    /** Error message if import fails */
    let errorMessage = $state<string | null>(null);

    // ========================================================================
    // DERIVED
    // ========================================================================

    let selectedChats = $derived(
        parsedChats.filter((_, i) => selectedIndices.has(i))
    );

    let hasSelection = $derived(selectedChats.length > 0);

    // ========================================================================
    // FILE HANDLING
    // ========================================================================

    async function handleFileChange(event: Event): Promise<void> {
        const input = event.target as HTMLInputElement;
        const file = input.files?.[0] ?? null;
        selectedFile = file;
        fileType = null;
        parsedChats = [];
        selectedIndices = new Set();
        costEstimate = null;
        parseError = null;
        importResults = null;
        errorMessage = null;

        if (!file) return;

        try {
            const result = await parseImportFile(file);
            fileType = result.fileType;
            parsedChats = result.chats;
            // Select all by default
            selectedIndices = new Set(result.chats.map((_, i) => i));
            costEstimate = estimateImportCost(result.chats);
        } catch (e) {
            parseError = e instanceof Error ? e.message : String(e);
        }
    }

    function toggleChat(index: number): void {
        const next = new Set(selectedIndices);
        if (next.has(index)) {
            next.delete(index);
        } else {
            next.add(index);
        }
        selectedIndices = next;
        costEstimate = estimateImportCost(parsedChats.filter((_, i) => next.has(i)));
    }

    function selectAll(): void {
        selectedIndices = new Set(parsedChats.map((_, i) => i));
        costEstimate = estimateImportCost(parsedChats);
    }

    function deselectAll(): void {
        selectedIndices = new Set();
        costEstimate = null;
    }

    // ========================================================================
    // IMPORT
    // ========================================================================

    async function startImport(): Promise<void> {
        if (!$authStore.isAuthenticated || !hasSelection) return;

        isImporting = true;
        errorMessage = null;
        importResults = null;
        importStatus = '';

        const progressCallback: ImportProgressCallback = (_phase, detail) => {
            importStatus = detail;
        };

        try {
            const response = await importChats(selectedChats, progressCallback);
            importResults = response.imported;
            totalCreditsCharged = response.total_credits_charged;
        } catch (e) {
            errorMessage = e instanceof Error ? e.message : String(e);
        } finally {
            isImporting = false;
        }
    }

    function resetState(): void {
        selectedFile = null;
        fileType = null;
        parsedChats = [];
        selectedIndices = new Set();
        costEstimate = null;
        parseError = null;
        importResults = null;
        errorMessage = null;
        importStatus = '';
        // Reset the file input
        const input = document.getElementById('import-file-input') as HTMLInputElement | null;
        if (input) input.value = '';
    }
</script>

<div class="import-account-container">
    <!-- Header -->
    <div class="import-header">
        <h2>{$text('settings.account.import_title')}</h2>
        <p class="description">{$text('settings.account.import_description')}</p>
    </div>

    {#if importResults}
        <!-- ── Success State ─────────────────────────────────────────────── -->
        <div class="results-container" data-testid="import-results-container">
            <div class="success-banner">
                <div class="icon icon_check"></div>
                <span>{$text('settings.account.import_success')}</span>
            </div>

            <ul class="results-list">
                {#each importResults as result}
                    <li class="result-item" data-testid="import-result-item">
                        <div class="result-title">{result.title || $text('common.untitled_chat')}</div>
                        <div class="result-stats">
                            <span>{result.messages_imported} {$text('settings.account.import_messages_imported')}</span>
                            {#if result.messages_blocked > 0}
                                <span class="blocked-badge">
                                    {result.messages_blocked} {$text('settings.account.import_messages_blocked')}
                                </span>
                            {/if}
                        </div>
                    </li>
                {/each}
            </ul>

            {#if totalCreditsCharged > 0}
                <p class="credits-charged">
                    {$text('settings.account.import_credits_charged')}: <strong>{totalCreditsCharged}</strong>
                </p>
            {/if}
        </div>

        <div class="action-buttons">
            <button class="btn btn-secondary" onclick={resetState} type="button">
                {$text('settings.account.import_another')}
            </button>
        </div>

    {:else}
        <!-- ── File Picker ────────────────────────────────────────────────── -->
        {#if !isImporting}
            <div class="file-section">
                <label class="file-label" for="import-file-input">
                    <div class="icon icon_upload"></div>
                    <span>
                        {selectedFile ? selectedFile.name : $text('settings.account.import_choose_file')}
                    </span>
                    {#if fileType}
                        <span class="file-type-badge file-type-badge--{fileType}">{fileType.toUpperCase()}</span>
                    {/if}
                </label>
                <input
                    id="import-file-input"
                    type="file"
                    accept=".zip,.yml,.yaml"
                    class="file-input-hidden"
                    onchange={handleFileChange}
                />
            </div>
        {/if}

        <!-- ── Parse Error ────────────────────────────────────────────────── -->
        {#if parseError}
            <div class="error-message">
                <div class="icon icon_error"></div>
                <span>{parseError}</span>
            </div>
        {/if}

        <!-- ── Chat Selection ─────────────────────────────────────────────── -->
        {#if parsedChats.length > 0 && !isImporting}
            <div class="select-section" data-testid="import-select-section">
                <div class="select-header">
                    <h3>{$text('settings.account.import_select_chats')}</h3>
                    <div class="select-all-controls">
                        <button class="btn-link" onclick={selectAll} type="button">
                            {$text('common.select_all')}
                        </button>
                        <span class="separator">·</span>
                        <button class="btn-link" onclick={deselectAll} type="button">
                            {$text('settings.account.import_deselect_all')}
                        </button>
                    </div>
                </div>

                <ul class="chat-list">
                    {#each parsedChats as chat, i}
                        <li class="chat-item" data-testid="chat-item">
                            <label class="chat-label">
                                <input
                                    type="checkbox"
                                    class="chat-checkbox"
                                    checked={selectedIndices.has(i)}
                                    onchange={() => toggleChat(i)}
                                />
                                <div class="chat-info">
                                    <span class="chat-title">{chat.title || $text('common.untitled_chat')}</span>
                                    <span class="chat-meta">
                                        {chat.messages.length} {$text('settings.account.import_messages_count')}
                                    </span>
                                </div>
                            </label>
                        </li>
                    {/each}
                </ul>
            </div>

            <!-- ── Cost Estimate ────────────────────────────────────────────── -->
            {#if costEstimate && hasSelection}
                <div class="cost-estimate">
                    <div class="icon icon_credits"></div>
                    <div class="cost-text">
                        <span class="cost-label">{$text('settings.account.import_estimated_cost')}</span>
                        <strong class="cost-value">~{costEstimate.estimatedCredits} {$text('common.credits')}</strong>
                        <span class="cost-detail">
                            ({costEstimate.chatCount} {$text('settings.account.import_chats_selected')},
                            {costEstimate.messageCount} {$text('settings.account.import_messages_count')})
                        </span>
                    </div>
                </div>
            {/if}
        {/if}

        <!-- ── Import Progress ────────────────────────────────────────────── -->
        {#if isImporting}
            <div class="progress-container">
                <div class="loading-spinner-large"></div>
                <p class="progress-message">{importStatus || $text('settings.account.import_scanning')}</p>
                <p class="progress-note">{$text('settings.account.import_scanning_note')}</p>
            </div>
        {/if}

        <!-- ── Error ─────────────────────────────────────────────────────── -->
        {#if errorMessage}
            <div class="error-message">
                <div class="icon icon_error"></div>
                <span>{errorMessage}</span>
            </div>
        {/if}

        <!-- ── Info Notice ────────────────────────────────────────────────── -->
        {#if !isImporting}
            <div class="info-notice">
                <div class="icon icon_info"></div>
                <p>{$text('settings.account.import_safety_notice')}</p>
            </div>
        {/if}

        <!-- ── Action Buttons ─────────────────────────────────────────────── -->
        <div class="action-buttons">
            <button
                class="btn btn-primary"
                onclick={startImport}
                disabled={isImporting || !$authStore.isAuthenticated || !hasSelection}
                type="button"
            >
                {#if isImporting}
                    <span class="loading-spinner"></span>
                    {$text('settings.account.import_importing')}
                {:else}
                    <div class="icon icon_upload"></div>
                    {$text('settings.account.import_button')}
                {/if}
            </button>
        </div>

        {#if !$authStore.isAuthenticated}
            <div class="login-notice">
                <p>{$text('settings.account.import_login_required')}</p>
            </div>
        {/if}
    {/if}
</div>

<style>
    .import-account-container {
        max-width: 640px;
        padding-bottom: 2rem;
    }

    .import-header {
        margin-bottom: 1.5rem;
    }

    .import-header h2 {
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

    /* ── File picker ─────────────────────────────────────────────────────── */
    .file-section {
        margin-bottom: 1.25rem;
    }

    .file-label {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.75rem 1rem;
        border: 1.5px dashed var(--color-grey-35);
        border-radius: var(--radius-4);
        cursor: pointer;
        color: var(--color-font-secondary);
        font-size: var(--font-size-p);
        transition: border-color var(--duration-fast), background var(--duration-fast);
    }

    .file-label:hover {
        border-color: var(--color-accent);
        background: var(--color-grey-10);
    }

    .file-input-hidden {
        display: none;
    }

    /* ── Chat selection ──────────────────────────────────────────────────── */
    .select-section {
        background: var(--color-grey-10);
        border: 1px solid var(--color-grey-25);
        border-radius: var(--radius-5);
        padding: 1.25rem;
        margin-bottom: 1.25rem;
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
        color: var(--color-grey-40);
        font-size: 0.85rem;
    }

    .btn-link {
        background: none;
        border: none;
        color: var(--color-accent);
        cursor: pointer;
        font-size: 0.8rem;
        padding: 0;
    }

    .chat-list {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }

    .chat-item {
        border-radius: var(--radius-3);
        overflow: hidden;
    }

    .chat-label {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 0.6rem 0.75rem;
        cursor: pointer;
        border-radius: var(--radius-3);
        transition: background 0.1s;
    }

    .chat-label:hover {
        background: var(--color-grey-20);
    }

    .chat-checkbox {
        width: 1rem;
        height: 1rem;
        flex-shrink: 0;
        accent-color: var(--color-accent);
    }

    .chat-info {
        display: flex;
        flex-direction: column;
        gap: 0.1rem;
    }

    .chat-title {
        font-size: var(--font-size-p);
        font-weight: 500;
        color: var(--color-font-primary);
    }

    .chat-meta {
        font-size: 0.78rem;
        color: var(--color-font-secondary);
    }

    /* ── Cost estimate ───────────────────────────────────────────────────── */
    .cost-estimate {
        display: flex;
        align-items: flex-start;
        gap: 0.6rem;
        padding: 0.9rem 1rem;
        background: var(--color-grey-10);
        border: 1px solid var(--color-grey-25);
        border-radius: var(--radius-4);
        margin-bottom: 1.25rem;
    }

    .cost-text {
        display: flex;
        flex-wrap: wrap;
        align-items: baseline;
        gap: 0.35rem;
        font-size: var(--font-size-p);
    }

    .cost-label {
        color: var(--color-font-secondary);
    }

    .cost-value {
        color: var(--color-font-primary);
    }

    .cost-detail {
        color: var(--color-font-secondary);
        font-size: 0.8rem;
    }

    /* ── Progress ────────────────────────────────────────────────────────── */
    .progress-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 0.75rem;
        padding: 2rem 1rem;
        text-align: center;
    }

    .loading-spinner-large {
        width: 2.5rem;
        height: 2.5rem;
        border: 3px solid var(--color-grey-25);
        border-top-color: var(--color-accent);
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
    }

    @keyframes spin {
        to { transform: rotate(360deg); }
    }

    .progress-message {
        color: var(--color-font-primary);
        font-size: var(--font-size-p);
        margin: 0;
    }

    .progress-note {
        color: var(--color-font-secondary);
        font-size: 0.8rem;
        margin: 0;
    }

    /* ── Results ─────────────────────────────────────────────────────────── */
    .results-container {
        margin-bottom: 1.5rem;
    }

    .success-banner {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.75rem 1rem;
        background: var(--color-success-bg, #ecfdf5);
        border: 1px solid var(--color-success-border, #a7f3d0);
        border-radius: var(--radius-4);
        color: var(--color-success-text, #065f46);
        margin-bottom: 1rem;
        font-size: var(--font-size-p);
    }

    .results-list {
        list-style: none;
        padding: 0;
        margin: 0 0 1rem;
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }

    .result-item {
        padding: 0.6rem 0.75rem;
        background: var(--color-grey-10);
        border: 1px solid var(--color-grey-25);
        border-radius: var(--radius-3);
    }

    .result-title {
        font-size: var(--font-size-p);
        font-weight: 500;
        color: var(--color-font-primary);
        margin-bottom: 0.15rem;
    }

    .result-stats {
        display: flex;
        gap: 0.75rem;
        font-size: 0.78rem;
        color: var(--color-font-secondary);
    }

    .blocked-badge {
        color: var(--color-warning-text, #92400e);
    }

    .credits-charged {
        font-size: 0.85rem;
        color: var(--color-font-secondary);
        margin: 0;
    }

    /* ── Messages ────────────────────────────────────────────────────────── */
    .error-message {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.75rem 1rem;
        background: var(--color-error-bg, #fef2f2);
        border: 1px solid var(--color-error-border, #fecaca);
        border-radius: var(--radius-4);
        color: var(--color-error-text, #991b1b);
        font-size: var(--font-size-p);
        margin-bottom: 1rem;
    }

    .info-notice {
        display: flex;
        align-items: flex-start;
        gap: 0.5rem;
        padding: 0.75rem 1rem;
        background: var(--color-grey-10);
        border: 1px solid var(--color-grey-25);
        border-radius: var(--radius-4);
        margin-bottom: 1.25rem;
    }

    .info-notice p {
        margin: 0;
        font-size: 0.82rem;
        color: var(--color-font-secondary);
        line-height: 1.5;
    }

    .login-notice {
        font-size: 0.82rem;
        color: var(--color-font-secondary);
        text-align: center;
        margin-top: 0.75rem;
    }

    /* ── Buttons ─────────────────────────────────────────────────────────── */
    .action-buttons {
        display: flex;
        gap: 0.75rem;
        flex-wrap: wrap;
    }

    .btn {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.6rem 1.2rem;
        border-radius: var(--radius-3);
        font-size: var(--font-size-p);
        font-weight: 500;
        cursor: pointer;
        border: 1.5px solid transparent;
        transition: opacity var(--duration-fast), background var(--duration-fast);
    }

    .btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .btn-primary {
        background: var(--color-accent);
        color: var(--color-accent-contrast, #fff);
        border-color: var(--color-accent);
    }

    .btn-primary:not(:disabled):hover {
        opacity: 0.85;
    }

    .btn-secondary {
        background: var(--color-grey-15);
        color: var(--color-font-primary);
        border-color: var(--color-grey-30);
    }

    .btn-secondary:not(:disabled):hover {
        background: var(--color-grey-20);
    }

    .loading-spinner {
        display: inline-block;
        width: 1rem;
        height: 1rem;
        border: 2px solid rgba(255, 255, 255, 0.4);
        border-top-color: #fff;
        border-radius: 50%;
        animation: spin 0.7s linear infinite;
    }

    /* ── File type badge ─────────────────────────────────────────────────── */
    .file-type-badge {
        margin-left: auto;
        padding: 0.1rem 0.45rem;
        border-radius: var(--radius-1);
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        line-height: 1.4;
        flex-shrink: 0;
    }

    .file-type-badge--zip {
        background: var(--color-accent-soft, #e0e7ff);
        color: var(--color-accent, #4f46e5);
    }

    .file-type-badge--yaml {
        background: var(--color-grey-20);
        color: var(--color-font-secondary);
    }
</style>
