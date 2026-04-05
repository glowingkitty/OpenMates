<!--
Add Custom Entry - Form for adding a custom text entry to hide in chat messages.

Users provide:
- Title: A label for this entry (e.g., "My company name")
- Text to hide: The actual text to detect (e.g., "Acme Corp")

The replacement placeholder is auto-generated based on the title.
All values are client-side encrypted before storage.
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { SettingsSectionHeading } from '../../settings/elements';
    import SettingsInput from '../elements/SettingsInput.svelte';
    import { personalDataStore } from '../../../stores/personalDataStore';

    const dispatch = createEventDispatcher();

    // ─── Form State ──────────────────────────────────────────────────────────

    let title = $state('');
    let textToHide = $state('');
    let isSaving = $state(false);
    let errorMessage = $state('');

    // ─── Auto-generated Placeholder ──────────────────────────────────────────

    /**
     * Generate a replacement placeholder from the title.
     * E.g., "My company name" -> "MY_COMPANY_NAME"
     */
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
        if (!isValid || isSaving) return;

        isSaving = true;
        errorMessage = '';

        try {
            await personalDataStore.addEntry({
                type: 'custom',
                title: title.trim(),
                textToHide: textToHide.trim(),
                replaceWith: autoPlaceholder,
                enabled: true,
            });

            // Navigate back
            dispatch('openSettings', {
                settingsPath: 'privacy/hide-personal-data',
                direction: 'backward',
                icon: 'privacy',
                title: $text('settings.privacy.hide_personal_data')
            });
        } catch (error) {
            console.error('[SettingsAddCustomEntry] Failed to save custom entry:', error);
            errorMessage = 'Failed to save. Please try again.';
        } finally {
            isSaving = false;
        }
    }
</script>

<!-- Title field -->
<SettingsSectionHeading title={$text('settings.privacy.form.title')} icon="text" />

<SettingsInput
    bind:value={title}
    placeholder={$text('settings.privacy.form.title.placeholder_custom')}
    disabled={isSaving}
/>

<!-- Text to hide field -->
<SettingsSectionHeading title={$text('settings.privacy.form.text_to_hide')} icon="text" />

<SettingsInput
    bind:value={textToHide}
    placeholder={$text('settings.privacy.form.text_to_hide.placeholder_custom')}
    disabled={isSaving}
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
        class:disabled={!isValid || isSaving}
        disabled={!isValid || isSaving}
        onclick={handleSave}
    >
        {$text('common.save')}
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
        padding: var(--spacing-8);
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
</style>
