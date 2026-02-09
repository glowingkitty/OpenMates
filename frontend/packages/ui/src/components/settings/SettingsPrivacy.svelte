<!--
Privacy Settings - Main page for privacy-related settings
Sections: Anonymization, Device Permissions, Auto Deletion

Based on Figma design: settings/privacy (node 1895:20576)
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../SettingsItem.svelte';
    import { personalDataStore } from '../../stores/personalDataStore';

    const dispatch = createEventDispatcher();

    // ─── PII Detection Settings (Anonymization section) ──────────────────────
    // Read master toggle and "hide personal data" enabled state from the store
    let piiSettings = $state({ masterEnabled: true, categories: {} as Record<string, boolean> });
    personalDataStore.settings.subscribe((s) => { piiSettings = s; });

    let hidePersonalDataEnabled = $derived(piiSettings.masterEnabled);

    // ─── Device Permission Toggles ───────────────────────────────────────────
    // These represent browser permission states — toggling requests/revokes permission
    let microphoneEnabled = $state(false);
    let cameraEnabled = $state(false);
    let locationEnabled = $state(false);

    // ─── Location / Maps Toggle ──────────────────────────────────────────────
    let nearbyByDefault = $state(true);

    // ─── Navigation Handlers ─────────────────────────────────────────────────

    /**
     * Navigate to the "Hide personal data" sub-page where users manage
     * names, addresses, birthdays, custom entries, and auto-detection toggles.
     */
    function navigateToHidePersonalData() {
        dispatch('openSettings', {
            settingsPath: 'privacy/hide-personal-data',
            direction: 'forward',
            icon: 'privacy',
            title: $text('settings.privacy.hide_personal_data.text')
        });
    }
</script>

<!-- Privacy Policy Info -->
<div class="privacy-description">
    <p class="description-text">
        {$text('settings.privacy.privacy.description.text')}
    </p>
    <a
        href="https://openmates.org/privacy"
        target="_blank"
        rel="noopener noreferrer"
        class="privacy-link"
    >
        {$text('settings.privacy.privacy.open_privacy_policy.text')}
    </a>
</div>

<!-- ─── Anonymization Section ─────────────────────────────────────────────── -->
<SettingsItem
    type="heading"
    icon="privacy"
    title={$text('settings.privacy.privacy.anonymization.text')}
/>

<!-- Hide personal data — navigates to sub-page, has toggle -->
<SettingsItem
    type="subsubmenu"
    icon="search"
    subtitleTop={$text('settings.privacy.privacy.hide_personal_data.chats.text')}
    title={$text('settings.privacy.privacy.hide_personal_data.text')}
    hasToggle={true}
    checked={hidePersonalDataEnabled}
    onClick={navigateToHidePersonalData}
/>

<!-- Nearby by default (Maps/Location) -->
<SettingsItem
    type="subsubmenu"
    icon="search"
    subtitleTop={$text('settings.privacy.privacy.maps_location.text')}
    title={$text('settings.privacy.privacy.nearby_by_default.text')}
    hasToggle={true}
    checked={nearbyByDefault}
    onClick={() => nearbyByDefault = !nearbyByDefault}
/>

<!-- ─── Device Permissions Section ────────────────────────────────────────── -->
<SettingsItem
    type="heading"
    icon="privacy"
    title={$text('settings.privacy.privacy.device_permissions.text')}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    title={$text('settings.privacy.privacy.microphone.text')}
    hasToggle={true}
    checked={microphoneEnabled}
    onClick={() => microphoneEnabled = !microphoneEnabled}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    title={$text('settings.privacy.privacy.camera.text')}
    hasToggle={true}
    checked={cameraEnabled}
    onClick={() => cameraEnabled = !cameraEnabled}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    title={$text('settings.privacy.privacy.location.text')}
    hasToggle={true}
    checked={locationEnabled}
    onClick={() => locationEnabled = !locationEnabled}
/>

<!-- ─── Auto Deletion Section ─────────────────────────────────────────────── -->
<SettingsItem
    type="heading"
    icon="privacy"
    title={$text('settings.privacy.privacy.auto_deletion.text')}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    subtitleTop={$text('settings.privacy.privacy.auto_deletion.chats.text')}
    title={$text('settings.privacy.privacy.auto_deletion.chats.value.text')}
    hasModifyButton={true}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    subtitleTop={$text('settings.privacy.privacy.auto_deletion.files.text')}
    title={$text('settings.privacy.privacy.auto_deletion.files.value.text')}
    hasModifyButton={true}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    subtitleTop={$text('settings.privacy.privacy.auto_deletion.usage_data.text')}
    title={$text('settings.privacy.privacy.auto_deletion.usage_data.value.text')}
    hasModifyButton={true}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    subtitleTop={$text('settings.privacy.privacy.auto_deletion.compliance_logs.text')}
    title={$text('settings.privacy.privacy.auto_deletion.compliance_logs.value.text')}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    subtitleTop={$text('settings.privacy.privacy.auto_deletion.invoices.text')}
    title={$text('settings.privacy.privacy.auto_deletion.invoices.value.text')}
/>

<!-- Compliance note -->
<div class="compliance-note">
    <p>{$text('settings.privacy.privacy.auto_deletion.compliance_note.text')}</p>
</div>

<style>
    .privacy-description {
        padding: 10px 16px;
        display: flex;
        flex-direction: column;
        gap: 10px;
    }

    .description-text {
        font-size: 16px;
        color: var(--color-grey-100);
        line-height: 1.5;
        margin: 0;
    }

    .privacy-link {
        font-size: 16px;
        font-weight: 700;
        background: var(--gradient-primary);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        text-decoration: none;
        cursor: pointer;
    }

    .privacy-link:hover {
        opacity: 0.8;
    }

    .compliance-note {
        padding: 10px 16px;
    }

    .compliance-note p {
        font-size: 14px;
        font-weight: 500;
        color: var(--color-grey-60);
        line-height: 1.5;
        margin: 0;
    }
</style>
