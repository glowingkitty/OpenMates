<!--
Edit Custom Entry - Form for editing an existing custom entry.

Pre-fills the current title and text to hide from personalDataStore.
Saves changes via personalDataStore.updateEntry(). Also offers delete.

All values are client-side encrypted before storage.

Architecture context: docs/architecture/pii-protection.md
Related to: SettingsAddCustomEntry.svelte, SettingsHidePersonalData.svelte
-->

<script lang="ts">
    import { createEventDispatcher, onMount } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';
    import { SettingsSectionHeading } from '../../settings/elements';
    import SettingsInput from '../elements/SettingsInput.svelte';
    import { personalDataStore } from '../../../stores/personalDataStore';

    const dispatch = createEventDispatcher();

    // ─── Props ───────────────────────────────────────────────────────────────

    interface Props {
        entryId?: string;
    }

    let { entryId = '' }: Props = $props();

    // ─── Form State ──────────────────────────────────────────────────────────

    let title = $state('');
    let textToHide = $state('');
    let enabled = $state(true);
    let isSaving = $state(false);
    let isDeleting = $state(false);
    let errorMessage = $state('');
    let isLoaded = $state(false);

    // ─── Load existing entry on mount ────────────────────────────────────────

    onMount(() => {
        loadEntry();
    });

    function loadEntry() {
        const unsubscribe = personalDataStore.subscribe((entries) => {
            const entry = entries.find(e => e.id === entryId);
            if (entry && !isLoaded) {
                title = entry.title;
                textToHide = entry.textToHide;
                enabled = entry.enabled;
                isLoaded = true;
            }
        });
        unsubscribe();
    }

    // ─── Toggle Handler ──────────────────────────────────────────────────────

    function handleToggle() {
        if (!entryId) return;
        enabled = !enabled;
        personalDataStore.toggleEntry(entryId);
    }

    // ─── Auto-generated Placeholder ──────────────────────────────────────────

    function generatePlaceholder(titleValue: string): string {
        if (!titleValue.trim()) return '';
        return titleValue.trim().toUpperCase().replace(/\s+/g, '_').replace(/[^A-Z0-9_]/g, '');
    }

    let autoPlaceholder = $derived(generatePlaceholder(title));

    // ─── Validation ──────────────────────────────────────────────────────────

    let isValid = $derived(
        title.trim().length > 0 &&
        textToHide.trim().length > 0
    );

    // ─── Save Handler ────────────────────────────────────────────────────────

    async function handleSave() {
        if (!isValid || isSaving || !entryId) return;

        isSaving = true;
        errorMessage = '';

        try {
            await personalDataStore.updateEntry(entryId, {
                title: title.trim(),
                textToHide: textToHide.trim(),
                replaceWith: autoPlaceholder,
            });

            navigateBack();
        } catch (error) {
            console.error('[SettingsEditCustomEntry] Failed to update custom entry:', error);
            errorMessage = 'Failed to save. Please try again.';
        } finally {
            isSaving = false;
        }
    }

    // ─── Delete Handler ──────────────────────────────────────────────────────

    async function handleDelete() {
        if (isDeleting || !entryId) return;

        isDeleting = true;
        errorMessage = '';

        try {
            await personalDataStore.removeEntry(entryId);
            navigateBack();
        } catch (error) {
            console.error('[SettingsEditCustomEntry] Failed to delete custom entry:', error);
            errorMessage = 'Failed to delete. Please try again.';
            isDeleting = false;
        }
    }

    // ─── Navigation ──────────────────────────────────────────────────────────

    function navigateBack() {
        dispatch('openSettings', {
            settingsPath: 'privacy/hide-personal-data',
            direction: 'backward',
            icon: 'privacy',
            title: $text('settings.privacy.hide_personal_data')
        });
    }
</script>

<!-- Enabled toggle -->
<SettingsItem
    type="subsubmenu"
    icon="create"
    title={$text('settings.privacy.hide_personal_data')}
    hasToggle={true}
    checked={enabled}
    onClick={handleToggle}
/>

<!-- Title field -->
<SettingsSectionHeading title={$text('settings.privacy.form.title')} icon="text" />

<SettingsInput
    bind:value={title}
    placeholder={$text('settings.privacy.form.title.placeholder_custom')}
    disabled={isSaving || isDeleting}
/>

<!-- Text to hide field -->
<SettingsSectionHeading title={$text('settings.privacy.form.text_to_hide')} icon="text" />

<SettingsInput
    bind:value={textToHide}
    placeholder={$text('settings.privacy.form.text_to_hide.placeholder_custom')}
    disabled={isSaving || isDeleting}
/>

<!-- Auto-generated placeholder preview -->
{#if autoPlaceholder}
    <div class="placeholder-preview">
        <span class="placeholder-label">{$text('settings.privacy.form.replace_with')}</span>
        <span class="placeholder-value">[{autoPlaceholder}]</span>
    </div>
{/if}

<!-- Error message -->
{#if errorMessage}
    <div class="error-message">
        <p>{errorMessage}</p>
    </div>
{/if}

<!-- Save button -->
<div class="save-button-container">
    <button
        class="save-button"
        class:disabled={!isValid || isSaving || isDeleting}
        disabled={!isValid || isSaving || isDeleting}
        onclick={handleSave}
    >
        {$text('common.save')}
    </button>
</div>

<!-- Delete button -->
<div class="delete-button-container">
    <button
        class="delete-button"
        class:disabled={isDeleting || isSaving}
        disabled={isDeleting || isSaving}
        onclick={handleDelete}
    >
        {$text('common.delete')}
    </button>
</div>

<style>
    .placeholder-preview {
        display: flex;
        align-items: center;
        gap: var(--spacing-4);
        padding: 0 16px 16px;
        font-size: var(--font-size-small);
    }

    .placeholder-label {
        color: var(--color-grey-60);
    }

    .placeholder-value {
        color: var(--color-grey-80);
        font-family: monospace;
        background-color: var(--color-grey-15, #f0f0f0);
        padding: var(--spacing-1) var(--spacing-4);
        border-radius: var(--radius-1);
    }

    .error-message {
        padding: 0 16px;
    }

    .error-message p {
        color: var(--color-error, #ff4444);
        font-size: var(--font-size-small);
        margin: 0;
    }

    .save-button-container {
        display: flex;
        justify-content: center;
        padding: var(--spacing-8) var(--spacing-8) var(--spacing-4);
    }

    .delete-button-container {
        display: flex;
        justify-content: center;
        padding: 0 16px 16px;
    }

    .save-button {
        width: 174px;
        height: 41px;
        border: none;
        border-radius: 15px;
        background-color: var(--color-cta, #ff553b);
        color: white;
        font-size: var(--font-size-p);
        font-weight: 500;
        font-family: inherit;
        cursor: pointer;
        transition: opacity var(--duration-normal) var(--easing-default);
    }

    .save-button:hover:not(.disabled) {
        opacity: 0.9;
    }

    .save-button.disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .delete-button {
        width: 174px;
        height: 41px;
        border: 1.5px solid var(--color-error, #ff4444);
        border-radius: 15px;
        background-color: transparent;
        color: var(--color-error, #ff4444);
        font-size: var(--font-size-p);
        font-weight: 500;
        font-family: inherit;
        cursor: pointer;
        transition: opacity var(--duration-normal) var(--easing-default);
    }

    .delete-button:hover:not(.disabled) {
        opacity: 0.8;
    }

    .delete-button.disabled {
        opacity: 0.4;
        cursor: not-allowed;
    }
</style>
