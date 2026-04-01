<!--
Add Address - Form for adding a new address entry with two address lines.

Users provide:
- Title: A label (e.g., "Home", "Work")
- First line to hide: First line of the address (e.g., "Friedrichstr. 19")
- Second line to hide: Second line of the address (e.g., "10247 Berlin")

The replacement placeholder is auto-generated based on the title.
Each address line is independently detectable by the PII engine.
All values are client-side encrypted before storage.

Based on Figma design for addresses section in hide personal data.
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
    let firstLine = $state('');
    let secondLine = $state('');
    let isSaving = $state(false);
    let errorMessage = $state('');

    // ─── Auto-generated Placeholder ──────────────────────────────────────────

    /**
     * Generate a replacement placeholder from the title.
     * E.g., "Home" -> "HOME_ADDRESS"
     */
    function generatePlaceholder(titleValue: string): string {
        if (!titleValue.trim()) return '';
        const base = titleValue.trim().toUpperCase().replace(/\s+/g, '_').replace(/[^A-Z0-9_]/g, '');
        return `${base}_ADDRESS`;
    }

    let autoPlaceholder = $derived(generatePlaceholder(title));

    // ─── Validation ──────────────────────────────────────────────────────────

    /** At least title and one address line must be filled */
    let isValid = $derived(
        title.trim().length > 0 &&
        (firstLine.trim().length > 0 || secondLine.trim().length > 0)
    );

    // ─── Save Handler ────────────────────────────────────────────────────────

    /**
     * Build composite textToHide from non-empty address lines.
     * Each non-empty line is added as a separate detection target.
     */
    function buildTextToHide(): string {
        const parts = [firstLine, secondLine]
            .map(p => p.trim())
            .filter(p => p.length > 0);
        return parts.join(', ');
    }

    async function handleSave() {
        if (!isValid || isSaving) return;

        isSaving = true;
        errorMessage = '';

        try {
            await personalDataStore.addEntry({
                type: 'address',
                title: title.trim(),
                textToHide: buildTextToHide(),
                replaceWith: autoPlaceholder,
                enabled: true,
                addressLines: {
                    street: firstLine.trim(),
                    city: secondLine.trim(),
                    state: '',
                    zip: '',
                    country: '',
                },
            });

            // Navigate back
            dispatch('openSettings', {
                settingsPath: 'privacy/hide-personal-data',
                direction: 'backward',
                icon: 'privacy',
                title: $text('settings.privacy.hide_personal_data')
            });
        } catch (error) {
            console.error('[SettingsAddAddress] Failed to save address entry:', error);
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
    placeholder={$text('settings.privacy.form.title.placeholder_address')}
    disabled={isSaving}
/>

<!-- First line to hide -->
<SettingsSectionHeading title={$text('settings.privacy.form.first_line')} icon="text" />

<SettingsInput
    bind:value={firstLine}
    placeholder={$text('settings.privacy.form.first_line.placeholder')}
    disabled={isSaving}
/>

<!-- Second line to hide -->
<SettingsSectionHeading title={$text('settings.privacy.form.second_line')} icon="text" />

<SettingsInput
    bind:value={secondLine}
    placeholder={$text('settings.privacy.form.second_line.placeholder')}
    disabled={isSaving}
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
        class:disabled={!isValid || isSaving}
        disabled={!isValid || isSaving}
        onclick={handleSave}
    >
        {$text('common.save')}
    </button>
</div>

<style>
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
