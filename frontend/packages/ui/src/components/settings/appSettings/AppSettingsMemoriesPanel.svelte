<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { appSettingsMemoriesStore, appSettingsMemoriesForApp, appSettingsMemoriesLoading } from '../../../stores/appSettingsMemoriesStore';
    import type { Readable } from 'svelte/store';

    // Use $props() for component props in Svelte 5
    let { appId }: { appId: string } = $props();

    // Reactive state using $state() and $derived() runes in Svelte 5
    // CRITICAL: Use $derived to maintain reactivity with stores
    // Without $derived, the store value is only read once at initialization
    // and won't update when loadEntriesForApp completes
    let entriesLoading = $derived($appSettingsMemoriesLoading);
    let appEntries: Readable<Record<string, unknown>> = appSettingsMemoriesForApp(appId);
    let groupedEntries = $derived($appEntries);
    let expandedGroups = $state(new Set<string>());

    let showCreateForm = $state(false);
    let formState = $state({
        itemKey: '',
        itemValue: '',
        settingsGroup: ''
    });
    let isCreating = $state(false);
    let createError = $state('');

    onMount(async () => {
        await appSettingsMemoriesStore.loadEntriesForApp(appId);

        const handleSyncReady = async () => {
            console.info('[AppSettingsMemoriesPanel] Sync ready event received, reloading entries');
            await appSettingsMemoriesStore.loadEntriesForApp(appId);
        };

        window.addEventListener('appSettingsMemoriesSyncReady', handleSyncReady);

        return () => {
            window.removeEventListener('appSettingsMemoriesSyncReady', handleSyncReady);
        };
    });

    // Toggle group expansion state
    // In Svelte 5, mutations to $state() objects automatically trigger reactivity
    function toggleGroup(groupName: string) {
        if (expandedGroups.has(groupName)) {
            expandedGroups.delete(groupName);
        } else {
            expandedGroups.add(groupName);
        }
        // No need to reassign in Svelte 5 - $state() handles reactivity automatically
    }

    function formatDate(timestamp: number): string {
        const date = new Date(timestamp * 1000);
        return date.toLocaleDateString(undefined, {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    function formatValue(value: unknown): string {
        if (value === null || value === undefined) {
            return 'null';
        }
        if (typeof value === 'boolean') {
            return value ? 'true' : 'false';
        }
        if (typeof value === 'object') {
            return JSON.stringify(value, null, 2);
        }
        return String(value);
    }

    async function handleCreateEntry() {
        createError = '';

        if (!formState.itemKey.trim()) {
            createError = 'Item key is required';
            return;
        }

        if (!formState.itemValue.trim()) {
            createError = 'Item value is required';
            return;
        }

        isCreating = true;
        try {
            let parsedValue: unknown;
            try {
                parsedValue = JSON.parse(formState.itemValue);
            } catch {
                parsedValue = formState.itemValue;
            }

            const settingsGroup = formState.settingsGroup.trim() || formState.itemKey.split('.')[0] || 'Default';

            await appSettingsMemoriesStore.createEntry(appId, {
                item_key: formState.itemKey.trim(),
                item_value: parsedValue,
                settings_group: settingsGroup
            });

            formState = { itemKey: '', itemValue: '', settingsGroup: '' };
            showCreateForm = false;

            console.info('[AppSettingsMemoriesPanel] Entry created successfully');
        } catch (error) {
            createError = error instanceof Error ? error.message : 'Failed to create entry';
            console.error('[AppSettingsMemoriesPanel] Error creating entry:', error);
        } finally {
            isCreating = false;
        }
    }

    function resetForm() {
        formState = { itemKey: '', itemValue: '', settingsGroup: '' };
        createError = '';
        showCreateForm = false;
    }
</script>

<div class="app-settings-memories">
    {#if entriesLoading}
        <div class="loading">
            <div class="spinner"></div>
            <p>{$text('settings.app_settings_memories.loading')}</p>
        </div>
    {:else if Object.keys(groupedEntries).length === 0}
        <div class="empty">
            <p>{$text('settings.app_settings_memories.no_settings')}</p>
            <button class="add-entry-btn" onclick={() => (showCreateForm = true)}>
                + {$text('settings.app_settings_memories.add_entry')}
            </button>
        </div>
    {:else}
        <div class="settings-container">
            {#each Object.entries(groupedEntries) as [groupName, entries]}
                <div class="settings-group">
                    <button
                        class="group-header"
                        onclick={() => toggleGroup(groupName)}
                    >
                        <span class="group-name">{groupName}</span>
                        <span class="entry-count">({entries.length})</span>
                        <span class="toggle-icon" class:expanded={expandedGroups.has(groupName)}>
                            ▼
                        </span>
                    </button>

                    {#if expandedGroups.has(groupName)}
                        <div class="group-entries">
                            {#each entries as entry (entry.id)}
                                <div class="entry-item">
                                    <div class="entry-header">
                                        <span class="entry-key">{entry.item_key}</span>
                                        <span class="entry-meta">
                                            v{entry.item_version} • {formatDate(entry.updated_at)}
                                        </span>
                                    </div>
                                    <div class="entry-value">
                                        <code>{formatValue(entry.item_value)}</code>
                                    </div>
                                </div>
                            {/each}
                        </div>
                    {/if}
                </div>
            {/each}

            <button class="add-entry-btn" onclick={() => (showCreateForm = true)}>
                + {$text('settings.app_settings_memories.add_entry')}
            </button>
        </div>
    {/if}

    {#if showCreateForm}
        <div class="modal-overlay" role="presentation" onclick={resetForm}>
            <div class="modal" role="dialog" tabindex={-1} onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.key === 'Escape' && resetForm()}>
                <div class="modal-header">
                    <h3>{$text('settings.app_settings_memories.add_entry')}</h3>
                    <button class="close-btn" onclick={resetForm}>✕</button>
                </div>

                <div class="form-group">
                    <label for="item-key">
                        {$text('settings.app_settings_memories.item_key')}
                        <span class="required">*</span>
                    </label>
                    <input
                        id="item-key"
                        type="text"
                        bind:value={formState.itemKey}
                        placeholder="e.g., favorite_movie or watched.2024"
                        disabled={isCreating}
                    />
                    <small>Key to identify this setting/memory entry</small>
                </div>

                <div class="form-group">
                    <label for="settings-group">
                        {$text('settings.app_settings_memories.settings_group')}
                    </label>
                    <input
                        id="settings-group"
                        type="text"
                        bind:value={formState.settingsGroup}
                        placeholder="e.g., Movies (defaults to first part of item key)"
                        disabled={isCreating}
                    />
                    <small>Group to organize this entry under</small>
                </div>

                <div class="form-group">
                    <label for="item-value">
                        {$text('settings.app_settings_memories.item_value')}
                        <span class="required">*</span>
                    </label>
                    <textarea
                        id="item-value"
                        bind:value={formState.itemValue}
                        placeholder="Example: JSON object or plain text"
                        rows="6"
                        disabled={isCreating}
                    ></textarea>
                    <small>Value can be JSON or plain text. JSON will be automatically parsed.</small>
                </div>

                {#if createError}
                    <div class="error-message">{createError}</div>
                {/if}

                <div class="modal-footer">
                    <button class="cancel-btn" onclick={resetForm} disabled={isCreating}>
                        {$text('settings.app_settings_memories.cancel')}
                    </button>
                    <button
                        class="create-btn"
                        onclick={handleCreateEntry}
                        disabled={isCreating}
                    >
                        {isCreating ? $text('settings.app_settings_memories.creating') : $text('settings.app_settings_memories.add_entry')}
                    </button>
                </div>
            </div>
        </div>
    {/if}
</div>

<style>
    .app-settings-memories {
        width: 100%;
    }

    .loading {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 3rem 1rem;
        gap: 1rem;
    }

    .spinner {
        width: 2rem;
        height: 2rem;
        border: 2px solid var(--color-grey-30);
        border-top-color: var(--color-primary);
        border-radius: 50%;
        animation: spin 0.6s linear infinite;
    }

    @keyframes spin {
        to {
            transform: rotate(360deg);
        }
    }

    .empty {
        padding: 2rem 1rem;
        text-align: center;
        color: var(--text-secondary);
    }

    .settings-container {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }

    .settings-group {
        border: 1px solid var(--color-grey-20);
        border-radius: 8px;
        overflow: hidden;
    }

    .group-header {
        width: 100%;
        padding: 1rem;
        background: var(--color-grey-10);
        border: none;
        cursor: pointer;
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-size: 0.95rem;
        font-weight: 500;
        color: var(--text-primary);
        transition: background-color 0.2s ease;
    }

    .group-header:hover {
        background: var(--color-grey-15);
    }

    .group-name {
        flex: 1;
        text-align: left;
    }

    .entry-count {
        color: var(--text-secondary);
        font-size: 0.9rem;
        font-weight: normal;
    }

    .toggle-icon {
        display: inline-block;
        transition: transform 0.2s ease;
        color: var(--text-secondary);
    }

    .toggle-icon.expanded {
        transform: rotate(180deg);
    }

    .group-entries {
        padding: 1rem;
        background: var(--color-white);
        display: flex;
        flex-direction: column;
        gap: 1rem;
        border-top: 1px solid var(--color-grey-20);
    }

    .entry-item {
        padding: 0.75rem;
        background: var(--color-grey-10);
        border-radius: 6px;
    }

    .entry-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 0.5rem;
        gap: 1rem;
    }

    .entry-key {
        font-family: 'Courier New', monospace;
        font-size: 0.85rem;
        font-weight: 600;
        color: var(--text-primary);
        word-break: break-word;
    }

    .entry-meta {
        font-size: 0.75rem;
        color: var(--text-secondary);
        white-space: nowrap;
    }

    .entry-value {
        margin-top: 0.5rem;
    }

    code {
        display: block;
        padding: 0.5rem;
        background: var(--color-white);
        border: 1px solid var(--color-grey-20);
        border-radius: 4px;
        font-family: 'Courier New', monospace;
        font-size: 0.8rem;
        overflow-x: auto;
        color: var(--text-primary);
        word-break: break-word;
        white-space: pre-wrap;
    }

    .add-entry-btn {
        margin-top: 1rem;
        padding: 0.75rem 1.5rem;
        background: var(--color-primary);
        color: white;
        border: none;
        border-radius: 6px;
        cursor: pointer;
        font-size: 0.95rem;
        font-weight: 500;
        transition: background-color 0.2s ease;
    }

    .add-entry-btn:hover {
        background: var(--color-primary-dark, #005fa3);
    }

    .add-entry-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .modal-overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 1000;
    }

    .modal {
        background: white;
        border-radius: 12px;
        max-width: 500px;
        width: 90%;
        max-height: 90vh;
        overflow-y: auto;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
    }

    .modal-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 1.5rem;
        border-bottom: 1px solid var(--color-grey-20);
    }

    .modal-header h3 {
        margin: 0;
        font-size: 1.25rem;
        font-weight: 600;
    }

    .close-btn {
        background: none;
        border: none;
        font-size: 1.5rem;
        cursor: pointer;
        color: var(--text-secondary);
        padding: 0;
        width: 2rem;
        height: 2rem;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: color 0.2s ease;
    }

    .close-btn:hover {
        color: var(--text-primary);
    }

    .form-group {
        padding: 1rem 1.5rem;
        border-bottom: 1px solid var(--color-grey-20);
    }

    .form-group label {
        display: block;
        margin-bottom: 0.5rem;
        font-weight: 500;
        color: var(--text-primary);
    }

    .required {
        color: var(--error-color, #dc3545);
    }

    input,
    textarea {
        width: 100%;
        padding: 0.75rem;
        border: 1px solid var(--color-grey-30);
        border-radius: 6px;
        font-family: inherit;
        font-size: 0.95rem;
        color: var(--text-primary);
        background: var(--color-white);
        transition: border-color 0.2s ease;
    }

    input:focus,
    textarea:focus {
        outline: none;
        border-color: var(--color-primary);
        box-shadow: 0 0 0 3px rgba(0, 95, 163, 0.1);
    }

    input:disabled,
    textarea:disabled {
        background: var(--color-grey-15);
        cursor: not-allowed;
        opacity: 0.6;
    }

    small {
        display: block;
        margin-top: 0.25rem;
        color: var(--text-secondary);
        font-size: 0.8rem;
    }

    .error-message {
        padding: 1rem 1.5rem;
        background: var(--color-error-light, #f8d7da);
        border: 1px solid var(--color-error, #f5c6cb);
        border-radius: 6px;
        color: var(--error-color, #721c24);
        margin: 0 1.5rem;
    }

    .modal-footer {
        display: flex;
        gap: 1rem;
        justify-content: flex-end;
        padding: 1.5rem;
        border-top: 1px solid var(--color-grey-20);
    }

    .cancel-btn,
    .create-btn {
        padding: 0.75rem 1.5rem;
        border-radius: 6px;
        border: none;
        cursor: pointer;
        font-size: 0.95rem;
        font-weight: 500;
        transition: background-color 0.2s ease;
    }

    .cancel-btn {
        background: var(--color-grey-30);
        color: var(--text-primary);
    }

    .cancel-btn:hover:not(:disabled) {
        background: var(--color-grey-40);
    }

    .create-btn {
        background: var(--color-primary);
        color: white;
    }

    .create-btn:hover:not(:disabled) {
        background: var(--color-primary-dark, #005fa3);
    }

    button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
</style>
