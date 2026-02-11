<!--
Add Birthday - Form for adding a birthday entry to hide in chat messages.

Users provide:
- Title: A label for this entry (e.g., "Me", "My partner")
- Date: The birthday date to detect (e.g., "15.03.1990")

The replacement placeholder is auto-generated based on the title.
All values are client-side encrypted before storage.
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';
    import { personalDataStore } from '../../../stores/personalDataStore';

    const dispatch = createEventDispatcher();

    // ─── Form State ──────────────────────────────────────────────────────────

    let title = $state('');
    let dateValue = $state('');
    let isSaving = $state(false);
    let errorMessage = $state('');

    // ─── Auto-generated Placeholder ──────────────────────────────────────────

    /**
     * Generate a replacement placeholder from the title.
     * E.g., "Me" -> "ME_BIRTHDAY"
     */
    function generatePlaceholder(titleValue: string): string {
        if (!titleValue.trim()) return '';
        const base = titleValue.trim().toUpperCase().replace(/\s+/g, '_').replace(/[^A-Z0-9_]/g, '');
        return `${base}_BIRTHDAY`;
    }

    let autoPlaceholder = $derived(generatePlaceholder(title));

    // ─── Validation ──────────────────────────────────────────────────────────

    let isValid = $derived(
        title.trim().length > 0 &&
        dateValue.trim().length > 0
    );

    // ─── Save Handler ────────────────────────────────────────────────────────

    async function handleSave() {
        if (!isValid || isSaving) return;

        isSaving = true;
        errorMessage = '';

        try {
            await personalDataStore.addEntry({
                type: 'birthday',
                title: title.trim(),
                textToHide: dateValue.trim(),
                replaceWith: autoPlaceholder,
                enabled: true,
            });

            // Navigate back
            dispatch('openSettings', {
                settingsPath: 'privacy/hide-personal-data',
                direction: 'backward',
                icon: 'privacy',
                title: $text('settings.privacy.privacy.hide_personal_data.text')
            });
        } catch (error) {
            console.error('[SettingsAddBirthday] Failed to save birthday entry:', error);
            errorMessage = 'Failed to save. Please try again.';
        } finally {
            isSaving = false;
        }
    }
</script>

<!-- Title field -->
<SettingsItem
    type="heading"
    icon="text"
    title={$text('settings.privacy.privacy.form.title.text')}
/>

<div class="form-field">
    <input
        type="text"
        class="form-input"
        placeholder={$text('settings.privacy.privacy.form.title.placeholder_birthday.text')}
        bind:value={title}
    />
</div>

<!-- Date field -->
<SettingsItem
    type="heading"
    icon="text"
    title={$text('settings.privacy.privacy.form.date.text')}
/>

<div class="form-field">
    <input
        type="text"
        class="form-input"
        placeholder={$text('settings.privacy.privacy.form.date.placeholder.text')}
        bind:value={dateValue}
    />
</div>

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
        {$text('settings.privacy.privacy.form.save.text')}
    </button>
</div>

<style>
    .form-field {
        padding: 0 16px 16px;
    }

    .form-input {
        width: 100%;
        height: 54px;
        border: none;
        border-radius: 24px;
        padding: 0 20px;
        font-size: 16px;
        font-family: inherit;
        color: var(--color-grey-100);
        background-color: white;
        box-shadow: 0px 4px 4px rgba(0, 0, 0, 0.25);
        outline: none;
        box-sizing: border-box;
    }

    .form-input::placeholder {
        color: var(--color-grey-50);
    }

    .form-input:focus {
        box-shadow: 0px 4px 8px rgba(0, 0, 0, 0.15);
    }

    .error-message {
        padding: 0 16px;
    }

    .error-message p {
        color: var(--color-error, #ff4444);
        font-size: 14px;
        margin: 0;
    }

    .save-button-container {
        display: flex;
        justify-content: center;
        padding: 16px;
    }

    .save-button {
        width: 174px;
        height: 41px;
        border: none;
        border-radius: 15px;
        background-color: var(--color-cta, #ff553b);
        color: white;
        font-size: 16px;
        font-weight: 500;
        font-family: inherit;
        cursor: pointer;
        transition: opacity 0.2s ease;
    }

    .save-button:hover:not(.disabled) {
        opacity: 0.9;
    }

    .save-button.disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
</style>
