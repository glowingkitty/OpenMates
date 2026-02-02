<!--
Chat Notifications Settings - Push notification preferences
Allows users to enable/disable notifications and configure notification categories
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';
    import {
        pushNotificationStore,
        requiresPWAInstall
    } from '../../../stores/pushNotificationStore';
    import { pushNotificationService } from '../../../services/pushNotificationService';
    import { updateProfile } from '../../../stores/userProfile';
    import { authStore } from '../../../stores/authStore';
    
    // Local state
    let isRequestingPermission = $state(false);
    let showIOSInstructions = $state(false);
    
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
    
    // Permission status text
    let permissionStatusText = $derived(
        permission === 'granted'
            ? $text('settings.chat.notifications.permission_granted.text', { default: 'Permission granted' })
            : permission === 'denied'
                ? $text('settings.chat.notifications.permission_denied.text', { default: 'Permission denied in browser settings' })
                : $text('settings.chat.notifications.permission_default.text', { default: 'Permission not yet requested' })
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
</script>

<div class="notifications-settings-container">
    <!-- Not Supported Warning -->
    {#if !isSupported}
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
</style>
