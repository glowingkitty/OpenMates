<!--
Chat Notifications Settings - Push and Email notification preferences
Allows users to enable/disable notifications and configure notification categories.
Email notifications are only sent when the user is offline (no active WebSocket connections).
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
    
    // Local state for push notifications
    let isRequestingPermission = $state(false);
    let showIOSInstructions = $state(false);
    
    // Local state for email notifications
    let emailNotificationsEnabled = $state($userProfile.email_notifications_enabled ?? false);
    let notificationEmail = $state($userProfile.email_notification_email ?? '');
    let emailPreferences = $state($userProfile.email_notification_preferences ?? { aiResponses: true });
    let isEmailValid = $state(true);
    let isSavingEmail = $state(false);
    let emailInputTimeout: ReturnType<typeof setTimeout> | null = null;
    
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
            push_notification_preferences: syncData.push_notification_preferences
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
            ? $text('settings.chat.notifications.permission_granted', { default: 'Permission granted' })
            : permission === 'denied'
                ? $text('settings.chat.notifications.permission_denied', { default: 'Permission denied in browser settings' })
                : $text('settings.chat.notifications.permission_default', { default: 'Permission not yet requested' })
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
     * Validate email address format
     */
    function validateEmail(email: string): boolean {
        if (!email) return true; // Empty is valid (will disable notifications)
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return emailRegex.test(email);
    }
    
    /**
     * Handle email notifications enable/disable toggle
     */
    function handleToggleEmailEnabled(): void {
        // If trying to enable but no valid email, don't allow
        if (!emailNotificationsEnabled && !notificationEmail) {
            // Focus on email input would be nice but we'll just prevent toggle
            return;
        }
        
        emailNotificationsEnabled = !emailNotificationsEnabled;
        syncEmailSettingsToServer();
    }
    
    /**
     * Handle email address input change with debounce
     */
    function handleEmailChange(event: Event): void {
        const target = event.target as HTMLInputElement;
        notificationEmail = target.value;
        
        // Validate email
        isEmailValid = validateEmail(notificationEmail);
        
        // Debounce server sync
        if (emailInputTimeout) {
            clearTimeout(emailInputTimeout);
        }
        
        if (isEmailValid && notificationEmail) {
            emailInputTimeout = setTimeout(() => {
                syncEmailSettingsToServer();
            }, 1000); // 1 second debounce
        }
    }
    
    /**
     * Toggle AI responses email notification preference
     */
    function handleToggleAIResponses(): void {
        emailPreferences = {
            ...emailPreferences,
            aiResponses: !emailPreferences.aiResponses
        };
        syncEmailSettingsToServer();
    }
    
    /**
     * Sync email notification settings to server
     */
    async function syncEmailSettingsToServer(): Promise<void> {
        if (!$authStore.isAuthenticated) {
            console.debug('[SettingsChatNotifications] User not authenticated, skipping email settings sync');
            return;
        }
        
        if (!isEmailValid) {
            console.debug('[SettingsChatNotifications] Email invalid, skipping sync');
            return;
        }
        
        isSavingEmail = true;
        
        try {
            // Update profile with email notification settings
            // Note: The email will be encrypted by the backend before storage
            updateProfile({
                email_notifications_enabled: emailNotificationsEnabled,
                email_notification_email: notificationEmail,
                email_notification_preferences: emailPreferences
            });
            
            console.debug('[SettingsChatNotifications] Email notification settings synced:', {
                enabled: emailNotificationsEnabled,
                email: notificationEmail ? '***@***' : '(empty)',
                preferences: emailPreferences
            });
        } finally {
            isSavingEmail = false;
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
                    {$text('settings.chat.notifications.pwa_install_title.text', { 
                        default: 'Add to Home Screen to Enable Notifications' 
                    })}
                </span>
            </div>
            <p class="pwa-install-desc">
                {$text('settings.chat.notifications.pwa_install_desc.text', {
                    default: 'Push notifications require the app to be installed on your device. Follow these steps:'
                })}
            </p>
            <div class="pwa-install-steps">
                <p>{$text('notifications.push.ios_install_step1.text', { default: '1. Tap the Share button in Safari' })}</p>
                <p>{$text('notifications.push.ios_install_step2.text', { default: '2. Select "Add to Home Screen"' })}</p>
                <p>{$text('notifications.push.ios_install_step3.text', { default: '3. Open OpenMates from your home screen' })}</p>
                <p>{$text('notifications.push.ios_install_step4.text', { default: '4. Then you can enable notifications here' })}</p>
            </div>
        </div>
    {:else if !isSupported}
        <!-- Truly unsupported browser/device -->
        <div class="warning-banner">
            <span class="warning-text">
                {$text('settings.chat.notifications.not_supported.text', { 
                    default: 'Push notifications are not supported on this browser or device.' 
                })}
            </span>
        </div>
    {:else}
        <!-- Main Enable/Disable Toggle -->
        <SettingsItem
            type="submenu"
            icon="subsetting_icon subsetting_icon_announcement"
            title={$text('settings.chat.notifications.enable.text', { default: 'Push Notifications' })}
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
                    {$text('settings.chat.notifications.denied_info.text', { 
                        default: 'To enable notifications, please allow them in your browser settings and refresh the page.' 
                    })}
                </span>
            </div>
        {/if}
        
        <!-- Notification Categories (only show if enabled) -->
        {#if isEnabled && permission === 'granted'}
            <div class="category-section">
                <h3 class="section-title">
                    {$text('settings.chat.notifications.categories.text', { default: 'Notification Types' })}
                </h3>
                
                <SettingsItem
                    type="submenu"
                    icon="subsetting_icon subsetting_icon_chat"
                    title={$text('settings.chat.notifications.new_messages.text', { default: 'New Messages' })}
                    subtitleTop={$text('settings.chat.notifications.new_messages_desc.text', { 
                        default: 'When an assistant completes a response' 
                    })}
                    hasToggle={true}
                    checked={preferences.newMessages}
                    onClick={() => handleTogglePreference('newMessages')}
                />
                
                <SettingsItem
                    type="submenu"
                    icon="subsetting_icon subsetting_icon_cloud"
                    title={$text('settings.chat.notifications.server_events.text', { default: 'Server Events' })}
                    subtitleTop={$text('settings.chat.notifications.server_events_desc.text', { 
                        default: 'Connection issues and maintenance alerts' 
                    })}
                    hasToggle={true}
                    checked={preferences.serverEvents}
                    onClick={() => handleTogglePreference('serverEvents')}
                />
                
                <SettingsItem
                    type="submenu"
                    icon="subsetting_icon subsetting_icon_download"
                    title={$text('settings.chat.notifications.software_updates.text', { default: 'Software Updates' })}
                    subtitleTop={$text('settings.chat.notifications.software_updates_desc.text', { 
                        default: 'When new versions are available' 
                    })}
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
            {$text('settings.chat.notifications.email_section.text', { default: 'Email Notifications' })}
        </h3>
        
        <!-- Info banner explaining how email notifications work -->
        <div class="info-banner email-info">
            <span class="info-text">
                {$text('settings.chat.notifications.email_how_it_works.text', { 
                    default: "Email notifications are only sent when you're not actively using OpenMates on any device." 
                })}
            </span>
        </div>
        
        <!-- Email address input -->
        <div class="email-input-container">
            <label for="notification-email" class="input-label">
                {$text('settings.chat.notifications.email_address.text', { default: 'Notification Email' })}
            </label>
            <input
                id="notification-email"
                type="email"
                class="email-input"
                class:invalid={!isEmailValid}
                placeholder={$text('settings.chat.notifications.email_address_placeholder.text', { 
                    default: 'Enter email address' 
                })}
                value={notificationEmail}
                oninput={handleEmailChange}
            />
            {#if !isEmailValid}
                <span class="error-text">
                    {$text('settings.chat.notifications.email_invalid.text', { 
                        default: 'Please enter a valid email address' 
                    })}
                </span>
            {:else}
                <span class="helper-text">
                    {$text('settings.chat.notifications.email_address_desc.text', { 
                        default: 'Where to send notifications (can differ from login email)' 
                    })}
                </span>
            {/if}
        </div>
        
        <!-- Main Enable/Disable Toggle for Email -->
        <SettingsItem
            type="submenu"
            icon="subsetting_icon subsetting_icon_email"
            title={$text('settings.chat.notifications.email_enable.text', { default: 'Email Notifications' })}
            subtitleTop={$text('settings.chat.notifications.email_enable_desc.text', { 
                default: "Receive emails when you're offline" 
            })}
            hasToggle={true}
            checked={emailNotificationsEnabled}
            disabled={!notificationEmail || !isEmailValid}
            onClick={handleToggleEmailEnabled}
        />
        
        <!-- Email notification options (only show if enabled) -->
        {#if emailNotificationsEnabled && notificationEmail && isEmailValid}
            <div class="email-options">
                <!-- AI Responses toggle -->
                <SettingsItem
                    type="submenu"
                    icon="subsetting_icon subsetting_icon_chat"
                    title={$text('settings.chat.notifications.email_ai_responses.text', { default: 'AI Responses' })}
                    subtitleTop={$text('settings.chat.notifications.email_ai_responses_desc.text', { 
                        default: "When an assistant completes a response while you're away" 
                    })}
                    hasToggle={true}
                    checked={emailPreferences.aiResponses}
                    onClick={handleToggleAIResponses}
                />
            </div>
        {/if}
        
        <!-- Saving indicator -->
        {#if isSavingEmail}
            <div class="saving-indicator">
                {$text('settings.chat.notifications.email_saving.text', { default: 'Saving...' })}
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
                    {$text('notifications.push.ios_install_title.text', { default: 'Install OpenMates First' })}
                </h3>
                <div class="ios-modal-content">
                    <p>{$text('notifications.push.ios_install_step1.text', { default: '1. Tap the Share button in Safari' })}</p>
                    <p>{$text('notifications.push.ios_install_step2.text', { default: '2. Select "Add to Home Screen"' })}</p>
                    <p>{$text('notifications.push.ios_install_step3.text', { default: '3. Open OpenMates from your home screen' })}</p>
                    <p>{$text('notifications.push.ios_install_step4.text', { default: '4. Then you can enable notifications' })}</p>
                </div>
                <button class="ios-modal-close" onclick={closeIOSInstructions}>
                    {$text('common.close.text', { default: 'Close' })}
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
    
    .email-input-container {
        margin-bottom: 16px;
        padding: 0 10px;
    }
    
    .input-label {
        display: block;
        font-size: 12px;
        font-weight: 600;
        color: var(--color-grey-60);
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 8px;
    }
    
    .email-input {
        width: 100%;
        padding: 12px 16px;
        font-size: 14px;
        color: var(--color-font-primary);
        background-color: var(--color-grey-10);
        border: 1px solid var(--color-grey-20);
        border-radius: 8px;
        outline: none;
        transition: border-color 0.2s ease, background-color 0.2s ease;
    }
    
    .email-input:focus {
        border-color: var(--color-button-primary);
        background-color: var(--color-grey-0);
    }
    
    .email-input.invalid {
        border-color: var(--color-error);
    }
    
    .email-input::placeholder {
        color: var(--color-grey-50);
    }
    
    .helper-text {
        display: block;
        font-size: 12px;
        color: var(--color-grey-50);
        margin-top: 6px;
        line-height: 1.4;
    }
    
    .error-text {
        display: block;
        font-size: 12px;
        color: var(--color-error);
        margin-top: 6px;
        line-height: 1.4;
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
