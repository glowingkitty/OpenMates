<!--
Chat Notifications Settings - Push and Email notification preferences
Allows users to enable/disable notifications and configure notification categories.
Chat email alerts are sent when the user is inactive. Workflow runs use a daily digest.
When enabled, notifications are sent to the verified account email.
Native Swift counterparts:
- apple/OpenMates/Sources/Features/Settings/Views/SettingsSubPages.swift
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';
    import { SettingsSectionHeading } from '../../settings/elements';
    import {
        pushNotificationStore,
        requiresPWAInstall
    } from '../../../stores/pushNotificationStore';
    import { pushNotificationService } from '../../../services/pushNotificationService';
    import { updateProfile, userProfile } from '../../../stores/userProfile';
    import { authStore } from '../../../stores/authStore';
    import { webSocketService } from '../../../services/websocketService';
    import { notificationStore } from '../../../stores/notificationStore';
    
    // Local state for push notifications
    let isRequestingPermission = $state(false);
    let showIOSInstructions = $state(false);
    
    // Local state for email notifications
    // The server uses the verified account email; no separate email input is needed.
    let emailNotificationsEnabled = $state($userProfile.email_notifications_enabled ?? false);
    const defaultEmailPreferences = {
        aiResponses: true,
        workflowRuns: true,
        includeContent: false,
        backupReminder: false,
        webhookChats: false
    };
    let emailPreferences = $state({
        ...defaultEmailPreferences,
        ...$userProfile.email_notification_preferences
    });
    let isSavingEmail = $state(false);
    const pendingEmailReads = new Set<string>();
    const pendingEmailWrites = new Set<string>();

    function restoreDurableEmailSettings(): void {
        emailNotificationsEnabled = $userProfile.email_notifications_enabled ?? false;
        emailPreferences = {
            ...defaultEmailPreferences,
            ...$userProfile.email_notification_preferences
        };
    }
    
    /**
     * Sync push notification settings to server via user profile update
     * This ensures settings persist across devices for authenticated users
     */
    function syncSettingsToServer(): void {
        // Only sync for authenticated users
        if (!$authStore.isAuthenticated) {
            console.warn('[SettingsChatNotifications] User not authenticated, skipping server sync');
            return;
        }
        
        const syncData = pushNotificationStore.getServerSyncData();
        updateProfile({
            push_notification_enabled: syncData.push_notification_enabled,
            push_notification_preferences: syncData.push_notification_preferences,
            push_notification_banner_shown: syncData.push_notification_banner_shown
        });
        console.warn('[SettingsChatNotifications] Synced settings to server:', syncData);
    }
    
    // Derived states for UI
    let isSupported = $derived($pushNotificationStore.isSupported);
    let permission = $derived($pushNotificationStore.permission);
    let isEnabled = $derived($pushNotificationStore.enabled);
    let preferences = $derived($pushNotificationStore.preferences);
    
    // iOS devices in Safari (non-PWA) report push as unsupported, but it works after
    // installing the app to the home screen. Show install instructions instead of "not supported".
    let needsPWAInstall = $derived($requiresPWAInstall);
    
    // Permission status text
    let permissionStatusText = $derived(
        permission === 'granted'
            ? $text('settings.chat.notifications.permission_granted')
            : permission === 'denied'
                ? $text('settings.chat.notifications.permission_denied')
                : $text('settings.chat.notifications.permission_default')
    );
    
    /**
     * Handle the main enable/disable toggle
     */
    async function handleToggleEnabled(): Promise<void> {
        // If trying to enable and permission not granted, request it first
        if (!isEnabled && permission !== 'granted') {
            // Check if iOS needs PWA installation
            if ($requiresPWAInstall) {
                showIOSInstructions = true;
                return;
            }
            
            isRequestingPermission = true;
            try {
                const result = await pushNotificationService.requestPermission();
                if (result.granted) {
                    pushNotificationStore.setEnabled(true);
                    syncSettingsToServer();
                }
            } finally {
                isRequestingPermission = false;
            }
        } else {
            // Toggle the enabled state
            pushNotificationStore.setEnabled(!isEnabled);
            
            // If disabling, unsubscribe from push
            if (isEnabled) {
                await pushNotificationService.unsubscribe();
            } else if (permission === 'granted') {
                // Re-enabling with permission already granted: confirm & subscribe
                await pushNotificationService.showActivationConfirmation();
                await pushNotificationService.subscribe();
            }
            
            // Sync to server
            syncSettingsToServer();
        }
    }
    
    /**
     * Toggle a specific notification preference
     */
    function handleTogglePreference(key: 'newMessages' | 'serverEvents' | 'softwareUpdates'): void {
        pushNotificationStore.togglePreference(key);
        // Sync to server after preference change
        syncSettingsToServer();
    }
    
    /**
     * Close iOS instructions modal
     */
    function closeIOSInstructions(): void {
        showIOSInstructions = false;
    }
    
    // =====================================================
    // EMAIL NOTIFICATION HANDLERS
    // =====================================================
    
    /**
     * Send the master switch to the server, which uses the verified account email.
     */
    async function sendEmailSettingsToServer(enabled: boolean): Promise<void> {
        const requestId = crypto.randomUUID();
        pendingEmailWrites.add(requestId);
        try {
            await webSocketService.sendMessage('email_notification_settings', {
                request_id: requestId,
                enabled,
                // Changing the master switch must not rewrite category choices.
                preferences: {}
            });
            console.warn('[SettingsChatNotifications] Sent email notification settings to server');
        } catch (error) {
            pendingEmailWrites.delete(requestId);
            console.error('[SettingsChatNotifications] Failed to send email notification settings:', error);
            throw error;
        }
    }
    
    /**
     * Handle email notifications enable/disable toggle.
     * When enabled, the server uses the verified account email.
     */
    async function handleToggleEmailEnabled(): Promise<void> {
        if (!$authStore.isAuthenticated) {
            console.warn('[SettingsChatNotifications] User not authenticated, skipping email toggle');
            return;
        }
        
        isSavingEmail = true;
        const previousEnabled = emailNotificationsEnabled;
        
        try {
            if (!emailNotificationsEnabled) {
                await sendEmailSettingsToServer(true);
                
                // Update local state optimistically
                emailNotificationsEnabled = true;
                
                console.warn('[SettingsChatNotifications] Email notifications enabled with login email');
            } else {
                // Disabling: send disable request to server
                await sendEmailSettingsToServer(false);
                
                // Update local state
                emailNotificationsEnabled = false;
                
                console.warn('[SettingsChatNotifications] Email notifications disabled');
            }
        } catch (error) {
            console.error('[SettingsChatNotifications] Error toggling email notifications:', error);
            // Revert local state on error
            emailNotificationsEnabled = previousEnabled;
        } finally {
            isSavingEmail = false;
        }
    }
    
    /**
     * Toggle AI responses email notification preference
     */
    async function handleToggleAIResponses(): Promise<void> {
        await toggleEmailPreference('aiResponses');
    }

    async function handleToggleWorkflowRuns(): Promise<void> {
        await toggleEmailPreference('workflowRuns');
    }

    async function handleToggleIncludeContent(): Promise<void> {
        await toggleEmailPreference('includeContent');
    }

    /**
     * Toggle webhook chats email notification preference
     */
    async function handleToggleWebhookChats(): Promise<void> {
        await toggleEmailPreference('webhookChats');
    }

    async function toggleEmailPreference(key: 'aiResponses' | 'workflowRuns' | 'includeContent' | 'webhookChats'): Promise<void> {
        const previous = emailPreferences;
        const value = !(previous[key] ?? (key !== 'includeContent'));
        const newPreferences = { ...previous, [key]: value };
        emailPreferences = newPreferences;
        try {
            await syncEmailPreferencesToServer({ [key]: value });
        } catch {
            emailPreferences = previous;
        }
    }
    
    /**
     * Sync email notification preferences to server via WebSocket
     */
    async function syncEmailPreferencesToServer(changed: Record<string, boolean>): Promise<void> {
        if (!$authStore.isAuthenticated) {
            console.warn('[SettingsChatNotifications] User not authenticated, skipping email preferences sync');
            return;
        }
        
        const requestId = crypto.randomUUID();
        pendingEmailWrites.add(requestId);
        try {
            await webSocketService.sendMessage('email_notification_settings', {
                request_id: requestId,
                preferences: changed
            });
            
            console.warn('[SettingsChatNotifications] Email notification preferences synced:', emailPreferences);
        } catch (error) {
            pendingEmailWrites.delete(requestId);
            console.error('[SettingsChatNotifications] Failed to sync email preferences:', error);
            throw error;
        }
    }

    /**
     * Register WebSocket handlers for email notification settings acknowledgement
     * and cross-device broadcast.
     *
     * email_notification_settings_ack  — server confirmed save on this device
     * email_notification_settings_updated — server broadcast to other devices
     */
    $effect(() => {
        function applyServerEmailSettings(payload: { enabled: boolean; preferences?: Record<string, boolean> }): void {
            if (typeof payload.enabled !== 'boolean' || !payload.preferences || typeof payload.preferences !== 'object') return;
            const mergedPreferences = { ...defaultEmailPreferences, ...payload.preferences };
            emailNotificationsEnabled = payload.enabled;
            emailPreferences = mergedPreferences;
            updateProfile({
                email_notifications_enabled: payload.enabled,
                email_notification_preferences: mergedPreferences
            });
        }

        function handleEmailSettingsAck(payload: { request_id?: string; success: boolean; enabled: boolean; preferences?: Record<string, boolean> }): void {
            if (!payload.request_id || !pendingEmailWrites.delete(payload.request_id)) return;
            if (!payload.success) {
                console.error('[SettingsChatNotifications] Server rejected email notification settings save');
                restoreDurableEmailSettings();
                return;
            }
            // Server confirmed: persist to IndexedDB via updateProfile (safe plain object)
            applyServerEmailSettings(payload);
            notificationStore.success(payload.enabled ? 'Email notification settings saved.' : 'Email notifications turned off.');
            console.warn('[SettingsChatNotifications] email_notification_settings_ack received, persisted to IDB');
        }

        function handleEmailSettingsUpdated(payload: { enabled: boolean; preferences?: Record<string, boolean> }): void {
            // Another device of the same user changed the setting — sync local UI and IDB
            applyServerEmailSettings(payload);
            console.warn('[SettingsChatNotifications] email_notification_settings_updated received from other device, synced');
        }

        function handleEmailSettingsSnapshot(payload: { request_id?: string; enabled: boolean; preferences?: Record<string, boolean> }): void {
            if (!payload.request_id || !pendingEmailReads.delete(payload.request_id)) return;
            applyServerEmailSettings(payload);
            console.warn('[SettingsChatNotifications] email_notification_settings_snapshot received, persisted to IDB');
        }

        function handleEmailSettingsError(payload: { request_id?: string }): void {
            if (!payload?.request_id) return;
            pendingEmailReads.delete(payload.request_id);
            if (pendingEmailWrites.delete(payload.request_id)) restoreDurableEmailSettings();
        }

        webSocketService.on('email_notification_settings_ack', handleEmailSettingsAck);
        webSocketService.on('email_notification_settings_updated', handleEmailSettingsUpdated);
        webSocketService.on('email_notification_settings_snapshot', handleEmailSettingsSnapshot);
        webSocketService.on('error', handleEmailSettingsError);
        if ($authStore.isAuthenticated) {
            const requestId = crypto.randomUUID();
            pendingEmailReads.add(requestId);
            void webSocketService.sendMessage('email_notification_settings_get', { request_id: requestId }).catch((error) => {
                pendingEmailReads.delete(requestId);
                console.error('[SettingsChatNotifications] Failed to load email notification settings:', error);
            });
        }

        return () => {
            webSocketService.off('email_notification_settings_ack', handleEmailSettingsAck);
            webSocketService.off('email_notification_settings_updated', handleEmailSettingsUpdated);
            webSocketService.off('email_notification_settings_snapshot', handleEmailSettingsSnapshot);
            webSocketService.off('error', handleEmailSettingsError);
            pendingEmailReads.clear();
            pendingEmailWrites.clear();
        };
    });
</script>

<div class="notifications-settings-container">
    <!-- Push Notification Support Status -->
    {#if !isSupported && needsPWAInstall}
        <!-- iOS Safari (non-PWA): Push is available after adding to Home Screen -->
        <div class="pwa-install-banner">
            <div class="pwa-install-header">
                <span class="pwa-install-title">
                    {$text('settings.chat.notifications.pwa_install_title', { 
                        default: 'Add to Home Screen to Enable Notifications' 
                    })}
                </span>
            </div>
            <p class="pwa-install-desc">
                {$text('settings.chat.notifications.pwa_install_desc')}
            </p>
            <div class="pwa-install-steps">
                <p>{$text('notifications.push.ios_install_step1')}</p>
                <p>{$text('notifications.push.ios_install_step2')}</p>
                <p>{$text('notifications.push.ios_install_step3')}</p>
                <p>{$text('notifications.push.ios_install_step4')}</p>
            </div>
        </div>
    {:else if !isSupported}
        <!-- Truly unsupported browser/device -->
        <div class="warning-banner">
            <span class="warning-text">
                {$text('settings.chat.notifications.not_supported')}
            </span>
        </div>
    {:else}
        <!-- Main Enable/Disable Toggle -->
        <SettingsItem
            type="submenu"
            icon="subsetting_icon announcement"
            title={$text('settings.chat.notifications.enable')}
            subtitleTop={permissionStatusText}
            hasToggle={true}
            checked={isEnabled && permission === 'granted'}
            disabled={isRequestingPermission || permission === 'denied'}
            onClick={handleToggleEnabled}
        />
        
        <!-- Permission Denied Info -->
        {#if permission === 'denied'}
            <div class="info-banner">
                <span class="info-text">
                    {$text('settings.chat.notifications.denied_info')}
                </span>
            </div>
        {/if}
        
        <!-- Notification Categories (only show if enabled) -->
        {#if isEnabled && permission === 'granted'}
            <div class="category-section">
                <SettingsSectionHeading
                    title={$text('settings.chat.notifications.categories')}
                    icon="announcement"
                />
                
                <SettingsItem
                    type="submenu"
                    icon="subsetting_icon chat"
                    title={$text('settings.chat.notifications.new_messages')}
                    subtitleTop={$text('settings.chat.notifications.new_messages_desc')}
                    hasToggle={true}
                    checked={preferences.newMessages}
                    onClick={() => handleTogglePreference('newMessages')}
                />
                
                <SettingsItem
                    type="submenu"
                    icon="subsetting_icon cloud"
                    title={$text('settings.chat.notifications.server_events')}
                    subtitleTop={$text('settings.chat.notifications.server_events_desc')}
                    hasToggle={true}
                    checked={preferences.serverEvents}
                    onClick={() => handleTogglePreference('serverEvents')}
                />
                
                <SettingsItem
                    type="submenu"
                    icon="subsetting_icon download"
                    title={$text('settings.chat.notifications.software_updates')}
                    subtitleTop={$text('settings.chat.notifications.software_updates_desc')}
                    hasToggle={true}
                    checked={preferences.softwareUpdates}
                    onClick={() => handleTogglePreference('softwareUpdates')}
                />
            </div>
        {/if}
    {/if}
    
    <!-- ================================================== -->
    <!-- EMAIL NOTIFICATIONS SECTION -->
    <!-- ================================================== -->
    <div class="email-section" data-testid="email-section">
        <SettingsSectionHeading
            title={$text('settings.chat.notifications.email_section')}
            icon="email"
        />
        
        <!-- Info banner explaining how email notifications work -->
        <div class="info-banner email-info">
            <span class="info-text">
                {$text('settings.chat.notifications.email_chat_how_it_works')}
            </span>
        </div>
        
        <!-- Main Enable/Disable Toggle for Email -->
        <!-- Uses the verified account email automatically -->
        <SettingsItem
            type="submenu"
            icon="subsetting_icon email"
            title={$text('settings.chat.notifications.email_enable')}
            data-testid="email-notifications-master"
            subtitleTop={$text('settings.chat.notifications.email_enable_desc')}
            hasToggle={true}
            checked={emailNotificationsEnabled}
            disabled={isSavingEmail}
            onClick={handleToggleEmailEnabled}
        />
        
        <!-- Email notification options (only show if enabled) -->
        {#if emailNotificationsEnabled}
            <div class="email-options">
                <!-- AI Responses toggle -->
                <SettingsItem
                    type="submenu"
                    icon="subsetting_icon chat"
                    title={$text('settings.chat.notifications.email_ai_responses')}
                    data-testid="email-notifications-ai-responses"
                    subtitleTop={$text('settings.chat.notifications.email_ai_responses_desc')}
                    hasToggle={true}
                    checked={emailPreferences.aiResponses}
                    disabled={isSavingEmail}
                    onClick={handleToggleAIResponses}
                />
                <SettingsItem
                    type="submenu"
                    icon="subsetting_icon cloud"
                    title={$text('settings.chat.notifications.email_workflow_runs')}
                    data-testid="email-notifications-workflow-runs"
                    subtitleTop={$text('settings.chat.notifications.email_workflow_runs_desc')}
                    hasToggle={true}
                    checked={emailPreferences.workflowRuns}
                    disabled={isSavingEmail}
                    onClick={handleToggleWorkflowRuns}
                />
                <SettingsItem
                    type="submenu"
                    icon="subsetting_icon email"
                    title={$text('settings.chat.notifications.email_include_content')}
                    data-testid="email-notifications-include-content"
                    subtitleTop={$text('settings.chat.notifications.email_include_content_desc')}
                    hasToggle={true}
                    checked={emailPreferences.includeContent}
                    disabled={isSavingEmail}
                    onClick={handleToggleIncludeContent}
                />
                <!-- Webhook Chats toggle -->
                <SettingsItem
                    type="submenu"
                    icon="subsetting_icon link"
                    title={$text('settings.chat.notifications.email_webhooks')}
                    data-testid="email-notifications-webhook-chats"
                    subtitleTop={$text('settings.chat.notifications.email_webhooks_desc')}
                    hasToggle={true}
                    checked={emailPreferences.webhookChats ?? true}
                    disabled={isSavingEmail}
                    onClick={handleToggleWebhookChats}
                />
            </div>
        {/if}
        
        <!-- Saving indicator -->
        {#if isSavingEmail}
            <div class="saving-indicator">
                {$text('settings.chat.notifications.email_saving')}
            </div>
        {/if}
    </div>
    
    <!-- iOS PWA Instructions Modal -->
    {#if showIOSInstructions}
        <div class="ios-modal-overlay" role="dialog" aria-modal="true" tabindex="-1" onclick={closeIOSInstructions} onkeydown={(e) => { if (e.key === 'Escape') { e.preventDefault(); closeIOSInstructions(); } }}>
            <div class="ios-modal" role="presentation" onclick={(e) => e.stopPropagation()}>
                <h3 class="ios-modal-title">
                    {$text('notifications.push.ios_install_title')}
                </h3>
                <div class="ios-modal-content">
                    <p>{$text('notifications.push.ios_install_step1')}</p>
                    <p>{$text('notifications.push.ios_install_step2')}</p>
                    <p>{$text('notifications.push.ios_install_step3')}</p>
                    <p>{$text('notifications.push.ios_install_step4')}</p>
                </div>
                <button class="ios-modal-close" onclick={closeIOSInstructions}>
                    {$text('common.close')}
                </button>
            </div>
        </div>
    {/if}
</div>

<style>
    .notifications-settings-container {
        width: 100%;
        padding: 0 10px;
    }
    
    .warning-banner,
    .info-banner {
        padding: var(--spacing-6) var(--spacing-8);
        border-radius: var(--radius-3);
        margin-bottom: var(--spacing-8);
    }
    
    .warning-banner {
        background-color: rgba(255, 193, 7, 0.15);
        border: 1px solid rgba(255, 193, 7, 0.3);
    }
    
    .info-banner {
        background-color: var(--color-grey-10);
        border: 1px solid var(--color-grey-20);
    }
    
    .warning-text,
    .info-text {
        font-size: var(--font-size-xs);
        line-height: 1.5;
        color: var(--color-font-primary);
    }
    
    /* PWA Install Instructions Banner (iOS Safari non-PWA) */
    .pwa-install-banner {
        padding: var(--spacing-8);
        border-radius: var(--radius-5);
        margin-bottom: var(--spacing-8);
        background-color: var(--color-grey-10);
        border: 1px solid var(--color-primary, var(--color-grey-30));
    }
    
    .pwa-install-header {
        display: flex;
        align-items: center;
        gap: var(--spacing-5);
        margin-bottom: var(--spacing-4);
    }
    
    .pwa-install-title {
        font-size: null;
        font-weight: 600;
        color: var(--color-font-primary);
        line-height: 1.4;
    }
    
    .pwa-install-desc {
        font-size: var(--font-size-xs);
        color: var(--color-grey-60);
        line-height: 1.5;
        margin: 0 0 12px 0;
    }
    
    .pwa-install-steps {
        display: flex;
        flex-direction: column;
        gap: var(--spacing-3);
    }
    
    .pwa-install-steps p {
        margin: 0;
        font-size: var(--font-size-small);
        color: var(--color-font-primary);
        line-height: 1.6;
    }
    
    .category-section {
        margin-top: var(--spacing-12);
        padding-top: var(--spacing-8);
        border-top: 1px solid var(--color-grey-20);
    }
    
    
    /* iOS Modal Styles */
    .ios-modal-overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background-color: rgba(0, 0, 0, 0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: var(--z-index-modal);
    }
    
    .ios-modal {
        background-color: var(--color-grey-0);
        border-radius: var(--radius-7);
        padding: var(--spacing-12);
        max-width: 320px;
        width: 90%;
        text-align: center;
    }
    
    .ios-modal-title {
        font-size: var(--font-size-h3-mobile);
        font-weight: 600;
        color: var(--color-font-primary);
        margin: 0 0 16px 0;
    }
    
    .ios-modal-content {
        text-align: left;
        margin-bottom: var(--spacing-10);
    }
    
    .ios-modal-content p {
        font-size: var(--font-size-small);
        color: var(--color-grey-70);
        line-height: 1.6;
        margin: 8px 0;
    }
    
    .ios-modal-close {
        width: 100%;
        padding: var(--spacing-6) var(--spacing-12);
        background-color: var(--color-button-primary);
        color: var(--color-font-button);
        border: none;
        border-radius: var(--radius-8);
        font-size: var(--font-size-small);
        font-weight: 600;
        cursor: pointer;
        transition: background-color var(--duration-normal) var(--easing-default);
    }
    
    .ios-modal-close:hover {
        background-color: var(--color-button-primary-hover);
    }
    
    /* Email Notifications Section Styles */
    .email-section {
        margin-top: var(--spacing-16);
        padding-top: var(--spacing-12);
        border-top: 1px solid var(--color-grey-20);
    }
    
    .email-info {
        margin-bottom: var(--spacing-8);
    }
    
    .email-options {
        margin-top: var(--spacing-8);
        padding-top: var(--spacing-8);
        border-top: 1px solid var(--color-grey-10);
    }
    
    .saving-indicator {
        text-align: center;
        font-size: var(--font-size-xxs);
        color: var(--color-grey-50);
        margin-top: var(--spacing-6);
        padding: var(--spacing-4);
    }
</style>
