<!--
Add Address - Form for adding a new address entry with structured fields.

Users provide:
- Title: A label (e.g., "Home", "Work")
- Address fields: Street, City, State/Province, ZIP, Country (each separately detectable)
- Replace with: The placeholder (e.g., "MY_HOME_ADDRESS")

Each address line is independently detectable by the PII engine.
All values are client-side encrypted before storage.

Based on Figma design for addresses section in hide personal data.
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';
    import { personalDataStore } from '../../../stores/personalDataStore';

    const dispatch = createEventDispatcher();

    // ─── Form State ──────────────────────────────────────────────────────────

    let title = $state('');
    let street = $state('');
    let city = $state('');
    let stateProvince = $state('');
    let zip = $state('');
    let country = $state('');
    let replaceWith = $state('');
    let isSaving = $state(false);
    let errorMessage = $state('');

    // ─── Validation ──────────────────────────────────────────────────────────

    /** At least title, one address field, and replaceWith must be filled */
    let isValid = $derived(
        title.trim().length > 0 &&
        replaceWith.trim().length > 0 &&
        (street.trim().length > 0 || city.trim().length > 0 || zip.trim().length > 0 || country.trim().length > 0)
    );

    // ─── Save Handler ────────────────────────────────────────────────────────

    /**
     * Build composite textToHide from all non-empty address fields.
     * Each non-empty line is added as a separate detection target.
     */
    function buildTextToHide(): string {
        const parts = [street, city, stateProvince, zip, country]
            .map(p => p.trim())
            .filter(p => p.length > 0);
        return parts.join(', ');
    }

    async function handleSave() {
        if (!isValid || isSaving) return;

        isSaving = true;
        errorMessage = '';

        try {
            personalDataStore.addEntry({
                type: 'address',
                title: title.trim(),
                textToHide: buildTextToHide(),
                replaceWith: replaceWith.trim(),
                enabled: true,
                addressLines: {
                    street: street.trim(),
                    city: city.trim(),
                    state: stateProvince.trim(),
                    zip: zip.trim(),
                    country: country.trim(),
                },
            });

            // Navigate back
            dispatch('openSettings', {
                settingsPath: 'privacy/hide-personal-data',
                direction: 'backward',
                icon: 'privacy',
                title: $text('settings.privacy.privacy.hide_personal_data.text')
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
<SettingsItem
    type="heading"
    icon="mate"
    title={$text('settings.privacy.privacy.form.title.text')}
/>

<div class="form-field">
    <input
        type="text"
        class="form-input"
        placeholder={$text('settings.privacy.privacy.form.title.placeholder_address.text')}
        bind:value={title}
    />
</div>

<!-- Street field -->
<SettingsItem
    type="heading"
    icon="mate"
    title={$text('settings.privacy.privacy.form.street.text')}
/>

<div class="form-field">
    <input
        type="text"
        class="form-input"
        placeholder={$text('settings.privacy.privacy.form.street.placeholder.text')}
        bind:value={street}
    />
</div>

<!-- City field -->
<SettingsItem
    type="heading"
    icon="mate"
    title={$text('settings.privacy.privacy.form.city.text')}
/>

<div class="form-field">
    <input
        type="text"
        class="form-input"
        placeholder={$text('settings.privacy.privacy.form.city.placeholder.text')}
        bind:value={city}
    />
</div>

<!-- State / Province field -->
<SettingsItem
    type="heading"
    icon="mate"
    title={$text('settings.privacy.privacy.form.state.text')}
/>

<div class="form-field">
    <input
        type="text"
        class="form-input"
        placeholder={$text('settings.privacy.privacy.form.state.placeholder.text')}
        bind:value={stateProvince}
    />
</div>

<!-- ZIP / Postal code field -->
<SettingsItem
    type="heading"
    icon="mate"
    title={$text('settings.privacy.privacy.form.zip.text')}
/>

<div class="form-field">
    <input
        type="text"
        class="form-input"
        placeholder={$text('settings.privacy.privacy.form.zip.placeholder.text')}
        bind:value={zip}
    />
</div>

<!-- Country field -->
<SettingsItem
    type="heading"
    icon="mate"
    title={$text('settings.privacy.privacy.form.country.text')}
/>

<div class="form-field">
    <input
        type="text"
        class="form-input"
        placeholder={$text('settings.privacy.privacy.form.country.placeholder.text')}
        bind:value={country}
    />
</div>

<!-- Replace with field -->
<SettingsItem
    type="heading"
    icon="mate"
    title={$text('settings.privacy.privacy.form.replace_with.text')}
/>

<div class="form-field">
    <input
        type="text"
        class="form-input"
        placeholder={$text('settings.privacy.privacy.form.replace_with.placeholder_address.text')}
        bind:value={replaceWith}
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
