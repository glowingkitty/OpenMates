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
    import { webSocketService } from '../../../services/websocketService';

    const dispatch = createEventDispatcher();

    // ---------------------------------------------------------------------------
    // Local state
    // ---------------------------------------------------------------------------

    // Use the cached profile while the fresh server snapshot loads.
    let backupReminderEnabled = $state(
        $userProfile.email_notification_preferences?.backupReminder ?? false
    );
    let intervalDays = $state($userProfile.backup_reminder_interval_days ?? 30);
    let isSaving = $state(false);
    const pendingReads = new Set<string>();
    const pendingWrites = new Set<string>();

    $effect(() => {
        function applyServerSettings(payload: {
            enabled: boolean;
            preferences?: Record<string, boolean>;
            backup_reminder_interval_days?: number;
        }): void {
            if (typeof payload.enabled !== 'boolean' || !payload.preferences || typeof payload.preferences !== 'object') return;
            const preferences = {
                aiResponses: true,
                workflowRuns: true,
                includeContent: false,
                backupReminder: false,
                webhookChats: false,
                ...payload.preferences,
            };
            backupReminderEnabled = preferences.backupReminder;
            if (typeof payload.backup_reminder_interval_days === 'number' && payload.backup_reminder_interval_days > 0) {
                intervalDays = payload.backup_reminder_interval_days;
            }
            updateProfile({
                email_notifications_enabled: payload.enabled,
                email_notification_preferences: preferences,
                backup_reminder_interval_days: intervalDays,
            });
        }

        function handleEmailSettingsSnapshot(payload: Parameters<typeof applyServerSettings>[0] & { request_id?: string }): void {
            if (!payload.request_id || !pendingReads.delete(payload.request_id)) return;
            applyServerSettings(payload);
            console.warn('[SettingsBackupReminders] email_notification_settings_snapshot received, persisted to IDB');
        }

        function handleEmailSettingsAck(payload: Parameters<typeof applyServerSettings>[0] & { request_id?: string; success?: boolean }): void {
            if (!payload.request_id || !pendingWrites.delete(payload.request_id)) return;
            if (payload.success) applyServerSettings(payload);
        }

        function handleEmailSettingsUpdated(payload: Parameters<typeof applyServerSettings>[0]): void {
            applyServerSettings(payload);
        }

        function handleEmailSettingsError(payload: { request_id?: string }): void {
            if (!payload?.request_id) return;
            pendingReads.delete(payload.request_id);
            if (pendingWrites.delete(payload.request_id)) {
                backupReminderEnabled = $userProfile.email_notification_preferences?.backupReminder ?? false;
                intervalDays = $userProfile.backup_reminder_interval_days ?? 30;
            }
        }

        webSocketService.on('email_notification_settings_snapshot', handleEmailSettingsSnapshot);
        webSocketService.on('email_notification_settings_ack', handleEmailSettingsAck);
        webSocketService.on('email_notification_settings_updated', handleEmailSettingsUpdated);
        webSocketService.on('error', handleEmailSettingsError);
        if ($authStore.isAuthenticated) {
            const requestId = crypto.randomUUID();
            pendingReads.add(requestId);
            void webSocketService.sendMessage('email_notification_settings_get', { request_id: requestId }).catch((error) => {
                pendingReads.delete(requestId);
                console.error('[SettingsBackupReminders] Failed to load email notification settings:', error);
            });
        }
        return () => {
            webSocketService.off('email_notification_settings_snapshot', handleEmailSettingsSnapshot);
            webSocketService.off('email_notification_settings_ack', handleEmailSettingsAck);
            webSocketService.off('email_notification_settings_updated', handleEmailSettingsUpdated);
            webSocketService.off('error', handleEmailSettingsError);
            pendingReads.clear();
            pendingWrites.clear();
        };
    });

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
     * WebSocket message. Send only this category so other notification choices survive.
     */
    async function syncPreferencesToServer(enabled: boolean, days: number): Promise<void> {
        if (!$authStore.isAuthenticated) return;

        const requestId = crypto.randomUUID();
        pendingWrites.add(requestId);
        try {
            await webSocketService.sendMessage('email_notification_settings', {
                request_id: requestId,
                preferences: { backupReminder: enabled },
                // Extra field consumed by the WS handler to persist interval separately.
                backup_reminder_interval_days: days,
            });

        } catch (error) {
            pendingWrites.delete(requestId);
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
        data-testid="email-backup-reminder"
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
