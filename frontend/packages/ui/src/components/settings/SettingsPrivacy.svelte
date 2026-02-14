<!--
Privacy Settings - Main page for privacy-related settings
Sections: Anonymization, Device Permissions, Auto Deletion

Based on Figma design: settings/privacy (node 1895:20576)
-->

<script lang="ts">
    import { createEventDispatcher, onMount } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../SettingsItem.svelte';
    import { personalDataStore } from '../../stores/personalDataStore';

    const dispatch = createEventDispatcher();

    // ─── Load from encrypted storage on mount ────────────────────────────────

    onMount(() => {
        personalDataStore.loadFromStorage();
    });

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
            title: $text('settings.privacy.hide_personal_data')
        });
    }

    /**
     * Navigate to the auto-deletion editing sub-page for a specific category.
     */
    function navigateToAutoDeletion(category: string) {
        dispatch('openSettings', {
            settingsPath: `privacy/auto-deletion/${category}`,
            direction: 'forward',
            icon: 'delete',
            title: $text(`settings.privacy.auto_deletion.${category}`)
        });
    }
</script>

<!-- Privacy Policy Info -->
<div class="privacy-description">
    <p class="description-text">
        {$text('settings.privacy.description')}
    </p>
    <a
        href="https://openmates.org/privacy"
        target="_blank"
        rel="noopener noreferrer"
        class="privacy-link"
    >
        {$text('settings.privacy.open_privacy_policy')}
    </a>
</div>

<!-- ─── Anonymization Section ─────────────────────────────────────────────── -->
<SettingsItem
    type="heading"
    icon="anonym"
    title={$text('settings.privacy.anonymization')}
/>

<!-- Hide personal data — navigates to sub-page, has toggle -->
<SettingsItem
    type="subsubmenu"
    icon="anonym"
    subtitleTop={$text('settings.privacy.hide_personal_data.chats')}
    title={$text('settings.privacy.hide_personal_data')}
    hasToggle={true}
    checked={hidePersonalDataEnabled}
    onClick={navigateToHidePersonalData}
/>

<!-- Nearby by default (Maps/Location) -->
<SettingsItem
    type="subsubmenu"
    icon="maps"
    subtitleTop={$text('settings.privacy.maps_location')}
    title={$text('settings.privacy.nearby_by_default')}
    hasToggle={true}
    checked={nearbyByDefault}
    onClick={() => nearbyByDefault = !nearbyByDefault}
/>

<!-- ─── Device Permissions Section ────────────────────────────────────────── -->
<SettingsItem
    type="heading"
    icon="desktop"
    title={$text('settings.privacy.device_permissions')}
/>

<SettingsItem
    type="subsubmenu"
    icon="recordaudio"
    title={$text('settings.privacy.microphone')}
    hasToggle={true}
    checked={microphoneEnabled}
    onClick={() => microphoneEnabled = !microphoneEnabled}
/>

<SettingsItem
    type="subsubmenu"
    icon="camera"
    title={$text('settings.privacy.camera')}
    hasToggle={true}
    checked={cameraEnabled}
    onClick={() => cameraEnabled = !cameraEnabled}
/>

<SettingsItem
    type="subsubmenu"
    icon="maps"
    title={$text('settings.privacy.location')}
    hasToggle={true}
    checked={locationEnabled}
    onClick={() => locationEnabled = !locationEnabled}
/>

<!-- ─── Auto Deletion Section ─────────────────────────────────────────────── -->
<SettingsItem
    type="heading"
    icon="delete"
    title={$text('settings.privacy.auto_deletion')}
/>

<!-- Chats — editable, has modify button -->
<SettingsItem
    type="subsubmenu"
    icon="chat"
    subtitleTop={$text('settings.privacy.auto_deletion.chats')}
    title={$text('settings.privacy.auto_deletion.chats.value')}
    hasModifyButton={true}
    onModifyClick={() => navigateToAutoDeletion('chats')}
/>

<!-- Files — editable, has modify button -->
<SettingsItem
    type="subsubmenu"
    icon="files"
    subtitleTop={$text('settings.privacy.auto_deletion.files')}
    title={$text('settings.privacy.auto_deletion.files.value')}
    hasModifyButton={true}
    onModifyClick={() => navigateToAutoDeletion('files')}
/>

<!-- Usage data — editable, has modify button -->
<SettingsItem
    type="subsubmenu"
    icon="usage"
    subtitleTop={$text('settings.privacy.auto_deletion.usage_data')}
    title={$text('settings.privacy.auto_deletion.usage_data.value')}
    hasModifyButton={true}
    onModifyClick={() => navigateToAutoDeletion('usage_data')}
/>

<!-- Compliance logs — NOT editable, no modify button -->
<SettingsItem
    type="subsubmenu"
    icon="log"
    subtitleTop={$text('settings.privacy.auto_deletion.compliance_logs')}
    title={$text('settings.privacy.auto_deletion.compliance_logs.value')}
/>

<!-- Invoices — NOT editable, no modify button -->
<SettingsItem
    type="subsubmenu"
    icon="billing"
    subtitleTop={$text('settings.privacy.auto_deletion.invoices')}
    title={$text('settings.privacy.auto_deletion.invoices.value')}
/>

<!-- Compliance note -->
<div class="compliance-note">
    <p>{$text('settings.privacy.auto_deletion.compliance_note')}</p>
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
        font-style: italic;
    }
</style>
