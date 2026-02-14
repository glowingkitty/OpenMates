<!--
Chat Notifications Settings - Push and Email notification preferences
Allows users to enable/disable notifications and configure notification categories.
Email notifications are only sent when the user is offline (no active WebSocket connections).
When enabled, notifications are sent to the user's login email (from account settings).
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';
    import {
        pushNotificationStore,
        requiresPWAInstall
    } from '../../../stores/pushNotificationStore';
    import { pushNotificationService } from '../../../services/pushNotificationService';
    import { updateProfile, userProfile } from '../../../stores/userProfile';
    import { authStore } from '../../../stores/authStore';
    import { getEmailDecryptedWithMasterKey } from '../../../services/cryptoService';
    import { webSocketService } from '../../../services/websocketService';
    
    // Local state for push notifications
    let isRequestingPermission = $state(false);
    let showIOSInstructions = $state(false);
    
    // Local state for email notifications
    // When enabled, uses the login email from account settings (no separate email input needed)
    let emailNotificationsEnabled = $state($userProfile.email_notifications_enabled ?? false);
    let emailPreferences = $state($userProfile.email_notification_preferences ?? { aiResponses: true });
    let isSavingEmail = $state(false);
    
    /**
     * Sync push notification settings to server via user profile update
     * This ensures settings persist across devices for authenticated users
     */
    function syncSettingsToServer(): void {
        // Only sync for authenticated users
        if (!$authStore.isAuthenticated) {
            console.debug('[SettingsChatNotifications] User not authenticated, skipping server sync');
            return;
        }
        
        const syncData = pushNotificationStore.getServerSyncData();
        updateProfile({
            push_notification_enabled: syncData.push_notification_enabled,
            push_notification_preferences: syncData.push_notification_preferences,
            push_notification_banner_shown: syncData.push_notification_banner_shown
        });
        console.debug('[SettingsChatNotifications] Synced settings to server:', syncData);
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
                // If enabling and permission already granted, subscribe
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
     * Send email notification settings to server via WebSocket.
     * Server will encrypt the email and store it.
     */
    async function sendEmailSettingsToServer(enabled: boolean, email: string | null): Promise<void> {
        try {
            await webSocketService.sendMessage('email_notification_settings', {
                enabled,
                email,  // Plaintext email - server will encrypt it
                preferences: emailPreferences
            });
            console.debug('[SettingsChatNotifications] Sent email notification settings to server');
        } catch (error) {
            console.error('[SettingsChatNotifications] Failed to send email notification settings:', error);
            throw error;
        }
    }
    
    /**
     * Handle email notifications enable/disable toggle.
     * When enabled: automatically uses the user's login email from account settings.
     * When disabled: clears the notification email from the server.
     */
    async function handleToggleEmailEnabled(): Promise<void> {
        if (!$authStore.isAuthenticated) {
            console.debug('[SettingsChatNotifications] User not authenticated, skipping email toggle');
            return;
        }
        
        isSavingEmail = true;
        
        try {
            if (!emailNotificationsEnabled) {
                // Enabling: fetch the login email and send to server for encryption
                const loginEmail = await getEmailDecryptedWithMasterKey();
                if (!loginEmail) {
                    console.error('[SettingsChatNotifications] Could not retrieve login email for notifications');
                    return;
                }
                
                // Send to server via WebSocket (server encrypts and stores)
                await sendEmailSettingsToServer(true, loginEmail);
                
                // Update local state optimistically
                emailNotificationsEnabled = true;
                updateProfile({
                    email_notifications_enabled: true,
                    email_notification_preferences: emailPreferences
                });
                
                console.debug('[SettingsChatNotifications] Email notifications enabled with login email');
            } else {
                // Disabling: send disable request to server
                await sendEmailSettingsToServer(false, null);
                
                // Update local state
                emailNotificationsEnabled = false;
                updateProfile({
                    email_notifications_enabled: false,
                    email_notification_preferences: emailPreferences
                });
                
                console.debug('[SettingsChatNotifications] Email notifications disabled');
            }
        } catch (error) {
            console.error('[SettingsChatNotifications] Error toggling email notifications:', error);
            // Revert local state on error
            emailNotificationsEnabled = !emailNotificationsEnabled;
        } finally {
            isSavingEmail = false;
        }
    }
    
    /**
     * Toggle AI responses email notification preference
     */
    async function handleToggleAIResponses(): Promise<void> {
        const newPreferences = {
            ...emailPreferences,
            aiResponses: !emailPreferences.aiResponses
        };
        
        // Update local state first
        emailPreferences = newPreferences;
        
        // Sync to server if email notifications are enabled
        if (emailNotificationsEnabled) {
            await syncEmailPreferencesToServer();
        } else {
            // Just update local profile
            updateProfile({
                email_notification_preferences: newPreferences
            });
        }
    }
    
    /**
     * Sync email notification preferences to server via WebSocket
     */
    async function syncEmailPreferencesToServer(): Promise<void> {
        if (!$authStore.isAuthenticated) {
            console.debug('[SettingsChatNotifications] User not authenticated, skipping email preferences sync');
            return;
        }
        
        try {
            // Get current email to include in the update (server needs it to maintain encryption)
            const loginEmail = await getEmailDecryptedWithMasterKey();
            await webSocketService.sendMessage('email_notification_settings', {
                enabled: emailNotificationsEnabled,
                email: loginEmail,
                preferences: emailPreferences
            });
            
            // Update local profile
            updateProfile({
                email_notification_preferences: emailPreferences
            });
            
            console.debug('[SettingsChatNotifications] Email notification preferences synced:', emailPreferences);
        } catch (error) {
            console.error('[SettingsChatNotifications] Failed to sync email preferences:', error);
        }
    }
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
            icon="subsetting_icon subsetting_icon_announcement"
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
                <h3 class="section-title">
                    {$text('settings.chat.notifications.categories')}
                </h3>
                
                <SettingsItem
                    type="submenu"
                    icon="subsetting_icon subsetting_icon_chat"
                    title={$text('settings.chat.notifications.new_messages')}
                    subtitleTop={$text('settings.chat.notifications.new_messages_desc')}
                    hasToggle={true}
                    checked={preferences.newMessages}
                    onClick={() => handleTogglePreference('newMessages')}
                />
                
                <SettingsItem
                    type="submenu"
                    icon="subsetting_icon subsetting_icon_cloud"
                    title={$text('settings.chat.notifications.server_events')}
                    subtitleTop={$text('settings.chat.notifications.server_events_desc')}
                    hasToggle={true}
                    checked={preferences.serverEvents}
                    onClick={() => handleTogglePreference('serverEvents')}
                />
                
                <SettingsItem
                    type="submenu"
                    icon="subsetting_icon subsetting_icon_download"
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
    <div class="email-section">
        <h3 class="section-title">
            {$text('settings.chat.notifications.email_section')}
        </h3>
        
        <!-- Info banner explaining how email notifications work -->
        <div class="info-banner email-info">
            <span class="info-text">
                {$text('settings.chat.notifications.email_how_it_works')}
            </span>
        </div>
        
        <!-- Main Enable/Disable Toggle for Email -->
        <!-- Uses the login email from account settings automatically -->
        <SettingsItem
            type="submenu"
            icon="subsetting_icon subsetting_icon_email"
            title={$text('settings.chat.notifications.email_enable')}
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
                    icon="subsetting_icon subsetting_icon_chat"
                    title={$text('settings.chat.notifications.email_ai_responses')}
                    subtitleTop={$text('settings.chat.notifications.email_ai_responses_desc')}
                    hasToggle={true}
                    checked={emailPreferences.aiResponses}
                    onClick={handleToggleAIResponses}
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
        <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
        <div class="ios-modal-overlay" onclick={closeIOSInstructions}>
            <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
            <div class="ios-modal" onclick={(e) => e.stopPropagation()}>
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
        padding: 12px 16px;
        border-radius: 8px;
        margin-bottom: 16px;
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
        font-size: 13px;
        line-height: 1.5;
        color: var(--color-font-primary);
    }
    
    /* PWA Install Instructions Banner (iOS Safari non-PWA) */
    .pwa-install-banner {
        padding: 16px;
        border-radius: 12px;
        margin-bottom: 16px;
        background-color: var(--color-grey-10);
        border: 1px solid var(--color-primary, var(--color-grey-30));
    }
    
    .pwa-install-header {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 8px;
    }
    
    .pwa-install-title {
        font-size: 15px;
        font-weight: 600;
        color: var(--color-font-primary);
        line-height: 1.4;
    }
    
    .pwa-install-desc {
        font-size: 13px;
        color: var(--color-grey-60);
        line-height: 1.5;
        margin: 0 0 12px 0;
    }
    
    .pwa-install-steps {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }
    
    .pwa-install-steps p {
        margin: 0;
        font-size: 14px;
        color: var(--color-font-primary);
        line-height: 1.6;
    }
    
    .category-section {
        margin-top: 24px;
        padding-top: 16px;
        border-top: 1px solid var(--color-grey-20);
    }
    
    .section-title {
        font-size: 12px;
        font-weight: 600;
        color: var(--color-grey-60);
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin: 0 0 12px 0;
        padding: 0 10px;
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
        z-index: 1000;
    }
    
    .ios-modal {
        background-color: var(--color-grey-0);
        border-radius: 16px;
        padding: 24px;
        max-width: 320px;
        width: 90%;
        text-align: center;
    }
    
    .ios-modal-title {
        font-size: 18px;
        font-weight: 600;
        color: var(--color-font-primary);
        margin: 0 0 16px 0;
    }
    
    .ios-modal-content {
        text-align: left;
        margin-bottom: 20px;
    }
    
    .ios-modal-content p {
        font-size: 14px;
        color: var(--color-grey-70);
        line-height: 1.6;
        margin: 8px 0;
    }
    
    .ios-modal-close {
        width: 100%;
        padding: 12px 24px;
        background-color: var(--color-button-primary);
        color: var(--color-font-button);
        border: none;
        border-radius: 20px;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        transition: background-color 0.2s ease;
    }
    
    .ios-modal-close:hover {
        background-color: var(--color-button-primary-hover);
    }
    
    /* Email Notifications Section Styles */
    .email-section {
        margin-top: 32px;
        padding-top: 24px;
        border-top: 1px solid var(--color-grey-20);
    }
    
    .email-info {
        margin-bottom: 16px;
    }
    
    .email-options {
        margin-top: 16px;
        padding-top: 16px;
        border-top: 1px solid var(--color-grey-10);
    }
    
    .saving-indicator {
        text-align: center;
        font-size: 12px;
        color: var(--color-grey-50);
        margin-top: 12px;
        padding: 8px;
    }
</style>
