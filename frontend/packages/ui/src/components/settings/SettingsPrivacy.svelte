<!--
Privacy Settings - Main page for privacy-related settings
Sections: Anonymization, Auto Deletion, Debug Logging

Based on Figma design: settings/privacy (node 1895:20576)
-->

<script lang="ts">
    import { createEventDispatcher, onMount } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../SettingsItem.svelte';
    import { personalDataStore } from '../../stores/personalDataStore';
    import { userProfile, updateProfile } from '../../stores/userProfile';

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

    // ─── Location / Maps Toggle ──────────────────────────────────────────────
    // Read from encrypted personalDataStore so the setting persists across sessions.
    // impreciseByDefault=true means area mode is the default (privacy-first).
    let locationSettings = $state({ impreciseByDefault: true });
    personalDataStore.locationSettings.subscribe((s) => { locationSettings = s; });
    // nearbyByDefault is the UI-facing toggle:
    //   checked=true  → "Nearby by default" is ON  → impreciseByDefault=true
    let nearbyByDefault = $derived(locationSettings.impreciseByDefault);

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

    // ─── Ephemeral Log Forwarding Opt-out ──────────────────────────────────
    // Anonymized console logs forwarded to help diagnose production errors.
    // ON by default (legitimate interest, GDPR Art. 6(1)(f)), user can opt out.
    let stabilityLogsEnabled = $derived(!($userProfile.console_log_forwarding_opted_out ?? false));

    /**
     * Toggle ephemeral log forwarding opt-out.
     * When toggling OFF: stops ephemeral forwarding immediately.
     * When toggling ON: starts ephemeral forwarding (takes effect on next page load
     * or immediately if the forwarder detects the profile change).
     */
    function toggleStabilityLogs(): void {
        const newOptedOut = !($userProfile.console_log_forwarding_opted_out ?? false);
        updateProfile({ console_log_forwarding_opted_out: newOptedOut });
        // Immediately start/stop the forwarder for responsive UX
        import('../../services/clientLogForwarder').then(({ clientLogForwarder }) => {
            if (newOptedOut) {
                clientLogForwarder.stopEphemeral();
            } else {
                clientLogForwarder.startEphemeral();
            }
        });
    }

    // ─── Debug Logging Opt-in ────────────────────────────────────────────
    // Read debug logging preference from the user profile (synced to Directus).
    let debugLoggingEnabled = $derived($userProfile.debug_logging_opted_in ?? false);

    /**
     * Toggle the debug logging opt-in and persist to user profile.
     * The updateProfile call writes to IndexedDB and syncs to Directus
     * via the existing WebSocket profile sync flow.
     */
    function toggleDebugLogging(): void {
        updateProfile({ debug_logging_opted_in: !debugLoggingEnabled });
    }

    /**
     * Navigate to the "Share Debug Logs" sub-page where users can temporarily
     * share browser console logs with the support team.
     */
    function navigateToShareDebugLogs() {
        dispatch('openSettings', {
            settingsPath: 'privacy/share-debug-logs',
            direction: 'forward',
            icon: 'privacy',
            title: $text('settings.privacy.share_debug_logs_title')
        });
    }

    /** Admin check for the debug logs admin notice. */
    let isAdminUser = $derived($userProfile.is_admin === true);

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

<!-- Privacy Policy Link (description text is shown in the gradient banner header above) -->
<div class="settings-description">
    <a
        href="/legal/privacy"
        target="_blank"
        rel="noopener noreferrer"
        class="settings-gradient-link"
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
    subtitleTop={$text('common.chats')}
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
    onClick={() => personalDataStore.updateLocationSettings({ impreciseByDefault: !locationSettings.impreciseByDefault })}
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
    subtitleTop={$text('common.chats')}
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

<!-- Usage data — NOT editable, retention enforced by S3 lifecycle policy (3 years) -->
<SettingsItem
    type="subsubmenu"
    icon="usage"
    subtitleTop={$text('settings.privacy.auto_deletion.usage_data')}
    title={$text('settings.privacy.auto_deletion.usage_data.value')}
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
    subtitleTop={$text('common.invoices')}
    title={$text('settings.privacy.auto_deletion.invoices.value')}
/>

<!-- Compliance note — uses global .settings-note from settings.css -->
<div class="settings-note" data-testid="settings-note">
    <p>{$text('settings.privacy.auto_deletion.compliance_note')}</p>
</div>

<!-- ─── Stability Logs Section ──────────────────────────────────────────── -->
<SettingsItem
    type="heading"
    icon="log"
    title={$text('settings.privacy.stability_logs_title')}
/>

<!-- Stability logs toggle — anonymized console log forwarding for error diagnosis -->
<SettingsItem
    type="subsubmenu"
    icon="log"
    subtitleTop={$text('settings.privacy.stability_logs_description')}
    title={$text('settings.privacy.stability_logs_toggle_label')}
    hasToggle={true}
    checked={stabilityLogsEnabled}
    onClick={toggleStabilityLogs}
/>

<!-- Stability logs privacy note -->
<div class="settings-note">
    <p>{$text('settings.privacy.stability_logs_privacy_note')}</p>
</div>

<!-- ─── Debug Logging Section ──────────────────────────────────────────── -->
<SettingsItem
    type="heading"
    icon="log"
    title={$text('settings.privacy.debug_logging_title')}
/>

<!-- Debug logging toggle — opt-in for Tier 3 OpenTelemetry traces -->
<SettingsItem
    type="subsubmenu"
    icon="log"
    subtitleTop={$text('settings.privacy.debug_logging_description')}
    title={$text('settings.privacy.debug_logging_toggle_label')}
    hasToggle={true}
    checked={debugLoggingEnabled}
    onClick={toggleDebugLogging}
/>

<!-- Encrypted content disclaimer -->
<div class="settings-note">
    <p>{$text('settings.privacy.debug_logging_never_collected')}</p>
</div>

<!-- Share Debug Logs — temporary log sharing with support team -->
<SettingsItem
    type="submenu"
    icon="log"
    title={$text('settings.privacy.share_debug_logs_title')}
    onClick={navigateToShareDebugLogs}
/>
{#if isAdminUser}
    <div class="settings-note">
        <p>{$text('settings.privacy.share_debug_logs_admin_notice')}</p>
    </div>
{/if}

<!-- All styles moved to global settings.css: .settings-description, .settings-gradient-link, .settings-note -->
