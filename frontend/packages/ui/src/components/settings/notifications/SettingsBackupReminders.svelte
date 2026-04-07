<!--
  Backup Reminder Settings — lets users configure periodic data-export reminder emails.

  Architecture:
  - backupReminder preference stored in email_notification_preferences.backupReminder (JSON column)
  - Synced to server via the existing email_notification_settings WebSocket message (same as aiResponses)
  - backup_reminder_interval_days stored as a separate integer field on directus_users
  - last_export_at is set server-side (read-only here, shown for context)

  See docs/architecture/account-backup.md
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';
    import { updateProfile, userProfile } from '../../../stores/userProfile';
    import { authStore } from '../../../stores/authStore';
    import { getEmailDecryptedWithMasterKey } from '../../../services/cryptoService';
    import { webSocketService } from '../../../services/websocketService';

    const dispatch = createEventDispatcher();

    // ---------------------------------------------------------------------------
    // Local state
    // ---------------------------------------------------------------------------

    // Read from profile; default to opted-in.
    let backupReminderEnabled = $state(
        $userProfile.email_notification_preferences?.backupReminder ?? true
    );
    let intervalDays = $state($userProfile.backup_reminder_interval_days ?? 30);
    let isSaving = $state(false);

    // Readable interval options (days).
    const INTERVAL_OPTIONS = [14, 30, 60, 90] as const;

    // Formatted last-export date for display.
    let lastExportFormatted = $derived((): string => {
        const raw = $userProfile.last_export_at;
        if (!raw) return $text('settings.notifications.backup.never_exported');
        try {
            return new Date(raw).toLocaleDateString(undefined, {
                year: 'numeric',
                month: 'long',
                day: 'numeric',
            });
        } catch {
            return raw.slice(0, 10); // ISO date fallback
        }
    });

    // ---------------------------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------------------------

    /**
     * Sync backup reminder preference to server via the existing email_notification_settings
     * WebSocket message. The server handler already persists the full preferences object,
     * so we simply include backupReminder in the payload alongside aiResponses.
     */
    async function syncPreferencesToServer(enabled: boolean, days: number): Promise<void> {
        if (!$authStore.isAuthenticated) return;

        const newPreferences = {
            ...($userProfile.email_notification_preferences ?? { aiResponses: true }),
            backupReminder: enabled,
        };

        try {
            // WebSocket handler expects the current email to update the encrypted store.
            const loginEmail = await getEmailDecryptedWithMasterKey();
            await webSocketService.sendMessage('email_notification_settings', {
                enabled: $userProfile.email_notifications_enabled ?? false,
                email: loginEmail,
                preferences: newPreferences,
                // Extra field consumed by the WS handler to persist interval separately.
                backup_reminder_interval_days: days,
            });

            updateProfile({
                email_notification_preferences: newPreferences,
                backup_reminder_interval_days: days,
            });

            console.debug('[SettingsBackupReminders] Synced preferences:', newPreferences, 'interval:', days);
        } catch (error) {
            console.error('[SettingsBackupReminders] Failed to sync preferences:', error);
            throw error;
        }
    }

    // ---------------------------------------------------------------------------
    // Event handlers
    // ---------------------------------------------------------------------------

    async function handleToggleEnabled(): Promise<void> {
        if (!$authStore.isAuthenticated) return;
        isSaving = true;
        const newEnabled = !backupReminderEnabled;
        try {
            await syncPreferencesToServer(newEnabled, intervalDays);
            backupReminderEnabled = newEnabled;
        } catch {
            // Revert optimistic state
            backupReminderEnabled = !newEnabled;
        } finally {
            isSaving = false;
        }
    }

    async function handleIntervalChange(days: number): Promise<void> {
        if (!$authStore.isAuthenticated || days === intervalDays) return;
        isSaving = true;
        const prevDays = intervalDays;
        intervalDays = days; // Optimistic
        try {
            await syncPreferencesToServer(backupReminderEnabled, days);
        } catch {
            intervalDays = prevDays; // Revert
        } finally {
            isSaving = false;
        }
    }

    function navigateToExport(): void {
        dispatch('openSettings', {
            settingsPath: 'account/export',
            direction: 'forward',
            icon: 'download',
            title: $text('settings.account.export'),
        });
    }
</script>

<div class="backup-reminders-container">
    <!-- Master toggle: enable / disable backup reminder emails -->
    <SettingsItem
        type="submenu"
        icon="subsetting_icon download"
        title={$text('settings.notifications.backup.email_toggle')}
        subtitleTop={$text('settings.notifications.backup.email_toggle_info')}
        hasToggle={true}
        checked={backupReminderEnabled}
        disabled={isSaving}
        onClick={handleToggleEnabled}
    />

    {#if backupReminderEnabled}
        <!-- Interval selector -->
        <div class="interval-section">
            <div class="interval-label">
                {$text('settings.notifications.backup.interval')}
            </div>
            <div class="interval-options">
                {#each INTERVAL_OPTIONS as days}
                    <button
                        class="interval-option"
                        class:selected={intervalDays === days}
                        disabled={isSaving}
                        onclick={() => handleIntervalChange(days)}
                    >
                        {$text('settings.notifications.backup.interval_days', { values: { count: days } })}
                    </button>
                {/each}
            </div>
        </div>
    {/if}

    <!-- Last export info — plain heading item (read-only) -->
    <SettingsItem
        type="heading"
        icon="subsetting_icon info"
        title={$text('settings.notifications.backup.last_export')}
        subtitleTop={lastExportFormatted()}
    />

    <!-- Quick link to the export page -->
    <SettingsItem
        type="submenu"
        icon="download"
        title={$text('settings.account.export')}
        subtitleTop={$text('settings.notifications.backup.export_hint')}
        onClick={navigateToExport}
    />
</div>

<style>
    .backup-reminders-container {
        width: 100%;
        padding: 0 10px;
    }

    .interval-section {
        padding: var(--spacing-6) var(--spacing-8);
        display: flex;
        flex-direction: column;
        gap: var(--spacing-5);
    }

    .interval-label {
        font-size: var(--font-size-xs);
        color: var(--color-text-secondary, #888);
        font-weight: 500;
    }

    .interval-options {
        display: flex;
        gap: var(--spacing-4);
        flex-wrap: wrap;
    }

    .interval-option {
        padding: 6px 14px;
        border-radius: var(--radius-8);
        border: 1.5px solid var(--color-border, #ccc);
        background: transparent;
        color: var(--color-text, #333);
        font-size: var(--font-size-xs);
        font-weight: 500;
        cursor: pointer;
        transition: background var(--duration-fast), border-color var(--duration-fast), color var(--duration-fast);
    }

    .interval-option:hover:not(:disabled) {
        border-color: var(--color-primary, #4f46e5);
        color: var(--color-primary, #4f46e5);
    }

    .interval-option.selected {
        background: var(--color-primary, #4f46e5);
        border-color: var(--color-primary, #4f46e5);
        color: white;
    }

    .interval-option:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
</style>
