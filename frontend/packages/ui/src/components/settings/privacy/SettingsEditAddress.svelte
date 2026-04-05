<!--
Edit Address - Form for editing an existing address entry.

Pre-fills the current title and address lines from personalDataStore.
Saves changes via personalDataStore.updateEntry(). Also offers delete.

All values are client-side encrypted before storage.

Architecture context: docs/architecture/pii-protection.md
Related to: SettingsAddAddress.svelte, SettingsHidePersonalData.svelte
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
    let firstLine = $state('');
    let secondLine = $state('');
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
                enabled = entry.enabled;
                // Restore from addressLines if available, else split textToHide
                if (entry.addressLines) {
                    firstLine = entry.addressLines.street || '';
                    secondLine = entry.addressLines.city || '';
                } else {
                    const parts = entry.textToHide.split(', ');
                    firstLine = parts[0] || '';
                    secondLine = parts[1] || '';
                }
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
        const base = titleValue.trim().toUpperCase().replace(/\s+/g, '_').replace(/[^A-Z0-9_]/g, '');
        return `${base}_ADDRESS`;
    }

    let autoPlaceholder = $derived(generatePlaceholder(title));

    // ─── Validation ──────────────────────────────────────────────────────────

    let isValid = $derived(
        title.trim().length > 0 &&
        (firstLine.trim().length > 0 || secondLine.trim().length > 0)
    );

    // ─── Save Handler ────────────────────────────────────────────────────────

    function buildTextToHide(): string {
        const parts = [firstLine, secondLine]
            .map(p => p.trim())
            .filter(p => p.length > 0);
        return parts.join(', ');
    }

    async function handleSave() {
        if (!isValid || isSaving || !entryId) return;

        isSaving = true;
        errorMessage = '';

        try {
            await personalDataStore.updateEntry(entryId, {
                title: title.trim(),
                textToHide: buildTextToHide(),
                replaceWith: autoPlaceholder,
                addressLines: {
                    street: firstLine.trim(),
                    city: secondLine.trim(),
                    state: '',
                    zip: '',
                    country: '',
                },
            });

            navigateBack();
        } catch (error) {
            console.error('[SettingsEditAddress] Failed to update address entry:', error);
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
            console.error('[SettingsEditAddress] Failed to delete address entry:', error);
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
    icon="maps"
    title={$text('settings.privacy.hide_personal_data')}
    hasToggle={true}
    checked={enabled}
    onClick={handleToggle}
/>

<!-- Title field -->
<SettingsSectionHeading title={$text('settings.privacy.form.title')} icon="text" />

<SettingsInput
    bind:value={title}
    placeholder={$text('settings.privacy.form.title.placeholder_address')}
    disabled={isSaving || isDeleting}
/>

<!-- First line to hide -->
<SettingsSectionHeading title={$text('settings.privacy.form.first_line')} icon="text" />

<SettingsInput
    bind:value={firstLine}
    placeholder={$text('settings.privacy.form.first_line.placeholder')}
    disabled={isSaving || isDeleting}
/>

<!-- Second line to hide -->
<SettingsSectionHeading title={$text('settings.privacy.form.second_line')} icon="text" />

<SettingsInput
    bind:value={secondLine}
    placeholder={$text('settings.privacy.form.second_line.placeholder')}
    disabled={isSaving || isDeleting}
/>

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
